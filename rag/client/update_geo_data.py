#!/usr/bin/env python3
"""
Utilidad de migración: añade columnas region/latitude/longitude a rag_queries
y las rellena a partir de las IPs ya almacenadas usando GeoLite2.

Uso:
    python update_geo_data.py [--dry-run] [--batch-size N]

Opciones:
    --dry-run       Muestra cuántas filas se actualizarían sin modificar la BD.
    --batch-size N  Número de filas a procesar por lote (por defecto 500).

Requisitos:
    - Las variables de entorno de queriesdb deben estar cargadas (mismas que client_rag).
    - geoip2 y asyncpg deben estar instalados.
    - La base de datos GeoLite2-City.mmdb debe estar disponible.
"""

import asyncio
import argparse
import logging
import os
import sys

# Añadir el directorio padre al path para poder importar tools
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

try:
    from tools.logs import logcfg
    logcfg('log.yml')
except Exception:
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

# Cargar variables de entorno
try:
    from tools.envvars import load_env_vars_from_directory
    env_dir = os.path.join(os.path.dirname(__file__), '..', '..')
    load_env_vars_from_directory(os.path.join(env_dir, '.env'))
except Exception as e:
    logging.warning(f"No se pudieron cargar variables de entorno: {e}")

logger = logging.getLogger(__name__)


def _get_geoip_reader():
    """Inicializa el lector GeoIP."""
    try:
        import geoip2.database
    except ImportError:
        logger.error("geoip2 no está instalado. Instálalo con: pip install geoip2")
        return None

    geoip_db_path = os.getenv("GEOIP_DB_PATH", "/var/lib/GeoIP/GeoLite2-City.mmdb")
    if not os.path.exists(geoip_db_path):
        logger.error(f"Base de datos GeoIP no encontrada en {geoip_db_path}")
        return None

    try:
        import geoip2.database
        reader = geoip2.database.Reader(geoip_db_path)
        logger.info(f"✅ GeoIP listo: {geoip_db_path}")
        return reader
    except Exception as e:
        logger.error(f"Error al abrir GeoIP: {e}")
        return None


def lookup_ip(reader, ip: str) -> dict:
    """Resuelve región, latitud y longitud para una IP."""
    result = {"region": None, "latitude": None, "longitude": None}
    if not ip or ip in ('unknown', '127.0.0.1', '::1'):
        return result
    try:
        resp = reader.city(ip)
        result["region"] = resp.subdivisions.most_specific.name if resp.subdivisions else None
        result["latitude"] = resp.location.latitude
        result["longitude"] = resp.location.longitude
    except Exception:
        pass
    return result


async def add_columns_if_missing(conn):
    """Añade las columnas region, latitude y longitude si no existen."""
    migrations = [
        ("region",    "VARCHAR(100)"),
        ("latitude",  "DOUBLE PRECISION"),
        ("longitude", "DOUBLE PRECISION"),
    ]
    for col, col_type in migrations:
        await conn.execute(f"""
            ALTER TABLE rag_queries ADD COLUMN IF NOT EXISTS {col} {col_type};
        """)
        logger.info(f"✅ Columna '{col}' verificada/creada en rag_queries")


async def get_rows_to_update(conn, batch_size: int, offset: int):
    """Obtiene un lote de filas con IP pero sin coordenadas."""
    return await conn.fetch("""
        SELECT id, ip
        FROM rag_queries
        WHERE ip IS NOT NULL
          AND ip NOT IN ('unknown', '127.0.0.1', '::1')
          AND (latitude IS NULL OR longitude IS NULL OR region IS NULL)
        ORDER BY id
        LIMIT $1 OFFSET $2
    """, batch_size, offset)


async def count_rows_to_update(conn) -> int:
    """Cuenta cuántas filas necesitan actualización."""
    return await conn.fetchval("""
        SELECT COUNT(*)
        FROM rag_queries
        WHERE ip IS NOT NULL
          AND ip NOT IN ('unknown', '127.0.0.1', '::1')
          AND (latitude IS NULL OR longitude IS NULL OR region IS NULL)
    """)


