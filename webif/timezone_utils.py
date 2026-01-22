"""
Utilidades para manejo de zonas horarias
"""

from datetime import datetime
from pytz import timezone as pytz_timezone, UTC
from typing import Optional

def convert_to_user_timezone(dt: datetime, user_timezone: str = "UTC") -> datetime:
    """
    Convertir un datetime UTC a la zona horaria del usuario
    
    Args:
        dt: Datetime en UTC (naive o aware)
        user_timezone: Nombre de la zona horaria del usuario (ej: "Europe/Madrid")
        
    Returns:
        Datetime en la zona horaria del usuario
    """
    if dt is None:
        return None
    
    try:
        # Si el datetime es naive, asumir que está en UTC
        if dt.tzinfo is None:
            dt_utc = UTC.localize(dt)
        else:
            dt_utc = dt
        
        # Convertir a la zona horaria del usuario
        user_tz = pytz_timezone(user_timezone)
        dt_user = dt_utc.astimezone(user_tz)
        
        return dt_user
    except Exception as e:
        # Si hay error, devolver el datetime original
        return dt


def get_timezone_offset(user_timezone: str = "UTC") -> str:
    """
    Obtener el offset de zona horaria del usuario en formato legible
    
    Args:
        user_timezone: Nombre de la zona horaria
        
    Returns:
        String con el offset (ej: "GMT+1" o "UTC-5")
    """
    try:
        tz = pytz_timezone(user_timezone)
        now = datetime.now(tz)
        offset = now.strftime('%z')
        # Convertir +0530 a +05:30
        if len(offset) >= 5:
            offset = offset[:3] + ':' + offset[3:]
        return f"UTC{offset}"
    except:
        return "UTC"


# Lista de zonas horarias comunes
COMMON_TIMEZONES = [
    ("UTC", "UTC"),
    ("Europe/Madrid", "España (Zona Horaria Central)"),
    ("Europe/London", "Reino Unido"),
    ("Europe/Paris", "Francia"),
    ("Europe/Berlin", "Alemania"),
    ("Europe/Rome", "Italia"),
    ("Europe/Amsterdam", "Países Bajos"),
    ("Europe/Brussels", "Bélgica"),
    ("Europe/Vienna", "Austria"),
    ("Europe/Prague", "República Checa"),
    ("Europe/Warsaw", "Polonia"),
    ("Europe/Athens", "Grecia"),
    ("Europe/Helsinki", "Finlandia"),
    ("Europe/Istanbul", "Turquía"),
    ("America/New_York", "Nueva York"),
    ("America/Los_Angeles", "Los Ángeles"),
    ("America/Chicago", "Chicago"),
    ("America/Mexico_City", "Ciudad de México"),
    ("America/Toronto", "Toronto"),
    ("America/Buenos_Aires", "Buenos Aires"),
    ("America/Sao_Paulo", "São Paulo"),
    ("Asia/Tokyo", "Tokio"),
    ("Asia/Hong_Kong", "Hong Kong"),
    ("Asia/Shanghai", "Shanghái"),
    ("Asia/Singapore", "Singapur"),
    ("Asia/Bangkok", "Bangkok"),
    ("Asia/Dubai", "Dubái"),
    ("Asia/Kolkata", "India"),
    ("Australia/Sydney", "Sídney"),
    ("Pacific/Auckland", "Nueva Zelanda"),
]
