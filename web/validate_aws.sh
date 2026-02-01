#!/bin/bash
# Script para validar credenciales de AWS

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="../.env/aws.env"

# Cambiar al directorio del script
cd "$SCRIPT_DIR"

echo "=========================================="
echo "Validando credenciales de AWS"
echo "=========================================="
echo ""

# Verificar que el archivo .env existe
if [ ! -f "$ENV_FILE" ]; then
    echo "❌ Error: No se encontró $ENV_FILE"
    exit 1
fi

# Cargar variables
export $(cat "$ENV_FILE" | grep -v '^#' | xargs)

# Verificar variables obligatorias
if [ -z "$AWS_ACCESS_KEY_ID" ]; then
    echo "❌ Error: AWS_ACCESS_KEY_ID no está definido"
    exit 1
fi

if [ -z "$AWS_SECRET_ACCESS_KEY" ]; then
    echo "❌ Error: AWS_SECRET_ACCESS_KEY no está definido"
    exit 1
fi

if [ -z "$AWS_REGION" ]; then
    echo "⚠️  AWS_REGION no definido, usando default"
    export AWS_REGION="eu-south-2"
fi

echo "✓ Variables cargadas desde $ENV_FILE"
echo ""

# Intentar listar buckets S3
echo "1️⃣  Probando conexión a AWS..."
if command -v aws &> /dev/null; then
    echo "   Listando buckets S3..."
    if aws s3 ls --region "$AWS_REGION" 2>/dev/null; then
        echo "   ✓ Conexión a AWS exitosa"
    else
        echo "   ❌ No se pudo conectar a AWS"
        echo "   Verifica que las credenciales son correctas"
        exit 1
    fi
else
    echo "   ⚠️  AWS CLI no instalada"
    echo "   No se puede validar las credenciales sin AWS CLI"
    echo "   Instala con: pip install awscli"
fi

echo ""
echo "✓ Validación completada"
echo ""
echo "Resumen de credenciales:"
echo "  AWS Region: $AWS_REGION"
echo "  AWS Access Key: ${AWS_ACCESS_KEY_ID:0:5}..."
echo "  Bucket Prefix: ${BUCKET_PREFIX:-no configurado}"
echo ""