async def run_migration(dry_run: bool = False, batch_size: int = 500):
    """Ejecuta la migración completa."""
    try:
        import asyncpg
    except ImportError:
        logger.error("asyncpg no está instalado.")
        return

    # Leer configuración de conexión
    host = os.getenv("QUERIESDB_HOST")
    port = int(os.getenv("QUERIESDB_PORT", "5432"))
    database = os.getenv("QUERIESDB_DB")
    user = os.getenv("QUERIESDB_USER")
    password = os.getenv("QUERIESDB_PASSWORD")

    if not all([host, database, user, password]):
        logger.error("Faltan variables de entorno de base de datos (QUERIESDB_HOST, QUERIESDB_DB, QUERIESDB_USER, QUERIESDB_PASSWORD)")
        return

    logger.info(f"Conectando a {user}@{host}:{port}/{database} ...")

    conn = await asyncpg.connect(
        host=host, port=port,
        user=user, password=password,
        database=database,
        timeout=30,
    )

    try:
        # 1. Añadir columnas si no existen
        if not dry_run:
            await add_columns_if_missing(conn)
        else:
            logger.info("[dry-run] Se omite la adición de columnas.")

        # 2. Contar filas pendientes
        pending = await count_rows_to_update(conn)
        logger.info(f"Filas pendientes de actualización: {pending}")

        if pending == 0:
            logger.info("No hay filas que actualizar.")
            return

        if dry_run:
            logger.info(f"[dry-run] Se actualizarían {pending} filas.")
            return

        # 3. Inicializar GeoIP
        reader = _get_geoip_reader()
        if not reader:
            logger.error("No se puede continuar sin GeoIP.")
            return

        # 4. Procesar en lotes
        updated = 0
        skipped = 0
        offset = 0

        try:
            while True:
                rows = await get_rows_to_update(conn, batch_size, offset)
                if not rows:
                    break

                for row in rows:
                    row_id = row["id"]
                    ip = row["ip"]
                    geo = lookup_ip(reader, ip)

                    if geo["latitude"] is None and geo["longitude"] is None and geo["region"] is None:
                        skipped += 1
                        offset += 1  # avanzar en offset para no quedarse en bucle
                        continue

                    await conn.execute("""
                        UPDATE rag_queries
                        SET region = $1, latitude = $2, longitude = $3
                        WHERE id = $4
                    """, geo["region"], geo["latitude"], geo["longitude"], row_id)
                    updated += 1

                logger.info(f"  Progreso: {updated} actualizadas, {skipped} sin resolución (IP no encontrada), {pending - updated - skipped} pendientes")

                # Si todas las filas del lote se saltaron, avanzamos manualmente
                # De lo contrario, las filas actualizadas desaparecen del query (ya tienen lat/lon)
                # y no necesitamos ajustar offset para ellas.
                if all(
                    lookup_ip(reader, r["ip"])["latitude"] is None
                    for r in rows
                ):
                    # Todas las IPs del lote no resolvieron; avanzar offset para evitar bucle infinito
                    if len(rows) < batch_size:
                        break
                else:
                    # Puede haber quedado alguna sin resolver en el lote; mantener offset
                    # en el valor actual (las resueltas ya no aparecerán en el siguiente query)
                    pass

                if len(rows) < batch_size:
                    break

        finally:
            reader.close()

        logger.info(f"✅ Migración completada: {updated} filas actualizadas, {skipped} IPs sin datos GeoIP")

    finally:
        await conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Solo muestra el número de filas a actualizar sin modificar la BD")
    parser.add_argument("--batch-size", type=int, default=500, metavar="N", help="Número de filas por lote (por defecto 500)")
    args = parser.parse_args()

    asyncio.run(run_migration(dry_run=args.dry_run, batch_size=args.batch_size))


if __name__ == "__main__":
    main()
