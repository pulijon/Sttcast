"""
Rutas de autenticación
"""

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..config import get_settings, Settings
from ..dependencies import get_db, get_current_user_optional, create_access_token
from ..models import User

router = APIRouter(tags=["auth"])
templates = Jinja2Templates(directory="webif/templates")


@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    error: Optional[str] = None,
    current_user: Optional[User] = Depends(get_current_user_optional)
):
    """Página de login"""
    # Si ya está autenticado, redirigir al dashboard
    if current_user:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": error}
    )


@router.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings)
):
    """Procesar login"""
    # Buscar usuario
    result = await db.execute(
        select(User).where(User.username == username)
    )
    user = result.scalar_one_or_none()
    
    if user is None or not user.verify_password(password):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Usuario o contraseña incorrectos"},
            status_code=status.HTTP_401_UNAUTHORIZED
        )
    
    if not user.is_active:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Usuario desactivado"},
            status_code=status.HTTP_401_UNAUTHORIZED
        )
    
    # Actualizar último login
    user.last_login = datetime.utcnow()
    await db.commit()
    
    # Crear token
    access_token = create_access_token(
        data={"sub": user.username, "role": user.role.value},
        settings=settings
    )
    
    # Crear respuesta con cookie
    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key="session",
        value=access_token,
        httponly=True,
        max_age=settings.session_expire_minutes * 60,
        samesite="lax"
    )
    
    return response


@router.get("/logout")
async def logout():
    """Cerrar sesión"""
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("session")
    return response
