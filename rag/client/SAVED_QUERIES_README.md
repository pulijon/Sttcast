# Sistema de Consultas Guardadas con UUID

## Descripción

Este sistema permite guardar consultas y sus respuestas en PostgreSQL con pgvector, asignando un UUID único a cada consulta. Esto habilita:

1. **Compartir URLs** de consultas específicas
2. **Sistema de caché semántico** futuro (respuestas rápidas para preguntas similares)
3. **Compatibilidad total** con la interfaz web existente

## Arquitectura

```
Usuario → /api/ask → Genera respuesta → Guarda en BD con UUID → Retorna URL compartible
                                                                         ↓
                                                              /savedquery/{uuid} (HTML)
                                                              /api/savedquery/{uuid} (JSON)
```

## Endpoints

### 1. POST `/api/ask` - Consulta nueva
Procesa una pregunta, genera respuesta y **guarda automáticamente** en la BD.

**Request:**
```json
{
  "question": "¿De qué hablaron sobre inteligencia artificial?",
  "language": "es"
}
```

**Response:**
```json
{
  "success": true,
  "response": {
    "es": "Los contertulios discutieron...",
    "en": "The speakers discussed..."
  },
  "references": [
    {
      "tag": "Juan",
      "label": {"es": "Episodio 123", "en": "Episode 123"},
      "file": "cm250101",
      "time": 1234,
      "url": "...",
      "formatted_time": "20:34",
      "hyperlink": {"es": "...", "en": "..."}
    }
  ],
  "timestamp": "2025-12-07T10:30:00",
  "saved_query_url": "https://example.com/sttcast/savedquery/550e8400-e29b-41d4-a716-446655440000"
}
```

### 2. GET `/savedquery/{uuid}` - Vista HTML (RECOMENDADO para compartir)
Renderiza la consulta guardada en la **interfaz web completa**, idéntica a una consulta nueva.

**Ejemplo:**
```
https://example.com/sttcast/savedquery/550e8400-e29b-41d4-a716-446655440000
```

**Características:**
- ✅ Muestra la pregunta original en el input
- ✅ Renderiza la respuesta con formato
- ✅ Muestra tabla de referencias con audio
- ✅ Permite hacer nuevas consultas desde la misma página
- ✅ Compatible con accesibilidad, cookies, etc.

### 3. GET `/api/savedquery/{uuid}` - Vista JSON (para APIs)
Retorna la consulta guardada en formato JSON puro.

**Response:**
```json
{
  "success": true,
  "response": {
    "es": "Los contertulios discutieron...",
    "en": "The speakers discussed..."
  },
  "references": [...],
  "timestamp": "2025-12-07T10:30:00",
  "query": "¿De qué hablaron sobre inteligencia artificial?",
  "podcast_name": "Cowboys de Medianoche",
  "uuid": "550e8400-e29b-41d4-a716-446655440000",
  "saved_query_url": "/api/savedquery/550e8400-e29b-41d4-a716-446655440000"
}
```

## Base de Datos

### Tabla `rag_queries`

| Columna          | Tipo           | Descripción                                           |
|------------------|----------------|-------------------------------------------------------|
| `id`             | SERIAL         | ID autoincremental                                    |
| `uuid`           | UUID           | Identificador único (gen_random_uuid())               |
| `query_text`     | TEXT           | Texto de la pregunta                                  |
| `response_text`  | TEXT           | Respuesta en español (backward compatibility)         |
| `response_data`  | JSONB          | **NUEVO**: Respuesta completa con referencias         |
| `query_embedding`| VECTOR(1536)   | Embedding de la pregunta (OpenAI ada-002)             |
| `created_at`     | TIMESTAMP      | Fecha de creación                                     |
| `podcast_name`   | VARCHAR(255)   | Nombre del podcast                                    |
| `likes`          | INTEGER        | Likes de usuarios (futuro)                            |
| `dislikes`       | INTEGER        | Dislikes de usuarios (futuro)                         |
| `allowed`        | BOOLEAN        | Si está permitido mostrarlo públicamente              |

