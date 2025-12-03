import sys
import os
import logging
import re
from tools.logs import logcfg
from tools.envvars import load_env_vars_from_directory

from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Optional
import requests
from datetime import datetime
from urllib.parse import urljoin
from api.apihmac import create_auth_headers, serialize_body
from findtime import find_nearest_time_id
from database import db  # Importar el gestor de BD


# Configuración desde variables de entorno
FILES_BASE_URL = os.getenv('FILES_BASE_URL', '/files')
WEB_SERVICE_TIMEOUT = int(os.getenv('WEB_SERVICE_TIMEOUT', '15'))
BASE_PATH = os.getenv('RAG_CLIENT_BASE_PATH', '')

# Lifespan event para inicializar BD
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    """Inicializa y cierra recursos al arrancar y parar FastAPI"""
    # Startup
    logging.info("Iniciando client_rag...")
    if app_instance.db and app_instance.db.is_available:
        await app_instance.db.initialize()
    yield
    # Shutdown
    logging.info("Deteniendo client_rag...")
    if app_instance.db and app_instance.db.is_available:
        await app_instance.db.close()

# Inicialización de FastAPI y Jinja2
app = FastAPI(lifespan=lifespan)

load_env_vars_from_directory("../../.env")

# Load authentication key
rag_server_api_key = os.getenv('RAG_SERVER_API_KEY')
if not rag_server_api_key:
    logging.error("RAG_SERVER_API_KEY not found in environment variables")
    raise ValueError("RAG_SERVER_API_KEY is required")
else:
    logging.info("RAG_SERVER_API_KEY loaded successfully")
app.rag_server_api_key = rag_server_api_key

# Load context server authentication key
context_server_api_key = os.getenv('CONTEXT_SERVER_API_KEY')
if not context_server_api_key:
    logging.error("CONTEXT_SERVER_API_KEY not found in environment variables")
    raise ValueError("CONTEXT_SERVER_API_KEY is required")
else:
    logging.info("CONTEXT_SERVER_API_KEY loaded successfully")
app.context_server_api_key = context_server_api_key

# In-memory history storage
app.query_history = []

# Database instance
app.db = db

# Load HISTORY_KEY from admin.env
history_key = os.getenv('HISTORY_KEY')
if not history_key:
    logging.warning("HISTORY_KEY not found in environment variables")
else:
    logging.info(f"HISTORY_KEY loaded successfully")
app.history_key = history_key

rag_client_host = os.getenv('RAG_CLIENT_HOST', 'localhost')
rag_client_port = int(os.getenv('RAG_CLIENT_PORT', '8004'))
context_server_host = os.getenv('CONTEXT_SERVER_HOST')
context_server_port = int(os.getenv('CONTEXT_SERVER_PORT'))
context_server_url = f"http://{context_server_host}:{context_server_port}"
get_context_path = "/getcontext"
get_context_url = urljoin(context_server_url, get_context_path)
logging.info(f"Context server URL: {get_context_url}")
app.get_context_url = get_context_url
app.context_server_url = context_server_url

# RAG Server URL - puede ser completo (RAG_SERVER_URL) o construido desde HOST:PORT
rag_server_url = os.getenv('RAG_SERVER_URL')
if not rag_server_url:
    rag_server_host = os.getenv('RAG_SERVER_HOST')
    rag_server_port = int(os.getenv('RAG_SERVER_PORT'))
    rag_server_url = f"http://{rag_server_host}:{rag_server_port}/"

relsearch_path = "/relsearch"
relsearch_url = urljoin(rag_server_url, relsearch_path)
logging.info(f"RAG server URL: {relsearch_url}")
app.relsearch_url = relsearch_url

# Detectar si estamos en Docker y ajustar la ruta de RAG_MP3_DIR
# Si la variable está configurada pero no existe (estamos en Docker), usar /app/transcripts
rag_mp3_dir = os.getenv('RAG_MP3_DIR')
in_docker = os.path.exists('/.dockerenv')

if in_docker and rag_mp3_dir and not os.path.exists(rag_mp3_dir):
    # En Docker, usar la ruta montada en el volumen
    rag_mp3_dir = '/app/transcripts'
    logging.info("Running in Docker, using /app/transcripts mount point")

