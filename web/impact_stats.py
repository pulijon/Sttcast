#!/usr/bin/env python3
"""
impact_stats.py — Estadísticas de impacto del podcast desde logs de CloudFront.

Descarga logs de CloudFront almacenados en S3, los parsea y almacena en SQLite.
Genera informes HTML/texto con desglose horario, diario, semanal y mensual.

Configuración por variables de entorno (.env/impact.env, .env/aws.env):
    IMPACT_DB          Ruta a la base de datos SQLite de impacto
    IMPACT_GEOIP_DB    Ruta a GeoLite2-City.mmdb
    BUCKET_NAME        Nombre base del bucket S3 (se añade '-logs')
    AWS_REGION         Región AWS del bucket

Modos de operación:
  --update (-u)   Actualiza la base de datos con los logs nuevos de S3
  --report (-r)   Genera informe(s) desde la base de datos
  (sin flags)     Hace ambas cosas

Acotamiento del informe:
  --hours N       Últimas N horas
  --days N        Últimos N días (default si no se indica nada: 7)
  --months N      Últimos N meses
  --all           Todos los datos disponibles
  --from FECHA    Desde (YYYY-MM-DD o 'YYYY-MM-DD HH:MM')
  --to FECHA      Hasta (YYYY-MM-DD o 'YYYY-MM-DD HH:MM', default: ahora)
  --standard      Genera 3 informes: 1 día, 7 días y 31 días

Ejemplos:
  # Primera ejecución (usa variables de .env/):
  python impact_stats.py -u

  # Actualizar + 3 informes estándar:
  python impact_stats.py -u -r --standard

  # Informe del último mes:
  python impact_stats.py -r --days 31

  # Sobreescribir bucket desde CLI:
  python impact_stats.py -u --bucket genred-jmrobles-logs
"""

import argparse
import gzip
import os
import re
import sqlite3
import subprocess
import sys
import threading
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote

# ── Cargar variables de entorno desde .env/ ──────────────────────────────
_project_root = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, _project_root)

from tools.envvars import load_env_vars_from_directory
load_env_vars_from_directory(os.path.join(_project_root, '.env'))

try:
    import boto3
except ImportError:
    print("Error: boto3 es necesario. Instálalo con: pip install boto3")
    sys.exit(1)

try:
    import geoip2.database
    HAS_GEOIP = True
except ImportError:
    HAS_GEOIP = False

# ═══════════════════════════════════════════════════════════════════════════════
# Constantes
# ═══════════════════════════════════════════════════════════════════════════════

MESES_ES = {
    1: 'Enero', 2: 'Febrero', 3: 'Marzo', 4: 'Abril',
    5: 'Mayo', 6: 'Junio', 7: 'Julio', 8: 'Agosto',
    9: 'Septiembre', 10: 'Octubre', 11: 'Noviembre', 12: 'Diciembre',
}

DIAS_SEMANA_ES = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']

PLATFORM_PATTERNS = [
    (re.compile(r'AppleCoreMedia|iTunes|Podcasts/|Apple%20Podcasts', re.I), 'Apple Podcasts'),
    (re.compile(r'Spotify', re.I), 'Spotify'),
    (re.compile(r'iVoox', re.I), 'iVoox'),
    (re.compile(r'Amazon\s?Music|Audible', re.I), 'Amazon Music'),
    (re.compile(r'Google-Podcasts|GoogleChirp', re.I), 'Google Podcasts'),
    (re.compile(r'Overcast', re.I), 'Overcast'),
    (re.compile(r'PocketCasts|Pocket\s?Casts', re.I), 'Pocket Casts'),
    (re.compile(r'CastBox', re.I), 'CastBox'),
    (re.compile(r'PlayerFM|Player\s?FM', re.I), 'Player FM'),
    (re.compile(r'Podimo', re.I), 'Podimo'),
    (re.compile(r'Castro', re.I), 'Castro'),
    (re.compile(r'Stitcher', re.I), 'Stitcher'),
    (re.compile(r'TuneIn', re.I), 'TuneIn'),
    (re.compile(r'Deezer', re.I), 'Deezer'),
    (re.compile(r'YouTube\s?Music', re.I), 'YouTube Music'),
    (re.compile(r'Podchaser', re.I), 'Podchaser'),
    (re.compile(r'AntennaPod', re.I), 'AntennaPod'),
    (re.compile(r'Podcast\s?Addict', re.I), 'Podcast Addict'),
    (re.compile(r'Pandora', re.I), 'Pandora'),
    (re.compile(r'Sonos', re.I), 'Sonos'),
    (re.compile(r'Alexa|Echo', re.I), 'Amazon Alexa'),
    (re.compile(r'facebookexternalhit|Facebot', re.I), 'Facebook Bot'),
    (re.compile(r'Googlebot|bingbot|Baiduspider|YandexBot|DuckDuckBot|Slurp', re.I), 'Bot buscador'),
    (re.compile(r'curl|wget|python-requests|libwww|axios|node-fetch', re.I), 'Automatizado/CLI'),
    (re.compile(r'Mozilla.*Chrome.*Safari', re.I), 'Navegador (Chrome)'),
    (re.compile(r'Mozilla.*Firefox', re.I), 'Navegador (Firefox)'),
    (re.compile(r'Mozilla.*Safari', re.I), 'Navegador (Safari)'),
    (re.compile(r'Mozilla', re.I), 'Navegador (Otro)'),
]

# Campos del log estándar de CloudFront (W3C Extended)
CF_FIELDS = [
    'date', 'time', 'x_edge_location', 'sc_bytes', 'c_ip',
    'cs_method', 'cs_host', 'cs_uri_stem', 'sc_status',
    'cs_referer', 'cs_user_agent', 'cs_uri_query', 'cs_cookie',
    'x_edge_result_type', 'x_edge_request_id', 'x_host_header',
    'cs_protocol', 'cs_bytes', 'time_taken', 'x_forwarded_for',
    'ssl_protocol', 'ssl_cipher', 'x_edge_response_result_type',
    'cs_protocol_version', 'fle_status', 'fle_encrypted_fields',
    'c_port', 'time_to_first_byte', 'x_edge_detailed_result_type',
    'sc_content_type', 'sc_content_len', 'sc_range_start', 'sc_range_end',
]


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def format_bytes(b: int) -> str:
    """Formatea bytes en unidades legibles."""
    if b is None:
        return '0 B'
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if b < 1024:
            return f'{b:.1f} {unit}'
        b /= 1024
    return f'{b:.1f} PB'


def identify_platform(user_agent: str) -> str:
    """Identifica la plataforma de podcast a partir del User-Agent."""
    if not user_agent or user_agent == '-':
        return 'Desconocido'
    ua = unquote(user_agent)
    for pattern, name in PLATFORM_PATTERNS:
        if pattern.search(ua):
            return name
    return 'Otro'


def classify_resource(uri: str) -> tuple[str, str]:
    """Clasifica el recurso solicitado. Devuelve (tipo, nombre).

    Tipos: mp3, transcript, index, rss, other
    """
    uri_lower = uri.lower()
    name = uri.rsplit('/', 1)[-1]
    if uri_lower.endswith('.mp3'):
        return 'mp3', name
    if uri_lower.endswith('.xml'):
        return 'rss', name
    if uri_lower.endswith('.html'):
        if name.lower() == 'index.html' or uri == '/':
            return 'index', name
        return 'transcript', name
    if uri == '/' or uri == '':
        return 'index', 'index.html'
    return 'other', name


