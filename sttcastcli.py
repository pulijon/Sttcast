#!/usr/bin/env python3
"""
Cliente CLI para STTCast REST Service - REFACTORIZADO
Mantiene compatibilidad total con sttcast.py pero usa el servicio REST con autenticación HMAC
"""

import argparse
import os
import sys
import time
import logging
import datetime
import asyncio
import aiohttp
from pathlib import Path
from typing import List, Dict, Any, Optional
import json

from api.apihmac import create_auth_headers
from tools.logs import logcfg
from tools.envvars import load_env_vars_from_directory

# Cargar configuración
load_env_vars_from_directory(os.path.join(os.path.dirname(__file__), '.env'))

# Configuración por defecto (compatible con sttcast.py)
DEFAULT_MODEL = "/mnt/ram/es/vosk-model-es-0.42"
DEFAULT_WHMODEL = "small"
DEFAULT_WHDEVICE = "cuda"
DEFAULT_WHLANGUAGE = "es"
DEFAULT_WHSUSPTIME = 60.0
DEFAULT_RWAVFRAMES = 4000
DEFAULT_SECONDS = 15000
DEFAULT_HCONF = 0.95
DEFAULT_MCONF = 0.7
DEFAULT_LCONF = 0.5
DEFAULT_OVERLAPTIME = 2
DEFAULT_MINOFFSET = 30
DEFAULT_MAXGAP = 0.8
DEFAULT_HTMLSUFFIX = ""
DEFAULT_PODCAST_CAL_FILE = "calfile"
DEFAULT_PODCAST_PREFIX = "cm"
DEFAULT_PODCAST_TEMPLATES = "templates"
DEFAULT_SERVER_URL = "http://localhost:8505"
DEFAULT_POLL_INTERVAL = 5.0
DEFAULT_TIMEOUT = 36000  # 10 horas por defecto

# Parámetros de Pyannote (valores por defecto, se sobrescriben con variables de entorno)
DEFAULT_PYANNOTE_METHOD = "ward"
DEFAULT_PYANNOTE_MIN_CLUSTER_SIZE = 15
DEFAULT_PYANNOTE_THRESHOLD = 0.7147

# Configuración de autenticación
API_SECRET_KEY = os.getenv('TRANSSRV_API_KEY', '')