### Índices

- `idx_uuid`: BTREE en UUID (búsquedas rápidas)
- `idx_query_embedding_cosine`: HNSW para búsqueda semántica
- `idx_rag_queries_response_data`: GIN para consultas JSONB
- `idx_created_at`: Ordenamiento temporal
- `idx_podcast_name`: Filtrado por podcast

## Estructura de `response_data` (JSONB)

```json
{
  "query": "¿De qué hablaron sobre inteligencia artificial?",
  "response": {
    "es": "Los contertulios discutieron sobre los avances en IA...",
    "en": "The speakers discussed advances in AI..."
  },
  "references": [
    {
      "tag": "Juan",
      "label": {
        "es": "Cowboys de Medianoche - Episodio del 1 de enero de 2025",
        "en": "Cowboys de Medianoche - Episode from January 1, 2025"
      },
      "file": "cm250101",
      "time": 1234,
      "url": "/sttcast/static/mp3/cm250101.mp3#t=1234",
      "formatted_time": "20:34",
      "hyperlink": {
        "es": "/transcripts/cm250101_whisper_audio_es.html#id_1234",
        "en": "/transcripts/cm250101_whisper_audio_en.html#id_1234"
      }
    }
  ],
  "timestamp": "2025-12-07T10:30:00",
  "saved_query_url": "/savedquery/550e8400-e29b-41d4-a716-446655440000"
}
```

## Migración de Base de Datos

### Aplicar migración

```bash
cd rag/client/docker
./migrate-db.sh
```

O manualmente:

```bash
docker exec -i sttcast-postgres psql -U cowboys_user -d cowboys < migrations/add_response_data_column.sql
```

### Verificar migración

```bash
docker exec sttcast-postgres psql -U cowboys_user -d cowboys -c "\d rag_queries"
```

Debes ver la columna `response_data | jsonb`.

## Uso en JavaScript

### Cargar consulta guardada automáticamente

Cuando se accede a `/savedquery/{uuid}`, el template Jinja2 inyecta:

```html
<script>
    window.savedQueryData = {
        "query": "...",
        "response": {"es": "...", "en": "..."},
        "references": [...],
        "timestamp": "...",
        "uuid": "...",
        "saved_query_url": "..."
    };
</script>
```

El código JavaScript en `client_rag.js` detecta `window.savedQueryData` y:

1. Oculta la selección de tipo de consulta
2. Muestra el formulario de temas
3. Rellena el campo de pregunta
4. Llama a `showResults()` para mostrar la respuesta
5. Hace scroll automático a los resultados

### Mostrar consulta guardada manualmente

```javascript
// Desde cualquier lugar del código
if (window.savedQueryData) {
    const lang = languageSelect.value; // 'es' o 'en'
    showResults(window.savedQueryData, lang);
}
```

## Flujo de Trabajo Completo

### 1. Usuario hace una consulta nueva

```
1. Usuario escribe pregunta en /
2. JavaScript POST → /api/ask
3. Backend:
   - Obtiene embedding de la pregunta
   - Busca contexto relevante
   - Genera respuesta con RAG
   - Guarda todo en BD con UUID
4. Retorna respuesta + saved_query_url
5. JavaScript muestra resultado
6. Usuario puede copiar saved_query_url para compartir
```

### 2. Usuario accede a URL compartida

```
1. Usuario abre /savedquery/550e8400-...
2. Backend:
   - Consulta BD por UUID
   - Parsea response_data JSONB
   - Renderiza template con saved_query inyectado
3. Browser carga página
4. JavaScript detecta window.savedQueryData
5. Muestra pregunta y respuesta automáticamente
6. Usuario puede hacer nuevas consultas desde ahí
```

## Compatibilidad hacia atrás

El código soporta **dos formatos**:

