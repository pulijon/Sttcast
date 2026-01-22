"""
Rutas de configuración del sistema
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..dependencies import get_db, get_admin_user
from ..models import User, SystemConfig

router = APIRouter(prefix="/config", tags=["config"])
templates = Jinja2Templates(directory="webif/templates")


# Claves de configuración conocidas
CONFIG_KEYS = {
    "trans_server_host": {
        "label": "Host del servidor de transcripción",
        "description": "Dirección IP o hostname del servidor de transcripción",
        "default": "127.0.0.1",
        "secret": False
    },
    "trans_server_port": {
        "label": "Puerto del servidor de transcripción",
        "description": "Puerto del servidor de transcripción",
        "default": "8000",
        "secret": False
    },
    "max_upload_size_mb": {
        "label": "Tamaño máximo de archivo (MB)",
        "description": "Tamaño máximo permitido para archivos de audio",
        "default": "500",
        "secret": False
    },
    "default_whisper_model": {
        "label": "Modelo Whisper por defecto",
        "description": "Modelo de Whisper a usar por defecto (tiny, base, small, medium, large)",
        "default": "small",
        "secret": False
    },
    "default_language": {
        "label": "Idioma por defecto",
        "description": "Código de idioma por defecto para transcripciones",
        "default": "es",
        "secret": False
    }
}


@router.get("", response_class=HTMLResponse)
async def config_page(
    request: Request,
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Página de configuración"""
    # Obtener valores actuales de la base de datos
    result = await db.execute(select(SystemConfig))
    db_configs = {c.key: c for c in result.scalars().all()}
    
    # Combinar con configuración conocida
    configs = []
    for key, info in CONFIG_KEYS.items():
        db_config = db_configs.get(key)
        configs.append({
            "key": key,
            "label": info["label"],
            "description": info["description"],
            "value": db_config.value if db_config else info["default"],
            "is_secret": info["secret"]
        })
    
    return templates.TemplateResponse(
        "config.html",
        {
            "request": request,
            "user": admin,
            "configs": configs
        }
    )


@router.post("")
async def update_config(
    request: Request,
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Actualizar configuración"""
    form_data = await request.form()
    
    for key in CONFIG_KEYS:
        value = form_data.get(key, "")
        
        # Buscar configuración existente
        result = await db.execute(
            select(SystemConfig).where(SystemConfig.key == key)
        )
        config = result.scalar_one_or_none()
        
        if config:
            config.value = value
        else:
            config = SystemConfig(
                key=key,
                value=value,
                description=CONFIG_KEYS[key]["description"],
                is_secret=CONFIG_KEYS[key]["secret"]
            )
            db.add(config)
    
    await db.commit()
    
    return RedirectResponse(url="/config?saved=1", status_code=status.HTTP_303_SEE_OTHER)


async def get_config_value(db: AsyncSession, key: str) -> Optional[str]:
    """Obtener valor de configuración"""
    result = await db.execute(
        select(SystemConfig).where(SystemConfig.key == key)
    )
    config = result.scalar_one_or_none()
    
    if config:
        return config.value
    
    # Retornar valor por defecto si existe
    if key in CONFIG_KEYS:
        return CONFIG_KEYS[key]["default"]
    
    return None
