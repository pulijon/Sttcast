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
from fastapi.responses import JSONResponse, HTMLResponse, Response, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel
from typing import List, Optional
import secrets
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
TRANSCRIPTS_URL_EXTERNAL = os.getenv('TRANSCRIPTS_URL_EXTERNAL')  # URL base de S3 u otro storage externo

# Thresholds de similitud para clasificación de consultas similares
QUERIES_HIGH_SIMILARITY = float(os.getenv('QUERIES_HIGH_SIMILARITY', '0.75'))
QUERIES_MEDIUM_SIMILARITY = float(os.getenv('QUERIES_MEDIUM_SIMILARITY', '0.65'))
QUERIES_LOW_SIMILARITY = float(os.getenv('QUERIES_LOW_SIMILARITY', '0.60'))

# Autenticación del panel de administración
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD')
SESSION_SECRET = os.getenv('SESSION_SECRET', secrets.token_hex(32))

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

from middleware_audio_fallback import AudioFallbackMiddleware
app.add_middleware(AudioFallbackMiddleware)

# Middleware de sesiones para el panel de administración
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="sttcast_admin",
    max_age=3600,  # 1 hora
    same_site="strict"
)

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

# Almacenar configuración en app para usar en endpoints
app.transcripts_url_external = TRANSCRIPTS_URL_EXTERNAL
app.transcripts_local_dir = rag_mp3_dir if rag_mp3_dir and os.path.exists(rag_mp3_dir) else None

if app.transcripts_local_dir:
    logging.info(f"Transcripts: Local directory available at {app.transcripts_local_dir}")
else:
    logging.warning(f"RAG_MP3_DIR not found or not configured: {rag_mp3_dir}")

if app.transcripts_url_external:
    logging.info(f"Transcripts: External URL configured: {app.transcripts_url_external}")
else:
    logging.info("Transcripts: No external URL configured, using local only")
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

async def get_transcript_file(file_path: str) -> tuple:
    """
    Obtiene archivo de transcripción desde fuente externa o local.
    Estrategia híbrida: intenta S3 primero, luego filesystem local.
    
    Retorna: (contenido, content_type, headers_dict) o (None, None, {}) si no existe
    """
    import mimetypes
    
    # Intentar S3 primero si está configurado
    if app.transcripts_url_external:
        try:
            external_url = f"{app.transcripts_url_external}/{file_path}"
            logging.info(f"Intentando obtener desde S3: {external_url}")
            
            response = requests.get(external_url, timeout=10)
            if response.status_code == 200:
                content_type = response.headers.get('content-type', 'application/octet-stream')
                # Devolver headers relevantes de S3 para Range support
                s3_headers = {}
                if 'content-length' in response.headers:
                    s3_headers['content-length'] = response.headers['content-length']
                if 'accept-ranges' in response.headers:
                    s3_headers['accept-ranges'] = response.headers['accept-ranges']
                logging.info(f"Archivo obtenido desde S3: {file_path}")
                return response.content, content_type, s3_headers
            elif response.status_code == 404:
                logging.debug(f"Archivo no encontrado en S3: {file_path}")
            else:
                logging.warning(f"Error al obtener de S3 ({response.status_code}): {file_path}")
        except requests.exceptions.Timeout:
            logging.warning(f"Timeout al intentar obtener de S3: {file_path}")
        except Exception as e:
            logging.warning(f"Error al obtener de S3: {e}")
    
    # Fallback a filesystem local
    if app.transcripts_local_dir:
        try:
            local_path = os.path.join(app.transcripts_local_dir, file_path)
            # Seguridad: evitar path traversal
            local_path = os.path.normpath(local_path)
            if not local_path.startswith(os.path.normpath(app.transcripts_local_dir)):
                logging.error(f"Intento de path traversal: {file_path}")
                return None, None, {}
            
            if os.path.isfile(local_path):
                logging.info(f"Archivo obtenido desde filesystem local: {file_path}")
                content_type, _ = mimetypes.guess_type(local_path)
                if content_type is None:
                    content_type = 'application/octet-stream'
                
                file_size = os.path.getsize(local_path)
                with open(local_path, 'rb') as f:
                    return f.read(), content_type, {'content-length': str(file_size)}
            else:
                logging.debug(f"Archivo no encontrado en filesystem: {local_path}")
        except Exception as e:
            logging.error(f"Error al obtener del filesystem: {e}")
    
    # No encontrado en ningún lugar
    logging.warning(f"Archivo no encontrado en ninguna fuente: {file_path}")
    return None, None, {}

