import os
from dotenv import dotenv_values
from pathlib import Path

def _confdir_env_path(confdir):
    """
    Devuelve el directorio .env asociado a una raiz de configuracion.

    Si confdir apunta ya a un directorio llamado .env, se usa directamente.
    Si apunta a la raiz de configuracion, se usa su subdirectorio .env.
    """
    conf_root = Path(confdir).expanduser()
    return conf_root if conf_root.name == ".env" else conf_root / ".env"


def _load_env_layer(env_path, protected_keys):
    """
    Carga una capa de ficheros .env.

    Las claves de protected_keys no se modifican nunca, porque proceden del
    entorno real del proceso. Dentro de una misma capa, el primer fichero en
    orden alfabetico que define una variable gana.
    """
    if not env_path.is_dir():
        raise FileNotFoundError(f"El directorio {env_path} no existe.")

    layer_keys = set()
    for env_file in sorted(env_path.glob("*.env")):
        for key, value in dotenv_values(env_file).items():
            if value is None or key in protected_keys or key in layer_keys:
                continue
            os.environ[key] = value
            layer_keys.add(key)


def load_env_vars_from_directory(directory=".env"):
    """
    Lee archivos `.env` y configura variables de entorno por capas.

    Prioridad, de mayor a menor:
      1. Variables ya configuradas en el entorno del proceso (por ejemplo Docker).
      2. Variables de la coleccion.
      3. Variables comunes.
      4. Valores por defecto del codigo.

    Si existe la variable de entorno `STTCAST_COLLECTION_CONFDIR`, tiene prioridad sobre
    el directorio recibido como argumento y se usa su subdirectorio `.env`.

    Si existe la variable de entorno `STTCAST_COMMON_CONFDIR`, se carga antes que la
    coleccion. Sus variables funcionan como valores comunes por defecto y pueden ser
    sobrescritas por la coleccion, pero nunca por encima del entorno real del proceso.

    Args:
        directory (str): Ruta del directorio que contiene los archivos `.env`.
    """
    protected_keys = set(os.environ)

    common_confdir = os.getenv("STTCAST_COMMON_CONFDIR")
    if common_confdir:
        _load_env_layer(_confdir_env_path(common_confdir), protected_keys)

    collection_confdir = os.getenv("STTCAST_COLLECTION_CONFDIR")
    if collection_confdir:
        env_path = _confdir_env_path(collection_confdir)
    else:
        env_path = Path(directory).expanduser()

    if common_confdir and not collection_confdir and not env_path.is_dir():
        return

    _load_env_layer(env_path, protected_keys)
    

if __name__ == "__main__":
    # Cargar las variables de entorno de los archivos .env en el directorio actual
    load_env_vars_from_directory()

    # Imprimir las variables de entorno
    print("Variables de entorno cargadas:")
    for key, value in os.environ.items():
        print(f"{key}={value}")
