import os
from dotenv import load_dotenv
from pathlib import Path

def load_env_vars_from_directory(directory=".env"):
    """
    Lee todos los archivos `.env` en un directorio en orden alfabético y configura las variables de entorno.
    Si una variable ya está configurada en el entorno (como en Docker), NO se sobrescribe.

    Args:
        directory (str): Ruta del directorio que contiene los archivos `.env`.
    """
    env_path = Path(directory)
    if not env_path.is_dir():
        raise FileNotFoundError(f"El directorio {directory} no existe.")
    
    # Leer todos los archivos .env en orden alfabético
    for env_file in sorted(env_path.glob("*.env")):
        load_dotenv(env_file, override=False)  # No sobrescribe variables ya configuradas en el entorno
    

if __name__ == "__main__":
    # Cargar las variables de entorno de los archivos .env en el directorio actual
    load_env_vars_from_directory()

    # Imprimir las variables de entorno
    print("Variables de entorno cargadas:")
    for key, value in os.environ.items():
        print(f"{key}={value}")
