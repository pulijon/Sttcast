"""
Modelos de base de datos para la interfaz web de Sttcast
Utiliza SQLAlchemy con PostgreSQL
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List
import uuid

from sqlalchemy import (
    Column, String, Integer, Boolean, DateTime, Text, Float,
    ForeignKey, Enum as SQLAEnum, JSON, UniqueConstraint, create_engine
)
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from passlib.context import CryptContext


# Contexto para hash de contraseñas
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class Base(DeclarativeBase):
    """Base declarativa para todos los modelos"""
    pass


class UserRole(str, Enum):
    """Roles de usuario"""
    ADMIN = "admin"
    USER = "user"
    VIEWER = "viewer"


class TranscriptionEngine(str, Enum):
    """Motores de transcripción disponibles"""
    WHISPER = "whisper"
    VOSK = "vosk"


class TranscriptionStatus(str, Enum):
    """Estados de transcripción"""
    PENDING = "pending"
    UPLOADING = "uploading"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class User(Base):
    """Modelo de usuario"""
    __tablename__ = "webif_users"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(100), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(SQLAEnum(UserRole), default=UserRole.USER, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    timezone = Column(String(100), default="UTC", nullable=False)  # Zona horaria del usuario
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)
    
    # Relaciones
    profiles = relationship("TranscriptionProfile", back_populates="owner", cascade="all, delete-orphan")
    transcriptions = relationship("TranscriptionJob", back_populates="user", cascade="all, delete-orphan")
    
    def set_password(self, password: str):
        """Establecer contraseña hasheada"""
        self.password_hash = pwd_context.hash(password)
    
    def verify_password(self, password: str) -> bool:
        """Verificar contraseña"""
        return pwd_context.verify(password, self.password_hash)
    
    def __repr__(self):
        return f"<User(username='{self.username}', role='{self.role}')>"


class TranscriptionProfile(Base):
    """Perfil de transcripción (configuración reutilizable)"""
    __tablename__ = "webif_profiles"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("webif_users.id"), nullable=False)
    is_public = Column(Boolean, default=False)
    
    # Configuración de colección
    prefix = Column(String(50), default="tr")
    calendar_file = Column(String(512), nullable=True)
    templates_dir = Column(String(512), nullable=True)
    html_suffix = Column(String(50), default="")
    
    # Configuración de transcripción
    default_engine = Column(SQLAEnum(TranscriptionEngine), default=TranscriptionEngine.WHISPER)
    whisper_model = Column(String(50), default="small")
    whisper_device = Column(String(20), default="cuda")
    default_language = Column(String(10), default="es")
    languages = Column(ARRAY(String), default=["es"])
    
    # Parámetros de procesamiento
    seconds = Column(Integer, default=15000)
    high_confidence = Column(Float, default=0.95)
    medium_confidence = Column(Float, default=0.7)
    low_confidence = Column(Float, default=0.5)
    overlap = Column(Integer, default=2)
    min_offset = Column(Integer, default=30)
    max_gap = Column(Float, default=0.8)
    
    # Opciones adicionales
    audio_tags = Column(Boolean, default=False)
    use_training = Column(Boolean, default=False)
    training_file = Column(String(512), nullable=True)
    
    # Parámetros de Pyannote (diarización)
    pyannote_method = Column(String(20), default="ward")
    pyannote_min_cluster_size = Column(Integer, default=15)
    pyannote_threshold = Column(Float, default=0.7147)
    pyannote_min_speakers = Column(Integer, nullable=True)
    pyannote_max_speakers = Column(Integer, nullable=True)
    
    # Metadatos
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relaciones
    owner = relationship("User", back_populates="profiles")
    transcriptions = relationship("TranscriptionJob", back_populates="profile")
    
    __table_args__ = (
        UniqueConstraint('name', 'owner_id', name='unique_profile_per_user'),
    )
    
    def __repr__(self):
        return f"<TranscriptionProfile(name='{self.name}', prefix='{self.prefix}')>"


class TranscriptionJob(Base):
    """Trabajo de transcripción"""
    __tablename__ = "webif_transcriptions"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("webif_users.id"), nullable=False)
    profile_id = Column(UUID(as_uuid=True), ForeignKey("webif_profiles.id"), nullable=True)
    
    # Información del archivo
    original_filename = Column(String(512), nullable=False)
    stored_filename = Column(String(512), nullable=False)
    file_size = Column(Integer, nullable=True)
    
    # Estado y progreso
    status = Column(SQLAEnum(TranscriptionStatus), default=TranscriptionStatus.PENDING)
    progress = Column(Float, default=0.0)
    message = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    
    # Configuración usada
    engine = Column(SQLAEnum(TranscriptionEngine), default=TranscriptionEngine.WHISPER)
    language = Column(String(10), default="es")
    config_snapshot = Column(JSON, nullable=True)  # Snapshot de la configuración al momento de crear
    
    # ID del trabajo en el servidor de transcripción
    remote_job_id = Column(String(100), nullable=True)
    
    # Resultados
    html_file = Column(String(512), nullable=True)
    srt_file = Column(String(512), nullable=True)
    
    # Tiempos
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    
    # Relaciones
    user = relationship("User", back_populates="transcriptions")
    profile = relationship("TranscriptionProfile", back_populates="transcriptions")
    
    def __repr__(self):
        return f"<TranscriptionJob(filename='{self.original_filename}', status='{self.status}')>"


class SystemConfig(Base):
    """Configuración del sistema"""
    __tablename__ = "webif_config"
    
    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    is_secret = Column(Boolean, default=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<SystemConfig(key='{self.key}')>"


# Funciones de utilidad para la base de datos
def get_database_url(
    host: str = "localhost",
    port: int = 5432,
    user: str = "sttcast",
    password: str = "",
    database: str = "sttcast_webif",
    async_mode: bool = True
) -> str:
    """Construir URL de conexión a PostgreSQL"""
    driver = "postgresql+asyncpg" if async_mode else "postgresql+psycopg2"
    if password:
        return f"{driver}://{user}:{password}@{host}:{port}/{database}"
    return f"{driver}://{user}@{host}:{port}/{database}"


async def init_database(database_url: str):
    """Inicializar base de datos y crear tablas"""
    engine = create_async_engine(database_url, echo=True)
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    return engine


def get_sync_engine(database_url: str):
    """Obtener engine síncrono para migraciones"""
    # Convertir URL async a sync si es necesario
    sync_url = database_url.replace("postgresql+asyncpg", "postgresql+psycopg2")
    return create_engine(sync_url)
