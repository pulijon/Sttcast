    document.addEventListener('DOMContentLoaded', () => {
        // Variables globales
        const askForm = document.getElementById('askForm');
        const questionInput = document.getElementById('question');
        const languageSelect = document.getElementById('language');
        const resultsSection = document.getElementById('results');
        const searchResult = document.getElementById('searchResult');
        const refsTable = document.getElementById('refsTable');
        const errorMsg = document.getElementById('errorMsg');
        const submitBtn = askForm.querySelector('button[type=submit]');
        const submitText = document.getElementById('submitText');
        const loadingSpinner = document.getElementById('loadingSpinner');
        const micBtn = document.getElementById('micBtn');
        const micStatus = document.getElementById('micStatus');
        
        // Variables para navegación entre formularios
        const queryTypeSelection = document.getElementById('queryTypeSelection');
        const queryTypeForm = document.getElementById('queryTypeForm');
        const topicsForm = document.getElementById('topicsForm');
        const speakersForm = document.getElementById('speakersForm');
        const backToSelection = document.getElementById('backToSelection');
        const backToSelectionSpeakers = document.getElementById('backToSelectionSpeakers');
        
        // Variables para análisis de intervinientes
        const speakersAnalysisForm = document.getElementById('speakersAnalysisForm');
        const startDateInput = document.getElementById('startDate');
        const endDateInput = document.getElementById('endDate');
        const speakersSelect = document.getElementById('speakers');
        const speakersLoading = document.getElementById('speakersLoading');
        const analyzeSpeakersBtn = document.getElementById('analyzeSpeakersBtn');
        const analyzeText = document.getElementById('analyzeText');
        const analyzeSpinner = document.getElementById('analyzeSpinner');
        const chartsSection = document.getElementById('chartsSection');
        const chartsContainer = document.getElementById('chartsContainer');
        const speakersErrorMsg = document.getElementById('speakersErrorMsg');
        
        const langMap = {
                "es": "es-ES",
                "en": "en-US",
                };

        let lastData = null;
        let recognizing = false;
        let recognition;
        let retryCount = 0;
        const MAX_RETRIES = 3;
        let fontSize = 16;
        let highContrast = false;

        // Navegación entre formularios
        queryTypeForm.addEventListener('submit', (e) => {
            console.log('[queryTypeForm] submit');
            e.preventDefault();
            const selectedType = document.querySelector('input[name="queryType"]:checked');
            console.log('[queryTypeForm] selectedType =', selectedType?.value);

            
            if (!selectedType) {
                alert('Por favor, selecciona un tipo de consulta.');
                return;
            }
            
            // Ocultar sección de selección
            queryTypeSelection.classList.add('hidden');
            
            if (selectedType.value === 'topics') {
                // Mostrar formulario de consultas por temas
                topicsForm.classList.remove('hidden');
                questionInput.focus();
                } else if (selectedType.value === 'speakers') {
                // Mostrar formulario de análisis de intervinientes
                speakersForm.classList.remove('hidden');
                startDateInput.focus();

                // Establecer fechas por defecto (último mes)
                const today = new Date();
                const lastMonth = new Date();
                lastMonth.setMonth(today.getMonth() - 1);
                
                startDateInput.value = lastMonth.toISOString().split('T')[0];
                endDateInput.value = today.toISOString().split('T')[0];
            }
        });
        
        // Botones de volver atrás
        backToSelection.addEventListener('click', () => {
            topicsForm.classList.add('hidden');
            queryTypeSelection.classList.remove('hidden');
            // Limpiar formulario de temas
            questionInput.value = '';
            resultsSection.classList.add('hidden');
            errorMsg.classList.add('hidden');
        });
        
        backToSelectionSpeakers.addEventListener('click', () => {
            speakersForm.classList.add('hidden');
            queryTypeSelection.classList.remove('hidden');
            // Limpiar formulario de intervinientes
            speakersAnalysisForm.reset();
            chartsSection.classList.add('hidden');
            speakersErrorMsg.classList.add('hidden');
            speakersSelect.innerHTML = '<option value="" disabled>Selecciona primero las fechas para cargar los intervinientes</option>';
            speakersSelect.disabled = true;
            analyzeSpeakersBtn.disabled = true;
        });

// Código fuera del DOMContentLoaded - mover funciones aquí
// Gestión de cookies
function initCookies() {
    const cookieConsent = localStorage.getItem('cookieConsent');
    if (!cookieConsent) {
        document.getElementById('cookieBanner').classList.add('show');
    }
}

document.getElementById('acceptCookies').addEventListener('click', () => {
    localStorage.setItem('cookieConsent', 'accepted');
    document.getElementById('cookieBanner').classList.remove('show');
});

document.getElementById('rejectCookies').addEventListener('click', () => {
    localStorage.setItem('cookieConsent', 'rejected');
    document.getElementById('cookieBanner').classList.remove('show');
});

document.getElementById('configureCookies').addEventListener('click', () => {
    showCookieConfig();
});

// Funciones de accesibilidad
document.getElementById('increaseFontSize').addEventListener('click', () => {
    fontSize = Math.min(fontSize + 2, 24);
    document.body.style.fontSize = fontSize + 'px';
});

document.getElementById('decreaseFontSize').addEventListener('click', () => {
    fontSize = Math.max(fontSize - 2, 12);
    document.body.style.fontSize = fontSize + 'px';
});

document.getElementById('toggleContrast').addEventListener('click', () => {
    highContrast = !highContrast;
    document.body.classList.toggle('high-contrast', highContrast);
});

// Funciones de información legal
function showPrivacyPolicy() {
    alert('Política de Privacidad:\n\nEsta aplicación procesa sus consultas para proporcionar respuestas relevantes. Los datos se procesan de acuerdo con el RGPD y la LOPDGDD. Para más información, contacte con el responsable del tratamiento.');
}

function showLegalNotice() {
    alert('Aviso Legal:\n\nEsta web pertenece a José Miguel Robles Román. Uso sujeto a términos y condiciones. Para dudas legales, contacte con el administrador. - José Miguel Robles Román - NIF: 11735610-K - e-mail: webmaster@awebaos.org');
}

function showCookiePolicy() {
    alert('Política de Cookies:\n\nUtilizamos cookies técnicas necesarias para el funcionamiento de la web y cookies de análisis para mejorar la experiencia. Puede configurar sus preferencias en cualquier momento.');
}

function showAccessibilityInfo() {
    alert('Información de Accesibilidad:\n\nEsta web cumple con las Pautas WCAG 2.1 nivel AA. Dispone de controles de accesibilidad, navegación por teclado y compatibilidad con lectores de pantalla. Para reportar problemas de accesibilidad, contacte con soporte.');
}

function showCookieConfig() {
    alert('Configuración de Cookies:\n\nCookies técnicas: Necesarias (no se pueden desactivar)\nCookies de análisis: Pueden activarse/desactivarse\nCookies de personalización: Pueden activarse/desactivarse');
}

languageSelect.addEventListener('change', () => {
    if (lastData) {
        showResults(lastData, languageSelect.value);
    }
});

// Envío del formulario
askForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    console.log('FORM SUBMITTED - Starting request...');

    // Occultar mensajes anteriores
    errorMsg.classList.add('hidden');
    resultsSection.classList.add('hidden');
    searchResult.innerHTML = '';
    refsTable.innerHTML = '';

        const question = questionInput.value.trim();
        const language = languageSelect.value;

        if (!question) {
            errorMsg.textContent = 'Por favor, introduce una pregunta.';
            errorMsg.classList.remove('hidden');
            return;
        }

        // Mostrar estado de carga
        setLoadingState(true);

        // Prevenir que se active el protector de pantalla durante la consulta
        let wakeLock = null;
        try {
            if ('wakeLock' in navigator) {
                wakeLock = await navigator.wakeLock.request('screen');
            }
        } catch (err) {
            console.log('Wake Lock no disponible:', err);
        }

        try {
            console.log('SENDING REQUEST with question:', question);
            const response = await fetch("/api/ask", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({question, language})
            });
            console.log('RESPONSE STATUS:', response.status);
            if (!response.ok) {
                const errorData = await response.json().catch(()=>{});
                throw new Error(errorData?.detail || errorData?.error || "Error en la consulta");
            }
            const data = await response.json();
            console.log('DATA RECEIVED:', data);
            lastData = data;
            showResults(data, language);

            // Check if query field exists and log for debugging
            console.log('Checking for query field:', data.query, 'Type:', typeof data.query);
            
            // If response contains a query field, replace the question in the form
            if (data.query) {
                console.log('History query detected:', data.query);
                const timestamp = new Date(data.timestamp).toLocaleString();
                const newValue = `${timestamp} - ${data.query}`;
                console.log('Setting question input to:', newValue);
                
                // Use setTimeout to ensure the DOM is updated
                setTimeout(() => {
                    const questionField = document.getElementById('question');
                    if (questionField) {
                        questionField.value = newValue;
                        console.log('Question input updated to:', questionField.value);
                    } else {
                        console.error('Question input field not found!');
                    }
                }, 150);
            } else {
                console.log('No query field found or query field is falsy');
            }

        } catch (error) {
            errorMsg.textContent = error.message || "No se pudo completar la consulta";
            errorMsg.classList.remove('hidden');
        } finally {
            // Liberar el wake lock
            if (wakeLock) {
                wakeLock.release();
            }
            
            askForm.querySelector('button[type=submit]').disabled = false;
            askForm.querySelector('button[type=submit]').textContent = 'Consultar';
        }
    });

    // Configurar reconocimiento de voz dentro del DOMContentLoaded
    if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
        micBtn.addEventListener('click', startRecognition);
        micBtn.setAttribute('aria-pressed', 'false');
        
        // Configurar botón de diagnóstico
        const micDiagnosticBtn = document.getElementById('micDiagnosticBtn');
        if (micDiagnosticBtn) {
            micDiagnosticBtn.addEventListener('click', showVoiceDiagnostics);
        }
        
        languageSelect.addEventListener('change', () => {
            if (recognition) {
                recognition.lang = langMap[languageSelect.value];
            }
        });
    } else {
        micBtn.disabled = true;
        micBtn.title = "El navegador no soporta reconocimiento de voz";
        micBtn.setAttribute('aria-label', 'Reconocimiento de voz no disponible');
    }

    // Navegación por teclado mejorada
    document.addEventListener('keydown', (e) => {
        // Ctrl + Enter para enviar formulario
        if (e.ctrlKey && e.key === 'Enter' && document.activeElement === questionInput) {
            askForm.dispatchEvent(new Event('submit'));
        }
        
        // Escape para cerrar banner de cookies
        if (e.key === 'Escape' && document.getElementById('cookieBanner').classList.contains('show')) {
            document.getElementById('cookieBanner').classList.remove('show');
        }
    });

    // Inicialización de cookies
    initCookies();

    // Funciones de utilidad dentro del scope del DOMContentLoaded
    let countdownInterval = null;
    
    function setLoadingState(loading) {
        submitBtn.disabled = loading;
        if (loading) {
            let countdown = 59;
            // Mantener el spinner visible pero ajustar el texto para que sea más claro
            loadingSpinner.classList.remove('hidden');
            submitText.textContent = `Consultando ... (${countdown}s)`;
            submitBtn.setAttribute('aria-busy', 'true');
            
            // Limpiar cualquier intervalo anterior
            if (countdownInterval) {
                clearInterval(countdownInterval);
            }
            
            // Iniciar cuenta atrás
            countdownInterval = setInterval(() => {
                countdown--;
                if (countdown >= 0) {
                    submitText.textContent = `Consultando ... (${countdown}s)`;
                } else {
                    // Si llega a 0, mostrar puntos suspensivos
                    submitText.textContent = '...';
                    clearInterval(countdownInterval);
                    countdownInterval = null;
                }
            }, 1000);
        } else {
            submitText.textContent = 'Consultar';
            loadingSpinner.classList.add('hidden');
            submitBtn.setAttribute('aria-busy', 'false');
            
            // Limpiar el intervalo cuando se detiene la carga
            if (countdownInterval) {
                clearInterval(countdownInterval);
                countdownInterval = null;
            }
        }
    }

    function showError(message) {
        errorMsg.textContent = message;
        errorMsg.classList.remove('hidden');
        errorMsg.focus();
    }

    function formatTime(seconds) {
        const mins = Math.floor(seconds / 60);
        const secs = Math.round(seconds % 60);
        return `${mins}:${secs.toString().padStart(2, '0')}`;
    }

    function showResults(data, lang) {
    console.log("Datos a mostrar:", data, lang);

    searchResult.innerHTML = data.response[lang] || "No hay respuesta para este idioma.";

    refsTable.innerHTML = '';
    if (data.references && data.references.length > 0) {
        data.references.forEach(ref => {
            const linkText = ref.file;
            let linkUrl = (ref.hyperlink && ref.hyperlink[lang]) ? ref.hyperlink[lang] : '';
            let linkHtml = linkUrl
                ? `<a class="text-blue-600 underline" href="${linkUrl}" target="_blank">${linkText}</a>`
                : `<span class="text-gray-400">${linkText}</span>`;
            refsTable.innerHTML += `
                <tr>
                    <td class="px-4 py-2 border-b">${ref.tag || ""}</td>
                    <td class="px-4 py-2 border-b">${ref.label && ref.label[lang] ? ref.label[lang] : ""}</td>
                    <td class="px-4 py-2 border-b">${linkHtml}</td>
                    <td class="px-4 py-2 border-b">${formatTime(ref.time)}</td>
                </tr>
            `;
        });
    } else {
        refsTable.innerHTML = `<tr><td colspan="4" class="px-4 py-2 text-gray-400">No hay referencias.</td></tr>`;
    }

    resultsSection.classList.remove('hidden');
    
    // Hacer scroll automático a los resultados y anunciar que están listos
    setTimeout(() => {
        resultsSection.scrollIntoView({ 
            behavior: 'smooth',
            block: 'start'
        });
        // Dar tiempo al scroll antes de hacer focus
        setTimeout(() => {
            searchResult.focus();
        }, 300);
    }, 100);
}

    function createRecognition() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
        return null;
    }
    
    try {
        const recog = new SpeechRecognition();
        recog.lang = langMap[languageSelect.value];
        recog.interimResults = true;
        recog.maxAlternatives = 1;
        recog.continuous = false; // Solo un resultado por click
        
        console.log(`[VoiceRecognition] Reconocimiento creado con idioma: ${recog.lang}`);
        return recog;
    } catch (error) {
        console.error('[VoiceRecognition] Error al crear reconocimiento:', error);
        return null;
    }
}

    function startRecognition(isRetry = false) {
    // Prevenir clics múltiples
    if (recognizing && !isRetry) {
        console.log('[VoiceRecognition] Ya está reconociendo, ignorando clic');
        return;
    }
    
    // Si hay un reconocimiento activo, detenerlo primero
    if (recognition && !isRetry) {
        console.log('[VoiceRecognition] Deteniendo reconocimiento activo');
        try {
            recognition.abort();
        } catch (e) {
            console.log('[VoiceRecognition] Error al abortar reconocimiento:', e);
        }
        recognition = null;
        recognizing = false;
        micBtn.classList.remove('bg-green-200');
        micBtn.setAttribute('aria-pressed', 'false');
        micStatus.textContent = '';
        return;
    }
    
    // Función interna para inicializar el reconocimiento
    const initializeRecognition = () => {
        if (!isRetry) {
            retryCount = 0;
        }
        
        // Crear nuevo reconocimiento
        recognition = createRecognition();
        if (!recognition) {
            showError('El reconocimiento de voz no está disponible en este navegador');
            return;
        }

        // Intentar iniciar directamente
        try {
            console.log('[VoiceRecognition] Iniciando reconocimiento...');
            recognizing = true; // Marcar como reconociendo antes de start()
            recognition.start();
        } catch (error) {
            console.error('[VoiceRecognition] Error al iniciar reconocimiento:', error);
            recognizing = false; // Resetear estado en caso de error
            recognition = null;
            micStatus.textContent = '';
            showError(`Error al iniciar reconocimiento: ${error.message}`);
        }
    };

    // Asegurar estado limpio
    recognizing = false; // Resetear estado antes de crear nuevo reconocimiento
    
    if (recognition) {
        try {
            console.log('[VoiceRecognition] Abortando reconocimiento anterior...');
            recognition.abort();
            recognition = null; // Limpiar referencia
            // Esperar a que el abort surta efecto antes de crear nuevo reconocimiento
            setTimeout(initializeRecognition, 100);
        } catch (e) {
            console.log('[VoiceRecognition] No se pudo abortar reconocimiento anterior, creando nuevo');
            recognition = null; // Limpiar referencia
            initializeRecognition();
        }
    } else {
        initializeRecognition();
    }

    recognition.onstart = () => {
        recognizing = true;
        micBtn.classList.add('bg-green-200');
        micBtn.setAttribute('aria-pressed', 'true');
        micStatus.textContent = '🎤 Escuchando... Habla ahora';
        console.log('[VoiceRecognition] Reconocimiento iniciado correctamente');
    };
    
    recognition.onend = () => {
        recognizing = false;
        recognition = null; // Limpiar referencia cuando termine
        micBtn.classList.remove('bg-green-200');
        micBtn.setAttribute('aria-pressed', 'false');
        micStatus.textContent = '';
        console.log('[VoiceRecognition] Reconocimiento terminado');
    };
    
    recognition.onerror = (event) => {
        recognizing = false;
        micBtn.classList.remove('bg-green-200');
        micBtn.setAttribute('aria-pressed', 'false');
        micStatus.textContent = '';
        
        // Limpiar referencia del reconocimiento con error
        if (recognition) {
            recognition = null;
        }
        
        console.error('[VoiceRecognition] Error:', event.error, event);
        
        let errorMessage = 'Error en el reconocimiento de voz';
        let suggestion = '';
        
        switch(event.error) {
            case 'not-allowed':
                errorMessage = '🚫 Acceso al micrófono denegado';
                suggestion = 'Permite el acceso al micrófono en la configuración del navegador. Haz clic en el botón de diagnóstico (ℹ️) para más detalles.';
                break;
            case 'no-speech':
                errorMessage = '🔇 No se detectó discurso';
                suggestion = 'Intenta hablar más cerca del micrófono y con más claridad.';
                break;
            case 'network':
                errorMessage = '🌐 Error de conexión';
                suggestion = 'Verifica tu conexión a internet. El reconocimiento de voz requiere conexión.';
                break;
            case 'audio-capture':
                // Desactivar reintentos automáticos temporalmente para evitar bucles
                // if (retryCount < MAX_RETRIES) {
                //     retryCount++;
                //     console.log(`[VoiceRecognition] Reintento ${retryCount}/${MAX_RETRIES} para audio-capture`);
                //     micStatus.textContent = `🔄 Reintentando... (${retryCount}/${MAX_RETRIES})`;
                //     
                //     // Esperar un poco antes del reintento
                //     setTimeout(() => {
                //         startRecognition(true);
                //     }, 1000 + (retryCount * 500)); // Delay incremental
                //     return; // No mostrar error aún
                // }
                errorMessage = '🎤 Error de captura de audio';
                suggestion = 'No se pudo acceder al micrófono. Este PC puede tener problemas específicos con el reconocimiento de voz web. Usa el diagnóstico (ℹ️) para más información técnica.';
                break;
            case 'aborted':
                errorMessage = '⏹️ Reconocimiento cancelado';
                suggestion = 'El reconocimiento se canceló. Puedes intentar de nuevo.';
                break;
            case 'bad-grammar':
                errorMessage = '📝 Error de gramática';
                suggestion = 'Hubo un problema con la configuración del reconocimiento. Intenta de nuevo.';
                break;
            case 'language-not-supported':
                errorMessage = '🌍 Idioma no soportado';
                suggestion = `El idioma seleccionado no está disponible. Cambia el idioma en el selector.`;
                break;
            case 'service-not-allowed':
                errorMessage = '🔒 Servicio no permitido';
                suggestion = 'El servicio de reconocimiento de voz no está disponible. Verifica que estés en HTTPS.';
                break;
            default:
                errorMessage = `❌ Error desconocido: ${event.error}`;
                suggestion = 'Error no identificado. Usa el botón de diagnóstico (ℹ️) para obtener más información técnica.';
                break;
        }
        
        // Mostrar error con sugerencia
        showError(`${errorMessage}\n\n💡 ${suggestion}`);
        
        // Log adicional para debugging
        console.log('[VoiceRecognition] Contexto del error:', {
            error: event.error,
            isSecure: location.protocol === 'https:',
            hasPermissions: 'permissions' in navigator,
            hasMediaDevices: 'mediaDevices' in navigator,
            userAgent: navigator.userAgent
        });
    };
    
    recognition.onresult = (event) => {
        const transcript = event.results[0][0].transcript;
        questionInput.value = transcript;
        questionInput.focus();
        micStatus.textContent = `Texto detectado: "${transcript}"`;
    };

    recognition.lang = langMap[languageSelect.value];
}