class STTCastRESTClient:
    """Cliente REST asíncrono para STTCast Service con autenticación HMAC"""
    
    def __init__(self, server_url: str, api_key: str = ""):
        self.server_url = server_url.rstrip('/')
        self.api_key = api_key
        
    async def _make_authenticated_request(self, session: aiohttp.ClientSession, method: str, url: str, **kwargs) -> aiohttp.ClientResponse:
        """Realizar petición autenticada con HMAC"""
        if not self.api_key:
            # Sin autenticación - usar endpoints legacy
            async with session.request(method, url, **kwargs) as response:
                response.raise_for_status()
                return await response.json()
        
        # Con autenticación HMAC - usar nuevos endpoints
        if 'data' in kwargs:
            # Para uploads multipart, usar autenticación HMAC con body vacío
            headers = create_auth_headers(self.api_key, method, url, None)
            
            # Merge headers
            request_headers = kwargs.get('headers', {})
            headers.update(request_headers)
            kwargs['headers'] = headers
            
        else:
            # Para JSON requests, usar autenticación HMAC normal
            body = kwargs.get('json', None)
            headers = create_auth_headers(self.api_key, method, url, body)
            
            # Merge headers
            request_headers = kwargs.get('headers', {})
            headers.update(request_headers)
            kwargs['headers'] = headers
        
        async with session.request(method, url, **kwargs) as response:
            response.raise_for_status()
            return await response.json()
    
    async def transcribe_file(self, session: aiohttp.ClientSession, file_path: str, config: Dict[str, Any], training_path: str = None, calendar_path: str = None) -> Dict[str, Any]:
        """Subir archivo para transcripción"""
        url = f"{self.server_url}/transcribe"
        
        data = aiohttp.FormData()
        
        # Archivo de audio principal - no cerrar el archivo hasta después de la petición
        audio_file = open(file_path, 'rb')
        data.add_field('audio_file', audio_file, filename=Path(file_path).name, content_type='audio/mpeg')
        
        training_file_handle = None
        calendar_file_handle = None
        
        try:
            # Añadir archivo de entrenamiento si se proporciona
            if training_path and os.path.exists(training_path):
                training_file_handle = open(training_path, 'rb')
                data.add_field('training_file', training_file_handle, filename=Path(training_path).name, content_type='audio/mpeg')
                config = config.copy()
                config['use_training'] = True
                logging.info(f"Incluyendo archivo de entrenamiento: {training_path}")
            
            # Añadir archivo de calendario si se proporciona
            if calendar_path and os.path.exists(calendar_path):
                calendar_file_handle = open(calendar_path, 'rb')
                data.add_field('calendar_file', calendar_file_handle, filename=Path(calendar_path).name, content_type='text/csv')
                logging.info(f"Incluyendo archivo de calendario: {calendar_path}")
            
            data.add_field('config', json.dumps(config))
            
            return await self._make_authenticated_request(session, 'POST', url, data=data)
        
        finally:
            # Cerrar archivos después de la petición
            audio_file.close()
            if training_file_handle:
                training_file_handle.close()
            if calendar_file_handle:
                calendar_file_handle.close()
    
    async def get_job_status(self, session: aiohttp.ClientSession, job_id: str) -> Dict[str, Any]:
        """Consultar estado del trabajo"""
        if self.api_key:
            url = f"{self.server_url}/jobs/{job_id}/status"
            return await self._make_authenticated_request(session, 'GET', url)
        else:
            url = f"{self.server_url}/status/{job_id}"
            async with session.get(url) as response:
                response.raise_for_status()
                return await response.json()
    
    async def list_job_files(self, session: aiohttp.ClientSession, job_id: str) -> List[Dict[str, Any]]:
        """Lista archivos disponibles para un trabajo completado"""
        if not self.api_key:
            # Sin autenticación, usar información del status
            status = await self.get_job_status(session, job_id)
            return status.get('files', [])
        
        url = f"{self.server_url}/jobs/{job_id}/files"
        return await self._make_authenticated_request(session, 'GET', url)
    
    async def download_result(self, session: aiohttp.ClientSession, job_id: str, filename: str, local_path: str):
        """Descargar archivo de resultado"""
        if self.api_key:
            url = f"{self.server_url}/jobs/{job_id}/files/{filename}"
            headers = create_auth_headers(self.api_key, 'GET', url, None)
            async with session.get(url, headers=headers) as response:
                response.raise_for_status()
                with open(local_path, 'wb') as f:
                    f.write(await response.read())
        else:
            url = f"{self.server_url}/results/{job_id}/{filename}"
            async with session.get(url) as response:
                response.raise_for_status()
                with open(local_path, 'wb') as f:
                    f.write(await response.read())
    
    async def wait_for_completion(self, session: aiohttp.ClientSession, job_id: str, poll_interval: float = 5.0, timeout: float = None) -> Dict[str, Any]:
        """Esperar a que complete el trabajo"""
        start_time = time.time()
        
        while True:
            status = await self.get_job_status(session, job_id)
            
            if status['status'] == 'completed':
                return status
            elif status['status'] == 'failed':
                raise Exception(f"Transcripción falló: {status.get('error', 'Error desconocido')}")
            
            # Verificar timeout
            if timeout and (time.time() - start_time) > timeout:
                raise Exception(f"Timeout: transcripción no completada en {timeout} segundos")
            
            # Mostrar progreso
            elapsed = time.time() - start_time
            logging.info(f"Job {job_id}: {status['status']} - {status.get('message', '')} (elapsed: {elapsed:.1f}s)")
            
            await asyncio.sleep(poll_interval)

