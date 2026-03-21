/**
 * TubeCLI Dashboard — SPA Logic
 * Dashboard → Extensions → API Manager → Settings
 */
const API = localStorage.getItem('tubecli_api') || 'http://localhost:5295';

// ═══ Tab Navigation ═══
document.querySelectorAll('.nav-item').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
        btn.classList.add('active');
        const el = document.getElementById('tab-' + btn.dataset.tab);
        if (el) el.classList.add('active');
        closeExtDetail(); // always close overlay when switching tabs
        const tab = btn.dataset.tab;
        if (tab === 'dashboard') loadDashboard();
        else if (tab === 'extensions') loadExtensions();
        else if (tab === 'api-manager') loadApiManagerPage();
    });
});

// Agent Modal Tabs
document.querySelectorAll('.agent-tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.agent-tab-btn').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.agent-tab-pane').forEach(p => p.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById('atab-' + btn.dataset.atab).classList.add('active');
    });
});

// ═══ API Helpers ═══
async function apiGet(path) { try { const r = await fetch(API + (path.includes('?') ? `${path}&_t=${Date.now()}` : `${path}?_t=${Date.now()}`)); if (!r.ok) { const t = await r.text().catch(()=>''); console.error('GET', path, r.status, t.slice(0,200)); return { error: `Server error ${r.status}`, status_code: r.status, detail: t.slice(0,200) }; } return await r.json(); } catch(e) { console.error('GET', path, e); return { error: e.message || 'Network error' }; } }
async function apiPost(path, data) { try { const r = await fetch(API + path, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data) }); return await r.json(); } catch(e) { console.error('POST', path, e); return { error: e.message }; } }
async function apiPut(path, data) { try { const r = await fetch(API + path, { method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data) }); return await r.json(); } catch(e) { console.error('PUT', path, e); return { error: e.message }; } }
async function apiDelete(path, data) { try { const opts = { method:'DELETE' }; if(data) { opts.headers = {'Content-Type':'application/json'}; opts.body = JSON.stringify(data); } const r = await fetch(API + path, opts); return await r.json(); } catch(e) { console.error('DEL', path, e); return { error: e.message }; } }

// ═══════════════════════════════════════════════════════════
// ═══ DASHBOARD (Stats + Status) ═══
// ═══════════════════════════════════════════════════════════
async function loadDashboard() {
    const [agents, profiles, skills, extensions, wfs, ollamaStatus, keysData] = await Promise.all([
        apiGet('/api/v1/agents'), apiGet('/api/v1/browser/profiles'),
        apiGet('/api/v1/skills'), apiGet('/api/v1/extensions'),
        apiGet('/api/v1/workflows'), apiGet('/api/v1/ollama/status'),
        apiGet('/api/v1/cloud-api/keys'),
    ]);
    document.getElementById('stat-agents').textContent = agents?.agents?.length ?? 0;
    document.getElementById('stat-profiles').textContent = profiles?.profiles?.length ?? 0;
    document.getElementById('stat-skills').textContent = skills?.skills?.length ?? 0;
    document.getElementById('stat-workflows').textContent = wfs?.workflows?.length ?? 0;
    document.getElementById('stat-extensions').textContent = extensions?.count ?? 0;
    // Count keys
    let keyCount = 0;
    if (keysData?.keys) Object.values(keysData.keys).forEach(labels => { keyCount += Object.keys(labels).length; });
    document.getElementById('stat-api-keys').textContent = keyCount;
    // Status
    document.getElementById('status-api-dot').style.color = 'var(--green)';
    document.getElementById('status-api-label').className = 'tag green';
    document.getElementById('status-api-label').textContent = T('status.online');
    if (ollamaStatus?.running) {
        document.getElementById('status-ollama-dot').style.color = 'var(--green)';
        document.getElementById('status-ollama-label').className = 'tag green';
        document.getElementById('status-ollama-label').textContent = `${T('status.online')} (${ollamaStatus.model_count} ${T('status.models')})`;
    } else {
        document.getElementById('status-ollama-dot').style.color = 'var(--red)';
        document.getElementById('status-ollama-label').className = 'tag';
        document.getElementById('status-ollama-label').textContent = T('status.offline');
    }
    const browserStatus = await apiGet('/api/v1/browser/status');
    const runCount = browserStatus?.instances?.length ?? 0;
    document.getElementById('status-browser-dot').style.color = runCount > 0 ? 'var(--green)' : 'var(--text-muted)';
    document.getElementById('status-browser-label').className = runCount > 0 ? 'tag green' : 'tag';
    document.getElementById('status-browser-label').textContent = runCount > 0 ? `${runCount} ${T('status.running')}` : T('status.idle');
}

// ═══════════════════════════════════════════════════════════
// ═══ EXTENSIONS (All features as clickable cards) ═══
// ═══════════════════════════════════════════════════════════
const EXT_REGISTRY = [
    { id:'agents', icon:'🤖', name:T('nav.dashboard'), desc:T('ext.agents_desc'), type:'core' },
    { id:'browser', icon:'🌐', name:T('stat.profiles'), desc:T('ext.browser_desc'), type:'core' },
    { id:'workflows', icon:'🔄', name:T('stat.workflows'), desc:T('ext.workflows_desc'), type:'core' },
    { id:'skills', icon:'⚡', name:T('stat.skills'), desc:T('ext.skills_desc'), type:'core' },
    { id:'market', icon:'🛒', name:T('ext.market_desc'), desc:T('ext.market_desc'), type:'core' },
    { id:'cloud_api', icon:'☁️', name:T('dash.cloud_api_keys'), desc:T('ext.cloud_api_desc'), type:'extension' },
    { id:'ollama', icon:'🧠', name:'Ollama Manager', desc:T('ext.ollama_desc'), type:'extension' },
    { id:'multi_agents', icon:'👥', name:'Multi-Agents', desc:T('ext.multi_agents_desc'), type:'extension' },
];

async function loadExtensions() {
    const extensionData = await apiGet('/api/v1/extensions');
    const extensions = extensionData?.extensions || [];
    const extensionMap = {};
    extensions.forEach(p => { extensionMap[p.name] = p; });
    const grid = document.getElementById('extensions-grid');
    grid.innerHTML = EXT_REGISTRY.map(ext => {
        const extension = extensionMap[ext.id];
        const version = extension?.version || '-';
        const isEnabled = extension ? extension.enabled : true;
        return `<div class="card ext-card" onclick="openExtDetail('${ext.id}')" style="${!isEnabled ? 'opacity:0.5' : ''}">
            <div class="card-icon">${ext.icon}</div>
            <h3>${esc(ext.name)}</h3>
            <p class="card-meta">v${esc(version)} · ${esc(ext.type)}</p>
            <p class="card-desc">${esc(ext.desc)}</p>
            <div class="card-footer" style="margin-top:10px"><span class="tag ${ext.type === 'extension' ? 'blue' : 'green'}">${ext.type}</span></div>
        </div>`;
    }).join('');
}

