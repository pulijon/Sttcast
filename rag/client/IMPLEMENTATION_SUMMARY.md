# Resumen de Implementación: Sistema de Consultas Guardadas

## ✅ Cambios Implementados

### 1. Base de Datos (queriesdb.py)

#### Tabla `rag_queries` actualizada:
- ✅ **Nueva columna**: `response_data JSONB` para almacenar respuesta completa
- ✅ **Índice GIN**: Para búsquedas eficientes en JSONB
- ✅ Mantiene backward compatibility con `response_text`

#### Método `save_query()` actualizado:
```python
async def save_query(
    query_text: str,
    response_text: str,  # Backward compatibility
    response_data: Optional[Dict] = None,  # NUEVO: respuesta completa
    query_embedding: Optional[List[float]] = None,
    podcast_name: Optional[str] = None
) -> Optional[Dict[str, Any]]
```

**Guarda**:
- Pregunta original
- Respuesta en ambos idiomas `{es: ..., en: ...}`
- Referencias completas con hipervínculos
- Timestamp
- Embedding para búsqueda semántica futura

### 2. Backend (client_rag.py)

#### Endpoint `/api/ask` modificado:
```python
# Ahora guarda respuesta completa
response_data_to_save = {
    "response": reldata["search"],  # {es: ..., en: ...}
    "references": references,       # Array con hipervínculos
    "timestamp": timestamp_iso,
    "query": question
}

await app.db.save_query(
    query_text=question,
    response_text=reldata["search"].get("es", ""),
    response_data=response_data_to_save,  # ← NUEVO
    query_embedding=query_embedding,
    podcast_name=app.podcast_name
)
```

**Retorna**:
```json
{
  "success": true,
  "response": {"es": "...", "en": "..."},
  "references": [...],
  "timestamp": "2025-12-07T10:30:00",
  "saved_query_url": "/savedquery/550e8400-e29b-41d4-a716-446655440000"
}
```

#### ✨ Nuevo endpoint `/api/savedquery/{uuid}` (JSON):
```python
@app.get("/api/savedquery/{query_uuid}")
async def get_saved_query(query_uuid: str, request: Request):
    """Retorna consulta guardada en formato JSON"""
```

**Para**: APIs externas, curl, Postman, scripts

#### ✨ Nuevo endpoint `/savedquery/{uuid}` (HTML):
```python
@app.get("/savedquery/{query_uuid}")
async def get_saved_query_html(query_uuid: str, request: Request):
    """Renderiza consulta guardada en interfaz web completa"""
```

**Para**: Compartir URLs con usuarios, navegadores

**Características**:
- Renderiza usando el template existente `index.html`
- Inyecta `window.savedQueryData` para JavaScript
- Compatible con accesibilidad, cookies, contraste, etc.
- Permite hacer nuevas consultas desde la misma página

### 3. Frontend (index.html)

#### Template actualizado:
```html
<script>
    {% if saved_query %}
    window.savedQueryData = {{ saved_query|safe }};
    {% endif %}
    
    {% if error %}
    window.serverError = "{{ error }}";
    {% endif %}
</script>
```

### 4. JavaScript (client_rag.js)

#### Detección automática de consulta guardada:
```javascript
if (window.savedQueryData) {
    console.log('[SAVED QUERY] Detectada consulta guardada, cargando...');
    
    // Mostrar formulario de temas
    queryTypeSelection.classList.add('hidden');
    topicsForm.classList.remove('hidden');
    
    // Rellenar pregunta
    questionInput.value = window.savedQueryData.query;
    
    // Mostrar resultados
    showResults(window.savedQueryData, lang);
    
    // Scroll automático
    resultsSection.scrollIntoView({ behavior: 'smooth' });
}
```

**No requiere cambios en `showResults()`**: Ya funciona con el formato correcto.

### 5. Migración de Base de Datos

#### Script SQL: `migrations/add_response_data_column.sql`
```sql
ALTER TABLE rag_queries ADD COLUMN response_data JSONB;
CREATE INDEX idx_rag_queries_response_data ON rag_queries USING GIN (response_data);
```

#### Script Bash: `migrate-db.sh`
```bash
#!/bin/bash
docker exec -i sttcast-postgres psql -U cowboys_user -d cowboys < migrations/add_response_data_column.sql
```

**Estado**: ✅ Migración aplicada exitosamente

### 6. Documentación

#### Archivo creado: `SAVED_QUERIES_README.md`
Contiene:
- Arquitectura del sistema
- Descripción de endpoints
- Estructura de base de datos
- Formato de `response_data` JSONB
- Flujo de trabajo completo
- Testing y troubleshooting
- Plan para sistema de caché semántico futuro

## 🎯 Flujo de Usuario

### Escenario 1: Consulta Nueva
```
1. Usuario visita /
2. Escribe pregunta: "¿De qué hablaron de IA?"
3. Click en "Consultar"
4. Sistema:
   - Genera respuesta con RAG
   - Guarda en BD con UUID
   - Retorna respuesta + URL
5. Usuario ve:
   - Respuesta formateada
   - Referencias con audio
   - URL para compartir: /savedquery/550e8400-...
```

### Escenario 2: URL Compartida
```
1. Usuario recibe URL: /savedquery/550e8400-...
2. Abre en navegador
3. Sistema:
   - Busca en BD por UUID
   - Renderiza index.html con saved_query inyectado
4. JavaScript detecta window.savedQueryData
5. Usuario ve:
   - Pregunta original en input
   - Respuesta formateada (IDÉNTICA a consulta nueva)
   - Referencias con audio
   - Puede hacer nuevas consultas
```

