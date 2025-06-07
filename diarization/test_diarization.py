import os
from dotenv import load_dotenv

# Cargar variables de entorno desde el archivo de configuración
load_dotenv(".env/huggingface.conf")

# Acceder a la variable de entorno en el código
hf_token = os.getenv("HUGGINGFACE_TOKEN")

# Verificar que se ha cargado correctamente
if hf_token:
    print("Token cargado correctamente.")
else:
    print("No se pudo cargar el token. Revisa el archivo de configuración.")

# Cargar el pipeline con la autenticación
from pyannote.audio import Pipeline
pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", use_auth_token=hf_token)
