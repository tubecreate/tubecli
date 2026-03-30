/**
 * ZhiYing Dashboard — SPA Logic
 * Dashboard → Extensions → API Manager → Settings
 */
const API = localStorage.getItem('zhiying_api') || 'http://localhost:5295';

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
    { id:'agents', icon:'🤖', name:'nav.dashboard', desc:'ext.agents_desc', type:'core' },
    { id:'browser', icon:'🌐', name:'stat.profiles', desc:'ext.browser_desc', type:'core' },
    { id:'workflows', icon:'🔄', name:'stat.workflows', desc:'ext.workflows_desc', type:'core' },
    { id:'skills', icon:'⚡', name:'stat.skills', desc:'ext.skills_desc', type:'core' },
    { id:'market', icon:'🛍️', name:'Marketplace', desc:'ext.market_desc', type:'core' },
    { id:'cloud_api', icon:'☁️', name:'dash.cloud_api_keys', desc:'ext.cloud_api_desc', type:'extension' },
    { id:'ollama', icon:'🧠', name:'Ollama Manager', desc:'ext.ollama_desc', type:'extension' },
    { id:'multi_agents', icon:'👥', name:'Multi-Agents', desc:'ext.multi_agents_desc', type:'extension' },
    { id:'downloader', icon:'📥', name:'Douyin Downloader', desc:'Download TikTok & Douyin videos', type:'extension' },
    { id:'video_editor', icon:'🎬', name:'Video Editor', desc:'AI-powered Video Editor with Timeline & FFmpeg', type:'extension' },
];

async function loadExtensions() {
    const extensionData = await apiGet('/api/v1/extensions');
    const extensions = extensionData?.extensions || [];
    const extensionMap = {};
    extensions.forEach(p => { extensionMap[p.name] = p; });
    const grid = document.getElementById('extensions-grid');

    // Render built-in/known extensions from EXT_REGISTRY
    let cards = EXT_REGISTRY.map(ext => {
        const extension = extensionMap[ext.id];
        const version = extension?.version || '-';
        const isEnabled = extension ? extension.enabled : true;
        const isExternal = extension?.extension_type === 'external';
        const displayType = isExternal ? 'external' : ext.type;
        const tagClass = displayType === 'core' ? 'green' : 'blue';

        let footerHtml = `<span class="tag ${tagClass}">${displayType}</span>`;
        if (isExternal && extension) {
            footerHtml += `
                <button class="btn-sm ${isEnabled ? 'btn-danger' : 'btn-primary'}"
                    onclick="event.stopPropagation();toggleExternalExt('${esc(ext.id)}',${isEnabled})">
                    ${isEnabled ? 'Disable' : 'Enable'}
                </button>
                <button class="btn-sm" style="background:var(--red)"
                    onclick="event.stopPropagation();uninstallExternalExt('${esc(ext.id)}')">
                    Uninstall
                </button>`;
        }

        return `<div class="card ext-card" onclick="openExtDetail('${ext.id}')" style="${!isEnabled ? 'opacity:0.5' : ''}">
            <div class="card-icon">${ext.icon}</div>
            <h3>${esc(T(ext.name))}</h3>
            <p class="card-meta">v${esc(version)} · ${esc(displayType)}</p>
            <p class="card-desc">${esc(T(ext.desc))}</p>
            <div class="card-footer" style="margin-top:10px;gap:8px">${footerHtml}</div>
        </div>`;
    }).join('');

    // Also render external extensions not in EXT_REGISTRY (installed from market/git)
    extensions.forEach(ext => {
        const inRegistry = EXT_REGISTRY.some(e => e.id === ext.name);
        if (!inRegistry && ext.extension_type === 'external') {
            const isEnabled = ext.enabled;
            cards += `<div class="card ext-card" onclick="openExternalExtDetail('${esc(ext.name)}')" style="${!isEnabled ? 'opacity:0.5' : ''}">
                <div class="card-icon">${esc(ext.icon || '\ud83d\udce6')}</div>
                <h3>${esc(ext.name)}</h3>
                <p class="card-meta">v${esc(ext.version || '-')} · external</p>
                <p class="card-desc">${esc(ext.description || '')}</p>
                <div class="card-footer" style="margin-top:10px;gap:8px">
                    <span class="tag blue">external</span>
                    <button class="btn-sm ${isEnabled ? 'btn-danger' : 'btn-primary'}"
                        onclick="event.stopPropagation();toggleExternalExt('${esc(ext.name)}',${isEnabled})">
                        ${isEnabled ? 'Disable' : 'Enable'}
                    </button>
                    <button class="btn-sm" style="background:var(--red)"
                        onclick="event.stopPropagation();uninstallExternalExt('${esc(ext.name)}')">
                        Uninstall
                    </button>
                </div>
            </div>`;
        }
    });

    grid.innerHTML = cards;
}

async function toggleExternalExt(name, isEnabled) {
    const action = isEnabled ? 'disable' : 'enable';
    await apiPost(`/api/v1/extensions/${encodeURIComponent(name)}/${action}`, {});
    loadExtensions();
}

async function uninstallExternalExt(name) {
    if (!confirm(`Uninstall extension "${name}"?`)) return;
    const r = await apiDelete(`/api/v1/extensions/${encodeURIComponent(name)}/uninstall`);
    if (r && r.status === 'success') { closeExtDetail(); loadExtensions(); }
    else alert('Failed: ' + (r?.message || r?.detail || '?'));
}