def get_pars():
    """Parsear argumentos CLI - compatible con sttcast.py"""
    # Cargar variables de entorno
    load_env_vars_from_directory(os.path.join(os.path.dirname(__file__), '.env'))
    
    cal_file = os.getenv('PODCAST_CAL_FILE', DEFAULT_PODCAST_CAL_FILE)
    prefix = os.getenv('PODCAST_PREFIX', DEFAULT_PODCAST_PREFIX)
    podcast_templates = os.getenv('PODCAST_TEMPLATES', DEFAULT_PODCAST_TEMPLATES)

    parser = argparse.ArgumentParser(
        description="STTCast CLI - Cliente para servicio REST de transcripción"
    )
    
    # Argumentos principales (compatibles con sttcast.py)
    parser.add_argument("fnames", type=str, nargs='+',
                        help="archivos de audio o directorios a transcribir")
    parser.add_argument("-m", "--model", type=str, default=DEFAULT_MODEL,
                        help=f"modelo Vosk a utilizar. Por defecto, {DEFAULT_MODEL}")
    parser.add_argument("-s", "--seconds", type=int, default=DEFAULT_SECONDS,
                        help=f"segundos de cada tarea. Por defecto, {DEFAULT_SECONDS}")
    parser.add_argument("-c", "--cpus", type=int, default=max(os.cpu_count()-2,1),
                        help="CPUs (ignorado en modo REST - configurado en servidor)")
    parser.add_argument("-i", "--hconf", type=float, default=DEFAULT_HCONF,
                        help=f"umbral de confianza alta. Por defecto, {DEFAULT_HCONF}")
    parser.add_argument("-n", "--mconf", type=float, default=DEFAULT_MCONF,
                        help=f"umbral de confianza media. Por defecto, {DEFAULT_MCONF}")
    parser.add_argument("-l", "--lconf", type=float, default=DEFAULT_LCONF,
                        help=f"umbral de confianza baja. Por defecto, {DEFAULT_LCONF}")
    parser.add_argument("-o", "--overlap", type=float, default=DEFAULT_OVERLAPTIME,
                        help=f"tiempo de solapamiento entre fragmentos. Por defecto, {DEFAULT_OVERLAPTIME}")
    parser.add_argument("-r", "--rwavframes", type=int, default=DEFAULT_RWAVFRAMES,
                        help=f"número de tramas en cada lectura del wav. Por defecto, {DEFAULT_RWAVFRAMES}")
    
    # Argumentos de Whisper
    parser.add_argument("-w", "--whisper", action='store_true',
                        help="utilización de motor whisper")
    parser.add_argument("--whmodel", type=str, default=DEFAULT_WHMODEL,
                        help=f"modelo whisper a utilizar. Por defecto, {DEFAULT_WHMODEL}")
    parser.add_argument("--whdevice", choices=['cuda', 'cpu'], default=DEFAULT_WHDEVICE,
                        help=f"aceleración a utilizar. Por defecto, {DEFAULT_WHDEVICE}")
    parser.add_argument("--whlanguage", default=DEFAULT_WHLANGUAGE,
                        help=f"lenguaje a utilizar. Por defecto, {DEFAULT_WHLANGUAGE}")
    parser.add_argument("--whtraining", type=str, default="training.mp3",
                        help="nombre del fichero de entrenamiento. Por defecto, 'training.mp3'")
    parser.add_argument("--whsusptime", type=float, default=DEFAULT_WHSUSPTIME,
                        help=f"tiempo mínimo de intervención en el segmento. Por defecto, {DEFAULT_WHSUSPTIME}")
    
    # Argumentos de salida
    parser.add_argument("-a", "--audio-tags", action='store_true',
                        help="inclusión de audio tags")
    parser.add_argument("--html-suffix", type=str, default=DEFAULT_HTMLSUFFIX,
                        help=f"sufijo para el fichero HTML con el resultado. Por defecto '{DEFAULT_HTMLSUFFIX}'")
    parser.add_argument("--min-offset", type=float, default=DEFAULT_MINOFFSET, 
                        help=f"diferencia mínima entre inicios de marcas de tiempo. Por defecto {DEFAULT_MINOFFSET}")
    parser.add_argument("--max-gap", type=float, default=DEFAULT_MAXGAP, 
                        help=f"diferencia máxima entre el inicio de un segmento y el final del anterior. "
                             f"Por defecto {DEFAULT_MAXGAP}")
    parser.add_argument("-p", "--prefix", type=str, default=prefix,
                        help=f"prefijo para los ficheros de salida. Por defecto {prefix}")
    parser.add_argument("--calendar", type=str, default=cal_file,
                        help=f"calendario de episodios en formato CSV. Por defecto {cal_file}")
    parser.add_argument("-t", "--templates", type=str, default=podcast_templates,
                        help=f"plantillas para los podcasts. Por defecto {podcast_templates}")
    
    # Argumentos específicos del cliente REST
    parser.add_argument("--server-url", type=str, default=DEFAULT_SERVER_URL,
                        help=f"URL del servidor STTCast REST. Por defecto {DEFAULT_SERVER_URL}")
    parser.add_argument("--poll-interval", type=float, default=DEFAULT_POLL_INTERVAL,
                        help=f"intervalo de consulta de estado en segundos. Por defecto {DEFAULT_POLL_INTERVAL}")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT,
                        help=f"timeout máximo en segundos. Por defecto {DEFAULT_TIMEOUT}")
    parser.add_argument("--no-download", action='store_true',
                        help="no descargar resultados automáticamente")
    
    # Argumentos de Pyannote (para diarización)
    pyannote_method = os.getenv('PYANNOTE_METHOD', DEFAULT_PYANNOTE_METHOD)
    pyannote_min_cluster = int(os.getenv('PYANNOTE_MIN_CLUSTER_SIZE', DEFAULT_PYANNOTE_MIN_CLUSTER_SIZE))
    pyannote_threshold = float(os.getenv('PYANNOTE_THRESHOLD', DEFAULT_PYANNOTE_THRESHOLD))
    
    parser.add_argument("--pyannote-method", type=str, default=pyannote_method,
                        choices=['ward', 'complete', 'average', 'single'],
                        help=f"método de clustering para Pyannote. Por defecto '{pyannote_method}'")
    parser.add_argument("--pyannote-min-cluster-size", type=int, default=pyannote_min_cluster,
                        help=f"tamaño mínimo del cluster. Por defecto {pyannote_min_cluster}")
    parser.add_argument("--pyannote-threshold", type=float, default=pyannote_threshold,
                        help=f"umbral de similitud para clustering. Por defecto {pyannote_threshold}")
    parser.add_argument("--pyannote-min-speakers", type=int, default=None,
                        help="número mínimo de hablantes esperados")
    parser.add_argument("--pyannote-max-speakers", type=int, default=None,
                        help="número máximo de hablantes esperados")
    
    return parser.parse_args()

