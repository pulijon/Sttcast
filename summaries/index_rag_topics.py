#!/usr/bin/env python3
"""
Indexa los temas tratados de los resúmenes RAG en PostgreSQL/pgvector.

Lee los JSON generados por get_rag_summaries.py, extrae las listas HTML de
temas en español e inglés, calcula embeddings usando el servidor RAG y guarda
los resultados en la tabla rag_episode_topics de la base de consultas.
"""

import argparse
import asyncio
import hashlib
import json
import logging
import os
import re
import sqlite3
import sys
from datetime import datetime, time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from api.apihmac import create_auth_headers, serialize_body
from tools.envvars import load_env_vars_from_directory
from tools.logs import logcfg


def parse_timecode(value: str) -> Optional[float]:
    parts = [p for p in value.strip().split(":") if p != ""]
    if len(parts) == 2:
        hours = 0
        minutes, seconds = parts
    elif len(parts) == 3:
        hours, minutes, seconds = parts
    else:
        return None

    try:
        return float(int(hours) * 3600 + int(minutes) * 60 + int(seconds))
    except ValueError:
        return None


def parse_topic_li(text: str) -> Optional[dict[str, Any]]:
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    match = re.search(r"\s+-\s+((?:\d{1,2}:)?\d{2}:\d{2})\s*$", cleaned)
    if not match:
        return None

    seconds = parse_timecode(match.group(1))
    if seconds is None:
        return None

    topic_text = cleaned[:match.start()].strip()
    if not topic_text:
        return None

    return {"text": topic_text, "start_seconds": seconds}


def extract_topics(summary_html: str) -> list[dict[str, Any]]:
    if not summary_html:
        return []

    soup = BeautifulSoup(summary_html, "html.parser")
    topic_summary = soup.find(id="topic-summary")
    if topic_summary is None:
        return []

    topic_list = topic_summary.find(id="tslist")
    if topic_list is None:
        return []

    topics = []
    for li in topic_list.find_all("li"):
        parsed = parse_topic_li(li.get_text(" ", strip=True))
        if parsed:
            topics.append(parsed)
    return topics


def load_episode_dates(db_file: Optional[str]) -> dict[str, str]:
    if not db_file:
        return {}

    db_path = Path(db_file).expanduser()
    if not db_path.exists():
        logging.warning("Base SQLite de episodios no encontrada: %s", db_path)
        return {}

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT epname, epdate FROM episode").fetchall()
        conn.close()
        return {str(row["epname"]): str(row["epdate"]) for row in rows if row["epdate"] is not None}
    except Exception as e:
        logging.warning("No se pudieron cargar fechas de episodios desde %s: %s", db_path, e)
        return {}


def build_rag_server_url() -> str:
    rag_server_url = os.getenv("RAG_SERVER_URL")
    if rag_server_url:
        return rag_server_url

    host = os.getenv("RAG_SERVER_HOST", "localhost")
    port = int(os.getenv("RAG_SERVER_PORT", "5500"))
    return f"http://{host}:{port}/"


def parse_from_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.combine(datetime.strptime(value, "%Y-%m-%d").date(), time.min)
    except ValueError as e:
        raise argparse.ArgumentTypeError("--from debe tener formato yyyy-mm-dd") from e


def iter_summary_files(summaries_dir: str, limit: Optional[int] = None, from_date: Optional[datetime] = None):
    count = 0
    for path in sorted(Path(summaries_dir).expanduser().glob("*_summary.json")):
        if from_date:
            mtime = datetime.fromtimestamp(path.stat().st_mtime)
            if mtime < from_date:
                continue
        yield path
        count += 1
        if limit is not None and count >= limit:
            return


