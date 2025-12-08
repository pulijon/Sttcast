import sys
import os
import logging
import re
from tools.logs import logcfg
from tools.envvars import load_env_vars_from_directory

# Cargar variables de entorno ANTES de importar queriesdb
# para que la instancia global 'db' tenga acceso a las variables
# Usar ruta relativa al archivo actual
env_dir = os.path.join(os.path.dirname(__file__), '..', '..')
load_env_vars_from_directory(os.path.join(env_dir, '.env'))

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
from queriesdb import db  # Importar el gestor de BD (después de cargar env vars)
from cache_buster import get_static_url


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
        # Crear tablas si no existen
        await app_instance.db.create_tables()
    yield
    # Shutdown
    logging.info("Deteniendo client_rag...")
    if app_instance.db and app_instance.db.is_available:
        await app_instance.db.close()

# Inicialización de FastAPI y Jinja2
app = FastAPI(lifespan=lifespan)

# Las variables de entorno ya fueron cargadas al inicio del archivo

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

# Load PGV_KEY from admin.env
pgv_key = os.getenv('PGV_KEY')
if not pgv_key:
    logging.warning("PGV_KEY not found in environment variables")
else:
    logging.info(f"PGV_KEY loaded successfully")
app.pgv_key = pgv_key

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

# Usar rutas relativas al archivo actual para templates y static
current_dir = os.path.dirname(__file__)
templates_dir = os.path.join(current_dir, "templates")
static_dir = os.path.join(current_dir, "static")

templates = Jinja2Templates(directory=templates_dir)

app.mount("/static",
          StaticFiles(directory=static_dir), name="static")

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
                                     "podcast_name": app.podcast_name,
                                     "base_path": BASE_PATH,
                                     "css_url": get_static_url("css/client_rag.css", base_path=BASE_PATH),
                                     "js_url": get_static_url("js/client_rag.js", base_path=BASE_PATH)
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
        # Paso 1: Obtener embedding de la pregunta
        gcpayload_emb = {
            "query": payload.question,
            "n_fragments": 1, # No importa, solo queremos el embedding
            "only_embedding": True
        }
        
        auth_headers_emb = create_auth_headers(
            app.context_server_api_key,
            "POST",
            "/getcontext",
            gcpayload_emb,
            "client_rag_service"
        )
        
        body_str_emb = serialize_body(gcpayload_emb)
        gcresp_emb = requests.post(app.get_context_url, data=body_str_emb, headers=auth_headers_emb, timeout=60)
        
        if gcresp_emb.status_code != 200:
             raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Error al obtener embedding de la pregunta: {gcresp_emb.status_code}"
            )
        
        data_emb = gcresp_emb.json()
        query_embedding = data_emb.get('query_embedding')
        
        if not query_embedding:
             raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="No se pudo obtener el embedding de la pregunta"
            )

        # Paso 2: Obtener contexto usando el embedding
        gcpayload = {
            "query": payload.question,
            "n_fragments": 100,
            "query_embedding": query_embedding
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
        gcresp = requests.post(app.get_context_url, data=body_str, headers=auth_headers, timeout=60)
        
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
        relresp = requests.post(app.relsearch_url, data=body_str, headers=auth_headers, timeout=60)
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
        saved_uuid = None
        logging.info(f"[DEBUG] Verificando guardado en BD. DB disponible: {app.db and app.db.is_available}")
        if app.db and app.db.is_available:
            try:
                # El embedding de la pregunta ya lo tenemos de la llamada inicial a /getcontext
                # query_embedding ya contiene el embedding
                logging.info(f"[DEBUG] query_embedding existe: {query_embedding is not None}, tipo: {type(query_embedding) if query_embedding else 'None'}")
                
                if query_embedding:
                    # Preparar response_data completo para almacenar
                    response_data_to_save = {
                        "response": reldata["search"],  # Contiene {es: ..., en: ...}
                        "references": references,
                        "timestamp": timestamp_iso,
                        "query": question
                    }
                    
                    # Guardar en BD con estructura completa
                    result = await app.db.save_query(
                        query_text=question,
                        response_text=reldata["search"].get("es", ""),  # Español como texto plano
                        response_data=response_data_to_save,
                        query_embedding=query_embedding,
                        podcast_name=app.podcast_name
                    )
                    if result and result.get('uuid'):
                        saved_uuid = result['uuid']
                        # Construir URL para recuperar la consulta (endpoint HTML)
                        saved_query_url = f"{BASE_PATH}/savedquery/{saved_uuid}"
                        response_data['saved_query_url'] = saved_query_url
                        logging.info(f"Pregunta guardada en BD con UUID: {saved_uuid}")
                        logging.info(f"URL para recuperar: {saved_query_url}")
                    
                    # Buscar consultas similares (excluyendo la actual si tiene UUID)
                    similar_queries = await app.db.search_similar_queries(
                        query_embedding=query_embedding,
                        podcast_name=app.podcast_name,
                        limit=10,  # Obtener hasta 10 para clasificar por niveles
                        similarity_threshold=0.60  # Umbral mínimo para capturar similitud baja
                    )
                    
                    # Clasificar por niveles de similitud
                    if similar_queries:
                        # Filtrar la consulta actual si existe
                        if saved_uuid:
                            similar_queries = [q for q in similar_queries if str(q.get('uuid')) != saved_uuid]
                        
                        # Clasificar en tres niveles
                        high_similarity = []
                        medium_similarity = []
                        low_similarity = []
                        
                        for query in similar_queries:
                            similarity = query.get('similarity', 0)
                            query_info = {
                                'uuid': str(query['uuid']),
                                'query_text': query['query_text'],
                                'similarity': round(similarity, 3),
                                'url': f"{BASE_PATH}/savedquery/{query['uuid']}"
                            }
                            
                            if similarity >= 0.75:
                                high_similarity.append(query_info)
                            elif similarity >= 0.65:
                                medium_similarity.append(query_info)
                            elif similarity >= 0.60:
                                low_similarity.append(query_info)
                        
                        response_data['similar_queries'] = {
                            'high': high_similarity[:3],     # Máximo 3 por nivel
                            'medium': medium_similarity[:3],
                            'low': low_similarity[:3]
                        }
                        logging.info(f"Consultas similares encontradas: {len(high_similarity)} altas, {len(medium_similarity)} medias, {len(low_similarity)} bajas")
                        logging.info(f"[DEBUG] response_data ahora incluye similar_queries: {response_data.get('similar_queries') is not None}")
                    
                else:
                    logging.warning("No se pudo obtener embedding para guardar en BD")
            except Exception as e:
                logging.error(f"Error guardando en BD: {e}")
        
        logging.info(f"[DEBUG] Antes de return - response_data tiene similar_queries: {response_data.get('similar_queries') is not None}")
        if response_data.get('similar_queries'):
            logging.info(f"[DEBUG] Contenido de similar_queries: {response_data['similar_queries']}")
        
        return response_data

    except requests.exceptions.Timeout:
        raise HTTPException(status_code=504, detail="Timeout: El servicio web tardó demasiado en responder")
    except requests.exceptions.ConnectionError:
        raise HTTPException(status_code=503, detail="Error de conexión con el servicio web")
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=f"Error en la petición: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")