app.rag_mp3_dir = rag_mp3_dir
logging.info(f"RAG MP3 directory: {rag_mp3_dir}")

podcast_name = os.getenv('PODCAST_NAME')
app.podcast_name = podcast_name
logging.info(f"Podcast Name: {podcast_name}")

templates = Jinja2Templates(directory="templates")

app.mount("/static",
          StaticFiles(directory="static"), name="static")

# Mount transcripts directory only if it exists
if rag_mp3_dir and os.path.exists(rag_mp3_dir):
    app.mount("/transcripts", StaticFiles(directory=rag_mp3_dir), name="transcripts")
    logging.info(f"Mounted /transcripts to {rag_mp3_dir}")
else:
    logging.warning(f"RAG_MP3_DIR not found or not configured: {rag_mp3_dir}")
# ------------------------
#   Utilidades
# ------------------------

def get_client_ip_from_request(request: Request) -> str:
    """Obtiene la IP del cliente considerando proxies."""
    forwarded = request.headers.get('X-Forwarded-For')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.client.host if request.client else 'unknown'

def get_transcript_url(filepath):
    """Construye URL para transcripts considerando el BASE_PATH."""
    if BASE_PATH:
        return f"{BASE_PATH}{filepath}"
    return filepath

def get_mark(file, seconds):
    """Función para obtener la marca temporal en el archivo."""
    return f"mark_{int(seconds)}"

def build_file_url(file, seconds):
    mark = get_mark(file, seconds)
    return f"{FILES_BASE_URL}/{file}#{mark}"

