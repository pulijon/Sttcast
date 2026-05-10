#!/usr/bin/env python3
"""
Calcula distancias de contexto para consultas RAG históricas.

Crea y rellena la tabla rag_query_context_distances en la base de queries.
Para cada consulta guardada llama a /getcontext con n_fragments y almacena la
mayor distancia del conjunto devuelto.
"""

import argparse
import asyncio
import os
import sys
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import requests

CURRENT_DIR = os.path.dirname(__file__)
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from api.apihmac import create_auth_headers, serialize_body
from tools.envvars import load_env_vars_from_directory


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("debe ser mayor que cero")
    return parsed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analiza la distancia máxima de los fragmentos recuperados por /getcontext."
    )
    parser.add_argument(
        "--fragments",
        type=positive_int,
        default=None,
        help="Número de fragmentos a pedir. Por defecto usa STTCAST_RELEVANT_FRAGMENTS.",
    )
    parser.add_argument(
        "--podcast-name",
        default=None,
        help="Filtra por podcast_name. Por defecto usa PODCAST_NAME; usa --all-podcasts para no filtrar.",
    )
    parser.add_argument(
        "--all-podcasts",
        action="store_true",
        help="Procesa todas las consultas sin filtrar por podcast_name.",
    )
    parser.add_argument("--limit", type=positive_int, default=None, help="Máximo de consultas a procesar.")
    parser.add_argument("--offset", type=int, default=0, help="Offset inicial de consultas.")
    parser.add_argument(
        "--reprocess",
        action="store_true",
        help="Recalcula aunque ya exista una fila para query_id/n_fragments.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="No inserta resultados; solo muestra qué haría.",
    )
    parser.add_argument(
        "--timeout",
        type=positive_int,
        default=120,
        help="Timeout en segundos para cada llamada a /getcontext.",
    )
    return parser.parse_args()


def context_url_from_env() -> str:
    host = os.getenv("CONTEXT_SERVER_HOST", "localhost")
    port = os.getenv("CONTEXT_SERVER_PORT")
    if not port:
        raise RuntimeError("CONTEXT_SERVER_PORT no está configurado")
    return urljoin(f"http://{host}:{port}", "/getcontext")


def get_context_distances(
    *,
    context_url: str,
    api_key: str,
    query_text: str,
    fragments: int,
    timeout: int,
) -> Dict[str, Any]:
    payload = {
        "query": query_text,
        "n_fragments": fragments,
    }
    headers = create_auth_headers(
        api_key,
        "POST",
        "/getcontext",
        payload,
        "context_distance_analyzer",
    )
    body = serialize_body(payload)
    response = requests.post(context_url, data=body, headers=headers, timeout=timeout)
    response.raise_for_status()

    data = response.json()
    context = data.get("context") or []
    cosine_distances = [
        float(item["cosine_distance"])
        for item in context
        if item.get("cosine_distance") is not None
    ]
    faiss_distances = [
        float(item["faiss_l2_distance"])
        for item in context
        if item.get("faiss_l2_distance") is not None
    ]
    similarities = [
        float(item["cosine_similarity"])
        for item in context
        if item.get("cosine_similarity") is not None
    ]

    if context and not cosine_distances:
        raise RuntimeError(
            "La respuesta de /getcontext no incluye cosine_distance; arranca el context_server actualizado."
        )

    return {
        "fragments_returned": len(context),
        "max_cosine_distance": max(cosine_distances) if cosine_distances else None,
        "max_faiss_l2_distance": max(faiss_distances) if faiss_distances else None,
        "min_cosine_similarity": min(similarities) if similarities else None,
    }


