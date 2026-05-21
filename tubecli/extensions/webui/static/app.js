/**
 * TubeCLI Dashboard — SPA Logic
 * Dashboard → Extensions → API Manager → Settings
 */
const API = localStorage.getItem('tubecli_api') || window.location.origin;

// ═══ Hash Router ═══
const ROUTE_TAB_MAP = {
    'dashboard': 'dashboard',
    'extensions': 'extensions',
    'api-manager': 'api-manager',
    'settings': 'settings',
    'ext-agents': 'ext-agents',
    'ext-browser': 'ext-browser',
    'ext-web-crawler': 'ext-web-crawler',
    'ext-sheets': 'ext-sheets',
    'ext-calendar': 'ext-calendar',
    'ext-downloader': 'ext-downloader',
    'ext-livestream': 'ext-livestream',
    'ext-teams': 'ext-teams',
    'ext-story': 'ext-story',
    'ext-video-editor': 'ext-video-editor',
    'ext-studio': 'ext-studio',
    'ext-file-manager': 'ext-file-manager',
    'ext-video-manager': 'ext-video-manager',
};

function navigateTo(tab) {
    const openMode = localStorage.getItem('ext_open_mode') || 'full_page';
    if (openMode === 'full_page' && tab.startsWith('ext-')) {
        const excludeTabs = ['ext-auth-manager', 'ext-calendar', 'ext-agents', 'ext-browser', 'ext-cloud-keys', 'ext-market'];
        if (!excludeTabs.includes(tab)) {
            const panel = document.getElementById('tab-' + tab);
            if (panel) {
                const iframe = panel.querySelector('iframe.ext-iframe[data-src]');
                if (iframe) {
                    const url = iframe.getAttribute('data-src');
                    if (url) {
                        window.open(url, '_blank');
                        return;
                    }
                }
            }
        }
    }
    window.location.hash = '#/' + tab;
}

async function shutdownServer() {
    if (!confirm('Are you sure you want to shut down TubeCLI?')) return;
    try {
        const btn = document.querySelector('#sidebar-footer button');
        if (btn) btn.innerHTML = '<span class="spinner" style="width:14px;height:14px;border-width:2px;display:inline-block;"></span> Shutting down...';
        await fetch(`${API}/api/v1/system/shutdown`, { method: 'POST' });
        setTimeout(() => {
            document.body.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100vh;background:#000;color:#fff;font-family:sans-serif;font-size:1.5rem;">TubeCLI has been shut down. You can close this window.</div>';
        }, 1000);
    } catch (e) {
        console.error('Failed to shutdown', e);
        alert('Failed to shutdown server.');
    }
}

window.syncThemeToIframe = function(iframe) {
    try {
        const doc = iframe.contentDocument || iframe.contentWindow.document;
        if (!doc) return;
        const rootStyles = getComputedStyle(document.documentElement);
        const getVar = (...names) => {
            for (const n of names) {
                const v = rootStyles.getPropertyValue(n).trim();
                if (v) return v;
            }
            return '';
        };

        const mappedVars = {
            '--bg': getVar('--bg'),
            '--bg2': getVar('--bg2'),
            '--bg3': getVar('--bg3', '--bg-secondary'),
            '--sidebar-bg': getVar('--bg2', '--bg-secondary'),
            '--surface': getVar('--bg2', '--bg-secondary'),
            '--hover-bg': getVar('--bg-hover', '--bg3'),
            '--text': getVar('--text'),
            '--text2': getVar('--text2', '--text-muted'),
            '--text3': getVar('--text-muted', '--text-subtle'),
            '--muted': getVar('--text-muted', '--text2'),
            '--border': getVar('--border'),
            '--card': getVar('--bg3', '--bg2'),
            '--card2': getVar('--bg-lighter', '--bg3'),
            '--card-bg': getVar('--bg3', '--bg2'),
            '--card-border': getVar('--border', '--border-subtle'),
            '--accent': getVar('--accent', '--primary'),
            '--accent2': getVar('--accent-hover', '--primary-hover'),
            '--cyan': getVar('--cyan'),
            '--red': getVar('--red'),
            '--green': getVar('--green'),
            '--orange': getVar('--orange'),
            '--yellow': getVar('--yellow')
        };
        let cssText = ':root { ';
        for (const [k, v] of Object.entries(mappedVars)) {
            if (v) cssText += `${k}: ${v} !important; `;
        }
        cssText += '} ';
        cssText += 'body { background: var(--bg) !important; color: var(--text) !important; } ';
        cssText += '.header { background: var(--bg2) !important; border-bottom-color: var(--border) !important; } ';
        cssText += '.studio-layout, .studio-sidebar, .studio-toolbar { background: var(--bg) !important; } ';
        
        let styleEl = doc.getElementById('tubecli-theme-sync');
        if (!styleEl) {
            styleEl = doc.createElement('style');
            styleEl.id = 'tubecli-theme-sync';
            doc.head.appendChild(styleEl);
        }
        styleEl.innerHTML = cssText;
    } catch(e) {}
};

function handleRoute() {
    const hash = window.location.hash.replace('#/', '') || 'dashboard';
    const tab = ROUTE_TAB_MAP[hash] || (hash.startsWith('ext-') ? hash : 'dashboard');
    activateTab(tab);
}

function activateTab(tab) {
    // Update sidebar active state
    document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
    const navBtn = document.querySelector(`.nav-item[data-tab="${tab}"]`);
    if (navBtn) navBtn.classList.add('active');

    // Toggle padding on content area for full-screen iframes (skip native calendar)
    const contentArea = document.querySelector('.content');
    if (contentArea) {
        if (tab.startsWith('ext-') && tab !== 'ext-calendar' && tab !== 'ext-agents' && tab !== 'ext-browser' && tab !== 'ext-cloud-keys') contentArea.classList.add('no-padding');
        else contentArea.classList.remove('no-padding');
    }

    // Switch tab panels
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    const panel = document.getElementById('tab-' + tab);
    if (panel) panel.classList.add('active');

    // Close extension detail overlay if switching main tabs
    closeExtDetail();

    // Lazy-load iframes: only set src when first activated
    if (tab.startsWith('ext-')) {
        const iframe = panel?.querySelector('iframe.ext-iframe[data-src]');
        if (iframe && (!iframe.getAttribute('src') || iframe.getAttribute('src') === '')) {
            const container = iframe.parentElement;
            
            // Add loading spinner UI
            const loader = document.createElement('div');
            loader.className = 'iframe-loader';
            loader.innerHTML = '<div class="iframe-loader-spinner"></div><div style="color:var(--text-muted); font-size: 0.9rem; font-weight: 500;">' + (typeof window.T === "function" ? window.T("app.loading_ext") : "Initializing Extension...") + '</div>';
            container.appendChild(loader);
            
            iframe.style.opacity = '0';
            
            iframe.onload = () => {
                iframe.style.opacity = '1';
                loader.style.opacity = '0';
                setTimeout(() => {
                    if (loader.parentNode) loader.parentNode.removeChild(loader);
                }, 300);
                window.syncThemeToIframe(iframe);
            };
            const rawSrc = iframe.getAttribute('data-src');
            iframe.src = rawSrc + (rawSrc.includes('?') ? '&' : '?') + 't=' + Date.now();
        }
    }

    // Tab-specific loading
    if (tab === 'dashboard') loadDashboard();
    else if (tab === 'extensions') loadExtensions();
    else if (tab === 'api-manager') loadApiManagerPage();
    else if (tab === 'ext-calendar') {
        renderCalendarManagerExt(document.getElementById('calendar-ext-body'));
    }
    else if (tab === 'ext-agents') {
        renderAgentsExt(document.getElementById('agents-ext-body'));
    }
    else if (tab === 'ext-browser') {
        renderBrowserExt(document.getElementById('browser-ext-body'));
    }
    else if (tab === 'ext-cloud-keys') {
        renderCloudApiExt(document.getElementById('cloud-keys-ext-body'));
    }
}

// Sidebar click → navigate via hash
document.querySelectorAll('.nav-item').forEach(btn => {
    btn.addEventListener('click', () => {
        navigateTo(btn.dataset.tab);
    });
});

// Listen for hash changes (back/forward)
window.addEventListener('hashchange', handleRoute);

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
    // ── Phase 1: Fast data (stats) ── load immediately
    const [agents, profiles, skills, extensions, wfs, keysData] = await Promise.all([
        apiGet('/api/v1/agents'), apiGet('/api/v1/browser/profiles'),
        apiGet('/api/v1/skills'), apiGet('/api/v1/extensions'),
        apiGet('/api/v1/workflows'), apiGet('/api/v1/cloud-api/keys'),
    ]);
    document.getElementById('stat-agents').textContent = agents?.agents?.length ?? 0;
    document.getElementById('stat-profiles').textContent = profiles?.profiles?.length ?? 0;
    document.getElementById('stat-skills').textContent = skills?.skills?.length ?? 0;
    document.getElementById('stat-workflows').textContent = wfs?.workflows?.length ?? 0;
    document.getElementById('stat-extensions').textContent = extensions?.count ?? 0;
    let keyCount = 0;
    if (keysData?.keys) Object.values(keysData.keys).forEach(labels => { keyCount += Object.keys(labels).length; });
    document.getElementById('stat-api-keys').textContent = keyCount;
    document.getElementById('status-api-dot').style.color = 'var(--green)';
    document.getElementById('status-api-label').className = 'tag green';
    document.getElementById('status-api-label').textContent = T('status.online');

    // ── Phase 2: Slow status checks ── run in background, non-blocking
    _checkStatusesInBackground();
}

function _checkStatusesInBackground() {
    // Ollama
    apiGet('/api/v1/ollama/status').then(ollamaStatus => {
        if (ollamaStatus?.running) {
            document.getElementById('status-ollama-dot').style.color = 'var(--green)';
            document.getElementById('status-ollama-label').className = 'tag green';
            document.getElementById('status-ollama-label').textContent = `${T('status.online')} (${ollamaStatus.model_count} ${T('status.models')})`;
        } else {
            document.getElementById('status-ollama-dot').style.color = 'var(--red)';
            document.getElementById('status-ollama-label').className = 'tag';
            document.getElementById('status-ollama-label').textContent = T('status.offline');
        }
    }).catch(() => {
        document.getElementById('status-ollama-dot').style.color = 'var(--red)';
        document.getElementById('status-ollama-label').className = 'tag';
        document.getElementById('status-ollama-label').textContent = T('status.offline');
    });

    // Browser
    apiGet('/api/v1/browser/status').then(browserStatus => {
        const runCount = browserStatus?.instances?.length ?? 0;
        document.getElementById('status-browser-dot').style.color = runCount > 0 ? 'var(--green)' : 'var(--text-muted)';
        document.getElementById('status-browser-label').className = runCount > 0 ? 'tag green' : 'tag';
        document.getElementById('status-browser-label').textContent = runCount > 0 ? `${runCount} ${T('status.running')}` : T('status.idle');
    }).catch(() => {});

    // 9Router
    apiGet('/api/v1/cloud-api/9router/status').then(nrStatus => {
        if (nrStatus?.running) {
            document.getElementById('status-9router-dot').style.color = 'var(--green)';
            document.getElementById('status-9router-label').className = 'tag green';
            document.getElementById('status-9router-label').textContent = `${T('status.online')} (${nrStatus.model_count} models)`;
        } else {
            document.getElementById('status-9router-dot').style.color = 'var(--red)';
            document.getElementById('status-9router-label').className = 'tag';
            document.getElementById('status-9router-label').textContent = T('status.offline');
        }
    }).catch(() => {
        document.getElementById('status-9router-dot').style.color = 'var(--red)';
        document.getElementById('status-9router-label').className = 'tag';
        document.getElementById('status-9router-label').textContent = T('status.offline');
    });
}

// ═══════════════════════════════════════════════════════════
// ═══ EXTENSIONS (All features as clickable cards) ═══
// ═══════════════════════════════════════════════════════════
const EXT_REGISTRY = [
    // core: always in nav, not groupable
    { id:'agents',    tab:'ext-agents',   icon:'smart_toy',  name:'nav.dashboard', type:'core' },
    { id:'browser',   tab:'ext-browser',  icon:'public',     name:'stat.profiles', type:'core' },
    { id:'workflows', tab:'workflows',    icon:'sync',       name:'stat.workflows',type:'core' },
    { id:'skills',    tab:'skills',       icon:'bolt',       name:'stat.skills',   type:'core' },
    { id:'market',    tab:'ext-market',   icon:'storefront', name:'Marketplace',   type:'core' },
    // extension: shown when API enabled, groupable
    { id:'cloud_api',          tab:'ext-cloud-keys',         icon:'cloud',          name:'dash.cloud_api_keys', type:'extension' },
    { id:'ollama',             tab:'ext-ollama',             icon:'🧠',             name:'Ollama Manager',      type:'extension' },
    { id:'multi_agents',       tab:'ext-teams',              icon:'groups',         name:'Teams AI',            type:'extension' },
    { id:'video_downloader',   tab:'ext-downloader',         icon:'download',       name:'Douyin Download',     type:'extension' },
    { id:'video_editor',       tab:'ext-video-editor',       icon:'video_settings', name:'Video Editor',        type:'extension' },
    { id:'video_manager',      tab:'ext-video-manager',      icon:'video_library',  name:'Video Manager',       type:'extension' },
    { id:'subtitle_extractor', tab:'ext-subtitle-extractor', icon:'subtitles',      name:'Subtitle Extractor',  type:'extension' },
    { id:'sheets_manager',     tab:'ext-sheets',             icon:'table_chart',    name:'Google Sheets',       type:'extension' },
    { id:'calendar_manager',   tab:'ext-calendar',           icon:'calendar_month', name:'Calendar Manager',    type:'extension' },
    { id:'web_crawler',        tab:'ext-web-crawler',        icon:'travel_explore', name:'Web Crawler',         type:'extension' },
    { id:'livestream',         tab:'ext-livestream',         icon:'cast',           name:'Livestream',          type:'extension' },
    { id:'ai_arena',           tab:'ext-ai-arena',           icon:'sports_esports', name:'AI Arena',            type:'extension' },
    // static: always shown, groupable (no API gate)
    { id:'story_engine',    tab:'ext-story',        icon:'movie',      name:'Story Engine',    type:'static' },
    { id:'studio_3d',       tab:'ext-studio',       icon:'palette',    name:'3D Studio',       type:'static' },
    { id:'content_tracker', tab:'ext-tracker',      icon:'monitoring', name:'Content Tracker', type:'static' },
    { id:'file_browser',    tab:'ext-file-manager', icon:'folder',     name:'Files',           type:'static' },
];