# ------------------------
#   Modelos
# ------------------------

class AskRequest(BaseModel):
    question: str
    language: str = 'es'
    skip_similarity_check: bool = False

class CheckSimilarRequest(BaseModel):
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

@app.get("/transcripts/{file_path:path}")
async def get_transcript(file_path: str, request: Request):
    """
    Endpoint proxy híbrido para archivos de transcripción.
    Intenta obtener de S3 primero, luego del filesystem local.
    Soporta HTTP Range Requests para seek eficiente en audio/video (marcas de tiempo).
    
    Para archivos grandes (3+ horas), esto es crítico: solo descarga los bytes necesarios.
    """
    
    # Si es un Range Request a S3, manejarlo especialmente
    range_header = request.headers.get("Range")
    if range_header and app.transcripts_url_external:
        return await get_transcript_with_range(file_path, range_header)
    
    # Si no es Range Request, obtener archivo completo (para fallback local)
    content, content_type, source_headers = await get_transcript_file(file_path)
    
    if content is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Archivo no encontrado: {file_path}"
        )
    
    file_size = len(content)
    
    # Headers comunes
    headers = {
        "Cache-Control": "public, max-age=86400",  # Cache 24 horas
        "Content-Disposition": f"inline; filename={os.path.basename(file_path)}",
        "Accept-Ranges": "bytes",  # Indicar que soportamos rangos
    }
    headers.update(source_headers)
    
    # Procesar Range Request si existe
    if range_header:
        try:
            if not range_header.startswith("bytes="):
                return Response(
                    content=content,
                    media_type=content_type,
                    status_code=200,
                    headers=headers
                )
            
            ranges_str = range_header[6:]
            
            # Soportar single range
            if "," not in ranges_str and "-" in ranges_str:
                start_str, end_str = ranges_str.split("-", 1)
                
                start = int(start_str) if start_str else 0
                end = int(end_str) if end_str else file_size - 1
                
                if start < 0 or start >= file_size or end >= file_size or start > end:
                    headers["Content-Range"] = f"bytes */{file_size}"
                    raise HTTPException(
                        status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE,
                        headers=headers,
                        detail="Range no satisfiable"
                    )
                
                partial_content = content[start:end + 1]
                headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
                
                logging.info(f"Range Request: {file_path} bytes {start}-{end}/{file_size}")
                
                return Response(
                    content=partial_content,
                    media_type=content_type,
                    status_code=206,
                    headers=headers
                )
        except (ValueError, IndexError):
            logging.warning(f"Error parsing Range header: {range_header}")
            pass
    
    # Devolver archivo completo
    return Response(
        content=content,
        media_type=content_type,
        status_code=200,
        headers=headers
    )


