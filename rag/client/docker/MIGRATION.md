# Migración a PostgreSQL Multi-Cliente

## Resumen de Cambios

Se ha reorganizado la configuración de la base de datos PostgreSQL para soportar **múltiples clientes RAG** (podcasts) compartiendo un mismo servidor PostgreSQL, donde cada cliente tiene su propia base de datos y usuario aislado.

## Arquitectura

### Antes
- Un solo archivo de configuración con credenciales de un usuario específico
- Una sola base de datos para todos los clientes
- Sin creación automática de recursos

### Ahora
- Separación de credenciales: administrador (queriesdb.env) y cliente (rag_client.env)
- Cada cliente tiene su propia base de datos y usuario
- Creación automática de BD y usuarios
- Aislamiento completo de datos entre clientes

## Estructura de Configuración

### 1. queriesdb.env (rag/client/docker/.env/)
Configuración del servidor y **credenciales del administrador**:

```bash
QUERIESDB_AVAILABLE = true
QUERIESDB_HOST = localhost
QUERIESDB_PORT = 5432

# Usuario administrador (con privilegios para crear BDs y usuarios)
QUERIESDB_ADMIN_USER = postgres
QUERIESDB_ADMIN_PASSWORD = postgres_admin_password

# Parámetros del pool
QUERIESDB_POOL_MIN_SIZE = 2
QUERIESDB_POOL_MAX_SIZE = 10
QUERIESDB_QUERY_TIMEOUT = 30
```

### 2. rag_client.env (.env/)
Configuración **específica de cada cliente**:

```bash
# Base de datos específica para este podcast/cliente
QUERIESDB_DB = cowboys
QUERIESDB_USER = cowboys_user
QUERIESDB_PASSWORD = cowboys_password
```

## Uso

### Arrancar PostgreSQL

```bash
cd rag/client/docker
./start-db.sh
```

O manualmente:
```bash
docker-compose -f docker-compose-db.yml --env-file .env/queriesdb.env up -d
```

### Configurar un Nuevo Cliente

1. Editar `.env/rag_client.env` con las credenciales del cliente:
   ```bash
   QUERIESDB_DB = nombre_podcast
   QUERIESDB_USER = nombre_podcast_user
   QUERIESDB_PASSWORD = contraseña_segura
   ```

2. Arrancar el cliente RAG:
   ```bash
   python rag/client/client_rag.py
   ```

3. El módulo `queriesdb.py` automáticamente:
   - Creará la base de datos si no existe
   - Creará el usuario si no existe
   - Habilitará pgvector
   - Creará las tablas necesarias

### Detener PostgreSQL

```bash
cd rag/client/docker
./stop-db.sh
```

O manualmente:
```bash
docker-compose -f docker-compose-db.yml down
```

## Múltiples Clientes

Para tener varios podcasts en el mismo servidor:

1. **Cliente 1 (Cowboys de Medianoche)**:
   ```bash
   QUERIESDB_DB = cowboys
   QUERIESDB_USER = cowboys_user
   QUERIESDB_PASSWORD = cowboys_pass
   ```

2. **Cliente 2 (Coffee Break)**:
   ```bash
   QUERIESDB_DB = coffeebreak
   QUERIESDB_USER = coffeebreak_user
   QUERIESDB_PASSWORD = coffeebreak_pass
   ```

3. **Cliente 3 (Listening Leaders)**:
   ```bash
   QUERIESDB_DB = listening_leaders
   QUERIESDB_USER = listening_leaders_user
   QUERIESDB_PASSWORD = listening_leaders_pass
   ```

Cada cliente:
- Se ejecuta independientemente
- Tiene su propia base de datos aislada
- No puede ver datos de otros clientes
- Se crea automáticamente al primer arranque

## Cambios en el Código

### queriesdb.py

**Nuevas funcionalidades**:
- Carga credenciales de administrador y cliente
- Método `_ensure_database_and_user_exist()` para auto-creación
- Validación de nombres seguros (prevención de SQL injection)
- Soporte para `QUERIESDB_AVAILABLE` flag

**Variables de entorno utilizadas**:
- `QUERIESDB_ADMIN_USER`: Usuario administrador
- `QUERIESDB_ADMIN_PASSWORD`: Contraseña administrador
- `QUERIESDB_HOST`: Servidor PostgreSQL
- `QUERIESDB_PORT`: Puerto
- `QUERIESDB_DB`: Base de datos del cliente
- `QUERIESDB_USER`: Usuario del cliente
- `QUERIESDB_PASSWORD`: Contraseña del cliente
- `QUERIESDB_AVAILABLE`: Habilitar/deshabilitar BD

### docker-compose-db.yml

**Cambios**:
- Usuario administrador como usuario principal del contenedor
- Base de datos por defecto: `postgres`
- Variables de entorno actualizadas a `QUERIESDB_*`

### init-db.sql

**Simplificado**:
- Solo habilita pgvector en template1 y postgres
- Las tablas se crean dinámicamente por cada cliente
- Sin creación de usuarios/BDs estáticas

## Seguridad

⚠️ **Nota de Seguridad**: Esta arquitectura prioriza la facilidad de uso sobre la seguridad máxima. El usuario administrador está disponible para todos los clientes, lo cual:

- ✅ Permite auto-aprovisionamiento
- ✅ Simplifica la gestión
- ❌ Potencialmente permite que un cliente acceda a otros

**Para producción**, considera:
- Usar un usuario intermedio con solo `CREATEDB` y `CREATEROLE`
- Implementar autenticación/autorización adicional
- Limitar el acceso de red al contenedor PostgreSQL
- Rotar credenciales regularmente

## Verificación

Para verificar que todo funciona:

```bash
# 1. Arrancar PostgreSQL
cd rag/client/docker
./start-db.sh

# 2. Verificar que el contenedor está corriendo
docker ps | grep sttcast-postgres

# 3. Conectarse a PostgreSQL
docker exec -it sttcast-postgres psql -U postgres

# 4. Listar bases de datos
\l

# 5. Listar usuarios
\du

# 6. Conectarse a una BD específica
\c cowboys

# 7. Listar tablas
\dt
```

## Solución de Problemas

### Error: "Base de datos no encontrada"
- El módulo creará la BD automáticamente al primer arranque
- Verifica que `QUERIESDB_ADMIN_USER` y `QUERIESDB_ADMIN_PASSWORD` sean correctos

### Error: "Usuario ya existe"
- Es normal, el sistema reutiliza usuarios existentes
- Verifica que la contraseña en `rag_client.env` sea correcta

### Error: "asyncpg no instalado"
- Instala el paquete: `pip install asyncpg`

### Contenedor no arranca
- Verifica que el puerto 5432 no esté en uso
- Revisa los logs: `docker-compose -f docker-compose-db.yml logs`

## Migración desde la Configuración Anterior

Si tenías una configuración anterior con variables `POSTGRES_*`:

1. Las variables han sido renombradas a `QUERIESDB_*`
2. Se han separado en dos archivos (queriesdb.env y rag_client.env)
3. Los datos existentes se preservan en el volumen Docker
4. Actualiza tus scripts/configuraciones para usar los nuevos nombres