async function openExternalExtDetail(name) {
    stopBrowserStatusPoller();
    const overlay = document.getElementById('ext-detail-overlay');
    const title = document.getElementById('ext-detail-title');
    const body = document.getElementById('ext-detail-body');
    title.textContent = '📦 ' + name;
    body.innerHTML = `<p class="text-muted">${T('chat.loading')}</p>`;
    overlay.classList.remove('hidden');

    const info = await apiGet(`/api/v1/extensions/${encodeURIComponent(name)}/info`);
    if (!info || info.error) { body.innerHTML = `<p class="text-muted">Failed to load extension info.</p>`; return; }

    const manifest = info.manifest || {};
    const isEnabled = info.enabled;
    const icon = manifest.icon || '📦';
    const apiPrefix = manifest.api_prefix || '';
    title.textContent = icon + ' ' + (manifest.name || name);

    // Determine if this extension has a download-like API
    const hasDownload = apiPrefix && (apiPrefix.includes('ytdl') || apiPrefix.includes('download'));

    // Build code examples based on api_prefix
    const baseUrl = API;
    const exampleUrl = hasDownload ? `${apiPrefix}/download` : `${apiPrefix}`;
    const exampleBody = hasDownload
        ? JSON.stringify({url: 'https://youtube.com/watch?v=dQw4w9WgXcQ', format: 'mp4', quality: '720p'}, null, 2)
        : JSON.stringify({}, null, 2);

    const examples = {
        curl: `curl -X POST "${baseUrl}${exampleUrl}" \\
  -H "Content-Type: application/json" \\
  -d '${exampleBody.replace(/\n/g,'\\n')}'`,
        python: `import requests

response = requests.post(
    "${baseUrl}${exampleUrl}",
    json=${exampleBody}
)
print(response.json())`,
        javascript: `const response = await fetch("${baseUrl}${exampleUrl}", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(${exampleBody})
});
const data = await response.json();
console.log(data);`,
    };

    body.innerHTML = `
    <!-- Header info row -->
    <div class="ext-info-grid" style="margin-bottom:20px">
        <div class="ext-info-card"><div class="info-value">${esc(info.version||'-')}</div><div class="info-label">Version</div></div>
        <div class="ext-info-card"><div class="info-value">${icon}</div><div class="info-label">external</div></div>
        <div class="ext-info-card"><div class="info-value">${info.has_nodes?'✅':'—'}</div><div class="info-label">Nodes</div></div>
        <div class="ext-info-card"><div class="info-value">${info.has_skill_md?'✅':'—'}</div><div class="info-label">Skill.md</div></div>
    </div>
    <p style="color:var(--text-muted);margin-bottom:20px">${esc(info.description||'')}</p>

    <!-- Tab Chips -->
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:20px" id="ext-tab-chips">
        ${hasDownload?`<button class="ext-chip active" style="pointer-events:none">📥 Download Mode</button>`:''}
        <button class="ext-chip" onclick="document.getElementById('ext-api-dialog').showModal()">⚡ API</button>
        ${info.has_skill_md?`<button class="ext-chip" onclick="document.getElementById('ext-skill-dialog').showModal()">📖 SKILL.md</button>`:''}
        <button class="ext-chip" onclick="document.getElementById('ext-info-dialog').showModal()">ℹ️ Info</button>
        ${hasDownload?`<button class="ext-chip" onclick="document.getElementById('ytdl-settings-dialog').showModal()">⚙️ Settings</button>`:''}
    </div>

    <!-- TAB: Download -->
    ${hasDownload?`<div id="ext-tab-download" class="ext-tab-panel">
        <div style="background:var(--bg3);border-radius:12px;padding:20px">
            <label style="display:block;margin-bottom:8px;font-weight:600;color:var(--cyan)">🔗 Video / Audio URLs (Multi-row)</label>
            <textarea id="ytdl-url" rows="4" placeholder="https://youtube.com/...\nhttps://tiktok.com/...\nNhập nhiều URL, mỗi link một dòng. Hệ thống tự xếp hàng chờ tải (tối đa 5 luồng cùng lúc)."
                style="width:100%;padding:12px 16px;border:1px solid var(--border);border-radius:8px;background:var(--bg);color:var(--text);font-size:.95rem;margin-bottom:12px;font-family:inherit;resize:vertical"></textarea>

            <button class="btn-primary" id="ytdl-btn" onclick="runYtdlDownload()"
                style="width:100%;padding:14px;font-size:1rem;font-weight:700;border-radius:10px">
                📥 Start Download
            </button>

            <div id="ytdl-queue-container" style="margin-top:16px;display:flex;flex-direction:column;gap:10px"></div>
        </div>
    </div>`:''}

    <!-- Dialog: Settings -->
    ${hasDownload?`<dialog id="ytdl-settings-dialog" style="margin:auto;top:50%;left:50%;transform:translate(-50%,-50%);padding:0;border:none;border-radius:12px;background:transparent;max-width:500px;width:90%;color:var(--text)">
        <div style="background:var(--bg3);border-radius:12px;padding:20px;border:1px solid var(--border);box-shadow:0 10px 30px rgba(0,0,0,0.5)">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
                <h3 style="margin:0;color:var(--text)">⚙️ Cấu hình Download</h3>
                <button onclick="document.getElementById('ytdl-settings-dialog').close()" style="background:none;border:none;color:var(--text);font-size:1.2rem;cursor:pointer">✕</button>
            </div>
            
            <label style="display:block;margin-bottom:8px;font-weight:600;color:var(--text)">🏷️ Filename Template</label>
            <input id="set-ytdl-filename" type="text" placeholder="%(title)s.%(ext)s" value="${localStorage.getItem('ytdl_filename')||'%(title)s.%(ext)s'}"
                style="width:100%;padding:12px 16px;border:1px solid var(--border);border-radius:8px;background:var(--bg);color:var(--text);font-size:.95rem;margin-bottom:12px">
            <div style="font-size:0.8rem;color:var(--text-muted);margin-top:-8px;margin-bottom:16px">Biến hỗ trợ: %(title)s, %(ext)s, %(id)s, %(uploader)s, %(resolution)s...</div>

            <label style="display:block;margin-bottom:8px;font-weight:600;color:var(--text)">📁 Save Directory</label>
            <input id="set-ytdl-save-dir" type="text" placeholder="Để trống = Mặc định" value="${localStorage.getItem('ytdl_save_dir')||''}"
                style="width:100%;padding:12px 16px;border:1px solid var(--border);border-radius:8px;background:var(--bg);color:var(--text);font-size:.95rem;margin-bottom:16px">

            <div style="display:flex;gap:12px;margin-bottom:16px;flex-wrap:wrap">
                <div style="flex:1;min-width:120px">
                    <label style="display:block;margin-bottom:6px;font-size:.8rem;color:var(--text-muted)">Format</label>
                    <select id="set-ytdl-format" style="width:100%;padding:10px;border:1px solid var(--border);border-radius:8px;background:var(--bg);color:var(--text)">
                        <option value="mp4" ${localStorage.getItem('ytdl_format')==='mp4'?'selected':''}>🎬 MP4 (Video)</option>
                        <option value="mp3" ${localStorage.getItem('ytdl_format')==='mp3'?'selected':''}>🎵 MP3 (Audio)</option>
                        <option value="webm" ${localStorage.getItem('ytdl_format')==='webm'?'selected':''}>🎞️ WebM</option>
                    </select>
                </div>
                <div style="flex:1;min-width:120px">
                    <label style="display:block;margin-bottom:6px;font-size:.8rem;color:var(--text-muted)">Quality</label>
                    <select id="set-ytdl-quality" style="width:100%;padding:10px;border:1px solid var(--border);border-radius:8px;background:var(--bg);color:var(--text)">
                        <option value="720p" ${(localStorage.getItem('ytdl_quality')||'720p')==='720p'?'selected':''}>720p (HD)</option>
                        <option value="1080p" ${localStorage.getItem('ytdl_quality')==='1080p'?'selected':''}>1080p (Full HD)</option>
                        <option value="480p" ${localStorage.getItem('ytdl_quality')==='480p'?'selected':''}>480p</option>
                        <option value="360p" ${localStorage.getItem('ytdl_quality')==='360p'?'selected':''}>360p</option>
                        <option value="best" ${localStorage.getItem('ytdl_quality')==='best'?'selected':''}>Best quality</option>
                    </select>
                </div>
            </div>

            <button class="btn-primary" onclick="window.saveYtdlSettings()"
                style="width:100%;padding:14px;font-size:1rem;font-weight:700;border-radius:10px;background:var(--cyan);color:#000">
                💾 Save Settings
            </button>
        </div>
    </dialog>`:''}

    <!-- Dialog: API Examples -->
    <dialog id="ext-api-dialog" style="margin:auto;top:50%;left:50%;transform:translate(-50%,-50%);padding:0;border:none;border-radius:12px;background:transparent;max-width:600px;width:90%;color:var(--text)">
        <div style="background:var(--bg3);border-radius:12px;padding:20px;border:1px solid var(--border);box-shadow:0 10px 30px rgba(0,0,0,0.5)">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
                <h3 style="margin:0;color:var(--text)">⚡ API Examples</h3>
                <button onclick="document.getElementById('ext-api-dialog').close()" style="background:none;border:none;color:var(--text);font-size:1.2rem;cursor:pointer">✕</button>
            </div>
            <div style="display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap">
                <button class="ext-chip active" onclick="switchCodeLang('curl',this)">🖥️ cURL</button>
                <button class="ext-chip" onclick="switchCodeLang('python',this)">🐍 Python</button>
                <button class="ext-chip" onclick="switchCodeLang('javascript',this)">🌐 JavaScript</button>
            </div>
            <div style="position:relative">
                <button onclick="copyExtCode()" style="position:absolute;top:8px;right:8px;z-index:1;padding:4px 10px;font-size:.75rem;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);cursor:pointer">📋 Copy</button>
                <pre id="ext-code-block" style="background:var(--bg);padding:16px;border-radius:10px;font-size:.82rem;overflow:auto;max-height:50vh;white-space:pre;tab-size:2;color:var(--text)">${esc(examples.curl)}</pre>
            </div>
            ${apiPrefix?`<p style="margin-top:12px;font-size:.8rem;color:var(--text-muted)">API Base: <code>${esc(baseUrl)}${esc(apiPrefix)}</code></p>`:''}
        </div>
    </dialog>

    <!-- Dialog: SKILL.md -->
    ${info.has_skill_md&&info.skill_md_content?`<dialog id="ext-skill-dialog" style="margin:auto;top:50%;left:50%;transform:translate(-50%,-50%);padding:0;border:none;border-radius:12px;background:transparent;max-width:800px;width:95%;color:var(--text)">
        <div style="background:var(--bg3);border-radius:12px;padding:20px;border:1px solid var(--border);box-shadow:0 10px 30px rgba(0,0,0,0.5)">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
                <h3 style="margin:0;color:var(--text)">📖 SKILL.md</h3>
                <button onclick="document.getElementById('ext-skill-dialog').close()" style="background:none;border:none;color:var(--text);font-size:1.2rem;cursor:pointer">✕</button>
            </div>
            <pre style="background:var(--bg);padding:16px;border-radius:10px;font-size:.82rem;overflow:auto;max-height:60vh;white-space:pre-wrap;color:var(--text)">${esc(info.skill_md_content)}</pre>
        </div>
    </dialog>`:''}

    <!-- Dialog: Info -->
    <dialog id="ext-info-dialog" style="margin:auto;top:50%;left:50%;transform:translate(-50%,-50%);padding:0;border:none;border-radius:12px;background:transparent;max-width:400px;width:90%;color:var(--text)">
        <div style="background:var(--bg3);border-radius:12px;padding:20px;border:1px solid var(--border);box-shadow:0 10px 30px rgba(0,0,0,0.5)">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
                <h3 style="margin:0;color:var(--text)">ℹ️ Info</h3>
                <button onclick="document.getElementById('ext-info-dialog').close()" style="background:none;border:none;color:var(--text);font-size:1.2rem;cursor:pointer">✕</button>
            </div>
            ${info.author?`<p style="margin-bottom:8px"><strong>Author:</strong> ${esc(info.author)}</p>`:''}
            ${apiPrefix?`<p style="margin-bottom:8px"><strong>API Prefix:</strong> <code>${esc(apiPrefix)}</code></p>`:''}
            ${(info.nodes||[]).length>0?`<p style="margin-bottom:8px"><strong>Nodes:</strong> ${info.nodes.map(n=>`<span class="tag">${esc(n)}</span>`).join(' ')}</p>`:''}
            ${(manifest.dependencies||[]).length>0?`<p style="margin-bottom:8px"><strong>Dependencies:</strong> ${manifest.dependencies.map(d=>`<code>${esc(d)}</code>`).join(', ')}</p>`:''}
            ${manifest.homepage?`<p style="margin-bottom:8px"><strong>Homepage:</strong> <a href="${esc(manifest.homepage)}" target="_blank">${esc(manifest.homepage)}</a></p>`:''}
        </div>
    </dialog>

    <!-- Footer buttons -->
    <div style="margin-top:24px;padding-top:16px;border-top:1px solid var(--border);display:flex;gap:10px">
        <button class="btn-primary ${isEnabled?'btn-danger':''}" onclick="toggleExternalExt('${esc(name)}',${isEnabled});closeExtDetail();loadExtensions()">
            ${isEnabled?'⏸ Disable':'▶ Enable'}
        </button>
        <button class="btn-sm" style="background:var(--red)" onclick="uninstallExternalExt('${esc(name)}')">
            🗑 Uninstall
        </button>
    </div>`;

    // Store examples for switchCodeLang
    window._extExamples = examples;
}

function switchExtTab(tab) {
    document.querySelectorAll('.ext-tab-panel').forEach(p => p.style.display = 'none');
    const el = document.getElementById('ext-tab-' + tab);
    if (el) el.style.display = '';
    document.querySelectorAll('#ext-tab-chips .ext-chip').forEach(c => {
        c.classList.toggle('active', c.textContent.toLowerCase().includes(tab) || (tab==='api'&&c.textContent.includes('API')) || (tab==='skill'&&c.textContent.includes('SKILL')) || (tab==='info'&&c.textContent.includes('Info')));
    });
}

function switchCodeLang(lang, btn) {
    document.querySelectorAll('#ext-tab-api .ext-chip').forEach(c => c.classList.remove('active'));
    if (btn) btn.classList.add('active');
    const pre = document.getElementById('ext-code-block');
    if (pre && window._extExamples) pre.textContent = window._extExamples[lang] || '';
}

function copyExtCode() {
    const text = document.getElementById('ext-code-block')?.textContent || '';
    navigator.clipboard.writeText(text).then(() => {
        const btn = document.querySelector('#ext-tab-api button[onclick="copyExtCode()"]');
        if (btn) { btn.textContent = '✅ Copied!'; setTimeout(() => btn.textContent='📋 Copy', 1500); }
    });
}

window._ytdlQueue = [];
window._ytdlActive = 0;
const YTDL_CONCURRENCY = 5;

window.saveYtdlSettings = function() {
    localStorage.setItem('ytdl_filename', document.getElementById('set-ytdl-filename').value.trim());
    localStorage.setItem('ytdl_save_dir', document.getElementById('set-ytdl-save-dir').value.trim());
    localStorage.setItem('ytdl_format', document.getElementById('set-ytdl-format').value);
    localStorage.setItem('ytdl_quality', document.getElementById('set-ytdl-quality').value);
    document.getElementById('ytdl-settings-dialog').close();
};