// ═══ Extension Detail Overlay ═══
function openExtDetail(id) {
    const ext = EXT_REGISTRY.find(e => e.id === id);
    if (!ext) return;
    const overlay = document.getElementById('ext-detail-overlay');
    const title = document.getElementById('ext-detail-title');
    const body = document.getElementById('ext-detail-body');
    title.textContent = ext.icon + ' ' + ext.name;
    body.innerHTML = `<p class="text-muted">${T('chat.loading')}</p>`;
    overlay.classList.remove('hidden');
    // Route to detail renderer
    stopBrowserStatusPoller();
    if (id === 'agents') renderAgentsExt(body);
    else if (id === 'browser') renderBrowserExt(body);
    else if (id === 'workflows') renderWorkflowsExt(body);
    else if (id === 'skills') renderSkillsExt(body);
    else if (id === 'market') renderMarketExt(body);
    else if (id === 'cloud_api') renderCloudApiExt(body);
    else if (id === 'ollama') renderOllamaExt(body);
    else if (id === 'multi_agents') renderMultiAgentsExt(body);
}
function closeExtDetail() { document.getElementById('ext-detail-overlay').classList.add('hidden'); }

// ── Agents Ext ──
async function renderAgentsExt(el) {
    const data = await apiGet('/api/v1/agents');
    const agents = data?.agents || [];
    let h = `<div style="display:flex;gap:10px;margin-bottom:20px">
        <button class="btn-primary" style="background:linear-gradient(135deg,#a855f7,#ec4899)" onclick="showGenerateAgent()">${T('agents.generate_ai')}</button>
        <button class="btn-primary" onclick="showCreateAgent()">${T('agents.create')}</button>
    </div>`;
    if (agents.length === 0) h += `<p class="text-muted">${T('agents.no_agents')}</p>`;
    else h += '<div class="cards-grid">' + agents.map(a => `<div class="card"><div class="card-icon">🤖</div><h3>${esc(a.name)}</h3><p class="card-meta">${esc(a.model||'default')}</p><p class="card-desc">${esc(a.description||'')}</p><div class="card-footer"><span class="tag">${(a.allowed_skills||[]).length} ${T('agents.skills_count')}</span><div class="card-actions"><button class="btn-sm btn-primary" onclick="openChatAgent('${a.id}','${esc(a.name)}')">${T('agents.chat')}</button><button class="btn-sm" onclick="openEditAgent('${a.id}')">${T('agents.edit')}</button><button class="btn-danger" onclick="deleteAgent('${a.id}');renderAgentsExt(document.getElementById('ext-detail-body'))">${T('agents.delete')}</button></div></div></div>`).join('') + '</div>';
    el.innerHTML = h;
}

// ── Browser Ext ──
let _browserStatusPoller = null;
let _lastRunningProfiles = '';
function startBrowserStatusPoller(el) {
    stopBrowserStatusPoller();
    _browserStatusPoller = setInterval(async () => {
        try {
            const status = await apiGet('/api/v1/browser/status');
            const running = (status?.instances||[]).map(i => i.profile).sort().join(',');
            if (running !== _lastRunningProfiles) {
                _lastRunningProfiles = running;
                renderBrowserExt(el);
            }
        } catch(e) {}
    }, 5000);
}
function stopBrowserStatusPoller() {
    if (_browserStatusPoller) { clearInterval(_browserStatusPoller); _browserStatusPoller = null; }
}

async function renderBrowserExt(el) {
    const data = await apiGet('/api/v1/browser/profiles');
    const profiles = data?.profiles || [];
    const status = await apiGet('/api/v1/browser/status');
    const runningProfiles = (status?.instances||[]).map(i => i.profile);
    _lastRunningProfiles = runningProfiles.slice().sort().join(',');
    startBrowserStatusPoller(el);
    let h = `<div style="margin-bottom:16px;display:flex;gap:10px"><button class="btn-primary" onclick="showCreateProfile()">${T('browser.new_profile')}</button><button class="btn-secondary" onclick="showBrowserEnginesModal()">Browser Engines</button></div>`;
    if (status?.instances?.length > 0) h += `<div class="status-bar"><span class="pulse-dot"></span> ${status.instances.length} ${T('status.running')}</div>`;
    if (profiles.length === 0) h += `<p class="text-muted">${T('browser.no_profiles')}</p>`;
    else h += '<div class="cards-grid">' + profiles.map(p => {
        const isR = runningProfiles.includes(p.name);
        return `<div class="card"><div class="card-icon">🌐</div><h3>${esc(p.name)} ${isR ? '<span class="pulse-dot" style="display:inline-block"></span>' : ''}</h3><p class="card-meta">${esc(p.proxy||T('browser.no_proxy'))}</p><p class="card-desc">${p.has_fingerprint ? '🧬 FP OK' : `<span style="color:var(--orange)">⚠️ No FP</span>`} ${p.has_cookies ? '🍪' : ''}</p><div class="card-footer" style="flex-wrap:wrap;gap:8px"><span class="tag green">${esc((p.created_at||'').slice(0,10))}</span><div class="card-actions">${isR ? `<button class="btn-sm btn-danger" onclick="stopProfile('${esc(p.name)}',this)">⏹</button>` : `<button class="btn-sm" onclick="launchProfile('${esc(p.name)}',this)">▶</button>`}<button class="btn-danger" onclick="deleteProfile('${esc(p.name)}');setTimeout(()=>renderBrowserExt(document.getElementById('ext-detail-body')),500)">✕</button></div></div></div>`;
    }).join('') + '</div>';
    el.innerHTML = h;
}

// ── Workflows Ext ──
async function renderWorkflowsExt(el) {
    el.innerHTML = `<div style="height:calc(100vh - 150px);border:1px solid var(--border);border-radius:8px;overflow:hidden"><iframe src="/workflow?v=3" style="width:100%;height:100%;border:none"></iframe></div>`;
}

// ── Skills Ext ──
async function renderSkillsExt(el) {
    const data = await apiGet('/api/v1/skills');
    const skills = data?.skills || [];
    if (skills.length === 0) { el.innerHTML = `<p class="text-muted">${T('skills.no_skills')}</p>`; return; }
    el.innerHTML = '<div class="cards-grid">' + skills.map(s => `<div class="card"><div class="card-icon">⚡</div><h3>${esc(s.name)}</h3><p class="card-desc">${esc(s.description||'')}</p><div class="card-footer"><span class="tag">${esc(s.type||'Skill')}</span><button class="btn-sm" onclick="alert(T('skills.executed'))">${T('skills.run')}</button></div></div>`).join('') + '</div>';
}

// ── Market Ext ──
function renderMarketExt(el) {
    el.innerHTML = `<div class="market-search"><input id="market-search" placeholder="Search skills, extensions..." oninput="searchMarket()"></div>
    <div id="market-list" class="cards-grid">
        <div class="card"><div class="card-icon">🎬</div><h3>YouTube Uploader</h3><p class="card-desc">Auto upload videos with SEO</p><div class="card-footer"><span class="tag">community</span><button class="btn-sm">Install</button></div></div>
        <div class="card"><div class="card-icon">📱</div><h3>TikTok Poster</h3><p class="card-desc">Auto post to TikTok</p><div class="card-footer"><span class="tag">community</span><button class="btn-sm">Install</button></div></div>
        <div class="card"><div class="card-icon">📧</div><h3>Email Sender</h3><p class="card-desc">Batch email with templates</p><div class="card-footer"><span class="tag">community</span><button class="btn-sm">Install</button></div></div>
        <div class="card"><div class="card-icon">🕷️</div><h3>Web Scraper</h3><p class="card-desc">Extract data with CSS selectors</p><div class="card-footer"><span class="tag">official</span><button class="btn-sm">Install</button></div></div>
    </div>`;
}