// ── IDs that cannot be grouped (core nav) ──
const CORE_NAV_IDS = new Set(['agents','browser','workflows','skills','market',
    'dashboard','extensions','api_manager','auth_manager','cloud_keys','marketplace']);

/**
 * buildSidebar(extensions, groups)
 * - extensions: array from /api/v1/extensions
 * - groups:     array of {id, name, icon, extensions:[extId,...]}
 * 
 * Strategy:
 *   All extension buttons live in #ext-btn-pool (hidden).
 *   This function moves them into #ext-nav-zone (or group containers).
 *   Dynamic external extensions get new buttons created on the fly.
 *   No hardcoded lists — pool buttons have data-ext, static ones have data-ext-static.
 */
function buildSidebar(extensions, groups) {
    const pool    = document.getElementById('ext-btn-pool');
    const navZone = document.getElementById('ext-nav-zone');
    if (!pool || !navZone) return;

    // 1. Return ALL current children of navZone back to pool (reset)
    //    Also remove sidebar-group wrappers
    Array.from(navZone.children).forEach(el => pool.appendChild(el));
    navZone.querySelectorAll('.sidebar-group').forEach(el => el.remove());

    // 2. Build lookup maps
    const enabledSet = new Set();
    const extApiMap  = {};
    extensions.forEach(e => { extApiMap[e.name] = e; if (e.enabled) enabledSet.add(e.name); });
    allAvailableExtensions = extensions; // keep global in sync

    // 3. Handle non-nav ext-conditional elements (quick-action cards etc.)
    document.querySelectorAll('.ext-conditional[data-ext]').forEach(el => {
        if (!el.classList.contains('nav-item') || !pool.contains(el)) {
            el.style.display = enabledSet.has(el.dataset.ext) ? '' : 'none';
        }
    });

    // 4. Collect ordered list of items to place in sidebar
    //    Each item: { extId, btn } — order preserved from pool DOM order first,
    //    then dynamic API extensions at the end
    const items = [];
    const seenExtIds = new Set(); // track extIds already added (some have multiple buttons e.g. video_editor)

    // 4a. Pool buttons (built-in/static) — in DOM order
    pool.querySelectorAll('.nav-item[data-ext]').forEach(btn => {
        const extId   = btn.dataset.ext;
        const isStatic = btn.dataset.extStatic === 'true';
        if (!isStatic && !enabledSet.has(extId)) return; // optional ext not installed
        items.push({ extId, btn });
        seenExtIds.add(extId);
    });

    // 4b. Dynamic external extensions from API (not in pool, not core)
    extensions.forEach(ext => {
        if (!ext.enabled) return;
        if (CORE_NAV_IDS.has(ext.name)) return;
        if (seenExtIds.has(ext.name)) return; // handled by pool already
        const reg = EXT_REGISTRY.find(r => r.id === ext.name);
        if (reg && (reg.type === 'core' || reg.type === 'static')) return;
        // Only show: external extensions (installed by user) that have a display_name
        // Skip internal/system extensions (webui, file_manager, dash.*, etc.)
        if (ext.extension_type !== 'external') return;
        if (!ext.display_name) return; // no display name = internal/unregistered, skip

        const tabId = 'ext-' + ext.name;
        let btn = pool.querySelector(`[data-tab="${tabId}"]`) ||
                  navZone.querySelector(`[data-tab="${tabId}"]`) ||
                  document.querySelector(`[data-tab="${tabId}"].nav-item:not([data-tab="ext-agents"]):not([data-tab="ext-browser"])`);

        if (!btn || btn.closest('#ext-btn-pool') === null && btn.closest('#ext-nav-zone') === null) {
            // Create new button
            btn = document.createElement('button');
            btn.className = 'nav-item';
            btn.dataset.tab = tabId;
            btn.dataset.ext = ext.name;
            const regInfo = EXT_REGISTRY.find(r => r.id === ext.name) || {};
            const iconHtml = renderExtIcon(ext.icon || regInfo.icon);
            const label = ext.display_name || regInfo.name || ext.name;
            btn.innerHTML = `<span class="nav-icon" style="display:flex;align-items:center;">${iconHtml}</span> <span class="nav-text">${esc(label)}</span>`;
            btn.addEventListener('click', () => navigateTo(tabId));
            pool.appendChild(btn); // add to pool so it can be moved
        }

        // Ensure iframe panel exists
        if (ext.page_url && !document.getElementById('tab-' + tabId)) {
            const panel = document.createElement('section');
            panel.className = 'tab-panel';
            panel.id = 'tab-' + tabId;
            panel.innerHTML = `<div class="iframe-container"><iframe data-src="${ext.page_url}" class="ext-iframe"></iframe></div>`;
            document.querySelector('.content').appendChild(panel);
        }

        items.push({ extId: ext.name, btn });
        seenExtIds.add(ext.name);
    });

    // 5. Build group containers (only for groups with ≥1 visible item)
    const extToGroup = {};
    groups.forEach(g => (g.extensions || []).forEach(id => { extToGroup[id] = g.id; }));

    const groupContainers = {};
    const orderedGroupIds = [];
    groups.forEach(g => {
        const hasItem = items.some(i => extToGroup[i.extId] === g.id);
        if (!hasItem) return;
        orderedGroupIds.push(g.id);

        const gDiv = document.createElement('div');
        gDiv.className = 'sidebar-group expanded';
        gDiv.dataset.groupId = g.id;
        gDiv.innerHTML = `
            <div class="sidebar-group-header" onclick="this.closest('.sidebar-group').classList.toggle('expanded')">
                <div class="sidebar-group-header-left">
                    <span style="display:flex;align-items:center;font-size:18px;">${renderGroupIcon(g.icon)}</span>
                    <span>${esc(g.name)}</span>
                </div>
                <span class="material-symbols-outlined sidebar-group-chevron">expand_more</span>
            </div>
            <div class="sidebar-group-items"></div>`;
        navZone.appendChild(gDiv);
        groupContainers[g.id] = gDiv.querySelector('.sidebar-group-items');
    });

    // 6. Place items: grouped → into group container, ungrouped → into navZone
    items.forEach(({ extId, btn }) => {
        const gId   = extToGroup[extId];
        const target = gId && groupContainers[gId] ? groupContainers[gId] : navZone;
        target.appendChild(btn);
    });

    // 7. Re-attach click handler for pool buttons that navigateTo
    pool.querySelectorAll('.nav-item[data-tab]').forEach(btn => {
        if (!btn._sidebarListenerAttached) {
            btn.addEventListener('click', () => navigateTo(btn.dataset.tab));
            btn._sidebarListenerAttached = true;
        }
    });
}


async function loadExtensions() {
    const extensionData = await apiGet('/api/v1/extensions');
    const extensions = extensionData?.extensions || [];
    const extensionMap = {};
    extensions.forEach(p => { extensionMap[p.name] = p; });
    const grid = document.getElementById('extensions-grid');

    // ── Update Banner ──
    let bannerHtml = '';
    const cachedUpdates = _extUpdateCache;
    if (cachedUpdates && cachedUpdates.length > 0) {
        bannerHtml = `<div style="background:linear-gradient(135deg,rgba(245,158,11,0.12),rgba(59,130,246,0.08));border:1px solid rgba(245,158,11,0.3);border-radius:14px;padding:16px 20px;margin-bottom:20px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px">
            <div style="display:flex;align-items:center;gap:12px">
                <span style="font-size:1.5rem">⬆️</span>
                <div>
                    <div style="font-weight:600;color:var(--text);font-size:0.95rem">${cachedUpdates.length} extension${cachedUpdates.length>1?'s':''} có bản cập nhật mới</div>
                    <div style="font-size:0.78rem;color:var(--text-muted);margin-top:2px">${cachedUpdates.map(u=>''+esc(u.display_name||u.name)+' (v'+esc(u.local_version)+' → v'+esc(u.market_version)+')').join(' · ')}</div>
                </div>
            </div>
            <div style="display:flex;gap:8px;flex-wrap:wrap">
                ${cachedUpdates.map(u => '<button class="btn-sm btn-primary" onclick="event.stopPropagation();doExtensionUpdate(\''+esc(u.name)+'\',\''+esc(u.public_id)+'\',\''+esc(u.git_url||'')+'\',this)" style="padding:6px 14px;border-radius:8px;font-size:0.8rem">⬆️ '+esc(u.display_name||u.name)+'</button>').join('')}<button class="btn-sm" onclick="event.stopPropagation();dismissAllExtUpdates()" style="padding:5px 10px;border-radius:8px;font-size:0.72rem;background:rgba(239,68,68,0.08);border-color:rgba(239,68,68,0.25);color:rgba(239,130,130,0.85)">🚫 Tắt</button>
            </div>
        </div>`;
    }

    // Render built-in/known extensions from EXT_REGISTRY
    let cards = EXT_REGISTRY.map(ext => {
        const extension = extensionMap[ext.id];
        const version = extension?.version || '-';
        const isEnabled = extension ? extension.enabled : true;
        const isExternal = extension?.extension_type === 'external';
        const displayType = isExternal ? 'external' : ext.type;
        const tagClass = displayType === 'core' ? 'green' : 'blue';
        const hasUpdate = cachedUpdates && cachedUpdates.find(u => (u.name||'').toLowerCase().replace(/ /g,'_') === (ext.id||'').toLowerCase().replace(/ /g,'_'));

        let footerHtml = `<span class="tag ${tagClass}">${displayType}</span>`;
        if (hasUpdate) {
            footerHtml += `<span class="tag" style="background:rgba(245,158,11,0.2);color:#f59e0b;border:1px solid rgba(245,158,11,0.3)">⬆️ Update</span>`;
        }
        if (isExternal && extension) {
            footerHtml += `
                <button class="${isEnabled ? 'btn-disable' : 'btn-enable'}"
                    onclick="event.stopPropagation();toggleExternalExt('${esc(ext.id)}',${isEnabled})">
                    ${isEnabled ? 'Disable' : 'Enable'}
                </button>
                <button class="btn-uninstall"
                    onclick="event.stopPropagation();uninstallExternalExt('${esc(ext.id)}')">
                    Uninstall
                </button>`;
        }

        let updateBtnHtml = '';
        if (hasUpdate) {
            updateBtnHtml = `
            <div style="margin: 6px 0 10px 0;">
                <button class="btn-ext-update-inline"
                    onclick="event.stopPropagation(); doExtensionUpdate('${esc(ext.id)}', '${esc(hasUpdate.public_id || '')}', '${esc(hasUpdate.git_url || '')}', this)">
                    ⬆️ Cập nhật ngay
                </button>
            </div>`;
        }

        return `<div class="card ext-card" onclick="openExtDetail('${ext.id}')" style="${!isEnabled ? 'opacity:0.5' : ''}">
            <div class="card-icon">${renderExtIcon(ext.icon, 32)}</div>
            <h3>${esc(T(ext.name))}</h3>
            <p class="card-meta">v${esc(version)} · ${esc(displayType)}</p>
            ${updateBtnHtml}
            <p class="card-desc">${esc(T(ext.desc))}</p>
            <div class="card-footer" style="margin-top:10px;gap:8px">${footerHtml}</div>
        </div>`;
    }).join('');

    // Also render external extensions not in EXT_REGISTRY (installed from market/git)
    extensions.forEach(ext => {
        const inRegistry = EXT_REGISTRY.some(e => e.id === ext.name);
        if (!inRegistry && ext.extension_type === 'external') {
            const isEnabled = ext.enabled;
            const hasUpdate = cachedUpdates && cachedUpdates.find(u => (u.name||'').toLowerCase().replace(/ /g,'_') === (ext.name||'').toLowerCase().replace(/ /g,'_'));
            const updateTag = hasUpdate ? '<span class="tag" style="background:rgba(245,158,11,0.2);color:#f59e0b;border:1px solid rgba(245,158,11,0.3)">⬆️ Update</span>' : '';
            
            let updateBtnHtml = '';
            if (hasUpdate) {
                updateBtnHtml = `
                <div style="margin: 6px 0 10px 0;">
                    <button class="btn-ext-update-inline"
                        onclick="event.stopPropagation(); doExtensionUpdate('${esc(ext.name)}', '${esc(hasUpdate.public_id || '')}', '${esc(hasUpdate.git_url || '')}', this)">
                        ⬆️ Cập nhật ngay
                    </button>
                </div>`;
            }

            cards += `<div class="card ext-card" onclick="openExternalExtDetail('${esc(ext.name)}')" style="${!isEnabled ? 'opacity:0.5' : ''}">
                <div class="card-icon">${esc(ext.icon || '\ud83d\udce6')}</div>
                <h3>${esc(ext.name)}</h3>
                <p class="card-meta">v${esc(ext.version || '-')} · external</p>
                ${updateBtnHtml}
                <p class="card-desc">${esc(ext.description || '')}</p>
                <div class="card-footer" style="margin-top:10px;gap:8px">
                    <span class="tag blue">external</span>
                    ${updateTag}
                    <button class="${isEnabled ? 'btn-disable' : 'btn-enable'}"
                        onclick="event.stopPropagation();toggleExternalExt('${esc(ext.name)}',${isEnabled})">
                        ${isEnabled ? 'Disable' : 'Enable'}
                    </button>
                    <button class="btn-uninstall"
                        onclick="event.stopPropagation();uninstallExternalExt('${esc(ext.name)}')">
                        Uninstall
                    </button>
                </div>
            </div>`;
        }
    });

    grid.innerHTML = bannerHtml + cards;
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
    // Extensions with dedicated sidebar tabs → navigate via hash route
    const hashRoutes = {
        'market': 'ext-market',
        'agents': 'ext-agents',
        'browser': 'ext-browser',
        'web_crawler': 'ext-web-crawler',
        'sheets_manager': 'ext-sheets',
        'calendar_manager': 'ext-calendar',
        'downloader': 'ext-downloader',
        'multi_agents': 'ext-teams',
        'story_engine': 'ext-story',
        'video_editor': 'ext-video-editor',
        'file_manager': 'ext-file-manager',
        'studio3d': 'ext-studio',
        'video_manager': 'ext-video-manager',
        'subtitle_extractor': 'ext-subtitle-extractor',
        'cloud_api': 'ext-cloud-keys',
    };
    if (hashRoutes[id]) { navigateTo(hashRoutes[id]); return; }

    const ext = EXT_REGISTRY.find(e => e.id === id);
    if (!ext) return;
    const overlay = document.getElementById('ext-detail-overlay');
    const title = document.getElementById('ext-detail-title');
    const body = document.getElementById('ext-detail-body');
    const tabExt = document.getElementById('tab-extensions');
    if (tabExt) tabExt.style.display = 'none';

    title.textContent = ext.icon + ' ' + ext.name;
    body.innerHTML = `<p class="text-muted">${T('chat.loading')}</p>`;
    overlay.classList.remove('hidden');
    // Route to detail renderer
    stopBrowserStatusPoller();
    if (id === 'agents') renderAgentsExt(body);
    else if (id === 'browser') renderBrowserExt(body);
    else if (id === 'workflows') renderWorkflowsExt(body);
    else if (id === 'skills') renderSkillsExt(body);
    else if (id === 'cloud_api') renderCloudApiExt(body);
    else if (id === 'ollama') renderOllamaExt(body);
    else if (id === 'video_editor') renderFullPageExt(body, 'Video Editor', 'AI-powered Video Editor with Timeline & FFmpeg Processing.', '/video-editor');
}
function closeExtDetail() { 
    document.getElementById('ext-detail-overlay').classList.add('hidden'); 
    const tabExt = document.getElementById('tab-extensions');
    if (tabExt) tabExt.style.display = '';
}