async def get_transcript_with_range(file_path: str, range_header: str):
    """
    Maneja Range Requests eficientemente para S3.
    En lugar de descargar todo el archivo, solo descarga el rango solicitado.
    
    Esto es crítico para archivos de 3+ horas.
    """
    external_url = f"{app.transcripts_url_external}/{file_path}"
    
    try:
        logging.info(f"Range Request a S3: {file_path} - {range_header}")
        
        # Pasar el Range header directamente a S3
        headers = {"Range": range_header}
        response = requests.get(external_url, headers=headers, timeout=10)
        
        # S3 devuelve 206 si puede satisfacer el rango
        if response.status_code == 206:
            logging.info(f"Rango obtenido de S3: {file_path}")
            return Response(
                content=response.content,
                media_type=response.headers.get('content-type', 'application/octet-stream'),
                status_code=206,
                headers={
                    "Cache-Control": "public, max-age=86400",
                    "Content-Disposition": f"inline; filename={os.path.basename(file_path)}",
                    "Accept-Ranges": "bytes",
                    "Content-Range": response.headers.get('content-range', ''),
                    "Content-Length": str(len(response.content))
                }
            )
        
        # Si S3 devuelve 200, significa que no soporta rangos (raro)
        # Descargar todo y procesar el rango localmente
        elif response.status_code == 200:
            logging.warning(f"S3 no devolvió 206, procesando rango localmente: {file_path}")
            
            try:
                ranges_str = range_header[6:]
                if "," not in ranges_str and "-" in ranges_str:
                    start_str, end_str = ranges_str.split("-", 1)
                    start = int(start_str) if start_str else 0
                    end = int(end_str) if end_str else len(response.content) - 1
                    
                    partial = response.content[start:end + 1]
                    return Response(
                        content=partial,
                        media_type=response.headers.get('content-type', 'application/octet-stream'),
                        status_code=206,
                        headers={
                            "Cache-Control": "public, max-age=86400",
                            "Content-Disposition": f"inline; filename={os.path.basename(file_path)}",
                            "Accept-Ranges": "bytes",
                            "Content-Range": f"bytes {start}-{end}/{len(response.content)}",
                            "Content-Length": str(len(partial))
                        }
                    )
            except (ValueError, IndexError):
                pass
            
            # Fallback: devolver todo
            return Response(
                content=response.content,
                media_type=response.headers.get('content-type', 'application/octet-stream'),
                status_code=200,
                headers={
                    "Cache-Control": "public, max-age=86400",
                    "Content-Disposition": f"inline; filename={os.path.basename(file_path)}",
                    "Accept-Ranges": "bytes",
                    "Content-Length": str(len(response.content))
                }
            )
        
        elif response.status_code == 404:
            # Intentar fallback local
            logging.debug(f"Archivo no encontrado en S3, intentando fallback local: {file_path}")
            content, content_type, source_headers = await get_transcript_file(file_path)
            
            if content is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Archivo no encontrado: {file_path}"
                )
            
            # Procesar el Range Request localmente
            try:
                ranges_str = range_header[6:]
                if "," not in ranges_str and "-" in ranges_str:
                    start_str, end_str = ranges_str.split("-", 1)
                    start = int(start_str) if start_str else 0
                    end = int(end_str) if end_str else len(content) - 1
                    
                    partial = content[start:end + 1]
                    return Response(
                        content=partial,
                        media_type=content_type,
                        status_code=206,
                        headers={
                            "Cache-Control": "public, max-age=86400",
                            "Content-Disposition": f"inline; filename={os.path.basename(file_path)}",
                            "Accept-Ranges": "bytes",
                            "Content-Range": f"bytes {start}-{end}/{len(content)}",
                            "Content-Length": str(len(partial))
                        }
                    )
            except (ValueError, IndexError):
                pass
            
            return Response(
                content=content,
                media_type=content_type,
                status_code=200,
                headers={
                    "Cache-Control": "public, max-age=86400",
                    "Content-Disposition": f"inline; filename={os.path.basename(file_path)}",
                    "Accept-Ranges": "bytes"
                }
            )
        
        else:
            logging.warning(f"Error al obtener de S3 ({response.status_code}): {file_path}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Error al obtener archivo de S3: {response.status_code}"
            )
    
    except requests.exceptions.Timeout:
        logging.error(f"Timeout en Range Request a S3: {file_path}")
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Timeout al obtener de S3"
        )
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error en Range Request: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error: {str(e)}"
        )