// ── Cloud API Ext ──
async function renderCloudApiExt(el) {
    const [provData, keysData] = await Promise.all([apiGet('/api/v1/cloud-api/providers'), apiGet('/api/v1/cloud-api/keys')]);
    const providers = provData?.providers || [];
    const keys = keysData?.keys || {};
    const provIcons = { gemini:'✨', openai:'🤖', claude:'🧠', deepseek:'🔍', grok:'⚡' };
    let h = `<div style="margin-bottom:20px"><button class="btn-primary" onclick="showAddApiKey()">${T('cloud_api.add_key')}</button></div>`;
    // Provider cards
    h += '<div class="cards-grid" style="margin-bottom:28px">';
    providers.forEach(p => {
        h += `<div class="card" style="text-align:center"><div class="card-icon">${provIcons[p.id]||'☁️'}</div><h3>${esc(p.name)}</h3><p class="card-desc">${p.models.slice(0,2).join(', ')}</p><div class="card-footer" style="justify-content:center;gap:8px"><span class="tag ${p.has_key?'green':''}">${p.has_key?T('cloud_api.active'):T('cloud_api.no_key')}</span>${!p.has_key ? `<button class="btn-sm btn-primary" onclick="prefillAddKey('${esc(p.id)}')">${T('cloud_api.add')}</button>` : `<button class="btn-sm" onclick="testApiKey('${esc(p.id)}')">${T('cloud_api.test')}</button>`}</div></div>`;
    });
    h += '</div>';
    // Keys table
    const allKeys = [];
    Object.entries(keys).forEach(([prov, labels]) => { Object.entries(labels).forEach(([label, info]) => { allKeys.push({provider:prov, label, ...info}); }); });
    h += `<h3 style="color:var(--cyan);margin-bottom:12px">${T('cloud_api.stored_keys')}</h3>`;
    if (allKeys.length > 0) {
        h += `<div class="table-container"><table class="data-table"><thead><tr><th>${T('cloud_api.provider')}</th><th>${T('cloud_api.label')}</th><th>${T('cloud_api.key')}</th><th>${T('cloud_api.status')}</th><th>${T('cloud_api.actions')}</th></tr></thead><tbody>`;
        allKeys.forEach(k => { h += `<tr><td style="font-weight:600;color:var(--cyan)">${esc(k.provider)}</td><td>${esc(k.label)}</td><td style="font-family:'JetBrains Mono',monospace;font-size:.8rem;color:var(--text-muted)">${esc(k.masked_key)}</td><td>${k.active?`<span style="color:var(--green)">● ${T('cloud_api.active')}</span>`:'○'}</td><td><button class="btn-danger" onclick="removeApiKeyExt('${esc(k.provider)}','${esc(k.label)}')">✕</button></td></tr>`; });
        h += '</tbody></table></div>';
    } else h += `<p class="text-muted">${T('cloud_api.no_keys')}</p>`;
    el.innerHTML = h;
}

async function removeApiKeyExt(provider, label) { if (!confirm(`Remove "${label}" from ${provider}?`)) return; await apiDelete('/api/v1/cloud-api/keys', {provider,label}); renderCloudApiExt(document.getElementById('ext-detail-body')); }

// ── Ollama Ext ──
async function renderOllamaExt(el) {
    const [st, mdls, run] = await Promise.all([apiGet('/api/v1/ollama/status'), apiGet('/api/v1/ollama/models'), apiGet('/api/v1/ollama/running')]);
    const models = mdls?.models || [];
    const running = run?.running || [];
    const runNames = running.map(r => r.name);
    let h = `<div class="ext-info-grid" style="margin-bottom:24px">
        <div class="ext-info-card"><div class="info-value" style="font-size:1.6rem">${st?.running?'🟢':'🔴'}</div><div class="info-label" style="font-weight:600;color:var(--text)">${st?.running?T('status.online'):T('status.offline')}</div><div class="info-label">${esc(st?.base_url||'')}</div></div>
        <div class="ext-info-card"><div class="info-value">${models.length}</div><div class="info-label">${T('ollama.models')}</div></div>
        <div class="ext-info-card"><div class="info-value">${running.length}</div><div class="info-label">${T('ollama.loaded')}</div></div>
    </div>`;
    h += `<h3 style="color:var(--cyan);margin-bottom:12px">${T('ollama.models')}</h3>`;
    if (models.length > 0) {
        h += `<div class="table-container"><table class="data-table"><thead><tr><th>${T('ollama.model_col')}</th><th>${T('ollama.size_col')}</th><th>${T('ollama.modified_col')}</th><th>${T('ollama.status_col')}</th><th>${T('ollama.actions_col')}</th></tr></thead><tbody>`;
        models.forEach(m => { const loaded = runNames.some(r => r.startsWith(m.name.split(':')[0])); h += `<tr><td style="font-weight:600;color:var(--cyan)">${esc(m.name)}</td><td>${esc(m.size_human)}</td><td style="color:var(--text-muted)">${esc((m.modified_at||'').slice(0,10))}</td><td>${loaded?`<span style="color:var(--green)">${T('ollama.loaded')}</span>`:`💤 ${T('status.idle')}`}</td><td><button class="btn-danger" onclick="removeOllamaModel('${esc(m.name)}')">✕</button></td></tr>`; });
        h += '</tbody></table></div>';
    } else h += `<p class="text-muted">${st?.running?T('ollama.no_models'):T('ollama.not_running')}</p>`;
    h += `<div style="margin-top:16px;display:flex;gap:10px"><input id="ollama-pull-input" placeholder="e.g. qwen:latest" style="flex:1;padding:10px 14px;border:1px solid var(--border);border-radius:8px;background:var(--bg);color:var(--text)"><button class="btn-primary" onclick="pullOllamaModel()">${T('ollama.pull')}</button><button class="btn-secondary" onclick="renderOllamaExt(document.getElementById('ext-detail-body'))">🔄</button></div>`;
    el.innerHTML = h;
}
async function pullOllamaModel() { const m = document.getElementById('ollama-pull-input')?.value.trim(); if(!m) return alert('Enter model name.'); alert(`Pulling "${m}"...`); const r = await apiPost('/api/v1/ollama/pull',{model:m}); if(r&&!r.error) { alert('Done!'); renderOllamaExt(document.getElementById('ext-detail-body')); } else alert('Failed: '+(r?.error||'?')); }
async function removeOllamaModel(name) { if(!confirm(`Remove "${name}"?`)) return; await apiDelete('/api/v1/ollama/models',{name}); renderOllamaExt(document.getElementById('ext-detail-body')); }

