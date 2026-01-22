"""
Rutas de gestión de perfiles de transcripción
"""

import os
import uuid as uuid_module
from pathlib import Path
from typing import Optional, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_

from ..config import get_settings
from ..dependencies import get_db, get_current_user
from ..models import User, TranscriptionProfile, TranscriptionEngine, UserRole

router = APIRouter(prefix="/profiles", tags=["profiles"])
templates = Jinja2Templates(directory="webif/templates")

# Extensiones permitidas para archivos de entrenamiento
ALLOWED_TRAINING_EXTENSIONS = {'.mp3', '.wav', '.m4a', '.ogg', '.flac'}
# Extensiones permitidas para archivos de calendario
ALLOWED_CALENDAR_EXTENSIONS = {'.txt', '.csv', '.json'}


def save_training_file(file: UploadFile, profile_id: str) -> str:
    """Guarda un archivo de entrenamiento y devuelve el nombre del archivo guardado"""
    settings = get_settings()
    
    # Obtener extensión del archivo original
    original_name = file.filename
    ext = Path(original_name).suffix.lower()
    
    if ext not in ALLOWED_TRAINING_EXTENSIONS:
        raise ValueError(f"Extensión no permitida: {ext}")
    
    # Crear nombre único: profile_id_training.ext
    saved_filename = f"{profile_id}_training{ext}"
    file_path = os.path.join(settings.training_dir, saved_filename)
    
    # Guardar archivo
    with open(file_path, "wb") as f:
        content = file.file.read()
        f.write(content)
    
    return saved_filename


def delete_training_file(filename: str):
    """Elimina un archivo de entrenamiento"""
    settings = get_settings()
    file_path = os.path.join(settings.training_dir, filename)
    if os.path.exists(file_path):
        os.remove(file_path)


def save_calendar_file(file: UploadFile, profile_id: str) -> str:
    """Guarda un archivo de calendario y devuelve el nombre del archivo guardado"""
    settings = get_settings()
    
    # Obtener extensión del archivo original
    original_name = file.filename
    ext = Path(original_name).suffix.lower()
    
    if ext not in ALLOWED_CALENDAR_EXTENSIONS:
        raise ValueError(f"Extensión no permitida: {ext}. Use TXT, CSV o JSON.")
    
    # Crear nombre único: profile_id_calendar.ext
    saved_filename = f"{profile_id}_calendar{ext}"
    file_path = os.path.join(settings.training_dir, saved_filename)
    
    # Guardar archivo
    with open(file_path, "wb") as f:
        content = file.file.read()
        f.write(content)
    
    return saved_filename


def delete_calendar_file(filename: str):
    """Elimina un archivo de calendario"""
    settings = get_settings()
    file_path = os.path.join(settings.training_dir, filename)
    if os.path.exists(file_path):
        os.remove(file_path)


