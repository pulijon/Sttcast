#!/usr/bin/env python3
"""
Script de validación de la refactorización de módulos API
Verifica que todos los imports funcionan correctamente
"""

import sys
import os

# Añadir el directorio raíz del proyecto al path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)

def test_apirag_imports():
    """Verifica que todos los modelos de api/apirag.py se pueden importar"""
    print("✓ Probando imports de api/apirag.py...")
    try:
        from api.apirag import (
            EpisodeInput,
            EpisodeOutput,
            EmbeddingInput,
            MultiLangText,
            References,
            RelSearchRequest,
            RelSearchResponse,
            GetEmbeddingsResponse,
            GetOneEmbeddingRequest,
            GetOneEmbeddingResponse
        )
        print("  ✅ Todos los modelos de apirag importados correctamente")
        return True
    except ImportError as e:
        print(f"  ❌ Error importando modelos de apirag: {e}")
        return False

def test_apihmac_imports():
    """Verifica que las funciones de api/apihmac.py se pueden importar"""
    print("✓ Probando imports de api/apihmac.py...")
    try:
        from api.apihmac import (
            create_hmac_signature,
            serialize_body,
            create_auth_headers,
            verify_hmac_signature,
            validate_hmac_auth
        )
        print("  ✅ Todas las funciones de apihmac importadas correctamente")
        return True
    except ImportError as e:
        print(f"  ❌ Error importando funciones de apihmac: {e}")
        return False

def test_context_server_imports():
    """Verifica que context_server.py puede importar correctamente"""
    print("✓ Probando imports en db/context_server.py...")
    try:
        # Cambiar al directorio db para el import
        original_dir = os.getcwd()
        db_dir = os.path.join(project_root, 'db')
        os.chdir(db_dir)
        
        from api.apirag import EmbeddingInput
        from api.apicontext import (
            AddSegmentsRequest,
            GetContextRequest,
            GetContextResponse
        )
        print("  ✅ context_server.py puede importar correctamente")
        
        os.chdir(original_dir)
        return True
    except ImportError as e:
        print(f"  ❌ Error en imports de context_server: {e}")
        os.chdir(original_dir)
        return False

def test_rag_service_imports():
    """Verifica que sttcast_rag_service.py puede importar correctamente"""
    print("✓ Probando imports en rag/sttcast_rag_service.py...")
    try:
        from api.apirag import (
            EpisodeInput,
            EpisodeOutput,
            RelSearchRequest,
            RelSearchResponse
        )
        from api.apihmac import validate_hmac_auth
        print("  ✅ sttcast_rag_service.py puede importar correctamente")
        return True
    except ImportError as e:
        print(f"  ❌ Error en imports de sttcast_rag_service: {e}")
        return False

def main():
    print("=" * 60)
    print("Validación de Refactorización de Módulos API")
    print("=" * 60)
    print()
    
    tests = [
        test_apirag_imports,
        test_apihmac_imports,
        test_context_server_imports,
        test_rag_service_imports
    ]
    
    results = []
    for test in tests:
        results.append(test())
        print()
    
    print("=" * 60)
    if all(results):
        print("✅ TODAS LAS PRUEBAS PASARON EXITOSAMENTE")
        print("=" * 60)
        return 0
    else:
        print("❌ ALGUNAS PRUEBAS FALLARON")
        print("=" * 60)
        return 1

if __name__ == "__main__":
    sys.exit(main())