// ── Multi-Agents Ext ──
async function renderMultiAgentsExt(el) {
    const [td, ld] = await Promise.all([apiGet('/api/v1/multi-agents/teams'), apiGet('/api/v1/multi-agents/log')]);
    const teams = td?.teams || [];
    const log = ld?.log || [];
    let h = `<div style="margin-bottom:16px"><button class="btn-primary" onclick="showCreateTeamPrompt()">+ Create Team</button></div>`;
    h += '<h3 style="color:var(--cyan);margin-bottom:12px">👥 Teams</h3>';
    if (teams.length > 0) {
        h += '<div class="table-container"><table class="data-table"><thead><tr><th>Team</th><th>Strategy</th><th>Agents</th><th>Actions</th></tr></thead><tbody>';
        teams.forEach(t => { const si = t.strategy==='sequential'?'📋':t.strategy==='parallel'?'⚡':'👑'; h += `<tr><td style="font-weight:600;color:var(--cyan)">${esc(t.name)}</td><td>${si} ${esc(t.strategy)}</td><td>${t.agent_ids?.length||0}</td><td><button class="btn-danger" onclick="deleteTeam('${esc(t.id)}')">✕</button></td></tr>`; });
        h += '</tbody></table></div>';
    } else h += '<p class="text-muted">No teams.</p>';
    h += '<h3 style="color:var(--cyan);margin:24px 0 12px">📋 Delegation Log</h3>';
    if (log.length > 0) {
        h += '<div class="table-container"><table class="data-table"><thead><tr><th>Time</th><th>Team</th><th>Strategy</th><th>Task</th></tr></thead><tbody>';
        log.slice(-10).reverse().forEach(e => { h += `<tr><td style="color:var(--text-muted)">${esc((e.timestamp||'').slice(0,19))}</td><td style="color:var(--cyan)">${esc(e.team_name)}</td><td>${esc(e.strategy)}</td><td>${esc((e.task||'').slice(0,60))}</td></tr>`; });
        h += '</tbody></table></div>';
    } else h += '<p class="text-muted">No history.</p>';
    el.innerHTML = h;
}
async function showCreateTeamPrompt() { const n = prompt('Team name:'); if(!n) return; const a = prompt('Agent IDs (comma-separated):'); if(!a) return; const s = prompt('Strategy (sequential/parallel/lead-delegate):','sequential')||'sequential'; const r = await apiPost('/api/v1/multi-agents/teams',{name:n,agent_ids:a.split(',').map(s=>s.trim()),strategy:s}); if(r&&r.status==='created') { alert('Created!'); renderMultiAgentsExt(document.getElementById('ext-detail-body')); } }
async function deleteTeam(id) { if(!confirm('Delete team?')) return; await apiDelete('/api/v1/multi-agents/teams/'+id); renderMultiAgentsExt(document.getElementById('ext-detail-body')); }

// ═══ Install Extension ═══
function showInstallExtension() { document.getElementById('modal-install-ext').classList.remove('hidden'); }
async function installExtension() { const u = document.getElementById('install-ext-url').value.trim(); if(!u) return alert('URL required.'); const btn = document.getElementById('btn-install-ext'); btn.disabled=true; btn.textContent='⏳ Installing...'; const r = await apiPost('/api/v1/extensions/install',{git_url:u}); btn.disabled=false; btn.textContent='🚀 Install'; if(r&&r.status==='success') { closeModal('modal-install-ext'); loadExtensions(); alert('Installed!'); } else alert('Failed: '+(r?.message||'?')); }

// ═══════════════════════════════════════════════════════════
// ═══ API MANAGER PAGE ═══
// ═══════════════════════════════════════════════════════════
async function loadApiManagerPage() {
    document.getElementById('api-base-display').textContent = API;
    const el = document.getElementById('api-endpoints-list');
    // Fetch OpenAPI spec
    try {
        const resp = await fetch(API + '/openapi.json');
        const spec = await resp.json();
        const paths = spec.paths || {};
        let rows = '';
        const methodColors = { get:'var(--green)', post:'var(--blue)', put:'var(--orange)', delete:'var(--red)', patch:'var(--purple)' };
        Object.entries(paths).forEach(([path, methods]) => {
            Object.entries(methods).forEach(([method, info]) => {
                if (['get','post','put','delete','patch'].includes(method)) {
                    rows += `<tr><td><span style="display:inline-block;padding:2px 8px;border-radius:4px;font-size:.7rem;font-weight:700;text-transform:uppercase;background:${methodColors[method]||'var(--text-muted)'}22;color:${methodColors[method]||'var(--text-muted)'}">${method}</span></td><td style="font-family:'JetBrains Mono',monospace;font-size:.82rem">${esc(path)}</td><td style="color:var(--text2);font-size:.82rem">${esc(info.summary||info.description||'')}</td><td>${(info.tags||[]).map(t=>`<span class="tag">${esc(t)}</span>`).join(' ')}</td></tr>`;
                }
            });
        });
        el.innerHTML = `<table class="data-table"><thead><tr><th style="width:70px">Method</th><th>Path</th><th>Description</th><th>Tags</th></tr></thead><tbody>${rows}</tbody></table>`;
    } catch(e) {
        el.innerHTML = '<p class="text-muted" style="padding:20px">Cannot load API spec. Check if server is running.</p>';
    }
}

// ═══ API Key Management ═══
function showAddApiKey() { document.getElementById('modal-add-key').classList.remove('hidden'); }
function prefillAddKey(provider) { document.getElementById('add-key-provider').value = provider; document.getElementById('add-key-value').value = ''; document.getElementById('add-key-label').value = 'default'; document.getElementById('modal-add-key').classList.remove('hidden'); }
async function addApiKey() { const prov=document.getElementById('add-key-provider').value, key=document.getElementById('add-key-value').value.trim(), label=document.getElementById('add-key-label').value.trim()||'default'; if(!key) return alert('Key required.'); const r = await apiPost('/api/v1/cloud-api/keys',{provider:prov,api_key:key,label}); if(r&&r.status==='success') { closeModal('modal-add-key'); renderCloudApiExt(document.getElementById('ext-detail-body')); alert('Added!'); } else alert('Failed.'); }
async function testApiKey(provider) { alert(`Testing ${provider}...`); const r = await apiPost('/api/v1/cloud-api/keys/test',{provider}); if(r) alert(`${r.status==='success'?'✅':'❌'} ${r.message||r.status}`); }

// ═══════════════════════════════════════════════════════════
// ═══ AGENT CRUD (unchanged logic) ═══
// ═══════════════════════════════════════════════════════════
let currentChatAgentId = null;

async function openChatAgent(id, name) { currentChatAgentId = id; document.getElementById('chat-agent-name').textContent = name; document.getElementById('chat-input').value = ''; document.getElementById('modal-chat').classList.remove('hidden'); const d = await apiGet('/api/v1/agents/'+id); renderChatHistory(d?.history_log||[]); }
function renderChatHistory(history) { const c = document.getElementById('chat-history'); if(!history.length) { c.innerHTML='<p class="text-muted" style="text-align:center">Say hello!</p>'; return; } c.innerHTML = history.map(m => { const u=m.role==='user'; return `<div style="display:flex;justify-content:${u?'flex-end':'flex-start'};width:100%"><div style="background:${u?'var(--blue)':'var(--bg3)'};color:${u?'#fff':'var(--text)'};padding:10px 14px;border-radius:8px;max-width:80%;white-space:pre-wrap;font-size:.9rem">${esc(m.content)}${m.skill_used?`<div style="font-size:.75rem;color:#10b981;margin-top:4px">⚡ ${esc(m.skill_used)}</div>`:''}</div></div>`; }).join(''); c.scrollTop=c.scrollHeight; }
async function sendChatMessage() { if(!currentChatAgentId) return; const inp=document.getElementById('chat-input'); const msg=inp.value.trim(); if(!msg) return; inp.value=''; const c=document.getElementById('chat-history'); if(c.innerHTML.includes('Say hello')) c.innerHTML=''; c.innerHTML+=`<div style="display:flex;justify-content:flex-end;width:100%;margin-top:12px"><div style="background:var(--blue);color:#fff;padding:10px 14px;border-radius:8px;max-width:80%;white-space:pre-wrap;font-size:.9rem">${esc(msg)}</div></div><div id="chat-typing" style="display:flex;justify-content:flex-start;width:100%;margin-top:12px"><div style="background:var(--bg3);color:var(--text-muted);padding:10px 14px;border-radius:8px;font-size:.9rem">Typing...</div></div>`; c.scrollTop=c.scrollHeight; const r=await apiPost('/api/v1/agents/'+currentChatAgentId+'/chat',{message:msg}); document.getElementById('chat-typing')?.remove(); if(r) renderChatHistory(r.history); }