// Función de diagnóstico del reconocimiento de voz
async function showVoiceDiagnostics() {
    console.log('[VoiceDiagnostics] Iniciando diagnóstico...');
    
    let diagnostics = ['=== DIAGNÓSTICO DE RECONOCIMIENTO DE VOZ ===\n'];
    
    // 1. Verificar soporte del navegador
    const hasWebkitSpeech = 'webkitSpeechRecognition' in window;
    const hasSpeech = 'SpeechRecognition' in window;
    diagnostics.push(`✓ Navegador: ${navigator.userAgent}`);
    diagnostics.push(`✓ webkitSpeechRecognition: ${hasWebkitSpeech ? 'SÍ' : 'NO'}`);
    diagnostics.push(`✓ SpeechRecognition: ${hasSpeech ? 'SÍ' : 'NO'}`);
    
    // 2. Verificar HTTPS
    const isSecure = location.protocol === 'https:' || location.hostname === 'localhost';
    diagnostics.push(`✓ Conexión segura (HTTPS): ${isSecure ? 'SÍ' : 'NO - REQUERIDO!'}`);
    
    // 3. Verificar permisos
    if (navigator.permissions) {
        try {
            const result = await navigator.permissions.query({ name: 'microphone' });
            diagnostics.push(`✓ Permiso micrófono: ${result.state}`);
        } catch {
            diagnostics.push(`✓ Permiso micrófono: No se pudo verificar`);
        }
    } else {
        diagnostics.push(`✓ API de permisos: No disponible`);
    }
    
    // 4. Verificar dispositivos de audio
    if (navigator.mediaDevices && navigator.mediaDevices.enumerateDevices) {
        try {
            const devices = await navigator.mediaDevices.enumerateDevices();
            const audioInputs = devices.filter(device => device.kind === 'audioinput');
            diagnostics.push(`✓ Dispositivos de audio encontrados: ${audioInputs.length}`);
            audioInputs.forEach((device, index) => {
                diagnostics.push(`  - ${index + 1}: ${device.label || 'Dispositivo desconocido'}`);
            });
        } catch (error) {
            diagnostics.push(`✗ Error al obtener dispositivos: ${error.message}`);
        }
    } else {
        diagnostics.push(`✗ API de dispositivos multimedia no disponible`);
    }
    
    // 5. Probar acceso al micrófono
    if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            diagnostics.push(`✓ Acceso al micrófono: EXITOSO`);
            stream.getTracks().forEach(track => track.stop()); // Liberar recursos
        } catch (error) {
            diagnostics.push(`✗ Error de acceso al micrófono: ${error.name} - ${error.message}`);
        }
    } else {
        diagnostics.push(`✗ getUserMedia no disponible`);
    }
    
    // Mostrar resultado UNA SOLA VEZ al final
    showDiagnosticsResult(diagnostics);
}