def build_transcription_config(args) -> Dict[str, Any]:
    """Construir configuración completa para el servicio REST"""
    return {
        # Motor de transcripción
        'whisper': args.whisper,
        'whmodel': args.whmodel,
        'whdevice': args.whdevice,
        'whlanguage': args.whlanguage,
        'whsusptime': args.whsusptime,
        
        # Configuración de colección (ahora por petición)
        'prefix': args.prefix,
        'calendar_file': args.calendar if args.calendar != DEFAULT_PODCAST_CAL_FILE else None,
        'templates_dir': args.templates if args.templates != DEFAULT_PODCAST_TEMPLATES else None,
        'html_suffix': args.html_suffix,
        'min_offset': args.min_offset,
        'max_gap': args.max_gap,
        
        # Procesamiento
        'seconds': args.seconds,
        'hconf': args.hconf,
        'mconf': args.mconf,
        'lconf': args.lconf,
        'overlap': int(args.overlap),
        
        # Opciones adicionales
        'audio_tags': args.audio_tags,
        'use_training': False,  # Se activa automáticamente si se proporciona archivo
        
        # Parámetros de Pyannote (desde entorno o argumentos)
        'pyannote_method': args.pyannote_method,
        'pyannote_min_cluster_size': args.pyannote_min_cluster_size,
        'pyannote_threshold': args.pyannote_threshold,
        'pyannote_min_speakers': args.pyannote_min_speakers,
        'pyannote_max_speakers': args.pyannote_max_speakers
    }