function renderFullPageExt(el, name, desc, url) {
    el.innerHTML = `
        <div style="height:100%; min-height:80vh; overflow:hidden; position:relative; display:flex; flex-direction:column;">
            <div class="iframe-loader">
                <div class="iframe-loader-spinner"></div>
                <div style="color:var(--text-muted); font-size: 0.9rem; font-weight: 500;">${typeof window.T === "function" ? window.T("app.loading_ext") : "Initializing Extension..."}</div>
            </div>
            <iframe src="${url}" style="flex:1; width:100%; border:none; opacity:0; transition:opacity 0.3s"></iframe>
        </div>
    `;
    const iframe = el.querySelector('iframe');
    const loader = el.querySelector('.iframe-loader');
    iframe.onload = () => {
        iframe.style.opacity = '1';
        if (loader) {
            loader.style.opacity = '0';
            setTimeout(() => { if (loader.parentNode) loader.parentNode.removeChild(loader); }, 300);
        }
        window.syncThemeToIframe(iframe);
    };
}

// ── Calendar Manager Ext ──
let _calCredId = '';

async function renderCalendarManagerExt(el) {
    el.innerHTML = `<p class="text-muted">Đang tải Calendar Manager...</p>`;

    // Step 1: Load credentials
    let creds = [];
    try {
        const credRes = await apiGet('/api/v1/calendar/credentials');
        creds = credRes?.credentials || [];
    } catch(e) {}

    // If we have creds and no selection yet, use the first one
    if (creds.length > 0 && !_calCredId) _calCredId = creds[0].id;

    // Step 2: Load data with selected cred_id
    let calendars = [], events = [], reminderSettings = {};
    if (_calCredId) {
        try {
            const [calRes, evRes, remRes] = await Promise.all([
                apiGet(`/api/v1/calendar/calendars?cred_id=${_calCredId}`).catch(() => ({calendars:[]})),
                apiGet(`/api/v1/calendar/events?cred_id=${_calCredId}`).catch(() => ({events:[]})),
                apiGet('/api/v1/calendar/reminders/settings').catch(() => ({})),
            ]);
            calendars = calRes?.calendars || [];
            events = evRes?.events || [];
            reminderSettings = remRes || {};
        } catch(e) {}
    }

    const hasAuth = creds.length > 0;

    let h = '';

    // ── Account Selector (top-right, like Sheets Manager) ──
    h += `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:24px;flex-wrap:wrap;gap:15px">
        <div style="display:flex;align-items:center;gap:12px">
            <div class="ext-info-card" style="min-width:80px;padding:12px;background:var(--bg3);border:1px solid var(--border);border-radius:12px;text-align:center"><div class="info-value" style="font-size:1.4rem;font-weight:700;color:var(--cyan)">${calendars.length}</div><div class="info-label" style="font-size:0.75rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.5px">${T('cal.calendars', 'Calendars')}</div></div>
            <div class="ext-info-card" style="min-width:80px;padding:12px;background:var(--bg3);border:1px solid var(--border);border-radius:12px;text-align:center"><div class="info-value" style="font-size:1.4rem;font-weight:700;color:var(--green)">${events.length}</div><div class="info-label" style="font-size:0.75rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.5px">${T('cal.events', 'Events')}</div></div>
            <div class="ext-info-card" style="min-width:80px;padding:12px;background:var(--bg3);border:1px solid var(--border);border-radius:12px;text-align:center"><div class="info-value" style="font-size:1.4rem;font-weight:700;color:var(--purple)">${reminderSettings.minutes_before || 15}m</div><div class="info-label" style="font-size:0.75rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.5px">${T('cal.reminder', 'Reminder')}</div></div>
        </div>
        <div style="display:flex;align-items:center;gap:12px">
            <div style="position:relative">
                <select id="cal-cred-select" onchange="onCalCredChange()"
                    style="appearance:none;padding:12px 36px 12px 16px;border:1px solid var(--border);border-radius:10px;background:var(--bg2);color:var(--text);font-size:.95rem;font-weight:500;min-width:220px;cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,0.1)">
                    ${creds.length === 0
                        ? '<option value="">⚠️ Chưa có tài khoản auth</option>'
                        : creds.map(c => `<option value="${esc(c.id)}" ${c.id === _calCredId ? 'selected' : ''}>${esc(c.name)}${c.email ? ' (' + esc(c.email) + ')' : ''}</option>`).join('')
                    }
                </select>
                <div style="position:absolute;right:14px;top:50%;transform:translateY(-50%);pointer-events:none;color:var(--text-muted)">▼</div>
            </div>
            <button class="btn-sm" style="padding:12px;border-radius:10px;background:var(--bg3);border:1px solid var(--border);transition:all 0.2s" onclick="renderCalendarManagerExt(document.getElementById('ext-detail-body'))" title="Refresh" onmouseover="this.style.background='var(--bg2)'" onmouseout="this.style.background='var(--bg3)'">🔄</button>
        </div>
    </div>`;

    if (!hasAuth) {
        h += `<div style="background:linear-gradient(135deg,rgba(239,68,68,0.1),rgba(245,158,11,0.1));border:1px solid rgba(239,68,68,0.3);border-radius:16px;padding:32px;margin-bottom:24px;text-align:center;box-shadow:0 8px 24px rgba(0,0,0,0.1)">
            <div style="font-size:56px;margin-bottom:16px;filter:drop-shadow(0 4px 8px rgba(0,0,0,0.2))">🔐</div>
            <h3 style="color:var(--text);margin-bottom:12px;font-size:1.4rem">${T('cal.no_auth_title', 'Chưa xác thực Google Calendar')}</h3>
            <p style="color:var(--text-muted);margin-bottom:24px;font-size:1rem;max-width:500px;margin-left:auto;margin-right:auto;line-height:1.5">${T('cal.no_auth_desc', 'Vào <strong>Auth Manager</strong> → Thêm Google OAuth credential với scope <code>calendar</code> → Authorize email của bạn để cấp quyền.')}</p>
        </div>`;
    }

    // Wrap in a 2-column grid layout for modern UI
    h += `<div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(450px, 1fr));gap:24px;align-items:start">`;

    // ── LEFT COLUMN (Events & Reminders) ──
    h += `<div style="display:flex;flex-direction:column;gap:24px">`;

    // ── Events List ──
    h += `<div style="background:var(--bg3);border-radius:16px;padding:24px;border:1px solid var(--border);box-shadow:0 4px 12px rgba(0,0,0,0.05)">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;border-bottom:1px solid rgba(255,255,255,0.05);padding-bottom:12px">
            <h3 style="color:var(--cyan);margin:0;font-size:1.2rem;display:flex;align-items:center;gap:8px"><span style="font-size:1.4rem">📋</span> ${T('cal.upcoming_events', 'Sự kiện sắp tới')}</h3>
        </div>`;

    if (events.length === 0) {
        h += `<div style="text-align:center;padding:40px 20px;background:var(--bg);border-radius:12px;border:1px dashed var(--border)">
            <div style="font-size:2rem;margin-bottom:12px;opacity:0.5">📭</div>
            <p class="text-muted" style="margin:0">${T('cal.no_events_7_days', 'Không có sự kiện nào trong 7 ngày tới.')}</p>
            </div>`;
    } else {
        h += `<div style="display:flex;flex-direction:column;gap:12px;max-height:500px;overflow-y:auto;padding-right:8px" class="custom-scrollbar">`;
        events.forEach(ev => {
            let timeStr = ev.start || '';
            try {
                const dt = new Date(ev.start);
                timeStr = dt.toLocaleString('vi-VN', {weekday:'short', day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit'});
            } catch(e) {}
            const hasRecurrence = ev.recurrence && ev.recurrence.length > 0;
            h += `<div style="display:flex;align-items:center;gap:16px;padding:16px;background:var(--bg2);border-radius:12px;border:1px solid var(--border);transition:transform 0.2s, box-shadow 0.2s" onmouseover="this.style.transform='translateY(-2px)';this.style.boxShadow='0 4px 12px rgba(0,0,0,0.1)'" onmouseout="this.style.transform='none';this.style.boxShadow='none'">
                <div style="font-size:1.8rem;background:rgba(255,255,255,0.05);padding:10px;border-radius:12px">${hasRecurrence ? '🔄' : '📅'}</div>
                <div style="flex:1;min-width:0">
                    <div style="font-weight:600;font-size:1.05rem;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-bottom:4px">${esc(ev.summary || '(No title)')}</div>
                    <div style="font-size:.85rem;color:var(--text-muted);display:flex;align-items:center;gap:6px">
                        <span style="display:inline-block;padding:2px 8px;background:rgba(0,0,0,0.2);border-radius:4px">${esc(timeStr)}</span>
                        ${ev.location ? `<span style="opacity:0.5">•</span> <span style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:150px" title="${esc(ev.location)}">📍 ${esc(ev.location)}</span>` : ''}
                    </div>
                </div>
                <button class="btn-sm btn-danger" onclick="calDeleteEvent('${esc(ev.id)}')" style="width:36px;height:36px;padding:0;border-radius:50%;display:flex;align-items:center;justify-content:center;opacity:0.7;transition:opacity 0.2s" onmouseover="this.style.opacity='1'" onmouseout="this.style.opacity='0.7'">✕</button>
            </div>`;
        });
        h += `</div>`;
    }
    h += `</div>`; // End Events

    // ── Reminder Settings ──
    h += `<div style="background:var(--bg3);border-radius:16px;padding:24px;border:1px solid var(--border);box-shadow:0 4px 12px rgba(0,0,0,0.05)">
        <h3 style="color:var(--yellow);margin-bottom:16px;font-size:1.2rem;display:flex;align-items:center;gap:8px"><span style="font-size:1.4rem">🔔</span> ${T('cal.telegram_settings', 'Cài đặt nhắc nhở Telegram')}</h3>
        <div style="display:flex;gap:16px;align-items:flex-end;background:var(--bg2);padding:16px;border-radius:12px;border:1px solid var(--border)">
            <div style="flex:1">
                <label style="display:block;margin-bottom:8px;font-size:.85rem;font-weight:600;color:var(--text-muted);text-transform:uppercase">${T('cal.remind_before_min', 'Nhắc trước (phút)')}</label>
                <div style="position:relative">
                    <input id="cal-reminder-min" type="number" value="${reminderSettings.minutes_before || 15}" min="1" max="1440"
                        style="width:100%;padding:12px 16px;border:1px solid var(--border);border-radius:8px;background:var(--bg);color:var(--text);font-size:1.1rem;font-weight:600">
                    <span style="position:absolute;right:16px;top:50%;transform:translateY(-50%);color:var(--text-muted);pointer-events:none">phút</span>
                </div>
            </div>
            <button class="btn-primary" onclick="calSaveReminder()" style="padding:12px 24px;border-radius:8px;font-weight:600;display:flex;align-items:center;gap:8px;height:47px"><span>💾</span> ${T('cal.save_settings', 'Lưu cài đặt')}</button>
        </div>
    </div>`;

    h += `</div>`; // End Left Column


    // ── RIGHT COLUMN (Forms) ──
    h += `<div style="display:flex;flex-direction:column;gap:24px">`;

    // ── Quick Add ──
    h += `<div style="background:var(--bg3);border-radius:16px;padding:24px;border:1px solid var(--border);box-shadow:0 4px 12px rgba(0,0,0,0.05);position:relative;overflow:hidden">
        <div style="position:absolute;top:-10px;right:-10px;font-size:100px;opacity:0.02;pointer-events:none transform:rotate(15deg)">⚡</div>
        <h3 style="color:var(--cyan);margin-bottom:16px;font-size:1.2rem;display:flex;align-items:center;gap:8px;position:relative"><span style="font-size:1.4rem">⚡</span> ${T('cal.quick_add_title', 'Quick Add Event')}</h3>
        <p style="color:var(--text-muted);font-size:0.9rem;margin-bottom:16px;position:relative">${T('cal.quick_add_desc', 'Sử dụng ngôn ngữ tự nhiên để thêm sự kiện siêu tốc.')}</p>
        <div style="display:flex;flex-direction:column;gap:12px;position:relative">
            <input id="cal-quick-text" type="text" placeholder='${T('cal.quick_add_placeholder', 'Ví dụ: "Meeting chiều mai 2h", "Livestream tiktok mỗi 8h tối"')}'
                style="width:100%;padding:14px 16px;border:1px solid rgba(6,182,212,0.3);border-radius:10px;background:var(--bg);color:var(--text);font-size:1rem;transition:all 0.2s"
                onfocus="this.style.borderColor='var(--cyan)';this.style.boxShadow='0 0 0 2px rgba(6,182,212,0.1)'"
                onblur="this.style.borderColor='rgba(6,182,212,0.3)';this.style.boxShadow='none'"
                onkeydown="if(event.key==='Enter')calQuickAdd()">
            <button class="btn-primary" onclick="calQuickAdd()" style="padding:14px;border-radius:10px;font-weight:600;display:flex;align-items:center;justify-content:center;gap:8px;background:linear-gradient(135deg, var(--cyan), #0284c7)"><span>✨</span> ${T('cal.quick_add_btn', 'Thêm thông minh')}</button>
        </div>
        <div id="cal-quick-result" style="margin-top:16px;display:none;padding:12px 16px;border-radius:8px;background:var(--bg);font-size:.95rem;font-weight:500;text-align:center"></div>
    </div>`;

    // ── Create Event Form ──
    h += `<div style="background:var(--bg3);border-radius:16px;padding:24px;border:1px solid var(--border);box-shadow:0 4px 12px rgba(0,0,0,0.05)">
        <h3 style="color:var(--purple);margin-bottom:20px;font-size:1.2rem;display:flex;align-items:center;gap:8px;border-bottom:1px solid rgba(255,255,255,0.05);padding-bottom:12px"><span style="font-size:1.4rem">📝</span> ${T('cal.create_event_title', 'Tạo sự kiện chi tiết')}</h3>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
            <div style="grid-column:span 2">
                <label style="display:block;margin-bottom:6px;font-size:.85rem;font-weight:600;color:var(--text-muted)">${T('cal.event_name', 'Tên sự kiện *')}</label>
                <input id="cal-summary" type="text" placeholder="${T('cal.event_name_placeholder', 'Livestream tối, Meeting kế hoạch...')}"
                    style="width:100%;padding:12px 16px;border:1px solid var(--border);border-radius:8px;background:var(--bg);color:var(--text);font-size:.95rem">
            </div>
            <div>
                <label style="display:block;margin-bottom:6px;font-size:.85rem;font-weight:600;color:var(--text-muted)">${T('cal.start_time', 'Bắt đầu *')}</label>
                <input id="cal-start" type="datetime-local" style="width:100%;padding:12px 16px;border:1px solid var(--border);border-radius:8px;background:var(--bg);color:var(--text);font-size:.95rem"
                       onfocus="this.showPicker && this.showPicker()">
            </div>
            <div>
                <label style="display:block;margin-bottom:6px;font-size:.85rem;font-weight:600;color:var(--text-muted)">${T('cal.end_time', 'Kết thúc')}</label>
                <input id="cal-end" type="datetime-local" style="width:100%;padding:12px 16px;border:1px solid var(--border);border-radius:8px;background:var(--bg);color:var(--text);font-size:.95rem"
                       onfocus="this.showPicker && this.showPicker()">
            </div>
            <div style="grid-column:span 2">
                <label style="display:block;margin-bottom:6px;font-size:.85rem;font-weight:600;color:var(--text-muted)">${T('cal.description', 'Mô tả chi tiết')}</label>
                <textarea id="cal-desc" placeholder="${T('cal.desc_placeholder', 'Agenda buổi meeting, link zoom...')}" rows="3"
                    style="width:100%;padding:12px 16px;border:1px solid var(--border);border-radius:8px;background:var(--bg);color:var(--text);font-size:.95rem;resize:vertical;font-family:inherit"></textarea>
            </div>
            <div>
                <label style="display:block;margin-bottom:6px;font-size:.85rem;font-weight:600;color:var(--text-muted)">${T('cal.recurring', 'Lặp lại (Recurring)')}</label>
                <div style="position:relative">
                    <select id="cal-recurrence" style="appearance:none;width:100%;padding:12px 36px 12px 16px;border:1px solid var(--border);border-radius:8px;background:var(--bg);color:var(--text);font-size:.95rem;cursor:pointer">
                        <option value="">${T('cal.rec_none', 'Không lặp lại')}</option>
                        <option value="RRULE:FREQ=DAILY">${T('cal.rec_daily', '🔄 Hằng ngày')}</option>
                        <option value="RRULE:FREQ=WEEKLY">${T('cal.rec_weekly', '🔄 Hằng tuần')}</option>
                        <option value="RRULE:FREQ=MONTHLY">${T('cal.rec_monthly', '🔄 Hằng tháng')}</option>
                        <option value="RRULE:FREQ=DAILY;COUNT=30">${T('cal.rec_daily_30', '🔄 Hằng ngày (30 ngày)')}</option>
                        <option value="RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR">${T('cal.rec_weekly_246', '🔄 T2, T4, T6')}</option>
                    </select>
                    <div style="position:absolute;right:14px;top:50%;transform:translateY(-50%);pointer-events:none;color:var(--text-muted);font-size:0.8rem">▼</div>
                </div>
            </div>
            <div>
                <label style="display:block;margin-bottom:6px;font-size:.85rem;font-weight:600;color:var(--text-muted)">${T('cal.location', 'Địa điểm / Nền tảng')}</label>
                <input id="cal-location" type="text" placeholder="${T('cal.location_placeholder', 'Google Meet, Tiktok...')}"
                    style="width:100%;padding:12px 16px;border:1px solid var(--border);border-radius:8px;background:var(--bg);color:var(--text);font-size:.95rem">
            </div>
        </div>
        <button class="btn-primary" onclick="calCreateEvent()" style="margin-top:24px;width:100%;padding:14px;font-weight:600;font-size:1.05rem;border-radius:10px;display:flex;align-items:center;justify-content:center;gap:8px;background:linear-gradient(135deg, var(--purple), #be185d)"><span>📅</span> ${T('cal.save_event', 'Lưu sự kiện')}</button>
        <div id="cal-create-result" style="margin-top:16px;display:none;padding:12px 16px;border-radius:8px;background:var(--bg);font-size:.95rem;font-weight:500;text-align:center"></div>
    </div>`;

    h += `</div>`; // End Right Column

    h += `</div>`; // End Grid Wrapper

    el.innerHTML = h;
}

// Calendar Manager — credential change handler
function onCalCredChange() {
    _calCredId = document.getElementById('cal-cred-select')?.value || '';
    renderCalendarManagerExt(document.getElementById('ext-detail-body'));
}

// Calendar Manager JS actions
async function calQuickAdd() {
    const text = document.getElementById('cal-quick-text')?.value?.trim();
    if (!text) { alert('Nhập mô tả sự kiện!'); return; }
    const res = document.getElementById('cal-quick-result');
    res.style.display = 'block';
    res.innerHTML = '<span style="color:var(--cyan)">⏳ Đang thêm...</span>';
    const r = await apiPost('/api/v1/calendar/quick-add', {text, cred_id: _calCredId});
    if (r?.status === 'success') {
        res.innerHTML = `<span style="color:var(--green)">✅ ${esc(r.message || 'Đã thêm!')}</span>`;
        document.getElementById('cal-quick-text').value = '';
        setTimeout(() => renderCalendarManagerExt(document.getElementById('ext-detail-body')), 1500);
    } else {
        res.innerHTML = `<span style="color:var(--red)">❌ ${esc(r?.detail || r?.message || 'Lỗi')}</span>`;
    }
}

async function calCreateEvent() {
    const summary = document.getElementById('cal-summary')?.value?.trim();
    const start = document.getElementById('cal-start')?.value;
    const end = document.getElementById('cal-end')?.value;
    const desc = document.getElementById('cal-desc')?.value?.trim();
    const recurrence = document.getElementById('cal-recurrence')?.value;
    const location = document.getElementById('cal-location')?.value?.trim();
    if (!summary || !start) { alert('Cần nhập tên sự kiện và thời gian bắt đầu!'); return; }
    const res = document.getElementById('cal-create-result');
    res.style.display = 'block';
    res.innerHTML = '<span style="color:var(--cyan)">⏳ Đang tạo...</span>';
    const startISO = new Date(start).toISOString();
    const endISO = end ? new Date(end).toISOString() : '';
    const body = {
        summary, start: startISO, end: endISO, description: desc, location,
        recurrence: recurrence ? [recurrence] : [],
        cred_id: _calCredId,
    };
    const r = await apiPost('/api/v1/calendar/events', body);
    if (r?.status === 'success') {
        res.innerHTML = `<span style="color:var(--green)">✅ ${esc(r.message || 'Đã tạo!')}</span>`;
        setTimeout(() => renderCalendarManagerExt(document.getElementById('ext-detail-body')), 1500);
    } else {
        res.innerHTML = `<span style="color:var(--red)">❌ ${esc(r?.detail || r?.message || 'Lỗi')}</span>`;
    }
}

async function calDeleteEvent(eventId) {
    if (!confirm('Xóa sự kiện này?')) return;
    const r = await apiDelete(`/api/v1/calendar/events/${encodeURIComponent(eventId)}?cred_id=${_calCredId}`);
    if (r?.status === 'success') {
        renderCalendarManagerExt(document.getElementById('ext-detail-body'));
    } else {
        alert('Lỗi: ' + (r?.detail || r?.message || '?'));
    }
}

async function calSaveReminder() {
    const min = parseInt(document.getElementById('cal-reminder-min')?.value) || 15;
    const r = await apiPut('/api/v1/calendar/reminders/settings', {minutes_before: min, enabled: true});
    if (r?.status === 'success') {
        alert('✅ Đã lưu cài đặt nhắc nhở!');
    } else {
        alert('Lỗi: ' + (r?.message || '?'));
    }
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
    else h += '<div class="cards-grid">' + agents.map(a => `<div class="card"><div class="card-icon">🤖</div><h3>${esc(a.name)}</h3><p class="card-meta">${esc(a.model||'default')}</p><p class="card-desc">${esc(a.description||'')}</p><div class="card-footer"><span class="tag">${(a.allowed_skills||[]).length} ${T('agents.skills_count')}</span><div class="card-actions"><button class="btn-sm btn-primary" onclick="openChatAgent('${a.id}','${esc(a.name)}')">${T('agents.chat')}</button><button class="btn-sm" onclick="openEditAgent('${a.id}')">${T('agents.edit')}</button><button class="btn-danger" onclick="deleteAgent('${a.id}');renderAgentsExt(getAgentsBody())">${T('agents.delete')}</button></div></div></div>`).join('') + '</div>';
    el.innerHTML = h;
}

// ── Browser Ext ──
function getBrowserBody() { return document.getElementById('browser-ext-body') || document.getElementById('ext-detail-body'); }
function getAgentsBody() { return document.getElementById('agents-ext-body') || document.getElementById('ext-detail-body'); }
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
        return `<div class="card" style="position:relative"><button class="btn-settings" onclick="showProfileSettings('${esc(p.name)}')" title="Settings">⚙️</button><div class="card-icon">🌐</div><h3>${esc(p.name)} ${isR ? '<span class="pulse-dot" style="display:inline-block"></span>' : ''}</h3><p class="card-meta">${esc(p.proxy||T('browser.no_proxy'))}</p><p class="card-desc">${p.has_fingerprint ? '🧬 FP OK' : `<span style="color:var(--orange)">⚠️ No FP</span>`} ${p.has_cookies ? '🍪' : ''} ${hasGA ? '<span style="color:var(--green)">🔐 ' + esc(p.google_account.email) + '</span>' : ''}</p><div class="card-footer" style="flex-wrap:wrap;gap:8px"><span class="tag green">${esc((p.created_at||'').slice(0,10))}</span><div class="card-actions">${isR ? `<button class="btn-sm btn-danger" onclick="stopProfile('${esc(p.name)}',this)">⏹</button>` : `<button class="btn-sm" onclick="launchProfile('${esc(p.name)}',this)">▶</button>`}<button class="btn-sm" onclick="showProfileCommand('${esc(p.name)}')" title="Run Command" style="background:linear-gradient(135deg,#8b5cf6,#06b6d4)">🚀</button><button class="btn-danger" onclick="deleteProfile('${esc(p.name)}');setTimeout(()=>renderBrowserExt(getBrowserBody()),500)">✕</button></div></div></div>`;
    }).join('') + '</div>';
    el.innerHTML = h;
}

// ── Workflows Ext ──
async function renderWorkflowsExt(el) {
    el.innerHTML = `<div style="height:calc(100vh - 150px);border:1px solid var(--border);border-radius:8px;overflow:hidden"><iframe src="/workflow?v=3" style="width:100%;height:100%;border:none" onload="window.syncThemeToIframe(this)"></iframe></div>`;
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
    const provIcons = { gemini:'✨', openai:'🤖', claude:'🧠', deepseek:'🔍', grok:'⚡', everai:'🎙️' };
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
            renderCloudApiExt(document.getElementById('cloud-keys-ext-body') || document.getElementById('ext-detail-body'));
        } else {
            alert(r.error || r.message || 'Lỗi khi lưu models.');
        }
    });
};

async function removeApiKeyExt(provider, label) { if (!confirm(`Remove "${label}" from ${provider}?`)) return; await apiDelete('/api/v1/cloud-api/keys', {provider,label}); renderCloudApiExt(document.getElementById('cloud-keys-ext-body') || document.getElementById('ext-detail-body')); }

// ── Ollama Ext ──
async function renderOllamaExt(el) {
    const [st, mdls, run] = await Promise.all([apiGet('/api/v1/ollama/status'), apiGet('/api/v1/ollama/models'), apiGet('/api/v1/ollama/running')]);
    const models = mdls?.models || [];
    const running = run?.running || [];
    const runNames = running.map(r => r.name);
    let h = `
    <div style="padding: 24px; max-width: 1200px; margin: 0 auto; box-sizing: border-box; width: 100%;">
        <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom: 24px;">
            <h2 style="margin:0; color:var(--text); font-size:1.8rem; font-weight:700;">🧠 Ollama Manager</h2>
        </div>
        <div class="ext-info-grid" style="margin-bottom:24px">
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
    h += `<div style="margin-top:16px;display:flex;gap:10px"><input id="ollama-pull-input" placeholder="e.g. qwen:latest" style="flex:1;padding:10px 14px;border:1px solid var(--border);border-radius:8px;background:var(--bg);color:var(--text)" autocomplete="off" spellcheck="false" data-lpignore="true"><button class="btn-primary" onclick="pullOllamaModel()">${T('ollama.pull')}</button><button class="btn-secondary" onclick="renderOllamaExt(document.getElementById('ext-detail-body'))">🔄</button></div>`;
    h += `</div>`; // Close padded container
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
function showInstallExtension() { document.getElementById('modal-install-ext').classList.remove('hidden'); document.getElementById('install-ext-url').value=''; const term = document.getElementById('install-ext-terminal'); if(term) { term.innerHTML=''; term.style.display='none'; } }
function installTermLog(msg, color = '#00ff00') { const term = document.getElementById('install-ext-terminal'); if (!term) return; term.style.display = 'block'; const div = document.createElement('div'); div.style.color = color; div.style.marginBottom = '4px'; div.textContent = '> ' + msg; term.appendChild(div); term.scrollTop = term.scrollHeight; }
async function installExtension() {
    const u = document.getElementById('install-ext-url').value.trim();
    if(!u) return alert('URL required.');
    const btn = document.getElementById('btn-install-ext');
    btn.disabled = true;
    btn.textContent = '⏳ Installing...';

    // Clear and show terminal
    const term = document.getElementById('install-ext-terminal');
    if(term) { term.innerHTML = ''; term.style.display = 'block'; }
    installTermLog('Initializing installation...', '#88aaff');

    const steps = [
        'Cloning Git repository (depth=1)...',
        'Validating tubecli-extension.json manifest...',
        'Resolving Python (PIP) dependencies if any...',
        'Resolving Node.js (NPM) dependencies if any...',
        'Loading extension module...'
    ];
    let stepIdx = 0;
    const termInterval = setInterval(() => {
        if (stepIdx < steps.length) {
            installTermLog(steps[stepIdx], '#aaaaaa');
            stepIdx++;
        }
    }, 1500);

    try {
        const r = await apiPost('/api/v1/market/items/install-git', {git_url: u});
        clearInterval(termInterval);

        if(r && r.status === 'success') {
            installTermLog('🎉 Installation Complete!', '#00ff00');
            if(r.message) installTermLog(r.message, '#00ff00');
            btn.textContent = '✅ Installed';
            btn.style.background = 'linear-gradient(135deg, #22c55e, #10b981)';
            setTimeout(() => {
                closeModal('modal-install-ext');
                loadExtensions();
                btn.disabled = false;
                btn.textContent = '🚀 Install';
                btn.style.background = '';
            }, 2000);
        } else {
            installTermLog('❌ Installation Failed: ' + (r?.message || 'Unknown error'), '#ff4444');
            btn.disabled = false;
            btn.textContent = '🚀 Install';
        }
    } catch(e) {
        clearInterval(termInterval);
        installTermLog('❌ Error: ' + e.message, '#ff4444');
        btn.disabled = false;
        btn.textContent = '🚀 Install';
    }
}

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
async function addApiKey() { const prov=document.getElementById('add-key-provider').value, key=document.getElementById('add-key-value').value.trim(), label=document.getElementById('add-key-label').value.trim()||'default'; if(!key) return alert('Key required.'); const r = await apiPost('/api/v1/cloud-api/keys',{provider:prov,api_key:key,label}); if(r&&r.status==='success') { closeModal('modal-add-key'); renderCloudApiExt(document.getElementById('cloud-keys-ext-body') || document.getElementById('ext-detail-body')); alert('Added!'); } else alert('Failed.'); }
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
    if (sel) {
        await loadEngineVersionsDropdown('profile-version', 'default');
    }
}

// ─── Shared helper: always fetch & populate an engine version <select> ───
async function loadEngineVersionsDropdown(selId, currentVersion) {
    const sel = document.getElementById(selId);
    if (!sel) return;
    const prev = sel.value || currentVersion || 'default';
    sel.innerHTML = '<option value="default">⏳ Loading...</option>';
    try {
        const r = await apiGet('/api/v1/browser/engine/versions');
        if (r && r.success && r.versions) {
            const installed = r.versions.filter(v => v.downloaded);
            if (installed.length === 0) {
                sel.innerHTML = '<option value="default">Default Latest (no engine installed)</option>';
                return;
            }
            sel.innerHTML = '<option value="default">Default Latest</option>' +
                installed.map(v => {
                    const nm  = typeof v === 'object' ? (v.browser_version || v.name) : v;
                    const bas = typeof v === 'object' ? v.bas_version : '';
                    const label = bas ? `${nm} (BAS ${bas})` : nm;
                    return `<option value="${esc(nm)}">${esc(label)}</option>`;
                }).join('');
            // Restore previously selected version
            if (prev && prev !== 'default') {
                sel.value = prev;
                if (!sel.value || sel.value === 'default') {
                    // Version not in list — add it
                    const opt = document.createElement('option');
                    opt.value = prev; opt.textContent = prev;
                    sel.insertBefore(opt, sel.options[1] || null);
                    sel.value = prev;
                }
            }
        } else {
            sel.innerHTML = '<option value="default">Default Latest</option>';
        }
    } catch (e) {
        sel.innerHTML = '<option value="default">Default Latest</option>';
        console.warn('[Engine dropdown] fetch failed:', e);
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
async function createProfile() {
    const btn = document.getElementById('btn-create-profile-submit');
    const name = document.getElementById('profile-name').value.trim();
    if (!name) return;
    btn.disabled = true;
    btn.textContent = 'Creating...';
    const width  = parseInt(document.getElementById('profile-win-width')?.value)  || 1920;
    const height = parseInt(document.getElementById('profile-win-height')?.value) || 1080;
    await apiPost('/api/v1/browser/profiles', {
        name,
        proxy: document.getElementById('profile-proxy').value,
        tags: [document.getElementById('profile-os').value, document.getElementById('profile-browser').value],
        browser_version: document.getElementById('profile-version')?.value,
        window_size: { width, height },
    });
    btn.disabled = false;
    btn.textContent = 'Create & Fetch Fingerprint';
    closeModal('modal-profile');
    document.getElementById('profile-name').value = '';
    document.getElementById('profile-proxy').value = '';
    if (document.getElementById('profile-win-width'))  document.getElementById('profile-win-width').value  = '1920';
    if (document.getElementById('profile-win-height')) document.getElementById('profile-win-height').value = '1080';
    renderBrowserExt(getBrowserBody());
}
async function launchProfile(name,btn) { if(btn){btn.disabled=true;btn.textContent='🚀...'} const r=await apiPost('/api/v1/browser/launch',{profile:name,manual:true}); if(r && !r.error && r.status !== 'error') { let n=0; const iv=setInterval(async()=>{await renderBrowserExt(getBrowserBody());if(++n>=3)clearInterval(iv)},2000); } else { if(btn){btn.disabled=false;btn.textContent='▶'} let msg = 'Failed to launch: ' + (r?.error || r?.detail || 'Unknown error'); if(r?.log_output) msg += '\n\n📋 Log output:\n' + r.log_output; if(r?.debug) { const d = r.debug; msg += '\n\n🔍 Debug info:'; msg += '\n• Node: ' + (d.node_available ? d.node_version : '❌ NOT FOUND'); msg += '\n• open.js: ' + (d.open_js_exists ? '✅' : '❌ NOT FOUND'); msg += '\n• node_modules: ' + (d.node_modules_exists ? '✅' : '❌ MISSING'); msg += '\n• Launcher dir: ' + (d.launcher_dir || '-'); if(d.launcher_dir_contents) msg += '\n• Dir contents: ' + d.launcher_dir_contents.join(', '); if(d.exit_code !== undefined) msg += '\n• Exit code: ' + d.exit_code; } alert(msg); } }
async function stopProfile(name,btn) { if(btn){btn.disabled=true;btn.textContent='...'} await apiPost('/api/v1/browser/stop',{profile:name}); setTimeout(()=>renderBrowserExt(getBrowserBody()),1000); }
async function deleteProfile(name) { if(!confirm('Delete '+name+'?')) return; await apiDelete('/api/v1/browser/profiles/'+name); }
async function viewProfileLog(name) { const r = await apiGet('/api/v1/browser/log/' + encodeURIComponent(name)); if (!r || r.error) { alert('No log available: ' + (r?.error || 'Unknown')); return; } let msg = '📋 Browser Log for: ' + name; msg += '\n\nStatus: ' + (r.status || '-'); msg += '\nCommand: ' + (r.command || '-'); msg += '\nLog file: ' + (r.log_file || '-'); if (r.debug) { const d = r.debug; if (d.node_version) msg += '\nNode: ' + d.node_version; if (d.open_js_exists !== undefined) msg += '\nopen.js: ' + (d.open_js_exists ? '✅' : '❌'); if (d.node_modules_exists !== undefined) msg += '\nnode_modules: ' + (d.node_modules_exists ? '✅' : '❌'); if (d.launcher_dir) msg += '\nLauncher: ' + d.launcher_dir; } msg += '\n\n─── LOG OUTPUT ───\n' + (r.log || '(empty)'); alert(msg); }

// ═══ Browser Command ═══
let _cmdProfile = '';
function showProfileCommand(name) { _cmdProfile = name; document.getElementById('cmd-profile-name').textContent = name; document.getElementById('cmd-input').value = ''; document.getElementById('modal-command').classList.remove('hidden'); setTimeout(() => document.getElementById('cmd-input').focus(), 100); }
function setCommand(cmd) { document.getElementById('cmd-input').value = cmd; document.getElementById('cmd-input').focus(); }
async function executeProfileCommand() { const cmd = document.getElementById('cmd-input').value.trim(); if (!cmd) return alert('Vui lòng nhập lệnh!'); const aiModel = document.getElementById('cmd-ai-model').value; const btn = document.getElementById('btn-run-command'); btn.disabled = true; btn.textContent = '⏳ Đang chạy...'; const r = await apiPost('/api/v1/browser/launch', { profile: _cmdProfile, prompt: cmd, manual: false, ai_model: aiModel }); btn.disabled = false; btn.textContent = '🚀 Chạy lệnh'; if (r && !r.error && r.status !== 'error') { closeModal('modal-command'); let n = 0; const iv = setInterval(async () => { await renderBrowserExt(getBrowserBody()); if (++n >= 3) clearInterval(iv); }, 2000); } else { let msg = 'Lỗi: ' + (r?.error || r?.detail || 'Unknown'); if (r?.log_output) msg += '\n\n' + r.log_output; alert(msg); } }
function searchMarket() { const q=(document.getElementById('market-search')?.value||'').toLowerCase(); document.querySelectorAll('#market-list .card').forEach(c=>{ c.style.display=c.textContent.toLowerCase().includes(q)?'':'none'; }); }

// ═══ Global Settings ═══
// Apply settings data to UI (called by init with pre-fetched data)
async function applyGlobalSettings(s) {
    if (!s) return;
    if (s.api_port && document.getElementById('set-port')) document.getElementById('set-port').value = s.api_port;
    if (s.api_base_url && document.getElementById('set-api')) document.getElementById('set-api').value = s.api_base_url;
    if (s.telegram_bot_token && document.getElementById('set-tg-token')) document.getElementById('set-tg-token').value = s.telegram_bot_token;
    if (s.telegram_chat_id && document.getElementById('set-tg-chat')) document.getElementById('set-tg-chat').value = s.telegram_chat_id;
    globalExtensionGroups = s.extension_groups || [];
    renderExtensionGroupsSettings();
    // These are async but non-critical, run in background
    populateModelDropdown(s.default_model || 'qwen:latest');
    loadCloudKeysInSettings();
    apiGet('/api/v1/settings/default-profile').then(bp => populateDefaultProfileDropdown(bp?.profile || 'default')).catch(() => {});
    populateDefaultCalendarDropdown(s.default_calendar_email || '').catch(() => {});
}

async function loadGlobalSettings() {
    try {
        const s = await apiGet('/api/v1/settings');
        await applyGlobalSettings(s);
    } catch(e) { console.warn('[Settings] Failed to load:', e); }
}

async function populateDefaultProfileDropdown(selectedProfile) {
    const sel = document.getElementById('set-default-profile');
    if (!sel) return;
    try {
        const d = await apiGet('/api/v1/browser/profiles');
        let html = '<option value="default">default (Mặc định AI)</option>';
        if (d && d.profiles && d.profiles.length > 0) {
            d.profiles.forEach(p => {
                if (p.name !== 'default') {
                    html += `<option value="${esc(p.name)}">${esc(p.name)}</option>`;
                }
            });
        }
        sel.innerHTML = html;
        if (selectedProfile) {
            sel.value = selectedProfile;
        }
    } catch (e) {
        console.warn('Profiles fetch failed:', e);
    }
}

async function changeDefaultProfile(val) {
    try {
        await apiPut('/api/v1/settings/default-profile', { profile: val });
        console.log("Default profile saved.");
    } catch (e) {
        console.error("Failed to save default profile", e);
    }
}

async function populateDefaultCalendarDropdown(selectedEmail) {
    const sel = document.getElementById('set-default-calendar');
    if (!sel) return;
    try {
        const d = await apiGet('/api/v1/calendar/credentials');
        let html = '<option value="">Chưa cấu hình / Bỏ trống</option>';
        if (d && d.credentials && d.credentials.length > 0) {
            d.credentials.forEach(c => {
                if (c.email) {
                    html += `<option value="${esc(c.email)}">${esc(c.email)} (${esc(c.name)})</option>`;
                }
            });
        } else {
            html = '<option value="">⚠️ Chưa có tài khoản Calendar trong Auth Manager</option>';
        }
        sel.innerHTML = html;
        if (selectedEmail) {
            const hasOption = Array.from(sel.options).some(opt => opt.value === selectedEmail);
            if (!hasOption && selectedEmail !== '') {
                sel.innerHTML += `<option value="${esc(selectedEmail)}">${esc(selectedEmail)} (⚠️ Đã lưu nhưng mất quyền truy cập)</option>`;
            }
            sel.value = selectedEmail;
        }
    } catch (e) {
        console.warn('Calendar credentials fetch failed:', e);
    }
}

async function changeDefaultCalendar(val) {
    // This function is triggered on UI change. We rely on saveGlobalSettings() to actually persist it 
    // to the global_settings.json together with other general settings.
    console.log("Selected Default Calendar Email pending save:", val);
}

async function populateModelDropdown(selectedModel) {
    const sel = document.getElementById('set-model');
    if (!sel) return;
    let html = '';
    let ollamaOnline = false;
    try {
        const ollama = await apiGet('/api/v1/ollama/models');
        if (ollama && ollama.models && ollama.models.length > 0) {
            ollamaOnline = true;
            html += '<optgroup label="🖥️ Ollama (Local)">';
            ollama.models.forEach(m => {
                const name = m.name || m;
                html += `<option value="${esc(name)}">${esc(name)}</option>`;
            });
            html += '</optgroup>';
        }
    } catch(e) { console.warn('[Settings] Ollama models fetch failed'); }
    if (!ollamaOnline) {
        html += '<optgroup label="🖥️ Ollama (Local)">';
        html += '<option disabled style="color:#888">⚠️ Ollama not running — start Ollama first</option>';
        html += '</optgroup>';
    }
    // 9Router models (local proxy)
    try {
        const nrStatus = await apiGet('/api/v1/cloud-api/9router/status');
        if (nrStatus?.running && nrStatus.models && nrStatus.models.length > 0) {
            html += '<optgroup label="🔀 9Router (Local Proxy)">';
            nrStatus.models.forEach(m => {
                html += `<option value="${esc(m)}">${esc(m)}</option>`;
            });
            html += '</optgroup>';
        }
    } catch(e) { console.warn('[Settings] 9Router status fetch failed'); }
    try {
        const cloud = await apiGet('/api/v1/cloud-api/providers');
        if (cloud && cloud.providers) {
            cloud.providers.forEach(p => {
                if (!p.models || p.models.length === 0) return;
                if (p.id === '9router') return; // Already handled above
                const label = { gemini: '✨ Gemini', openai: '🤖 OpenAI', claude: '🧠 Claude', grok: '⚡ Grok', deepseek: '🔮 DeepSeek', openrouter: '🌐 OpenRouter' }[p.id] || p.id;
                html += `<optgroup label="☁️ ${esc(label)}">`;
                p.models.forEach(m => {
                });
                html += '</optgroup>';
            });
        }
    } catch(e) { console.warn('[Settings] Cloud API models fetch failed'); }

    if (!html) {
        html = '<option value="qwen:latest">qwen:latest</option>';
    }
    sel.innerHTML = html;
    if (selectedModel) {
        const exists = Array.from(sel.options).some(o => o.value === selectedModel);
        if (exists) {
            sel.value = selectedModel;
        } else {
            sel.insertAdjacentHTML('afterbegin', `<option value="${esc(selectedModel)}">${esc(selectedModel)}</option>`);
            sel.value = selectedModel;
        }
    }
}

// Filter model dropdown by provider chip
function filterModelsByProvider(provider, chipEl) {
    // Update active chip
    document.querySelectorAll('#provider-filter .ext-chip').forEach(c => c.classList.remove('active'));
    if (chipEl) chipEl.classList.add('active');
    
    const sel = document.getElementById('set-model');
    if (!sel) return;
    
    const providerKeywords = {
        'ollama': 'Ollama',
        'gemini': 'Gemini',
        'openai': 'OpenAI',
        'deepseek': 'DeepSeek',
        'claude': 'Claude',
        'grok': 'Grok',
        'openrouter': 'OpenRouter',
        '9router': '9Router',
    };
    
    const optgroups = sel.querySelectorAll('optgroup');
    
    optgroups.forEach(og => {
        if (provider === 'all') {
            og.style.display = '';
            og.querySelectorAll('option').forEach(o => o.style.display = '');
        } else {
            const keyword = providerKeywords[provider] || provider;
            if (og.label && og.label.includes(keyword)) {
                og.style.display = '';
                og.querySelectorAll('option').forEach(o => o.style.display = '');
            } else {
                og.style.display = 'none';
                og.querySelectorAll('option').forEach(o => o.style.display = 'none');
            }
        }
    });
    
    // Also handle standalone options (not in optgroup)
    sel.querySelectorAll(':scope > option').forEach(o => {
        o.style.display = (provider === 'all') ? '' : 'none';
    });
    
    // If current selection is hidden, select first visible option
    const selectedOpt = sel.options[sel.selectedIndex];
    if (selectedOpt && selectedOpt.style.display === 'none') {
        for (let i = 0; i < sel.options.length; i++) {
            if (sel.options[i].style.display !== 'none' && !sel.options[i].disabled) {
                sel.selectedIndex = i;
                break;
            }
        }
    }
}

// Check if selected model needs an API key
async function onModelSelectChange() {
    const sel = document.getElementById('set-model');
    const warn = document.getElementById('model-key-warning');
    if (!sel || !warn) return;
    const selectedOpt = sel.options[sel.selectedIndex];
    if (!selectedOpt) { warn.style.display = 'none'; return; }
    const optgroup = selectedOpt.closest('optgroup');
    if (!optgroup || !optgroup.label.includes('☁️')) {
        warn.style.display = 'none';
        return;
    }
    const providerMap = { 'Gemini': 'gemini', 'OpenAI': 'openai', 'Claude': 'claude', 'Grok': 'grok', 'DeepSeek': 'deepseek', 'OpenRouter': 'openrouter' };
    let provider = '';
    for (const [name, id] of Object.entries(providerMap)) {
        if (optgroup.label.includes(name)) { provider = id; break; }
    }
    if (!provider) { warn.style.display = 'none'; return; }
    try {
        const data = await apiGet('/api/v1/cloud-api/keys');
        const providerKeys = data?.keys?.[provider];
        if (providerKeys && Object.keys(providerKeys).length > 0) {
            const hasActive = Object.values(providerKeys).some(k => k.active);
            if (hasActive) {
                warn.style.display = 'none';
            } else {
                warn.style.display = 'block';
                warn.innerHTML = `⚠️ Tất cả API keys của <b>${provider}</b> đều hết hạn hoặc lỗi. Vui lòng thêm key mới ở phần <b>Cloud API Keys</b> bên dưới.`;
            }
        } else {
            warn.style.display = 'block';
            warn.innerHTML = `⚠️ Chưa có API key cho <b>${provider}</b>. Hãy thêm key ở phần <b>Cloud API Keys</b> bên dưới để sử dụng model này.`;
        }
    } catch(e) {
        warn.style.display = 'none';
    }
}

async function testDefaultAI() {
    const sel = document.getElementById('set-model');
    const resultDiv = document.getElementById('test-default-ai-result');
    const btn = document.getElementById('btn-test-default-ai');
    
    if (!sel || !resultDiv || !btn) return;
    
    const selectedOpt = sel.options[sel.selectedIndex];
    if (!selectedOpt) return;
    
    const model = selectedOpt.value;
    const optgroup = selectedOpt.closest('optgroup');
    
    if (!optgroup) {
        resultDiv.style.display = 'block';
        resultDiv.textContent = `Không hỗ trợ test cho model này.`;
        resultDiv.style.color = '#ef4444';
        resultDiv.style.background = 'rgba(239, 68, 68, 0.1)';
        return;
    }
    
    resultDiv.style.display = 'block';
    resultDiv.textContent = 'Đang kiểm tra kết nối...';
    resultDiv.style.color = 'var(--text)';
    resultDiv.style.background = 'var(--bg-lighter)';
    btn.disabled = true;
    
    try {
        if (optgroup.label.includes('Ollama')) {
            const resp = await fetch('http://localhost:11434/api/generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    model: model,
                    prompt: "Reply 'OK'",
                    stream: false
                })
            });
            if (resp.ok) {
                resultDiv.textContent = `✅ Thành công (Ollama: ${model})`;
                resultDiv.style.color = '#10b981';
                resultDiv.style.background = 'rgba(16, 185, 129, 0.1)';
            } else {
                resultDiv.textContent = `❌ Lỗi Ollama: ${resp.status}`;
                resultDiv.style.color = '#ef4444';
                resultDiv.style.background = 'rgba(239, 68, 68, 0.1)';
            }
        } else if (optgroup.label.includes('☁️')) {
            const providerMap = { 'Gemini': 'gemini', 'OpenAI': 'openai', 'Claude': 'claude', 'Grok': 'grok', 'DeepSeek': 'deepseek', 'OpenRouter': 'openrouter' };
            let provider = '';
            for (const [name, id] of Object.entries(providerMap)) {
                if (optgroup.label.includes(name)) { provider = id; break; }
            }
            if (!provider) throw new Error("Không xác định được provider");
            
            const resp = await fetch(`/api/v1/cloud-api/providers/${provider}/test-model`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    model: model,
                    prompt: "Reply 'Hello from API!'"
                })
            });
            
            const data = await resp.json();
            if (resp.ok && data.status === 'success') {
                resultDiv.textContent = `✅ Kết nối tốt! (${data.response?.substring(0, 50) || 'OK'})`;
                resultDiv.style.color = '#10b981';
                resultDiv.style.background = 'rgba(16, 185, 129, 0.1)';
            } else {
                let errText = data.detail || data.message || 'Unknown error';
                if (typeof errText === 'string' && errText.length > 100) errText = errText.substring(0, 100) + '...';
                resultDiv.textContent = `❌ Lỗi: ${errText}`;
                resultDiv.style.color = '#ef4444';
                resultDiv.style.background = 'rgba(239, 68, 68, 0.1)';
            }
        } else if (optgroup.label.includes('9Router')) {
            // Test 9Router directly via OpenAI-compatible API
            resultDiv.textContent = 'Testing 9Router...';
            const resp = await fetch('http://localhost:20128/v1/chat/completions', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    model: model,
                    messages: [{ role: 'user', content: "Reply 'Hello from 9Router!'" }],
                    max_tokens: 30
                })
            });
            if (resp.ok) {
                const data = await resp.json();
                const reply = data?.choices?.[0]?.message?.content || 'OK';
                resultDiv.textContent = `✅ 9Router OK! (${reply.substring(0, 60)})`;
                resultDiv.style.color = '#10b981';
                resultDiv.style.background = 'rgba(16, 185, 129, 0.1)';
            } else {
                const errData = await resp.json().catch(() => ({}));
                const errMsg = errData?.error?.message || `HTTP ${resp.status}`;
                resultDiv.textContent = `❌ 9Router Error: ${errMsg.substring(0, 80)}`;
                resultDiv.style.color = '#ef4444';
                resultDiv.style.background = 'rgba(239, 68, 68, 0.1)';
            }
        } else {
            resultDiv.textContent = `Test not supported for this group.`;
        }
    } catch (e) {
        resultDiv.textContent = `❌ Lỗi: ${e.message}`;
        resultDiv.style.color = '#ef4444';
        resultDiv.style.background = 'rgba(239, 68, 68, 0.1)';
    } finally {
        btn.disabled = false;
        setTimeout(() => {
            if (resultDiv.textContent.includes('Thành công') || resultDiv.textContent.includes('tốt')) {
                resultDiv.style.display = 'none';
            }
        }, 5000);
    }
}

