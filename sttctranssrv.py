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
from typing import Optional, Dict, List, Any
from pathlib import Path
import tempfile
import shutil
from contextlib import asynccontextmanager
from concurrent.futures import ProcessPoolExecutor
import multiprocessing as mp

from fastapi import FastAPI, File, UploadFile, Form, HTTPException, BackgroundTasks, Request, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
import uvicorn

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
SERVER_VOSK_MODEL = os.getenv('TRANSSRV_VOSK_MODEL', '/mnt/ram/es/vosk-model-es-0.42')
SERVER_WHMODEL = os.getenv('TRANSSRV_WHMODEL', 'small')
SERVER_WHDEVICE = os.getenv('TRANSSRV_WHDEVICE', 'cuda')
SERVER_WHBATCH_SIZE = int(os.getenv('TRANSSRV_WHBATCH_SIZE', '8'))
SERVER_CUDA_OOM_RETRIES = int(os.getenv('TRANSSRV_CUDA_OOM_RETRIES', '2'))
SERVER_CUDA_OOM_RETRY_DELAY = float(os.getenv('TRANSSRV_CUDA_OOM_RETRY_DELAY', '45'))
SERVER_GPU_START_INTERVAL = float(os.getenv('TRANSSRV_GPU_START_INTERVAL', '0'))
SERVER_VOSK_ADMISSION_DELAY = float(os.getenv('TRANSSRV_VOSK_ADMISSION_DELAY', str(SERVER_GPU_START_INTERVAL)))
SERVER_FFMPEG_SLOTS = max(1, int(os.getenv('TRANSSRV_FFMPEG_SLOTS', '2')))
SERVER_FFMPEG_THREADS = max(1, int(os.getenv('TRANSSRV_FFMPEG_THREADS', '1')))
SERVER_RESOURCE_TRACE_INTERVAL = float(os.getenv('TRANSSRV_RESOURCE_TRACE_INTERVAL', '10'))
SERVER_RESOURCE_TRACE_TOPN = max(1, int(os.getenv('TRANSSRV_RESOURCE_TRACE_TOPN', '12')))
SERVER_PYANNOTE_BATCH_SIZE = max(1, int(os.getenv('TRANSSRV_PYANNOTE_BATCH_SIZE', '16')))
API_SECRET_KEY = os.getenv('TRANSSRV_API_KEY', '')

if not API_SECRET_KEY:
    raise ValueError("TRANSSRV_API_KEY no está configurada en .env/transsrv.env")

# Variables globales del servicio
resource_scheduler: Optional["ResourceScheduler"] = None
gpu_process_pool: Optional[ProcessPoolExecutor] = None
ffmpeg_manager = None
ffmpeg_semaphore = None
resource_trace_task = None
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
    whlanguage: str = Field("es", description="Idioma")
    whsusptime: float = Field(60.0, description="Tiempo mínimo de intervención en segundos")
    
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
    cpu_slots_available: int
    gpu_slots_available: int
    server_cpus: int
    server_gpus: int
    uptime: str