def format_time(seconds):
    """Formatea segundos en mm:ss"""
    mins = int(float(seconds) // 60)
    secs = int(float(seconds) % 60)
    return f"{mins}:{secs:02d}"

# ------------------------
#   Modelos
# ------------------------

class AskRequest(BaseModel):
    question: str
    language: str = 'es'

# ------------------------
#   Endpoints
# ------------------------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Página principal"""
    return templates.TemplateResponse("index.html", 
                                    {
                                     "request": request,
                                     "podcast_name": app.podcast_name
                                    })

@app.post("/api/ask")
async def ask_question(payload: AskRequest, request: Request):
    """Procesa la pregunta enviada"""
    question = payload.question.strip() if payload.question else ""
    language = payload.language

    if not question:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La pregunta no puede estar vacía"
        )

    # Check if this is a history query
    if app.history_key:
        # Check if question matches the exact history key (return latest)
        if question == app.history_key:
            if app.query_history:
                latest_entry = app.query_history[-1]
                logging.info(f"RETURNING HISTORY ENTRY: query='{latest_entry['query']}'")
                return {
                    "success": True,
                    "response": latest_entry["response"],
                    "references": latest_entry["references"],
                    "timestamp": latest_entry["timestamp"],
                    "query": latest_entry["query"]
                }
            else:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="No hay historial disponible"
                )
        
        # Check if question matches the pattern HISTORY_KEY-number
        pattern = f"^{re.escape(app.history_key)}-(\\d+)$"
        match = re.match(pattern, question)
        if match:
            index_back = int(match.group(1))
            if index_back > 0 and index_back <= len(app.query_history):
                # Return the entry from n positions back (1-based indexing)
                entry = app.query_history[-(index_back)]
                logging.info(f"RETURNING HISTORY ENTRY #{index_back}: query='{entry['query']}'")
                return {
                    "success": True,
                    "response": entry["response"],
                    "references": entry["references"],
                    "timestamp": entry["timestamp"],
                    "query": entry["query"]
                }
            else:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"No hay entrada de historial en la posición {index_back}"
                )

    try:
        gcpayload = {
            "query": payload.question,
            "n_fragments": 100
        }
        
        # Crear headers de autenticación HMAC para context server
        auth_headers = create_auth_headers(
            app.context_server_api_key,
            "POST",
            "/getcontext",
            gcpayload,
            "client_rag_service"
        )
        
        # ENVIAR EL JSON EXACTO QUE USAMOS PARA LA FIRMA
        body_str = serialize_body(gcpayload)
        gcresp = requests.post(app.get_context_url, data=body_str, headers=auth_headers)
        
        if gcresp.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Error al obtener contexto: {gcresp.status_code}"
            )
        data = gcresp.json()
        logging.info(f"Respuesta del servicio de contexto: {len(data.get('context'))} fragmentos obtenidos")
        if 'context' in data:
            context = data['context']
        # Pregunta al servicio de búsqueda RAG
        client_ip = get_client_ip_from_request(request)
        relquery_data = {
            "query": payload.question,
            "embeddings": context,
            "requester": client_ip
        }
        
        # Crear headers de autenticación HMAC
        auth_headers = create_auth_headers(
            app.rag_server_api_key,
            "POST",
            "/relsearch",
            relquery_data,
            "client_rag_service"
        )
        
        # ENVIAR EL JSON EXACTO QUE USAMOS PARA LA FIRMA
        body_str = serialize_body(relquery_data)
        relresp = requests.post(app.relsearch_url, data=body_str, headers=auth_headers)
        if relresp.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Error al realizar búsqueda: {relresp.status_code}"
            )
        reldata = relresp.json()
        logging.info(f"Respuesta del servicio de búsqueda: {reldata}")
        
        references = []
        if "refs" in reldata and reldata["refs"]:
            logging.info(f"Referencias encontradas: {len(reldata['refs'])}")
            for ref in reldata["refs"]:
                if all(k in ref for k in ['label', 'file', 'time']):
                    if app.rag_mp3_dir:
                        logging.info(f"Procesando referencia: {ref['label']} - {ref['file']} a {ref['time']} segundos")
                        html_file = {
                            l: get_transcript_url(os.path.join("/transcripts", f"{ref['file']}_whisper_audio_{l}.html")) for l in ['es', 'en']
                        }
                        real_file = {
                            l: os.path.join(app.rag_mp3_dir, f"{ref['file']}_whisper_audio_{l}.html") for l in ['es', 'en']
                        }
                        logging.info(f"Archivos HTML: {html_file}")
                        logging.info(f"Buscando ID más cercano para {ref['time']} segundos en {html_file['es']}")
                        nearest_id = find_nearest_time_id(
                            real_file['es'], 
                            ref['time']
                        )
                        logging.info(f"ID más cercano encontrado: {nearest_id}")
                        ref['hyperlink'] = {
                            l: f"{html_file[l]}#{nearest_id}" if nearest_id else None
                            for l in ['es', 'en']
                        }
                        logging.info(f"Referencia con hipervínculo: {ref['hyperlink']}")

                    references.append({
                        "label": ref["label"],
                        "tag": ref.get("tag", ""),
                        "file": ref["file"],
                        "time": ref["time"],
                        "url": build_file_url(ref["file"], ref["time"]),
                        "formatted_time": format_time(ref["time"]),
                        "hyperlink": ref.get("hyperlink", None)
                    })

        timestamp_iso = datetime.now().isoformat()
        
        # Create response
        response_data = {
            "success": True,
            "response": reldata["search"],
            "references": references,
            "timestamp": timestamp_iso
        }
        
        # Store this query and response in history
        if history_key:
            history_entry = {
                "query": question,
                "response": reldata["search"],
                "references": references,
                "timestamp": timestamp_iso
            }
            app.query_history.append(history_entry)
            logging.info(f"Stored query in history. Total entries: {len(app.query_history)}")

        # ===== GUARDAR EN BASE DE DATOS (SOLO /api/ask) =====
        # Guardar la pregunta y respuesta en BD para futuro caché semántico
        if app.db and app.db.is_available:
            try:
                # Obtener embedding de la pregunta del RAG server
                query_embedding = None
                try:
                    embed_url = f"{app.relsearch_url.rsplit('/', 1)[0]}/getoneembedding"
                    embed_data = {"query": question}
                    auth_headers = create_auth_headers(
                        app.rag_server_api_key,
                        "POST",
                        "/getoneembedding",
                        embed_data,
                        "client_rag_service"
                    )
                    body_str = serialize_body(embed_data)
                    embed_resp = requests.post(embed_url, data=body_str, headers=auth_headers, timeout=15)
                    if embed_resp.status_code == 200:
                        query_embedding = embed_resp.json().get("embedding")
                        logging.debug(f"Embedding obtenido: {len(query_embedding) if query_embedding else 0} dimensiones")
                except Exception as e:
                    logging.debug(f"No se pudo obtener embedding (continuando sin él): {e}")
                
                # Guardar de forma asíncrona sin bloquear
                import asyncio
                asyncio.create_task(
                    app.db.save_query(
                        query_text=question,
                        response_text=reldata["search"],
                        query_embedding=query_embedding,
                        podcast_name=app.podcast_name
                    )
                )
                logging.info("💾 Query guardada en BD para caché semántico")
            except Exception as e:
                logging.warning(f"⚠️  Error al guardar en BD (no crítico): {e}")

        return response_data

    except requests.exceptions.Timeout:
        raise HTTPException(status_code=504, detail="Timeout: El servicio web tardó demasiado en responder")
    except requests.exceptions.ConnectionError:
        raise HTTPException(status_code=503, detail="Error de conexión con el servicio web")
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=f"Error en la petición: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")