function showDiagnosticsResult(diagnostics) {
    const result = diagnostics.join('\n');
    console.log(result);
    
    // Crear un modal o alert mejorado
    const modal = document.createElement('div');
    modal.className = 'fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50';
    modal.innerHTML = `
        <div class="bg-white p-6 rounded-lg max-w-2xl max-h-96 overflow-y-auto">
            <h3 class="text-lg font-bold mb-4">Diagnóstico de Reconocimiento de Voz</h3>
            <pre class="text-sm bg-gray-100 p-4 rounded overflow-x-auto whitespace-pre-wrap">${result}</pre>
            <div class="mt-4 text-sm text-gray-600">
                <strong>Problemas comunes:</strong><br>
                • Si no tienes HTTPS, el reconocimiento no funcionará<br>
                • Verifica que has dado permisos al micrófono<br>
                • Algunos navegadores requieren interacción del usuario antes del primer uso<br>
                • En Chrome, prueba con Chrome://settings/content/microphone
            </div>
            <button onclick="this.parentElement.parentElement.remove()" 
                    class="mt-4 bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600">
                Cerrar
            </button>
        </div>
    `;
    document.body.appendChild(modal);
    
    // Cerrar al hacer clic fuera
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            modal.remove();
        }
    });
}

// Mejoras de rendimiento y SEO
if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
        navigator.serviceWorker.register('/sw.js')
            .then(registration => console.log('[ServiceWorker] Registrado correctamente'))
            .catch(error => {
                // Service Worker es opcional, no mostrar error si no existe
                console.debug('[ServiceWorker] No disponible:', error.message);
            });
    });
}

        // Cargar intervinientes cuando cambien las fechas
        function loadSpeakers() {
            const startDate = startDateInput.value;
            const endDate = endDateInput.value;
            
            if (!startDate || !endDate) {
            speakersSelect.innerHTML = '<option value="" disabled>Selecciona primero las fechas para cargar los intervinientes</option>';
            speakersSelect.disabled = true;
            analyzeSpeakersBtn.disabled = true;
            return;
            }
            
            if (new Date(startDate) > new Date(endDate)) {
            alert('La fecha de inicio debe ser anterior a la fecha de fin.');
            return;
            }
            
            // Mostrar indicador de carga
            speakersLoading.classList.remove('hidden');
            speakersSelect.disabled = true;
            console.log('[loadSpeakers] Cargando intervinientes para el período', startDate, 'a', endDate);
            
            // Llamada real a la api gen_stats para obtener intervinientes
            fetch('/api/gen_stats', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                fromdate: startDate,
                todate: endDate
            })
            })
            .then(response => {
            if (!response.ok) {
                throw new Error('Error al obtener estadísticas generales');
            }
            return response.json();
            })
            .then(data => {
            // Mostrar estadísticas generales
            const statsHtml = `
                <div class="bg-blue-50 p-4 rounded-lg mb-4">
                <h4 class="font-semibold mb-2">Estadísticas del período seleccionado:</h4>
                <div class="grid grid-cols-1 md:grid-cols-3 gap-4 text-sm stats-grid">
                    <div class="text-center stats-item">
                    <div class="text-2xl font-bold text-blue-600">${data.total_episodes}</div>
                    <div class="text-gray-600">Episodios totales</div>
                    </div>
                    <div class="text-center stats-item">
                    <div class="text-2xl font-bold text-blue-600">${data.speakers.length}</div>
                    <div class="text-gray-600">Intervinientes</div>
                    </div>
                    <div class="text-center stats-item">
                    <div class="text-2xl font-bold text-blue-600">${Math.round(data.total_duration / 3600)}</div>
                    <div class="text-gray-600">Horas totales</div>
                    </div>
                </div>
                </div>
            `;
            
            // Insertar estadísticas antes del selector de intervinientes
            const statsContainer = document.getElementById('generalStats') || (() => {
                const container = document.createElement('div');
                container.id = 'generalStats';
                speakersSelect.parentNode.insertBefore(container, speakersSelect.parentNode.firstChild);
                return container;
            })();
            statsContainer.innerHTML = statsHtml;
            
            // Llenar el selector de intervinientes con información detallada
            speakersSelect.innerHTML = '';
            data.speakers.forEach(speaker => {
                const option = document.createElement('option');
                option.value = speaker.tag;
                
                // Formatear tiempo total de intervenciones
                const totalHours = Math.floor(speaker.total_duration / 3600);
                const totalMinutes = Math.floor((speaker.total_duration % 3600) / 60);
                const timeFormatted = totalHours > 0 
                ? `${totalHours}h ${totalMinutes}m`
                : `${totalMinutes}m`;
                
                option.textContent = `${speaker.tag} (${speaker.total_episodes} episodios, ${timeFormatted})`;
            
                speakersSelect.appendChild(option);
            });
            
            speakersSelect.disabled = false;
            speakersLoading.classList.add('hidden');
            analyzeSpeakersBtn.disabled = false;
            
            // Actualizar texto de ayuda con límite de selección
            const helpText = document.getElementById('speakers-help');
            helpText.textContent = 'Mantén presionado Ctrl (Cmd en Mac) para seleccionar múltiples intervinientes.';
            })
            .catch(error => {
            speakersErrorMsg.textContent = error.message || 'Error al cargar los intervinientes';
            speakersErrorMsg.classList.remove('hidden');
            speakersLoading.classList.add('hidden');
            });
        }
        
        // Event listeners para cargar intervinientes cuando cambien las fechas
        startDateInput.addEventListener('change', loadSpeakers);
        endDateInput.addEventListener('change', loadSpeakers);
        
        // Limitar selección múltiple a 10 intervinientes
        speakersSelect.addEventListener('change', function() {
            const selected = Array.from(this.selectedOptions);
            // if (selected.length > 10) {
            // // Deseleccionar el último elemento seleccionado
            // selected[selected.length - 1].selected = false;
            // alert('Solo puedes seleccionar un máximo de 10 intervinientes.');
            // }
            
            // Habilitar/deshabilitar botón según selección
            analyzeSpeakersBtn.disabled = selected.length === 0;
            
            // Actualizar visualización de intervinientes seleccionados
            updateSelectedSpeakersDisplay();
        });
        
        // Función para mostrar los intervinientes seleccionados
        function updateSelectedSpeakersDisplay() {
            const selectedDisplay = document.getElementById('selectedSpeakersDisplay');
            const selectedList = document.getElementById('selectedSpeakersList');
            const selected = Array.from(speakersSelect.selectedOptions);
            
            if (selected.length === 0) {
                selectedDisplay.classList.add('hidden');
                return;
            }
            
            selectedDisplay.classList.remove('hidden');
            selectedList.innerHTML = '';
            
            selected.forEach(option => {
                const tag = document.createElement('span');
                tag.className = 'inline-block bg-blue-100 text-blue-800 px-2 py-1 rounded-full text-xs font-medium';
                tag.textContent = option.textContent;
                selectedList.appendChild(tag);
            });
        }
    });


    // Código para análisis de intervinientes
    // Manejador del formulario de análisis de intervinientes
