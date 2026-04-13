/**
 * admin.js - Panel de administración de Consultas Destacadas y Categorías
 * 
 * Gestiona:
 * - Listado y filtrado de consultas
 * - Toggle de consultas destacadas (featured)
 * - CRUD de categorías jerárquicas
 * - Categorización automática con LLM
 * - Asignación de consultas a categorías
 */

const BASE_PATH = window.ADMIN_CONFIG?.basePath || '';

// =============================================
//  Estado global
// =============================================
let allQueries = [];
let allCategories = [];  // flat
let categoriesTree = [];
let llmProposal = null;

// =============================================
//  Inicialización
// =============================================
document.addEventListener('DOMContentLoaded', () => {
    initTabs();
    loadQueries();
    loadCategories();
    initEventListeners();
});

// =============================================
//  Tabs
// =============================================
function initTabs() {
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const tabId = btn.dataset.tab;
            // Actualizar botones
            document.querySelectorAll('.tab-btn').forEach(b => {
                b.classList.remove('tab-active');
                b.classList.add('tab-inactive');
            });
            btn.classList.remove('tab-inactive');
            btn.classList.add('tab-active');
            // Mostrar/ocultar contenido
            document.querySelectorAll('.tab-content').forEach(tc => tc.classList.add('hidden'));
            document.getElementById(`tab-${tabId}`).classList.remove('hidden');
            
            // Al cambiar a tab LLM, verificar prerequisitos
            if (tabId === 'llm') checkLlmPrerequisites();
        });
    });
}

// =============================================
//  Event Listeners
// =============================================
function initEventListeners() {
    // Búsqueda de consultas
    document.getElementById('searchQueries').addEventListener('input', filterQueries);
    document.getElementById('filterFeatured').addEventListener('change', filterQueries);
    
    // Formulario de categoría
    document.getElementById('categoryForm').addEventListener('submit', handleCategorySubmit);
    document.getElementById('cancelCategoryBtn').addEventListener('click', resetCategoryForm);
    document.getElementById('addCategoryBtn').addEventListener('click', () => {
        resetCategoryForm();
        document.getElementById('categoryFormTitle').textContent = 'Nueva categoría';
    });
    
    // Auto-generar slug desde nombre
    document.getElementById('categoryName').addEventListener('input', (e) => {
        const slugField = document.getElementById('categorySlug');
        if (!document.getElementById('categoryId').value) {
            slugField.value = generateSlug(e.target.value);
        }
    });
    
    // LLM
    document.getElementById('suggestCategoriesBtn').addEventListener('click', requestLlmSuggestion);
    document.getElementById('applyLlmBtn')?.addEventListener('click', applyLlmProposal);
    document.getElementById('discardLlmBtn')?.addEventListener('click', () => {
        document.getElementById('llmResult').classList.add('hidden');
        llmProposal = null;
    });
    
    // Modal de asignación
    document.getElementById('cancelAssignBtn').addEventListener('click', closeAssignModal);
    document.getElementById('confirmAssignBtn').addEventListener('click', confirmAssignment);
}

// =============================================
//  Consultas
// =============================================
async function loadQueries() {
    try {
        const resp = await fetch(`${BASE_PATH}/api/admin/queries`);
        if (!resp.ok) {
            if (resp.status === 401) { window.location.href = `${BASE_PATH}/admin/login`; return; }
            throw new Error(`Error ${resp.status}`);
        }
        const data = await resp.json();
        allQueries = data.queries || [];
        renderQueries(allQueries);
        document.getElementById('queriesLoading').classList.add('hidden');
        document.getElementById('queriesTable').classList.remove('hidden');
    } catch (e) {
        console.error('Error cargando consultas:', e);
        showToast('Error al cargar consultas', 'error');
    }
}

