# Sistema Híbrido de Almacenamiento de Transcripciones

## Descripción

El cliente RAG ahora soporta un sistema híbrido de almacenamiento de transcripciones que permite:

1. **Almacenamiento local** (filesystem)
2. **Almacenamiento externo** (S3 u otro storage remoto)
3. **Fallback automático** entre ambas fuentes

## Cómo Funciona

### Estrategia de Obtención de Archivos

Cuando se solicita un archivo de transcripción (`/transcripts/archivo.html`), el sistema:

1. **Si TRANSCRIPTS_URL_EXTERNAL está configurada:**
   - Intenta obtener el archivo de la URL externa (S3, etc.)
   - Si está disponible (HTTP 200), lo devuelve
   - Si no existe en S3 (HTTP 404) o hay error, continúa

2. **Fallback a almacenamiento local:**
   - Si existe RAG_MP3_DIR y el archivo está disponible localmente, lo devuelve
   - Incluye validación de seguridad contra path traversal

3. **Si no existe en ningún lugar:**
   - Devuelve HTTP 404

### Ventajas

- ✅ Punto de montaje único `/transcripts` para el cliente
- ✅ Descarga directa de S3 (sin pasar por proxy si está disponible)
- ✅ Fallback automático a archivos locales
- ✅ Sistema de caché HTTP (24 horas)
- ✅ Sin cambios en las URLs del cliente
- ✅ Compatible con derechos de autor (mp3 locales no se sirven, solo en S3)

## Configuración

### Variables de Entorno

Añade a tu archivo `.env`:

```ini
# URL base del bucket S3
TRANSCRIPTS_URL_EXTERNAL=https://listlead-jmrobles.s3.eu-south-2.amazonaws.com

# Ruta local de fallback (ya existente)
RAG_MP3_DIR=/ruta/a/transcripts/local
```

### Casos de Uso

#### Caso 1: Solo S3 (recomendado para Listening Leaders)

```ini
TRANSCRIPTS_URL_EXTERNAL=https://listlead-jmrobles.s3.eu-south-2.amazonaws.com
RAG_MP3_DIR=/app/transcripts  # O no configurar si no lo tienes local
```

**Resultado**: Todos los archivos se obtienen de S3

#### Caso 2: Solo almacenamiento local (por defecto)

```ini
# TRANSCRIPTS_URL_EXTERNAL no configurada o vacía
RAG_MP3_DIR=/ruta/a/transcripts
```

**Resultado**: Todos los archivos se obtienen del filesystem local

#### Caso 3: Híbrido (S3 principal, local como fallback)

```ini
TRANSCRIPTS_URL_EXTERNAL=https://listlead-jmrobles.s3.eu-south-2.amazonaws.com
RAG_MP3_DIR=/ruta/local
```

**Resultado**: 
- Si existe en S3 → se obtiene de S3
- Si no existe en S3 pero existe localmente → se obtiene del filesystem
- Si no existe en ninguno → 404

## URLs en el Navegador

El cliente **nunca verá URLs complejas de S3**. Las URLs siempre son:

```
http://tu-servidor:puerto/transcripts/archivo.html
```

El proxy interno maneja la redirección transparente.

## Rendimiento

- **S3**: Muy rápido, descarga directa del bucket (si está público)
- **Caché HTTP**: 24 horas en el navegador del cliente
- **Timeout**: 10 segundos por archivo
- **Sin bloqueos**: Los timeouts de S3 no rompen la aplicación, fallback a local

## Logs de Depuración

Busca estos mensajes en los logs para entender qué está pasando:

```
# Configuración inicial
Transcripts: External URL configured: https://...
Transcripts: Local directory available at /path/to/dir

# Durante las peticiones
Intentando obtener desde S3: archivo.html
Archivo obtenido desde S3: archivo.html
Archivo obtenido desde filesystem local: archivo.html
Archivo no encontrado en ninguna fuente: archivo.html
```

## Seguridad

✅ **Validación de path traversal**: No permite `../` en rutas de archivos
✅ **HTTPS recomendado**: Para URLs de S3 públicas
✅ **Sin exposición de rutas internas**: El cliente nunca ve rutas de filesystem

## Compatibilidad

Esta implementación es **totalmente compatible** con:
- El middleware `AudioFallbackMiddleware` (para permitir mp3 locales)
- Las funciones `get_transcript_url()` y `build_file_url()` existentes
- Todas las referencias existentes en el código

No es necesario cambiar nada en el frontend o en otras partes de la aplicación.

## Ejemplo: Docker con S3

```dockerfile
ENV TRANSCRIPTS_URL_EXTERNAL=https://listlead-jmrobles.s3.eu-south-2.amazonaws.com
ENV RAG_MP3_DIR=/app/transcripts
```

Si no montas un volumen en `/app/transcripts`, no hay problema: el sistema simplemente obtiene todo de S3.

## Ejemplo: Docker con almacenamiento local

```dockerfile
ENV RAG_MP3_DIR=/app/transcripts
# No configurar TRANSCRIPTS_URL_EXTERNAL

# Montar el volumen:
# docker run -v /ruta/transcripts:/app/transcripts ...
```

## Troubleshooting

### No se encuentra un archivo

1. Verifica que está en S3 (si está configurado)
2. Verifica que está en el directorio local (si está configurado)
3. Revisa los logs para ver dónde intenta buscar

### Los archivos se cargan lentamente

1. Si es S3: Verifica la latencia de red hacia el bucket
2. Si es local: Verifica el I/O del disco

### Error 404 frecuentes

1. Asegúrate que la ruta en S3 es correcta
2. Verifica que RAG_MP3_DIR contiene los archivos esperados

---

**Última actualización**: 2026-01-04
**Versión**: 1.0
