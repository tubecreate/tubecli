const API = '/api/v1/scripts';

// Fallback translation helper if /static/i18n.js is not loaded
if (typeof T !== 'function') {
    window.T = function(key, vars) {
        const defaults = {
            "script_studio.toast_select_script": "⚠️ Please select a script before running",
            "script_studio.toast_select_profile": "⚠️ Please select a Browser Profile before running",
            "script_studio.toast_synced_profile": "🔄 Synced account credentials from profile",
            "script_studio.toast_duplicated_step": "📋 Duplicated step {idx}",
            "script_studio.toast_copied_clipboard": "📋 Copied {text} to clipboard",
            "script_studio.toast_describe_steps": "⚠️ Please describe the steps you want to generate",
            "script_studio.toast_select_script_first": "⚠️ Select a script first",
            "script_studio.toast_ai_generated_steps": "✅ AI generated {count} steps",
            "script_studio.toast_empty_var_name": "⚠️ Variable name cannot be empty",
            "script_studio.toast_var_exists": "⚠️ Variable \"{name}\" already exists",
            "script_studio.toast_var_created": "✅ Created variable {{{name}}}",
            "script_studio.toast_fn_inserted": "📦 Inserted function \"{name}\"",
            "script_studio.toast_ai_failed_steps": "❌ AI failed to generate steps",
            "script_studio.toast_error_ai_config": "❌ Error loading AI config",
            "script_studio.no_functions_available": "No functions available",
            "script_studio.no_functions_hint": "Mark a script as \"Function\" in Settings to use this feature",
            "script_studio.add_steps_hint": "Add steps to start building your script",
            "script_studio.btn_add_first_step": "Add First Step",
            "script_studio.insert_step_above": "Insert step above",
            "script_studio.insert_step_below": "Insert step below",
            "script_studio.duplicate_step": "Duplicate step",
            "script_studio.ai_generate_here": "AI Generate steps here",
            "script_studio.insert_call_function": "Insert Call Function",
            "script_studio.create_var": "Create variable {{var}}",
            "script_studio.insert_var": "Insert variable",
            "script_studio.disable_step": "Disable step",
            "script_studio.enable_step": "Enable step",
            "script_studio.delete_step": "Delete step",
            "script_studio.add_new_step": "Add new step",
            "script_studio.ai_generate_steps": "AI Generate steps",
            "script_studio.chat_cleared": "Chat cleared. Ask me anything!",
            "script_studio.chat_script_updated": "✅ Script updated! View steps on the left.",
            "script_studio.chat_error": "❌ Error: {error}",
            "script_studio.status_generated": "✅ Successfully generated! {count} steps ({provider})",
            "script_studio.status_failed": "❌ Failed to generate script",
            "script_studio.status_error": "❌ Error: {error}",
            "script_studio.confirm_delete_script": "Delete this script?",
            "script_studio.confirm_delete_cookies": "Delete all cookies for profile \"{profile}\"?",
            "script_studio.url_pattern_label": "URL Pattern (Contains keyword/path to capture)",
            "script_studio.toast_cookies_deleted": "Cookies deleted"
        };
        let s = defaults[key] || key;
        if (vars) {
            Object.keys(vars).forEach(k => {
                s = s.replace(new RegExp('\\{' + k + '\\}', 'g'), vars[k]);
            });
        }
        return s;
    };
}
let currentScript = null;
let scripts = [];
let previewSession = null;
let pickerActive = false;
let cachedProfileData = null; // Cached profile info (loaded once, updated on profile change)
let cachedProfilesList = []; // All browser profiles loaded from API
let cachedAIModels = {}; // Cached AI models list by provider

// ── Init ──
document.addEventListener('DOMContentLoaded', async () => {
    if (typeof loadI18nFromApi === 'function') {
        await loadI18nFromApi();
    }
    loadScripts();

    // Restore last selected engine from localStorage first (for filtering profile list)
    const savedEngine = localStorage.getItem('scriptStudio_engine');
    if (savedEngine) {
        const engineEl = document.getElementById('execEngine');
        if (engineEl) engineEl.value = savedEngine;
    }

    loadProfiles().then(() => {
        // Load cached profile data for the initially selected profile
        const sel = document.getElementById('execProfile');
        if (sel && sel.value) loadProfileData(sel.value);
    });
    setupEventListeners();
    setupResizeHandles();

    // Load AI Provider configurations and select default
    loadAIProviders();

    // Save AI model selection on change
    document.getElementById('aiModelSelect')?.addEventListener('change', (e) => {
        const prov = document.querySelector('#aiProviderChips .ext-chip.active')?.dataset.provider || 'auto';
        localStorage.setItem('scriptStudio_aiModel', e.target.value);
        localStorage.setItem('scriptStudio_aiModel_' + prov, e.target.value);
    });

    // Save engine selection on change and re-filter profiles
    document.getElementById('execEngine')?.addEventListener('change', (e) => {
        localStorage.setItem('scriptStudio_engine', e.target.value);
        filterProfilesByEngine(e.target.value);
    });

    // Save profile selection on change → reload profile data
    document.getElementById('execProfile')?.addEventListener('change', (e) => {
        if (e.target.value) {
            localStorage.setItem('scriptStudio_profile', e.target.value);
            loadProfileData(e.target.value);
        } else {
            cachedProfileData = null;
            localStorage.removeItem('scriptStudio_profile');
        }
    });
});



function setupEventListeners() {
    document.getElementById('btnNewScript').onclick = () => showModal('newScriptModal');
    document.getElementById('btnAddStep').onclick = () => showModal('stepTypeModal');
    document.getElementById('btnImportScript').onclick = importScriptPrompt;
    document.getElementById('btnAIGenerate').onclick = () => {
        loadAIProviders();
        showModal('aiGenerateModal');
    };
    document.getElementById('searchScripts').oninput = e => filterScripts(e.target.value);
    document.querySelectorAll('.category-item').forEach(el => {
        el.onclick = () => {
            document.querySelectorAll('.category-item').forEach(c => c.classList.remove('active'));
            el.classList.add('active');
            loadScripts(el.dataset.category);
        };
    });
    document.querySelectorAll('.tab').forEach(tab => {
        tab.onclick = () => {
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            tab.classList.add('active');
            document.getElementById('tab' + capitalize(tab.dataset.tab)).classList.add('active');
        };
    });
}

// ── API Helpers ──
async function api(url, opts = {}) {
    const res = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...opts });
    return res.json();
}

// ── Scripts CRUD ──
async function loadScripts(category) {
    const q = category ? `?category=${category}` : '';
    const data = await api(`${API}${q}`);
    scripts = data.scripts || [];
    renderScriptList();
}

function renderScriptList() {
    const list = document.getElementById('scriptList');
    if (!scripts.length) {
        list.innerHTML = '<div class="empty-state"><span class="material-symbols-outlined">code_off</span><p>No scripts yet</p></div>';
        return;
    }
    list.innerHTML = scripts.map(s => `
        <div class="script-item ${currentScript?.id === (s.slug || s.id) ? 'active' : ''}" onclick="selectScript('${esc(s.slug || s.id)}')">
            <div class="script-item-name">${s.is_function ? '📦 ' : ''}${esc(s.name)}</div>
            <div class="script-item-meta">
                <span>${getCategoryIcon(s.category)} ${s.category}</span>
                <span>${(s.steps || []).length} steps</span>
            </div>
            <div class="script-item-actions">
                <button class="step-action-btn" onclick="event.stopPropagation();duplicateScript('${esc(s.slug || s.id)}')" title="Duplicate">
                    <span class="material-symbols-outlined" style="font-size:0.9rem">content_copy</span>
                </button>
                <button class="step-action-btn" onclick="event.stopPropagation();deleteScript('${esc(s.slug || s.id)}')" title="Delete">
                    <span class="material-symbols-outlined" style="font-size:0.9rem">delete</span>
                </button>
            </div>
        </div>
    `).join('');
}

async function selectScript(idOrSlug) {
    currentScript = await api(`${API}/${idOrSlug}`);
    if (currentScript && currentScript.slug) {
        currentScript.id = currentScript.slug; // Use slug as primary key
    }
    document.getElementById('currentScriptName').textContent = currentScript.name;
    renderScriptList();
    renderSteps();
    renderVariables();
    fillSettings();
    loadHistory();
    
    // Sync profile variables if a profile is currently selected
    if (document.getElementById('execProfile')?.value) {
        syncProfileVariablesToScript();
    }
}

async function createNewScript() {
    const name = document.getElementById('newScriptName').value.trim();
    if (!name) return;
    const data = await api(API, {
        method: 'POST',
        body: JSON.stringify({
            name,
            category: document.getElementById('newScriptCategory').value,
            target_url: document.getElementById('newScriptUrl').value.trim(),
        })
    });
    closeModal('newScriptModal');
    document.getElementById('newScriptName').value = '';
    await loadScripts();
    if (data.script) selectScript(data.script.slug || data.script.id);
}

async function deleteScript(slug) {
    if (!confirm(T('script_studio.confirm_delete_script'))) return;
    await api(`${API}/${slug}`, { method: 'DELETE' });
    if (currentScript?.id === slug) currentScript = null;
    loadScripts();
}

async function duplicateScript(slug) {
    const data = await api(`${API}/${slug}/duplicate`, { method: 'POST' });
    await loadScripts();
    if (data.script) selectScript(data.script.slug || data.script.id);
}

// ── Steps ──
const STEP_ICONS = {
    navigate: 'language', click: 'ads_click', type: 'keyboard', wait: 'hourglass_empty',
    sleep: 'timer', evaluate: 'code', extract: 'content_copy', screenshot: 'screenshot_monitor',
    download: 'download', condition: 'call_split', loop: 'loop', keyboard: 'keyboard_return',
    wait_hidden: 'visibility_off', scroll: 'swap_vert', mouse_move: 'mouse', hover: 'near_me',
    ai_generate: 'auto_awesome', call_function: 'functions', wait_network_response: 'network_check',
};

function renderSteps() {
    const list = document.getElementById('stepsList');
    const steps = currentScript?.steps || [];
    if (!steps.length) {
        list.innerHTML = '<div class="empty-state"><span class="material-symbols-outlined">list_alt</span><p>Add steps to build your script</p><button class="btn btn-primary btn-sm" onclick="showModal(\'stepTypeModal\')"><span class="material-symbols-outlined">add</span> Add Step</button></div>';
        return;
    }
    list.innerHTML = steps.map((s, i) => `
        <div class="step-card ${s.enabled === false ? 'disabled' : ''}" data-index="${i}" id="step-${i}" oncontextmenu="event.preventDefault();event.stopPropagation();showStepContextMenu(event,${i})">
            <div class="step-header" onclick="toggleStep(${i})">
                <span class="step-drag material-symbols-outlined" style="font-size:1rem">drag_indicator</span>
                <span class="step-index">${i + 1}</span>
                <span class="step-type-icon material-symbols-outlined">${STEP_ICONS[s.type] || 'code'}</span>
                <span class="step-label">${esc(s.label || s.type)}</span>
                <div class="step-actions">
                    <button class="step-action-btn" onclick="event.stopPropagation();testStep(${i})" title="Test step">
                        <span class="material-symbols-outlined" style="font-size:0.9rem">play_arrow</span>
                    </button>
                    <button class="step-action-btn" onclick="event.stopPropagation();toggleEnabled(${i})" title="Toggle">
                        <span class="material-symbols-outlined" style="font-size:0.9rem">${s.enabled === false ? 'toggle_off' : 'toggle_on'}</span>
                    </button>
                    <button class="step-action-btn" onclick="event.stopPropagation();removeStep(${i})" title="Remove">
                        <span class="material-symbols-outlined" style="font-size:0.9rem">close</span>
                    </button>
                </div>
            </div>
            <div class="step-body">${renderStepBody(s, i)}</div>
        </div>
    `).join('');
    setupDragDrop();
    // Also attach contextmenu to the steps list container for right-click on empty area
    list.oncontextmenu = (e) => {
        if (e.target === list || e.target.closest('.empty-state')) {
            e.preventDefault();
            showStepContextMenu(e, -1);
        }
    };
}