def build_topic_records(path: Path, podcast_name: Optional[str], episode_dates: dict[str, str]) -> list[dict[str, Any]]:
    raw = path.read_text(encoding="utf-8")
    source_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    data = json.loads(raw)

    epname = path.name.removesuffix("_summary.json")
    topics_es = extract_topics(data.get("es", ""))
    topics_en = extract_topics(data.get("en", ""))
    topic_count = max(len(topics_es), len(topics_en))
    records = []

    for idx in range(topic_count):
        es_item = topics_es[idx] if idx < len(topics_es) else None
        en_item = topics_en[idx] if idx < len(topics_en) else None
        start_seconds = None
        if es_item:
            start_seconds = es_item["start_seconds"]
        elif en_item:
            start_seconds = en_item["start_seconds"]
        if start_seconds is None:
            continue

        text_es = es_item["text"] if es_item else None
        text_en = en_item["text"] if en_item else None
        if not text_es and not text_en:
            continue

        records.append({
            "podcast_name": podcast_name,
            "epname": epname,
            "epdate": episode_dates.get(epname),
            "topic_index": idx,
            "topic_text_es": text_es,
            "topic_text_en": text_en,
            "start_seconds": start_seconds,
            "summary_file": str(path),
            "source_hash": source_hash,
            "embedding_text": "\n".join(
                part for part in (f"ES: {text_es}" if text_es else "", f"EN: {text_en}" if text_en else "")
                if part
            ),
        })

    return records


def get_embeddings(records: list[dict[str, Any]], rag_server_url: str, rag_server_api_key: str) -> list[list[float]]:
    if not records:
        return []

    payload = [
        {
            "tag": "topic",
            "epname": record["epname"],
            "epdate": record.get("epdate") or "",
            "start": record["start_seconds"],
            "end": record["start_seconds"],
            "content": record["embedding_text"],
        }
        for record in records
    ]

    path = "/getembeddings"
    url = urljoin(rag_server_url, path)
    auth_headers = create_auth_headers(rag_server_api_key, "POST", path, payload, client_id="index_rag_topics")
    response = requests.post(url, data=serialize_body(payload), headers=auth_headers, timeout=120)
    response.raise_for_status()
    data = response.json()
    embeddings = data.get("embeddings")
    if not isinstance(embeddings, list) or len(embeddings) != len(records):
        raise ValueError("El servidor RAG devolvió un número inválido de embeddings")
    return embeddings


