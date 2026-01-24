#!/usr/bin/env python3
"""
Servicio REST de transcripción STTCast - Refactorizado
Arquitectura mejorada con autenticación HMAC y gestión asíncrona optimizada
"""

import asyncio
import os
import uuid
import logging
import datetime
import time
import json
import multiprocessing as mp
from typing import Optional, Dict, List, Any
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
import tempfile
import shutil
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, UploadFile, Form, HTTPException, BackgroundTasks, Request, Depends
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
import uvicorn
from dotenv import load_dotenv

# Importar autenticación HMAC
from api.apihmac import validate_hmac_auth

# Aplicar parche para PyTorch 2.6+ con omegaconf
import torch_fix
import sttcast_core
from tools.logs import logcfg
from tools.envvars import load_env_vars_from_directory

# Cargar configuración del servicio
conf_dir = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(conf_dir):
    load_env_vars_from_directory(conf_dir)

# Configuración del servidor desde variables de entorno
SERVER_HOST = os.getenv('TRANSSRV_HOST', '127.0.0.1')
SERVER_PORT = int(os.getenv('TRANSSRV_PORT', '8000'))
SERVER_CPUS = int(os.getenv('TRANSSRV_CPUS', str(max(os.cpu_count() - 2, 1))))
SERVER_GPUS = int(os.getenv('TRANSSRV_GPUS', '1'))
API_SECRET_KEY = os.getenv('TRANSSRV_API_KEY', '')

if not API_SECRET_KEY:
    raise ValueError("TRANSSRV_API_KEY no está configurada en .env/transsrv.env")

# Variables globales del servicio
gpu_semaphore: Optional[asyncio.Semaphore] = None
process_pool: Optional[ProcessPoolExecutor] = None
jobs: Dict[str, Dict[str, Any]] = {}

# Configuración de directorios
UPLOAD_DIR = Path(tempfile.gettempdir()) / "sttcast_uploads"
PROCESSING_DIR = Path(tempfile.gettempdir()) / "sttcast_processing" 
RESULTS_DIR = Path(tempfile.gettempdir()) / "sttcast_results" / "completed"
UPLOAD_DIR.mkdir(exist_ok=True)
PROCESSING_DIR.mkdir(exist_ok=True, parents=True)
RESULTS_DIR.mkdir(exist_ok=True, parents=True)

# Modelos Pydantic
class TranscriptionConfig(BaseModel):
    """Configuración completa para transcripción"""
    # Motor de transcripción  
    whisper: bool = Field(False, description="Usar Whisper (GPU) en lugar de Vosk (CPU)")
    whmodel: str = Field("small", description="Modelo Whisper")
    whdevice: str = Field("cuda", description="Dispositivo para Whisper")
    whlanguage: str = Field("es", description="Idioma")
    
    # Configuración de colección (antes en servidor)
    prefix: str = Field("cm", description="Prefijo para archivos de salida")
    calendar_file: Optional[str] = Field(None, description="Archivo de calendario CSV")
    templates_dir: Optional[str] = Field(None, description="Directorio de plantillas")
    html_suffix: str = Field("", description="Sufijo para archivos HTML")
    min_offset: int = Field(30, description="Offset mínimo en segundos")
    max_gap: float = Field(0.8, description="Gap máximo entre segmentos")
    
    # Procesamiento
    seconds: int = Field(15000, description="Duración de segmentos en segundos")
    hconf: float = Field(0.95, description="Umbral confianza alta")
    mconf: float = Field(0.7, description="Umbral confianza media") 
    lconf: float = Field(0.5, description="Umbral confianza baja")
    overlap: int = Field(2, description="Solapamiento entre segmentos")
    
    # Opciones adicionales
    audio_tags: bool = Field(False, description="Incluir audio tags en HTML")
    use_training: bool = Field(False, description="Usar archivo de entrenamiento para speaker diarization")
    
    # Parámetros de Pyannote para diarización (enviados desde cliente)
    pyannote_method: str = Field("ward", description="Método de clustering para Pyannote")
    pyannote_min_cluster_size: int = Field(15, description="Tamaño mínimo del cluster")
    pyannote_threshold: float = Field(0.7147, description="Umbral de similitud para clustering")
    pyannote_min_speakers: Optional[int] = Field(None, description="Número mínimo de hablantes")
    pyannote_max_speakers: Optional[int] = Field(None, description="Número máximo de hablantes")

