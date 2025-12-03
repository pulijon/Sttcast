"""
Módulo de acceso a base de datos PostgreSQL para almacenar queries y embeddings.
Proporciona una capa de abstracción para guardar preguntas, respuestas y embeddings.

Este módulo es OPCIONAL y solo se activa si existen credenciales en rag_client.env
"""

import asyncio
import os
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
        self.host = os.getenv("POSTGRES_HOST")
        self.port = int(os.getenv("POSTGRES_PORT", "5432"))
        self.database = os.getenv("POSTGRES_DB")
        self.user = os.getenv("POSTGRES_USER")
        self.password = os.getenv("POSTGRES_PASSWORD")
        
        # Pool de conexiones
        self.pool = None
        
        # Parámetros del pool
        self.pool_min_size = int(os.getenv("POSTGRES_POOL_MIN_SIZE", "2"))
        self.pool_max_size = int(os.getenv("POSTGRES_POOL_MAX_SIZE", "10"))
        self.query_timeout = int(os.getenv("POSTGRES_QUERY_TIMEOUT", "30"))
        
        # Flag de disponibilidad
        self.is_available = self._check_configuration()
        
        if self.is_available:
            logger.info("📦 Configuración de BD encontrada. Base de datos habilitada.")
        else:
            logger.info("⚠️  Configuración de BD no encontrada. Ejecutando sin BD (compatible hacia atrás)")

    def _check_configuration(self) -> bool:
        """Verifica si todas las credenciales están configuradas"""
        required_vars = [
            "POSTGRES_HOST",
            "POSTGRES_PORT",
            "POSTGRES_DB",
            "POSTGRES_USER",
            "POSTGRES_PASSWORD"
        ]
        
        # Comprobar que todas las variables existan
        for var in required_vars:
            if not os.getenv(var):
                return False
        
        # Comprobar que asyncpg esté disponible
        if not HAS_ASYNCPG:
            logger.warning("⚠️  asyncpg no instalado. Base de datos deshabilitada.")
            return False
        
        return True

    async def initialize(self):
        """Inicializa el pool de conexiones"""
        if not self.is_available:
            return
        
        try:
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

    async def close(self):
        """Cierra el pool de conexiones"""
        if self.pool:
            await self.pool.close()

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
        query_embedding: Optional[List[float]] = None,
        podcast_name: Optional[str] = None
    ) -> Optional[int]:
        """
        Guarda una query, respuesta y embedding en la BD
        
        Args:
            query_text: Texto de la pregunta
            response_text: Texto de la respuesta
            query_embedding: Vector embedding de la pregunta (lista de floats)
            podcast_name: Nombre del podcast
            
        Returns:
            ID de la fila insertada o None si error
        """
        if not self.is_available:
            return None
        
        try:
            async with self.get_connection() as conn:
                if conn is None:
                    return None
                
                # Preparar el embedding como vector para PostgreSQL
                # asyncpg enviará la lista de floats directamente
                embedding_value = None
                if query_embedding:
                    embedding_value = query_embedding
                
                # SQL para insertar
                query = """
                    INSERT INTO rag_queries (query_text, response_text, query_embedding, podcast_name, created_at)
                    VALUES ($1, $2, $3, $4, $5)
                    RETURNING id;
                """
                
                result = await conn.fetchval(
                    query,
                    query_text,
                    response_text,
                    embedding_value,
                    podcast_name,
                    datetime.now()
                )
                
                logger.debug(f"💾 Query guardada con ID: {result}")
                return result
                
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
                        query_embedding,
                        podcast_name,
                        1 - similarity_threshold,
                        limit
                    )
                else:
                    query = """
                        SELECT 
                            id,
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
                        query_embedding,
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
                        SELECT id, query_text, response_text, created_at, podcast_name
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
                        SELECT id, query_text, response_text, created_at, podcast_name
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