function renderQueries(queries) {
    const tbody = document.getElementById('queriesTableBody');
    tbody.innerHTML = '';
    
    queries.forEach(q => {
        const tr = document.createElement('tr');
        tr.className = 'hover:bg-gray-50';
        
        const featuredClass = q.featured ? 'active' : 'inactive';
        const featuredTitle = q.featured ? 'Quitar de destacadas' : 'Marcar como destacada';
        
        // Categorías badges (azul=manual, morado=LLM)
        let catBadges = '';
        if (q.categories && q.categories.length > 0) {
            q.categories.forEach(cat => {
                if (cat && cat.name) {
                    const isLlm = cat.assigned_by === 'llm';
                    const badgeBg = isLlm ? 'bg-purple-100 text-purple-800' : 'bg-blue-100 text-blue-800';
                    const originIcon = isLlm ? '🤖 ' : '';
                    catBadges += `<span class="category-badge ${badgeBg}" title="Asignada por: ${isLlm ? 'LLM' : 'Admin'}">
                        ${originIcon}${cat.name}
                        <span class="remove-cat" onclick="removeCategoryFromQuery(${q.id}, ${cat.id})" title="Quitar">×</span>
                    </span>`;
                }
            });
        }
        
        const dateStr = q.created_at ? new Date(q.created_at).toLocaleDateString('es-ES', {
            day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit'
        }) : '';
        
        tr.innerHTML = `
            <td class="px-3 py-2">
                <span class="featured-star ${featuredClass}" 
                      onclick="toggleFeatured('${q.uuid}')" 
                      title="${featuredTitle}">★</span>
            </td>
            <td class="px-3 py-2">
                <a href="${BASE_PATH}/savedquery/${q.uuid}" target="_blank" 
                   class="text-blue-600 hover:underline" title="Ver consulta completa">
                    ${escapeHtml(q.query_text?.substring(0, 120))}${q.query_text?.length > 120 ? '...' : ''}
                </a>
            </td>
            <td class="px-3 py-2 text-gray-500 text-xs">${dateStr}</td>
            <td class="px-3 py-2 text-center">
                <span class="vote-cell" data-uuid="${q.uuid}" data-field="likes" data-value="${q.likes || 0}"
                      onclick="editVote(this)" title="Clic para editar">${q.likes || 0}</span>
            </td>
            <td class="px-3 py-2 text-center">
                <span class="vote-cell" data-uuid="${q.uuid}" data-field="dislikes" data-value="${q.dislikes || 0}"
                      onclick="editVote(this)" title="Clic para editar">${q.dislikes || 0}</span>
            </td>
            <td class="px-3 py-2 text-gray-500 text-xs">${escapeHtml(q.ip || '')}</td>
            <td class="px-3 py-2 text-gray-500 text-xs">${escapeHtml(q.country || '')}${q.country && q.city ? ' / ' : ''}${escapeHtml(q.city || '')}</td>
            <td class="px-3 py-2">${catBadges}</td>
            <td class="px-3 py-2 text-center">
                <button class="assign-cat-btn text-xs bg-blue-100 text-blue-700 px-2 py-1 rounded hover:bg-blue-200 transition"
                        data-query-id="${q.id}"
                        data-query-text="${escapeAttr(q.query_text?.substring(0, 80))}"
                        title="Asignar categoría">
                    + Cat
                </button>
            </td>
            <td class="px-3 py-2 text-center">
                <button class="vote-history-btn text-xs bg-gray-100 text-gray-700 px-2 py-1 rounded hover:bg-gray-200 transition"
                        data-query-id="${q.id}"
                        title="Ver historial de votos">
                    📋
                </button>
            </td>
        `;
        tbody.appendChild(tr);

        // Fila colapsable para historial de votos
        const historyTr = document.createElement('tr');
        historyTr.id = `vote-history-row-${q.id}`;
        historyTr.className = 'vote-history-row hidden';
        historyTr.innerHTML = `
            <td colspan="10" class="px-3 py-2 bg-gray-50">
                <div class="vote-history-content text-xs text-gray-600">
                    <span class="loading-spinner"></span> Cargando historial...
                </div>
            </td>
        `;
        tbody.appendChild(historyTr);

        // Bind click handler sin inline onclick (evita problemas con comillas en el texto)
        const assignBtn = tr.querySelector('.assign-cat-btn');
        if (assignBtn) {
            assignBtn.addEventListener('click', () => {
                openAssignModal(
                    parseInt(assignBtn.dataset.queryId),
                    assignBtn.dataset.queryText
                );
            });
        }

        // Bind vote history toggle
        const historyBtn = tr.querySelector('.vote-history-btn');
        if (historyBtn) {
            historyBtn.addEventListener('click', () => {
                toggleVoteHistory(parseInt(historyBtn.dataset.queryId));
            });
        }
    });
    
    document.getElementById('queriesCount').textContent = 
        `Mostrando ${queries.length} de ${allQueries.length} consultas`;
}

function filterQueries() {
    const search = document.getElementById('searchQueries').value.toLowerCase();
    const onlyFeatured = document.getElementById('filterFeatured').checked;
    
    let filtered = allQueries;
    
    if (onlyFeatured) {
        filtered = filtered.filter(q => q.featured);
    }
    
    if (search) {
        filtered = filtered.filter(q => 
            q.query_text?.toLowerCase().includes(search)
        );
    }
    
    renderQueries(filtered);
}