def collect_audio_files(fnames: List[str], training_file: str = None) -> List[str]:
    """Recopilar archivos de audio de archivos y directorios"""
    audio_files = []
    
    for fname in fnames:
        if os.path.isdir(fname):
            # Procesar directorio
            logging.info(f"Tratando directorio {fname}")
            for root, dirs, files in os.walk(fname):
                for file in files:
                    if file.endswith(".mp3"):
                        full_path = os.path.join(root, file)
                        if training_file and os.path.abspath(full_path) == os.path.abspath(training_file):
                            logging.info(f"El fichero de entrenamiento {full_path} no se procesa")
                            continue
                        audio_files.append(full_path)
        else:
            # Procesar archivo individual
            if training_file and os.path.abspath(fname) == os.path.abspath(training_file):
                logging.info(f"El fichero de entrenamiento {fname} no se procesa")
                continue
            audio_files.append(fname)
    
    return audio_files

async def download_job_results(client: STTCastRESTClient, session: aiohttp.ClientSession, job_status: Dict[str, Any], original_file: str, args):
    """Descargar resultados del trabajo y guardarlos localmente"""
    if not job_status.get('files'):
        logging.warning(f"No hay archivos de resultado para {original_file}")
        return
    
    # Determinar nombres de archivo locales
    file_base = Path(original_file).stem
    file_dir = Path(original_file).parent
    
    html_suffix = "" if args.html_suffix == "" else "_" + args.html_suffix
    
    for file_info in job_status['files']:
        filename = file_info['filename']
        file_type = file_info['type']
        
        # Determinar nombre local basado en el archivo original
        if file_type == 'html':
            local_path = file_dir / f"{file_base}{html_suffix}.html"
        elif file_type == 'srt':
            local_path = file_dir / f"{file_base}{html_suffix}.srt"
        else:
            local_path = file_dir / filename
        
        try:
            await client.download_result(session, job_status['job_id'], filename, str(local_path))
            logging.info(f"Descargado: {local_path}")
        except Exception as e:
            logging.error(f"Error descargando {filename}: {e}")

async def process_single_file(client: STTCastRESTClient, session: aiohttp.ClientSession, audio_file: str, config: Dict[str, Any], training_file: str, calendar_file: str, args) -> tuple[str, bool, Optional[str]]:
    """Procesar un solo archivo de audio de forma asíncrona"""
    try:
        logging.info(f"Iniciando transcripción: {audio_file}")
        
        # Verificar que el archivo existe
        if not os.path.exists(audio_file):
            error_msg = "Archivo no encontrado"
            logging.error(f"{audio_file}: {error_msg}")
            return audio_file, False, error_msg
        
        # Subir archivo para transcripción
        job_status = await client.transcribe_file(session, audio_file, config, training_file, calendar_file)
        job_id = job_status['job_id']
        
        logging.info(f"Trabajo iniciado: {job_id} para {audio_file}")
        
        # Esperar a que complete
        final_status = await client.wait_for_completion(
            session,
            job_id, 
            poll_interval=args.poll_interval,
            timeout=args.timeout
        )
        
        # Descargar resultados si está habilitado
        if not args.no_download:
            await download_job_results(client, session, final_status, audio_file, args)
        
        logging.info(f"✅ Completado: {audio_file}")
        return audio_file, True, None
        
    except Exception as e:
        error_msg = str(e)
        logging.error(f"❌ Error procesando {audio_file}: {error_msg}")
        return audio_file, False, error_msg

