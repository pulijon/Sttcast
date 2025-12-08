# Guía de Prueba - Sistema de Consultas Guardadas

## ✅ Implementación Completada

Se ha implementado exitosamente el sistema de consultas guardadas con UUID que permite:

1. **Guardar automáticamente** todas las consultas en PostgreSQL
2. **Compartir URLs** de respuestas específicas
3. **Renderizar en HTML** usando la interfaz existente
4. **Base para caché semántico** futuro

## 🎯 Próximos Pasos para Probar

### 1. Iniciar el Sistema

```bash
# Terminal 1: Base de datos (si no está corriendo)
cd "/home/jmrobles/Podcasts/Cowboys de Medianoche/Sttcast/rag/client/docker"
./start-db.sh

# Terminal 2: Cliente RAG
cd "/home/jmrobles/Podcasts/Cowboys de Medianoche/Sttcast"
source .venv/bin/activate
python rag/client/client_rag.py
```

**Verifica que inicia correctamente**:
```
✅ Conectado a PostgreSQL (pool: 2-10 conexiones)
✅ Tabla rag_queries verificada/creada
✅ Índices verificados/creados
INFO:     Uvicorn running on http://0.0.0.0:8322
```

### 2. Hacer una Consulta Nueva

```bash
# Abrir en navegador
firefox http://localhost:8322/sttcast/
```

1. Seleccionar "Consultas sobre temas tratados"
2. Escribir pregunta: **"¿De qué hablaron sobre inteligencia artificial?"**
3. Click "Consultar"
4. Esperar respuesta

**Verificar**:
- ✅ Se muestra la respuesta
- ✅ Se muestran referencias con audio
- ✅ En la consola del navegador (F12) NO debe haber errores JavaScript

### 3. Verificar Guardado en BD

```bash
# Ver última consulta guardada
docker exec sttcast-postgres psql -U cowboys_user -d cowboys -c "
SELECT 
    uuid,
    query_text,
    response_data IS NOT NULL as has_full_response,
    created_at
FROM rag_queries 
ORDER BY created_at DESC 
LIMIT 1;
"
```

**Deberías ver**:
```
                 uuid                 |          query_text          | has_full_response |         created_at
--------------------------------------+------------------------------+-------------------+----------------------------
 550e8400-e29b-41d4-a716-446655440000 | ¿De qué hablaron sobre int... | t                 | 2025-12-07 10:30:00.123456
```

### 4. Obtener URL Compartible

**Opción A: Desde la respuesta de la API** (si modificaste el frontend para mostrarla):

La respuesta JSON de `/api/ask` incluye:
```json
{
  "saved_query_url": "/savedquery/550e8400-e29b-41d4-a716-446655440000"
}
```

**Opción B: Desde la base de datos**:

```bash
UUID=$(docker exec sttcast-postgres psql -U cowboys_user -d cowboys -t -c "
SELECT uuid FROM rag_queries ORDER BY created_at DESC LIMIT 1;
" | xargs)

echo "URL completa: http://localhost:8322/sttcast/savedquery/$UUID"
```

### 5. Probar Endpoint HTML (Vista Usuario)

```bash
# Copiar la URL del paso anterior y abrir en navegador
firefox "http://localhost:8322/sttcast/savedquery/$UUID"
```

**Verificar**:
- ✅ Se muestra la interfaz completa (igual que la página principal)
- ✅ El campo de pregunta está **pre-rellenado** con la consulta guardada
- ✅ La respuesta se muestra automáticamente
- ✅ Las referencias aparecen en la tabla
- ✅ Puedes hacer **nuevas consultas** desde ahí

**En DevTools (F12 → Console)**:
```javascript
// Verificar que se cargó correctamente
console.log(window.savedQueryData);
```

Deberías ver:
```javascript
{
  query: "¿De qué hablaron sobre inteligencia artificial?",
  response: {
    es: "Los contertulios discutieron...",
    en: "The speakers discussed..."
  },
  references: [...],
  timestamp: "2025-12-07T10:30:00",
  uuid: "550e8400-...",
  saved_query_url: "/savedquery/550e8400-..."
}
```

### 6. Probar Endpoint JSON (API)

```bash
curl -s "http://localhost:8322/sttcast/api/savedquery/$UUID" | jq .
```

**Deberías ver**:
```json
{
  "success": true,
  "response": {
    "es": "Los contertulios discutieron sobre los avances en inteligencia artificial...",
    "en": "The speakers discussed advances in artificial intelligence..."
  },
  "references": [
    {
      "tag": "Juan",
      "label": {
        "es": "Cowboys de Medianoche - Episodio del 1 de enero de 2025",
        "en": "..."
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
  "query": "¿De qué hablaron sobre inteligencia artificial?",
  "podcast_name": "Cowboys de Medianoche",
  "uuid": "550e8400-e29b-41d4-a716-446655440000",
  "saved_query_url": "/api/savedquery/550e8400-e29b-41d4-a716-446655440000"
}
```

### 7. Verificar Compatibilidad con Idiomas

```bash
# Abrir URL guardada
firefox "http://localhost:8322/sttcast/savedquery/$UUID"

# En la interfaz:
# 1. Cambiar idioma de "Español" a "English"
# 2. La respuesta debería cambiar al inglés
```

### 8. Probar Múltiples Consultas

