#!/bin/bash
# Script para cargar variables desde .env/aws.env y generar terraform.tfvars

set -e

# Rutas
ENV_FILE="../.env/aws.env"
TFVARS_FILE="terraform.tfvars"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Cambiar al directorio del script
cd "$SCRIPT_DIR"

# Verificar que el archivo .env existe
if [ ! -f "$ENV_FILE" ]; then
    echo "Error: No se encontró $ENV_FILE"
    exit 1
fi

# Crear el archivo terraform.tfvars
cat > "$TFVARS_FILE" << 'EOF'
# Auto-generated from .env/aws.env
# Do not edit manually - run ./load_env.sh instead

EOF

# Leer el archivo .env y convertir a formato terraform.tfvars
while IFS='=' read -r key value; do
    # Ignorar líneas vacías y comentarios
    [[ -z "$key" || "$key" == \#* ]] && continue
    
    # Mapear nombres de variables de .env a terraform
    case "$key" in
        AWS_ACCESS_KEY_ID)
            echo "AWS_ACCESS_KEY_ID = \"$value\"" >> "$TFVARS_FILE"
            ;;
        AWS_SECRET_ACCESS_KEY)
            echo "AWS_SECRET_ACCESS_KEY = \"$value\"" >> "$TFVARS_FILE"
            ;;
        AWS_REGION)
            echo "aws_region = \"$value\"" >> "$TFVARS_FILE"
            ;;
        UPLOAD_SITE)
            echo "site = \"$value\"" >> "$TFVARS_FILE"
            ;;
        BUCKET_PREFIX)
            echo "bucket_prefix = \"$value\"" >> "$TFVARS_FILE"
            ;;
        DOMAIN_NAME)
            echo "domain_name = \"$value\"" >> "$TFVARS_FILE"
            ;;
        HOST_NAME)
            echo "host_name = \"$value\"" >> "$TFVARS_FILE"
            ;;
    esac
done < "$ENV_FILE"

echo "✓ Archivo $TFVARS_FILE generado exitosamente desde $ENV_FILE"
echo ""
echo "Próximos pasos:"
echo "  - Para planificar: terraform plan"
echo "  - Para aplicar: terraform apply"
echo "  - Para destruir: terraform destroy"