async function toggleFeatured(uuid) {
    try {
        const resp = await fetch(`${BASE_PATH}/api/admin/toggle_featured/${uuid}`, {
            method: 'POST'
        });
        if (!resp.ok) {
            if (resp.status === 401) { window.location.href = `${BASE_PATH}/admin/login`; return; }
            throw new Error(`Error ${resp.status}`);
        }
        const data = await resp.json();
        
        // Actualizar en el array local
        const query = allQueries.find(q => q.uuid === uuid);
        if (query) query.featured = data.featured;
        
        filterQueries();
        showToast(data.featured ? '★ Consulta marcada como destacada' : 'Consulta desmarcada', 'success');
    } catch (e) {
        console.error('Error toggling featured:', e);
        showToast('Error al actualizar', 'error');
    }
}

function editVote(cell) {
    // Evitar abrir doble editor
    if (cell.querySelector('input')) return;
    
    const currentValue = parseInt(cell.dataset.value) || 0;
    cell.classList.add('vote-cell-editing');
    
    const input = document.createElement('input');
    input.type = 'number';
    input.min = '0';
    input.value = currentValue;
    cell.textContent = '';
    cell.appendChild(input);
    input.focus();
    input.select();
    
    const finish = () => {
        const newValue = Math.max(0, parseInt(input.value) || 0);
        cell.classList.remove('vote-cell-editing');
        cell.textContent = newValue;
        cell.dataset.value = newValue;
        
        if (newValue !== currentValue) {
            saveVote(cell.dataset.uuid, cell.dataset.field, newValue);
        }
    };
    
    input.addEventListener('blur', finish);
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); input.blur(); }
        if (e.key === 'Escape') { input.value = currentValue; input.blur(); }
    });
}