@app.post("/api/check_similar")
async def check_similar_queries(payload: CheckSimilarRequest, request: Request):
    """
    Verifica si existen consultas similares antes del procesamiento completo.
    Retorna las consultas similares encontradas para que el usuario pueda elegir
    una respuesta rápida o continuar con el procesamiento completo.
    """
    question = payload.question.strip() if payload.question else ""
    
    if not question:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La pregunta no puede estar vacía"
        )

    if not app.db or not app.db.is_available:
        # Si no hay BD disponible, indicar que puede continuar
        return {
            "exact_match": False,
            "similar_queries": {"high": [], "medium": [], "low": []},
            "can_continue": True
        }

    try:
        # Paso 1: Obtener embedding de la pregunta
        gcpayload_emb = {
            "query": payload.question,
            "n_fragments": 1,
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
        gcresp_emb = requests.post(app.get_context_url, data=body_str_emb, headers=auth_headers_emb, timeout=120)
        
        if gcresp_emb.status_code != 200:
            logging.warning(f"Error al obtener embedding para verificación: {gcresp_emb.status_code}")
            return {
                "exact_match": False,
                "similar_queries": {"high": [], "medium": [], "low": []},
                "can_continue": True
            }
        
        data_emb = gcresp_emb.json()
        query_embedding = data_emb.get('query_embedding')
        
        if not query_embedding:
            return {
                "exact_match": False,
                "similar_queries": {"high": [], "medium": [], "low": []},
                "can_continue": True
            }

        # Paso 2: Buscar consultas similares
        similar_queries = await app.db.search_similar_queries(
            query_embedding=query_embedding,
            podcast_name=app.podcast_name,
            limit=15,
            similarity_threshold=0.60
        )
        
        if not similar_queries:
            return {
                "exact_match": False,
                "similar_queries": {"high": [], "medium": [], "low": []},
                "can_continue": True
            }
        
        # Clasificar consultas por similitud
        high_similarity = []
        medium_similarity = []
        low_similarity = []
        exact_match = False
        
        for query in similar_queries:
            similarity = query.get('similarity', 0)
            
            # Verificar match exacto (100% de similitud)
            if similarity >= 0.9999:  # Prácticamente 100%
                exact_match = True
                # Para match exacto, retornar directamente esa consulta
                return {
                    "exact_match": True,
                    "exact_match_query": {
                        'uuid': str(query['uuid']),
                        'query_text': query['query_text'],
                        'similarity': round(similarity, 4),
                        'url': f"{BASE_PATH}/savedquery/{query['uuid']}"
                    },
                    "can_continue": False
                }
            
            query_info = {
                'uuid': str(query['uuid']),
                'query_text': query['query_text'],
                'similarity': round(similarity, 3),
                'url': f"{BASE_PATH}/savedquery/{query['uuid']}"
            }
            
            if similarity >= QUERIES_HIGH_SIMILARITY:  # Umbral alto para alta similitud
                high_similarity.append(query_info)
            elif similarity >= QUERIES_MEDIUM_SIMILARITY:  # Umbral medio
                medium_similarity.append(query_info)
            elif similarity >= QUERIES_LOW_SIMILARITY:  # Umbral bajo
                low_similarity.append(query_info)
        
        response = {
            "exact_match": False,
            "similar_queries": {
                'high': high_similarity[:4],   # Máximo 4 por nivel
                'medium': medium_similarity[:4],
                'low': low_similarity[:4]
            },
            "can_continue": True,
            "total_found": len(high_similarity) + len(medium_similarity) + len(low_similarity)
        }
        
        logging.info(f"Verificación de similares para '{question[:50]}...': "
                   f"{len(high_similarity)} altas, {len(medium_similarity)} medias, "
                   f"{len(low_similarity)} bajas")
        
        return response

    except requests.exceptions.Timeout:
        logging.warning("Timeout al verificar consultas similares")
        return {
            "exact_match": False,
            "similar_queries": {"high": [], "medium": [], "low": []},
            "can_continue": True
        }
    except Exception as e:
        logging.error(f"Error verificando consultas similares: {e}")
        return {
            "exact_match": False,
            "similar_queries": {"high": [], "medium": [], "low": []},
            "can_continue": True
        }

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

    # Si no se solicita saltar la verificación de similitud, verificar primero
    if not payload.skip_similarity_check:
        try:
            # Verificar consultas similares primero
            check_request = CheckSimilarRequest(question=question, language=language)
            similar_check = await check_similar_queries(check_request, request)
            
            # Si hay match exacto, retornar inmediatamente
            if similar_check.get('exact_match'):
                exact_query = similar_check.get('exact_match_query')
                if exact_query:
                    # Obtener la consulta completa de la BD
                    try:
                        query_data = await app.db.get_query_by_uuid(exact_query['uuid'])
                        if query_data and query_data.get('response_data'):
                            import json
                            stored_response = json.loads(query_data['response_data'])
                            
                            return {
                                "success": True,
                                "response": stored_response.get('response', query_data.get('response_text', '')),
                                "references": stored_response.get('references', []),
                                "timestamp": query_data['created_at'].isoformat(),
                                "query": query_data['query_text'],
                                "exact_match_used": True,
                                "uuid": str(query_data['uuid']),
                                "saved_query_url": f"{BASE_PATH}/savedquery/{query_data['uuid']}"
                            }
                    except Exception as e:
                        logging.error(f"Error obteniendo consulta exacta: {e}")
            
            # Si hay consultas similares (no exactas), sugerir al frontend que las muestre
            total_similar = similar_check.get('total_found', 0)
            if total_similar > 0:
                return {
                    "success": False,
                    "requires_confirmation": True,
                    "similar_queries": similar_check.get('similar_queries', {}),
                    "message": f"Encontré {total_similar} consulta{'s' if total_similar != 1 else ''} similar{'es' if total_similar != 1 else ''}. ¿Quieres usar alguna de las respuestas existentes o continuar con una nueva búsqueda?"
                }
                
        except Exception as e:
            logging.error(f"Error en verificación de similitud: {e}")
            # Si hay error, continuar con el procesamiento normal
            pass

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
        gcresp_emb = requests.post(app.get_context_url, data=body_str_emb, headers=auth_headers_emb, timeout=120)
        
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
        gcresp = requests.post(app.get_context_url, data=body_str, headers=auth_headers, timeout=120)
        
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
        relresp = requests.post(app.relsearch_url, data=body_str, headers=auth_headers, timeout=120)
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
                    # Procesar hiperenlaces si hay directorio local o URL externa
                    if app.rag_mp3_dir or app.transcripts_url_external:
                        logging.info(f"Procesando referencia: {ref['label']} - {ref['file']} a {ref['time']} segundos")
                        html_file = {
                            l: get_transcript_url(os.path.join("/transcripts", f"{ref['file']}_whisper_audio_{l}.html")) for l in ['es', 'en']
                        }
                        # Solo construir rutas locales si hay directorio configurado
                        if app.rag_mp3_dir:
                            real_file = {
                                l: os.path.join(app.rag_mp3_dir, f"{ref['file']}_whisper_audio_{l}.html") for l in ['es', 'en']
                            }
                        else:
                            real_file = {'es': None, 'en': None}
                        logging.info(f"Archivos HTML: {html_file}")
                        logging.info(f"Buscando ID más cercano para {ref['time']} segundos")
                        
                        # Determinar qué ruta usar: local o URL externa
                        file_to_search = None
                        if app.rag_mp3_dir and real_file['es'] and os.path.exists(real_file['es']):
                            # Usar ruta local si existe
                            file_to_search = real_file['es']
                            logging.info(f"Usando archivo local: {file_to_search}")
                        elif app.transcripts_url_external:
                            # Usar URL externa si está configurada
                            file_to_search = f"{app.transcripts_url_external}/{ref['file']}_whisper_audio_es.html"
                            logging.info(f"Usando URL externa: {file_to_search}")
                        
                        if file_to_search:
                            nearest_id = find_nearest_time_id(
                                file_to_search, 
                                ref['time']
                            )
                        else:
                            nearest_id = None
                            logging.warning(f"No se encontró archivo local ni URL externa configurada")
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
                            
                            if similarity >= QUERIES_HIGH_SIMILARITY:
                                high_similarity.append(query_info)
                            elif similarity >= QUERIES_MEDIUM_SIMILARITY:
                                medium_similarity.append(query_info)
                            elif similarity >= QUERIES_LOW_SIMILARITY:
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
        
        # Buscar consultas similares usando el embedding de la consulta guardada
        if query_data.get('query_embedding'):
            try:
                # Convertir el string del embedding de vuelta a lista
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
                            'url': f"{BASE_PATH}/api/savedquery/{query['uuid']}"
                        }
                        
                        if similarity >= QUERIES_HIGH_SIMILARITY:
                            high_similarity.append(query_info)
                        elif similarity >= QUERIES_MEDIUM_SIMILARITY:
                            medium_similarity.append(query_info)
                        elif similarity >= QUERIES_LOW_SIMILARITY:
                            low_similarity.append(query_info)
                    
                    response_data['similar_queries'] = {
                        'high': high_similarity[:3],
                        'medium': medium_similarity[:3],
                        'low': low_similarity[:3]
                    }
                    logging.info(f"Consultas similares para {query_uuid}: {len(high_similarity)} altas, {len(medium_similarity)} medias, {len(low_similarity)} bajas")
                else:
                    # Incluir estructura vacía si no hay similares
                    response_data['similar_queries'] = {
                        'high': [],
                        'medium': [],
                        'low': []
                    }
            except Exception as e:
                logging.error(f"Error buscando consultas similares para consulta guardada: {e}")
                # Incluir estructura vacía en caso de error
                response_data['similar_queries'] = {
                    'high': [],
                    'medium': [],
                    'low': []
                }
        else:
            # Sin embedding, incluir estructura vacía
            response_data['similar_queries'] = {
                'high': [],
                'medium': [],
                'low': []
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
                        
                        if similarity >= QUERIES_HIGH_SIMILARITY:
                            high_similarity.append(query_info)
                        elif similarity >= QUERIES_MEDIUM_SIMILARITY:
                            medium_similarity.append(query_info)
                        elif similarity >= QUERIES_LOW_SIMILARITY:
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
            query_uuid = query.get('uuid', '')
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
        response = requests.post(f"{app.context_server_url}/api/gen_stats", data=body_str, headers=auth_headers, timeout=120)
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

# =============================================
#  Helpers de autenticación admin
# =============================================

def require_admin(request: Request):
    """Verifica que el usuario tiene sesión de administrador activa"""
    if not request.session.get('is_admin'):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Requiere autenticación de administrador"
        )

