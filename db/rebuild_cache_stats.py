#!/usr/bin/env python3
"""
Script para migrar una base de datos existente sin tabla cache_stats.

Uso:
    python rebuild_cache_stats.py <ruta_db> [--verify]

Opciones:
    --verify    Verifica integridad después de la reconstrucción
"""

import sys
import os
import logging
import argparse
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.logs import logcfg
from sttcastdb import SttcastDB


def verify_cache_stats(db: SttcastDB) -> bool:
    """Verifica que la tabla cache_stats sea consistente con speakerintervention."""
    logging.info("Iniciando verificación de integridad...")
    
    # Contar entradas en cache_stats
    db.cursor.execute("SELECT COUNT(*) FROM cache_stats")
    cache_count = db.cursor.fetchone()[0]
    logging.info(f"Entradas en cache_stats: {cache_count}")
    
    # Contar combinaciones únicas de (tag, epname) en speakerintervention
    query = """
    SELECT COUNT(DISTINCT st.tag, e.epname)
    FROM speakerintervention si
    JOIN episode e ON si.episodeid = e.id
    JOIN speakertag st ON si.tagid = st.id
    WHERE si.start IS NOT NULL AND si.end IS NOT NULL
    """
    db.cursor.execute(query)
    expected_count = db.cursor.fetchone()[0]
    logging.info(f"Combinaciones esperadas (tag, epname): {expected_count}")
    
    if cache_count != expected_count:
        logging.warning(f"⚠️  Mismatch: {cache_count} entradas en cache vs {expected_count} esperadas")
        return False
    
    # Verificar que no hay NULL en campos críticos
    db.cursor.execute("""
    SELECT COUNT(*) FROM cache_stats 
    WHERE tag IS NULL 
    OR epname IS NULL 
    OR epdate IS NULL
    """)
    null_count = db.cursor.fetchone()[0]
    if null_count > 0:
        logging.warning(f"⚠️  {null_count} entradas con NULL en campos críticos")
        return False
    
    # Spot check: verificar algunos valores aleatorios
    db.cursor.execute("""
    SELECT cs.tag, cs.epname, cs.interventions_in_episode_by_speaker
    FROM cache_stats cs
    LIMIT 5
    """)
    samples = db.cursor.fetchall()
    
    all_match = True
    for row in samples:
        tag, epname, cached_count = row[0], row[1], row[2]
        
        # Verificar el conteo en speakerintervention
        check_query = """
        SELECT COUNT(*)
        FROM speakerintervention si
        JOIN episode e ON si.episodeid = e.id
        JOIN speakertag st ON si.tagid = st.id
        WHERE st.tag = ? AND e.epname = ?
        AND si.start IS NOT NULL AND si.end IS NOT NULL
        """
        db.cursor.execute(check_query, (tag, epname))
        actual_count = db.cursor.fetchone()[0]
        
        if cached_count != actual_count:
            logging.warning(f"⚠️  Inconsistencia: {tag} en {epname}: caché={cached_count}, actual={actual_count}")
            all_match = False
    
    if all_match:
        logging.info("✅ Verificación de integridad EXITOSA")
        return True
    else:
        logging.warning("❌ Verificación de integridad FALLIDA")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Migra una base de datos existente agregando/reconstruyendo la tabla cache_stats"
    )
    parser.add_argument("db_path", type=str, help="Ruta a la base de datos SQLite")
    parser.add_argument("--verify", action="store_true", help="Verifica integridad después de la reconstrucción")
    parser.add_argument("--backup", action="store_true", default=True, help="Crea backup antes de migrar (por defecto: True)")
    
    args = parser.parse_args()
    
    # Configurar logging
    logcfg(__file__)
    
    db_path = args.db_path
    
    # Verificar que la BD existe
    if not os.path.exists(db_path):
        logging.error(f"❌ El archivo {db_path} no existe")
        return 1
    
    logging.info(f"Iniciando migración de {db_path}")
    
    # Crear backup si es solicitado
    if args.backup:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"{db_path}.backup_{timestamp}"
        try:
            import shutil
            shutil.copy2(db_path, backup_path)
            logging.info(f"✅ Backup creado en {backup_path}")
        except Exception as e:
            logging.error(f"❌ Error creando backup: {e}")
            return 1
    
    try:
        # Abrir BD
        db = SttcastDB(db_path, create_if_not_exists=False, wal=True)
        
        # Crear tabla si no existe
        db.ensure_cache_stats_exists()
        
        # Reconstruir cache_stats
        logging.info("Reconstruyendo tabla cache_stats...")
        start_time = datetime.now()
        count = db.rebuild_cache_stats_table()
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        logging.info(f"✅ Tabla cache_stats reconstruida con {count} entradas en {duration:.2f} segundos")
        
        # Verificar si se solicita
        if args.verify:
            if verify_cache_stats(db):
                logging.info("✅ Migración completada y verificada exitosamente")
            else:
                logging.error("❌ Migración completada pero con fallos de integridad")
                db.close()
                return 1
        else:
            logging.info("✅ Migración completada exitosamente")
        
        db.close()
        return 0
        
    except Exception as e:
        logging.error(f"❌ Error durante migración: {e}")
        logging.exception("Traceback completo:")
        return 1


if __name__ == "__main__":
    exit_code = main()
    exit(exit_code)
