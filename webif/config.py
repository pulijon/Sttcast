"""
Configuración de la aplicación web de Sttcast
Lee variables de entorno y proporciona valores por defecto
"""

import os
from functools import lru_cache
from typing import Optional
from urllib.parse import quote
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Configuración de la aplicación"""
    
    # Servidor web
    host: str = Field(default="127.0.0.1", validation_alias="WEBIF_HOST")
    port: int = Field(default=8080, validation_alias="WEBIF_PORT")
    debug: bool = Field(default=False, validation_alias="WEBIF_DEBUG")
    
    # Administrador inicial
    admin_name: str = Field(default="admin", validation_alias="WEBIF_ADMIN_NAME")
    admin_password: str = Field(default="admin", validation_alias="WEBIF_ADMIN_PASSWORD")
    admin_email: Optional[str] = Field(default=None, validation_alias="WEBIF_ADMIN_EMAIL")
    
    # Base de datos PostgreSQL
    db_host: str = Field(default="localhost", validation_alias="WEBIF_DB_HOST")
    db_port: int = Field(default=5432, validation_alias="WEBIF_DB_PORT")
    db_user: str = Field(default="sttcast", validation_alias="WEBIF_DB_USER")
    db_password: str = Field(default="", validation_alias="WEBIF_DB_PASSWORD")
    db_name: str = Field(default="sttcast_webif", validation_alias="WEBIF_DB_NAME")
    
    # Servidor de transcripción
    trans_server_host: str = Field(default="127.0.0.1", validation_alias="TRANSSRV_HOST")
    trans_server_port: int = Field(default=8000, validation_alias="TRANSSRV_PORT")
    trans_api_key: str = Field(default="", validation_alias="TRANSSRV_API_KEY")
    
    # Sesión
    secret_key: str = Field(default="change-this-secret-key-in-production", validation_alias="WEBIF_SECRET_KEY")
    session_expire_minutes: int = Field(default=480, validation_alias="WEBIF_SESSION_EXPIRE")
    
    # Almacenamiento de archivos
    upload_dir: str = Field(default="/tmp/sttcast_webif/uploads", validation_alias="WEBIF_UPLOAD_DIR")
    results_dir: str = Field(default="/tmp/sttcast_webif/results", validation_alias="WEBIF_RESULTS_DIR")
    training_dir: str = Field(default="/tmp/sttcast_webif/training", validation_alias="WEBIF_TRAINING_DIR")
    max_upload_size: int = Field(default=500 * 1024 * 1024, validation_alias="WEBIF_MAX_UPLOAD_SIZE")  # 500MB
    
    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
        "populate_by_name": True
    }
    
    @property
    def database_url(self) -> str:
        """URL de conexión a PostgreSQL (async) con contraseña codificada en URL"""
        if self.db_password:
            encoded_password = quote(self.db_password, safe='')
            return f"postgresql+asyncpg://{self.db_user}:{encoded_password}@{self.db_host}:{self.db_port}/{self.db_name}"
        return f"postgresql+asyncpg://{self.db_user}@{self.db_host}:{self.db_port}/{self.db_name}"
    
    @property
    def database_connection_params(self) -> dict:
        """Parámetros de conexión para asyncpg (evita problemas de URL con caracteres especiales)"""
        return {
            'host': self.db_host,
            'port': self.db_port,
            'user': self.db_user,
            'password': self.db_password,
            'database': self.db_name
        }
    
    @property
    def database_url_sync(self) -> str:
        """URL de conexión a PostgreSQL (sync) con contraseña codificada en URL"""
        if self.db_password:
            encoded_password = quote(self.db_password, safe='')
            return f"postgresql+psycopg2://{self.db_user}:{encoded_password}@{self.db_host}:{self.db_port}/{self.db_name}"
        return f"postgresql+psycopg2://{self.db_user}@{self.db_host}:{self.db_port}/{self.db_name}"
    
    @property
    def trans_server_url(self) -> str:
        """URL del servidor de transcripción"""
        return f"http://{self.trans_server_host}:{self.trans_server_port}"


@lru_cache()
def get_settings() -> Settings:
    """Obtener configuración (cacheada)"""
    return Settings()