function runYtdlDownload() {
    const text = document.getElementById('ytdl-url')?.value?.trim();
    if (!text) { alert('Nhập URL vào!'); return; }
    
    const urls = text.split('\n').map(u => u.trim()).filter(u => u);
    const format = localStorage.getItem('ytdl_format') || 'mp4';
    const quality = localStorage.getItem('ytdl_quality') || '720p';
    const save_dir = localStorage.getItem('ytdl_save_dir') || '';
    const filename_template = localStorage.getItem('ytdl_filename') || '';
    const container = document.getElementById('ytdl-queue-container');
    
    for (const url of urls) {
        const uid = 'q_' + Math.random().toString(36).slice(2);
        container.innerHTML += `
            <div id="${uid}" style="padding:12px;border-radius:8px;background:var(--bg2);border:1px solid var(--border)">
                <div style="font-size:.85rem;color:var(--text);margin-bottom:6px;word-break:break-all">${esc(url)}</div>
                <div style="display:flex;align-items:center;margin-bottom:4px;gap:8px">
                    <div style="flex:1;height:6px;background:var(--bg);border-radius:3px;overflow:hidden">
                        <div id="prog-${uid}" style="height:100%;width:0%;background:linear-gradient(90deg,var(--cyan),var(--green));transition:width 0.3s"></div>
                    </div>
                    <div id="pct-${uid}" style="font-size:.8rem;color:var(--text-muted);width:35px;text-align:right">0%</div>
                </div>
                <div id="stat-${uid}" style="font-size:.75rem;color:var(--text-muted)">⏳ Queued...</div>
                <div id="res-${uid}" style="margin-top:6px;display:none;font-size:0.85rem"></div>
            </div>`;
        window._ytdlQueue.push({uid, url, format, quality, save_dir, filename_template});
    }
    document.getElementById('ytdl-url').value = '';
    processYtdlQueue();
}

async function processYtdlQueue() {
    while (window._ytdlActive < YTDL_CONCURRENCY && window._ytdlQueue.length > 0) {
        const task = window._ytdlQueue.shift();
        window._ytdlActive++;
        startYtdlTask(task).finally(() => {
            window._ytdlActive--;
            processYtdlQueue();
        });
    }
}

async function startYtdlTask(task) {
    const st = document.getElementById('stat-' + task.uid);
    if(st) { st.textContent = '🚀 Preparing...'; st.style.color = 'var(--cyan)'; }
    try {
        const r = await apiPost('/api/v1/ytdl/download_async', { 
            url: task.url, 
            format: task.format, 
            quality: task.quality,
            save_dir: task.save_dir
        });
        if (r && r.status === 'success' && r.task_id) {
            await pollYtdlTask(task.uid, r.task_id);
        } else {
            if(st) { st.textContent = '❌ Lỗi khởi tạo'; st.style.color = 'var(--red)'; }
        }
    } catch(e) {
        if(st) { st.textContent = '❌ Lỗi server'; st.style.color = 'var(--red)'; }
    }
}

async function pollYtdlTask(uid, taskId) {
    return new Promise(resolve => {
        const poll = setInterval(async () => {
            try {
                const r = await apiGet('/api/v1/ytdl/status/' + taskId);
                if (r && r.success && r.data) {
                    const d = r.data;
                    const prog = document.getElementById('prog-' + uid);
                    const pct = document.getElementById('pct-' + uid);
                    const stat = document.getElementById('stat-' + uid);
                    const res = document.getElementById('res-' + uid);
                    
                    if (prog) prog.style.width = d.progress + '%';
                    if (pct) pct.textContent = Math.round(d.progress) + '%';
                    
                    if (d.status === 'downloading') {
                        const dl = (d.downloaded/1024/1024).toFixed(1);
                        const tot = (d.total_size/1024/1024).toFixed(1);
                        const spd = (d.speed/1024/1024).toFixed(1);
                        if (d.progress >= 100) {
                            if (stat) stat.textContent = `⚙️ Đang xử lý/gộp file video và audio (có thể mất thời gian tuỳ độ dài)...`;
                            if (prog) prog.style.background = 'var(--cyan)';
                        } else {
                            if (stat) stat.textContent = `⬇️ Đang tải: ${dl}MB / ${tot}MB (${spd}MB/s)`;
                        }
                    } else if (d.status === 'done') {
                        clearInterval(poll);
                        if (prog) prog.style.background = 'var(--green)';
                        if (stat) { stat.textContent = '✅ Xong! (100%)'; stat.style.color = 'var(--green)'; }
                        if (res) {
                            res.style.display = 'block';
                            res.innerHTML = `
                                <div style="font-weight:600;margin-bottom:8px;color:var(--text)">${esc(d.filename)}</div>
                                <a href="/api/v1/ytdl/downloads/${encodeURIComponent(d.filename)}" download class="btn-sm" style="background:var(--green);color:#fff;text-decoration:none">⬇️ Save File</a>
                            `;
                        }
                        resolve();
                    } else if (d.status === 'error') {
                        clearInterval(poll);
                        if (prog) prog.style.background = 'var(--red)';
                        if (stat) { stat.textContent = '❌ ' + esc(d.error || 'Syntax'); stat.style.color = 'var(--red)'; }
                        resolve();
                    }
                }
            } catch(e) {}
        }, 800);
    });
}


// ═══ Extension Detail Overlay ═══
function openExtDetail(id) {
    // Redirect to dedicated pages (only studio3d has no overlay)
    if (id === 'studio3d') { window.location.href = '/studio'; return; }

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
    else if (id === 'market') renderFullPageExt(body, 'Marketplace', 'Khám phá và cài đặt extension từ cộng đồng', `/market?v=${Date.now()}`);
    else if (id === 'cloud_api') renderCloudApiExt(body);
    else if (id === 'ollama') renderOllamaExt(body);
    else if (id === 'multi_agents') renderFullPageExt(body, 'Multi-Agents', 'Quản lý đội nhóm agent và phân công nhiệm vụ tự động.', '/teams');
    else if (id === 'downloader') renderFullPageExt(body, 'Video Downloader', 'Tải video từ TikTok & Douyin. Hỗ trợ quét kênh, tải hàng loạt.', '/downloader');
    else if (id === 'video_editor') renderFullPageExt(body, 'Video Editor', 'AI-powered Video Editor with Timeline & FFmpeg Processing.', '/video-editor');
}
function closeExtDetail() { document.getElementById('ext-detail-overlay').classList.add('hidden'); }

function renderFullPageExt(el, name, desc, url) {
    el.innerHTML = `<div style="height:calc(100vh - 150px);overflow:hidden"><iframe src="${url}" style="width:100%;height:100%;border:none"></iframe></div>`;
}

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
            const running = (status?.instances||[]).filter(i => i.status === 'running').map(i => i.profile).sort().join(',');
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
    const runningInstances = (status?.instances||[]).filter(i => i.status === 'running');
    const runningProfiles = runningInstances.map(i => i.profile);
    _lastRunningProfiles = runningProfiles.slice().sort().join(',');
    startBrowserStatusPoller(el);
    let h = `<div style="margin-bottom:16px;display:flex;gap:10px"><button class="btn-primary" onclick="showCreateProfile()">${T('browser.new_profile')}</button><button class="btn-secondary" onclick="showBrowserEnginesModal()">Browser Engines</button></div>`;
    if (runningInstances.length > 0) h += `<div class="status-bar"><span class="pulse-dot"></span> ${runningInstances.length} ${T('status.running')}</div>`;
    if (profiles.length === 0) h += `<p class="text-muted">${T('browser.no_profiles')}</p>`;
    else h += '<div class="cards-grid">' + profiles.map(p => {
        const isR = runningProfiles.includes(p.name);
        const hasGA = p.google_account && p.google_account.email;
        return `<div class="card" style="position:relative"><button class="btn-settings" onclick="showProfileSettings('${esc(p.name)}')" title="Settings">⚙️</button><div class="card-icon">🌐</div><h3>${esc(p.name)} ${isR ? '<span class="pulse-dot" style="display:inline-block"></span>' : ''}</h3><p class="card-meta">${esc(p.proxy||T('browser.no_proxy'))}</p><p class="card-desc">${p.has_fingerprint ? '🧬 FP OK' : `<span style="color:var(--orange)">⚠️ No FP</span>`} ${p.has_cookies ? '🍪' : ''} ${hasGA ? '<span style="color:var(--green)">🔐 ' + esc(p.google_account.email) + '</span>' : ''}</p><div class="card-footer" style="flex-wrap:wrap;gap:8px"><span class="tag green">${esc((p.created_at||'').slice(0,10))}</span><div class="card-actions">${isR ? `<button class="btn-sm btn-danger" onclick="stopProfile('${esc(p.name)}',this)">⏹</button>` : `<button class="btn-sm" onclick="launchProfile('${esc(p.name)}',this)">▶</button>`}<button class="btn-sm" onclick="showProfileCommand('${esc(p.name)}')" title="Run Command" style="background:linear-gradient(135deg,#8b5cf6,#06b6d4)">🚀</button><button class="btn-danger" onclick="deleteProfile('${esc(p.name)}');setTimeout(()=>renderBrowserExt(document.getElementById('ext-detail-body')),500)">✕</button></div></div></div>`;
    }).join('') + '</div>';
    el.innerHTML = h;
}

// ── Workflows Ext ──
async function renderWorkflowsExt(el) {
    el.innerHTML = `<div style="height:calc(100vh - 150px);border:1px solid var(--border);border-radius:8px;overflow:hidden"><iframe src="/workflow?v=3" style="width:100%;height:100%;border:none"></iframe></div>`;
}

// ── Skills Ext ──
let _loadedSkills = []; // cache for modals

function categorizeSkill(skill) {
    const nodes = skill.workflow_data?.nodes || [];
    const nodeTypes = nodes.map(n => n.type);
    
    if (skill.skill_type === 'Markdown' || nodes.length === 0) 
        return { cat: 'markdown', label: '📝 Prompt / Khái niệm', color: '#ec4899', icon: '📝' };
        
    if (skill.skill_type === 'Workflow Skill' || nodes.some(n => n.type === 'google_sheets' || n.type === 'google_auth'))
        return { cat: 'workflow', label: '🔧 Workflow Đầu-Cuối', color: '#a855f7', icon: '🔧' };
        
    if (nodeTypes.includes('browser_action'))
        return { cat: 'browser', label: '🌐 Browser Automation', color: '#22d3ee', icon: '🌐' };
        
    if (nodeTypes.includes('api_request'))
        return { cat: 'api', label: '⚡ API Integration', color: '#ef4444', icon: '⚡' };
        
    if (nodeTypes.includes('ai_node'))
        return { cat: 'ai', label: '🧠 AI Chuyên biệt', color: '#22c55e', icon: '🧠' };
        
    return { cat: 'general', label: '⚡ General', color: '#f59e0b', icon: '⚡' };
}