### Escenario 3: API Externa
```bash
curl http://localhost:8322/sttcast/api/savedquery/550e8400-...
```

Retorna JSON puro para integración con otros sistemas.

## 🚀 Ventajas del Sistema

### 1. Compartir Conocimiento
- ✅ URLs permanentes para respuestas específicas
- ✅ Perfecto para redes sociales, emails, documentación

### 2. Caché Semántico (Futuro)
```python
# Buscar preguntas similares antes de llamar al modelo
similar = await db.search_similar_queries(
    query_embedding=current_embedding,
    similarity_threshold=0.95
)

if similar:
    return {
        "cached": True,
        "response": similar[0]['response_data'],
        "similarity": 0.96,
        "original_query": "¿De qué hablaron de IA?"
    }
```

**Interfaz propuesta**:
```
┌───────────────────────────────────────────┐
│ 💡 Pregunta similar encontrada (96%)      │
│ "¿De qué hablaron de IA?"                 │
│                                           │
│ [Respuesta rápida] [Nueva búsqueda]      │
└───────────────────────────────────────────┘
```

### 3. Analítica
- Consultas más frecuentes
- Temas más buscados
- Satisfacción de usuarios (likes/dislikes)

### 4. Moderación
- Campo `allowed` para filtrar contenido público
- Auditoría con `rag_queries_access_log`

## 🔧 Testing Realizado

### ✅ Migración aplicada
```
Columna response_data agregada exitosamente
Índice idx_rag_queries_response_data creado exitosamente
```

### ⏳ Pendiente de Testing
1. Iniciar `client_rag.py`
2. Hacer consulta nueva → Verificar que guarda con `response_data`
3. Copiar `saved_query_url`
4. Abrir en navegador → Verificar renderizado HTML
5. Probar `/api/savedquery/{uuid}` → Verificar JSON

## 📝 Comandos Útiles

### Iniciar servicios
```bash
cd rag/client/docker
./start-db.sh
cd ../..
source .venv/bin/activate
python rag/client/client_rag.py
```

### Verificar BD
```bash
docker exec sttcast-postgres psql -U cowboys_user -d cowboys -c "
SELECT uuid, query_text, response_data IS NOT NULL as has_full_response 
FROM rag_queries 
ORDER BY created_at DESC 
LIMIT 5;"
```

### Probar endpoint HTML
```bash
# Obtener UUID de última consulta
UUID=$(docker exec sttcast-postgres psql -U cowboys_user -d cowboys -t -c "
SELECT uuid FROM rag_queries ORDER BY created_at DESC LIMIT 1;
" | xargs)

echo "http://localhost:8322/sttcast/savedquery/$UUID"
```

### Probar endpoint JSON
```bash
curl "http://localhost:8322/sttcast/api/savedquery/$UUID" | jq .
```

## 🎨 Compatibilidad

### ✅ Con consultas antiguas (solo `response_text`)
El código detecta automáticamente y convierte:
```python
if query_data.get('response_data'):
    # Nuevo formato
    stored_response = json.loads(query_data['response_data'])
else:
    # Formato antiguo - convertir
    response_data = {
        "response": {"es": old_text, "en": old_text},
        "references": []
    }
```

### ✅ Con interfaz web existente
- No requiere cambios en `showResults()`
- Usa mismo formato de datos
- Mismo estilo CSS
- Mismas funciones de accesibilidad

## 🔮 Roadmap Futuro

### Fase 1: Validación (ACTUAL)
- ✅ Implementación básica
- ⏳ Testing con usuarios reales
- ⏳ Ajustes de UX

### Fase 2: Caché Semántico
- Implementar `search_similar_queries()`
- UI para elegir respuesta rápida vs nueva
- Métricas de hit rate

### Fase 3: Social Features
- Sistema de likes/dislikes funcional
- Moderación de contenido (`allowed` flag)
- Consultas más populares

### Fase 4: Analytics
- Dashboard de estadísticas
- Temas más buscados
- Horarios de mayor uso

## 📄 Archivos Modificados

```
rag/client/
├── queriesdb.py                    # ✏️ Modificado: save_query()
├── client_rag.py                   # ✏️ Modificado: /api/ask, nuevos endpoints
├── templates/index.html            # ✏️ Modificado: inyección saved_query
├── static/js/client_rag.js         # ✏️ Modificado: detección automática
├── docker/
│   ├── migrate-db.sh              # ✨ Nuevo
│   └── migrations/
│       └── add_response_data_column.sql  # ✨ Nuevo
└── SAVED_QUERIES_README.md        # ✨ Nuevo (esta documentación)
```

## 🎓 Aprendizajes

1. **JSONB es poderoso**: Permite almacenar estructuras complejas manteniendo queries SQL simples
2. **Índices GIN**: Esenciales para búsquedas eficientes en JSONB
3. **Backward compatibility**: Importante mantener `response_text` para datos antiguos
4. **Inyección de datos**: Template Jinja2 + JavaScript es patrón limpio para datos servidor→cliente
5. **UUIDs**: Mejor que IDs autoincrementales para URLs públicas

---

**Estado**: ✅ Implementación completa  
**Próximo paso**: Testing con consultas reales  
**Fecha**: 2025-12-07