// ═══ Auto-Save Individual Setting ═══
function showFieldIndicator(inputEl, type, text) {
    const field = inputEl.closest('.settings-field') || inputEl.closest('.form-group');
    if (!field) return;
    // Remove existing indicator
    const existing = field.querySelector('.save-indicator');
    if (existing) existing.remove();
    // Create new indicator
    const indicator = document.createElement('span');
    indicator.className = 'save-indicator ' + type;
    indicator.textContent = text;
    field.style.position = 'relative';
    field.appendChild(indicator);
    // Auto-remove after 2.5s
    if (type !== 'saving') {
        setTimeout(() => {
            indicator.style.animation = 'fadeOutSlide 0.3s forwards';
            setTimeout(() => indicator.remove(), 300);
        }, 2500);
    }
}

async function autoSaveSetting(key, value, inputEl) {
    if (inputEl) showFieldIndicator(inputEl, 'saving', '⏳ Saving...');
    
    // Build full payload from current form state
    const payload = {
        default_model: document.getElementById('set-model')?.value || 'qwen:latest',
        api_port: document.getElementById('set-port')?.value || '5295',
        api_base_url: document.getElementById('set-api')?.value || window.location.origin,
        telegram_bot_token: document.getElementById('set-tg-token')?.value || '',
        telegram_chat_id: document.getElementById('set-tg-chat')?.value || '',
        default_calendar_email: document.getElementById('set-default-calendar')?.value || '',
    };
    // Override with the specific changed key
    payload[key] = value;
    
    try {
        const r = await apiPut('/api/v1/settings', payload);
        if (r && r.status === 'success') {
            if (key === 'api_base_url' && value) localStorage.setItem('tubecli_api', value);
            if (inputEl) showFieldIndicator(inputEl, 'success', '✓ Saved');
        } else {
            if (inputEl) showFieldIndicator(inputEl, 'error', '✗ Error');
        }
    } catch (e) {
        if (inputEl) showFieldIndicator(inputEl, 'error', '✗ ' + e.message);
    }
}