class TranscriptionRequest(BaseModel):
    """Compatibilidad hacia atrás"""
    config: TranscriptionConfig = Field(default_factory=TranscriptionConfig)

class JobStatus(BaseModel):
    job_id: str
    status: str  # pending, running, completed, failed
    progress: Optional[float] = None
    message: Optional[str] = None
    created_at: datetime.datetime
    started_at: Optional[datetime.datetime] = None
    completed_at: Optional[datetime.datetime] = None
    error: Optional[str] = None
    engine: Optional[str] = None
    files: Optional[List[Dict[str, Any]]] = None  # Changed to Any to accept int for size

class JobFile(BaseModel):
    filename: str
    type: str  # 'html', 'srt'
    size: int
    created_at: datetime.datetime

class ServiceStats(BaseModel):
    total_jobs: int
    active_jobs: int
    completed_jobs: int
    failed_jobs: int
    gpu_slots_available: int
    server_cpus: int
    server_gpus: int
    uptime: str

# Dependencia para autenticación HMAC
async def get_authenticated_user(request: Request) -> str:
    """Validar autenticación HMAC para todas las rutas protegidas"""
    logging.debug(f"get_authenticated_user: Iniciando autenticación para {request.method} {request.url.path}")
    
    # Leer el cuerpo de la petición para validar HMAC
    content_type = request.headers.get('content-type', '')
    logging.debug(f"get_authenticated_user: Content-Type: {content_type}")
    
    if 'multipart/form-data' in content_type:
        # Para multipart requests, usar body vacío para HMAC
        # ya que el contenido multipart es difícil de reproducir exactamente en cliente
        body = b""
        logging.debug("get_authenticated_user: Usando body vacío para multipart/form-data")
    else:
        # Para JSON requests, usar el cuerpo completo
        body = await request.body()
        logging.debug(f"get_authenticated_user: Usando body completo, tamaño: {len(body)} bytes")
    
    try:
        result = validate_hmac_auth(request, API_SECRET_KEY, body)
        logging.debug(f"get_authenticated_user: Autenticación exitosa para cliente: {result}")
        return result
    except Exception as e:
        logging.error(f"get_authenticated_user: Error de autenticación: {e}")
        raise

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gestión del ciclo de vida del servicio"""
    global gpu_semaphore, process_pool
    
    # Startup
    logcfg(__file__)
    
    # Obtener configuración final (puede ser sobrescrita por args)
    final_cpus = getattr(app.state, 'cpus', SERVER_CPUS)
    final_gpus = getattr(app.state, 'gpus', SERVER_GPUS)
    
    logging.info(f"Iniciando STTCast Service con {final_cpus} CPUs y {final_gpus} slots GPU")
    
    # Crear semáforo GPU con configuración final
    gpu_semaphore = asyncio.Semaphore(final_gpus)

    # Crear pool global de procesos con límite por máquina
    # Usar contexto 'spawn' para evitar heredar sockets del servidor
    process_pool = ProcessPoolExecutor(max_workers=final_cpus, mp_context=mp.get_context("spawn"))
    
    # Configurar directorios
    UPLOAD_DIR.mkdir(exist_ok=True)
    PROCESSING_DIR.mkdir(exist_ok=True, parents=True)
    RESULTS_DIR.mkdir(exist_ok=True, parents=True)
    
    logging.info(f"Upload dir: {UPLOAD_DIR}")
    logging.info(f"Processing dir: {PROCESSING_DIR}")
    logging.info(f"Results dir: {RESULTS_DIR}")
    logging.info(f"HMAC Authentication: {'Enabled' if API_SECRET_KEY else 'Disabled'}")
    
    yield
    
    # Shutdown
    logging.info("Cerrando STTCast Service")
    if process_pool:
        process_pool.shutdown(wait=True)

# Configuración global
app = FastAPI(
    title="STTCast Transcription Service",
    description="Servicio REST para transcripción de audio con Vosk y Whisper",
    version="1.0.0",
    lifespan=lifespan
)



def create_job_id() -> str:
    """Generar ID único para trabajo"""
    return str(uuid.uuid4())

def update_job_status(job_id: str, **kwargs):
    """Actualizar estado de trabajo"""
    if job_id in jobs:
        jobs[job_id].update(kwargs)

async def run_transcription_task(job_id: str, config: Dict[str, Any], use_gpu: bool):
    """
    Ejecutar tarea de transcripción con flujo mejorado:
    1. Procesar en directorio temporal /processing/{job_id}/
    2. Solo mover a /completed/{job_id}/ cuando esté 100% completado
    3. Archivos finales sin UUID ni sufijos
    """
    try:
        update_job_status(job_id, 
                         status="running", 
                         started_at=datetime.datetime.now(),
                         message="Iniciando transcripción...")
        
        # Crear directorio de procesamiento único para este trabajo
        job_processing_dir = PROCESSING_DIR / job_id
        job_processing_dir.mkdir(exist_ok=True)
        config['temp_dir'] = str(job_processing_dir)
        config['work_id'] = job_id
        
        # Obtener nombre original del archivo
        # Con la nueva estructura, el archivo ya tiene su nombre original en job_dir/original_filename
        original_filename = None
        if 'fnames' in config and config['fnames']:
            original_path = Path(config['fnames'][0])
            # El archivo ya tiene su nombre original (sin UUID)
            original_filename = original_path.stem  # Sin extensión
        
        # Inyectar pool global para evitar crear procesos por trabajo
        if process_pool:
            config['executor'] = process_pool

        # Si usa GPU, adquirir semáforo
        if use_gpu:
            logging.info(f"Job {job_id}: Intentando adquirir slot GPU (slots disponibles: {gpu_semaphore._value})")
            await gpu_semaphore.acquire()
            try:
                logging.info(f"Job {job_id}: Slot GPU adquirido (slots restantes: {gpu_semaphore._value})")
                
                # Ejecutar transcripción Whisper
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None,
                    sttcast_core.transcribe_audio, 
                    config
                )
            finally:
                # Forzar liberación de memoria GPU
                import gc
                import torch
                gc.collect()
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    torch.cuda.synchronize()
                    logging.info(f"Job {job_id}: Memoria GPU liberada")
                
                gpu_semaphore.release()
                logging.info(f"Job {job_id}: Slot GPU liberado (slots disponibles: {gpu_semaphore._value})")
        else:
            # Transcripción CPU (Vosk) - sin semáforo
            logging.info(f"Job {job_id}: Ejecutando en CPU")
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                sttcast_core.transcribe_audio,
                config
            )
        
        # Crear directorio de resultados finales
        job_result_dir = RESULTS_DIR / job_id
        job_result_dir.mkdir(exist_ok=True)
        
        result_files = []
        
        # Obtener html_suffix del config (ya incluye el '_' si no está vacío)
        html_suffix = config.get('html_suffix', '')
        if html_suffix and not html_suffix.startswith('_'):
            html_suffix = '_' + html_suffix
        
        # Mover archivos de resultado con nombres finales limpios
        for output_file in result['output_files']:
            html_src = Path(output_file['html'])
            srt_src = Path(output_file['srt'])
            
            if html_src.exists():
                # Nombre final con sufijo si está configurado
                html_filename = f"{original_filename}{html_suffix}.html" if original_filename else "transcription.html"
                html_dst = job_result_dir / html_filename
                shutil.move(html_src, html_dst)
                result_files.append({
                    'type': 'html',
                    'filename': html_filename,
                    'path': str(html_dst),
                    'size': html_dst.stat().st_size
                })
            
            if srt_src.exists():
                # Nombre final con sufijo si está configurado
                srt_filename = f"{original_filename}{html_suffix}.srt" if original_filename else "transcription.srt"
                srt_dst = job_result_dir / srt_filename
                shutil.move(srt_src, srt_dst)
                result_files.append({
                    'type': 'srt', 
                    'filename': srt_filename,
                    'path': str(srt_dst),
                    'size': srt_dst.stat().st_size
                })
        
        # Crear archivo de metadatos
        metadata = {
            'job_id': job_id,
            'original_filename': original_filename,
            'completed_at': datetime.datetime.now().isoformat(),
            'engine': 'whisper' if use_gpu else 'vosk',
            'duration': result.get('duration', 'unknown'),
            'files': result_files
        }
        
        metadata_path = job_result_dir / 'metadata.json'
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)
        
        # Marcar trabajo como completado
        update_job_status(job_id,
                         status="completed",
                         completed_at=datetime.datetime.now(),
                         message=f"Transcripción completada en {result['duration']}",
                         files=result_files)
        
        # Limpiar archivos temporales
        _cleanup_temp_files(job_id, config)
        
        logging.info(f"Job {job_id}: Completado exitosamente")
        
    except Exception as e:
        logging.error(f"Job {job_id}: Error - {str(e)}")
        
        # Limpiar archivos temporales en caso de error
        _cleanup_temp_files(job_id, config)
        
        update_job_status(job_id,
                         status="failed", 
                         completed_at=datetime.datetime.now(),
                         error=str(e),
                         message=f"Error en transcripción: {str(e)}")

def _cleanup_temp_files(job_id: str, config: Dict[str, Any]):
    """Limpiar archivos temporales de un trabajo"""
    try:
        # Con la nueva estructura de directorios por trabajo, limpiar el directorio completo
        job_upload_dir = UPLOAD_DIR / job_id
        if job_upload_dir.exists():
            shutil.rmtree(job_upload_dir)
            logging.info(f"Job {job_id}: Directorio de uploads limpiado: {job_upload_dir}")
        
        # Limpiar directorio temporal del trabajo
        if 'temp_dir' in config and config['temp_dir']:
            temp_dir = Path(config['temp_dir'])
            try:
                if temp_dir.exists():
                    shutil.rmtree(temp_dir)
                    logging.info(f"Job {job_id}: Directorio temporal limpiado: {temp_dir}")
            except Exception as e:
                logging.warning(f"Job {job_id}: Error limpiando directorio temporal {temp_dir}: {e}")
                
        # Limpiar directorio de procesamiento
        processing_dir = PROCESSING_DIR / job_id
        try:
            if processing_dir.exists():
                shutil.rmtree(processing_dir)
                logging.info(f"Job {job_id}: Directorio de procesamiento limpiado: {processing_dir}")
        except Exception as e:
            logging.warning(f"Job {job_id}: Error limpiando directorio de procesamiento {processing_dir}: {e}")
                
    except Exception as e:
        logging.warning(f"Job {job_id}: Error en limpieza general: {e}")

## FASE 2: API REDISEÑADA - NUEVOS ENDPOINTS

@app.post("/transcribe", response_model=JobStatus)
async def transcribe_audio_endpoint(
    background_tasks: BackgroundTasks,
    request: Request,
    audio_file: UploadFile = File(...),
    config: str = Form(..., description="Configuración JSON como string"),
    training_file: Optional[UploadFile] = File(None, description="Archivo de entrenamiento opcional para diarización"),
    calendar_file: Optional[UploadFile] = File(None, description="Archivo de calendario CSV opcional"),
    client_id: str = Depends(get_authenticated_user)
):
    """
    Subir archivo de audio para transcripción con autenticación HMAC
    Retorna job_id y procesa en background
    """
    logging.info(f"Endpoint transcribe iniciado por cliente: {client_id}")
    logging.info(f"Archivo recibido: {audio_file.filename}")
    
    # Parsear configuración JSON
    try:
        config_dict = json.loads(config)
        config_obj = TranscriptionConfig(**config_dict)
        # Log detallado de todas las opciones del trabajo
        logging.info("=" * 60)
        logging.info(f"NUEVO TRABAJO DE TRANSCRIPCIÓN")
        logging.info("=" * 60)
        logging.info(f"  Cliente: {client_id}")
        logging.info(f"  Archivo: {audio_file.filename}")
        logging.info(f"  Motor: {'whisper' if config_obj.whisper else 'vosk'}")
        logging.info(f"  Modelo Whisper: {config_obj.whmodel}")
        logging.info(f"  Idioma: {config_obj.whlanguage}")
        logging.info(f"  Audio tags: {config_obj.audio_tags}")
        logging.info(f"  Use training: {config_obj.use_training}")
        logging.info(f"  Training file: {training_file.filename if training_file else 'N/A'}")
        logging.info(f"  Calendar file: {calendar_file.filename if calendar_file else config_obj.calendar_file or 'N/A'}")
        logging.info(f"  Prefix: {config_obj.prefix}")
        logging.info(f"  Pyannote method: {config_obj.pyannote_method}")
        logging.info(f"  Pyannote min_cluster_size: {config_obj.pyannote_min_cluster_size}")
        logging.info(f"  Pyannote threshold: {config_obj.pyannote_threshold}")
        logging.info(f"  Pyannote min_speakers: {config_obj.pyannote_min_speakers}")
        logging.info(f"  Pyannote max_speakers: {config_obj.pyannote_max_speakers}")
        logging.info(f"  Config completa: {json.dumps(config_dict, indent=2)}")
        logging.info("=" * 60)
    except json.JSONDecodeError as e:
        logging.error(f"Error parsing JSON config: {e}")
        raise HTTPException(status_code=400, detail="Configuración JSON inválida")
    except Exception as e:
        logging.error(f"Error validando configuración: {e}")
        raise HTTPException(status_code=400, detail=f"Error en configuración: {str(e)}")

    # Validar archivo de audio
    if not audio_file.filename.lower().endswith(('.mp3', '.wav', '.m4a', '.ogg', '.flac')):
        raise HTTPException(status_code=400, detail="Formato de audio no soportado")
    
    # Validar archivo de entrenamiento si se proporciona
    if training_file and not training_file.filename.lower().endswith(('.mp3', '.wav', '.m4a', '.ogg')):
        raise HTTPException(status_code=400, detail="Formato de archivo de entrenamiento no soportado")
    
    # Solo permitir training file si se usa Whisper
    if training_file and not config_obj.whisper:
        raise HTTPException(status_code=400, detail="Archivo de entrenamiento solo disponible con Whisper")
    
    # Crear trabajo
    job_id = create_job_id()
    logging.info(f"Nuevo trabajo creado: {job_id} por cliente {client_id}")
    
    # Crear directorio específico para este trabajo
    job_dir = UPLOAD_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    
    # Extraer el nombre original del archivo (puede venir con prefijo UUID del webif)
    original_filename = audio_file.filename
    # Si el nombre tiene formato UUID_nombre.ext, extraer solo nombre.ext
    parts = original_filename.split('_', 1)
    if len(parts) > 1 and len(parts[0]) == 36:  # UUID tiene 36 caracteres
        try:
            uuid.UUID(parts[0])  # Verificar que es un UUID válido
            original_filename = parts[1]  # Usar solo la parte después del UUID
        except ValueError:
            pass  # No es un UUID, mantener el nombre completo
    
    # Guardar archivo con su nombre original en el directorio del trabajo
    upload_path = job_dir / original_filename
    with open(upload_path, "wb") as f:
        shutil.copyfileobj(audio_file.file, f)
    
    # Guardar archivo de entrenamiento si se proporciona (en el directorio del trabajo)
    training_path = None
    if training_file:
        # Extraer nombre original del training file
        training_original_name = training_file.filename
        parts = training_original_name.split('_', 1)
        if len(parts) > 1 and len(parts[0]) == 36:
            try:
                uuid.UUID(parts[0])
                training_original_name = parts[1]
            except ValueError:
                pass
        training_path = job_dir / f"training_{training_original_name}"
        with open(training_path, "wb") as f:
            shutil.copyfileobj(training_file.file, f)
        logging.info(f"Job {job_id}: Archivo de entrenamiento guardado: {training_path}")
    
    # Guardar archivo de calendario si se proporciona (en el directorio del trabajo)
    calendar_path = None
    if calendar_file:
        calendar_original_name = calendar_file.filename
        parts = calendar_original_name.split('_', 1)
        if len(parts) > 1 and len(parts[0]) == 36:
            try:
                uuid.UUID(parts[0])
                calendar_original_name = parts[1]
            except ValueError:
                pass
        calendar_path = job_dir / f"calendar_{calendar_original_name}"
        with open(calendar_path, "wb") as f:
            shutil.copyfileobj(calendar_file.file, f)
        logging.info(f"Job {job_id}: Archivo de calendario guardado: {calendar_path}")
    
    # Preparar configuración completa con toda la configuración de negocio por petición
    transcription_config = {
        'fnames': [str(upload_path)],
        'cpus': SERVER_CPUS,  # Solo configuración técnica del servidor
        
        # Configuración del motor (desde petición)
        'whisper': config_obj.whisper,
        'whmodel': config_obj.whmodel,
        'whdevice': config_obj.whdevice,
        'whlanguage': config_obj.whlanguage,
        
        # Configuración de procesamiento (desde petición)
        'seconds': config_obj.seconds,
        'lconf': config_obj.lconf,
        'mconf': config_obj.mconf,
        'hconf': config_obj.hconf,
        'overlap': config_obj.overlap,
        'min_offset': config_obj.min_offset,
        'max_gap': config_obj.max_gap,
        
        # Configuración de colección (desde petición, no del servidor)
        'prefix': config_obj.prefix,
        'html_suffix': config_obj.html_suffix,
        'audio_tags': config_obj.audio_tags,
        
        # Valores por defecto técnicos
        'model': '/mnt/ram/es/vosk-model-es-0.42',
        'whsusptime': 60.0,
        'rwavframes': 4000,
        
        # Parámetros de Pyannote (desde petición del cliente)
        'pyannote_method': config_obj.pyannote_method,
        'pyannote_min_cluster_size': config_obj.pyannote_min_cluster_size,
        'pyannote_threshold': config_obj.pyannote_threshold,
        'pyannote_min_speakers': config_obj.pyannote_min_speakers,
        'pyannote_max_speakers': config_obj.pyannote_max_speakers,
        'huggingface_token': os.getenv('HUGGINGFACE_TOKEN', '')
    }
    
    # Agregar archivos opcionales si se proporcionan
    if training_path:
        transcription_config['whtraining'] = str(training_path)
    
    if calendar_path:
        transcription_config['calendar'] = str(calendar_path)
    elif config_obj.calendar_file:
        transcription_config['calendar'] = config_obj.calendar_file
    
    if config_obj.templates_dir:
        transcription_config['templates'] = config_obj.templates_dir
    
    # Crear entrada de trabajo
    job_status = JobStatus(
        job_id=job_id,
        status="pending",
        created_at=datetime.datetime.now(),
        engine="whisper" if config_obj.whisper else "vosk"
    )
    
    jobs[job_id] = job_status.model_dump()
    
    # Programar tarea en background
    background_tasks.add_task(
        run_transcription_task,
        job_id,
        transcription_config,
        config_obj.whisper
    )
    
    return job_status

@app.get("/jobs/{job_id}/status", response_model=JobStatus)
async def get_job_status(
    job_id: str,
    client_id: str = Depends(get_authenticated_user)
):
    """
    Consultar estado de un trabajo de transcripción
    """
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Trabajo no encontrado")
    
    try:
        job_data = jobs[job_id]
        logging.debug(f"Job {job_id} data keys: {list(job_data.keys())}")
        logging.debug(f"Job {job_id} data: {job_data}")
        
        # Crear JobStatus solo con los campos que conoce el modelo
        job_status_data = {
            'job_id': job_data['job_id'],
            'status': job_data['status'],
            'progress': job_data.get('progress'),
            'message': job_data.get('message'),
            'created_at': job_data['created_at'],
            'started_at': job_data.get('started_at'),
            'completed_at': job_data.get('completed_at'),
            'error': job_data.get('error'),
            'engine': job_data.get('engine'),
            'files': job_data.get('files')
        }
        
        return JobStatus(**job_status_data)
    except Exception as e:
        logging.error(f"Error creating JobStatus for job {job_id}: {e}")
        logging.error(f"Job data: {jobs[job_id]}")
        raise HTTPException(status_code=500, detail=f"Error procesando estado del trabajo: {str(e)}")

@app.get("/jobs/{job_id}/files", response_model=List[JobFile])
async def list_job_files(
    job_id: str,
    client_id: str = Depends(get_authenticated_user)
):
    """
    Lista archivos disponibles para un trabajo completado
    """
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Trabajo no encontrado")
    
    job = jobs[job_id]
    if job['status'] != 'completed':
        raise HTTPException(status_code=400, detail="Trabajo no completado")
    
    files = []
    if job.get('files'):
        for file_info in job['files']:
            file_path = Path(file_info['path'])
            if file_path.exists():
                stat = file_path.stat()
                files.append(JobFile(
                    filename=file_info['filename'],
                    type=file_info['type'],
                    size=stat.st_size,
                    created_at=datetime.datetime.fromtimestamp(stat.st_ctime)
                ))
    
    return files

@app.get("/jobs/{job_id}/files/{filename}")
async def download_result(
    job_id: str, 
    filename: str,
    client_id: str = Depends(get_authenticated_user)
):
    """
    Descargar archivo de resultado (HTML o SRT)
    """
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Trabajo no encontrado")
    
    job = jobs[job_id]
    if job['status'] != 'completed':
        raise HTTPException(status_code=400, detail="Trabajo no completado")
    
    # Buscar archivo en los resultados del trabajo
    file_path = None
    if job.get('files'):
        for file_info in job['files']:
            if file_info['filename'] == filename:
                file_path = Path(file_info['path'])
                break
    
    if not file_path or not file_path.exists():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    
    # Determinar media type basado en extensión
    media_type = 'application/octet-stream'
    if filename.endswith('.html'):
        media_type = 'text/html; charset=utf-8'
    elif filename.endswith('.srt'):
        media_type = 'application/x-subrip'
    
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type=media_type
    )

@app.delete("/jobs/{job_id}")
async def delete_job(
    job_id: str,
    client_id: str = Depends(get_authenticated_user)
):
    """
    Eliminar trabajo y sus archivos
    """
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Trabajo no encontrado")
    
    job = jobs[job_id]
    
    # Eliminar archivos de resultado
    job_result_dir = RESULTS_DIR / job_id
    if job_result_dir.exists():
        shutil.rmtree(job_result_dir)
    
    # Eliminar directorio de uploads del trabajo (nueva estructura)
    job_upload_dir = UPLOAD_DIR / job_id
    if job_upload_dir.exists():
        shutil.rmtree(job_upload_dir)
    
    # Eliminar directorio de procesamiento
    processing_dir = PROCESSING_DIR / job_id
    if processing_dir.exists():
        shutil.rmtree(processing_dir)
    
    # Eliminar trabajo de memoria
    del jobs[job_id]
    
    return {"message": f"Trabajo {job_id} eliminado"}

@app.get("/server/stats", response_model=ServiceStats)
async def get_server_stats(
    client_id: str = Depends(get_authenticated_user)
):
    """
    Estadísticas del servidor
    """
    total_jobs = len(jobs)
    active_jobs = len([j for j in jobs.values() if j['status'] in ['pending', 'running']])
    completed_jobs = len([j for j in jobs.values() if j['status'] == 'completed'])
    failed_jobs = len([j for j in jobs.values() if j['status'] == 'failed'])
    
    return ServiceStats(
        total_jobs=total_jobs,
        active_jobs=active_jobs,
        completed_jobs=completed_jobs,
        failed_jobs=failed_jobs,
        gpu_slots_available=gpu_semaphore._value if gpu_semaphore else 0,
        server_cpus=getattr(app.state, 'cpus', SERVER_CPUS),
        server_gpus=getattr(app.state, 'gpus', SERVER_GPUS),
        uptime="N/A"  # TODO: Calcular uptime real
    )

@app.get("/server/debug")
async def get_server_debug(
    client_id: str = Depends(get_authenticated_user)
):
    """
    Endpoint de diagnóstico para depurar bloqueos del servidor
    Muestra el estado del semáforo GPU y trabajos activos
    """
    # Información del semáforo GPU
    semaphore_info = {
        "total_slots": getattr(app.state, 'gpus', SERVER_GPUS),
        "available_slots": gpu_semaphore._value if gpu_semaphore else 0,
        "occupied_slots": (getattr(app.state, 'gpus', SERVER_GPUS) - (gpu_semaphore._value if gpu_semaphore else 0)),
        "locked": gpu_semaphore.locked() if gpu_semaphore else False,
    }
    
    # Clasificar trabajos por estado y tipo
    pending_gpu = []
    running_gpu = []
    pending_cpu = []
    running_cpu = []
    completed = []
    failed = []
    
    for job_id, job_data in jobs.items():
        job_info = {
            "job_id": job_id,
            "status": job_data['status'],
            "engine": "whisper" if job_data.get('whisper', False) else "vosk",
            "created_at": job_data['created_at'].isoformat() if isinstance(job_data['created_at'], datetime.datetime) else str(job_data['created_at']),
            "elapsed_seconds": (datetime.datetime.now() - job_data['created_at']).total_seconds() if isinstance(job_data['created_at'], datetime.datetime) else 0,
            "message": job_data.get('message', 'N/A')
        }
        
        is_gpu = job_data.get('whisper', False)
        status = job_data['status']
        
        if status == 'pending':
            if is_gpu:
                pending_gpu.append(job_info)
            else:
                pending_cpu.append(job_info)
        elif status == 'running':
            if is_gpu:
                running_gpu.append(job_info)
            else:
                running_cpu.append(job_info)
        elif status == 'completed':
            completed.append(job_info)
        elif status == 'failed':
            failed.append(job_info)
    
    return {
        "timestamp": datetime.datetime.now().isoformat(),
        "gpu_semaphore": semaphore_info,
        "jobs_summary": {
            "total": len(jobs),
            "pending_gpu": len(pending_gpu),
            "running_gpu": len(running_gpu),
            "pending_cpu": len(pending_cpu),
            "running_cpu": len(running_cpu),
            "completed": len(completed),
            "failed": len(failed)
        },
        "jobs_detail": {
            "pending_gpu": pending_gpu,
            "running_gpu": running_gpu,
            "pending_cpu": pending_cpu,
            "running_cpu": running_cpu,
            "completed": completed[:10],  # Solo últimos 10 completados
            "failed": failed[:10]  # Solo últimos 10 fallidos
        },
        "warnings": []
    }

## ENDPOINTS DE COMPATIBILIDAD HACIA ATRÁS (sin autenticación para compatibilidad)

@app.get("/status/{job_id}", response_model=JobStatus)
async def get_job_status_compat(job_id: str):
    """Compatibilidad hacia atrás - sin autenticación"""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Trabajo no encontrado")
    return JobStatus(**jobs[job_id])

@app.get("/results/{job_id}/{filename}")
async def download_result_compat(job_id: str, filename: str):
    """Compatibilidad hacia atrás - sin autenticación"""
    return await download_result.__wrapped__(job_id, filename, 'legacy_client')

@app.get("/jobs", response_model=List[JobStatus])
async def list_jobs(status: Optional[str] = None):
    """
    Listar trabajos de transcripción (sin autenticación para compatibilidad)
    """
    job_list = [JobStatus(**job) for job in jobs.values()]
    
    if status:
        job_list = [job for job in job_list if job.status == status]
    
    # Ordenar por fecha de creación (más recientes primero)
    job_list.sort(key=lambda x: x.created_at, reverse=True)
    
    return job_list

@app.get("/stats", response_model=ServiceStats)
async def get_service_stats_compat():
    """Compatibilidad hacia atrás - sin autenticación"""
    return await get_server_stats.__wrapped__('legacy_client')

@app.get("/")
async def root():
    """
    Información básica del servicio
    """
    return {
        "service": "STTCast Transcription Service",
        "version": "2.0.0 - Refactorizado",
        "status": "running",
        "authentication": "HMAC enabled" if API_SECRET_KEY else "disabled",
        "endpoints": {
            "new_api": {
                "transcribe": "POST /transcribe - Subir audio para transcripción (autenticado)",
                "job_status": "GET /jobs/{job_id}/status - Consultar estado de trabajo (autenticado)",
                "list_files": "GET /jobs/{job_id}/files - Lista archivos disponibles (autenticado)",
                "download": "GET /jobs/{job_id}/files/{filename} - Descargar resultado (autenticado)",
                "delete": "DELETE /jobs/{job_id} - Eliminar trabajo (autenticado)",
                "server_stats": "GET /server/stats - Estadísticas del servidor (autenticado)"
            },
            "legacy_api": {
                "status": "GET /status/{job_id} - Consultar estado de trabajo",
                "results": "GET /results/{job_id}/{filename} - Descargar resultado", 
                "jobs": "GET /jobs - Listar trabajos",
                "stats": "GET /stats - Estadísticas del servicio"
            }
        },
        "directory_structure": {
            "upload": str(UPLOAD_DIR),
            "processing": str(PROCESSING_DIR),
            "results": str(RESULTS_DIR)
        }
    }

@app.get("/health")
async def health_check():
    """Endpoint de health check"""
    return {"status": "ok", "service": "sttcast-trans", "timestamp": time.time()}

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="STTCast REST Transcription Service - Refactorizado")
    parser.add_argument("--host", default=SERVER_HOST, help=f"Host a bind (default: {SERVER_HOST})")
    parser.add_argument("--port", type=int, default=SERVER_PORT, help=f"Puerto del servicio (default: {SERVER_PORT})")
    parser.add_argument("--cpus", type=int, default=SERVER_CPUS, help=f"CPUs del servidor (default: {SERVER_CPUS})")
    parser.add_argument("--gpus", type=int, default=SERVER_GPUS, help=f"Slots GPU simultáneos (default: {SERVER_GPUS})")
    parser.add_argument("--log-level", default="info", help="Nivel de logging")
    
    args = parser.parse_args()
    
    # Configurar state de la app con argumentos finales
    app.state.cpus = args.cpus
    app.state.gpus = args.gpus
    
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level=args.log_level,
        access_log=True
    )