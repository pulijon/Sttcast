# Acceso a pgAdmin - Interfaz Web para PostgreSQL

## 🌐 URL de Acceso

**URL:** http://localhost:5050

## 🔐 Credenciales de Login

- **Email:** admin@sttcast.com
- **Contraseña:** admin

## 📊 Configurar Conexión al Servidor PostgreSQL

Una vez dentro de pgAdmin:

### 1. Agregar Nuevo Servidor

1. Click derecho en "Servers" → "Register" → "Server"
2. En la pestaña **General**:
   - **Name:** Sttcast PostgreSQL

3. En la pestaña **Connection**:
   - **Host name/address:** postgres
   - **Port:** 5432
   - **Maintenance database:** postgres
   - **Username:** postgres
   - **Password:** postgres_admin_password
   - ✅ Marcar "Save password"

4. Click en "Save"

### 2. Explorar Bases de Datos

Después de conectarte, podrás ver:

- **Bases de datos del sistema:**
  - `postgres` (BD por defecto)
  - `template0`, `template1` (plantillas)

- **Bases de datos de clientes:**
  - `cowboys` (si ya se ha ejecutado el cliente)
  - Otras BDs que se creen automáticamente

### 3. Ver Tablas de un Cliente

1. Expandir: Servers → Sttcast PostgreSQL → Databases → cowboys
2. Expandir: Schemas → public → Tables
3. Deberías ver:
   - `rag_queries` - Consultas y respuestas
   - `rag_queries_access_log` - Log de accesos

### 4. Ejecutar Queries SQL

1. Click derecho en la base de datos → "Query Tool"
2. Puedes ejecutar queries como:

```sql
-- Ver todas las consultas
SELECT * FROM rag_queries;

-- Ver consultas recientes
SELECT query_text, response_text, created_at 
FROM rag_queries 
ORDER BY created_at DESC 
LIMIT 10;

-- Contar consultas por podcast
SELECT podcast_name, COUNT(*) as total
FROM rag_queries
GROUP BY podcast_name;

-- Búsqueda por similitud (requiere embedding)
SELECT query_text, query_embedding <=> '[0.1, 0.2, ...]'::vector AS distance
FROM rag_queries
ORDER BY distance
LIMIT 5;
```

## 🛠️ Operaciones Útiles

### Ver Usuarios de PostgreSQL

```sql
SELECT usename, usecreatedb, usesuper 
FROM pg_user;
```

### Ver Todas las Bases de Datos

```sql
SELECT datname, pg_size_pretty(pg_database_size(datname)) AS size
FROM pg_database
ORDER BY datname;
```

### Ver Extensiones Habilitadas

```sql
SELECT * FROM pg_extension;
```

### Verificar pgvector

```sql
-- En cada base de datos cliente
SELECT extname, extversion 
FROM pg_extension 
WHERE extname = 'vector';
```

## 📝 Notas Importantes

1. **Conexión desde dentro del contenedor:** Use `postgres` como hostname (no `localhost`)
2. **Conexión desde el host:** Use `localhost` con puerto `5432`
3. **Los datos persisten** en volúmenes Docker incluso si detienes los contenedores
4. **Seguridad:** Estas credenciales son para desarrollo. En producción, cámbialas.

## 🔄 Gestión de Servicios

### Ver logs de pgAdmin
```bash
docker-compose -f docker-compose-db.yml logs -f pgadmin
```

### Ver logs de PostgreSQL
```bash
docker-compose -f docker-compose-db.yml logs -f postgres
```

### Reiniciar pgAdmin
```bash
docker-compose -f docker-compose-db.yml restart pgadmin
```

## 🚨 Solución de Problemas

### No puedo acceder a http://localhost:5050
- Verifica que el contenedor esté corriendo: `docker ps | grep pgadmin`
- Revisa los logs: `docker-compose -f docker-compose-db.yml logs pgadmin`
- Verifica que el puerto 5050 no esté en uso

### Error de conexión al servidor PostgreSQL
- Asegúrate de usar `postgres` como hostname (no `localhost`)
- Verifica las credenciales en `.env/queriesdb.env`
- Confirma que el contenedor de PostgreSQL esté corriendo

### Olvidé la contraseña
- Las credenciales están en `.env/queriesdb.env`
- Para resetear pgAdmin, elimina el volumen: `docker-compose down -v`