def parse_datetime_arg(s: str) -> datetime:
    """Parsea argumentos de fecha flexibles."""
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise ValueError(f"Formato de fecha no reconocido: '{s}'. Usa YYYY-MM-DD o 'YYYY-MM-DD HH:MM'")


def get_bucket_from_terraform() -> str | None:
    """Intenta obtener el nombre del bucket de logs desde terraform output."""
    try:
        result = subprocess.run(
            ['terraform', 'output', '-raw', 'logs_bucket'],
            capture_output=True, text=True, timeout=15,
            cwd=os.path.dirname(os.path.abspath(__file__)),
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# Parser de logs de CloudFront
# ═══════════════════════════════════════════════════════════════════════════════

def parse_cf_log_line(line: str) -> dict | None:
    """Parsea una línea de log de CloudFront. Devuelve None si es comentario."""
    if line.startswith('#'):
        return None
    parts = line.strip().split('\t')
    if len(parts) < 15:
        return None
    rec = {}
    for i, field in enumerate(CF_FIELDS):
        rec[field] = parts[i] if i < len(parts) else '-'
    return rec


# ═══════════════════════════════════════════════════════════════════════════════
# Descarga de logs desde S3 (paralela, con inserción incremental)
# ═══════════════════════════════════════════════════════════════════════════════

BATCH_INSERT_SIZE = 500
MAX_DOWNLOAD_WORKERS = 10


def _parse_log_file_body(body: bytes, geoip_path: str | None) -> list[dict]:
    """Parsea un fichero de log de CloudFront (bytes, posiblemente gzip).
    Devuelve lista de registros.
    """
    try:
        text = gzip.decompress(body).decode('utf-8')
    except gzip.BadGzipFile:
        text = body.decode('utf-8')

    geo_reader = None
    if geoip_path and HAS_GEOIP and os.path.exists(geoip_path):
        try:
            geo_reader = geoip2.database.Reader(geoip_path)
        except Exception:
            pass

    records = []
    for line in text.strip().split('\n'):
        raw = parse_cf_log_line(line)
        if not raw:
            continue

        uri = unquote(raw['cs_uri_stem'])
        resource_type, resource_name = classify_resource(uri)

        try:
            ts = datetime.strptime(f"{raw['date']} {raw['time']}", '%Y-%m-%d %H:%M:%S')
        except ValueError:
            continue

        try:
            status = int(raw['sc_status'])
        except (ValueError, TypeError):
            status = 0
        try:
            bytes_sent = int(raw['sc_bytes'])
        except (ValueError, TypeError):
            bytes_sent = 0
        try:
            time_taken = float(raw['time_taken'])
        except (ValueError, TypeError):
            time_taken = 0.0

        ua = unquote(raw['cs_user_agent']) if raw['cs_user_agent'] != '-' else ''
        referer = raw['cs_referer'] if raw['cs_referer'] != '-' else ''

        country, city = '', ''
        if geo_reader:
            try:
                geo = geo_reader.city(raw['c_ip'])
                country = geo.country.names.get('es', geo.country.name) or ''
                city = geo.city.names.get('es', geo.city.name) or ''
            except Exception:
                pass

        records.append({
            'request_id': raw['x_edge_request_id'],
            'timestamp': ts.strftime('%Y-%m-%dT%H:%M:%S'),
            'date': raw['date'],
            'hour': ts.hour,
            'weekday': ts.weekday(),
            'ip': raw['c_ip'],
            'uri': uri,
            'status': status,
            'bytes_sent': bytes_sent,
            'time_taken': time_taken,
            'user_agent': ua,
            'referer': referer,
            'platform': identify_platform(raw['cs_user_agent']),
            'resource_type': resource_type,
            'resource_name': resource_name,
            'edge_location': raw['x_edge_location'],
            'country': country,
            'city': city,
        })

    if geo_reader:
        geo_reader.close()

    return records


def _download_one_file(s3_client, bucket: str, key: str) -> bytes:
    """Descarga un fichero de S3 y devuelve su contenido."""
    response = s3_client.get_object(Bucket=bucket, Key=key)
    return response['Body'].read()


def download_and_insert_logs(db: 'StatsDB', bucket: str, prefix: str,
                             since: datetime | None, region: str,
                             geoip_path: str | None) -> tuple[int, int, int]:
    """Descarga logs de S3, parsea e inserta en la DB en batches.

    Usa descarga en paralelo con ThreadPoolExecutor.
    Devuelve (ficheros_procesados, registros_parseados, registros_nuevos).
    """
    s3 = boto3.client('s3', region_name=region)

    # Buffer de 6h para logs de entrega tardía
    cutoff = None
    if since:
        cutoff = since.replace(tzinfo=timezone.utc) - timedelta(hours=6)
        print(f'  Logs desde: {cutoff.strftime("%Y-%m-%d %H:%M")} UTC (buffer 6h)')

    # Fase 1: listar todos los ficheros relevantes
    print(f'Listando ficheros en s3://{bucket}/{prefix} ...')
    paginator = s3.get_paginator('list_objects_v2')
    keys_to_process = []
    files_total = 0

    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get('Contents', []):
            files_total += 1
            if cutoff and obj['LastModified'] < cutoff:
                continue
            keys_to_process.append(obj['Key'])

    files_to_download = len(keys_to_process)
    print(f'  Ficheros en bucket: {files_total}, a descargar: {files_to_download}')

    if files_to_download == 0:
        return 0, 0, 0

    # Fase 2: descargar en paralelo e insertar en batches
    total_parsed = 0
    total_new = 0
    files_done = 0
    pending_records = []
    lock = threading.Lock()

    def flush_batch():
        nonlocal total_new, pending_records
        if pending_records:
            new = db.insert_requests(pending_records)
            total_new += new
            pending_records = []

    # Crear un cliente S3 por hilo (no son thread-safe)
    thread_local = threading.local()

    def get_s3_client():
        if not hasattr(thread_local, 's3'):
            thread_local.s3 = boto3.client('s3', region_name=region)
        return thread_local.s3

    def download_and_parse(key: str) -> list[dict]:
        client = get_s3_client()
        body = _download_one_file(client, bucket, key)
        return _parse_log_file_body(body, geoip_path)

    with ThreadPoolExecutor(max_workers=MAX_DOWNLOAD_WORKERS) as executor:
        futures = {executor.submit(download_and_parse, key): key
                   for key in keys_to_process}

        for future in as_completed(futures):
            files_done += 1
            try:
                records = future.result()
            except Exception as e:
                key = futures[future]
                print(f'  Error procesando {key}: {e}')
                continue

            total_parsed += len(records)
            pending_records.extend(records)

            # Insertar en batches
            if len(pending_records) >= BATCH_INSERT_SIZE:
                flush_batch()

            # Progreso cada 50 ficheros o al llegar al final
            if files_done % 50 == 0 or files_done == files_to_download:
                print(f'  Progreso: {files_done}/{files_to_download} ficheros, '
                      f'{total_parsed} registros, {total_new} nuevos en DB')

    # Flush registros restantes
    flush_batch()

    print(f'  Completado: {files_done} ficheros, {total_parsed} registros parseados, '
          f'{total_new} nuevos insertados')
    return files_done, total_parsed, total_new


# ═══════════════════════════════════════════════════════════════════════════════
# Base de datos SQLite
# ═══════════════════════════════════════════════════════════════════════════════

class StatsDB:
    """Gestiona la base de datos SQLite de estadísticas."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('PRAGMA journal_mode=WAL')
        self.conn.execute('PRAGMA synchronous=NORMAL')
        self._create_tables()

    def _create_tables(self):
        self.conn.executescript('''
            CREATE TABLE IF NOT EXISTS requests (
                request_id    TEXT PRIMARY KEY,
                timestamp     TEXT NOT NULL,
                date          TEXT NOT NULL,
                hour          INTEGER NOT NULL,
                weekday       INTEGER NOT NULL,
                ip            TEXT,
                uri           TEXT,
                status        INTEGER,
                bytes_sent    INTEGER DEFAULT 0,
                time_taken    REAL DEFAULT 0,
                user_agent    TEXT,
                referer       TEXT,
                platform      TEXT,
                resource_type TEXT,
                resource_name TEXT,
                edge_location TEXT,
                country       TEXT,
                city          TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_req_timestamp     ON requests(timestamp);
            CREATE INDEX IF NOT EXISTS idx_req_date           ON requests(date);
            CREATE INDEX IF NOT EXISTS idx_req_resource_type  ON requests(resource_type);
            CREATE INDEX IF NOT EXISTS idx_req_status         ON requests(status);

            CREATE TABLE IF NOT EXISTS meta (
                key   TEXT PRIMARY KEY,
                value TEXT
            );
        ''')
        self.conn.commit()

    # ── Meta ─────────────────────────────────────────────────────────────────

    def get_meta(self, key: str) -> str | None:
        row = self.conn.execute('SELECT value FROM meta WHERE key = ?', (key,)).fetchone()
        return row['value'] if row else None

    def set_meta(self, key: str, value: str):
        self.conn.execute('INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)', (key, value))
        self.conn.commit()

    def get_last_update(self) -> datetime | None:
        val = self.get_meta('last_update')
        if val:
            return datetime.fromisoformat(val)
        return None

    def set_last_update(self, dt: datetime):
        self.set_meta('last_update', dt.isoformat())

    # ── Inserción ────────────────────────────────────────────────────────────

    def insert_requests(self, records: list[dict]) -> int:
        """Inserta registros. Devuelve cuántos se insertaron (nuevos)."""
        if not records:
            return 0
        before = self.conn.execute('SELECT COUNT(*) FROM requests').fetchone()[0]
        self.conn.executemany('''
            INSERT OR IGNORE INTO requests (
                request_id, timestamp, date, hour, weekday,
                ip, uri, status, bytes_sent, time_taken,
                user_agent, referer, platform,
                resource_type, resource_name, edge_location,
                country, city
            ) VALUES (
                :request_id, :timestamp, :date, :hour, :weekday,
                :ip, :uri, :status, :bytes_sent, :time_taken,
                :user_agent, :referer, :platform,
                :resource_type, :resource_name, :edge_location,
                :country, :city
            )
        ''', records)
        self.conn.commit()
        after = self.conn.execute('SELECT COUNT(*) FROM requests').fetchone()[0]
        return after - before

    # ── Rango disponible ─────────────────────────────────────────────────────

    def get_date_range(self) -> tuple[str | None, str | None]:
        row = self.conn.execute(
            'SELECT MIN(timestamp) as mn, MAX(timestamp) as mx FROM requests'
        ).fetchone()
        return (row['mn'], row['mx']) if row['mn'] else (None, None)

    def get_record_count(self) -> int:
        return self.conn.execute('SELECT COUNT(*) FROM requests').fetchone()[0]

    # ── Consultas para informes ──────────────────────────────────────────────

    def _where_range(self, from_dt: datetime, to_dt: datetime) -> tuple[str, tuple]:
        return "timestamp >= ? AND timestamp < ?", (from_dt.strftime('%Y-%m-%dT%H:%M:%S'),
                                                     to_dt.strftime('%Y-%m-%dT%H:%M:%S'))

    def _success_filter(self) -> str:
        return "AND status BETWEEN 200 AND 399"

    def query_summary(self, from_dt: datetime, to_dt: datetime) -> dict:
        wh, params = self._where_range(from_dt, to_dt)
        sf = self._success_filter()
        row = self.conn.execute(f'''
            SELECT
                COUNT(*) as total_requests,
                COUNT(DISTINCT ip) as unique_ips,
                SUM(bytes_sent) as total_bytes,
                SUM(CASE WHEN resource_type='mp3' {sf} THEN 1 ELSE 0 END) as mp3_downloads,
                SUM(CASE WHEN resource_type='mp3' {sf} THEN bytes_sent ELSE 0 END) as mp3_bytes,
                SUM(CASE WHEN resource_type='transcript' {sf} THEN 1 ELSE 0 END) as transcript_views,
                SUM(CASE WHEN resource_type='rss' {sf} THEN 1 ELSE 0 END) as rss_checks,
                SUM(CASE WHEN resource_type='index' {sf} THEN 1 ELSE 0 END) as index_views,
                MIN(timestamp) as first_ts,
                MAX(timestamp) as last_ts
            FROM requests WHERE {wh}
        ''', params).fetchone()
        return dict(row)

    def query_daily(self, from_dt: datetime, to_dt: datetime) -> list[dict]:
        wh, params = self._where_range(from_dt, to_dt)
        sf = self._success_filter()
        rows = self.conn.execute(f'''
            SELECT
                date,
                COUNT(*) as total_requests,
                COUNT(DISTINCT ip) as unique_ips,
                SUM(bytes_sent) as total_bytes,
                SUM(CASE WHEN resource_type='mp3' {sf} THEN 1 ELSE 0 END) as mp3_downloads,
                SUM(CASE WHEN resource_type='mp3' {sf} THEN bytes_sent ELSE 0 END) as mp3_bytes,
                SUM(CASE WHEN resource_type='transcript' {sf} THEN 1 ELSE 0 END) as transcript_views,
                SUM(CASE WHEN resource_type='rss' {sf} THEN 1 ELSE 0 END) as rss_checks
            FROM requests WHERE {wh}
            GROUP BY date ORDER BY date
        ''', params).fetchall()
        return [dict(r) for r in rows]

    def query_hourly_distribution(self, from_dt: datetime, to_dt: datetime) -> list[dict]:
        wh, params = self._where_range(from_dt, to_dt)
        sf = self._success_filter()
        rows = self.conn.execute(f'''
            SELECT
                hour,
                COUNT(*) as requests,
                SUM(CASE WHEN resource_type='mp3' {sf} THEN 1 ELSE 0 END) as mp3_downloads
            FROM requests WHERE {wh}
            GROUP BY hour ORDER BY hour
        ''', params).fetchall()
        # Rellenar horas sin datos
        hour_map = {r['hour']: dict(r) for r in rows}
        return [hour_map.get(h, {'hour': h, 'requests': 0, 'mp3_downloads': 0}) for h in range(24)]

    def query_weekday_distribution(self, from_dt: datetime, to_dt: datetime) -> list[dict]:
        wh, params = self._where_range(from_dt, to_dt)
        sf = self._success_filter()
        rows = self.conn.execute(f'''
            SELECT
                weekday,
                COUNT(*) as requests,
                SUM(CASE WHEN resource_type='mp3' {sf} THEN 1 ELSE 0 END) as mp3_downloads
            FROM requests WHERE {wh}
            GROUP BY weekday ORDER BY weekday
        ''', params).fetchall()
        wd_map = {r['weekday']: dict(r) for r in rows}
        return [{'weekday': w, 'label': DIAS_SEMANA_ES[w],
                 'requests': wd_map.get(w, {}).get('requests', 0),
                 'mp3_downloads': wd_map.get(w, {}).get('mp3_downloads', 0)}
                for w in range(7)]

    def query_platforms(self, from_dt: datetime, to_dt: datetime) -> list[dict]:
        wh, params = self._where_range(from_dt, to_dt)
        sf = self._success_filter()
        rows = self.conn.execute(f'''
            SELECT platform, COUNT(*) as downloads
            FROM requests WHERE {wh} AND resource_type='mp3' {sf}
            GROUP BY platform ORDER BY downloads DESC
        ''', params).fetchall()
        return [dict(r) for r in rows]

    def query_episodes(self, from_dt: datetime, to_dt: datetime, limit: int = 30) -> list[dict]:
        wh, params = self._where_range(from_dt, to_dt)
        sf = self._success_filter()
        rows = self.conn.execute(f'''
            SELECT resource_name as episode, COUNT(*) as downloads,
                   SUM(bytes_sent) as bytes_total
            FROM requests WHERE {wh} AND resource_type='mp3' {sf}
            GROUP BY resource_name ORDER BY downloads DESC LIMIT ?
        ''', (*params, limit)).fetchall()
        return [dict(r) for r in rows]

    def query_transcripts(self, from_dt: datetime, to_dt: datetime, limit: int = 30) -> list[dict]:
        wh, params = self._where_range(from_dt, to_dt)
        sf = self._success_filter()
        rows = self.conn.execute(f'''
            SELECT resource_name as page, COUNT(*) as views
            FROM requests WHERE {wh} AND resource_type='transcript' {sf}
            GROUP BY resource_name ORDER BY views DESC LIMIT ?
        ''', (*params, limit)).fetchall()
        return [dict(r) for r in rows]

    def query_top_ips(self, from_dt: datetime, to_dt: datetime, limit: int = 20) -> list[dict]:
        wh, params = self._where_range(from_dt, to_dt)
        rows = self.conn.execute(f'''
            SELECT ip, COUNT(*) as requests,
                   MAX(country) as country, MAX(city) as city
            FROM requests WHERE {wh}
            GROUP BY ip ORDER BY requests DESC LIMIT ?
        ''', (*params, limit)).fetchall()
        return [dict(r) for r in rows]

    def query_countries(self, from_dt: datetime, to_dt: datetime, limit: int = 20) -> list[dict]:
        wh, params = self._where_range(from_dt, to_dt)
        rows = self.conn.execute(f'''
            SELECT country, COUNT(*) as requests
            FROM requests WHERE {wh} AND country != '' AND country IS NOT NULL
            GROUP BY country ORDER BY requests DESC LIMIT ?
        ''', (*params, limit)).fetchall()
        return [dict(r) for r in rows]

    def query_cities(self, from_dt: datetime, to_dt: datetime, limit: int = 20) -> list[dict]:
        wh, params = self._where_range(from_dt, to_dt)
        rows = self.conn.execute(f'''
            SELECT city || ', ' || country as location, COUNT(*) as requests
            FROM requests WHERE {wh} AND city != '' AND city IS NOT NULL
            GROUP BY location ORDER BY requests DESC LIMIT ?
        ''', (*params, limit)).fetchall()
        return [dict(r) for r in rows]

    def query_referers(self, from_dt: datetime, to_dt: datetime, limit: int = 20) -> list[dict]:
        wh, params = self._where_range(from_dt, to_dt)
        rows = self.conn.execute(f'''
            SELECT referer, COUNT(*) as requests
            FROM requests WHERE {wh} AND referer != '' AND referer IS NOT NULL
            GROUP BY referer ORDER BY requests DESC LIMIT ?
        ''', (*params, limit)).fetchall()
        return [dict(r) for r in rows]

    def query_status_codes(self, from_dt: datetime, to_dt: datetime) -> list[dict]:
        wh, params = self._where_range(from_dt, to_dt)
        rows = self.conn.execute(f'''
            SELECT status, COUNT(*) as requests
            FROM requests WHERE {wh}
            GROUP BY status ORDER BY requests DESC
        ''', params).fetchall()
        return [dict(r) for r in rows]

    def query_edge_locations(self, from_dt: datetime, to_dt: datetime, limit: int = 15) -> list[dict]:
        wh, params = self._where_range(from_dt, to_dt)
        rows = self.conn.execute(f'''
            SELECT edge_location, COUNT(*) as requests
            FROM requests WHERE {wh}
            GROUP BY edge_location ORDER BY requests DESC LIMIT ?
        ''', (*params, limit)).fetchall()
        return [dict(r) for r in rows]

    def close(self):
        self.conn.close()


# ═══════════════════════════════════════════════════════════════════════════════
# Agregación semanal y mensual (desde datos diarios)
# ═══════════════════════════════════════════════════════════════════════════════

def aggregate_weekly(daily_data: list[dict]) -> list[dict]:
    """Agrupa datos diarios en semanas ISO (lunes a domingo)."""
    weeks = defaultdict(lambda: {
        'mp3_downloads': 0, 'transcript_views': 0,
        'total_requests': 0, 'total_bytes': 0, 'rss_checks': 0,
        'unique_ips': 0,  # suma aproximada
    })

    for row in daily_data:
        dt = datetime.strptime(row['date'], '%Y-%m-%d')
        monday = dt - timedelta(days=dt.weekday())
        sunday = monday + timedelta(days=6)
        key = monday.strftime('%Y-%m-%d')
        label = f"{monday.strftime('%d %b')} – {sunday.strftime('%d %b %Y')}"

        w = weeks[key]
        w['label'] = label
        w['start'] = key
        w['mp3_downloads'] += row.get('mp3_downloads', 0) or 0
        w['transcript_views'] += row.get('transcript_views', 0) or 0
        w['total_requests'] += row.get('total_requests', 0) or 0
        w['total_bytes'] += row.get('total_bytes', 0) or 0
        w['rss_checks'] += row.get('rss_checks', 0) or 0
        w['unique_ips'] += row.get('unique_ips', 0) or 0

    return [weeks[k] for k in sorted(weeks.keys())]


def aggregate_monthly(daily_data: list[dict]) -> list[dict]:
    """Agrupa datos diarios en meses."""
    months = defaultdict(lambda: {
        'mp3_downloads': 0, 'transcript_views': 0,
        'total_requests': 0, 'total_bytes': 0, 'rss_checks': 0,
        'unique_ips': 0,
    })

    for row in daily_data:
        dt = datetime.strptime(row['date'], '%Y-%m-%d')
        key = dt.strftime('%Y-%m')
        label = f"{MESES_ES[dt.month]} {dt.year}"

        m = months[key]
        m['label'] = label
        m['key'] = key
        m['mp3_downloads'] += row.get('mp3_downloads', 0) or 0
        m['transcript_views'] += row.get('transcript_views', 0) or 0
        m['total_requests'] += row.get('total_requests', 0) or 0
        m['total_bytes'] += row.get('total_bytes', 0) or 0
        m['rss_checks'] += row.get('rss_checks', 0) or 0
        m['unique_ips'] += row.get('unique_ips', 0) or 0

    return [months[k] for k in sorted(months.keys())]


# ═══════════════════════════════════════════════════════════════════════════════
# Montaje de datos del informe
# ═══════════════════════════════════════════════════════════════════════════════

def build_report_data(db: StatsDB, from_dt: datetime, to_dt: datetime) -> dict:
    """Extrae todos los datos necesarios de la DB para generar el informe."""
    daily = db.query_daily(from_dt, to_dt)

    return {
        'from_dt': from_dt,
        'to_dt': to_dt,
        'summary': db.query_summary(from_dt, to_dt),
        'daily': daily,
        'weekly': aggregate_weekly(daily),
        'monthly': aggregate_monthly(daily),
        'hourly_dist': db.query_hourly_distribution(from_dt, to_dt),
        'weekday_dist': db.query_weekday_distribution(from_dt, to_dt),
        'platforms': db.query_platforms(from_dt, to_dt),
        'episodes': db.query_episodes(from_dt, to_dt),
        'transcripts': db.query_transcripts(from_dt, to_dt),
        'top_ips': db.query_top_ips(from_dt, to_dt),
        'countries': db.query_countries(from_dt, to_dt),
        'cities': db.query_cities(from_dt, to_dt),
        'referers': db.query_referers(from_dt, to_dt),
        'status_codes': db.query_status_codes(from_dt, to_dt),
        'edge_locations': db.query_edge_locations(from_dt, to_dt),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Generador de informe HTML
# ═══════════════════════════════════════════════════════════════════════════════

def _html_bar_chart(items: list[tuple[str, int]], color: str = '#4a90d9', max_items: int = 20) -> str:
    """Genera un gráfico de barras CSS a partir de una lista de (label, valor)."""
    items = items[:max_items]
    if not items:
        return '<p class="empty">Sin datos</p>'
    max_val = max(v for _, v in items) if items else 1
    rows = []
    for label, val in items:
        pct = val / max_val * 100 if max_val else 0
        rows.append(f'''<div class="bar-row">
            <span class="bar-label" title="{label}">{label}</span>
            <div class="bar-container"><div class="bar" style="width:{pct:.1f}%;background:{color}"></div></div>
            <span class="bar-value">{val:,}</span></div>''')
    return '\n'.join(rows)


def _html_hourly_chart(hourly: list[dict]) -> str:
    """Gráfico de barras verticales para distribución horaria."""
    max_val = max(h['requests'] for h in hourly) if hourly else 1
    bars = []
    for h in hourly:
        pct = h['requests'] / max_val * 100 if max_val else 0
        bars.append(f'''<div class="hour-bar-wrapper" title="{h['hour']:02d}:00 — {h['requests']:,} pet. / {h['mp3_downloads']:,} MP3">
            <div class="hour-bar" style="height:{pct:.1f}%"></div>
            <span class="hour-label">{h['hour']:02d}</span></div>''')
    return '<div class="hour-chart">' + '\n'.join(bars) + '</div>'


def _html_table(headers: list[str], rows: list[list[str]], num_cols: set[int] | None = None) -> str:
    """Genera una tabla HTML."""
    if not rows:
        return '<p class="empty">Sin datos</p>'
    num_cols = num_cols or set()
    th = ''.join(f'<th>{h}</th>' for h in headers)
    trs = []
    for row in rows:
        tds = ''.join(
            f'<td class="num">{c}</td>' if i in num_cols else f'<td>{c}</td>'
            for i, c in enumerate(row)
        )
        trs.append(f'<tr>{tds}</tr>')
    return f'<table><thead><tr>{th}</tr></thead><tbody>{"".join(trs)}</tbody></table>'


def generate_html_report(data: dict) -> str:
    """Genera un informe HTML autocontenido."""
    s = data['summary']
    from_str = data['from_dt'].strftime('%Y-%m-%d %H:%M')
    to_str = data['to_dt'].strftime('%Y-%m-%d %H:%M')
    days_in_range = max(1, (data['to_dt'] - data['from_dt']).days)
    mp3_total = s['mp3_downloads'] or 0
    avg_daily = mp3_total / days_in_range if days_in_range else 0

    # Día pico
    peak_day = ''
    peak_downloads = 0
    for d in data['daily']:
        if (d['mp3_downloads'] or 0) > peak_downloads:
            peak_downloads = d['mp3_downloads'] or 0
            peak_day = d['date']

    # ── Secciones ──

    # Plataformas
    plat_items = [(p['platform'], p['downloads']) for p in data['platforms']]
    plat_total = sum(v for _, v in plat_items) or 1
    plat_html = ''
    for p, count in plat_items[:20]:
        pct = count / plat_total * 100
        bar_w = pct
        plat_html += f'''<div class="bar-row">
            <span class="bar-label">{p}</span>
            <div class="bar-container"><div class="bar" style="width:{bar_w:.1f}%;background:#e74c3c"></div></div>
            <span class="bar-value">{count:,} ({pct:.1f}%)</span></div>\n'''

    # Episodios
    ep_items = [(e['episode'], e['downloads']) for e in data['episodes']]

    # Transcripciones
    tr_items = [(t['page'], t['views']) for t in data['transcripts']]

    # Diario
    daily_headers = ['Fecha', 'Descargas MP3', 'Transcripciones', 'IPs únicas', 'Peticiones', 'Tráfico', 'RSS']
    daily_rows = [[d['date'], f"{d['mp3_downloads'] or 0:,}", f"{d['transcript_views'] or 0:,}",
                   f"{d['unique_ips'] or 0:,}", f"{d['total_requests'] or 0:,}",
                   format_bytes(d['total_bytes'] or 0), f"{d['rss_checks'] or 0:,}"]
                  for d in data['daily']]

    # Semanal
    weekly_headers = ['Semana', 'Descargas MP3', 'Transcripciones', 'Peticiones', 'Tráfico']
    weekly_rows = [[w['label'], f"{w['mp3_downloads']:,}", f"{w['transcript_views']:,}",
                    f"{w['total_requests']:,}", format_bytes(w['total_bytes'])]
                   for w in data['weekly']]

    # Mensual
    monthly_headers = ['Mes', 'Descargas MP3', 'Transcripciones', 'Peticiones', 'Tráfico']
    monthly_rows = [[m['label'], f"{m['mp3_downloads']:,}", f"{m['transcript_views']:,}",
                     f"{m['total_requests']:,}", format_bytes(m['total_bytes'])]
                    for m in data['monthly']]

    # IPs
    ip_headers = ['IP', 'País', 'Ciudad', 'Peticiones']
    ip_rows = [[i['ip'], i['country'] or '', i['city'] or '', f"{i['requests']:,}"]
               for i in data['top_ips']]

    # Países
    country_items = [(c['country'], c['requests']) for c in data['countries']]
    city_items = [(c['location'], c['requests']) for c in data['cities']]

    # Referers
    ref_items = [(r['referer'][:80], r['requests']) for r in data['referers']]

    # Status codes
    status_items = [(str(s['status']), s['requests']) for s in data['status_codes']]

    # Edge locations
    edge_items = [(e['edge_location'], e['requests']) for e in data['edge_locations']]

    # Día de la semana
    wd_items = [(w['label'], w['requests']) for w in data['weekday_dist']]
    wd_mp3 = [(w['label'], w['mp3_downloads']) for w in data['weekday_dist']]

    # ── Construir HTML ──

    geo_section = ''
    if data['countries']:
        geo_section = f'''
        <div class="two-col">
            <div class="section"><h2>Países</h2>{_html_bar_chart(country_items, '#1abc9c')}</div>
            <div class="section"><h2>Ciudades</h2>{_html_bar_chart(city_items, '#3498db')}</div>
        </div>'''

    # Precomputar tablas (evita problemas con sets en f-strings)
    _tbl_monthly = _html_table(monthly_headers, monthly_rows, {1, 2, 3})
    _tbl_weekly = _html_table(weekly_headers, weekly_rows, {1, 2, 3})
    _tbl_daily = _html_table(daily_headers, daily_rows, {1, 2, 3, 4, 6})
    _tbl_ips = _html_table(ip_headers, ip_rows, {3})

    html = f'''<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Estadísticas Podcast — {from_str} a {to_str}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f0f2f5;color:#333;padding:20px;max-width:1200px;margin:0 auto}}
h1{{text-align:center;margin:20px 0 5px;color:#2c3e50;font-size:1.6em}}
.period{{text-align:center;color:#888;font-size:.9em;margin-bottom:20px}}
.summary{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:20px 0}}
.card{{background:#fff;border-radius:10px;padding:18px 12px;text-align:center;box-shadow:0 2px 8px rgba(0,0,0,.06)}}
.card .number{{font-size:1.8em;font-weight:700;color:#4a90d9}}
.card .label{{font-size:.82em;color:#888;margin-top:4px}}
.section{{background:#fff;border-radius:10px;padding:18px;margin:18px 0;box-shadow:0 2px 8px rgba(0,0,0,.06)}}
.section h2{{color:#2c3e50;margin-bottom:12px;border-bottom:2px solid #4a90d9;padding-bottom:6px;font-size:1.15em}}
.bar-row{{display:flex;align-items:center;margin:3px 0}}
.bar-label{{width:200px;font-size:.82em;text-align:right;padding-right:10px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.bar-container{{flex:1;background:#eee;border-radius:3px;height:18px}}
.bar{{height:100%;border-radius:3px;transition:width .3s;min-width:2px}}
.bar-value{{width:110px;text-align:right;font-size:.82em;font-weight:600;padding-left:8px}}
.hour-chart{{display:flex;align-items:flex-end;height:140px;gap:2px;padding:10px 0}}
.hour-bar-wrapper{{flex:1;display:flex;flex-direction:column;align-items:center;height:100%;justify-content:flex-end}}
.hour-bar{{width:100%;background:#4a90d9;border-radius:2px 2px 0 0;min-height:2px;transition:height .3s}}
.hour-label{{font-size:.65em;color:#888;margin-top:3px}}
table{{width:100%;border-collapse:collapse;margin:8px 0;font-size:.85em}}
th{{background:#f8f9fa;padding:7px 10px;text-align:left;color:#555;font-weight:600;position:sticky;top:0}}
td{{padding:5px 10px;border-bottom:1px solid #eee}}
td.num{{text-align:right;font-weight:600}}
tr:hover{{background:#f8f9fa}}
.table-scroll{{max-height:400px;overflow-y:auto}}
.two-col{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}
.tabs{{display:flex;gap:0;margin-bottom:0;border-bottom:2px solid #e0e0e0}}
.tab-btn{{padding:8px 18px;border:none;background:transparent;cursor:pointer;font-size:.9em;color:#888;border-bottom:2px solid transparent;margin-bottom:-2px;transition:all .2s}}
.tab-btn.active{{color:#4a90d9;border-bottom-color:#4a90d9;font-weight:600}}
.tab-content{{display:none;padding-top:12px}}
.tab-content.active{{display:block}}
.empty{{color:#aaa;font-style:italic;padding:10px}}
.footer{{text-align:center;color:#aaa;font-size:.75em;margin:30px 0 10px}}
@media(max-width:700px){{.two-col{{grid-template-columns:1fr}}.bar-label{{width:120px}}}}
</style>
</head>
<body>
<h1>Estadísticas del Podcast</h1>
<p class="period">{from_str} — {to_str} UTC</p>

<div class="summary">
  <div class="card"><div class="number">{mp3_total:,}</div><div class="label">Descargas MP3</div></div>
  <div class="card"><div class="number">{s['transcript_views'] or 0:,}</div><div class="label">Transcripciones</div></div>
  <div class="card"><div class="number">{s['unique_ips'] or 0:,}</div><div class="label">IPs únicas</div></div>
  <div class="card"><div class="number">{format_bytes(s['total_bytes'] or 0)}</div><div class="label">Tráfico total</div></div>
  <div class="card"><div class="number">{avg_daily:.1f}</div><div class="label">Media diaria MP3</div></div>
  <div class="card"><div class="number">{s['rss_checks'] or 0:,}</div><div class="label">Checks RSS</div></div>
  <div class="card"><div class="number">{s['total_requests'] or 0:,}</div><div class="label">Peticiones totales</div></div>
  <div class="card"><div class="number">{peak_day}</div><div class="label">Día pico ({peak_downloads:,} MP3)</div></div>
</div>

<div class="section">
  <h2>Plataformas de Podcast (descargas MP3)</h2>
  {plat_html if plat_html else '<p class="empty">Sin descargas MP3</p>'}
</div>

<div class="section">
  <h2>Episodios más descargados</h2>
  {_html_bar_chart(ep_items, '#27ae60')}
</div>

<div class="section">
  <h2>Desglose temporal</h2>
  <div class="tabs" id="timeTabs">
    <button class="tab-btn active" onclick="showTab('monthly')">Mensual</button>
    <button class="tab-btn" onclick="showTab('weekly')">Semanal</button>
    <button class="tab-btn" onclick="showTab('daily')">Diario</button>
  </div>
  <div class="tab-content active" id="tab-monthly">
    {_tbl_monthly}
  </div>
  <div class="tab-content" id="tab-weekly">
    <div class="table-scroll">{_tbl_weekly}</div>
  </div>
  <div class="tab-content" id="tab-daily">
    <div class="table-scroll">{_tbl_daily}</div>
  </div>
</div>

<div class="two-col">
  <div class="section">
    <h2>Distribución horaria (UTC)</h2>
    {_html_hourly_chart(data['hourly_dist'])}
  </div>
  <div class="section">
    <h2>Día de la semana</h2>
    {_html_bar_chart(wd_items, '#9b59b6', 7)}
    <p style="margin-top:8px;font-size:.82em;color:#888">MP3 por día de la semana:</p>
    {_html_bar_chart(wd_mp3, '#e67e22', 7)}
  </div>
</div>

{geo_section}

<div class="two-col">
  <div class="section">
    <h2>Transcripciones más vistas</h2>
    {_html_bar_chart(tr_items, '#8e44ad')}
  </div>
  <div class="section">
    <h2>Top Referers</h2>
    {_html_bar_chart(ref_items, '#2980b9')}
  </div>
</div>

<div class="section">
  <h2>Top IPs</h2>
  <div class="table-scroll">{_tbl_ips}</div>
</div>

<div class="two-col">
  <div class="section">
    <h2>Códigos HTTP</h2>
    {_html_bar_chart(status_items, '#f39c12')}
  </div>
  <div class="section">
    <h2>Edge Locations</h2>
    {_html_bar_chart(edge_items, '#34495e')}
  </div>
</div>

<p class="footer">Generado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} — podcast_stats.py</p>

<script>
function showTab(name) {{
  document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  event.target.classList.add('active');
}}
</script>
</body>
</html>'''
    return html


# ═══════════════════════════════════════════════════════════════════════════════
# Generador de informe texto
# ═══════════════════════════════════════════════════════════════════════════════

def generate_text_report(data: dict) -> str:
    """Genera un informe en texto plano."""
    s = data['summary']
    from_str = data['from_dt'].strftime('%Y-%m-%d %H:%M')
    to_str = data['to_dt'].strftime('%Y-%m-%d %H:%M')
    sep = '=' * 72
    sec = '-' * 72
    lines = [
        sep, '  INFORME DE ESTADÍSTICAS DEL PODCAST', sep,
        f'  Período:           {from_str}  →  {to_str} UTC',
        f'  Peticiones totales: {s["total_requests"] or 0:,}',
        f'  IPs únicas:         {s["unique_ips"] or 0:,}',
        f'  Tráfico total:      {format_bytes(s["total_bytes"] or 0)}', '',
        sec, '  DESCARGAS MP3', sec,
        f'  Total:              {s["mp3_downloads"] or 0:,}',
        f'  Tráfico MP3:        {format_bytes(s["mp3_bytes"] or 0)}', '',
    ]

    days_in_range = max(1, (data['to_dt'] - data['from_dt']).days)
    avg = (s['mp3_downloads'] or 0) / days_in_range
    lines.append(f'  Media diaria:       {avg:.1f}')
    lines.append('')

    # Mensual
    if data['monthly']:
        lines += [sec, '  DESGLOSE MENSUAL', sec]
        for m in data['monthly']:
            lines.append(f"    {m['label']:<25} MP3: {m['mp3_downloads']:>5}  Trans: {m['transcript_views']:>5}  "
                         f"Pet: {m['total_requests']:>6}  {format_bytes(m['total_bytes']):>10}")
        lines.append('')

    # Semanal
    if data['weekly']:
        lines += [sec, '  DESGLOSE SEMANAL (lunes a domingo)', sec]
        for w in data['weekly']:
            lines.append(f"    {w['label']:<30} MP3: {w['mp3_downloads']:>5}  Trans: {w['transcript_views']:>5}  "
                         f"Pet: {w['total_requests']:>6}")
        lines.append('')

    # Diario
    lines += [sec, '  DESGLOSE DIARIO', sec]
    for d in data['daily']:
        lines.append(f"    {d['date']}  MP3: {d['mp3_downloads'] or 0:>4}  Trans: {d['transcript_views'] or 0:>4}  "
                     f"IPs: {d['unique_ips'] or 0:>4}  Pet: {d['total_requests'] or 0:>5}  "
                     f"{format_bytes(d['total_bytes'] or 0):>10}")
    lines.append('')

    # Plataformas
    if data['platforms']:
        lines += [sec, '  PLATAFORMAS DE PODCAST (MP3)', sec]
        total_mp3 = s['mp3_downloads'] or 1
        for p in data['platforms']:
            pct = p['downloads'] / total_mp3 * 100
            bar = '█' * int(pct / 2.5)
            lines.append(f"    {p['platform']:<25} {p['downloads']:>5} ({pct:5.1f}%) {bar}")
        lines.append('')

    # Episodios
    if data['episodes']:
        lines += [sec, '  EPISODIOS MÁS DESCARGADOS', sec]
        for e in data['episodes']:
            lines.append(f"    {e['downloads']:>5}  {e['episode']}")
        lines.append('')

    # Transcripciones
    if data['transcripts']:
        lines += [sec, '  TRANSCRIPCIONES MÁS VISTAS', sec]
        for t in data['transcripts']:
            lines.append(f"    {t['views']:>5}  {t['page']}")
        lines.append('')

    # Horario
    lines += [sec, '  DISTRIBUCIÓN HORARIA (UTC)', sec]
    max_h = max((h['requests'] for h in data['hourly_dist']), default=1)
    for h in data['hourly_dist']:
        bar = '█' * int(h['requests'] / max_h * 40) if max_h else ''
        lines.append(f"    {h['hour']:02d}:00  {h['requests']:>5}  {bar}")
    lines.append('')

    # Día de la semana
    lines += [sec, '  DÍA DE LA SEMANA', sec]
    for w in data['weekday_dist']:
        lines.append(f"    {w['label']:<12} {w['requests']:>6} pet.  {w['mp3_downloads']:>5} MP3")
    lines.append('')

    # IPs
    if data['top_ips']:
        lines += [sec, '  TOP IPs', sec]
        for i in data['top_ips']:
            loc = f" ({i['country']}, {i['city']})" if i.get('country') else ''
            lines.append(f"    {i['ip']:<40} {i['requests']:>5}{loc}")
        lines.append('')

    # Geolocalización
    if data['countries']:
        lines += [sec, '  PAÍSES', sec]
        for c in data['countries']:
            lines.append(f"    {c['country']:<30} {c['requests']:>5}")
        lines.append('')

    # Referers
    if data['referers']:
        lines += [sec, '  REFERERS', sec]
        for r in data['referers']:
            lines.append(f"    {r['requests']:>5}  {r['referer'][:70]}")
        lines.append('')

    # Status
    lines += [sec, '  CÓDIGOS HTTP', sec]
    for sc in data['status_codes']:
        lines.append(f"    {sc['status']:>3}: {sc['requests']:>7}")
    lines.append('')

    lines += [sep, f'  Generado: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}', sep]
    return '\n'.join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# Proceso de actualización
# ═══════════════════════════════════════════════════════════════════════════════

def do_update(db: StatsDB, bucket: str, prefix: str, region: str,
              geoip_path: str | None, verbose: bool = False):
    """Actualiza la DB descargando y procesando logs nuevos de S3."""
    last_update = db.get_last_update()
    if last_update:
        print(f'Última actualización: {last_update.isoformat()}')
    else:
        print('Primera ejecución: se descargarán todos los logs disponibles.')

    files_done, total_parsed, total_new = download_and_insert_logs(
        db, bucket, prefix, last_update, region, geoip_path
    )

    if total_parsed == 0:
        print('No hay registros nuevos.')

    # Actualizar timestamp de última ejecución
    # Usar el máximo timestamp de la DB (más robusto que los registros en memoria)
    mn, mx = db.get_date_range()
    if mx:
        db.set_last_update(datetime.fromisoformat(mx))
    else:
        db.set_last_update(datetime.now(timezone.utc).replace(tzinfo=None))

    total = db.get_record_count()
    print(f'Total en DB: {total:,} registros')


# ═══════════════════════════════════════════════════════════════════════════════
# Proceso de generación de informes
# ═══════════════════════════════════════════════════════════════════════════════

def do_report(db: StatsDB, from_dt: datetime, to_dt: datetime,
              output_dir: str, fmt: str, label: str = ''):
    """Genera informe(s) para el rango especificado."""
    total = db.get_record_count()
    if total == 0:
        print('La base de datos está vacía. Ejecuta primero con --update.')
        return

    print(f'Generando informe: {from_dt.strftime("%Y-%m-%d %H:%M")} → {to_dt.strftime("%Y-%m-%d %H:%M")}')
    data = build_report_data(db, from_dt, to_dt)

    if (data['summary']['total_requests'] or 0) == 0:
        print(f'  Sin datos para el rango seleccionado.')
        return

    os.makedirs(output_dir, exist_ok=True)
    date_str = datetime.now().strftime('%Y%m%d')

    if label:
        base = f'podcast_report_{label}_{date_str}'
    else:
        f_str = from_dt.strftime('%Y%m%d')
        t_str = to_dt.strftime('%Y%m%d')
        base = f'podcast_report_{f_str}_{t_str}'

    if fmt in ('html', 'both'):
        html = generate_html_report(data)
        path = os.path.join(output_dir, f'{base}.html')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(html)
        print(f'  HTML: {path}')

    if fmt in ('text', 'both'):
        text = generate_text_report(data)
        path = os.path.join(output_dir, f'{base}.txt')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)
        print(f'  Texto: {path}')

        # Imprimir también en consola si es solo texto
        if fmt == 'text':
            print()
            print(text)


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    # Defaults desde variables de entorno (.env/impact.env, .env/aws.env)
    bucket_name = os.environ.get('BUCKET_NAME', '')
    default_bucket = f'{bucket_name}-logs' if bucket_name else ''
    default_region = os.environ.get('AWS_REGION', 'eu-south-2')
    default_db = os.environ.get('IMPACT_DB', 'podcast_stats.db')
    default_geoip = os.environ.get('IMPACT_GEOIP_DB', '')

    parser = argparse.ArgumentParser(
        description='Estadísticas de impacto del podcast desde logs de CloudFront',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Variables de entorno (.env/impact.env, .env/aws.env):
  IMPACT_DB          Ruta a la base de datos SQLite
  IMPACT_GEOIP_DB    Ruta a GeoLite2-City.mmdb
  BUCKET_NAME        Nombre base del bucket S3 (se añade '-logs')
  AWS_REGION         Región AWS del bucket

Ejemplos:
  # Primera ejecución (usa valores de .env/):
  %(prog)s -u

  # Actualizar + informes estándar (1d, 7d, 31d):
  %(prog)s -u -r --standard

  # Informe de la última semana:
  %(prog)s -r --days 7

  # Sobreescribir bucket desde CLI:
  %(prog)s -u --bucket genred-jmrobles-logs
        '''
    )

    # Acciones
    actions = parser.add_argument_group('Acciones')
    actions.add_argument('-u', '--update', action='store_true',
                         help='Actualizar base de datos con logs nuevos de S3')
    actions.add_argument('-r', '--report', action='store_true',
                         help='Generar informe(s) desde la base de datos')

    # Rango temporal del informe
    rng = parser.add_argument_group('Rango del informe (mutuamente excluyentes)')
    rng_ex = rng.add_mutually_exclusive_group()
    rng_ex.add_argument('--hours', type=int, metavar='N', help='Últimas N horas')
    rng_ex.add_argument('--days', type=int, metavar='N', help='Últimos N días')
    rng_ex.add_argument('--months', type=int, metavar='N', help='Últimos N meses')
    rng_ex.add_argument('--all', action='store_true', help='Todos los datos disponibles')
    rng_ex.add_argument('--standard', action='store_true',
                        help='Genera 3 informes: último día, 7 días y 31 días')
    rng.add_argument('--from', dest='from_dt', metavar='FECHA',
                     help="Inicio (YYYY-MM-DD o 'YYYY-MM-DD HH:MM'). Combinable con --to")
    rng.add_argument('--to', dest='to_dt', metavar='FECHA',
                     help="Fin (YYYY-MM-DD o 'YYYY-MM-DD HH:MM'). Default: ahora")

    # Opciones S3
    s3g = parser.add_argument_group('S3')
    s3g.add_argument('--bucket', default=default_bucket,
                     help=f'Nombre del bucket S3 de logs (default: {default_bucket!r})')
    s3g.add_argument('--prefix', default='cloudfront/', help='Prefijo S3 (default: cloudfront/)')
    s3g.add_argument('--region', default=default_region,
                     help=f'Región AWS del bucket de logs (default: {default_region})')

    # Opciones generales
    gen = parser.add_argument_group('General')
    gen.add_argument('--db', default=default_db,
                     help=f'Ruta a la base de datos SQLite (default: {default_db})')
    gen.add_argument('--output-dir', default='reports', help='Directorio para informes (default: reports/)')
    gen.add_argument('--format', choices=['html', 'text', 'both'], default='html',
                     help='Formato del informe (default: html)')
    gen.add_argument('--geoip-db', default=default_geoip or None,
                     help=f'Ruta a GeoLite2-City.mmdb (default: {default_geoip!r})')
    gen.add_argument('-v', '--verbose', action='store_true', help='Salida detallada')

    args = parser.parse_args()

    # Si no se indica acción, hacer ambas
    if not args.update and not args.report:
        args.update = True
        args.report = True
    # Imprimir argumentos para debug
    if args.verbose:
        print('Argumentos:', args)
    # Validar bucket si se necesita update
    bucket = args.bucket
    if args.update:
        if not bucket:
            bucket = get_bucket_from_terraform()
        if not bucket:
            parser.error('Se necesita --bucket para actualizar. '
                         'No se pudo auto-detectar desde terraform output.')

    # Abrir DB
    db = StatsDB(args.db)

    try:
        # ── Update ──
        if args.update:
            print('\n=== ACTUALIZACIÓN DE BASE DE DATOS ===\n')
            do_update(db, bucket, args.prefix, args.region, args.geoip_db, args.verbose)

        # ── Report ──
        if args.report:
            print('\n=== GENERACIÓN DE INFORMES ===\n')

            now = datetime.now(timezone.utc).replace(tzinfo=None)

            if args.standard:
                # 3 informes estándar
                for days, label in [(1, '1d'), (7, '7d'), (31, '31d')]:
                    from_dt = now - timedelta(days=days)
                    do_report(db, from_dt, now, args.output_dir, args.format, label)
                    print()

            elif args.from_dt:
                # Rango personalizado con --from [--to]
                from_dt = parse_datetime_arg(args.from_dt)
                to_dt = parse_datetime_arg(args.to_dt) if args.to_dt else now
                do_report(db, from_dt, to_dt, args.output_dir, args.format)

            elif args.hours:
                from_dt = now - timedelta(hours=args.hours)
                do_report(db, from_dt, now, args.output_dir, args.format, f'{args.hours}h')

            elif args.months:
                from_dt = now - timedelta(days=args.months * 30)
                do_report(db, from_dt, now, args.output_dir, args.format, f'{args.months}m')

            elif args.all:
                mn, mx = db.get_date_range()
                if mn:
                    from_dt = datetime.fromisoformat(mn)
                    to_dt = datetime.fromisoformat(mx) if mx else now
                    do_report(db, from_dt, to_dt, args.output_dir, args.format, 'all')
                else:
                    print('No hay datos en la base de datos.')

            elif args.days:
                from_dt = now - timedelta(days=args.days)
                do_report(db, from_dt, now, args.output_dir, args.format, f'{args.days}d')

            else:
                # Default: últimos 7 días
                from_dt = now - timedelta(days=7)
                do_report(db, from_dt, now, args.output_dir, args.format, '7d')

        print('\nHecho.')

    finally:
        db.close()


if __name__ == '__main__':
    main()
