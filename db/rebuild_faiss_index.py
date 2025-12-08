#!/usr/bin/env python3
"""
Script para regenerar el índice FAISS desde la base de datos SQLite.
Reconstruye completamente el archivo .faiss usando los embeddings almacenados en la tabla speakerintervention.

Uso:
    python rebuild_faiss_index.py
    
El script lee las variables de entorno desde ../.env para obtener las rutas de los archivos.
"""

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import logging
from tools.logs import logcfg
from tools.envvars import load_env_vars_from_directory
from sttcastdb import SttcastDB
import numpy as np
import faiss
from datetime import datetime

def rebuild_faiss_index():
    """
    Reconstruye el índice FAISS desde los embeddings almacenados en SQLite.
    """
    # Configurar logging
    logcfg(__file__)
    logging.info("=" * 80)
    logging.info("Iniciando reconstrucción del índice FAISS desde SQLite")
    logging.info("=" * 80)
    
    # Cargar variables de entorno
    env_dir = os.path.join(os.path.dirname(__file__), '../.env')
    load_env_vars_from_directory(directory=env_dir)
    
    db_file = os.getenv("STTCAST_DB_FILE")
    if not db_file:
        raise ValueError("STTCAST_DB_FILE environment variable is not set")
    
    index_file = os.getenv("STTCAST_FAISS_FILE")
    if not index_file:
        raise ValueError("STTCAST_FAISS_FILE environment variable is not set")
    
    logging.info(f"Base de datos SQLite: {db_file}")
    logging.info(f"Archivo de índice FAISS: {index_file}")
    
    # Verificar que existe la base de datos
    if not os.path.exists(db_file):
        raise FileNotFoundError(f"La base de datos {db_file} no existe")
    
    # Hacer backup del índice corrupto si existe
    if os.path.exists(index_file):
        backup_file = f"{index_file}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        logging.info(f"Creando backup del índice actual en: {backup_file}")
        os.rename(index_file, backup_file)
    
    # Conectar a la base de datos
    logging.info("Conectando a la base de datos...")
    db = SttcastDB(db_file, create_if_not_exists=False)
    
    # Obtener todas las intervenciones con embeddings
    logging.info("Recuperando intervenciones con embeddings desde la base de datos...")
    ints = db.get_ints(with_embeddings=True)
    
    if not ints:
        logging.error("No se encontraron intervenciones con embeddings en la base de datos")
        db.close()
        return False
    
    logging.info(f"Se encontraron {len(ints)} intervenciones con embeddings")
    
    # Extraer IDs y embeddings
    ids = []
    embeddings = []
    
    logging.info("Procesando embeddings...")
    for i, intv in enumerate(ints):
        if i % 10000 == 0:
            logging.info(f"Procesado {i}/{len(ints)} embeddings...")
        
        int_id = intv['id']
        embedding_blob = intv['embedding']
        
        if embedding_blob is None:
            logging.warning(f"Intervención {int_id} no tiene embedding, saltando...")
            continue
        
        # Convertir de BLOB a numpy array
        # Los embeddings están guardados como float32, dimensión 1536
        try:
            embedding = np.frombuffer(embedding_blob, dtype=np.float32)
            
            # Verificar dimensión
            if len(embedding) != 1536:
                logging.warning(f"Intervención {int_id} tiene dimensión incorrecta: {len(embedding)}, esperado 1536")
                continue
            
            ids.append(int_id)
            embeddings.append(embedding)
            
        except Exception as e:
            logging.error(f"Error procesando embedding de intervención {int_id}: {e}")
            continue
    
    logging.info(f"Se procesaron exitosamente {len(embeddings)} embeddings válidos")
    
    if not embeddings:
        logging.error("No se pudieron procesar embeddings válidos")
        db.close()
        return False
    
    # Convertir a arrays numpy
    embeddings_array = np.array(embeddings, dtype=np.float32)
    ids_array = np.array(ids, dtype=np.int64)
    
    logging.info(f"Shape de embeddings: {embeddings_array.shape}")
    logging.info(f"Shape de IDs: {ids_array.shape}")
    
    # Normalizar vectores (como se hace en el servidor)
    logging.info("Normalizando vectores...")
    faiss.normalize_L2(embeddings_array)
    
    # Crear el índice FAISS
    logging.info("Creando índice FAISS...")
    dim = embeddings_array.shape[1]
    
    # Usar el mismo tipo de índice que el servidor: IndexFlatL2 con IndexIDMap2
    flat_index = faiss.IndexFlatL2(dim)
    index = faiss.IndexIDMap2(flat_index)
    
    logging.info(f"Índice creado con dimensión {dim}")
    
    # Añadir vectores al índice
    logging.info("Añadiendo vectores al índice...")
    index.add_with_ids(embeddings_array, ids_array)
    
    logging.info(f"Índice contiene {index.ntotal} vectores")
    
    # Guardar el índice
    logging.info(f"Guardando índice en {index_file}...")
    faiss.write_index(index, index_file)
    
    # Verificar el archivo guardado
    file_size = os.path.getsize(index_file)
    logging.info(f"Índice guardado exitosamente: {file_size / 1024 / 1024:.2f} MB")
    
    # Verificar que se puede leer correctamente
    logging.info("Verificando integridad del índice guardado...")
    try:
        test_index = faiss.read_index(index_file)
        logging.info(f"✅ Verificación exitosa: {test_index.ntotal} vectores, dimensión {test_index.d}")
    except Exception as e:
        logging.error(f"❌ Error verificando el índice guardado: {e}")
        db.close()
        return False
    
    # Cerrar base de datos
    db.close()
    
    logging.info("=" * 80)
    logging.info("✅ Reconstrucción del índice FAISS completada exitosamente")
    logging.info("=" * 80)
    
    return True

if __name__ == "__main__":
    try:
        success = rebuild_faiss_index()
        sys.exit(0 if success else 1)
    except Exception as e:
        logging.error(f"Error fatal durante la reconstrucción: {e}", exc_info=True)
        sys.exit(1)
