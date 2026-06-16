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
    'ext-douyin-downloader': 'ext-douyin-downloader',
    'ext-douyin_downloader': 'ext-douyin-downloader',
    'ext-livestream': 'ext-livestream',
    'ext-teams': 'ext-teams',
    'ext-story': 'ext-story',
    'ext-video-editor': 'ext-video-editor',
    'ext-studio': 'ext-studio',
    'ext-file-manager': 'ext-file-manager',
    'ext-video-manager': 'ext-video-manager',
    'ext-video-downloader': 'ext-video-downloader',
    'ext-video_downloader': 'ext-video-downloader',
    'ext-subtitle-extractor': 'ext-subtitle-extractor',
    'ext-workflows': 'ext-workflows',
    'workflows': 'ext-workflows',
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
            '--bg-dark': getVar('--bg-dark', '--bg-canvas', '--bg'),
            '--bg-hover': getVar('--bg-hover', '--bg3'),
            '--bg-lighter': getVar('--bg-lighter', '--bg3'),
            '--sidebar-bg': getVar('--bg2', '--bg-secondary'),
            '--surface': getVar('--bg2', '--bg-secondary'),
            '--text': getVar('--text'),
            '--text2': getVar('--text2', '--text-muted'),
            '--text-muted': getVar('--text-muted', '--text2'),
            '--text3': getVar('--text-muted', '--text-subtle'),
            '--muted': getVar('--text-muted', '--text2'),
            '--border': getVar('--border'),
            '--border-subtle': getVar('--border-subtle', '--border'),
            '--card': getVar('--bg3', '--bg2'),
            '--card2': getVar('--bg-lighter', '--bg3'),
            '--card-bg': getVar('--bg3', '--bg2'),
            '--card-border': getVar('--border', '--border-subtle'),
            '--primary': getVar('--primary', '--accent'),
            '--primary-hover': getVar('--primary-hover', '--accent-hover'),
            '--primary-light': getVar('--primary-light'),
            '--accent': getVar('--accent', '--primary'),
            '--accent-hover': getVar('--accent-hover', '--primary-hover'),
            '--cyan': getVar('--cyan'),
            '--purple': getVar('--purple'),
            '--red': getVar('--red'),
            '--green': getVar('--green'),
            '--orange': getVar('--orange'),
            '--yellow': getVar('--yellow'),
            /* Workflow builder internal aliases — auto-derived from above */
            '--bg-deep':    getVar('--bg-dark', '--bg'),
            '--bg-canvas':  getVar('--bg-dark', '--bg'),
            '--bg-surface': getVar('--bg2'),
            '--bg-card':    getVar('--bg3'),
            '--bg-input':   getVar('--bg'),
            '--border-focus': getVar('--primary', '--accent'),
            '--text-primary':   getVar('--text'),
            '--text-secondary': getVar('--text2'),
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
    let hash = window.location.hash.replace('#/', '') || 'dashboard';

    // Support deep linking to extension details
    if (hash.startsWith('extensions/detail/')) {
        const extId = hash.substring('extensions/detail/'.length);
        activateTab('extensions', true);
        
        // Highlight Skills nav item if opening skills
        if (extId === 'skills') {
            document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
            const skillsBtn = document.getElementById('nav-skills');
            if (skillsBtn) skillsBtn.classList.add('active');
        }
        
        setTimeout(() => {
            const ext = EXT_REGISTRY.find(e => e.id === extId);
            if (ext) openExtDetail(extId);
            else openExternalExtDetail(extId);
        }, 150);
        return;
    }
    if (hash === 'skills' || hash === 'ext-skills') {
        activateTab('extensions', true);
        document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
        const skillsBtn = document.getElementById('nav-skills');
        if (skillsBtn) skillsBtn.classList.add('active');
        setTimeout(() => openExtDetail('skills'), 150);
        return;
    }

    const tab = ROUTE_TAB_MAP[hash] || (hash.startsWith('ext-') ? hash : 'dashboard');
    activateTab(tab);
}