function renderStepBody(step, idx) {
    const p = step.params || {};
    let html = `<div class="form-group"><label>Label</label><input class="form-input" value="${esc(step.label || '')}" onchange="updateStepField(${idx},'label',this.value)"></div>`;

    if (['click', 'type', 'wait', 'wait_hidden', 'extract', 'download'].includes(step.type)) {
        html += `<div class="form-group"><label>CSS Selector</label><div class="selector-row"><input class="form-input" value="${esc(step.selector || '')}" onchange="updateStepField(${idx},'selector',this.value)"><button class="btn btn-sm btn-accent" onclick="pickElement(${idx})" title="Pick from browser"><span class="material-symbols-outlined" style="font-size:1rem">my_location</span></button></div></div>`;
    }
    if (step.type === 'navigate') {
        html += `<div class="form-group"><label>URL</label><input class="form-input" value="${esc(p.url || '')}" onchange="updateStepParam(${idx},'url',this.value)"></div>`;
    }
    if (step.type === 'type') {
        html += `<div class="form-group"><label>Text</label><textarea class="form-input" rows="2" onchange="updateStepParam(${idx},'text',this.value)">${esc(p.text || '')}</textarea></div>`;
        html += `<div class="form-group"><label><input type="checkbox" ${p.clear_first ? 'checked' : ''} onchange="updateStepParam(${idx},'clear_first',this.checked)"> Clear first</label></div>`;
    }
    if (step.type === 'sleep') {
        html += `<div class="form-group"><label>Duration (ms)</label><input type="number" class="form-input" value="${p.ms || 2000}" onchange="updateStepParam(${idx},'ms',+this.value)"></div>`;
    }
    if (step.type === 'wait_network_response') {
        html += `<div class="form-group"><label>${T('script_studio.url_pattern_label')}</label><input class="form-input" value="${esc(p.url_pattern || p.url || '')}" onchange="updateStepParam(${idx},'url_pattern',this.value)" placeholder="vd: /api/v1/user"></div>`;
        html += `<div class="form-group"><label>Expected HTTP Status</label><input type="number" class="form-input" value="${p.status || 200}" onchange="updateStepParam(${idx},'status',+this.value)"></div>`;
        html += `<div class="form-group"><label>Save Response as Variable</label><input class="form-input" value="${esc(p.save_as || '_network_data')}" onchange="updateStepParam(${idx},'save_as',this.value)"></div>`;
    }
    if (step.type === 'evaluate') {
        html += `<div class="form-group"><label>JavaScript Code</label><textarea class="form-input" rows="4" style="font-family:var(--mono)" onchange="updateStepParam(${idx},'code',this.value)">${esc(p.code || '')}</textarea></div>`;
        html += `<div class="form-group"><label>Save result as variable</label><input class="form-input" value="${esc(p.save_as || '')}" onchange="updateStepParam(${idx},'save_as',this.value)"></div>`;
    }
    if (step.type === 'extract') {
        html += `<div class="form-group"><label>Attribute</label><select class="form-input" onchange="updateStepParam(${idx},'attribute',this.value)"><option value="innerText" ${p.attribute === 'innerText' ? 'selected' : ''}>innerText</option><option value="innerHTML" ${p.attribute === 'innerHTML' ? 'selected' : ''}>innerHTML</option><option value="href" ${p.attribute === 'href' ? 'selected' : ''}>href</option><option value="src" ${p.attribute === 'src' ? 'selected' : ''}>src</option><option value="value" ${p.attribute === 'value' ? 'selected' : ''}>value</option></select></div>`;
        html += `<div class="form-group"><label>Save as variable</label><input class="form-input" value="${esc(p.save_as || '')}" onchange="updateStepParam(${idx},'save_as',this.value)"></div>`;
    }
    if (step.type === 'keyboard') {
        html += `<div class="form-group"><label>Key</label><input class="form-input" value="${esc(p.key || 'Enter')}" onchange="updateStepParam(${idx},'key',this.value)"></div>`;
    }
    if (step.type === 'loop') {
        html += `<div class="form-group"><label>Iterations</label><input type="number" class="form-input" value="${p.count || 1}" onchange="updateStepParam(${idx},'count',+this.value)"></div>`;
        html += `<div class="form-group"><label>Delay between (ms)</label><input type="number" class="form-input" value="${p.delay || 1000}" onchange="updateStepParam(${idx},'delay',+this.value)"></div>`;
    }
    if (step.type === 'call_function') {
        html += `<div class="form-group"><label>Function Slug</label><input class="form-input" value="${esc(p.function_slug || '')}" onchange="updateStepParam(${idx},'function_slug',this.value)" placeholder="gmail_login_with_2fa"></div>`;
        html += `<div class="form-group"><label>Inputs (JSON: {"fn_var": "{{caller_var}}"})</label><textarea class="form-input" rows="3" style="font-family:var(--mono)" onchange="try{updateStepParam(${idx},'inputs',JSON.parse(this.value))}catch(e){}">${esc(JSON.stringify(p.inputs || {}, null, 2))}</textarea></div>`;
        html += `<div class="form-group"><label>Outputs (JSON: {"caller_var": "fn_output_var"})</label><textarea class="form-input" rows="2" style="font-family:var(--mono)" onchange="try{updateStepParam(${idx},'outputs',JSON.parse(this.value))}catch(e){}">${esc(JSON.stringify(p.outputs || {}, null, 2))}</textarea></div>`;
    }

    // Error handling
    html += `<div style="display:flex;gap:8px;margin-top:8px">`;
    html += `<div class="form-group" style="flex:1"><label>On Error</label><select class="form-input" onchange="updateStepField(${idx},'on_error',this.value)"><option value="abort" ${step.on_error === 'abort' ? 'selected' : ''}>Abort</option><option value="skip" ${step.on_error === 'skip' ? 'selected' : ''}>Skip</option><option value="retry" ${step.on_error === 'retry' ? 'selected' : ''}>Retry</option></select></div>`;
    html += `<div class="form-group" style="width:80px"><label>Retries</label><input type="number" class="form-input" value="${step.retry_count || 0}" onchange="updateStepField(${idx},'retry_count',+this.value)"></div>`;
    html += `<div class="form-group" style="width:100px"><label>Timeout</label><input type="number" class="form-input" value="${(p.timeout || 10000)}" onchange="updateStepParam(${idx},'timeout',+this.value)"></div>`;
    html += `</div>`;
    return html;
}

function toggleStep(idx) {
    const card = document.getElementById(`step-${idx}`);
    card.classList.toggle('expanded');
}

function updateStepField(idx, field, value) {
    if (!currentScript) return;
    currentScript.steps[idx][field] = value;
    saveSteps();
}

function updateStepParam(idx, param, value) {
    if (!currentScript) return;
    if (!currentScript.steps[idx].params) currentScript.steps[idx].params = {};
    currentScript.steps[idx].params[param] = value;
    saveSteps();
}

function toggleEnabled(idx) {
    if (!currentScript) return;
    currentScript.steps[idx].enabled = currentScript.steps[idx].enabled === false ? true : false;
    renderSteps();
    saveSteps();
}

function removeStep(idx) {
    if (!currentScript) return;
    currentScript.steps.splice(idx, 1);
    renderSteps();
    saveSteps();
}

function addStep() { showModal('stepTypeModal'); }

// insertAtIndex: if >= 0, insert at that position; if -1 or undefined, append to end
let _pendingInsertIndex = -1;

async function insertStep(type) {
    if (!currentScript) {
        // Auto-create a script if none selected
        const data = await api(API, {
            method: 'POST',
            body: JSON.stringify({ name: 'Untitled Script', category: 'general' })
        });
        if (data.script) {
            await loadScripts();
            await selectScript(data.script.slug || data.script.id);
        }
        if (!currentScript) return;
    }
    if (!currentScript.steps) currentScript.steps = [];
    const newStep = {
        id: `step_${Date.now()}`,
        type,
        label: type.charAt(0).toUpperCase() + type.slice(1),
        enabled: true,
        selector: '',
        params: {},
        on_error: 'abort',
        retry_count: 0,
    };
    const idx = _pendingInsertIndex;
    _pendingInsertIndex = -1; // Reset
    if (idx >= 0 && idx <= currentScript.steps.length) {
        currentScript.steps.splice(idx, 0, newStep);
    } else {
        currentScript.steps.push(newStep);
    }
    closeModal('stepTypeModal');
    renderSteps();
    saveSteps();
    // Auto expand the inserted step
    const expandIdx = (idx >= 0 && idx <= currentScript.steps.length - 1) ? idx : currentScript.steps.length - 1;
    const card = document.getElementById(`step-${expandIdx}`);
    if (card) card.classList.add('expanded');
}

function insertStepAt(index) {
    _pendingInsertIndex = index;
    showModal('stepTypeModal');
}

async function saveSteps() {
    if (!currentScript) return;
    await api(`${API}/${currentScript.id}/steps`, {
        method: 'PUT',
        body: JSON.stringify({ steps: currentScript.steps })
    });
}

// ── Drag & Drop ──
function setupDragDrop() {
    const list = document.getElementById('stepsList');
    let dragIdx = null;
    list.querySelectorAll('.step-drag').forEach((handle, idx) => {
        const card = handle.closest('.step-card');
        card.setAttribute('draggable', true);
        card.ondragstart = e => { dragIdx = idx; e.dataTransfer.effectAllowed = 'move'; card.style.opacity = '0.5'; };
        card.ondragend = () => { card.style.opacity = '1'; };
        card.ondragover = e => { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; };
        card.ondrop = e => {
            e.preventDefault();
            if (dragIdx === null || dragIdx === idx) return;
            const steps = currentScript.steps;
            const [moved] = steps.splice(dragIdx, 1);
            steps.splice(idx, 0, moved);
            dragIdx = null;
            renderSteps();
            saveSteps();
        };
    });
}

// ── Variables ──
function renderVariables() {
    const list = document.getElementById('variablesList');
    const vars = currentScript?.variables || [];
    if (!vars.length) {
        list.innerHTML = '<div class="empty-state" style="padding:20px"><p>No variables defined</p></div>';
        return;
    }
    list.innerHTML = vars.map((v, i) => `
        <div class="variable-row">
            <input class="form-input" value="${esc(v.name || '')}" placeholder="Name" onchange="updateVar(${i},'name',this.value)">
            <select class="form-input" style="width:100px" onchange="updateVar(${i},'type',this.value)">
                <option value="string" ${v.type === 'string' ? 'selected' : ''}>String</option>
                <option value="number" ${v.type === 'number' ? 'selected' : ''}>Number</option>
                <option value="boolean" ${v.type === 'boolean' ? 'selected' : ''}>Boolean</option>
            </select>
            <input class="form-input" value="${esc(v.default || '')}" placeholder="Default" onchange="updateVar(${i},'default',this.value)">
            <button class="step-action-btn" onclick="removeVar(${i})"><span class="material-symbols-outlined" style="font-size:0.9rem">close</span></button>
        </div>
    `).join('');
}

function addVariable() {
    if (!currentScript) return;
    if (!currentScript.variables) currentScript.variables = [];
    currentScript.variables.push({ name: '', type: 'string', default: '' });
    renderVariables();
}

function updateVar(idx, field, value) {
    currentScript.variables[idx][field] = value;
    api(`${API}/${currentScript.id}`, { method: 'PUT', body: JSON.stringify({ variables: currentScript.variables }) });
}

function removeVar(idx) {
    currentScript.variables.splice(idx, 1);
    renderVariables();
    api(`${API}/${currentScript.id}`, { method: 'PUT', body: JSON.stringify({ variables: currentScript.variables }) });
}

