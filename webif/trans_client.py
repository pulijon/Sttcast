"""
Cliente para comunicación con el servidor de transcripción
"""

import hashlib
import hmac
import time
import logging
from typing import Dict, Any, Optional, List
from pathlib import Path

import httpx
from pydantic import BaseModel

from .config import Settings


class TranscriptionConfig(BaseModel):
    """Configuración para enviar al servidor de transcripción"""
    whisper: bool = False
    whmodel: str = "small"
    whdevice: str = "cuda"
    whlanguage: str = "es"
    prefix: str = "tr"
    calendar_file: Optional[str] = None
    templates_dir: Optional[str] = None
    html_suffix: str = ""
    min_offset: int = 30
    max_gap: float = 0.8
    seconds: int = 15000
    hconf: float = 0.95
    mconf: float = 0.7
    lconf: float = 0.5
    overlap: int = 2
    audio_tags: bool = False
    use_training: bool = False
    training_file: Optional[str] = None
    pyannote_method: str = "ward"
    pyannote_min_cluster_size: int = 15
    pyannote_threshold: float = 0.7147
    pyannote_min_speakers: Optional[int] = None
    pyannote_max_speakers: Optional[int] = None


class TranscriptionClient:
    """Cliente para comunicarse con el servidor de transcripción STTCast"""
    
    def __init__(self, settings: Settings):
        self.base_url = settings.trans_server_url
        self.api_key = settings.trans_api_key
        self.timeout = httpx.Timeout(30.0, connect=10.0)
    
    def _generate_hmac_headers(self, method: str, path: str, body: str = "") -> Dict[str, str]:
        """Generar headers de autenticación HMAC compatibles con apihmac.py"""
        timestamp = str(int(time.time()))
        
        # Formato del mensaje: method|path|body|timestamp
        message = f"{method}|{path}|{body}|{timestamp}"
        
        # Generar firma HMAC
        signature = hmac.new(
            self.api_key.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()
        
        return {
            "X-Timestamp": timestamp,
            "X-Signature": signature,
            "X-Client-ID": "webif_client"
        }
    
    async def get_status(self) -> Dict[str, Any]:
        """Obtener estado del servidor de transcripción"""
        path = "/status"
        headers = self._generate_hmac_headers("GET", path)
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{self.base_url}{path}",
                headers=headers
            )
            response.raise_for_status()
            return response.json()
    
    async def submit_transcription(
        self,
        file_path: Path,
        config: TranscriptionConfig,
        training_file_path: Optional[Path] = None,
        calendar_file_path: Optional[Path] = None
    ) -> Dict[str, Any]:
        """Enviar archivo para transcripción"""
        path = "/transcribe"
        
        # Para multipart/form-data, el body se considera vacío en el HMAC
        headers = self._generate_hmac_headers("POST", path, "")
        
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=30.0)) as client:
            # Preparar archivos - el servidor espera 'audio_file'
            files_to_send = []
            
            # Archivo de audio principal
            audio_file = open(file_path, "rb")
            files_to_send.append(("audio_file", (file_path.name, audio_file, "audio/mpeg")))
            
            # Archivo de entrenamiento opcional - solo para Whisper
            training_handle = None
            if config.whisper and training_file_path and training_file_path.exists():
                training_handle = open(training_file_path, "rb")
                files_to_send.append(("training_file", (training_file_path.name, training_handle, "audio/mpeg")))
            
            # Archivo de calendario opcional
            calendar_handle = None
            if calendar_file_path and calendar_file_path.exists():
                calendar_handle = open(calendar_file_path, "rb")
                files_to_send.append(("calendar_file", (calendar_file_path.name, calendar_handle, "text/plain")))
            
            try:
                data = {"config": config.model_dump_json()}
                
                response = await client.post(
                    f"{self.base_url}{path}",
                    files=files_to_send,
                    data=data,
                    headers=headers
                )
                response.raise_for_status()
                return response.json()
            finally:
                # Cerrar todos los archivos abiertos
                audio_file.close()
                if training_handle:
                    training_handle.close()
                if calendar_handle:
                    calendar_handle.close()
    
    async def get_job_status(self, job_id: str) -> Dict[str, Any]:
        """Obtener estado de un trabajo"""
        path = f"/jobs/{job_id}/status"
        headers = self._generate_hmac_headers("GET", path)
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{self.base_url}{path}",
                headers=headers
            )
            response.raise_for_status()
            return response.json()
    
    async def get_job_files(self, job_id: str) -> List[Dict[str, Any]]:
        """Obtener lista de archivos de resultado"""
        path = f"/jobs/{job_id}/files"
        headers = self._generate_hmac_headers("GET", path)
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{self.base_url}{path}",
                headers=headers
            )
            response.raise_for_status()
            return response.json()
    
    async def download_file(self, job_id: str, filename: str, dest_path: Path) -> bool:
        """Descargar archivo de resultado"""
        path = f"/jobs/{job_id}/files/{filename}"
        headers = self._generate_hmac_headers("GET", path)
        
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
            response = await client.get(
                f"{self.base_url}{path}",
                headers=headers
            )
            response.raise_for_status()
            
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            dest_path.write_bytes(response.content)
            return True
    
    async def cancel_job(self, job_id: str) -> bool:
        """Cancelar un trabajo"""
        path = f"/jobs/{job_id}/cancel"
        headers = self._generate_hmac_headers("POST", path)
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}{path}",
                headers=headers
            )
            return response.status_code == 200
