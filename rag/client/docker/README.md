# Docker - Cliente RAG de Sttcast

Este directorio contiene los archivos necesarios para dockerizar la aplicación cliente RAG de Sttcast.

## Estructura

```
rag/client/docker/
├── Dockerfile           # Definición de la imagen Docker
├── docker-compose.yml   # Orquestación del contenedor
├── .dockerignore        # Archivos excluidos de la imagen
├── requirements.txt     # Dependencias Python específicas
└── README.md           # Esta documentación
```

## Prerequisitos

- Docker instalado (versión 20.10 o superior)
- Docker Compose instalado (versión 1.29 o superior)
- Directorio `.env` configurado en la raíz del proyecto (3 niveles arriba)
- Archivo `log.yml` en el directorio padre
- Paquete Sttcast instalado en modo desarrollo (opcional para desarrollo local):
  ```bash
  pip install -e .
  ```

## Arquitectura Modular

El proyecto ha sido reestructurado para una mejor modularidad:

- **`api/`**: Definiciones compartidas entre servicios
  - `apicontext.py` - Modelos Pydantic para context_server
  - `apihmac.py` - Funciones HMAC para autenticación segura
- **`tools/`**: Utilidades compartidas (logs, envvars)
- **`rag/`**: Servicios RAG (servidor y cliente)
- **`db/`**: Servicios de base de datos y contexto

El cliente RAG **solo** requiere:
- `rag/client/` - Código del cliente web (sin dependencias externas de rag)
- `tools/` - Utilidades de logging y variables de entorno
- `api/` - Modelos de API y funciones HMAC

**NO requiere**:
- ❌ `db/` - Servicios de base de datos
- ❌ `rag/sttcast_rag_service.py` - Servidor RAG
- ❌ Manipulación de `sys.path` - Usa PYTHONPATH

Esto reduce significativamente el tamaño de la imagen Docker y elimina dependencias innecesarias.

## Configuración

### Variables de Entorno

Las variables de entorno se cargan desde `../../../.env/rag_client.env`. Las principales son:

| Variable | Descripción | Default | Ejemplo |
|----------|-------------|---------|---------|
| `RAG_CLIENT_PORT` | Puerto expuesto en el host | 8322 | 8322 |
| `RAG_CLIENT_HOST` | Host donde escucha el contenedor | 0.0.0.0 | 0.0.0.0 |
| `RAG_MP3_DIR` | Ruta local con transcripciones/MP3s | - | `/home/user/Podcasts/MiPodcast` |
| `RAG_CLIENT_STT_LANG` | Idioma de la interfaz | es-ES | es-ES, en-US |
| `PODCAST_NAME` | Nombre del podcast | - | Cowboys de Medianoche |
| `CONTEXT_SERVER_URL` | URL del servidor de contexto | http://localhost:8321 | - |
| `RAG_SERVER_URL` | URL del servidor RAG | http://localhost:8320 | - |

**Nota importante**: El puerto en `docker-compose.yml` se configura automáticamente desde `RAG_CLIENT_PORT` si está definido en `rag_client.env`.

### Logging

El directorio de logs se monta como volumen en `./logs`. Los logs se persistirán fuera del contenedor y se configuran mediante el archivo `log.yml` del directorio padre.

## Uso

### Construcción de la Imagen

Desde el directorio `rag/client/docker`:

```bash
docker-compose build
```

### Ejecución del Contenedor

```bash
docker-compose up
```

Para ejecutar en modo background (detached):

```bash
docker-compose up -d
```

### Ver Logs

```bash
docker-compose logs -f
```

### Detener el Contenedor

```bash
docker-compose down
```

### Reiniciar el Contenedor

```bash
docker-compose restart
```

## Volúmenes Montados

El contenedor monta los siguientes volúmenes:

1. **Variables de entorno** (solo lectura):
   - Host: `../../../.env`
   - Contenedor: `/app/.env`

2. **Logs** (lectura/escritura):
   - Host: `./logs`
   - Contenedor: `/app/rag/client/logs`

3. **Configuración de logging** (solo lectura):
   - Host: `../log.yml`
   - Contenedor: `/app/rag/client/log.yml`