async function saveVote(uuid, field, value) {
    // Obtener el otro campo del mismo row
    const row = document.querySelector(`[data-uuid="${uuid}"][data-field="likes"]`);
    const rowDislike = document.querySelector(`[data-uuid="${uuid}"][data-field="dislikes"]`);
    const likes = field === 'likes' ? value : parseInt(row?.dataset.value || 0);
    const dislikes = field === 'dislikes' ? value : parseInt(rowDislike?.dataset.value || 0);
    
    try {
        const resp = await fetch(`${BASE_PATH}/api/admin/set_votes/${uuid}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ likes, dislikes })
        });
        if (!resp.ok) {
            if (resp.status === 401) { window.location.href = `${BASE_PATH}/admin/login`; return; }
            throw new Error(`Error ${resp.status}`);
        }
        const data = await resp.json();
        
        // Actualizar en el array local
        const query = allQueries.find(q => q.uuid === uuid);
        if (query) {
            query.likes = data.likes;
            query.dislikes = data.dislikes;
        }
        
        showToast('Votos actualizados', 'success');
    } catch (e) {
        console.error('Error saving votes:', e);
        showToast('Error al guardar votos', 'error');
        // Re-render para restaurar valores
        filterQueries();
    }
}

// =============================================
//  Historial de votos
// =============================================
async function toggleVoteHistory(queryId) {
    const row = document.getElementById(`vote-history-row-${queryId}`);
    if (!row) return;

    if (!row.classList.contains('hidden')) {
        row.classList.add('hidden');
        return;
    }

    row.classList.remove('hidden');
    const contentDiv = row.querySelector('.vote-history-content');
    contentDiv.innerHTML = '<span class="loading-spinner"></span> Cargando historial...';

    try {
        const resp = await fetch(`${BASE_PATH}/api/admin/vote_history/${queryId}`);
        if (!resp.ok) {
            if (resp.status === 401) { window.location.href = `${BASE_PATH}/admin/login`; return; }
            throw new Error(`Error ${resp.status}`);
        }
        const data = await resp.json();
        const votes = data.votes || [];

        if (votes.length === 0) {
            contentDiv.innerHTML = '<em class="text-gray-400">Sin registros de votos (los votos anteriores a la auditoría no se registran)</em>';
            return;
        }

        let html = `<table class="vote-history-table w-full text-xs">
            <thead><tr class="bg-gray-100">
                <th class="px-2 py-1 text-left">Fecha</th>
                <th class="px-2 py-1 text-center">Tipo</th>
                <th class="px-2 py-1 text-center">Origen</th>
                <th class="px-2 py-1 text-left">IP</th>
                <th class="px-2 py-1 text-left">País</th>
                <th class="px-2 py-1 text-left">Ciudad</th>
            </tr></thead><tbody>`;

        votes.forEach(v => {
            const dateStr = v.date ? new Date(v.date).toLocaleString('es-ES', {
                day: '2-digit', month: '2-digit', year: 'numeric',
                hour: '2-digit', minute: '2-digit', second: '2-digit'
            }) : '';
            const tipo = v.is_like ? '👍' : '👎';
            const origen = v.from_admin ? '🔧 Admin' : '👤 Usuario';
            const rowClass = v.is_like ? 'bg-green-50' : 'bg-red-50';
            html += `<tr class="${rowClass}">
                <td class="px-2 py-1">${dateStr}</td>
                <td class="px-2 py-1 text-center">${tipo}</td>
                <td class="px-2 py-1 text-center">${origen}</td>
                <td class="px-2 py-1">${escapeHtml(v.ip || '')}</td>
                <td class="px-2 py-1">${escapeHtml(v.country || '')}</td>
                <td class="px-2 py-1">${escapeHtml(v.city || '')}</td>
            </tr>`;
        });

        html += '</tbody></table>';
        contentDiv.innerHTML = html;
    } catch (e) {
        console.error('Error loading vote history:', e);
        contentDiv.innerHTML = '<em class="text-red-500">Error al cargar historial</em>';
    }
}

// =============================================
//  Categorías
// =============================================
async function loadCategories() {
    try {
        const resp = await fetch(`${BASE_PATH}/api/admin/categories`);
        if (!resp.ok) {
            if (resp.status === 401) return;
            throw new Error(`Error ${resp.status}`);
        }
        const data = await resp.json();
        categoriesTree = data.tree || [];
        allCategories = data.flat || [];
        
        renderCategoriesTree(categoriesTree);
        populateCategorySelects();
        
        document.getElementById('categoriesLoading').classList.add('hidden');
    } catch (e) {
        console.error('Error cargando categorías:', e);
        document.getElementById('categoriesLoading').classList.add('hidden');
    }
}

function renderCategoriesTree(tree, container = null) {
    const target = container || document.getElementById('categoriesTree');
    if (!container) target.innerHTML = '';
    
    if (tree.length === 0 && !container) {
        document.getElementById('noCategoriesMsg').classList.remove('hidden');
        return;
    }
    document.getElementById('noCategoriesMsg').classList.add('hidden');
    
    tree.forEach(cat => {
        const div = document.createElement('div');
        const isLlm = cat.created_by === 'llm';
        const originClass = isLlm ? 'cat-origin-llm' : 'cat-origin-admin';
        div.className = `category-tree-item ${cat.is_primary ? 'primary' : ''} ${originClass} py-2`;
        
        const originBadge = isLlm 
            ? '<span class="text-xs bg-purple-100 text-purple-700 px-1.5 py-0.5 rounded ml-2" title="Creada por LLM">🤖 LLM</span>'
            : '<span class="text-xs bg-green-100 text-green-700 px-1.5 py-0.5 rounded ml-2" title="Creada/editada manualmente">✋ Manual</span>';
        
        div.innerHTML = `
            <div class="flex justify-between items-center">
                <div>
                    <span class="font-medium">${escapeHtml(cat.name)}</span>
                    ${cat.is_primary ? '<span class="text-xs bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded ml-2">Primaria</span>' : ''}
                    ${originBadge}
                    <span class="text-xs text-gray-500 ml-2">(${cat.query_count || 0} consultas)</span>
                </div>
                <div class="flex gap-1">
                    <button onclick="editCategory(${cat.id})" 
                            class="text-xs bg-yellow-100 text-yellow-700 px-2 py-1 rounded hover:bg-yellow-200">
                        ✏️
                    </button>
                    <button onclick="deleteCategory(${cat.id}, '${escapeAttr(cat.name)}')" 
                            class="text-xs bg-red-100 text-red-700 px-2 py-1 rounded hover:bg-red-200">
                        🗑️
                    </button>
                </div>
            </div>
            ${cat.description ? `<p class="text-xs text-gray-500 mt-1">${escapeHtml(cat.description)}</p>` : ''}
        `;
        
        target.appendChild(div);
        
        // Renderizar hijos recursivamente
        if (cat.children && cat.children.length > 0) {
            const childContainer = document.createElement('div');
            childContainer.className = 'ml-4';
            target.appendChild(childContainer);
            renderCategoriesTree(cat.children, childContainer);
        }
    });
}

function populateCategorySelects() {
    const parentSelect = document.getElementById('categoryParent');
    const assignSelect = document.getElementById('assignCategorySelect');
    
    // Select de padre en formulario
    parentSelect.innerHTML = '<option value="">Ninguna (categoría raíz)</option>';
    allCategories.forEach(cat => {
        parentSelect.innerHTML += `<option value="${cat.id}">${cat.name}</option>`;
    });
    
    // Select en modal de asignación
    assignSelect.innerHTML = '';
    if (allCategories.length === 0) {
        assignSelect.innerHTML = '<option value="" disabled>No hay categorías creadas</option>';
    } else {
        allCategories.forEach(cat => {
            const indent = cat.parent_id ? '  └ ' : '';
            assignSelect.innerHTML += `<option value="${cat.id}">${indent}${cat.name}</option>`;
        });
    }
}

async function handleCategorySubmit(e) {
    e.preventDefault();
    
    const id = document.getElementById('categoryId').value;
    const data = {
        name: document.getElementById('categoryName').value.trim(),
        slug: document.getElementById('categorySlug').value.trim(),
        description: document.getElementById('categoryDescription').value.trim(),
        parent_id: document.getElementById('categoryParent').value ? 
                   parseInt(document.getElementById('categoryParent').value) : null,
        is_primary: document.getElementById('categoryPrimary').checked,
        display_order: parseInt(document.getElementById('categoryOrder').value) || 0
    };
    
    try {
        let resp;
        if (id) {
            resp = await fetch(`${BASE_PATH}/api/admin/categories/${id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });
        } else {
            resp = await fetch(`${BASE_PATH}/api/admin/categories`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });
        }
        
        if (!resp.ok) {
            if (resp.status === 401) { window.location.href = `${BASE_PATH}/admin/login`; return; }
            const err = await resp.json();
            throw new Error(err.detail || `Error ${resp.status}`);
        }
        
        showToast(id ? 'Categoría actualizada' : 'Categoría creada', 'success');
        resetCategoryForm();
        await loadCategories();
    } catch (e) {
        console.error('Error guardando categoría:', e);
        showToast(`Error: ${e.message}`, 'error');
    }
}

