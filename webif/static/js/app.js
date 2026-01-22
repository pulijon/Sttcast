/**
 * Sttcast Web Interface - JavaScript
 */

// ===========================================
// Sidebar Toggle
// ===========================================
document.addEventListener('DOMContentLoaded', function() {
    const sidebar = document.getElementById('sidebar');
    const sidebarToggle = document.getElementById('sidebarToggle');
    
    if (sidebarToggle && sidebar) {
        sidebarToggle.addEventListener('click', function() {
            sidebar.classList.toggle('open');
        });
        
        // Cerrar sidebar al hacer clic fuera en móvil
        document.addEventListener('click', function(e) {
            if (window.innerWidth <= 992) {
                if (!sidebar.contains(e.target) && !sidebarToggle.contains(e.target)) {
                    sidebar.classList.remove('open');
                }
            }
        });
    }
});

// ===========================================
// Toast Notifications
// ===========================================
function showToast(type, message, duration = 3000) {
    const container = document.getElementById('toastContainer');
    if (!container) return;
    
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    
    const icon = type === 'success' ? 'check-circle' : 
                 type === 'error' ? 'exclamation-circle' :
                 type === 'warning' ? 'exclamation-triangle' : 'info-circle';
    
    toast.innerHTML = `
        <i class="fas fa-${icon}"></i>
        <span>${message}</span>
    `;
    
    container.appendChild(toast);
    
    setTimeout(() => {
        toast.classList.add('fade-out');
        setTimeout(() => toast.remove(), 300);
    }, duration);
}

// ===========================================
// Confirm Dialogs
// ===========================================
function confirmAction(message, callback) {
    if (confirm(message)) {
        callback();
    }
}

// ===========================================
// Form Validation
// ===========================================
function validateForm(formElement) {
    const inputs = formElement.querySelectorAll('[required]');
    let isValid = true;
    
    inputs.forEach(input => {
        if (!input.value.trim()) {
            isValid = false;
            input.classList.add('is-invalid');
        } else {
            input.classList.remove('is-invalid');
        }
    });
    
    return isValid;
}

// ===========================================
// AJAX Helpers
// ===========================================
async function fetchJSON(url, options = {}) {
    try {
        const response = await fetch(url, {
            ...options,
            headers: {
                'Content-Type': 'application/json',
                ...options.headers
            }
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Error en la petición');
        }
        
        return await response.json();
    } catch (error) {
        showToast('error', error.message);
        throw error;
    }
}

async function postForm(url, formData) {
    try {
        const response = await fetch(url, {
            method: 'POST',
            body: formData
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Error en la petición');
        }
        
        return await response.json();
    } catch (error) {
        showToast('error', error.message);
        throw error;
    }
}

// ===========================================
// File Size Formatter
// ===========================================
function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

// ===========================================
// Date Formatter
// ===========================================
function formatDate(dateString) {
    const date = new Date(dateString);
    return date.toLocaleDateString('es-ES', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
}

// ===========================================
// Debounce
// ===========================================
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// ===========================================
// Copy to Clipboard
// ===========================================
async function copyToClipboard(text) {
    try {
        await navigator.clipboard.writeText(text);
        showToast('success', 'Copiado al portapapeles');
    } catch (err) {
        showToast('error', 'Error al copiar');
    }
}

// ===========================================
// Keyboard Shortcuts
// ===========================================
document.addEventListener('keydown', function(e) {
    // ESC para cerrar modales
    if (e.key === 'Escape') {
        const modals = document.querySelectorAll('.modal.open');
        modals.forEach(modal => modal.classList.remove('open'));
    }
});

// ===========================================
// Initialize Tooltips
// ===========================================
document.querySelectorAll('[title]').forEach(element => {
    element.addEventListener('mouseenter', function(e) {
        // Simple tooltip implementation
        const tooltip = document.createElement('div');
        tooltip.className = 'tooltip';
        tooltip.textContent = this.getAttribute('title');
        document.body.appendChild(tooltip);
        
        const rect = this.getBoundingClientRect();
        tooltip.style.top = rect.bottom + 5 + 'px';
        tooltip.style.left = rect.left + 'px';
    });
    
    element.addEventListener('mouseleave', function() {
        const tooltips = document.querySelectorAll('.tooltip');
        tooltips.forEach(t => t.remove());
    });
});

// ===========================================
// Auto-refresh for active transcriptions
// ===========================================
function setupAutoRefresh() {
    const hasActiveJobs = document.querySelector('.status-running, .status-queued');
    
    if (hasActiveJobs) {
        // Refresh página cada 30 segundos si hay trabajos activos
        setTimeout(() => {
            location.reload();
        }, 30000);
    }
}

// Iniciar auto-refresh si estamos en la página de transcripciones
if (window.location.pathname.includes('/transcriptions')) {
    setupAutoRefresh();
}
