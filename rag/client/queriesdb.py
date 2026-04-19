"""
Módulo de acceso a base de datos PostgreSQL para almacenar queries y embeddings.
Proporciona una capa de abstracción para guardar preguntas, respuestas y embeddings.

Este módulo soporta múltiples clientes:
- Cada cliente tiene su propia base de datos y usuario (configurados en rag_client.env)
- Un usuario administrador con privilegios (configurado en queriesdb.env) se usa para:
  * Crear la base de datos del cliente si no existe
  * Crear el usuario del cliente si no existe
  * Otorgar permisos al usuario sobre su base de datos

Este módulo es OPCIONAL y solo se activa si QUERIESDB_AVAILABLE=true en queriesdb.env
"""

import asyncio
import os
import uuid
from typing import Optional, List, Dict, Any
import logging
from datetime import datetime
from contextlib import asynccontextmanager

try:
    import asyncpg
    HAS_ASYNCPG = True
except ImportError:
    HAS_ASYNCPG = False

try:
    import geoip2.database
    HAS_GEOIP = True
except ImportError:
    HAS_GEOIP = False

logger = logging.getLogger(__name__)

# Ruta por defecto de la base de datos GeoLite2-City
GEOIP_DB_PATH = os.getenv("GEOIP_DB_PATH", "/var/lib/GeoIP/GeoLite2-City.mmdb")
_geoip_reader = None


def _get_geoip_reader():
    """Obtiene (o crea) el lector GeoIP singleton."""
    global _geoip_reader
    if _geoip_reader is not None:
        return _geoip_reader
    if not HAS_GEOIP:
        return None
    if not os.path.exists(GEOIP_DB_PATH):
        logger.warning(f"⚠️  Base de datos GeoIP no encontrada en {GEOIP_DB_PATH}")
        return None
    try:
        _geoip_reader = geoip2.database.Reader(GEOIP_DB_PATH)
        logger.info(f"✅ GeoIP inicializado con {GEOIP_DB_PATH}")
        return _geoip_reader
    except Exception as e:
        logger.warning(f"⚠️  Error al abrir base de datos GeoIP: {e}")
        return None


def geoip_lookup(ip: str) -> dict:
    """
    Busca país y ciudad a partir de una IP usando GeoLite2.
    Retorna {'country': ..., 'city': ...} o valores None si no se puede resolver.
    """
    result = {"country": None, "city": None}
    if not ip or ip in ('unknown', '127.0.0.1', '::1'):
        return result
    reader = _get_geoip_reader()
    if not reader:
        return result
    try:
        response = reader.city(ip)
        result["country"] = response.country.name
        result["city"] = response.city.name
    except Exception:
        pass  # IP no encontrada en la base de datos GeoIP
    return result


