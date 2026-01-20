"""
HMAC Authentication utilities for Sttcast API
Provides functions for creating and verifying HMAC signatures for secure API communication
"""

import hmac
import hashlib
import time
import json
import logging
from typing import Union, Any
from urllib.parse import urlparse
from fastapi import Request, HTTPException


def create_hmac_signature(secret_key: str, method: str, path: str, body: str, timestamp: str) -> str:
    """
    Crea una firma HMAC para autenticar la solicitud.
    
    Args:
        secret_key: Clave secreta compartida entre cliente y servidor
        method: Método HTTP (GET, POST, etc.)
        path: Ruta del endpoint (ej: /api/getcontext)
        body: Cuerpo de la petición serializado como string JSON
        timestamp: Timestamp Unix como string
        
    Returns:
        Firma HMAC en formato hexadecimal
    """
    message = f"{method}|{path}|{body}|{timestamp}"
    return hmac.new(
        secret_key.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()


def serialize_body(body: Any) -> str:
    """
    Serializa el cuerpo de la petición de forma consistente.
    
    Args:
        body: Objeto a serializar (dict, list, Pydantic model, etc.)
        
    Returns:
        String JSON serializado de forma consistente (sin espacios, ordenado)
    """
    # Para multipart/form-data, retornar cadena vacía literal
    if body is None or body == "":
        return ""
    
    # SERIALIZACIÓN CONSISTENTE SIN ESPACIOS
    if hasattr(body, 'model_dump'):
        # Pydantic model
        return json.dumps(body.model_dump(), separators=(',', ':'), sort_keys=True, ensure_ascii=False)
    elif isinstance(body, list) and len(body) > 0 and hasattr(body[0], 'model_dump'):
        # Lista de Pydantic models
        return json.dumps([item.model_dump() for item in body], separators=(',', ':'), sort_keys=True, ensure_ascii=False)
    elif isinstance(body, (dict, list)):
        # Dict o list estándar
        return json.dumps(body, separators=(',', ':'), sort_keys=True, ensure_ascii=False)
    else:
        # Otros tipos: intentar serializar
        return json.dumps(body, separators=(',', ':'), sort_keys=True, ensure_ascii=False)


def create_auth_headers(
    secret_key: str, 
    method: str, 
    url: str, 
    body: Any,
    client_id: str = 'sttcast_client'
) -> dict:
    """
    Crea los headers de autenticación HMAC para una petición.
    
    Args:
        secret_key: Clave secreta compartida
        method: Método HTTP (POST, GET, etc.)
        url: URL completa o path del endpoint
        body: Cuerpo de la petición (dict, list, Pydantic model, etc.)
        client_id: Identificador del cliente (por defecto 'sttcast_client')
        
    Returns:
        Dictionary con los headers de autenticación
    """
    # Extraer el path de la URL
    parsed_url = urlparse(url)
    path = parsed_url.path if parsed_url.path else url
    
    timestamp = str(int(time.time()))
    body_str = serialize_body(body)
    
    # Logging detallado para debugging
    message = f"{method}|{path}|{body_str}|{timestamp}"
    logging.debug(f"Creando autenticación HMAC:")
    logging.debug(f"  URL: {url}")
    logging.debug(f"  Método: {method}, Path: {path}")
    logging.debug(f"  Timestamp: {timestamp}")
    logging.debug(f"  Body original type: {type(body).__name__}")
    logging.debug(f"  Body serializado: {body_str[:200]}...")
    logging.debug(f"  Mensaje completo: {message}")
    
    signature = create_hmac_signature(secret_key, method, path, body_str, timestamp)
    
    logging.debug(f"HMAC Cliente - Generando para {path}: método={method}, timestamp={timestamp}, body_len={len(body_str)}")
    logging.debug(f"HMAC Cliente - Mensaje: '{message}'")
    logging.debug(f"HMAC Cliente - Firma generada: {signature}")
    logging.debug(f"HMAC Cliente - Clave API (primeros 10 chars): {secret_key[:10]}...")
    
    headers = {
        'X-Timestamp': timestamp,
        'X-Signature': signature,
        'X-Client-ID': client_id
    }
    
    # Solo añadir Content-Type: application/json si es body no vacío
    # Para multipart/form-data, dejar que requests maneje el Content-Type
    if body_str and body_str != '{}':
        headers['Content-Type'] = 'application/json'
    
    return headers


def verify_hmac_signature(
    secret_key: str, 
    signature: str, 
    method: str, 
    path: str, 
    body: str, 
    timestamp: str,
    max_age_seconds: int = 300
) -> bool:
    """
    Verifica la firma HMAC y el timestamp de la solicitud.
    
    Args:
        secret_key: Clave secreta compartida
        signature: Firma HMAC recibida
        method: Método HTTP
        path: Path del endpoint
        body: Cuerpo de la petición como string JSON
        timestamp: Timestamp recibido
        max_age_seconds: Máxima antigüedad permitida del timestamp (por defecto 5 minutos)
        
    Returns:
        True si la firma es válida y el timestamp es reciente, False en caso contrario
    """
    try:
        # Verificar que timestamp no sea muy antiguo
        current_time = time.time()
        request_time = float(timestamp)
        time_diff = abs(current_time - request_time)
        
        if time_diff > max_age_seconds:
            logging.warning(f"Timestamp demasiado antiguo: {timestamp}, diferencia: {time_diff} segundos")
            return False
        
        expected = create_hmac_signature(secret_key, method, path, body, timestamp)
        is_valid = hmac.compare_digest(signature, expected)
        
        # Logging detallado para debugging
        message_servidor = f"{method}|{path}|{body}|{timestamp}"
        logging.debug(f"HMAC Servidor - Verificando: método={method}, path='{path}', timestamp={timestamp}, body_len={len(body)}")
        logging.debug(f"HMAC Servidor - Mensaje completo: '{message_servidor}'")
        logging.debug(f"HMAC Servidor - Clave API (primeros 10 chars): {secret_key[:10]}...")
        logging.debug(f"HMAC Servidor - Firma esperada: {expected}")
        logging.debug(f"HMAC Servidor - Firma recibida: {signature}")
        logging.debug(f"HMAC Servidor - ¿Válida?: {is_valid}")
        
        if not is_valid:
            logging.warning("Las firmas HMAC no coinciden")
            
        return is_valid
    except (ValueError, TypeError) as e:
        logging.error(f"Error verificando firma HMAC: {e}")
        return False


def validate_hmac_auth(
    request: Request, 
    secret_key: str,
    body_bytes: bytes = b""
) -> str:
    """
    Valida la autenticación HMAC de una petición FastAPI y retorna el client_id.
    
    Args:
        request: Objeto Request de FastAPI
        secret_key: Clave secreta para verificar la firma
        body_bytes: Bytes del cuerpo de la petición (opcional)
        
    Returns:
        client_id si la autenticación es válida
        
    Raises:
        HTTPException: Si la autenticación falla o faltan headers
    """
    if not secret_key:
        logging.error("Secret key no configurada")
        raise HTTPException(status_code=500, detail="Error de configuración del servidor")
    
    # Obtener headers requeridos
    timestamp = request.headers.get('X-Timestamp')
    signature = request.headers.get('X-Signature')
    client_id = request.headers.get('X-Client-ID', 'unknown')
    
    if not timestamp or not signature:
        logging.warning(f"Headers de autenticación faltantes para client_id: {client_id}")
        logging.warning(f"Timestamp: {'presente' if timestamp else 'ausente'}, Signature: {'presente' if signature else 'ausente'}")
        raise HTTPException(
            status_code=401, 
            detail="Headers de autenticación requeridos: X-Timestamp, X-Signature"
        )
    
    # Verificar firma
    method = request.method
    path = str(request.url.path)
    # USAR EL BODY EXACTO QUE RECIBIMOS, NO RESERIALIZARLO
    body = body_bytes.decode('utf-8') if body_bytes else ""
    
    # LOGGING DETALLADO DEL CUERPO CRUDO
    logging.debug(f"HMAC Validate - Cuerpo crudo recibido: '{body[:200]}...'")
    logging.debug(f"HMAC Validate - Bytes del cuerpo: {len(body_bytes)} bytes")
    logging.debug(f"Validando HMAC para {client_id}: {method} {path} con body de {len(body)} caracteres")
    
    if not verify_hmac_signature(secret_key, signature, method, path, body, timestamp):
        logging.warning(f"Autenticación HMAC fallida para client_id: {client_id}")
        logging.debug(f"Esperado vs recibido - Método: {method}, Path: {path}, Timestamp: {timestamp}")
        logging.debug(f"Body hash: {hashlib.sha256(body.encode()).hexdigest()[:16]}")
        raise HTTPException(status_code=401, detail="Autenticación HMAC inválida")
    
    logging.debug(f"Autenticación HMAC exitosa para client_id: {client_id}")
    return client_id