# =============================================
#  Endpoints de autenticación admin
# =============================================

@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    """Página de login del panel de administración"""
    if request.session.get('is_admin'):
        return RedirectResponse(url=f"{BASE_PATH}/admin", status_code=303)
    return templates.TemplateResponse("admin_login.html", {
        "request": request,
        "podcast_name": app.podcast_name,
        "base_path": BASE_PATH,
        "error": None
    })

@app.post("/admin/login")
async def admin_login(request: Request):
    """Procesa el login del administrador"""
    form = await request.form()
    password = form.get('password', '')
    
    if not ADMIN_PASSWORD or password != ADMIN_PASSWORD:
        return templates.TemplateResponse("admin_login.html", {
            "request": request,
            "podcast_name": app.podcast_name,
            "base_path": BASE_PATH,
            "error": "Contraseña incorrecta"
        })
    
    request.session['is_admin'] = True
    request.session['login_time'] = datetime.now().isoformat()
    logging.info(f"Admin login exitoso desde {get_client_ip_from_request(request)}")
    return RedirectResponse(url=f"{BASE_PATH}/admin", status_code=303)

@app.get("/admin/logout")
async def admin_logout(request: Request):
    """Cierra la sesión de administrador"""
    request.session.clear()
    return RedirectResponse(url=f"{BASE_PATH}/", status_code=303)

