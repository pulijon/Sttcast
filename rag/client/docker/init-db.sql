-- Script de inicialización de PostgreSQL con PGVector para Sttcast RAG
-- Solo crea la extensión pgvector en la base de datos template1
-- para que esté disponible para todas las bases de datos creadas posteriormente
-- Las bases de datos y usuarios específicos se crean dinámicamente desde queriesdb.py

-- Habilitar pgvector en template1 para que esté disponible en todas las BDs nuevas
\c template1;
CREATE EXTENSION IF NOT EXISTS vector;

-- También habilitarlo en postgres (BD por defecto)
\c postgres;
CREATE EXTENSION IF NOT EXISTS vector;