@router.get("", response_class=HTMLResponse)
async def list_profiles(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Listar perfiles del usuario y públicos"""
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
    
    return templates.TemplateResponse(
        "profiles/list.html",
        {
            "request": request,
            "user": current_user,
            "profiles": profiles,
            "engines": TranscriptionEngine
        }
    )


@router.get("/new", response_class=HTMLResponse)
async def new_profile_form(
    request: Request,
    current_user: User = Depends(get_current_user)
):
    """Formulario para crear nuevo perfil"""
    return templates.TemplateResponse(
        "profiles/form.html",
        {
            "request": request,
            "user": current_user,
            "profile": None,
            "engines": TranscriptionEngine,
            "is_new": True
        }
    )


@router.post("/new")
async def create_profile(
    request: Request,
    name: str = Form(...),
    description: Optional[str] = Form(None),
    is_public: bool = Form(False),
    prefix: str = Form("tr"),
    default_engine: str = Form("whisper"),
    whisper_model: str = Form("small"),
    whisper_device: str = Form("cuda"),
    default_language: str = Form("es"),
    seconds: int = Form(15000),
    high_confidence: float = Form(0.95),
    medium_confidence: float = Form(0.7),
    low_confidence: float = Form(0.5),
    overlap: int = Form(2),
    min_offset: int = Form(30),
    max_gap: float = Form(0.8),
    audio_tags: bool = Form(False),
    use_training: bool = Form(False),
    training_file: UploadFile = File(None),
    calendar_file: UploadFile = File(None),
    # Parámetros de Pyannote
    pyannote_method: str = Form("ward"),
    pyannote_min_cluster_size: int = Form(15),
    pyannote_threshold: float = Form(0.7147),
    pyannote_min_speakers: Optional[int] = Form(None),
    pyannote_max_speakers: Optional[int] = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Crear nuevo perfil"""
    # Verificar nombre único para el usuario
    result = await db.execute(
        select(TranscriptionProfile).where(
            TranscriptionProfile.name == name,
            TranscriptionProfile.owner_id == current_user.id
        )
    )
    if result.scalar_one_or_none():
        return templates.TemplateResponse(
            "profiles/form.html",
            {
                "request": request,
                "user": current_user,
                "profile": None,
                "engines": TranscriptionEngine,
                "is_new": True,
                "error": "Ya tienes un perfil con ese nombre"
            },
            status_code=status.HTTP_400_BAD_REQUEST
        )
    
    # Solo admins pueden crear perfiles públicos
    if is_public and current_user.role != UserRole.ADMIN:
        is_public = False
    
    # Generar ID del perfil para nombrar el archivo
    profile_id = uuid_module.uuid4()
    
    # Procesar archivo de entrenamiento si se subió
    saved_training_file = None
    if use_training and training_file and training_file.filename:
        try:
            saved_training_file = save_training_file(training_file, str(profile_id))
        except ValueError as e:
            return templates.TemplateResponse(
                "profiles/form.html",
                {
                    "request": request,
                    "user": current_user,
                    "profile": None,
                    "engines": TranscriptionEngine,
                    "is_new": True,
                    "error": f"Error con el archivo de entrenamiento: {e}"
                },
                status_code=status.HTTP_400_BAD_REQUEST
            )
    
    # Procesar archivo de calendario si se subió
    saved_calendar_file = None
    if calendar_file and calendar_file.filename:
        try:
            saved_calendar_file = save_calendar_file(calendar_file, str(profile_id))
        except ValueError as e:
            return templates.TemplateResponse(
                "profiles/form.html",
                {
                    "request": request,
                    "user": current_user,
                    "profile": None,
                    "engines": TranscriptionEngine,
                    "is_new": True,
                    "error": f"Error con el archivo de calendario: {e}"
                },
                status_code=status.HTTP_400_BAD_REQUEST
            )
    
    profile = TranscriptionProfile(
        id=profile_id,
        name=name,
        description=description,
        owner_id=current_user.id,
        is_public=is_public,
        prefix=prefix,
        default_engine=TranscriptionEngine(default_engine),
        whisper_model=whisper_model,
        whisper_device=whisper_device,
        default_language=default_language,
        languages=[default_language],
        seconds=seconds,
        high_confidence=high_confidence,
        medium_confidence=medium_confidence,
        low_confidence=low_confidence,
        overlap=overlap,
        min_offset=min_offset,
        max_gap=max_gap,
        audio_tags=audio_tags,
        use_training=use_training,
        training_file=saved_training_file,
        calendar_file=saved_calendar_file,
        # Parámetros de Pyannote
        pyannote_method=pyannote_method,
        pyannote_min_cluster_size=pyannote_min_cluster_size,
        pyannote_threshold=pyannote_threshold,
        pyannote_min_speakers=pyannote_min_speakers,
        pyannote_max_speakers=pyannote_max_speakers
    )
    
    db.add(profile)
    await db.commit()
    
    return RedirectResponse(url="/profiles", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{profile_id}", response_class=HTMLResponse)
async def edit_profile_form(
    request: Request,
    profile_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Formulario para editar perfil"""
    result = await db.execute(
        select(TranscriptionProfile).where(TranscriptionProfile.id == profile_id)
    )
    profile = result.scalar_one_or_none()
    
    if not profile:
        raise HTTPException(status_code=404, detail="Perfil no encontrado")
    
    # Solo el propietario o admin puede editar
    if profile.owner_id != current_user.id and current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="No tienes permiso para editar este perfil")
    
    return templates.TemplateResponse(
        "profiles/form.html",
        {
            "request": request,
            "user": current_user,
            "profile": profile,
            "engines": TranscriptionEngine,
            "is_new": False
        }
    )


@router.post("/{profile_id}")
async def update_profile(
    request: Request,
    profile_id: UUID,
    name: str = Form(...),
    description: Optional[str] = Form(None),
    is_public: bool = Form(False),
    prefix: str = Form("tr"),
    default_engine: str = Form("whisper"),
    whisper_model: str = Form("small"),
    whisper_device: str = Form("cuda"),
    default_language: str = Form("es"),
    seconds: int = Form(15000),
    high_confidence: float = Form(0.95),
    medium_confidence: float = Form(0.7),
    low_confidence: float = Form(0.5),
    overlap: int = Form(2),
    min_offset: int = Form(30),
    max_gap: float = Form(0.8),
    audio_tags: bool = Form(False),
    use_training: bool = Form(False),
    training_file: UploadFile = File(None),
    remove_training_file: bool = Form(False),
    calendar_file: UploadFile = File(None),
    remove_calendar_file: bool = Form(False),
    # Parámetros de Pyannote
    pyannote_method: str = Form("ward"),
    pyannote_min_cluster_size: int = Form(15),
    pyannote_threshold: float = Form(0.7147),
    pyannote_min_speakers: Optional[int] = Form(None),
    pyannote_max_speakers: Optional[int] = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Actualizar perfil"""
    result = await db.execute(
        select(TranscriptionProfile).where(TranscriptionProfile.id == profile_id)
    )
    profile = result.scalar_one_or_none()
    
    if not profile:
        raise HTTPException(status_code=404, detail="Perfil no encontrado")
    
    # Solo el propietario o admin puede editar
    if profile.owner_id != current_user.id and current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="No tienes permiso para editar este perfil")
    
    # Solo admins pueden hacer perfiles públicos
    if is_public and current_user.role != UserRole.ADMIN:
        is_public = profile.is_public  # Mantener valor anterior
    
    # Manejar archivo de entrenamiento
    if remove_training_file and profile.training_file:
        # Eliminar archivo existente
        delete_training_file(profile.training_file)
        profile.training_file = None
    elif training_file and training_file.filename:
        # Subir nuevo archivo (eliminar anterior si existe)
        if profile.training_file:
            delete_training_file(profile.training_file)
        try:
            profile.training_file = save_training_file(training_file, str(profile_id))
        except ValueError as e:
            return templates.TemplateResponse(
                "profiles/form.html",
                {
                    "request": request,
                    "user": current_user,
                    "profile": profile,
                    "engines": TranscriptionEngine,
                    "is_new": False,
                    "error": f"Error con el archivo de entrenamiento: {e}"
                },
                status_code=status.HTTP_400_BAD_REQUEST
            )
    # Si no se sube nuevo ni se elimina, mantener el actual
    
    # Manejar archivo de calendario
    if remove_calendar_file and profile.calendar_file:
        # Eliminar archivo existente
        delete_calendar_file(profile.calendar_file)
        profile.calendar_file = None
    elif calendar_file and calendar_file.filename:
        # Subir nuevo archivo (eliminar anterior si existe)
        if profile.calendar_file:
            delete_calendar_file(profile.calendar_file)
        try:
            profile.calendar_file = save_calendar_file(calendar_file, str(profile_id))
        except ValueError as e:
            return templates.TemplateResponse(
                "profiles/form.html",
                {
                    "request": request,
                    "user": current_user,
                    "profile": profile,
                    "engines": TranscriptionEngine,
                    "is_new": False,
                    "error": f"Error con el archivo de calendario: {e}"
                },
                status_code=status.HTTP_400_BAD_REQUEST
            )
    # Si no se sube nuevo ni se elimina, mantener el actual
    
    # Actualizar campos
    profile.name = name
    profile.description = description
    profile.is_public = is_public
    profile.prefix = prefix
    profile.default_engine = TranscriptionEngine(default_engine)
    profile.whisper_model = whisper_model
    profile.whisper_device = whisper_device
    profile.default_language = default_language
    profile.languages = [default_language]
    profile.seconds = seconds
    profile.high_confidence = high_confidence
    profile.medium_confidence = medium_confidence
    profile.low_confidence = low_confidence
    profile.overlap = overlap
    profile.min_offset = min_offset
    profile.max_gap = max_gap
    profile.audio_tags = audio_tags
    profile.use_training = use_training
    # training_file ya se maneja arriba
    # Parámetros de Pyannote
    profile.pyannote_method = pyannote_method
    profile.pyannote_min_cluster_size = pyannote_min_cluster_size
    profile.pyannote_threshold = pyannote_threshold
    profile.pyannote_min_speakers = pyannote_min_speakers
    profile.pyannote_max_speakers = pyannote_max_speakers
    
    await db.commit()
    
    return RedirectResponse(url="/profiles", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{profile_id}/delete")
async def delete_profile(
    profile_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Eliminar perfil"""
    result = await db.execute(
        select(TranscriptionProfile).where(TranscriptionProfile.id == profile_id)
    )
    profile = result.scalar_one_or_none()
    
    if not profile:
        raise HTTPException(status_code=404, detail="Perfil no encontrado")
    
    # Solo el propietario o admin puede eliminar
    if profile.owner_id != current_user.id and current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="No tienes permiso para eliminar este perfil")
    
    # Eliminar archivo de entrenamiento si existe
    if profile.training_file:
        delete_training_file(profile.training_file)
    
    # Eliminar archivo de calendario si existe
    if profile.calendar_file:
        delete_calendar_file(profile.calendar_file)
    
    await db.delete(profile)
    await db.commit()
    
    return RedirectResponse(url="/profiles", status_code=status.HTTP_303_SEE_OTHER)
