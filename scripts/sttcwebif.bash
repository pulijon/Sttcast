#!/bin/bash
# Script de inicio para Sttcast Web Interface (Transcripción)

# Tomar el directorio del proyecto desde la variable de entorno
# Si no está definida, usar el método anterior como fallback
if [ -z "$STTCAST_SW_DIR" ]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
else
    PROJECT_DIR="$STTCAST_SW_DIR"
fi

# Cargar variables de entorno si existen
if [ -f "$PROJECT_DIR/.env/webif.env" ]; then
    set -a  # Export all variables automatically
    source "$PROJECT_DIR/.env/webif.env"
    set +a  # Stop exporting
fi

# Valores por defecto
WEBIF_HOST=${WEBIF_HOST:-127.0.0.1}
WEBIF_PORT=${WEBIF_PORT:-8302}

echo "============================================"
echo "  Sttcast Web Interface (Transcripción)"
echo "============================================"
echo "Host: $WEBIF_HOST"
echo "Port: $WEBIF_PORT"
echo "============================================"

# Cambiar al directorio del proyecto
cd "$PROJECT_DIR"

# Activar el entorno virtual
source .venv/bin/activate

# Iniciar la aplicación
python -m webif.webif --host "$WEBIF_HOST" --port "$WEBIF_PORT" "$@"