@app.get("/api/savedquery/{query_uuid}")
async def get_saved_query(query_uuid: str, request: Request):
    """
    Recupera una consulta guardada por su UUID
    
    Retorna el mismo formato que /api/ask cuando hace match,
    permitiendo acceder a cualquier consulta almacenada mediante su URL.
    """
    if not app.db or not app.db.is_available:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Base de datos no disponible"
        )
    
    try:
        # Obtener query de la BD
        query_data = await app.db.get_query_by_uuid(query_uuid)
        
        if not query_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No se encontró ninguna consulta con UUID: {query_uuid}"
            )
        
        # Si existe response_data (nuevo formato), usarlo; si no, usar response_text (compatibilidad)
        import json
        if query_data.get('response_data'):
            # Nuevo formato: respuesta completa con referencias
            stored_response = json.loads(query_data['response_data'])
            response_data = {
                "success": True,
                "response": stored_response.get('response', query_data.get('response_text', '')),
                "references": stored_response.get('references', []),
                "timestamp": query_data['created_at'].isoformat(),
                "query": query_data['query_text'],
                "podcast_name": query_data.get('podcast_name'),
                "uuid": str(query_data['uuid']),
                "saved_query_url": f"{BASE_PATH}/api/savedquery/{query_uuid}"
            }
        else:
            # Formato antiguo: solo texto plano
            response_data = {
                "success": True,
                "response": {"es": query_data['response_text'], "en": query_data['response_text']},
                "references": [],
                "timestamp": query_data['created_at'].isoformat(),
                "query": query_data['query_text'],
                "podcast_name": query_data.get('podcast_name'),
                "uuid": str(query_data['uuid']),
                "saved_query_url": f"{BASE_PATH}/api/savedquery/{query_uuid}"
            }
        
        logging.info(f"Consulta recuperada: UUID={query_uuid}, Query='{query_data['query_text'][:50]}...'")
        return response_data
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error al recuperar consulta guardada: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno al recuperar la consulta: {str(e)}"
        )

