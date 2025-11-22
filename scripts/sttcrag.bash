#! /usr/bin/bash

# Tomar el directorio del proyecto desde la variable de entorno
# Si no está definida, usar el método anterior como fallback
if [ -z "$STTCAST_SW_DIR" ]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
else
    PROJECT_DIR="$STTCAST_SW_DIR"
fi

# Cambiar al directorio del proyecto
cd "$PROJECT_DIR"

# Activar el entorno virtual y ejecutar los scripts
source .venv/bin/activate

cd rag
python sttcast_rag_service.py