```bash
# Hacer 3 consultas diferentes
# 1. ¿De qué hablaron sobre tecnología?
# 2. ¿Qué dijeron sobre videojuegos?
# 3. ¿Cuál fue el tema principal del último episodio?

# Ver todas las consultas guardadas
docker exec sttcast-postgres psql -U cowboys_user -d cowboys -c "
SELECT 
    LEFT(query_text, 50) as query,
    LEFT(uuid::text, 8) || '...' as uuid,
    created_at
FROM rag_queries 
ORDER BY created_at DESC 
LIMIT 5;
"
```

### 9. Compartir URL con Otra Persona

1. Copia una URL de consulta guardada
2. Compártela (email, WhatsApp, etc.)
3. La otra persona puede:
   - Ver la pregunta original
   - Ver la respuesta exacta que recibiste
   - Ver las mismas referencias
   - Hacer nuevas preguntas desde ahí

**Esto es ideal para**:
- Documentación interna
- Compartir hallazgos en redes sociales
- Referencias en artículos
- FAQ con respuestas específicas

## 🐛 Troubleshooting

### Error: "Base de datos no disponible"

```bash
# Verificar que Docker está corriendo
docker ps | grep sttcast-postgres

# Si no está corriendo
cd rag/client/docker
./start-db.sh
```

### Error: No se guarda la consulta

```bash
# Verificar logs del cliente
# Buscar línea: "💾 Query guardada con ID: X, UUID: Y"

# Si no aparece, verificar configuración
echo $QUERIESDB_AVAILABLE  # Debe ser "true"
```

### Error: La página no muestra la consulta guardada

```bash
# Abrir DevTools (F12) en el navegador
# Console tab

# Verificar
console.log(window.savedQueryData);

# Si es undefined, revisar que:
# 1. El UUID es correcto
# 2. La consulta existe en BD
# 3. No hay errores en la consola
```

### Error 404: No se encuentra la consulta

```bash
# Verificar que el UUID existe
docker exec sttcast-postgres psql -U cowboys_user -d cowboys -c "
SELECT COUNT(*) FROM rag_queries WHERE uuid = '550e8400-e29b-41d4-a716-446655440000';
"

# Debe retornar 1
```

### Referencias no se muestran

Posibles causas:
1. `response_data` no contiene el array `references`
2. Frontend esperando formato diferente
3. JavaScript no está parseando correctamente

```bash
# Verificar estructura de response_data
docker exec sttcast-postgres psql -U cowboys_user -d cowboys -c "
SELECT 
    query_text,
    jsonb_pretty(response_data)
FROM rag_queries 
ORDER BY created_at DESC 
LIMIT 1;
"
```

## 📊 Métricas de Éxito

Al completar las pruebas, deberías poder confirmar:

- ✅ Consultas se guardan automáticamente en BD
- ✅ Cada consulta tiene UUID único
- ✅ `/savedquery/{uuid}` muestra interfaz completa
- ✅ `/api/savedquery/{uuid}` retorna JSON correcto
- ✅ Referencias incluyen hipervínculos funcionales
- ✅ Ambos idiomas (ES/EN) funcionan
- ✅ Puedes compartir URLs y otras personas las ven igual
- ✅ Puedes hacer nuevas consultas desde una URL guardada

## 🎉 Casos de Uso Reales

### 1. FAQ Dinámica
```markdown
# Preguntas Frecuentes

**P: ¿De qué hablaron sobre IA en 2025?**
R: [Ver respuesta completa](http://localhost:8322/sttcast/savedquery/550e8400-...)

**P: ¿Cuáles son los mejores juegos mencionados?**
R: [Ver respuesta completa](http://localhost:8322/sttcast/savedquery/660f9511-...)
```

### 2. Documentación Interna
```
Reunión del 7/12/2025 - Temas discutidos:
- Tendencias en IA: http://localhost:8322/sttcast/savedquery/550e8400-...
- Nuevos videojuegos: http://localhost:8322/sttcast/savedquery/660f9511-...
```

### 3. Redes Sociales
```
🎙️ Descubre qué dijeron los Cowboys sobre inteligencia artificial:
http://localhost:8322/sttcast/savedquery/550e8400-...

#Cowboys #IA #Podcast
```

### 4. Email/Newsletter
```
Esta semana los Cowboys hablaron sobre:

🤖 Inteligencia Artificial
   → http://localhost:8322/sttcast/savedquery/550e8400-...

🎮 Nuevos Videojuegos
   → http://localhost:8322/sttcast/savedquery/660f9511-...
```

## 📈 Siguientes Pasos (Futuro)

### Fase 1: Mejoras UX
- [ ] Botón "Compartir" visible en resultados
- [ ] Copiar URL al portapapeles
- [ ] QR code para móviles
- [ ] Preview en redes sociales (Open Graph tags)

### Fase 2: Caché Semántico
- [ ] Implementar `search_similar_queries()`
- [ ] UI: "¿Quieres la respuesta rápida o nueva búsqueda?"
- [ ] Métricas de hit rate
- [ ] Ahorro de tokens/costos

### Fase 3: Social
- [ ] Likes/Dislikes funcionales
- [ ] Consultas más populares
- [ ] Trending topics
- [ ] Moderación (`allowed` flag)

### Fase 4: Analytics
- [ ] Dashboard de estadísticas
- [ ] Gráficos de uso
- [ ] Temas más buscados
- [ ] Mejores horarios

---

**Estado**: ✅ Listo para testing  
**Última actualización**: 2025-12-07  
**Autor**: José Miguel Robles Román
