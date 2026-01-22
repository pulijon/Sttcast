"""
Rutas de gestión de usuarios (solo administradores)
"""

from typing import Optional, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from pydantic import BaseModel, EmailStr

from ..dependencies import get_db, get_admin_user
from ..models import User, UserRole

router = APIRouter(prefix="/users", tags=["users"])
templates = Jinja2Templates(directory="webif/templates")


class UserCreate(BaseModel):
    """Modelo para crear usuario"""
    username: str
    password: str
    email: Optional[str] = None
    role: UserRole = UserRole.USER


class UserUpdate(BaseModel):
    """Modelo para actualizar usuario"""
    email: Optional[str] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None


@router.get("", response_class=HTMLResponse)
async def list_users(
    request: Request,
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Listar todos los usuarios"""
    result = await db.execute(
        select(User).order_by(User.created_at.desc())
    )
    users = result.scalars().all()
    
    return templates.TemplateResponse(
        "users/list.html",
        {
            "request": request,
            "user": admin,
            "users": users,
            "roles": UserRole
        }
    )


@router.get("/new", response_class=HTMLResponse)
async def new_user_form(
    request: Request,
    admin: User = Depends(get_admin_user)
):
    """Formulario para crear nuevo usuario"""
    return templates.TemplateResponse(
        "users/form.html",
        {
            "request": request,
            "user": admin,
            "form_user": None,
            "roles": UserRole,
            "is_new": True
        }
    )


@router.post("/new")
async def create_user(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    email: Optional[str] = Form(None),
    role: str = Form("user"),
    timezone: str = Form("UTC"),
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Crear nuevo usuario"""
    # Verificar si el usuario ya existe
    result = await db.execute(
        select(User).where(User.username == username)
    )
    if result.scalar_one_or_none():
        return templates.TemplateResponse(
            "users/form.html",
            {
                "request": request,
                "user": admin,
                "form_user": None,
                "roles": UserRole,
                "is_new": True,
                "error": "El nombre de usuario ya existe"
            },
            status_code=status.HTTP_400_BAD_REQUEST
        )
    
    # Crear usuario
    new_user = User(
        username=username,
        email=email if email else None,
        role=UserRole(role),
        timezone=timezone,
        is_active=True
    )
    new_user.set_password(password)
    
    db.add(new_user)
    await db.commit()
    
    return RedirectResponse(url="/users", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{user_id}", response_class=HTMLResponse)
async def edit_user_form(
    request: Request,
    user_id: UUID,
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Formulario para editar usuario"""
    result = await db.execute(
        select(User).where(User.id == user_id)
    )
    form_user = result.scalar_one_or_none()
    
    if not form_user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    return templates.TemplateResponse(
        "users/form.html",
        {
            "request": request,
            "user": admin,
            "form_user": form_user,
            "roles": UserRole,
            "is_new": False
        }
    )


@router.post("/{user_id}")
async def update_user(
    request: Request,
    user_id: UUID,
    email: Optional[str] = Form(None),
    role: str = Form(...),
    timezone: str = Form("UTC"),
    is_active: bool = Form(True),
    password: Optional[str] = Form(None),
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Actualizar usuario"""
    result = await db.execute(
        select(User).where(User.id == user_id)
    )
    form_user = result.scalar_one_or_none()
    
    if not form_user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    # No permitir desactivar o cambiar rol del propio admin
    if form_user.id == admin.id:
        if not is_active:
            return templates.TemplateResponse(
                "users/form.html",
                {
                    "request": request,
                    "user": admin,
                    "form_user": form_user,
                    "roles": UserRole,
                    "is_new": False,
                    "error": "No puedes desactivar tu propia cuenta"
                },
                status_code=status.HTTP_400_BAD_REQUEST
            )
    
    # Actualizar campos
    form_user.email = email if email else None
    form_user.role = UserRole(role)
    form_user.timezone = timezone
    form_user.is_active = is_active
    
    if password and password.strip():
        form_user.set_password(password)
    
    await db.commit()
    
    return RedirectResponse(url="/users", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{user_id}/delete")
async def delete_user(
    user_id: UUID,
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Eliminar usuario"""
    if user_id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No puedes eliminar tu propia cuenta"
        )
    
    result = await db.execute(
        select(User).where(User.id == user_id)
    )
    user_to_delete = result.scalar_one_or_none()
    
    if not user_to_delete:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    await db.delete(user_to_delete)
    await db.commit()
    
    return RedirectResponse(url="/users", status_code=status.HTTP_303_SEE_OTHER)