// ── Settings ──
function fillSettings() {
    if (!currentScript) return;
    document.getElementById('settingName').value = currentScript.name || '';
    document.getElementById('settingSlug').value = currentScript.slug || '';
    document.getElementById('settingDesc').value = currentScript.description || '';
    document.getElementById('settingCategory').value = currentScript.category || 'general';
    document.getElementById('settingUrl').value = currentScript.target_url || '';
    document.getElementById('settingIsFunction').checked = currentScript.is_function || false;
}

async function saveSettings() {
    if (!currentScript) return;
    const isFunction = document.getElementById('settingIsFunction').checked;
    await api(`${API}/${currentScript.id}`, {
        method: 'PUT',
        body: JSON.stringify({
            name: document.getElementById('settingName').value,
            slug: document.getElementById('settingSlug').value,
            description: document.getElementById('settingDesc').value,
            category: document.getElementById('settingCategory').value,
            target_url: document.getElementById('settingUrl').value,
            is_function: isFunction,
        })
    });
    currentScript.name = document.getElementById('settingName').value;
    currentScript.is_function = isFunction;
    document.getElementById('currentScriptName').textContent = currentScript.name;
    loadScripts();
}

// ── Execution ──
let currentExecId = null;

async function runScript() {
    if (!currentScript) {
        showToast(T('script_studio.toast_select_script'), 'warning');
        return;
    }
    const profile = document.getElementById('execProfile').value;
    if (!profile) {
        showToast(T('script_studio.toast_select_profile'), 'warning');
        // Highlight the profile dropdown briefly
        const sel = document.getElementById('execProfile');
        sel.style.outline = '2px solid #f59e0b';
        sel.focus();
        setTimeout(() => { sel.style.outline = ''; }, 2000);
        return;
    }
    const vars = {};
    (currentScript.variables || []).forEach(v => { if (v.name) vars[v.name] = v.default || ''; });
    const showBrowser = document.getElementById('showBrowserToggle')?.checked || false;
    const engine = document.getElementById('execEngine')?.value || 'playwright';
    const data = await api(`${API}/${currentScript.id}/run`, {
        method: 'POST',
        body: JSON.stringify({ profile, variables: vars, headless: !showBrowser, engine })
    });
    currentExecId = data.exec_id;
    document.getElementById('btnRun').disabled = true;
    document.getElementById('btnStop').disabled = false;
    document.getElementById('btnPause').disabled = false;
    appendLog('Script started...', 'info');
    pollExecution();
}

let scriptPaused = false;

function togglePauseScript() {
    if (!previewWs || previewWs.readyState !== 1) return;
    scriptPaused = !scriptPaused;
    const btn = document.getElementById('btnPause');
    if (scriptPaused) {
        previewWs.send(JSON.stringify({ type: 'pause' }));
        btn.innerHTML = '<span class="material-symbols-outlined">play_arrow</span> Resume';
        btn.classList.remove('btn-warning');
        btn.classList.add('btn-success');
        appendLog('⏸ Script paused — you can interact with the browser.', 'info');
    } else {
        previewWs.send(JSON.stringify({ type: 'resume' }));
        btn.innerHTML = '<span class="material-symbols-outlined">pause</span> Pause';
        btn.classList.remove('btn-success');
        btn.classList.add('btn-warning');
        appendLog('▶ Script resumed.', 'info');
    }
}

function finishExecutionUI() {
    if (logPollTimer) {
        clearInterval(logPollTimer);
        logPollTimer = null;
    }
    // The run is over — the per-run preview server has shut down. Mark the
    // preview stopped and close the socket cleanly (code 1000, which onclose
    // treats as intentional) so it does not reconnect into a dead port loop.
    // Any step still showing the running spinner must stop — on Stop/fail it
    // would otherwise spin forever. Only the 'running' class is removed, so a
    // step already marked success/error keeps its mark.
    document.querySelectorAll('.step-card.running').forEach(el => el.classList.remove('running'));

    previewStopped = true;
    if (previewReconnectTimer) { clearTimeout(previewReconnectTimer); previewReconnectTimer = null; }
    if (previewWs) {
        try { previewWs.close(1000, 'run finished'); } catch (e) {}
        previewWs = null;
    }
    stopScreenshotStream();
    document.getElementById('btnRun').disabled = false;
    document.getElementById('btnStop').disabled = true;
    document.getElementById('btnPause').disabled = true;
    scriptPaused = false;
    const pauseBtn = document.getElementById('btnPause');
    pauseBtn.innerHTML = '<span class="material-symbols-outlined">pause</span> Pause';
    pauseBtn.classList.remove('btn-success');
    pauseBtn.classList.add('btn-warning');
    
    // Refresh profile cache (cookies/fingerprint may have changed during execution)
    const profile = document.getElementById('execProfile')?.value;
    if (profile) loadProfileData(profile);
}

async function stopScript() {
    if (!currentExecId) return;
    // Send stop via WS first (graceful)
    if (previewWs && previewWs.readyState === 1) {
        previewWs.send(JSON.stringify({ type: 'stop_script' }));
        appendLog('Stop script requested...', 'info');
    } else {
        // WS is not connected -> force kill
        await api(`${API}/execution/${currentExecId}/stop`, { method: 'POST' });
        finishExecutionUI();
        appendLog('Script stopped (forced).', 'error');
    }
}

let logPollTimer = null;
let logOffset = 0;
let activeStepIndex = -1;

function clearStepStates() {
    document.querySelectorAll('.step-card').forEach(el => {
        el.classList.remove('running', 'success', 'error', 'ai-fixing');
    });
    activeStepIndex = -1;
}