async def process_files_async(args):
    """Procesar archivos usando corrutinas asíncronas"""
    client = STTCastRESTClient(args.server_url, API_SECRET_KEY)
    config = build_transcription_config(args)
    
    # Obtener archivo de entrenamiento si está especificado
    training_file = None
    if hasattr(args, 'whtraining') and args.whtraining and args.whtraining != "training.mp3":
        training_file = os.path.abspath(args.whtraining)
    
    # Recopilar archivos de audio
    audio_files = collect_audio_files(args.fnames, training_file)
    
    if not audio_files:
        logging.error("No se encontraron archivos de audio para procesar")
        return False
    
    logging.info(f"🚀 Iniciando procesamiento asíncrono de {len(audio_files)} archivos")
    
    # Crear sesión HTTP asíncrona
    timeout = aiohttp.ClientTimeout(total=None, connect=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        # Crear una corrutina para cada archivo
        tasks = []
        for audio_file in audio_files:
            task = process_single_file(
                client, session, audio_file, config, 
                training_file, args.calendar, args
            )
            tasks.append(task)
        
        # Ejecutar todas las corrutinas concurrentemente
        results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Procesar resultados
    successful_jobs = []
    failed_jobs = []
    
    for result in results:
        if isinstance(result, Exception):
            failed_jobs.append(("Error de sistema", str(result)))
        else:
            audio_file, success, error = result
            if success:
                successful_jobs.append(audio_file)
            else:
                failed_jobs.append((audio_file, error))
    
    # Resumen final
    logging.info(f"📊 Procesamiento completado:")
    logging.info(f"  ✅ Exitosos: {len(successful_jobs)}")
    logging.info(f"  ❌ Fallidos: {len(failed_jobs)}")
    
    if failed_jobs:
        logging.error("💥 Trabajos fallidos:")
        for audio_file, error in failed_jobs:
            logging.error(f"  {audio_file}: {error}")
    
    if successful_jobs:
        logging.info("🎯 Trabajos exitosos:")
        for audio_file in successful_jobs:
            logging.info(f"  ✅ {audio_file}")
    
    return len(failed_jobs) == 0

async def test_server_connection(server_url: str) -> bool:
    """Verificar que el servidor esté disponible"""
    try:
        timeout = aiohttp.ClientTimeout(total=5)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(f"{server_url.rstrip('/')}/") as response:
                response.raise_for_status()
                server_info = await response.json()
                logging.info(f"Conectado a: {server_info.get('service', 'STTCast Service')} "
                             f"v{server_info.get('version', 'unknown')}")
                return True
        
    except Exception as e:
        logging.error(f"Error conectando al servidor {server_url}: {e}")
        return False

async def main_async():
    """Función principal asíncrona"""
    logcfg(__file__)
    
    args = get_pars()
    
    # Verificar configuración de autenticación
    auth_status = "HMAC habilitada" if API_SECRET_KEY else "sin autenticación"
    
    logging.info(f"STTCast CLI REST Client - Refactorizado v3.0 (Async)")
    logging.info(f"Servidor: {args.server_url}")
    logging.info(f"Autenticación: {auth_status}")
    logging.info(f"Motor: {'Whisper' if args.whisper else 'Vosk'}")
    logging.info(f"Argumentos: {args}")
    
    # Verificar conexión al servidor
    if not await test_server_connection(args.server_url):
        logging.error("No se pudo conectar al servidor STTCast")
        sys.exit(1)
    
    # Procesar archivos
    stime = datetime.datetime.now()
    
    success = await process_files_async(args)
    
    etime = datetime.datetime.now()
    logging.info(f"⏱️ Tiempo total de ejecución: {etime - stime}")
    
    if not success:
        sys.exit(1)
    
    logging.info("🎉 Todos los archivos procesados exitosamente")

def main():
    """Punto de entrada - wrapper para la función asíncrona"""
    asyncio.run(main_async())

if __name__ == "__main__":
    main()