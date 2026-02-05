gi#!/bin/bash

# Script para resolver conflictos repetitivos en notebooks de Jupyter
# Mantiene execution_count: null en lugar de números específicos

echo "Resolviendo conflictos en changespeakers.ipynb..."

while true; do
    # Verificar si hay conflictos
    if ! grep -q "<<<<<<< HEAD\|=======\|>>>>>>>" notebooks/changespeakers.ipynb; then
        echo "No se encontraron marcadores de conflicto."
        break
    fi
    
    echo "Resolviendo marcadores de conflicto..."
    
    # Eliminar secciones de HEAD (mantener la versión con execution_count: null)
    sed -i '/<<<<<<< HEAD/,/=======/{/<<<<<<< HEAD/d; /=======/d; }' notebooks/changespeakers.ipynb
    
    # Eliminar marcadores de fin de conflicto
    sed -i '/>>>>>>> [0-9a-f]\{7\}/d' notebooks/changespeakers.ipynb
    
    # Limpiar cualquier marcador suelto
    sed -i '/=======/d' notebooks/changespeakers.ipynb
done

echo "Conflictos resueltos."

# Verificar que el JSON sea válido
if python3 -m json.tool notebooks/changespeakers.ipynb > /dev/null 2>&1; then
    echo "JSON válido ✓"
else
    echo "ADVERTENCIA: El JSON podría tener problemas"
fi

# Agregar el archivo resuelto
git add notebooks/changespeakers.ipynb

echo "Archivo agregado al staging. Ejecute 'git rebase --continue' para continuar."