import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__),"../tools")))
from logs import logcfg
import logging
from envvars import load_env_vars_from_directory
from fastapi import FastAPI, HTTPException
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
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__),"../rag")))
from sttcast_rag_service import EmbeddingInput
from contextlib import asynccontextmanager
import threading
from concurrent.futures import ThreadPoolExecutor
import hmac
import hashlib
import time
import json
from urllib.parse import urlparse
import hmac
import hashlib
import time
import json
from urllib.parse import urlparse

def create_hmac_signature(secret_key: str, method: str, path: str, body: str, timestamp: str) -> str:
    """Crea una firma HMAC para autenticar la solicitud."""
    message = f"{method}|{path}|{body}|{timestamp}"
    return hmac.new(
        secret_key.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()

def create_auth_headers(secret_key: str, method: str, url: str, body) -> dict:
    """Crea los headers de autenticación HMAC."""
    parsed_url = urlparse(url)
    path = parsed_url.path
    timestamp = str(int(time.time()))
    
    # SERIALIZACIÓN CONSISTENTE SIN ESPACIOS
    if hasattr(body, 'model_dump'):
        body_str = json.dumps(body.model_dump(), separators=(',', ':'), sort_keys=True, ensure_ascii=False)
    elif isinstance(body, list) and len(body) > 0 and hasattr(body[0], 'model_dump'):
        body_str = json.dumps([item.model_dump() for item in body], separators=(',', ':'), sort_keys=True, ensure_ascii=False)
    elif isinstance(body, dict):
        body_str = json.dumps(body, separators=(',', ':'), sort_keys=True, ensure_ascii=False)
    else:
        body_str = json.dumps(body, separators=(',', ':'), sort_keys=True, ensure_ascii=False)
    
    # Logging detallado para debugging
    message = f"{method}|{path}|{body_str}|{timestamp}"
    logging.debug(f"Creando autenticación HMAC:")
    logging.debug(f"  URL: {url}")
    logging.debug(f"  Método: {method}, Path: {path}")
    logging.debug(f"  Timestamp: {timestamp}")
    logging.debug(f"  Body original: {body}")
    logging.debug(f"  Body serializado: {body_str}")
    logging.debug(f"  Mensaje completo: {message}")
    
    signature = create_hmac_signature(secret_key, method, path, body_str, timestamp)
    logging.info(f"HMAC Debug - Enviando a {path}: timestamp={timestamp}, signature={signature}")
    logging.info(f"HMAC Debug - Clave API (primeros 10 chars): {secret_key[:10]}...")
    logging.info(f"HMAC Debug - Body: {body_str}")
    logging.info(f"HMAC Debug - Mensaje construido: {method}|{path}|{body_str}|{timestamp}")
    
    return {
        'X-Timestamp': timestamp,
        'X-Signature': signature,
        'X-Client-ID': 'context_server',
        'Content-Type': 'application/json'
    }



class AddSegmentsRequest(BaseModel):
    epname: str
    epdate: datetime
    epfile: str
    segments: List[dict]

class GetContextRequest(BaseModel):
    query: str
    n_fragments: int = 20

class GetContextResponse(BaseModel):
    context: List[dict]

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

    # ---------- Índice FAISS único ----------   
    
    index_file = os.getenv("STTCAST_FAISS_FILE", "sttcast.index")
    app.state.index_file = index_file
    app.state.index_lock = threading.Lock()

    if os.path.exists(index_file):
        app.state.index = faiss.read_index(index_file)
        logging.info(f"Índice FAISS cargado de {index_file} (d={app.state.index.d})")
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

    # ---------- Otros parámetros ----------
    app.state.relevant_fragments = int(os.getenv("STTCAST_RELEVANT_FRAGMENTS", "100"))
    
    # Llamar al método build_cache_speaker_episode_stats para inicializar la caché en otro thread
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(app.state.db.build_cache_speaker_episode_stats)


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
def addsegments(request: AddSegmentsRequest):
    db: SttcastDB = app.state.db
    db_lock: threading.Lock = app.state.db_write_lock
    index_lock: threading.Lock = app.state.index_lock
    index = app.state.index
    index_file = app.state.index_file
    rag_server_url = app.state.rag_server_url

    # 1) Borrado de episodio previo + inserción de segmentos (ESCRITURA: usar lock)
    with db_lock:
        eid = db.get_episode_id(request.epname)
        if eid is not None:
            # recuperar IDs embebidos de ese episodio para quitar del índice FAISS
            ints = db.get_ints(with_embeddings=True, epname=request.epname)
            ids_np = np.array([intv['id'] for intv in ints], dtype=np.int64)
            # borrar datos del episodio en DB
            db.del_episode_data(eid)
        else:
            ids_np = np.array([], dtype=np.int64)

        newid = db.add_episode(request.epname, request.epdate, request.epfile, request.segments)
        if newid is None:
            raise HTTPException(status_code=500, detail="Error al añadir el episodio a la base de datos")

    # 2) Calcular embeddings (FUERA del lock de DB)
    ints = db.get_ints(with_embeddings=False, epname=request.epname)
    logging.info(f"Se han encontrado {len(ints)} segmentos para el episodio {request.epname}")

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
    auth_headers = create_auth_headers(rag_api_key, "POST", url, segments)
    
    # ENVIAR EL JSON EXACTO QUE USAMOS PARA LA FIRMA
    body_str = json.dumps(segments, separators=(',', ':'), sort_keys=True, ensure_ascii=False)
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
    remaining = db.get_ints(with_embeddings=False, epname=request.epname)
    logging.info(f"Tras actualización, quedan {len(remaining)} segmentos sin embedding para {request.epname}")
    return {"ok": True, "episode": request.epname, "segments": len(segments)}
    

@app.post("/getcontext")
def getcontext(request: GetContextRequest):
    db: SttcastDB = app.state.db
    index = app.state.index
    rag_server_url = app.state.rag_server_url
    k = request.n_fragments

    if index is None:
        raise HTTPException(status_code=500, detail="El índice FAISS aún no está inicializado")

    # Embedding de la query (no toca DB)
    qurl = f"{rag_server_url}/getoneembedding"
    query_data = {"query": request.query}
    
    # Crear headers de autenticación HMAC
    rag_api_key = app.state.rag_server_api_key
    auth_headers = create_auth_headers(rag_api_key, "POST", qurl, query_data)
    
    # ENVIAR EL JSON EXACTO QUE USAMOS PARA LA FIRMA
    body_str = json.dumps(query_data, separators=(',', ':'), sort_keys=True, ensure_ascii=False)
    r = requests.post(qurl, data=body_str, headers=auth_headers)
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    qvec = np.array(r.json().get("embedding"), dtype=np.float32).reshape(1, -1)
    faiss.normalize_L2(qvec)

    D, I = index.search(qvec, k=k)
    ids = I[0].tolist()
    if not ids or ids[0] == -1:
        raise HTTPException(status_code=404, detail="No se han encontrado segmentos relevantes para la consulta")

    rows = db.get_ints(with_embeddings=True, ids=ids)
    context = [{k: v for k, v in dict(row).items() if k != 'embedding'} for row in rows]
    logging.info(f"Contexto recuperado: {len(context)} fragmentos")
    return GetContextResponse(context=context)

class GenStatsRequest(BaseModel):
    fromdate: str = None
    todate: str = None
class GetGeneralStatsResponse(BaseModel):
    total_episodes: int
    total_duration: float
    speakers: List[dict]

# Endpoint para obtener estadísticas generales entre dos fechas
@app.post("/api/gen_stats")
def get_gen_stats(request: GenStatsRequest):
    db: SttcastDB = app.state.db
    stats = db.get_general_stats(request.fromdate, request.todate)
    # Filtra Unknown
    stats['speakers'] = [s for s in stats['speakers'] if not s['tag'].lower().startswith('unknown')]
    return GetGeneralStatsResponse(**stats)

# Endpoint para obtener las estadísticas de una lista de hablantes entre dos fechas
class SpeakerStat(BaseModel):
    tag: str
    episodes: List[dict]
    total_interventions: int
    total_duration: float
    # total_episode_interventions: int
    # total_episode_duration: float
    total_episodes_in_period: int
class GetSpeakerStatsResponse(BaseModel):
    tags: List[str]
    stats: List[SpeakerStat]
class SpeakerStatsRequest(BaseModel):
    tags: List[str]
    fromdate: str = None
    todate: str = None
@app.post("/api/speaker_stats")
def get_speaker_stats(request: SpeakerStatsRequest):
    db: SttcastDB = app.state.db
    raw_stats = db.get_speakers_stats(request.tags, request.fromdate, request.todate)
    # Coerción a SpeakerStat para validar estructura (opcional):
    try:
        stats = [SpeakerStat.model_validate(s) for s in raw_stats]
    except Exception as e:
        logging.exception("Error validando SpeakerStat")
        raise HTTPException(status_code=500, detail=f"Error de validación en stats: {e}")
    return GetSpeakerStatsResponse(tags=request.tags, stats=stats)

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
    
    
    