async function renderSkillsExt(el) {
    el.innerHTML = `<p class="text-muted">Đang tải cấu trúc Skills...</p>`;
    const data = await apiGet('/api/v1/skills');
    const skills = data?.skills || [];
    _loadedSkills = skills; // cache
    
    if (skills.length === 0) { 
        el.innerHTML = `<p class="text-muted">${T('skills.no_skills')}</p>`; 
        return; 
    }
    
    let html = '<div class="cards-grid">';
    
    skills.forEach(s => {
        const cat = categorizeSkill(s);
        
        let actionsHtml = `<button class="btn-sm" onclick="showSkillMarkdown('${s.id}')" title="Xem JSON Schema & Context mà LLM nhận được">📄 Xem Markdown</button>`;
        
        if (cat.cat === 'workflow' || cat.cat === 'browser' || cat.cat === 'general' || cat.cat === 'api' || cat.cat === 'ai') {
            actionsHtml += `<button class="btn-sm" onclick="window.open('/workflow?skill_id=${s.id}', '_blank')" title="Chỉnh sửa luồng chạy nghiệm của Skill này">🔧 Sửa Workflow</button>`;
        }
        
        actionsHtml += `<button class="btn-sm" style="background:linear-gradient(135deg,#10b981,#22c55e); color:#fff; border-color:transparent;" onclick="openRunSkillModal('${s.id}', '${esc(s.name)}')" title="Thực thi trực tiếp nhập liệu">▶ Chạy Test</button>`;

        html += `
        <div class="card" style="display:flex; flex-direction:column;">
            <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:12px;">
                <div class="card-icon" style="margin:0; width:40px; height:40px; border-radius:10px; font-size:1.2rem; background:rgba(0,0,0,0.2); box-shadow:0 4px 10px rgba(0,0,0,0.1); display:flex; align-items:center; justify-content:center;">${cat.icon}</div>
                <span class="tag" style="background:${cat.color}20; color:${cat.color}; border:1px solid ${cat.color}40; font-size:0.75rem; font-weight:600;">${cat.label}</span>
            </div>
            <h3 style="margin-bottom:8px; font-size:1.05rem;">${esc(s.name)}</h3>
            <p class="card-desc" style="flex:1; margin-bottom:16px;">${esc(s.description||'')}</p>
            <div style="font-size:0.8rem; color:var(--text-muted); margin-bottom:12px; background:var(--bg2); padding:6px 10px; border-radius:6px; font-family:'JetBrains Mono', monospace; word-break:break-all;">
                <strong style="color:var(--text)">Input Schema:</strong> ${s.commands && s.commands.length > 0 ? "['" + esc(s.commands.join("', '")) + "']" : "Text Prompt"}
            </div>
            <div class="card-footer" style="padding-top:12px; border-top:1px solid var(--border); display:flex; gap:6px; flex-wrap:wrap;">
                ${actionsHtml}
            </div>
        </div>`;
    });
    
    html += '</div>';
    el.innerHTML = html;
}

function showSkillMarkdown(skillId) {
    const skill = _loadedSkills.find(s => s.id === skillId);
    if (!skill) return;
    
    document.getElementById('skill-md-name').textContent = skill.name;
    const cat = categorizeSkill(skill);
    
    const nodes = (skill.workflow_data?.nodes || []).map(n => 
        `### Node: ${n.label || n.id} (type: ${n.type})\n\`\`\`json\n${JSON.stringify(n.config || {}, null, 2)}\n\`\`\``
    ).join('\n\n');
    
    const connections = (skill.workflow_data?.connections || []).map(c => 
        `- ${c.from_node_id}.${c.from_port_id} ➜ ${c.to_node_id}.${c.to_port_id}`
    ).join('\n');
    
    let md = `# Schema / Tool Definition\n\n`;
    md += `**Tool Name:** \`${skill.name.replace(/[^a-zA-Z0-9_-]/g, '_')}\`\n`;
    md += `**Description:** ${skill.description}\n`;
    md += `**Type:** ${cat.label}\n`;
    md += `**Trigger Keywords:** ${(skill.commands || []).join(', ') || 'N/A'}\n\n`;
    md += `--- \n\n## Cấu trúc logic (Internal Workflow)\n`;
    if (nodes) {
        md += `\n${nodes}\n\n### Chuyển giao dữ liệu (Connections)\n${connections}`;
    } else {
        md += `\n*Không có workflow định nghĩa (Skill tĩnh/Prompt-based).*`;
    }
    
    document.getElementById('skill-md-content').textContent = md;
    openModal('modal-skill-markdown');
}

function openRunSkillModal(skillId, skillName) {
    document.getElementById('skill-run-name').textContent = skillName;
    document.getElementById('skill-run-id').value = skillId;
    document.getElementById('skill-run-input').value = '';
    
    document.getElementById('skill-run-result-container').style.display = 'none';
    document.getElementById('btn-execute-skill').disabled = false;
    document.getElementById('btn-execute-skill').textContent = '🚀 Thực thi';
    
    openModal('modal-skill-run');
}

async function executeSkillRun() {
    const btn = document.getElementById('btn-execute-skill');
    const skillId = document.getElementById('skill-run-id').value;
    const inputVal = document.getElementById('skill-run-input').value.trim();
    const resultBox = document.getElementById('skill-run-result');
    const resultContainer = document.getElementById('skill-run-result-container');
    
    btn.disabled = true;
    btn.textContent = '⏳ Đang xử lý Workflow...';
    resultContainer.style.display = 'block';
    resultBox.innerHTML = '<span style="color:var(--cyan)">Đang gửi request cho API Server...</span>';
    
    try {
        const res = await fetch(`${API}/api/v1/skills/${skillId}/run?input_text=${encodeURIComponent(inputVal)}`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'}
        });
        
        const data = await res.json();
        
        if (res.ok) {
            btn.textContent = '✅ Xong';
            resultBox.textContent = JSON.stringify(data, null, 2);
        } else {
            throw new Error(data.detail || data.error || 'Server error');
        }
    } catch(err) {
        btn.textContent = '❌ Lỗi';
        resultBox.innerHTML = `<span style="color:var(--red)">Lỗi khi gọi skill:\n${err.message}</span>`;
    }
    
    setTimeout(() => {
        btn.disabled = false;
        btn.textContent = '🚀 Thực thi lại';
    }, 2000);
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
        h += `<div class="card" style="text-align:center">
        <div class="card-icon" style="position:relative">${provIcons[p.id]||'☁️'}
            <button class="btn-sm" style="position:absolute;top:0;right:0;padding:2px 6px;background:transparent;color:var(--text-muted);border:none" onclick="editProviderSettings('${esc(p.id)}', '${esc(p.models.join(','))}')" title="Edit Models">⚙️</button>
        </div>
        <h3>${esc(p.name)}</h3>
        <p class="card-desc" title="${esc(p.models.join(', '))}">${p.models.slice(0,3).join(', ')}${p.models.length>3?'...':''}</p>
        <div class="card-footer" style="justify-content:center;gap:8px">
            <span class="tag ${p.has_key?'green':''}">${p.has_key?T('cloud_api.active'):T('cloud_api.no_key')} <span style="font-size:0.75rem;margin-left:4px">(${p.key_count || 0})</span></span>
            <button class="btn-sm btn-primary" onclick="prefillAddKey('${esc(p.id)}')">${T('cloud_api.add')}</button>
        </div>
        </div>`;
    });
    h += '</div>';
    // Keys table
    const allKeys = [];
    Object.entries(keys).forEach(([prov, labels]) => { Object.entries(labels).forEach(([label, info]) => { allKeys.push({provider:prov, label, ...info}); }); });
    h += `<h3 style="color:var(--cyan);margin-bottom:12px">${T('cloud_api.stored_keys')}</h3>`;
    if (allKeys.length > 0) {
        h += `<div class="table-container"><table class="data-table"><thead><tr><th>${T('cloud_api.provider')}</th><th>${T('cloud_api.label')}</th><th>${T('cloud_api.key')}</th><th>${T('cloud_api.status')}</th><th>${T('cloud_api.actions')}</th></tr></thead><tbody>`;
        allKeys.forEach(k => { 
            let st = k.active ? `<span style="color:var(--green)">● ${T('cloud_api.active')}</span>` : `<span style="color:var(--text-muted)">○ Bị tắt</span>`;
            if (!k.active && k.status_msg) st = `<span style="color:var(--red)">⚠️ ${esc(k.status_msg)}</span>`;
            h += `<tr><td style="font-weight:600;color:var(--cyan)">${esc(k.provider)}</td><td>${esc(k.label)}</td><td style="font-family:'JetBrains Mono',monospace;font-size:.8rem;color:var(--text-muted)">${esc(k.masked_key)}</td><td>${st}</td>
            <td style="white-space:nowrap">
                <button class="btn-sm" style="background:var(--green);color:white;border:none;margin-right:4px;padding:2px 8px" onclick="testApiKey('${esc(k.provider)}', '${esc(k.label)}')">▶ Test</button>
                <button class="btn-danger btn-sm" style="padding:2px 8px" onclick="removeApiKeyExt('${esc(k.provider)}','${esc(k.label)}')">✕</button>
            </td></tr>`; 
        });
        h += '</tbody></table></div>';
    } else h += `<p class="text-muted">${T('cloud_api.no_keys')}</p>`;
    el.innerHTML = h;
}

let currentEditProvider = '';
let currentEditModels = [];

function editProviderSettings(provider, currentModelsStr) {
    currentEditProvider = provider;
    currentEditModels = currentModelsStr ? currentModelsStr.split(',').map(m => m.trim()).filter(Boolean) : [];
    document.getElementById('edit-models-title').innerHTML = `⚙️ Models: <strong>${esc(provider.toUpperCase())}</strong>`;
    document.getElementById('add-model-input').value = '';
    document.getElementById('model-test-panel').style.display = 'none';
    renderEditModelsList();
    document.getElementById('modal-edit-models').classList.remove('hidden');
    setTimeout(() => document.getElementById('add-model-input').focus(), 100);
}

window.addModelToList = function() {
    const input = document.getElementById('add-model-input');
    const val = input.value.trim();
    if (val && !currentEditModels.includes(val)) {
        currentEditModels.unshift(val); // Add to top
        input.value = '';
        renderEditModelsList();
    }
};

window.removeModelFromList = function(idx) {
    currentEditModels.splice(idx, 1);
    renderEditModelsList();
};

