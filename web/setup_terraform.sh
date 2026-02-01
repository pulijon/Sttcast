#!/bin/bash
# Script completo para setup de Terraform con variables desde .env/aws.env

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=========================================="
echo "Terraform AWS Setup"
echo "=========================================="
echo ""

# Step 1: Generar terraform.tfvars
echo "1️⃣  Generando terraform.tfvars desde .env/aws.env..."
bash load_env.sh
echo ""

# Step 2: Inicializar Terraform
echo "2️⃣  Inicializando Terraform..."
if terraform init; then
    echo "✓ Terraform inicializado"
else
    echo "✗ Error al inicializar Terraform"
    exit 1
fi
echo ""

# Step 3: Validar configuración
echo "3️⃣  Validando configuración de Terraform..."
if terraform validate; then
    echo "✓ Configuración válida"
else
    echo "✗ Errores de validación"
    exit 1
fi
echo ""

# Step 4: Mostrar el plan
echo "4️⃣  Mostrando plan de cambios..."
echo ""
terraform plan
echo ""

echo "=========================================="
echo "✓ Setup completo"
echo "=========================================="
echo ""
echo "Próximos pasos:"
echo "  - Revisa el plan anterior"
echo "  - Ejecuta: terraform apply"
echo "  - O para destruir: terraform destroy"
echo ""