@app.get("/admin", response_class=HTMLResponse)
async def admin_panel(request: Request):
    """Panel de administración de consultas destacadas y categorías"""
    require_admin(request)
    return templates.TemplateResponse("admin.html", {
        "request": request,
        "podcast_name": app.podcast_name,
        "base_path": BASE_PATH,
        "css_url": get_static_url("css/client_rag.css", base_path=BASE_PATH),
        "admin_js_url": get_static_url("js/admin.js", base_path=BASE_PATH)
    })

# =============================================
#  API Endpoints de administración
# =============================================

@app.get("/api/admin/queries")
async def admin_get_queries(request: Request, limit: int = 500, offset: int = 0):
    """Obtiene todas las consultas con info de featured y categorías"""
    require_admin(request)
    if not app.db or not app.db.is_available:
        raise HTTPException(status_code=503, detail="Base de datos no disponible")
    queries = await app.db.get_all_queries_admin(
        podcast_name=app.podcast_name, limit=limit, offset=offset
    )
    # Serializar datetimes
    for q in queries:
        if hasattr(q.get('created_at'), 'isoformat'):
            q['created_at'] = q['created_at'].isoformat()
        q['uuid'] = str(q.get('uuid', ''))
    return {"queries": queries, "total": len(queries)}

@app.post("/api/admin/toggle_featured/{query_uuid}")
async def admin_toggle_featured(query_uuid: str, request: Request):
    """Marca/desmarca una consulta como destacada"""
    require_admin(request)
    if not app.db or not app.db.is_available:
        raise HTTPException(status_code=503, detail="Base de datos no disponible")
    query = await app.db.get_query_by_uuid(query_uuid)
    if not query:
        raise HTTPException(status_code=404, detail="Consulta no encontrada")
    new_featured = not query.get('featured', False)
    success = await app.db.update_featured(query_uuid, new_featured)
    if not success:
        raise HTTPException(status_code=500, detail="Error al actualizar")
    return {"uuid": query_uuid, "featured": new_featured}

@app.get("/api/admin/categories")
async def admin_get_categories(request: Request):
    """Obtiene el árbol de categorías"""
    require_admin(request)
    if not app.db or not app.db.is_available:
        raise HTTPException(status_code=503, detail="Base de datos no disponible")
    tree = await app.db.get_categories_tree()
    flat = await app.db.get_all_categories_flat()
    return {"tree": tree, "flat": flat}