document.getElementById('speakersAnalysisForm').addEventListener('submit', function(e) {
    e.preventDefault();
    
    const startDate = document.getElementById('startDate').value;
    const endDate = document.getElementById('endDate').value;
    const speakersSelect = document.getElementById('speakers');
    const selectedSpeakers = Array.from(speakersSelect.selectedOptions).map(option => option.value);
    
    if (selectedSpeakers.length === 0) {
        alert('Debes seleccionar al menos un interviniente.');
        return;
    }
    
    // Mostrar indicador de carga
    const analyzeBtn = document.getElementById('analyzeSpeakersBtn');
    const analyzeText = document.getElementById('analyzeText');
    const analyzeSpinner = document.getElementById('analyzeSpinner');
    const speakersErrorMsg = document.getElementById('speakersErrorMsg');
    
    analyzeBtn.disabled = true;
    analyzeText.textContent = 'Analizando...';
    analyzeSpinner.classList.remove('hidden');
    speakersErrorMsg.classList.add('hidden');
    
    console.log('[speakersAnalysis] Enviando solicitud para intervinientes:', selectedSpeakers);
    console.log('[speakersAnalysis] Período:', startDate, 'a', endDate);
    
    // Llamada al endpoint de análisis de intervinientes
    fetch('/api/speaker_stats', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            tags: selectedSpeakers,
            fromdate: startDate,
            todate: endDate
        })
    })
    .then(response => {
        if (!response.ok) {
            throw new Error('Error al obtener estadísticas de intervinientes');
        }
        return response.json();
    })
    .then(data => {
        console.log('[speakersAnalysis] Datos recibidos:', data);
        
        // Mostrar las gráficas con los datos obtenidos
	// Inclusión de campo link en episodes
	data.stats.forEach(speaker => {
        speaker.episodes = speaker.episodes.map(ep => ({
              ...ep,
              link: `<a href="transcripts/${ep.name}_whisper_audio_es.html">${ep.name}</a>`
           }));
        });

        displaySpeakersCharts(data);
        // Mostrar la sección de gráficas
        document.getElementById('chartsSection').classList.remove('hidden');
        
        // Hacer scroll hasta las gráficas
        document.getElementById('chartsSection').scrollIntoView({ 
            behavior: 'smooth' 
        });
    })
    .catch(error => {
        console.error('[speakersAnalysis] Error:', error);
        speakersErrorMsg.textContent = error.message || 'Error al generar el análisis de intervinientes';
        speakersErrorMsg.classList.remove('hidden');
    })
    .finally(() => {
        // Restaurar botón
        analyzeBtn.disabled = false;
        analyzeText.textContent = 'Generar análisis';
        analyzeSpinner.classList.add('hidden');
    });
});