class RAGDatabase:
    """Gestor de conexiones y operaciones a PostgreSQL con PGVector"""

    def __init__(self):
        """Inicializa la configuración de BD desde variables de entorno"""
        # Configuración del administrador (con privilegios para crear BDs y usuarios)
        self.admin_user = os.getenv("QUERIESDB_ADMIN_USER")
        self.admin_password = os.getenv("QUERIESDB_ADMIN_PASSWORD")
        
        # Configuración del cliente (base de datos y usuario específicos)
        self.host = os.getenv("QUERIESDB_HOST")
        self.port = int(os.getenv("QUERIESDB_PORT", "5432"))
        self.database = os.getenv("QUERIESDB_DB")
        self.user = os.getenv("QUERIESDB_USER")
        self.password = os.getenv("QUERIESDB_PASSWORD")
        
        # Pool de conexiones
        self.pool = None
        
        # Parámetros del pool
        self.pool_min_size = int(os.getenv("QUERIESDB_POOL_MIN_SIZE", "2"))
        self.pool_max_size = int(os.getenv("QUERIESDB_POOL_MAX_SIZE", "10"))
        self.query_timeout = int(os.getenv("QUERIESDB_QUERY_TIMEOUT", "30"))
        
        # Flag de disponibilidad
        self.is_available = self._check_configuration()
        
        if self.is_available:
            logger.info("📦 Configuración de BD encontrada. Base de datos habilitada.")
        else:
            logger.info("⚠️  Configuración de BD no encontrada. Ejecutando sin BD (compatible hacia atrás)")

    def _check_configuration(self) -> bool:
        """Verifica si todas las credenciales están configuradas"""
        
        # Primero comprobar si el flag QUERIESDB_AVAILABLE está en false
        available_flag = os.getenv("QUERIESDB_AVAILABLE", "").lower()
        if available_flag == "false":
            logger.info("⚠️  QUERIESDB_AVAILABLE=false. Base de datos deshabilitada por configuración.")
            return False
        
        # Variables requeridas para el administrador
        admin_required = [
            "QUERIESDB_ADMIN_USER",
            "QUERIESDB_ADMIN_PASSWORD"
        ]
        
        # Variables requeridas para el cliente
        client_required = [
            "QUERIESDB_HOST",
            "QUERIESDB_PORT",
            "QUERIESDB_DB",
            "QUERIESDB_USER",
            "QUERIESDB_PASSWORD"
        ]
        
        # Comprobar que todas las variables existan
        for var in admin_required + client_required:
            if not os.getenv(var):
                logger.warning(f"⚠️  Variable {var} no encontrada en configuración.")
                return False
        
        # Comprobar que asyncpg esté disponible
        if not HAS_ASYNCPG:
            logger.warning("⚠️  asyncpg no instalado. Base de datos deshabilitada.")
            return False
        
        return True

    async def initialize(self):
        """Inicializa el pool de conexiones, creando BD y usuario si es necesario"""
        if not self.is_available:
            return
        
        try:
            # Paso 1: Conectar como administrador para crear BD y usuario si no existen
            await self._ensure_database_and_user_exist()
            
            # Paso 2: Conectar con el usuario del cliente a su base de datos
            self.pool = await asyncpg.create_pool(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                database=self.database,
                min_size=self.pool_min_size,
                max_size=self.pool_max_size,
                timeout=self.query_timeout,
                command_timeout=self.query_timeout,
            )
            logger.info(f"✅ Conectado a PostgreSQL: {self.user}@{self.host}:{self.port}/{self.database}")
        except Exception as e:
            logger.error(f"❌ Error al conectar a PostgreSQL: {e}")
            self.is_available = False

    async def _ensure_database_and_user_exist(self):
        """
        Conecta como administrador y crea la base de datos y usuario si no existen.
        Este método permite que múltiples clientes tengan sus propias BDs sin interferir.
        """
        admin_conn = None
        try:
            # Conectar como administrador a la BD 'postgres' (siempre existe)
            admin_conn = await asyncpg.connect(
                host=self.host,
                port=self.port,
                user=self.admin_user,
                password=self.admin_password,
                database='postgres',
                timeout=self.query_timeout,
            )
            
            # Verificar si el usuario existe
            user_exists = await admin_conn.fetchval(
                "SELECT 1 FROM pg_roles WHERE rolname = $1",
                self.user
            )
            
            if not user_exists:
                # Crear usuario - no se pueden usar parámetros para identifiers
                # Validar que el nombre de usuario sea seguro (solo alfanuméricos y _)
                if not self.user.replace('_', '').isalnum():
                    raise ValueError(f"Nombre de usuario inválido: {self.user}")
                
                # Escapar la contraseña correctamente
                escaped_password = self.password.replace("'", "''")
                await admin_conn.execute(
                    f"CREATE USER {self.user} WITH PASSWORD '{escaped_password}'"
                )
                logger.info(f"✅ Usuario '{self.user}' creado exitosamente")
            else:
                logger.info(f"ℹ️  Usuario '{self.user}' ya existe")
            
            # Verificar si la base de datos existe
            db_exists = await admin_conn.fetchval(
                "SELECT 1 FROM pg_database WHERE datname = $1",
                self.database
            )
            
            if not db_exists:
                # Validar que el nombre de BD sea seguro
                if not self.database.replace('_', '').isalnum():
                    raise ValueError(f"Nombre de base de datos inválido: {self.database}")
                
                # Crear base de datos
                await admin_conn.execute(
                    f"CREATE DATABASE {self.database} OWNER {self.user}"
                )
                logger.info(f"✅ Base de datos '{self.database}' creada exitosamente")
                
                # Conectar a la nueva BD para habilitar pgvector
                db_conn = await asyncpg.connect(
                    host=self.host,
                    port=self.port,
                    user=self.admin_user,
                    password=self.admin_password,
                    database=self.database,
                    timeout=self.query_timeout,
                )
                try:
                    await db_conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
                    logger.info(f"✅ Extensión pgvector habilitada en '{self.database}'")
                finally:
                    await db_conn.close()
            else:
                logger.info(f"ℹ️  Base de datos '{self.database}' ya existe")
            
            # Otorgar todos los privilegios sobre la BD al usuario
            await admin_conn.execute(
                f"GRANT ALL PRIVILEGES ON DATABASE {self.database} TO {self.user}"
            )
            
        except Exception as e:
            logger.error(f"❌ Error al crear BD/usuario: {e}")
            raise
        finally:
            if admin_conn:
                await admin_conn.close()

    async def close(self):
        """Cierra el pool de conexiones"""
        if self.pool:
            await self.pool.close()

    async def create_tables(self) -> bool:
        """Crea las tablas necesarias si no existen"""
        if not self.is_available:
            return False
        
        try:
            async with self.get_connection() as conn:
                if conn is None:
                    return False
                
                # Crear extensión pgvector
                await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
                logger.info("✅ Extensión pgvector verificada/creada")
                
                # Crear tabla principal rag_queries
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS rag_queries (
                        id SERIAL PRIMARY KEY,
                        uuid UUID DEFAULT gen_random_uuid() UNIQUE NOT NULL,
                        query_text TEXT NOT NULL,
                        response_text TEXT NOT NULL,
                        query_embedding vector(1536),
                        created_at TIMESTAMP DEFAULT NOW(),
                        podcast_name VARCHAR(255),
                        likes INTEGER DEFAULT 0,
                        dislikes INTEGER DEFAULT 0,
                        allowed BOOLEAN DEFAULT TRUE,
                        response_data JSONB,
                        CONSTRAINT query_text_not_empty CHECK (query_text != '')
                    );
                """)
                logger.info("✅ Tabla rag_queries verificada/creada")
                
                # Agregar columna response_data si no existe (para migraciones)
                await conn.execute("""
                    DO $$ 
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns 
                            WHERE table_name = 'rag_queries' 
                            AND column_name = 'response_data'
                        ) THEN
                            ALTER TABLE rag_queries ADD COLUMN response_data JSONB;
                        END IF;
                    END $$;
                """)
                logger.info("✅ Columna response_data verificada/creada")
                
                # Crear índices
                # Usar vector_cosine_ops para búsquedas por similitud de coseno
                # (compatible con pgvector >= 0.5.0)
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_query_embedding_cosine 
                    ON rag_queries USING hnsw (query_embedding vector_cosine_ops);
                """)
                
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_podcast_name 
                    ON rag_queries(podcast_name);
                """)
                
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_created_at 
                    ON rag_queries(created_at DESC);
                """)
                
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_uuid 
                    ON rag_queries(uuid);
                """)
                
                # Crear índice GIN para búsquedas en JSONB
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_response_data_gin 
                    ON rag_queries USING GIN (response_data);
                """)
                
                logger.info("✅ Índices verificados/creados")
                
                # Crear tabla de auditoría
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS rag_queries_access_log (
                        id SERIAL PRIMARY KEY,
                        query_id INTEGER REFERENCES rag_queries(id) ON DELETE CASCADE,
                        access_time TIMESTAMP DEFAULT NOW(),
                        similarity_score FLOAT
                    );
                """)
                logger.info("✅ Tabla rag_queries_access_log verificada/creada")
                
                # ===== FAQ / CATEGORÍAS =====
                
                # Columna featured en rag_queries (consultas destacadas para FAQ)
                await conn.execute("""
                    DO $$ 
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns 
                            WHERE table_name = 'rag_queries' 
                            AND column_name = 'featured'
                        ) THEN
                            ALTER TABLE rag_queries ADD COLUMN featured BOOLEAN DEFAULT FALSE;
                        END IF;
                    END $$;
                """)
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_featured 
                    ON rag_queries(featured) WHERE featured = TRUE;
                """)
                logger.info("✅ Columna featured verificada/creada")
                
                # Columna categorization_embedding (embedding combinado pregunta+respuesta)
                await conn.execute("""
                    DO $$ 
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns 
                            WHERE table_name = 'rag_queries' 
                            AND column_name = 'categorization_embedding'
                        ) THEN
                            ALTER TABLE rag_queries ADD COLUMN categorization_embedding vector(1536);
                        END IF;
                    END $$;
                """)
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_categorization_embedding 
                    ON rag_queries USING hnsw (categorization_embedding vector_cosine_ops);
                """)
                logger.info("✅ Columna categorization_embedding verificada/creada")
                
                # Tabla de categorías jerárquicas
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS rag_categories (
                        id SERIAL PRIMARY KEY,
                        name VARCHAR(255) NOT NULL,
                        slug VARCHAR(255) UNIQUE NOT NULL,
                        description TEXT,
                        parent_id INTEGER REFERENCES rag_categories(id) ON DELETE SET NULL,
                        is_primary BOOLEAN DEFAULT FALSE,
                        display_order INTEGER DEFAULT 0,
                        created_at TIMESTAMP DEFAULT NOW(),
                        category_embedding vector(1536)
                    );
                """)
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_category_parent 
                    ON rag_categories(parent_id);
                """)
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_category_primary 
                    ON rag_categories(is_primary);
                """)
                logger.info("✅ Tabla rag_categories verificada/creada")
                
                # Columna created_by en rag_categories (para distinguir origen LLM vs admin)
                await conn.execute("""
                    DO $$ 
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns 
                            WHERE table_name = 'rag_categories' 
                            AND column_name = 'created_by'
                        ) THEN
                            ALTER TABLE rag_categories ADD COLUMN created_by VARCHAR(50) DEFAULT 'admin';
                        END IF;
                    END $$;
                """)
                logger.info("✅ Columna created_by en rag_categories verificada/creada")
                
                # Tabla de relación N:M consultas-categorías
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS rag_query_categories (
                        query_id INTEGER REFERENCES rag_queries(id) ON DELETE CASCADE,
                        category_id INTEGER REFERENCES rag_categories(id) ON DELETE CASCADE,
                        assigned_by VARCHAR(50) DEFAULT 'admin',
                        confidence FLOAT DEFAULT 1.0,
                        created_at TIMESTAMP DEFAULT NOW(),
                        PRIMARY KEY (query_id, category_id)
                    );
                """)
                logger.info("✅ Tabla rag_query_categories verificada/creada")
                
                # Tabla de auditoría de likes/dislikes con IP
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS ip_likes (
                        id SERIAL PRIMARY KEY,
                        query_id INTEGER REFERENCES rag_queries(id) ON DELETE CASCADE,
                        is_like BOOLEAN NOT NULL,
                        date TIMESTAMP DEFAULT NOW(),
                        ip VARCHAR(45) NOT NULL,
                        from_admin BOOLEAN DEFAULT FALSE
                    );
                """)
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_ip_likes_query_id
                    ON ip_likes(query_id);
                """)
                # Añadir columna from_admin si no existe (migración)
                await conn.execute("""
                    ALTER TABLE ip_likes ADD COLUMN IF NOT EXISTS from_admin BOOLEAN DEFAULT FALSE;
                """)
                logger.info("✅ Tabla ip_likes verificada/creada")
                
                # ===== GeoIP: columnas ip, country, city en rag_queries =====
                for col, col_type in [('ip', 'VARCHAR(45)'), ('country', 'VARCHAR(100)'), ('city', 'VARCHAR(100)')]:
                    await conn.execute(f"""
                        ALTER TABLE rag_queries ADD COLUMN IF NOT EXISTS {col} {col_type};
                    """)
                logger.info("✅ Columnas ip/country/city en rag_queries verificadas/creadas")
                
                # ===== GeoIP: columnas country, city en ip_likes =====
                for col in ['country', 'city']:
                    await conn.execute(f"""
                        ALTER TABLE ip_likes ADD COLUMN IF NOT EXISTS {col} VARCHAR(100);
                    """)
                logger.info("✅ Columnas country/city en ip_likes verificadas/creadas")
                
                return True
                
        except Exception as e:
            logger.error(f"❌ Error al crear tablas: {e}")
            return False

    @asynccontextmanager
    async def get_connection(self):
        """Context manager para obtener una conexión del pool"""
        if not self.is_available or not self.pool:
            yield None
            return
        
        conn = await self.pool.acquire()
        try:
            yield conn
        finally:
            await self.pool.release(conn)

    async def save_query(
        self,
        query_text: str,
        response_text: str,
        response_data: Optional[Dict[str, Any]] = None,
        query_embedding: Optional[List[float]] = None,
        podcast_name: Optional[str] = None,
        ip: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Guarda una query, respuesta y embedding en la BD
        
        Args:
            query_text: Texto de la pregunta
            response_text: Texto de la respuesta (para backward compatibility)
            response_data: Dict completo con {response: {es: ..., en: ...}, references: [...]}
            query_embedding: Vector embedding de la pregunta (lista de floats)
            podcast_name: Nombre del podcast
            ip: Dirección IP del cliente
            
        Returns:
            Dict con id y uuid de la fila insertada o None si error
        """
        if not self.is_available:
            return None
        
        try:
            async with self.get_connection() as conn:
                if conn is None:
                    return None
                
                # Preparar el embedding como vector para PostgreSQL
                # Para pgvector con asyncpg, convertir la lista a string formato '[x,y,z,...]'
                embedding_value = None
                if query_embedding:
                    # Convertir lista de floats a string con formato de vector de PostgreSQL
                    embedding_value = str(query_embedding)
                
                # Convertir response_data a JSON para PostgreSQL
                import json
                response_data_json = json.dumps(response_data) if response_data else None
                
                # Resolver GeoIP
                geo = geoip_lookup(ip) if ip else {"country": None, "city": None}
                
                # SQL para insertar - El orden debe coincidir con el de VALUES
                query = """
                    INSERT INTO rag_queries (query_text, response_text, query_embedding, podcast_name, response_data, created_at, ip, country, city)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    RETURNING id, uuid;
                """
                
                result = await conn.fetchrow(
                    query,
                    query_text,          # $1 -> query_text (TEXT)
                    response_text,       # $2 -> response_text (TEXT)
                    embedding_value,     # $3 -> query_embedding (vector(1536))
                    podcast_name,        # $4 -> podcast_name (VARCHAR)
                    response_data_json,  # $5 -> response_data (JSONB)
                    datetime.now(),      # $6 -> created_at (TIMESTAMP)
                    ip,                  # $7 -> ip (VARCHAR)
                    geo["country"],      # $8 -> country (VARCHAR)
                    geo["city"]          # $9 -> city (VARCHAR)
                )
                
                if result:
                    result_dict = {"id": result["id"], "uuid": str(result["uuid"])}
                    logger.debug(f"💾 Query guardada con ID: {result_dict['id']}, UUID: {result_dict['uuid']}")
                    return result_dict
                return None
                
        except Exception as e:
            logger.error(f"❌ Error al guardar query en BD: {e}")
            return None

    async def search_similar_queries(
        self,
        query_embedding: List[float],
        podcast_name: Optional[str] = None,
        limit: int = 5,
        similarity_threshold: float = 0.8
    ) -> List[Dict[str, Any]]:
        """
        Busca queries similares usando búsqueda semántica
        
        Args:
            query_embedding: Vector embedding de la pregunta
            podcast_name: Filtrar por nombre de podcast
            limit: Número máximo de resultados
            similarity_threshold: Umbral de similitud (0-1)
            
        Returns:
            Lista de queries similares con score de similitud
        """
        if not self.is_available:
            return []
        
        try:
            async with self.get_connection() as conn:
                if conn is None:
                    return []
                
                # Calcular similitud del coseno entre embeddings
                if podcast_name:
                    query = """
                        SELECT 
                            id,
                            uuid,
                            query_text,
                            response_text,
                            1 - (query_embedding <=> $1::vector) AS similarity,
                            created_at,
                            podcast_name,
                            likes,
                            dislikes
                        FROM rag_queries
                        WHERE podcast_name = $2 AND (query_embedding <=> $1::vector) < $3
                        ORDER BY query_embedding <=> $1::vector
                        LIMIT $4;
                    """
                    results = await conn.fetch(
                        query,
                        str(query_embedding),
                        podcast_name,
                        1 - similarity_threshold,
                        limit
                    )
                else:
                    query = """
                        SELECT 
                            id,
                            uuid,
                            query_text,
                            response_text,
                            1 - (query_embedding <=> $1::vector) AS similarity,
                            created_at,
                            podcast_name,
                            likes,
                            dislikes
                        FROM rag_queries
                        WHERE (query_embedding <=> $1::vector) < $2
                        ORDER BY query_embedding <=> $1::vector
                        LIMIT $3;
                    """
                    results = await conn.fetch(
                        query,
                        str(query_embedding),
                        1 - similarity_threshold,
                        limit
                    )
                
                # Convertir a lista de dicts
                return [dict(record) for record in results]
                
        except Exception as e:
            logger.error(f"❌ Error al buscar queries similares: {e}")
            return []

    async def get_query_by_id(self, query_id: int) -> Optional[Dict[str, Any]]:
        """Obtiene una query por ID"""
        if not self.is_available:
            return None
        
        try:
            async with self.get_connection() as conn:
                if conn is None:
                    return None
                
                record = await conn.fetchrow(
                    "SELECT * FROM rag_queries WHERE id = $1",
                    query_id
                )
                
                return dict(record) if record else None
                
        except Exception as e:
            logger.error(f"❌ Error al obtener query: {e}")
            return None

    async def get_query_by_uuid(self, query_uuid: str) -> Optional[Dict[str, Any]]:
        """Obtiene una query por UUID"""
        if not self.is_available:
            return None
        
        try:
            async with self.get_connection() as conn:
                if conn is None:
                    return None
                
                record = await conn.fetchrow(
                    "SELECT * FROM rag_queries WHERE uuid = $1",
                    query_uuid
                )
                
                return dict(record) if record else None
                
        except Exception as e:
            logger.error(f"❌ Error al obtener query por UUID: {e}")
            return None

    async def get_all_queries(
        self,
        podcast_name: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Obtiene todas las queries (con paginación)"""
        if not self.is_available:
            return []
        
        try:
            async with self.get_connection() as conn:
                if conn is None:
                    return []
                
                if podcast_name:
                    records = await conn.fetch(
                        """
                        SELECT id, uuid, query_text, response_text, created_at, podcast_name,
                               ip, country, city
                        FROM rag_queries
                        WHERE podcast_name = $1
                        ORDER BY created_at DESC
                        LIMIT $2 OFFSET $3
                        """,
                        podcast_name,
                        limit,
                        offset
                    )
                else:
                    records = await conn.fetch(
                        """
                        SELECT id, uuid, query_text, response_text, created_at, podcast_name,
                               ip, country, city
                        FROM rag_queries
                        ORDER BY created_at DESC
                        LIMIT $1 OFFSET $2
                        """,
                        limit,
                        offset
                    )
                
                return [dict(record) for record in records]
                
        except Exception as e:
            logger.error(f"❌ Error al obtener queries: {e}")
            return []

    async def log_query_access(
        self,
        query_id: int,
        similarity_score: Optional[float] = None
    ) -> bool:
        """Registra el acceso a una query en el log de auditoría"""
        if not self.is_available:
            return False
        
        try:
            async with self.get_connection() as conn:
                if conn is None:
                    return False
                
                await conn.execute(
                    """
                    INSERT INTO rag_queries_access_log (query_id, access_time, similarity_score)
                    VALUES ($1, $2, $3)
                    """,
                    query_id,
                    datetime.now(),
                    similarity_score
                )
                
                return True
                
        except Exception as e:
            logger.error(f"❌ Error al registrar acceso: {e}")
            return False

    async def update_likes(self, query_uuid: str, increment: int = 1) -> bool:
        """Incrementa o decrementa los likes de una query"""
        if not self.is_available:
            return False
        
        try:
            async with self.get_connection() as conn:
                if conn is None:
                    return False
                
                result = await conn.execute(
                    "UPDATE rag_queries SET likes = likes + $1 WHERE uuid = $2",
                    increment,
                    query_uuid
                )
                
                return result != "UPDATE 0"
                
        except Exception as e:
            logger.error(f"❌ Error al actualizar likes: {e}")
            return False

    async def update_dislikes(self, query_uuid: str, increment: int = 1) -> bool:
        """Incrementa o decrementa los dislikes de una query"""
        if not self.is_available:
            return False
        
        try:
            async with self.get_connection() as conn:
                if conn is None:
                    return False
                
                result = await conn.execute(
                    "UPDATE rag_queries SET dislikes = dislikes + $1 WHERE uuid = $2",
                    increment,
                    query_uuid
                )
                
                return result != "UPDATE 0"
                
        except Exception as e:
            logger.error(f"❌ Error al actualizar dislikes: {e}")
            return False

    async def set_votes(self, query_uuid: str, likes: int, dislikes: int) -> bool:
        """Establece los valores absolutos de likes y dislikes de una query (uso admin)"""
        if not self.is_available:
            return False
        
        try:
            async with self.get_connection() as conn:
                if conn is None:
                    return False
                
                result = await conn.execute(
                    "UPDATE rag_queries SET likes = $1, dislikes = $2 WHERE uuid = $3",
                    max(0, likes),
                    max(0, dislikes),
                    query_uuid
                )
                
                return result != "UPDATE 0"
                
        except Exception as e:
            logger.error(f"❌ Error al establecer votos: {e}")
            return False

    async def update_allowed(self, query_uuid: str, allowed: bool) -> bool:
        """Actualiza el estado de allowed (censura) de una query"""
        if not self.is_available:
            return False
        
        try:
            async with self.get_connection() as conn:
                if conn is None:
                    return False
                
                result = await conn.execute(
                    "UPDATE rag_queries SET allowed = $1 WHERE uuid = $2",
                    allowed,
                    query_uuid
                )
                
                return result != "UPDATE 0"
                
        except Exception as e:
            logger.error(f"❌ Error al actualizar allowed: {e}")
            return False

    async def delete_query(self, query_id: int) -> bool:
        """Elimina una query por ID"""
        if not self.is_available:
            return False
        
        try:
            async with self.get_connection() as conn:
                if conn is None:
                    return False
                
                result = await conn.execute(
                    "DELETE FROM rag_queries WHERE id = $1",
                    query_id
                )
                
                return result != "DELETE 0"
                
        except Exception as e:
            logger.error(f"❌ Error al eliminar query: {e}")
            return False

    async def cleanup_old_queries(self, days: int = 30) -> int:
        """Limpia queries más antiguas que X días"""
        if not self.is_available:
            return 0
        
        try:
            async with self.get_connection() as conn:
                if conn is None:
                    return 0
                
                result = await conn.execute(
                    """
                    DELETE FROM rag_queries
                    WHERE created_at < NOW() - INTERVAL '%s days'
                    """,
                    days
                )
                
                return int(result.split()[-1]) if "DELETE" in result else 0
                
        except Exception as e:
            logger.error(f"❌ Error al limpiar queries antiguas: {e}")
            return 0

    async def _drop_and_recreate_database(self):
        """
        Elimina la base de datos existente (si existe) y la recrea.
        Útil para hacer una restauración limpia desde un backup.
        """
        admin_conn = None
        try:
            # Conectar como administrador a la BD 'postgres'
            admin_conn = await asyncpg.connect(
                host=self.host,
                port=self.port,
                user=self.admin_user,
                password=self.admin_password,
                database='postgres',
                timeout=self.query_timeout,
            )
            
            # Terminar todas las conexiones a la BD antes de eliminarla
            await admin_conn.execute(
                f"""
                SELECT pg_terminate_backend(pg_stat_activity.pid)
                FROM pg_stat_activity
                WHERE pg_stat_activity.datname = $1
                AND pid <> pg_backend_pid()
                """,
                self.database
            )
            logger.info(f"✅ Conexiones existentes a '{self.database}' terminadas")
            
            # Eliminar la base de datos si existe
            db_exists = await admin_conn.fetchval(
                "SELECT 1 FROM pg_database WHERE datname = $1",
                self.database
            )
            
            if db_exists:
                # Validar nombre de BD
                if not self.database.replace('_', '').isalnum():
                    raise ValueError(f"Nombre de base de datos inválido: {self.database}")
                
                await admin_conn.execute(f"DROP DATABASE {self.database}")
                logger.info(f"✅ Base de datos '{self.database}' eliminada")
            
            # Crear la base de datos nuevamente
            if not self.database.replace('_', '').isalnum():
                raise ValueError(f"Nombre de base de datos inválido: {self.database}")
            
            await admin_conn.execute(
                f"CREATE DATABASE {self.database} OWNER {self.user}"
            )
            logger.info(f"✅ Base de datos '{self.database}' recreada")
            
            # Conectar a la nueva BD para habilitar pgvector
            db_conn = await asyncpg.connect(
                host=self.host,
                port=self.port,
                user=self.admin_user,
                password=self.admin_password,
                database=self.database,
                timeout=self.query_timeout,
            )
            try:
                await db_conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
                logger.info(f"✅ Extensión pgvector habilitada en '{self.database}'")
            finally:
                await db_conn.close()
            
            # Otorgar privilegios
            await admin_conn.execute(
                f"GRANT ALL PRIVILEGES ON DATABASE {self.database} TO {self.user}"
            )
            
        except Exception as e:
            logger.error(f"❌ Error al eliminar/recrear base de datos: {e}")
            raise
        finally:
            if admin_conn:
                await admin_conn.close()

    async def backup_to_file(self, backup_file: str) -> bool:
        """
        Crea un backup completo de la base de datos en un archivo SQL.
        
        Args:
            backup_file: Ruta del archivo donde guardar el backup
            
        Returns:
            True si el backup se realizó exitosamente, False en caso contrario
        """
        if not self.is_available:
            logger.error("❌ Base de datos no disponible. No se puede hacer backup.")
            return False
        
        try:
            import subprocess
            
            # Configurar variables de entorno para pg_dump
            env = os.environ.copy()
            env['PGPASSWORD'] = self.password
            
            # Comando pg_dump para hacer backup completo
            cmd = [
                'pg_dump',
                f'--host={self.host}',
                f'--port={self.port}',
                f'--username={self.user}',
                '--no-password',
                '--format=plain',
                '--verbose',
                '--file={}'.format(backup_file),
                self.database
            ]
            
            logger.info(f"📦 Iniciando backup de '{self.database}' a '{backup_file}'...")
            result = subprocess.run(cmd, env=env, capture_output=True, text=True)
            
            if result.returncode != 0:
                logger.error(f"❌ Error en pg_dump: {result.stderr}")
                return False
            
            # Verificar que el archivo se creó
            if not os.path.exists(backup_file):
                logger.error(f"❌ Archivo de backup no creado: {backup_file}")
                return False
            
            file_size = os.path.getsize(backup_file) / (1024 * 1024)  # Tamaño en MB
            logger.info(f"✅ Backup realizado exitosamente: {backup_file} ({file_size:.2f} MB)")
            return True
            
        except FileNotFoundError:
            logger.error("❌ pg_dump no encontrado. Asegúrate de tener PostgreSQL instalado.")
            return False
        except Exception as e:
            logger.error(f"❌ Error durante backup: {e}")
            return False

    async def restore_from_file(self, backup_file: str, create_db_and_user: bool = False) -> bool:
        """
        Restaura la base de datos desde un archivo de backup SQL.
        
        Args:
            backup_file: Ruta del archivo de backup
            create_db_and_user: Si True, crea la BD y usuario si no existen
            
        Returns:
            True si la restauración se realizó exitosamente, False en caso contrario
        """
        if not self.is_available:
            logger.error("❌ Base de datos no disponible. No se puede restaurar.")
            return False
        
        if not os.path.exists(backup_file):
            logger.error(f"❌ Archivo de backup no encontrado: {backup_file}")
            return False
        
        try:
            import subprocess
            
            # Si se pide crear BD y usuario, hacerlo primero
            if create_db_and_user:
                logger.info("📝 Creando base de datos y usuario si no existen...")
                await self._ensure_database_and_user_exist()
            else:
                # Si NO estamos en modo create_db_and_user, eliminar la BD existente
                # para asegurar una restauración limpia
                logger.info("🗑️  Eliminando base de datos existente para hacer restauración limpia...")
                await self._drop_and_recreate_database()
            
            # Configurar variables de entorno para psql
            env = os.environ.copy()
            env['PGPASSWORD'] = self.password
            
            # Comando psql para restaurar desde el backup
            cmd = [
                'psql',
                f'--host={self.host}',
                f'--port={self.port}',
                f'--username={self.user}',
                '--no-password',
                f'--dbname={self.database}',
                f'--file={backup_file}'
            ]
            
            logger.info(f"📥 Iniciando restauración desde '{backup_file}' a base de datos '{self.database}'...")
            result = subprocess.run(cmd, env=env, capture_output=True, text=True)
            
            if result.returncode != 0:
                logger.error(f"❌ Error en psql durante restauración: {result.stderr}")
                return False
            
            logger.info(f"✅ Restauración completada exitosamente desde {backup_file}")
            return True
            
        except FileNotFoundError:
            logger.error("❌ psql no encontrado. Asegúrate de tener PostgreSQL instalado.")
            return False
        except Exception as e:
            logger.error(f"❌ Error durante restauración: {e}")
            return False

    # =============================================
    #  FAQ: Featured queries & Categorías
    # =============================================

    async def update_featured(self, query_uuid: str, featured: bool) -> bool:
        """Marca/desmarca una consulta como destacada para FAQ público"""
        if not self.is_available:
            return False
        try:
            async with self.get_connection() as conn:
                if conn is None:
                    return False
                result = await conn.execute(
                    "UPDATE rag_queries SET featured = $1 WHERE uuid = $2",
                    featured, query_uuid
                )
                return result != "UPDATE 0"
        except Exception as e:
            logger.error(f"❌ Error al actualizar featured: {e}")
            return False

    async def log_vote(self, query_id: int, is_like: bool, ip: str, from_admin: bool = False) -> bool:
        """Registra un voto en la tabla de auditoría ip_likes con datos GeoIP"""
        if not self.is_available:
            return False
        try:
            geo = geoip_lookup(ip) if ip else {"country": None, "city": None}
            async with self.get_connection() as conn:
                if conn is None:
                    return False
                await conn.execute(
                    "INSERT INTO ip_likes (query_id, is_like, ip, from_admin, country, city) VALUES ($1, $2, $3, $4, $5, $6)",
                    query_id, is_like, ip, from_admin, geo["country"], geo["city"]
                )
                return True
        except Exception as e:
            logger.error(f"❌ Error al registrar voto en ip_likes: {e}")
            return False

    async def get_vote_history(self, query_id: int) -> List[Dict[str, Any]]:
        """Obtiene el historial de votos de una consulta desde ip_likes"""
        if not self.is_available:
            return []
        try:
            async with self.get_connection() as conn:
                if conn is None:
                    return []
                records = await conn.fetch(
                    """
                    SELECT id, is_like, date, ip, from_admin, country, city
                    FROM ip_likes
                    WHERE query_id = $1
                    ORDER BY date DESC
                    """,
                    query_id
                )
                return [
                    {
                        "id": r["id"],
                        "is_like": r["is_like"],
                        "date": r["date"].isoformat() if r["date"] else None,
                        "ip": r["ip"],
                        "from_admin": r["from_admin"],
                        "country": r["country"],
                        "city": r["city"]
                    }
                    for r in records
                ]
        except Exception as e:
            logger.error(f"❌ Error al obtener historial de votos: {e}")
            return []

    async def get_featured_queries(
        self,
        podcast_name: Optional[str] = None,
        limit: int = 2000
    ) -> List[Dict[str, Any]]:
        """Obtiene consultas destacadas con sus categorías"""
        if not self.is_available:
            return []
        try:
            async with self.get_connection() as conn:
                if conn is None:
                    return []
                if podcast_name:
                    records = await conn.fetch("""
                        SELECT q.id, q.uuid, q.query_text, q.response_text,
                               q.created_at, q.likes, q.dislikes, q.podcast_name,
                               COALESCE(
                                   array_agg(DISTINCT c.name) FILTER (WHERE c.name IS NOT NULL),
                                   ARRAY[]::VARCHAR[]
                               ) as categories,
                               COALESCE(
                                   array_agg(DISTINCT c.slug) FILTER (WHERE c.slug IS NOT NULL),
                                   ARRAY[]::VARCHAR[]
                               ) as category_slugs
                        FROM rag_queries q
                        LEFT JOIN rag_query_categories qc ON q.id = qc.query_id
                        LEFT JOIN rag_categories c ON qc.category_id = c.id
                        WHERE q.featured = TRUE AND q.allowed = TRUE
                              AND q.podcast_name = $1
                        GROUP BY q.id
                        ORDER BY (q.likes - q.dislikes) DESC, q.created_at DESC
                        LIMIT $2
                    """, podcast_name, limit)
                else:
                    records = await conn.fetch("""
                        SELECT q.id, q.uuid, q.query_text, q.response_text,
                               q.created_at, q.likes, q.dislikes, q.podcast_name,
                               COALESCE(
                                   array_agg(DISTINCT c.name) FILTER (WHERE c.name IS NOT NULL),
                                   ARRAY[]::VARCHAR[]
                               ) as categories,
                               COALESCE(
                                   array_agg(DISTINCT c.slug) FILTER (WHERE c.slug IS NOT NULL),
                                   ARRAY[]::VARCHAR[]
                               ) as category_slugs
                        FROM rag_queries q
                        LEFT JOIN rag_query_categories qc ON q.id = qc.query_id
                        LEFT JOIN rag_categories c ON qc.category_id = c.id
                        WHERE q.featured = TRUE AND q.allowed = TRUE
                        GROUP BY q.id
                        ORDER BY (q.likes - q.dislikes) DESC, q.created_at DESC
                        LIMIT $1
                    """, limit)
                result = [dict(r) for r in records]
                if len(result) >= limit:
                    logger.warning(f"⚠️  get_featured_queries alcanzó el límite de {limit} consultas. "
                                   f"Puede haber consultas destacadas que no se muestran.")
                return result
        except Exception as e:
            logger.error(f"❌ Error al obtener consultas destacadas: {e}")
            return []

    async def get_featured_queries_by_category(
        self,
        category_id: int,
        podcast_name: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Obtiene consultas destacadas de una categoría específica"""
        if not self.is_available:
            return []
        try:
            async with self.get_connection() as conn:
                if conn is None:
                    return []
                if podcast_name:
                    records = await conn.fetch("""
                        SELECT q.id, q.uuid, q.query_text, q.response_text,
                               q.created_at, q.likes, c.name as category_name
                        FROM rag_queries q
                        JOIN rag_query_categories qc ON q.id = qc.query_id
                        JOIN rag_categories c ON qc.category_id = c.id
                        WHERE q.featured = TRUE AND q.allowed = TRUE
                              AND c.id = $1 AND q.podcast_name = $2
                        ORDER BY q.likes DESC, q.created_at DESC
                        LIMIT $3
                    """, category_id, podcast_name, limit)
                else:
                    records = await conn.fetch("""
                        SELECT q.id, q.uuid, q.query_text, q.response_text,
                               q.created_at, q.likes, c.name as category_name
                        FROM rag_queries q
                        JOIN rag_query_categories qc ON q.id = qc.query_id
                        JOIN rag_categories c ON qc.category_id = c.id
                        WHERE q.featured = TRUE AND q.allowed = TRUE
                              AND c.id = $1
                        ORDER BY q.likes DESC, q.created_at DESC
                        LIMIT $2
                    """, category_id, limit)
                return [dict(r) for r in records]
        except Exception as e:
            logger.error(f"❌ Error al obtener consultas por categoría: {e}")
            return []

    async def get_queries_geo_summary(
        self,
        podcast_name: Optional[str] = None,
        likes_threshold: int = 0
    ) -> List[Dict[str, Any]]:
        """Obtiene un resumen geográfico de consultas agrupadas por ciudad o país.

        Filtra consultas cuyo (likes - dislikes) >= likes_threshold.
        Retorna una lista de dicts con country, city, query_count y sample_ip
        (una IP representativa para resolver coordenadas localmente vía GeoIP).
        Si falta la ciudad, la entrada se mantiene usando el país.
        """
        if not self.is_available:
            return []
        try:
            async with self.get_connection() as conn:
                if conn is None:
                    return []
                if podcast_name:
                    records = await conn.fetch("""
                        SELECT country, city, COUNT(*) AS query_count,
                               MIN(ip) AS sample_ip
                        FROM rag_queries
                        WHERE podcast_name = $1
                          AND featured = TRUE
                          AND allowed = TRUE
                          AND country IS NOT NULL
                          AND ip IS NOT NULL
                          AND (likes - dislikes) >= $2
                        GROUP BY country, city
                        ORDER BY query_count DESC
                    """, podcast_name, likes_threshold)
                else:
                    records = await conn.fetch("""
                        SELECT country, city, COUNT(*) AS query_count,
                               MIN(ip) AS sample_ip
                        FROM rag_queries
                        WHERE featured = TRUE
                          AND allowed = TRUE
                          AND country IS NOT NULL
                          AND ip IS NOT NULL
                          AND (likes - dislikes) >= $1
                        GROUP BY country, city
                        ORDER BY query_count DESC
                    """, likes_threshold)
                return [dict(r) for r in records]
        except Exception as e:
            logger.error(f"❌ Error al obtener resumen geográfico: {e}")
            return []

    async def get_queries_by_city(
        self,
        city: str,
        podcast_name: Optional[str] = None,
        likes_threshold: int = 0,
        limit: int = 500
    ) -> List[Dict[str, Any]]:
        """Obtiene consultas realizadas desde una ciudad específica.

        Filtra consultas cuyo (likes - dislikes) >= likes_threshold.
        No devuelve la IP (privacidad).
        """
        if not self.is_available:
            return []
        try:
            async with self.get_connection() as conn:
                if conn is None:
                    return []
                if podcast_name:
                    records = await conn.fetch("""
                        SELECT id, uuid, query_text, response_text, created_at,
                               podcast_name, country, city, likes, dislikes
                        FROM rag_queries
                        WHERE city = $1 AND podcast_name = $2
                          AND featured = TRUE AND allowed = TRUE
                          AND (likes - dislikes) >= $3
                        ORDER BY created_at DESC
                        LIMIT $4
                    """, city, podcast_name, likes_threshold, limit)
                else:
                    records = await conn.fetch("""
                        SELECT id, uuid, query_text, response_text, created_at,
                               podcast_name, country, city, likes, dislikes
                        FROM rag_queries
                        WHERE city = $1
                          AND featured = TRUE AND allowed = TRUE
                          AND (likes - dislikes) >= $2
                        ORDER BY created_at DESC
                        LIMIT $3
                    """, city, likes_threshold, limit)
                return [dict(r) for r in records]
        except Exception as e:
            logger.error(f"❌ Error al obtener consultas por ciudad: {e}")
            return []

    async def get_queries_by_country(
        self,
        country: str,
        podcast_name: Optional[str] = None,
        likes_threshold: int = 0,
        limit: int = 500
    ) -> List[Dict[str, Any]]:
        """Obtiene consultas realizadas desde un país específico."""
        if not self.is_available:
            return []
        try:
            async with self.get_connection() as conn:
                if conn is None:
                    return []
                if podcast_name:
                    records = await conn.fetch("""
                        SELECT id, uuid, query_text, response_text, created_at,
                               podcast_name, country, city, likes, dislikes
                        FROM rag_queries
                        WHERE country = $1 AND podcast_name = $2
                          AND featured = TRUE AND allowed = TRUE
                          AND (likes - dislikes) >= $3
                        ORDER BY created_at DESC
                        LIMIT $4
                    """, country, podcast_name, likes_threshold, limit)
                else:
                    records = await conn.fetch("""
                        SELECT id, uuid, query_text, response_text, created_at,
                               podcast_name, country, city, likes, dislikes
                        FROM rag_queries
                        WHERE country = $1
                          AND featured = TRUE AND allowed = TRUE
                          AND (likes - dislikes) >= $2
                        ORDER BY created_at DESC
                        LIMIT $3
                    """, country, likes_threshold, limit)
                return [dict(r) for r in records]
        except Exception as e:
            logger.error(f"❌ Error al obtener consultas por país: {e}")
            return []

    async def get_all_queries_admin(
        self,
        podcast_name: Optional[str] = None,
        limit: int = 500,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Obtiene todas las consultas con info de featured y categorías (para admin)"""
        if not self.is_available:
            return []
        try:
            async with self.get_connection() as conn:
                if conn is None:
                    return []
                if podcast_name:
                    records = await conn.fetch("""
                        SELECT q.id, q.uuid, q.query_text, q.response_text,
                               q.created_at, q.likes, q.dislikes,
                               q.featured, q.allowed, q.podcast_name,
                               q.ip, q.country, q.city,
                               COALESCE(
                                   array_agg(DISTINCT jsonb_build_object(
                                       'id', c.id, 'name', c.name, 'slug', c.slug,
                                       'assigned_by', qc.assigned_by
                                   ))
                                   FILTER (WHERE c.id IS NOT NULL),
                                   ARRAY[]::JSONB[]
                               ) as categories
                        FROM rag_queries q
                        LEFT JOIN rag_query_categories qc ON q.id = qc.query_id
                        LEFT JOIN rag_categories c ON qc.category_id = c.id
                        WHERE q.podcast_name = $1
                        GROUP BY q.id
                        ORDER BY q.created_at DESC
                        LIMIT $2 OFFSET $3
                    """, podcast_name, limit, offset)
                else:
                    records = await conn.fetch("""
                        SELECT q.id, q.uuid, q.query_text, q.response_text,
                               q.created_at, q.likes, q.dislikes,
                               q.featured, q.allowed, q.podcast_name,
                               q.ip, q.country, q.city,
                               COALESCE(
                                   array_agg(DISTINCT jsonb_build_object(
                                       'id', c.id, 'name', c.name, 'slug', c.slug,
                                       'assigned_by', qc.assigned_by
                                   ))
                                   FILTER (WHERE c.id IS NOT NULL),
                                   ARRAY[]::JSONB[]
                               ) as categories
                        FROM rag_queries q
                        LEFT JOIN rag_query_categories qc ON q.id = qc.query_id
                        LEFT JOIN rag_categories c ON qc.category_id = c.id
                        GROUP BY q.id
                        ORDER BY q.created_at DESC
                        LIMIT $1 OFFSET $2
                    """, limit, offset)
                result = []
                for r in records:
                    d = dict(r)
                    # Parsear array de JSONB a lista de dicts
                    import json as json_mod
                    cats = d.get('categories', [])
                    parsed_cats = []
                    for c in cats:
                        if isinstance(c, str):
                            parsed_cats.append(json_mod.loads(c))
                        elif isinstance(c, dict):
                            parsed_cats.append(c)
                    d['categories'] = parsed_cats
                    result.append(d)
                return result
        except Exception as e:
            logger.error(f"❌ Error al obtener consultas para admin: {e}")
            return []

    async def update_categorization_embedding(
        self,
        query_id: int,
        embedding: List[float]
    ) -> bool:
        """Actualiza el embedding combinado pregunta+respuesta de una consulta"""
        if not self.is_available:
            return False
        try:
            async with self.get_connection() as conn:
                if conn is None:
                    return False
                await conn.execute(
                    "UPDATE rag_queries SET categorization_embedding = $1 WHERE id = $2",
                    str(embedding), query_id
                )
                return True
        except Exception as e:
            logger.error(f"❌ Error al actualizar categorization_embedding: {e}")
            return False

    async def get_categorization_text(self, query_id: int) -> Optional[str]:
        """
        Construye texto combinado pregunta+respuesta para categorización.
        La respuesta aporta el contexto semántico que la pregunta sola no tiene.
        """
        if not self.is_available:
            return None
        try:
            async with self.get_connection() as conn:
                if conn is None:
                    return None
                record = await conn.fetchrow(
                    "SELECT query_text, response_text FROM rag_queries WHERE id = $1",
                    query_id
                )
                if not record:
                    return None
                response_text = record['response_text'] or ''
                response_words = response_text.split()
                if len(response_words) > 500:
                    response_text = ' '.join(response_words[:500])
                return f"Pregunta: {record['query_text']}\nRespuesta: {response_text}"
        except Exception as e:
            logger.error(f"❌ Error al obtener texto de categorización: {e}")
            return None

    # --- Categorías ---

    async def create_category(
        self,
        name: str,
        slug: str,
        description: Optional[str] = None,
        parent_id: Optional[int] = None,
        is_primary: bool = False,
        display_order: int = 0,
        category_embedding: Optional[List[float]] = None,
        created_by: str = 'admin'
    ) -> Optional[Dict[str, Any]]:
        """Crea una nueva categoría"""
        if not self.is_available:
            return None
        try:
            async with self.get_connection() as conn:
                if conn is None:
                    return None
                embedding_value = str(category_embedding) if category_embedding else None
                result = await conn.fetchrow("""
                    INSERT INTO rag_categories (name, slug, description, parent_id, is_primary, display_order, category_embedding, created_by)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    RETURNING id, name, slug, description, parent_id, is_primary, display_order, created_by
                """, name, slug, description, parent_id, is_primary, display_order, embedding_value, created_by)
                return dict(result) if result else None
        except Exception as e:
            logger.error(f"❌ Error al crear categoría: {e}")
            return None

    async def update_category(
        self,
        category_id: int,
        name: Optional[str] = None,
        slug: Optional[str] = None,
        description: Optional[str] = None,
        parent_id: Optional[int] = None,
        is_primary: Optional[bool] = None,
        display_order: Optional[int] = None
    ) -> bool:
        """Actualiza campos de una categoría"""
        if not self.is_available:
            return False
        try:
            async with self.get_connection() as conn:
                if conn is None:
                    return False
                # Construir SET dinámico
                updates = []
                params = []
                param_idx = 1
                if name is not None:
                    updates.append(f"name = ${param_idx}")
                    params.append(name)
                    param_idx += 1
                if slug is not None:
                    updates.append(f"slug = ${param_idx}")
                    params.append(slug)
                    param_idx += 1
                if description is not None:
                    updates.append(f"description = ${param_idx}")
                    params.append(description)
                    param_idx += 1
                if parent_id is not None:
                    # Usar -1 para indicar "sin padre"
                    actual_parent = None if parent_id == -1 else parent_id
                    updates.append(f"parent_id = ${param_idx}")
                    params.append(actual_parent)
                    param_idx += 1
                if is_primary is not None:
                    updates.append(f"is_primary = ${param_idx}")
                    params.append(is_primary)
                    param_idx += 1
                if display_order is not None:
                    updates.append(f"display_order = ${param_idx}")
                    params.append(display_order)
                    param_idx += 1
                
                if not updates:
                    return True  # Nada que actualizar
                
                # Editar una categoría la convierte en 'admin' (manual)
                updates.append(f"created_by = ${param_idx}")
                params.append('admin')
                param_idx += 1
                
                params.append(category_id)
                query = f"UPDATE rag_categories SET {', '.join(updates)} WHERE id = ${param_idx}"
                result = await conn.execute(query, *params)
                return result != "UPDATE 0"
        except Exception as e:
            logger.error(f"❌ Error al actualizar categoría: {e}")
            return False

    async def delete_category(self, category_id: int) -> bool:
        """
        Elimina una categoría. Los hijos se reasignan al padre (ON DELETE SET NULL).
        También se eliminan las asignaciones a consultas (ON DELETE CASCADE).
        """
        if not self.is_available:
            return False
        try:
            async with self.get_connection() as conn:
                if conn is None:
                    return False
                # Obtener padre de la categoría a eliminar
                parent = await conn.fetchval(
                    "SELECT parent_id FROM rag_categories WHERE id = $1",
                    category_id
                )
                # Reasignar hijos al padre
                await conn.execute(
                    "UPDATE rag_categories SET parent_id = $1 WHERE parent_id = $2",
                    parent, category_id
                )
                # Eliminar la categoría
                result = await conn.execute(
                    "DELETE FROM rag_categories WHERE id = $1",
                    category_id
                )
                return result != "DELETE 0"
        except Exception as e:
            logger.error(f"❌ Error al eliminar categoría: {e}")
            return False

    async def get_categories_tree(self) -> List[Dict[str, Any]]:
        """Obtiene todas las categorías como árbol jerárquico"""
        if not self.is_available:
            return []
        try:
            async with self.get_connection() as conn:
                if conn is None:
                    return []
                records = await conn.fetch("""
                    SELECT c.id, c.name, c.slug, c.description, c.parent_id,
                           c.is_primary, c.display_order, c.created_by,
                           COUNT(qc.query_id) as query_count
                    FROM rag_categories c
                    LEFT JOIN rag_query_categories qc ON c.id = qc.category_id
                    LEFT JOIN rag_queries q ON qc.query_id = q.id AND q.featured = TRUE AND q.allowed = TRUE
                    GROUP BY c.id
                    ORDER BY c.display_order, c.name
                """)
                categories = [dict(r) for r in records]
                # Construir árbol
                by_id = {c['id']: {**c, 'children': []} for c in categories}
                tree = []
                for c in categories:
                    if c['parent_id'] and c['parent_id'] in by_id:
                        by_id[c['parent_id']]['children'].append(by_id[c['id']])
                    else:
                        tree.append(by_id[c['id']])
                return tree
        except Exception as e:
            logger.error(f"❌ Error al obtener árbol de categorías: {e}")
            return []

    async def get_all_categories_flat(self) -> List[Dict[str, Any]]:
        """Obtiene todas las categorías como lista plana (para selects)"""
        if not self.is_available:
            return []
        try:
            async with self.get_connection() as conn:
                if conn is None:
                    return []
                records = await conn.fetch("""
                    SELECT id, name, slug, description, parent_id, is_primary, display_order, created_by
                    FROM rag_categories
                    ORDER BY display_order, name
                """)
                return [dict(r) for r in records]
        except Exception as e:
            logger.error(f"❌ Error al obtener categorías: {e}")
            return []

    async def assign_query_to_category(
        self,
        query_id: int,
        category_id: int,
        assigned_by: str = 'admin',
        confidence: float = 1.0
    ) -> bool:
        """Asigna una consulta a una categoría"""
        if not self.is_available:
            return False
        try:
            async with self.get_connection() as conn:
                if conn is None:
                    return False
                await conn.execute("""
                    INSERT INTO rag_query_categories (query_id, category_id, assigned_by, confidence)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (query_id, category_id) DO UPDATE SET
                        assigned_by = CASE 
                            WHEN rag_query_categories.assigned_by = 'admin' 
                            THEN rag_query_categories.assigned_by 
                            ELSE EXCLUDED.assigned_by 
                        END,
                        confidence = CASE 
                            WHEN rag_query_categories.assigned_by = 'admin' 
                            THEN rag_query_categories.confidence 
                            ELSE EXCLUDED.confidence 
                        END
                """, query_id, category_id, assigned_by, confidence)
                return True
        except Exception as e:
            logger.error(f"❌ Error al asignar consulta a categoría: {e}")
            return False

    async def remove_query_from_category(
        self,
        query_id: int,
        category_id: int
    ) -> bool:
        """Elimina la asignación de una consulta a una categoría"""
        if not self.is_available:
            return False
        try:
            async with self.get_connection() as conn:
                if conn is None:
                    return False
                result = await conn.execute(
                    "DELETE FROM rag_query_categories WHERE query_id = $1 AND category_id = $2",
                    query_id, category_id
                )
                return result != "DELETE 0"
        except Exception as e:
            logger.error(f"❌ Error al eliminar asignación: {e}")
            return False

    async def suggest_categories_for_query(
        self,
        embedding: List[float],
        limit: int = 3
    ) -> List[Dict[str, Any]]:
        """Sugiere categorías para una consulta usando similitud vectorial"""
        if not self.is_available:
            return []
        try:
            async with self.get_connection() as conn:
                if conn is None:
                    return []
                records = await conn.fetch("""
                    SELECT id, name, slug,
                           1 - (category_embedding <=> $1::vector) AS similarity
                    FROM rag_categories
                    WHERE category_embedding IS NOT NULL
                    ORDER BY category_embedding <=> $1::vector
                    LIMIT $2
                """, str(embedding), limit)
                return [dict(r) for r in records]
        except Exception as e:
            logger.error(f"❌ Error al sugerir categorías: {e}")
            return []

    async def get_faq_grouped(
        self,
        podcast_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Obtiene consultas destacadas agrupadas por categoría para el FAQ público.
        Retorna estructura con árbol de categorías y consultas agrupadas.
        """
        if not self.is_available:
            return {"categories": [], "grouped_queries": {}, "uncategorized": []}
        try:
            categories = await self.get_categories_tree()
            featured = await self.get_featured_queries(podcast_name=podcast_name)
            
            grouped = {}
            uncategorized = []
            
            for q in featured:
                cats = q.get('categories', [])
                query_info = {
                    'uuid': str(q['uuid']),
                    'query_text': q['query_text'],
                    'likes': q.get('likes', 0),
                    'dislikes': q.get('dislikes', 0),
                    'created_at': q['created_at'].isoformat() if hasattr(q['created_at'], 'isoformat') else str(q['created_at'])
                }
                if not cats or cats == [None]:
                    uncategorized.append(query_info)
                else:
                    for cat_name in cats:
                        if cat_name:
                            grouped.setdefault(cat_name, []).append(query_info)
            
            return {
                "categories": categories,
                "grouped_queries": grouped,
                "uncategorized": uncategorized
            }
        except Exception as e:
            logger.error(f"❌ Error al obtener FAQ agrupadas: {e}")
            return {"categories": [], "grouped_queries": {}, "uncategorized": []}


# Instancia global del gestor de BD
db = RAGDatabase()