async def run(args) -> int:
    summaries_dir = args.summaries or os.getenv("DIARY_SUMMARIES")
    if not summaries_dir:
        raise RuntimeError("Configura DIARY_SUMMARIES o usa --summaries")
    if not Path(summaries_dir).expanduser().is_dir():
        raise RuntimeError(f"El directorio de resúmenes no existe: {summaries_dir}")

    podcast_name = args.podcast_name or os.getenv("PODCAST_NAME")
    episode_dates = load_episode_dates(args.episode_db or os.getenv("STTCAST_DB_FILE"))
    rag_server_url = args.rag_url or build_rag_server_url()
    rag_server_api_key = os.getenv("RAG_SERVER_API_KEY")
    if not rag_server_api_key and not args.dry_run:
        raise RuntimeError("RAG_SERVER_API_KEY es necesaria para calcular embeddings")

    total_episodes = 0
    total_topics = 0
    total_skipped = 0
    from_date = parse_from_date(args.from_date)

    db = None
    if not args.dry_run or args.inspect_db:
        from rag.client.queriesdb import db as queries_db

        db = queries_db
        if args.dry_run:
            db.query_timeout = min(db.query_timeout, 5)
        await db.initialize()
        if not db.is_available:
            if args.dry_run:
                logging.warning("La base de datos de consultas no está disponible; dry-run sin inspección de existentes")
                db = None
            else:
                raise RuntimeError("La base de datos de consultas no está disponible")

        if db is not None:
            table_ready = await db.create_episode_topics_table()
            if not table_ready:
                if args.dry_run:
                    logging.warning("No se pudo verificar rag_episode_topics; dry-run sin inspección de existentes")
                    await db.close()
                    db = None
                else:
                    raise RuntimeError("No se pudo crear/verificar rag_episode_topics")

    try:
        if from_date:
            logging.info("Procesando sólo summaries modificados desde %s", args.from_date)
        if args.force:
            logging.info("Modo --force activo: se reemplazarán embeddings existentes de los ficheros procesados")

        for summary_path in iter_summary_files(summaries_dir, args.limit, from_date):
            records = build_topic_records(summary_path, podcast_name, episode_dates)
            total_episodes += 1
            if not records:
                logging.info("Sin temas extraíbles: %s", summary_path.name)
                continue

            epname = records[0]["epname"]
            existing = await db.get_episode_topic_status(podcast_name, epname) if db is not None else {}
            missing_records = [
                record for record in records
                if not existing.get(record["topic_index"], {}).get("has_embedding")
            ]

            if args.dry_run:
                mtime = datetime.fromtimestamp(summary_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                if args.force:
                    action_count = len(records)
                    action = "reemplazaría"
                elif db is None:
                    action_count = len(records)
                    action = "analizaría"
                else:
                    action_count = len(missing_records)
                    action = "insertaría/completaría"
                skipped = len(records) - action_count
                total_topics += action_count
                total_skipped += max(0, skipped)
                logging.info(
                    "%s (mtime=%s): %d temas detectados; %s %d; saltaría %d",
                    summary_path.name,
                    mtime,
                    len(records),
                    action,
                    action_count,
                    max(0, skipped),
                )
                continue

            records_to_embed = records if args.force else missing_records
            if not records_to_embed:
                total_skipped += len(records)
                logging.info("%s: %d temas ya tenían embedding; sin cambios", summary_path.name, len(records))
                continue

            for start in range(0, len(records_to_embed), args.batch_size):
                batch = records_to_embed[start:start + args.batch_size]
                embeddings = get_embeddings(batch, rag_server_url, rag_server_api_key)
                for record, embedding in zip(batch, embeddings):
                    record["topic_embedding"] = embedding

            if args.force:
                changed = await db.replace_episode_topics(podcast_name, epname, records)
                skipped = 0
                logging.info("%s: %d temas reemplazados", summary_path.name, changed)
            else:
                changed = await db.upsert_missing_episode_topics(podcast_name, records_to_embed)
                skipped = len(records) - changed
                logging.info("%s: %d temas insertados/completados; %d respetados", summary_path.name, changed, skipped)

            total_topics += changed
            total_skipped += max(0, skipped)

    finally:
        if db is not None:
            await db.close()

    logging.info(
        "Proceso terminado: %d episodios, %d temas afectados, %d temas respetados/saltados",
        total_episodes,
        total_topics,
        total_skipped,
    )
    return total_topics


def main():
    env_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))
    load_env_vars_from_directory(env_dir)

    parser = argparse.ArgumentParser(description="Indexa temas tratados de summaries RAG en pgvector")
    parser.add_argument("-s", "--summaries", help="Directorio de summaries JSON; por defecto DIARY_SUMMARIES")
    parser.add_argument("--podcast-name", help="Nombre del podcast; por defecto PODCAST_NAME")
    parser.add_argument("--episode-db", help="SQLite de episodios para completar epdate; por defecto STTCAST_DB_FILE")
    parser.add_argument("--rag-url", help="URL base del servidor RAG; por defecto RAG_SERVER_URL o HOST:PORT")
    parser.add_argument("--batch-size", type=int, default=32, help="Tamaño de lote para embeddings")
    parser.add_argument("--limit", type=int, help="Número máximo de summaries a procesar")
    parser.add_argument("--dry-run", action="store_true", help="Muestra qué haría sin crear embeddings ni guardar")
    parser.add_argument("--from", dest="from_date", help="Procesa sólo summaries modificados desde yyyy-mm-dd")
    parser.add_argument("--force", action="store_true", help="Sobrescribe embeddings existentes de los ficheros procesados")
    parser.add_argument(
        "--no-inspect-db",
        dest="inspect_db",
        action="store_false",
        default=True,
        help="En dry-run, no consulta la BD para distinguir temas existentes",
    )
    args = parser.parse_args()

    if args.batch_size <= 0:
        parser.error("--batch-size debe ser mayor que cero")
    if args.from_date:
        parse_from_date(args.from_date)

    asyncio.run(run(args))


if __name__ == "__main__":
    logcfg(__file__)
    main()