@app.post("/api/admin/categories")
async def admin_create_category(request: Request):
    """Crea una nueva categoría"""
    require_admin(request)
    if not app.db or not app.db.is_available:
        raise HTTPException(status_code=503, detail="Base de datos no disponible")
    body = await request.json()
    
    name = body.get('name', '').strip()
    slug = body.get('slug', '').strip()
    if not name or not slug:
        raise HTTPException(status_code=400, detail="name y slug son obligatorios")
    
    # Calcular embedding de la categoría (nombre + descripción)
    category_embedding = None
    description = body.get('description', '')
    embedding_text = f"{name}: {description}" if description else name
    try:
        emb_payload = {
            "query": embedding_text,
            "n_fragments": 1,
            "only_embedding": True
        }
        auth_headers = create_auth_headers(
            app.context_server_api_key, "POST", "/getcontext",
            emb_payload, "client_rag_service"
        )
        body_str = serialize_body(emb_payload)
        emb_resp = requests.post(app.get_context_url, data=body_str, headers=auth_headers, timeout=30)
        if emb_resp.status_code == 200:
            category_embedding = emb_resp.json().get('query_embedding')
    except Exception as e:
        logging.warning(f"No se pudo calcular embedding de categoría: {e}")
    
    result = await app.db.create_category(
        name=name,
        slug=slug,
        description=description,
        parent_id=body.get('parent_id'),
        is_primary=body.get('is_primary', False),
        display_order=body.get('display_order', 0),
        category_embedding=category_embedding
    )
    if not result:
        raise HTTPException(status_code=500, detail="Error al crear categoría")
    return result

@app.put("/api/admin/categories/{category_id}")
async def admin_update_category(category_id: int, request: Request):
    """Actualiza una categoría"""
    require_admin(request)
    if not app.db or not app.db.is_available:
        raise HTTPException(status_code=503, detail="Base de datos no disponible")
    body = await request.json()
    success = await app.db.update_category(category_id, **body)
    if not success:
        raise HTTPException(status_code=500, detail="Error al actualizar categoría")
    return {"success": True}

@app.delete("/api/admin/categories/{category_id}")
async def admin_delete_category(category_id: int, request: Request):
    """Elimina una categoría"""
    require_admin(request)
    if not app.db or not app.db.is_available:
        raise HTTPException(status_code=503, detail="Base de datos no disponible")
    success = await app.db.delete_category(category_id)
    if not success:
        raise HTTPException(status_code=500, detail="Error al eliminar categoría")
    return {"success": True}

@app.post("/api/admin/assign_category")
async def admin_assign_category(request: Request):
    """Asigna una consulta a una categoría"""
    require_admin(request)
    if not app.db or not app.db.is_available:
        raise HTTPException(status_code=503, detail="Base de datos no disponible")
    body = await request.json()
    query_id = body.get('query_id')
    category_id = body.get('category_id')
    if not query_id or not category_id:
        raise HTTPException(status_code=400, detail="query_id y category_id son obligatorios")
    success = await app.db.assign_query_to_category(
        query_id, category_id, assigned_by='admin'
    )
    return {"success": success}

@app.post("/api/admin/remove_category_assignment")
async def admin_remove_category_assignment(request: Request):
    """Elimina la asignación de una consulta a una categoría"""
    require_admin(request)
    if not app.db or not app.db.is_available:
        raise HTTPException(status_code=503, detail="Base de datos no disponible")
    body = await request.json()
    success = await app.db.remove_query_from_category(
        body.get('query_id'), body.get('category_id')
    )
    return {"success": success}

@app.post("/api/admin/suggest_categories")
async def admin_suggest_categories(request: Request):
    """Solicita al LLM una propuesta de categorización"""
    require_admin(request)
    if not app.db or not app.db.is_available:
        raise HTTPException(status_code=503, detail="Base de datos no disponible")
    
    body = await request.json()
    selected_model = body.get('model')  # Modelo elegido por el admin
    
    # Obtener consultas destacadas con sus respuestas para enviar al LLM
    featured = await app.db.get_featured_queries(podcast_name=app.podcast_name)
    queries_for_llm = []
    for q in featured:
        queries_for_llm.append({
            "id": q['id'],
            "question": q['query_text'],
            "answer": q.get('response_text', '')[:500]  # Limitar respuesta
        })
    
    existing_categories = await app.db.get_all_categories_flat()
    
    # Enviar al servicio RAG para categorización con LLM
    suggest_payload = {
        "queries": queries_for_llm,
        "existing_categories": [
            {"name": c['name'], "slug": c['slug'], "description": c.get('description', ''),
             "parent_slug": next((p['slug'] for p in existing_categories if p['id'] == c.get('parent_id')), None)}
            for c in existing_categories
        ]
    }
    if selected_model:
        suggest_payload['model'] = selected_model
    
    try:
        rag_base_url = app.relsearch_url.rsplit('/', 1)[0]
        auth_headers = create_auth_headers(
            app.rag_server_api_key, "POST", "/suggest_categories",
            suggest_payload, "client_rag_service"
        )
        body_str = serialize_body(suggest_payload)
        resp = requests.post(
            f"{rag_base_url}/suggest_categories",
            data=body_str, headers=auth_headers, timeout=300
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=f"Error del servicio RAG: {resp.text}")
        return resp.json()
    except requests.exceptions.Timeout:
        raise HTTPException(status_code=504, detail="Timeout al solicitar categorización")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

