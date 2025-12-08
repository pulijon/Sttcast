-- Migración: Agregar columna response_data JSONB a rag_queries
-- Fecha: 2025-12-07
-- Descripción: Añade soporte para almacenar respuestas completas con referencias
--              en formato compatible con la interfaz web

-- Agregar columna response_data si no existe
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'rag_queries' 
        AND column_name = 'response_data'
    ) THEN
        ALTER TABLE rag_queries ADD COLUMN response_data JSONB;
        RAISE NOTICE 'Columna response_data agregada exitosamente';
    ELSE
        RAISE NOTICE 'Columna response_data ya existe';
    END IF;
END $$;

-- Crear índice GIN para búsquedas eficientes en JSONB (opcional pero recomendado)
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_indexes 
        WHERE tablename = 'rag_queries' 
        AND indexname = 'idx_rag_queries_response_data'
    ) THEN
        CREATE INDEX idx_rag_queries_response_data ON rag_queries USING GIN (response_data);
        RAISE NOTICE 'Índice idx_rag_queries_response_data creado exitosamente';
    ELSE
        RAISE NOTICE 'Índice idx_rag_queries_response_data ya existe';
    END IF;
END $$;

-- Comentario descriptivo
COMMENT ON COLUMN rag_queries.response_data IS 'Respuesta completa en formato JSON con estructura {response: {es: ..., en: ...}, references: [...], timestamp: ..., query: ...}';
