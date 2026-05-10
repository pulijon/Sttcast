#!/usr/bin/env python3
"""
Calcula estadisticas de total_matches para /getcontextbyd sobre consultas guardadas.
"""

import argparse
import asyncio
import os
import statistics
import sys
from pathlib import Path
from typing import List

import requests

CURRENT_DIR = os.path.dirname(__file__)
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from api.apihmac import create_auth_headers, serialize_body
from tools.envvars import load_env_vars_from_directory

DEFAULT_THRESHOLDS = [0.6, 0.65, 0.7]
ENV_THRESHOLDS = "CONTEXT_DISTANCE_THRESHOLDS"
ENV_LIMIT = "CONTEXT_STATS_LIMIT"
ENV_OFFSET = "CONTEXT_STATS_OFFSET"
ENV_TIMEOUT = "CONTEXT_STATS_TIMEOUT"
ENV_PROGRESS_EVERY = "CONTEXT_STATS_PROGRESS_EVERY"


class DefaultsRawHelpFormatter(
    argparse.ArgumentDefaultsHelpFormatter,
    argparse.RawDescriptionHelpFormatter,
):
    pass


def percentile(values: List[int], p: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    k = (len(ordered) - 1) * p / 100.0
    lower = int(k)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (k - lower)


def parse_vector(value) -> List[float]:
    if value is None:
        return []
    if isinstance(value, list):
        return [float(item) for item in value]
    text = str(value).strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    if not text:
        return []
    return [float(item) for item in text.split(",")]


def env_int(name: str, default: int | None = None) -> int | None:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return int(value)


def env_thresholds() -> List[float]:
    value = os.getenv(ENV_THRESHOLDS)
    if not value:
        return DEFAULT_THRESHOLDS
    return [
        float(item.strip())
        for item in value.replace(";", ",").split(",")
        if item.strip()
    ]


def parse_args() -> argparse.Namespace:
    default_podcast = os.getenv("PODCAST_NAME")
    default_limit = env_int(ENV_LIMIT)
    default_offset = env_int(ENV_OFFSET, 0)
    default_timeout = env_int(ENV_TIMEOUT, 120)
    default_progress_every = env_int(ENV_PROGRESS_EVERY, 25)
    default_thresholds = env_thresholds()

    parser = argparse.ArgumentParser(
        description=(
            "Calcula cuantos fragmentos devolveria /getcontextbyd para cada "
            "consulta guardada y para uno o varios umbrales de distancia coseno."
        ),
        formatter_class=DefaultsRawHelpFormatter,
        epilog=f"""
Variables de entorno usadas como valores por defecto:
  PODCAST_NAME                         default de --podcast-name
  {ENV_THRESHOLDS}       lista de umbrales separada por comas
  {ENV_LIMIT}             default de --limit
  {ENV_OFFSET}            default de --offset
  {ENV_TIMEOUT}           default de --timeout
  {ENV_PROGRESS_EVERY}   default de --progress-every

Tambien usa la configuracion comun cargada desde .env/*.env:
  QUERIESDB_HOST, QUERIESDB_PORT, QUERIESDB_DB, QUERIESDB_USER,
  QUERIESDB_PASSWORD, CONTEXT_SERVER_HOST, CONTEXT_SERVER_PORT,
  CONTEXT_SERVER_API_KEY.

Ejemplos:
  %(prog)s
  %(prog)s --thresholds 0.45 0.50 0.55 0.60
  %(prog)s --thresholds 0.6 --limit 25
  %(prog)s --all-podcasts --progress-every 100
""",
    )
    parser.add_argument(
        "--thresholds",
        nargs="+",
        type=float,
        default=default_thresholds,
        help=f"umbrales de distancia coseno; tambien admite {ENV_THRESHOLDS}=0.6,0.65,0.7",
    )
    parser.add_argument(
        "--podcast-name",
        default=default_podcast,
        help="podcast_name a analizar; por defecto usa PODCAST_NAME",
    )
    parser.add_argument(
        "--all-podcasts",
        action="store_true",
        help="ignora --podcast-name y analiza todas las consultas con embedding",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=default_limit,
        help="numero maximo de consultas a procesar",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=default_offset,
        help="offset inicial sobre las consultas seleccionadas",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=default_timeout,
        help="timeout en segundos para cada llamada a /getcontextbyd",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=default_progress_every,
        help="muestra progreso cada N consultas; usa 0 para desactivarlo",
    )
    return parser.parse_args()


def context_url_from_env() -> str:
    return "http://{}:{}/getcontextbyd".format(
        os.getenv("CONTEXT_SERVER_HOST", "localhost"),
        os.getenv("CONTEXT_SERVER_PORT"),
    )


def get_total_matches(context_url: str, api_key: str, query: str, embedding: List[float], threshold: float, timeout: int) -> int:
    payload = {
        "query": query,
        "query_embedding": embedding,
        "distance_threshold": threshold,
        "max_fragments": 1,
    }
    headers = create_auth_headers(
        api_key,
        "POST",
        "/getcontextbyd",
        payload,
        "threshold_match_stats",
    )
    response = requests.post(
        context_url,
        data=serialize_body(payload),
        headers=headers,
        timeout=timeout,
    )
    if response.status_code == 404:
        return 0
    response.raise_for_status()
    return int(response.json().get("total_matches", 0))


def print_stats(threshold: float, values: List[int]) -> None:
    print()
    print(f"Umbral {threshold}")
    print(f"n:       {len(values)}")
    print(f"min:     {min(values)}")
    print(f"media:   {statistics.mean(values):.2f}")
    print(f"mediana: {percentile(values, 50):.2f}")
    print(f"p75:     {percentile(values, 75):.2f}")
    print(f"p90:     {percentile(values, 90):.2f}")
    print(f"p95:     {percentile(values, 95):.2f}")
    print(f"p99:     {percentile(values, 99):.2f}")
    print(f"max:     {max(values)}")
    for cutoff in [10, 20, 50, 100, 250, 500, 1000, 5000, 10000]:
        count = sum(value <= cutoff for value in values)
        print(f"<= {cutoff:5d}: {count:4d}/{len(values)} ({100.0 * count / len(values):6.2f}%)")


def format_query_for_line(query_text: str) -> str:
    return " ".join((query_text or "").split())


async def fetch_queries(conn, podcast_name: str | None, limit: int | None, offset: int):
    if podcast_name:
        sql = """
            SELECT id, query_text, query_embedding
            FROM rag_queries
            WHERE podcast_name = $1 AND query_embedding IS NOT NULL
            ORDER BY created_at ASC, id ASC
            LIMIT $2 OFFSET $3;
        """
        return await conn.fetch(sql, podcast_name, limit or 2_147_483_647, offset)

    sql = """
        SELECT id, query_text, query_embedding
        FROM rag_queries
        WHERE query_embedding IS NOT NULL
        ORDER BY created_at ASC, id ASC
        LIMIT $1 OFFSET $2;
    """
    return await conn.fetch(sql, limit or 2_147_483_647, offset)


async def main() -> int:
    load_env_vars_from_directory(Path(PROJECT_ROOT) / ".env")

    try:
        import asyncpg
    except ImportError:
        print("Error: asyncpg no esta instalado.", file=sys.stderr)
        return 1

    args = parse_args()
    podcast_name = None if args.all_podcasts else args.podcast_name
    context_url = context_url_from_env()
    api_key = os.getenv("CONTEXT_SERVER_API_KEY")
    if not api_key:
        print("Error: CONTEXT_SERVER_API_KEY no esta configurado.", file=sys.stderr)
        return 1

    conn = await asyncpg.connect(
        host=os.getenv("QUERIESDB_HOST"),
        port=int(os.getenv("QUERIESDB_PORT", "5432")),
        user=os.getenv("QUERIESDB_USER"),
        password=os.getenv("QUERIESDB_PASSWORD"),
        database=os.getenv("QUERIESDB_DB"),
        timeout=int(os.getenv("QUERIESDB_QUERY_TIMEOUT", "30")),
    )

    try:
        rows = await fetch_queries(conn, podcast_name, args.limit, args.offset)
    finally:
        await conn.close()

    queries = [
        (int(row["id"]), row["query_text"], parse_vector(row["query_embedding"]))
        for row in rows
    ]
    queries = [(query_id, text, emb) for query_id, text, emb in queries if emb]

    print(f"DB: {os.getenv('QUERIESDB_USER')}@{os.getenv('QUERIESDB_HOST')}:{os.getenv('QUERIESDB_PORT')}/{os.getenv('QUERIESDB_DB')}", flush=True)
    print(f"Context server: {context_url}", flush=True)
    print(f"Podcast: {podcast_name or '(todos)'}", flush=True)
    print(f"Umbrales: {', '.join(str(threshold) for threshold in args.thresholds)}", flush=True)
    print(f"Consultas con embedding: {len(queries)}", flush=True)

    all_results: dict[float, List[int]] = {threshold: [] for threshold in args.thresholds}
    worst_examples: dict[float, list[tuple[int, int, str]]] = {threshold: [] for threshold in args.thresholds}

    for index, (query_id, text, embedding) in enumerate(queries, start=1):
        for threshold in args.thresholds:
            total = get_total_matches(context_url, api_key, text, embedding, threshold, args.timeout)
            all_results[threshold].append(total)
            worst_examples[threshold].append((total, query_id, text))

        if args.progress_every and index % args.progress_every == 0:
            print(f"Procesadas {index}/{len(queries)} consultas...", flush=True)

    for threshold in args.thresholds:
        values = all_results[threshold]
        if not values:
            continue
        print_stats(threshold, values)
        print("Top 10 consultas con mas fragmentos:")
        for total, query_id, text in sorted(worst_examples[threshold], reverse=True)[:10]:
            print(f"{query_id}: {total} {format_query_for_line(text)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
