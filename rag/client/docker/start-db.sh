#!/bin/bash
# Script para arrancar la base de datos PostgreSQL con pgvector
# Este script debe ejecutarse desde el directorio rag/client/docker

set -e

# Colores para output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}==================================================${NC}"
echo -e "${GREEN}  Iniciando PostgreSQL con pgvector para Sttcast${NC}"
echo -e "${GREEN}==================================================${NC}"
echo ""

# Verificar que estamos en el directorio correcto
if [ ! -f "docker-compose-db.yml" ]; then
    echo -e "${RED}Error: Este script debe ejecutarse desde rag/client/docker${NC}"
    exit 1
fi

# Verificar que existe el archivo de configuración
if [ ! -f ".env/queriesdb.env" ]; then
    echo -e "${RED}Error: No se encuentra .env/queriesdb.env${NC}"
    echo -e "${YELLOW}Por favor, configura el archivo .env/queriesdb.env primero${NC}"
    exit 1
fi

# Cargar variables de entorno
set -a
source .env/queriesdb.env
set +a

echo -e "${YELLOW}Configuración:${NC}"
echo "  Host: ${QUERIESDB_HOST}"
echo "  Port: ${QUERIESDB_PORT}"
echo "  Admin User: ${QUERIESDB_ADMIN_USER}"
echo ""

# Arrancar el contenedor
echo -e "${GREEN}Arrancando contenedor PostgreSQL...${NC}"
docker-compose -f docker-compose-db.yml --env-file .env/queriesdb.env up -d

# Esperar a que el servicio esté listo
echo -e "${YELLOW}Esperando a que PostgreSQL esté listo...${NC}"
sleep 5

# Verificar estado
if docker-compose -f docker-compose-db.yml ps | grep -q "Up"; then
    echo ""
    echo -e "${GREEN}==================================================${NC}"
    echo -e "${GREEN}  ✅ PostgreSQL y pgAdmin están listos${NC}"
    echo -e "${GREEN}==================================================${NC}"
    echo ""
    echo -e "${YELLOW}📊 PostgreSQL:${NC}"
    echo "  Host: ${QUERIESDB_HOST}"
    echo "  Port: ${QUERIESDB_PORT}"
    echo "  Admin User: ${QUERIESDB_ADMIN_USER}"
    echo ""
    echo -e "${YELLOW}🌐 pgAdmin (Interfaz Web):${NC}"
    echo "  URL: http://localhost:${PGADMIN_PORT:-5050}"
    echo "  Email: ${PGADMIN_EMAIL}"
    echo "  Password: ${PGADMIN_PASSWORD}"
    echo ""
    echo -e "${YELLOW}📖 Instrucciones completas en:${NC}"
    echo "  rag/client/docker/PGADMIN_ACCESS.md"
    echo ""
    echo -e "${YELLOW}Para ver logs:${NC}"
    echo "  docker-compose -f docker-compose-db.yml logs -f"
    echo ""
    echo -e "${YELLOW}Para detener:${NC}"
    echo "  docker-compose -f docker-compose-db.yml down"
    echo ""
else
    echo -e "${RED}Error: Los contenedores no se iniciaron correctamente${NC}"
    echo -e "${YELLOW}Revisa los logs con:${NC}"
    echo "  docker-compose -f docker-compose-db.yml logs"
    exit 1
fi
