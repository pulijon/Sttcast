import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import logging
from tools.logs import logcfg
from tools.envvars import load_env_vars_from_directory
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from typing import List, Optional
import pandas as pd
import numpy as np
import sqlite3
from sttcastdb import SttcastDB
from openai import OpenAI
import json
import faiss
import requests
from datetime import datetime
from api.apirag import EmbeddingInput
from api.apicontext import (
    AddSegmentsRequest,
    ContextFiltersRequest,
    GetContextByDistanceRequest,
    GetContextRequest,
    GetContextResponse,
    GenStatsRequest,
    GetGeneralStatsResponse,
    SpeakerStat,
    GetSpeakerStatsResponse,
    SpeakerStatsRequest
)
from api.apihmac import create_auth_headers, validate_hmac_auth, serialize_body
from contextlib import asynccontextmanager
import threading

# Clave para autenticación HMAC del servidor
CONTEXT_SERVER_API_KEY = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Se ejecuta al iniciar y parar FastAPI.
    - Carga .env
    - Crea una única conexión a SQLite con WAL
    - Carga/crea índice FAISS
    - Guarda todo en app.state
    """
    # Logging
    logcfg(__file__)
    logging.info("Iniciando lifespan de context_server")

    # ---------- Cargar variables de entorno ----------
    env_dir = os.path.join(os.path.dirname(__file__), '../.env')
    load_env_vars_from_directory(directory=env_dir)

    db_file = os.getenv("STTCAST_DB_FILE", "sttcast.db")
    if not os.path.exists(db_file):
        logging.warning(f"El fichero de base de datos {db_file} no existe (se creará si se añade un episodio)")

    # ---------- Instancia única de DB con WAL ----------
    # Nota: SttcastDB debe activar WAL en su __init__ (journal_mode=WAL, synchronous=NORMAL, busy_timeout)
    app.state.db = SttcastDB(db_file, create_if_not_exists=True, wal=True)  # wal=True requiere que lo hayas implementado
    app.state.db_write_lock = threading.Lock()

    # ---------- Construir caché de estadísticas PRIMERO (antes de FAISS) ----------
    # Esto es menos costoso en memoria que FAISS, así que lo hacemos primero
    try:
        logging.info("Iniciando construcción de caché de estadísticas...")
        start_cache_time = datetime.now()
        app.state.db.ensure_cache_stats_exists()
        
        # Verificar si la tabla está vacía (nueva BD)
        app.state.db.cursor.execute("SELECT COUNT(*) FROM cache_stats")
        cache_count = app.state.db.cursor.fetchone()[0]
        
        if cache_count == 0:
            logging.info("Tabla cache_stats vacía, reconstruyendo desde speakerintervention...")
            app.state.db.rebuild_cache_stats_table()
        
        end_cache_time = datetime.now()
        duration = (end_cache_time - start_cache_time).total_seconds()
        logging.info(f"✅ Caché de estadísticas lista en {duration:.2f} segundos")
    except Exception as e:
        logging.error(f"Error construyendo cache de estadísticas: {e}")
        logging.exception("Traceback:")
        raise
    
    # ---------- Índice FAISS único (después de la caché) ----------   
    
    index_file = os.getenv("STTCAST_FAISS_FILE", "sttcast.index")
    app.state.index_file = index_file
    app.state.index_lock = threading.Lock()

    if os.path.exists(index_file):
        try:
            logging.info(f"Cargando índice FAISS desde {index_file}...")
            app.state.index = faiss.read_index(index_file)
            logging.info(f"Índice FAISS cargado exitosamente de {index_file} (d={app.state.index.d})")
        except Exception as e:
            logging.error(f"Error cargando índice FAISS desde {index_file}: {e}")
            logging.warning(f"El índice FAISS está corrupto. El servidor arrancará sin índice.")
            logging.warning(f"Considera regenerar el índice o restaurar desde un backup.")
            app.state.index = None
    else:
        app.state.index = None
        logging.info("No existe índice FAISS en disco; se creará al añadir segmentos por primera vez")

    # ---------- RAG server ----------
    rag_server_host = os.getenv("RAG_SERVER_HOST", "localhost")
    rag_server_port = int(os.getenv("RAG_SERVER_PORT", "5500"))
    app.state.rag_server_url = f"http://{rag_server_host}:{rag_server_port}"
    
    # Cargar clave de autenticación para RAG server
    rag_server_api_key = os.getenv('RAG_SERVER_API_KEY')
    if not rag_server_api_key:
        logging.error("RAG_SERVER_API_KEY not found in environment variables")
        raise ValueError("RAG_SERVER_API_KEY is required")
    app.state.rag_server_api_key = rag_server_api_key
    logging.info("RAG server authentication configured successfully")
    
    # Cargar clave de autenticación para Context server
    global CONTEXT_SERVER_API_KEY
    CONTEXT_SERVER_API_KEY = os.getenv('CONTEXT_SERVER_API_KEY')
    if not CONTEXT_SERVER_API_KEY:
        logging.error("CONTEXT_SERVER_API_KEY not found in environment variables")
        raise ValueError("CONTEXT_SERVER_API_KEY is required")
    logging.info("Context server authentication configured successfully")

    # ---------- Otros parámetros ----------
    app.state.relevant_fragments = int(os.getenv("STTCAST_RELEVANT_FRAGMENTS", "100"))
    
    # Nota: La caché de estadísticas ya está cargada (se construye de forma sincrónica arriba)
    # No es necesario construirla en background
    
    # Listo para servir
    yield

    # ---------- Cierre ordenado ----------
    
    try:
        app.state.db.close()
        logging.info("Conexión a DB cerrada correctamente")
    except Exception as e:
        logging.warning(f"Error al cerrar DB: {e}")

    try:
        if app.state.index is not None:
            faiss.write_index(app.state.index, app.state.index_file)
            logging.info(f"Índice FAISS guardado en {app.state.index_file}")
    except Exception as e:
        logging.warning(f"Error al guardar índice FAISS al finalizar: {e}")
    
openai: OpenAI = None

app = FastAPI(lifespan=lifespan)

@app.post("/addsegments")
async def addsegments(request: Request):
    # Validar autenticación HMAC
    body_bytes = await request.body()
    client_id = validate_hmac_auth(request, CONTEXT_SERVER_API_KEY, body_bytes)
    
    # Parse del body
    body_dict = json.loads(body_bytes.decode('utf-8'))
    req = AddSegmentsRequest(**body_dict)
    
    db: SttcastDB = app.state.db
    db_lock: threading.Lock = app.state.db_write_lock
    index_lock: threading.Lock = app.state.index_lock
    index = app.state.index
    index_file = app.state.index_file
    rag_server_url = app.state.rag_server_url

    # 1) Borrado de episodio previo + inserción de segmentos (ESCRITURA: usar lock)
    with db_lock:
        eid = db.get_episode_id(req.epname)
        if eid is not None:
            # recuperar IDs embebidos de ese episodio para quitar del índice FAISS
            ints = db.get_ints(with_embeddings=True, epname=req.epname)
            ids_np = np.array([intv['id'] for intv in ints], dtype=np.int64)
            # borrar datos del episodio en DB
            db.del_episode_data(eid)
        else:
            ids_np = np.array([], dtype=np.int64)

        newid = db.add_episode(req.epname, req.epdate, req.epfile, req.segments)
        if newid is None:
            raise HTTPException(status_code=500, detail="Error al añadir el episodio a la base de datos")

    # 2) Calcular embeddings (FUERA del lock de DB)
    ints = db.get_ints(with_embeddings=False, epname=req.epname)
    logging.info(f"Se han encontrado {len(ints)} segmentos para el episodio {req.epname}")

    segments = [
        {
            "tag": intv["tag"],
            "epname": intv["epname"],
            "epdate": intv["epdate"].strftime("%Y-%m-%d") if hasattr(intv["epdate"], "strftime") else str(intv["epdate"]),
            "start": intv["start"],
            "end": intv["end"],
            "content": intv["content"],
        }
        for intv in ints
    ]
    ids = [intv["id"] for intv in ints]

    url = f"{rag_server_url}/getembeddings"
    
    # Crear headers de autenticación HMAC
    rag_api_key = app.state.rag_server_api_key
    auth_headers = create_auth_headers(rag_api_key, "POST", url, segments, client_id='context_server')
    
    # ENVIAR EL JSON EXACTO QUE USAMOS PARA LA FIRMA
    body_str = serialize_body(segments)
    r = requests.post(url, data=body_str, headers=auth_headers)
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    rjson = r.json()

    vectors = rjson.get("embeddings")
    prompt_tokens = rjson.get("prompt_tokens", 0)
    total_tokens = rjson.get("total_tokens", 0)

    if not isinstance(vectors, list) or not all(isinstance(v, list) for v in vectors):
        raise HTTPException(status_code=500, detail="Formato de embeddings inválido")
    if len(vectors) != len(segments):
        raise HTTPException(status_code=500, detail="Número de embeddings no coincide con segmentos")

    vectors = np.array(vectors, dtype=np.float32)
    # Normalizar vectores para búsquedas con IndexFlatIP
    faiss.normalize_L2(vectors)
    if vectors.ndim != 2 or vectors.shape[0] != len(segments):
        raise HTTPException(status_code=500, detail="Forma de embeddings inválida")

    # 3) Actualizar índice FAISS (ÍNDICE: usar lock)
    with index_lock:
        if app.state.index is None:
            dim = vectors.shape[1]
            flat = faiss.IndexFlatL2(dim)
            app.state.index = faiss.IndexIDMap2(flat)
            logging.info(f"Índice FAISS creado (dim={dim})")

        if vectors.shape[1] != app.state.index.d:
            raise HTTPException(
                status_code=500,
                detail=f"Dimensión de vectores incorrecta: esperando {app.state.index.d}, recibido {vectors.shape[1]}"
            )

        # Si habías borrado episodio antes, quita IDs antiguos del índice
        if ids_np.size > 0:
            try:
                app.state.index.remove_ids(ids_np)
            except Exception as e:
                logging.warning(f"No se pudieron eliminar IDs previos del índice: {e}")

        # Añade nuevos vectores
        app.state.index.add_with_ids(vectors, np.array(ids, dtype=np.int64))
        faiss.write_index(app.state.index, index_file)
        logging.info(f"Índice FAISS actualizado y guardado en {index_file}")

    # 4) Guardar embeddings en DB (ESCRITURA: lock)
    with db_lock:
        for _id, emb in zip(ids, vectors):
            db.update_embedding(_id, emb.tobytes(), prompt_tokens, total_tokens)
        db.commit()

    # 5) Verificación ligera
    remaining = db.get_ints(with_embeddings=False, epname=req.epname)
    logging.info(f"Tras actualización, quedan {len(remaining)} segmentos sin embedding para {req.epname}")
    return {"ok": True, "episode": req.epname, "segments": len(segments)}


async def get_query_embedding(query: str, app) -> Optional[List[float]]:
    """
    Obtiene el embedding de una query genérica del RAG server.
    Retorna una lista de floats o None si falla.
    """
    try:
        rag_server_url = app.state.rag_server_url
        rag_api_key = app.state.rag_server_api_key
        
        qurl = f"{rag_server_url}/getoneembedding"
        query_data = {"query": query}
        
        auth_headers = create_auth_headers(rag_api_key, "POST", qurl, query_data, client_id='context_server')
        body_str = serialize_body(query_data)
        
        r = requests.post(qurl, data=body_str, headers=auth_headers)
        if r.status_code != 200:
            logging.warning(f"Error obteniendo embedding: {r.status_code} - {r.text}")
            return None
        
        embedding = r.json().get("embedding")
        if isinstance(embedding, list):
            return embedding
        return None
        
    except Exception as e:
        logging.error(f"Error en get_query_embedding: {e}")
        return None


def normalize_speakers_filter(speakers: Optional[List[str]]) -> Optional[set[str]]:
    if not speakers:
        return None
    normalized = {speaker.strip() for speaker in speakers if speaker and speaker.strip()}
    if not normalized or "todos" in {speaker.lower() for speaker in normalized}:
        return None
    return normalized


def has_context_filters(fromdate: Optional[str], todate: Optional[str], speakers: Optional[List[str]]) -> bool:
    return bool(fromdate or todate or normalize_speakers_filter(speakers))


def row_matches_context_filters(row, fromdate: Optional[str], todate: Optional[str], speakers: Optional[set[str]]) -> bool:
    epdate = str(row["epdate"])
    if fromdate and epdate < fromdate:
        return False
    if todate and epdate > todate:
        return False
    if speakers and str(row["tag"]) not in speakers:
        return False
    return True


def build_context_from_faiss_results(
    db: SttcastDB,
    ids: List[int],
    distances: List[float],
    fromdate: Optional[str] = None,
    todate: Optional[str] = None,
    speakers: Optional[List[str]] = None,
) -> tuple[List[dict], int]:
    """Construye el contexto preservando el orden de FAISS y añadiendo métricas de distancia."""
    valid_pairs = [
        (int(raw_id), float(raw_distance))
        for raw_id, raw_distance in zip(ids, distances)
        if int(raw_id) != -1
    ]
    if not valid_pairs:
        return [], 0

    rows = db.get_ints(with_embeddings=True, ids=[raw_id for raw_id, _ in valid_pairs])
    rows_by_id = {int(row["id"]): row for row in rows}
    context = []
    speakers_filter = normalize_speakers_filter(speakers)
    matches_after_filter = 0

    for raw_id, raw_distance in valid_pairs:
        row = rows_by_id.get(raw_id)
        if row is None:
            logging.warning(f"FAISS devolvió el id {raw_id}, pero no existe en la base de datos")
            continue
        if not row_matches_context_filters(row, fromdate, todate, speakers_filter):
            continue

        matches_after_filter += 1

        item = {k: v for k, v in dict(row).items() if k != 'embedding'}
        faiss_l2_distance = float(raw_distance)
        cosine_distance = faiss_l2_distance / 2.0
        item["faiss_l2_distance"] = faiss_l2_distance
        item["cosine_distance"] = cosine_distance
        item["cosine_similarity"] = 1.0 - cosine_distance
        context.append(item)

    return context, matches_after_filter


def get_context_filter_defaults(db: SttcastDB, fromdate: Optional[str] = None, todate: Optional[str] = None) -> dict:
    db.cursor.execute("SELECT MIN(epdate) AS min_date, MAX(epdate) AS max_date FROM episode")
    bounds = db.cursor.fetchone()
    min_date = str(bounds["min_date"]) if bounds and bounds["min_date"] is not None else None
    max_date = str(bounds["max_date"]) if bounds and bounds["max_date"] is not None else None

    effective_fromdate = fromdate or min_date
    effective_todate = todate or max_date

    query = "SELECT DISTINCT tag FROM intview WHERE 1=1"
    params = []
    if effective_fromdate:
        query += " AND epdate >= ?"
        params.append(effective_fromdate)
    if effective_todate:
        query += " AND epdate <= ?"
        params.append(effective_todate)
    query += " ORDER BY tag"
    db.cursor.execute(query, params)
    speakers = [str(row["tag"]) for row in db.cursor.fetchall()]

    return {
        "min_date": min_date,
        "max_date": max_date,
        "fromdate": effective_fromdate,
        "todate": effective_todate,
        "speakers": speakers,
        "selected_speakers": ["todos"],
    }


def validate_context_index(index):
    if index is None:
        raise HTTPException(status_code=500, detail="El índice FAISS aún no está inicializado")


def get_normalized_query_vector(req, rag_server_url: str, rag_api_key: str) -> tuple[np.ndarray, List[float]]:
    if req.query_embedding:
        qvec = np.array(req.query_embedding, dtype=np.float32).reshape(1, -1)
    else:
        qurl = f"{rag_server_url}/getoneembedding"
        query_data = {"query": req.query}
        auth_headers = create_auth_headers(rag_api_key, "POST", qurl, query_data, client_id='context_server')
        body_str = serialize_body(query_data)
        r = requests.post(qurl, data=body_str, headers=auth_headers)
        if r.status_code != 200:
            raise HTTPException(status_code=r.status_code, detail=r.text)
        qvec = np.array(r.json().get("embedding"), dtype=np.float32).reshape(1, -1)

    faiss.normalize_L2(qvec)
    return qvec, qvec[0].tolist()


@app.post("/getcontext")
async def getcontext(request: Request):
    # Validar autenticación HMAC
    body_bytes = await request.body()
    client_id = validate_hmac_auth(request, CONTEXT_SERVER_API_KEY, body_bytes)
    
    # Parse del body
    body_dict = json.loads(body_bytes.decode('utf-8'))
    req = GetContextRequest(**body_dict)
    
    db: SttcastDB = app.state.db
    index = app.state.index
    rag_server_url = app.state.rag_server_url
    rag_api_key = app.state.rag_server_api_key
    k = req.n_fragments

    validate_context_index(index)

    # 1. Obtener embedding de la query
    qvec, query_embedding_list = get_normalized_query_vector(req, rag_server_url, rag_api_key)

    # 2. Si solo se pide el embedding, devolverlo y salir
    if req.only_embedding:
        return GetContextResponse(context=[], query_embedding=query_embedding_list)

    # 3. Buscar en FAISS
    D, I = index.search(qvec, k=k)
    ids = I[0].tolist()
    if not ids or ids[0] == -1:
        raise HTTPException(status_code=404, detail="No se han encontrado segmentos relevantes para la consulta")

    context, _ = build_context_from_faiss_results(db, ids, D[0].tolist())
    logging.info(f"Contexto recuperado: {len(context)} fragmentos")
    
    return GetContextResponse(context=context, query_embedding=query_embedding_list)


@app.post("/getcontextbyd")
async def getcontextbyd(request: Request):
    # Validar autenticación HMAC
    body_bytes = await request.body()
    client_id = validate_hmac_auth(request, CONTEXT_SERVER_API_KEY, body_bytes)

    # Parse del body
    body_dict = json.loads(body_bytes.decode('utf-8'))
    req = GetContextByDistanceRequest(**body_dict)

    if req.distance_threshold < 0 or req.distance_threshold > 2:
        raise HTTPException(status_code=400, detail="distance_threshold debe estar entre 0 y 2")
    if req.max_fragments <= 0:
        raise HTTPException(status_code=400, detail="max_fragments debe ser mayor que cero")

    db: SttcastDB = app.state.db
    index = app.state.index
    rag_server_url = app.state.rag_server_url
    rag_api_key = app.state.rag_server_api_key

    validate_context_index(index)

    qvec, query_embedding_list = get_normalized_query_vector(req, rag_server_url, rag_api_key)
    if req.only_embedding:
        return GetContextResponse(context=[], query_embedding=query_embedding_list)

    # FAISS IndexFlatL2 devuelve distancia euclidea cuadrada. Con vectores normalizados:
    # squared_l2 = 2 * cosine_distance.
    radius = float(req.distance_threshold) * 2.0
    lims, distances, ids = index.range_search(qvec, radius)
    result_count = int(lims[1] - lims[0])
    if result_count == 0:
        raise HTTPException(status_code=404, detail="No se han encontrado segmentos bajo el umbral indicado")

    pairs = sorted(
        zip(ids.tolist(), distances.tolist()),
        key=lambda pair: pair[1],
    )
    filtering_requested = has_context_filters(req.fromdate, req.todate, req.speakers)
    pairs_to_fetch = pairs if filtering_requested else pairs[:req.max_fragments]

    context, matches_after_filter = build_context_from_faiss_results(
        db,
        [raw_id for raw_id, _ in pairs_to_fetch],
        [raw_distance for _, raw_distance in pairs_to_fetch],
        fromdate=req.fromdate,
        todate=req.todate,
        speakers=req.speakers,
    )
    truncated = len(context) > req.max_fragments
    context = context[:req.max_fragments]
    if not filtering_requested:
        matches_after_filter = result_count
    logging.info(
        f"Contexto por distancia recuperado: {len(context)} fragmentos "
        f"(total_bajo_umbral={result_count}, threshold={req.distance_threshold}, truncated={truncated})"
    )

    return {
        "context": context,
        "query_embedding": query_embedding_list,
        "total_matches": result_count,
        "matches_after_filter": matches_after_filter,
        "returned_matches": len(context),
        "truncated": truncated,
        "distance_threshold": req.distance_threshold,
        "max_fragments": req.max_fragments,
        "fromdate": req.fromdate,
        "todate": req.todate,
        "speakers": req.speakers or ["todos"],
    }


@app.post("/contextfilters")
async def contextfilters(request: Request):
    body_bytes = await request.body()
    client_id = validate_hmac_auth(request, CONTEXT_SERVER_API_KEY, body_bytes)

    body_dict = json.loads(body_bytes.decode('utf-8')) if body_bytes else {}
    req = ContextFiltersRequest(**body_dict)
    return get_context_filter_defaults(app.state.db, req.fromdate, req.todate)


# Endpoint para obtener estadísticas generales entre dos fechas
@app.post("/api/gen_stats")
async def get_gen_stats(request: Request):
    # Validar autenticación HMAC
    body_bytes = await request.body()
    client_id = validate_hmac_auth(request, CONTEXT_SERVER_API_KEY, body_bytes)
    
    # Parse del body
    body_dict = json.loads(body_bytes.decode('utf-8'))
    req = GenStatsRequest(**body_dict)
    
    db: SttcastDB = app.state.db
    stats = db.get_general_stats(req.fromdate, req.todate)
    # Filtra Unknown
    stats['speakers'] = [s for s in stats['speakers'] if not s['tag'].lower().startswith('unknown')]
    return GetGeneralStatsResponse(**stats)


# Endpoint para obtener las estadísticas de una lista de hablantes entre dos fechas
@app.post("/api/speaker_stats")
async def get_speaker_stats(request: Request):
    # Validar autenticación HMAC
    body_bytes = await request.body()
    client_id = validate_hmac_auth(request, CONTEXT_SERVER_API_KEY, body_bytes)
    
    # Parse del body
    body_dict = json.loads(body_bytes.decode('utf-8'))
    req = SpeakerStatsRequest(**body_dict)
    
    db: SttcastDB = app.state.db
    raw_stats = db.get_speakers_stats(req.tags, req.fromdate, req.todate)
    # Coerción a SpeakerStat para validar estructura (opcional):
    try:
        stats = [SpeakerStat.model_validate(s) for s in raw_stats]
    except Exception as e:
        logging.exception("Error validando SpeakerStat")
        raise HTTPException(status_code=500, detail=f"Error de validación en stats: {e}")
    return GetSpeakerStatsResponse(tags=req.tags, stats=stats)

if __name__ == "__main__":
    env_dir = os.path.join(os.path.dirname(__file__), '../.env')
    # Cargar variables de entorno desde el directorio actual
    load_env_vars_from_directory(directory=env_dir)

    server_host = os.getenv("CONTEXT_SERVER_HOST", "localhost")
    server_port = int(os.getenv("CONTEXT_SERVER_PORT", 8000))
    openai_gpt_model = os.getenv("OPENAI_GPT_MODEL", "gpt-4o-mini")
    openai_embeddings_model = os.getenv("OPENAI_EMBEDDINGS_MODEL", "text-embedding-3-small")
    relevant_fragments = int(os.getenv("STTCAST_RELEVANT_FRAGMENTS", 100))

    # Iniciar el servidor FastAPI   
    import uvicorn
    uvicorn.run(app, host=server_host, port=server_port, log_level="info")
    
    
    