function showCreateAgent() { document.getElementById('agent-modal-title').textContent='Create Agent'; document.getElementById('agent-id').value=''; document.getElementById('agent-name').value=''; document.getElementById('agent-desc').value=''; document.getElementById('agent-prompt').value='You are a helpful AI assistant.'; document.getElementById('agent-model').value='qwen:latest'; document.getElementById('agent-browser-model').value='qwen:latest'; document.getElementById('agent-avatar-type').value='bot'; document.getElementById('agent-avatar-color').value='blue'; document.getElementById('agent-interests').value=''; document.getElementById('agent-behavior').value='{\n  "dailyRoutine": [],\n  "workHabits": {}\n}'; document.getElementById('agent-proxy-mode').value='none'; document.getElementById('agent-proxy').value=''; onProxyModeChange(); document.getElementById('agent-schedule-enable').checked=false; document.getElementById('agent-timezone').value='Asia/Ho_Chi_Minh'; document.getElementById('agent-schedule-repeat').value='daily'; document.getElementById('agent-schedule-interval').value='60'; document.getElementById('agent-schedule-start').value='08:00'; document.getElementById('agent-schedule-end').value='22:00'; document.getElementById('agent-schedule-max-runs').value='10'; document.querySelectorAll('.agent-day-cb').forEach((cb,i)=>cb.checked=i<5); onScheduleRepeatChange(); document.getElementById('agent-scraping-enable').checked=false; document.getElementById('agent-scraper-limit').value='10000'; document.getElementById('agent-scraper-format').value='json'; document.getElementById('agent-tg-token').value=''; document.getElementById('agent-tg-chat').value=''; document.getElementById('agent-ms-token').value=''; document.getElementById('agent-ms-page').value=''; document.getElementById('agent-ms-php').value=''; document.getElementById('agent-ms-skill').value=''; populateAgentProfiles([]); populateAgentSkills([]); document.querySelector('.agent-tab-btn[data-atab="identity"]').click(); document.getElementById('modal-agent').classList.remove('hidden'); }

async function openEditAgent(id) { const d=await apiGet('/api/v1/agents/'+id); if(!d) return alert('Failed'); document.getElementById('agent-modal-title').textContent='Edit: '+d.name; document.getElementById('agent-id').value=d.id; document.getElementById('agent-name').value=d.name||''; document.getElementById('agent-desc').value=d.description||''; document.getElementById('agent-prompt').value=d.system_prompt||''; document.getElementById('agent-model').value=d.model||'qwen:latest'; document.getElementById('agent-browser-model').value=d.browser_ai_model||'qwen:latest'; document.getElementById('agent-avatar-type').value=d.avatar_type||'bot'; document.getElementById('agent-avatar-color').value=d.avatar_color||'blue'; const p=d.persona||{}; document.getElementById('agent-interests').value=(p.interests||[]).join(', '); document.getElementById('agent-behavior').value=JSON.stringify({dailyRoutine:(d.routine||{}).dailyRoutine||[],workHabits:(d.routine||{}).workHabits||{}},null,2); const pp=d.proxy_provider||{mode:'none'}; document.getElementById('agent-proxy-mode').value=pp.mode||'none'; document.getElementById('agent-proxy').value=d.proxy_config||''; onProxyModeChange(); const sc=d.schedule||{}; document.getElementById('agent-schedule-enable').checked=sc.enabled||false; document.getElementById('agent-timezone').value=d.timezone||'Asia/Ho_Chi_Minh'; document.getElementById('agent-schedule-repeat').value=sc.repeat||'daily'; document.getElementById('agent-schedule-interval').value=sc.interval||60; document.getElementById('agent-schedule-start').value=sc.start_time||'08:00'; document.getElementById('agent-schedule-end').value=sc.end_time||'22:00'; document.getElementById('agent-schedule-max-runs').value=sc.max_runs||10; document.querySelectorAll('.agent-day-cb').forEach(cb=>cb.checked=(sc.active_days||['mon','tue','wed','thu','fri']).includes(cb.value)); onScheduleRepeatChange(); document.getElementById('agent-scraping-enable').checked=d.enable_scraping||false; document.getElementById('agent-scraper-limit').value=d.scraper_text_limit||10000; document.getElementById('agent-scraper-format').value=d.script_output_format||'json'; document.getElementById('agent-tg-token').value=d.telegram_token||''; document.getElementById('agent-tg-chat').value=d.telegram_chat_id||''; document.getElementById('agent-ms-token').value=d.messenger_token||''; document.getElementById('agent-ms-page').value=d.messenger_page_id||''; document.getElementById('agent-ms-php').value=d.messenger_php_url||''; document.getElementById('agent-ms-skill').value=d.direct_trigger_skill_id||''; await populateAgentProfiles(d.allowed_profiles||[]); await populateAgentSkills(d.allowed_skills||[]); document.querySelector('.agent-tab-btn[data-atab="identity"]').click(); document.getElementById('modal-agent').classList.remove('hidden'); }

async function populateAgentProfiles(allowed) { const d=await apiGet('/api/v1/browser/profiles'); const c=document.getElementById('agent-profiles-list'); if(!d?.profiles?.length) { c.innerHTML='<p class="text-muted">No profiles.</p>'; return; } c.innerHTML=d.profiles.map(p=>`<label class="checkbox-item"><input type="checkbox" value="${esc(p.name)}" class="agent-profile-cb" ${allowed.includes(p.name)?'checked':''}>${esc(p.name)}</label>`).join(''); }
async function populateAgentSkills(allowed) { const d=await apiGet('/api/v1/skills'); const c=document.getElementById('agent-skills-list'); if(!d?.skills?.length) { c.innerHTML='<p class="text-muted">No skills.</p>'; return; } c.innerHTML=d.skills.map(s=>`<label class="checkbox-item"><input type="checkbox" value="${s.id}" class="agent-skill-cb" ${allowed.includes(s.id)?'checked':''}>${esc(s.name)} <span class="tag" style="margin-left:auto">${esc(s.type)}</span></label>`).join(''); }

