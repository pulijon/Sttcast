import sys
import os
import logging
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__),"../../tools")))
from logs import logcfg
from envvars import load_env_vars_from_directory

from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import requests
from datetime import datetime
from urllib.parse import urljoin
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from sttcast_rag_service import RelSearchRequest
from findtime import find_nearest_time_id


# Configuración desde variables de entorno
API_URL = os.getenv('API_URL', 'http://localhost:8080/api/questions')
FILES_BASE_URL = os.getenv('FILES_BASE_URL', '/files')
WEB_SERVICE_TIMEOUT = int(os.getenv('WEB_SERVICE_TIMEOUT', '15'))


# Inicialización de FastAPI y Jinja2
app = FastAPI()

load_env_vars_from_directory("../../.env")
rag_client_host = os.getenv('RAG_CLIENT_HOST', 'localhost')
rag_client_port = int(os.getenv('RAG_CLIENT_PORT', '8004'))

context_server_host = os.getenv('CONTEXT_SERVER_HOST')
context_server_port = int(os.getenv('CONTEXT_SERVER_PORT'))
context_server_url = f"http://{context_server_host}:{context_server_port}/"
get_context_path = "/getcontext"
get_context_url = urljoin(context_server_url, get_context_path)
logging.info(f"Context server URL: {get_context_url}")
app.get_context_url = get_context_url

rag_server_host = os.getenv('RAG_SERVER_HOST')
rag_server_port = int(os.getenv('RAG_SERVER_PORT'))
rag_server_url = f"http://{rag_server_host}:{rag_server_port}/"
relsearch_path = "/relsearch"
relsearch_url = urljoin(rag_server_url, relsearch_path)
logging.info(f"RAG server URL: {relsearch_url}")
app.relsearch_url = relsearch_url

rag_mp3_dir = os.getenv('RAG_MP3_DIR')
app.rag_mp3_dir = rag_mp3_dir
logging.info(f"RAG MP3 directory: {rag_mp3_dir}")

templates = Jinja2Templates(directory="templates")

app.mount("/static",
          StaticFiles(directory="static"), name="static")
app.mount("/transcripts", StaticFiles(directory=rag_mp3_dir), name="transcripts")
# ------------------------
#   Utilidades
# ------------------------

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
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/api/ask")
async def ask_question(payload: AskRequest):
    """Procesa la pregunta enviada"""
    question = payload.question.strip() if payload.question else ""
    language = payload.language

    if not question:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La pregunta no puede estar vacía"
        )

    try:
        gcpayload = {
            "query": payload.question,
            "n_fragments": 100
        }

        gcresp = requests.post(app.get_context_url, json=gcpayload)
        
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
        relquery = RelSearchRequest(
            query=payload.question,
            embeddings=context
        ).model_dump()
        relresp = requests.post(app.relsearch_url, json=relquery)
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
                            l: os.path.join("/transcripts", f"{ref['file']}_whisper_audio_{l}.html") for l in ['es', 'en']
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

                        

        return {
            "success": True,
            "response": reldata["search"],
            "references": references,
            "timestamp": datetime.now().isoformat()
        }

    except requests.exceptions.Timeout:
        raise HTTPException(status_code=504, detail="Timeout: El servicio web tardó demasiado en responder")
    except requests.exceptions.ConnectionError:
        raise HTTPException(status_code=503, detail="Error de conexión con el servicio web")
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=f"Error en la petición: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")

@app.get("/health")
async def health_check():
    """Endpoint de salud"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "config": {
            "api_url": API_URL,
            "files_base_url": FILES_BASE_URL,
            "timeout": WEB_SERVICE_TIMEOUT
        }
    }

if __name__ == "__main__":
    import uvicorn
    logcfg(__file__)


    uvicorn.run(
        "client_rag:app",  # Asume que este archivo se llama main.py
        host=rag_client_host,
        port=rag_client_port,
        reload=True,
        log_level="info"
    )
    