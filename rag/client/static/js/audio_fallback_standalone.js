/**
 * Sistema de Fallback de Audios Locales
 * Para Transcripciones HTML
 * 
 * Este script detecta cuando los audios incrustados en las transcripciones
 * no están disponibles en el servidor y permite al usuario cargarlos localmente.
 * 
 * Uso: Incluir al final de cada archivo HTML de transcripción generado por add_audio_tag.py
 * 
 * Ejemplo en add_audio_tag.py:
 *   soup.append(soup.new_tag("script", src="/static/js/audio_fallback_standalone.js"))
 */

(function() {
    'use strict';

    // Configuración
    const CONFIG = {
        DEBUG: true,
        PREFIX: '[AudioFallback]',
        AUTO_PLAY: true
    };

    // Utilidades de logging
    const logger = {
        log: (msg) => CONFIG.DEBUG && console.log(`${CONFIG.PREFIX} ${msg}`),
        warn: (msg) => console.warn(`${CONFIG.PREFIX} ${msg}`),
        error: (msg) => console.error(`${CONFIG.PREFIX} ${msg}`)
    };

    /**
     * Inicia el sistema de fallback para audios
     */
    function init() {
        logger.log('Inicializando sistema de fallback de audios locales...');

        // Esperar a que el DOM esté completamente cargado
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', setupAudioFallback);
        } else {
            setupAudioFallback();
        }
    }

    /**
     * Configura el fallback para todos los audios de la página
     */
    function setupAudioFallback() {
        const audios = document.querySelectorAll('audio');
        logger.log(`Encontrados ${audios.length} elementos de audio`);

        audios.forEach((audio, index) => {
            setupAudioErrorHandler(audio, index);
        });
    }

    /**
     * Configura los manejadores de error para un audio específico
     */
    function setupAudioErrorHandler(audio, index) {
        // Evitar configuración múltiple
        if (audio.dataset.audioFallbackSetup === 'true') {
            return;
        }
        audio.dataset.audioFallbackSetup = 'true';
        audio.dataset.audioIndex = index;

        // Evento 1: Error al cargar el audio
        audio.addEventListener('error', function(event) {
            if (this.error) {
                logger.log(`Error en audio #${this.dataset.audioIndex}: ${this.error.code}`);
                // MEDIA_ERR_SRC_NOT_SUPPORTED = 4
                if (this.error.code === 4 || this.error.code === 2) {
                    handleAudioNotFound.call(this);
                }
            }
        });

        // Evento 2: Intento de reproducción sin fuente
        audio.addEventListener('play', function(event) {
            if (this.networkState === this.NETWORK_NO_SOURCE) {
                logger.log(`Intento de reproducción sin fuente en audio #${this.dataset.audioIndex}`);
                handleAudioNotFound.call(this);
                event.preventDefault();
            }
        }, true);

        logger.log(`Audio #${index} configurado: ${audio.src}`);
    }

    /**
     * Maneja la situación cuando un audio no está disponible
     */
    function handleAudioNotFound() {
        // Evitar múltiples diálogos para el mismo audio
        if (this.dataset.userAskedForFile === 'true') {
            logger.log(`Audio ya solicitado, ignorando...`);
            return;
        }
        this.dataset.userAskedForFile = 'true';

        // Extraer información del audio
        const audioUrl = this.src || 'audio desconocido';
        const audioFilename = audioUrl.split('/').pop().split('#')[0] || 'audio.mp3';
        const expectedTime = audioUrl.includes('#t=') ? audioUrl.split('#t=')[1] : null;

        logger.log(`Audio no disponible: ${audioFilename}`);

        // Mostrar diálogo personalizado HTML (no confirm() que rompe el contexto)
        mostrarDialogoPersonalizado.call(this, audioFilename, expectedTime);
    }

    /**
     * Muestra un diálogo HTML personalizado que no rompe el contexto de interacción
     */
    function mostrarDialogoPersonalizado(filename, expectedTime) {
        const audioElement = this;
        
        // Crear overlay
        const overlay = document.createElement('div');
        overlay.style.cssText = `
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.5);
            z-index: 10000;
            display: flex;
            align-items: center;
            justify-content: center;
        `;
        
        // Crear diálogo
        const dialog = document.createElement('div');
        dialog.style.cssText = `
            background: white;
            padding: 24px;
            border-radius: 8px;
            max-width: 500px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.3);
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        `;
        
        // Construir mensaje
        let mensaje = `<p style="margin: 0 0 16px 0; font-size: 14px; line-height: 1.5;">
            El archivo de audio <strong>"${filename}"</strong> no está disponible en el servidor.
        </p>
        <p style="margin: 0 0 16px 0; font-size: 14px; line-height: 1.5;">
            ¿Tienes este archivo en tu equipo? Puedes seleccionarlo para escucharlo.
        </p>`;
        
        if (expectedTime) {
            mensaje += `<p style="margin: 0 0 16px 0; font-size: 13px; color: #666;">
                Se reproducirá desde: <strong>${expectedTime}</strong>
            </p>`;
        }
        
        // Botones
        mensaje += `
            <div style="display: flex; gap: 12px; justify-content: flex-end; margin-top: 24px;">
                <button id="audio-fallback-cancel" style="
                    padding: 8px 16px;
                    border: 1px solid #ccc;
                    background: white;
                    border-radius: 4px;
                    cursor: pointer;
                    font-size: 14px;
                ">Cancelar</button>
                <button id="audio-fallback-accept" style="
                    padding: 8px 16px;
                    border: none;
                    background: #2563eb;
                    color: white;
                    border-radius: 4px;
                    cursor: pointer;
                    font-size: 14px;
                    font-weight: 500;
                ">Seleccionar archivo</button>
            </div>
        `;
        
        dialog.innerHTML = mensaje;
        overlay.appendChild(dialog);
        document.body.appendChild(overlay);
        
        // Crear input de archivo (oculto pero listo)
        const input = document.createElement('input');
        input.type = 'file';
        input.accept = 'audio/*';
        input.style.display = 'none';
        document.body.appendChild(input);
        
        // Función para limpiar diálogo
        const cerrarDialogo = () => {
            if (document.body.contains(overlay)) {
                document.body.removeChild(overlay);
            }
            if (document.body.contains(input)) {
                document.body.removeChild(input);
            }
        };
        
        // Manejador de cambio de archivo
        input.addEventListener('change', (e) => {
            const file = e.target.files[0];
            if (file) {
                cargarAudioLocal.call(audioElement, file, filename, expectedTime);
                logger.log(`Archivo seleccionado: ${file.name}`);
            }
            cerrarDialogo();
        });
        
        // Botón Aceptar - disparar selector DIRECTAMENTE desde el click
        const btnAccept = dialog.querySelector('#audio-fallback-accept');
        btnAccept.addEventListener('click', () => {
            cerrarDialogo();
            // Click INMEDIATO desde el evento del usuario
            input.click();
            logger.log(`Selector de archivo abierto para ${filename}`);
        });
        
        // Botón Cancelar
        const btnCancel = dialog.querySelector('#audio-fallback-cancel');
        btnCancel.addEventListener('click', () => {
            audioElement.dataset.userAskedForFile = 'false';
            logger.log(`Usuario canceló la selección`);
            cerrarDialogo();
        });
        
        // Cerrar con ESC
        const handleEsc = (e) => {
            if (e.key === 'Escape') {
                audioElement.dataset.userAskedForFile = 'false';
                cerrarDialogo();
                document.removeEventListener('keydown', handleEsc);
            }
        };
        document.addEventListener('keydown', handleEsc);
    }

    /**
     * Carga un archivo de audio local
     */
    function cargarAudioLocal(file, filename, expectedTime) {
        try {
            // Liberar URL anterior si existe
            if (this.src && this.src.startsWith('blob:')) {
                URL.revokeObjectURL(this.src);
                logger.log(`URL anterior liberada`);
            }

            // Crear blob URL
            const blobUrl = URL.createObjectURL(file);
            logger.log(`Blob URL creado: ${blobUrl.substring(0, 50)}...`);

            // Preservar timestamp si existe
            if (expectedTime) {
                this.src = blobUrl + '#t=' + expectedTime;
                logger.log(`Audio con timestamp: ${expectedTime}`);
            } else {
                this.src = blobUrl;
            }

            // Recargar elemento de audio
            this.load();

            // Intentar reproducción automática
            if (CONFIG.AUTO_PLAY) {
                const playPromise = this.play();
                if (playPromise !== undefined) {
                    playPromise
                        .then(() => {
                            logger.log(`Reproducción iniciada correctamente`);
                        })
                        .catch(error => {
                            logger.warn(`No se pudo reproducir: ${error.message}`);
                        });
                }
            }

            // Mostrar confirmación visual
            mostrarConfirmacion(file.name);

        } catch (error) {
            logger.error(`Error al cargar archivo: ${error.message}`);
            alert(`Error al cargar el archivo: ${error.message}`);
            this.dataset.userAskedForFile = 'false';
        }
    }

    /**
     * Muestra una confirmación visual de que el archivo fue cargado
     */
    function mostrarConfirmacion(filename) {
        // Crear elemento temporal de confirmación
        const confirmDiv = document.createElement('div');
        confirmDiv.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            background: #4caf50;
            color: white;
            padding: 15px 20px;
            border-radius: 4px;
            z-index: 9999;
            box-shadow: 0 2px 8px rgba(0,0,0,0.2);
            font-family: Arial, sans-serif;
            font-size: 14px;
        `;
        confirmDiv.textContent = `✓ Reproduciéndose: ${filename}`;
        document.body.appendChild(confirmDiv);

        // Remover después de 3 segundos
        setTimeout(() => {
            confirmDiv.remove();
        }, 3000);
    }

    /**
     * API pública para debugging/control
     */
    window.AudioFallback = {
        init: init,
        setupAll: setupAudioFallback,
        debugInfo: () => {
            const audios = document.querySelectorAll('audio');
            return {
                totalAudios: audios.length,
                audios: Array.from(audios).map((a, i) => ({
                    index: i,
                    src: a.src,
                    fallbackSetup: a.dataset.audioFallbackSetup,
                    networkState: a.networkState,
                    error: a.error ? a.error.code : null
                }))
            };
        },
        getAudio: (index) => document.querySelectorAll('audio')[index],
        simulateError: (index) => {
            const audio = document.querySelectorAll('audio')[index];
            if (audio) audio.dispatchEvent(new Event('error'));
        }
    };

    // Iniciar automáticamente
    init();
})();