function closeModal(id) { document.getElementById(id).classList.add('hidden'); }
function onProxyModeChange() { const m=document.getElementById('agent-proxy-mode').value; document.getElementById('proxy-static-group').style.display=m==='static'?'block':'none'; document.getElementById('proxy-dynamic-group').style.display=m==='dynamic'?'block':'none'; }
function onScheduleRepeatChange() { document.getElementById('schedule-interval-group').style.display=document.getElementById('agent-schedule-repeat').value==='interval'?'block':'none'; }
document.getElementById('agent-schedule-repeat')?.addEventListener('change', onScheduleRepeatChange);

async function saveAgent() { const name=document.getElementById('agent-name').value.trim(); if(!name) return alert('Name required'); const id=document.getElementById('agent-id').value; const interests=document.getElementById('agent-interests').value.split(',').map(s=>s.trim()).filter(s=>s); let routine={}; try { const v=document.getElementById('agent-behavior').value; if(v) routine=JSON.parse(v); } catch(e) { return alert('Invalid JSON: '+e.message); } const pm=document.getElementById('agent-proxy-mode').value; const pp={mode:pm}; if(pm==='dynamic') { pp.api_url=document.getElementById('agent-proxy-api')?.value||''; pp.api_key=document.getElementById('agent-proxy-api-key')?.value||''; pp.location=document.getElementById('agent-proxy-location')?.value||''; } const payload = { name, description:document.getElementById('agent-desc').value, system_prompt:document.getElementById('agent-prompt').value, model:document.getElementById('agent-model').value, browser_ai_model:document.getElementById('agent-browser-model').value, avatar_type:document.getElementById('agent-avatar-type').value, avatar_color:document.getElementById('agent-avatar-color').value, persona:{interests}, routine, proxy_config:pm==='static'?document.getElementById('agent-proxy').value:'', proxy_provider:pp, timezone:document.getElementById('agent-timezone').value, schedule:{ enabled:document.getElementById('agent-schedule-enable').checked, repeat:document.getElementById('agent-schedule-repeat').value, interval:parseInt(document.getElementById('agent-schedule-interval').value)||60, active_days:Array.from(document.querySelectorAll('.agent-day-cb:checked')).map(cb=>cb.value), start_time:document.getElementById('agent-schedule-start').value, end_time:document.getElementById('agent-schedule-end').value, max_runs:parseInt(document.getElementById('agent-schedule-max-runs').value)||10 }, enable_scraping:document.getElementById('agent-scraping-enable').checked, scraper_text_limit:parseInt(document.getElementById('agent-scraper-limit').value)||10000, script_output_format:document.getElementById('agent-scraper-format').value, telegram_token:document.getElementById('agent-tg-token').value, telegram_chat_id:document.getElementById('agent-tg-chat').value, messenger_token:document.getElementById('agent-ms-token').value, messenger_page_id:document.getElementById('agent-ms-page').value, messenger_php_url:document.getElementById('agent-ms-php').value, direct_trigger_skill_id:document.getElementById('agent-ms-skill').value, allowed_profiles:Array.from(document.querySelectorAll('.agent-profile-cb:checked')).map(cb=>cb.value), allowed_skills:Array.from(document.querySelectorAll('.agent-skill-cb:checked')).map(cb=>cb.value) }; if(id) await apiPut('/api/v1/agents/'+id,payload); else await apiPost('/api/v1/agents',payload); closeModal('modal-agent'); renderAgentsExt(document.getElementById('ext-detail-body')); }
async function deleteAgent(id) { if(!confirm('Delete agent?')) return; await apiDelete('/api/v1/agents/'+id); }

// ═══ Generate Agent ═══
const AI_PROVIDERS = { "ollama":{models:["deepseek-r1:latest","llama3.2","mistral-nemo"],needs_api:false}, "gemini":{models:["gemini-2.5-flash","gemini-2.0-flash","gemini-2.5-pro"],needs_api:true}, "chatgpt":{models:["gpt-4o","gpt-4o-mini","gpt-4-turbo"],needs_api:true}, "claude":{models:["claude-sonnet-4-20250514","claude-3-5-haiku-20241022"],needs_api:true}, "grok":{models:["grok-3","grok-3-mini","grok-2"],needs_api:true} };
function showGenerateAgent() { document.getElementById('agent-gen-name').value=''; document.getElementById('agent-gen-prefix').value=''; document.getElementById('agent-gen-desc').value=''; document.getElementById('agent-gen-provider').value='ollama'; document.getElementById('agent-gen-accounts').value=''; document.getElementById('agent-gen-preview').value=''; document.getElementById('agent-gen-status').textContent=''; document.getElementById('btn-apply-ai').style.display='none'; onGenProviderChange(); const ni=document.getElementById('agent-gen-name'); const nn=ni.cloneNode(true); ni.parentNode.replaceChild(nn,ni); nn.addEventListener('input',e=>{ document.getElementById('agent-gen-prefix').value=e.target.value.toLowerCase().replace(/[^a-z0-9]+/g,'_').replace(/(^_|_$)/g,''); }); document.getElementById('modal-generate-agent').classList.remove('hidden'); }
function onGenProviderChange() { const p=document.getElementById('agent-gen-provider').value; const i=AI_PROVIDERS[p]||AI_PROVIDERS.ollama; document.getElementById('agent-gen-model').innerHTML=i.models.map(m=>`<option value="${m}">${m}</option>`).join(''); document.getElementById('agent-gen-apikey-group').style.display=i.needs_api?'block':'none'; }
async function generateAgentJSON() { const name=document.getElementById('agent-gen-name').value.trim(), desc=document.getElementById('agent-gen-desc').value.trim(); if(!name||!desc) return alert('Name & Description required!'); const btn=document.getElementById('btn-generate-ai'); btn.disabled=true; document.getElementById('btn-apply-ai').style.display='none'; const prov=document.getElementById('agent-gen-provider').value, model=document.getElementById('agent-gen-model').value, api_key=document.getElementById('agent-gen-apikey')?.value?.trim()||''; const st=document.getElementById('agent-gen-status'); st.style.color='var(--text)'; st.textContent=`🤖 Calling ${prov}/${model}...`; document.getElementById('agent-gen-preview').value='Generating...'; try { const r=await apiPost('/api/v1/agents/generate',{name,description:desc,provider:prov,model,api_key}); if(r?.status==='success'&&r.data) { document.getElementById('agent-gen-preview').value=JSON.stringify(r.data,null,2); st.textContent='✅ Done!'; st.style.color='var(--green)'; document.getElementById('btn-apply-ai').style.display='inline-block'; window._lastGen=r.data; } else { st.textContent='❌ Failed'; st.style.color='var(--red)'; document.getElementById('agent-gen-preview').value=JSON.stringify(r,null,2); } } catch(e) { st.textContent='❌ Error'; st.style.color='var(--red)'; } btn.disabled=false; }
function applyGeneratedAgent() { if(!window._lastGen) return; showCreateAgent(); document.getElementById('agent-name').value=window._lastGen.name||''; document.getElementById('agent-desc').value=window._lastGen.description||''; const p=window._lastGen.persona||{}; document.getElementById('agent-interests').value=(p.interests||[]).join(', '); document.getElementById('agent-behavior').value=JSON.stringify({dailyRoutine:(window._lastGen.routine||{}).dailyRoutine||[],workHabits:(window._lastGen.routine||{}).workHabits||{}},null,2); closeModal('modal-generate-agent'); }

