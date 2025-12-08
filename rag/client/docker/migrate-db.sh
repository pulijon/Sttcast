#!/bin/bash

# Script para aplicar migración de base de datos
# Agrega columna response_data JSONB a la tabla rag_queries

set -e

echo "========================================"
echo "  Migración: Agregar response_data"
echo "========================================"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MIGRATION_FILE="$SCRIPT_DIR/migrations/add_response_data_column.sql"

if [ ! -f "$MIGRATION_FILE" ]; then
    echo "❌ Error: No se encuentra el archivo de migración: $MIGRATION_FILE"
    exit 1
fi

echo "📄 Archivo de migración: $MIGRATION_FILE"
echo ""
echo "Aplicando migración a la base de datos..."
echo ""

# Ejecutar migración en el contenedor Docker
docker exec -i sttcast-postgres psql -U cowboys_user -d cowboys < "$MIGRATION_FILE"

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Migración aplicada exitosamente"
    echo ""
    echo "Verificando estructura de la tabla..."
    docker exec sttcast-postgres psql -U cowboys_user -d cowboys -c "\d rag_queries"
else
    echo ""
    echo "❌ Error al aplicar la migración"
    exit 1
fi
