"""
Dependencias compartidas para la aplicación web de Sttcast
"""

from datetime import datetime, timedelta
from typing import Optional, AsyncGenerator
import logging

from fastapi import Depends, HTTPException, status, Request, Cookie
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import select
from jose import JWTError, jwt

from .config import get_settings, Settings
from .models import User, UserRole, Base

# Variables globales para la sesión de base de datos
_async_engine = None
_async_session_maker = None

logger = logging.getLogger(__name__)


async def init_db(settings: Settings):
    """Inicializar conexión a base de datos"""
    global _async_engine, _async_session_maker
    
    # Log the database URL for debugging (with masked password)
    db_url = settings.database_url
    masked_url = db_url.split('@')[0] + '@' + db_url.split('@')[1] if '@' in db_url else db_url
    logger.info(f"Database URL: {masked_url}")
    logger.info(f"DB Host: {settings.db_host}, User: {settings.db_user}")
    
    _async_engine = create_async_engine(
        db_url,
        echo=settings.debug,
        pool_size=10,
        max_overflow=20
    )
    
    _async_session_maker = async_sessionmaker(
        _async_engine,
        class_=AsyncSession,
        expire_on_commit=False
    )
    
    # Crear tablas
    async with _async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    return _async_engine


async def close_db():
    """Cerrar conexión a base de datos"""
    global _async_engine
    if _async_engine:
        await _async_engine.dispose()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Obtener sesión de base de datos"""
    if _async_session_maker is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Base de datos no inicializada"
        )
    
    async with _async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()


def create_access_token(data: dict, settings: Settings, expires_delta: Optional[timedelta] = None) -> str:
    """Crear token JWT de acceso"""
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.session_expire_minutes)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.secret_key, algorithm="HS256")
    
    return encoded_jwt


def decode_access_token(token: str, settings: Settings) -> Optional[dict]:
    """Decodificar y validar token JWT"""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        return payload
    except JWTError:
        return None


async def get_current_user_optional(
    request: Request,
    session_token: Optional[str] = Cookie(default=None, alias="session"),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings)
) -> Optional[User]:
    """Obtener usuario actual (opcional, no lanza excepción)"""
    if not session_token:
        return None
    
    payload = decode_access_token(session_token, settings)
    if payload is None:
        return None
    
    username = payload.get("sub")
    if username is None:
        return None
    
    result = await db.execute(
        select(User).where(User.username == username, User.is_active == True)
    )
    user = result.scalar_one_or_none()
    
    return user


async def get_current_user(
    request: Request,
    session_token: Optional[str] = Cookie(default=None, alias="session"),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings)
) -> User:
    """Obtener usuario actual (requerido)"""
    if not session_token:
        # Redireccionar a login si es una petición de navegador
        if "text/html" in request.headers.get("accept", ""):
            raise HTTPException(
                status_code=status.HTTP_303_SEE_OTHER,
                headers={"Location": "/login"}
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autenticado"
        )
    
    payload = decode_access_token(session_token, settings)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado"
        )
    
    username = payload.get("sub")
    if username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido"
        )
    
    result = await db.execute(
        select(User).where(User.username == username, User.is_active == True)
    )
    user = result.scalar_one_or_none()
    
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario no encontrado o inactivo"
        )
    
    return user


async def get_admin_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """Verificar que el usuario actual es administrador"""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso denegado. Se requiere rol de administrador."
        )
    return current_user


async def ensure_admin_user(db: AsyncSession, settings: Settings):
    """Asegurar que existe el usuario administrador"""
    result = await db.execute(
        select(User).where(User.username == settings.admin_name)
    )
    admin = result.scalar_one_or_none()
    
    if admin is None:
        logging.info(f"Creando usuario administrador: {settings.admin_name}")
        admin = User(
            username=settings.admin_name,
            email=settings.admin_email,
            role=UserRole.ADMIN,
            is_active=True
        )
        admin.set_password(settings.admin_password)
        db.add(admin)
        await db.commit()
        logging.info("Usuario administrador creado exitosamente")
    else:
        logging.info(f"Usuario administrador '{settings.admin_name}' ya existe")