4. **Transcripciones/MP3s** (solo lectura):
   - Host: `${RAG_MP3_DIR}` (variable de entorno desde `rag_client.env`)
   - Contenedor: `/app/transcripts`
   - Nota: Se monta solo si `RAG_MP3_DIR` está definido

## Características

✅ **Configuración mediante variables de entorno** - El puerto y directorios se configuran desde `.env/rag_client.env`  
✅ **Detección automática de Docker** - La aplicación detecta si está en un contenedor y ajusta las rutas automáticamente  
✅ **Volúmenes compartidos** - Logs y transcripciones persistentes fuera del contenedor  
✅ **Restart automático** - Se reinicia automáticamente si falla  
✅ **Red compartida** - Comunicación con otros servicios dockerizados

## Puertos

El servicio expone el puerto `8322` para el cliente RAG web.

## Red

El contenedor se ejecuta en la red `sttcast-network`, lo que permite la comunicación con otros servicios de Sttcast si se dockerizan en el futuro.

## Troubleshooting

### El contenedor no arranca

1. Verifica que el directorio `.env` existe y contiene los archivos necesarios:
   ```bash
   ls -la ../../../.env
   ```

2. Verifica que el archivo `log.yml` existe:
   ```bash
   ls -la ../log.yml
   ```

3. Revisa los logs del contenedor:
   ```bash
   docker-compose logs
   ```

### Errores de permisos

Si hay problemas de permisos con los logs:

```bash
mkdir -p logs
chmod 777 logs
```

### Reconstruir desde cero

```bash
docker-compose down
docker-compose build --no-cache
docker-compose up
```

## Notas

- La aplicación se reiniciará automáticamente (`restart: unless-stopped`) si falla o si se reinicia el host
- Los archivos de entorno se montan como solo lectura por seguridad
- El directorio de logs es persistente y se mantiene entre reinicios del contenedor

## Acceso a Servicios Externos (Context Server, RAG Server)

### ⚠️ Situación Actual

Los valores en `.env/rag_client.env` son para **ejecución LOCAL en el HOST**:
- `CONTEXT_SERVER_HOST = localhost`
- `RAG_SERVER_URL = http://localhost:8320`

Cuando ejecutas el cliente RAG en Docker, **`localhost` NO es accesible** desde el contenedor.

### 🎯 Soluciones según tu caso

#### **CASO 1: context_server corre en el HOST** ✅ (Recomendado actualmente)

Si `context_server.py` está ejecutándose en tu máquina (no en Docker):

**Para Linux:**
Descomentar en `docker-compose.yml`:
```yaml
environment:
  - CONTEXT_SERVER_HOST=172.17.0.1  # IP de acceso a host desde Docker en Linux
```

**Para Mac/Windows:**
```yaml
environment:
  - CONTEXT_SERVER_HOST=host.docker.internal
```

#### **CASO 2: context_server corre en Docker (red compartida)**

Si dockerizas tanto el cliente como el servidor, usar una red compartida:

```yaml
services:
  rag-client:
    networks:
      - sttcast-network
    environment:
      - CONTEXT_SERVER_HOST=context-server  # Nombre del servicio
  
  context-server:
    networks:
      - sttcast-network
    # ... config ...

networks:
  sttcast-network:
    driver: bridge
```

#### **CASO 3: Mantener localhost** ❌ (NO funcionará en Docker)

Solo si ejecutas TODO en el host sin Docker. En Docker nunca funcionará.

### 📝 Configuración Recomendada

**Para tu situación actual** (contexto en host, client en Docker):

Editar `docker-compose.yml` y descomentar:
```yaml
# - CONTEXT_SERVER_HOST=172.17.0.1  # Para Linux
# O
# - CONTEXT_SERVER_HOST=host.docker.internal  # Para Mac/Windows
```

## Futuras Dockerizaciones

Este patrón se puede replicar para:
- `rag/sttcast_rag_service.py` → `rag/docker/`
- `db/context_server.py` → `db/docker/`

Cada servicio tendrá su propio directorio `docker/` con su configuración específica.
