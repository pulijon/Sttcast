"""
Middleware para inyectar automáticamente el script de fallback de audios
en todos los HTML servidos desde el servidor.

Este módulo permite que archivos HTML existentes (incluso de 10+ años)
funcionen automáticamente con el sistema de fallback de audios locales,
sin necesidad de modificarlos.

Uso en client_rag.py:
    from middleware_audio_fallback import AudioFallbackMiddleware
    
    app = FastAPI(...)
    app.add_middleware(AudioFallbackMiddleware)
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import StreamingResponse
import re
import logging

logger = logging.getLogger(__name__)


class AudioFallbackMiddleware(BaseHTTPMiddleware):
    """
    Middleware que inyecta automáticamente el script de fallback de audios
    en todos los HTML servidos desde el servidor.
    
    Características:
    - Solo modifica respuestas HTML
    - No afecta otros tipos de archivos
    - Compatible con iframes
    - Preserva estructura HTML original
    """

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        
        # Solo procesar respuestas HTML
        if self._is_html_response(response):
            try:
                # Capturar el body de la respuesta
                body = b""
                async for chunk in response.body_iterator:
                    body += chunk
                
                # Inyectar el script
                modified_body = self._inject_fallback_script(body)
                
                # Preparar headers (copiar y remover Content-Length)
                headers = dict(response.headers)
                if 'content-length' in headers:
                    del headers['content-length']
                
                # Retornar respuesta modificada con nuevo tamaño
                return StreamingResponse(
                    iter([modified_body]),
                    status_code=response.status_code,
                    headers=headers,
                    media_type=response.media_type
                )
            except Exception as e:
                logger.warning(f"Error al inyectar script de fallback: {e}")
                # Si hay error, retornar respuesta original
                return response
        
        return response

    def _is_html_response(self, response):
        """Verifica si la respuesta es HTML"""
        content_type = response.headers.get('content-type', '').lower()
        return 'text/html' in content_type

    def _inject_fallback_script(self, html_bytes):
        """Inyecta el script de fallback en el HTML"""
        try:
            html_str = html_bytes.decode('utf-8')
            
            # Script a inyectar
            fallback_script = (
                '\n    <script src="/static/js/audio_fallback_standalone.js" '
                'defer async="false"></script>\n'
            )
            
            # Buscar </body> y colocar el script antes
            # Esto asegura que todos los elementos HTML estén cargados
            if '</body>' in html_str:
                html_str = html_str.replace('</body>', fallback_script + '</body>')
            elif '</html>' in html_str:
                # Fallback si no hay </body>
                html_str = html_str.replace('</html>', fallback_script + '</html>')
            else:
                # Último recurso: agregar al final
                html_str += fallback_script
            
            logger.debug("Script de fallback inyectado correctamente")
            return html_str.encode('utf-8')
            
        except Exception as e:
            logger.warning(f"Error decodificando HTML: {e}")
            return html_bytes