function editCategory(categoryId) {
    const cat = allCategories.find(c => c.id === categoryId);
    if (!cat) return;
    
    document.getElementById('categoryFormTitle').textContent = 'Editar categoría';
    document.getElementById('categoryId').value = cat.id;
    document.getElementById('categoryName').value = cat.name;
    document.getElementById('categorySlug').value = cat.slug;
    document.getElementById('categoryDescription').value = cat.description || '';
    document.getElementById('categoryParent').value = cat.parent_id || '';
    document.getElementById('categoryPrimary').checked = cat.is_primary;
    document.getElementById('categoryOrder').value = cat.display_order || 0;
    
    // Cambiar a tab categorías si no estamos
    document.querySelector('[data-tab="categories"]').click();
}

async function deleteCategory(categoryId, categoryName) {
    if (!confirm(`¿Eliminar la categoría "${categoryName}"?\n\nLas subcategorías se reasignarán al padre.`)) return;
    
    try {
        const resp = await fetch(`${BASE_PATH}/api/admin/categories/${categoryId}`, {
            method: 'DELETE'
        });
        if (!resp.ok) {
            if (resp.status === 401) { window.location.href = `${BASE_PATH}/admin/login`; return; }
            throw new Error(`Error ${resp.status}`);
        }
        showToast('Categoría eliminada', 'success');
        await loadCategories();
    } catch (e) {
        showToast(`Error: ${e.message}`, 'error');
    }
}

function resetCategoryForm() {
    document.getElementById('categoryId').value = '';
    document.getElementById('categoryForm').reset();
    document.getElementById('categoryFormTitle').textContent = 'Nueva categoría';
}

// =============================================
//  Asignación de categorías a consultas
// =============================================
function openAssignModal(queryId, queryText) {
    document.getElementById('assignQueryId').value = queryId;
    document.getElementById('assignQueryText').textContent = queryText;
    document.getElementById('assignCategoryModal').classList.remove('hidden');
}

function closeAssignModal() {
    document.getElementById('assignCategoryModal').classList.add('hidden');
}