function displaySpeakersCharts(data) {
    const chartsContainer = document.getElementById('chartsContainer');
    chartsContainer.innerHTML = '';
    
    // Crear gráfica de total de intervenciones por interviniente
    // const interventionsData = data.stats.map(speaker => ({
    //    name: speaker.tag,
    //    value: speaker.total_interventions,
    //    episodes: speaker.total_episodes_in_period,
    //    duration: Math.round(speaker.total_duration / 60) // en minutos
    //}));
    
    // Gráfica de barras para total de intervenciones
    // const interventionsChart = createBarChart(
    //    'Número total de intervenciones por interviniente',
    //    interventionsData,
    //    'Intervenciones',
    //    '#3B82F6'
    //);
    // chartsContainer.appendChild(interventionsChart);

    
    // Crear gráfica de episodios por interviniente
    const episodesData = data.stats.map(speaker => ({
        name: speaker.tag,
        value: speaker.episodes.length,
        // interventions: speaker.total_interventions,
        duration: Math.round(speaker.total_duration / 60)
    }));

    const episodesChart = createBarChart(
        'Número de episodios con participación por interviniente',
        episodesData,
        'Episodios',
        '#F59E0B'
    );
    chartsContainer.appendChild(episodesChart);
 
        // Crear gráfica de duración total por interviniente
    const durationData = data.stats.map(speaker => ({
        name: speaker.tag,
        value: Math.round(speaker.episodes.reduce((sum, ep) => sum + ep.duration, 0) / 60), // en minutos
        // interventions: speaker.total_interventions,
        episodes: speaker.total_episodes_in_period
    }));
    
    const durationChart = createBarChart(
        'Tiempo total de intervención por interviniente (minutos)',
        durationData,
        'Minutos',
        '#10B981'
    );
    chartsContainer.appendChild(durationChart);

    // Crear gráfica de tiempo promedio por intervención
    //const avgDurationData = data.stats.map(speaker => ({
    //    name: speaker.tag,
    //    value: speaker.total_interventions > 0 
    //        ? Math.round((speaker.total_duration / speaker.total_interventions) / 60 * 100) / 100 
    //        : 0,
    //    total_interventions: speaker.total_interventions,
    //    total_duration: Math.round(speaker.total_duration / 60)
    //}));

    //const avgDurationChart = createBarChart(
    //    'Duración promedio por intervención (minutos)',
    //    avgDurationData,
    //    'Minutos promedio',
    //    '#8B5CF6'
    //);
    //chartsContainer.appendChild(avgDurationChart);
    
    // Cear gráfico de línea de tiempo
    const timeLineChart = createTimeLineChart(data.stats);
    chartsContainer.appendChild(timeLineChart);
    
    // Crear tabla de detalles por episodio para cada interviniente
    if (data.stats.length <= 20) { // Solo mostrar detalles si hay pocos intervinientes seleccionados
        data.stats.forEach(speaker => {
            if (speaker.episodes && speaker.episodes.length > 0) {
                const detailsTable = createSpeakerEpisodesTable(speaker);
                chartsContainer.appendChild(detailsTable);
            }
        });
    } else {
        // Mostrar mensaje informativo
        const infoDiv = document.createElement('div');
        infoDiv.className = 'bg-blue-50 p-4 rounded-lg mt-6';
        infoDiv.innerHTML = `
            <p class="text-blue-800 text-sm">
                <strong>Nota:</strong> Se han seleccionado ${data.stats.length} intervinientes (demasiados para mostrar detalles).
            </p>
        `;
        chartsContainer.appendChild(infoDiv);
    }
}

