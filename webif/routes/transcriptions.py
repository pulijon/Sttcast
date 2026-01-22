"""
Rutas de gestión de transcripciones
"""

import os
import uuid
import asyncio
import logging
import json
from datetime import datetime
from typing import Optional, List
from uuid import UUID
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status, Request, Form, UploadFile, File, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_

from ..config import get_settings, Settings
from ..dependencies import get_db, get_current_user
from ..models import (
    User, TranscriptionJob, TranscriptionProfile, 
    TranscriptionStatus, TranscriptionEngine, UserRole
)
from ..trans_client import TranscriptionClient, TranscriptionConfig
from ..timezone_utils import convert_to_user_timezone

router = APIRouter(prefix="/transcriptions", tags=["transcriptions"])
templates = Jinja2Templates(directory="webif/templates")

# Registrar filtro personalizado para convertir fechas a zona horaria del usuario
def format_datetime_user(dt, user_timezone="UTC"):
    """Filtro para formatear datetime según la zona horaria del usuario"""
    if not dt:
        return "-"
    converted = convert_to_user_timezone(dt, user_timezone)
    return converted.strftime("%d/%m/%Y %H:%M") if converted else "-"

templates.env.filters["format_datetime_user"] = format_datetime_user

# Registrar filtro Jinja2 personalizado para convertir fechas a zona horaria del usuario
def format_datetime_for_user(dt, user_timezone="UTC"):
    """Filtro para formatear datetime según la zona horaria del usuario"""
    if not dt:
        return "-"
    converted = convert_to_user_timezone(dt, user_timezone)
    return converted.strftime("%d/%m/%Y %H:%M") if converted else "-"

templates.env.filters["format_datetime_user"] = format_datetime_for_user


async def check_job_status_task(
    job_id: UUID,
    settings: Settings
):
    """Tarea en background para verificar estado del trabajo"""
    from ..dependencies import _async_session_maker
    
    client = TranscriptionClient(settings)
    
    async with _async_session_maker() as db:
        result = await db.execute(
            select(TranscriptionJob).where(TranscriptionJob.id == job_id)
        )
        job = result.scalar_one_or_none()
        
        if not job or not job.remote_job_id:
            return
        
        try:
            # Polling del estado
            max_attempts = 3600  # 1 hora máximo
            attempt = 0
            
            while attempt < max_attempts:
                status_response = await client.get_job_status(job.remote_job_id)
                remote_status = status_response.get("status", "unknown")
                
                if remote_status == "running":
                    job.status = TranscriptionStatus.RUNNING
                    job.progress = status_response.get("progress", 0)
                    job.message = status_response.get("message", "Transcribiendo...")
                    if not job.started_at:
                        job.started_at = datetime.utcnow()
                
                elif remote_status == "completed":
                    job.status = TranscriptionStatus.COMPLETED
                    job.progress = 100
                    job.completed_at = datetime.utcnow()
                    job.message = "Transcripción completada"
                    
                    # Descargar archivos de resultado
                    try:
                        files = await client.get_job_files(job.remote_job_id)
                        results_dir = Path(settings.results_dir) / str(job.id)
                        results_dir.mkdir(parents=True, exist_ok=True)
                        
                        for file_info in files:
                            filename = file_info.get("filename", "")
                            if filename.endswith(".html"):
                                dest = results_dir / filename
                                await client.download_file(job.remote_job_id, filename, dest)
                                job.html_file = str(dest)
                            elif filename.endswith(".srt"):
                                dest = results_dir / filename
                                await client.download_file(job.remote_job_id, filename, dest)
                                job.srt_file = str(dest)
                    except Exception as e:
                        logging.error(f"Error descargando archivos: {e}")
                    
                    await db.commit()
                    break
                
                elif remote_status == "failed":
                    job.status = TranscriptionStatus.FAILED
                    job.error = status_response.get("error", "Error desconocido")
                    job.completed_at = datetime.utcnow()
                    await db.commit()
                    break
                
                await db.commit()
                await asyncio.sleep(5)  # Esperar 5 segundos entre polls
                attempt += 1
                
        except Exception as e:
            logging.error(f"Error verificando estado del trabajo: {e}")
            job.status = TranscriptionStatus.FAILED
            job.error = str(e)
            await db.commit()