function renderEditModelsList() {
    const tbody = document.getElementById('edit-models-list');
    if(currentEditModels.length === 0) {
        tbody.innerHTML = '<tr><td class="text-muted" style="text-align:center;padding:15px">Chưa có model nào. Hãy thêm mới!</td></tr>';
        return;
    }
    let h = '';
    currentEditModels.forEach((m, i) => {
        h += `<tr>
            <td style="font-weight:600;color:var(--cyan);white-space:nowrap">${esc(m)}</td>
            <td style="text-align:right;width:95px;white-space:nowrap">
                <button class="btn-sm" style="background:var(--green);color:white;border:none;margin-right:2px;padding:2px 8px" onclick="window.openModelTest('${esc(m)}')">▶ Test</button>
                <button class="btn-danger btn-sm" style="padding:2px 8px" onclick="window.removeModelFromList(${i})">✕</button>
            </td>
        </tr>`;
    });
    tbody.innerHTML = h;
}

window.openModelTest = function(model) {
    document.getElementById('model-test-panel').style.display = 'block';
    document.getElementById('test-model-name').textContent = model;
    document.getElementById('test-model-result').textContent = 'Dữ liệu trả về sẽ hiển thị ở đây...';
    document.getElementById('test-model-result').style.color = 'var(--text)';
    window.currentTestModel = model;
    window.updateCurlPreview();
    // Scroll to panel
    setTimeout(() => {
        const mb = document.querySelector('#modal-edit-models .modal-body');
        if(mb) mb.scrollTop = mb.scrollHeight;
    }, 50);
};

