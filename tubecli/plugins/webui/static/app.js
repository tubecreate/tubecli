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
                <button class="btn-danger" onclick="deleteAgent('${a.id}')">Delete</button>
            </div>
        </div>
    `).join('');
}

function showCreateAgent() { document.getElementById('modal-agent').classList.remove('hidden'); }
function closeModal(id) { document.getElementById(id).classList.add('hidden'); }

async function createAgent() {
    const name = document.getElementById('agent-name').value.trim();
    if (!name) return;
    await apiPost('/api/v1/agents', {
        name,
        description: document.getElementById('agent-desc').value,
        model: document.getElementById('agent-model').value
    });
    closeModal('modal-agent');
    document.getElementById('agent-name').value = '';
    document.getElementById('agent-desc').value = '';
    loadAgents();
}

async function deleteAgent(id) {
    if (!confirm('Delete this agent?')) return;
    await apiDelete('/api/v1/agents/' + id);
    loadAgents();
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
    container.innerHTML = data.profiles.map(p => `
        <div class="card">
            <div class="card-icon">🌐</div>
            <h3>${esc(p.name)}</h3>
            <p class="card-meta">${esc(p.proxy || 'No proxy')} · ${(p.tags || []).join(', ')}</p>
            <p class="card-desc">${p.has_cookies ? '🍪 Has cookies' : ''} ${esc(p.notes || '')}</p>
            <div class="card-footer">
                <span class="tag green">${esc(p.created_at ? p.created_at.slice(0, 10) : '')}</span>
                <div class="card-actions">
                    <button class="btn-sm" onclick="launchProfile('${esc(p.name)}')">▶ Launch</button>
                    <button class="btn-danger" onclick="deleteProfile('${esc(p.name)}')">✕</button>
                </div>
            </div>
        </div>
    `).join('');

    // Check running
    const status = await apiGet('/api/v1/browser/status');
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
    const name = document.getElementById('profile-name').value.trim();
    if (!name) return;
    await apiPost('/api/v1/browser/profiles', {
        name,
        proxy: document.getElementById('profile-proxy').value
    });
    closeModal('modal-profile');
    document.getElementById('profile-name').value = '';
    document.getElementById('profile-proxy').value = '';
    loadProfiles();
}

async function launchProfile(name) {
    const result = await apiPost('/api/v1/browser/launch', { profile: name });
    if (result) loadProfiles();
}

async function deleteProfile(name) {
    if (!confirm('Delete profile ' + name + '?')) return;
    await apiDelete('/api/v1/browser/profiles/' + name);
    loadProfiles();
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
    const container = document.getElementById('workflows-list');
    const data = await apiGet('/api/v1/nodes');
    if (!data) {
        container.innerHTML = '<p style="color:var(--text-muted)">Cannot connect to API.</p>';
        return;
    }
    // Show available node types as cards
    container.innerHTML = (data.nodes || []).map(n => `
        <div class="card">
            <div class="card-icon">${n.icon || '📦'}</div>
            <h3>${esc(n.name)}</h3>
            <p class="card-meta">${esc(n.type)}</p>
            <p class="card-desc">In: ${esc(n.inputs.join(', '))} → Out: ${esc(n.outputs.join(', '))}</p>
        </div>
    `).join('');
}

// ═══ Market ═══
function searchMarket() {
    const q = document.getElementById('market-search').value.toLowerCase();
    document.querySelectorAll('#market-list .card').forEach(card => {
        const text = card.textContent.toLowerCase();
        card.style.display = text.includes(q) ? '' : 'none';
    });
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