async function saveGlobalSettings() {
    const payload = {
        default_model: document.getElementById('set-model')?.value || 'qwen:latest',
        api_port: document.getElementById('set-port')?.value || '5295',
        api_base_url: document.getElementById('set-api')?.value || window.location.origin,
        telegram_bot_token: document.getElementById('set-tg-token')?.value || '',
        telegram_chat_id: document.getElementById('set-tg-chat')?.value || '',
        default_calendar_email: document.getElementById('set-default-calendar')?.value || '',
    };
    try {
        const r = await apiPut('/api/v1/settings', payload);
        if (r && r.status === 'success') {
            if (payload.api_base_url) localStorage.setItem('tubecli_api', payload.api_base_url);
            const toast = document.createElement('div');
            toast.textContent = '✅ Settings saved!';
            toast.style.cssText = 'position:fixed;top:20px;right:20px;background:linear-gradient(135deg,#10b981,#06b6d4);color:#fff;padding:14px 28px;border-radius:10px;z-index:99999;font-weight:700;font-size:1rem;box-shadow:0 4px 20px rgba(0,0,0,0.3);animation:fadeIn .3s';
            document.body.appendChild(toast);
            setTimeout(() => toast.remove(), 3000);
        } else {
            alert('❌ Save failed: ' + JSON.stringify(r));
        }
    } catch (e) {
        alert('❌ Error: ' + e.message);
    }
}

