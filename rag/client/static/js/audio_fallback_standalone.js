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

        // Construir mensaje
        const message = construirMensajeDialogo(audioFilename, expectedTime);

        // Mostrar diálogo
        if (confirm(message)) {
            mostrarSelectorfArchivo.call(this, audioFilename, expectedTime);
        } else {
            // Permitir reintentar
            this.dataset.userAskedForFile = 'false';
            logger.log(`Usuario canceló la selección para ${audioFilename}`);
        }
    }

    /**
     * Construye el mensaje del diálogo de confirmación
     */
    function construirMensajeDialogo(filename, timestamp) {
        let mensaje = `El archivo de audio "${filename}" no está disponible en el servidor.\n\n`;
        mensaje += `¿Tienes este archivo en tu equipo? Puedes seleccionarlo para escucharlo.`;

        if (timestamp) {
            mensaje += `\n\nSe reproducirá desde: ${timestamp}`;
        }

        return mensaje;
    }

    /**
     * Muestra el selector de archivo local
     */
    function mostrarSelectorfArchivo(filename, expectedTime) {
        const input = document.createElement('input');
        input.type = 'file';
        input.accept = 'audio/*';
        input.style.display = 'none';

        const audioElement = this;
        const audioIndex = this.dataset.audioIndex;

        // Manejador cuando selecciona un archivo
        input.addEventListener('change', (e) => {
            const file = e.target.files[0];
            if (file) {
                cargarAudioLocal.call(audioElement, file, filename, expectedTime);
                logger.log(`Archivo seleccionado para audio #${audioIndex}: ${file.name}`);
            }
            // Limpiar después de completar
            document.body.removeChild(input);
        });

        // Manejador cuando cancela
        input.addEventListener('cancel', () => {
            this.dataset.userAskedForFile = 'false';
            logger.log(`Usuario canceló la selección de archivo`);
            document.body.removeChild(input);
        });

        // Manejador para cuando se cierra el diálogo sin seleccionar
        input.addEventListener('close', () => {
            if (document.body.contains(input)) {
                document.body.removeChild(input);
            }
        });

        // Disparar diálogo de selección
        document.body.appendChild(input);
        input.click();
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
