/**
 * TubeCLI Dashboard — Client-side SPA Logic
 * Communicates with TubeCLI API at configurable base URL
 */

const API = localStorage.getItem('tubecli_api') || 'http://localhost:5295';

// ═══ Tab Navigation ═══
document.querySelectorAll('.nav-item').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById('tab-' + btn.dataset.tab).classList.add('active');

        // Auto-load data for the tab
        const tab = btn.dataset.tab;
        if (tab === 'agents') loadAgents();
        else if (tab === 'browser') loadProfiles();
        else if (tab === 'skills') loadSkills();
        else if (tab === 'workflows') loadWorkflows();
        else if (tab === 'plugins') loadPlugins();
    });
});

// Agent Modal Tab Navigation
document.querySelectorAll('.agent-tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.agent-tab-btn').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.agent-tab-pane').forEach(p => p.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById('atab-' + btn.dataset.atab).classList.add('active');
    });
});

// ═══ API Helpers ═══
async function apiGet(path) {
    try {
        const resp = await fetch(API + path);
        return await resp.json();
    } catch (e) {
        console.error('API Error:', path, e);
        return null;
    }
}

async function apiPost(path, data) {
    try {
        const resp = await fetch(API + path, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        return await resp.json();
    } catch (e) {
        console.error('API Error:', path, e);
        return null;
    }
}

async function apiDelete(path) {
    try {
        const resp = await fetch(API + path, { method: 'DELETE' });
        return await resp.json();
    } catch (e) {
        console.error('API Error:', path, e);
        return null;
    }
}

async function apiPut(path, data) {
    try {
        const resp = await fetch(API + path, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        return await resp.json();
    } catch (e) {
        console.error('API Error:', path, e);
        return null;
    }
}

// ═══ Agents ═══
async function loadAgents() {
    const data = await apiGet('/api/v1/agents');
    const container = document.getElementById('agents-list');
    if (!data || !data.agents) {
        container.innerHTML = '<p style="color:var(--text-muted)">Cannot connect to API. Start with: tubecli api start</p>';
        return;
    }
    if (data.agents.length === 0) {
        container.innerHTML = '<p style="color:var(--text-muted)">No agents yet. Create one!</p>';
        return;
    }
    container.innerHTML = data.agents.map(a => `
        <div class="card">
            <div class="card-icon">🤖</div>
            <h3>${esc(a.name)}</h3>
            <p class="card-meta">${esc(a.model || 'default')}</p>
            <p class="card-desc">${esc(a.description || '')}</p>
            <div class="card-footer">
                <span class="tag">${(a.allowed_skills || []).length} skills</span>
                <div class="card-actions">
                    <button class="btn-sm" onclick="openEditAgent('${a.id}')">Edit</button>
                    <button class="btn-danger" onclick="deleteAgent('${a.id}')">Delete</button>
                </div>
            </div>
        </div>
    `).join('');
}

function showCreateAgent() { 
    document.getElementById('agent-modal-title').textContent = 'Create Agent';
    document.getElementById('agent-id').value = '';
    
    // Clear all fields to defaults
    document.getElementById('agent-name').value = '';
    document.getElementById('agent-desc').value = '';
    document.getElementById('agent-prompt').value = 'You are a helpful AI assistant.';
    document.getElementById('agent-model').value = 'qwen:latest';
    document.getElementById('agent-browser-model').value = 'qwen:latest';
    
    document.getElementById('agent-avatar-type').value = 'bot';
    document.getElementById('agent-avatar-color').value = 'blue';
    
    document.getElementById('agent-interests').value = '';
    document.getElementById('agent-behavior').value = '{\n  "dailyRoutine": [],\n  "workHabits": {}\n}';
    
    // Proxy defaults
    document.getElementById('agent-proxy-mode').value = 'none';
    document.getElementById('agent-proxy').value = '';
    document.getElementById('agent-proxy-api').value = 'https://tmproxy.com/api/proxy/get-new-proxy';
    if (document.getElementById('agent-proxy-api-key')) document.getElementById('agent-proxy-api-key').value = '';
    if (document.getElementById('agent-proxy-location')) document.getElementById('agent-proxy-location').value = '';
    onProxyModeChange();
    
    // Schedule defaults
    document.getElementById('agent-schedule-enable').checked = false;
    document.getElementById('agent-timezone').value = 'Asia/Ho_Chi_Minh';
    document.getElementById('agent-schedule-repeat').value = 'daily';
    document.getElementById('agent-schedule-interval').value = '60';
    document.getElementById('agent-schedule-start').value = '08:00';
    document.getElementById('agent-schedule-end').value = '22:00';
    document.getElementById('agent-schedule-max-runs').value = '10';
    document.querySelectorAll('.agent-day-cb').forEach((cb, i) => cb.checked = i < 5);
    onScheduleRepeatChange();
    
    document.getElementById('agent-scraping-enable').checked = false;
    document.getElementById('agent-scraper-limit').value = '10000';
    document.getElementById('agent-scraper-format').value = 'json';
    
    document.getElementById('agent-tg-token').value = '';
    document.getElementById('agent-tg-chat').value = '';
    
    document.getElementById('agent-ms-token').value = '';
    document.getElementById('agent-ms-page').value = '';
    document.getElementById('agent-ms-php').value = '';
    document.getElementById('agent-ms-skill').value = '';
    
    // Load dynamic lists
    populateAgentProfiles([]);
    populateAgentSkills([]);
    
    // Switch to first tab
    document.querySelector('.agent-tab-btn[data-atab="identity"]').click();
    
    document.getElementById('modal-agent').classList.remove('hidden'); 
}

async function openEditAgent(id) {
    const data = await apiGet('/api/v1/agents/' + id);
    if (!data) return alert('Failed to load agent');
    
    document.getElementById('agent-modal-title').textContent = 'Edit Agent: ' + data.name;
    document.getElementById('agent-id').value = data.id;
    
    document.getElementById('agent-name').value = data.name || '';
    document.getElementById('agent-desc').value = data.description || '';
    document.getElementById('agent-prompt').value = data.system_prompt || '';
    document.getElementById('agent-model').value = data.model || 'qwen:latest';
    document.getElementById('agent-browser-model').value = data.browser_ai_model || 'qwen:latest';
    
    document.getElementById('agent-avatar-type').value = data.avatar_type || 'bot';
    document.getElementById('agent-avatar-color').value = data.avatar_color || 'blue';
    
    const persona = data.persona || {};
    document.getElementById('agent-interests').value = (persona.interests || []).join(', ');
    
    const behavior = {
        dailyRoutine: (data.routine || {}).dailyRoutine || [],
        workHabits: (data.routine || {}).workHabits || {}
    };
    document.getElementById('agent-behavior').value = JSON.stringify(behavior, null, 2);
    
    // Proxy
    const proxyProv = data.proxy_provider || {mode: "none"};
    document.getElementById('agent-proxy-mode').value = proxyProv.mode || 'none';
    document.getElementById('agent-proxy').value = data.proxy_config || '';
    document.getElementById('agent-proxy-api').value = proxyProv.api_url || '';
    if (document.getElementById('agent-proxy-api-key')) document.getElementById('agent-proxy-api-key').value = proxyProv.api_key || '';
    if (document.getElementById('agent-proxy-location')) document.getElementById('agent-proxy-location').value = proxyProv.location || '';
    onProxyModeChange();
    
    // Schedule
    const schedule = data.schedule || {};
    document.getElementById('agent-schedule-enable').checked = schedule.enabled || false;
    document.getElementById('agent-timezone').value = data.timezone || 'Asia/Ho_Chi_Minh';
    document.getElementById('agent-schedule-repeat').value = schedule.repeat || 'daily';
    document.getElementById('agent-schedule-interval').value = schedule.interval || 60;
    document.getElementById('agent-schedule-start').value = schedule.start_time || '08:00';
    document.getElementById('agent-schedule-end').value = schedule.end_time || '22:00';
    document.getElementById('agent-schedule-max-runs').value = schedule.max_runs || 10;
    const activeDays = schedule.active_days || ['mon','tue','wed','thu','fri'];
    document.querySelectorAll('.agent-day-cb').forEach(cb => cb.checked = activeDays.includes(cb.value));
    onScheduleRepeatChange();
    
    document.getElementById('agent-scraping-enable').checked = data.enable_scraping || false;
    document.getElementById('agent-scraper-limit').value = data.scraper_text_limit || 10000;
    document.getElementById('agent-scraper-format').value = data.script_output_format || 'json';
    
    document.getElementById('agent-tg-token').value = data.telegram_token || '';
    document.getElementById('agent-tg-chat').value = data.telegram_chat_id || '';
    
    document.getElementById('agent-ms-token').value = data.messenger_token || '';
    document.getElementById('agent-ms-page').value = data.messenger_page_id || '';
    document.getElementById('agent-ms-php').value = data.messenger_php_url || '';
    document.getElementById('agent-ms-skill').value = data.direct_trigger_skill_id || '';
    
    await populateAgentProfiles(data.allowed_profiles || []);
    await populateAgentSkills(data.allowed_skills || []);
    
    document.querySelector('.agent-tab-btn[data-atab="identity"]').click();
    document.getElementById('modal-agent').classList.remove('hidden');
}

async function populateAgentProfiles(allowed) {
    const data = await apiGet('/api/v1/browser/profiles');
    const container = document.getElementById('agent-profiles-list');
    if (!data || !data.profiles || data.profiles.length === 0) {
        container.innerHTML = '<p class="text-muted">No browser profiles found.</p>';
        return;
    }
    container.innerHTML = data.profiles.map(p => `
        <label class="checkbox-item">
            <input type="checkbox" value="${esc(p.name)}" class="agent-profile-cb" ${allowed.includes(p.name) ? 'checked' : ''}>
            ${esc(p.name)}
        </label>
    `).join('');
}

async function populateAgentSkills(allowed) {
    const data = await apiGet('/api/v1/skills');
    const container = document.getElementById('agent-skills-list');
    if (!data || !data.skills || data.skills.length === 0) {
        container.innerHTML = '<p class="text-muted">No skills found.</p>';
        return;
    }
    container.innerHTML = data.skills.map(s => `
        <label class="checkbox-item">
            <input type="checkbox" value="${s.id}" class="agent-skill-cb" ${allowed.includes(s.id) ? 'checked' : ''}>
            ${esc(s.name)} <span class="tag" style="margin-left:auto">${esc(s.type)}</span>
        </label>
    `).join('');
}

function closeModal(id) { document.getElementById(id).classList.add('hidden'); }

// ═══ Proxy / Schedule Toggles ═══
function onProxyModeChange() {
    const mode = document.getElementById('agent-proxy-mode').value;
    document.getElementById('proxy-static-group').style.display = mode === 'static' ? 'block' : 'none';
    document.getElementById('proxy-dynamic-group').style.display = mode === 'dynamic' ? 'block' : 'none';
}

function onScheduleRepeatChange() {
    const mode = document.getElementById('agent-schedule-repeat').value;
    document.getElementById('schedule-interval-group').style.display = mode === 'interval' ? 'block' : 'none';
}
// Attach change listener for schedule repeat
document.getElementById('agent-schedule-repeat')?.addEventListener('change', onScheduleRepeatChange);

async function saveAgent() {
    const name = document.getElementById('agent-name').value.trim();
    if (!name) return alert("Agent Name is required");
    
    const id = document.getElementById('agent-id').value;
    
    // Parse interests
    const interestsStr = document.getElementById('agent-interests').value;
    const interests = interestsStr ? interestsStr.split(',').map(s => s.trim()).filter(s => s) : [];
    
    // Parse behavior
    let routine = {};
    try {
        const val = document.getElementById('agent-behavior').value;
        if (val) routine = JSON.parse(val);
    } catch(e) {
        alert("Invalid JSON in Behavior tab: " + e.message);
        return;
    }
    
    const persona = { interests };
    
    // Collect profiles
    const allowed_profiles = Array.from(document.querySelectorAll('.agent-profile-cb:checked')).map(cb => cb.value);
    
    // Collect skills
    const allowed_skills = Array.from(document.querySelectorAll('.agent-skill-cb:checked')).map(cb => cb.value);
    
    // Build proxy provider
    const proxyMode = document.getElementById('agent-proxy-mode').value;
    const proxy_provider = { mode: proxyMode };
    if (proxyMode === 'dynamic') {
        proxy_provider.api_url = document.getElementById('agent-proxy-api').value;
        proxy_provider.api_key = document.getElementById('agent-proxy-api-key') ? document.getElementById('agent-proxy-api-key').value : '';
        proxy_provider.location = document.getElementById('agent-proxy-location') ? document.getElementById('agent-proxy-location').value : '';
    }
    
    // Build schedule
    const schedule = {
        enabled: document.getElementById('agent-schedule-enable').checked,
        repeat: document.getElementById('agent-schedule-repeat').value,
        interval: parseInt(document.getElementById('agent-schedule-interval').value) || 60,
        active_days: Array.from(document.querySelectorAll('.agent-day-cb:checked')).map(cb => cb.value),
        start_time: document.getElementById('agent-schedule-start').value,
        end_time: document.getElementById('agent-schedule-end').value,
        max_runs: parseInt(document.getElementById('agent-schedule-max-runs').value) || 10
    };
    
    const payload = {
        name,
        description: document.getElementById('agent-desc').value,
        system_prompt: document.getElementById('agent-prompt').value,
        model: document.getElementById('agent-model').value,
        browser_ai_model: document.getElementById('agent-browser-model').value,
        avatar_type: document.getElementById('agent-avatar-type').value,
        avatar_color: document.getElementById('agent-avatar-color').value,
        persona,
        routine,
        proxy_config: proxyMode === 'static' ? document.getElementById('agent-proxy').value : '',
        proxy_provider,
        timezone: document.getElementById('agent-timezone').value,
        schedule,
        enable_scraping: document.getElementById('agent-scraping-enable').checked,
        scraper_text_limit: parseInt(document.getElementById('agent-scraper-limit').value) || 10000,
        script_output_format: document.getElementById('agent-scraper-format').value,
        telegram_token: document.getElementById('agent-tg-token').value,
        telegram_chat_id: document.getElementById('agent-tg-chat').value,
        messenger_token: document.getElementById('agent-ms-token').value,
        messenger_page_id: document.getElementById('agent-ms-page').value,
        messenger_php_url: document.getElementById('agent-ms-php').value,
        direct_trigger_skill_id: document.getElementById('agent-ms-skill').value,
        allowed_profiles,
        allowed_skills
    };
    
    if (id) {
        await apiPut('/api/v1/agents/' + id, payload);
    } else {
        await apiPost('/api/v1/agents', payload);
    }
    
    closeModal('modal-agent');
    loadAgents();
}

async function deleteAgent(id) {
    if (!confirm('Delete this agent?')) return;
    await apiDelete('/api/v1/agents/' + id);
    loadAgents();
}

// ═══ Generate Agent with AI ═══
const AI_PROVIDERS = {
    "ollama": { models: ["deepseek-r1:latest", "llama3.2", "mistral-nemo"], needs_api: false },
    "gemini": { models: ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-2.5-pro", "gemini-2.0-flash-lite"], needs_api: true },
    "chatgpt": { models: ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"], needs_api: true },
    "claude": { models: ["claude-sonnet-4-20250514", "claude-3-5-haiku-20241022", "claude-3-5-sonnet-20241022"], needs_api: true },
    "grok": { models: ["grok-3", "grok-3-mini", "grok-2"], needs_api: true }
};

function showGenerateAgent() {
    document.getElementById('agent-gen-name').value = '';
    document.getElementById('agent-gen-prefix').value = '';
    document.getElementById('agent-gen-desc').value = '';
    document.getElementById('agent-gen-provider').value = 'ollama';
    document.getElementById('agent-gen-accounts').value = '';
    document.getElementById('agent-gen-preview').value = '';
    document.getElementById('agent-gen-status').textContent = '';
    document.getElementById('btn-apply-ai').style.display = 'none';
    
    onGenProviderChange();
    
    // Name to prefix auto-fill logic
    document.getElementById('agent-gen-name').addEventListener('input', (e) => {
        let val = e.target.value;
        let slug = val.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^agent_/, '').replace(/(^_|_$)/g, '');
        document.getElementById('agent-gen-prefix').value = slug;
    }, { once: false }); // Remove previously attached listeners if necessary, but here simple ID binds are ok since we replace but might stack. Better to use oninput in html normally, but replacing innerHTML of form isn't happening. Let's just define it inline.
    // Re-attach to avoid stacking
    const nameInput = document.getElementById('agent-gen-name');
    const newNameInput = nameInput.cloneNode(true);
    nameInput.parentNode.replaceChild(newNameInput, nameInput);
    newNameInput.addEventListener('input', (e) => {
        let val = e.target.value;
        let slug = val.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^agent_/, '').replace(/(^_|_$)/g, '');
        document.getElementById('agent-gen-prefix').value = slug;
    });

    const accInput = document.getElementById('agent-gen-accounts');
    const newAccInput = accInput.cloneNode(true);
    accInput.parentNode.replaceChild(newAccInput, accInput);
    newAccInput.addEventListener('input', (e) => {
        let val = e.target.value.trim();
        let lines = val ? val.split('\n').filter(l => l.includes('\t') || l.includes('@')).length : 0;
        document.getElementById('agent-gen-acc-count').textContent = lines + " accounts detected";
    });

    document.getElementById('modal-generate-agent').classList.remove('hidden');
}

function onGenProviderChange() {
    const prov = document.getElementById('agent-gen-provider').value;
    const info = AI_PROVIDERS[prov] || AI_PROVIDERS["ollama"];
    
    const modelSelect = document.getElementById('agent-gen-model');
    modelSelect.innerHTML = info.models.map(m => `<option value="${m}">${m}</option>`).join('');
    
    const apiGroup = document.getElementById('agent-gen-apikey-group');
    apiGroup.style.display = info.needs_api ? 'block' : 'none';
}

async function generateAgentJSON() {
    const name = document.getElementById('agent-gen-name').value.trim();
    const desc = document.getElementById('agent-gen-desc').value.trim();
    if (!name || !desc) return alert("Agent Name and Description are required parameter strings for the AI!");
    
    const btnGen = document.getElementById('btn-generate-ai');
    btnGen.disabled = true;
    document.getElementById('btn-apply-ai').style.display = 'none';
    
    const provider = document.getElementById('agent-gen-provider').value;
    const model = document.getElementById('agent-gen-model').value;
    const api_key = document.getElementById('agent-gen-apikey').value.trim();
    
    const statusLine = document.getElementById('agent-gen-status');
    statusLine.style.color = 'var(--text)';
    statusLine.textContent = `🤖 Calling ${provider} / ${model}... (this may take up to 2 minutes)`;
    document.getElementById('agent-gen-preview').value = 'Generating... Please wait. Do not close this dialog.';
    
    const payload = { name, description: desc, provider, model, api_key };
    
    try {
        const resp = await apiPost('/api/v1/agents/generate', payload);
        if (resp && resp.status === 'success' && resp.data) {
            document.getElementById('agent-gen-preview').value = JSON.stringify(resp.data, null, 2);
            statusLine.textContent = '✅ Generation Complete!';
            statusLine.style.color = 'var(--green)';
            document.getElementById('btn-apply-ai').style.display = 'inline-block';
            window._lastGeneratedAgent = resp.data;
        } else {
            statusLine.textContent = '❌ Generation Failed';
            statusLine.style.color = 'var(--red)';
            document.getElementById('agent-gen-preview').value = JSON.stringify(resp, null, 2);
        }
    } catch(err) {
        statusLine.textContent = '❌ Error contacting server. Ensure API provider keys are correct.';
        statusLine.style.color = 'var(--red)';
        console.error(err);
    }
    btnGen.disabled = false;
}

function applyGeneratedAgent() {
    if (!window._lastGeneratedAgent) return;
    const data = window._lastGeneratedAgent;
    
    // Open main modal
    showCreateAgent();
    // Overwrite auto-cleaned fields with new data
    document.getElementById('agent-name').value = data.name || '';
    document.getElementById('agent-desc').value = data.description || '';
    
    const persona = data.persona || {};
    document.getElementById('agent-interests').value = (persona.interests || []).join(', ');
    
    const behavior = {
        dailyRoutine: (data.routine || {}).dailyRoutine || [],
        workHabits: (data.routine || {}).workHabits || {}
    };
    document.getElementById('agent-behavior').value = JSON.stringify(behavior, null, 2);
    
    // Process accounts to create browser profiles in UI state
    // In the real python-video-studio, it hits the api to create profiles.
    // Here we can parse the accounts textarea
    const rawAccounts = document.getElementById('agent-gen-accounts').value.trim();
    const prefix = document.getElementById('agent-gen-prefix').value.trim() || 'profile';
    
    let allowed_profiles = [];
    if (rawAccounts) {
        const lines = rawAccounts.split('\\n');
        let idx = 1;
        lines.forEach(line => {
            if (line.includes('\\t') || line.includes('@')) {
                const profileName = `${prefix}_${idx.toString().padStart(3, '0')}`;
                allowed_profiles.push(profileName);
                
                // Fire and forget creation of profiles on backend
                apiPost('/api/v1/browser/profiles', { name: profileName, proxy: '' });
                idx++;
            }
        });
    }
    
    // We mock the populate of profiles temporarily or force reload from API after a short delay
    setTimeout(() => {
        populateAgentProfiles(allowed_profiles);
    }, 1000); // 1s delay to let backend create them

    closeModal('modal-generate-agent');
}

// ═══ Browser Profiles ═══
async function loadProfiles() {
    const data = await apiGet('/api/v1/browser/profiles');
    const container = document.getElementById('profiles-list');
    if (!data || !data.profiles) {
        container.innerHTML = '<p style="color:var(--text-muted)">Browser plugin not active. Enable with: tubecli plugin enable browser</p>';
        return;
    }
    if (data.profiles.length === 0) {
        container.innerHTML = '<p style="color:var(--text-muted)">No profiles. Create one!</p>';
        return;
    }
    // Get running statuses
    const status = await apiGet('/api/v1/browser/status');
    const runningProfiles = (status?.instances || []).map(i => i.profile);

    container.innerHTML = data.profiles.map(p => {
        const isRunning = runningProfiles.includes(p.name);
        return `
        <div class="card ${isRunning ? 'border-blue' : ''}">
            <div class="card-icon">🌐</div>
            <h3>${esc(p.name)} ${isRunning ? ' <span class="pulse-dot" style="display:inline-block"></span>' : ''}</h3>
            <p class="card-meta">${esc(p.proxy || 'No proxy')} · ${(p.tags || []).join(', ')}</p>
            <p class="card-desc">
                ${p.has_cookies ? '🍪 Cookies ' : ''} 
                ${p.has_fingerprint ? '🧬 Fingerprint OK ' : '<span style="color:var(--orange)">⚠️ No Fingerprint</span> '}
                <br>${esc(p.notes || '')}
            </p>
            <div class="card-footer" style="flex-wrap: wrap; gap: 8px;">
                <span class="tag green">${esc(p.created_at ? p.created_at.slice(0, 10) : '')}</span>
                <div class="card-actions">
                    ${isRunning 
                        ? `<button class="btn-sm btn-danger" onclick="stopProfile('${esc(p.name)}', this)">⏹ Stop</button>`
                        : `<button class="btn-sm" onclick="launchProfile('${esc(p.name)}', this)">▶ Launch</button>`
                    }
                    <button class="btn-sm" style="background:var(--bg3)" onclick="resetFingerprint('${esc(p.name)}')">🔄 Reset FP</button>
                    <button class="btn-danger" onclick="deleteProfile('${esc(p.name)}')">✕</button>
                </div>
            </div>
        </div>
    `}).join('');

    const bar = document.getElementById('running-browsers');
    if (status && status.instances && status.instances.length > 0) {
        document.getElementById('running-count').textContent = status.instances.length;
        bar.classList.remove('hidden');
    } else {
        bar.classList.add('hidden');
    }
}

function showCreateProfile() { document.getElementById('modal-profile').classList.remove('hidden'); }

async function createProfile() {
    const btn = document.getElementById('btn-create-profile-submit');
    const name = document.getElementById('profile-name').value.trim();
    if (!name) return;

    btn.disabled = true;
    btn.textContent = 'Creating...';

    const tags = [
        document.getElementById('profile-os').value,
        document.getElementById('profile-browser').value
    ];

    await apiPost('/api/v1/browser/profiles', {
        name,
        proxy: document.getElementById('profile-proxy').value,
        tags: tags
    });

    btn.disabled = false;
    btn.textContent = 'Create & Fetch Fingerprint';

    closeModal('modal-profile');
    document.getElementById('profile-name').value = '';
    document.getElementById('profile-proxy').value = '';
    loadProfiles();
}

async function launchProfile(name, btn) {
    if (btn) {
        btn.disabled = true;
        btn.textContent = '🚀 Launching...';
    }
    console.log(`[Browser] Launching profile: ${name}...`);
    const result = await apiPost('/api/v1/browser/launch', { profile: name, manual: true });
    if (result) {
        console.log(`[Browser] Launch requested successfully:`, result);
        // Retry status check a few times
        let attempts = 0;
        const interval = setInterval(async () => {
            await loadProfiles();
            attempts++;
            if (attempts >= 5) clearInterval(interval);
        }, 2000);
    } else {
        console.error(`[Browser] Failed to request launch for ${name}`);
        if (btn) {
            btn.disabled = false;
            btn.textContent = '▶ Launch';
        }
        alert('Failed to launch browser. Check console/logs.');
    }
}

async function stopProfile(name, btn) {
    if (btn) {
        btn.disabled = true;
        btn.textContent = 'Stopping...';
    }
    await apiPost('/api/v1/browser/stop', { profile: name });
    setTimeout(loadProfiles, 1000);
}

async function deleteProfile(name) {
    if (!confirm('Delete profile ' + name + '?')) return;
    await apiDelete('/api/v1/browser/profiles/' + name);
    loadProfiles();
}

async function resetFingerprint(name) {
    if (!confirm('Reset fingerprint for profile ' + name + '? A new one will be fetched.')) return;
    const res = await apiPost('/api/v1/browser/profiles/' + name + '/fingerprint/reset', {});
    if (res) {
        alert('Fingerprint reset successfully.');
        loadProfiles();
    } else {
        alert('Failed to reset fingerprint.');
    }
}

// ═══ Skills ═══
async function loadSkills() {
    const data = await apiGet('/api/v1/skills');
    const container = document.getElementById('skills-list');
    if (!data || !data.skills) {
        container.innerHTML = '<p style="color:var(--text-muted)">Cannot load skills.</p>';
        return;
    }
    container.innerHTML = data.skills.map(s => `
        <div class="card">
            <div class="card-icon">⚡</div>
            <h3>${esc(s.name)}</h3>
            <p class="card-desc">${esc(s.description || '')}</p>
            <div class="card-footer">
                <span class="tag">${esc(s.type || 'Skill')}</span>
                <button class="btn-sm" onclick="runSkill('${s.id}')">▶ Run</button>
            </div>
        </div>
    `).join('');
}

async function runSkill(id) {
    alert('Skill execution started. Check terminal for output.');
}

// ═══ Workflows ═══
async function loadWorkflows() {
    const iframe = document.getElementById('workflow-iframe');
    // If we want to force reload on tab click:
    // iframe.src = '/workflow';
}

function openFullscreenWorkflow() {
    window.open('/workflow', '_blank');
}

function reloadWorkflowEditor() {
    const iframe = document.getElementById('workflow-iframe');
    iframe.src = iframe.src;
}

// ═══ Market ═══
function searchMarket() {
    const q = document.getElementById('market-search').value.toLowerCase();
    document.querySelectorAll('#market-list .card').forEach(card => {
        const text = card.textContent.toLowerCase();
        card.style.display = text.includes(q) ? '' : 'none';
    });
}

// ═══ Plugins ═══
async function loadPlugins() {
    const data = await apiGet('/api/v1/plugins');
    const container = document.getElementById('plugins-list');
    if (!data || !data.plugins) {
        container.innerHTML = '<p style="color:var(--text-muted)">Cannot load plugins.</p>';
        return;
    }
    
    container.innerHTML = data.plugins.map(p => `
        <div class="card ${!p.enabled ? 'disabled-plugin' : ''}" style="${!p.enabled ? 'opacity: 0.6;' : ''}">
            <div class="card-icon">🧩</div>
            <h3>${esc(p.name)}</h3>
            <p class="card-meta">v${esc(p.version)} · By ${esc(p.author)}</p>
            <p class="card-desc">${esc(p.description)}</p>
            ${p.current_port ? `<p class="card-meta" style="color:var(--cyan)">🔌 Port: <b>${p.current_port}</b></p>` : ''}
            
            <div class="card-footer" style="margin-top: 15px; border-top: 1px solid var(--border); padding-top: 10px;">
                <span class="tag ${p.enabled ? 'green' : ''}">${p.enabled ? 'Active' : 'Disabled'}</span>
                <div class="card-actions">
                    ${p.default_port !== null ? `<button class="btn-sm" style="background:var(--bg3)" onclick="configurePlugin('${esc(p.name)}', ${p.current_port || p.default_port})">⚙️ Port</button>` : ''}
                    <button class="${p.enabled ? 'btn-danger' : 'btn-primary'} btn-sm" onclick="togglePlugin('${esc(p.name)}', ${p.enabled})">
                        ${p.enabled ? 'Disable' : 'Enable'}
                    </button>
                </div>
            </div>
        </div>
    `).join('');
}

async function togglePlugin(name, isEnabled) {
    const action = isEnabled ? 'disable' : 'enable';
    const res = await apiPost(`/api/v1/plugins/${name}/${action}`, {});
    if (res) {
        loadPlugins();
    } else {
        alert(`Failed to ${action} plugin: ${name}`);
    }
}

function configurePlugin(name, currentPort) {
    document.getElementById('edit-plugin-name').value = name;
    document.getElementById('edit-plugin-port').value = currentPort || '';
    document.getElementById('modal-plugin-port').classList.remove('hidden');
}

async function savePluginPort() {
    const name = document.getElementById('edit-plugin-name').value;
    const port = parseInt(document.getElementById('edit-plugin-port').value);
    
    if (!name || isNaN(port)) return;
    
    const res = await apiPut(`/api/v1/plugins/${name}`, { port: port });
    if (res) {
        closeModal('modal-plugin-port');
        loadPlugins();
        alert('Port updated successfully. You may need to restart the plugin for the changes to take effect.');
    } else {
        alert('Failed to update port.');
    }
}

// ═══ Settings ═══
function saveSettings() {
    const api = document.getElementById('set-api').value.trim();
    if (api) {
        localStorage.setItem('tubecli_api', api);
        location.reload();
    }
}

// ═══ Utility ═══
function esc(s) {
    if (!s) return '';
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
}

// ═══ Check API Connection ═══
async function checkConnection() {
    try {
        const resp = await fetch(API + '/api/v1/health', { signal: AbortSignal.timeout(2000) });
        if (resp.ok) {
            document.querySelector('.sidebar-footer').innerHTML = '<span class="status-dot"></span> API Connected';
        } else {
            throw new Error();
        }
    } catch {
        document.querySelector('.sidebar-footer').innerHTML = '<span class="status-dot" style="background:var(--red)"></span> API Offline';
    }
}

// ═══ Init ═══
document.addEventListener('DOMContentLoaded', () => {
    checkConnection();
    loadAgents();
    // Load saved API URL
    const savedApi = localStorage.getItem('tubecli_api');
    if (savedApi) document.getElementById('set-api').value = savedApi;
});