window.updateCurlPreview = function() {
    if(!window.currentTestModel) return;
    const model = window.currentTestModel;
    const provider = currentEditProvider;
    const prompt = document.getElementById('test-model-prompt').value;
    const safePrompt = prompt.replace(/'/g, "'\\''").replace(/\n/g, "\\n");
    
    let curl = '';
    if (provider === 'gemini') {
        curl = `curl -X POST "https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=$API_KEY" \\\n-H "Content-Type: application/json" \\\n-d '{"contents":[{"parts":[{"text":"${safePrompt}"}]}]}'`;
    } else if (provider === 'claude') {
        curl = `curl -X POST "https://api.anthropic.com/v1/messages" \\\n-H "x-api-key: $API_KEY" \\\n-H "anthropic-version: 2023-06-01" \\\n-H "content-type: application/json" \\\n-d '{"model":"${model}","max_tokens":1024,"messages":[{"role":"user","content":"${safePrompt}"}]}'`;
    } else {
        let baseUrl = "https://api.openai.com/v1/chat/completions";
        if (provider === 'deepseek') baseUrl = "https://api.deepseek.com/chat/completions";
        if (provider === 'grok') baseUrl = "https://api.x.ai/v1/chat/completions";
        curl = `curl -X POST "${baseUrl}" \\\n-H "Content-Type: application/json" \\\n-H "Authorization: Bearer $API_KEY" \\\n-d '{"model":"${model}","messages":[{"role":"user","content":"${safePrompt}"}]}'`;
    }
    document.getElementById('test-model-curl').textContent = curl;
};

window.runModelTest = async function() {
    if(!window.currentTestModel) return;
    const btn = document.getElementById('btn-run-model-test');
    const resBox = document.getElementById('test-model-result');
    btn.disabled = true;
    btn.textContent = '⏳ Đang gửi...';
    resBox.textContent = 'Đang gọi API...';
    resBox.style.color = 'var(--text-muted)';
    
    try {
        const r = await apiPost(`/api/v1/cloud-api/providers/${currentEditProvider}/test-model`, {
            model: window.currentTestModel,
            prompt: document.getElementById('test-model-prompt').value
        });
        
        if (r && r.status === 'success') {
            resBox.style.color = 'var(--green)';
            resBox.textContent = typeof r.response === 'string' ? r.response : JSON.stringify(r.response, null, 2);
        } else {
            resBox.style.color = 'var(--red)';
            resBox.textContent = r?.error || r?.message || JSON.stringify(r);
        }
    } catch (e) {
        resBox.style.color = 'var(--red)';
        resBox.textContent = 'Lỗi kết nối: ' + e.message;
    }
    btn.disabled = false;
    btn.textContent = '▶ Gửi Request 🚀';
};

window.saveProviderModels = function() {
    apiPut(`/api/v1/cloud-api/providers/${currentEditProvider}/settings`, {models: currentEditModels})
    .then(r => {
        if(r?.status === 'success') {
            closeModal('modal-edit-models');
            renderCloudApiExt(document.getElementById('ext-detail-body'));
        } else {
            alert(r.error || r.message || 'Lỗi khi lưu models.');
        }
    });
};

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

// Group config: icon, label, description (vi/en)
const API_GROUPS = {
    'health': { icon: '💓', label: 'Health', desc_vi: 'Kiểm tra trạng thái server', desc_en: 'Server health check' },
    'agents': { icon: '🤖', label: 'Agents', desc_vi: 'Quản lý AI agents, tạo, sửa, xóa, chat', desc_en: 'Manage AI agents — create, edit, delete, chat' },
    'skills': { icon: '⚡', label: 'Skills', desc_vi: 'Quản lý kỹ năng agent, chạy skill', desc_en: 'Manage agent skills, run skills' },
    'workflows': { icon: '🔄', label: 'Workflows', desc_vi: 'Tạo và quản lý workflow tự động', desc_en: 'Create and manage automated workflows' },
    'nodes': { icon: '🧩', label: 'Nodes', desc_vi: 'Danh sách node workflow khả dụng', desc_en: 'List available workflow nodes' },
    'extensions': { icon: '📦', label: 'Extensions', desc_vi: 'Quản lý extension: bật/tắt, cài đặt, cập nhật', desc_en: 'Manage extensions: enable/disable, install, update' },
    'system': { icon: '⚙️', label: 'System', desc_vi: 'Phiên bản, cập nhật hệ thống', desc_en: 'Version info, system updates' },
    'settings': { icon: '🔧', label: 'Settings', desc_vi: 'Cài đặt hệ thống (ngôn ngữ, proxy...)', desc_en: 'System settings (language, proxy...)' },
    'cloud-api': { icon: '☁️', label: 'Cloud API', desc_vi: 'Quản lý API key cho Gemini, OpenAI, Claude...', desc_en: 'Manage API keys for Gemini, OpenAI, Claude...' },
    'downloader': { icon: '📥', label: 'Downloader', desc_vi: 'Tải video TikTok & Douyin, quét kênh', desc_en: 'Download TikTok & Douyin videos, scan channels' },
    'ollama': { icon: '🧠', label: 'Ollama', desc_vi: 'Quản lý mô hình AI local', desc_en: 'Manage local AI models' },
    'other': { icon: '📡', label: 'Other', desc_vi: 'Các API khác', desc_en: 'Other APIs' },
};

// i18n description overrides for specific endpoints
const API_DESC_VI = {
    '/api/v1/health': 'Kiểm tra server đang chạy',
    '/api/v1/agents': { 'get': 'Danh sách tất cả agents', 'post': 'Tạo agent mới' },
    '/api/v1/agents/generate': 'Tạo agent bằng AI',
    '/api/v1/agents/{agent_id}': { 'get': 'Chi tiết một agent', 'put': 'Cập nhật agent', 'delete': 'Xóa agent' },
    '/api/v1/agents/{agent_id}/chat': 'Chat với agent',
    '/api/v1/skills': { 'get': 'Danh sách kỹ năng', 'post': 'Tạo kỹ năng mới' },
    '/api/v1/skills/{skill_id}': { 'get': 'Chi tiết kỹ năng', 'delete': 'Xóa kỹ năng' },
    '/api/v1/skills/{skill_id}/run': 'Chạy kỹ năng',
    '/api/v1/workflows': { 'get': 'Danh sách workflows' },
    '/api/v1/workflows/run': 'Chạy workflow',
    '/api/v1/workflows/save-as-skill': 'Lưu workflow thành skill',
    '/api/v1/extensions': 'Danh sách extension',
    '/api/v1/extensions/{name}/enable': 'Bật extension',
    '/api/v1/extensions/{name}/disable': 'Tắt extension',
    '/api/v1/extensions/install': 'Cài extension từ Git',
    '/api/v1/system/version': 'Phiên bản hiện tại',
    '/api/v1/system/check-update': 'Kiểm tra cập nhật',
    '/api/v1/system/update': 'Cập nhật hệ thống',
    '/api/v1/settings/language': { 'get': 'Lấy ngôn ngữ hiện tại', 'post': 'Đổi ngôn ngữ' },
};

let _apiSpec = null; // cached spec

async function loadApiManagerPage() {
    document.getElementById('api-base-display').textContent = API;
    const el = document.getElementById('api-endpoints-list');

    try {
        const resp = await fetch(API + '/openapi.json');
        _apiSpec = await resp.json();
        renderApiGroups(_apiSpec, el);
    } catch(e) {
        el.innerHTML = '<p class="text-muted" style="padding:20px">Cannot load API spec. Check if server is running.</p>';
    }
}

function renderApiGroups(spec, el) {
    const paths = spec.paths || {};
    const lang = (document.documentElement.lang || 'en').startsWith('vi') ? 'vi' : 'en';

    // Group endpoints by prefix
    const groups = {};
    Object.entries(paths).forEach(([path, methods]) => {
        Object.entries(methods).forEach(([method, info]) => {
            if (!['get','post','put','delete','patch'].includes(method)) return;
            // Determine group from path
            const parts = path.replace('/api/v1/', '').split('/');
            let groupKey = parts[0] || 'other';
            if (groupKey === '{name}' || groupKey === '{agent_id}' || groupKey === '{skill_id}') groupKey = 'other';

            if (!groups[groupKey]) groups[groupKey] = [];

            // Get description
            let desc = info.summary || info.description || '';
            const viDesc = API_DESC_VI[path];
            if (lang === 'vi' && viDesc) {
                desc = typeof viDesc === 'string' ? viDesc : (viDesc[method] || desc);
            }

            groups[groupKey].push({ path, method, desc, info, tags: info.tags || [] });
        });
    });

    // Render groups
    let html = '';
    const orderKeys = Object.keys(API_GROUPS);
    const allGroupKeys = [...new Set([...orderKeys.filter(k => groups[k]), ...Object.keys(groups)])];

    allGroupKeys.forEach(key => {
        const items = groups[key];
        if (!items || items.length === 0) return;
        const grp = API_GROUPS[key] || { icon: '📡', label: key.charAt(0).toUpperCase() + key.slice(1), desc_vi: '', desc_en: '' };
        const grpDesc = lang === 'vi' ? grp.desc_vi : grp.desc_en;

        html += `<div class="api-group open" data-group="${key}">
            <div class="api-group-header" onclick="this.parentElement.classList.toggle('open')">
                <span class="group-icon">${grp.icon}</span>
                <span class="group-title">${grp.label}</span>
                <span style="font-size:0.75rem;color:var(--text-muted)">${esc(grpDesc)}</span>
                <span class="group-count">${items.length}</span>
                <span class="group-arrow">▶</span>
            </div>
            <div class="api-group-body">`;

        items.forEach(ep => {
            html += `<div class="api-row" data-path="${esc(ep.path)}" data-method="${ep.method}" onclick="openApiTest('${esc(ep.method)}','${esc(ep.path)}','${esc(ep.desc.replace(/'/g,''))}')">
                <span class="method-badge method-${ep.method}">${ep.method}</span>
                <span class="api-path">${esc(ep.path)}</span>
                <span class="api-desc">${esc(ep.desc)}</span>
                <button class="btn-test">▶ Test</button>
            </div>`;
        });

        html += '</div></div>';
    });

    el.innerHTML = html;
}

function filterApiEndpoints() {
    const q = document.getElementById('api-search').value.toLowerCase().trim();
    document.querySelectorAll('.api-row').forEach(row => {
        const path = (row.dataset.path || '').toLowerCase();
        const method = (row.dataset.method || '').toLowerCase();
        const desc = (row.querySelector('.api-desc')?.textContent || '').toLowerCase();
        row.classList.toggle('hidden', q && !path.includes(q) && !method.includes(q) && !desc.includes(q));
    });
    document.querySelectorAll('.api-group').forEach(grp => {
        const visibleRows = grp.querySelectorAll('.api-row:not(.hidden)');
        grp.style.display = visibleRows.length > 0 ? '' : 'none';
        if (q && visibleRows.length > 0) grp.classList.add('open');
    });
}

// === API Test Runner (inline below clicked row) ===
let _testMethod = 'GET', _testPath = '';

function openApiTest(method, path, desc, event) {
    if (event) event.stopPropagation();
    _testMethod = method.toUpperCase();
    _testPath = path;

    // Remove any existing inline test panel
    const existing = document.getElementById('api-test-inline');
    if (existing) existing.remove();

    // Find the clicked row
    const rows = document.querySelectorAll('.api-row');
    let targetRow = null;
    rows.forEach(r => {
        if (r.dataset.path === path && r.dataset.method === method) targetRow = r;
    });
    if (!targetRow) return;

    // Build param inputs
    const pathParams = (path.match(/\{(\w+)\}/g) || []).map(p => p.slice(1,-1));
    
    let queryParams = [];
    if (typeof _apiSpec !== 'undefined' && _apiSpec?.paths?.[path]?.[method]) {
        const specParams = _apiSpec.paths[path][method].parameters || [];
        specParams.forEach(p => {
            if (p.in === 'query') queryParams.push(p.name);
        });
    }

    let phtml = '';
    pathParams.forEach(p => {
        phtml += `<div class="api-test-params-group">
            <label>${p}</label>
            <input type="text" id="param-path-${p}" placeholder="Enter ${p}...">
        </div>`;
    });
    
    queryParams.forEach(p => {
        phtml += `<div class="api-test-params-group">
            <label>${p} <span style="color:var(--text-muted);font-weight:normal;font-size:0.8rem;">(query)</span></label>
            <input type="text" id="param-query-${p}" data-query-param="${p}" placeholder="Enter ${p}...">
        </div>`;
    });

    // Add request body if POST/PUT with JSON example
    if (['POST','PUT','PATCH'].includes(_testMethod)) {
        let exBody = '{}';
        if (_apiSpec && _apiSpec.paths[path] && _apiSpec.paths[path][method]) {
            const rb = _apiSpec.paths[path][method].requestBody;
            if (rb) {
                const schema = rb.content?.['application/json']?.schema;
                if (schema) {
                    exBody = JSON.stringify(buildExample(schema, _apiSpec), null, 2);
                }
            }
        }
        phtml += `<div class="api-test-params-group">
            <label>Request Body (JSON)</label>
            <textarea id="param-body" rows="6" style="width:100%;padding:8px 12px;border:1px solid var(--border);border-radius:6px;background:var(--bg);color:var(--text);font-family:'JetBrains Mono',monospace;font-size:.82rem;">${esc(exBody)}</textarea>
        </div>`;
    }

    // Create inline panel
    const panel = document.createElement('div');
    panel.id = 'api-test-inline';
    panel.className = 'api-test-panel';
    panel.innerHTML = `
        <div class="api-test-header">
            <span class="method-badge method-${method}">${_testMethod}</span>
            <code style="flex:1;font-size:14px;">${esc(path)}</code>
            <button class="btn-sm" onclick="closeApiTest()" style="background:var(--red);">✕ Đóng</button>
        </div>
        <p style="color:var(--text-muted);font-size:13px;margin:8px 0;">${esc(desc)}</p>
        <div>${phtml}</div>
        <div style="display:flex;gap:8px;margin-top:12px;">
            <button class="btn-primary" onclick="runApiTest()" id="btn-run-test">▶ Run Test</button>
        </div>
        <div id="api-test-response" class="api-response hidden">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                <span id="api-test-status" style="font-weight:700;"></span>
                <button class="btn-sm" onclick="copyApiResponse()">📋 Copy</button>
            </div>
            <pre id="api-test-body" style="max-height:400px;overflow:auto;font-size:12px;white-space:pre-wrap;"></pre>
        </div>`;

    // Insert right after the clicked row
    targetRow.insertAdjacentElement('afterend', panel);
    panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

// Build example JSON from OpenAPI schema
function buildExample(schema, spec) {
    if (!schema) return {};
    // Resolve $ref
    if (schema['$ref']) {
        const refPath = schema['$ref'].replace('#/', '').split('/');
        let resolved = spec;
        refPath.forEach(p => { resolved = resolved?.[p]; });
        return buildExample(resolved, spec);
    }
    // Handle anyOf (Pydantic Optional types)
    if (schema.anyOf) {
        const nonNull = schema.anyOf.find(s => s.type !== 'null');
        if (nonNull) return buildExample(nonNull, spec);
        return null;
    }
    if (schema.properties) {
        const obj = {};
        Object.entries(schema.properties).forEach(([k, v]) => {
            if (v['$ref']) {
                obj[k] = buildExample(v, spec);
            } else if (v.anyOf) {
                const nonNull = v.anyOf.find(s => s.type !== 'null');
                if (nonNull) {
                    obj[k] = buildExample(nonNull, spec);
                } else {
                    obj[k] = null;
                }
            } else if (v.type === 'array') {
                obj[k] = v.items ? [buildExample(v.items, spec)] : [];
            } else if (v.type === 'object') {
                obj[k] = v.properties ? buildExample(v, spec) : {};
            } else {
                obj[k] = v.default !== undefined ? v.default
                    : v.example !== undefined ? v.example
                    : v.type === 'string' ? (v.enum ? v.enum[0] : '')
                    : v.type === 'integer' || v.type === 'number' ? 0
                    : v.type === 'boolean' ? false : null;
            }
        });
        return obj;
    }
    // Handle primitive types directly
    if (schema.type === 'string') return schema.default !== undefined ? schema.default : '';
    if (schema.type === 'integer' || schema.type === 'number') return schema.default !== undefined ? schema.default : 0;
    if (schema.type === 'boolean') return schema.default !== undefined ? schema.default : false;
    return {};
}

function closeApiTest() {
    const panel = document.getElementById('api-test-inline');
    if (panel) panel.remove();
}

async function runApiTest() {
    const btn = document.getElementById('btn-run-test');
    btn.disabled = true; btn.textContent = '⏳ Running...';

    // Build URL with path and query params
    let url = _testPath;
    const pathParams = (_testPath.match(/\{(\w+)\}/g) || []).map(p => p.slice(1,-1));
    pathParams.forEach(p => {
        const val = document.getElementById('param-path-' + p)?.value || '';
        url = url.replace(`{${p}}`, encodeURIComponent(val));
    });

    const queryInputs = document.querySelectorAll('input[data-query-param]');
    if (queryInputs.length > 0) {
        const params = new URLSearchParams();
        queryInputs.forEach(inp => {
            if (inp.value && inp.value.trim() !== '') {
                params.append(inp.getAttribute('data-query-param'), inp.value);
            }
        });
        const qs = params.toString();
        if (qs) url += (url.includes('?') ? '&' : '?') + qs;
    }

    const fetchOpts = { method: _testMethod, headers: {} };
    if (['POST','PUT','PATCH'].includes(_testMethod)) {
        const bodyEl = document.getElementById('param-body');
        if (bodyEl) {
            let bodyText = bodyEl.value.trim();
            // Auto-fix common JSON mistakes: single quotes → double quotes
            if (bodyText) {
                // Replace single-quoted string values with double-quoted
                bodyText = bodyText.replace(/:\s*'([^']*)'/g, ': "$1"');
                // Remove trailing commas before } or ]
                bodyText = bodyText.replace(/,\s*([}\]])/g, '$1');
                bodyEl.value = bodyText;
            }
            // Validate JSON
            try {
                JSON.parse(bodyText);
            } catch(e) {
                const respDiv = document.getElementById('api-test-response');
                const statusEl = document.getElementById('api-test-status');
                const bodyPre = document.getElementById('api-test-body');
                statusEl.innerHTML = `<span style="color:var(--red)">❌ Invalid JSON</span>`;
                bodyPre.textContent = `JSON không hợp lệ: ${e.message}\n\nLưu ý: JSON phải dùng dấu nháy kép (") chứ không phải nháy đơn (')\n\nBody hiện tại:\n${bodyText}`;
                respDiv.classList.remove('hidden');
                btn.disabled = false; btn.textContent = '▶ Run Test';
                return;
            }
            fetchOpts.headers['Content-Type'] = 'application/json';
            fetchOpts.body = bodyText;
        }
    }

    const respDiv = document.getElementById('api-test-response');
    const statusEl = document.getElementById('api-test-status');
    const bodyEl = document.getElementById('api-test-body');

    try {
        const t0 = Date.now();
        const res = await fetch(url, fetchOpts);
        const elapsed = Date.now() - t0;
        const text = await res.text();
        let formatted = text;
        try { formatted = JSON.stringify(JSON.parse(text), null, 2); } catch(e) {}

        statusEl.innerHTML = `<span style="color:${res.ok?'var(--green)':'var(--red)'}"> ${res.status} ${res.statusText}</span> <span style="color:var(--text-muted);font-weight:400;font-size:.8rem;">(${elapsed}ms)</span>`;
        bodyEl.textContent = formatted;
        respDiv.classList.remove('hidden');
    } catch(e) {
        statusEl.innerHTML = `<span style="color:var(--red)">Error</span>`;
        bodyEl.textContent = e.message;
        respDiv.classList.remove('hidden');
    }
    btn.disabled = false; btn.textContent = '▶ Run Test';
}

