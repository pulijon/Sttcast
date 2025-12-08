#!/bin/bash
# Script para detener la base de datos PostgreSQL
# Este script debe ejecutarse desde el directorio rag/client/docker

set -e

# Colores para output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${YELLOW}==================================================${NC}"
echo -e "${YELLOW}  Deteniendo PostgreSQL${NC}"
echo -e "${YELLOW}==================================================${NC}"
echo ""

# Verificar que estamos en el directorio correcto
if [ ! -f "docker-compose-db.yml" ]; then
    echo -e "${RED}Error: Este script debe ejecutarse desde rag/client/docker${NC}"
    exit 1
fi

# Detener el contenedor
docker-compose -f docker-compose-db.yml down

echo ""
echo -e "${GREEN}✅ PostgreSQL detenido correctamente${NC}"
echo ""
echo -e "${YELLOW}Nota: Los datos persisten en el volumen Docker.${NC}"
echo -e "${YELLOW}Para eliminar también los datos:${NC}"
echo "  docker-compose -f docker-compose-db.yml down -v"
echo ""
