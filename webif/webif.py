"""
Aplicación principal de la interfaz web de Sttcast
"""

import os
import sys
import logging
import argparse
from pathlib import Path
from contextlib import asynccontextmanager

# Cargar variables de entorno ANTES de importar configuración
from tools.envvars import load_env_vars_from_directory
env_dir = os.path.join(os.path.dirname(__file__), '..')
load_env_vars_from_directory(os.path.join(env_dir, '.env'))

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
import uvicorn

# Añadir el directorio padre al path para imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from webif.config import get_settings, Settings
from webif.dependencies import init_db, close_db, get_db, ensure_admin_user
from webif.routes import (
    auth_router,
    main_router,
    users_router,
    profiles_router,
    transcriptions_router,
    config_router
)

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gestión del ciclo de vida de la aplicación"""
    settings = get_settings()
    
    logger.info("Iniciando Sttcast Web Interface...")
    logger.info(f"Host: {settings.host}:{settings.port}")
    logger.info(f"Base de datos: {settings.db_host}:{settings.db_port}/{settings.db_name}")
    
    # Inicializar base de datos
    try:
        await init_db(settings)
        logger.info("Base de datos inicializada correctamente")
        
        # Asegurar que existe el usuario administrador
        from webif.dependencies import _async_session_maker
        async with _async_session_maker() as db:
            await ensure_admin_user(db, settings)
        
    except Exception as e:
        logger.error(f"Error inicializando base de datos: {e}")
        raise
    
    # Crear directorios necesarios
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.results_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.training_dir).mkdir(parents=True, exist_ok=True)
    logger.info(f"Directorio de uploads: {settings.upload_dir}")
    logger.info(f"Directorio de resultados: {settings.results_dir}")
    logger.info(f"Directorio de training: {settings.training_dir}")
    
    yield
    
    # Cerrar conexiones
    logger.info("Cerrando Sttcast Web Interface...")
    await close_db()


def create_app() -> FastAPI:
    """Crear y configurar la aplicación FastAPI"""
    settings = get_settings()
    
    app = FastAPI(
        title="Sttcast Web Interface",
        description="Interfaz web para gestión de transcripciones de audio",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/api/docs" if settings.debug else None,
        redoc_url="/api/redoc" if settings.debug else None
    )
    
    # Montar archivos estáticos
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    
    # Registrar routers
    app.include_router(auth_router)
    app.include_router(main_router)
    app.include_router(users_router)
    app.include_router(profiles_router)
    app.include_router(transcriptions_router)
    app.include_router(config_router)
    
    # Middleware para manejar errores de autenticación
    @app.exception_handler(401)
    async def unauthorized_handler(request: Request, exc):
        if "text/html" in request.headers.get("accept", ""):
            return RedirectResponse(url="/login", status_code=303)
        return {"detail": "No autenticado"}
    
    return app


# Crear instancia de la aplicación
app = create_app()


def main():
    """Punto de entrada principal"""
    parser = argparse.ArgumentParser(description="Sttcast Web Interface")
    parser.add_argument("--host", type=str, help="Host de escucha")
    parser.add_argument("--port", type=int, help="Puerto de escucha")
    parser.add_argument("--reload", action="store_true", help="Modo desarrollo con recarga automática")
    parser.add_argument("--debug", action="store_true", help="Modo debug")
    
    args = parser.parse_args()
    settings = get_settings()
    
    host = args.host or settings.host
    port = args.port or settings.port
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    uvicorn.run(
        "webif.webif:app",
        host=host,
        port=port,
        reload=args.reload,
        log_level="debug" if args.debug else "info"
    )


if __name__ == "__main__":
    main()
