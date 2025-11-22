#! /usr/bin/bash

# Determinar el directorio del script y el directorio padre (donde está el proyecto)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Cambiar al directorio del proyecto
cd "$PROJECT_DIR"

# Activar el entorno virtual y ejecutar los scripts
source .venv/bin/activate
./scripts/batch_stt_whisper.bash "$1" 
./scripts/batch_stt_whisper.bash "$1" en
