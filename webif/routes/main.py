"""
Rutas principales y dashboard
"""

from typing import Optional

from fastapi import APIRouter, Depends, Request, Form, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from ..dependencies import get_db, get_current_user
from ..models import User, TranscriptionJob, TranscriptionProfile, TranscriptionStatus
from ..timezone_utils import convert_to_user_timezone

router = APIRouter(tags=["main"])
templates = Jinja2Templates(directory="webif/templates")

# Registrar filtro personalizado para convertir fechas a zona horaria del usuario
def format_datetime_user(dt, user_timezone="UTC"):
    """Filtro para formatear datetime según la zona horaria del usuario"""
    if not dt:
        return "-"
    converted = convert_to_user_timezone(dt, user_timezone)
    return converted.strftime("%d/%m/%Y %H:%M") if converted else "-"

templates.env.filters["format_datetime_user"] = format_datetime_user


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Dashboard principal"""
    # Obtener estadísticas
    
    # Total de transcripciones del usuario
    result = await db.execute(
        select(func.count(TranscriptionJob.id)).where(
            TranscriptionJob.user_id == current_user.id
        )
    )
    total_transcriptions = result.scalar() or 0
    
    # Transcripciones pendientes/en progreso
    result = await db.execute(
        select(func.count(TranscriptionJob.id)).where(
            TranscriptionJob.user_id == current_user.id,
            TranscriptionJob.status.in_([
                TranscriptionStatus.PENDING,
                TranscriptionStatus.UPLOADING,
                TranscriptionStatus.QUEUED,
                TranscriptionStatus.RUNNING
            ])
        )
    )
    active_transcriptions = result.scalar() or 0
    
    # Transcripciones completadas
    result = await db.execute(
        select(func.count(TranscriptionJob.id)).where(
            TranscriptionJob.user_id == current_user.id,
            TranscriptionJob.status == TranscriptionStatus.COMPLETED
        )
    )
    completed_transcriptions = result.scalar() or 0
    
    # Perfiles del usuario
    result = await db.execute(
        select(func.count(TranscriptionProfile.id)).where(
            TranscriptionProfile.owner_id == current_user.id
        )
    )
    total_profiles = result.scalar() or 0
    
    # Transcripciones recientes
    result = await db.execute(
        select(TranscriptionJob)
        .where(TranscriptionJob.user_id == current_user.id)
        .order_by(TranscriptionJob.created_at.desc())
        .limit(5)
    )
    recent_transcriptions = result.scalars().all()
    
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": current_user,
            "stats": {
                "total_transcriptions": total_transcriptions,
                "active_transcriptions": active_transcriptions,
                "completed_transcriptions": completed_transcriptions,
                "total_profiles": total_profiles
            },
            "recent_transcriptions": recent_transcriptions
        }
    )


@router.get("/profile", response_class=HTMLResponse)
async def user_profile(
    request: Request,
    current_user: User = Depends(get_current_user)
):
    """Ver perfil del usuario"""
    return templates.TemplateResponse(
        "profile.html",
        {
            "request": request,
            "user": current_user
        }
    )


@router.post("/profile")
async def update_user_profile(
    request: Request,
    timezone: str = Form("UTC"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Actualizar perfil del usuario"""
    # Actualizar zona horaria
    current_user.timezone = timezone
    await db.commit()
    
    return RedirectResponse(url="/profile", status_code=status.HTTP_303_SEE_OTHER)
