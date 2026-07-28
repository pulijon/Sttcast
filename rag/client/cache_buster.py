"""
Cache busting utility for static files.
Generates versioned URLs based on file content hash to ensure browsers reload updated files.
"""

import os
import hashlib
import shutil
from functools import lru_cache


@lru_cache(maxsize=128)
def get_file_hash(filepath: str, hash_length: int = 8) -> str:
    """
    Calculate MD5 hash of a file for cache busting.
    
    Args:
        filepath: Path to the file
        hash_length: Length of the hash to use (default: 8)
    
    Returns:
        Hash string or empty string if file doesn't exist
    """
    if not os.path.exists(filepath):
        return ""
    
    try:
        with open(filepath, 'rb') as f:
            file_hash = hashlib.md5(f.read()).hexdigest()
            return file_hash[:hash_length]
    except Exception:
        return ""


def get_static_url(static_path: str, base_dir: str = "static", base_path: str = "") -> str:
    """
    Generate cache-busted URL for a static file.
    
    Args:
        static_path: Relative path to the static file (e.g., "css/client_rag.css")
        base_dir: Base directory for static files (default: "static")
        base_path: Base path prefix for the URL (e.g., "/sttcast")
    
    Returns:
        URL with version parameter (e.g., "/sttcast/static/css/client_rag.css?v=a1b2c3d4")
    """
    current_dir = os.path.dirname(os.path.abspath(__file__))
    full_path = os.path.join(current_dir, base_dir, static_path)
    file_hash = get_file_hash(full_path)

    if file_hash:
        path_root, path_ext = os.path.splitext(static_path)
        fingerprinted_static_path = f"{path_root}.{file_hash}{path_ext}"
        fingerprinted_full_path = os.path.join(current_dir, base_dir, fingerprinted_static_path)
        try:
            if not os.path.exists(fingerprinted_full_path):
                shutil.copy2(full_path, fingerprinted_full_path)
            static_path = fingerprinted_static_path
        except Exception:
            pass
    
    # Construir URL con base_path - asegurar que empiece con /
    if base_path:
        # Normalizar base_path para que empiece con / y no termine con /
        normalized_base = base_path if base_path.startswith('/') else f'/{base_path}'
        normalized_base = normalized_base.rstrip('/')
        url = f"{normalized_base}/{base_dir}/{static_path}"
    else:
        # Si no hay base_path, asegurar que empiece con /
        url = f"/{base_dir}/{static_path}"
    
    return url