// ═══ Browser Profile CRUD ═══
async function showCreateProfile() { 
    // Check if any engine is installed first
    try {
        const r = await apiGet('/api/v1/browser/engine/versions');
        const versions = (r && r.success && r.versions) ? r.versions : [];
        const hasInstalled = versions.some(v => v.downloaded);
        
        if (!hasInstalled) {
            // No engine installed - show custom alert modal
            const latest = versions[0] || null;
            const latestName = latest ? latest.name : 'N/A';
            document.getElementById('engine-alert-latest').textContent = latestName;
            // Store latest version data for direct download
            window._latestEngineData = latest;
            document.getElementById('modal-engine-alert').classList.remove('hidden');
            return;
        }
    } catch(e) {
        console.warn('Failed to check engines:', e);
    }
    
    document.getElementById('modal-profile').classList.remove('hidden'); 
    // Fetch browser versions for dropdown
    const sel = document.getElementById('profile-version');
    if (sel && sel.options.length <= 1) {
        sel.innerHTML = '<option value="default">Loading...</option>';
        try {
            const r = await apiGet('/api/v1/browser/engine/versions');
            if (r && r.success && r.versions) {
                const installed = r.versions.filter(v => v.downloaded);
                sel.innerHTML = '<option value="default">Default Latest</option>' + 
                    installed.map(v => {
                        const name = typeof v === 'object' ? v.name : v;
                        return `<option value="${name}">${name} ✅</option>`;
                    }).join('');
            } else {
                sel.innerHTML = '<option value="default">Default Latest</option>';
            }
        } catch (e) {
            sel.innerHTML = '<option value="default">Default Latest</option>';
        }
    }
}
async function showBrowserEnginesModal() {
    document.getElementById('modal-engines').classList.remove('hidden');
    const container = document.getElementById('engines-list-container');
    container.innerHTML = '<p class="text-muted">Fetching available engines...</p>';
    
    try {
        const r = await apiGet('/api/v1/browser/engine/versions');
        if (r && r.success && r.versions) {
            let rows = r.versions.map(v => {
                const name = typeof v === 'object' ? v.name : v;
                const installed = (typeof v === 'object' && v.downloaded);
                const path = (typeof v === 'object' && v.path) ? v.path : '-';
                const isBas = (typeof v === 'object' && v.is_bas_app);
                const downloadUrl = (typeof v === 'object' && v.download_url) ? v.download_url : '';
                
                return `<tr>
                    <td style="font-weight:600;color:var(--cyan)">
                        ${esc(name)}
                        ${isBas ? '<span style="font-size:0.65rem;background:var(--purple);color:white;padding:1px 4px;border-radius:4px;margin-left:5px">BAS APP</span>' : ''}
                        ${v.is_private ? '<span style="font-size:0.65rem;background:var(--green);color:white;padding:1px 4px;border-radius:4px;margin-left:5px">PRIVATE</span>' : ''}
                    </td>
                    <td style="color:${installed ? 'var(--green)' : 'var(--red)'}">${installed ? '✅ Installed' : '❌ Missing'}</td>
                    <td style="font-size:0.75rem;color:var(--text-muted);word-break:break-all">${esc(path)}</td>
                    <td style="text-align:right">
                        ${installed ? '' : `<button class="btn-install" style="padding:2px 10px;font-size:0.8rem" onclick="installEngineVersionProgress('${esc(v.bas_version || name)}', '${esc(downloadUrl)}')">Install</button>`}
                    </td>
                </tr>`;
            }).join('');
            
            container.innerHTML = `<table class="data-table">
                <thead><tr><th>Version</th><th>Status</th><th>Path</th><th style="text-align:right">Action</th></tr></thead>
                <tbody>${rows}</tbody>
            </table>`;
            // Show warning if using fallback
            if (r.warning) {
                container.innerHTML = `<div style="background:rgba(255,165,0,0.1);border:1px solid var(--orange);border-radius:8px;padding:10px;margin-bottom:12px;font-size:0.85rem">⚠️ ${esc(r.warning)} — Showing fallback versions list.</div>` + container.innerHTML;
            }
        } else {
            const errMsg = r?.error || r?.message || 'Unknown error';
            const errDetail = r?.detail ? `<br><small style="color:var(--text-muted)">${esc(r.detail.slice(0,200))}</small>` : '';
            container.innerHTML = `<p class="text-muted">Failed to load engines: ${esc(errMsg)}${errDetail}</p><p style="margin-top:10px"><button class="btn-secondary" onclick="showBrowserEnginesModal()">🔄 Retry</button></p>`;
        }
    } catch (e) {
        container.innerHTML = `<p class="text-muted">Error: ${esc(e.message)}</p>`;
    }
}

let downloadCancelled = false;
let currentDownloadVersion = null;

async function cancelEngineDownload() {
    downloadCancelled = true;
    document.getElementById('download-overlay').classList.add('hidden');
    if (currentDownloadVersion) {
        await apiPost('/api/v1/browser/engine/cancel/' + currentDownloadVersion, {});
    }
}

async function downloadLatestEngineNow() {
    closeModal('modal-engine-alert');
    const data = window._latestEngineData;
    if (!data) {
        showBrowserEnginesModal();
        return;
    }
    const version = data.bas_version || data.name;
    const downloadUrl = data.download_url || '';
    installEngineVersionProgress(version, downloadUrl);
}

async function installEngineVersionProgress(version, downloadUrl = '') {
    currentDownloadVersion = version;
    const overlay = document.getElementById('download-overlay');
    const progressBar = document.getElementById('download-progress-bar');
    const percentText = document.getElementById('download-percent');
    const titleText = document.getElementById('download-title');
    
    titleText.textContent = `Installing ${version}...`;
    progressBar.style.width = '0%';
    percentText.textContent = '0%';
    overlay.classList.remove('hidden');
    
    try {
        // Start download (version = bas_version like 29.7.0)
        const start = await apiPost('/api/v1/browser/engine/download/' + version, {
            download_url: downloadUrl,
            bas_version: version
        });
        if (!start || start.error) {
            alert('Failed to start download: ' + (start?.error || 'Unknown error'));
            overlay.classList.add('hidden');
            return;
        }
        
        // Poll for progress
        let done = false;
        downloadCancelled = false;
        while (!done && !downloadCancelled) {
            await new Promise(r => setTimeout(r, 1000));
            const status = await apiGet('/api/v1/browser/engine/status/' + version);
            
            if (!status || status.error) {
                console.warn('Status check failed', status);
                continue;
            }
            
            if (status.percent !== undefined) {
                const p = Math.min(100, Math.max(0, status.percent));
                progressBar.style.width = p + '%';
                percentText.textContent = Math.round(p) + '%';
            }
            
            if (status.status === 'completed') {
                done = true;
                progressBar.style.width = '100%';
                percentText.textContent = '100%';
                titleText.textContent = 'Installation Complete!';
                setTimeout(() => {
                    overlay.classList.add('hidden');
                    showBrowserEnginesModal(); // refresh list
                }, 1000);
            } else if (status.status === 'error') {
                done = true;
                alert('Installation failed: ' + (status.error || 'Unknown error'));
                overlay.classList.add('hidden');
            }
        }
    } catch (e) {
        alert('Request failed: ' + e.message);
        overlay.classList.add('hidden');
    }
}
async function createProfile() { const btn=document.getElementById('btn-create-profile-submit'); const name=document.getElementById('profile-name').value.trim(); if(!name) return; btn.disabled=true; btn.textContent='Creating...'; await apiPost('/api/v1/browser/profiles',{name,proxy:document.getElementById('profile-proxy').value,tags:[document.getElementById('profile-os').value,document.getElementById('profile-browser').value],browser_version:document.getElementById('profile-version')?.value}); btn.disabled=false; btn.textContent='Create & Fetch Fingerprint'; closeModal('modal-profile'); document.getElementById('profile-name').value=''; document.getElementById('profile-proxy').value=''; renderBrowserExt(document.getElementById('ext-detail-body')); }
async function launchProfile(name,btn) { if(btn){btn.disabled=true;btn.textContent='🚀...'} const r=await apiPost('/api/v1/browser/launch',{profile:name,manual:true}); if(r && !r.error && r.status !== 'error') { let n=0; const iv=setInterval(async()=>{await renderBrowserExt(document.getElementById('ext-detail-body'));if(++n>=3)clearInterval(iv)},2000); } else { if(btn){btn.disabled=false;btn.textContent='▶'} alert('Failed to launch: ' + (r?.error || r?.detail || 'Unknown error')); } }
async function stopProfile(name,btn) { if(btn){btn.disabled=true;btn.textContent='...'} await apiPost('/api/v1/browser/stop',{profile:name}); setTimeout(()=>renderBrowserExt(document.getElementById('ext-detail-body')),1000); }
async function deleteProfile(name) { if(!confirm('Delete '+name+'?')) return; await apiDelete('/api/v1/browser/profiles/'+name); }
function searchMarket() { const q=(document.getElementById('market-search')?.value||'').toLowerCase(); document.querySelectorAll('#market-list .card').forEach(c=>{ c.style.display=c.textContent.toLowerCase().includes(q)?'':'none'; }); }