// Función auxiliar para crear gráficas de barras
// function createBarChart(title, data, yLabel, color) {
//     const chartDiv = document.createElement('div');
//     chartDiv.className = 'bg-white p-6 rounded-lg border shadow-sm overflow-visible';
//     
//     const chartTitle = document.createElement('h4');
//     chartTitle.className = 'text-lg font-semibold mb-4 text-gray-800';
//     chartTitle.textContent = title;
//     chartDiv.appendChild(chartTitle);
//     
//     const canvas = document.createElement('canvas');
//     canvas.className = 'w-full'
//     // canvas.className = 'w-[85%]'
//     chartDiv.appendChild(canvas);
//     
//     // Crear gráfica usando Canvas API (implementación básica)
//     setTimeout(() => {
//         const containerWidth = chartDiv.offsetWidth - 48; // Restar padding
//         canvas.width = containerWidth;
//         canvas.height = Math.max(400, data.length * 50); // Altura dinámica para barras horizontales
// 
//         // Crear gráfica usando Canvas API con barras horizontales
//         const ctx = canvas.getContext('2d');
//         const padding = 80;
//         const chartWidth = canvas.width - 2 * padding;
//         const chartHeight = canvas.height - 2 * padding;
// 
//         if (data.length === 0) {
//             ctx.fillStyle = '#6B7280';
//             ctx.font = '16px Arial';
//             ctx.textAlign = 'center';
//             ctx.fillText('No hay datos para mostrar', canvas.width / 2, canvas.height / 2);
//             return;
//         }
// 
//         const maxValue = Math.max(...data.map(d => d.value));
//         const barHeight = (chartHeight / data.length) * 0.7;
//         const barSpacing = (chartHeight / data.length) * 0.3;
//         
//         // Ordenar datos de mayor a menor
//         data.sort((a, b) => b.value - a.value);
//         
//         // Dibujar barras horizontales
//         data.forEach((item, index) => {
//             const barWidth = (item.value / maxValue) * chartWidth * 0.9;
//             const x = padding;
//             const y = padding + index * (barHeight + barSpacing) + barSpacing / 2;
// 
//             // Barra
//             ctx.fillStyle = color;
//             ctx.fillRect(x, y, barWidth, barHeight);
// 
//             // Valor al final de la barra
//             ctx.fillStyle = '#374151';
//             ctx.font = '12px Arial';
//             ctx.textAlign = 'left';
//             ctx.fillText(item.value.toString(), x + barWidth + 5, y + barHeight / 2 + 4);
// 
//             // Etiqueta del eje Y (nombres a la izquierda)
//             ctx.textAlign = 'right';
//             ctx.fillText(item.name, padding - 10, y + barHeight / 2 + 4);
//         });
// 
//         // Eje X (horizontal en la parte inferior)
//         ctx.strokeStyle = '#D1D5DB';
//         ctx.lineWidth = 1;
//         ctx.beginPath();
//         ctx.moveTo(padding, canvas.height - padding);
//         ctx.lineTo(canvas.width - padding, canvas.height - padding);
//         ctx.stroke();
// 
//         // Eje Y (vertical a la izquierda)
//         ctx.beginPath();
//         ctx.moveTo(padding, padding);
//         ctx.lineTo(padding, canvas.height - padding);
//         ctx.stroke();
// 
//         // Etiqueta eje X (abajo)
//         ctx.fillStyle = '#6B7280';
//         ctx.font = '14px Arial';
//         ctx.textAlign = 'center';
//         ctx.fillText(yLabel, canvas.width / 2, canvas.height - padding + 40);
//     }, 100);
//     return chartDiv;
// }

function createBarChart(title, data, yLabel, color) {
    const chartDiv = document.createElement('div');
    chartDiv.className = 'bg-white p-3 rounded-lg border shadow-sm overflow-visible'; // Reducido p-6 a p-3
    
    const chartTitle = document.createElement('h4');
    chartTitle.className = 'text-lg font-semibold mb-4 text-gray-800';
    chartTitle.textContent = title;
    chartDiv.appendChild(chartTitle);
    
    const canvas = document.createElement('canvas');
    canvas.className = 'w-full'
    chartDiv.appendChild(canvas);
    
    // Crear gráfica usando Canvas API (implementación básica)
    setTimeout(() => {
        const containerWidth = chartDiv.offsetWidth - 24; // Reducido desde 48 a 24
        canvas.width = containerWidth;
        canvas.height = Math.max(400, data.length * 50); // Altura dinámica para barras horizontales

        // Crear gráfica usando Canvas API con barras horizontales
        const ctx = canvas.getContext('2d');
        
        // Calcular el ancho máximo de las etiquetas
        ctx.font = '12px Arial';
        const maxLabelWidth = Math.max(...data.map(d => ctx.measureText(d.name).width));
        
        const paddingLeft = Math.max(80, maxLabelWidth + 10); // Reducido desde 120 y 20 a 80 y 10
        const paddingRight = 30; // Reducido desde 60 a 30
        const paddingTop = 40;
        const paddingBottom = 60;
        
        const chartWidth = canvas.width - paddingLeft - paddingRight;
        const chartHeight = canvas.height - paddingTop - paddingBottom;

        if (data.length === 0) {
            ctx.fillStyle = '#6B7280';
            ctx.font = '16px Arial';
            ctx.textAlign = 'center';
            ctx.fillText('No hay datos para mostrar', canvas.width / 2, canvas.height / 2);
            return;
        }

        const maxValue = Math.max(...data.map(d => d.value));
        const barHeight = (chartHeight / data.length) * 0.7;
        const barSpacing = (chartHeight / data.length) * 0.3;
        
        // Ordenar datos de mayor a menor
        data.sort((a, b) => b.value - a.value);
        
        // Dibujar barras horizontales
        data.forEach((item, index) => {
            const barWidth = (item.value / maxValue) * chartWidth * 0.9;
            const x = paddingLeft;
            const y = paddingTop + index * (barHeight + barSpacing) + barSpacing / 2;

            // Barra
            ctx.fillStyle = color;
            ctx.fillRect(x, y, barWidth, barHeight);

            // Valor al final de la barra
            ctx.fillStyle = '#374151';
            ctx.font = '12px Arial';
            ctx.textAlign = 'left';
            ctx.fillText(item.value.toString(), x + barWidth + 5, y + barHeight / 2 + 4);

            // Etiqueta del eje Y (nombres a la izquierda)
            ctx.textAlign = 'right';
            ctx.fillText(item.name, paddingLeft - 10, y + barHeight / 2 + 4);
        });

        // Eje X (horizontal en la parte inferior)
        ctx.strokeStyle = '#D1D5DB';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(paddingLeft, canvas.height - paddingBottom);
        ctx.lineTo(canvas.width - paddingRight, canvas.height - paddingBottom);
        ctx.stroke();

        // Eje Y (vertical a la izquierda)
        ctx.beginPath();
        ctx.moveTo(paddingLeft, paddingTop);
        ctx.lineTo(paddingLeft, canvas.height - paddingBottom);
        ctx.stroke();

        // Etiqueta eje X (abajo)
        ctx.fillStyle = '#6B7280';
        ctx.font = '14px Arial';
        ctx.textAlign = 'center';
        ctx.fillText(yLabel, paddingLeft + chartWidth / 2, canvas.height - paddingBottom + 40);
    }, 100);
    return chartDiv;
}

