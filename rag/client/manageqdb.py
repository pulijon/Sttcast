#!/usr/bin/env python3
"""
Script para gestionar backups y restauración de la base de datos de queries RAG.

Facilita la migración de bases de datos de consultas entre entornos.

Uso:
    python manageqdb.py backup <archivo_destino>
    python manageqdb.py restore <archivo_origen>
    python manageqdb.py restore <archivo_origen> --create-db

Ejemplos:
    # Crear backup
    python manageqdb.py backup ./backups/coffeebreak_2026-01-08.sql
    
    # Restaurar desde backup (la BD debe existir)
    python manageqdb.py restore ./backups/coffeebreak_2026-01-08.sql
    
    # Restaurar en nuevo entorno (crea BD y usuario automáticamente)
    python manageqdb.py restore ./backups/coffeebreak_2026-01-08.sql --create-db
"""

import asyncio
import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

# Agregar el directorio parent a sys.path para importar desde tools y api
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from logs import logcfg
from envvars import load_env_vars_from_directory
from rag.client.queriesdb import RAGDatabase

# Configurar logging
logcfg(__file__)


class QueryDBManager:
    """Gestor de backups y restauración de base de datos de queries"""
    
    def __init__(self):
        """Inicializa el manager cargando variables de entorno"""
        # Cargar variables de entorno desde .env/
        env_dir = os.path.join(os.path.dirname(__file__), '../../.env')
        load_env_vars_from_directory(env_dir)
        
        self.db = RAGDatabase()
    
    async def backup(self, output_file: str) -> bool:
        """
        Crea un backup de la base de datos.
        
        Args:
            output_file: Ruta donde guardar el backup
            
        Returns:
            True si fue exitoso, False en caso contrario
        """
        if not self.db.is_available:
            print("❌ Error: Base de datos no disponible. Verifica la configuración en .env/")
            return False
        
        # Crear directorio si no existe
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        print(f"\n📦 Iniciando backup de base de datos: {self.db.database}")
        print(f"   Host: {self.db.host}:{self.db.port}")
        print(f"   Usuario: {self.db.user}")
        print(f"   Destino: {output_file}\n")
        
        success = await self.db.backup_to_file(output_file)
        
        if success:
            file_size = os.path.getsize(output_file) / (1024 * 1024)
            print(f"\n✅ Backup completado:")
            print(f"   Archivo: {output_file}")
            print(f"   Tamaño: {file_size:.2f} MB")
            print(f"   Fecha: {datetime.now().isoformat()}\n")
        else:
            print("\n❌ El backup falló. Verifica los logs anteriores.\n")
        
        return success
    
    async def restore(self, input_file: str, create_db: bool = False) -> bool:
        """
        Restaura la base de datos desde un backup.
        
        Args:
            input_file: Ruta del archivo de backup
            create_db: Si True, crea la BD y usuario si no existen
            
        Returns:
            True si fue exitoso, False en caso contrario
        """
        if not self.db.is_available:
            print("❌ Error: Base de datos no disponible. Verifica la configuración en .env/")
            return False
        
        if not os.path.exists(input_file):
            print(f"❌ Error: Archivo no encontrado: {input_file}\n")
            return False
        
        file_size = os.path.getsize(input_file) / (1024 * 1024)
        
        print(f"\n📥 Iniciando restauración desde backup")
        print(f"   Host: {self.db.host}:{self.db.port}")
        print(f"   Base de datos: {self.db.database}")
        print(f"   Usuario: {self.db.user}")
        print(f"   Origen: {input_file}")
        print(f"   Tamaño: {file_size:.2f} MB\n")
        
        if create_db:
            print("⚠️  Se crearán la base de datos y usuario si no existen.\n")
        else:
            print("⚠️  La base de datos debe existir. Usa --create-db si necesitas crearla.\n")
        
        # Confirmación
        response = input("¿Deseas continuar con la restauración? (escribir 's' para confirmar): ")
        if response.lower() != 's':
            print("❌ Operación cancelada.\n")
            return False
        
        # Inicializar BD si es necesario
        if create_db:
            await self.db.initialize()
        
        success = await self.db.restore_from_file(input_file, create_db_and_user=create_db)
        
        if success:
            print(f"\n✅ Restauración completada:")
            print(f"   Base de datos: {self.db.database}")
            print(f"   Timestamp: {datetime.now().isoformat()}\n")
        else:
            print("\n❌ La restauración falló. Verifica los logs anteriores.\n")
        
        return success


async def main():
    """Función principal que procesa los argumentos de línea de comandos"""
    parser = argparse.ArgumentParser(
        description="Gestor de backups y restauración para la BD de queries RAG",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  # Crear backup
  python manageqdb.py backup ./backups/coffeebreak_2026-01-08.sql
  
  # Restaurar desde backup (la BD debe existir)
  python manageqdb.py restore ./backups/coffeebreak_2026-01-08.sql
  
  # Restaurar creando BD y usuario
  python manageqdb.py restore ./backups/coffeebreak_2026-01-08.sql --create-db
        """.strip()
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Comando a ejecutar')
    
    # Comando backup
    backup_parser = subparsers.add_parser('backup', help='Crear backup de la base de datos')
    backup_parser.add_argument(
        'output_file',
        help='Ruta del archivo donde guardar el backup'
    )
    
    # Comando restore
    restore_parser = subparsers.add_parser('restore', help='Restaurar la base de datos desde un backup')
    restore_parser.add_argument(
        'input_file',
        help='Ruta del archivo de backup'
    )
    restore_parser.add_argument(
        '--create-db',
        action='store_true',
        help='Crear la base de datos y usuario si no existen'
    )
    
    args = parser.parse_args()
    
    # Validar que se proporcionó un comando
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    # Crear manager y ejecutar comando
    manager = QueryDBManager()
    
    if args.command == 'backup':
        success = await manager.backup(args.output_file)
        sys.exit(0 if success else 1)
    
    elif args.command == 'restore':
        success = await manager.restore(args.input_file, create_db=args.create_db)
        sys.exit(0 if success else 1)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Operación cancelada por el usuario.\n")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error inesperado: {e}\n")
        sys.exit(1)