class ResourceScheduler:
    """
    Planificador de admisión para jobs de transcripción.

    TRANSSRV_CPUS representa slots de admisión CPU. TRANSSRV_GPUS representa
    slots de VRAM, no necesariamente GPUs físicas. Cada job admitido toma un
    slot CPU; Whisper con CUDA toma además un slot VRAM.
    """

    def __init__(self, cpus: int, gpu_slots: int, gpu_start_interval: float = 0.0, vosk_admission_delay: float = 0.0):
        self.total_cpus = cpus
        self.total_gpu_slots = gpu_slots
        self.available_cpus = cpus
        self.available_gpu_slots = gpu_slots
        self.gpu_start_interval = max(0.0, gpu_start_interval)
        self.vosk_admission_delay = max(0.0, vosk_admission_delay)
        self.last_gpu_start_at = 0.0
        self.waiting: List[Dict[str, Any]] = []
        self.running: Dict[str, Dict[str, Any]] = {}
        self.condition = asyncio.Condition()

    def _first_waiting_gpu(self) -> Optional[Dict[str, Any]]:
        return next((job for job in self.waiting if job["requires_gpu"]), None)

    def _first_waiting_cpu(self) -> Optional[Dict[str, Any]]:
        return next((job for job in self.waiting if not job["requires_gpu"]), None)

    def _is_entry_ready(self, entry: Dict[str, Any]) -> bool:
        return time.monotonic() >= entry["ready_at"]

    def _is_gpu_start_ready(self) -> bool:
        if self.last_gpu_start_at <= 0.0:
            return True
        return (time.monotonic() - self.last_gpu_start_at) >= self.gpu_start_interval

    def _gpu_waiting_blocks_cpu(self) -> bool:
        return self._first_waiting_gpu() is not None and self.available_gpu_slots >= 1

    def _next_wakeup_delay(self, entry: Dict[str, Any]) -> float:
        now = time.monotonic()
        delays = []
        if now < entry["ready_at"]:
            delays.append(entry["ready_at"] - now)
        first_gpu = self._first_waiting_gpu()
        if (
            first_gpu is not None
            and self.available_gpu_slots >= 1
            and self.last_gpu_start_at > 0.0
            and not self._is_gpu_start_ready()
        ):
            delays.append(max(0.0, self.gpu_start_interval - (now - self.last_gpu_start_at)))
        return max(0.1, min(delays)) if delays else 1.0

    def _can_run(self, entry: Dict[str, Any]) -> bool:
        if (
            entry not in self.waiting
            or self.available_cpus < 1
            or not self._is_entry_ready(entry)
        ):
            return False

        first_gpu = self._first_waiting_gpu()
        if entry["requires_gpu"]:
            return (
                first_gpu is entry
                and self.available_gpu_slots >= 1
                and self._is_gpu_start_ready()
            )

        first_cpu = self._first_waiting_cpu()
        return first_cpu is entry and not self._gpu_waiting_blocks_cpu()

    async def acquire(self, job_id: str, requires_gpu: bool, timeout: float):
        now = time.monotonic()
        entry = {
            "job_id": job_id,
            "requires_gpu": requires_gpu,
            "queued_at": datetime.datetime.now(),
            "queued_monotonic": now,
            "ready_at": now + (0.0 if requires_gpu else self.vosk_admission_delay),
        }

        async with self.condition:
            self.waiting.append(entry)
            self.condition.notify_all()
            try:
                deadline = time.monotonic() + timeout
                while not self._can_run(entry):
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise asyncio.TimeoutError()
                    wait_time = min(self._next_wakeup_delay(entry), remaining)
                    try:
                        await asyncio.wait_for(self.condition.wait(), timeout=wait_time)
                    except asyncio.TimeoutError:
                        pass
            except BaseException:
                if entry in self.waiting:
                    self.waiting.remove(entry)
                    self.condition.notify_all()
                raise

            self.waiting.remove(entry)
            self.available_cpus -= 1
            if requires_gpu:
                self.available_gpu_slots -= 1
                self.last_gpu_start_at = time.monotonic()
            self.running[job_id] = entry
            self.condition.notify_all()

    async def release(self, job_id: str):
        async with self.condition:
            entry = self.running.pop(job_id, None)
            if entry is None:
                logging.warning(f"Job {job_id}: intento de liberar recursos no adquiridos")
                return

            self.available_cpus += 1
            if entry["requires_gpu"]:
                self.available_gpu_slots += 1

            self.available_cpus = min(self.available_cpus, self.total_cpus)
            self.available_gpu_slots = min(self.available_gpu_slots, self.total_gpu_slots)
            self.condition.notify_all()

    def snapshot(self) -> Dict[str, Any]:
        return {
            "total_cpus": self.total_cpus,
            "available_cpus": self.available_cpus,
            "occupied_cpus": self.total_cpus - self.available_cpus,
            "total_gpu_slots": self.total_gpu_slots,
            "available_gpu_slots": self.available_gpu_slots,
            "occupied_gpu_slots": self.total_gpu_slots - self.available_gpu_slots,
            "gpu_start_interval": self.gpu_start_interval,
            "vosk_admission_delay": self.vosk_admission_delay,
            "last_gpu_start_at": self.last_gpu_start_at,
            "waiting": list(self.waiting),
            "running": dict(self.running),
        }

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
    global resource_scheduler, gpu_process_pool
    global ffmpeg_manager, ffmpeg_semaphore, resource_trace_task
    
    # Startup
    logcfg(__file__)
    
    # Obtener configuración final (puede ser sobrescrita por args)
    final_cpus = getattr(app.state, 'cpus', SERVER_CPUS)
    final_gpus = getattr(app.state, 'gpus', SERVER_GPUS)

    logging.info(
        f"Iniciando STTCast Service con {final_cpus} CPUs, "
        f"{final_gpus} workers GPU persistentes, "
        f"{SERVER_FFMPEG_SLOTS} slots ffmpeg, "
        f"{SERVER_FFMPEG_THREADS} threads por ffmpeg"
    )
    
    resource_scheduler = ResourceScheduler(
        final_cpus,
        final_gpus,
        SERVER_GPU_START_INTERVAL,
        SERVER_VOSK_ADMISSION_DELAY,
    )
    ffmpeg_manager = mp.Manager()
    ffmpeg_semaphore = ffmpeg_manager.BoundedSemaphore(SERVER_FFMPEG_SLOTS)

    if final_gpus > 0 and SERVER_WHDEVICE == "cuda":
        gpu_process_pool = ProcessPoolExecutor(
            max_workers=final_gpus,
            mp_context=mp.get_context("spawn"),
        )
        warmup_futures = [gpu_process_pool.submit(warm_gpu_worker) for _ in range(final_gpus)]
        warmup_pids = [future.result(timeout=180) for future in warmup_futures]
        logging.info(f"Workers GPU precalentados: {warmup_pids}")
    elif SERVER_WHDEVICE != "cuda":
        logging.info(f"Whisper configurado en {SERVER_WHDEVICE}; no se crea pool GPU")
    
    # Configurar directorios
    UPLOAD_DIR.mkdir(exist_ok=True)
    PROCESSING_DIR.mkdir(exist_ok=True, parents=True)
    RESULTS_DIR.mkdir(exist_ok=True, parents=True)
    
    logging.info(f"Upload dir: {UPLOAD_DIR}")
    logging.info(f"Processing dir: {PROCESSING_DIR}")
    logging.info(f"Results dir: {RESULTS_DIR}")
    logging.info(f"HMAC Authentication: {'Enabled' if API_SECRET_KEY else 'Disabled'}")
    if SERVER_RESOURCE_TRACE_INTERVAL > 0:
        resource_trace_task = asyncio.create_task(resource_trace_loop())
        logging.info(
            f"RESOURCE_TRACE activado cada {SERVER_RESOURCE_TRACE_INTERVAL:.1f}s "
            f"(top {SERVER_RESOURCE_TRACE_TOPN} procesos)"
        )
    
    yield
    
    # Shutdown
    logging.info("Cerrando STTCast Service")
    if resource_trace_task:
        resource_trace_task.cancel()
        try:
            await resource_trace_task
        except asyncio.CancelledError:
            pass
        resource_trace_task = None
    if gpu_process_pool:
        gpu_process_pool.shutdown(wait=True)
        gpu_process_pool = None
    if ffmpeg_manager:
        ffmpeg_manager.shutdown()
        ffmpeg_manager = None
        ffmpeg_semaphore = None

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