// Función para crear gráfico de línea de tiempo
function createTimeLineChart(stats) {
    const chartDiv = document.createElement('div');
    chartDiv.className = 'bg-white p-3 rounded-lg border shadow-sm mt-6 overflow-visible'; // Reducido p-6 a p-3

    const chartTitle = document.createElement('h4');
    chartTitle.className = 'text-lg font-semibold mb-4 text-gray-800';
    chartTitle.textContent = 'Línea de tiempo de episodios e intervenciones';
    chartDiv.appendChild(chartTitle);

    const canvas = document.createElement('canvas');
    canvas.className = 'w-full';
    canvas.style.display = 'block'; // Asegurar que no haya espacio extra
    chartDiv.appendChild(canvas);

    setTimeout(() => {
        // Recopilar todos los episodios únicos con sus fechas
        const episodesMap = new Map();
        const speakersColors = generateColors(stats.length);

        stats.forEach((speaker, speakerIndex) => {
            speaker.episodes.forEach(episode => {
                const episodeKey = `${episode.date}_${episode.name}`;
                if (!episodesMap.has(episodeKey)) {
                    episodesMap.set(episodeKey, {
                        date: new Date(episode.date),
                        name: episode.name,
                        interventions: []
                    });
                }
                episodesMap.get(episodeKey).interventions.push({
                    speaker: speaker.tag,
                    duration: episode.duration,
                    color: speakersColors[speakerIndex]
                });
            });
        });

        // Ordenar episodios por fecha
        const episodes = Array.from(episodesMap.values()).sort((a, b) => a.date - b.date);

        if (episodes.length === 0) {
            const ctx = canvas.getContext('2d');
            ctx.fillStyle = '#6B7280';
            ctx.font = '16px Arial';
            ctx.textAlign = 'center';
            ctx.fillText('No hay episodios para mostrar', canvas.width / 2, 100);
            return;
        }

        // Establecer dimensiones
        const containerWidth = chartDiv.offsetWidth - 24; // Reducido desde 48 a 24
        canvas.width = containerWidth;
        
        // Calcular altura dinámica para leyenda
        const legendLines = Math.ceil(stats.length / 5); // Aproximadamente 5 items por línea
        const legendHeight = legendLines * 20 + 40; // 20px por línea + padding
        
        canvas.height = Math.max(600, episodes.length * 80) + legendHeight;

        const ctx = canvas.getContext('2d');
        
        // Optimizar padding para maximizar área de gráfico
        const paddingLeft = 90; // Reducido desde 130 a 90
        const paddingRight = 30; // Reducido desde 50 a 30
        const paddingTop = legendHeight + 40; // Espacio para la leyenda arriba
        const paddingBottom = 60;
        
        const timelineX = paddingLeft;
        const chartHeight = canvas.height - paddingTop - paddingBottom;
        const episodeSpacing = chartHeight / Math.max(episodes.length - 1, 1);

        // Limpiar canvas
        ctx.clearRect(0, 0, canvas.width, canvas.height);

        // Dibujar leyenda de colores en la parte superior
        let legendY = 20;
        let legendX = paddingLeft;
        ctx.font = '11px Arial';
        ctx.textAlign = 'left';

        stats.forEach((speaker, index) => {
            // Cuadrado de color
            ctx.fillStyle = speakersColors[index];
            ctx.fillRect(legendX, legendY, 12, 12);

            // Nombre del speaker
            ctx.fillStyle = '#374151';
            ctx.fillText(speaker.tag, legendX + 16, legendY + 10);

            const textWidth = ctx.measureText(speaker.tag).width;
            legendX += textWidth + 30;

            // Saltar a siguiente línea si es necesario
            if (legendX > canvas.width - 150) {
                legendX = paddingLeft;
                legendY += 20;
            }
        });

        // Dibujar línea de tiempo vertical
        ctx.strokeStyle = '#9CA3AF';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(timelineX, paddingTop);
        ctx.lineTo(timelineX, canvas.height - paddingBottom);
        ctx.stroke();

        // Dibujar episodios y sus intervenciones
        episodes.forEach((episode, index) => {
            const y = paddingTop + index * episodeSpacing;

            // Punto en la línea de tiempo
            ctx.fillStyle = '#3B82F6';
            ctx.beginPath();
            ctx.arc(timelineX, y, 6, 0, 2 * Math.PI);
            ctx.fill();

            // Fecha (con más espacio a la izquierda)
            ctx.fillStyle = '#374151';
            ctx.font = '11px Arial';
            ctx.textAlign = 'right';
            ctx.fillText(episode.date.toLocaleDateString(), timelineX - 15, y + 4);

            // Nombre del episodio (truncado si es muy largo)
            ctx.textAlign = 'left';
            ctx.font = 'bold 12px Arial';
            const maxEpisodeNameWidth = canvas.width - timelineX - paddingRight - 30;
            let episodeName = episode.name;
            let episodeNameWidth = ctx.measureText(episodeName).width;
            
            // Truncar el nombre si es muy largo
            while (episodeNameWidth > maxEpisodeNameWidth && episodeName.length > 10) {
                episodeName = episodeName.substring(0, episodeName.length - 4) + '...';
                episodeNameWidth = ctx.measureText(episodeName).width;
            }
            
            ctx.fillText(episodeName, timelineX + 15, y - 10);

            // Dibujar barras de intervenciones
            let currentX = timelineX + 15;
            const barHeight = 20;
            const maxBarWidth = canvas.width - timelineX - paddingRight - 15;

            // Calcular duración total del episodio para escalar las barras
            const totalDuration = episode.interventions.reduce((sum, inv) => sum + inv.duration, 0);

            episode.interventions.forEach(intervention => {
                const barWidth = Math.max(30, (intervention.duration / totalDuration) * maxBarWidth * 0.8);

                // Barra de intervención
                ctx.fillStyle = intervention.color;
                ctx.fillRect(currentX, y + 5, barWidth, barHeight);

                // Etiqueta del speaker
                ctx.fillStyle = '#FFFFFF';
                ctx.font = '10px Arial';
                ctx.textAlign = 'center';
                const speakerLabel = intervention.speaker.length > 8 ? intervention.speaker.substring(0, 6) + '..' : intervention.speaker;
                ctx.fillText(speakerLabel, currentX + barWidth / 2, y + 18);

                // Duración en minutos (debajo de la barra)
                ctx.fillStyle = '#6B7280';
                ctx.font = '9px Arial';
                const durationMin = Math.round(intervention.duration / 60);
                ctx.fillText(`${durationMin}m`, currentX + barWidth / 2, y + 35);

                currentX += barWidth + 5;
            });
        });
    }, 100);

    return chartDiv;
}