function copyApiResponse() {
    const text = document.getElementById('api-test-body').textContent;
    navigator.clipboard.writeText(text).then(() => alert('Copied!'));
}

// ═══ API Key Management ═══
function showAddApiKey() { document.getElementById('modal-add-key').classList.remove('hidden'); }
function prefillAddKey(provider) { document.getElementById('add-key-provider').value = provider; document.getElementById('add-key-value').value = ''; document.getElementById('add-key-label').value = `key_${Math.floor(Date.now() / 1000)}`; document.getElementById('modal-add-key').classList.remove('hidden'); }
async function addApiKey() { const prov=document.getElementById('add-key-provider').value, key=document.getElementById('add-key-value').value.trim(), label=document.getElementById('add-key-label').value.trim()||'default'; if(!key) return alert('Key required.'); const r = await apiPost('/api/v1/cloud-api/keys',{provider:prov,api_key:key,label}); if(r&&r.status==='success') { closeModal('modal-add-key'); renderCloudApiExt(document.getElementById('ext-detail-body')); alert('Added!'); } else alert('Failed.'); }
async function testApiKey(provider, label = 'default') { 
    alert(`Testing ${provider} [${label}]...`); 
    const r = await apiPost('/api/v1/cloud-api/keys/test', {provider, label}); 
    if (r) {
        if (r.status === 'success') {
            alert(`✅ OK! ${r.message}`);
        } else if (r.status === 'info') {
            alert(`ℹ️ INFO: ${r.message}`);
        } else {
            alert(`❌ LỖI: ${r.message || r.status}`);
        }
    } 
}

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

function openModal(id) { document.getElementById(id).classList.remove('hidden'); }
function closeModal(id) { document.getElementById(id).classList.add('hidden'); }
function onProxyModeChange() { const m=document.getElementById('agent-proxy-mode').value; document.getElementById('proxy-static-group').style.display=m==='static'?'block':'none'; document.getElementById('proxy-dynamic-group').style.display=m==='dynamic'?'block':'none'; }
function onScheduleRepeatChange() { document.getElementById('schedule-interval-group').style.display=document.getElementById('agent-schedule-repeat').value==='interval'?'block':'none'; }
document.getElementById('agent-schedule-repeat')?.addEventListener('change', onScheduleRepeatChange);

async function saveAgent() { const name=document.getElementById('agent-name').value.trim(); if(!name) return alert('Name required'); const id=document.getElementById('agent-id').value; const interests=document.getElementById('agent-interests').value.split(',').map(s=>s.trim()).filter(s=>s); let routine={}; try { const v=document.getElementById('agent-behavior').value; if(v) routine=JSON.parse(v); } catch(e) { return alert('Invalid JSON: '+e.message); } const pm=document.getElementById('agent-proxy-mode').value; const pp={mode:pm}; if(pm==='dynamic') { pp.api_url=document.getElementById('agent-proxy-api')?.value||''; pp.api_key=document.getElementById('agent-proxy-api-key')?.value||''; pp.location=document.getElementById('agent-proxy-location')?.value||''; } const payload = { name, description:document.getElementById('agent-desc').value, system_prompt:document.getElementById('agent-prompt').value, model:document.getElementById('agent-model').value, browser_ai_model:document.getElementById('agent-browser-model').value, avatar_type:document.getElementById('agent-avatar-type').value, avatar_color:document.getElementById('agent-avatar-color').value, persona:{interests}, routine, proxy_config:pm==='static'?document.getElementById('agent-proxy').value:'', proxy_provider:pp, timezone:document.getElementById('agent-timezone').value, schedule:{ enabled:document.getElementById('agent-schedule-enable').checked, repeat:document.getElementById('agent-schedule-repeat').value, interval:parseInt(document.getElementById('agent-schedule-interval').value)||60, active_days:Array.from(document.querySelectorAll('.agent-day-cb:checked')).map(cb=>cb.value), start_time:document.getElementById('agent-schedule-start').value, end_time:document.getElementById('agent-schedule-end').value, max_runs:parseInt(document.getElementById('agent-schedule-max-runs').value)||10 }, enable_scraping:document.getElementById('agent-scraping-enable').checked, scraper_text_limit:parseInt(document.getElementById('agent-scraper-limit').value)||10000, script_output_format:document.getElementById('agent-scraper-format').value, telegram_token:document.getElementById('agent-tg-token').value, telegram_chat_id:document.getElementById('agent-tg-chat').value, messenger_token:document.getElementById('agent-ms-token').value, messenger_page_id:document.getElementById('agent-ms-page').value, messenger_php_url:document.getElementById('agent-ms-php').value, direct_trigger_skill_id:document.getElementById('agent-ms-skill').value, allowed_profiles:Array.from(document.querySelectorAll('.agent-profile-cb:checked')).map(cb=>cb.value), allowed_skills:Array.from(document.querySelectorAll('.agent-skill-cb:checked')).map(cb=>cb.value) }; if(id) await apiPut('/api/v1/agents/'+id,payload); else await apiPost('/api/v1/agents',payload); closeModal('modal-agent'); renderAgentsExt(document.getElementById('ext-detail-body')); }
async function deleteAgent(id) { if(!confirm('Delete agent?')) return; await apiDelete('/api/v1/agents/'+id); }