function setStepState(index, state) {
    // Clear previous running state
    if (state === 'running') {
        document.querySelectorAll('.step-card.running').forEach(el => el.classList.remove('running'));
    }
    const card = document.getElementById(`step-${index}`);
    if (!card) return;
    card.classList.remove('running', 'success', 'error', 'ai-fixing');
    if (state) card.classList.add(state);
    if (state === 'running') {
        activeStepIndex = index;
        card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
}

function parseStepLog(line) {
    if (typeof line !== 'string') return;
    // Try JSON parse
    if (line.trimStart().startsWith('{')) {
        try {
            const parsed = JSON.parse(line);
            if (parsed.status === 'step' && parsed.step_index !== undefined) {
                const idx = parseInt(parsed.step_index);
                const msg = parsed.message || '';
                if (msg.includes('failed') || msg.includes('FAILED')) {
                    setStepState(idx, 'error');
                } else if (msg.includes('SKIPPED')) {
                    // skip
                } else {
                    setStepState(idx, 'running');
                }
            }
            if (parsed.status === 'done') {
                if (parsed.success) {
                    // Mark last running step as success
                    if (activeStepIndex >= 0) setStepState(activeStepIndex, 'success');
                } else if (parsed.stopped) {
                    // User stop: clear the running spinner, no red error mark.
                    if (activeStepIndex >= 0) setStepState(activeStepIndex, '');
                } else {
                    // Real failure: mark the step that failed.
                    if (activeStepIndex >= 0) setStepState(activeStepIndex, 'error');
                }
                finishExecutionUI();
            }
            // Detect AI fix
            if (parsed.message && parsed.message.includes('AI Auto-Fix')) {
                if (activeStepIndex >= 0) setStepState(activeStepIndex, 'ai-fixing');
            }
            if (parsed.message && parsed.message.includes('✅')) {
                if (activeStepIndex >= 0) setStepState(activeStepIndex, 'success');
            }
            return;
        } catch (e) {}
    }

    // Non-JSON fallback: detect step status from text
    if (line.includes('AI Auto-Fix')) {
        if (activeStepIndex >= 0) setStepState(activeStepIndex, 'ai-fixing');
    } else if (line.includes('✅') || line.includes('AI fix worked')) {
        if (activeStepIndex >= 0) setStepState(activeStepIndex, 'success');
    } else if (line.includes('Navigated to') || line.includes('Clicked') || line.includes('Typed') ||
               line.includes('Element visible') || line.includes('Slept') || line.includes('Pressed key') ||
               line.includes('Extracted') || line.includes('Evaluated') || line.includes('Screenshot saved')) {
        // Step completed successfully
        if (activeStepIndex >= 0) setStepState(activeStepIndex, 'success');
    } else if (line.includes('failed') || line.includes('❌')) {
        if (activeStepIndex >= 0) setStepState(activeStepIndex, 'error');
    }
}

async function pollExecution() {
    if (!currentExecId) return;
    logOffset = 0;
    clearStepStates();
    if (logPollTimer) clearInterval(logPollTimer);
    logPollTimer = setInterval(async () => {
        try {
            const data = await api(`${API}/execution/${currentExecId}/logs?offset=${logOffset}`);
            if (data.lines && data.lines.length > 0) {
                data.lines.forEach(line => {
                    appendLog(line);
                    parseStepLog(line);

                    // Check if runner reported a preview port
                    if (typeof line === 'string' && line.includes('preview_port')) {
                        try {
                            const parsed = JSON.parse(line);
                            if (parsed.preview_port) {
                                previewSession = { port: parsed.preview_port };
                                // Prefer WebSocket for real-time preview
                                if (parsed.preview_ws) {
                                    connectPreviewWS(parsed.preview_port);
                                } else {
                                    startScreenshotStream();
                                }
                                document.getElementById('btnLaunchPreview').innerHTML =
                                    '<span class="material-symbols-outlined">check_circle</span> Live';
                                document.getElementById('btnLaunchPreview').classList.add('btn-success');
                            }
                        } catch (e) {}
                    }
                });
                logOffset = data.offset;
            }
            if (!data.running) {
                finishExecutionUI();
            }
        } catch (e) {}
    }, 800);
}

async function testStep(idx) {
    appendLog(`Testing step ${idx + 1}...`, 'info');
    // For now just log — full implementation would run single step via preview browser
}

// ── Browser Preview (WebSocket + CDP Screencast) ──
let previewWs = null;
let previewCanvas = null;
let previewCtx = null;
let previewScale = { x: 1, y: 1 };
// True once the run has finished: the preview server on the run's port is gone,
// so any further reconnect would connect, find a dead upstream, drop, and loop
// forever. onclose checks this to stop reconnecting.
let previewStopped = false;
// The pending WS reconnect timer, so finishExecutionUI can CANCEL it — otherwise
// a timer scheduled just before the run ended fires afterward, reopens the dead
// port and restarts the whole reconnect+screenshot loop (a dangling setInterval
// + WS churn that never stops until the page reloads).
let previewReconnectTimer = null;

async function launchPreview() {
    const profile = document.getElementById('execProfile').value;
    const url = document.getElementById('previewUrl').value || 'about:blank';
    appendLog('Launching browser preview...', 'info');
    const data = await api(`${API}/preview/launch`, {
        method: 'POST',
        body: JSON.stringify({ profile, url })
    });
    if (data.session_id) {
        previewSession = data;
        appendLog(`Browser launched on port ${data.port}`, 'success');
        document.getElementById('btnLaunchPreview').textContent = 'Connected';
        connectPreviewWS(data.port);
    }
}

function connectPreviewWS(port) {
    if (previewWs) { previewWs.close(); previewWs = null; }
    previewStopped = false;   // a fresh run — reconnect is allowed again
    stopScreenshotStream();

    const container = document.getElementById('previewContainer');
    container.innerHTML = `
        <div id="canvasWrapper" style="position:relative; display:inline-block; max-width:100%; max-height:100%; line-height:0;">
            <canvas id="previewCanvas" style="cursor:crosshair;display:block;max-width:100%;max-height:100%;object-fit:contain;border-radius:2px;"></canvas>
            <div id="inspectOverlay" style="position:absolute;pointer-events:none;border:2px solid #58a6ff;background:rgba(88,166,255,0.1);display:none;z-index:10;box-sizing:border-box;"></div>
        </div>
        <div id="inspectInfo" style="position:absolute;bottom:10px;left:10px;background:#1a1a2e;color:#e0e0e0;padding:8px 12px;border-radius:6px;font:12px monospace;z-index:10;pointer-events:none;display:none;box-shadow:var(--shadow)"></div>
    `;
    previewCanvas = document.getElementById('previewCanvas');
    previewCtx = previewCanvas.getContext('2d', { alpha: false });

    try {
        // Detect if accessed via remote domain (tunnel) — use server proxy
        const isRemote = location.hostname !== 'localhost' && location.hostname !== '127.0.0.1';
        let wsUrl;
        if (isRemote) {
            // Proxy through main server: wss://domain/api/v1/scripts/preview/ws/{port}
            const wsProto = location.protocol === 'https:' ? 'wss:' : 'ws:';
            wsUrl = `${wsProto}//${location.host}/api/v1/scripts/preview/ws/${port}`;
        } else {
            wsUrl = `ws://localhost:${port}`;
        }
        appendLog(`Connecting preview: ${wsUrl}`, 'info');
        previewWs = new WebSocket(wsUrl);

        // Timeout: if WS doesn't connect within 5s, fall back to screenshots
        const wsTimeout = setTimeout(() => {
            if (previewWs && previewWs.readyState !== 1) {
                appendLog('WebSocket timeout, falling back to screenshots', 'info');
                try { previewWs.close(); } catch (e) {}
                previewWs = null;
                startScreenshotStream();
            }
        }, 5000);

        const origOnOpen = null;
        previewWs._clearTimeout = () => clearTimeout(wsTimeout);
    } catch (e) {
        appendLog('WebSocket failed, falling back to screenshots', 'error');
        startScreenshotStream();
        return;
    }

    previewWs.onopen = () => {
        if (previewWs._clearTimeout) previewWs._clearTimeout();
        // NOTE: the retry counter is NOT reset here. Opening only proves the
        // relay accepted us, not that the upstream preview server is alive — a
        // dead port opens then closes instantly. Resetting on open made every
        // phantom open wipe the counter, so the 5-attempt limit never tripped
        // and the reconnect looped forever. The counter is reset on the first
        // real FRAME instead (onmessage), which proves the pipe actually works.
        stopScreenshotStream(); // Stop fallback screenshots if they were running
        appendLog('🔴 Live preview connected (WebSocket)', 'success');
    };

    previewWs.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            if (msg.type === 'frame') {
                // A real frame proves the relay→upstream pipe is healthy. This
                // is where the reconnect counter resets — not on bare onopen.
                window._wsReconnectAttempt = 0;
                if (msg.viewport) window.previewCSSViewport = msg.viewport;
                // Draw CDP screencast frame on canvas
                const img = new Image();
                img.onload = () => {
                    if (previewCanvas.width !== img.width || previewCanvas.height !== img.height) {
                        previewCanvas.width = img.width;
                        previewCanvas.height = img.height;
                    }
                    previewCtx.drawImage(img, 0, 0);
                    // Calculate scale for mouse coordinate translation
                    const rect = previewCanvas.getBoundingClientRect();
                    previewScale.x = img.width / rect.width;
                    previewScale.y = img.height / rect.height;
                };
                img.src = 'data:image/jpeg;base64,' + msg.data;
            } else if (msg.type === 'picked') {
                // Element picker result
                if (msg.selector && pickerTargetStep !== null) {
                    const input = document.querySelector(`#step-${pickerTargetStep} .selector-row input`);
                    if (input) input.value = msg.selector;
                    updateStepField(pickerTargetStep, 'selector', msg.selector);
                    appendLog(`Picked: ${msg.selector}`, 'success');
                } else if (msg.selector) {
                    appendLog(`Element: ${msg.selector}`, 'info');
                }
                pickerActive = false;
                document.getElementById('btnPicker').classList.remove('btn-accent');
                document.getElementById('btnPicker').classList.add('btn-ghost');
            } else if (msg.type === 'inspect') {
                // Show hover overlay
                const overlay = document.getElementById('inspectOverlay');
                const info = document.getElementById('inspectInfo');
                if (window.previewCSSViewport && previewCanvas.width) {
                    const rect = previewCanvas.getBoundingClientRect();
                    const cw = previewCanvas.width;
                    const ch = previewCanvas.height;
                    const displayAspect = rect.width / rect.height;
                    const canvasAspect = cw / ch;
                    let renderW, renderH, offsetX, offsetY;
                    
                    if (canvasAspect > displayAspect) {
                        renderW = rect.width;
                        renderH = rect.width / canvasAspect;
                        offsetX = 0;
                        offsetY = (rect.height - renderH) / 2;
                    } else {
                        renderH = rect.height;
                        renderW = rect.height * canvasAspect;
                        offsetX = (rect.width - renderW) / 2;
                        offsetY = 0;
                    }
                    
                    const pctX = msg.rect.x / window.previewCSSViewport.width;
                    const pctY = msg.rect.y / window.previewCSSViewport.height;
                    const pctW = (msg.rect.width || msg.rect.w) / window.previewCSSViewport.width;
                    const pctH = (msg.rect.height || msg.rect.h) / window.previewCSSViewport.height;
                    
                    overlay.style.display = 'block';
                    overlay.style.left = (offsetX + pctX * renderW) + 'px';
                    overlay.style.top = (offsetY + pctY * renderH) + 'px';
                    overlay.style.width = (pctW * renderW) + 'px';
                    overlay.style.height = (pctH * renderH) + 'px';
                }
                info.style.display = 'block';
                info.textContent = `<${msg.tag}${msg.id ? '#' + msg.id : ''}${msg.classes ? '.' + msg.classes.split(' ')[0] : ''}> ${msg.text}`;
            } else if (msg.type === 'url_changed') {
                document.getElementById('previewUrl').value = msg.url || '';
            }
        } catch (e) {}
    };

    previewWs.onclose = (evt) => {
        previewWs = null;
        // The run finished (or the user stopped it): the preview server on this
        // port is gone, so reconnecting would just reopen → dead upstream →
        // close → loop. Stop here.
        if (previewStopped) {
            appendLog('Preview đã dừng.', 'info');
            stopScreenshotStream();
            return;
        }
        // Auto-reconnect unless intentionally closed (code 1000)
        if (evt.code !== 1000 && port) {
            const attempt = (window._wsReconnectAttempt || 0) + 1;
            window._wsReconnectAttempt = attempt;
            if (attempt <= 5) {
                const delay = Math.min(attempt * 2000, 10000);
                appendLog(`Preview disconnected — reconnecting in ${delay / 1000}s (attempt ${attempt}/5)`, 'info');
                startScreenshotStream(); // Fallback during reconnect
                previewReconnectTimer = setTimeout(() => {
                    previewReconnectTimer = null;
                    // Re-check previewStopped: the run may have finished while
                    // this timer was pending. Without this, the timer would call
                    // connectPreviewWS, which clears previewStopped and restarts
                    // the very loop finishExecutionUI just stopped.
                    if (!previewWs && !previewStopped) connectPreviewWS(port);
                }, delay);
            } else {
                appendLog('Preview disconnected — max reconnect attempts reached, using screenshots', 'info');
                startScreenshotStream();
                window._wsReconnectAttempt = 0;
            }
        } else {
            appendLog('Preview disconnected', 'info');
        }
    };

    previewWs.onerror = () => {
        appendLog('WebSocket error, falling back to screenshots', 'error');
        startScreenshotStream();
    };

    // Mouse events on canvas → forward to browser
    previewCanvas.addEventListener('click', (e) => {
        if (!previewWs) return;
        const { x, y } = canvasCoords(e);
        if (pickerActive) {
            previewWs.send(JSON.stringify({ type: 'pick_element', x, y }));
        } else {
            previewWs.send(JSON.stringify({ type: 'mouse', action: 'click', x, y }));
        }
    });

    previewCanvas.addEventListener('mousemove', (e) => {
        if (!previewWs) return;
        const { x, y } = canvasCoords(e);
        if (pickerActive) {
            previewWs.send(JSON.stringify({ type: 'hover_inspect', x, y }));
        }
    });

    previewCanvas.addEventListener('wheel', (e) => {
        if (!previewWs) return;
        e.preventDefault();
        previewWs.send(JSON.stringify({ type: 'scroll', deltaX: e.deltaX, deltaY: e.deltaY }));
    }, { passive: false });

    previewCanvas.addEventListener('mouseleave', () => {
        document.getElementById('inspectOverlay').style.display = 'none';
        document.getElementById('inspectInfo').style.display = 'none';
    });

    // Keyboard events when canvas is focused
    previewCanvas.setAttribute('tabindex', '0');
    previewCanvas.addEventListener('keydown', (e) => {
        if (!previewWs) return;
        e.preventDefault();
        if (e.key.length === 1) {
            previewWs.send(JSON.stringify({ type: 'keyboard', action: 'type', text: e.key }));
        } else {
            previewWs.send(JSON.stringify({ type: 'keyboard', action: 'press', key: e.key }));
        }
    });
}

function canvasCoords(e) {
    const rect = previewCanvas.getBoundingClientRect();
    const cw = previewCanvas.width;  // actual pixel width of canvas (from CDP)
    const ch = previewCanvas.height; // actual pixel height of canvas
    // With object-fit:contain, canvas is centered with letterboxing
    const displayAspect = rect.width / rect.height;
    const canvasAspect = cw / ch;
    let renderW, renderH, offsetX, offsetY;
    if (canvasAspect > displayAspect) {
        // Canvas is wider than container — letterbox top/bottom
        renderW = rect.width;
        renderH = rect.width / canvasAspect;
        offsetX = 0;
        offsetY = (rect.height - renderH) / 2;
    } else {
        // Canvas is taller — letterbox left/right
        renderH = rect.height;
        renderW = rect.height * canvasAspect;
        offsetX = (rect.width - renderW) / 2;
        offsetY = 0;
    }
    const localX = e.clientX - rect.left - offsetX;
    const localY = e.clientY - rect.top - offsetY;

    const pctX = Math.max(0, Math.min(1, localX / renderW));
    const pctY = Math.max(0, Math.min(1, localY / renderH));

    if (window.previewCSSViewport) {
        return {
            x: pctX * window.previewCSSViewport.width,
            y: pctY * window.previewCSSViewport.height,
            pctX, pctY
        };
    }
    
    return {
        x: Math.max(0, Math.min(cw, pctX * cw)),
        y: Math.max(0, Math.min(ch, pctY * ch)),
        pctX, pctY
    };
}

let screenshotInterval = null;
let screenshotFails = 0;
function startScreenshotStream() {
    // Do NOT start (or restart) the screenshot poll for a run that already
    // finished — its preview server is gone, so every request 502s and the
    // <img> shows a broken-image icon. previewStopped is the single gate.
    if (!previewSession || previewStopped) return;
    stopScreenshotStream();
    screenshotFails = 0;
    const container = document.getElementById('previewContainer');
    container.innerHTML = '<img id="previewImg" alt="Browser Preview" style="width:100%;height:100%;object-fit:contain">';
    const img = document.getElementById('previewImg');
    let loading = false;
    screenshotInterval = setInterval(() => {
        if (loading) return;
        loading = true;
        const buf = new Image();
        buf.onload = () => { img.src = buf.src; loading = false; screenshotFails = 0; };
        buf.onerror = () => {
            loading = false;
            // Upstream preview server dead (502 / connection refused). Stop
            // hammering it after a few misses and show a neutral ended state
            // instead of a broken image looping forever.
            if (++screenshotFails >= 3) {
                stopScreenshotStream();
                showPreviewEnded();
            }
        };
        const isRemote = location.hostname !== 'localhost' && location.hostname !== '127.0.0.1';
        const screenshotUrl = isRemote
            ? `${location.origin}/api/v1/scripts/preview/screenshot/${previewSession.port}?t=${Date.now()}`
            : `http://localhost:${previewSession.port}/screenshot?t=${Date.now()}`;
        buf.src = screenshotUrl;
    }, 1000);
}

function stopScreenshotStream() {
    if (screenshotInterval) { clearInterval(screenshotInterval); screenshotInterval = null; }
}

