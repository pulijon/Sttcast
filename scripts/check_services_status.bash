#!/usr/bin/bash

# Script para mostrar el estado de todos los servicios sttcast configurados

# Directorio donde están los ficheros de configuración
CONFIG_DIR="/opt/sttcast/etc"

# Colores para la salida
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color
BOLD='\033[1m'

echo -e "${BOLD}======================================${NC}"
echo -e "${BOLD}  Estado de servicios Sttcast${NC}"
echo -e "${BOLD}======================================${NC}"
echo ""

# Verificar si el directorio existe
if [ ! -d "$CONFIG_DIR" ]; then
    echo -e "${RED}Error: El directorio $CONFIG_DIR no existe${NC}"
    exit 1
fi

# Contador de servicios
total_services=0
running_services=0
stopped_services=0
failed_services=0

# Iterar sobre todos los archivos .env
for env_file in "$CONFIG_DIR"/*.env; do
    # Verificar si existen archivos .env
    if [ ! -f "$env_file" ]; then
        echo -e "${YELLOW}No se encontraron archivos .env en $CONFIG_DIR${NC}"
        exit 0
    fi
    
    # Extraer el nombre de la instancia del nombre del archivo
    instance=$(basename "$env_file" .env)
    
    # Leer el directorio del software desde el archivo .env
    source "$env_file"
    
    echo -e "${BOLD}Instancia: ${YELLOW}$instance${NC}"
    echo -e "  Directorio: ${STTCAST_SW_DIR}"
    echo ""
    
    # Verificar cada servicio
    for service in sttccontext sttcrag sttcweb; do
        service_name="${service}@${instance}"
        ((total_services++))
        
        # Obtener el estado del servicio
        if systemctl is-active --quiet "$service_name"; then
            echo -e "  ├─ ${service}: ${GREEN}✓ Activo${NC}"
            ((running_services++))
        elif systemctl is-failed --quiet "$service_name"; then
            echo -e "  ├─ ${service}: ${RED}✗ Fallido${NC}"
            ((failed_services++))
        else
            echo -e "  ├─ ${service}: ${YELLOW}○ Inactivo${NC}"
            ((stopped_services++))
        fi
    done
    
    echo ""
    echo -e "${BOLD}────────────────────────────────────${NC}"
    echo ""
done

# Resumen
echo -e "${BOLD}Resumen:${NC}"
echo -e "  Total de servicios: $total_services"
echo -e "  ${GREEN}Activos: $running_services${NC}"
echo -e "  ${YELLOW}Inactivos: $stopped_services${NC}"
echo -e "  ${RED}Fallidos: $failed_services${NC}"
echo ""