@app.post("/api/admin/apply_categories")
async def admin_apply_categories(request: Request):
    """Aplica un esquema de categorías propuesto por el LLM"""
    require_admin(request)
    if not app.db or not app.db.is_available:
        raise HTTPException(status_code=503, detail="Base de datos no disponible")
    
    body = await request.json()
    categories = body.get('categories', [])
    assignments = body.get('assignments', [])
    
    created_categories = {}
    errors = []
    
    # Resolver categorías existentes por slug para reutilizarlas
    existing_cats = await app.db.get_all_categories_flat()
    existing_by_slug = {c['slug']: c['id'] for c in existing_cats}
    
    # Crear categorías primarias y sus hijos
    for cat in categories:
        try:
            slug = cat['slug']
            if slug in existing_by_slug:
                # La categoría ya existe, reutilizar su ID
                created_categories[slug] = existing_by_slug[slug]
            else:
                result = await app.db.create_category(
                    name=cat['name'],
                    slug=slug,
                    description=cat.get('description', ''),
                    is_primary=cat.get('is_primary', True),
                    display_order=cat.get('display_order', 0),
                    created_by='llm'
                )
                if result:
                    created_categories[slug] = result['id']
                    existing_by_slug[slug] = result['id']
            
            # Crear subcategorías
            parent_id = created_categories.get(slug)
            for child in cat.get('children', []):
                child_slug = child['slug']
                if child_slug in existing_by_slug:
                    created_categories[child_slug] = existing_by_slug[child_slug]
                else:
                    child_result = await app.db.create_category(
                        name=child['name'],
                        slug=child_slug,
                        description=child.get('description', ''),
                        parent_id=parent_id,
                        is_primary=False,
                        created_by='llm'
                    )
                    if child_result:
                        created_categories[child_slug] = child_result['id']
                        existing_by_slug[child_slug] = child_result['id']
        except Exception as e:
            errors.append(f"Error creando categoría {cat.get('name')}: {e}")
    
    # Aplicar asignaciones
    applied_count = 0
    for assignment in assignments:
        query_id = assignment.get('query_id')
        for slug in assignment.get('category_slugs', []):
            cat_id = created_categories.get(slug)
            if cat_id and query_id:
                success = await app.db.assign_query_to_category(
                    query_id, cat_id,
                    assigned_by='llm',
                    confidence=assignment.get('confidence', 0.8)
                )
                if success:
                    applied_count += 1
    
    # Aplicar reasignaciones de padres
    reparents = body.get('reparents', [])
    reparent_count = 0
    for rp in reparents:
        cat_slug = rp.get('category_slug')
        new_parent_slug = rp.get('new_parent_slug')
        cat_id = existing_by_slug.get(cat_slug) or created_categories.get(cat_slug)
        if cat_id:
            new_parent_id = None
            if new_parent_slug:
                new_parent_id = existing_by_slug.get(new_parent_slug) or created_categories.get(new_parent_slug)
                if not new_parent_id:
                    errors.append(f"Padre '{new_parent_slug}' no encontrado para reasignar '{cat_slug}'")
                    continue
            success = await app.db.update_category(cat_id, parent_id=new_parent_id if new_parent_id else -1)
            if success:
                reparent_count += 1
    
    return {
        "created_categories": len(created_categories),
        "applied_assignments": applied_count,
        "applied_reparents": reparent_count,
        "errors": errors
    }

# =============================================
#  FAQ público (sin autenticación)
# =============================================

@app.get("/api/faq")
async def get_faq(category_slug: str = None):
    """
    Endpoint público: devuelve consultas destacadas organizadas por categoría.
    No requiere autenticación.
    """
    if not app.db or not app.db.is_available:
        return {"categories": [], "grouped_queries": {}, "uncategorized": []}
    
    try:
        faq_data = await app.db.get_faq_grouped(podcast_name=app.podcast_name)
        return faq_data
    except Exception as e:
        logging.error(f"Error obteniendo FAQ: {e}")
        return {"categories": [], "grouped_queries": {}, "uncategorized": []}


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
    
