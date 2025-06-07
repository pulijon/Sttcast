// Estado de la aplicación
let isLoading = false;

// Elementos del DOM
const questionInput = document.getElementById('question');
const languageSelect = document.getElementById('language');
const submitBtn = document.getElementById('submitBtn');
const errorDiv = document.getElementById('errorDiv');
const errorText = document.getElementById('errorText');
const loadingContainer = document.getElementById('loadingContainer');
const resultsContainer = document.getElementById('resultsContainer');
const responseContent = document.getElementById('responseContent');
const referencesContent = document.getElementById('referencesContent');
const refCount = document.getElementById('refCount');

// Event listeners
submitBtn.addEventListener('click', handleSubmit);
questionInput.addEventListener('keydown', function(e) {
    if (e.ctrlKey && e.key === 'Enter') {
        handleSubmit();
    }
});

function showError(message) {
    errorText.textContent = message;
    errorDiv.classList.remove('hidden');
}

function hideError() {
    errorDiv.classList.add('hidden');
}

function setLoading(loading) {
    isLoading = loading;
    submitBtn.disabled = loading;

    if (loading) {
        submitBtn.innerHTML = `
            <div class="spinner w-5 h-5 border-2 border-white border-t-transparent"></div>
            <span>Procesando...</span>
        `;
        loadingContainer.classList.remove('hidden');
        resultsContainer.classList.add('hidden');
    } else {
        submitBtn.innerHTML = `
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"></path>
            </svg>
            <span>Enviar Pregunta</span>
        `;
        loadingContainer.classList.add('hidden');
    }
}

function displayResults(data) {
    // Mostrar respuesta
    if (data.response) {
        responseContent.innerHTML = `<p class="text-gray-700 leading-relaxed whitespace-pre-wrap">${data.response}</p>`;
    } else {
        responseContent.innerHTML = '<p class="text-gray-400 italic">No hay respuesta disponible</p>';
    }

    // Mostrar referencias
    refCount.textContent = data.references.length;

    if (data.references && data.references.length > 0) {
        const referencesHTML = data.references.map((ref, index) => `
            <div class="reference-card group p-4 bg-gray-50 hover:bg-blue-50 rounded-xl border border-gray-200 hover:border-blue-300 cursor-pointer transition-all duration-200" 
                onclick="openReference('${ref.url}')">
                <div class="flex items-start justify-between gap-3">
                    <div class="flex-1">
                        <p class="font-semibold text-gray-800 group-hover:text-blue-700 mb-1">
                            ${ref.label}
                        </p>
                        <div class="flex items-center gap-4 text-sm text-gray-600">
                            <span class="flex items-center gap-1">
                                📁 ${ref.file}
                            </span>
                            <span class="flex items-center gap-1">
                                <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"></path>
                                </svg>
                                ${ref.formatted_time}
                            </span>
                        </div>
                    </div>
                    <div class="text-blue-600 group-hover:text-blue-700 opacity-0 group-hover:opacity-100 transition-opacity">
                        ↗️
                    </div>
                </div>
            </div>
        `).join('');
        referencesContent.innerHTML = `<div class="space-y-3">${referencesHTML}</div>`;
    } else {
        referencesContent.innerHTML = '<p class="text-gray-400 italic">No hay referencias disponibles</p>';
    }

    resultsContainer.classList.remove('hidden');
}

window.openReference = function(url) {
    window.open(url, '_blank');
}

async function handleSubmit() {
    const question = questionInput.value.trim();
    const language = languageSelect.value;

    if (!question) {
        showError('Por favor, introduce una pregunta');
        return;
    }

    if (isLoading) return;

    hideError();
    setLoading(true);

    try {
        const response = await fetch('/api/ask', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                question: question,
                language: language
            })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || `Error del servidor: ${response.status}`);
        }

        if (data.success) {
            displayResults(data);
        } else {
            throw new Error(data.error || 'Error desconocido');
        }

    } catch (error) {
        console.error('Error:', error);
        showError(error.message || 'Error al procesar la pregunta');
    } finally {
        setLoading(false);
    }
}

// Inicialización
document.addEventListener('DOMContentLoaded', function() {
    questionInput.focus();
});