async function testTelegramConnection() {
    const token = document.getElementById('set-tg-token')?.value?.trim();
    const chatId = document.getElementById('set-tg-chat')?.value?.trim();
    const resultEl = document.getElementById('tg-test-result');
    const btn = document.getElementById('btn-test-tg');
    if (!token || !chatId) {
        resultEl.innerHTML = '<span style="color:var(--red)">⚠️ Nhập Bot Token và Chat ID trước</span>';
        return;
    }
    btn.disabled = true;
    btn.textContent = '⏳ Đang gửi...';
    resultEl.innerHTML = '';
    try {
        const url = `https://api.telegram.org/bot${token}/sendMessage`;
        const res = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                chat_id: chatId,
                text: '✅ TubeCLI kết nối thành công!\n🤖 Bot đã sẵn sàng nhận thông báo.',
                parse_mode: 'HTML'
            })
        });
        const data = await res.json();
        if (data.ok) {
            resultEl.innerHTML = '<span style="color:var(--green)">✅ Gửi thành công! Kiểm tra Telegram của bạn.</span>';
        } else {
            resultEl.innerHTML = `<span style="color:var(--red)">❌ Lỗi: ${esc(data.description || 'Unknown')}</span>`;
        }
    } catch(e) {
        resultEl.innerHTML = `<span style="color:var(--red)">❌ Lỗi kết nối: ${e.message}</span>`;
    }
    btn.disabled = false;
    btn.textContent = '📡 Test kết nối';
}