async function confirmAssignment() {
    const queryId = parseInt(document.getElementById('assignQueryId').value);
    const categoryId = parseInt(document.getElementById('assignCategorySelect').value);
    
    if (!queryId || !categoryId) {
        showToast('Selecciona una categoría', 'error');
        return;
    }
    
    try {
        const resp = await fetch(`${BASE_PATH}/api/admin/assign_category`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query_id: queryId, category_id: categoryId })
        });
        if (!resp.ok) throw new Error(`Error ${resp.status}`);
        
        showToast('Categoría asignada', 'success');
        closeAssignModal();
        await loadQueries();
        await loadCategories();
    } catch (e) {
        showToast(`Error: ${e.message}`, 'error');
    }
}

async function removeCategoryFromQuery(queryId, categoryId) {
    if (!confirm('¿Quitar esta categoría de la consulta?')) return;
    
    try {
        const resp = await fetch(`${BASE_PATH}/api/admin/remove_category_assignment`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query_id: queryId, category_id: categoryId })
        });
        if (!resp.ok) throw new Error(`Error ${resp.status}`);
        
        showToast('Categoría eliminada de la consulta', 'success');
        await loadQueries();
        await loadCategories();
    } catch (e) {
        showToast(`Error: ${e.message}`, 'error');
    }
}

// =============================================
//  Categorización LLM
// =============================================
function checkLlmPrerequisites() {
    const featuredCount = allQueries.filter(q => q.featured).length;
    
    if (featuredCount === 0) {
        document.getElementById('llmNoFeatured').classList.remove('hidden');
        document.getElementById('llmReady').classList.add('hidden');
        document.getElementById('suggestCategoriesBtn').disabled = true;
    } else {
        document.getElementById('llmNoFeatured').classList.add('hidden');
        document.getElementById('llmReady').classList.remove('hidden');
        document.getElementById('llmFeaturedCount').textContent = 
            `✅ Hay ${featuredCount} consultas destacadas listas para categorizar.`;
        document.getElementById('suggestCategoriesBtn').disabled = false;
    }
}

async function requestLlmSuggestion() {
    const btn = document.getElementById('suggestCategoriesBtn');
    const spinner = document.getElementById('llmSpinner');
    const statusEl = document.getElementById('llmStatus');
    
    btn.disabled = true;
    spinner.classList.remove('hidden');
    statusEl.textContent = 'Consultando al modelo de lenguaje...';
    
    try {
        const selectedModel = document.getElementById('llmModelSelect').value;
        const resp = await fetch(`${BASE_PATH}/api/admin/suggest_categories`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model: selectedModel })
        });
        
        if (!resp.ok) {
            if (resp.status === 401) { window.location.href = `${BASE_PATH}/admin/login`; return; }
            const err = await resp.json();
            throw new Error(err.detail || `Error ${resp.status}`);
        }
        
        llmProposal = await resp.json();
        renderLlmProposal(llmProposal);
        statusEl.textContent = 'Propuesta recibida. Revísala antes de aplicar.';
    } catch (e) {
        console.error('Error en categorización LLM:', e);
        showToast(`Error: ${e.message}`, 'error');
        statusEl.textContent = `Error: ${e.message}`;
    } finally {
        btn.disabled = false;
        spinner.classList.add('hidden');
    }
}