// ═══ Settings ═══
function saveSettings() { const api=document.getElementById('set-api').value.trim(); if(api){localStorage.setItem('tubecli_api',api);location.reload();} }

// ═══ Version & Update ═══
async function loadVersionInfo() {
    const d = await apiGet('/api/v1/system/version');
    if (!d) return;
    document.getElementById('version-badge').textContent = '⚡ TubeCLI v' + (d.version || '?');
    document.getElementById('version-hash').textContent = d.git_hash ? ('#' + d.git_hash) : '';
    document.getElementById('version-branch').textContent = d.git_branch ? ('📌 ' + d.git_branch) : '';
    document.getElementById('update-status').textContent = '';
    document.getElementById('update-status').className = 'update-status';
}

async function checkForUpdate() {
    const btn = document.getElementById('btn-check-update');
    const st = document.getElementById('update-status');
    btn.disabled = true; btn.textContent = '🔍 Checking...';
    st.textContent = 'Fetching from GitHub...'; st.className = 'update-status';
    
    const d = await apiPost('/api/v1/system/check-update', {});
    btn.disabled = false; btn.textContent = '🔍 Check for Update';
    
    if (!d || d.error) {
        st.textContent = '❌ ' + (d?.error || 'Failed to check'); st.className = 'update-status';
        return;
    }
    if (d.has_update) {
        st.textContent = `🔔 Update available! ${d.commits_behind} new commit(s)`;
        st.className = 'update-status has-update';
        document.getElementById('btn-system-update').style.display = 'inline-block';
        // Show changelog
        if (d.changelog && d.changelog.length > 0) {
            document.getElementById('changelog-box').style.display = 'block';
            document.getElementById('changelog-list').innerHTML = d.changelog.map(c => `<li>${esc(c)}</li>`).join('');
        }
    } else {
        st.textContent = '✅ You are up to date!';
        st.className = 'update-status up-to-date';
        document.getElementById('btn-system-update').style.display = 'none';
        document.getElementById('changelog-box').style.display = 'none';
    }
}

async function performSystemUpdate() {
    const btn = document.getElementById('btn-system-update');
    const st = document.getElementById('update-status');
    if (!confirm('Update TubeCLI to latest version? The API server will need to restart after update.')) return;
    btn.disabled = true; btn.textContent = '⏳ Updating...';
    st.textContent = 'Pulling latest code from GitHub...'; st.className = 'update-status';
    
    const d = await apiPost('/api/v1/system/update', {});
    btn.disabled = false;
    
    if (d?.status === 'success') {
        st.innerHTML = `✅ Updated to v${esc(d.new_version)}! <strong>Please restart the API server.</strong>`;
        st.className = 'update-status has-update';
        btn.textContent = '✅ Done';
        btn.style.display = 'none';
        document.getElementById('changelog-box').style.display = 'none';
        // Show restart banner
        const card = document.getElementById('version-card');
        if (!document.getElementById('restart-banner')) {
            card.insertAdjacentHTML('afterend', '<div class="restart-banner" id="restart-banner">⚠️ Restart the API server to apply the update. Run: <code>tubecli api start</code></div>');
        }
    } else {
        st.textContent = '❌ Update failed: ' + (d?.error || 'Unknown error');
        st.className = 'update-status';
        btn.textContent = '⬆️ Update Now';
    }
}

// ═══ Extension Update (External) ═══
async function checkExtensionUpdate(name, btn) {
    btn.disabled = true; btn.textContent = '...';
    const d = await apiPost(`/api/v1/extensions/${name}/check-update`, {});
    if (d?.has_update) {
        btn.textContent = '⬆️ Update'; btn.disabled = false;
        btn.className = 'btn-ext-update';
        btn.onclick = () => updateExtension(name, btn);
    } else {
        btn.textContent = '✅'; btn.disabled = true;
        setTimeout(() => { btn.textContent = d?.message || 'Up to date'; }, 500);
    }
}

async function updateExtension(name, btn) {
    btn.disabled = true; btn.textContent = '⏳...';
    const d = await apiPost(`/api/v1/extensions/${name}/update`, {});
    if (d?.status === 'success') {
        btn.textContent = '✅ v' + (d.new_version || '?');
        alert(d.message || 'Updated! Restart API to apply.');
    } else {
        btn.textContent = '❌';
        alert('Update failed: ' + (d?.error || d?.detail || 'Unknown'));
        btn.disabled = false;
    }
}

// ═══ Sidebar Toggle ═══
function toggleSidebar() { document.getElementById('sidebar').classList.toggle('collapsed'); }

// ═══ Utility ═══
function esc(s) { if(!s) return ''; const d=document.createElement('div'); d.textContent=s; return d.innerHTML; }

// ═══ Connection Check ═══
async function checkConnection() { try { const r=await fetch(API+'/api/v1/health',{signal:AbortSignal.timeout(2000)}); if(r.ok) document.querySelector('.sidebar-footer').innerHTML='<span class="status-dot"></span> API Connected'; else throw 0; } catch { document.querySelector('.sidebar-footer').innerHTML='<span class="status-dot" style="background:var(--red)"></span> API Offline'; } }

// ═══ Init ═══
document.addEventListener('DOMContentLoaded', async () => {
    await loadI18nFromApi();
    checkConnection();
    loadDashboard();
    loadVersionInfo();
    const s=localStorage.getItem('tubecli_api');
    if(s) document.getElementById('set-api').value=s;
    if(document.getElementById('set-lang')) document.getElementById('set-lang').value = _lang;
});