### Formato antiguo (solo `response_text`)
```sql
response_text = "Los contertulios discutieron..."
response_data = NULL
```

Se convierte automáticamente a:
```json
{
  "response": {"es": "...", "en": "..."},
  "references": []
}
```

### Formato nuevo (con `response_data`)
```sql
response_data = '{"response": {"es": "...", "en": "..."}, "references": [...]}'
```

Se usa directamente.

## Sistema de Caché Semántico (Futuro)

La columna `query_embedding` permite implementar:

```python
# Buscar queries similares antes de llamar al modelo
similar_queries = await db.search_similar_queries(
    query_embedding=current_embedding,
    similarity_threshold=0.95,  # Muy similar (95%)
    limit=1
)

if similar_queries:
    # Mostrar respuesta guardada con opción de re-procesar
    return {
        "cached": True,
        "response": similar_queries[0]['response_data'],
        "original_query": similar_queries[0]['query_text'],
        "similarity": similar_queries[0]['similarity']
    }
else:
    # Generar nueva respuesta
    ...
```

Interfaz propuesta:
```
┌─────────────────────────────────────────────────────┐
│ 💡 Encontramos una pregunta muy similar:            │
│                                                      │
│ "¿De qué hablaron de IA?"                           │
│ (Similitud: 96%)                                    │
│                                                      │
│ [Usar respuesta guardada] [Generar nueva respuesta] │
└─────────────────────────────────────────────────────┘
```

## Testing

### Probar guardado de consulta

```bash
curl -X POST http://localhost:8322/sttcast/api/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "¿De qué hablaron?", "language": "es"}'
```

Copiar el `saved_query_url` de la respuesta.

### Probar endpoint HTML

```bash
# Abrir en navegador
firefox "http://localhost:8322/sttcast/savedquery/{uuid}"
```

### Probar endpoint JSON

```bash
curl http://localhost:8322/sttcast/api/savedquery/{uuid}
```

## Seguridad

- ✅ UUIDs v4 (aleatorios, no adivinables)
- ✅ Validación de UUID en endpoints
- ✅ Escape de HTML en templates Jinja2
- ✅ JSONB previene inyección SQL
- ⚠️  TODO: Rate limiting para evitar scraping masivo
- ⚠️  TODO: Campo `allowed` para moderar contenido público

## Logs

El sistema registra:

```python
# Al guardar
logger.debug(f"💾 Query guardada con ID: {id}, UUID: {uuid}")

# Al recuperar
logger.info(f"Consulta recuperada: UUID={uuid}, Query='{text[:50]}...'")
logger.info(f"Renderizando consulta guardada: UUID={uuid}")
```

## Mantenimiento

### Limpiar consultas antiguas

```sql
-- Borrar consultas de más de 1 año
DELETE FROM rag_queries 
WHERE created_at < NOW() - INTERVAL '1 year';
```

### Ver estadísticas

```sql
-- Total de consultas guardadas
SELECT COUNT(*) FROM rag_queries;

-- Por podcast
SELECT podcast_name, COUNT(*) 
FROM rag_queries 
GROUP BY podcast_name;

-- Consultas más recientes
SELECT query_text, created_at 
FROM rag_queries 
ORDER BY created_at DESC 
LIMIT 10;
```

## Troubleshooting

### Error: "No se encontró ninguna consulta con UUID"

- Verificar que el UUID existe en la BD
- Verificar formato del UUID (36 caracteres con guiones)

### Error: "Base de datos no disponible"

- Verificar que Docker containers están corriendo: `docker ps`
- Verificar conexión: `docker exec sttcast-postgres psql -U cowboys_user -d cowboys -c "SELECT 1"`

### JavaScript no carga la consulta guardada

- Abrir DevTools Console (F12)
- Verificar que existe `window.savedQueryData`
- Verificar que no hay errores de sintaxis JSON

### Referencias no se muestran

- Verificar que `response_data` contiene el array `references`
- Verificar que `showResults()` recibe el idioma correcto