function renderLlmProposal(proposal) {
    const resultDiv = document.getElementById('llmResult');
    resultDiv.classList.remove('hidden');
    
    // === CATEGORÍAS con checkboxes ===
    const catDiv = document.getElementById('llmCategoriesProposal');
    let catHtml = `<div class="flex justify-between items-center mb-2">
        <h4 class="text-sm font-semibold">Categorías propuestas:</h4>
        <div class="flex gap-2">
            <button onclick="llmToggleAll('cat', true)" class="text-xs text-blue-600 hover:underline">Todas</button>
            <button onclick="llmToggleAll('cat', false)" class="text-xs text-gray-500 hover:underline">Ninguna</button>
        </div>
    </div>`;
    catHtml += '<div class="space-y-2">';
    
    (proposal.categories || []).forEach((cat, ci) => {
        catHtml += `
            <div class="bg-purple-50 border border-purple-200 rounded-lg p-3">
                <label class="flex items-start gap-2 cursor-pointer">
                    <input type="checkbox" class="llm-check-cat mt-1" data-cat-idx="${ci}" checked>
                    <div>
                        <span class="font-medium">${escapeHtml(cat.name)}</span>
                        <span class="text-xs text-gray-500">(${cat.slug})</span>
                        ${cat.is_primary ? '<span class="text-xs bg-purple-200 text-purple-800 px-1.5 py-0.5 rounded ml-1">Primaria</span>' : ''}
                        ${cat.description ? `<p class="text-xs text-gray-600 mt-1">${escapeHtml(cat.description)}</p>` : ''}
                    </div>
                </label>
        `;
        if (cat.children && cat.children.length > 0) {
            catHtml += '<div class="ml-6 mt-2 space-y-1">';
            cat.children.forEach((child, chi) => {
                catHtml += `
                    <label class="flex items-start gap-2 cursor-pointer text-sm text-gray-700">
                        <input type="checkbox" class="llm-check-cat mt-0.5" data-cat-idx="${ci}" data-child-idx="${chi}" checked>
                        <span>└ ${escapeHtml(child.name)} <span class="text-xs text-gray-500">(${child.slug})</span>
                        ${child.description ? ` — <span class="text-xs text-gray-500">${escapeHtml(child.description)}</span>` : ''}</span>
                    </label>
                `;
            });
            catHtml += '</div>';
        }
        catHtml += '</div>';
    });
    catHtml += '</div>';
    catDiv.innerHTML = catHtml;
    
    // === ASIGNACIONES con checkboxes ===
    const assignDiv = document.getElementById('llmAssignmentsProposal');
    const assignments = proposal.assignments || [];
    if (assignments.length > 0) {
        let assignHtml = `<div class="flex justify-between items-center mb-2 mt-4">
            <h4 class="text-sm font-semibold">Asignaciones propuestas:</h4>
            <div class="flex gap-2">
                <button onclick="llmToggleAll('assign', true)" class="text-xs text-blue-600 hover:underline">Todas</button>
                <button onclick="llmToggleAll('assign', false)" class="text-xs text-gray-500 hover:underline">Ninguna</button>
            </div>
        </div>`;
        assignHtml += '<div class="text-sm space-y-1">';
        assignments.forEach((a, ai) => {
            const query = allQueries.find(q => q.id === a.query_id);
            const queryText = query ? query.query_text?.substring(0, 60) + '...' : `Consulta #${a.query_id}`;
            assignHtml += `
                <label class="flex items-center gap-2 text-gray-700 cursor-pointer">
                    <input type="checkbox" class="llm-check-assign" data-assign-idx="${ai}" checked>
                    <span class="truncate max-w-xs">${escapeHtml(queryText)}</span>
                    <span class="text-gray-400">→</span>
                    <span class="font-medium">${a.category_slugs?.join(', ')}</span>
                    <span class="text-xs text-gray-500">(${Math.round((a.confidence || 0) * 100)}%)</span>
                </label>
            `;
        });
        assignHtml += '</div>';
        assignDiv.innerHTML = assignHtml;
    }
    
    // === REASIGNACIONES DE PADRES con checkboxes ===
    const reparents = proposal.reparents || [];
    if (reparents.length > 0) {
        let rpHtml = `<div class="flex justify-between items-center mb-2 mt-4">
            <h4 class="text-sm font-semibold">Reasignaciones de padres propuestas:</h4>
            <div class="flex gap-2">
                <button onclick="llmToggleAll('reparent', true)" class="text-xs text-blue-600 hover:underline">Todas</button>
                <button onclick="llmToggleAll('reparent', false)" class="text-xs text-gray-500 hover:underline">Ninguna</button>
            </div>
        </div>`;
        rpHtml += '<div class="text-sm space-y-1">';
        reparents.forEach((rp, ri) => {
            const parentName = rp.new_parent_slug || '(raíz)';
            rpHtml += `
                <label class="flex items-center gap-2 text-gray-700 cursor-pointer">
                    <input type="checkbox" class="llm-check-reparent" data-reparent-idx="${ri}" checked>
                    <span class="font-medium">${escapeHtml(rp.category_slug)}</span>
                    <span class="text-gray-400">→ padre:</span>
                    <span class="font-medium">${escapeHtml(parentName)}</span>
                    ${rp.reason ? `<span class="text-xs text-gray-500 ml-1">(${escapeHtml(rp.reason)})</span>` : ''}
                </label>
            `;
        });
        rpHtml += '</div>';
        // Insertar después de asignaciones
        assignDiv.insertAdjacentHTML('afterend', `<div id="llmReparentsProposal">${rpHtml}</div>`);
    }
    
    // Uso de tokens
    if (proposal.usage) {
        const modelUsed = proposal.usage.model_used ? ` | Modelo: ${proposal.usage.model_used}` : '';
        document.getElementById('llmUsage').textContent = 
            `Tokens: ${proposal.usage.prompt_tokens} entrada + ${proposal.usage.completion_tokens} salida | ` +
            `Coste: $${proposal.usage.cost_usd}${modelUsed}`;
    }
}