async def ensure_analysis_table(conn) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS rag_query_context_distances (
            id SERIAL PRIMARY KEY,
            query_id INTEGER NOT NULL REFERENCES rag_queries(id) ON DELETE CASCADE,
            n_fragments INTEGER NOT NULL,
            fragments_returned INTEGER NOT NULL,
            max_cosine_distance DOUBLE PRECISION,
            max_faiss_l2_distance DOUBLE PRECISION,
            min_cosine_similarity DOUBLE PRECISION,
            context_server_url TEXT,
            error TEXT,
            analyzed_at TIMESTAMP DEFAULT NOW(),
            UNIQUE (query_id, n_fragments)
        );
        """
    )
    await conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_rag_query_context_distances_query_id
        ON rag_query_context_distances(query_id);
        """
    )
    await conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_rag_query_context_distances_n_fragments
        ON rag_query_context_distances(n_fragments);
        """
    )


async def fetch_queries(conn, podcast_name: Optional[str], limit: Optional[int], offset: int) -> List[Dict[str, Any]]:
    limit_clause = "LIMIT $2 OFFSET $3" if podcast_name else "LIMIT $1 OFFSET $2"
    if limit is None:
        limit = 2_147_483_647

    if podcast_name:
        records = await conn.fetch(
            f"""
            SELECT id, uuid, query_text, podcast_name, created_at
            FROM rag_queries
            WHERE podcast_name = $1
            ORDER BY created_at ASC, id ASC
            {limit_clause}
            """,
            podcast_name,
            limit,
            offset,
        )
    else:
        records = await conn.fetch(
            f"""
            SELECT id, uuid, query_text, podcast_name, created_at
            FROM rag_queries
            ORDER BY created_at ASC, id ASC
            {limit_clause}
            """,
            limit,
            offset,
        )
    return [dict(record) for record in records]


async def result_exists(conn, query_id: int, fragments: int) -> bool:
    return bool(
        await conn.fetchval(
            """
            SELECT 1
            FROM rag_query_context_distances
            WHERE query_id = $1 AND n_fragments = $2
            """,
            query_id,
            fragments,
        )
    )


async def upsert_result(
    conn,
    *,
    query_id: int,
    fragments: int,
    result: Dict[str, Any],
    context_url: str,
    error: Optional[str] = None,
) -> None:
    await conn.execute(
        """
        INSERT INTO rag_query_context_distances (
            query_id,
            n_fragments,
            fragments_returned,
            max_cosine_distance,
            max_faiss_l2_distance,
            min_cosine_similarity,
            context_server_url,
            error,
            analyzed_at
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
        ON CONFLICT (query_id, n_fragments) DO UPDATE SET
            fragments_returned = EXCLUDED.fragments_returned,
            max_cosine_distance = EXCLUDED.max_cosine_distance,
            max_faiss_l2_distance = EXCLUDED.max_faiss_l2_distance,
            min_cosine_similarity = EXCLUDED.min_cosine_similarity,
            context_server_url = EXCLUDED.context_server_url,
            error = EXCLUDED.error,
            analyzed_at = NOW();
        """,
        query_id,
        fragments,
        result.get("fragments_returned", 0),
        result.get("max_cosine_distance"),
        result.get("max_faiss_l2_distance"),
        result.get("min_cosine_similarity"),
        context_url,
        error,
    )


async def main() -> int:
    load_env_vars_from_directory(os.path.join(PROJECT_ROOT, ".env"))

    try:
        import asyncpg
    except ImportError:
        print("Error: asyncpg no está instalado.", file=sys.stderr)
        return 1

    args = parse_args()
    fragments = args.fragments or int(os.getenv("STTCAST_RELEVANT_FRAGMENTS", "100"))
    podcast_name = None if args.all_podcasts else (args.podcast_name or os.getenv("PODCAST_NAME"))
    context_url = context_url_from_env()
    api_key = os.getenv("CONTEXT_SERVER_API_KEY")
    if not api_key:
        print("Error: CONTEXT_SERVER_API_KEY no está configurado.", file=sys.stderr)
        return 1

    db_host = os.getenv("QUERIESDB_HOST")
    db_port = int(os.getenv("QUERIESDB_PORT", "5432"))
    db_name = os.getenv("QUERIESDB_DB")
    db_user = os.getenv("QUERIESDB_USER")
    print(f"Conectando a queries DB: {db_user}@{db_host}:{db_port}/{db_name}")
    print(f"Context server: {context_url}")

    conn = await asyncpg.connect(
        host=db_host,
        port=db_port,
        user=db_user,
        password=os.getenv("QUERIESDB_PASSWORD"),
        database=db_name,
        timeout=int(os.getenv("QUERIESDB_QUERY_TIMEOUT", "30")),
    )

    processed = 0
    skipped = 0
    failed = 0

    try:
        await ensure_analysis_table(conn)
        queries = await fetch_queries(conn, podcast_name, args.limit, args.offset)
        print(
            f"Analizando {len(queries)} consultas con n_fragments={fragments}"
            + (f" para podcast_name={podcast_name!r}" if podcast_name else "")
        )

        for query in queries:
            query_id = int(query["id"])
            if not args.reprocess and await result_exists(conn, query_id, fragments):
                skipped += 1
                continue

            try:
                result = get_context_distances(
                    context_url=context_url,
                    api_key=api_key,
                    query_text=query["query_text"],
                    fragments=fragments,
                    timeout=args.timeout,
                )
                processed += 1
                print(
                    f"query_id={query_id} fragments={result['fragments_returned']} "
                    f"max_cosine_distance={result['max_cosine_distance']}"
                )
                if not args.dry_run:
                    await upsert_result(
                        conn,
                        query_id=query_id,
                        fragments=fragments,
                        result=result,
                        context_url=context_url,
                    )
            except Exception as exc:
                failed += 1
                error = str(exc)[:1000]
                print(f"query_id={query_id} ERROR {error}", file=sys.stderr)
                if not args.dry_run:
                    await upsert_result(
                        conn,
                        query_id=query_id,
                        fragments=fragments,
                        result={"fragments_returned": 0},
                        context_url=context_url,
                        error=error,
                    )

        print(f"Completado: processed={processed}, skipped={skipped}, failed={failed}")
        return 0 if failed == 0 else 2
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
