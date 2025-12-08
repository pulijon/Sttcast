# 🎯 GUÍA DE USO: CACHÉ SEMÁNTICO CON PostgreSQL + PGVector

## ¿Cómo habilitar la BD?

En `.env/rag_client.env`, descomenta estas líneas:

```bash
POSTGRES_HOST = postgres           # En Docker: "postgres", En local: "localhost"
POSTGRES_PORT = 5432
POSTGRES_DB = sttcast_rag
POSTGRES_USER = rag_user
POSTGRES_PASSWORD = rag_password   # ⚠️  CAMBIAR EN PRODUCCIÓN
```

## ¿Qué se guarda?

Cada pregunta en `/api/ask` se guarda en BD:
- **query_text**: La pregunta del usuario
- **response_text**: La respuesta del RAG
- **query_embedding**: Vector de embeddings (1536 dimensiones)
- **podcast_name**: Nombre del podcast
- **created_at**: Timestamp

## ¿Cómo acceder a las queries guardadas?

```python
from rag.client.database import db
import asyncio

# Obtener todas las queries de un podcast
queries = asyncio.run(
    db.get_all_queries(podcast_name="Cowboys de Medianoche", limit=10)
)

# Buscar queries similares (aún no implementado en UI)
similar = asyncio.run(
    db.search_similar_queries(
        query_embedding=[0.1, 0.2, ...],  # embedding de la pregunta
        podcast_name="Cowboys de Medianoche",
        similarity_threshold=0.8
    )
)
```

## Próxima optimización: CACHÉ SEMÁNTICO

Antes de consultar `context_server`, el flujo será:

```
1. Usuario pregunta: "¿Qué dijeron sobre economía?"
2. Obtener embedding de la pregunta
3. Buscar en BD: ¿hay preguntas similares (>0.8 similitud)?
4. SI → Retornar respuesta en caché (⚡ rápido, sin costo)
5. NO → Consultar context_server normalmente (→ guardar en BD)
```

## Estructura de la BD

```sql
-- Tabla principal
CREATE TABLE rag_queries (
    id SERIAL PRIMARY KEY,
    query_text TEXT NOT NULL,
    response_text TEXT NOT NULL,
    query_embedding vector(1536),     -- Búsqueda semántica
    created_at TIMESTAMP DEFAULT NOW(),
    podcast_name VARCHAR(255)
);

-- Índices para performance
CREATE INDEX idx_query_embedding_gist ON rag_queries USING gist (query_embedding);
CREATE INDEX idx_podcast_name ON rag_queries(podcast_name);
CREATE INDEX idx_created_at ON rag_queries(created_at DESC);

-- Tabla de auditoría
CREATE TABLE rag_queries_access_log (
    id SERIAL PRIMARY KEY,
    query_id INTEGER REFERENCES rag_queries(id) ON DELETE CASCADE,
    access_time TIMESTAMP DEFAULT NOW(),
    similarity_score FLOAT
);
```

## Módulo database.py - API

```python
# Guardar query
await db.save_query(
    query_text="¿Qué pasó con...?",
    response_text="La respuesta fue...",
    query_embedding=[0.1, 0.2, ...],
    podcast_name="Cowboys de Medianoche"
)

# Buscar similares
similar = await db.search_similar_queries(
    query_embedding=[0.1, 0.2, ...],
    podcast_name="Cowboys de Medianoche",
    limit=5,
    similarity_threshold=0.8
)

# Obtener todo
all_queries = await db.get_all_queries(
    podcast_name="Cowboys de Medianoche",
    limit=100,
    offset=0
)

# Registrar acceso (para auditoría)
await db.log_query_access(query_id=123, similarity_score=0.95)

# Limpiar antiguas (>30 días)
deleted = await db.cleanup_old_queries(days=30)
```

## Troubleshooting

### ❌ Error: "asyncpg not installed"
```bash
pip install asyncpg
```

### ❌ Error: "POSTGRES_HOST not configured"
App funciona sin BD. Descomenta las variables en `.env/rag_client.env`

### ❌ Error: "Connection refused"
- En Docker: ¿existe el servicio postgres en docker-compose.yml?
- En local: ¿está corriendo PostgreSQL? `psql -U rag_user -d sttcast_rag`

### ❌ Error: "pgvector extension not found"
```bash
# Dentro del contenedor de postgres
psql -U rag_user -d sttcast_rag
CREATE EXTENSION IF NOT EXISTS vector;
```

## Performance

- **Pool size**: 2-10 conexiones (configurable)
- **Query timeout**: 30 segundos (configurable)
- **Índices**: GiST para búsquedas de embeddings (O(log N))
- **Async**: No bloquea el endpoint `/api/ask`

## Seguridad

⚠️  En producción:
1. Cambiar `POSTGRES_PASSWORD`
2. Usar secrets management (AWS Secrets, HashiCorp Vault)
3. Configurar SSL para conexiones a BD
4. Limitar acceso a la BD por firewall

## Próximas características

- [ ] Dashboard de caché hit/miss rate
- [ ] API para consultar queries guardadas
- [ ] Limpieza automática de queries antiguas
- [ ] Exportar queries a CSV/JSON
- [ ] Visualizar similitudes entre queries
- [ ] Estadísticas de coste evitado (queries en caché)