function llmToggleAll(type, checked) {
    const selector = type === 'cat' ? '.llm-check-cat' 
        : type === 'assign' ? '.llm-check-assign' 
        : '.llm-check-reparent';
    document.querySelectorAll(selector).forEach(cb => cb.checked = checked);
}

async function applyLlmProposal() {
    if (!llmProposal) return;
    
    // Recoger solo los items seleccionados
    const selectedCategories = [];
    const selectedSlugs = new Set();
    
    (llmProposal.categories || []).forEach((cat, ci) => {
        const parentCheck = document.querySelector(`.llm-check-cat[data-cat-idx="${ci}"]:not([data-child-idx])`);
        if (parentCheck && parentCheck.checked) {
            const selectedCat = { ...cat, children: [] };
            selectedSlugs.add(cat.slug);
            // Recoger hijos seleccionados
            (cat.children || []).forEach((child, chi) => {
                const childCheck = document.querySelector(`.llm-check-cat[data-cat-idx="${ci}"][data-child-idx="${chi}"]`);
                if (childCheck && childCheck.checked) {
                    selectedCat.children.push(child);
                    selectedSlugs.add(child.slug);
                }
            });
            selectedCategories.push(selectedCat);
        } else {
            // Aunque el padre no esté seleccionado, comprobar hijos sueltos
            (cat.children || []).forEach((child, chi) => {
                const childCheck = document.querySelector(`.llm-check-cat[data-cat-idx="${ci}"][data-child-idx="${chi}"]`);
                if (childCheck && childCheck.checked) {
                    // Hijo seleccionado sin padre: crear como categoría raíz
                    selectedCategories.push({ ...child, is_primary: false, children: [] });
                    selectedSlugs.add(child.slug);
                }
            });
        }
    });
    
    const selectedAssignments = [];
    (llmProposal.assignments || []).forEach((a, ai) => {
        const cb = document.querySelector(`.llm-check-assign[data-assign-idx="${ai}"]`);
        if (cb && cb.checked) {
            // Filtrar slugs de categorías que no se seleccionaron
            const validSlugs = (a.category_slugs || []).filter(s => selectedSlugs.has(s));
            if (validSlugs.length > 0) {
                selectedAssignments.push({ ...a, category_slugs: validSlugs });
            }
        }
    });
    
    const selectedReparents = [];
    (llmProposal.reparents || []).forEach((rp, ri) => {
        const cb = document.querySelector(`.llm-check-reparent[data-reparent-idx="${ri}"]`);
        if (cb && cb.checked) {
            selectedReparents.push(rp);
        }
    });
    
    const totalSelected = selectedCategories.length + selectedAssignments.length + selectedReparents.length;
    if (totalSelected === 0) {
        showToast('No hay elementos seleccionados para aplicar', 'error');
        return;
    }
    
    if (!confirm(`¿Aplicar ${selectedCategories.length} categorías, ${selectedAssignments.length} asignaciones y ${selectedReparents.length} reasignaciones seleccionadas?`)) return;
    
    try {
        const resp = await fetch(`${BASE_PATH}/api/admin/apply_categories`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                categories: selectedCategories,
                assignments: selectedAssignments,
                reparents: selectedReparents
            })
        });
        
        if (!resp.ok) throw new Error(`Error ${resp.status}`);
        
        const result = await resp.json();
        let msg = `Categorías: ${result.created_categories}, asignaciones: ${result.applied_assignments}`;
        if (result.applied_reparents > 0) msg += `, reasignaciones: ${result.applied_reparents}`;
        showToast(msg, 'success');
        
        document.getElementById('llmResult').classList.add('hidden');
        const rpDiv = document.getElementById('llmReparentsProposal');
        if (rpDiv) rpDiv.remove();
        llmProposal = null;
        
        // Recargar datos
        await loadCategories();
        await loadQueries();
    } catch (e) {
        showToast(`Error: ${e.message}`, 'error');
    }
}

// =============================================
//  Utilidades
// =============================================
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function escapeAttr(text) {
    if (!text) return '';
    return text
        .replace(/&/g, '&amp;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

function generateSlug(text) {
    return text
        .toLowerCase()
        .normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '')
        .replace(/[^a-z0-9\s-]/g, '')
        .replace(/\s+/g, '-')
        .replace(/-+/g, '-')
        .trim();
}

function showToast(message, type = 'success') {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.className = `toast toast-${type}`;
    toast.classList.remove('hidden');
    
    setTimeout(() => {
        toast.classList.add('hidden');
    }, 3000);
}