// ═══ Cloud API Keys in Settings ═══
async function loadCloudKeysInSettings() {
    const container = document.getElementById('settings-cloud-keys-list');
    if (!container) return;
    container.innerHTML = '<div style="display:flex;align-items:center;gap:8px;padding:16px;justify-content:center;color:var(--text-muted)"><span class="spinner" style="width:18px;height:18px;border:2px solid var(--border);border-top-color:var(--primary);border-radius:50%;animation:spin .6s linear infinite;display:inline-block"></span> Loading API keys...</div>';
    try {
        const data = await apiGet('/api/v1/cloud-api/keys');
        if (!data || !data.keys || Object.keys(data.keys).length === 0) {
            container.innerHTML = '<p style="color:var(--text-muted);font-size:.85rem;font-style:italic">Chưa có API key nào. Thêm key bên dưới để sử dụng mô hình Cloud.</p>';
            return;
        }
        const icons = { gemini: '✨', openai: '🤖', claude: '🧠', deepseek: '🔮', grok: '⚡', openrouter: '🌐', everai: '🎙️', github: '🐙', '9router': '🔀' };
        let html = '';
        let totalKeys = 0;
        for (const [provider, labelsObj] of Object.entries(data.keys)) {
            if (!labelsObj || typeof labelsObj !== 'object') continue;
            for (const [label, info] of Object.entries(labelsObj)) {
                totalKeys++;
                const maskedKey = info.masked_key || '••••••';
                const isActive = info.active !== false;
                const statusMsg = info.status_msg || '';
                const statusColor = isActive ? 'var(--green)' : 'var(--red)';
                const statusIcon = isActive ? '✅' : '⚠️';
                html += `<div style="display:flex;align-items:center;flex-wrap:wrap;gap:10px;padding:10px 14px;background:var(--bg2);border:1px solid var(--border);border-radius:8px;">
                    <span style="font-size:1.1rem;display:flex;align-items:center;">${icons[provider] || '🔑'}</span>
                    <span style="font-weight:600;color:var(--text);min-width:70px;text-transform:capitalize">${esc(provider)}</span>
                    <code style="flex:1;min-width:100px;font-size:.8rem;color:var(--text-muted);background:var(--bg);padding:4px 8px;border-radius:4px;word-break:break-all">${esc(maskedKey)}</code>
                    <span class="tag" style="font-size:.7rem;white-space:nowrap">${esc(label)}</span>
                    <span style="font-size:.75rem;color:${statusColor};white-space:nowrap;display:flex;align-items:center;gap:4px;">${statusIcon} ${esc(statusMsg) || (isActive ? 'Active' : '')}</span>
                    <button onclick="removeCloudKeyFromSettings('${esc(provider)}','${esc(label)}')" style="background:none;border:none;color:var(--red);cursor:pointer;font-size:1rem;padding:2px 6px;margin-left:auto" title="Xóa key">🗑️</button>
                </div>`;
            }
        }
        container.innerHTML = totalKeys > 0 ? html : '<p style="color:var(--text-muted);font-size:.85rem;font-style:italic">Chưa có API key nào.</p>';
    } catch(e) {
        console.warn('[Settings] Cloud keys load error:', e);
        container.innerHTML = '<p style="color:var(--text-muted);font-size:.85rem;font-style:italic">Chưa có API key nào. Thêm key bên dưới để sử dụng mô hình Cloud.</p>';
    }
}

async function addCloudKeyFromSettings() {
    const prov = document.getElementById('settings-add-key-provider').value;
    const key = document.getElementById('settings-add-key-value').value.trim();
    if (!key) return alert('Vui lòng nhập API key!');
    const label = 'key_' + Math.floor(Date.now() / 1000);
    const r = await apiPost('/api/v1/cloud-api/keys', { provider: prov, api_key: key, label });
    if (r && r.status === 'success') {
        document.getElementById('settings-add-key-value').value = '';
        loadCloudKeysInSettings();
        const currentModel = document.getElementById('set-model')?.value || 'qwen:latest';
        await populateModelDropdown(currentModel);
        const toast = document.createElement('div');
        toast.textContent = `✅ Đã thêm key ${prov}!`;
        toast.style.cssText = 'position:fixed;top:20px;right:20px;background:linear-gradient(135deg,#8b5cf6,#06b6d4);color:#fff;padding:12px 24px;border-radius:10px;z-index:99999;font-weight:700;box-shadow:0 4px 20px rgba(0,0,0,0.3);animation:fadeIn .3s';
        document.body.appendChild(toast);
        setTimeout(() => toast.remove(), 2500);
    } else {
        alert('❌ Thêm key thất bại: ' + JSON.stringify(r));
    }
}

async function removeCloudKeyFromSettings(provider, label) {
    if (!confirm(`Xóa key "${label}" của ${provider}?`)) return;
    await apiDelete('/api/v1/cloud-api/keys', { provider, label });
    loadCloudKeysInSettings();
    const currentModel = document.getElementById('set-model')?.value || 'qwen:latest';
    await populateModelDropdown(currentModel);
}

// ═══ Version & Update ═══ (defined below at end of file)

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
    // Reset fingerprint status
    const fpStatus = document.getElementById('settings-fp-status');
    if (fpStatus) fpStatus.textContent = 'Đang tải...';

    // Load profile data then populate dropdown with correct selection
    try {
        const data = await apiGet(`/api/v1/browser/profiles/${name}`);
        // Populate engine versions — always fresh, pre-select saved version
        await loadEngineVersionsDropdown('settings-version', data?.browser_version || 'default');
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
            // Window size
            const ws = data.window_size || { width: 1920, height: 1080 };
            if (document.getElementById('settings-win-width'))  document.getElementById('settings-win-width').value  = ws.width  || 1920;
            if (document.getElementById('settings-win-height')) document.getElementById('settings-win-height').value = ws.height || 1080;
            // Google account
            const ga = data.google_account;
            if (ga && ga.email) {
                const parts = [ga.email, ga.password || '', ga.recoveryEmail || '', ga.twoFactorCodes || ''].filter(p => p);
                document.getElementById('settings-google-account').value = parts.join('|');
            } else {
                document.getElementById('settings-google-account').value = '';
            }
            previewGoogleAccount();
            // Fingerprint status
            if (fpStatus) fpStatus.textContent = data.has_fingerprint ? '✅ Đã có fingerprint' : '⚠️ Chưa có fingerprint';
        }
    } catch (e) {
        console.error('Failed to load profile:', e);
        if (fpStatus) fpStatus.textContent = '❌ Lỗi tải profile';
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
    const browserVersion = document.getElementById('settings-version')?.value || 'default';
    const googleRaw = document.getElementById('settings-google-account').value.trim();
    const width  = parseInt(document.getElementById('settings-win-width')?.value)  || 1920;
    const height = parseInt(document.getElementById('settings-win-height')?.value) || 1080;
    
    const payload = {
        proxy: proxy,
        tags: [os, browser],
        browser_version: browserVersion,
        window_size: { width, height },
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
            const el = getBrowserBody();
            if (el) renderBrowserExt(el);
        } else {
            alert('❌ Save failed: ' + JSON.stringify(result));
        }
    } catch (e) {
        console.error('[Settings] Error:', e);
        alert('❌ Error: ' + e.message);
    }
}

async function refreshFingerprint() {
    const btn = document.getElementById('btn-refresh-fp');
    const fpStatus = document.getElementById('settings-fp-status');
    if (!_settingsProfileName) return;
    if (btn) { btn.disabled = true; btn.textContent = '⏳ Đang lấy...'; }
    if (fpStatus) fpStatus.textContent = '⏳ Đang lấy fingerprint mới...';
    try {
        const result = await apiPost(`/api/v1/browser/profiles/${_settingsProfileName}/fingerprint/refresh`, {});
        if (result && result.status === 'refreshed') {
            if (fpStatus) fpStatus.textContent = '✅ Fingerprint mới đã được lấy thành công!';
            const toast = document.createElement('div');
            toast.textContent = '🧬 Fingerprint đã được làm mới!';
            toast.style.cssText = 'position:fixed;top:20px;right:20px;background:linear-gradient(135deg,#8b5cf6,#06b6d4);color:#fff;padding:12px 24px;border-radius:8px;z-index:99999;font-weight:600;box-shadow:0 4px 12px rgba(0,0,0,0.3);animation:fadeIn .3s';
            document.body.appendChild(toast);
            setTimeout(() => toast.remove(), 3000);
            // Refresh cards
            const el = getBrowserBody();
            if (el) renderBrowserExt(el);
        } else {
            if (fpStatus) fpStatus.textContent = '❌ Lỗi: ' + JSON.stringify(result);
            alert('❌ Refresh fingerprint thất bại: ' + JSON.stringify(result));
        }
    } catch (e) {
        if (fpStatus) fpStatus.textContent = '❌ Lỗi kết nối: ' + e.message;
        alert('❌ Error: ' + e.message);
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = '🔄 Làm mới vân tay'; }
    }
}

// ═══ Connection Check ═══
async function checkConnection() { try { const r=await fetch(API+'/api/v1/health',{signal:AbortSignal.timeout(2000)}); if(!r.ok) throw 0; } catch { console.warn('API Offline'); } }

