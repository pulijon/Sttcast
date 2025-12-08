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

logger = logging.getLogger(__name__)


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
        podcast_name: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Guarda una query, respuesta y embedding en la BD
        
        Args:
            query_text: Texto de la pregunta
            response_text: Texto de la respuesta (para backward compatibility)
            response_data: Dict completo con {response: {es: ..., en: ...}, references: [...]}
            query_embedding: Vector embedding de la pregunta (lista de floats)
            podcast_name: Nombre del podcast
            
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
                
                # SQL para insertar - El orden debe coincidir con el de VALUES
                query = """
                    INSERT INTO rag_queries (query_text, response_text, query_embedding, podcast_name, response_data, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    RETURNING id, uuid;
                """
                
                result = await conn.fetchrow(
                    query,
                    query_text,          # $1 -> query_text (TEXT)
                    response_text,       # $2 -> response_text (TEXT)
                    embedding_value,     # $3 -> query_embedding (vector(1536))
                    podcast_name,        # $4 -> podcast_name (VARCHAR)
                    response_data_json,  # $5 -> response_data (JSONB)
                    datetime.now()       # $6 -> created_at (TIMESTAMP)
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
                            podcast_name
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
                            podcast_name
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
                        SELECT id, uuid, query_text, response_text, created_at, podcast_name
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
                        SELECT id, uuid, query_text, response_text, created_at, podcast_name
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


# Instancia global del gestor de BD
db = RAGDatabase()