@app.get("/savedquery/{query_uuid}")
async def get_saved_query_html(query_uuid: str, request: Request):
    """
    Renderiza una consulta guardada en formato HTML usando la plantilla existente
    
    Permite compartir URLs que se visualizan igual que consultas normales,
    facilitando el sistema de caché futuro.
    """
    if not app.db or not app.db.is_available:
        return templates.TemplateResponse("index.html", 
                                        {
                                         "request": request,
                                         "podcast_name": app.podcast_name,
                                         "base_path": BASE_PATH,
                                         "css_url": get_static_url("css/client_rag.css", base_path=BASE_PATH),
                                         "js_url": get_static_url("js/client_rag.js", base_path=BASE_PATH),
                                         "error": "Base de datos no disponible"
                                        })
    
    try:
        # Obtener query de la BD
        query_data = await app.db.get_query_by_uuid(query_uuid)
        
        if not query_data:
            return templates.TemplateResponse("index.html", 
                                            {
                                             "request": request,
                                             "podcast_name": app.podcast_name,
                                             "base_path": BASE_PATH,
                                             "css_url": get_static_url("css/client_rag.css", base_path=BASE_PATH),
                                             "js_url": get_static_url("js/client_rag.js", base_path=BASE_PATH),
                                             "error": f"No se encontró ninguna consulta con UUID: {query_uuid}"
                                            })
        
        # Parsear response_data almacenado
        import json
        if query_data.get('response_data'):
            stored_response = json.loads(query_data['response_data'])
            saved_query_data = {
                "query": query_data['query_text'],
                "response": stored_response.get('response', {}),
                "references": stored_response.get('references', []),
                "timestamp": query_data['created_at'].isoformat(),
                "uuid": str(query_data['uuid']),
                "saved_query_url": f"{BASE_PATH}/savedquery/{query_uuid}"
            }
        else:
            # Compatibilidad con formato antiguo
            saved_query_data = {
                "query": query_data['query_text'],
                "response": {"es": query_data.get('response_text', ''), "en": query_data.get('response_text', '')},
                "references": [],
                "timestamp": query_data['created_at'].isoformat(),
                "uuid": str(query_data['uuid']),
                "saved_query_url": f"{BASE_PATH}/savedquery/{query_uuid}"
            }
        
        # Buscar consultas similares usando el embedding de la consulta guardada
        if query_data.get('query_embedding'):
            try:
                # Convertir el string del embedding de vuelta a lista
                # El embedding está almacenado como string '[x,y,z,...]'
                embedding_str = query_data['query_embedding']
                if isinstance(embedding_str, str):
                    # Parsear el string a lista de floats
                    import ast
                    query_embedding = ast.literal_eval(embedding_str)
                else:
                    query_embedding = embedding_str
                
                similar_queries = await app.db.search_similar_queries(
                    query_embedding=query_embedding,
                    podcast_name=app.podcast_name,
                    limit=10,
                    similarity_threshold=0.60
                )
                
                if similar_queries:
                    # Filtrar la consulta actual
                    similar_queries = [q for q in similar_queries if str(q.get('uuid')) != query_uuid]
                    
                    # Clasificar en tres niveles
                    high_similarity = []
                    medium_similarity = []
                    low_similarity = []
                    
                    for query in similar_queries:
                        similarity = query.get('similarity', 0)
                        query_info = {
                            'uuid': str(query['uuid']),
                            'query_text': query['query_text'],
                            'similarity': round(similarity, 3),
                            'url': f"{BASE_PATH}/savedquery/{query['uuid']}"
                        }
                        
                        if similarity >= 0.75:
                            high_similarity.append(query_info)
                        elif similarity >= 0.65:
                            medium_similarity.append(query_info)
                        elif similarity >= 0.60:
                            low_similarity.append(query_info)
                    
                    saved_query_data['similar_queries'] = {
                        'high': high_similarity[:3],
                        'medium': medium_similarity[:3],
                        'low': low_similarity[:3]
                    }
                    logging.info(f"Consultas similares para {query_uuid}: {len(high_similarity)} altas, {len(medium_similarity)} medias, {len(low_similarity)} bajas")
            except Exception as e:
                logging.error(f"Error buscando consultas similares para consulta guardada: {e}")
        
        logging.info(f"Renderizando consulta guardada: UUID={query_uuid}")
        
        # Convertir a JSON para pasar a JavaScript
        saved_query_json = json.dumps(saved_query_data)
        
        return templates.TemplateResponse("index.html", 
                                        {
                                         "request": request,
                                         "podcast_name": app.podcast_name,
                                         "base_path": BASE_PATH,
                                         "css_url": get_static_url("css/client_rag.css", base_path=BASE_PATH),
                                         "js_url": get_static_url("js/client_rag.js", base_path=BASE_PATH),
                                         "saved_query": saved_query_json
                                        })
        
    except Exception as e:
        logging.error(f"Error al renderizar consulta guardada: {e}")
        return templates.TemplateResponse("index.html", 
                                        {
                                         "request": request,
                                         "podcast_name": app.podcast_name,
                                         "base_path": BASE_PATH,
                                         "css_url": get_static_url("css/client_rag.css", base_path=BASE_PATH),
                                         "js_url": get_static_url("js/client_rag.js", base_path=BASE_PATH),
                                         "error": f"Error al cargar la consulta: {str(e)}"
                                        })

