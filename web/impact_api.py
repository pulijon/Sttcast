#!/usr/bin/env python3
"""
impact_api.py — Dashboard interactivo de estadísticas de impacto del podcast.

API REST (FastAPI) + Dashboard HTML con Chart.js.
Consume datos de la base de datos de impacto generada por podcast_stats.py.

Configuración por variables de entorno (.env/impact.env):
    IMPACT_SERVER_HOST   Host del servidor (default: 0.0.0.0)
    IMPACT_SERVER_PORT   Puerto (default: 8343)
    IMPACT_DB            Ruta a la base de datos SQLite de impacto
    IMPACT_GEOIP_DB      Ruta a GeoLite2-City.mmdb

Uso:
    python impact_api.py                           # Usa valores de .env/impact.env
    python impact_api.py --port 9000               # Sobreescribe el puerto
    python impact_api.py --root-path /impacto      # Detrás de reverse proxy
    uvicorn impact_api:app --reload                # Desarrollo

Endpoints:
    GET /                               Dashboard interactivo
    GET /api/v1/meta/date-range         Rango de fechas disponible
    GET /api/v1/summary                 KPIs principales
    GET /api/v1/downloads/trend         Tendencia diaria de descargas
    GET /api/v1/downloads/by-episode    Descargas por episodio
    GET /api/v1/platforms               Distribución por plataforma
    GET /api/v1/geo/countries           Top países
    GET /api/v1/geo/cities              Top ciudades
    GET /api/v1/temporal/hours          Distribución por hora del día
    GET /api/v1/temporal/weekdays       Distribución por día de la semana
    GET /api/v1/engagement              Descargas completas vs parciales
"""

import argparse
import os
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path

# ── Cargar variables de entorno desde .env/ ──────────────────────────────
_project_root = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, _project_root)

from tools.envvars import load_env_vars_from_directory
load_env_vars_from_directory(os.path.join(_project_root, '.env'))

# ── FastAPI imports ──────────────────────────────────────────────────────
from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

# ═══════════════════════════════════════════════════════════════════════════════
# Configuración (valores de .env/impact.env como defaults)
# ═══════════════════════════════════════════════════════════════════════════════

DB_PATH = os.environ.get(
    'IMPACT_DB',
    str(Path(__file__).parent / 'podcast_stats.db'),
)

# Plataformas clasificadas como bots (no representan oyentes reales)
BOT_PLATFORMS = [
    'Bot buscador',
    'Automatizado/CLI',
    'Facebook Bot',
    'Podchaser',
]

DIAS_SEMANA = ['Lunes', 'Martes', 'Miércoles', 'Jueves',
               'Viernes', 'Sábado', 'Domingo']

# ═══════════════════════════════════════════════════════════════════════════════
# FastAPI App
# ═══════════════════════════════════════════════════════════════════════════════

