#!/usr/bin/env python3
"""
Resume estadísticamente rag_query_context_distances para escoger umbrales.
"""

import argparse
import asyncio
import os
import statistics
import sys
from pathlib import Path
from typing import List

CURRENT_DIR = os.path.dirname(__file__)
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from tools.envvars import load_env_vars_from_directory


def percentile(values: List[float], p: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    k = (len(ordered) - 1) * p / 100.0
    lower = int(k)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (k - lower)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Estadísticas de distancias máximas del contexto RAG.")
    parser.add_argument("--fragments", type=int, default=None)
    parser.add_argument("--podcast-name", default=None)
    parser.add_argument("--all-podcasts", action="store_true")
    parser.add_argument("--examples", type=int, default=10)
    parser.add_argument(
        "--thresholds",
        nargs="*",
        type=float,
        default=[0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70],
    )
    return parser.parse_args()


async def main() -> int:
    load_env_vars_from_directory(Path(PROJECT_ROOT) / ".env")

    try:
        import asyncpg
    except ImportError:
        print("Error: asyncpg no está instalado.", file=sys.stderr)
        return 1

    args = parse_args()
    fragments = args.fragments or int(os.getenv("STTCAST_RELEVANT_FRAGMENTS", "100"))
    podcast_name = None if args.all_podcasts else (args.podcast_name or os.getenv("PODCAST_NAME"))

    conn = await asyncpg.connect(
        host=os.getenv("QUERIESDB_HOST"),
        port=int(os.getenv("QUERIESDB_PORT", "5432")),
        user=os.getenv("QUERIESDB_USER"),
        password=os.getenv("QUERIESDB_PASSWORD"),
        database=os.getenv("QUERIESDB_DB"),
        timeout=int(os.getenv("QUERIESDB_QUERY_TIMEOUT", "30")),
    )

    try:
        if podcast_name:
            rows = await conn.fetch(
                """
                SELECT q.id, q.query_text, d.fragments_returned, d.max_cosine_distance,
                       d.max_faiss_l2_distance, d.min_cosine_similarity, d.error
                FROM rag_query_context_distances d
                JOIN rag_queries q ON q.id = d.query_id
                WHERE q.podcast_name = $1 AND d.n_fragments = $2
                ORDER BY d.max_cosine_distance NULLS LAST;
                """,
                podcast_name,
                fragments,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT q.id, q.query_text, d.fragments_returned, d.max_cosine_distance,
                       d.max_faiss_l2_distance, d.min_cosine_similarity, d.error
                FROM rag_query_context_distances d
                JOIN rag_queries q ON q.id = d.query_id
                WHERE d.n_fragments = $1
                ORDER BY d.max_cosine_distance NULLS LAST;
                """,
                fragments,
            )

        ok_rows = [row for row in rows if row["error"] is None and row["max_cosine_distance"] is not None]
        values = [float(row["max_cosine_distance"]) for row in ok_rows]
        errors = [row for row in rows if row["error"]]

        print(f"DB: {os.getenv('QUERIESDB_USER')}@{os.getenv('QUERIESDB_HOST')}:{os.getenv('QUERIESDB_PORT')}/{os.getenv('QUERIESDB_DB')}")
        print(f"Podcast: {podcast_name or '(todos)'}")
        print(f"n_fragments: {fragments}")
        print(f"filas: {len(rows)} ok: {len(values)} errores: {len(errors)}")

        if not values:
            return 0

        print()
        print("Distribucion max_cosine_distance")
        print(f"min:    {min(values):.6f}")
        print(f"media:  {statistics.mean(values):.6f}")
        print(f"mediana:{percentile(values, 50):.6f}")
        print(f"stdev:  {statistics.pstdev(values):.6f}")
        print(f"max:    {max(values):.6f}")
        for p in [5, 10, 25, 50, 75, 90, 95, 99]:
            print(f"p{p:02d}:   {percentile(values, p):.6f}")

        print()
        print("Cobertura por umbral")
        for threshold in args.thresholds:
            count = sum(value <= threshold for value in values)
            print(f"{threshold:.3f}: {count}/{len(values)} ({100.0 * count / len(values):.2f}%)")

        examples = max(args.examples, 0)
        if examples:
            print()
            print("Consultas con menor distancia maxima")
            for row in ok_rows[:examples]:
                print(f"{row['id']}: {float(row['max_cosine_distance']):.6f} {row['query_text'][:120].replace(chr(10), ' ')}")

            print()
            print("Consultas con mayor distancia maxima")
            for row in ok_rows[-examples:]:
                print(f"{row['id']}: {float(row['max_cosine_distance']):.6f} {row['query_text'][:120].replace(chr(10), ' ')}")

        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
