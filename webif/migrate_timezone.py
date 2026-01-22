#!/usr/bin/env python3
"""
Script de migración para agregar el campo timezone a la tabla webif_users
Se puede ejecutar manualmente o se ejecutará automáticamente cuando se reinicie el servidor.
"""

import asyncio
import sys
import os
from pathlib import Path

# Cargar variables de entorno ANTES de importar configuración
from tools.envvars import load_env_vars_from_directory
env_dir = os.path.join(os.path.dirname(__file__), '..')
load_env_vars_from_directory(os.path.join(env_dir, '.env'))

# Añadir el directorio padre al path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text, inspect
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from webif.config import get_settings
from webif.models import Base, User


async def check_timezone_column(session: AsyncSession) -> bool:
    """Verificar si la columna timezone existe"""
    inspector = inspect(session.sync_session_maker.kw['bind'])
    columns = [col.name for col in inspector.get_columns('webif_users')]
    return 'timezone' in columns


async def migrate_timezone():
    """Migración para agregar timezone a webif_users"""
    settings = get_settings()
    
    print("Conectando a la base de datos...")
    print(f"DB: {settings.db_name}@{settings.db_host}:{settings.db_port}")
    
    try:
        # Crear motor async
        async_engine = create_async_engine(
            settings.database_url,
            echo=False,
            pool_size=10,
            max_overflow=20
        )
        
        async_session_maker = async_sessionmaker(
            async_engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
        
        # Crear todas las tablas (esto también agregará nuevas columnas si están definidas en el modelo)
        async with async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        
        async with async_session_maker() as session:
            # Verificar si la columna existe
            result = await session.execute(
                text("""
                    SELECT 1 FROM information_schema.columns 
                    WHERE table_name = 'webif_users' AND column_name = 'timezone'
                """)
            )
            
            if result.scalar():
                print("✓ La columna 'timezone' ya existe en webif_users")
                await async_engine.dispose()
                return True
            
            # Crear la columna si no existe
            print("Creando columna 'timezone' en webif_users...")
            await session.execute(
                text("""
                    ALTER TABLE webif_users 
                    ADD COLUMN timezone VARCHAR(100) NOT NULL DEFAULT 'UTC'
                """)
            )
            
            # Crear índice para búsquedas rápidas
            print("Creando índice idx_webif_users_timezone...")
            await session.execute(
                text("""
                    CREATE INDEX IF NOT EXISTS idx_webif_users_timezone 
                    ON webif_users(timezone)
                """)
            )
            
            await session.commit()
            print("✓ Columna 'timezone' agregada a webif_users con éxito")
            print("✓ Índice creado: idx_webif_users_timezone")
        
        await async_engine.dispose()
        return True
            
    except Exception as e:
        print(f"✗ Error durante la migración: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Función principal"""
    print("Iniciando migración de timezone...")
    print("-" * 50)
    
    success = await migrate_timezone()
    
    print("-" * 50)
    if success:
        print("Migración completada exitosamente")
        sys.exit(0)
    else:
        print("La migración falló")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