@router.get("", response_class=HTMLResponse)
async def list_transcriptions(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Listar transcripciones del usuario"""
    result = await db.execute(
        select(TranscriptionJob)
        .where(TranscriptionJob.user_id == current_user.id)
        .order_by(TranscriptionJob.created_at.desc())
    )
    transcriptions = result.scalars().all()
    
    # Obtener perfiles disponibles
    result = await db.execute(
        select(TranscriptionProfile)
        .where(
            or_(
                TranscriptionProfile.owner_id == current_user.id,
                TranscriptionProfile.is_public == True
            )
        )
        .order_by(TranscriptionProfile.name)
    )
    profiles = result.scalars().all()
    
    # Crear diccionario JSON de perfiles para JavaScript
    profiles_json = {}
    for profile in profiles:
        profiles_json[str(profile.id)] = {
            "name": profile.name,
            "default_engine": profile.default_engine.value if profile.default_engine else "whisper",
            "default_language": profile.default_language or "es",
            "audio_tags": profile.audio_tags,
            "training_file": profile.training_file
        }
    
    profiles_json_str = json.dumps(profiles_json)
    
    return templates.TemplateResponse(
        "transcriptions/list.html",
        {
            "request": request,
            "user": current_user,
            "transcriptions": transcriptions,
            "profiles": profiles,
            "profiles_json": profiles_json_str,
            "engines": TranscriptionEngine,
            "statuses": TranscriptionStatus,
            "user_timezone": current_user.timezone
        }
    )


@router.post("/upload")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    profile_id: Optional[str] = Form(None),
    engine: str = Form("whisper"),
    language: str = Form("es"),
    audio_tags: str = Form("false"),
    training_option: str = Form("none"),
    training_file: Optional[UploadFile] = File(None),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings)
):
    """Subir archivo para transcripción"""
    # Validar tipo de archivo
    if not file.filename.lower().endswith(('.mp3', '.wav', '.m4a', '.ogg', '.flac')):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Formato de archivo no soportado. Use MP3, WAV, M4A, OGG o FLAC."
        )
    
    # Crear directorio de uploads
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    
    # Generar nombre único
    job_uuid = uuid.uuid4()
    stored_filename = f"{job_uuid}_{file.filename}"
    file_path = upload_dir / stored_filename
    
    # Guardar archivo
    content = await file.read()
    file_path.write_bytes(content)
    
    # Obtener perfil si se especificó
    profile = None
    if profile_id and profile_id != "none":
        result = await db.execute(
            select(TranscriptionProfile).where(
                TranscriptionProfile.id == UUID(profile_id)
            )
        )
        profile = result.scalar_one_or_none()
    
    # Manejar fichero de training
    training_file_path = None
    if training_option == "profile" and profile and profile.training_file:
        # Usar el training del perfil
        training_file_path = str(Path(settings.training_dir) / profile.training_file)
    elif training_option == "custom" and training_file and training_file.filename:
        # Guardar el training file personalizado
        if not training_file.filename.lower().endswith(('.mp3', '.wav', '.m4a', '.ogg', '.flac')):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Formato de fichero de entrenamiento no soportado. Use MP3, WAV, M4A, OGG o FLAC."
            )
        
        training_dir = Path(settings.training_dir)
        training_dir.mkdir(parents=True, exist_ok=True)
        
        training_stored_filename = f"{job_uuid}_training_{training_file.filename}"
        training_file_path = str(training_dir / training_stored_filename)
        
        training_content = await training_file.read()
        Path(training_file_path).write_bytes(training_content)
    
    # Crear trabajo de transcripción
    job = TranscriptionJob(
        id=job_uuid,
        user_id=current_user.id,
        profile_id=profile.id if profile else None,
        original_filename=file.filename,
        stored_filename=stored_filename,
        file_size=len(content),
        status=TranscriptionStatus.PENDING,
        engine=TranscriptionEngine(engine),
        language=language
    )
    
    # Convertir audio_tags de string a boolean
    audio_tags_bool = audio_tags.lower() == 'true'
    
    # Guardar snapshot de configuración
    if profile:
        # Construir ruta completa del calendario si existe
        calendar_file_path = None
        if profile.calendar_file:
            calendar_file_path = str(Path(settings.training_dir) / profile.calendar_file)
        
        job.config_snapshot = {
            "prefix": profile.prefix,
            "whisper_model": profile.whisper_model,
            "whisper_device": profile.whisper_device,
            "seconds": profile.seconds,
            "high_confidence": profile.high_confidence,
            "medium_confidence": profile.medium_confidence,
            "low_confidence": profile.low_confidence,
            "overlap": profile.overlap,
            "min_offset": profile.min_offset,
            "max_gap": profile.max_gap,
            "audio_tags": audio_tags_bool,  # El valor del checkbox del usuario tiene prioridad
            "use_training": profile.use_training,
            "training_file": training_file_path,
            "calendar_file": calendar_file_path,
            "pyannote_method": profile.pyannote_method,
            "pyannote_min_cluster_size": profile.pyannote_min_cluster_size,
            "pyannote_threshold": profile.pyannote_threshold,
            "pyannote_min_speakers": profile.pyannote_min_speakers,
            "pyannote_max_speakers": profile.pyannote_max_speakers
        }
    else:
        # Sin perfil - usar valores manuales
        job.config_snapshot = {
            "audio_tags": audio_tags_bool,
            "training_file": training_file_path,
            "calendar_file": None
        }
    
    db.add(job)
    await db.commit()
    
    return JSONResponse({
        "id": str(job.id),
        "filename": file.filename,
        "status": job.status.value,
        "engine": engine,
        "language": language,
        "audio_tags": audio_tags_bool,
        "message": "Archivo subido correctamente"
    })


@router.post("/{job_id}/start")
async def start_transcription(
    job_id: UUID,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings)
):
    """Iniciar transcripción de un trabajo"""
    result = await db.execute(
        select(TranscriptionJob).where(
            TranscriptionJob.id == job_id,
            TranscriptionJob.user_id == current_user.id
        )
    )
    job = result.scalar_one_or_none()
    
    if not job:
        raise HTTPException(status_code=404, detail="Trabajo no encontrado")
    
    if job.status not in [TranscriptionStatus.PENDING, TranscriptionStatus.FAILED]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El trabajo ya está en proceso o completado"
        )
    
    # Preparar configuración para el servidor de transcripción
    config = TranscriptionConfig(
        whisper=(job.engine == TranscriptionEngine.WHISPER),
        whlanguage=job.language
    )
    
    # Aplicar configuración del perfil si existe
    if job.config_snapshot:
        config.prefix = job.config_snapshot.get("prefix", "tr")
        config.whmodel = job.config_snapshot.get("whisper_model", "small")
        config.whdevice = job.config_snapshot.get("whisper_device", "cuda")
        config.seconds = job.config_snapshot.get("seconds", 15000)
        config.hconf = job.config_snapshot.get("high_confidence", 0.95)
        config.mconf = job.config_snapshot.get("medium_confidence", 0.7)
        config.lconf = job.config_snapshot.get("low_confidence", 0.5)
        config.overlap = job.config_snapshot.get("overlap", 2)
        config.min_offset = job.config_snapshot.get("min_offset", 30)
        config.max_gap = job.config_snapshot.get("max_gap", 0.8)
        config.audio_tags = job.config_snapshot.get("audio_tags", False)
        # Training solo es válido para Whisper
        if config.whisper:
            config.use_training = job.config_snapshot.get("use_training", False)
            config.training_file = job.config_snapshot.get("training_file")
        else:
            config.use_training = False
            config.training_file = None
        config.calendar_file = job.config_snapshot.get("calendar_file")
        config.pyannote_method = job.config_snapshot.get("pyannote_method", "ward")
        config.pyannote_min_cluster_size = job.config_snapshot.get("pyannote_min_cluster_size", 15)
        config.pyannote_threshold = job.config_snapshot.get("pyannote_threshold", 0.7147)
        config.pyannote_min_speakers = job.config_snapshot.get("pyannote_min_speakers")
        config.pyannote_max_speakers = job.config_snapshot.get("pyannote_max_speakers")
    
    # Generar html_suffix basado en motor, audio_tags e idioma
    # Formato: {motor}_{audio_si_aplica}_{idioma}
    # Ejemplos: whisper_audio_es, vosk_es, whisper_en
    engine_name = "whisper" if config.whisper else "vosk"
    audio_part = "audio_" if config.audio_tags else ""
    config.html_suffix = f"{engine_name}_{audio_part}{job.language}"
    
    try:
        # Enviar al servidor de transcripción
        client = TranscriptionClient(settings)
        file_path = Path(settings.upload_dir) / job.stored_filename
        
        # Preparar archivos opcionales de training y calendar
        training_file_path = None
        calendar_file_path = None
        
        if job.config_snapshot:
            # Training solo aplica para Whisper
            if config.whisper:
                training_path_str = job.config_snapshot.get("training_file")
                if training_path_str:
                    training_file_path = Path(training_path_str)
            
            calendar_path_str = job.config_snapshot.get("calendar_file")
            if calendar_path_str:
                calendar_file_path = Path(calendar_path_str)
        
        job.status = TranscriptionStatus.QUEUED
        job.message = "Enviando al servidor de transcripción..."
        await db.commit()
        
        response = await client.submit_transcription(
            file_path, 
            config,
            training_file_path=training_file_path,
            calendar_file_path=calendar_file_path
        )
        
        job.remote_job_id = response.get("job_id")
        job.status = TranscriptionStatus.QUEUED
        job.message = "En cola de transcripción"
        await db.commit()
        
        # Iniciar tarea de polling en background
        background_tasks.add_task(check_job_status_task, job.id, settings)
        
        return JSONResponse({
            "id": str(job.id),
            "status": job.status.value,
            "message": "Transcripción iniciada"
        })
        
    except Exception as e:
        logging.error(f"Error iniciando transcripción: {e}")
        job.status = TranscriptionStatus.FAILED
        job.error = str(e)
        await db.commit()
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al iniciar transcripción: {str(e)}"
        )


@router.get("/{job_id}/status")
async def get_job_status(
    job_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Obtener estado de un trabajo"""
    result = await db.execute(
        select(TranscriptionJob).where(
            TranscriptionJob.id == job_id,
            TranscriptionJob.user_id == current_user.id
        )
    )
    job = result.scalar_one_or_none()
    
    if not job:
        raise HTTPException(status_code=404, detail="Trabajo no encontrado")
    
    return JSONResponse({
        "id": str(job.id),
        "status": job.status.value,
        "progress": job.progress,
        "message": job.message,
        "error": job.error,
        "has_html": bool(job.html_file),
        "has_srt": bool(job.srt_file)
    })


@router.get("/{job_id}/download/{file_type}")
async def download_result(
    job_id: UUID,
    file_type: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Descargar archivo de resultado"""
    result = await db.execute(
        select(TranscriptionJob).where(
            TranscriptionJob.id == job_id,
            TranscriptionJob.user_id == current_user.id
        )
    )
    job = result.scalar_one_or_none()
    
    if not job:
        raise HTTPException(status_code=404, detail="Trabajo no encontrado")
    
    if job.status != TranscriptionStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La transcripción no está completada"
        )
    
    if file_type == "html" and job.html_file:
        file_path = Path(job.html_file)
        if file_path.exists():
            return FileResponse(
                file_path,
                media_type="text/html",
                filename=file_path.name
            )
    elif file_type == "srt" and job.srt_file:
        file_path = Path(job.srt_file)
        if file_path.exists():
            return FileResponse(
                file_path,
                media_type="text/plain",
                filename=file_path.name
            )
    
    raise HTTPException(status_code=404, detail="Archivo no encontrado")


@router.post("/{job_id}/delete")
async def delete_job(
    job_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings)
):
    """Eliminar trabajo y archivos asociados"""
    result = await db.execute(
        select(TranscriptionJob).where(
            TranscriptionJob.id == job_id,
            TranscriptionJob.user_id == current_user.id
        )
    )
    job = result.scalar_one_or_none()
    
    if not job:
        raise HTTPException(status_code=404, detail="Trabajo no encontrado")
    
    # Eliminar archivo subido
    upload_path = Path(settings.upload_dir) / job.stored_filename
    if upload_path.exists():
        upload_path.unlink()
    
    # Eliminar archivos de resultado
    if job.html_file:
        html_path = Path(job.html_file)
        if html_path.exists():
            html_path.unlink()
    
    if job.srt_file:
        srt_path = Path(job.srt_file)
        if srt_path.exists():
            srt_path.unlink()
    
    # Eliminar directorio de resultados si está vacío
    results_dir = Path(settings.results_dir) / str(job.id)
    if results_dir.exists() and not any(results_dir.iterdir()):
        results_dir.rmdir()
    
    await db.delete(job)
    await db.commit()
    
    # Redirigir a la lista de transcripciones
    return RedirectResponse(url="/transcriptions", status_code=303)