// Función auxiliar para generar colores (debe estar definida)
function generateColors(count) {
    const colors = [
        '#3B82F6', '#EF4444', '#10B981', '#F59E0B', '#8B5CF6',
        '#EC4899', '#14B8A6', '#F97316', '#6366F1', '#84CC16'
    ];
    
    // Si necesitamos más colores, generarlos dinámicamente
    if (count <= colors.length) {
        return colors.slice(0, count);
    }
    
    const result = [...colors];
    for (let i = colors.length; i < count; i++) {
        const hue = (i * 137.508) % 360; // Ángulo dorado para distribución uniforme
        result.push(`hsl(${hue}, 70%, 50%)`);
    }
    
    return result;
}
// Función para crear tabla de detalles por episodio
function createSpeakerEpisodesTable(speaker) {
    const tableDiv = document.createElement('div');
    tableDiv.className = 'bg-white p-6 rounded-lg border shadow-sm mt-6';
    
    const title = document.createElement('h4');
    title.className = 'text-lg font-semibold mb-4 text-gray-800';
    title.textContent = `Detalle de participación - ${speaker.tag}`;
    tableDiv.appendChild(title);
    
    const table = document.createElement('table');
    table.className = 'w-full text-sm';
    
    // Cabecera
    const thead = document.createElement('thead');
    thead.innerHTML = `
        <tr class="border-b border-gray-200">
            <th class="text-left py-2 px-3 font-semibold">Episodio</th>
            <th class="text-left py-2 px-3 font-semibold">Fecha</th>
            <th class="text-right py-2 px-3 font-semibold">Duración (min)</th>
            <th class="text-right py-2 px-3 font-semibold">% del episodio</th>
        </tr>
    `;
    table.appendChild(thead);
    
    // Cuerpo
    const tbody = document.createElement('tbody');
    // Ordenar episodios por fecha antes de mostrarlos
    const sortedEpisodes = [...speaker.episodes].sort((a, b) => new Date(a.date) - new Date(b.date));
    
    sortedEpisodes.forEach((episode, index) => {
        const row = document.createElement('tr');
        row.className = index % 2 === 0 ? 'bg-gray-50' : '';
        
        const percentage = episode.total_episode_duration > 0 
            ? Math.round((episode.duration / episode.total_episode_duration) * 100 * 100) / 100 
            : 0;
        console.log(`Episodio: ${episode.name}, Duración: ${episode.duration}, Total episodio: ${episode.total_episode_duration}, %: ${percentage}`);   
        row.innerHTML = `
            <td class="py-2 px-3 text-blue-600 hover:text-blue-800 hover:underline">${episode.link}</td>
            <td class="py-2 px-3">${new Date(episode.date).toLocaleDateString()}</td>
            <td class="py-2 px-3 text-right">${Math.round(episode.duration / 60 * 100) / 100}</td>
            <td class="py-2 px-3 text-right">${percentage}%</td>
        `;
        tbody.appendChild(row);
    });
    table.appendChild(tbody);
    
    // Pie de tabla con totales
    // Calcular la suma de episode.duration para el TOTAL
    speaker.total_speaker_duration = sortedEpisodes.reduce((sum, ep) => sum + ep.duration, 0);
    const tfoot = document.createElement('tfoot');
    const percentageTotal = Math.round(speaker.total_speaker_duration / speaker.total_duration * 100 * 100)/100;
    tfoot.innerHTML = `
        <tr class="border-t-2 border-gray-300 font-semibold">
            <td class="py-2 px-3">TOTAL</td>
            <td class="py-2 px-3">${speaker.episodes.length} episodios</td>
            <td class="py-2 px-3 text-right">${Math.round(speaker.total_speaker_duration / 60 * 100) / 100}</td>
            <td class="py-2 px-3 text-right">${percentageTotal}%</td>
        </tr>
    `;
    table.appendChild(tfoot);
    
    tableDiv.appendChild(table);
    return tableDiv;
}

    // Cargar intervinientes cuando cambien las fechas (dentro del DOMContentLoaded)
    function loadSpeakers() {
        const startDate = startDateInput.value;
        const endDate = endDateInput.value;
        
        if (!startDate || !endDate) {
            speakersSelect.innerHTML = '<option value="" disabled>Selecciona primero las fechas para cargar los intervinientes</option>';
            speakersSelect.disabled = true;
            analyzeSpeakersBtn.disabled = true;
            return;
        }
        
        if (new Date(startDate) > new Date(endDate)) {
            alert('La fecha de inicio debe ser anterior a la fecha de fin.');
            return;
        }
        
        // Mostrar indicador de carga
        speakersLoading.classList.remove('hidden');
        speakersSelect.disabled = true;
        console.log('[loadSpeakers] Cargando intervinientes para el período', startDate, 'a', endDate);
        
        // Llamada real a la api gen_stats para obtener intervinientes
        fetch('/api/gen_stats', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                fromdate: startDate,
                todate: endDate
            })
        })
        .then(response => {
            if (!response.ok) {
                throw new Error('Error al obtener estadísticas generales');
            }
            return response.json();
        })
        .then(data => {
            // Código para procesar los datos...
            speakersSelect.innerHTML = '';
            data.speakers.forEach(speaker => {
                const option = document.createElement('option');
                option.value = speaker.tag;
                const totalHours = Math.floor(speaker.total_duration / 3600);
                const totalMinutes = Math.floor((speaker.total_duration % 3600) / 60);
                const timeFormatted = totalHours > 0 ? `${totalHours}h ${totalMinutes}m` : `${totalMinutes}m`;
                option.textContent = `${speaker.tag} (${speaker.total_episodes} episodios, ${timeFormatted})`;
                speakersSelect.appendChild(option);
            });
            
            speakersSelect.disabled = false;
            speakersLoading.classList.add('hidden');
            analyzeSpeakersBtn.disabled = false;
        })
        .catch(error => {
            speakersErrorMsg.textContent = error.message || 'Error al cargar los intervinientes';
            speakersErrorMsg.classList.remove('hidden');
            speakersLoading.classList.add('hidden');
        });
    }
    
    // Event listener para el formulario de análisis de speakers
    speakersAnalysisForm.addEventListener('submit', function(e) {
        e.preventDefault();
        // Código del análisis...
    });

// Código continúa...

// Funciones globales que deben estar fuera del DOMContentLoaded
// Gestión de cookies
function initCookies() {
    const cookieConsent = localStorage.getItem('cookieConsent');
    if (!cookieConsent) {
        document.getElementById('cookieBanner').classList.add('show');
    }
}

// Funciones de información legal
function showPrivacyPolicy() {
    alert('Política de Privacidad:\\n\\nEsta aplicación procesa sus consultas para proporcionar respuestas relevantes. Los datos se procesan de acuerdo con el RGPD y la LOPDGDD. Para más información, contacte con el responsable del tratamiento.');
}

function showLegalNotice() {
    alert('Aviso Legal:\\n\\nEsta web pertenece a José Miguel Robles Román. Uso sujeto a términos y condiciones. Para dudas legales, contacte con el administrador. - José Miguel Robles Román - NIF: 11735610-K - e-mail: webmaster@awebaos.org');
}

function showCookiePolicy() {
    alert('Política de Cookies:\\n\\nUtilizamos cookies técnicas necesarias para el funcionamiento de la web y cookies de análisis para mejorar la experiencia. Puede configurar sus preferencias en cualquier momento.');
}

function showAccessibilityInfo() {
    alert('Información de Accesibilidad:\\n\\nEsta web cumple con las Pautas WCAG 2.1 nivel AA. Dispone de controles de accesibilidad, navegación por teclado y compatibilidad con lectores de pantalla. Para reportar problemas de accesibilidad, contacte con soporte.');
}

function showCookieConfig() {
    alert('Configuración de Cookies:\\n\\nCookies técnicas: Necesarias (no se pueden desactivar)\\nCookies de análisis: Pueden activarse/desactivarse\\nCookies de personalización: Pueden activarse/desactivarse');
}

// Event listeners que deben estar fuera del DOMContentLoaded
document.getElementById('acceptCookies').addEventListener('click', () => {
    localStorage.setItem('cookieConsent', 'accepted');
    document.getElementById('cookieBanner').classList.remove('show');
});

document.getElementById('rejectCookies').addEventListener('click', () => {
    localStorage.setItem('cookieConsent', 'rejected');
    document.getElementById('cookieBanner').classList.remove('show');
});

document.getElementById('configureCookies').addEventListener('click', () => {
    showCookieConfig();
});

// Funciones de accesibilidad
document.getElementById('increaseFontSize').addEventListener('click', () => {
    let fontSize = parseInt(document.body.style.fontSize) || 16;
    fontSize = Math.min(fontSize + 2, 24);
    document.body.style.fontSize = fontSize + 'px';
});

document.getElementById('decreaseFontSize').addEventListener('click', () => {
    let fontSize = parseInt(document.body.style.fontSize) || 16;
    fontSize = Math.max(fontSize - 2, 12);
    document.body.style.fontSize = fontSize + 'px';
});

document.getElementById('toggleContrast').addEventListener('click', () => {
    document.body.classList.toggle('high-contrast');
});

// Mejoras de rendimiento y SEO
if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
        navigator.serviceWorker.register('/sw.js')
            .then(registration => console.log('[ServiceWorker] Registrado correctamente'))
            .catch(error => {
                // Service Worker es opcional, no mostrar error si no existe
                console.debug('[ServiceWorker] No disponible:', error.message);
            });
    });
}