# Función que pregunta al endpoint de context server gen_stats para obtener estadísticas generales
# a partir de dos fechas
class GenStatsRequest(BaseModel):
    fromdate: str = None
    todate: str = None
@app.post("/api/gen_stats")
async def get_gen_stats(request: GenStatsRequest):
    logging.info(f"/api/gen_stats called with fromdate={request.fromdate}, todate={request.todate}")
    logging.info(f"Llamando a {app.context_server_url}/api/gen_stats con {request.dict()}")
    try:
        payload = request.dict()
        
        # Crear headers de autenticación HMAC para context server
        auth_headers = create_auth_headers(
            app.context_server_api_key,
            "POST",
            "/api/gen_stats",
            payload,
            "client_rag_service"
        )
        
        # ENVIAR EL JSON EXACTO QUE USAMOS PARA LA FIRMA
        body_str = serialize_body(payload)
        response = requests.post(f"{app.context_server_url}/api/gen_stats", data=body_str, headers=auth_headers, timeout=60)
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail=response.text)
        
        result = response.json()
        return result
    except requests.exceptions.Timeout:
        logging.error("Timeout al consultar estadísticas generales")
        raise HTTPException(status_code=504, detail="Timeout: La consulta está tardando demasiado.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")

# Función que pregunta al endpoint de context server speaker_stats para obtener estadísticas de una lista de hablantes
# a partir de dos fechas
class SpeakerStatsRequest(BaseModel):
    tags: List[str]
    fromdate: str = None
    todate: str = None
@app.post("/api/speaker_stats")
async def get_speaker_stats(request: SpeakerStatsRequest):
    logging.info(f"/api/speaker_stats called with {request}")
    logging.info(f"Llamando a {app.context_server_url}/api/speaker_stats con {request.dict()}")
    try:
        payload = request.dict()
        
        # Crear headers de autenticación HMAC para context server
        auth_headers = create_auth_headers(
            app.context_server_api_key,
            "POST",
            "/api/speaker_stats",
            payload,
            "client_rag_service"
        )
        
        # ENVIAR EL JSON EXACTO QUE USAMOS PARA LA FIRMA
        body_str = serialize_body(payload)
        response = requests.post(f"{app.context_server_url}/api/speaker_stats", data=body_str, headers=auth_headers, timeout=120)
        logging.info(f"Respuesta del context server recibida: {response.status_code}")
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail=response.text)
        
        result = response.json()
        logging.info(f"Datos procesados exitosamente para {len(request.tags)} intervinientes")
        return result
    except requests.exceptions.Timeout:
        logging.error("Timeout al consultar estadísticas de intervinientes")
        raise HTTPException(status_code=504, detail="Timeout: La consulta está tardando demasiado. Intenta con un período de fechas más pequeño o menos intervinientes.")
    except Exception as e:
        logging.error(f"Error en speaker_stats: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")

@app.get("/health")
async def health_check():
    """Endpoint de salud"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "config": {
            "api_url": context_server_url,
            "files_base_url": FILES_BASE_URL,
            "timeout": WEB_SERVICE_TIMEOUT
        }
    }

if __name__ == "__main__":
    import uvicorn
    logcfg(__file__)


    uvicorn.run(
        "client_rag:app",
        host=rag_client_host,
        port=rag_client_port,
        reload=False,  # Desactivado para evitar bucle infinito con archivos .log
        log_level="info"
    )
    
