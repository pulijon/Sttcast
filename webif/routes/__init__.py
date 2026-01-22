"""
Rutas de la aplicación web de Sttcast
"""

from .auth import router as auth_router
from .main import router as main_router
from .users import router as users_router
from .profiles import router as profiles_router
from .transcriptions import router as transcriptions_router
from .config import router as config_router

__all__ = [
    "auth_router",
    "main_router", 
    "users_router",
    "profiles_router",
    "transcriptions_router",
    "config_router"
]