// ═══ Generate Agent ═══
let AI_PROVIDERS = { "ollama":{models:["deepseek-r1:latest","llama3.2","mistral-nemo"],needs_api:false}, "gemini":{models:["gemini-2.5-flash","gemini-2.0-flash","gemini-2.5-pro"],needs_api:true}, "chatgpt":{models:["gpt-4o","gpt-4o-mini","gpt-4-turbo"],needs_api:true}, "claude":{models:["claude-sonnet-4-20250514","claude-3-5-haiku-20241022"],needs_api:true}, "grok":{models:["grok-3","grok-3-mini","grok-2"],needs_api:true} };
function showGenerateAgent() { document.getElementById('agent-gen-name').value=''; document.getElementById('agent-gen-prefix').value=''; document.getElementById('agent-gen-desc').value=''; document.getElementById('agent-gen-provider').value='ollama'; document.getElementById('agent-gen-accounts').value=''; document.getElementById('agent-gen-preview').value=''; document.getElementById('agent-gen-status').textContent=''; document.getElementById('btn-apply-ai').style.display='none'; onGenProviderChange(); const ni=document.getElementById('agent-gen-name'); const nn=ni.cloneNode(true); ni.parentNode.replaceChild(nn,ni); nn.addEventListener('input',e=>{ document.getElementById('agent-gen-prefix').value=e.target.value.toLowerCase().replace(/[^a-z0-9]+/g,'_').replace(/(^_|_$)/g,''); }); document.getElementById('modal-generate-agent').classList.remove('hidden'); apiGet('/api/v1/cloud-api/providers').then(res=>{if(res&&res.providers){res.providers.forEach(p=>{if(AI_PROVIDERS[p.id])AI_PROVIDERS[p.id].models=p.models;});onGenProviderChange();}}); }
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
                const downloadUrl = (typeof v === 'object' && (v.local_url || v.download_url)) ? (v.local_url || v.download_url) : '';
                
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
    const downloadUrl = data.local_url || data.download_url || '';
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
        if (start && start.status === 'already_downloading') {
            // Another tab already started this download - just poll progress
            titleText.textContent = `Downloading ${version}... (resuming)`;
        } else if (!start || start.error) {
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
async function launchProfile(name,btn) { if(btn){btn.disabled=true;btn.textContent='🚀...'} const r=await apiPost('/api/v1/browser/launch',{profile:name,manual:true}); if(r && !r.error && r.status !== 'error') { let n=0; const iv=setInterval(async()=>{await renderBrowserExt(document.getElementById('ext-detail-body'));if(++n>=3)clearInterval(iv)},2000); } else { if(btn){btn.disabled=false;btn.textContent='▶'} let msg = 'Failed to launch: ' + (r?.error || r?.detail || 'Unknown error'); if(r?.log_output) msg += '\n\n📋 Log output:\n' + r.log_output; if(r?.debug) { const d = r.debug; msg += '\n\n🔍 Debug info:'; msg += '\n• Node: ' + (d.node_available ? d.node_version : '❌ NOT FOUND'); msg += '\n• open.js: ' + (d.open_js_exists ? '✅' : '❌ NOT FOUND'); msg += '\n• node_modules: ' + (d.node_modules_exists ? '✅' : '❌ MISSING'); msg += '\n• Launcher dir: ' + (d.launcher_dir || '-'); if(d.launcher_dir_contents) msg += '\n• Dir contents: ' + d.launcher_dir_contents.join(', '); if(d.exit_code !== undefined) msg += '\n• Exit code: ' + d.exit_code; } alert(msg); } }
async function stopProfile(name,btn) { if(btn){btn.disabled=true;btn.textContent='...'} await apiPost('/api/v1/browser/stop',{profile:name}); setTimeout(()=>renderBrowserExt(document.getElementById('ext-detail-body')),1000); }
async function deleteProfile(name) { if(!confirm('Delete '+name+'?')) return; await apiDelete('/api/v1/browser/profiles/'+name); }
async function viewProfileLog(name) { const r = await apiGet('/api/v1/browser/log/' + encodeURIComponent(name)); if (!r || r.error) { alert('No log available: ' + (r?.error || 'Unknown')); return; } let msg = '📋 Browser Log for: ' + name; msg += '\n\nStatus: ' + (r.status || '-'); msg += '\nCommand: ' + (r.command || '-'); msg += '\nLog file: ' + (r.log_file || '-'); if (r.debug) { const d = r.debug; if (d.node_version) msg += '\nNode: ' + d.node_version; if (d.open_js_exists !== undefined) msg += '\nopen.js: ' + (d.open_js_exists ? '✅' : '❌'); if (d.node_modules_exists !== undefined) msg += '\nnode_modules: ' + (d.node_modules_exists ? '✅' : '❌'); if (d.launcher_dir) msg += '\nLauncher: ' + d.launcher_dir; } msg += '\n\n─── LOG OUTPUT ───\n' + (r.log || '(empty)'); alert(msg); }

// ═══ Browser Command ═══
let _cmdProfile = '';
function showProfileCommand(name) { _cmdProfile = name; document.getElementById('cmd-profile-name').textContent = name; document.getElementById('cmd-input').value = ''; document.getElementById('modal-command').classList.remove('hidden'); setTimeout(() => document.getElementById('cmd-input').focus(), 100); }
function setCommand(cmd) { document.getElementById('cmd-input').value = cmd; document.getElementById('cmd-input').focus(); }
async function executeProfileCommand() { const cmd = document.getElementById('cmd-input').value.trim(); if (!cmd) return alert('Vui lòng nhập lệnh!'); const aiModel = document.getElementById('cmd-ai-model').value; const btn = document.getElementById('btn-run-command'); btn.disabled = true; btn.textContent = '⏳ Đang chạy...'; const r = await apiPost('/api/v1/browser/launch', { profile: _cmdProfile, prompt: cmd, manual: false, ai_model: aiModel }); btn.disabled = false; btn.textContent = '🚀 Chạy lệnh'; if (r && !r.error && r.status !== 'error') { closeModal('modal-command'); let n = 0; const iv = setInterval(async () => { await renderBrowserExt(document.getElementById('ext-detail-body')); if (++n >= 3) clearInterval(iv); }, 2000); } else { let msg = 'Lỗi: ' + (r?.error || r?.detail || 'Unknown'); if (r?.log_output) msg += '\n\n' + r.log_output; alert(msg); } }
function searchMarket() { const q=(document.getElementById('market-search')?.value||'').toLowerCase(); document.querySelectorAll('#market-list .card').forEach(c=>{ c.style.display=c.textContent.toLowerCase().includes(q)?'':'none'; }); }

// ═══ Settings ═══
function saveSettings() { const api=document.getElementById('set-api').value.trim(); if(api){localStorage.setItem('zhiying_api',api);location.reload();} }

// ═══ Version & Update ═══
async function loadVersionInfo() {
    const d = await apiGet('/api/v1/system/version');
    if (!d) return;
    document.getElementById('version-badge').textContent = '⚡ ZhiYing v' + (d.version || '?');
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
    if (!confirm('Update ZhiYing to latest version? The API server will need to restart after update.')) return;
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
            card.insertAdjacentHTML('afterend', '<div class="restart-banner" id="restart-banner">⚠️ Restart the API server to apply the update. Run: <code>zhiying api start</code></div>');
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

// ═══ Profile Settings ═══
let _settingsProfileName = '';

async function showProfileSettings(name) {
    _settingsProfileName = name;
    document.getElementById('settings-profile-name').textContent = name;
    
    // Load profile data
    try {
        const data = await apiGet(`/api/v1/browser/profiles/${name}`);
        if (data) {
            document.getElementById('settings-proxy').value = data.proxy || '';
            // Set fingerprint tags
            const tags = data.tags || ['Windows', 'Chrome'];
            const osEl = document.getElementById('settings-fp-os');
            const brEl = document.getElementById('settings-fp-browser');
            for (const t of tags) {
                if (['Windows','macOS','Linux','Android'].includes(t)) osEl.value = t;
                if (['Chrome','Firefox','Edge'].includes(t)) brEl.value = t;
            }
            // Google account
            const ga = data.google_account;
            if (ga && ga.email) {
                const parts = [ga.email, ga.password || '', ga.recoveryEmail || '', ga.twoFactorCodes || ''].filter(p => p);
                document.getElementById('settings-google-account').value = parts.join('|');
            } else {
                document.getElementById('settings-google-account').value = '';
            }
            previewGoogleAccount();
        }
    } catch (e) {
        console.error('Failed to load profile:', e);
    }
    
    openModal('modal-settings');
}

function previewGoogleAccount() {
    const raw = document.getElementById('settings-google-account').value.trim();
    const previewEl = document.getElementById('settings-account-preview');
    if (!raw) { previewEl.style.display = 'none'; return; }
    
    const parts = raw.includes('|') ? raw.split('|') : raw.split('\t');
    document.getElementById('preview-email').textContent = (parts[0] || '').trim();
    document.getElementById('preview-pass').textContent = (parts[1] || '').trim() ? '••••••••' : '(empty)';
    document.getElementById('preview-recovery').textContent = (parts[2] || '').trim() || '(none)';
    document.getElementById('preview-2fa').textContent = (parts[3] || '').trim() || '(none)';
    previewEl.style.display = 'block';
}

async function saveProfileSettings() {
    const proxy = document.getElementById('settings-proxy').value.trim();
    const os = document.getElementById('settings-fp-os').value;
    const browser = document.getElementById('settings-fp-browser').value;
    const googleRaw = document.getElementById('settings-google-account').value.trim();
    
    const payload = {
        proxy: proxy,
        tags: [os, browser],
    };
    
    // Send google_account as raw string — backend will parse it
    if (googleRaw) {
        payload.google_account = googleRaw;
    } else {
        payload.google_account = '';
    }
    
    try {
        console.log('[Settings] Saving:', _settingsProfileName, payload);
        const result = await apiPut(`/api/v1/browser/profiles/${_settingsProfileName}`, payload);
        console.log('[Settings] Result:', result);
        if (result && result.status === 'updated') {
            closeModal('modal-settings');
            // Show inline toast
            const toast = document.createElement('div');
            toast.textContent = '✅ Settings saved!';
            toast.style.cssText = 'position:fixed;top:20px;right:20px;background:#22c55e;color:#fff;padding:12px 24px;border-radius:8px;z-index:99999;font-weight:600;box-shadow:0 4px 12px rgba(0,0,0,0.3);animation:fadeIn .3s';
            document.body.appendChild(toast);
            setTimeout(() => toast.remove(), 2500);
            // Refresh the browser extension view
            const el = document.getElementById('ext-detail-body');
            if (el) renderBrowserExt(el);
        } else {
            alert('❌ Save failed: ' + JSON.stringify(result));
        }
    } catch (e) {
        console.error('[Settings] Error:', e);
        alert('❌ Error: ' + e.message);
    }
}

// ═══ Connection Check ═══
async function checkConnection() { try { const r=await fetch(API+'/api/v1/health',{signal:AbortSignal.timeout(2000)}); if(r.ok) document.querySelector('.sidebar-footer').innerHTML='<span class="status-dot"></span> API Connected'; else throw 0; } catch { document.querySelector('.sidebar-footer').innerHTML='<span class="status-dot" style="background:var(--red)"></span> API Offline'; } }

// ═══ Version & Update ═══
async function loadVersionInfo() {
    const badge = document.getElementById('version-badge');
    const hashEl = document.getElementById('version-hash');
    const branchEl = document.getElementById('version-branch');
    if (!badge) return;
    try {
        const info = await apiGet('/api/v1/version');
        if (!info || info.error) return;
        badge.textContent = '⚡ ZhiYing v' + (info.version || '?');
        if (hashEl && info.git_hash) hashEl.textContent = '#' + info.git_hash;
        if (branchEl && info.git_branch) branchEl.textContent = '🌿 ' + info.git_branch;
        // Auto-check update on startup (silent)
        checkForUpdate(true);
    } catch(e) { console.warn('[Version] Failed to load version info', e); }
}

async function checkForUpdate(silent = false) {
    const btn = document.getElementById('btn-check-update');
    const statusEl = document.getElementById('update-status');
    const changelogBox = document.getElementById('changelog-box');
    const changelogList = document.getElementById('changelog-list');
    const updateBtn = document.getElementById('btn-system-update');
    if (btn && !silent) { btn.disabled = true; btn.textContent = '🔍 Checking...'; }
    try {
        // Get local version
        const local = await apiGet('/api/v1/version');
        const localVer = local?.version || '0';

        // Fetch remote version.json from server
        const res = await fetch('https://api.tubecreate.com/api/market-cli/version.json?_t=' + Date.now(), {
            signal: AbortSignal.timeout(5000)
        });
        if (!res.ok) throw new Error('Server not reachable');
        const remote = await res.json();
        const remoteVer = remote.version || '0';

        // Compare
        const hasUpdate = remoteVer > localVer;
        if (statusEl) {
            if (hasUpdate) {
                statusEl.innerHTML = `<span style="color:var(--yellow);font-weight:700">🆕 Phiên bản mới có sẵn: v${remoteVer}</span>`;
                if (updateBtn) updateBtn.style.display = '';
                // Show changelog
                if (changelogBox && changelogList && remote.changelog?.length) {
                    changelogList.innerHTML = remote.changelog.map(c => `<li>${esc(c)}</li>`).join('');
                    changelogBox.style.display = '';
                }
            } else {
                if (!silent) statusEl.innerHTML = `<span style="color:var(--green)">✅ Đang dùng phiên bản mới nhất (v${localVer})</span>`;
                if (updateBtn) updateBtn.style.display = 'none';
                if (changelogBox) changelogBox.style.display = 'none';
            }
        }
    } catch(e) {
        if (!silent && statusEl) statusEl.innerHTML = `<span style="color:var(--red)">⚠️ Không kết nối được server kiểm tra update</span>`;
        console.warn('[Update] Check failed:', e.message);
    }
    if (btn) { btn.disabled = false; btn.textContent = '🔍 Check for Update'; }
}

async function performSystemUpdate() {
    const btn = document.getElementById('btn-system-update');
    const statusEl = document.getElementById('update-status');
    if (!confirm('🚀 Bắt đầu cập nhật phiên bản mới?\n\nApp sẽ chạy git pull và có thể cần khởi động lại.')) return;
    if (btn) { btn.disabled = true; btn.textContent = '⬇️ Đang cập nhật...'; }
    if (statusEl) statusEl.innerHTML = '<span style="color:var(--cyan)">⏳ Đang tải bản cập nhật...</span>';
    try {
        const r = await apiPost('/api/v1/version/update', {});
        if (r.status === 'success') {
            if (statusEl) statusEl.innerHTML = `<span style="color:var(--green)">✅ Cập nhật xong! Vui lòng tải lại trang.<br><small style="color:var(--text-muted)">${esc(r.output)}</small></span>`;
            setTimeout(() => { if (confirm('✅ Cập nhật thành công! Tải lại trang ngay?')) location.reload(); }, 1500);
        } else {
            if (statusEl) statusEl.innerHTML = `<span style="color:var(--red)">❌ Lỗi: ${esc(r.output)}</span>`;
        }
    } catch(e) {
        if (statusEl) statusEl.innerHTML = `<span style="color:var(--red)">❌ Lỗi kết nối: ${e.message}</span>`;
    }
    if (btn) { btn.disabled = false; btn.textContent = '⬆️ Update Now'; }
}


// ═══ Init ═══
document.addEventListener('DOMContentLoaded', async () => {
    await loadI18nFromApi();
    checkConnection();
    loadDashboard();
    loadVersionInfo();
    const s=localStorage.getItem('zhiying_api');
    if(s) document.getElementById('set-api').value=s;
    if(document.getElementById('set-lang')) document.getElementById('set-lang').value = _lang;
});