function activateTab(tab, skipCloseDetail) {
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
    let panel = document.getElementById('tab-' + tab);
    
    // Auto-create panel for dynamic extensions if missing
    if (!panel && tab.startsWith('ext-')) {
        const extName = tab.replace('ext-', '');
        panel = document.createElement('section');
        panel.className = 'tab-panel';
        panel.id = 'tab-' + tab;
        panel.innerHTML = '<div class="iframe-container"><iframe data-src="/' + extName + '" class="ext-iframe"></iframe></div>';
        const contentArea = document.querySelector('.content');
        if (contentArea) contentArea.appendChild(panel);
    }

    if (panel) panel.classList.add('active');

    // Close extension detail overlay if switching main tabs
    if (!skipCloseDetail) {
        closeExtDetail(true);
    }

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
        if (!btn.dataset.atab) return;
        document.querySelectorAll('#modal-agent .agent-tab-btn').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('#modal-agent .agent-tab-pane').forEach(p => p.classList.remove('active'));
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
    { id:'workflows', tab:'ext-workflows', icon:'sync',       name:'stat.workflows',type:'core', url:'/workflow' },
    { id:'skills',    tab:'skills',       icon:'bolt',       name:'stat.skills',   type:'core' },
    { id:'market',    tab:'ext-market',   icon:'storefront', name:'Marketplace',   type:'core' },
    // extension: shown when API enabled, groupable
    { id:'cloud_api',          tab:'ext-cloud-keys',         icon:'cloud',          name:'dash.cloud_api_keys', type:'extension' },
    { id:'ollama',             tab:'ext-ollama',             icon:'🧠',             name:'Ollama Manager',      type:'extension' },
    { id:'multi_agents',       tab:'ext-teams',              icon:'groups',         name:'Teams AI',            type:'extension' },
    { id:'douyin_downloader',  tab:'ext-douyin-downloader',  icon:'download',       name:'Douyin Downloader',   type:'extension' },
    { id:'video_manager',      tab:'ext-video-manager',      icon:'video_library',  name:'Video Manager',       type:'extension' },
    { id:'sheets_manager',     tab:'ext-sheets',             icon:'table_chart',    name:'Google Sheets',       type:'extension' },
    { id:'calendar_manager',   tab:'ext-calendar',           icon:'calendar_month', name:'Calendar Manager',    type:'extension' },
    { id:'browser_scripts',    tab:'ext-browser-scripts',    icon:'integration_instructions', name:'Script Studio', type:'extension' },
    { id:'livestream',         tab:'ext-livestream',         icon:'cast',           name:'Livestream',          type:'extension' },
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
    const isAlreadyOpen = !overlay.classList.contains('hidden') && title.dataset.currentExtId === name;
    if (isAlreadyOpen) return;
    title.dataset.currentExtId = name;

    if (window.location.hash !== '#/extensions/detail/' + name) {
        window.location.hash = '#/extensions/detail/' + name;
    }

    const urlContainer = document.getElementById('ext-detail-url-container');
    if (urlContainer) urlContainer.innerHTML = '';

    title.textContent = '📦 ' + name;
    body.innerHTML = `
        <div class="iframe-loader" style="position:relative; min-height:300px; background:transparent;">
            <div class="iframe-loader-spinner"></div>
            <div style="color:var(--text-muted); font-size: 0.9rem; font-weight: 500;">${typeof window.T === "function" ? T("chat.loading", "Loading...") : "Loading..."}</div>
        </div>
    `;
    overlay.classList.remove('hidden');

    const info = await apiGet(`/api/v1/extensions/${encodeURIComponent(name)}/info`);
    if (!info || info.error) { body.innerHTML = `<p class="text-muted">Failed to load extension info.</p>`; return; }

    const manifest = info.manifest || {};
    const isEnabled = info.enabled;
    const icon = manifest.icon || '📦';
    const apiPrefix = manifest.api_prefix || '';
    let iconHtmlExt = icon;
    if (icon && icon.length > 2) {
        iconHtmlExt = `<span class="material-symbols-outlined" style="font-size: 28px; vertical-align: bottom; margin-right: 4px;">${icon}</span>`;
    } else {
        iconHtmlExt = `<span style="font-size: 24px; vertical-align: bottom; margin-right: 4px;">${icon}</span>`;
    }
    title.innerHTML = iconHtmlExt + (manifest.display_name || manifest.name || name);

    const gitUrl = info.git_url || info.homepage || manifest.homepage || '';
    if (urlContainer && gitUrl) {
        urlContainer.innerHTML = `<a href="${esc(gitUrl)}" target="_blank" style="color:var(--cyan); text-decoration:none; display:flex; align-items:center; gap:4px;"><span class="material-symbols-outlined" style="font-size:16px;">link</span> ${esc(gitUrl)}</a>`;
    }

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
        'douyin_downloader': 'ext-douyin-downloader',
        'video_downloader': 'ext-video-downloader',
        'multi_agents': 'ext-teams',
        'story_engine': 'ext-story',
        'video_editor': 'ext-video-editor',
        'file_manager': 'ext-file-manager',
        'studio3d': 'ext-studio',
        'video_manager': 'ext-video-manager',
        'subtitle_extractor': 'ext-subtitle-extractor',
        'cloud_api': 'ext-cloud-keys',
        'workflows': 'ext-workflows',
    };
    if (hashRoutes[id]) { navigateTo(hashRoutes[id]); return; }

    const ext = EXT_REGISTRY.find(e => e.id === id);
    if (!ext) return;
    const overlay = document.getElementById('ext-detail-overlay');
    const title = document.getElementById('ext-detail-title');
    const body = document.getElementById('ext-detail-body');
    const isAlreadyOpen = !overlay.classList.contains('hidden') && title.dataset.currentExtId === id;
    if (isAlreadyOpen) return;
    title.dataset.currentExtId = id;

    if (window.location.hash !== '#/extensions/detail/' + id) {
        window.location.hash = '#/extensions/detail/' + id;
    }

    const urlContainer = document.getElementById('ext-detail-url-container');
    if (urlContainer) urlContainer.innerHTML = '';
    const tabExt = document.getElementById('tab-extensions');
    if (tabExt) tabExt.style.display = 'none';

    let iconHtml = ext.icon;
    if (ext.icon && ext.icon.length > 2) {
        iconHtml = `<span class="material-symbols-outlined" style="font-size: 28px; vertical-align: bottom; margin-right: 4px;">${ext.icon}</span>`;
    } else {
        iconHtml = `<span style="font-size: 24px; vertical-align: bottom; margin-right: 4px;">${ext.icon}</span>`;
    }
    title.innerHTML = iconHtml + (typeof window.T === 'function' ? T(ext.name) : ext.name);
    body.innerHTML = `
        <div class="iframe-loader" style="position:relative; min-height:400px; background:transparent;">
            <div class="iframe-loader-spinner"></div>
            <div style="color:var(--text-muted); font-size: 0.9rem; font-weight: 500;">${typeof window.T === "function" ? T("chat.loading", "Loading...") : "Loading..."}</div>
        </div>
    `;
    overlay.classList.remove('hidden');

    // Display URL if extension info is available in allAvailableExtensions
    const dbExt = (typeof allAvailableExtensions !== 'undefined' ? allAvailableExtensions : []).find(e => e.name === id);
    const gitUrl = dbExt?.git_url || dbExt?.homepage || '';
    if (urlContainer && gitUrl) {
        urlContainer.innerHTML = `<a href="${esc(gitUrl)}" target="_blank" style="color:var(--cyan); text-decoration:none; display:flex; align-items:center; gap:4px;"><span class="material-symbols-outlined" style="font-size:16px;">link</span> ${esc(gitUrl)}</a>`;
    }

    // Route to detail renderer
    stopBrowserStatusPoller();
    if (id === 'agents') renderAgentsExt(body);
    else if (id === 'browser') renderBrowserExt(body);
    else if (id === 'workflows') renderFullPageExt(body, 'Workflow Builder', 'Visual workflow automation.', '/workflow');
    else if (id === 'skills') renderSkillsExt(body);
    else if (id === 'cloud_api') renderCloudApiExt(body);
    else if (id === 'ollama') renderOllamaExt(body);
    else if (id === 'video_editor') renderFullPageExt(body, 'Video Editor', 'AI-powered Video Editor with Timeline & FFmpeg Processing.', '/video-editor');
}
function closeExtDetail(skipHashReset) { 
    document.getElementById('ext-detail-overlay').classList.add('hidden'); 
    const tabExt = document.getElementById('tab-extensions');
    if (tabExt) tabExt.style.display = '';
    const urlContainer = document.getElementById('ext-detail-url-container');
    if (urlContainer) urlContainer.innerHTML = '';
    const title = document.getElementById('ext-detail-title');
    if (title) delete title.dataset.currentExtId;
    
    if (!skipHashReset) {
        const hash = window.location.hash;
        if (hash.includes('/detail/') || hash === '#/skills' || hash === '#/ext-skills') {
            window.location.hash = '#/extensions';
        }
    }
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
    el.innerHTML = `
        <div class="iframe-loader" style="position:relative; min-height:300px; background:transparent;">
            <div class="iframe-loader-spinner"></div>
            <div style="color:var(--text-muted); font-size: 0.9rem; font-weight: 500;">${typeof window.T === "function" ? T("cal.loading", "Loading Calendar Manager...") : "Loading Calendar Manager..."}</div>
        </div>
    `;

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
    if (!el) return;
    const isPoller = el.querySelector('.cards-grid') || el.querySelector('.text-muted');
    if (!isPoller) {
        el.innerHTML = `
            <div class="iframe-loader" style="position:relative; min-height:300px; background:transparent;">
                <div class="iframe-loader-spinner"></div>
                <div style="color:var(--text-muted); font-size: 0.9rem; font-weight: 500;">${typeof window.T === "function" ? T("chat.loading", "Loading...") : "Loading..."}</div>
            </div>
        `;
    }
    const data = await apiGet('/api/v1/agents');
    const agents = data?.agents || [];
    agents.sort((a, b) => {
        const dateA = a.created_at ? new Date(a.created_at) : 0;
        const dateB = b.created_at ? new Date(b.created_at) : 0;
        return dateB - dateA;
    });
    let h = `<div style="display:flex;gap:10px;margin-bottom:20px">
        <button class="btn-primary" style="background:linear-gradient(135deg,#a855f7,#ec4899)" onclick="showGenerateAgent()">${T('agents.generate_ai')}</button>
        <button class="btn-primary" onclick="showCreateAgent()">${T('agents.create')}</button>
    </div>`;
    if (agents.length === 0) h += `<p class="text-muted">${T('agents.no_agents')}</p>`;
    else h += '<div class="cards-grid">' + agents.map(a => `<div class="card" style="display:flex;flex-direction:column;padding:16px;"><div style="display:flex;gap:12px;align-items:flex-start;margin-bottom:12px;"><div class="card-icon" style="margin:0;width:42px;height:42px;border-radius:10px;background:rgba(255,255,255,0.05);display:flex;align-items:center;justify-content:center;flex-shrink:0;">${a.avatar_icon && a.avatar_icon !== 'SMART_TOY' && a.avatar_icon !== 'smart_toy' ? (!/^[a-zA-Z_0-9-]+$/.test(a.avatar_icon) ? '<span style="font-size:24px">' + esc(a.avatar_icon) + '</span>' : '<span class="material-symbols-outlined" style="font-size: 28px;">' + esc(a.avatar_icon.toLowerCase()) + '</span>') : '<span class="material-symbols-outlined" style="font-size: 28px;">smart_toy</span>'}</div><div style="flex:1;min-width:0;"><h3 style="margin:0 0 4px 0;font-size:1.05rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(a.name)}</h3><p class="card-meta" style="margin:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(a.model||'default')}</p></div></div><p class="card-desc" style="flex:1;margin:0 0 16px 0;line-height:1.4;">${esc(a.description||'')}</p><div class="card-footer" style="padding-top:12px;border-top:1px solid var(--border);"><span class="tag">${(a.allowed_skills||[]).length} ${T('agents.skills_count')}</span><div class="card-actions"><button class="btn-sm btn-primary" onclick="openChatAgent('${a.id}','${esc(a.name)}')">${T('agents.chat')}</button><button class="btn-sm" onclick="openEditAgent('${a.id}')">${T('agents.edit')}</button><button class="btn-sm btn-danger" onclick="deleteAgent('${a.id}');renderAgentsExt(getAgentsBody())">${T('agents.delete')}</button></div></div></div>`).join('') + '</div>';
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
    if (!el) return;
    const isPoller = el.querySelector('.cards-grid') || el.querySelector('.text-muted');
    if (!isPoller) {
        el.innerHTML = `
            <div class="iframe-loader" style="position:relative; min-height:300px; background:transparent;">
                <div class="iframe-loader-spinner"></div>
                <div style="color:var(--text-muted); font-size: 0.9rem; font-weight: 500;">${typeof window.T === "function" ? T("chat.loading", "Loading...") : "Loading..."}</div>
            </div>
        `;
    }
    const data = await apiGet('/api/v1/browser/profiles');
    const profiles = data?.profiles || [];
    const status = await apiGet('/api/v1/browser/status');
    const runningInstances = (status?.instances||[]).filter(i => i.status === 'running');
    const runningProfiles = runningInstances.map(i => i.profile);
    _lastRunningProfiles = runningProfiles.slice().sort().join(',');
    startBrowserStatusPoller(el);
    let h = `<div style="margin-bottom:16px;display:flex;gap:10px"><button class="btn-primary" onclick="showCreateProfile()">${T('browser.new_profile')}</button><button class="btn-secondary" onclick="showBrowserEnginesModal()">${T('browser.engines', 'Browser Engines')}</button></div>`;
    if (runningInstances.length > 0) h += `<div class="status-bar"><span class="pulse-dot"></span> ${runningInstances.length} ${T('status.running')}</div>`;
    if (profiles.length === 0) h += `<p class="text-muted">${T('browser.no_profiles')}</p>`;
    else h += '<div class="cards-grid">' + profiles.map(p => {
        const isR = runningProfiles.includes(p.name);
        const hasGA = p.google_account && p.google_account.email;
        return `<div class="card" style="position:relative"><button class="btn-settings" onclick="showProfileSettings('${esc(p.name)}')" title="${T('browser.settings', 'Settings')}">⚙️</button><div class="card-icon">🌐</div><h3>${esc(p.name)} ${isR ? '<span class="pulse-dot" style="display:inline-block"></span>' : ''}</h3><p class="card-meta">${esc(p.proxy||T('browser.no_proxy'))}</p><p class="card-desc">${p.has_fingerprint ? T('browser.fp_ok', '🧬 FP OK') : `<span style="color:var(--orange)">${T('browser.no_fp', '⚠️ No FP')}</span>`} ${p.has_cookies ? '🍪' : ''} ${hasGA ? '<span style="color:var(--green)">🔐 ' + esc(p.google_account.email) + '</span>' : ''}</p><div class="card-footer" style="flex-wrap:wrap;gap:8px"><span class="tag green">${esc((p.created_at||'').slice(0,10))}</span><div class="card-actions">${isR ? `<button class="btn-sm btn-danger" onclick="stopProfile('${esc(p.name)}',this)">⏹</button>` : `<button class="btn-sm" onclick="launchProfile('${esc(p.name)}',this)">▶</button>`}<button class="btn-sm" onclick="openWSProfile('${esc(p.name)}')" title="Mở Browser Remote (Tab mới)" style="background:linear-gradient(135deg,#06b6d4,#3b82f6);color:#fff">🌐 Remote</button><button class="btn-danger" onclick="deleteProfile('${esc(p.name)}');setTimeout(()=>renderBrowserExt(getBrowserBody()),500)">✕</button></div></div></div>`;
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
        return { cat: 'markdown', label: T('skills.cat_markdown'), color: '#ec4899', icon: '📝' };
        
    if (skill.skill_type === 'Workflow Skill' || nodes.some(n => n.type === 'google_sheets' || n.type === 'google_auth'))
        return { cat: 'workflow', label: T('skills.cat_workflow'), color: '#a855f7', icon: '🔧' };
        
    if (nodeTypes.includes('browser_action'))
        return { cat: 'browser', label: T('skills.cat_browser'), color: '#22d3ee', icon: '🌐' };
        
    if (nodeTypes.includes('api_request'))
        return { cat: 'api', label: T('skills.cat_api'), color: '#ef4444', icon: '⚡' };
        
    if (nodeTypes.includes('ai_node'))
        return { cat: 'ai', label: T('skills.cat_ai'), color: '#22c55e', icon: '🧠' };
        
    return { cat: 'general', label: T('skills.cat_general'), color: '#f59e0b', icon: '⚡' };
}

async function renderSkillsExt(el) {
    el.innerHTML = `
        <div class="iframe-loader" style="position:relative; min-height:300px; background:transparent;">
            <div class="iframe-loader-spinner"></div>
            <div style="color:var(--text-muted); font-size: 0.9rem; font-weight: 500;">${typeof window.T === "function" ? T("skills.loading", "Loading Skills...") : "Loading Skills..."}</div>
        </div>
    `;
    const data = await apiGet('/api/v1/skills');
    const skills = data?.skills || [];
    _loadedSkills = skills; // cache
    
    let html = `
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px; gap:16px;">
        <div style="position: relative; display: flex; align-items: center;">
            <span class="material-symbols-outlined" style="position: absolute; left: 12px; color: var(--text-muted); font-size: 20px;">search</span>
            <input type="text" id="skills-search-input" class="input" placeholder="${T('skills.search')}" oninput="filterSkillsList()" style="width:320px; padding:10px 12px 10px 40px; margin:0; border-radius: 20px; background: var(--bg2); border: 1px solid var(--border); box-shadow: 0 2px 5px rgba(0,0,0,0.05); transition: all 0.3s; font-size: 0.9rem;" onfocus="this.style.boxShadow='0 0 0 2px var(--accent)';" onblur="this.style.boxShadow='0 2px 5px rgba(0,0,0,0.05)';">
        </div>
        <button class="btn-primary" onclick="openCreateSkillModal()" style="display:flex; align-items:center; gap:6px; background:linear-gradient(135deg, var(--accent), #7c3aed); font-weight:600; padding:10px 18px; border-radius:8px;">
            <span class="material-symbols-outlined" style="font-size:20px;">add_circle</span> ${T('skills.btn_create_new').replace('add_circle ', '')}
        </button>
    </div>
    <div id="skills-list-container">
    `;
    
    if (skills.length === 0) { 
        html += `<p class="text-muted" style="padding: 20px 0;">${T('skills.no_skills')}</p></div>`; 
        el.innerHTML = html;
        return; 
    }
    
    html += '<div class="cards-grid" id="skills-cards-grid">';
    
    skills.forEach(s => {
        const cat = categorizeSkill(s);
        
        let actionsHtml = `<div style="display: flex; width: 100%; justify-content: space-between; align-items: center; padding-top: 4px;">`;
        actionsHtml += `<button class="btn-sm" style="background:linear-gradient(135deg,#10b981,#22c55e); color:#fff; border-color:transparent; display: flex; align-items: center; gap: 4px; padding: 6px 14px; font-weight: 600; border-radius: 8px; box-shadow: 0 4px 6px rgba(16,185,129,0.2);" onclick="openRunSkillModal('${s.id}', '${esc(s.name)}')">${T('skills.btn_run_test')}</button>`;

        actionsHtml += `<div style="display: flex; gap: 6px; align-items: center;">`;
        actionsHtml += `<button class="btn-icon btn-sm" onclick="showSkillMarkdown('${s.id}')" title="${T('skills.title_view_md')}" style="padding:4px; border-radius:6px; min-width:32px; height:32px;"><span class="material-symbols-outlined" style="font-size: 18px;">visibility</span></button>`;
        actionsHtml += `<button class="btn-icon btn-sm" onclick="openEditSkillModal('${s.id}')" title="${T('skills.title_edit')}" style="padding:4px; border-radius:6px; min-width:32px; height:32px;"><span class="material-symbols-outlined" style="font-size: 18px;">edit</span></button>`;
        
        if (cat.cat === 'workflow' || cat.cat === 'browser' || cat.cat === 'general' || cat.cat === 'api' || cat.cat === 'ai') {
            actionsHtml += `<button class="btn-icon btn-sm" onclick="window.open('/workflow?skill_id=${s.id}', '_blank')" title="${T('skills.title_edit_wf')}" style="padding:4px; border-radius:6px; min-width:32px; height:32px;"><span class="material-symbols-outlined" style="font-size: 18px;">account_tree</span></button>`;
        }
        
        actionsHtml += `<button class="btn-icon btn-sm btn-danger-icon" onclick="deleteSkill('${s.id}')" title="${T('skills.title_delete')}" style="padding:4px; border-radius:6px; min-width:32px; height:32px; color: var(--danger);"><span class="material-symbols-outlined" style="font-size: 18px;">delete</span></button>`;
        actionsHtml += `</div></div>`;

        html += `
        <div class="card skill-item-card" data-name="${esc(s.name.toLowerCase())}" data-desc="${esc((s.description||'').toLowerCase())}" style="display:flex; flex-direction:column;">
            <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:12px;">
                <div class="card-icon" style="margin:0; width:40px; height:40px; border-radius:10px; font-size:1.2rem; background:rgba(0,0,0,0.2); box-shadow:0 4px 10px rgba(0,0,0,0.1); display:flex; align-items:center; justify-content:center;">${cat.icon}</div>
                <span class="tag" style="background:${cat.color}20; color:${cat.color}; border:1px solid ${cat.color}40; font-size:0.75rem; font-weight:600;">${cat.label}</span>
            </div>
            <h3 style="margin-bottom:8px; font-size:1.05rem;">${esc(s.name)}</h3>
            <p class="card-desc" style="flex:1; margin-bottom:16px;">${esc(s.description||'')}</p>
            <div style="font-size:0.8rem; color:var(--text-muted); margin-bottom:12px; background:var(--bg2); padding:6px 10px; border-radius:6px; font-family:'JetBrains Mono', monospace; word-break:break-all;">
                <strong style="color:var(--text)">${T('skills.lbl_input_schema')}</strong> ${s.commands && s.commands.length > 0 ? "['" + esc(s.commands.join("', '")) + "']" : T('skills.val_text_prompt')}
            </div>
            <div class="card-footer" style="padding-top:12px; border-top:1px solid var(--border); display:flex; gap:6px; flex-wrap:wrap;">
                ${actionsHtml}
            </div>
        </div>`;
    });
    
    html += '</div></div>';
    el.innerHTML = html;
}

function filterSkillsList() {
    const q = document.getElementById('skills-search-input').value.trim().toLowerCase();
    document.querySelectorAll('#skills-cards-grid .skill-item-card').forEach(card => {
        const name = card.dataset.name || '';
        const desc = card.dataset.desc || '';
        if (name.includes(q) || desc.includes(q)) {
            card.style.display = 'flex';
        } else {
            card.style.display = 'none';
        }
    });
}

async function deleteSkill(skillId) {
    if (!confirm('Bạn có chắc chắn muốn xóa Skill này? Hành động này không thể hoàn tác.')) return;
    try {
        const res = await apiDelete(`/api/v1/skills/${skillId}`);
        if (res && res.status === 'deleted') {
            // Reload list
            const body = document.getElementById('ext-detail-body');
            renderSkillsExt(body);
        } else {
            alert('Lỗi xóa skill: ' + (res?.message || res?.error || 'Unknown error'));
        }
    } catch(e) {
        alert('Lỗi kết nối: ' + e.message);
    }
}

function switchSkillCreateTab(tabName) {
    const manualBtn = document.getElementById('btn-tab-skill-manual');
    const aiBtn = document.getElementById('btn-tab-skill-ai');
    const manualPane = document.getElementById('tab-skill-manual');
    const aiPane = document.getElementById('tab-skill-ai');
    
    if (tabName === 'manual') {
        manualBtn.classList.add('active');
        aiBtn.classList.remove('active');
        manualPane.classList.add('active');
        aiPane.classList.remove('active');
    } else {
        manualBtn.classList.remove('active');
        aiBtn.classList.add('active');
        manualPane.classList.remove('active');
        aiPane.classList.add('active');
    }
}

function toggleManualSkillFields() {
    const type = document.getElementById('skill-type-select').value;
    const markdownGroup = document.getElementById('group-skill-markdown');
    if (type === 'Markdown' || type === 'Extension Skill' || type === 'Extension') {
        markdownGroup.style.display = 'block';
    } else {
        markdownGroup.style.display = 'none';
    }
}

function openCreateSkillModal() {
    document.getElementById('skill-modal-title').innerHTML = T('skills.create.title', '✨ Tạo Skill Mới');
    document.getElementById('skill-edit-id').value = '';
    
    document.getElementById('skill-name-input').value = '';
    document.getElementById('skill-type-select').value = 'Markdown';
    document.getElementById('skill-desc-input').value = '';
    document.getElementById('skill-trigger-input').value = '';
    document.getElementById('skill-markdown-input').value = '';
    
    document.getElementById('skill-ai-prompt').value = '';
    document.getElementById('skill-ai-name').value = '';
    document.getElementById('skill-ai-desc').value = '';
    document.getElementById('skill-ai-trigger').value = '';
    document.getElementById('skill-ai-markdown').value = '';
    
    document.getElementById('skill-ai-preview-container').style.display = 'none';
    document.getElementById('skill-ai-loading').style.display = 'none';
    
    toggleManualSkillFields();
    switchSkillCreateTab('manual');
    loadSkillAIModels();
    
    openModal('modal-create-skill');
}

function openEditSkillModal(skillId) {
    const skill = _loadedSkills.find(s => s.id === skillId);
    if (!skill) return;
    
    document.getElementById('skill-modal-title').textContent = '✏️ Chỉnh sửa Skill';
    document.getElementById('skill-edit-id').value = skill.id;
    
    document.getElementById('skill-name-input').value = skill.name || '';
    document.getElementById('skill-type-select').value = skill.skill_type || 'Markdown';
    document.getElementById('skill-desc-input').value = skill.description || '';
    document.getElementById('skill-trigger-input').value = (skill.commands || []).join(', ');
    document.getElementById('skill-markdown-input').value = skill.workflow_data?.markdown || skill.workflow_data?.sop || '';
    
    document.getElementById('skill-ai-prompt').value = '';
    document.getElementById('skill-ai-name').value = '';
    document.getElementById('skill-ai-desc').value = '';
    document.getElementById('skill-ai-trigger').value = '';
    document.getElementById('skill-ai-markdown').value = '';
    
    document.getElementById('skill-ai-preview-container').style.display = 'none';
    document.getElementById('skill-ai-loading').style.display = 'none';
    
    toggleManualSkillFields();
    switchSkillCreateTab('manual');
    loadSkillAIModels();
    
    openModal('modal-create-skill');
}

async function loadSkillAIModels() {
    const provider = document.getElementById('skill-ai-provider').value;
    const modelSel = document.getElementById('skill-ai-model');
    if (!modelSel) return;
    
    modelSel.innerHTML = '<option value="">⏳ Đang tải các model...</option>';
    
    try {
        if (provider === 'ollama') {
            const ollama = await apiGet('/api/v1/ollama/models');
            if (ollama && ollama.models && ollama.models.length > 0) {
                modelSel.innerHTML = ollama.models.map(m => `<option value="${esc(m.name || m)}">${esc(m.name || m)}</option>`).join('');
            } else {
                modelSel.innerHTML = '<option value="qwen:latest">qwen:latest (Mặc định)</option><option disabled>⚠️ Ollama chưa chạy</option>';
            }
        } else if (provider === '9router') {
            const nrStatus = await apiGet('/api/v1/cloud-api/9router/status');
            if (nrStatus?.running && nrStatus.models && nrStatus.models.length > 0) {
                modelSel.innerHTML = nrStatus.models.map(m => `<option value="${esc(m)}">${esc(m)}</option>`).join('');
            } else {
                modelSel.innerHTML = '<option value="deepseek-chat">deepseek-chat (Mặc định)</option><option disabled>⚠️ 9Router chưa chạy</option>';
            }
        } else {
            const cloud = await apiGet('/api/v1/cloud-api/providers');
            if (cloud && cloud.providers) {
                const mappedProv = provider === 'chatgpt' ? 'openai' : provider;
                const match = cloud.providers.find(p => p.id === mappedProv);
                if (match && match.models && match.models.length > 0) {
                    modelSel.innerHTML = match.models.map(m => `<option value="${esc(m)}">${esc(m)}</option>`).join('');
                } else {
                    const fallbacks = {
                        'gemini': ['gemini-2.0-flash', 'gemini-2.0-pro-exp', 'gemini-1.5-pro', 'gemini-1.5-flash'],
                        'chatgpt': ['gpt-4o-mini', 'gpt-4o', 'o1-mini', 'gpt-3.5-turbo'],
                        'claude': ['claude-3-5-sonnet-latest', 'claude-3-5-haiku-latest', 'claude-3-opus-latest'],
                        'deepseek': ['deepseek-chat', 'deepseek-reasoner'],
                        'grok': ['grok-2-1212', 'grok-beta']
                    };
                    const models = fallbacks[provider] || ['default'];
                    modelSel.innerHTML = models.map(m => `<option value="${esc(m)}">${esc(m)}</option>`).join('');
                }
            } else {
                const fallbacks = {
                    'gemini': ['gemini-2.0-flash', 'gemini-2.0-pro-exp', 'gemini-1.5-pro', 'gemini-1.5-flash'],
                    'chatgpt': ['gpt-4o-mini', 'gpt-4o', 'o1-mini', 'gpt-3.5-turbo'],
                    'claude': ['claude-3-5-sonnet-latest', 'claude-3-5-haiku-latest', 'claude-3-opus-latest'],
                    'deepseek': ['deepseek-chat', 'deepseek-reasoner'],
                    'grok': ['grok-2-1212', 'grok-beta']
                };
                const models = fallbacks[provider] || ['default'];
                modelSel.innerHTML = models.map(m => `<option value="${esc(m)}">${esc(m)}</option>`).join('');
            }
        }
    } catch(e) {
        console.warn('Failed to fetch models for provider:', provider, e);
        modelSel.innerHTML = '<option value="">Chọn model...</option>';
    }
}

async function generateSkillWithAI() {
    const prompt = document.getElementById('skill-ai-prompt').value.trim();
    if (!prompt) {
        alert('Vui lòng nhập yêu cầu thiết kế Skill.');
        return;
    }
    
    const provider = document.getElementById('skill-ai-provider').value;
    const model = document.getElementById('skill-ai-model').value;
    
    const loadingDiv = document.getElementById('skill-ai-loading');
    const previewContainer = document.getElementById('skill-ai-preview-container');
    const generateBtn = document.getElementById('btn-generate-skill-ai');
    
    loadingDiv.style.display = 'block';
    previewContainer.style.display = 'none';
    generateBtn.disabled = true;
    
    try {
        const payload = {
            prompt: prompt,
            provider: provider,
            model: model,
            api_key: '__CLOUD_API__'
        };
        
        const res = await apiPost('/api/v1/skills/generate-ai', payload);
        
        if (res && res.status === 'success' && res.skill) {
            const skill = res.skill;
            
            document.getElementById('skill-ai-name').value = skill.name || '';
            document.getElementById('skill-ai-type').value = skill.skill_type || 'Markdown';
            document.getElementById('skill-ai-desc').value = skill.description || '';
            document.getElementById('skill-ai-trigger').value = (skill.commands || []).join(', ');
            
            const groupMd = document.getElementById('group-skill-ai-markdown');
            const groupWf = document.getElementById('group-skill-ai-workflow');
            
            window._generatedAISkillWorkflow = skill.workflow_data || {};
            
            if (skill.skill_type === 'Markdown') {
                groupMd.style.display = 'block';
                groupWf.style.display = 'none';
                document.getElementById('skill-ai-markdown').value = skill.workflow_data?.markdown || '';
            } else {
                groupMd.style.display = 'none';
                groupWf.style.display = 'block';
                const nodeCount = (skill.workflow_data?.nodes || []).length;
                const connCount = (skill.workflow_data?.connections || []).length;
                document.getElementById('skill-ai-workflow-summary').innerHTML = 
                    `Số lượng Node: <strong style="color:var(--cyan);">${nodeCount}</strong> | Số lượng Kết nối: <strong style="color:var(--cyan);">${connCount}</strong>.`;
            }
            
            previewContainer.style.display = 'block';
        } else {
            alert('Lỗi thiết kế Skill: ' + (res?.error || res?.message || 'Không có kết quả trả về. Vui lòng kiểm tra API Key/Ollama.'));
        }
    } catch(e) {
        alert('Lỗi kết nối: ' + e.message);
    } finally {
        loadingDiv.style.display = 'none';
        generateBtn.disabled = false;
    }
}

async function saveCreatedSkill() {
    const isManual = document.getElementById('btn-tab-skill-manual').classList.contains('active');
    
    let id, name, description, trigger, skill_type, workflow_data;
    
    if (isManual) {
        id = document.getElementById('skill-edit-id').value;
        name = document.getElementById('skill-name-input').value.trim();
        skill_type = document.getElementById('skill-type-select').value;
        description = document.getElementById('skill-desc-input').value.trim();
        trigger = document.getElementById('skill-trigger-input').value.trim();
        
        if (!name) {
            alert(T('skills.create.alert_no_name', 'Vui lòng nhập Tên Skill.'));
            return;
        }
        
        let baseWfData = {};
        if (id) {
            const existing = _loadedSkills.find(s => s.id === id);
            if (existing && existing.workflow_data) {
                baseWfData = { ...existing.workflow_data };
            }
        }
        
        if (skill_type === 'Markdown' || skill_type === 'Extension Skill' || skill_type === 'Extension') {
            const markdown = document.getElementById('skill-markdown-input').value;
            workflow_data = { ...baseWfData };
            if (skill_type === 'Markdown') {
                workflow_data.markdown = markdown;
            } else {
                workflow_data.sop = markdown;
            }
            workflow_data.nodes = workflow_data.nodes || [];
            workflow_data.connections = workflow_data.connections || [];
        } else {
            let existingNodes = baseWfData.nodes || [];
            let existingConns = baseWfData.connections || [];
            
            if (existingNodes.length === 0) {
                const OFFSET = 25000;
                existingNodes = [
                    {
                        id: "node_1",
                        type: "text_input",
                        label: "Input Prompt",
                        x: OFFSET + 100,
                        y: OFFSET + 150,
                        config: { text: "" }
                    },
                    {
                        id: "node_2",
                        type: "output",
                        label: "Output",
                        x: OFFSET + 450,
                        y: OFFSET + 150,
                        config: {}
                    }
                ];
                existingConns = [
                    {
                        from_node_id: "node_1",
                        from_port_id: "content",
                        to_node_id: "node_2",
                        to_port_id: "data"
                    }
                ];
            }
            
            workflow_data = {
                ...baseWfData,
                nodes: existingNodes,
                connections: existingConns
            };
        }
    } else {
        const previewContainer = document.getElementById('skill-ai-preview-container');
        if (previewContainer.style.display === 'none') {
            alert('Vui lòng thực hiện thiết kế Skill bằng AI trước khi lưu.');
            return;
        }
        
        id = '';
        name = document.getElementById('skill-ai-name').value.trim();
        skill_type = document.getElementById('skill-ai-type').value;
        description = document.getElementById('skill-ai-desc').value.trim();
        trigger = document.getElementById('skill-ai-trigger').value.trim();
        
        if (!name) {
            alert(T('skills.create.alert_no_name', 'Vui lòng nhập Tên Skill.'));
            return;
        }
        
        if (skill_type === 'Markdown') {
            const markdown = document.getElementById('skill-ai-markdown').value;
            workflow_data = {
                markdown: markdown,
                nodes: [],
                connections: []
            };
        } else {
            workflow_data = window._generatedAISkillWorkflow || { nodes: [], connections: [], markdown: '' };
        }
    }
    
    const payload = {
        name: name,
        description: description,
        skill_type: skill_type,
        trigger: trigger,
        workflow_data: workflow_data
    };
    
    const saveBtn = document.getElementById('btn-save-created-skill');
    saveBtn.disabled = true;
    saveBtn.textContent = '⏳ Đang lưu...';
    
    try {
        let res;
        if (id) {
            res = await apiPut(`/api/v1/skills/${id}`, payload);
        } else {
            res = await apiPost('/api/v1/skills', payload);
        }
        
        if (res && (res.status === 'created' || res.status === 'updated')) {
            closeModal('modal-create-skill');
            const body = document.getElementById('ext-detail-body');
            renderSkillsExt(body);
        } else {
            alert('Lỗi lưu skill: ' + (res?.message || res?.error || 'Unknown error'));
        }
    } catch(e) {
        alert('Lỗi kết nối: ' + e.message);
    } finally {
        saveBtn.disabled = false;
        saveBtn.textContent = '💾 Lưu Skill';
    }
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
    if (skill.workflow_data?.sop) {
        md += `\n### Hướng dẫn thao tác (SOP)\n${skill.workflow_data.sop}\n`;
        if (skill.workflow_data.extension) {
            md += `\n**Extension:** ${skill.workflow_data.extension} | **Action:** ${skill.workflow_data.action || 'N/A'}\n`;
        }
    }
    if (nodes) {
        md += `\n${nodes}\n\n### Chuyển giao dữ liệu (Connections)\n${connections}`;
    } else if (!skill.workflow_data?.sop) {
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
    document.getElementById('btn-execute-skill').innerHTML = T('skills.run.btn_execute', '🚀 Thực thi');
    
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
        btn.innerHTML = T('skills.run.btn_execute_again', '🚀 Thực thi lại');
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
    if (!el) return;
    const isPoller = el.querySelector('.cards-grid') || el.querySelector('.table-container') || el.querySelector('.text-muted');
    if (!isPoller) {
        el.innerHTML = `
            <div class="iframe-loader" style="position:relative; min-height:300px; background:transparent;">
                <div class="iframe-loader-spinner"></div>
                <div style="color:var(--text-muted); font-size: 0.9rem; font-weight: 500;">${typeof window.T === "function" ? T("chat.loading", "Loading...") : "Loading..."}</div>
            </div>
        `;
    }
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
    'agents': { icon: 'smart_toy', label: 'Agents', desc_vi: 'Quản lý AI agents, tạo, sửa, xóa, chat', desc_en: 'Manage AI agents — create, edit, delete, chat' },
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

function showCreateAgent() {
    document.getElementById('agent-modal-title').textContent = T('agent_modal.create_title') || 'Create Agent';
    document.getElementById('agent-id').value='';
    document.getElementById('agent-name').value='';
    document.getElementById('agent-desc').value='';
    document.getElementById('agent-prompt').value='You are a helpful AI assistant.';
    document.getElementById('agent-icon').value='smart_toy';
    document.getElementById('agent-interests').value='';
    document.getElementById('agent-behavior').value='{\n  "dailyRoutine": [],\n  "workHabits": {}\n}';
    document.getElementById('agent-proxy-mode').value='none';
    document.getElementById('agent-proxy').value='';
    onProxyModeChange();
    document.getElementById('agent-schedule-enable').checked=false;
    document.getElementById('agent-timezone').value='Asia/Ho_Chi_Minh';
    document.getElementById('agent-schedule-repeat').value='daily';
    document.getElementById('agent-schedule-interval').value='60';
    document.getElementById('agent-schedule-start').value='08:00';
    document.getElementById('agent-schedule-end').value='22:00';
    document.getElementById('agent-schedule-max-runs').value='10';
    document.querySelectorAll('.agent-day-cb').forEach((cb,i)=>cb.checked=i<5);
    onScheduleRepeatChange();
    document.getElementById('agent-scraping-enable').checked=false;
    document.getElementById('agent-scraper-limit').value='10000';
    document.getElementById('agent-scraper-format').value='json';
    document.getElementById('agent-tg-token').value='';
    document.getElementById('agent-tg-chat').value='';
    document.getElementById('agent-ms-token').value='';
    document.getElementById('agent-ms-page').value='';
    document.getElementById('agent-ms-php').value='';
    document.getElementById('agent-ms-skill').value='';
    populateAgentProfiles([]);
    populateAgentSkills([]);
    document.querySelector('.agent-tab-btn[data-atab="identity"]').click();
    document.getElementById('modal-agent').classList.remove('hidden');
    // Load model dropdowns with global default (async, non-blocking)
    apiGet('/api/v1/settings').then(s => {
        const defaultModel = s?.default_model || 'qwen:latest';
        populateAgentModelDropdown('chatbot', defaultModel);
        populateAgentModelDropdown('browser', defaultModel);
    }).catch(() => {
        populateAgentModelDropdown('chatbot', 'qwen:latest');
        populateAgentModelDropdown('browser', 'qwen:latest');
    });
}

async function openEditAgent(id) {
    const d = await apiGet('/api/v1/agents/'+id);
    if (!d) return alert('Failed');
    document.getElementById('agent-modal-title').textContent = (T('agent_modal.edit_title') || 'Edit:') + ' ' + d.name;
    document.getElementById('agent-id').value=d.id;
    document.getElementById('agent-name').value=d.name||'';
    document.getElementById('agent-desc').value=d.description||'';
    document.getElementById('agent-prompt').value=d.system_prompt||'';
    let iconVal = d.avatar_icon || 'smart_toy';
    if (iconVal === 'SMART_TOY' || iconVal === 'smart_toy') iconVal = 'smart_toy';
    document.getElementById('agent-icon').value = iconVal;
    const p=d.persona||{};
    document.getElementById('agent-interests').value=(p.interests||[]).join(', ');
    document.getElementById('agent-behavior').value=JSON.stringify({dailyRoutine:(d.routine||{}).dailyRoutine||[],workHabits:(d.routine||{}).workHabits||{}},null,2);
    const pp=d.proxy_provider||{mode:'none'};
    document.getElementById('agent-proxy-mode').value=pp.mode||'none';
    document.getElementById('agent-proxy').value=d.proxy_config||'';
    onProxyModeChange();
    const sc=d.schedule||{};
    document.getElementById('agent-schedule-enable').checked=sc.enabled||false;
    document.getElementById('agent-timezone').value=d.timezone||'Asia/Ho_Chi_Minh';
    document.getElementById('agent-schedule-repeat').value=sc.repeat||'daily';
    document.getElementById('agent-schedule-interval').value=sc.interval||60;
    document.getElementById('agent-schedule-start').value=sc.start_time||'08:00';
    document.getElementById('agent-schedule-end').value=sc.end_time||'22:00';
    document.getElementById('agent-schedule-max-runs').value=sc.max_runs||10;
    document.querySelectorAll('.agent-day-cb').forEach(cb=>cb.checked=(sc.active_days||['mon','tue','wed','thu','fri']).includes(cb.value));
    onScheduleRepeatChange();
    document.getElementById('agent-scraping-enable').checked=d.enable_scraping||false;
    document.getElementById('agent-scraper-limit').value=d.scraper_text_limit||10000;
    document.getElementById('agent-scraper-format').value=d.script_output_format||'json';
    document.getElementById('agent-tg-token').value=d.telegram_token||'';
    document.getElementById('agent-tg-chat').value=d.telegram_chat_id||'';
    document.getElementById('agent-ms-token').value=d.messenger_token||'';
    document.getElementById('agent-ms-page').value=d.messenger_page_id||'';
    document.getElementById('agent-ms-php').value=d.messenger_php_url||'';
    document.getElementById('agent-ms-skill').value=d.direct_trigger_skill_id||'';
    await Promise.all([
        populateAgentProfiles(d.allowed_profiles||[]),
        populateAgentSkills(d.allowed_skills||[])
    ]);
    document.querySelector('.agent-tab-btn[data-atab="identity"]').click();
    document.getElementById('modal-agent').classList.remove('hidden');
    // Load model dropdowns async (non-blocking, lazy)
    populateAgentModelDropdown('chatbot', d.model || 'qwen:latest');
    populateAgentModelDropdown('browser', d.browser_ai_model || d.model || 'qwen:latest');
}

async function populateAgentProfiles(allowed) { const d=await apiGet('/api/v1/browser/profiles'); const c=document.getElementById('agent-profiles-list'); if(!d?.profiles?.length) { c.innerHTML='<p class="text-muted">No profiles.</p>'; return; } c.innerHTML=d.profiles.map(p=>`<label class="checkbox-item"><input type="checkbox" value="${esc(p.name)}" class="agent-profile-cb" ${allowed.includes(p.name)?'checked':''}>${esc(p.name)}</label>`).join(''); }
async function populateAgentSkills(allowed) {
    const d = await apiGet('/api/v1/skills');
    const c = document.getElementById('agent-skills-list');
    if (!d?.skills?.length) { c.innerHTML = '<p class="text-muted">No skills found.</p>'; return; }

    // Type → color map for badges
    const typeColor = {
        'Skill': '#6366f1', 'Tool': '#0ea5e9', 'Automation': '#10b981',
        'Browser': '#f59e0b', 'API': '#8b5cf6', 'AI': '#ec4899',
    };
    // Type → icon
    const typeIcon = {
        'Skill': '⚡', 'Tool': '🔧', 'Automation': '🤖',
        'Browser': '🌐', 'API': '🔌', 'AI': '🧠',
    };

    c.innerHTML = d.skills.map(s => {
        const isSelected = allowed.includes(s.id);
        const color = typeColor[s.type] || '#6366f1';
        const icon = typeIcon[s.type] || '⚡';
        return `
        <div class="skill-chip${isSelected ? ' selected' : ''}"
             data-skill-id="${esc(s.id)}"
             data-skill-name="${esc(s.name).toLowerCase()}"
             onclick="toggleSkillChip(this)"
             title="${esc(s.description || s.name)}"
             style="position:relative;display:inline-flex;align-items:center;gap:7px;padding:7px 13px;
                    border-radius:20px;cursor:pointer;font-size:.82rem;font-weight:500;
                    border:1.5px solid ${isSelected ? color : 'var(--border)'};
                    background:${isSelected ? color + '22' : 'var(--bg3)'};
                    color:${isSelected ? '#fff' : 'var(--text-muted)'};
                    transition:all .18s ease;user-select:none">
            <span style="font-size:.9rem">${icon}</span>
            <span>${esc(s.name)}</span>
            <span style="font-size:.7rem;padding:1px 6px;border-radius:10px;
                         background:${isSelected ? 'rgba(255,255,255,0.15)' : color+'33'};
                         color:${isSelected ? '#fff' : color}">${esc(s.type)}</span>
            <input type="checkbox" class="agent-skill-cb" value="${esc(s.id)}" ${isSelected ? 'checked' : ''}
                   style="position:absolute;opacity:0;pointer-events:none">
        </div>`;
    }).join('');
    updateSkillCount();
}

function toggleSkillChip(el) {
    const cb = el.querySelector('input.agent-skill-cb');
    const selected = !cb.checked;
    cb.checked = selected;
    el.classList.toggle('selected', selected);
    // Get color from badge
    const badge = el.querySelector('span:last-of-type');
    if (selected) {
        const colorMatch = el.style.border.match(/#[0-9a-f]{6}/i) || ['', '#6366f1'];
        el.style.borderColor = colorMatch[0] || '#6366f1';
        el.style.background = (colorMatch[0] || '#6366f1') + '22';
        el.style.color = '#fff';
        if (badge) badge.style.background = 'rgba(255,255,255,0.15)', badge.style.color = '#fff';
    } else {
        el.style.borderColor = 'var(--border)';
        el.style.background = 'var(--bg3)';
        el.style.color = 'var(--text-muted)';
        if (badge) { badge.style.background = ''; badge.style.color = ''; }
    }
    updateSkillCount();
}

function updateSkillCount() {
    const total = document.querySelectorAll('.agent-skill-cb').length;
    const selected = document.querySelectorAll('.agent-skill-cb:checked').length;
    const el = document.getElementById('agent-skills-count');
    if (el) el.textContent = selected === 0 ? `${total} skills available`
        : `${selected} / ${total} selected`;
}

function filterSkillChips(query) {
    const q = (query || '').toLowerCase().trim();
    document.querySelectorAll('.skill-chip').forEach(chip => {
        const name = chip.dataset.skillName || '';
        chip.style.display = (!q || name.includes(q)) ? '' : 'none';
    });
}

// ─── Agent Model Selector Helpers ───────────────────────────────────────────
// type: 'chatbot' | 'browser'
// selId map: chatbot → 'agent-model', browser → 'agent-browser-model'

function _agentSelId(type) { return type === 'chatbot' ? 'agent-model' : 'agent-browser-model'; }
function _agentWarnId(type) { return type === 'chatbot' ? 'agent-model-warning' : 'agent-browser-model-warning'; }
function _agentFilterId(type) { return type === 'chatbot' ? 'agent-model-provider-filter' : 'agent-browser-model-provider-filter'; }

// Cache: avoid re-fetching Ollama/9Router within same modal session
const _agentModelCache = { cloudProviders: null, ollamaLoaded: {}, nrLoaded: {} };

async function _agentLoadOllama(sel) {
    let og = sel.querySelector('optgroup[label*="Ollama"]');
    if (og && og.querySelector('option:not([disabled])')) return; // already loaded
    let html = '';
    let ok = false;
    try {
        const r = await apiGet('/api/v1/ollama/models');
        if (r?.models?.length) {
            ok = true;
            html = '<optgroup label="🖥️ Ollama (Local)">' +
                r.models.map(m => `<option value="${esc(m.name||m)}">${esc(m.name||m)}</option>`).join('') +
                '</optgroup>';
        }
    } catch(e) {}
    if (!ok) html = '<optgroup label="🖥️ Ollama (Local)"><option disabled style="color:#888">⚠️ Ollama not running</option></optgroup>';
    if (og) { const tmp = document.createElement('div'); tmp.innerHTML = `<select>${html}</select>`; og.replaceWith(tmp.querySelector('optgroup')); }
    else sel.insertAdjacentHTML('afterbegin', html);
}

async function _agentLoad9Router(sel) {
    let og = sel.querySelector('optgroup[label*="9Router"]');
    if (og && og.querySelector('option:not([disabled])')) return; // already loaded
    let html = '';
    try {
        const nr = await apiGet('/api/v1/cloud-api/9router/status');
        if (nr?.running && nr.models?.length) {
            html = '<optgroup label="🔀 9Router (Local Proxy)">' +
                nr.models.map(m => `<option value="${esc(m)}">${esc(m)}</option>`).join('') +
                '</optgroup>';
        }
    } catch(e) {}
    if (html) {
        if (og) { const tmp = document.createElement('div'); tmp.innerHTML = `<select>${html}</select>`; og.replaceWith(tmp.querySelector('optgroup')); }
        else { const ollamaOg = sel.querySelector('optgroup[label*="Ollama"]'); if(ollamaOg) ollamaOg.insertAdjacentHTML('afterend', html); else sel.insertAdjacentHTML('afterbegin', html); }
    }
}

function _agentRenderCloud(sel, cloudProviders) {
    if (!cloudProviders?.length) return;
    if (sel.querySelector('optgroup[label*="Gemini"], optgroup[label*="OpenAI"], optgroup[label*="Claude"]')) return;
    let html = '';
    cloudProviders.forEach(p => {
        if (!p.models?.length || p.id === '9router') return;
        const label = { gemini:'✨ Gemini', openai:'🤖 OpenAI', claude:'🧠 Claude', grok:'⚡ Grok', deepseek:'🔮 DeepSeek', openrouter:'🌐 OpenRouter' }[p.id] || p.id;
        html += `<optgroup label="☁️ ${esc(label)}">` + p.models.map(m => `<option value="${esc(m)}">${esc(m)}</option>`).join('') + '</optgroup>';
    });
    if (html) sel.insertAdjacentHTML('beforeend', html);
}

function _agentEnsureOption(sel, model) {
    if (!model) return;
    const exists = Array.from(sel.options).some(o => o.value === model);
    if (!exists) sel.insertAdjacentHTML('afterbegin', `<option value="${esc(model)}" selected>${esc(model)}</option>`);
    sel.value = model;
}

/**
 * Populate agent model dropdown (lazy — only active provider loaded first).
 * @param {string} type - 'chatbot' | 'browser'
 * @param {string} selectedModel - model to pre-select
 */
async function populateAgentModelDropdown(type, selectedModel) {
    const sel = document.getElementById(_agentSelId(type));
    if (!sel) return;
    sel.innerHTML = '<option value="" disabled selected>⏳ Loading...</option>';

    // 1. Cloud providers (instant local call)
    let cloudProviders = _agentModelCache.cloudProviders;
    if (!cloudProviders) {
        try {
            const r = await apiGet('/api/v1/cloud-api/providers');
            cloudProviders = r?.providers || [];
            _agentModelCache.cloudProviders = cloudProviders;
        } catch(e) { cloudProviders = []; }
    }

    // 2. Detect provider of selectedModel
    const lower = (selectedModel || '').toLowerCase();
    const isCloud = cloudProviders.some(p => p.models?.includes(selectedModel));
    const is9R = lower.startsWith('9router') || lower.includes('9router');

    sel.innerHTML = ''; // clear loading placeholder

    // 3. Lazy-load: only active provider first
    if (isCloud) {
        _agentRenderCloud(sel, cloudProviders);
    } else if (is9R) {
        await _agentLoad9Router(sel);
        _agentRenderCloud(sel, cloudProviders);
    } else {
        // Default: Ollama
        await _agentLoadOllama(sel);
        _agentRenderCloud(sel, cloudProviders);
    }

    // 4. Pre-select (insert if not found)
    _agentEnsureOption(sel, selectedModel);
}

/**
 * Filter agent model dropdown by provider chip.
 * @param {string} type - 'chatbot' | 'browser'
 * @param {string} provider - 'all' | 'ollama' | 'cloud' | '9router'
 * @param {HTMLElement} chipEl
 */
async function agentModelFilter(type, provider, chipEl) {
    const filterId = _agentFilterId(type);
    const sel = document.getElementById(_agentSelId(type));
    if (!sel) return;

    // Activate chip
    document.querySelectorAll(`#${filterId} .ext-chip`).forEach(c => c.classList.remove('active'));
    if (chipEl) chipEl.classList.add('active');

    // Lazy-load on demand
    if (provider === 'ollama' || provider === 'all') await _agentLoadOllama(sel);
    if (provider === '9router' || provider === 'all') await _agentLoad9Router(sel);
    if ((provider === 'cloud' || provider === 'all') && _agentModelCache.cloudProviders) {
        _agentRenderCloud(sel, _agentModelCache.cloudProviders);
    }

    // Filter visibility
    const providerKeywords = { ollama:'Ollama', cloud:'☁️', '9router':'9Router' };
    sel.querySelectorAll('optgroup').forEach(og => {
        if (provider === 'all') {
            og.style.display = '';
            og.querySelectorAll('option').forEach(o => o.style.display = '');
        } else {
            const kw = providerKeywords[provider] || provider;
            const match = og.label && og.label.includes(kw);
            og.style.display = match ? '' : 'none';
            og.querySelectorAll('option').forEach(o => o.style.display = match ? '' : 'none');
        }
    });
    sel.querySelectorAll(':scope > option').forEach(o => {
        o.style.display = (provider === 'all') ? '' : 'none';
    });

    // If current selection hidden, move to first visible
    const cur = sel.options[sel.selectedIndex];
    if (cur && cur.style.display === 'none') {
        for (let i = 0; i < sel.options.length; i++) {
            if (sel.options[i].style.display !== 'none' && !sel.options[i].disabled) { sel.selectedIndex = i; break; }
        }
    }
}

/**
 * Check API key availability when a cloud model is selected (lazy, only on selection).
 * @param {string} type - 'chatbot' | 'browser'
 */
async function onAgentModelChange(type) {
    const sel = document.getElementById(_agentSelId(type));
    const warn = document.getElementById(_agentWarnId(type));
    if (!sel || !warn) return;
    const opt = sel.options[sel.selectedIndex];
    if (!opt) { warn.style.display = 'none'; return; }
    const og = opt.closest('optgroup');
    if (!og || !og.label.includes('☁️')) { warn.style.display = 'none'; return; }
    // Detect provider from optgroup label
    const providerMap = { Gemini:'gemini', OpenAI:'openai', Claude:'claude', Grok:'grok', DeepSeek:'deepseek', OpenRouter:'openrouter' };
    let provider = '';
    for (const [name, id] of Object.entries(providerMap)) { if (og.label.includes(name)) { provider = id; break; } }
    if (!provider) { warn.style.display = 'none'; return; }
    try {
        const data = await apiGet('/api/v1/cloud-api/keys');
        const pKeys = data?.keys?.[provider];
        if (pKeys && Object.keys(pKeys).length > 0) {
            const hasActive = Object.values(pKeys).some(k => k.active);
            if (hasActive) { warn.style.display = 'none'; }
            else {
                warn.style.display = 'block';
                const msg = T('agent_modal.model_key_expired') || '⚠️ All keys for {provider} expired.';
                warn.innerHTML = msg.replace('{provider}', `<b>${provider}</b>`);
            }
        } else {
            warn.style.display = 'block';
            const msg = T('agent_modal.model_no_key') || '⚠️ No API key for {provider}.';
            warn.innerHTML = msg.replace('{provider}', `<b>${provider}</b>`);
        }
    } catch(e) { warn.style.display = 'none'; }
}
// Reset cloud provider cache when modal closes (so fresh data next open)
document.getElementById('modal-agent')?.addEventListener('click', e => {
    if (e.target.classList.contains('modal') || e.target.classList.contains('btn-close')) {
        _agentModelCache.cloudProviders = null;
    }
});


function openModal(id) { document.getElementById(id).classList.remove('hidden'); }
function closeModal(id) { document.getElementById(id).classList.add('hidden'); }
function onProxyModeChange() { const m=document.getElementById('agent-proxy-mode').value; document.getElementById('proxy-static-group').style.display=m==='static'?'block':'none'; document.getElementById('proxy-dynamic-group').style.display=m==='dynamic'?'block':'none'; }
function onScheduleRepeatChange() { document.getElementById('schedule-interval-group').style.display=document.getElementById('agent-schedule-repeat').value==='interval'?'block':'none'; }
document.getElementById('agent-schedule-repeat')?.addEventListener('change', onScheduleRepeatChange);

async function saveAgent() { const name=document.getElementById('agent-name').value.trim(); if(!name) return alert('Name required'); const id=document.getElementById('agent-id').value; const interests=document.getElementById('agent-interests').value.split(',').map(s=>s.trim()).filter(s=>s); let routine={}; try { const v=document.getElementById('agent-behavior').value; if(v) routine=JSON.parse(v); } catch(e) { return alert('Invalid JSON: '+e.message); } const pm=document.getElementById('agent-proxy-mode').value; const pp={mode:pm}; if(pm==='dynamic') { pp.api_url=document.getElementById('agent-proxy-api')?.value||''; pp.api_key=document.getElementById('agent-proxy-api-key')?.value||''; pp.location=document.getElementById('agent-proxy-location')?.value||''; } const payload = { name, description:document.getElementById('agent-desc').value, system_prompt:document.getElementById('agent-prompt').value, model:document.getElementById('agent-model').value, browser_ai_model:document.getElementById('agent-browser-model').value, avatar_icon:document.getElementById('agent-icon').value, persona:{interests}, routine, proxy_config:pm==='static'?document.getElementById('agent-proxy').value:'', proxy_provider:pp, timezone:document.getElementById('agent-timezone').value, schedule:{ enabled:document.getElementById('agent-schedule-enable').checked, repeat:document.getElementById('agent-schedule-repeat').value, interval:parseInt(document.getElementById('agent-schedule-interval').value)||60, active_days:Array.from(document.querySelectorAll('.agent-day-cb:checked')).map(cb=>cb.value), start_time:document.getElementById('agent-schedule-start').value, end_time:document.getElementById('agent-schedule-end').value, max_runs:parseInt(document.getElementById('agent-schedule-max-runs').value)||10 }, enable_scraping:document.getElementById('agent-scraping-enable').checked, scraper_text_limit:parseInt(document.getElementById('agent-scraper-limit').value)||10000, script_output_format:document.getElementById('agent-scraper-format').value, telegram_token:document.getElementById('agent-tg-token').value, telegram_chat_id:document.getElementById('agent-tg-chat').value, messenger_token:document.getElementById('agent-ms-token').value, messenger_page_id:document.getElementById('agent-ms-page').value, messenger_php_url:document.getElementById('agent-ms-php').value, direct_trigger_skill_id:document.getElementById('agent-ms-skill').value, allowed_profiles:Array.from(document.querySelectorAll('.agent-profile-cb:checked')).map(cb=>cb.value), allowed_skills:Array.from(document.querySelectorAll('.agent-skill-cb:checked')).map(cb=>cb.value) }; if(id) await apiPut('/api/v1/agents/'+id,payload); else await apiPost('/api/v1/agents',payload); closeModal('modal-agent'); renderAgentsExt(getAgentsBody()); }
async function deleteAgent(id) { if(!confirm('Delete agent?')) return; await apiDelete('/api/v1/agents/'+id); }

// ═══ Generate Agent ═══
let AI_PROVIDERS = {
    "ollama": { models: ["deepseek-r1:latest", "llama3.2", "mistral-nemo"], needs_api: false },
    "gemini": { models: ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-2.5-pro"], needs_api: true },
    "chatgpt": { models: ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"], needs_api: true },
    "claude": { models: ["claude-sonnet-4-20250514", "claude-3-5-haiku-20241022"], needs_api: true },
    "grok": { models: ["grok-3", "grok-3-mini", "grok-2"], needs_api: true },
    "deepseek": { models: ["deepseek-chat", "deepseek-reasoner"], needs_api: true },
    "openrouter": { models: ["google/gemini-2.5-flash-lite", "openai/gpt-4o-mini", "deepseek/deepseek-r1"], needs_api: true },
    "9router": { models: ["deepseek-chat", "deepseek-reasoner"], needs_api: true }
};
window.provHasKey = {};

function showGenerateAgent() {
    document.getElementById('agent-gen-name').value = '';
    document.getElementById('agent-gen-prefix').value = '';
    document.getElementById('agent-gen-desc').value = '';
    document.getElementById('agent-gen-provider').value = 'ollama';
    document.getElementById('agent-gen-accounts').value = '';
    document.getElementById('agent-gen-preview').value = '';
    document.getElementById('agent-gen-status').textContent = '';
    document.getElementById('btn-apply-ai').style.display = 'none';
    document.getElementById('agent-gen-apikey').value = '';
    onGenProviderChange();
    const ni = document.getElementById('agent-gen-name');
    const nn = ni.cloneNode(true);
    ni.parentNode.replaceChild(nn, ni);
    nn.addEventListener('input', e => {
        document.getElementById('agent-gen-prefix').value = e.target.value.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/(^_|_$)/g, '');
    });
    document.getElementById('modal-generate-agent').classList.remove('hidden');
    apiGet('/api/v1/cloud-api/providers').then(res => {
        if (res && res.providers) {
            res.providers.forEach(p => {
                let id = p.id;
                if (id === 'openai') id = 'chatgpt';
                if (AI_PROVIDERS[id]) {
                    AI_PROVIDERS[id].models = p.models;
                }
                // Store has_key mapping
                window.provHasKey[id] = p.has_key;
            });
            onGenProviderChange();
        }
    });
}

async function onGenProviderChange() {
    const p = document.getElementById('agent-gen-provider').value;
    const i = AI_PROVIDERS[p] || AI_PROVIDERS.ollama;
    const modelSel = document.getElementById('agent-gen-model');
    const apiGroup = document.getElementById('agent-gen-apikey-group');
    const input = document.getElementById('agent-gen-apikey');
    
    apiGroup.style.display = i.needs_api ? 'block' : 'none';
    
    let backendProvId = p;
    if (backendProvId === 'chatgpt') backendProvId = 'openai';
    
    const hasSavedKey = window.provHasKey && window.provHasKey[backendProvId];
    if (hasSavedKey) {
        input.placeholder = T('gen.apikey_placeholder_saved') || 'Bỏ trống để dùng key đã lưu';
    } else {
        input.placeholder = T('gen.apikey_placeholder_new') || 'Nhập API Key mới để lưu và sử dụng';
    }
    
    if (p === '9router') {
        modelSel.innerHTML = '<option value="" disabled selected>⏳ Loading 9Router models...</option>';
        try {
            const nr = await apiGet('/api/v1/cloud-api/9router/status');
            if (nr && nr.running && nr.models && nr.models.length > 0) {
                AI_PROVIDERS['9router'].models = nr.models;
            }
        } catch(e) {
            console.warn('[Generate Agent] Failed to fetch 9Router models', e);
        }
    } else if (p === 'ollama') {
        modelSel.innerHTML = '<option value="" disabled selected>⏳ Loading Ollama models...</option>';
        try {
            const r = await apiGet('/api/v1/ollama/models');
            if (r && r.models && r.models.length > 0) {
                AI_PROVIDERS['ollama'].models = r.models.map(m => m.name || m);
            }
        } catch(e) {
            console.warn('[Generate Agent] Failed to fetch Ollama models', e);
        }
    }
    
    const activeInfo = AI_PROVIDERS[p] || AI_PROVIDERS.ollama;
    modelSel.innerHTML = activeInfo.models.map(m => `<option value="${esc(m)}">${esc(m)}</option>`).join('');
}

async function generateAgentJSON() {
    const name = document.getElementById('agent-gen-name').value.trim();
    const desc = document.getElementById('agent-gen-desc').value.trim();
    if (!name || !desc) return alert('Name & Description required!');
    const btn = document.getElementById('btn-generate-ai');
    btn.disabled = true;
    document.getElementById('btn-apply-ai').style.display = 'none';
    const prov = document.getElementById('agent-gen-provider').value;
    const model = document.getElementById('agent-gen-model').value;
    const api_key = document.getElementById('agent-gen-apikey')?.value?.trim() || '';
    const st = document.getElementById('agent-gen-status');
    st.style.color = 'var(--text)';
    st.textContent = `🤖 Calling ${prov}/${model}...`;
    document.getElementById('agent-gen-preview').value = 'Generating...';
    
    if (api_key) {
        st.textContent = `🔑 Saving API Key for ${prov}...`;
        try {
            let backendProvId = prov;
            if (backendProvId === 'chatgpt') backendProvId = 'openai';
            await apiPost('/api/v1/cloud-api/keys', { provider: backendProvId, api_key: api_key, label: 'default' });
            if (window.provHasKey) window.provHasKey[backendProvId] = true;
        } catch(e) {
            console.warn('Failed to update cloud API key:', e);
        }
    }
    
    st.textContent = `🤖 Calling ${prov}/${model}...`;
    try {
        const r = await apiPost('/api/v1/agents/generate', { name, description: desc, provider: prov, model, api_key });
        if (r?.status === 'success' && r.data) {
            document.getElementById('agent-gen-preview').value = JSON.stringify(r.data, null, 2);
            st.textContent = '✅ Done!';
            st.style.color = 'var(--green)';
            document.getElementById('btn-apply-ai').style.display = 'inline-block';
            window._lastGen = r.data;
        } else {
            st.textContent = '❌ Failed';
            st.style.color = 'var(--red)';
            document.getElementById('agent-gen-preview').value = JSON.stringify(r, null, 2);
        }
    } catch (e) {
        st.textContent = '❌ Error';
        st.style.color = 'var(--red)';
    }
    btn.disabled = false;
}
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
    const prev = currentVersion || sel.value || 'default';
    sel.innerHTML = '<option value="default">⏳ ' + T('browser.loading', 'Loading...') + '</option>';
    try {
        const r = await apiGet('/api/v1/browser/engine/versions');
        if (r && r.success && r.versions) {
            const installed = r.versions.filter(v => v.downloaded);
            if (installed.length === 0) {
                sel.innerHTML = `<option value="default">${T('browser.default_latest_no_engine', 'Default Latest (no engine installed)')}</option>`;
                return;
            }
            sel.innerHTML = `<option value="default">${T('browser.default_latest', 'Default Latest')}</option>` +
                installed.map(v => {
                    const nm  = typeof v === 'object' ? (v.browser_version || v.name) : v;
                    const bas = typeof v === 'object' ? v.bas_version : '';
                    const isShardX = typeof v === 'object' ? v.is_shardx : false;
                    
                    let label = nm;
                    if (isShardX) {
                        const verNum = nm.replace('ShardX', '').trim();
                        label = `${verNum} (ShardX)`;
                    } else if (bas) {
                        label = `${nm} (BAS)`;
                    }
                    return `<option value="${esc(nm)}">${esc(label)}</option>`;
                }).join('');
            // Restore previously selected version
            if (prev) {
                sel.value = prev;
                if (prev !== 'default' && (!sel.value || sel.value === 'default')) {
                    // Version not in list — add it
                    const opt = document.createElement('option');
                    opt.value = prev; opt.textContent = prev;
                    sel.insertBefore(opt, sel.options[1] || null);
                    sel.value = prev;
                }
            }
        } else {
            sel.innerHTML = `<option value="default">${T('browser.default_latest', 'Default Latest')}</option>`;
            if (prev) sel.value = prev;
        }
    } catch (e) {
        sel.innerHTML = `<option value="default">${T('browser.default_latest', 'Default Latest')}</option>`;
        if (prev) sel.value = prev;
        console.warn('[Engine dropdown] fetch failed:', e);
    }
}
async function showBrowserEnginesModal() {
    document.getElementById('modal-engines').classList.remove('hidden');
    const container = document.getElementById('engines-list-container');
    container.innerHTML = `<p class="text-muted">${T('browser.fetching_engines', 'Fetching available engines...')}</p>`;
    
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
                    <td style="color:${installed ? 'var(--green)' : 'var(--red)'}">${installed ? T('browser.installed', '✅ Installed') : T('browser.missing', '❌ Missing')}</td>
                    <td style="font-size:0.75rem;color:var(--text-muted);word-break:break-all">${esc(path)}</td>
                    <td style="text-align:right">
                        ${installed ? '' : `<button class="btn-install" style="padding:2px 10px;font-size:0.8rem" onclick="installEngineVersionProgress('${esc(v.bas_version || name)}', '${esc(downloadUrl)}')">${T('browser.btn_install', 'Install')}</button>`}
                    </td>
                </tr>`;
            }).join('');
            
            container.innerHTML = `<table class="data-table">
                <thead><tr><th>${T('browser.hdr_version', 'Version')}</th><th>${T('browser.hdr_status', 'Status')}</th><th>${T('browser.hdr_path', 'Path')}</th><th style="text-align:right">${T('browser.hdr_action', 'Action')}</th></tr></thead>
                <tbody>${rows}</tbody>
            </table>`;
            // Show warning if using fallback
            if (r.warning) {
                container.innerHTML = `<div style="background:rgba(255,165,0,0.1);border:1px solid var(--orange);border-radius:8px;padding:10px;margin-bottom:12px;font-size:0.85rem">⚠️ ${esc(r.warning)}</div>` + container.innerHTML;
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
    
    titleText.textContent = T('browser.installing_version', {version: version});
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
            titleText.textContent = T('browser.downloading_version_resume', {version: version});
        } else if (!start || start.error) {
            alert(T('browser.download_start_failed', 'Failed to start download: ') + (start?.error || 'Unknown error'));
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
                titleText.textContent = T('browser.install_complete', 'Installation Complete!');
                setTimeout(() => {
                    overlay.classList.add('hidden');
                    showBrowserEnginesModal(); // refresh list
                }, 1000);
            } else if (status.status === 'error') {
                done = true;
                alert(T('browser.install_failed', 'Installation failed: ') + (status.error || 'Unknown error'));
                overlay.classList.add('hidden');
            }
        }
    } catch (e) {
        alert(T('browser.request_failed', 'Request failed: ') + e.message);
        overlay.classList.add('hidden');
    }
}
async function createProfile() {
    const btn = document.getElementById('btn-create-profile-submit');
    const name = document.getElementById('profile-name').value.trim();
    if (!name) return;
    btn.disabled = true;
    btn.textContent = T('browser.creating', 'Creating...');
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
    btn.textContent = T('browser.create_fetch', 'Create & Fetch Fingerprint');
    closeModal('modal-profile');
    document.getElementById('profile-name').value = '';
    document.getElementById('profile-proxy').value = '';
    if (document.getElementById('profile-win-width'))  document.getElementById('profile-win-width').value  = '1920';
    if (document.getElementById('profile-win-height')) document.getElementById('profile-win-height').value = '1080';
    renderBrowserExt(getBrowserBody());
}
async function launchProfile(name,btn) { if(btn){btn.disabled=true;btn.textContent='🚀...'} const r=await apiPost('/api/v1/browser/launch',{profile:name,manual:true}); if(r && !r.error && r.status !== 'error') { let n=0; const iv=setInterval(async()=>{await renderBrowserExt(getBrowserBody());if(++n>=3)clearInterval(iv)},2000); } else { if(btn){btn.disabled=false;btn.textContent='▶'} let msg = T('browser.launch_failed', 'Failed to launch: ') + (r?.error || r?.detail || T('browser.err_unknown', 'Unknown error')); if(r?.log_output) msg += '\n\n📋 Log output:\n' + r.log_output; if(r?.debug) { const d = r.debug; msg += '\n\n🔍 Debug info:'; msg += '\n• Node: ' + (d.node_available ? d.node_version : '❌ NOT FOUND'); msg += '\n• open.js: ' + (d.open_js_exists ? '✅' : '❌ NOT FOUND'); msg += '\n• node_modules: ' + (d.node_modules_exists ? '✅' : '❌ MISSING'); msg += '\n• Launcher dir: ' + (d.launcher_dir || '-'); if(d.launcher_dir_contents) msg += '\n• Dir contents: ' + d.launcher_dir_contents.join(', '); if(d.exit_code !== undefined) msg += '\n• Exit code: ' + d.exit_code; } alert(msg); } }
async function stopProfile(name,btn) { if(btn){btn.disabled=true;btn.textContent='...'} await apiPost('/api/v1/browser/stop',{profile:name}); setTimeout(()=>renderBrowserExt(getBrowserBody()),1000); }
function openWSProfile(name) { window.open('/browser/view?profile=' + encodeURIComponent(name), '_blank'); }
async function deleteProfile(name) { if(!confirm(T('browser.delete_confirm_prompt', {name: name}))) return; await apiDelete('/api/v1/browser/profiles/'+name); }
async function viewProfileLog(name) { const r = await apiGet('/api/v1/browser/log/' + encodeURIComponent(name)); if (!r || r.error) { alert('No log available: ' + (r?.error || 'Unknown')); return; } let msg = '📋 Browser Log for: ' + name; msg += '\n\nStatus: ' + (r.status || '-'); msg += '\nCommand: ' + (r.command || '-'); msg += '\nLog file: ' + (r.log_file || '-'); if (r.debug) { const d = r.debug; if (d.node_version) msg += '\nNode: ' + d.node_version; if (d.open_js_exists !== undefined) msg += '\nopen.js: ' + (d.open_js_exists ? '✅' : '❌'); if (d.node_modules_exists !== undefined) msg += '\nnode_modules: ' + (d.node_modules_exists ? '✅' : '❌'); if (d.launcher_dir) msg += '\nLauncher: ' + d.launcher_dir; } msg += '\n\n─── LOG OUTPUT ───\n' + (r.log || '(empty)'); alert(msg); }

// ═══ Browser Command ═══
let _cmdProfile = '';
function showProfileCommand(name) { _cmdProfile = name; document.getElementById('cmd-profile-name').textContent = name; document.getElementById('cmd-input').value = ''; document.getElementById('modal-command').classList.remove('hidden'); setTimeout(() => document.getElementById('cmd-input').focus(), 100); }
function setCommand(cmd) { document.getElementById('cmd-input').value = cmd; document.getElementById('cmd-input').focus(); }
async function executeProfileCommand() { const cmd = document.getElementById('cmd-input').value.trim(); if (!cmd) return alert(T('browser.alert_enter_command', 'Please enter a command!')); const aiModel = document.getElementById('cmd-ai-model').value; const btn = document.getElementById('btn-run-command'); btn.disabled = true; btn.textContent = '⏳ ' + T('browser.running', 'Running...'); const r = await apiPost('/api/v1/browser/launch', { profile: _cmdProfile, prompt: cmd, manual: false, ai_model: aiModel }); btn.disabled = false; btn.textContent = '🚀 ' + T('browser.run_command', 'Run Command'); if (r && !r.error && r.status !== 'error') { closeModal('modal-command'); let n = 0; const iv = setInterval(async () => { await renderBrowserExt(getBrowserBody()); if (++n >= 3) clearInterval(iv); }, 2000); } else { let msg = T('browser.alert_error', 'Error: ') + (r?.error || r?.detail || T('browser.err_unknown', 'Unknown error')); if (r?.log_output) msg += '\n\n' + r.log_output; alert(msg); } }
function searchMarket() { const q=(document.getElementById('market-search')?.value||'').toLowerCase(); document.querySelectorAll('#market-list .card').forEach(c=>{ c.style.display=c.textContent.toLowerCase().includes(q)?'':'none'; }); }

// ═══ Global Settings ═══
// Apply settings data to UI (called by init with pre-fetched data)
async function applyGlobalSettings(s) {
    if (!s) return;
    if (s.api_port && document.getElementById('set-port')) document.getElementById('set-port').value = s.api_port;
    if (s.api_base_url && document.getElementById('set-api')) document.getElementById('set-api').value = s.api_base_url;
    if (s.telegram_bot_token && document.getElementById('set-tg-token')) document.getElementById('set-tg-token').value = s.telegram_bot_token;
    if (s.telegram_chat_id && document.getElementById('set-tg-chat')) document.getElementById('set-tg-chat').value = s.telegram_chat_id;
    
    const notifyEnabled = s.ext_update_notifications !== undefined ? s.ext_update_notifications : false;
    if (document.getElementById('set-ext-update-notify')) {
        document.getElementById('set-ext-update-notify').checked = notifyEnabled;
    }
    localStorage.setItem('ext_update_notifications', notifyEnabled ? 'true' : 'false');

    const openMode = s.ext_open_mode || 'full_page';
    if (document.getElementById('set-ext-open-mode')) {
        document.getElementById('set-ext-open-mode').value = openMode;
    }
    localStorage.setItem('ext_open_mode', openMode);

    globalExtensionGroups = s.extension_groups || [];
    renderExtensionGroupsSettings();
    
    // Show immediate loading state with the saved model to prevent user confusion
    const modelSel = document.getElementById('set-model');
    if (modelSel) {
        const savedModel = s.default_model || 'qwen:latest';
        modelSel.innerHTML = `<option value="${esc(savedModel)}" selected>⏳ ${esc(savedModel)} (Đang tải...)</option>`;
    }

    // These are async but non-critical, run in background
    populateModelDropdown(s.default_model || 'qwen:latest');
    loadCloudKeysInSettings();
    apiGet('/api/v1/settings/default-profile').then(bp => populateDefaultProfileDropdown(bp?.profile || 'default')).catch(() => {});
    populateDefaultCalendarDropdown(s.default_calendar_email || '').catch(() => {});
    populateDefaultStorageDropdown(s.default_storage_email || '').catch(() => {});
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
        let html = `<option value="default">${T('settings.default_profile_ai', 'default (AI Default)')}</option>`;
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
        let html = `<option value="">${T('settings.google_not_configured', 'Not configured / Leave empty')}</option>`;
        if (d && d.credentials && d.credentials.length > 0) {
            d.credentials.forEach(c => {
                if (c.email) {
                    html += `<option value="${esc(c.email)}">${esc(c.email)} (${esc(c.name)})</option>`;
                }
            });
        } else {
            html = `<option value="">${T('settings.google_no_calendar', '⚠️ No Calendar account in Auth Manager')}</option>`;
        }
        sel.innerHTML = html;
        if (selectedEmail) {
            const hasOption = Array.from(sel.options).some(opt => opt.value === selectedEmail);
            if (!hasOption && selectedEmail !== '') {
                sel.innerHTML += `<option value="${esc(selectedEmail)}">${esc(selectedEmail)} (${T('settings.google_lost_access', '⚠️ Saved but access lost')})</option>`;
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

async function populateDefaultStorageDropdown(selectedEmail) {
    const sel = document.getElementById('set-default-storage');
    if (!sel) return;
    try {
        const d = await apiGet('/api/v1/auth-manager/tokens?provider=google');
        let html = `<option value="">${T('settings.google_not_configured', 'Not configured / Leave empty')}</option>`;
        if (d && d.tokens && d.tokens.length > 0) {
            d.tokens.forEach(t => {
                if (t.authorized_email) {
                    html += `<option value="${esc(t.authorized_email)}">${esc(t.authorized_email)} (${esc(t.credential_name || t.token_id)})</option>`;
                }
            });
        } else {
            html = `<option value="">${T('settings.google_no_storage', '⚠️ No Google account in Auth Manager')}</option>`;
        }
        sel.innerHTML = html;
        if (selectedEmail) {
            const hasOption = Array.from(sel.options).some(opt => opt.value === selectedEmail);
            if (!hasOption && selectedEmail !== '') {
                sel.innerHTML += `<option value="${esc(selectedEmail)}">${esc(selectedEmail)} (${T('settings.google_lost_access', '⚠️ Saved but access lost')})</option>`;
            }
            sel.value = selectedEmail;
        }
    } catch (e) {
        console.warn('Storage credentials fetch failed:', e);
    }
}

async function loadOllamaModels() {
    const sel = document.getElementById('set-model');
    if (!sel) return;
    
    // Check if already loaded
    let optgroup = sel.querySelector('optgroup[label*="Ollama"]');
    if (optgroup && optgroup.querySelector('option:not([disabled])')) {
        return; // Already loaded successfully
    }
    
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
    
    if (optgroup) {
        const tempDiv = document.createElement('div');
        tempDiv.innerHTML = `<select>${html}</select>`;
        const newOptgroup = tempDiv.querySelector('optgroup');
        optgroup.replaceWith(newOptgroup);
    } else {
        sel.insertAdjacentHTML('afterbegin', html);
    }
}

async function load9RouterModels() {
    const sel = document.getElementById('set-model');
    if (!sel) return;
    
    let optgroup = sel.querySelector('optgroup[label*="9Router"]');
    if (optgroup && optgroup.querySelector('option:not([disabled])')) {
        return; // Already loaded successfully
    }
    
    let html = '';
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
    
    if (html) {
        if (optgroup) {
            const tempDiv = document.createElement('div');
            tempDiv.innerHTML = `<select>${html}</select>`;
            const newOptgroup = tempDiv.querySelector('optgroup');
            optgroup.replaceWith(newOptgroup);
        } else {
            const ollamaGroup = sel.querySelector('optgroup[label*="Ollama"]');
            if (ollamaGroup) {
                ollamaGroup.insertAdjacentHTML('afterend', html);
            } else {
                sel.insertAdjacentHTML('afterbegin', html);
            }
        }
    }
}

function renderCloudModelsHTML(cloudProviders) {
    const sel = document.getElementById('set-model');
    if (!sel || !cloudProviders) return;
    
    // Avoid double rendering
    if (sel.querySelector('optgroup[label*="Gemini"], optgroup[label*="OpenAI"], optgroup[label*="Claude"]')) {
        return;
    }
    
    let html = '';
    cloudProviders.forEach(p => {
        if (!p.models || p.models.length === 0) return;
        if (p.id === '9router') return;
        const label = { gemini: '✨ Gemini', openai: '🤖 OpenAI', claude: '🧠 Claude', grok: '⚡ Grok', deepseek: '🔮 DeepSeek', openrouter: '🌐 OpenRouter' }[p.id] || p.id;
        html += `<optgroup label="☁️ ${esc(label)}">`;
        p.models.forEach(m => {
            html += `<option value="${esc(m)}">${esc(m)}</option>`;
        });
        html += '</optgroup>';
    });
    sel.insertAdjacentHTML('beforeend', html);
}

async function populateModelDropdown(selectedModel) {
    const sel = document.getElementById('set-model');
    if (!sel) return;
    
    // Clear dropdown and start loading
    sel.innerHTML = '';
    
    // 1. Fetch Cloud providers immediately (local API call, instant < 5ms)
    let cloudProviders = [];
    try {
        const cloud = await apiGet('/api/v1/cloud-api/providers');
        if (cloud && cloud.providers) {
            cloudProviders = cloud.providers;
        }
    } catch(e) { console.warn('[Settings] Cloud API models fetch failed'); }
    
    // 2. Identify the active provider of the selectedModel
    let isCloudModel = false;
    let is9RouterModel = false;
    
    if (selectedModel) {
        cloudProviders.forEach(p => {
            if (p.models && p.models.includes(selectedModel)) {
                isCloudModel = true;
            }
        });
        
        const lower = selectedModel.toLowerCase();
        if (lower.startsWith('9router') || lower.includes('9router')) {
            is9RouterModel = true;
        }
    }
    
    // 3. Populate only the active/selected provider first to ensure instant rendering (no delays!)
    if (isCloudModel) {
        // Cloud model: Only render cloud models, skip Ollama & 9Router entirely on startup
        renderCloudModelsHTML(cloudProviders);
    } else if (is9RouterModel) {
        // 9Router model: Load 9Router only
        await load9RouterModels();
        renderCloudModelsHTML(cloudProviders);
    } else {
        // Ollama model (or others): Load Ollama only
        await loadOllamaModels();
        renderCloudModelsHTML(cloudProviders);
    }
    
    // 4. Ensure the selectedModel is selected (and insert it if not present)
    if (selectedModel) {
        const exists = Array.from(sel.options).some(o => o.value === selectedModel);
        if (exists) {
            sel.value = selectedModel;
        } else {
            sel.insertAdjacentHTML('afterbegin', `<option value="${esc(selectedModel)}" selected>${esc(selectedModel)}</option>`);
            sel.value = selectedModel;
        }
    }
}

// Filter model dropdown by provider chip
async function filterModelsByProvider(provider, chipEl) {
    // Load on demand based on what provider chip is clicked
    if (provider === 'ollama' || provider === 'all') {
        await loadOllamaModels();
    }
    if (provider === '9router' || provider === 'all') {
        await load9RouterModels();
    }
    
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
                    max_tokens: 30,
                    stream: false
                })
            });
            if (resp.ok) {
                const text = await resp.text();
                let reply = 'OK';
                try {
                    const data = JSON.parse(text);
                    reply = data?.choices?.[0]?.message?.content || 'OK';
                } catch(parseErr) {
                    console.log('[Settings] Failed to parse 9Router response as JSON, trying SSE stream format...', parseErr);
                    let content = '';
                    const lines = text.split('\n');
                    for (const line of lines) {
                        const trimmed = line.trim();
                        if (trimmed.startsWith('data:')) {
                            const rawJson = trimmed.substring(5).trim();
                            if (rawJson === '[DONE]') continue;
                            try {
                                const parsedChunk = JSON.parse(rawJson);
                                const delta = parsedChunk?.choices?.[0]?.delta?.content || parsedChunk?.choices?.[0]?.text || '';
                                content += delta;
                            } catch(e) {}
                        }
                    }
                    if (content) {
                        reply = content;
                    } else {
                        throw parseErr;
                    }
                }
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
    
    // Only send the key that changed to avoid overwriting other values with loading/temporary states
    const payload = {};
    payload[key] = value;
    
    try {
        const r = await apiPut('/api/v1/settings', payload);
        if (r && r.status === 'success') {
            if (key === 'api_base_url' && value) localStorage.setItem('tubecli_api', value);
            if (key === 'ext_update_notifications') {
                localStorage.setItem('ext_update_notifications', value ? 'true' : 'false');
                updateSidebarBadgeVisibility();
            }
            if (key === 'ext_open_mode') {
                localStorage.setItem('ext_open_mode', value);
            }
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
        default_storage_email: document.getElementById('set-default-storage')?.value || '',
        ext_update_notifications: document.getElementById('set-ext-update-notify')?.checked || false,
    };
    try {
        const r = await apiPut('/api/v1/settings', payload);
        if (r && r.status === 'success') {
            localStorage.setItem('ext_update_notifications', payload.ext_update_notifications ? 'true' : 'false');
            updateSidebarBadgeVisibility();
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

// ═══ Profile Settings & Cookies ═══
let _settingsProfileName = '';
let _settingsAccounts = { google: '', facebook: '', tiktok: '', x: '', discord: '', telegram: '' };
let _settingsActiveService = 'google';
let _loadedCookies = [];

function switchSettingsTab(tabId, btn) {
    // remove active class from all settings-tab-btn
    document.querySelectorAll('.settings-tab-btn').forEach(b => b.classList.remove('active'));
    // hide all settings-tab-pane
    document.querySelectorAll('.settings-tab-pane').forEach(p => p.classList.remove('active'));
    
    // add active class to clicked button
    if (btn) btn.classList.add('active');
    else {
        // Fallback: search for button by click text or target
        const buttons = document.querySelectorAll('.settings-tab-btn');
        for (const b of buttons) {
            if (b.getAttribute('onclick') && b.getAttribute('onclick').includes(`'${tabId}'`)) {
                b.classList.add('active');
                break;
            }
        }
    }
    
    // show target pane
    const targetPane = document.getElementById('settings-tab-' + tabId);
    if (targetPane) {
        targetPane.classList.add('active');
    }
}

async function loadProfileCookies(name) {
    const countEl = document.getElementById('settings-cookies-count');
    const dataEl = document.getElementById('settings-cookies-data');
    if (countEl) countEl.textContent = '⏳';
    if (dataEl) dataEl.value = T('browser.loading_cookies', 'Loading cookies...');
    
    _loadedCookies = [];
    try {
        const res = await apiGet(`/api/v1/browser/profiles/${name}/cookies`);
        if (res && Array.isArray(res.cookies)) {
            _loadedCookies = res.cookies;
        } else if (res && res.cookies && Array.isArray(res.cookies.cookies)) {
            _loadedCookies = res.cookies.cookies;
        }
    } catch (e) {
        console.error('Lỗi tải cookies:', e);
    }
    
    updateCookieCountDisplay();
    const formatSelect = document.getElementById('settings-cookies-format');
    const format = formatSelect ? formatSelect.value : 'json';
    displayCookies(format);
}

function updateCookieCountDisplay() {
    const countEl = document.getElementById('settings-cookies-count');
    if (countEl) {
        countEl.textContent = _loadedCookies ? _loadedCookies.length : 0;
    }
}

function displayCookies(format) {
    const textarea = document.getElementById('settings-cookies-data');
    if (!textarea) return;
    
    if (!_loadedCookies || _loadedCookies.length === 0) {
        textarea.value = '';
        return;
    }
    
    if (format === 'json') {
        textarea.value = JSON.stringify(_loadedCookies, null, 2);
    } else if (format === 'string') {
        const parts = _loadedCookies.map(c => `${c.name || c.key || ''}=${c.value || ''}`);
        textarea.value = parts.join('; ');
    }
}

function onCookieFormatChange() {
    const select = document.getElementById('settings-cookies-format');
    if (select) {
        displayCookies(select.value);
    }
}

async function importCookies() {
    const text = document.getElementById('settings-cookies-data').value.trim();
    let defaultDomain = document.getElementById('settings-cookies-domain').value.trim() || '.google.com';
    if (!text) {
        alert(T('browser.alert_empty_cookies', 'Please enter cookie content first!'));
        return;
    }
    
    let cookiesList = [];
    try {
        // Try parsing JSON first
        const parsed = JSON.parse(text);
        if (Array.isArray(parsed)) {
            cookiesList = parsed;
        } else if (parsed && typeof parsed === 'object') {
            if (Array.isArray(parsed.cookies)) {
                cookiesList = parsed.cookies;
            } else {
                cookiesList = [parsed];
            }
        }
    } catch (e) {
        // Fallback to plain string parsing (name=value; name2=value2)
        const pairs = text.split(';');
        for (let pair of pairs) {
            pair = pair.trim();
            if (!pair) continue;
            const eqIdx = pair.indexOf('=');
            if (eqIdx === -1) continue;
            const name = pair.substring(0, eqIdx).trim();
            const value = pair.substring(eqIdx + 1).trim();
            if (name) {
                cookiesList.push({
                    name: name,
                    value: value,
                    domain: defaultDomain,
                    path: '/',
                    secure: true,
                    httpOnly: false
                });
            }
        }
    }
    
    if (cookiesList.length === 0) {
        alert(T('browser.alert_invalid_cookies', 'No valid cookies found to import!'));
        return;
    }
    
    // Normalize properties
    cookiesList = cookiesList.map(c => {
        if (c.key && !c.name) c.name = c.key;
        if (!c.name && c.Name) c.name = c.Name;
        if (!c.value && c.Value) c.value = c.Value;
        if (!c.domain && c.Domain) c.domain = c.Domain;
        if (!c.path && c.Path) c.path = c.Path;
        if (!c.secure && c.Secure !== undefined) c.secure = c.Secure;
        if (!c.httpOnly && c.HttpOnly !== undefined) c.httpOnly = c.HttpOnly;
        
        if (!c.name) c.name = '';
        if (!c.value) c.value = '';
        if (!c.domain) c.domain = defaultDomain;
        if (!c.path) c.path = '/';
        if (c.secure === undefined) c.secure = true;
        if (c.httpOnly === undefined) c.httpOnly = false;
        return c;
    }).filter(c => c.name);
    
    try {
        const result = await apiPost(`/api/v1/browser/profiles/${_settingsProfileName}/cookies`, cookiesList);
        if (result && result.status === 'imported') {
            alert(T('browser.alert_import_success', {count: result.count || cookiesList.length}));
            _loadedCookies = cookiesList;
            updateCookieCountDisplay();
            const formatSelect = document.getElementById('settings-cookies-format');
            displayCookies(formatSelect ? formatSelect.value : 'json');
            
            const el = getBrowserBody();
            if (el) renderBrowserExt(el);
        } else {
            alert(T('browser.alert_save_failed', 'Save failed: ') + JSON.stringify(result));
        }
    } catch (err) {
        console.error('Import cookie failed:', err);
        alert(T('browser.alert_error', 'Error: ') + err.message);
    }
}

function copyCookiesToClipboard() {
    const textarea = document.getElementById('settings-cookies-data');
    if (!textarea || !textarea.value.trim()) {
        alert(T('browser.alert_no_cookies_copy', 'No cookie data to copy!'));
        return;
    }
    navigator.clipboard.writeText(textarea.value).then(() => {
        const toast = document.createElement('div');
        toast.textContent = T('browser.alert_copied_clipboard', 'Cookies copied to clipboard!');
        toast.style.cssText = 'position:fixed;top:20px;right:20px;background:#22c55e;color:#fff;padding:12px 24px;border-radius:8px;z-index:99999;font-weight:600;box-shadow:0 4px 12px rgba(0,0,0,0.3);animation:fadeIn .3s';
        document.body.appendChild(toast);
        setTimeout(() => toast.remove(), 2000);
    }).catch(err => {
        console.error('Copy failed:', err);
        alert(T('browser.alert_error', 'Error: ') + err.message);
    });
}

function downloadCookiesFile() {
    if (!_loadedCookies || _loadedCookies.length === 0) {
        alert(T('browser.alert_no_cookies_download', 'No cookie data to download!'));
        return;
    }
    const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(_loadedCookies, null, 2));
    const dlAnchorElem = document.createElement('a');
    dlAnchorElem.setAttribute("href", dataStr);
    dlAnchorElem.setAttribute("download", `${_settingsProfileName}_cookies.json`);
    dlAnchorElem.click();
}

async function clearProfileCookies() {
    if (!confirm(T('browser.confirm_clear_cookies', 'Are you sure you want to clear all cookies for this profile? This will delete cookies.json.'))) {
        return;
    }
    try {
        const result = await apiDelete(`/api/v1/browser/profiles/${_settingsProfileName}/cookies`);
        if (result && (result.status === 'deleted' || result.status === 'not_found')) {
            alert(T('browser.alert_clear_success', 'Cookies cleared successfully!'));
            _loadedCookies = [];
            updateCookieCountDisplay();
            const textarea = document.getElementById('settings-cookies-data');
            if (textarea) textarea.value = '';
            
            const el = getBrowserBody();
            if (el) renderBrowserExt(el);
        } else {
            alert(T('browser.alert_error', 'Error: ') + JSON.stringify(result));
        }
    } catch (err) {
        console.error('Clear cookies failed:', err);
        alert(T('browser.alert_error', 'Error: ') + err.message);
    }
}

async function showProfileSettings(name) {
    _settingsProfileName = name;
    document.getElementById('settings-profile-name').textContent = name;
    
    // Reset tab to general
    switchSettingsTab('general');
    
    // Reset fingerprint status
    const fpStatus = document.getElementById('settings-fp-status');
    if (fpStatus) fpStatus.textContent = T('browser.loading_fp', 'Loading fingerprint...');

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
            
            // Service accounts
            _settingsActiveService = 'google';
            const selectEl = document.getElementById('settings-account-service');
            if (selectEl) selectEl.value = 'google';

            const services = ['google', 'facebook', 'tiktok', 'x', 'discord', 'telegram'];
            services.forEach(s => {
                const acc = data[s + '_account'];
                if (acc && acc.email) {
                    const parts = [acc.email, acc.password || '', acc.recoveryEmail || '', acc.twoFactorCodes || ''];
                    let endIdx = parts.length - 1;
                    while (endIdx >= 0 && !parts[endIdx]) {
                        endIdx--;
                    }
                    _settingsAccounts[s] = parts.slice(0, endIdx + 1).join('|');
                } else {
                    _settingsAccounts[s] = '';
                }
            });

            const dataEl = document.getElementById('settings-account-data');
            if (dataEl) dataEl.value = _settingsAccounts.google;
            updateAccountServiceUI();

            // Fingerprint status
            if (fpStatus) fpStatus.textContent = data.has_fingerprint ? T('browser.fp_loaded_indicator', '✅ Fingerprint loaded') : T('browser.fp_missing_indicator', '⚠️ Fingerprint missing');
            
            // Default cookies domain based on OS/service or just default to .google.com
            const cookieDomainInput = document.getElementById('settings-cookies-domain');
            if (cookieDomainInput) {
                cookieDomainInput.value = '.google.com';
            }
            
            // Load cookies
            loadProfileCookies(name);
        }
    } catch (e) {
        console.error('Failed to load profile:', e);
        if (fpStatus) fpStatus.textContent = T('browser.err_loading_profile', '❌ Error loading profile');
    }
    
    openModal('modal-settings');
}

const ACCOUNT_TEMPLATES = {
    google: {
        placeholder_key: "browser.google_placeholder",
        placeholder: "email@gmail.com|password|recovery@gmail.com|2FA_secret",
        help: "browser.google_help",
        default_help: "Format: email|password|recovery_email|2FA_secret",
        preview: {
            email: "browser.google_lbl_email",
            default_email: "📧 Email:",
            pass: "browser.google_lbl_pass",
            default_pass: "🔑 Password:",
            recovery: "browser.google_lbl_recovery",
            default_recovery: "📩 Recovery Email:",
            twofa: "browser.google_lbl_2fa",
            default_twofa: "🔢 2FA Secret:"
        }
    },
    facebook: {
        placeholder_key: "browser.fb_placeholder",
        placeholder: "uid_or_email|password|recovery_email_or_empty|2FA_secret",
        help: "browser.facebook_help",
        default_help: "Format: UID/Email|Password|Recovery/Empty|2FA_secret",
        preview: {
            email: "browser.fb_lbl_email",
            default_email: "👤 UID / Email:",
            pass: "browser.fb_lbl_pass",
            default_pass: "🔑 Password:",
            recovery: "browser.fb_lbl_recovery",
            default_recovery: "📩 Email/Other:",
            twofa: "browser.fb_lbl_2fa",
            default_twofa: "🔢 2FA Secret:"
        }
    },
    tiktok: {
        placeholder_key: "browser.tiktok_placeholder",
        placeholder: "username_or_email|password|recovery_email_or_empty|2FA_secret",
        help: "browser.tiktok_help",
        default_help: "Format: Username/Email|Password|Recovery/Empty|2FA_secret",
        preview: {
            email: "browser.tiktok_lbl_email",
            default_email: "👤 Username / Email:",
            pass: "browser.tiktok_lbl_pass",
            default_pass: "🔑 Password:",
            recovery: "browser.tiktok_lbl_recovery",
            default_recovery: "📩 Email/Other:",
            twofa: "browser.tiktok_lbl_2fa",
            default_twofa: "🔢 2FA Secret:"
        }
    },
    x: {
        placeholder_key: "browser.x_placeholder",
        placeholder: "username_or_email|password|recovery_email_or_empty|2FA_secret",
        help: "browser.x_help",
        default_help: "Format: Username/Email|Password|Recovery/Empty|2FA_secret",
        preview: {
            email: "browser.x_lbl_email",
            default_email: "👤 Username / Email:",
            pass: "browser.x_lbl_pass",
            default_pass: "🔑 Password:",
            recovery: "browser.x_lbl_recovery",
            default_recovery: "📩 Recovery Email:",
            twofa: "browser.x_lbl_2fa",
            default_twofa: "🔢 2FA Secret:"
        }
    },
    discord: {
        placeholder_key: "browser.discord_placeholder",
        placeholder: "token_or_email|password|recovery_email_or_empty|2FA_secret",
        help: "browser.discord_help",
        default_help: "Format: Token or Email|Password|Recovery/Empty|2FA_secret",
        preview: {
            email: "browser.discord_lbl_email",
            default_email: "👤 Token / Email:",
            pass: "browser.discord_lbl_pass",
            default_pass: "🔑 Password (if using email):",
            recovery: "browser.discord_lbl_recovery",
            default_recovery: "📩 Email/Other:",
            twofa: "browser.discord_lbl_2fa",
            default_twofa: "🔢 2FA Secret:"
        }
    },
    telegram: {
        placeholder_key: "browser.tg_placeholder",
        placeholder: "phone_number|2fa_password|recovery_email_or_empty|2FA_secret",
        help: "browser.telegram_help",
        default_help: "Format: Phone number|2FA Password|Recovery/Empty|2FA_secret (if any)",
        preview: {
            email: "browser.tg_lbl_email",
            default_email: "📞 Phone Number:",
            pass: "browser.tg_lbl_pass",
            default_pass: "🔑 2FA Password:",
            recovery: "browser.tg_lbl_recovery",
            default_recovery: "📩 Email/Other:",
            twofa: "browser.tg_lbl_2fa",
            default_twofa: "🔢 2FA Secret (if any):"
        }
    }
};

function updateAccountServiceUI() {
    const select = document.getElementById('settings-account-service');
    const dataEl = document.getElementById('settings-account-data');
    const helpEl = document.getElementById('settings-account-help');
    
    if (!select || !dataEl) return;
    const service = select.value;
    const tpl = ACCOUNT_TEMPLATES[service] || ACCOUNT_TEMPLATES.google;
    
    dataEl.placeholder = T(tpl.placeholder_key, tpl.placeholder);
    if (helpEl) {
        helpEl.innerHTML = `${T('browser.separate_by', 'Separate using | or Tab.')} ${T(tpl.help, tpl.default_help)}`;
    }
    
    previewActiveAccount();
}

function switchAccountService() {
    const select = document.getElementById('settings-account-service');
    if (!select) return;
    const nextService = select.value;
    
    // Save current input to active service
    const dataEl = document.getElementById('settings-account-data');
    if (dataEl) {
        _settingsAccounts[_settingsActiveService] = dataEl.value.trim();
    }
    
    // Load next service data
    _settingsActiveService = nextService;
    if (dataEl) {
        dataEl.value = _settingsAccounts[nextService] || '';
    }
    updateAccountServiceUI();
}

function previewActiveAccount() {
    const select = document.getElementById('settings-account-service');
    const raw = document.getElementById('settings-account-data').value.trim();
    const previewEl = document.getElementById('settings-account-preview');
    if (!raw) { previewEl.style.display = 'none'; return; }
    
    const service = select ? select.value : 'google';
    const tpl = ACCOUNT_TEMPLATES[service] || ACCOUNT_TEMPLATES.google;
    const parts = raw.includes('|') ? raw.split('|') : raw.split('\t');
    
    const emailLbl = document.getElementById('preview-lbl-email');
    const passLbl = document.getElementById('preview-lbl-pass');
    const recoveryLbl = document.getElementById('preview-lbl-recovery');
    const twofaLbl = document.getElementById('preview-lbl-2fa');
    
    if (emailLbl) emailLbl.textContent = T(tpl.preview.email, tpl.preview.default_email);
    if (passLbl) passLbl.textContent = T(tpl.preview.pass, tpl.preview.default_pass);
    if (recoveryLbl) recoveryLbl.textContent = T(tpl.preview.recovery, tpl.preview.default_recovery);
    if (twofaLbl) twofaLbl.textContent = T(tpl.preview.twofa, tpl.preview.default_twofa);
    
    const emailSpan = document.getElementById('preview-email');
    const passSpan = document.getElementById('preview-pass');
    const recoverySpan = document.getElementById('preview-recovery');
    const twofaSpan = document.getElementById('preview-2fa');
    
    if (emailSpan) emailSpan.textContent = (parts[0] || '').trim() || T('browser.preview_empty', '(empty)');
    if (passSpan) passSpan.textContent = (parts[1] || '').trim() ? '••••••••' : T('browser.preview_empty', '(empty)');
    if (recoverySpan) recoverySpan.textContent = (parts[2] || '').trim() || T('browser.preview_none', '(none)');
    if (twofaSpan) twofaSpan.textContent = (parts[3] || '').trim() || T('browser.preview_none', '(none)');
    
    previewEl.style.display = 'block';
}

async function saveProfileSettings() {
    const proxy = document.getElementById('settings-proxy').value.trim();
    const os = document.getElementById('settings-fp-os').value;
    const browser = document.getElementById('settings-fp-browser').value;
    const browserVersion = document.getElementById('settings-version')?.value || 'default';
    const width  = parseInt(document.getElementById('settings-win-width')?.value)  || 1920;
    const height = parseInt(document.getElementById('settings-win-height')?.value) || 1080;
    
    // Save active service input to in-memory accounts first
    const dataEl = document.getElementById('settings-account-data');
    if (dataEl) {
        _settingsAccounts[_settingsActiveService] = dataEl.value.trim();
    }

    const payload = {
        proxy: proxy,
        tags: [os, browser],
        browser_version: browserVersion,
        window_size: { width, height },
    };
    
    // Add all service accounts to payload
    const services = ['google', 'facebook', 'tiktok', 'x', 'discord', 'telegram'];
    services.forEach(s => {
        payload[s + '_account'] = _settingsAccounts[s] || '';
    });
    
    try {
        console.log('[Settings] Saving:', _settingsProfileName, payload);
        const result = await apiPut(`/api/v1/browser/profiles/${_settingsProfileName}`, payload);
        console.log('[Settings] Result:', result);
        if (result && result.status === 'updated') {
            closeModal('modal-settings');
            // Show inline toast
            const toast = document.createElement('div');
            toast.textContent = T('browser.alert_save_success', '✅ Settings saved!');
            toast.style.cssText = 'position:fixed;top:20px;right:20px;background:#22c55e;color:#fff;padding:12px 24px;border-radius:8px;z-index:99999;font-weight:600;box-shadow:0 4px 12px rgba(0,0,0,0.3);animation:fadeIn .3s';
            document.body.appendChild(toast);
            setTimeout(() => toast.remove(), 2500);
            // Refresh the browser extension view
            const el = getBrowserBody();
            if (el) renderBrowserExt(el);
        } else {
            alert(T('browser.alert_save_failed', 'Save failed: ') + JSON.stringify(result));
        }
    } catch (e) {
        console.error('[Settings] Error:', e);
        alert(T('browser.alert_error', 'Error: ') + e.message);
    }
}

async function refreshFingerprint() {
    const btn = document.getElementById('btn-refresh-fp');
    const fpStatus = document.getElementById('settings-fp-status');
    if (!_settingsProfileName) return;
    if (btn) { btn.disabled = true; btn.textContent = '⏳ ' + T('browser.loading', 'Loading...'); }
    if (fpStatus) fpStatus.textContent = '⏳ ' + T('browser.loading_fp', 'Loading fingerprint...');
    try {
        const result = await apiPost(`/api/v1/browser/profiles/${_settingsProfileName}/fingerprint/refresh`, {});
        if (result && result.status === 'refreshed') {
            if (fpStatus) fpStatus.textContent = T('browser.fp_refresh_success', '✅ New fingerprint fetched successfully!');
            const toast = document.createElement('div');
            toast.textContent = T('browser.fp_refreshed_toast', '🧬 Fingerprint refreshed!');
            toast.style.cssText = 'position:fixed;top:20px;right:20px;background:linear-gradient(135deg,#8b5cf6,#06b6d4);color:#fff;padding:12px 24px;border-radius:8px;z-index:99999;font-weight:600;box-shadow:0 4px 12px rgba(0,0,0,0.3);animation:fadeIn .3s';
            document.body.appendChild(toast);
            setTimeout(() => toast.remove(), 3000);
            // Refresh cards
            const el = getBrowserBody();
            if (el) renderBrowserExt(el);
        } else {
            if (fpStatus) fpStatus.textContent = T('browser.alert_error', 'Error: ') + JSON.stringify(result);
            alert(T('browser.fp_refresh_failed', '❌ Fingerprint refresh failed: ') + JSON.stringify(result));
        }
    } catch (e) {
        if (fpStatus) fpStatus.textContent = T('browser.fp_refresh_conn_error', '❌ Connection error: ') + e.message;
        alert(T('browser.alert_error', 'Error: ') + e.message);
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = T('browser.fp_refresh_label', '🔄 Refresh Fingerprint'); }
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
    if (!confirm('🚀 Bắt đầu cập nhật phiên bản mới?\n\nApp sẽ chạy git pull và tự động khởi động lại.')) return;
    if (btn) { btn.disabled = true; btn.textContent = '⬇️ Đang cập nhật...'; }
    if (statusEl) statusEl.innerHTML = '<span style="color:var(--cyan)">⏳ Đang tải bản cập nhật...</span>';
    try {
        const r = await apiPost('/api/v1/version/update', {});
        if (r.status === 'success') {
            if (r.restarting) {
                // Server will restart — show countdown and wait for reconnect
                if (statusEl) statusEl.innerHTML = '<span style="color:var(--green)">✅ Cập nhật xong! Đang khởi động lại server...</span>';
                if (btn) { btn.textContent = '🔄 Đang khởi động lại...'; }
                // Wait for server to come back up, then reload
                let attempts = 0;
                const maxAttempts = 30;
                const checkInterval = setInterval(async () => {
                    attempts++;
                    if (statusEl) statusEl.innerHTML = `<span style="color:var(--cyan)">⏳ Đang chờ server khởi động lại... (${attempts}s)</span>`;
                    try {
                        const healthResp = await fetch('/api/v1/health', { signal: AbortSignal.timeout(2000) });
                        if (healthResp.ok) {
                            clearInterval(checkInterval);
                            if (statusEl) statusEl.innerHTML = '<span style="color:var(--green)">✅ Server đã khởi động lại! Đang tải lại trang...</span>';
                            setTimeout(() => location.reload(), 1000);
                        }
                    } catch(e) {
                        // Server not ready yet, keep waiting
                    }
                    if (attempts >= maxAttempts) {
                        clearInterval(checkInterval);
                        if (statusEl) statusEl.innerHTML = '<span style="color:var(--orange)">⚠️ Server chưa sẵn sàng. Vui lòng tải lại trang thủ công hoặc chạy lại tubecli init.</span>';
                        if (btn) { btn.disabled = false; btn.textContent = '🔄 Reload'; btn.onclick = () => location.reload(); }
                    }
                }, 1000);
            } else {
                if (statusEl) statusEl.innerHTML = `<span style="color:var(--green)">✅ Cập nhật xong!<br><small style="color:var(--text-muted)">${esc(r.output)}</small></span>`;
                setTimeout(() => { if (confirm('✅ Cập nhật thành công! Tải lại trang ngay?')) location.reload(); }, 1500);
            }
        } else {
            if (statusEl) statusEl.innerHTML = `<span style="color:var(--red)">❌ Lỗi: ${esc(r.output)}</span>`;
            if (btn) { btn.disabled = false; btn.textContent = '⬆️ Update Now'; }
        }
    } catch(e) {
        if (statusEl) statusEl.innerHTML = `<span style="color:var(--red)">❌ Lỗi kết nối: ${e.message}</span>`;
        if (btn) { btn.disabled = false; btn.textContent = '⬆️ Update Now'; }
    }
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
    const notifyEnabled = localStorage.getItem('ext_update_notifications') === 'true';
    if (count > 0 && notifyEnabled) {
        badge.textContent = count;
        badge.style.display = 'inline-flex';
    } else {
        badge.style.display = 'none';
    }
}

function updateSidebarBadgeVisibility() {
    if (_extUpdateCache !== null) {
        updateExtBadge(_extUpdateCache.length);
    } else {
        checkExtensionUpdates(false);
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
    if (!confirm('Bạn có chắc chắn muốn cập nhật extension "' + name + '" lên phiên bản mới nhất không?')) {
        return;
    }
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

// Helper to get all active groupable extensions
function getGroupableExtensions() {
    const enabledSet = new Set(allAvailableExtensions.filter(e => e.enabled).map(e => e.name));
    const extApiMap = {};
    allAvailableExtensions.forEach(e => extApiMap[e.name] = e);

    const groupable = [];
    const seenExtIds = new Set();

    const isExcluded = (extId) => {
        return CORE_NAV_IDS.has(extId);
    };

    // Pool buttons (built-in/static)
    document.querySelectorAll('.nav-item[data-ext]').forEach(btn => {
        const extId = btn.dataset.ext;
        if (isExcluded(extId)) return;
        const isStatic = btn.dataset.extStatic === 'true';
        if (!isStatic && !enabledSet.has(extId)) return;
        if (seenExtIds.has(extId)) return;
        seenExtIds.add(extId);

        const reg = EXT_REGISTRY.find(r => r.id === extId) || {};
        const apiExt = extApiMap[extId] || {};
        groupable.push({
            id: extId,
            name: apiExt.display_name || reg.name || extId,
            icon: apiExt.icon || reg.icon || ''
        });
    });

    // Dynamic external extensions
    allAvailableExtensions.forEach(ext => {
        if (!ext.enabled || !ext.display_name) return;
        if (ext.extension_type !== 'external') return;
        if (isExcluded(ext.name)) return;
        if (seenExtIds.has(ext.name)) return;
        const reg = EXT_REGISTRY.find(r => r.id === ext.name) || {};
        if (reg.type === 'core' || reg.type === 'static') return;
        seenExtIds.add(ext.name);

        groupable.push({
            id: ext.name,
            name: ext.display_name || reg.name || ext.name,
            icon: ext.icon || reg.icon || ''
        });
    });

    return groupable;
}
window.getGroupableExtensions = getGroupableExtensions;

// Global helper to load new dynamic extensions, update sidebar & settings UI
async function loadDynamicExtensionsToSidebar() {
    try {
        const extData = await apiGet('/api/v1/extensions');
        allAvailableExtensions = extData?.extensions || [];
        // update sidebar
        buildSidebar(allAvailableExtensions, globalExtensionGroups);
        // update settings UI
        renderExtensionGroupsSettings();
    } catch (e) {
        console.error('loadDynamicExtensionsToSidebar failed', e);
    }
}
window.loadDynamicExtensionsToSidebar = loadDynamicExtensionsToSidebar;

// HTML5 Drag & Drop handlers
function handleDragStart(e, extId) {
    try {
        e.dataTransfer.setData('text/plain', extId);
    } catch (err) {
        console.warn('dataTransfer.setData failed, using fallback', err);
    }
    window._draggedExtId = extId;
    e.currentTarget.classList.add('dragging');
    document.body.classList.add('dragging-active');
}

function handleDragEnd(e) {
    e.currentTarget.classList.remove('dragging');
    document.body.classList.remove('dragging-active');
    document.querySelectorAll('.ext-group-card').forEach(el => el.classList.remove('drag-over'));
}

function handleDragOver(e) {
    e.preventDefault();
}

function handleDragEnter(e, el) {
    e.preventDefault();
    el.classList.add('drag-over');
}

function handleDragLeave(e, el) {
    el.classList.remove('drag-over');
}

function handleDrop(e, groupId) {
    e.preventDefault();
    const el = e.currentTarget;
    el.classList.remove('drag-over');
    document.body.classList.remove('dragging-active');
    const extId = e.dataTransfer.getData('text/plain') || window._draggedExtId;
    if (extId) {
        addExtToGroup(groupId, extId);
    }
}

function handleDropToDefault(e) {
    e.preventDefault();
    const el = e.currentTarget;
    el.classList.remove('drag-over');
    document.body.classList.remove('dragging-active');
    const extId = e.dataTransfer.getData('text/plain') || window._draggedExtId;
    if (extId) {
        let changed = false;
        globalExtensionGroups.forEach(g => {
            const oldLen = (g.extensions || []).length;
            g.extensions = (g.extensions || []).filter(eid => eid !== extId);
            if ((g.extensions || []).length !== oldLen) changed = true;
        });
        if (changed) {
            saveExtensionGroups();
        }
    }
}

window.handleDragStart = handleDragStart;
window.handleDragEnd = handleDragEnd;
window.handleDragOver = handleDragOver;
window.handleDragEnter = handleDragEnter;
window.handleDragLeave = handleDragLeave;
window.handleDrop = handleDrop;
window.handleDropToDefault = handleDropToDefault;

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
    
    const groupableExtensions = getGroupableExtensions();
    const alreadyGrouped = new Set(globalExtensionGroups.flatMap(grp => grp.extensions || []));
    const defaultExts = groupableExtensions.filter(ext => !alreadyGrouped.has(ext.id));
    
    let html = '';

    // 1. Render Default Group (Ungrouped Extensions) at the top
    let defaultChipsHtml = '';
    if (defaultExts.length === 0) {
        defaultChipsHtml = '<div style="color:var(--text-muted);font-size:0.8rem;padding:4px 8px;font-style:italic;">No ungrouped extensions. Drag here to reset.</div>';
    } else {
        defaultExts.forEach(ext => {
            const extIconHtml = renderExtIcon(ext.icon);
            defaultChipsHtml += `<span class="ext-chip draggable-chip" draggable="true" 
                ondragstart="handleDragStart(event, '${esc(ext.id)}')" 
                ondragend="handleDragEnd(event)"
                style="margin:2px; display:inline-flex; align-items:center; gap:6px; padding:4px 8px 4px 6px;">
                <span style="display:flex;align-items:center;">${extIconHtml}</span>
                <span>${esc(ext.name)}</span>
            </span>`;
        });
    }

    html += `
    <div class="ext-group-card default-group-card" 
         ondragover="handleDragOver(event)" 
         ondragenter="handleDragEnter(event, this)" 
         ondragleave="handleDragLeave(event, this)" 
         ondrop="handleDropToDefault(event)"
         style="padding:16px; border-radius:8px;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
            <div style="font-weight:600; color:var(--text); display:flex; gap:8px; align-items:center;">
                <span class="material-symbols-outlined" style="font-size:20px;color:var(--text-muted);">folder_open</span>
                <span>Default Group (Ungrouped)</span>
            </div>
            <span style="font-size:0.75rem; color:var(--text-muted); font-weight:500; background:var(--bg2); padding:2px 8px; border-radius:10px;">
                ${defaultExts.length} extension${defaultExts.length !== 1 ? 's' : ''}
            </span>
        </div>
        <div style="font-size:0.75rem; color:var(--text-muted); margin-bottom:12px;">Extensions in this group appear directly in the sidebar (ungrouped).</div>
        <div style="display:flex; flex-wrap:wrap; gap:6px; min-height:40px; align-items:center;">
            ${defaultChipsHtml}
        </div>
    </div>`;

    // 2. Render Custom Groups
    if (globalExtensionGroups.length === 0) {
        html += '<div style="color:var(--text-muted);font-size:0.85rem;margin-top:8px;">No custom groups created.</div>';
    } else {
        globalExtensionGroups.forEach((g, idx) => {
            const icon = g.icon || 'folder_special';
            const name = g.name || 'Unnamed Group';
            const extIds = g.extensions || [];
            
            // Build custom dropdown items — only extensions visible in dynamic sidebar
            const hardcodedExtensions = [
                'web_crawler', 'sheets_manager', 'calendar_manager',
                'multi_agents', 'livestream', 'files', 'video_editor', 'douyin_downloader', 'video_downloader', 'video_manager', 'subtitle_extractor', 'ai_arena'
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
                chipsHtml += `<span class="ext-chip draggable-chip" draggable="true"
                    ondragstart="handleDragStart(event, '${esc(eid)}')"
                    ondragend="handleDragEnd(event)"
                    style="margin:2px; display:inline-flex; align-items:center; gap:6px; padding:4px 8px 4px 6px;">
                    <span style="display:flex;align-items:center;">${extIconHtml}</span>
                    <span>${esc(displayName)}</span>
                    <button style="background:none;border:none;color:inherit;cursor:pointer;padding:0 0 0 2px;opacity:0.7;" onclick="removeExtFromGroup('${esc(g.id)}', '${esc(eid)}')">✕</button>
                </span>`;
            });
            
            html += `
            <div class="ext-group-card" 
                 ondragover="handleDragOver(event)" 
                 ondragenter="handleDragEnter(event, this)" 
                 ondragleave="handleDragLeave(event, this)" 
                 ondrop="handleDrop(event, '${esc(g.id)}')"
                 style="background:var(--bg3); padding:12px; border-radius:8px; border:1px solid var(--border); margin-top:8px;">
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
                    <div style="display:flex; flex-wrap:wrap; gap:4px; min-height:30px; align-items:center;">${chipsHtml}</div>
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

// ═══ Icon Picker for Extension Groups ═══
const ICON_PICKER_LIST = [
    { icon: 'folder', label: 'Folder' },
    { icon: 'folder_special', label: 'Special' },
    { icon: 'computer', label: 'Computer' },
    { icon: 'smart_toy', label: 'Robot' },
    { icon: 'movie', label: 'Movie' },
    { icon: 'videocam', label: 'Video' },
    { icon: 'music_note', label: 'Music' },
    { icon: 'brush', label: 'Design' },
    { icon: 'code', label: 'Code' },
    { icon: 'terminal', label: 'Terminal' },
    { icon: 'language', label: 'Language' },
    { icon: 'public', label: 'Web' },
    { icon: 'cloud', label: 'Cloud' },
    { icon: 'storage', label: 'Storage' },
    { icon: 'analytics', label: 'Analytics' },
    { icon: 'monitoring', label: 'Monitor' },
    { icon: 'build', label: 'Tools' },
    { icon: 'settings', label: 'Settings' },
    { icon: 'extension', label: 'Extension' },
    { icon: 'widgets', label: 'Widgets' },
    { icon: 'image', label: 'Image' },
    { icon: 'photo_camera', label: 'Camera' },
    { icon: 'mic', label: 'Mic' },
    { icon: 'headphones', label: 'Audio' },
    { icon: 'download', label: 'Download' },
    { icon: 'upload', label: 'Upload' },
    { icon: 'schedule', label: 'Schedule' },
    { icon: 'notifications', label: 'Notify' },
    { icon: 'mail', label: 'Mail' },
    { icon: 'chat', label: 'Chat' },
    { icon: 'group', label: 'Team' },
    { icon: 'person', label: 'Person' },
    { icon: 'shopping_cart', label: 'Shop' },
    { icon: 'attach_money', label: 'Money' },
    { icon: 'trending_up', label: 'Trending' },
    { icon: 'auto_awesome', label: 'AI Magic' },
    { icon: 'psychology', label: 'Brain' },
    { icon: 'school', label: 'Learn' },
    { icon: 'science', label: 'Science' },
    { icon: 'biotech', label: 'Biotech' },
    { icon: 'security', label: 'Security' },
    { icon: 'vpn_key', label: 'Key' },
    { icon: 'palette', label: 'Palette' },
    { icon: 'sports_esports', label: 'Game' },
    { icon: 'rocket_launch', label: 'Rocket' },
    { icon: 'travel_explore', label: 'Explore' },
    { icon: 'hub', label: 'Hub' },
    { icon: 'dns', label: 'Server' },
];

let _iconPickerInit = false;

function toggleIconPicker() {
    const dropdown = document.getElementById('icon-picker-dropdown');
    if (!dropdown) return;

    if (!_iconPickerInit) {
        const grid = document.getElementById('icon-picker-grid');
        if (grid) {
            grid.innerHTML = ICON_PICKER_LIST.map(item => `
                <div class="icon-picker-item" title="${item.label}"
                    onclick="selectGroupIcon('${item.icon}')"
                    style="display:flex; align-items:center; justify-content:center;
                        padding:8px; border-radius:8px; cursor:pointer; transition:all 0.15s ease;
                        border:1px solid transparent;">
                    <span class="material-symbols-outlined" style="font-size:22px; color:var(--text-secondary)">${item.icon}</span>
                </div>
            `).join('');
        }
        _iconPickerInit = true;
    }

    const isOpen = dropdown.style.display !== 'none';
    dropdown.style.display = isOpen ? 'none' : 'block';

    if (!isOpen) {
        // Close when clicking outside
        setTimeout(() => {
            function closeHandler(e) {
                if (!dropdown.contains(e.target) && e.target.id !== 'set-ext-group-icon') {
                    dropdown.style.display = 'none';
                    document.removeEventListener('click', closeHandler);
                }
            }
            document.addEventListener('click', closeHandler);
        }, 10);
    }
}

function selectGroupIcon(iconName) {
    const input = document.getElementById('set-ext-group-icon');
    if (input) input.value = iconName;
    const dropdown = document.getElementById('icon-picker-dropdown');
    if (dropdown) dropdown.style.display = 'none';
}

let _agentIconPickerInit = false;

function toggleAgentIconPicker() {
    const dropdown = document.getElementById('agent-icon-picker-dropdown');
    if (!dropdown) return;

    if (!_agentIconPickerInit) {
        const grid = document.getElementById('agent-icon-picker-grid');
        if (grid) {
            grid.innerHTML = ICON_PICKER_LIST.map(item => `
                <div class="icon-picker-item" title="${item.label}"
                    onclick="selectAgentIcon('${item.icon}')"
                    style="display:flex; align-items:center; justify-content:center;
                        padding:8px; border-radius:8px; cursor:pointer; transition:all 0.15s ease;
                        border:1px solid transparent;">
                    <span class="material-symbols-outlined" style="font-size:22px; color:var(--text-secondary)">${item.icon}</span>
                </div>
            `).join('');
        }
        _agentIconPickerInit = true;
    }

    const isOpen = dropdown.style.display !== 'none';
    dropdown.style.display = isOpen ? 'none' : 'block';

    if (!isOpen) {
        // Close when clicking outside
        setTimeout(() => {
            function closeHandler(e) {
                const trigger = document.getElementById('agent-icon-trigger');
                if (!dropdown.contains(e.target) && (!trigger || !trigger.contains(e.target))) {
                    dropdown.style.display = 'none';
                    document.removeEventListener('click', closeHandler);
                }
            }
            document.addEventListener('click', closeHandler);
        }, 10);
    }
}

function selectAgentIcon(iconName) {
    const input = document.getElementById('agent-icon');
    if (input) input.value = iconName;
    const dropdown = document.getElementById('agent-icon-picker-dropdown');
    if (dropdown) dropdown.style.display = 'none';
}

function updateAgentIconPreview(val) {
    const preview = document.getElementById('agent-icon-preview');
    if (!preview) return;
    
    if (!val) {
        preview.className = 'material-symbols-outlined';
        preview.textContent = 'smart_toy';
        preview.style.fontSize = '24px';
    } else if (!/^[a-zA-Z_0-9-]+$/.test(val)) {
        // It's an emoji
        preview.className = '';
        preview.textContent = val;
        preview.style.fontSize = '22px';
    } else {
        // It's a Material Symbol
        preview.className = 'material-symbols-outlined';
        preview.textContent = val.toLowerCase();
        preview.style.fontSize = '24px';
    }
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
    // Setup getter/setter on #agent-icon for visual preview updates
    const agentIconEl = document.getElementById('agent-icon');
    if (agentIconEl) {
        const descriptor = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
        Object.defineProperty(agentIconEl, 'value', {
            get() {
                return descriptor.get.call(this);
            },
            set(val) {
                descriptor.set.call(this, val);
                updateAgentIconPreview(val);
            }
        });
        // Initial sync
        updateAgentIconPreview(agentIconEl.value);
    }

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