def _read_meminfo_mb() -> Dict[str, Any]:
    result = {}
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            for line in f:
                key, value = line.split(":", 1)
                if key in {"MemTotal", "MemAvailable", "MemFree", "Cached", "SwapTotal", "SwapFree"}:
                    result[key] = int(value.strip().split()[0]) // 1024
    except Exception as e:
        result["error"] = str(e)
    return result


def _read_process_status_mb(pid: int) -> Dict[str, Any]:
    data = {"rss_mb": 0, "threads": 0}
    try:
        with open(f"/proc/{pid}/status", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    data["rss_mb"] = int(line.split()[1]) // 1024
                elif line.startswith("Threads:"):
                    data["threads"] = int(line.split()[1])
    except Exception:
        pass
    return data


def _read_process_stat(pid: int) -> Dict[str, Any]:
    try:
        with open(f"/proc/{pid}/stat", "r", encoding="utf-8") as f:
            stat = f.read()
        end_comm = stat.rfind(")")
        parts = stat[end_comm + 2:].split()
        return {
            "state": parts[0],
            "ppid": int(parts[1]),
            "pgid": int(parts[2]),
        }
    except Exception:
        return {"state": "?", "ppid": -1, "pgid": -1}


def _read_cmdline(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            return f.read().replace(b"\0", b" ").decode("utf-8", errors="replace").strip()
    except Exception:
        return ""


def _interesting_process(cmdline: str, pgid: int, server_pgid: int) -> bool:
    return (
        pgid == server_pgid
        or "sttctranssrv.py" in cmdline
        or "sttcastcli.py" in cmdline
        or ("spawn_main" in cmdline and "Sttcast" in cmdline)
        or cmdline.startswith("ffmpeg ")
    )


def _collect_sttcast_processes(topn: int) -> List[Dict[str, Any]]:
    server_pgid = os.getpgid(os.getpid())
    processes = []
    for pid_name in os.listdir("/proc"):
        if not pid_name.isdigit():
            continue
        pid = int(pid_name)
        cmdline = _read_cmdline(pid)
        stat = _read_process_stat(pid)
        if not cmdline or not _interesting_process(cmdline, stat["pgid"], server_pgid):
            continue
        status = _read_process_status_mb(pid)
        processes.append({
            "pid": pid,
            "ppid": stat["ppid"],
            "pgid": stat["pgid"],
            "state": stat["state"],
            "rss_mb": status["rss_mb"],
            "threads": status["threads"],
            "orphan": stat["ppid"] == 1,
            "cmd": cmdline[:180],
        })
    return sorted(processes, key=lambda p: p["rss_mb"], reverse=True)[:topn]


def _job_summary() -> Dict[str, int]:
    summary = {
        "pending_whisper": 0,
        "running_whisper": 0,
        "pending_vosk": 0,
        "running_vosk": 0,
        "completed": 0,
        "failed": 0,
    }
    for job in jobs.values():
        status = job.get("status")
        engine = "whisper" if job.get("whisper", False) else "vosk"
        if status in {"pending", "running"}:
            summary[f"{status}_{engine}"] += 1
        elif status in {"completed", "failed"}:
            summary[status] += 1
    return summary


async def resource_trace_loop():
    while True:
        await asyncio.sleep(SERVER_RESOURCE_TRACE_INTERVAL)
        try:
            scheduler_snapshot = resource_scheduler.snapshot() if resource_scheduler else {}
            logging.info(
                "[RESOURCE_TRACE] mem=%s jobs=%s resources=%s top_processes=%s",
                _read_meminfo_mb(),
                _job_summary(),
                {
                    "cpu_free": scheduler_snapshot.get("available_cpus"),
                    "cpu_total": scheduler_snapshot.get("total_cpus"),
                    "gpu_free": scheduler_snapshot.get("available_gpu_slots"),
                    "gpu_total": scheduler_snapshot.get("total_gpu_slots"),
                    "waiting": len(scheduler_snapshot.get("waiting", [])),
                    "running": len(scheduler_snapshot.get("running", {})),
                },
                _collect_sttcast_processes(SERVER_RESOURCE_TRACE_TOPN),
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logging.warning(f"[RESOURCE_TRACE] error generando traza: {e}")


def is_cuda_oom_error(exc: Exception) -> bool:
    error = str(exc).lower()
    if "batch_size" in error and (
        "too large" in error
        or "memory" in error
        or "smaller value" in error
    ):
        return True
    return (
        "cuda" in error
        and (
            "out of memory" in error
            or "batch_size" in error
            or "memory error" in error
        )
    )


def reset_processing_dir(job_id: str, config: Dict[str, Any]):
    temp_dir = Path(config['temp_dir'])
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(exist_ok=True, parents=True)
    config['temp_dir'] = str(temp_dir)
    config['work_id'] = job_id


def warm_gpu_worker():
    sttcast_core.configure_worker_threads()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.init()
            probe = torch.zeros((1,), device="cuda")
            torch.cuda.synchronize()
            del probe
            sttcast_core.cleanup_cuda_memory()
        time.sleep(2.0)
    except Exception as e:
        logging.warning(f"No se pudo precalentar worker GPU: {e}")
    return os.getpid()


async def run_transcription_task(job_id: str, config: Dict[str, Any], use_gpu: bool):
    """
    Ejecutar tarea de transcripción con flujo mejorado:
    1. Procesar en directorio temporal /processing/{job_id}/
    2. Solo mover a /completed/{job_id}/ cuando esté 100% completado
    3. Archivos finales sin UUID ni sufijos
    4. Admisión por recursos CPU/VRAM con prioridad para Whisper
    """
    result = None
    requires_gpu_slot = use_gpu and config.get('whdevice', SERVER_WHDEVICE) == 'cuda'
    resources_acquired = False
    
    try:
        update_job_status(job_id,
                         status="pending",
                         message="Esperando recursos...")
        
        # Crear directorio de procesamiento único para este trabajo
        job_processing_dir = PROCESSING_DIR / job_id
        job_processing_dir.mkdir(exist_ok=True)
        config['temp_dir'] = str(job_processing_dir)
        config['work_id'] = job_id
        
        # Obtener nombre original del archivo
        original_filename = None
        if 'fnames' in config and config['fnames']:
            original_path = Path(config['fnames'][0])
            original_filename = original_path.stem
        
        # En modo servicio cada archivo ocupa un slot CPU. Se ejecuta inline
        # para evitar pools hijos por job; Vosk reutiliza un modelo cacheado.
        config['cpus'] = 1
        config['inline_executor'] = True

        resource_timeout = 172800  # 48 horas esperando recursos
        if not resource_scheduler:
            raise RuntimeError("Planificador de recursos no inicializado")
        if requires_gpu_slot and not gpu_process_pool:
            raise RuntimeError("Pool persistente GPU no inicializado")

        max_attempts = 1 + (SERVER_CUDA_OOM_RETRIES if requires_gpu_slot else 0)
        attempt = 0
        while True:
            attempt += 1
            if attempt > 1:
                reset_processing_dir(job_id, config)

            update_job_status(job_id,
                              status="pending",
                              message=f"Esperando recursos... intento {attempt}/{max_attempts}")
            logging.info(
                f"Job {job_id}: esperando recursos "
                f"({'CPU+VRAM' if requires_gpu_slot else 'CPU'}) "
                f"intento {attempt}/{max_attempts}"
            )
            await resource_scheduler.acquire(job_id, requires_gpu_slot, resource_timeout)
            resources_acquired = True
            resource_snapshot = resource_scheduler.snapshot()
            logging.info(
                f"Job {job_id}: recursos adquiridos "
                f"(CPU {resource_snapshot['available_cpus']}/{resource_snapshot['total_cpus']} libres, "
                f"VRAM {resource_snapshot['available_gpu_slots']}/{resource_snapshot['total_gpu_slots']} libre)"
            )

            try:
                engine_msg = "Whisper" if use_gpu else "Vosk"
                batch_msg = (
                    f", batch_size={config.get('whbatch_size')}"
                    if requires_gpu_slot else ""
                )
                update_job_status(job_id,
                                  status="running",
                                  started_at=jobs[job_id].get('started_at') or datetime.datetime.now(),
                                  message=f"Transcribiendo con {engine_msg}... intento {attempt}/{max_attempts}")
                logging.info(
                    f"Job {job_id}: Iniciando transcripción {engine_msg} "
                    f"intento {attempt}/{max_attempts}{batch_msg}"
                )
                loop = asyncio.get_event_loop()
                start_time = time.time()

                executor = gpu_process_pool if requires_gpu_slot else None
                result = await loop.run_in_executor(
                    executor,
                    sttcast_core.transcribe_audio,
                    config
                )

                elapsed = time.time() - start_time
                logging.info(
                    f"Job {job_id}: Transcripción {engine_msg} completada "
                    f"en {elapsed:.1f}s en intento {attempt}/{max_attempts}"
                )

                await resource_scheduler.release(job_id)
                resources_acquired = False
                resource_snapshot = resource_scheduler.snapshot()
                logging.info(
                    f"Job {job_id}: recursos liberados "
                    f"(CPU {resource_snapshot['available_cpus']}/{resource_snapshot['total_cpus']} libres, "
                    f"VRAM {resource_snapshot['available_gpu_slots']}/{resource_snapshot['total_gpu_slots']} libre)"
                )
                break

            except Exception as attempt_error:
                if resources_acquired:
                    await resource_scheduler.release(job_id)
                    resources_acquired = False
                    resource_snapshot = resource_scheduler.snapshot()
                    logging.info(
                        f"Job {job_id}: recursos liberados tras error "
                        f"(CPU {resource_snapshot['available_cpus']}/{resource_snapshot['total_cpus']} libres, "
                        f"VRAM {resource_snapshot['available_gpu_slots']}/{resource_snapshot['total_gpu_slots']} libre)"
                    )

                if (
                    attempt < max_attempts
                    and requires_gpu_slot
                    and is_cuda_oom_error(attempt_error)
                ):
                    current_batch_size = max(1, int(config.get('whbatch_size', SERVER_WHBATCH_SIZE)))
                    next_batch_size = max(1, current_batch_size // 2)
                    config['whbatch_size'] = next_batch_size
                    delay = SERVER_CUDA_OOM_RETRY_DELAY * attempt
                    logging.warning(
                        f"Job {job_id}: OOM CUDA en intento {attempt}/{max_attempts}: "
                        f"{attempt_error}. Reintento en {delay:.1f}s con "
                        f"batch_size={next_batch_size}"
                    )
                    update_job_status(job_id,
                                      status="pending",
                                      message=(
                                          f"OOM CUDA; reintentando en {delay:.0f}s "
                                          f"con batch_size={next_batch_size}"
                                      ))
                    await asyncio.sleep(delay)
                    continue

                raise
        
        # Verificar que tenemos resultado antes de continuar
        if not result:
            raise RuntimeError(f"Job {job_id}: transcribe_audio retornó None o sin contenido")
        
        # Crear directorio de resultados finales
        job_result_dir = RESULTS_DIR / job_id
        job_result_dir.mkdir(exist_ok=True)
        
        result_files = []
        
        # Obtener html_suffix del config (ya incluye el '_' si no está vacío)
        html_suffix = config.get('html_suffix', '')
        if html_suffix and not html_suffix.startswith('_'):
            html_suffix = '_' + html_suffix
        
        # Mover archivos de resultado con nombres finales limpios
        if 'output_files' not in result:
            logging.warning(f"Job {job_id}: Resultado sin 'output_files'")
        else:
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
                         message=f"Transcripción completada en {result.get('duration', 'N/A')}",
                         files=result_files)
        
        # Limpiar archivos temporales
        _cleanup_temp_files(job_id, config)
        
        logging.info(f"Job {job_id}: Completado exitosamente")
        
    except Exception as e:
        logging.error(f"Job {job_id}: Error - {str(e)}", exc_info=True)
        
        # Si todavía tenemos recursos por algún error, liberarlos
        if resources_acquired and resource_scheduler:
            try:
                await resource_scheduler.release(job_id)
                resources_acquired = False
                logging.warning(f"Job {job_id}: recursos liberados tras excepción")
            except Exception as release_err:
                logging.error(f"Job {job_id}: Error liberando recursos en excepción: {release_err}")
        
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
        logging.info(f"  Modelo Whisper servidor: {SERVER_WHMODEL}")
        logging.info(f"  Dispositivo Whisper servidor: {SERVER_WHDEVICE}")
        logging.info(f"  Idioma: {config_obj.whlanguage}")
        logging.info(f"  Whisper batch size servidor: {SERVER_WHBATCH_SIZE}")
        logging.info(f"  whsusptime: {config_obj.whsusptime}")
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
        'cpus': 1,
        
        # Configuración del motor (desde petición)
        'whisper': config_obj.whisper,
        'whmodel': SERVER_WHMODEL,
        'whdevice': SERVER_WHDEVICE,
        'whlanguage': config_obj.whlanguage,
        'whbatch_size': max(1, SERVER_WHBATCH_SIZE),
        
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
        'model': SERVER_VOSK_MODEL,
        'whsusptime': config_obj.whsusptime,
        'rwavframes': 4000,
        'mp_start_method': 'spawn',
        'ffmpeg_semaphore': ffmpeg_semaphore,
        'ffmpeg_threads': SERVER_FFMPEG_THREADS,
        'pyannote_batch_size': SERVER_PYANNOTE_BATCH_SIZE,
        
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
    jobs[job_id]['whisper'] = config_obj.whisper
    jobs[job_id]['requires_gpu'] = config_obj.whisper and SERVER_WHDEVICE == 'cuda'
    
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
    scheduler_snapshot = resource_scheduler.snapshot() if resource_scheduler else {}
    
    return ServiceStats(
        total_jobs=total_jobs,
        active_jobs=active_jobs,
        completed_jobs=completed_jobs,
        failed_jobs=failed_jobs,
        cpu_slots_available=scheduler_snapshot.get('available_cpus', 0),
        gpu_slots_available=scheduler_snapshot.get('available_gpu_slots', 0),
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
    Muestra el estado del planificador y trabajos activos
    """
    scheduler_snapshot = resource_scheduler.snapshot() if resource_scheduler else {}
    resource_info = {
        "total_cpus": scheduler_snapshot.get("total_cpus", getattr(app.state, 'cpus', SERVER_CPUS)),
        "available_cpus": scheduler_snapshot.get("available_cpus", 0),
        "occupied_cpus": scheduler_snapshot.get("occupied_cpus", 0),
        "total_gpu_slots": scheduler_snapshot.get("total_gpu_slots", getattr(app.state, 'gpus', SERVER_GPUS)),
        "available_gpu_slots": scheduler_snapshot.get("available_gpu_slots", 0),
        "occupied_gpu_slots": scheduler_snapshot.get("occupied_gpu_slots", 0),
        "ffmpeg_slots": SERVER_FFMPEG_SLOTS,
        "ffmpeg_threads": SERVER_FFMPEG_THREADS,
        "waiting_count": len(scheduler_snapshot.get("waiting", [])),
        "running_count": len(scheduler_snapshot.get("running", {})),
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
            "requires_gpu": job_data.get('requires_gpu', False),
            "created_at": job_data['created_at'].isoformat() if isinstance(job_data['created_at'], datetime.datetime) else str(job_data['created_at']),
            "elapsed_seconds": (datetime.datetime.now() - job_data['created_at']).total_seconds() if isinstance(job_data['created_at'], datetime.datetime) else 0,
            "message": job_data.get('message', 'N/A')
        }
        
        is_gpu = job_data.get('requires_gpu', job_data.get('whisper', False))
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
        "resources": resource_info,
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