// Neutral placeholder shown when the preview source is gone (run finished),
// replacing the broken-image icon.
function showPreviewEnded() {
    const container = document.getElementById('previewContainer');
    if (!container) return;
    container.innerHTML = '<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;gap:8px;color:var(--muted);font-size:13px;">'
        + '<span class="material-symbols-outlined" style="font-size:34px;opacity:.5">visibility_off</span>'
        + '<span>Preview đã kết thúc</span></div>';
}

async function navigatePreview() {
    let url = document.getElementById('previewUrl').value.trim();
    if (!url) return;
    // Auto-add protocol
    if (!/^https?:\/\//i.test(url) && url !== 'about:blank') {
        url = 'https://' + url;
        document.getElementById('previewUrl').value = url;
    }
    // Use WebSocket if available (script runner mode)
    if (previewWs && previewWs.readyState === 1) {
        previewWs.send(JSON.stringify({ type: 'navigate', url }));
        return;
    }
    // Fallback: preview server HTTP
    if (previewSession) {
        await fetch(`http://localhost:${previewSession.port}/navigate`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url })
        });
    }
}

function navAction(action) {
    if (previewWs && previewWs.readyState === 1) {
        previewWs.send(JSON.stringify({ type: 'nav', action }));
    }
}

// ── Element Picker ──
async function togglePicker() {
    if (!previewSession && !previewWs) { appendLog('Launch browser first', 'error'); return; }
    pickerActive = !pickerActive;
    const btn = document.getElementById('btnPicker');
    if (pickerActive) {
        btn.classList.add('btn-accent');
        btn.classList.remove('btn-ghost');
        if (previewCanvas) previewCanvas.style.cursor = 'crosshair';
        appendLog('🎯 Element Picker ON — hover to inspect, click to select', 'info');
    } else {
        btn.classList.remove('btn-accent');
        btn.classList.add('btn-ghost');
        if (previewCanvas) previewCanvas.style.cursor = 'default';
        document.getElementById('inspectOverlay').style.display = 'none';
        document.getElementById('inspectInfo').style.display = 'none';
    }
}

let pickerTargetStep = null;
async function pickElement(stepIdx) {
    if (!previewSession) { appendLog('Launch browser first', 'error'); return; }
    pickerTargetStep = stepIdx;
    if (!pickerActive) await togglePicker();
    appendLog(`Pick element for Step ${stepIdx + 1}`, 'info');
}

async function takeScreenshot() {
    if (!previewSession) return;
    window.open(`http://localhost:${previewSession.port}/screenshot`, '_blank');
}

// ── Profiles ──
async function loadProfiles() {
    try {
        const data = await api('/api/v1/browser/profiles');
        cachedProfilesList = data.profiles || [];

        const engineVal = document.getElementById('execEngine')?.value || 'playwright';
        filterProfilesByEngine(engineVal);
    } catch (e) {}
}

function filterProfilesByEngine(engine) {
    const select = document.getElementById('execProfile');
    if (!select) return;

    const currentValue = select.value || localStorage.getItem('scriptStudio_profile') || '';

    // Filter profiles based on selected engine
    const filtered = cachedProfilesList.filter(p => {
        const isShardX = p.browser_version && p.browser_version.includes('ShardX');
        if (engine === 'playwright') {
            return isShardX;
        } else {
            return !isShardX;
        }
    });

    select.innerHTML = '<option value="">Select Profile...</option>' +
        filtered.map(p => `<option value="${p.name}">${p.name}</option>`).join('');

    // Restore selection if it exists in the filtered list
    const exists = filtered.some(p => p.name === currentValue);
    if (exists) {
        select.value = currentValue;
    } else {
        select.value = '';
        cachedProfileData = null;
        localStorage.removeItem('scriptStudio_profile');
    }
}

// Load profile data into cache (called once on init & on profile change)
async function loadProfileData(profileName) {
    if (!profileName) { cachedProfileData = null; return; }
    try {
        const data = await api(`/api/v1/browser/profiles/${encodeURIComponent(profileName)}`);
        // Also fetch cookies count
        let cookieCount = 0;
        try {
            const cookieData = await api(`/api/v1/browser/profiles/${encodeURIComponent(profileName)}/cookies`);
            cookieCount = cookieData.count || 0;
        } catch (e) {}
        cachedProfileData = { ...data, cookie_count: cookieCount, _loaded_at: Date.now() };

        // Automatically sync variables to script
        syncProfileVariablesToScript();
    } catch (e) {
        cachedProfileData = null;
    }
}

function syncProfileVariablesToScript() {
    if (!currentScript || !cachedProfileData) return;

    let updated = false;
    if (!currentScript.variables) currentScript.variables = [];

    const services = ['google', 'facebook', 'tiktok', 'x', 'discord', 'telegram'];
    
    services.forEach(service => {
        const acc = cachedProfileData[service + '_account'];
        if (acc) {
            // We have account data for this service!
            const fields = [
                { suffix: 'email', val: acc.email },
                { suffix: 'password', val: acc.password },
                { suffix: 'recovery', val: acc.recoveryEmail },
                { suffix: '2fa', val: acc.twoFactorCodes }
            ];

            fields.forEach(f => {
                const varName = `${service}_${f.suffix}`;
                const val = f.val || '';
                
                // Find if variable already exists
                const existing = currentScript.variables.find(v => v.name === varName);
                if (existing) {
                    if (existing.default !== val) {
                        existing.default = val;
                        updated = true;
                    }
                } else {
                    currentScript.variables.push({
                        name: varName,
                        type: 'string',
                        default: val
                    });
                    updated = true;
                }
            });
        }
    });

    if (updated) {
        renderVariables();
        // Save back to backend script variables
        api(`${API}/${currentScript.id}`, {
            method: 'PUT',
            body: JSON.stringify({ variables: currentScript.variables })
        });
        showToast(T('script_studio.toast_synced_profile'), 'success');
    }
}

// ── Create Profile ──
function showCreateProfileDialog() {
    document.getElementById('newProfileName').value = '';
    document.getElementById('newProfileProxy').value = '';
    document.getElementById('newProfileWidth').value = '1920';
    document.getElementById('newProfileHeight').value = '1080';
    document.querySelectorAll('input[name="profileTag"]').forEach(cb => {
        cb.checked = cb.value === 'Windows' || cb.value === 'Chrome';
    });
    const errEl = document.getElementById('createProfileError');
    errEl.style.display = 'none';
    errEl.textContent = '';
    showModal('createProfileModal');
    setTimeout(() => document.getElementById('newProfileName').focus(), 200);
}

async function doCreateProfile() {
    const name = document.getElementById('newProfileName').value.trim();
    const proxy = document.getElementById('newProfileProxy').value.trim();
    const width = parseInt(document.getElementById('newProfileWidth').value) || 1920;
    const height = parseInt(document.getElementById('newProfileHeight').value) || 1080;
    const tags = Array.from(document.querySelectorAll('input[name="profileTag"]:checked')).map(cb => cb.value);
    const errEl = document.getElementById('createProfileError');

    if (!name) {
        errEl.textContent = '⚠️ Profile name is required';
        errEl.style.display = 'block';
        document.getElementById('newProfileName').focus();
        return;
    }

    const btn = document.getElementById('btnDoCreateProfile');
    const origText = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span class="material-symbols-outlined" style="animation:spin 1s linear infinite">progress_activity</span> Creating...';

    // Determine browser version based on currently selected engine
    const currentEngine = document.getElementById('execEngine')?.value || 'playwright';
    const browser_version = currentEngine === 'playwright' ? 'ShardX-148.0.7778.97' : 'latest';

    try {
        const resp = await fetch('/api/v1/browser/profiles', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, proxy, tags, window_size: { width, height }, browser_version })
        });
        if (!resp.ok) {
            const errData = await resp.json().catch(() => ({}));
            throw new Error(errData.detail || `HTTP ${resp.status}`);
        }
        const data = await resp.json();
        closeModal('createProfileModal');
        showToast(`✅ Profile "${data.profile?.name || name}" created!`, 'success');
        await loadProfiles();
        const select = document.getElementById('execProfile');
        const safeName = data.profile?.name || name.replace(/[^a-zA-Z0-9_-]/g, '');
        select.value = safeName;
        localStorage.setItem('scriptStudio_profile', safeName);
    } catch (err) {
        errEl.textContent = `❌ ${err.message}`;
        errEl.style.display = 'block';
    } finally {
        btn.disabled = false;
        btn.innerHTML = origText;
    }
}

// ── History ──
async function loadHistory() {
    if (!currentScript) return;
    try {
        const data = await api(`${API}/executions/history`);
        const list = document.getElementById('executionHistory');
        const execs = (data.executions || []).filter(e => e.script_id === currentScript.id);
        if (!execs.length) {
            list.innerHTML = '<div class="empty-state"><span class="material-symbols-outlined">history</span><p>No history</p></div>';
            return;
        }
        list.innerHTML = execs.slice(0, 20).map(e => `
            <div class="history-item ${e.status}">
                <div style="display:flex;justify-content:space-between;font-size:0.82rem">
                    <span>${e.status === 'success' ? '✅' : e.status === 'error' ? '❌' : '⏳'} ${e.status}</span>
                    <span style="color:var(--text-muted)">${e.started_at || ''}</span>
                </div>
                <div style="font-size:0.75rem;color:var(--text-muted);margin-top:4px">${e.profile_name || 'No profile'}</div>
            </div>
        `).join('');
    } catch (e) {}
}

// ── Profile Settings ──
function showProfileSettings() {
    const profile = document.getElementById('execProfile').value;
    if (!profile) {
        showToast(T('script_studio.toast_select_profile'), 'warning');
        return;
    }
    document.getElementById('profileSettingsName').textContent = `📂 ${profile}`;
    document.getElementById('profileSettingsError').style.display = 'none';
    document.getElementById('profileSettingsSuccess').style.display = 'none';

    // Use cached profile data — no API call needed
    const data = cachedProfileData || {};
    document.getElementById('settingsProxy').value = data.proxy || '';
    document.getElementById('settingsWidth').value = data.window_size?.width || 1920;
    document.getElementById('settingsHeight').value = data.window_size?.height || 1080;

    // Fingerprint status
    const hasFP = data.has_fingerprint;
    document.getElementById('fingerprintStatus').textContent = hasFP ? '✅ Loaded' : '❌ Not found';
    document.getElementById('fingerprintStatus').style.color = hasFP ? 'var(--success)' : 'var(--danger)';

    // Cookies status from cache
    const cookieCount = data.cookie_count || 0;
    document.getElementById('cookiesStatus').textContent = cookieCount > 0 ? `🍪 ${cookieCount} cookies` : '❌ No cookies';
    document.getElementById('cookiesStatus').style.color = cookieCount > 0 ? 'var(--success)' : 'var(--text-muted)';

    showModal('profileSettingsModal');
}

async function saveProfileSettings() {
    const profile = document.getElementById('execProfile').value;
    if (!profile) return;

    const proxy = document.getElementById('settingsProxy').value.trim();
    const width = parseInt(document.getElementById('settingsWidth').value) || 1920;
    const height = parseInt(document.getElementById('settingsHeight').value) || 1080;

    const errEl = document.getElementById('profileSettingsError');
    const okEl = document.getElementById('profileSettingsSuccess');
    errEl.style.display = 'none';
    okEl.style.display = 'none';

    try {
        await api(`/api/v1/browser/profiles/${encodeURIComponent(profile)}`, {
            method: 'PUT',
            body: JSON.stringify({ proxy, window_size: { width, height } })
        });
        // Update cache locally
        if (cachedProfileData) {
            cachedProfileData.proxy = proxy;
            cachedProfileData.window_size = { width, height };
        }
        okEl.textContent = '✅ Settings saved!';
        okEl.style.display = 'block';
        setTimeout(() => { okEl.style.display = 'none'; }, 3000);
    } catch (e) {
        errEl.textContent = `❌ ${e.message}`;
        errEl.style.display = 'block';
    }
}