// ═══ Version & Update ═══
async function loadVersionInfo() {
    const badge = document.getElementById('version-badge');
    const hashEl = document.getElementById('version-hash');
    const branchEl = document.getElementById('version-branch');
    if (!badge) return;
    try {
        const info = await apiGet('/api/v1/version');
        if (!info || info.error) return;
        badge.textContent = '⚡ TubeCLI v' + (info.version || '?');
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
        // Use backend endpoint that checks GitHub
        const data = await apiGet('/api/v1/version/check');
        if (!data || data.error) {
            if (!silent && statusEl) statusEl.innerHTML = `<span style="color:var(--yellow)">⚠️ ${data?.error || 'Could not check for updates'}</span>`;
            return;
        }
        
        if (statusEl) {
            if (data.has_update) {
                statusEl.innerHTML = `<span style="color:var(--yellow);font-weight:700">🆕 New version available: v${data.remote_version}</span>`;
                if (updateBtn) updateBtn.style.display = '';
                if (changelogBox) changelogBox.style.display = 'none'; // Changelog not available from this endpoint
            } else {
                if (!silent) statusEl.innerHTML = `<span style="color:var(--green)">✅ Up to date (v${data.current_version})</span>`;
                if (updateBtn) updateBtn.style.display = 'none';
                if (changelogBox) changelogBox.style.display = 'none';
            }
        }
    } catch(e) {
        if (!silent && statusEl) statusEl.innerHTML = `<span style="color:var(--red)">⚠️ Could not connect to update server</span>`;
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


// ═══ Extension Update Check System ═══
let _extUpdateCache = null;
let _extUpdateCacheTime = 0;
const EXT_UPDATE_CACHE_TTL = 30 * 60 * 1000; // 30 minutes

function getSkippedExtUpdates() {
    try { return JSON.parse(localStorage.getItem('tcf_skip_updates') || '[]'); } catch(e) { return []; }
}
function skipExtensionUpdate(name) {
    var list = getSkippedExtUpdates();
    var key = (name || '').toLowerCase().replace(/ /g, '_');
    if (!list.includes(key)) { list.push(key); localStorage.setItem('tcf_skip_updates', JSON.stringify(list)); }
}

async function checkExtensionUpdates(force) {
    if (!force && _extUpdateCache !== null && Date.now() - _extUpdateCacheTime < EXT_UPDATE_CACHE_TTL) {
        updateExtBadge(_extUpdateCache.length);
        return _extUpdateCache;
    }
    try {
        const result = await apiGet('/api/v1/market/check-updates');
        var allUpdates = result?.updates || [];
        var skipped = getSkippedExtUpdates();
        var updates = allUpdates.filter(function(u) {
            return !skipped.includes((u.name || '').toLowerCase().replace(/ /g, '_'));
        });
        _extUpdateCache = updates;
        _extUpdateCacheTime = Date.now();
        updateExtBadge(updates.length);
        return updates;
    } catch (e) {
        console.warn('[Updates] Check failed:', e);
        return [];
    }
}

function updateExtBadge(count) {
    const badge = document.getElementById('ext-update-badge');
    if (!badge) return;
    if (count > 0) {
        badge.textContent = count;
        badge.style.display = 'inline-flex';
    } else {
        badge.style.display = 'none';
    }
}

function dismissAllExtUpdates() {
    if (!confirm('T\u1eaft th\u00f4ng b\u00e1o c\u1eadp nh\u1eadt v\u0129nh vi\u1ec5n cho t\u1ea5t c\u1ea3 extension \u0111ang hi\u1ec3n th\u1ecb?\n\nB\u1ea1n v\u1eabn c\u00f3 th\u1ec3 b\u1eadt l\u1ea1i b\u1eb1ng c\u00e1ch x\u00f3a key "tcf_skip_updates" trong localStorage.')) return;
    if (_extUpdateCache) {
        _extUpdateCache.forEach(function(u) { skipExtensionUpdate(u.name); });
    }
    _extUpdateCache = null;
    _extUpdateCacheTime = 0;
    checkExtensionUpdates(true);
    loadExtensions();
}

async function doExtensionUpdate(name, publicId, gitUrl, btn) {
    if (btn) { btn.disabled = true; btn.textContent = '⏳ Updating...'; }
    try {
        let result;
        // Try local git update first (fastest)
        result = await apiPost('/api/v1/market/items/' + encodeURIComponent(name) + '/update-local', {});
        if (!result || result.status === 'error') {
            // Fallback: re-download from market
            if (publicId) {
                const detail = await apiGet('/api/v1/market/items/' + publicId);
                if (detail && detail.item) {
                    result = await apiPost('/api/v1/market/items/' + publicId + '/install', {
                        item_data: JSON.stringify(detail.item.item_data || {}),
                        item_name: name,
                        category: 'extension',
                        force_update: true,
                    });
                }
            }
        }
        if (result && result.status === 'success') {
            if (btn) { btn.textContent = '✅ Done!'; btn.style.background = 'var(--green)'; }
            _extUpdateCache = null;
            _extUpdateCacheTime = 0;
            setTimeout(function() {
                checkExtensionUpdates(true);
                loadExtensions();
            }, 1000);
        } else {
            var msg = (result && (result.message || result.detail)) || 'Update failed';
            if (btn) { btn.textContent = '❌ Error'; btn.style.background = 'var(--red)'; }
            alert('Update failed: ' + msg);
        }
    } catch (e) {
        if (btn) { btn.textContent = '❌ Error'; btn.style.background = 'var(--red)'; }
        alert('Update error: ' + e.message);
    } finally {
        setTimeout(function() {
            if (btn) { btn.disabled = false; btn.textContent = '⬆️ Update'; btn.style.background = ''; }
        }, 3000);
    }
}

// ── Extension Groups Settings ──
let globalExtensionGroups = [];
let allAvailableExtensions = [];

function renderGroupIcon(iconStr) {
    if (!iconStr) return '<span class="material-symbols-outlined" style="font-size:inherit;">folder_special</span>';
    if (/^[a-z0-9_]+$/.test(iconStr.trim())) {
        return `<span class="material-symbols-outlined" style="font-size:inherit;">${esc(iconStr.trim())}</span>`;
    }
    return esc(iconStr.trim());
}

function renderExtIcon(iconStr, size) {
    if (!iconStr) return '📦';
    const s = iconStr.trim();
    const px = size || 20;
    // Material Symbol name = lowercase letters/digits/underscores, must start with letter
    if (/^[a-z][a-z0-9_]+$/.test(s)) {
        return `<span class="material-symbols-outlined" style="font-size:${px}px;">${s}</span>`;
    }
    // Emoji / unicode — inject directly (esc() would break multi-byte emoji)
    return s;
}

async function renderExtensionGroupsSettings() {
    const listEl = document.getElementById('settings-ext-groups-list');
    if (!listEl) return;
    
    // Fetch extensions if not loaded
    if (allAvailableExtensions.length === 0) {
        try {
            const extData = await apiGet('/api/v1/extensions');
            allAvailableExtensions = extData?.extensions || [];
        } catch(e) { console.warn('Failed to load extensions for groups', e); }
    }
    
    let html = '';
    if (globalExtensionGroups.length === 0) {
        html = '<div style="color:var(--text-muted);font-size:0.85rem;">No groups created.</div>';
    } else {
        globalExtensionGroups.forEach((g, idx) => {
            const icon = g.icon || 'folder_special';
            const name = g.name || 'Unnamed Group';
            const extIds = g.extensions || [];
            
            // Build custom dropdown items — only extensions visible in dynamic sidebar
            const hardcodedExtensions = [
                'web_crawler', 'sheets_manager', 'calendar_manager',
                'multi_agents', 'livestream', 'files', 'video_editor', 'video_downloader', 'video_manager', 'subtitle_extractor', 'ai_arena'
            ];
            let dropdownItemsHtml = '';
            allAvailableExtensions.forEach(ext => {
                const inGroup = globalExtensionGroups.some(grp => (grp.extensions||[]).includes(ext.name));
                if (inGroup) return; // already in a group
                
                const inRegistry = EXT_REGISTRY.some(e => e.id === ext.name);
                const isHardcoded = hardcodedExtensions.includes(ext.name);
                // Only list extensions that would appear in the dynamic sidebar
                if (!inRegistry && !isHardcoded && ext.extension_type === 'external' && ext.enabled) {
                    const extIconHtml = renderExtIcon(ext.icon);
                    const extDisplay = ext.display_name || ext.name;
                    dropdownItemsHtml += `
                    <div class="ext-group-dropdown-item" onclick="addExtToGroup('${esc(g.id)}', '${esc(ext.name)}'); this.closest('.ext-group-dropdown-wrapper').classList.remove('open');" style="display:flex;align-items:center;gap:8px;padding:7px 12px;cursor:pointer;border-radius:6px;" onmouseenter="this.style.background='var(--bg)'" onmouseleave="this.style.background='';">
                        <span style="display:flex;align-items:center;width:20px;">${extIconHtml}</span>
                        <span style="font-size:0.85rem;">${esc(extDisplay)}</span>
                    </div>`;
                }
            });
            
            const hasDropdownItems = dropdownItemsHtml.length > 0;
            
            // Build chips with icon+name (look up in API list AND EXT_REGISTRY)
            let chipsHtml = '';
            extIds.forEach(eid => {
                if (!eid) return;
                const apiInfo  = allAvailableExtensions.find(e => e.name === eid) || {};
                const regInfo  = EXT_REGISTRY.find(e => e.id === eid) || {};
                const displayName = apiInfo.display_name || regInfo.name || apiInfo.name || eid;
                const iconRaw     = apiInfo.icon || regInfo.icon || '';
                const extIconHtml = renderExtIcon(iconRaw);
                chipsHtml += `<span class="ext-chip" style="margin:2px; display:inline-flex; align-items:center; gap:6px; padding:4px 8px 4px 6px;">
                    <span style="display:flex;align-items:center;">${extIconHtml}</span>
                    <span>${esc(displayName)}</span>
                    <button style="background:none;border:none;color:inherit;cursor:pointer;padding:0 0 0 2px;opacity:0.7;" onclick="removeExtFromGroup('${esc(g.id)}', '${esc(eid)}')">✕</button>
                </span>`;
            });
            
            html += `
            <div style="background:var(--bg3); padding:12px; border-radius:8px; border:1px solid var(--border);">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                    <div style="font-weight:600; color:var(--cyan); display:flex; gap:8px; align-items:center;">
                        <span style="display:flex;align-items:center;font-size:18px;">${renderGroupIcon(icon)}</span>
                        <span>${esc(name)}</span>
                    </div>
                    <button class="btn-danger" style="padding:4px 8px; font-size:0.75rem;" onclick="deleteExtensionGroup('${esc(g.id)}')">✕ Delete</button>
                </div>
                <div style="display:flex; gap:8px; align-items:flex-start; flex-wrap:wrap;">
                    ${hasDropdownItems ? `
                    <div class="ext-group-dropdown-wrapper">
                        <button class="btn-secondary" id="ext-group-btn-${esc(g.id)}" style="padding:4px 10px;font-size:0.82rem;display:flex;align-items:center;gap:4px;" onclick="openExtGroupDropdown('${esc(g.id)}', this)">
                            <span class="material-symbols-outlined" style="font-size:16px;">add</span> Add Extension
                            <span class="material-symbols-outlined" style="font-size:14px;opacity:0.6;">expand_more</span>
                        </button>
                    </div>` : ''}
                    <div style="display:flex; flex-wrap:wrap; gap:4px;">${chipsHtml}</div>
                </div>
            </div>`;
        });
    }
    listEl.innerHTML = html;
}

// Build a single shared fixed dropdown menu (portaled to body)
function openExtGroupDropdown(groupId, btnEl) {
    let menu = document.getElementById('ext-group-fixed-menu');
    if (!menu) {
        menu = document.createElement('div');
        menu.id = 'ext-group-fixed-menu';
        menu.className = 'ext-group-dropdown-menu';
        document.body.appendChild(menu);
        document.addEventListener('click', e => {
            if (!e.target.closest('.ext-group-dropdown-wrapper') && !e.target.closest('#ext-group-fixed-menu')) {
                menu.classList.remove('open');
            }
        });
    }
    // If already open for same group, close it
    if (menu.dataset.groupId === groupId && menu.classList.contains('open')) {
        menu.classList.remove('open');
        return;
    }
    // Build items for this group
    const g = globalExtensionGroups.find(g => g.id === groupId);
    if (!g) return;
    // Build list: same rules as buildSidebar so both stay in sync
    const enabledSet = new Set(allAvailableExtensions.filter(e => e.enabled).map(e => e.name));
    const extApiMap  = {};
    allAvailableExtensions.forEach(e => extApiMap[e.name] = e);
    const alreadyGrouped = new Set(globalExtensionGroups.flatMap(grp => grp.extensions || []));

    // Helper to build one item row
    const makeItem = (extId, icon, displayName) => {
        if (alreadyGrouped.has(extId)) return ''; // already in a group
        if (CORE_NAV_IDS.has(extId)) return '';
        const iconHtml = renderExtIcon(icon);
        return `<div style="display:flex;align-items:center;gap:8px;padding:7px 12px;cursor:pointer;border-radius:6px;"
            onmouseenter="this.style.background='var(--bg3)'" onmouseleave="this.style.background='';"
            onclick="addExtToGroup('${esc(g.id)}', '${esc(extId)}'); document.getElementById('ext-group-fixed-menu').classList.remove('open');">
            <span style="display:flex;align-items:center;width:20px;">${iconHtml}</span>
            <span style="font-size:0.85rem;">${esc(displayName)}</span>
        </div>`;
    };

    let itemsHtml = '';
    const seenInDropdown = new Set();

    // Extension buttons (built-in + static + already loaded dynamic)
    document.querySelectorAll('.nav-item[data-ext]').forEach(btn => {
        const extId   = btn.dataset.ext;
        const isStatic = btn.dataset.extStatic === 'true';
        if (!isStatic && !enabledSet.has(extId)) return;
        if (seenInDropdown.has(extId)) return;
        seenInDropdown.add(extId);
        const reg = EXT_REGISTRY.find(r => r.id === extId) || {};
        const apiExt = extApiMap[extId] || {};
        const icon = apiExt.icon || reg.icon;
        const label = apiExt.display_name || reg.name || extId;
        itemsHtml += makeItem(extId, icon, label);
    });

    // Dynamic external extensions (same as buildSidebar step 4b)
    allAvailableExtensions.forEach(ext => {
        if (!ext.enabled || !ext.display_name) return;
        if (ext.extension_type !== 'external') return;
        if (CORE_NAV_IDS.has(ext.name)) return;
        if (seenInDropdown.has(ext.name)) return;
        const reg = EXT_REGISTRY.find(r => r.id === ext.name) || {};
        if (reg.type === 'core' || reg.type === 'static') return;
        seenInDropdown.add(ext.name);
        itemsHtml += makeItem(ext.name, ext.icon || reg.icon, ext.display_name || reg.name || ext.name);
    });

    if (!itemsHtml) itemsHtml = '<div style="padding:8px 12px;color:var(--text-muted);font-size:0.82rem;">No extensions available</div>';
    menu.innerHTML = itemsHtml;
    menu.dataset.groupId = groupId;
    // Position below button
    const rect = btnEl.getBoundingClientRect();
    menu.style.left = rect.left + 'px';
    menu.style.top = (rect.bottom + 4) + 'px';
    // Ensure it doesn't go off-screen bottom
    requestAnimationFrame(() => {
        const mh = menu.getBoundingClientRect().height;
        if (rect.bottom + 4 + mh > window.innerHeight - 8) {
            menu.style.top = (rect.top - mh - 4) + 'px';
        }
    });
    menu.classList.add('open');
}

function createExtensionGroup() {
    const name = document.getElementById('set-ext-group-name').value.trim();
    const icon = document.getElementById('set-ext-group-icon').value.trim();
    if (!name) return alert('Please enter a group name');
    
    const newGroup = {
        id: 'group_' + Date.now().toString(36),
        name: name,
        icon: icon || 'folder_special',
        extensions: []
    };
    globalExtensionGroups.push(newGroup);
    document.getElementById('set-ext-group-name').value = '';
    document.getElementById('set-ext-group-icon').value = '';
    
    saveExtensionGroups();
}

function deleteExtensionGroup(id) {
    if(!confirm('Delete this group?')) return;
    globalExtensionGroups = globalExtensionGroups.filter(g => g.id !== id);
    saveExtensionGroups();
}

function addExtToGroup(groupId, extId) {
    const group = globalExtensionGroups.find(g => g.id === groupId);
    if (!group) return;
    
    // Remove from other groups first
    globalExtensionGroups.forEach(g => {
        g.extensions = (g.extensions || []).filter(e => e !== extId);
    });
    
    if (!group.extensions) group.extensions = [];
    if (!group.extensions.includes(extId)) group.extensions.push(extId);
    
    saveExtensionGroups();
}

function removeExtFromGroup(groupId, extId) {
    const group = globalExtensionGroups.find(g => g.id === groupId);
    if (!group) return;
    group.extensions = (group.extensions || []).filter(e => e !== extId);
    saveExtensionGroups();
}

async function saveExtensionGroups() {
    try {
        const r = await apiPut('/api/v1/settings', { extension_groups: globalExtensionGroups });
        if (r && r.status === 'success') {
            renderExtensionGroupsSettings();
            buildSidebar(allAvailableExtensions, globalExtensionGroups); // update sidebar immediately
        } else {
            alert('Failed to save groups');
        }
    } catch (e) {
        console.error('saveExtensionGroups failed', e);
        alert('Error saving groups');
    }
}
// ── End Extension Groups Settings ──

// ═══ Init ═══
document.addEventListener('DOMContentLoaded', async () => {
    await loadI18nFromApi();
    loadVersionInfo();
    // Parallel: fetch extensions + settings in one round trip
    const [extData, settingsData] = await Promise.all([
        apiGet('/api/v1/extensions'),
        apiGet('/api/v1/settings'),
    ]);
    // Apply settings
    globalExtensionGroups = settingsData?.extension_groups || [];
    if (settingsData) applyGlobalSettings(settingsData);
    // Build sidebar once — clean, no hardcode, no double fetch
    buildSidebar(extData?.extensions || [], globalExtensionGroups);
    // Restore form values
    const s = localStorage.getItem('tubecli_api');
    if (s) document.getElementById('set-api').value = s;
    if (document.getElementById('set-lang')) document.getElementById('set-lang').value = _lang;
    // Route
    handleRoute();
    // Non-blocking background tasks
    setTimeout(checkExtensionUpdates, 2000);
    _checkStatusesInBackground();
    // Close fixed dropdown on outside click
    document.addEventListener('click', e => {
        if (!e.target.closest('.ext-group-dropdown-wrapper') && !e.target.closest('#ext-group-fixed-menu')) {
            const m = document.getElementById('ext-group-fixed-menu');
            if (m) m.classList.remove('open');
        }
    });
});