@app.get("/pgv/{clave}", response_class=HTMLResponse)
async def list_all_queries(clave: str, request: Request):
    """
    Lista todas las consultas guardadas en la base de datos en formato HTML
    Requiere autenticación mediante PGV_KEY
    """
    # Verificar la clave
    if not app.pgv_key or clave != app.pgv_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso no autorizado"
        )
    
    if not app.db or not app.db.is_available:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Base de datos no disponible"
        )
    
    try:
        # Obtener todas las consultas de la base de datos
        # Podemos usar limit alto para obtener todas, o implementar paginación si es necesario
        all_queries = await app.db.get_all_queries(
            podcast_name=app.podcast_name,
            limit=1000,  # Ajustar según necesidades
            offset=0
        )
        
        # Construir la tabla HTML
        html_content = f"""
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Consultas Guardadas - {app.podcast_name}</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 20px;
            background-color: #f5f5f5;
        }}
        h1 {{
            color: #333;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            background-color: white;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        th {{
            background-color: #4CAF50;
            color: white;
            padding: 12px;
            text-align: left;
            font-weight: bold;
        }}
        td {{
            padding: 10px;
            border-bottom: 1px solid #ddd;
        }}
        tr:hover {{
            background-color: #f5f5f5;
        }}
        a {{
            color: #1976d2;
            text-decoration: none;
        }}
        a:hover {{
            text-decoration: underline;
        }}
        .query-text {{
            max-width: 600px;
            word-wrap: break-word;
        }}
        .timestamp {{
            white-space: nowrap;
            color: #666;
        }}
        .total-count {{
            margin: 10px 0;
            color: #666;
        }}
    </style>
</head>
<body>
    <h1>Consultas Guardadas - {app.podcast_name}</h1>
    <div class="total-count">Total de consultas: {len(all_queries)}</div>
    <table>
        <thead>
            <tr>
                <th>#</th>
                <th>Fecha</th>
                <th>Consulta</th>
                <th>URL Persistente</th>
            </tr>
        </thead>
        <tbody>
"""
        
        # Añadir filas para cada consulta
        for idx, query in enumerate(all_queries, 1):
            query_uuid = str(query.get('uuid', ''))
            query_text = query.get('query_text', '')
            created_at = query.get('created_at', '')
            
            # Construir URL persistente usando el UUID
            query_url = f"{BASE_PATH}/savedquery/{query_uuid}"
            
            # Formatear fecha
            if isinstance(created_at, datetime):
                formatted_date = created_at.strftime('%Y-%m-%d %H:%M:%S')
            else:
                formatted_date = str(created_at)
            
            html_content += f"""
            <tr>
                <td>{idx}</td>
                <td class="timestamp">{formatted_date}</td>
                <td class="query-text">{query_text}</td>
                <td><a href="{query_url}" target="_blank">Ver consulta</a></td>
            </tr>
"""
        
        html_content += """
        </tbody>
    </table>
</body>
</html>
"""
        
        return HTMLResponse(content=html_content)
        
    except Exception as e:
        logging.error(f"Error al listar consultas: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al obtener las consultas: {str(e)}"
        )

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
    
