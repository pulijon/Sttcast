#!/bin/bash
# Script para migrar la base de datos y agregar el campo timezone a webif_users

# Configuración de base de datos
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-sttcast}"
DB_USER="${DB_USER:-postgres}"

# Crear la columna timezone si no existe
psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" <<EOF
-- Verificar si la columna existe, si no, crearla
DO \$\$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'webif_users' AND column_name = 'timezone'
    ) THEN
        ALTER TABLE webif_users 
        ADD COLUMN timezone VARCHAR(100) NOT NULL DEFAULT 'UTC';
        
        -- Crear índice para búsquedas rápidas
        CREATE INDEX IF NOT EXISTS idx_webif_users_timezone 
        ON webif_users(timezone);
        
        RAISE NOTICE 'Columna timezone añadida a webif_users';
    ELSE
        RAISE NOTICE 'Columna timezone ya existe en webif_users';
    END IF;
END \$\$;
EOF

echo "Migración completada"