async function refreshFingerprint() {
    const profile = document.getElementById('execProfile').value;
    if (!profile) return;

    const btn = document.getElementById('btnRefreshFP');
    const origHTML = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span class="material-symbols-outlined" style="animation:spin 1s linear infinite;font-size:16px">progress_activity</span> Refreshing...';
    document.getElementById('fingerprintStatus').textContent = '⏳ Fetching new fingerprint...';
    document.getElementById('fingerprintStatus').style.color = 'var(--warning)';

    try {
        await api(`/api/v1/browser/profiles/${encodeURIComponent(profile)}/fingerprint/refresh`, { method: 'POST' });
        if (cachedProfileData) cachedProfileData.has_fingerprint = true;
        document.getElementById('fingerprintStatus').textContent = '✅ Refreshed!';
        document.getElementById('fingerprintStatus').style.color = 'var(--success)';
        showToast('✅ Fingerprint refreshed!', 'success');
    } catch (e) {
        document.getElementById('fingerprintStatus').textContent = '❌ Failed';
        document.getElementById('fingerprintStatus').style.color = 'var(--danger)';
        showToast(`❌ ${e.message}`, 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = origHTML;
    }
}

async function exportCookies() {
    const profile = document.getElementById('execProfile').value;
    if (!profile) return;

    try {
        const data = await api(`/api/v1/browser/profiles/${encodeURIComponent(profile)}/cookies`);
        if (!data.cookies || data.cookies.length === 0) {
            showToast('❌ No cookies to export', 'warning');
            return;
        }
        const blob = new Blob([JSON.stringify(data.cookies, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${profile}_cookies.json`;
        a.click();
        URL.revokeObjectURL(url);
        showToast(`✅ Exported ${data.cookies.length} cookies`, 'success');
    } catch (e) {
        showToast(`❌ Export failed: ${e.message}`, 'error');
    }
}

async function importCookies(input) {
    const profile = document.getElementById('execProfile').value;
    if (!profile || !input.files.length) return;

    const file = input.files[0];
    try {
        const text = await file.text();
        const cookies = JSON.parse(text);
        await api(`/api/v1/browser/profiles/${encodeURIComponent(profile)}/cookies`, {
            method: 'POST',
            body: JSON.stringify({ cookies: Array.isArray(cookies) ? cookies : [cookies] })
        });
        const count = Array.isArray(cookies) ? cookies.length : 1;
        if (cachedProfileData) cachedProfileData.cookie_count = count;
        document.getElementById('cookiesStatus').textContent = `🍪 ${count} cookies`;
        document.getElementById('cookiesStatus').style.color = 'var(--success)';
        showToast(`✅ Imported ${count} cookies`, 'success');
    } catch (e) {
        showToast(`❌ Import failed: ${e.message}`, 'error');
    }
    input.value = ''; // Reset file input
}

async function deleteCookies() {
    const profile = document.getElementById('execProfile').value;
    if (!profile) return;

    if (!confirm(T('script_studio.confirm_delete_cookies', { profile }))) return;

    try {
        await api(`/api/v1/browser/profiles/${encodeURIComponent(profile)}/cookies`, { method: 'DELETE' });
        if (cachedProfileData) cachedProfileData.cookie_count = 0;
        document.getElementById('cookiesStatus').textContent = '❌ No cookies';
        document.getElementById('cookiesStatus').style.color = 'var(--text-muted)';
        showToast(T('script_studio.toast_cookies_deleted'), 'success');
    } catch (e) {
        showToast(`❌ ${e.message}`, 'error');
    }
}

// ── Import ──
async function importScriptPrompt() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.json,.js';
    input.onchange = async () => {
        const file = input.files[0];
        if (!file) return;
        const text = await file.text();
        try {
            if (file.name.endsWith('.js')) {
                // AI Parser for .js files
                appendLog(`Parsing ${file.name} with AI...`, 'info');
                const data = await api(`${API}/import/js`, {
                    method: 'POST',
                    body: JSON.stringify({ content: text, filename: file.name, use_ai: true })
                });
                await loadScripts();
                if (data.script) selectScript(data.script.slug || data.script.id);
                appendLog(`Imported! ${data.parsed_steps || 0} steps, ${data.parsed_variables || 0} variables`, 'success');
            } else {
                // JSON import
                const json = JSON.parse(text);
                const data = await api(`${API}/import/json`, {
                    method: 'POST',
                    body: JSON.stringify({ script: json.script || json })
                });
                await loadScripts();
                if (data.script) selectScript(data.script.slug || data.script.id);
                appendLog('Script imported!', 'success');
            }
        } catch (e) { appendLog('Import failed: ' + e.message, 'error'); }
    };
    input.click();
}

// ── AI Generate ──
async function doAIGenerate() {
    const prompt = document.getElementById('aiPrompt').value.trim();
    const targetUrl = document.getElementById('aiTargetUrl').value.trim();
    if (!prompt) { alert('Please describe the script you want to generate'); return; }

    const statusEl = document.getElementById('aiGenerateStatus');
    const statusText = document.getElementById('aiGenerateStatusText');
    const btn = document.getElementById('btnDoAIGenerate');

    statusEl.style.display = 'block';
    statusText.textContent = T('script_studio.generating_script');
    btn.disabled = true;

    try {
        const provider = document.querySelector('#aiProviderChips .ext-chip.active')?.dataset.provider || 'auto';
        const model = document.getElementById('aiModelSelect')?.value || '';
        const data = await api(`${API}/generate`, {
            method: 'POST',
            body: JSON.stringify({ prompt, target_url: targetUrl, provider, model })
        });

        if (data.script) {
            statusText.textContent = T('script_studio.status_generated', { count: data.steps_count, provider: data.provider });
            await loadScripts();
            await selectScript(data.script.slug || data.script.id);
            appendLog(`AI generated script: ${data.script.name} (${data.steps_count} steps via ${data.provider})`, 'success');

            setTimeout(() => {
                closeModal('aiGenerateModal');
                statusEl.style.display = 'none';
                document.getElementById('aiPrompt').value = '';
                document.getElementById('aiTargetUrl').value = '';
            }, 1500);
        } else {
            statusText.textContent = T('script_studio.status_failed');
        }
    } catch (e) {
        statusText.textContent = T('script_studio.status_error', { error: e.message || 'AI generation failed' });
        appendLog('AI generate failed: ' + (e.message || 'Unknown error'), 'error');
    } finally {
        btn.disabled = false;
    }
}

// ── Log ──
let _lastLogMsg = null;
function appendLog(msg, type = '') {
    const log = document.getElementById('logContent');
    const time = new Date().toLocaleTimeString();

    // Parse JSON log lines from script_runner.js
    let displayMsg = msg;
    let wasStopped = false;
    if (typeof msg === 'string' && msg.trimStart().startsWith('{')) {
        try {
            const parsed = JSON.parse(msg);
            displayMsg = parsed.message || parsed.error || msg;
            wasStopped = parsed.stopped === true;
            // Auto-detect type from status
            if (!type) {
                if (wasStopped) type = 'warn';                       // user stop ≠ crash
                else if (parsed.status === 'error' || parsed.success === false) type = 'error';
                else if (parsed.status === 'done' && parsed.success) type = 'success';
                else if (parsed.status === 'step') type = 'info';
            }
        } catch (e) {} // not JSON, use as-is
    }

    // A user-initiated stop is not an error — never paint it red.
    if (type === 'error' && typeof displayMsg === 'string'
        && /stopped by user|đã dừng|script stopped/i.test(displayMsg)) {
        type = 'warn';
    }

    // Collapse consecutive identical lines: the preview teardown and the
    // runner/frontend double-logging repeat the same text several times.
    if (displayMsg === _lastLogMsg) return;
    _lastLogMsg = displayMsg;

    // 'warn' is a new type; colour it inline so it works even where the served
    // stylesheet predates the .log-line.warn rule.
    const extraStyle = type === 'warn' ? ' style="color:#eab308"' : '';
    log.innerHTML += `<div class="log-line ${type}"${extraStyle}>[${time}] ${esc(displayMsg)}</div>`;
    log.scrollTop = log.scrollHeight;
}

function clearLog() { document.getElementById('logContent').innerHTML = ''; _lastLogMsg = null; }

// ── Resize Handles ──
function setupResizeHandles() {
    setupResize('sidebarResize', 'sidebar', 'left');
    setupResize('editorResize', 'preview-panel', 'right');
}

function setupResize(handleId, panelId, side) {
    const handle = document.getElementById(handleId);
    const panel = document.getElementById(panelId);
    if (!handle || !panel) return;
    let startX, startW;
    handle.onmousedown = e => {
        startX = e.clientX;
        startW = panel.offsetWidth;
        document.body.classList.add('panel-resizing');
        const onMove = e => {
            const diff = side === 'left' ? e.clientX - startX : startX - e.clientX;
            panel.style.width = Math.max(200, startW + diff) + 'px';
            panel.style.flex = 'none';
        };
        const onUp = () => {
            document.removeEventListener('mousemove', onMove);
            document.removeEventListener('mouseup', onUp);
            document.body.classList.remove('panel-resizing');
        };
        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup', onUp);
    };
}

// ── Utils ──
function showModal(id) { document.getElementById(id).style.display = 'flex'; }
function closeModal(id) { document.getElementById(id).style.display = 'none'; }
function closeStepTypeModal() { closeModal('stepTypeModal'); }
function closeNewScriptModal() { closeModal('newScriptModal'); }
function esc(s) { const d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML; }
function capitalize(s) { return s.charAt(0).toUpperCase() + s.slice(1); }
function getCategoryIcon(c) { return { video: '🎬', image: '🖼️', audio: '🎵', scraping: '🕷️' }[c] || '📄'; }
function filterScripts(q) {
    const items = document.querySelectorAll('.script-item');
    items.forEach(el => { el.style.display = el.textContent.toLowerCase().includes(q.toLowerCase()) ? '' : 'none'; });
}

// ── Chat Bot ──
let chatHistory = [];

function toggleChat() {
    const panel = document.getElementById('chatPanel');
    const btn = document.getElementById('chatToggle');
    if (panel.style.display === 'none') {
        panel.style.display = 'flex';
        btn.style.display = 'none';
        document.getElementById('chatInput').focus();
    } else {
        panel.style.display = 'none';
        btn.style.display = 'flex';
    }
}

function clearChat() {
    chatHistory = [];
    const msgs = document.getElementById('chatMessages');
    msgs.innerHTML = `<div class="chat-msg bot"><div class="chat-bubble">${T('script_studio.chat_cleared')}</div></div>`;
}

function addChatMsg(role, html) {
    const msgs = document.getElementById('chatMessages');
    const div = document.createElement('div');
    div.className = `chat-msg ${role}`;
    div.innerHTML = `<div class="chat-bubble">${html}</div>`;
    msgs.appendChild(div);
    msgs.scrollTop = msgs.scrollHeight;
    return div;
}

async function sendChat() {
    const input = document.getElementById('chatInput');
    const text = input.value.trim();
    if (!text) return;
    input.value = '';

    addChatMsg('user', esc(text));
    chatHistory.push({ role: 'user', content: text });

    // Show typing indicator
    const typingDiv = addChatMsg('bot', '<div class="typing-dots"><span></span><span></span><span></span></div>');

    try {
        const provider = document.querySelector('#aiProviderChips .ext-chip.active')?.dataset.provider || localStorage.getItem('scriptStudio_aiProvider') || 'auto';
        const model = document.getElementById('aiModelSelect')?.value || localStorage.getItem('scriptStudio_aiModel_' + provider) || localStorage.getItem('scriptStudio_aiModel') || '';
        const data = await api(`${API}/chat`, {
            method: 'POST',
            body: JSON.stringify({
                message: text,
                history: chatHistory.slice(-10),
                script: currentScript,
                provider: provider,
                model: model,
            })
        });

        typingDiv.remove();

        if (data.reply) {
            addChatMsg('bot', data.reply);
            chatHistory.push({ role: 'assistant', content: data.reply });
        }

        // If AI modified steps, apply them
        if (data.updated_steps && currentScript) {
            currentScript.steps = data.updated_steps;
            renderSteps();
            saveSteps();
            addChatMsg('bot', T('script_studio.chat_script_updated'));
        }
    } catch (e) {
        typingDiv.remove();
        addChatMsg('bot', T('script_studio.chat_error', { error: e.message }));
    }
}

// ── Toast Notification ──
function showToast(message, type = 'info') {
    // Remove any existing toast
    const existing = document.getElementById('scriptStudioToast');
    if (existing) existing.remove();

    const colors = {
        warning: { bg: 'linear-gradient(135deg, #f59e0b, #d97706)', icon: '⚠️' },
        error:   { bg: 'linear-gradient(135deg, #ef4444, #dc2626)', icon: '❌' },
        success: { bg: 'linear-gradient(135deg, #10b981, #059669)', icon: '✅' },
        info:    { bg: 'linear-gradient(135deg, #3b82f6, #2563eb)', icon: 'ℹ️' },
    };
    const c = colors[type] || colors.info;

    const toast = document.createElement('div');
    toast.id = 'scriptStudioToast';
    toast.innerHTML = `${c.icon} ${esc(message)}`;
    Object.assign(toast.style, {
        position: 'fixed', top: '16px', left: '50%', transform: 'translateX(-50%) translateY(-20px)',
        padding: '12px 24px', borderRadius: '12px', background: c.bg,
        color: '#fff', fontWeight: '600', fontSize: '14px', fontFamily: 'Inter, sans-serif',
        boxShadow: '0 8px 32px rgba(0,0,0,0.3)', zIndex: '99999',
        opacity: '0', transition: 'all 0.3s ease', cursor: 'pointer',
        backdropFilter: 'blur(8px)', border: '1px solid rgba(255,255,255,0.15)',
    });
    toast.onclick = () => { toast.style.opacity = '0'; setTimeout(() => toast.remove(), 300); };
    document.body.appendChild(toast);

    // Animate in
    requestAnimationFrame(() => {
        toast.style.opacity = '1';
        toast.style.transform = 'translateX(-50%) translateY(0)';
    });

    // Auto dismiss
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(-50%) translateY(-20px)';
        setTimeout(() => toast.remove(), 300);
    }, 3500);
}

// ══════════════════════════════════════════════════════════════
// ── Context Menu System (Right-Click on Steps)
// ══════════════════════════════════════════════════════════════

let _ctxTargetIndex = -1; // Which step index the context menu is targeting

function showStepContextMenu(event, stepIndex) {
    _ctxTargetIndex = stepIndex;
    hideContextMenu();

    const menu = document.getElementById('contextMenu');
    const vars = currentScript?.variables || [];
    const step = stepIndex >= 0 ? currentScript?.steps?.[stepIndex] : null;

    let html = '';

    if (step) {
        // ── Actions on a specific step ──
        html += ctxItem('arrow_upward', T('script_studio.insert_step_above'), `insertStepAt(${stepIndex})`);
        html += ctxItem('arrow_downward', T('script_studio.insert_step_below'), `insertStepAt(${stepIndex + 1})`);
        html += ctxItem('content_copy', T('script_studio.duplicate_step'), `duplicateStep(${stepIndex})`);
        html += '<div class="context-menu-separator"></div>';
        html += ctxItem('auto_awesome', T('script_studio.ai_generate_here'), `showQuickAIDialog(${stepIndex})`, 'ai-action');
        html += ctxItem('functions', T('script_studio.insert_call_function'), `showInsertFunctionDialog(${stepIndex})`, 'fn-action');
        html += '<div class="context-menu-separator"></div>';
        html += ctxItem('data_object', T('script_studio.create_var'), `showCreateVarDialog()`);

        // Variable insertion sub-menu
        if (vars.length > 0) {
            html += `<div class="context-menu-item" style="cursor:default">
                <span class="material-symbols-outlined">code</span>
                <span class="ctx-label">${T('script_studio.insert_var')}</span>
                <span class="material-symbols-outlined" style="font-size:14px;color:var(--text-muted)">chevron_right</span>
                <div class="context-submenu">`;
            vars.forEach(v => {
                if (v.name) {
                    html += `<div class="context-menu-item" onclick="event.stopPropagation();copyVarToClipboard('${esc(v.name)}')">
                        <span class="var-tag">{{${esc(v.name)}}}</span>
                    </div>`;
                }
            });
            html += `</div></div>`;
        }

        html += '<div class="context-menu-separator"></div>';
        const isEnabled = step.enabled !== false;
        html += ctxItem(
            isEnabled ? 'toggle_off' : 'toggle_on',
            isEnabled ? T('script_studio.disable_step') : T('script_studio.enable_step'),
            `toggleEnabled(${stepIndex});hideContextMenu()`
        );
        html += ctxItem('delete', T('script_studio.delete_step'), `removeStep(${stepIndex});hideContextMenu()`, 'danger');
    } else {
        // ── Right-click on empty area ──
        const insertIdx = currentScript?.steps?.length || 0;
        html += ctxItem('add_circle', T('script_studio.add_new_step'), `insertStepAt(${insertIdx})`);
        html += ctxItem('auto_awesome', T('script_studio.ai_generate_steps'), `showQuickAIDialog(${insertIdx})`, 'ai-action');
        html += ctxItem('functions', T('script_studio.insert_call_function'), `showInsertFunctionDialog(${insertIdx})`, 'fn-action');
        html += '<div class="context-menu-separator"></div>';
        html += ctxItem('data_object', T('script_studio.create_var'), `showCreateVarDialog()`);
    }

    menu.innerHTML = html;
    menu.style.display = 'block';

    // Position — make sure menu stays within viewport
    const menuRect = menu.getBoundingClientRect();
    let x = event.clientX;
    let y = event.clientY;
    if (x + menuRect.width > window.innerWidth) x = window.innerWidth - menuRect.width - 8;
    if (y + menuRect.height > window.innerHeight) y = window.innerHeight - menuRect.height - 8;
    if (x < 0) x = 8;
    if (y < 0) y = 8;
    menu.style.left = x + 'px';
    menu.style.top = y + 'px';

    // Close on click outside
    setTimeout(() => {
        document.addEventListener('click', _closeCtxOnClick);
        document.addEventListener('contextmenu', _closeCtxOnRightClick);
    }, 10);
}

function ctxItem(icon, label, onclick, extraClass = '') {
    return `<div class="context-menu-item ${extraClass}" onclick="event.stopPropagation();hideContextMenu();${onclick}">
        <span class="material-symbols-outlined">${icon}</span>
        <span class="ctx-label">${label}</span>
    </div>`;
}

function hideContextMenu() {
    const menu = document.getElementById('contextMenu');
    if (menu.style.display === 'none') return;
    menu.classList.add('closing');
    setTimeout(() => {
        menu.style.display = 'none';
        menu.classList.remove('closing');
    }, 120);
    document.removeEventListener('click', _closeCtxOnClick);
    document.removeEventListener('contextmenu', _closeCtxOnRightClick);
}

function _closeCtxOnClick() { hideContextMenu(); }
function _closeCtxOnRightClick(e) {
    // If right-clicking another step, let it show a new menu
    const stepCard = e.target.closest('.step-card');
    if (!stepCard) hideContextMenu();
}

// ── Duplicate Step ──
function duplicateStep(idx) {
    if (!currentScript?.steps?.[idx]) return;
    const clone = JSON.parse(JSON.stringify(currentScript.steps[idx]));
    clone.id = `step_${Date.now()}`;
    clone.label = (clone.label || clone.type) + ' (copy)';
    currentScript.steps.splice(idx + 1, 0, clone);
    renderSteps();
    saveSteps();
    showToast(T('script_studio.toast_duplicated_step', { idx: idx + 1 }), 'success');
    // Expand the cloned step
    const card = document.getElementById(`step-${idx + 1}`);
    if (card) card.classList.add('expanded');
}

// ── Copy Variable to Clipboard ──
function copyVarToClipboard(varName) {
    const text = `{{${varName}}}`;
    navigator.clipboard.writeText(text).then(() => {
        showToast(T('script_studio.toast_copied_clipboard', { text: text }), 'success');
    }).catch(() => {
        // Fallback
        const ta = document.createElement('textarea');
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        ta.remove();
        showToast(T('script_studio.toast_copied_clipboard', { text: text }), 'success');
    });
    hideContextMenu();
}

// ══════════════════════════════════════════════════════════════
// ── Mini Modal Helpers
// ══════════════════════════════════════════════════════════════

function closeMiniModal(id) {
    const modal = document.getElementById(id);
    const miniModal = modal.querySelector('.mini-modal');
    if (miniModal) miniModal.classList.add('closing');
    setTimeout(() => {
        modal.style.display = 'none';
        if (miniModal) miniModal.classList.remove('closing');
    }, 150);
}

// ── Quick AI Generate Steps ──
let _quickAIInsertIndex = 0;

function showQuickAIDialog(insertAfterIndex) {
    _quickAIInsertIndex = insertAfterIndex;
    document.getElementById('quickAIPrompt').value = '';
    document.getElementById('quickAIStatus').style.display = 'none';
    document.getElementById('btnDoQuickAI').disabled = false;
    document.getElementById('quickAIModal').style.display = 'block';
    setTimeout(() => document.getElementById('quickAIPrompt').focus(), 150);
}

async function doQuickAIGenerate() {
    const prompt = document.getElementById('quickAIPrompt').value.trim();
    if (!prompt) {
        showToast(T('script_studio.toast_describe_steps'), 'warning');
        return;
    }
    if (!currentScript) {
        showToast(T('script_studio.toast_select_script_first'), 'warning');
        return;
    }

    const statusEl = document.getElementById('quickAIStatus');
    const statusText = document.getElementById('quickAIStatusText');
    const btn = document.getElementById('btnDoQuickAI');

    statusEl.style.display = 'block';
    statusText.textContent = T('script_studio.generating_steps');
    btn.disabled = true;

    try {
        // Gather context: surrounding steps
        const steps = currentScript.steps || [];
        const contextBefore = steps.slice(Math.max(0, _quickAIInsertIndex - 3), _quickAIInsertIndex);
        const contextAfter = steps.slice(_quickAIInsertIndex, _quickAIInsertIndex + 3);

        const provider = document.querySelector('#aiProviderChips .ext-chip.active')?.dataset.provider || localStorage.getItem('scriptStudio_aiProvider') || 'auto';
        const model = document.getElementById('aiModelSelect')?.value || localStorage.getItem('scriptStudio_aiModel_' + provider) || localStorage.getItem('scriptStudio_aiModel') || '';
        const data = await api(`${API}/${currentScript.id}/ai-generate-steps`, {
            method: 'POST',
            body: JSON.stringify({
                prompt,
                insert_after: _quickAIInsertIndex,
                context_before: contextBefore,
                context_after: contextAfter,
                variables: currentScript.variables || [],
                provider: provider,
                model: model,
            })
        });

        if (data.steps && data.steps.length > 0) {
            // Insert new steps at the target position
            if (!currentScript.steps) currentScript.steps = [];
            currentScript.steps.splice(_quickAIInsertIndex, 0, ...data.steps);
            renderSteps();
            saveSteps();

            // Auto-add any new variables the AI suggested
            if (data.variables && data.variables.length > 0) {
                if (!currentScript.variables) currentScript.variables = [];
                const existingNames = new Set(currentScript.variables.map(v => v.name));
                data.variables.forEach(v => {
                    if (v.name && !existingNames.has(v.name)) {
                        currentScript.variables.push(v);
                        existingNames.add(v.name);
                    }
                });
                renderVariables();
                await api(`${API}/${currentScript.id}`, {
                    method: 'PUT',
                    body: JSON.stringify({ variables: currentScript.variables })
                });
            }

            statusText.textContent = T('script_studio.status_generated', { count: data.steps.length, provider: data.provider || 'AI' });
            showToast(T('script_studio.toast_ai_generated_steps', { count: data.steps.length }), 'success');

            // Expand inserted steps
            for (let i = _quickAIInsertIndex; i < _quickAIInsertIndex + data.steps.length; i++) {
                const card = document.getElementById(`step-${i}`);
                if (card) card.classList.add('expanded');
            }

            setTimeout(() => closeMiniModal('quickAIModal'), 1200);
        } else {
            statusText.textContent = T('script_studio.toast_ai_failed_steps');
        }
    } catch (e) {
        statusText.textContent = T('script_studio.status_error', { error: e.message || 'AI generation failed' });
    } finally {
        btn.disabled = false;
    }
}

// ── Create Variable Dialog ──
function showCreateVarDialog() {
    if (!currentScript) {
        showToast('⚠️ Select a script first', 'warning');
        return;
    }
    document.getElementById('quickVarName').value = '';
    document.getElementById('quickVarType').value = 'string';
    document.getElementById('quickVarDefault').value = '';
    document.getElementById('varPreview').style.display = 'none';
    document.getElementById('createVarModal').style.display = 'block';
    setTimeout(() => document.getElementById('quickVarName').focus(), 150);
}

function updateVarPreview() {
    const name = document.getElementById('quickVarName').value.trim();
    const preview = document.getElementById('varPreview');
    const previewName = document.getElementById('varPreviewName');
    if (name) {
        previewName.textContent = name;
        preview.style.display = 'inline-flex';
    } else {
        preview.style.display = 'none';
    }
}

function doCreateVariable() {
    if (!currentScript) return;
    const name = document.getElementById('quickVarName').value.trim();
    if (!name) {
        showToast(T('script_studio.toast_empty_var_name'), 'warning');
        return;
    }
    // Check duplicate
    if (!currentScript.variables) currentScript.variables = [];
    if (currentScript.variables.some(v => v.name === name)) {
        showToast(T('script_studio.toast_var_exists', { name }), 'warning');
        return;
    }
    currentScript.variables.push({
        name,
        type: document.getElementById('quickVarType').value,
        default: document.getElementById('quickVarDefault').value,
    });
    renderVariables();
    api(`${API}/${currentScript.id}`, {
        method: 'PUT',
        body: JSON.stringify({ variables: currentScript.variables })
    });
    closeMiniModal('createVarModal');
    showToast(T('script_studio.toast_var_created', { name }), 'success');

    // Copy to clipboard for convenience
    navigator.clipboard.writeText(`{{${name}}}`).catch(() => {});
}

// ── Insert Function Dialog ──
let _fnInsertIndex = 0;

async function showInsertFunctionDialog(insertIndex) {
    _fnInsertIndex = insertIndex;
    if (!currentScript) {
        showToast(T('script_studio.toast_select_script_first'), 'warning');
        return;
    }

    const container = document.getElementById('fnListContainer');
    container.innerHTML = `<div class="empty-state" style="padding:20px">
        <span class="material-symbols-outlined" style="animation:spin 1s linear infinite;font-size:1.5rem;color:var(--accent)">progress_activity</span>
        <p style="font-size:0.8rem">Loading functions...</p>
    </div>`;
    document.getElementById('insertFunctionModal').style.display = 'block';

    try {
        const data = await api(`${API}/functions`);
        const functions = data.functions || [];

        if (functions.length === 0) {
            container.innerHTML = `<div class="empty-state" style="padding:24px">
                <span class="material-symbols-outlined" style="font-size:2rem;opacity:0.3">functions</span>
                <p style="font-size:0.82rem">No functions available</p>
                <p style="font-size:0.72rem;color:var(--text-muted)">Mark a script as "Function" in Settings to use this feature</p>
            </div>`;
            return;
        }

        container.innerHTML = functions.map(fn => `
            <div class="fn-list-item" onclick="doInsertFunction('${esc(fn.slug)}','${esc(fn.name)}')">
                <span class="material-symbols-outlined fn-icon">functions</span>
                <div class="fn-info">
                    <div class="fn-name">${esc(fn.name)}</div>
                    <div class="fn-desc">${esc(fn.description || 'No description')}</div>
                </div>
                <span class="fn-slug">${esc(fn.slug)}</span>
            </div>
        `).join('');
    } catch (e) {
        container.innerHTML = `<div class="empty-state" style="padding:20px">
            <p style="font-size:0.82rem;color:var(--danger)">❌ Error: ${e.message}</p>
        </div>`;
    }
}

function doInsertFunction(slug, name) {
    if (!currentScript) return;
    if (!currentScript.steps) currentScript.steps = [];

    const newStep = {
        id: `step_${Date.now()}`,
        type: 'call_function',
        label: `Call: ${name}`,
        enabled: true,
        selector: '',
        params: {
            function_slug: slug,
            inputs: {},
            outputs: {},
        },
        on_error: 'abort',
        retry_count: 0,
    };

    if (_fnInsertIndex >= 0 && _fnInsertIndex <= currentScript.steps.length) {
        currentScript.steps.splice(_fnInsertIndex, 0, newStep);
    } else {
        currentScript.steps.push(newStep);
    }

    renderSteps();
    saveSteps();
    closeMiniModal('insertFunctionModal');
    showToast(T('script_studio.toast_fn_inserted', { name }), 'success');

    // Expand the inserted step
    const idx = _fnInsertIndex >= 0 ? _fnInsertIndex : currentScript.steps.length - 1;
    const card = document.getElementById(`step-${idx}`);
    if (card) card.classList.add('expanded');
}

// ── Load AI Providers Status ──
async function loadAIProviders() {
    const container = document.getElementById('aiProviderChips');
    if (!container) return;

    try {
        const data = await api(`${API}/ai-providers`);
        const providers = data.providers || {};
        const defaultProvider = data.default_provider || 'gemini';
        const defaultModel = data.default_model || '';

        // Store models in cache
        cachedAIModels = data.models || {};

        // Build chips HTML
        let html = '';
        
        // 1. Auto Chip
        const displayDefault = providers[defaultProvider] ? providers[defaultProvider].display_name : defaultProvider;
        const autoLabel = `🤖 Auto (Default: ${displayDefault})`;
        html += `<button type="button" class="ext-chip" data-provider="auto" title="Default model: ${defaultModel}">${autoLabel}</button>`;

        // 2. Individual Provider Chips
        const keys = ["deepseek", "gemini", "grok", "chatgpt", "9router", "ollama"];
        keys.forEach(key => {
            const info = providers[key];
            if (!info) return;
            const statusIcon = info.active ? '🟢' : '🔴';
            const disabledClass = info.active ? '' : 'disabled';
            const statusText = info.active ? 'Active' : 'Not configured';
            html += `<button type="button" class="ext-chip ${disabledClass}" data-provider="${key}" title="${info.display_name} - ${statusText}">${statusIcon} ${info.display_name}</button>`;
        });

        container.innerHTML = html;

        // Bind click events to chips
        container.querySelectorAll('.ext-chip').forEach(btn => {
            btn.onclick = () => {
                if (btn.classList.contains('disabled')) return;
                container.querySelectorAll('.ext-chip').forEach(c => c.classList.remove('active'));
                btn.classList.add('active');
                localStorage.setItem('scriptStudio_aiProvider', btn.dataset.provider);
                updateAIModelDropdown();
            };
        });

        // Restore saved option
        const savedProvider = localStorage.getItem('scriptStudio_aiProvider') || 'auto';
        let activeBtn = container.querySelector(`.ext-chip[data-provider="${savedProvider}"]:not(.disabled)`);
        if (!activeBtn) {
            activeBtn = container.querySelector('.ext-chip[data-provider="auto"]');
            localStorage.setItem('scriptStudio_aiProvider', 'auto');
        }
        
        if (activeBtn) {
            activeBtn.classList.add('active');
        }

        // Update models dropdown based on selected provider
        updateAIModelDropdown();
    } catch (e) {
        console.error('Failed to load AI providers:', e);
        container.innerHTML = '<span style="color:var(--danger)">❌ Error loading AI config</span>';
    }
}

// ── Update AI Model Dropdown based on Provider ──
function updateAIModelDropdown() {
    const modelGroup = document.getElementById('aiModelGroup');
    const modelSel = document.getElementById('aiModelSelect');
    if (!modelGroup || !modelSel) return;

    // Get active provider from chips
    const provider = document.querySelector('#aiProviderChips .ext-chip.active')?.dataset.provider || 'auto';
    
    if (provider === 'auto') {
        modelGroup.style.display = 'none';
        modelSel.innerHTML = '';
        return;
    }

    const models = cachedAIModels[provider] || [];
    if (models.length === 0) {
        modelGroup.style.display = 'none';
        modelSel.innerHTML = '';
        return;
    }

    modelGroup.style.display = 'block';
    modelSel.innerHTML = '';

    models.forEach(model => {
        const option = document.createElement('option');
        option.value = model;
        option.textContent = model;
        modelSel.appendChild(option);
    });

    // Restore saved model for this specific provider, or generic saved model, or default to first
    const savedModel = localStorage.getItem('scriptStudio_aiModel_' + provider) || localStorage.getItem('scriptStudio_aiModel') || '';
    if (savedModel && models.includes(savedModel)) {
        modelSel.value = savedModel;
    } else {
        if (modelSel.options.length > 0) {
            modelSel.selectedIndex = 0;
            localStorage.setItem('scriptStudio_aiModel_' + provider, modelSel.value);
            localStorage.setItem('scriptStudio_aiModel', modelSel.value);
        }
    }
}

// ── Prompt Suggestion Templates ──
function applyPromptTemplate(type) {
    const promptInput = document.getElementById('aiPrompt');
    if (!promptInput) return;
    
    let text = '';
    let targetUrl = '';
    
    if (type === 'gmail') {
        text = 'Go to accounts.google.com, fill email from variable {{google_email}} and password from variable {{google_password}}. If a 2FA verification page is encountered, use secret from variable {{google_2fa}} to get the OTP code, fill it into the input field, then click the Next button to complete the login.';
        targetUrl = 'https://accounts.google.com';
    } else if (type === 'youtube_scrape') {
        text = 'Go to youtube.com, search for keyword {{search_query}}. Wait for the results to load, scroll down twice to load more videos. Extract the title (selector: #video-title) and save it to a variable, then take a screenshot of the results page.';
        targetUrl = 'https://www.youtube.com';
    } else if (type === 'auto_comment') {
        text = 'Go to any YouTube video page, scroll down to load the comments section. Wait for the comment input to display, click on it, use the AI Text step to automatically write a random comment praising the video, paste it into the input, and click send comment.';
    } else if (type === 'download_file') {
        text = 'Go to unsplash.com, search for "desktop wallpaper". Click on the first image in search results, wait for the image detail page to display, then click the Download button to download the image to the default directory.';
        targetUrl = 'https://unsplash.com';
    }
    
    promptInput.value = text;
    if (targetUrl) {
        const targetUrlInput = document.getElementById('aiTargetUrl');
        if (targetUrlInput) targetUrlInput.value = targetUrl;
    }
}

function applyQuickPromptTemplate(type) {
    const promptInput = document.getElementById('quickAIPrompt');
    if (!promptInput) return;
    
    let text = '';
    if (type === 'click_button') {
        text = 'Hover over the Subscribe button (selector: #subscribe-button button), wait 500ms, then click it.';
    } else if (type === 'fill_form') {
        text = 'Click on the comment input field (selector: #contenteditable-root), fill it with content from variable {{comment_text}} and press Enter.';
    } else if (type === 'scroll_page') {
        text = 'Scroll the page down by 500px, then wait 2000ms for new data to load.';
    } else if (type === 'extract_data') {
        text = 'Extract the href attribute of the link tag (selector: a#video-title) and save the result to the video_url variable.';
    }
    
    promptInput.value = text;
}