app = FastAPI(
    title="Podcast Impact API",
    description="Dashboard interactivo de estadísticas de impacto del podcast",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ═══════════════════════════════════════════════════════════════════════════════
# Base de datos
# ═══════════════════════════════════════════════════════════════════════════════

@contextmanager
def get_db():
    """Context manager para conexión SQLite de solo lectura."""
    conn = sqlite3.connect(f'file:{DB_PATH}?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _where(from_date: str | None, to_date: str | None,
           exclude_bots: bool, resource_type: str = 'mp3') -> tuple[str, list]:
    """Construye WHERE clause con filtros comunes.

    Devuelve (clause_sql, params).
    """
    clauses = []
    params = []

    if resource_type:
        clauses.append("resource_type = ?")
        params.append(resource_type)

    clauses.append("status IN (200, 206)")

    if exclude_bots:
        ph = ','.join('?' * len(BOT_PLATFORMS))
        clauses.append(f"platform NOT IN ({ph})")
        params.extend(BOT_PLATFORMS)

    if from_date:
        clauses.append("date >= ?")
        params.append(from_date)

    if to_date:
        clauses.append("date <= ?")
        params.append(to_date)

    return 'WHERE ' + ' AND '.join(clauses), params


# ═══════════════════════════════════════════════════════════════════════════════
# Endpoints — Meta
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/v1/meta/date-range")
def api_date_range():
    """Devuelve el rango de fechas disponible en la base de datos."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT MIN(date) as min_date, MAX(date) as max_date, "
            "COUNT(*) as total FROM requests"
        ).fetchone()
        return {
            "min_date": row['min_date'],
            "max_date": row['max_date'],
            "total_records": row['total'],
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Endpoints — Summary
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/v1/summary")
def api_summary(
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
    exclude_bots: bool = Query(True),
):
    """KPIs principales: descargas únicas, totales, episodios, media diaria."""
    where, params = _where(from_date, to_date, exclude_bots)

    with get_db() as conn:
        row = conn.execute(
            f"SELECT "
            f"  COUNT(*) as total, "
            f"  COUNT(DISTINCT ip || '|' || resource_name || '|' || date) as unique_dl, "
            f"  COUNT(DISTINCT resource_name) as episodes, "
            f"  COALESCE(SUM(bytes_sent), 0) as total_bytes, "
            f"  COUNT(DISTINCT date) as active_days "
            f"FROM requests {where}", params
        ).fetchone()

        active_days = max(row['active_days'], 1)

        return {
            "total_requests": row['total'],
            "unique_downloads": row['unique_dl'],
            "episodes": row['episodes'],
            "avg_per_day": round(row['unique_dl'] / active_days, 1),
            "total_bytes": row['total_bytes'],
            "active_days": active_days,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Endpoints — Downloads
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/v1/downloads/trend")
def api_downloads_trend(
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
    exclude_bots: bool = Query(True),
):
    """Tendencia diaria de descargas (totales y únicas)."""
    where, params = _where(from_date, to_date, exclude_bots)

    with get_db() as conn:
        rows = conn.execute(
            f"SELECT date, "
            f"  COUNT(*) as total, "
            f"  COUNT(DISTINCT ip || '|' || resource_name) as unique_dl "
            f"FROM requests {where} "
            f"GROUP BY date ORDER BY date", params
        ).fetchall()

        return {
            "dates": [r['date'] for r in rows],
            "total": [r['total'] for r in rows],
            "unique": [r['unique_dl'] for r in rows],
        }


@app.get("/api/v1/downloads/by-episode")
def api_downloads_by_episode(
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
    exclude_bots: bool = Query(True),
):
    """Descargas desglosadas por episodio."""
    where, params = _where(from_date, to_date, exclude_bots)

    with get_db() as conn:
        rows = conn.execute(
            f"SELECT resource_name as episode, "
            f"  COUNT(*) as total, "
            f"  COUNT(DISTINCT ip || '|' || date) as unique_dl "
            f"FROM requests {where} "
            f"GROUP BY resource_name ORDER BY unique_dl DESC", params
        ).fetchall()

        return [
            {"episode": r['episode'], "total": r['total'], "unique": r['unique_dl']}
            for r in rows
        ]


# ═══════════════════════════════════════════════════════════════════════════════
# Endpoints — Platforms
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/v1/platforms")
def api_platforms(
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
    exclude_bots: bool = Query(True),
):
    """Distribución de descargas por plataforma de podcast."""
    where, params = _where(from_date, to_date, exclude_bots)

    with get_db() as conn:
        rows = conn.execute(
            f"SELECT platform, "
            f"  COUNT(DISTINCT ip || '|' || resource_name || '|' || date) as downloads "
            f"FROM requests {where} "
            f"GROUP BY platform ORDER BY downloads DESC", params
        ).fetchall()

        return [
            {"platform": r['platform'], "downloads": r['downloads']}
            for r in rows
        ]


# ═══════════════════════════════════════════════════════════════════════════════
# Endpoints — Geografía
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/v1/geo/countries")
def api_geo_countries(
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
    exclude_bots: bool = Query(True),
    limit: int = Query(15),
):
    """Top países por descargas únicas."""
    where, params = _where(from_date, to_date, exclude_bots)

    with get_db() as conn:
        rows = conn.execute(
            f"SELECT CASE WHEN country = '' THEN '(Desconocido)' ELSE country END as country, "
            f"  COUNT(DISTINCT ip || '|' || resource_name || '|' || date) as downloads "
            f"FROM requests {where} "
            f"GROUP BY country ORDER BY downloads DESC LIMIT ?",
            params + [limit]
        ).fetchall()

        return [
            {"country": r['country'], "downloads": r['downloads']}
            for r in rows
        ]


@app.get("/api/v1/geo/cities")
def api_geo_cities(
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
    exclude_bots: bool = Query(True),
    limit: int = Query(15),
):
    """Top ciudades por descargas únicas."""
    where, params = _where(from_date, to_date, exclude_bots)

    with get_db() as conn:
        rows = conn.execute(
            f"SELECT "
            f"  CASE WHEN city = '' AND country = '' THEN '(Desconocido)' "
            f"       WHEN city = '' THEN country "
            f"       ELSE city || ', ' || country END as location, "
            f"  COUNT(DISTINCT ip || '|' || resource_name || '|' || date) as downloads "
            f"FROM requests {where} "
            f"GROUP BY location ORDER BY downloads DESC LIMIT ?",
            params + [limit]
        ).fetchall()

        return [
            {"city": r['location'], "downloads": r['downloads']}
            for r in rows
        ]


# ═══════════════════════════════════════════════════════════════════════════════
# Endpoints — Temporal
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/v1/temporal/hours")
def api_temporal_hours(
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
    exclude_bots: bool = Query(True),
):
    """Distribución de descargas por hora del día (0-23)."""
    where, params = _where(from_date, to_date, exclude_bots)

    with get_db() as conn:
        rows = conn.execute(
            f"SELECT hour, COUNT(*) as downloads "
            f"FROM requests {where} "
            f"GROUP BY hour ORDER BY hour", params
        ).fetchall()

        # Rellenar horas sin datos con 0
        hour_map = {r['hour']: r['downloads'] for r in rows}
        hours = list(range(24))
        values = [hour_map.get(h, 0) for h in hours]

        return {
            "hours": [f'{h:02d}:00' for h in hours],
            "values": values,
        }


@app.get("/api/v1/temporal/weekdays")
def api_temporal_weekdays(
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
    exclude_bots: bool = Query(True),
):
    """Distribución de descargas por día de la semana."""
    where, params = _where(from_date, to_date, exclude_bots)

    with get_db() as conn:
        rows = conn.execute(
            f"SELECT weekday, COUNT(*) as downloads "
            f"FROM requests {where} "
            f"GROUP BY weekday ORDER BY weekday", params
        ).fetchall()

        wd_map = {r['weekday']: r['downloads'] for r in rows}
        values = [wd_map.get(i, 0) for i in range(7)]

        return {
            "weekdays": DIAS_SEMANA,
            "values": values,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Endpoints — Engagement
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/v1/engagement")
def api_engagement(
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
    exclude_bots: bool = Query(True),
):
    """Métricas de engagement: descargas completas vs parciales por episodio.

    Estima el porcentaje de escucha basándose en bytes descargados vs
    tamaño total del fichero (MAX bytes_sent con status 200).
    """
    where, params = _where(from_date, to_date, exclude_bots)

    with get_db() as conn:
        # Primero obtener tamaño de fichero por episodio (max bytes con status 200)
        sizes = conn.execute(
            "SELECT resource_name, MAX(bytes_sent) as file_size "
            "FROM requests WHERE resource_type = 'mp3' AND status = 200 "
            "GROUP BY resource_name"
        ).fetchall()
        size_map = {r['resource_name']: r['file_size'] for r in sizes}

        # Métricas por episodio
        rows = conn.execute(
            f"SELECT resource_name as episode, "
            f"  COUNT(*) as total, "
            f"  SUM(CASE WHEN status = 200 THEN 1 ELSE 0 END) as full_dl, "
            f"  SUM(CASE WHEN status = 206 THEN 1 ELSE 0 END) as partial_dl, "
            f"  AVG(bytes_sent) as avg_bytes "
            f"FROM requests {where} "
            f"GROUP BY resource_name ORDER BY total DESC", params
        ).fetchall()

        result = []
        for r in rows:
            file_size = size_map.get(r['episode'], 0)
            avg_completion = 0.0
            if file_size > 0:
                avg_completion = min(100.0, round(r['avg_bytes'] * 100.0 / file_size, 1))

            result.append({
                "episode": r['episode'],
                "total": r['total'],
                "full": r['full_dl'],
                "partial": r['partial_dl'],
                "pct_full": round(r['full_dl'] * 100.0 / max(r['total'], 1), 1),
                "avg_completion": avg_completion,
                "file_size": file_size,
            })

        return result


# ═══════════════════════════════════════════════════════════════════════════════
# Dashboard HTML
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    """Sirve el dashboard HTML interactivo."""
    html_path = Path(__file__).parent / "templates" / "dashboard.html"
    if not html_path.exists():
        return HTMLResponse(
            "<h1>Error</h1><p>No se encuentra templates/dashboard.html</p>",
            status_code=404,
        )
    html = html_path.read_text(encoding='utf-8')
    # Inyectar root_path para que el JS sepa la base de la API
    root_path = request.scope.get('root_path', '')
    html = html.replace(
        '/* __ROOT_PATH__ */',
        f'const API_BASE = "{root_path}/api/v1";',
    )
    return HTMLResponse(html)


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    import uvicorn

    # Defaults desde variables de entorno (.env/impact.env)
    default_host = os.environ.get('IMPACT_SERVER_HOST', '0.0.0.0')
    default_port = int(os.environ.get('IMPACT_SERVER_PORT', '8343'))
    default_db = os.environ.get('IMPACT_DB', str(Path(__file__).parent / 'podcast_stats.db'))
    default_geoip = os.environ.get('IMPACT_GEOIP_DB', '')
    default_root_path = os.environ.get('IMPACT_ROOT_PATH', '')

    parser = argparse.ArgumentParser(
        description='Dashboard de estadísticas de impacto del podcast',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            'Variables de entorno (.env/impact.env):\n'
            '  IMPACT_SERVER_HOST   Host del servidor\n'
            '  IMPACT_SERVER_PORT   Puerto del servidor\n'
            '  IMPACT_DB            Ruta a la base de datos SQLite\n'
            '  IMPACT_GEOIP_DB     Ruta a GeoLite2-City.mmdb\n'
            '  IMPACT_ROOT_PATH    Root path para reverse proxy\n'
        ),
    )
    parser.add_argument('--host', default=default_host,
                        help=f'Host (default: {default_host})')
    parser.add_argument('--port', type=int, default=default_port,
                        help=f'Puerto (default: {default_port})')
    parser.add_argument('--db', default=default_db,
                        help=f'Ruta a la base de datos (default: {default_db})')
    parser.add_argument('--geoip-db', default=default_geoip,
                        help=f'Ruta a GeoLite2-City.mmdb (default: {default_geoip})')
    parser.add_argument('--reload', action='store_true',
                        help='Auto-reload en desarrollo')
    parser.add_argument('--root-path', default=default_root_path,
                        help=f'Root path para reverse proxy (default: {default_root_path!r})')
    args = parser.parse_args()

    # Aplicar la DB seleccionada
    global DB_PATH
    DB_PATH = args.db

    print(f'\n  Podcast Impact Dashboard')
    print(f'  http://{args.host}:{args.port}{args.root_path}')
    print(f'  DB: {DB_PATH}')
    if args.geoip_db:
        print(f'  GeoIP: {args.geoip_db}')
    print()

    uvicorn.run(
        'impact_api:app',
        host=args.host,
        port=args.port,
        reload=args.reload,
        root_path=args.root_path,
    )


if __name__ == '__main__':
    main()
