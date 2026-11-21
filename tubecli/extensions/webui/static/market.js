/**
 * TubeCLI Extension Market — Client Logic
 */

const API = '/api/v1/market';
// Chợ trên Cloudflare Worker (cùng tài khoản với cloud.tubecreate.com). Máy chủ PHP cũ ở api.tubecreate.com
// đã bỏ (user 14/10/2026) — đăng nhập, đăng ký, ảnh/video minh hoạ đều đi đường này. Có CORS cho mọi origin.
const MARKET_CLI = 'https://market.tubecreate.com/api/market-cli';

function cmpVersions(a, b) {
    if (!a && !b) return 0;
    if (!a) return -1;
    if (!b) return 1;
    const pa = a.split('.').map(Number);
    const pb = b.split('.').map(Number);
    for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
        const na = pa[i] || 0;
        const nb = pb[i] || 0;
        if (na > nb) return 1;
        if (na < nb) return -1;
    }
    return 0;
}

function termLog(msg, color = '#00ff00') {
    const term = document.getElementById('installTerminal');
    if (!term) return;
    term.style.display = 'block';
    const div = document.createElement('div');
    div.style.color = color;
    div.style.marginBottom = '4px';
    div.textContent = '> ' + msg;
    term.appendChild(div);
    term.scrollTop = term.scrollHeight;
}

function clearTerm() {
    const term = document.getElementById('installTerminal');
    if (term) {
        term.innerHTML = '';
        term.style.display = 'none';
    }
}

function updateProgressLog(message, type = 'info', customContainer = null) {
    const logContainer = customContainer || document.getElementById('uploadProgressLog');
    if (!logContainer) return;
    logContainer.style.display = 'block';
    
    let color = '#8cd8f7'; // default info
    let prefix = '[INFO]';
    if (type === 'success') {
        color = '#4ade80';
        prefix = '[SUCCESS]';
    } else if (type === 'error') {
        color = '#f87171';
        prefix = '[ERROR]';
    } else if (type === 'warn') {
        color = '#fbbf24';
        prefix = '[WARN]';
    } else if (type === 'progress') {
        color = '#60a5fa';
        prefix = '[PROGRESS]';
    }
    
    const timeStr = new Date().toLocaleTimeString();
    const newText = `${timeStr} ${prefix} ${message}`;
    
    if (type === 'progress' && logContainer.lastChild && logContainer.lastChild.dataset.type === 'progress') {
        logContainer.lastChild.textContent = newText;
        logContainer.lastChild.style.color = color;
    } else {
        const div = document.createElement('div');
        div.style.marginBottom = '6px';
        div.style.color = color;
        div.dataset.type = type;
        div.textContent = newText;
        logContainer.appendChild(div);
    }
    logContainer.scrollTop = logContainer.scrollHeight;
}

function clearProgressLog() {
    const logContainer = document.getElementById('uploadProgressLog');
    if (logContainer) {
        logContainer.innerHTML = '';
        logContainer.style.display = 'none';
    }
}


// gzip+base64 a string with the browser's native CompressionStream. Python's
// gzip.decompress reads this directly (same RFC 1952 format).
async function _gzipB64String(str) {
    const cs = new CompressionStream('gzip');
    const ab = await new Response(new Blob([str]).stream().pipeThrough(cs)).arrayBuffer();
    const bytes = new Uint8Array(ab);
    let bin = '';
    for (let i = 0; i < bytes.length; i += 0x8000) {
        bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    }
    return btoa(bin);
}

function syncPackageManifest(itemDataObj, metadata, category) {
    if (!itemDataObj) return itemDataObj;
    
    if (!itemDataObj.manifest) {
        itemDataObj.manifest = {};
    }
    
    const manifest = itemDataObj.manifest;
    
    manifest.display_name = metadata.displayName;
    manifest.version = metadata.version;
    manifest.description = metadata.description;
    
    if (metadata.gitUrl !== undefined) {
        itemDataObj.git_url = metadata.gitUrl;
        manifest.git_url = metadata.gitUrl;
    }
    
    if (metadata.authorName || metadata.authorContact || metadata.authorDonate) {
        const authorInfo = {
            name: metadata.authorName,
            contact: metadata.authorContact,
            donate_qr: metadata.authorDonate
        };
        itemDataObj.author_info = authorInfo;
        manifest.author_info = authorInfo;
    }
    
    if (category === 'extension') {
        manifest.dependencies = metadata.dependencies;
        itemDataObj.dependencies = metadata.dependencies;
        
        if (Array.isArray(itemDataObj.files)) {
            const manifestFile = itemDataObj.files.find(f => 
                f.path === 'tubecli-extension.json' || f.path.endsWith('/tubecli-extension.json')
            );
            if (manifestFile) {
                try {
                    let parsedContent = {};
                    if (typeof manifestFile.content === 'string') {
                        parsedContent = JSON.parse(manifestFile.content);
                    } else if (typeof manifestFile.content === 'object') {
                        parsedContent = manifestFile.content;
                    }
                    
                    parsedContent.display_name = metadata.displayName;
                    parsedContent.version = metadata.version;
                    parsedContent.description = metadata.description;
                    parsedContent.dependencies = metadata.dependencies;
                    
                    if (metadata.gitUrl !== undefined) {
                        parsedContent.git_url = metadata.gitUrl;
                    }
                    
                    if (metadata.authorName || metadata.authorContact || metadata.authorDonate) {
                        parsedContent.author_info = {
                            name: metadata.authorName,
                            contact: metadata.authorContact,
                            donate_qr: metadata.authorDonate
                        };
                    }
                    
                    manifestFile.content = JSON.stringify(parsedContent, null, 4);
                    console.log('[Market] Successfully synchronized tubecli-extension.json file content');
                } catch(err) {
                    console.error('[Market] Failed to parse/sync tubecli-extension.json content:', err);
                }
            } else {
                console.warn('[Market] tubecli-extension.json not found in files array to sync');
            }
        }
    }
    
    return itemDataObj;
}

// Language for this iframe context (fetched from API at init)
let _marketLang = localStorage.getItem('tubecli_lang') || 'en';

// ── State ──
const state = {
    category: '',
    kind: '',          // chỉ với category=template: content (mẫu video) | layout (mẫu bìa)
    search: '',
    sort: 'newest',
    minPrice: null,
    maxPrice: null,
    minRating: null,
    activeTags: [],
    page: 1,
    limit: 20,
};

let searchTimer = null;
let categoriesData = null;
let editingPublicId = null; // Track if we're editing an existing listing

const EXTENSION_FEATURES = {
    'android_window': { tagline: 'Android phones on your TubeCLI machine', features: ['📱 Android 14', '🪟 Flow node', '🤖 Agents'] },
    'ai_arena': { tagline: 'AI Chess & Game Battle Arena', features: ['♟️ Chess AI', '🐍 Snake Arena', '🏆 ELO Ranking'] },
    'pod_studio': { tagline: 'AI Video & Podcast Studio', features: ['🎙️ Record', '🎬 Gen AI Video', '✂️ Edit'] },
    'tts_vibevoice': { tagline: 'Ultra-realistic Text to Speech', features: ['🗣️ 100+ Voices', '🎚️ Pitch Control', '🌍 Multi-lang'] },
    'browser_scripts': { tagline: 'Automate Browser Tasks', features: ['🌐 Auto Web', '🖱️ Clicker', '📝 Scrape'] },
    'content_studio': { tagline: 'Content Generation Hub', features: ['✍️ AI Write', '🖼️ AI Image', '📅 Schedule'] },
    'web_crawler': { tagline: 'Data Extraction & Crawling', features: ['🕷️ Spider', '📊 Export CSV', '🕒 Cron Jobs'] },
    'subtitle_extractor': { tagline: 'Extract CC/Subtitles', features: ['📝 SRT/VTT', '🎥 YouTube', '🌍 Translate'] },
    'sheets_manager': { tagline: 'Spreadsheet Automation', features: ['📊 Google Sheets', '🔄 Sync', '📈 Charts'] },
    'video_manager': { tagline: 'Multi-platform Video Uploader', features: ['🎬 YouTube', '📱 TikTok', '🕒 Schedule'] },
    'livestream': { tagline: 'Live Broadcast Manager', features: ['📡 Stream', '💬 Chat', '🔴 Record'] },
    'video_downloader': { tagline: 'Download from Any Platform', features: ['⬇️ YouTube', '⬇️ TikTok', '⬇️ Douyin'] },
    'video_editor': { tagline: 'Timeline Video Editor', features: ['✂️ Trim', '✨ Effects', '🎵 Audio'] }
};

// ── Danh mục trên máy + đồng bộ ngầm (21/11/2026) ──
// User: «chợ load chậm — data kèm luôn trên local trước, chạy đồng bộ ngầm nếu có update extension chứ không mỗi lần
// mỗi load» + «extension trước, template để trong tab, giao diện dễ nhìn — hiện tại vào thấy toàn là button».
// Trước: mỗi lần mở / lọc / lật trang / gõ tìm = một lượt hỏi market.tubecreate.com (~2 s, lâu hơn qua tunnel).
// Nay: máy giữ TOÀN BỘ danh mục (GET /catalog — market/catalog.py, kèm bản chụp theo lõi), trình duyệt nhớ bản
// lần trước (localStorage) ⇒ vẽ ngay; lọc / tìm / sắp xếp làm tại chỗ; máy kéo bản mới trong nền và trang chỉ
// vẽ lại khi chữ ký (sig) hoặc trạng thái đã cài đổi.
const CAT_LS = 'tubecli_market_catalog_v1';
const UI_LS = 'tubecli_market_ui_v1';
const PAGE_SIZE = 60;
let catalog = { items: [], installed: {}, sig: '', synced_at: 0 };
let _syncing = false;
let _shown = PAGE_SIZE;
const ui = { tab: 'extension', kind: '', search: '', sort: 'newest', price: '' };

// T() trả lại chính khoá khi thiếu bản dịch — ở đây thiếu thì dùng câu tiếng Anh viết sẵn.
function tt(key, fallback, vars) {
    let s = (typeof _resolves === 'function' && _resolves(key)) ? T(key) : fallback;
    if (vars) Object.keys(vars).forEach((k) => { s = s.split('{' + k + '}').join(String(vars[k])); });
    return s;
}

function lsGet(key) {
    try { return JSON.parse(localStorage.getItem(key) || 'null'); } catch (e) { return null; }
}
function lsSet(key, val) {
    try { localStorage.setItem(key, JSON.stringify(val)); } catch (e) { /* đầy / bị chặn: bỏ qua */ }
}

const TABS = [
    { key: 'extension', label: () => tt('market.tab_extensions', 'Extensions'), icon: '🧩' },
    { key: 'template', label: () => tt('market.tab_templates', 'Templates'), icon: '🎬' },
    { key: 'skill', label: () => tt('market.tab_skills', 'Skills'), icon: '⚡' },
    { key: 'node', label: () => tt('market.tab_nodes', 'Nodes'), icon: '🔗' },
    { key: 'model3d', label: () => tt('market.tab_models', '3D models'), icon: '🎨' },
];

// ── Init ──
document.addEventListener('DOMContentLoaded', async () => {
    const saved = lsGet(UI_LS);
    if (saved && typeof saved === 'object') {
        ['tab', 'kind', 'sort', 'price'].forEach((k) => { if (typeof saved[k] === 'string') ui[k] = saved[k]; });
    }
    const sortSel = document.getElementById('sortSelect');
    if (sortSel && [...sortSel.options].some((o) => o.value === ui.sort)) sortSel.value = ui.sort; else ui.sort = 'newest';
    const priceSel = document.getElementById('priceSelect');
    if (priceSel) priceSel.value = ui.price;

    // 1) Bản trình duyệt nhớ từ lần trước → vẽ NGAY, trước cả khi máy trả lời.
    const remembered = lsGet(CAT_LS);
    if (remembered && Array.isArray(remembered.items) && remembered.items.length) {
        catalog = remembered;
        renderCatalog();
    }
    // 2) Danh mục của máy (đọc đĩa, nhanh) song song với bản dịch.
    const local = fetchCatalog({}).catch((e) => { console.warn('[Market] catalog', e); return false; });
    await loadI18nFromApi();
    _marketLang = _lang || localStorage.getItem('tubecli_lang') || 'zh';
    await local;
    renderCatalog();
    // 3) Máy đang kéo bản mới (danh mục cũ / chưa có) → chờ nó trong nền, có thay đổi thì vẽ lại.
    if (catalog.syncing || !catalog.items.length) syncCatalog(false);
    // Mở lâu: cứ 10 phút hỏi lại — máy chỉ thật sự gọi Chợ khi danh mục đã cũ.
    setInterval(() => { if (!document.hidden) syncCatalog(false); }, 10 * 60 * 1000);
});

async function fetchCatalog({ wait = false, force = false } = {}) {
    const q = new URLSearchParams({ wait: wait ? '1' : '0', force: force ? '1' : '0' });
    const res = await fetch(`${API}/catalog?${q}`);
    const d = await res.json();
    if (!res.ok || d.status !== 'success') throw new Error(d.detail || d.message || `HTTP ${res.status}`);
    const before = catalog.sig + '|' + JSON.stringify(catalog.installed || {});
    catalog = {
        items: Array.isArray(d.items) ? d.items : [],
        installed: d.installed || {},
        sig: d.sig || '',
        synced_at: d.synced_at || 0,
        syncing: !!d.syncing,
        sync_error: d.sync_error || '',
        source: d.source || '',
    };
    lsSet(CAT_LS, catalog);
    return before !== catalog.sig + '|' + JSON.stringify(catalog.installed);
}

// Đồng bộ với Chợ: force=true = hỏi Chợ ngay cả khi danh mục còn mới (sau khi đăng / sửa / gỡ, hoặc bấm «Check for
// updates»). Chỉ vẽ lại khi có thay đổi.
async function syncCatalog(force = false) {
    if (_syncing) return;
    _syncing = true;
    renderSync();
    try {
        const changed = await fetchCatalog({ wait: true, force });
        if (changed) renderCatalog();
        if (force && !catalog.sync_error) showToast(tt('market.sync_done', 'The Market list is up to date'), 'success');
    } catch (e) {
        catalog.sync_error = String((e && e.message) || e);
    } finally {
        _syncing = false;
        renderSync();
    }
}

// Tên cũ — các chỗ khác trong file gọi sau khi đăng / sửa / gỡ / cài. loadItems = đọc lại danh mục của máy (kèm
// trạng thái đã cài, nhanh); loadCategories = đồng bộ hẳn với Chợ (món vừa đăng / sửa phải hiện ngay).
async function loadItems() {
    try { await fetchCatalog({}); } catch (e) { console.warn('[Market] catalog', e); }
    renderCatalog();
}
const loadMarketItems = loadItems;
function loadCategories() { return syncCatalog(true); }

// Cài / gỡ / cập nhật xong → làm mới trạng thái «đã cài» trên thẻ (máy có thể khởi động lại sau khi cài: đợi chút).
['installItem', 'uninstallItem', 'updateLocalItem'].forEach((name) => {
    const orig = window[name];
    if (typeof orig !== 'function') return;
    window[name] = async function (...args) {
        try { return await orig.apply(this, args); } finally { setTimeout(() => { loadItems(); }, 1500); }
    };
});

function renderSync() {
    const el = document.getElementById('mkSync');
    if (!el) return;
    el.classList.toggle('is-warn', !_syncing && !!catalog.sync_error);
    if (_syncing) {
        el.innerHTML = `<span class="mk-sync-spin"></span>${escapeHtml(tt('market.sync_checking', 'Checking for updates…'))}`;
    } else if (catalog.sync_error) {
        el.textContent = tt('market.sync_offline', 'Offline — showing the saved list');
        el.title = catalog.sync_error;
    } else if (catalog.synced_at) {
        el.textContent = tt('market.sync_ago', 'Updated {t}', { t: timeAgo(catalog.synced_at) });
        el.title = tt('market.menu_check', 'Check for updates');
    } else {
        el.textContent = '';
    }
}

function timeAgo(sec) {
    const d = Math.max(0, Date.now() / 1000 - Number(sec || 0));
    if (d < 60) return tt('market.ago_now', 'just now');
    if (d < 3600) return tt('market.ago_min', '{n} min ago', { n: Math.floor(d / 60) });
    if (d < 86400) return tt('market.ago_hour', '{n} h ago', { n: Math.floor(d / 3600) });
    return tt('market.ago_day', '{n} d ago', { n: Math.floor(d / 86400) });
}

// ── Lọc / sắp xếp tại chỗ ──
function priceOf(it) { return parseFloat(it.price || 0) || 0; }
function tagsOf(it) {
    let t = it.tags;
    if (typeof t === 'string') { try { t = JSON.parse(t); } catch (e) { t = t.split(','); } }
    return Array.isArray(t) ? t.map((x) => String(x).trim()).filter(Boolean) : [];
}
function hasUpdate(it) {
    const inst = (catalog.installed || {})[it.public_id];
    if (!inst || !inst.installed || !inst.local_version) return false;
    try { return cmpVersions(String(it.version || ''), String(inst.local_version)) > 0; } catch (e) { return false; }
}
function isInstalled(it) { const i = (catalog.installed || {})[it.public_id]; return !!(i && i.installed); }

function matchesFilters(it) {
    const p = priceOf(it);
    if (ui.price === 'free' && p > 0) return false;
    if (ui.price === 'paid' && p <= 0) return false;
    const q = ui.search.toLowerCase().trim();
    if (q) {
        const hay = [it.title, it.description, it.seller_name, it.author, ...tagsOf(it)].join(' ').toLowerCase();
        if (!q.split(/\s+/).every((w) => hay.includes(w))) return false;
    }
    return true;
}

function sortItems(list) {
    const by = {
        newest: (a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')),
        updated: (a, b) => String(b.updated_at || '').localeCompare(String(a.updated_at || '')),
        popular: (a, b) => (parseInt(b.downloads || 0) - parseInt(a.downloads || 0)),
        rating: (a, b) => (parseFloat(b.rating_avg || 0) - parseFloat(a.rating_avg || 0)),
        price_asc: (a, b) => priceOf(a) - priceOf(b),
        price_desc: (a, b) => priceOf(b) - priceOf(a),
    }[ui.sort] || ((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')));
    return list.slice().sort(by);
}

function tabOf(it) {
    const c = it.category || 'extension';
    return TABS.some((t) => t.key === c) ? c : 'extension';
}

// ── Vẽ ──
function renderCatalog() {
    const items = catalog.items || [];
    const loading = document.getElementById('marketLoading');
    const grid = document.getElementById('marketGrid');
    const empty = document.getElementById('marketEmpty');
    const pag = document.getElementById('marketPagination');
    if (pag) pag.style.display = 'none';
    renderSync();

    if (!items.length) {
        // Chưa có danh mục nào trên máy (máy cài cực cũ, mất bản chụp): chờ lượt đồng bộ đầu.
        loading.style.display = 'flex';
        grid.style.display = 'none';
        empty.style.display = 'none';
        renderTabs({});
        return;
    }
    loading.style.display = 'none';

    // Chưa có món trả phí nào ⇒ ẩn ô lọc giá (một ô chọn vô nghĩa ít đi).
    const priceSel = document.getElementById('priceSelect');
    const anyPaid = items.some((it) => priceOf(it) > 0);
    if (priceSel) priceSel.style.display = anyPaid ? '' : 'none';
    if (!anyPaid) ui.price = '';

    const filtered = items.filter(matchesFilters);
    const counts = {};
    filtered.forEach((it) => { const k = tabOf(it); counts[k] = (counts[k] || 0) + 1; });
    const totals = {};
    items.forEach((it) => { const k = tabOf(it); totals[k] = (totals[k] || 0) + 1; });
    if (!totals[ui.tab]) ui.tab = TABS.find((t) => totals[t.key])?.key || 'extension';
    renderTabs(counts, totals);

    let list = filtered.filter((it) => tabOf(it) === ui.tab);
    const kinds = renderSubtabs(list);
    if (ui.tab === 'template' && ui.kind && kinds.includes(ui.kind)) {
        list = list.filter((it) => (it.tpl_kind || 'content') === ui.kind);
    }
    list = sortItems(list);

    const countEl = document.getElementById('vsx-result-count');
    if (countEl) {
        countEl.textContent = ui.tab === 'extension' ? tt('market.n_ext', '{n} extensions', { n: list.length })
            : ui.tab === 'template' ? tt('market.n_tpl', '{n} templates', { n: list.length })
            : tt('market.n_items', '{n} items', { n: list.length });
    }

    if (!list.length) {
        grid.style.display = 'none';
        empty.style.display = 'block';
        const hint = document.getElementById('mkEmptyHint');
        if (hint) {
            const other = TABS.find((t) => t.key !== ui.tab && counts[t.key]);
            hint.innerHTML = other && ui.search
                ? `<a href="#" onclick="event.preventDefault(); setTab('${other.key}')">${escapeHtml(tt('market.more_in', '{n} matches in {tab}', { n: counts[other.key], tab: other.label() }))}</a>`
                : escapeHtml(tt('market.empty_hint', 'Try another word or clear the filters.'));
        }
        return;
    }
    empty.style.display = 'none';
    grid.style.display = 'block';
    grid.innerHTML = '';

    if (ui.tab === 'extension') {
        const updates = list.filter((it) => isInstalled(it) && hasUpdate(it));
        const avail = list.filter((it) => !isInstalled(it));
        const done = list.filter((it) => isInstalled(it) && !hasUpdate(it));
        addSection(grid, tt('market.sec_updates', 'Updates available'), updates, 'is-update');
        addSection(grid, tt('market.sec_available', 'Available'), avail);
        addSection(grid, tt('market.sec_installed', 'Installed'), done);
    } else {
        addSection(grid, '', list.slice(0, _shown));
        if (list.length > _shown) {
            const more = document.createElement('button');
            more.type = 'button';
            more.className = 'mk-more';
            more.textContent = tt('market.show_more', 'Show more ({n})', { n: list.length - _shown });
            more.onclick = () => { _shown += PAGE_SIZE; renderCatalog(); };
            grid.appendChild(more);
        }
    }
}

function addSection(grid, title, list, cls = '') {
    if (!list.length) return;
    const sec = document.createElement('section');
    sec.className = 'mk-section ' + cls;
    if (title) {
        const h = document.createElement('h2');
        h.className = 'mk-section-title';
        h.innerHTML = `${escapeHtml(title)} <span>${list.length}</span>`;
        sec.appendChild(h);
    }
    const g = document.createElement('div');
    g.className = ui.tab === 'template' ? 'mk-tpl-grid' : 'mk-ext-grid';
    list.forEach((it) => g.appendChild(ui.tab === 'template' ? templateCard(it) : createCard(it, (catalog.installed || {})[it.public_id])));
    sec.appendChild(g);
    grid.appendChild(sec);
}

function renderTabs(counts, totals = counts) {
    const nav = document.getElementById('mkTabs');
    if (!nav) return;
    const shown = TABS.filter((t) => totals[t.key] || t.key === 'extension' || t.key === 'template');
    nav.innerHTML = shown.map((t) => `
        <button type="button" role="tab" class="mk-tab${t.key === ui.tab ? ' active' : ''}" aria-selected="${t.key === ui.tab}"
                onclick="setTab('${t.key}')">
            <span class="mk-tab-ico">${t.icon}</span>${escapeHtml(t.label())}<span class="mk-tab-n">${counts[t.key] || 0}</span>
        </button>`).join('');
}

// Mẫu chia mẫu video / mẫu bìa — chỉ hiện nút chọn khi cả hai loại đều có hàng.
function renderSubtabs(list) {
    const box = document.getElementById('mkSubtabs');
    const kinds = [...new Set(list.map((it) => it.tpl_kind || 'content'))];
    if (!box) return kinds;
    if (ui.tab !== 'template' || kinds.length < 2) { box.innerHTML = ''; box.style.display = 'none'; return kinds; }
    const names = { '': tt('market.type_all', 'All'), content: tt('market.kind_video', 'Video'), layout: tt('market.kind_layout', 'Cover layouts') };
    box.style.display = 'flex';
    box.innerHTML = ['', ...kinds].map((k) => `<button type="button" class="mk-seg${(ui.kind || '') === k ? ' active' : ''}" onclick="setKind('${k}')">${escapeHtml(names[k] || k)}</button>`).join('');
    return kinds;
}

function saveUi() { lsSet(UI_LS, { tab: ui.tab, kind: ui.kind, sort: ui.sort, price: ui.price }); }
function setTab(key) {
    ui.tab = key; ui.kind = ''; _shown = PAGE_SIZE; saveUi(); renderCatalog();
    const main = document.querySelector('main.market-page');
    if (main) main.scrollTop = 0;
}
function setKind(k) { ui.kind = k; _shown = PAGE_SIZE; saveUi(); renderCatalog(); }
// Tên cũ: '' | extension | template:content | template:layout | skill…
function setType(key) { const [cat, kind] = String(key || '').split(':'); ui.tab = cat || 'extension'; ui.kind = kind || ''; saveUi(); renderCatalog(); }
function setCategoryFromSelect(val) { setType(val); }

function iconFor(item) {
    const icons = { extension: '🧩', node: '🔗', skill: '⚡', model3d: '🎨', template: '🎬' };
    const extName = (item.title || '').toLowerCase().replace(/[^a-z0-9_-]/g, '_');
    let thumbUrl = item.thumbnail_url;
    if (thumbUrl && thumbUrl.startsWith('/images/')) {
        const imgName = thumbUrl.replace('/images/', '').replace('.png', '');
        thumbUrl = (imgName === 'edu_studio' || imgName === 'pod_ad_studio')
            ? '/static/market_logos/pod_studio_logo.png' : `/static/market_logos/${imgName}_logo.png`;
    }
    if (thumbUrl && !/^(https?:\/\/|\/)/i.test(thumbUrl)) thumbUrl = '';
    if (!thumbUrl && EXTENSION_FEATURES[extName]) thumbUrl = `/static/market_logos/${extName}_logo.png`;
    const fallback = icons[item.category || 'extension'] || '📦';
    return thumbUrl
        ? `<img src="${escapeHtml(thumbUrl)}" alt="" loading="lazy" onerror="this.replaceWith(document.createTextNode('${fallback}'))">`
        : fallback;
}

function jsq(s) { return escapeHtml(String(s || '')).replace(/'/g, "\\'"); }

// Một nút duy nhất mỗi thẻ: Cập nhật (cam) / Cài (xanh) / Mua (giá) — đã cài thì chỉ là chữ «✓ Installed».
function actionHtml(item, installData) {
    const pid = item.public_id;
    const cat = item.category || 'extension';
    const price = priceOf(item);
    if (installData && installData.installed) {
        let upd = false;
        try { upd = !!installData.local_version && cmpVersions(String(item.version || ''), String(installData.local_version)) > 0; } catch (e) {}
        if (upd && cat === 'extension') {
            return `<button type="button" id="cardUpdateBtn_${pid}" class="mk-btn mk-btn-warn" title="${escapeHtml(installData.local_version)} → ${escapeHtml(item.version)}"
                onclick="event.stopPropagation(); updateLocalItem('${pid}', '${jsq(item.title)}', '${jsq(cat)}')">${escapeHtml(tt('card.update', 'Update'))}</button>`;
        }
        if (upd && cat === 'template') {
            return `<button type="button" id="cardUpdateBtn_${pid}" class="mk-btn mk-btn-warn" title="${escapeHtml(installData.local_version)} → ${escapeHtml(item.version)}"
                onclick="event.stopPropagation(); installItem('${pid}', '${jsq(item.title)}', 'template', true)">${escapeHtml(tt('card.update', 'Update'))}</button>`;
        }
        return `<span class="mk-installed">✓ ${escapeHtml(tt('market.sec_installed', 'Installed'))}</span>`;
    }
    if (price <= 0) {
        return `<button type="button" id="cardInstallBtn_${pid}" class="mk-btn mk-btn-primary"
            onclick="event.stopPropagation(); installItem('${pid}', '${jsq(item.title)}', '${jsq(cat)}')">${escapeHtml(tt('card.install', 'Install'))}</button>`;
    }
    // Hàng trả phí: mở chi tiết (ở đó có Mua bằng ví / PayPal).
    return `<button type="button" class="mk-btn mk-btn-paid" onclick="event.stopPropagation(); openDetailModal('${pid}')">${escapeHtml(formatCredits(price))}</button>`;
}

function metaHtml(item) {
    // Lượt tải + sao trước, người bán cuối (dòng hẹp thì cắt phần cuối).
    const parts = [];
    const dl = parseInt(item.downloads || 0);
    if (dl > 0) parts.push(`<span title="Downloads">⬇ ${formatNumber(dl)}</span>`);
    if (parseInt(item.rating_count || 0) > 0) parts.push(`<span>★ ${parseFloat(item.rating_avg || 0).toFixed(1)}</span>`);
    const who = item.seller_name || item.author;
    if (who) parts.push(`<span class="mk-who">${escapeHtml(who)}</span>`);
    return parts.join('<i>·</i>');
}

function shortVersion(v) {
    // 2026.11.20.230000 → 2026.11.20 (đuôi giờ đăng chỉ làm rối; bản đầy đủ nằm ở title)
    const s = String(v || '');
    const m = s.match(/^(\d{4}\.\d{1,2}\.\d{1,2})\.\d{4,}$/);
    return m ? m[1] : s;
}

function createCard(item, installData) {
    const extName = (item.title || '').toLowerCase().replace(/[^a-z0-9_-]/g, '_');
    const feat = EXTENSION_FEATURES[extName];
    const desc = item.description || (feat && feat.tagline) || '';
    const card = document.createElement('div');
    card.className = 'mk-card';
    card.tabIndex = 0;
    card.onclick = () => openDetailModal(item.public_id);
    card.onkeydown = (e) => { if (e.key === 'Enter') openDetailModal(item.public_id); };
    card.innerHTML = `
        <div class="mk-ico">${iconFor(item)}</div>
        <div class="mk-body">
            <h3 class="mk-name" title="${escapeHtml(item.title)}">${escapeHtml(item.title)}</h3>
            <p class="mk-desc">${escapeHtml(desc)}</p>
            <div class="mk-foot">
                <div class="mk-meta">${item.version ? `<span class="mk-ver" title="${escapeHtml(item.version)}">v${escapeHtml(shortVersion(item.version))}</span><i>·</i>` : ''}${metaHtml(item)}</div>
                <div class="mk-act">${actionHtml(item, installData)}</div>
            </div>
        </div>`;
    return card;
}

function templateCard(item) {
    const installData = (catalog.installed || {})[item.public_id];
    const card = document.createElement('div');
    card.className = 'mk-tpl';
    card.tabIndex = 0;
    card.onclick = () => openDetailModal(item.public_id);
    card.onkeydown = (e) => { if (e.key === 'Enter') openDetailModal(item.public_id); };
    const cover = item.thumbnail_url
        ? `<img class="tpl-still" src="${escapeHtml(item.thumbnail_url)}" alt="" loading="lazy" onerror="this.style.visibility='hidden'">`
        : `<span class="mk-tpl-ph">🎬</span>`;
    card.innerHTML = `
        <div class="mk-tpl-cover">${cover}
            ${item.anim ? `<img class="tpl-anim" data-src="${escapeHtml(item.anim)}" alt="">` : ''}
            ${item.tpl_kind === 'layout' ? `<span class="mk-tpl-kind">${escapeHtml(tt('market.kind_layout', 'Cover layouts'))}</span>` : ''}
        </div>
        <div class="mk-tpl-info">
            <div class="mk-tpl-text">
                <h3 class="mk-tpl-name" title="${escapeHtml(item.title)}">${escapeHtml(item.title)}</h3>
                <div class="mk-meta">${metaHtml(item)}</div>
            </div>
            <div class="mk-act">${actionHtml(item, installData)}</div>
        </div>`;
    // Ảnh động chỉ TẢI khi có người rê vào lần đầu.
    const anim = card.querySelector('.tpl-anim');
    if (anim) {
        card.addEventListener('mouseenter', () => { if (!anim.src) anim.src = anim.dataset.src; card.classList.add('playing'); });
        card.addEventListener('mouseleave', () => card.classList.remove('playing'));
    }
    return card;
}

// ── Bộ lọc ──
function applyFilters() {
    ui.sort = document.getElementById('sortSelect')?.value || 'newest';
    ui.price = document.getElementById('priceSelect')?.value || '';
    _shown = PAGE_SIZE;
    saveUi();
    renderCatalog();
}

// ── Tìm (tại chỗ — không cần chờ lâu) ──
function debounceSearch() {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
        ui.search = document.getElementById('marketSearch').value.trim();
        _shown = PAGE_SIZE;
        renderCatalog();
    }, 120);
}

// Menu «⋯» (Bán / Hàng của tôi / Kiểm tra cập nhật / Đăng xuất) — thay hàng nút trên đầu trang.
function toggleMkMenu(ev) {
    ev && ev.stopPropagation();
    const m = document.getElementById('mkMenu');
    if (m) m.classList.toggle('open');
}
document.addEventListener('click', (e) => {
    const m = document.getElementById('mkMenu');
    if (m && m.classList.contains('open') && !e.target.closest('.mk-menu')) m.classList.remove('open');
});

// ── Detail Modal ──
async function openDetailModal(publicId) {
    const overlay = document.getElementById('detailModal');
    const body = document.getElementById('modalBody');
    const heroIcon = document.getElementById('modalHeroIcon');

    overlay.classList.add('active');
    body.innerHTML = '<div class="market-loading"><div class="market-spinner"></div></div>';

    try {
        const [res, mediaRes] = await Promise.all([
            fetch(`${API}/items/${publicId}`),
            fetch(`${MARKET_CLI}/get-media?public_id=${encodeURIComponent(publicId)}`).catch(() => null)
        ]);

        const data = await res.json();
        let mediaData = { screenshots: [], videos: [] };
        if (mediaRes && mediaRes.ok) {
            const m = await mediaRes.json();
            // Chợ mới trả mảng URL (chuỗi), PHP cũ trả {url}: chuẩn hoá về {url} cho phần vẽ bên dưới.
            const asObj = (v) => (typeof v === 'string' ? { url: v } : v);
            if (m.status === 'success') mediaData = {
                screenshots: (m.screenshots || []).map(asObj).filter((v) => v && v.url),
                videos: (m.videos || []).map(asObj).filter((v) => v && v.url),
            };
        }

        if (data.status !== 'success') {
            body.innerHTML = '<p style="color:var(--red)">Failed to load item</p>';
            return;
        }

        const item = data.item;
        const reviews = data.reviews || [];
        const price = parseFloat(item.price || 0);
        const isFree = price <= 0;
        const rating = parseFloat(item.rating_avg || 0);
        const tags = item.tags || [];

        const extSlug = (item.title || '').toLowerCase().replace(/[^a-z0-9_-]/g, '_');
        const locale = await loadExtLocale(extSlug);
        const displayTitle = extT(locale, 'name', item.title);
        const displayDesc  = extT(locale, 'description', item.description || 'No description provided.');

        const categoryIcons = { extension: '🧩', node: '🔗', skill: '⚡', model3d: '🎨' };
        
        const knownLogo = EXTENSION_FEATURES[extSlug] ? `/static/market_logos/${extSlug}_logo.png` : null;
        let thumbUrl = item.thumbnail_url;
        if (thumbUrl && thumbUrl.startsWith('/images/')) {
            const imgName = thumbUrl.replace('/images/', '').replace('.png', '');
            if (imgName === 'edu_studio' || imgName === 'pod_ad_studio') {
                thumbUrl = '/static/market_logos/pod_studio_logo.png';
            } else {
                thumbUrl = `/static/market_logos/${imgName}_logo.png`;
            }
        }
        
        if (thumbUrl || knownLogo) {
            heroIcon.innerHTML = `<img src="${escapeHtml(thumbUrl || knownLogo)}" alt="Logo" style="width:100%;height:100%;object-fit:cover;">`;
        } else {
            heroIcon.textContent = categoryIcons[item.category] || '📦';
        }

        // Generate Tabs HTML
        body.innerHTML = `
            <div style="padding: 32px 40px 0 40px;">
                <h2 class="modal-title">${escapeHtml(displayTitle)}</h2>
                <div class="modal-seller">
                    ${item.seller_avatar ? `<img src="${escapeHtml(item.seller_avatar)}" alt="avatar">` : '<span>\u{1F464}</span>'}
                    <span class="seller-name">${escapeHtml(item.seller_name || item.seller_id)}</span>
                    <span>·</span>
                    <span>${data.seller_item_count || 0} ${T('detail.other_items')}</span>
                </div>
                
                <div class="modal-action-row" style="margin-top: 24px;">
                    ${isFree ? '' : `<button class="btn-buy" onclick="buyItem('${publicId}')" id="buyBtn_${publicId}">
                        🛒 ${T('detail.buy_for')} ${formatCredits(price)}
                    </button>`}
                    <button class="btn-install" onclick="installItem('${publicId}', '${escapeHtml(item.title)}', '${escapeHtml(item.category)}')" id="installBtn_${publicId}" style="${isFree ? '' : 'display:none;'}">
                        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
                        ${T('detail.install')}
                    </button>
                </div>
                
                <div class="modal-stats-row" style="margin-top: 24px; padding-bottom: 24px; border-bottom: 1px solid var(--border);">
                    <div class="modal-stat"><span class="stat-icon">⬇️</span> ${formatNumber(item.downloads || 0)} ${T('detail.downloads')}</div>
                    <div class="modal-stat"><span class="stat-icon">⭐</span> ${rating.toFixed(1)}</div>
                    <div class="modal-stat"><span class="stat-icon">📦</span> v${escapeHtml(item.version || '1.0.0')}</div>
                    <div class="modal-stat"><span class="stat-icon">🏷️</span> ${escapeHtml(item.category)}</div>
                </div>
            </div>

            <div class="modal-tabs">
                <div class="modal-tab active" onclick="switchModalTab('overview', this)">📖 Overview</div>
                <div class="modal-tab" onclick="switchModalTab('media', this)">📸 Media Gallery</div>
                <div class="modal-tab" onclick="switchModalTab('reviews', this)">⭐ Reviews (${reviews.length})</div>
            </div>
            
            <div style="padding: 0 40px 32px 40px;">

                <!-- OVERVIEW TAB -->
                <div id="tab-overview" class="tab-content active">
                    <div class="markdown-body" style="margin-top: 24px;">${escapeHtml(displayDesc).replace(/\n/g, '<br>')}</div>
                    ${tags.length ? `<div class="modal-tags" style="margin-top: 24px;">${tags.map(t => `<span class="modal-tag">${escapeHtml(t)}</span>`).join('')}</div>` : ''}
                    
                    ${(() => {
                        try {
                            const itemDataObj = typeof item.item_data === 'string' ? JSON.parse(item.item_data) : item.item_data;
                            const auth = itemDataObj && itemDataObj.author_info;
                            if (!auth) return '';
                            return `
                            <div style="margin:32px 0 0 0;padding:24px;background:var(--bg3);border:1px solid var(--border);border-radius:12px;">
                                <h4 style="margin:0 0 16px 0;font-size:1.1rem;color:var(--text);">💖 Author & Support</h4>
                                <div style="display:flex;flex-wrap:wrap;gap:16px;align-items:center;font-size:0.95rem;">
                                    ${auth.name ? `<div><strong style="color:var(--text2);">Author:</strong> <span style="font-weight:600;color:var(--text);">${escapeHtml(auth.name)}</span></div>` : ''}
                                    ${auth.contact ? `<div><a href="${escapeHtml(auth.contact)}" target="_blank" style="color:var(--primary);text-decoration:none;font-weight:600;">💬 Contact Support</a></div>` : ''}
                                    ${auth.donate_qr ? `<div style="flex-basis:100%;margin-top:12px;">
                                        <strong style="color:var(--text2);display:block;margin-bottom:12px;">Support the Author (Donate):</strong>
                                        <a href="${escapeHtml(auth.donate_qr)}" target="_blank"><img src="${escapeHtml(auth.donate_qr)}" style="max-height:200px;border-radius:12px;border:1px solid var(--border);" alt="Donate QR"></a>
                                    </div>` : ''}
                                </div>
                            </div>`;
                        } catch(e) { return ''; }
                    })()}
                </div>

                <!-- MEDIA TAB -->
                <div id="tab-media" class="tab-content" style="margin-top: 24px;">
                    ${mediaData.videos && mediaData.videos.length ? `
                        <h3 style="margin-bottom: 16px; color: var(--text);">🎬 Demo Video</h3>
                        <div class="media-gallery">
                            ${mediaData.videos.map(v => {
                                const isYouTube = v.url.includes('youtube.com') || v.url.includes('youtu.be');
                                if (isYouTube) {
                                    const ytid = v.url.match(/(?:youtu\.be\/|youtube\.com\/(?:embed\/|v\/|watch\?v=|watch\?.+&v=))([^&]{11})/)?.[1];
                                    return ytid ? `<div class="media-item" onclick="openLightboxVideo('https://www.youtube.com/embed/${ytid}')">
                                        <img src="https://img.youtube.com/vi/${ytid}/hqdefault.jpg" alt="YouTube Demo">
                                        <div class="media-play-icon">▶</div>
                                    </div>` : '';
                                } else {
                                    return `<div class="media-item" onclick="openLightboxVideo('${escapeHtml(v.url)}')">
                                        <video src="${escapeHtml(v.url)}#t=0.1" preload="metadata"></video>
                                        <div class="media-play-icon">▶</div>
                                    </div>`;
                                }
                            }).join('')}
                        </div>
                    ` : ''}
                    
                    ${mediaData.screenshots && mediaData.screenshots.length ? `
                        <h3 style="margin-top: 32px; margin-bottom: 16px; color: var(--text);">📸 Screenshots</h3>
                        <div class="media-gallery">
                            ${mediaData.screenshots.map(s => `
                                <div class="media-item" onclick="openLightboxImage('${escapeHtml(s.url)}')">
                                    <img src="${escapeHtml(s.url)}" alt="Screenshot" loading="lazy">
                                </div>
                            `).join('')}
                        </div>
                    ` : (mediaData.videos && mediaData.videos.length ? '' : '<p style="color:var(--text-muted)">No media uploaded for this item.</p>')}
                </div>

                <!-- REVIEWS TAB -->
                <div id="tab-reviews" class="tab-content" style="margin-top: 24px;">
                    ${reviews.length ? reviews.map(r => `
                        <div class="review-card" style="background:var(--bg3);padding:20px;border-radius:12px;margin-bottom:16px;">
                            <div class="review-header" style="display:flex;justify-content:space-between;margin-bottom:8px;">
                                <span class="review-author" style="font-weight:600;color:var(--text);">${escapeHtml(r.reviewer_name || r.reviewer_id)}</span>
                                <span class="review-date" style="color:var(--text-muted);font-size:0.85rem;">${formatDate(r.created_at)}</span>
                            </div>
                            <div class="review-stars" style="color:var(--accent-orange);margin-bottom:12px;">${renderStars(r.rating)}</div>
                            ${r.comment ? `<div class="review-text" style="line-height:1.5;">${escapeHtml(r.comment)}</div>` : ''}
                        </div>
                    `).join('') : `<p style="color:var(--text-muted);">${T('detail.no_reviews')}</p>`}
                </div>
            </div>
        `;

        // Check if item is already installed locally
        try {
            const checkParams = new URLSearchParams({ item_name: item.title, category: item.category });
            const checkRes = await fetch(`${API}/items/${publicId}/check-installed?${checkParams}`);
            const checkData = await checkRes.json();
            if (checkData.installed) {
                const installBtn = document.getElementById('installBtn_' + publicId);
                if (installBtn) {
                    installBtn.innerHTML = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg> ${T('detail.installed')}`;
                    installBtn.disabled = true;
                    installBtn.style.display = '';
                    installBtn.style.background = '#10b981 linear-gradient(135deg, #22c55e, #10b981)';
                    installBtn.style.boxShadow = '0 2px 12px rgba(34,197,94,0.25)';
                }
                // Hide buy button if item is already installed
                const buyBtn = document.getElementById('buyBtn_' + publicId);
                if (buyBtn) buyBtn.style.display = 'none';

                // Add Uninstall button
                const actionRow = installBtn?.parentElement;
                if (actionRow && !document.getElementById('uninstallBtn_' + publicId)) {
                    const unBtn = document.createElement('button');
                    unBtn.id = 'uninstallBtn_' + publicId;
                    unBtn.className = 'btn-uninstall';
                    unBtn.innerHTML = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"></path><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"></path><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"></path></svg> ${T('detail.uninstall')}`;
                    unBtn.onclick = () => uninstallItem(publicId, item.title, item.category);
                    actionRow.appendChild(unBtn);
                }
                
                // Add Update button for extensions
                if (item.category === 'extension' && actionRow && !document.getElementById('updateBtn_' + publicId)) {
                    let hasUpdate = false;
                    try {
                        if (checkData.local_version && cmpVersions(item.version, checkData.local_version) > 0) {
                            hasUpdate = true;
                        }
                    } catch(e) {}
                    
                    const upBtn = document.createElement('button');
                    upBtn.id = 'updateBtn_' + publicId;
                    upBtn.className = 'btn-update';
                    const rotateSvg = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 2v6h-6"></path><path d="M3 12a9 9 0 0 1 15-6.7L21 8"></path><path d="M3 22v-6h6"></path><path d="M21 12a9 9 0 0 1-15 6.7L3 16"></path></svg>`;
                    upBtn.innerHTML = hasUpdate
                        ? `${rotateSvg} Update ${checkData.local_version} → ${item.version}`
                        : `${rotateSvg} Update`;
                    if (hasUpdate) upBtn.style.boxShadow = '0 0 18px rgba(245,158,11,0.55)';
                    upBtn.onclick = () => updateLocalItem(publicId, item.title, item.category);
                    actionRow.appendChild(upBtn);
                }

                // Mẫu: hiện khi Chợ có bản mới hơn bản máy đã cài (nút sáng, ghi «cũ → mới»), hoặc khi mẫu mua về qua
                // Content Studio mà không rõ bản (nút thường). Máy người bán / mẫu trùng tên tự tạo: không có nút —
                // cập nhật THAY mẫu trùng tên.
                const tplNewer = checkData.local_version && cmpVersions(item.version, checkData.local_version) > 0;
                if (item.category === 'template' && actionRow && !document.getElementById('updateBtn_' + publicId)
                        && (tplNewer || (!checkData.local_version && checkData.version_unknown))) {
                    const upBtn = document.createElement('button');
                    upBtn.id = 'updateBtn_' + publicId;
                    upBtn.className = 'btn-update';
                    if (tplNewer) upBtn.style.boxShadow = '0 0 18px rgba(245,158,11,0.55)';
                    upBtn.innerHTML = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 2v6h-6"></path><path d="M3 12a9 9 0 0 1 15-6.7L21 8"></path><path d="M3 22v-6h6"></path><path d="M21 12a9 9 0 0 1-15 6.7L3 16"></path></svg> ${T('card.update') || 'Update'}`
                        + (tplNewer ? ` ${escapeHtml(checkData.local_version)} → ${escapeHtml(item.version)}` : (item.version ? ` → ${escapeHtml(item.version)}` : ''));
                    upBtn.onclick = () => installItem(publicId, item.title, 'template', true);
                    actionRow.appendChild(upBtn);
                }
            }
        } catch (e) {
            console.warn('[Market] Check installed error:', e);
        }
    } catch (e) {
        body.innerHTML = '<p style="color:var(--red)">Error loading item details</p>';
        console.error('[Market] Detail error:', e);
    }
}

function closeDetailModal() {
    document.getElementById('detailModal').classList.remove('active');
}

// ── Buy Item (with payment choice: Credits or Stripe Quick Pay) ──
async function buyItem(publicId) {
    // Fetch item detail to get price
    try {
        const res = await fetch(`${API}/items/${publicId}`);
        const data = await res.json();
        if (data.status !== 'success') { showToast('Cannot load item', 'error'); return; }
        const item  = data.item;
        const price = parseFloat(item.price || 0);
        if (price <= 0) {
            // Free item — install directly
            await installItem(publicId, item.title, item.category);
            return;
        }
        // Show payment choice modal
        openPaymentChoiceModal(publicId, item.title, price);
    } catch (e) {
        showToast('Error loading item', 'error');
    }
}

// ── Buy with credits (original flow) ──
async function buyItemWithCredits(publicId) {
    closePaymentChoiceModal();
    const btn = document.getElementById('buyBtn_' + publicId);

    const doFetch = async () => {
        try {
            const token = getAuthToken();
            const res = await fetch(`${API}/items/${publicId}/buy`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
                },
            });
            const data = await res.json();
            if (data.status === 'success' || data.purchased) {
                if (btn) { btn.innerHTML = '✅ Purchased'; btn.classList.add('free'); }
                showToast('Mua thành công! Đang tải về máy…', 'success');
                // Refresh balance in header
                loadStripeBalance();
                // Mua xong là CÀI LUÔN (user 29/9: «khi chủ server mua thì tải dữ liệu về máy») —
                // giống luồng PayPal quickpay vốn đã tự bấm Cài sau khi trả tiền.
                const installBtn = document.getElementById('installBtn_' + publicId);
                if (installBtn) {
                    installBtn.style.display = '';
                    installBtn.click();
                } else {
                    try {
                        const det = await (await fetch(`${API}/items/${publicId}`)).json();
                        if (det.item) installItem(publicId, det.item.title, det.item.category);
                    } catch (e) { /* vẫn còn nút Cài trong trang chi tiết */ }
                }
            } else {
                const msg = data.message || data.detail || '';
                if (msg.includes('credit') || msg.includes('insufficient') || res.status === 402) {
                    // Not enough credits — offer top-up
                    openTopUpModal();
                    showToast('Không đủ credits. Vui lòng nạp thêm.', 'warn');
                } else {
                    showToast(msg || 'Purchase failed', 'error');
                }
            }
        } catch (e) {
            showToast('Network error', 'error');
        }
    };
    await doFetch();
}


// ── Install Item ──
// Mẫu (category=template) tải bằng TÀI KHOẢN Chợ của người dùng — chưa đăng nhập thì cài chắc chắn hỏng. Hỏi đăng
// nhập TRƯỚC (hộp có nút «Đăng nhập bằng tài khoản Cloud»), đăng nhập xong tự cài tiếp. User 14/10/2026: «bấm
// install không thành công cũng không thấy thông báo cảnh báo gì».
function askLoginThenInstall(publicId, itemName, category, forceUpdate) {
    pendingAfterLogin = () => installItem(publicId, itemName, category, forceUpdate);
    showLoginModal();
    showToast(T('auth.login_to_install') || 'Sign in to the Market to install templates — your Cloud account works.', 'error');
}

// Cửa sổ cha CÙNG tên miền (dashboard của máy nhúng Chợ), hoặc null. Trong Flow, Chợ nằm trong khung của
// cloud.tubecreate.com: chỉ ĐỌC một thuộc tính của window.parent đã ném SecurityError — «Install error: Failed to read
// a named property 'loadDynamicExtensionsToSidebar' from 'Window'» hiện ra SAU khi mẫu đã cài xong (user 4/11/2026).
function sameOriginParent() {
    try {
        const p = window.parent;
        if (!p || p === window) return null;
        void p.location.href;          // khác tên miền → ném tại đây
        return p;
    } catch (e) {
        return null;
    }
}

async function installItem(publicId, itemName, category, forceUpdate = false) {
    if (category === 'template' && !isLoggedIn()) {
        askLoginThenInstall(publicId, itemName, category, forceUpdate);
        return;
    }
    const modalBtn = document.getElementById('installBtn_' + publicId);
    const cardInstallBtn = document.getElementById('cardInstallBtn_' + publicId);
    const cardUpdateBtn = document.getElementById('cardUpdateBtn_' + publicId);
    const modalUpdateBtn = document.getElementById('updateBtn_' + publicId);   // nút cập nhật mẫu trong chi tiết
    const btns = [modalBtn, cardInstallBtn, cardUpdateBtn, modalUpdateBtn].filter(Boolean);
    
    let originalTexts = [];
    btns.forEach((btn, i) => {
        originalTexts[i] = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<div class="market-spinner" style="width:14px;height:14px;border-width:2px;margin:0 6px 0 0;display:inline-block;vertical-align:middle;"></div> ' + (forceUpdate ? 'Cập nhật...' : 'Đang cài...');
    });

    clearTerm();
    termLog(`Initializing installation for ${itemName}...`, '#88aaff');

    const steps = category === 'template' ? [
        "Downloading the template package from the Market...",
        "Unpacking scenes, layouts and picture libraries...",
        "Importing into Content Studio...",
    ] : [
        "Fetching remote payload from Market API...",
        "Resolving installation paths...",
        "Extracting content into local file system...",
        "Resolving Python (PIP) dependencies if any...",
        "Resolving Node.js (NPM) dependencies if any (This may take a while)..."
    ];
    let stepIdx = 0;
    const termInterval = setInterval(() => {
        if (stepIdx < steps.length) {
            termLog(steps[stepIdx], '#aaaaaa');
            stepIdx++;
        }
    }, 1500);

    try {
        // First get the item detail to access item_data
        const detailRes = await fetch(`${API}/items/${publicId}`);
        const detailData = await detailRes.json();

        if (detailData.status !== 'success' || !detailData.item) {
            clearInterval(termInterval);
            termLog("Failed to fetch item data from Market API.", '#ff4444');
            showToast('Failed to get item data', 'error');
            btns.forEach((btn, i) => {
                btn.disabled = false;
                btn.innerHTML = originalTexts[i];
            });
            return;
        }

        const item = detailData.item;
        const token = getAuthToken();

        const res = await fetch(`${API}/items/${publicId}/install`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
            },
            body: JSON.stringify({
                item_data: item.item_data || JSON.stringify(item),
                item_name: itemName,
                category: category,
                force_update: forceUpdate
            }),
        });
        
        clearInterval(termInterval);
        termLog("Finalizing installation...", '#aaaaaa');
        
        const data = await res.json();

        if (data.status === 'success') {
            termLog("🎉 Installation Complete!", '#00ff00');

            // Derive extension slug for navigation — mẫu thì mở Content Studio, nơi nó vừa được cài
            const extSlug = category === 'template' ? (data.open || 'content_studio')
                : itemName.toLowerCase().replace(/[^a-z0-9_-]/g, '_');
            const extTabId = 'ext-' + extSlug;

            // Refresh sidebar to show the new extension
            const host = sameOriginParent();
            if (host && typeof host.loadDynamicExtensionsToSidebar === 'function') {
                try { await host.loadDynamicExtensionsToSidebar(); } catch(e) {}
            } else if (typeof loadDynamicExtensionsToSidebar === 'function') {
                try { await loadDynamicExtensionsToSidebar(); } catch(e) {}
            }

            btns.forEach((btn) => {
                if (btn.id.startsWith('updateBtn_')) {
                    btn.remove();          // đã lên bản mới — nút Cài bên cạnh thành «Mở Content Studio»
                } else if (btn.id.startsWith('card')) {
                    btn.innerHTML = 'Đã cài';
                    btn.style.background = 'var(--mk-w05)';
                    btn.style.border = '1px solid var(--border)';
                    btn.style.color = 'var(--text-muted)';
                    btn.style.boxShadow = 'none';
                    btn.disabled = true;
                } else {
                    btn.innerHTML = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:middle;margin-right:4px;"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg> ${category === 'template' ? (T('card.open_studio') || 'Open Content Studio') : 'Open ' + itemName}`;
                    btn.style.background = '#10b981 linear-gradient(135deg, #22c55e, #10b981)';
                    btn.style.boxShadow = '0 2px 12px rgba(34,197,94,0.25)';
                    btn.disabled = false;
                    btn.onclick = () => {
                        closeDetailModal();
                        const host = sameOriginParent();
                        if (host && typeof host.navigateTo === 'function') {
                            host.navigateTo(extTabId);
                        } else if (typeof navigateTo === 'function') {
                            navigateTo(extTabId);
                        } else if (host) {
                            host.location.hash = '#/' + extTabId;
                        } else if (window.parent && window.parent !== window) {
                            // Khung của trang khác (Flow trên cloud.tubecreate.com): không điều khiển được trang ngoài
                            // → mở dashboard của máy này ở tab mới, đúng extension vừa cài.
                            window.open(location.origin + '/#/' + extTabId, '_blank', 'noopener');
                        } else {
                            window.location.hash = '#/' + extTabId;
                        }
                    };
                }
            });
            showToast(data.message || 'Installed successfully!', 'success');
        } else if (res.status === 409 || data.detail?.already_installed) {
            termLog("Item is already installed.", '#ffaa00');
            btns.forEach((btn) => {
                if (btn.id.startsWith('card')) {
                    btn.innerHTML = 'Đã cài';
                    btn.style.background = 'var(--mk-w05)';
                    btn.style.border = '1px solid var(--border)';
                    btn.style.color = 'var(--text-muted)';
                    btn.style.boxShadow = 'none';
                } else {
                    btn.innerHTML = '✅ Installed';
                }
                btn.disabled = true;
            });
            showToast(data.detail?.message || 'This item is already installed', 'error');
        } else {
            // detail có thể là chuỗi hoặc {message} — trước đây đối tượng thành «[object Object]».
            const errMsg = (typeof data.detail === 'string' ? data.detail : (data.detail && data.detail.message))
                || data.message || 'Install failed';
            btns.forEach((btn, i) => {
                btn.disabled = false;
                btn.innerHTML = originalTexts[i];
            });
            // Khoá Chợ hết hạn / bị thu hồi (401 từ Chợ, KHÔNG phải 401 đăng nhập TubeCLI — cái đó có `reason`):
            // bỏ khoá cũ rồi hỏi đăng nhập lại, xong tự cài tiếp.
            if (res.status === 401 && category === 'template' && !data.reason) {
                localStorage.removeItem('user_token');
                try { updateMarketAuthUI(); } catch {}
                termLog("🔑 " + errMsg, '#ffaa00');
                askLoginThenInstall(publicId, itemName, category, forceUpdate);
                return;
            }
            termLog("❌ Installation Failed: " + errMsg, '#ff4444');
            showToast(errMsg, 'error');
            const err = new Error(errMsg);
            err.toastShown = true;
            throw err;
        }
    } catch (e) {
        clearInterval(termInterval);
        btns.forEach((btn, i) => {
            btn.disabled = false;
            btn.innerHTML = originalTexts[i];
        });
        if (!e.toastShown) {
            termLog("❌ Network / Execution Error: " + e.message, '#ff4444');
            showToast('Install error: ' + e.message, 'error');
        }
        throw e;
    }
}

// ── Uninstall Item ──
async function uninstallItem(publicId, itemName, category) {
    const confirmed = await customConfirm(
        'Gỡ cài đặt extension',
        `Bạn có chắc muốn gỡ cài đặt "<b>${itemName}</b>"?<br>Hành động này sẽ xóa toàn bộ source files của extension này khỏi máy.`,
        'Xác nhận gỡ cài đặt',
        'Hủy',
        '#dc2626 linear-gradient(135deg, #ef4444, #dc2626)',
        '🗑️'
    );
    if (!confirmed) return;

    const unBtn = document.getElementById('uninstallBtn_' + publicId);
    if (unBtn) {
        unBtn.innerHTML = '<div class="market-spinner" style="width:18px;height:18px;border-width:2px;margin:0;"></div> Removing...';
        unBtn.disabled = true;
    }

    try {
        const params = new URLSearchParams({ item_name: itemName, category });
        const res = await fetch(`${API}/items/${publicId}/uninstall?${params}`, {
            method: 'POST',
        });
        const data = await res.json();

        if (res.ok && (data.status === 'success')) {
            showToast(data.message || `"${itemName}" uninstalled`, 'success');
            // Reset Install button
            const installBtn = document.getElementById('installBtn_' + publicId);
            if (installBtn) {
                installBtn.innerHTML = '📦 Install';
                installBtn.disabled = false;
                installBtn.style.background = '';
            }
            // Remove Uninstall button
            if (unBtn) unBtn.remove();
            // Show buy button again if needed
            const buyBtn = document.getElementById('buyBtn_' + publicId);
            if (buyBtn) buyBtn.style.display = '';
        } else {
            throw new Error(data.detail || data.message || 'Uninstall failed');
        }
    } catch (e) {
        showToast(e.message || 'Uninstall error', 'error');
        if (unBtn) {
            unBtn.innerHTML = '🗑️ Uninstall';
            unBtn.disabled = false;
        }
    }
}

// ── Update Item ──
async function updateLocalItem(publicId, itemName, category = "extension") {
    const modalBtn = document.getElementById('updateBtn_' + publicId);
    const cardBtn = document.getElementById('cardUpdateBtn_' + publicId);
    const btns = [modalBtn, cardBtn].filter(Boolean);
    
    let originalTexts = [];
    btns.forEach((btn, i) => {
        originalTexts[i] = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<div class="market-spinner" style="width:14px;height:14px;border-width:2px;margin:0 6px 0 0;display:inline-block;vertical-align:middle;"></div> Đang cập nhật...';
    });

    clearTerm();
    termLog(`Checking updates for ${itemName}...`, '#88aaff');

    const updateInterval = setInterval(() => {
        termLog("Executing Git Pull and dependency updates...", '#aaaaaa');
    }, 2000);

    try {
        const res = await fetch(`${API}/items/${encodeURIComponent(itemName)}/update-local`, {
            method: 'POST',
        });
        
        clearInterval(updateInterval);
        const data = await res.json();
        
        if (data.status === 'success') {
            termLog("✅ Extension hot-reloaded successfully!", '#00ff00');
            showToast(data.message || `"${itemName}" updated`, 'success');
            setTimeout(() => {
                btns.forEach((btn) => {
                    if (btn.id.startsWith('card')) {
                        btn.innerHTML = 'Đã cập nhật';
                        btn.style.background = 'var(--mk-w05)';
                        btn.style.border = '1px solid var(--border)';
                        btn.style.color = 'var(--text-muted)';
                        btn.style.boxShadow = 'none';
                        btn.disabled = true;
                    } else {
                        btn.innerHTML = '✅ Updated';
                        btn.style.boxShadow = 'none';
                        btn.disabled = true;
                    }
                });
            }, 1000);
        } else if (res.status === 400 && (data.detail === "Currently only extensions installed via Git can be updated." || 
                                         data.message === "Currently only extensions installed via Git can be updated.")) {
            // ZIP Fallback Update Overwrite
            termLog("Extension was not installed via Git. Triggering Market ZIP Fallback Force Update...", '#ffaa00');
            showToast('Fetching latest ZIP update from Market...', 'info');
            await installItem(publicId, itemName, category, true);
            btns.forEach((btn) => {
                if (btn.id.startsWith('card')) {
                    btn.innerHTML = 'Đã cập nhật';
                    btn.style.background = 'var(--mk-w05)';
                    btn.style.border = '1px solid var(--border)';
                    btn.style.color = 'var(--text-muted)';
                    btn.style.boxShadow = 'none';
                } else {
                    btn.innerHTML = '✅ Updated';
                    btn.style.boxShadow = 'none';
                }
                btn.disabled = true;
            });
        } else {
            termLog("❌ Update Failed: " + (data.detail || data.message || 'Unknown'), '#ff4444');
            throw new Error(data.message || data.detail || 'Update failed');
        }
    } catch (e) {
        clearInterval(updateInterval);
        termLog("❌ Error: " + e.message, '#ff4444');
        showToast(e.message || 'Update error', 'error');
        btns.forEach((btn, i) => {
            btn.innerHTML = originalTexts[i];
            btn.disabled = false;
        });
    }
}

// ── Upload Wizard ──
let uploadState = {
    category: 'skill',
    selectedItem: null,
    allItems: [],
};

const CATEGORY_API_MAP = {
    skill:     '/api/v1/skills',
    extension: '/api/v1/extensions',
    node:      '/api/v1/nodes',
    model3d:   '/api/v1/workflows',  // 3D models stored as workflows
};

const CATEGORY_ICONS = { extension: '🧩', node: '🔗', skill: '⚡', model3d: '🎨' };

function openUploadModal() {
    uploadState.selectedItem = null;
    uploadState.category = 'extension';
    
    // Clear all Step 2 inputs to prevent leaked state from previous runs
    document.getElementById('uploadDisplayName').value = '';
    document.getElementById('uploadPrice').value = '0';
    document.getElementById('uploadVisibility').value = 'PUBLIC';
    document.getElementById('uploadVersion').value = '1.0.0';
    const uploadAvatar = document.getElementById('uploadAvatar');
    if (uploadAvatar) uploadAvatar.value = '';
    document.getElementById('uploadTags').value = '';
    document.getElementById('uploadDesc').value = '';
    document.getElementById('uploadData').value = '';
    
    const depsInput = document.getElementById('uploadDeps');
    if (depsInput) depsInput.value = '';
    const gitInput = document.getElementById('uploadGitUrl');
    if (gitInput) gitInput.value = '';
    const aName = document.getElementById('uploadAuthorName');
    const aContact = document.getElementById('uploadAuthorContact');
    const aDonate = document.getElementById('uploadAuthorDonate');
    if (aName) aName.value = '';
    if (aContact) aContact.value = '';
    if (aDonate) aDonate.value = '';
    const videoUrl = document.getElementById('uploadVideoUrl');
    if (videoUrl) videoUrl.value = '';
    
    const submitBtn = document.getElementById('uploadSubmitBtn');
    if (submitBtn) submitBtn.innerHTML = '📤 Publish to Market';
    
    clearProgressLog();
    
    // Reset active category tab styles
    document.querySelectorAll('.ucat-tab').forEach(t => {
        if (t.getAttribute('data-cat') === 'extension') {
            t.classList.add('active');
        } else {
            t.classList.remove('active');
        }
    });
    
    goToUploadStep(1);
    document.getElementById('uploadModal').classList.add('active');
    loadUploadItems('extension');
}

function closeUploadModal() {
    document.getElementById('uploadModal').classList.remove('active');
    editingPublicId = null; // Clear edit mode
}

function goToUploadStep(step) {
    const step1 = document.getElementById('uploadStep1');
    const step2 = document.getElementById('uploadStep2');
    const steps = document.querySelectorAll('#uploadSteps .upload-step');

    if (step === 1) {
        step1.style.display = 'block';
        step2.style.display = 'none';
        steps[0].className = 'upload-step active';
        steps[1].className = 'upload-step';
    } else {
        step1.style.display = 'none';
        step2.style.display = 'block';
        steps[0].className = 'upload-step done';
        steps[1].className = 'upload-step active';

        // Fill preview
        if (uploadState.selectedItem) {
            const item = uploadState.selectedItem;
            const icon = CATEGORY_ICONS[uploadState.category] || '📦';
            document.getElementById('selectedItemPreview').innerHTML = `
                <span class="preview-icon">${icon}</span>
                <div class="preview-info">
                    <div class="preview-name">${escapeHtml(item._displayName)}</div>
                    <div class="preview-type">${uploadState.category}</div>
                </div>
            `;
            document.getElementById('uploadDisplayName').value = item._displayName;
            document.getElementById('uploadCategory').value = uploadState.category;
            document.getElementById('uploadTitle').value = item._displayName;
            document.getElementById('uploadDesc').value = item._description || '';

            // For extensions: package all source files via /package API
            if (uploadState.category === 'extension') {
                document.getElementById('uploadData').value = '{}'; // placeholder
                const depsGroup = document.getElementById('uploadDepsGroup');
                if (depsGroup) depsGroup.style.display = 'block';
                
                fetch(`/api/v1/extensions/${encodeURIComponent(item._id)}/package`)
                    .then(r => r.json())
                    .then(pkg => {
                        if (pkg.status === 'success') {
                            document.getElementById('uploadData').value = JSON.stringify({
                                manifest: pkg.manifest,
                                files: pkg.files,
                            });
                            console.log(`[Market] Packaged extension: ${pkg.file_count} files`);
                            
                            // Auto-fill version from manifest
                            if (pkg.manifest?.version) {
                                document.getElementById('uploadVersion').value = pkg.manifest.version;
                            }
                            
                            // Auto-fill dependencies from manifest
                            const depsInput = document.getElementById('uploadDeps');
                            if (depsInput && pkg.manifest?.dependencies?.length) {
                                depsInput.value = pkg.manifest.dependencies.join(', ');
                            }
                            
                            // Auto-fill git url from manifest
                            if (pkg.manifest?.git_url) {
                                document.getElementById('uploadGitUrl').value = pkg.manifest.git_url;
                            }
                            
                            // Auto-fill author info from manifest
                            if (pkg.manifest?.author_info) {
                                const a = pkg.manifest.author_info;
                                const aName = document.getElementById('uploadAuthorName');
                                const aContact = document.getElementById('uploadAuthorContact');
                                const aDonate = document.getElementById('uploadAuthorDonate');
                                if (aName && a.name) aName.value = a.name;
                                if (aContact && a.contact) aContact.value = a.contact;
                                if (aDonate && a.donate_qr) aDonate.value = a.donate_qr;
                            }
                        } else {
                            showToast('Failed to package extension files', 'error');
                            document.getElementById('uploadData').value = JSON.stringify(item._rawData);
                        }
                    })
                    .catch(() => {
                        document.getElementById('uploadData').value = JSON.stringify(item._rawData);
                    });
            } else {
                // Hide deps group for non-extension categories
                const depsGroup = document.getElementById('uploadDepsGroup');
                if (depsGroup) depsGroup.style.display = 'none';
                document.getElementById('uploadData').value = JSON.stringify(item._rawData);
            }
        }
    }
}

function switchUploadCategory(category, btn) {
    uploadState.category = category;
    uploadState.selectedItem = null;
    document.querySelectorAll('.ucat-tab').forEach(t => t.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('uploadItemSearch').value = '';
    loadUploadItems(category);
}

async function loadUploadItems(category) {
    const list = document.getElementById('uploadItemsList');
    list.innerHTML = '<div class="market-loading" style="padding:40px 0;"><div class="market-spinner"></div><span style="color:var(--text-muted)">Loading your items...</span></div>';

    const apiUrl = CATEGORY_API_MAP[category] || '/api/v1/skills';
    try {
        const res = await fetch(apiUrl);
        const data = await res.json();

        let items = [];

        if (category === 'skill') {
            const raw = data.skills || data || [];
            items = (Array.isArray(raw) ? raw : []).map(s => ({
                _id: s.id || s.name,
                _displayName: s.name || s.id || 'Unnamed Skill',
                _description: s.description || '',
                _meta: s.type || 'skill',
                _rawData: s,
            }));
        } else if (category === 'extension') {
            const raw = data.extensions || data || [];
            items = (Array.isArray(raw) ? raw : [])
                .filter(e => e.extension_type === 'external')  // Only allow selling external extensions
                .map(e => ({
                    _id: e.name || e.id,
                    _displayName: e.name || e.id || 'Unnamed Extension',
                    _description: e.description || '',
                    _meta: `v${e.version || '1.0'}`,
                    _rawData: e,
                }));
        } else if (category === 'node') {
            const raw = data.nodes || data || [];
            items = (Array.isArray(raw) ? raw : []).map(n => ({
                _id: n.type || n.name || n.id,
                _displayName: n.name || n.type || 'Unnamed Node',
                _description: n.description || '',
                _meta: n.category || 'node',
                _rawData: n,
            }));
        } else if (category === 'model3d') {
            const raw = data.workflows || data || [];
            items = (Array.isArray(raw) ? raw : []).map(w => ({
                _id: w.name || w.id,
                _displayName: w.name || w.id || 'Unnamed Model',
                _description: w.description || '',
                _meta: `${(w.nodes || []).length} nodes`,
                _rawData: w,
            }));
        }

        // Fetch user's listings to filter out already published ones
        const token = getAuthToken();
        let myItems = [];
        try {
            const myItemsRes = await fetch(`${API}/my-items`, {
                headers: token ? { 'Authorization': `Bearer ${token}` } : {},
            });
            if (myItemsRes.ok) {
                const myItemsData = await myItemsRes.json();
                if (myItemsData.status === 'success' && Array.isArray(myItemsData.data)) {
                    myItems = myItemsData.data;
                }
            }
        } catch (err) {
            console.error('[Market] Failed to load my-items for upload filtering:', err);
        }

        if (myItems.length > 0) {
            const myItemsOfCategory = myItems.filter(mi => mi.category === category);
            items = items.filter(localItem => {
                const normLocalId = normalizeString(localItem._id);
                const normLocalName = normalizeString(localItem._displayName);
                
                const alreadyPublished = myItemsOfCategory.some(mi => {
                    const normTitle = normalizeString(mi.title);
                    return normTitle === normLocalId || normTitle === normLocalName;
                });
                return !alreadyPublished;
            });
        }

        uploadState.allItems = items;
        renderUploadItems(items);

    } catch (e) {
        console.error('[Market] Load upload items error:', e);
        list.innerHTML = '<div class="upload-items-empty"><div class="empty-icon">⚠️</div><p>Failed to load items</p></div>';
    }
}

function renderUploadItems(items) {
    const list = document.getElementById('uploadItemsList');
    const icon = CATEGORY_ICONS[uploadState.category] || '📦';

    if (!items.length) {
        list.innerHTML = `<div class="upload-items-empty"><div class="empty-icon">${icon}</div><p>No ${uploadState.category}s found.<br>Create some first!</p></div>`;
        return;
    }

    list.innerHTML = '';
    items.forEach(item => {
        const card = document.createElement('div');
        card.className = 'upload-item-card' + (uploadState.selectedItem?._id === item._id ? ' selected' : '');
        card.onclick = () => selectUploadItem(item);

        card.innerHTML = `
            <span class="upload-item-icon">${icon}</span>
            <div class="upload-item-info">
                <div class="upload-item-name">${escapeHtml(item._displayName)}</div>
                <div class="upload-item-meta">${escapeHtml(item._meta)}${item._description ? ' · ' + escapeHtml(item._description).substring(0, 60) : ''}</div>
            </div>
            <span class="upload-item-select-btn">${uploadState.selectedItem?._id === item._id ? '✓ Selected' : 'Select'}</span>
        `;
        list.appendChild(card);
    });
}

function selectUploadItem(item) {
    uploadState.selectedItem = item;
    // Re-render to update selection UI
    renderUploadItems(uploadState.allItems.filter(i => {
        const query = document.getElementById('uploadItemSearch').value.toLowerCase();
        return !query || i._displayName.toLowerCase().includes(query);
    }));
    // Auto-advance to step 2
    setTimeout(() => goToUploadStep(2), 300);
}

function filterUploadItems() {
    const query = document.getElementById('uploadItemSearch').value.toLowerCase();
    const filtered = uploadState.allItems.filter(i =>
        i._displayName.toLowerCase().includes(query) ||
        (i._description || '').toLowerCase().includes(query)
    );
    renderUploadItems(filtered);
}

async function submitUpload(e) {
    e.preventDefault();
    const btn = document.getElementById('uploadSubmitBtn');
    btn.disabled = true;
    
    const isEdit = !!editingPublicId;
    btn.innerHTML = isEdit ? '⏳ Saving changes...' : '⏳ Publishing...';
    
    // Clear and initialize log panel
    clearProgressLog();
    updateProgressLog(isEdit ? "Chuẩn bị lưu thay đổi listing..." : "Bắt đầu đăng sản phẩm lên Market...", "info");

    const tagsInput = document.getElementById('uploadTags').value;
    const tags = tagsInput ? tagsInput.split(',').map(t => t.trim()).filter(Boolean) : [];
    
    const category = document.getElementById('uploadCategory').value;
    const displayName = document.getElementById('uploadDisplayName').value || document.getElementById('uploadTitle').value;
    const version = document.getElementById('uploadVersion').value || '1.0.0';
    const description = document.getElementById('uploadDesc').value;
    
    // Build metadata object for synchronization
    const metadata = {
        displayName: displayName,
        version: version,
        description: description || '',
        dependencies: (() => {
            const depsInput = document.getElementById('uploadDeps')?.value || '';
            return depsInput.split(',').map(d => d.trim()).filter(Boolean);
        })(),
        gitUrl: document.getElementById('uploadGitUrl') ? document.getElementById('uploadGitUrl').value : '',
        authorName: document.getElementById('uploadAuthorName') ? document.getElementById('uploadAuthorName').value.trim() : '',
        authorContact: document.getElementById('uploadAuthorContact') ? document.getElementById('uploadAuthorContact').value.trim() : '',
        authorDonate: document.getElementById('uploadAuthorDonate') ? document.getElementById('uploadAuthorDonate').value.trim() : ''
    };

    updateProgressLog(`[Metadata] Đang đồng bộ thông tin: ${displayName} (v${version})`, "info");

    const payload = {
        title: displayName,
        category: category,
        price: parseFloat(document.getElementById('uploadPrice').value) || 0,
        visibility: document.getElementById('uploadVisibility').value,
        version: version,
        thumbnail_url: document.getElementById('uploadAvatar') ? document.getElementById('uploadAvatar').value.trim() : undefined,
        tags: tags,
        description: description,
        item_data: (() => {
            let raw = document.getElementById('uploadData').value;
            try {
                let parsed = JSON.parse(raw);
                parsed = syncPackageManifest(parsed, metadata, category);
                raw = JSON.stringify(parsed);
                
                if (category === 'extension') {
                    updateProgressLog("Đã đồng bộ hoá manifest tubecli-extension.json thành công.", "success");
                }
            } catch(err) {
                updateProgressLog("Cảnh báo: Không thể đồng bộ hoá manifest file bên trong gói file.", "warn");
                console.error('[Market] Parsing error during syncPackageManifest inside submitUpload:', err);
            }
            return raw;
        })(),
        git_url: metadata.gitUrl || undefined,
    };

    // A big extension's item_data blows the market server's request limit
    // (capcut_tts: 1.1 MB of JSON -> HTTP 413). Compress AFTER the manifest
    // sync so the sync always operates on the plain {manifest, files} object;
    // the installer's _unwrap_item_data decompresses this envelope.
    if (category === 'extension' && typeof CompressionStream !== 'undefined'
        && payload.item_data && payload.item_data.length > 600_000) {
        try {
            const rawKB = Math.round(payload.item_data.length / 1024);
            const packedData = await _gzipB64String(payload.item_data);
            payload.item_data = JSON.stringify({
                format: 'gzip+b64',
                name: displayName, version: version,
                data: packedData,
            });
            updateProgressLog(`Đã nén gói: ${rawKB} KB → ${Math.round(payload.item_data.length / 1024)} KB.`, "success");
        } catch (err) {
            updateProgressLog("Không nén được gói — gửi bản thường.", "warn");
            console.error('[Market] compress failed:', err);
        }
    }

    try {
        const token = getAuthToken();
        const url = isEdit ? `${API}/items/${editingPublicId}` : `${API}/items`;
        const method = isEdit ? 'PUT' : 'POST';
        
        updateProgressLog("Đang tải dữ liệu metadata lên Market API...", "info");
        
        const res = await fetch(url, {
            method,
            headers: {
                'Content-Type': 'application/json',
                ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
            },
            body: JSON.stringify(payload),
        });
        const data = await res.json();

        if (res.status === 409) {
            const errMsg = typeof data.detail === 'string' ? data.detail : (data.message || 'Extension name already taken');
            updateProgressLog(`Thất bại: ${errMsg}`, "error");
            showToast(errMsg, 'error');
        } else if (data.status === 'success' || data.public_id) {
            const publicId = data.public_id || data.item?.public_id || editingPublicId;
            updateProgressLog(`Tải metadata thành công! ID sản phẩm: ${publicId}`, "success");
            
            // --- UPLOAD MEDIA ---
            const ytUrl = document.getElementById('uploadVideoUrl')?.value.trim();
            if (publicId && (uploadMediaFiles.screenshots.length > 0 || uploadMediaFiles.video || ytUrl)) {
                updateProgressLog("Phát hiện file media. Đang chuẩn bị tải lên media...", "info");
                btn.innerHTML = '⏳ Uploading Media...';
                
                try {
                    // Chợ mới (Worker) nhận MỘT file mỗi lượt (trường `file`) — PHP cũ nhận cả lô
                    // screenshots[] + video + youtube_url trong một form. Gửi lần lượt, mỗi món một dòng log.
                    const jobs = uploadMediaFiles.screenshots.map((f, i) => ({ file: f, label: `ảnh ${i + 1}` }));
                    if (uploadMediaFiles.video) jobs.push({ file: uploadMediaFiles.video, label: 'video' });
                    if (ytUrl) jobs.push({ youtube_url: ytUrl, label: 'link YouTube' });

                    const sendOne = (job) => new Promise((resolve) => {
                        const formData = new FormData();
                        formData.append('public_id', publicId);
                        formData.append('token', token);
                        if (job.file) formData.append('file', job.file);
                        if (job.youtube_url) formData.append('youtube_url', job.youtube_url);
                        const xhr = new XMLHttpRequest();
                        xhr.open('POST', `${MARKET_CLI}/upload-media`);
                        xhr.setRequestHeader('Authorization', `Bearer ${token}`);
                        xhr.upload.onprogress = (evt) => {
                            if (evt.lengthComputable) {
                                updateProgressLog(`Đang tải lên ${job.label}: ${Math.round((evt.loaded / evt.total) * 100)}%...`, "progress");
                            }
                        };
                        xhr.onload = () => {
                            let resData = null;
                            try { resData = JSON.parse(xhr.responseText); } catch (e) { /* trả lời không phải JSON */ }
                            if (xhr.status >= 200 && xhr.status < 300 && resData && resData.status === 'success') {
                                updateProgressLog(`Đã tải lên ${job.label}.`, "success");
                            } else {
                                updateProgressLog(`Không tải lên được ${job.label}: ` + ((resData && resData.message) || ('HTTP ' + xhr.status)), "warn");
                            }
                            resolve(resData);
                        };
                        xhr.onerror = () => {
                            updateProgressLog(`Lỗi mạng khi tải lên ${job.label}`, "warn");
                            resolve(null);
                        };
                        xhr.send(formData);
                    });

                    updateProgressLog("Đang bắt đầu tải lên media server...", "info");
                    for (const job of jobs) await sendOne(job);
                } catch(me) {
                    updateProgressLog("Lỗi tải lên media: " + me.message, "warn");
                    console.error('[Market] Media upload error:', me);
                }
            }
            // --------------------

            updateProgressLog("Đã hoàn thành toàn bộ tiến trình publish!", "success");

            if (data.auto_updated) {
                showToast(`✅ Version updated! "${payload.title}" v${payload.version} has been published.`, 'success');
            } else {
                showToast(isEdit ? 'Listing updated successfully!' : 'Item published to Market!', 'success');
            }
            
            // Wait slightly so they can see the gorgeous 100% success log
            setTimeout(() => {
                closeUploadModal();
                loadItems();
                loadCategories();
            }, 1000);
            
            // Clear media state
            uploadMediaFiles = { screenshots: [], video: null };
            const uvUrl = document.getElementById('uploadVideoUrl');
            if (uvUrl) uvUrl.value = '';
            renderUploadMediaPreviews();
        } else {
            let errMsg = isEdit ? 'Update failed' : 'Upload failed';
            if (typeof data.detail === 'string') errMsg = data.detail;
            else if (typeof data.detail === 'object' && data.detail?.msg) errMsg = data.detail.msg;
            else if (data.error) errMsg = data.error;
            else if (data.message) errMsg = data.message;
            
            updateProgressLog(`Thất bại: ${errMsg}`, "error");
            console.error('[Market] Submit error:', data);
            showToast(errMsg, 'error');
        }
    } catch (e) {
        updateProgressLog(`Lỗi kết nối mạng: ${e.message}`, "error");
        console.error('[Market] Submit network error:', e);
        showToast('Network error: ' + e.message, 'error');
    }

    btn.disabled = false;
    btn.innerHTML = editingPublicId ? '💾 Save Changes' : '📤 Publish to Market';
}

// ── Helpers ──
function showLoading() {
    document.getElementById('marketLoading').style.display = 'flex';
    document.getElementById('marketGrid').style.display = 'none';
    document.getElementById('marketEmpty').style.display = 'none';
    document.getElementById('marketPagination').style.display = 'none';
}

/**
 * Get the current app language (works in iframe context).
 */
function getAppLang() {
    return _marketLang || localStorage.getItem('tubecli_lang') || 'en';
}

/**
 * Load locale strings for a local extension (identified by its name slug).
 * Calls /api/v1/extensions/{name}/locale/{lang} with fallback.
 * Results are cached in window._extLocaleCache.
 * Returns flat key-value object (may be empty if no locales found).
 */
const _extLocaleCache = {};
async function loadExtLocale(extName) {
    if (!extName) return {};
    const lang = getAppLang();
    const cacheKey = `${extName}__${lang}`;
    if (_extLocaleCache[cacheKey] !== undefined) return _extLocaleCache[cacheKey];
    try {
        const res = await fetch(`/api/v1/extensions/${encodeURIComponent(extName)}/locale/${encodeURIComponent(lang)}`);
        if (res.ok) {
            const data = await res.json();
            _extLocaleCache[cacheKey] = data || {};
            return _extLocaleCache[cacheKey];
        }
    } catch(e) { /* ignore */ }
    _extLocaleCache[cacheKey] = {};
    return {};
}

/**
 * Get a translated string from extension locale, fallback to default value.
 */
function extT(locale, key, fallback) {
    return (locale && locale[key]) ? locale[key] : (fallback || '');
}

function setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
}

function capitalize(str) {
    if (!str) return '';
    return str.charAt(0).toUpperCase() + str.slice(1);
}

function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function formatCredits(amount) {
    return `${parseInt(amount).toLocaleString()} credits`;
}

function formatNumber(n) {
    if (n >= 1000) return (n / 1000).toFixed(1) + 'k';
    return String(n);
}

function formatDate(dateStr) {
    if (!dateStr) return '';
    const d = new Date(dateStr);
    return d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
}

function renderStars(rating) {
    let html = '';
    for (let i = 1; i <= 5; i++) {
        html += `<span class="star ${i <= rating ? '' : 'empty'}">★</span>`;
    }
    return html;
}

function updatePriceLabel() {
    const val = document.getElementById('priceRange').value;
    document.getElementById('priceLabel').textContent = parseInt(val).toLocaleString() + ' credits';
}

function getAuthToken() {
    return localStorage.getItem('user_token') || '';
}

function isLoggedIn() {
    return !!getAuthToken();
}

function getAuthUser() {
    if (!isLoggedIn()) return null;
    try {
        return JSON.parse(localStorage.getItem('market_user') || '{}');
    } catch(e) {
        return null;
    }
}

function showToast(message, type = 'success') {
    const toast = document.getElementById('marketToast');
    toast.textContent = message;
    toast.className = 'market-toast ' + type + ' show';
    setTimeout(() => {
        toast.classList.remove('show');
    }, 3000);
}

// ── Auth System ──

// Đăng nhập / đăng ký bằng tài khoản cloud.tubecreate.com qua Chợ (Worker) — PHP api.tubecreate.com đã bỏ.
let marketIsRegisterMode = false;
let pendingSellAction = false;
// Việc làm tiếp SAU khi đăng nhập xong (vd. cài một mẫu — mẫu cần tài khoản Chợ). Huỷ hộp đăng nhập = bỏ.
let pendingAfterLogin = null;

// Đăng nhập xong (SSO hay email) → làm tiếp việc đang chờ. Hai cờ phải đọc TRƯỚC closeLoginModal(), vì hàm
// đó xoá chúng — trước 14/10/2026 cả hai đường đều đóng hộp trước rồi mới xem cờ, nên «Bán» không bao giờ
// tự mở lại sau khi đăng nhập.
function resumeAfterLogin(resumeSell, resumeFn) {
    if (resumeSell) {
        setTimeout(() => openUploadModal(), 300);
    } else if (typeof resumeFn === 'function') {
        setTimeout(() => { try { resumeFn(); } catch (e) { console.error('[Market] resume after login', e); } }, 300);
    } else {
        setTimeout(() => { try { loadMarketItems(); } catch {} }, 300);
    }
}

function requireAuth(callback) {
    if (isLoggedIn()) {
        callback();
    } else {
        pendingSellAction = true;
        showLoginModal();
    }
}


// ── SSO với TubeCLI Cloud ────────────────────────────────────────────────────
// Chợ chạy trên domain của server này nên localStorage KHÔNG dùng chung với
// cloud.tubecreate.com. Thay vì bắt gõ lại email/mật khẩu: mở popup sang cloud (đã đăng nhập
// sẵn ở đó), cloud kiểm origin này có thuộc server của chính user rồi postMessage token về.
const CLOUD_ORIGIN = 'https://cloud.tubecreate.com';

function loginWithCloud() {
    const url = `${CLOUD_ORIGIN}/sso/market?origin=${encodeURIComponent(location.origin)}`;
    const w = window.open(url, 'tubecli-cloud-sso', 'width=460,height=560,menubar=no,toolbar=no');
    if (!w) { showToast(T('auth.sso_popup_blocked') || 'Your browser blocked the popup — allow it and try again.', 'error'); return; }
    const btn = document.getElementById('btnCloudSso');
    if (btn) { btn.disabled = true; btn.dataset.old = btn.innerHTML; btn.innerHTML = '⏳ ' + (T('auth.sso_waiting') || 'Waiting for the sign-in window…'); }
    // Người dùng đóng popup giữa chừng → mở khoá nút
    const iv = setInterval(() => {
        if (w.closed) {
            clearInterval(iv);
            if (btn && btn.disabled) { btn.disabled = false; btn.innerHTML = btn.dataset.old || btn.innerHTML; }
        }
    }, 700);
}

window.addEventListener('message', (e) => {
    if (e.origin !== CLOUD_ORIGIN) return;                       // chỉ tin cloud
    const d = e.data || {};
    if (d.type !== 'tubecli-market-sso' || !d.token) return;
    localStorage.setItem('user_token', d.token);
    localStorage.setItem('market_user', JSON.stringify(d.user || {}));
    const resumeSell = pendingSellAction, resumeFn = pendingAfterLogin;
    try { closeLoginModal(); } catch {}
    updateMarketAuthUI();
    try { loadStripeBalance(); } catch {}
    showToast((T('auth.sso_ok') || 'Signed in with your Cloud account') + (d.user && d.user.username ? ' (' + d.user.username + ')' : ''), 'success');
    resumeAfterLogin(resumeSell, resumeFn);
});

function showLoginModal() {
    const modal = document.getElementById('loginModal');
    if (!modal) return;
    modal.classList.add('active');

    // Reset fields
    document.getElementById('authEmail').value = '';
    document.getElementById('authPassword').value = '';
    const nameF = document.getElementById('authName');
    const userF = document.getElementById('authUsername');
    const confF = document.getElementById('authConfirmPassword');
    if (nameF) nameF.value = '';
    if (userF) userF.value = '';
    if (confF) confF.value = '';
    document.getElementById('authErrorMsg').style.display = 'none';

    // Reset to login mode
    if (marketIsRegisterMode) toggleMarketAuthMode(null, false);

    setTimeout(() => {
        const emailInput = document.getElementById('authEmail');
        if (emailInput) emailInput.focus();
    }, 100);
}

function closeLoginModal() {
    const modal = document.getElementById('loginModal');
    if (modal) modal.classList.remove('active');
    pendingSellAction = false;
    pendingAfterLogin = null;
}

function toggleMarketAuthMode(event, forceMode = null) {
    if (event) event.preventDefault();
    if (forceMode !== null) {
        marketIsRegisterMode = forceMode;
    } else {
        marketIsRegisterMode = !marketIsRegisterMode;
    }

    const title = document.getElementById('authTitle');
    const subtitle = document.getElementById('authSubtitle');
    const submitBtn = document.getElementById('authSubmitBtn');
    const regTop = document.getElementById('registerFieldsTop');
    const regBottom = document.getElementById('registerFieldsBottom');
    const toggleText = document.getElementById('authToggleText');
    const toggleLink = document.getElementById('authToggleLink');
    const errorBox = document.getElementById('authErrorMsg');

    errorBox.style.display = 'none';

    if (marketIsRegisterMode) {
        title.textContent = '📝 Tạo tài khoản';
        subtitle.textContent = 'Đăng ký để bán trên Extension Market';
        submitBtn.textContent = '🚀 Đăng ký';
        if (regTop) regTop.style.display = 'block';
        if (regBottom) regBottom.style.display = 'block';
        toggleText.textContent = 'Đã có tài khoản?';
        toggleLink.textContent = 'Đăng nhập';
    } else {
        title.textContent = '🔐 Đăng nhập';
        subtitle.textContent = 'Đăng nhập để bán trên Market';
        submitBtn.textContent = '🔑 Đăng nhập';
        if (regTop) regTop.style.display = 'none';
        if (regBottom) regBottom.style.display = 'none';
        toggleText.textContent = 'Chưa có tài khoản?';
        toggleLink.textContent = 'Đăng ký';
    }
}

async function handleMarketAuth() {
    const email = document.getElementById('authEmail').value.trim();
    const password = document.getElementById('authPassword').value;
    const errorBox = document.getElementById('authErrorMsg');
    const btn = document.getElementById('authSubmitBtn');

    let name = '', username = '';

    if (!email || !password) {
        errorBox.textContent = 'Vui lòng nhập email và mật khẩu';
        errorBox.style.display = 'block';
        return;
    }

    if (marketIsRegisterMode) {
        name = document.getElementById('authName').value.trim();
        username = document.getElementById('authUsername').value.trim();
        const confirmPassword = document.getElementById('authConfirmPassword').value;

        if (!name || !username) {
            errorBox.textContent = 'Vui lòng nhập đầy đủ Tên và Username';
            errorBox.style.display = 'block';
            return;
        }
        if (password !== confirmPassword) {
            errorBox.textContent = 'Mật khẩu xác nhận không khớp';
            errorBox.style.display = 'block';
            return;
        }
    }

    errorBox.style.display = 'none';
    btn.textContent = marketIsRegisterMode ? '⏳ Đang đăng ký...' : '⏳ Đang đăng nhập...';
    btn.disabled = true;

    try {
        let apiUrl = `${MARKET_CLI}/login`;
        let payload = { email, password };

        if (marketIsRegisterMode) {
            apiUrl = `${MARKET_CLI}/register`;
            payload = { name, username, email, password, auto_verify: true };
        }

        const response = await fetch(apiUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });

        const data = await response.json();

        if (response.ok && (data.token || data.status === 'success' || data.success)) {
            // Save token
            if (data.token) {
                localStorage.setItem('user_token', data.token);
            }

            // Save user info
            const userObj = {
                name: data.name || name || '',
                username: data.username || username || '',
                email: email,
            };
            if (data.user) Object.assign(userObj, data.user);
            localStorage.setItem('market_user', JSON.stringify(userObj));

            const resumeSell = pendingSellAction, resumeFn = pendingAfterLogin;   // đọc TRƯỚC khi đóng hộp
            closeLoginModal();
            updateMarketAuthUI();
            loadStripeBalance();  // Load credit balance + show TopUp badge immediately
            showToast(marketIsRegisterMode ? 'Đăng ký thành công!' : 'Đăng nhập thành công!', 'success');
            resumeAfterLogin(resumeSell, resumeFn);

        } else if (response.ok && (data.success || data.status === 'success') && !data.token) {
            // Registered but no token → auto-login
            showToast('Tạo tài khoản thành công! Đang đăng nhập...', 'success');
            marketIsRegisterMode = false;
            handleMarketAuth();
        } else {
            throw new Error(data.message || data.error || (marketIsRegisterMode ? 'Đăng ký thất bại' : 'Email hoặc mật khẩu không đúng'));
        }
    } catch (err) {
        errorBox.textContent = err.message;
        errorBox.style.display = 'block';
    } finally {
        btn.textContent = marketIsRegisterMode ? '🚀 Đăng ký' : '🔑 Đăng nhập';
        btn.disabled = false;
    }
}

function updateMarketAuthUI() {
    const userInfo = document.getElementById('marketUserInfo');
    const userName = document.getElementById('marketUserName');
    const myListingsBtn = document.getElementById('btnMyListings');

    if (isLoggedIn()) {
        const user = JSON.parse(localStorage.getItem('market_user') || '{}');
        const displayName = user.name || user.username || user.email || 'User';
        if (userInfo) {
            userInfo.style.display = 'flex';
            userName.textContent = '👤 ' + displayName;
        }
        if (myListingsBtn) myListingsBtn.style.display = '';
        const lo = document.getElementById('btnLogout');
        if (lo) lo.style.display = '';
    } else {
        if (userInfo) userInfo.style.display = 'none';
        if (myListingsBtn) myListingsBtn.style.display = 'none';
        const lo = document.getElementById('btnLogout');
        if (lo) lo.style.display = 'none';
    }
}

function logoutMarket() {
    localStorage.removeItem('user_token');
    localStorage.removeItem('market_user');
    updateMarketAuthUI();
    showToast('Đã đăng xuất', 'success');
    setTimeout(() => location.reload(), 500);
}

// ── My Listings Management ──

function openMyListingsModal() {
    document.getElementById('myListingsModal').classList.add('active');
    loadMyListings();
}

function closeMyListingsModal() {
    document.getElementById('myListingsModal').classList.remove('active');
}

function normalizeString(str) {
    if (!str) return '';
    return str.toLowerCase().replace(/[^a-z0-9]/g, '');
}

async function loadMyListings() {
    const container = document.getElementById('myListingsContent');
    container.innerHTML = '<div class="market-loading" style="padding:40px 0;"><div class="market-spinner"></div><span style="color:var(--text-muted)">Loading your listings...</span></div>';

    try {
        const token = getAuthToken();
        // Fetch seller listings and local extensions in parallel for comparison
        const [res, localRes] = await Promise.all([
            fetch(`${API}/my-items`, {
                headers: token ? { 'Authorization': `Bearer ${token}` } : {},
            }),
            fetch(`/api/v1/extensions`).catch(() => null)
        ]);

        const data = await res.json();
        
        let localExtensions = [];
        if (localRes && localRes.ok) {
            const localData = await localRes.json();
            localExtensions = localData.extensions || localData || [];
        }

        if (data.status === 'success' && data.data && data.data.length > 0) {
            renderMyListings(data.data, localExtensions);
        } else if (data.data && data.data.length === 0) {
            container.innerHTML = `
                <div style="text-align:center;padding:40px 0;color:var(--text-muted);">
                    <div style="font-size:2.5rem;margin-bottom:12px;">📦</div>
                    <h3 style="font-size:1.1rem;margin-bottom:6px;">No listings yet</h3>
                    <p style="font-size:0.85rem;">Sell your extensions, skills, and nodes to the community!</p>
                </div>
            `;
        } else {
            container.innerHTML = '<p style="color:var(--red);text-align:center;padding:20px;">Failed to load listings</p>';
        }
    } catch (e) {
        console.error('[Market] My listings error:', e);
        container.innerHTML = '<p style="color:var(--red);text-align:center;padding:20px;">Network error</p>';
    }
}

function renderMyListings(items, localExtensions = []) {
    const container = document.getElementById('myListingsContent');
    const categoryIcons = { extension: '🧩', node: '🔗', skill: '⚡', model3d: '🎨' };

    container.innerHTML = items.map(item => {
        const icon = categoryIcons[item.category] || '📦';
        const price = parseFloat(item.price || 0);
        const isFree = price <= 0;

        let hasNewerLocalVersion = false;
        let localExtName = '';
        let localExtVersion = '';

        if (item.category === 'extension' && localExtensions.length > 0) {
            const matchLe = localExtensions.find(le => {
                const normLeName = normalizeString(le.name);
                const normLeDisplay = normalizeString(le.display_name);
                const normItemTitle = normalizeString(item.title);
                return normLeName === normItemTitle || normLeDisplay === normItemTitle;
            });
            if (matchLe) {
                localExtName = matchLe.name;
                localExtVersion = matchLe.version;
                try {
                    if (cmpVersions(matchLe.version, item.version) > 0) {
                        hasNewerLocalVersion = true;
                    }
                } catch(e) {}
            }
        }

        const updateBadgeHtml = hasNewerLocalVersion 
            ? `<span class="update-badge" title="Local version v${localExtVersion} is newer than Market v${item.version}">✨ Local: v${localExtVersion} (Newer)</span>`
            : '';

        const pushButtonHtml = hasNewerLocalVersion 
            ? `<button class="btn-push-update" data-action="push-update" data-id="${item.public_id}" data-local-name="${localExtName}" data-local-ver="${localExtVersion}" title="Đẩy bản cập nhật v${localExtVersion} lên Market">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                    <polyline points="17 8 12 3 7 8"></polyline>
                    <line x1="12" y1="3" x2="12" y2="15"></line>
                </svg> Update to Market
               </button>`
            : '';

        return `
            <div class="my-listing-item ${hasNewerLocalVersion ? 'has-update-available' : ''}" id="myListing_${item.public_id}">
                <div class="my-listing-icon">${icon}</div>
                <div class="my-listing-info">
                    <div class="my-listing-title">
                        ${escapeHtml(item.title)}
                        ${updateBadgeHtml}
                    </div>
                    <div class="my-listing-meta">
                        <span class="my-listing-category ${item.category}">${escapeHtml(item.category)}</span>
                        <span>·</span>
                        <span>v${escapeHtml(item.version || '1.0.0')}</span>
                        <span>·</span>
                        <span>${isFree ? '🆓 Free' : '💰 ' + formatCredits(price)}</span>
                        <span>·</span>
                        <span>⬇️ ${item.downloads || 0}</span>
                        <span>·</span>
                        <span>⭐ ${parseFloat(item.rating_avg || 0).toFixed(1)}</span>
                    </div>
                </div>
                <div class="my-listing-actions">
                    ${pushButtonHtml}
                    <button class="btn-edit-listing" data-action="edit" data-id="${item.public_id}" title="Edit Info">
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>
                    </button>
                    <button class="btn-view-listing" data-action="view" data-id="${item.public_id}" title="View">
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0"></path><circle cx="12" cy="12" r="3"></circle></svg>
                    </button>
                    <button class="btn-delete-listing" data-action="delete" data-id="${item.public_id}" data-title="${escapeHtml(item.title)}" title="Delete">
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"></path><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"></path><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"></path><line x1="10" y1="11" x2="10" y2="17"></line><line x1="14" y1="11" x2="14" y2="17"></line></svg>
                    </button>
                </div>
            </div>
        `;
    }).join('');

    // Event delegation for listings actions
    container.onclick = function(e) {
        const btn = e.target.closest('[data-action]');
        if (!btn) return;
        const action = btn.getAttribute('data-action');
        const id = btn.getAttribute('data-id');
        if (action === 'view') {
            closeMyListingsModal();
            setTimeout(() => openDetailModal(id), 200);
        } else if (action === 'edit') {
            editListing(id);
        } else if (action === 'delete') {
            const title = btn.getAttribute('data-title');
            confirmDeleteListing(id, title);
        } else if (action === 'push-update') {
            const localName = btn.getAttribute('data-local-name');
            const localVer = btn.getAttribute('data-local-ver');
            pushUpdateToListing(id, localName, localVer);
        }
    };
}

async function pushUpdateToListing(publicId, localName, localVer) {
    const btn = document.querySelector(`.btn-push-update[data-id="${publicId}"]`);
    const listingItem = document.getElementById('myListing_' + publicId);
    if (!btn || !listingItem) return;

    const confirmed = await customConfirm(
        'Đẩy bản cập nhật lên Market',
        `Bạn có chắc muốn đẩy bản cập nhật <b>v${localVer}</b> của extension <b>"${localName}"</b> lên Market?<br>Source files trên máy của bạn sẽ được đóng gói và cập nhật trực tiếp.`,
        'Xác nhận cập nhật',
        'Hủy',
        '#d97706 linear-gradient(135deg, #f59e0b, #d97706)',
        '🔄'
    );
    if (!confirmed) return;

    // Create/get a terminal log container for this listing card
    let logContainer = listingItem.querySelector('.push-update-progress-log');
    if (!logContainer) {
        logContainer = document.createElement('div');
        logContainer.className = 'push-update-progress-log';
        logContainer.style.marginTop = '12px';
        logContainer.style.background = '#07070a';
        logContainer.style.border = '1px solid #1a1a24';
        logContainer.style.borderRadius = '8px';
        logContainer.style.padding = '10px';
        logContainer.style.fontFamily = "'Courier New', Courier, monospace";
        logContainer.style.fontSize = '0.78rem';
        logContainer.style.color = '#8cd8f7';
        logContainer.style.maxHeight = '120px';
        logContainer.style.overflowY = 'auto';
        logContainer.style.width = '100%';
        logContainer.style.boxShadow = 'inset 0 2px 6px rgba(0,0,0,0.8)';
        logContainer.style.lineHeight = '1.4';
        logContainer.style.pointerEvents = 'auto'; // allow scroll
        listingItem.appendChild(logContainer);
    }
    logContainer.innerHTML = '';
    logContainer.style.display = 'block';

    // Show loading state
    const originalContent = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = `<div class="market-spinner" style="width:14px;height:14px;border-width:2px;margin:0;display:inline-block;vertical-align:middle;"></div> Đang đẩy...`;
    listingItem.style.pointerEvents = 'none';
    listingItem.style.opacity = '0.9'; // keep it readable but indicate work

    updateProgressLog("Bắt đầu tiến trình cập nhật nhanh cho extension...", "info", logContainer);

    try {
        const token = getAuthToken();

        // 1. Fetch current listing details
        updateProgressLog("Đang tải thông tin listing hiện tại từ Market...", "info", logContainer);
        const detailRes = await fetch(`${API}/items/${publicId}`);
        const detailData = await detailRes.json();
        if (detailData.status !== 'success' || !detailData.item) {
            throw new Error('Không thể tải thông tin listing hiện tại từ Market');
        }
        const item = detailData.item;
        updateProgressLog("Đã tải thông tin listing hiện tại thành công.", "success", logContainer);

        // 2. Fetch packaged extension source files
        updateProgressLog("Đang đóng gói và nén source files từ máy...", "info", logContainer);
        const packageRes = await fetch(`/api/v1/extensions/${encodeURIComponent(localName)}/package`);
        const pkg = await packageRes.json();
        if (pkg.status !== 'success') {
            throw new Error('Không thể đóng gói source files của extension từ máy.');
        }
        updateProgressLog(`Đã đóng gói thành công ${pkg.files?.length || 0} files.`, "success", logContainer);

        // 3. Merge files & manifest into item_data and sync
        updateProgressLog("Đồng bộ hóa metadata và manifest tubecli-extension.json...", "info", logContainer);
        let itemDataObj = {};
        try {
            itemDataObj = typeof item.item_data === 'string' ? JSON.parse(item.item_data) : (item.item_data || {});
        } catch(e) {}

        itemDataObj.manifest = pkg.manifest || {};
        itemDataObj.files = pkg.files || [];
        if (pkg.manifest && pkg.manifest.dependencies) {
            itemDataObj.dependencies = pkg.manifest.dependencies;
        }

        // Build metadata object for synchronization
        const metadata = {
            displayName: pkg.manifest.display_name || item.title,
            version: localVer,
            description: pkg.manifest.description || item.description || '',
            dependencies: pkg.manifest.dependencies || [],
            gitUrl: pkg.manifest.git_url || itemDataObj.git_url || item.git_url || '',
            authorName: pkg.manifest.author_info?.name || itemDataObj.author_info?.name || '',
            authorContact: pkg.manifest.author_info?.contact || itemDataObj.author_info?.contact || '',
            authorDonate: pkg.manifest.author_info?.donate_qr || itemDataObj.author_info?.donate_qr || ''
        };

        // Sync the package manifest inside itemDataObj
        itemDataObj = syncPackageManifest(itemDataObj, metadata, 'extension');
        updateProgressLog("Đã đồng bộ hoá manifest tubecli-extension.json thành công.", "success", logContainer);

        // 4. Construct payload
        const payload = {
            title: metadata.displayName || item.title,
            category: 'extension',
            price: parseFloat(item.price) || 0,
            visibility: item.visibility || 'PUBLIC',
            version: localVer,
            thumbnail_url: item.thumbnail_url || item.thumbnail || '',
            tags: item.tags || [],
            description: metadata.description || item.description || '',
            item_data: JSON.stringify(itemDataObj),
            git_url: metadata.gitUrl || item.git_url || ''
        };

        // 5. Submit PUT
        updateProgressLog("Đang đẩy gói dữ liệu mới lên Market API...", "info", logContainer);
        const res = await fetch(`${API}/items/${publicId}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
                ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
            },
            body: JSON.stringify(payload),
        });
        const data = await res.json();

        if (res.ok && (data.status === 'success' || data.public_id)) {
            updateProgressLog(`🚀 Đã cập nhật "${payload.title}" lên v${localVer} thành công!`, 'success', logContainer);
            showToast(`🚀 Đã cập nhật "${payload.title}" lên v${localVer} thành công!`, 'success');
            
            // Allow 1.2s to review the success console logs before re-render
            setTimeout(async () => {
                await loadMyListings();
                loadItems();
            }, 1200);
        } else {
            const errMsg = data.detail || data.message || 'Cập nhật thất bại';
            throw new Error(errMsg);
        }
    } catch (err) {
        updateProgressLog(`Thất bại: ${err.message}`, "error", logContainer);
        console.error('[Market] Push update error:', err);
        showToast(err.message, 'error');
        btn.disabled = false;
        btn.innerHTML = originalContent;
        listingItem.style.pointerEvents = '';
        listingItem.style.opacity = '1';
    }
}

async function editListing(publicId) {
    closeMyListingsModal();
    editingPublicId = publicId; // ← Mark as edit mode
    
    // Use uploadModal but jump to step 2
    const modal = document.getElementById('uploadModal');
    if (!modal) return;
    modal.classList.add('active');
    
    // Update submit button to show "Save Changes"
    const submitBtn = document.getElementById('uploadSubmitBtn');
    if (submitBtn) submitBtn.innerHTML = '💾 Save Changes';

    // Jump straight to step 2 bypassing local selection
    const step1 = document.getElementById('uploadStep1');
    const step2 = document.getElementById('uploadStep2');
    const steps = document.querySelectorAll('#uploadSteps .upload-step');
    if(step1) step1.style.display = 'none';
    if(step2) step2.style.display = 'block';
    if(steps.length > 1) {
        steps[0].className = 'upload-step done';
        steps[1].className = 'upload-step active';
    }

    // Set a loading preview
    document.getElementById('selectedItemPreview').innerHTML = '<div class="market-spinner" style="margin:20px auto;"></div>';

    try {
        const res = await fetch(`${API}/items/${publicId}`);
        const data = await res.json();
        
        if (data.status === 'success' && data.item) {
            const item = data.item;
            // Setup preview visually
            const categoryIcons = { extension: '🧩', node: '🔗', skill: '⚡', model3d: '🎨' };
            const icon = categoryIcons[item.category] || '📦';
            document.getElementById('selectedItemPreview').innerHTML = `
                <span class="preview-icon">${icon}</span>
                <div class="preview-info">
                    <div class="preview-name">${escapeHtml(item.title)}</div>
                    <div class="preview-type">${escapeHtml(item.category)}</div>
                    <div style="font-size:0.75rem;color:var(--orange);margin-top:5px;font-weight:bold;">
                        ✏️ Editing Market Listing
                    </div>
                </div>
            `;

            // Prefill standard form
            uploadState.selectedItem = null; // We are not uploading a local extension
            const category = item.category || 'extension';
            document.getElementById('uploadCategory').value = category;
            document.getElementById('uploadDisplayName').value = item.title;
            document.getElementById('uploadTitle').value = item.title;
            document.getElementById('uploadPrice').value = item.price || 0;
            document.getElementById('uploadVisibility').value = item.visibility || 'PUBLIC';
            document.getElementById('uploadVersion').value = item.version || '1.0.0';
            const uploadBtn = document.getElementById('uploadAvatar');
            if (uploadBtn) uploadBtn.value = item.thumbnail_url || item.thumbnail || '';
            document.getElementById('uploadTags').value = (item.tags || []).join(', ');
            document.getElementById('uploadDesc').value = item.description || '';
            
            // Set underlying data so if they just press Save, it uploads the old JSON unmodified in its core
            document.getElementById('uploadData').value = typeof item.item_data === 'string' ? item.item_data : JSON.stringify(item.item_data);

            // Toggle dependencies group visibility
            const depsGroup = document.getElementById('uploadDepsGroup');
            if (depsGroup) {
                depsGroup.style.display = (category === 'extension') ? 'block' : 'none';
            }

            // Depopulate specific meta fields for UI rendering
            try {
                const parsed = typeof item.item_data === 'string' ? JSON.parse(item.item_data) : item.item_data;
                
                // Prefill dependencies if category is extension
                if (category === 'extension') {
                    const depsInput = document.getElementById('uploadDeps');
                    if (depsInput) {
                        const deps = parsed.dependencies || parsed.manifest?.dependencies || [];
                        depsInput.value = Array.isArray(deps) ? deps.join(', ') : '';
                    }
                } else {
                    const depsInput = document.getElementById('uploadDeps');
                    if (depsInput) depsInput.value = '';
                }

                const gitUrlField = document.getElementById('uploadGitUrl');
                if(gitUrlField) gitUrlField.value = parsed.git_url || parsed.manifest?.git_url || item.git_url || '';

                const aName = document.getElementById('uploadAuthorName');
                const aContact = document.getElementById('uploadAuthorContact');
                const aDonate = document.getElementById('uploadAuthorDonate');
                
                const authorInfo = parsed.author_info || parsed.manifest?.author_info;
                if (authorInfo) {
                    if(aName) aName.value = authorInfo.name || '';
                    if(aContact) aContact.value = authorInfo.contact || '';
                    if(aDonate) aDonate.value = authorInfo.donate_qr || '';
                } else {
                    if(aName) aName.value = '';
                    if(aContact) aContact.value = '';
                    if(aDonate) aDonate.value = '';
                }
            } catch(e) {
                console.error('[Market] Error depopulating edit listing fields:', e);
            }
            
        } else {
            showToast('Item not found', 'error');
            closeUploadModal();
        }
    } catch(e) {
        showToast('Network error while loading item', 'error');
        closeUploadModal();
    }
}
// ── Custom Confirm Dialog ──
function customConfirm(title, message, okText = 'Tiếp tục', cancelText = 'Hủy', okBg = '', icon = '⚠️') {
    return new Promise((resolve) => {
        const modal = document.getElementById('confirmModal');
        document.getElementById('confirmTitle').innerHTML = title;
        document.getElementById('confirmMessage').innerHTML = message;
        
        // Dynamic OK button text and styling
        const okBtn = document.getElementById('confirmOkBtn');
        if (okBtn) {
            okBtn.innerHTML = okText;
            if (okBg) {
                okBtn.style.background = okBg;
            } else {
                // Default fallback
                okBtn.style.background = '#dc2626 linear-gradient(135deg, #ef4444, #dc2626)';
            }
        }

        // Dynamic Cancel button text
        const cancelBtn = document.getElementById('confirmCancelBtn');
        if (cancelBtn) {
            cancelBtn.innerHTML = cancelText;
        }

        // Dynamic Icon
        const iconDiv = document.getElementById('confirmIcon');
        if (iconDiv) {
            iconDiv.innerHTML = icon;
        }
        
        modal.classList.add('active');
        // Add subtle animation
        modal.querySelector('.market-modal').style.animation = 'marketModalFadeIn 0.2s cubic-bezier(0.16, 1, 0.3, 1)';

        const cleanup = () => {
            modal.classList.remove('active');
            if (okBtn) okBtn.onclick = null;
            if (cancelBtn) cancelBtn.onclick = null;
        };

        if (okBtn) okBtn.onclick = () => { cleanup(); resolve(true); };
        if (cancelBtn) cancelBtn.onclick = () => { cleanup(); resolve(false); };
    });
}

async function confirmDeleteListing(publicId, title) {
    const confirmed = await customConfirm(
        'Xoá Listing', 
        `Bạn có chắc muốn xoá <b>"${title}"</b> khỏi Market?<br>Hành động này không thể hoàn tác.`,
        'Xác nhận xóa',
        'Hủy',
        '#dc2626 linear-gradient(135deg, #ef4444, #dc2626)',
        '⚠️'
    );
    if (!confirmed) return;

    const el = document.getElementById('myListing_' + publicId);
    if (el) {
        el.style.opacity = '0.5';
        el.style.pointerEvents = 'none';
    }

    try {
        const token = getAuthToken();
        const res = await fetch(`${API}/items/${publicId}`, {
            method: 'DELETE',
            headers: token ? { 'Authorization': `Bearer ${token}` } : {},
        });
        const data = await res.json();

        if (data.status === 'success' || res.ok) {
            showToast(`"${title}" deleted from Market`, 'success');
            if (el) el.remove();
            // Check if no items left
            const container = document.getElementById('myListingsContent');
            if (!container.querySelector('.my-listing-item')) {
                container.innerHTML = `
                    <div style="text-align:center;padding:40px 0;color:var(--text-muted);">
                        <div style="font-size:2.5rem;margin-bottom:12px;">📦</div>
                        <h3 style="font-size:1.1rem;margin-bottom:6px;">No listings yet</h3>
                        <p style="font-size:0.85rem;">Sell your extensions, skills, and nodes to the community!</p>
                    </div>
                `;
            }
            // Refresh main grid
            loadItems();
            loadCategories();
        } else {
            showToast(data.message || data.detail || 'Delete failed', 'error');
            if (el) { el.style.opacity = '1'; el.style.pointerEvents = ''; }
        }
    } catch (e) {
        showToast('Network error', 'error');
        if (el) { el.style.opacity = '1'; el.style.pointerEvents = ''; }
    }
}

// Close modals on overlay click
document.getElementById('detailModal').addEventListener('click', (e) => {
    if (e.target === e.currentTarget) closeDetailModal();
});
document.getElementById('uploadModal').addEventListener('click', (e) => {
    if (e.target === e.currentTarget) closeUploadModal();
});
document.getElementById('loginModal').addEventListener('click', (e) => {
    if (e.target === e.currentTarget) closeLoginModal();
});
document.getElementById('myListingsModal').addEventListener('click', (e) => {
    if (e.target === e.currentTarget) closeMyListingsModal();
});
const gitInstallModal = document.getElementById('gitInstallModal');
if(gitInstallModal) {
    gitInstallModal.addEventListener('click', (e) => {
        if (e.target === e.currentTarget) closeGitInstallModal();
    });
}

// Close modals on Escape
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        closeDetailModal();
        closeUploadModal();
        closeLoginModal();
        closeMyListingsModal();
        closeGitInstallModal();
    }
});

// Submit on Enter in login modal
document.getElementById('authPassword').addEventListener('keypress', (e) => {
    if (e.key === 'Enter') handleMarketAuth();
});

// ── Git Install Modal ──
function openGitInstallModal() {
    document.getElementById('gitInstallUrl').value = '';
    document.getElementById('gitInstallModal').classList.add('active');
}

function closeGitInstallModal() {
    document.getElementById('gitInstallModal').classList.remove('active');
}

async function submitGitInstall() {
    const url = document.getElementById('gitInstallUrl').value.trim();
    if (!url) {
        showToast('Please enter a Git URL', 'error');
        return;
    }
    
    const btn = document.getElementById('gitInstallBtn');
    const originalText = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<div class="market-spinner" style="width:18px;height:18px;border-width:2px;margin:0;"></div> Installing...';
    
    clearTerm();
    termLog(`Initializing git install for ${url}...`, '#88aaff');

    const steps = [
        "Cloning Git repository (depth=1)...",
        "Validating tubecli-extension.json manifest...",
        "Resolving Python (PIP) dependencies if any...",
        "Resolving Node.js (NPM) dependencies if any...",
        "Loading extension module..."
    ];
    let stepIdx = 0;
    const termInterval = setInterval(() => {
        if (stepIdx < steps.length) {
            termLog(steps[stepIdx], '#aaaaaa');
            stepIdx++;
        }
    }, 1500);

    try {
        const res = await fetch(`${API}/items/install-git`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ git_url: url })
        });
        const data = await res.json();
        clearInterval(termInterval);
        
        if (data.status === 'success') {
            termLog('🎉 Installation Complete!', '#00ff00');
            if (data.message) termLog(data.message, '#00ff00');
            showToast(data.message || 'Installed successfully via Git!', 'success');

            // Refresh sidebar to show the new extension
            if (typeof loadDynamicExtensionsToSidebar === 'function') {
                try { await loadDynamicExtensionsToSidebar(); } catch(e) {}
            }

            setTimeout(() => {
                closeGitInstallModal();
                loadItems();
            }, 1500);
        } else {
            termLog('❌ Installation Failed: ' + (data.message || data.detail || 'Unknown error'), '#ff4444');
            showToast(data.message || data.detail || 'Git Install failed', 'error');
        }
    } catch (e) {
        clearInterval(termInterval);
        termLog('❌ Network Error: ' + e.message, '#ff4444');
        showToast('Network error', 'error');
    }
    
    btn.disabled = false;
    btn.innerHTML = originalText;
}

// Init auth UI on load
updateMarketAuthUI();

// ── Tab Switching Logic ──
function switchModalTab(tabId, btn) {
    const tabs = document.querySelectorAll('#detailModal .modal-tab');
    const contents = document.querySelectorAll('#detailModal .tab-content');
    
    tabs.forEach(t => t.classList.remove('active'));
    contents.forEach(c => c.classList.remove('active'));
    
    btn.classList.add('active');
    document.getElementById('tab-' + tabId).classList.add('active');
}

// ── Lightbox Logic ──
function openLightboxImage(url) {
    const lb = document.getElementById('mediaLightbox');
    const content = document.getElementById('lightboxContent');
    content.innerHTML = `<img src="${url}" class="lightbox-content" style="max-height:90vh;max-width:90vw;object-fit:contain;">`;
    lb.classList.add('active');
}

function openLightboxVideo(url) {
    const lb = document.getElementById('mediaLightbox');
    const content = document.getElementById('lightboxContent');
    if (url.includes('youtube.com')) {
        content.innerHTML = `<iframe src="${url}?autoplay=1" class="lightbox-content" style="width:80vw;height:45vw;max-height:80vh;border:none;" allow="autoplay; fullscreen"></iframe>`;
    } else {
        content.innerHTML = `<video src="${url}" class="lightbox-content" style="max-height:90vh;max-width:90vw;" controls autoplay></video>`;
    }
    lb.classList.add('active');
}

function closeLightbox(e) {
    if (e.target.id === 'mediaLightbox' || e.target.classList.contains('lightbox-close')) {
        const lb = document.getElementById('mediaLightbox');
        document.getElementById('lightboxContent').innerHTML = ''; // stop video
        lb.classList.remove('active');
    }
}

// ── Upload Media Handling in form ──
let uploadMediaFiles = { screenshots: [], video: null };

document.getElementById('uploadScreenshots')?.addEventListener('change', (e) => {
    const files = Array.from(e.target.files).slice(0, 5 - uploadMediaFiles.screenshots.length);
    uploadMediaFiles.screenshots.push(...files);
    renderUploadMediaPreviews();
});

document.getElementById('uploadVideo')?.addEventListener('change', (e) => {
    if (e.target.files.length) {
        uploadMediaFiles.video = e.target.files[0];
        document.getElementById('uploadVideoUrl').value = ''; // clear url if file selected
        renderUploadMediaPreviews();
    }
});

function removeUploadScreenshot(index) {
    uploadMediaFiles.screenshots.splice(index, 1);
    renderUploadMediaPreviews();
}

function removeUploadVideo() {
    uploadMediaFiles.video = null;
    document.getElementById('uploadVideo').value = '';
    renderUploadMediaPreviews();
}

function renderUploadMediaPreviews() {
    const sGrid = document.getElementById('screenshotsPreview');
    if (sGrid) {
        sGrid.innerHTML = uploadMediaFiles.screenshots.map((f, i) => `
            <div class="media-preview-item">
                <img src="${URL.createObjectURL(f)}">
                <button type="button" class="media-remove-btn" onclick="removeUploadScreenshot(${i})">✕</button>
            </div>
        `).join('');
    }
    
    const vGrid = document.getElementById('videoPreview');
    if (vGrid) {
        if (uploadMediaFiles.video) {
            vGrid.innerHTML = `
                <div class="media-preview-item">
                    <video src="${URL.createObjectURL(uploadMediaFiles.video)}#t=0.1" preload="metadata"></video>
                    <button type="button" class="media-remove-btn" onclick="removeUploadVideo()">✕</button>
                </div>
            `;
        } else {
            vGrid.innerHTML = '';
        }
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
//  STRIPE PAYMENT — TopUp Credits + Quick Pay
// ═══════════════════════════════════════════════════════════════════════════════

let _stripeBalance = null;
let _stripePublishableKey = null;
let _stripePackages = [];
let _paymentChoiceItemId = null;
let _paymentChoicePrice  = 0;
let _paymentChoiceTitle  = '';

// ── Universal dialog helpers (works with <dialog> and old overlay divs) ──
function _dlgShow(id) {
    const el = document.getElementById(id);
    if (!el) return;
    if (el.tagName === 'DIALOG') {
        try {
            if (!el.open) el.showModal();
        } catch(e) {
            // Fallback: set open attr manually
            el.setAttribute('open', '');
            el.style.cssText = 'display:flex!important;position:fixed;inset:0;z-index:9999;margin:auto;';
        }
    } else {
        el.classList.add('active');
    }
}
function _dlgClose(id) {
    const el = document.getElementById(id);
    if (!el) return;
    if (el.tagName === 'DIALOG') {
        if (el.open) el.close();
        el.removeAttribute('open');
        el.style.cssText = '';
    } else {
        el.classList.remove('active');
    }
}


// Ví giờ tính bằng USD (hợp nhất với cloud.tubecreate.com): "credits" = số USD vào ví.
// Gói giữ nguyên id/giá cũ; 1 credit cũ = $0.001 nên bonus gói cũ quy ra USD thật.
const STRIPE_PACKAGES_DEFAULT = [
    { id: 'starter',  name: 'Starter',  credits: 5,   bonus_usd: 0,  price_usd: 5.00,  badge: null,          color: '#6366f1' },
    { id: 'pro',      name: 'Pro',       credits: 15,  bonus_usd: 3,  price_usd: 12.00, badge: 'Popular',     color: '#8b5cf6' },
    { id: 'power',    name: 'Power',     credits: 50,  bonus_usd: 15, price_usd: 35.00, badge: 'Best Value',  color: '#a855f7' },
    { id: 'ultimate', name: 'Ultimate',  credits: 150, bonus_usd: 60, price_usd: 90.00, badge: 'Pro',         color: '#ec4899' },
];
const fmtUsd = (n) => '$' + Number(n || 0).toFixed(2);


// ── Init: Load Stripe config + balance on page load ──
async function initStripe() {
    try {
        const res = await fetch(`${API}/paypal/config`);
        const cfg = await res.json();
        _stripePublishableKey = cfg.client_id;
        _stripePackages       = cfg.packages || [];
    } catch (e) {
        console.warn('[PayPal] Failed to load config:', e);
    }
    await loadStripeBalance();
    renderCreditBadge();
    handleStripeReturn();
    handlePaypalRedirectReturn();
}

async function loadStripeBalance() {
    const token = getAuthToken();
    if (!token) { _stripeBalance = null; renderCreditBadge(); return; }
    try {
        const res = await fetch(`${API}/paypal/balance`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        const data = await res.json();
        _stripeBalance = data.balance ?? 0;
    } catch (e) {
        _stripeBalance = null;
    }
    renderCreditBadge();
}

function renderCreditBadge() {
    const el = document.getElementById('creditBalanceBadge');
    if (!el) return;
    if (_stripeBalance === null) { el.style.display = 'none'; return; }
    el.style.display = 'flex';
    el.innerHTML = `
        <span style="opacity:0.7;font-size:0.75rem;">💎</span>
        <span id="creditBalanceVal" style="font-weight:700;">${fmtUsd(_stripeBalance)}</span>
        <span style="opacity:0.6;font-size:0.75rem;">USD</span>
        <button onclick="openTopUpModal()" style="margin-left:6px;padding:2px 10px;font-size:0.72rem;background:#6366f1 linear-gradient(135deg,#6366f1,#8b5cf6);border:none;border-radius:8px;color:#fff;cursor:pointer;font-weight:600;transition:all 0.2s;" onmouseover="this.style.transform='translateY(-1px)'" onmouseout="this.style.transform=''">+ Nạp</button>
    `;
}

// ── Handle return from Stripe ──
function handleStripeReturn() {
    const params = new URLSearchParams(window.location.search);

    if (params.get('stripe_success')) {
        const credits = params.get('credits');
        const pkg     = params.get('package');
        showToast(`🎉 Nạp thành công ${credits || ''} credits (gói ${pkg || ''})!`, 'success');
        loadStripeBalance();
        history.replaceState({}, '', window.location.pathname);
    }
    if (params.get('stripe_quickpay_success')) {
        showToast('🎉 Thanh toán thành công! Bạn có thể cài đặt ngay.', 'success');
        const itemId = params.get('item_id');
        if (itemId) {
            const installBtn = document.getElementById('installBtn_' + itemId);
            if (installBtn) installBtn.style.display = '';
        }
        history.replaceState({}, '', window.location.pathname);
    }
    if (params.get('stripe_cancel')) {
        showToast('Thanh toán đã bị huỷ.', 'warn');
        history.replaceState({}, '', window.location.pathname);
    }
}

// ── Payment Choice Modal (native <dialog>) ──
function openPaymentChoiceModal(publicId, title, priceCredits) {
    _paymentChoiceItemId = publicId;
    _paymentChoicePrice  = priceCredits;
    _paymentChoiceTitle  = title;

    // Giá item và số dư đều là USD (ví hợp nhất với cloud) — không còn quy đổi credits.
    const priceUsd  = Number(priceCredits).toFixed(2);
    const balance   = _stripeBalance !== null ? Number(_stripeBalance) : null;
    const canAfford = balance !== null && balance + 1e-9 >= Number(priceCredits);

    const dlg = document.getElementById('paymentChoiceModal');
    if (!dlg) { buyItemWithCredits(publicId); return; }

    document.getElementById('paymentChoiceBody').innerHTML = `
        <div class="pmc-item-info">
            <div class="pmc-item-icon">🧩</div>
            <div>
                <div style="font-weight:700;font-size:1rem;color:var(--text)">${escapeHtml(title)}</div>
                <div style="font-size:0.8rem;color:var(--text-muted);margin-top:3px">
                    Giá: <strong style="color:var(--mk-indigo-strong)">$${priceUsd} USD</strong>
                </div>
            </div>
        </div>

        ${balance !== null ? `
        <div class="pmc-balance">
            <span>💎 Số dư của bạn:</span>
            <strong style="color:${canAfford ? 'var(--mk-green-text)' : 'var(--mk-red-text)'}">${fmtUsd(balance)}</strong>
            ${!canAfford ? `<span style="color:var(--mk-red-text);font-size:0.74rem;margin-left:6px;">⚠ Thiếu ${fmtUsd(Number(priceCredits) - balance)}</span>` : ''}
        </div>` : ''}

        <div class="pmc-options">
            <div class="pmc-option ${!canAfford ? 'pmc-disabled' : ''}" onclick="${canAfford ? `buyItemWithCredits('${publicId}')` : 'openTopUpModal()'}">
                <div class="pmc-opt-icon">💎</div>
                <div class="pmc-opt-body">
                    <div class="pmc-opt-title">${canAfford ? 'Trả bằng Credits' : 'Nạp thêm Credits'}</div>
                    <div class="pmc-opt-desc">${canAfford
                        ? `Dùng ${priceCredits} credits từ số dư — tức thì`
                        : `Thiếu ${priceCredits - (balance||0)} credits — bấm để nạp`}</div>
                </div>
                <span class="pmc-opt-badge ${canAfford ? 'badge-green' : 'badge-orange'}">${canAfford ? '✅ Đủ' : '+ Nạp'}</span>
            </div>

            <div class="pmc-option pmc-stripe" onclick="closePaymentChoiceModal(); openTopUpModal(); showPaypalButtons({ type: 'quickpay', itemId: '${publicId}', itemTitle: '${escapeHtml(title).replace(/'/g, "\\\'")}', priceCredits: ${priceCredits} })">
                <div class="pmc-opt-icon">💳</div>
                <div class="pmc-opt-body">
                    <div class="pmc-opt-title">Thanh toán PayPal / Thẻ quốc tế</div>
                    <div class="pmc-opt-desc">Trả trực tiếp $${priceUsd} USD qua PayPal hoặc Thẻ Visa/Mastercard bảo mật</div>
                </div>
                <span class="pmc-opt-badge badge-stripe" style="background:#003087;">⚡ PayPal / Card</span>
            </div>
        </div>
    `;

    _dlgShow('paymentChoiceModal');
    // Close on backdrop click
    const dlg2 = document.getElementById('paymentChoiceModal');
    if (dlg2) dlg2.onclick = (e) => { if (e.target === dlg2) _dlgClose('paymentChoiceModal'); };
}

function closePaymentChoiceModal() {
    _dlgClose('paymentChoiceModal');
    _paymentChoiceItemId = null;
}


// ── TopUp Modal (native <dialog>) ──
function openTopUpModal() {
    closePaymentChoiceModal();

    const packages = _stripePackages.length ? _stripePackages : STRIPE_PACKAGES_DEFAULT;
    if (!_stripePackages.length) {
        fetch(`${API}/paypal/config`)
            .then(r => r.json())
            .then(cfg => {
                if (cfg.packages && cfg.packages.length) {
                    _stripePackages = cfg.packages;
                    renderTopUpPackages();
                }
            })
            .catch(() => {});
    }
    renderTopUpPackages(packages);

    _dlgShow('topupModal');
    const dlg = document.getElementById('topupModal');
    if (dlg) {
        dlg.classList.remove('topup-compact');
        dlg.onclick = (e) => { if (e.target === dlg) _dlgClose('topupModal'); };
    }
}

function closeTopUpModal() {
    _dlgClose('topupModal');
}


function renderTopUpPackages(packages) {
    const grid = document.getElementById('topupPackageGrid');
    if (!grid) return;
    // Use provided packages, or _stripePackages, or fallback
    const pkgs = packages || (_stripePackages.length ? _stripePackages : STRIPE_PACKAGES_DEFAULT);
    grid.innerHTML = pkgs.map(pkg => {
        const isPopular = pkg.badge === 'Popular';
        const isBest    = pkg.badge === 'Best Value';
        return `
        <div class="topup-pkg ${isPopular ? 'topup-popular' : ''} ${isBest ? 'topup-best' : ''}" onclick="startTopUp('${pkg.id}', this)">
            ${pkg.badge ? `<div class="topup-badge">${pkg.badge}</div>` : ''}
            <div class="topup-credits-num">${fmtUsd(pkg.credits)}</div>
            <div class="topup-credits-lbl">vào ví</div>
            <div class="topup-price-tag">Trả $${Number(pkg.price_usd).toFixed(2)} <span style="font-size:0.7rem;opacity:0.6;">USD</span></div>
            <div class="topup-rate">${pkg.bonus_usd ? `🎁 Tặng thêm ${fmtUsd(pkg.bonus_usd)}` : 'Không bonus'}</div>
            <button class="topup-go-btn">Nạp ngay →</button>
        </div>`;
    }).join('');
}


// ── Dynamic PayPal Card Fields Loader ──
let paypalSdkPromise = null;
function getPayPalSDK(clientId) {
    if (paypalSdkPromise) return paypalSdkPromise;
    paypalSdkPromise = new Promise((resolve, reject) => {
        if (window.paypal && window.paypal.CardFields) {
            resolve(window.paypal);
            return;
        }
        const script = document.createElement('script');
        script.src = `https://www.paypal.com/sdk/js?client-id=${clientId}&components=card-fields&currency=USD`;
        script.onload = () => {
            if (window.paypal && window.paypal.CardFields) {
                resolve(window.paypal);
            } else {
                reject(new Error('PayPal Card Fields SDK load failed'));
            }
        };
        script.onerror = (err) => reject(err);
        document.head.appendChild(script);
    });
    return paypalSdkPromise;
}

let _paypalCardFieldsInstance = null;
let _paypalFieldsRendered = false;
let _activePaymentSession = null; // { type: 'topup', packageId: 'pro' } or { type: 'quickpay', itemId: '...', priceCredits: 15000, itemTitle: '...' }

async function initAndRenderPaypalFields() {
    if (_paypalFieldsRendered) return;
    
    const client_id = _stripePublishableKey; // PayPal Client ID fetched from /config
    if (!client_id) {
        showToast("Lỗi: Không lấy được cấu hình PayPal Client ID", "error");
        return;
    }
    
    try {
        const paypal = await getPayPalSDK(client_id);
        
        if (!paypal.CardFields) {
            showToast("PayPal Card Fields is not supported by current SDK version", "error");
            return;
        }
        
        _paypalCardFieldsInstance = paypal.CardFields({
            createOrder: async function() {
                const token = getAuthToken();
                if (!token) {
                    showToast("Vui lòng đăng nhập lại", "error");
                    throw new Error("Not authenticated");
                }
                
                document.getElementById('card-submit-btn').disabled = true;
                document.getElementById('card-submit-btn').innerHTML = '<div class="market-spinner" style="width:18px;height:18px;border-width:2px;margin:0;"></div> Đang tạo giao dịch...';
                document.getElementById('card-fields-error').style.display = 'none';

                let url, body;
                if (_activePaymentSession.type === 'topup') {
                    url = `${API}/paypal/topup-session`;
                    body = {
                        package_id: _activePaymentSession.packageId,
                        success_url: window.location.href.split('?')[0],
                        cancel_url: window.location.href.split('?')[0]
                    };
                } else {
                    url = `${API}/paypal/quickpay-session`;
                    body = {
                        item_public_id: _activePaymentSession.itemId,
                        item_title: _activePaymentSession.itemTitle,
                        item_price_credits: _activePaymentSession.priceCredits,
                        success_url: window.location.href.split('?')[0],
                        cancel_url: window.location.href.split('?')[0]
                    };
                }
                
                try {
                    const res = await fetch(url, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'Authorization': `Bearer ${token}`
                        },
                        body: JSON.stringify(body)
                    });
                    const data = await res.json();
                    if (!res.ok || !data.order_id) {
                        throw new Error(data.error || data.detail || "Không tạo được order ID từ PayPal");
                    }
                    return data.order_id;
                } catch (err) {
                    document.getElementById('card-submit-btn').disabled = false;
                    document.getElementById('card-submit-btn').innerHTML = '⚡ Thanh toán ngay';
                    document.getElementById('card-fields-error').style.display = 'block';
                    document.getElementById('card-fields-error').textContent = err.message;
                    throw err;
                }
            },
            onApprove: async function(data) {
                const { orderID } = data;
                const token = getAuthToken();
                
                document.getElementById('card-submit-btn').innerHTML = '<div class="market-spinner" style="width:18px;height:18px;border-width:2px;margin:0;"></div> Đang xác nhận thanh toán...';
                
                try {
                    const res = await fetch(`${API}/paypal/capture`, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'Authorization': `Bearer ${token}`
                        },
                        body: JSON.stringify({ order_id: orderID })
                    });
                    const result = await res.json();
                    
                    if (result.status === 'success') {
                        showToast("🎉 Thanh toán thành công!", "success");
                        loadStripeBalance(); // Refresh credits balance immediately
                        
                        if (_activePaymentSession.type === 'quickpay') {
                            const itemId = _activePaymentSession.itemId;
                            const installBtn = document.getElementById('installBtn_' + itemId);
                            if (installBtn) {
                                installBtn.style.display = '';
                                installBtn.click(); // trigger install immediately!
                            }
                        }
                        
                        setTimeout(() => {
                            closeTopUpModal();
                        }, 1000);
                    } else {
                        throw new Error(result.error || "Giao dịch không thành công");
                    }
                } catch (err) {
                    document.getElementById('card-submit-btn').disabled = false;
                    document.getElementById('card-submit-btn').innerHTML = '⚡ Thanh toán ngay';
                    document.getElementById('card-fields-error').style.display = 'block';
                    document.getElementById('card-fields-error').textContent = err.message;
                }
            },
            onError: function(err) {
                console.error("PayPal Card Fields Error:", err);
                document.getElementById('card-submit-btn').disabled = false;
                document.getElementById('card-submit-btn').innerHTML = '⚡ Thanh toán ngay';
                document.getElementById('card-fields-error').style.display = 'block';
                document.getElementById('card-fields-error').textContent = "Thao tác thất bại. Vui lòng kiểm tra lại thông tin thẻ hoặc thử lại.";
            }
        });
        
        // Render fields securely
        const cardNumberField = _paypalCardFieldsInstance.NumberField();
        await cardNumberField.render('#card-number-container');
        
        const cardExpiryField = _paypalCardFieldsInstance.ExpiryField();
        await cardExpiryField.render('#card-expiry-container');
        
        const cardCvvField = _paypalCardFieldsInstance.CVVField();
        await cardCvvField.render('#card-cvv-container');
        
        // Add click listener for submission
        document.getElementById('card-submit-btn').addEventListener('click', () => {
            _paypalCardFieldsInstance.submit().catch(err => {
                console.error("Card submit error:", err);
            });
        });
        
        _paypalFieldsRendered = true;
    } catch (e) {
        console.error("PayPal Fields Render Error:", e);
        showToast("Không thể tải cổng thanh toán bằng thẻ. Vui lòng thử lại.", "error");
    }
}

// ── Dynamic PayPal Smart Buttons SDK Loader ──
let paypalButtonsSdkPromise = null;
function getPayPalSDKButtons(clientId) {
    if (paypalButtonsSdkPromise) return paypalButtonsSdkPromise;
    paypalButtonsSdkPromise = new Promise((resolve, reject) => {
        if (window.paypal && window.paypal.Buttons) {
            resolve(window.paypal);
            return;
        }
        const script = document.createElement('script');
        script.src = `https://www.paypal.com/sdk/js?client-id=${clientId}&currency=USD&components=buttons`;
        script.onload = () => {
            if (window.paypal && window.paypal.Buttons) {
                resolve(window.paypal);
            } else {
                reject(new Error('PayPal Buttons SDK load failed'));
            }
        };
        script.onerror = (err) => reject(err);
        document.head.appendChild(script);
    });
    return paypalButtonsSdkPromise;
}

let _paypalButtonsInstance = null;

async function showPaypalButtons(sessionObj) {
    _activePaymentSession = sessionObj;
    
    // Hide package selection grid
    document.getElementById('topupPackageGrid').style.display = 'none';
    
    // Show buttons container
    const container = document.getElementById('paypal-button-container');
    container.style.display = 'block';
    
    // Clear previous error
    const errorEl = document.getElementById('paypal-buttons-error');
    errorEl.style.display = 'none';
    errorEl.textContent = '';
    
    // Render package summary
    const summaryEl = document.getElementById('selected-package-summary');
    if (sessionObj.type === 'topup') {
        const pkgMap = {
            'starter': 'Gói nạp: Starter (5,000 credits - $5.00 USD)',
            'pro': 'Gói nạp: Pro (15,000 credits - $12.00 USD)',
            'power': 'Gói nạp: Power (50,000 credits - $35.00 USD)',
            'ultimate': 'Gói nạp: Ultimate (150,000 credits - $90.00 USD)'
        };
        summaryEl.textContent = pkgMap[sessionObj.packageId] || `${sessionObj.packageId} package`;
    } else {
        const priceUsd = (sessionObj.priceCredits * 0.10).toFixed(2);
        summaryEl.textContent = `Mua đứt: ${sessionObj.itemTitle} ($${priceUsd} USD)`;
    }
    
    // Clear mount point to avoid duplicate renders
    const mountEl = document.getElementById('paypal-buttons-mount');
    mountEl.innerHTML = '';
    
    const client_id = _stripePublishableKey; // PayPal Client ID fetched from /config
    if (!client_id) {
        showToast("Lỗi: Không lấy được cấu hình PayPal Client ID", "error");
        return;
    }
    
    try {
        const paypal = await getPayPalSDKButtons(client_id);
        
        _paypalButtonsInstance = paypal.Buttons({
            style: {
                layout: 'vertical',
                color:  'gold',
                shape:  'rect',
                label:  'paypal'
            },
            createOrder: async function() {
                const token = getAuthToken();
                if (!token) {
                    showToast("Vui lòng đăng nhập lại", "error");
                    throw new Error("Not authenticated");
                }
                
                errorEl.style.display = 'none';
                
                let url, body;
                if (_activePaymentSession.type === 'topup') {
                    url = `${API}/paypal/topup-session`;
                    body = {
                        package_id: _activePaymentSession.packageId,
                        success_url: window.location.href.split('?')[0],
                        cancel_url: window.location.href.split('?')[0]
                    };
                } else {
                    url = `${API}/paypal/quickpay-session`;
                    body = {
                        item_public_id: _activePaymentSession.itemId,
                        item_title: _activePaymentSession.itemTitle,
                        item_price_credits: _activePaymentSession.priceCredits,
                        success_url: window.location.href.split('?')[0],
                        cancel_url: window.location.href.split('?')[0]
                    };
                }
                
                try {
                    const res = await fetch(url, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'Authorization': `Bearer ${token}`
                        },
                        body: JSON.stringify(body)
                    });
                    const data = await res.json();
                    if (!res.ok || !data.order_id) {
                        throw new Error(data.error || data.detail || "Không tạo được order ID từ PayPal");
                    }
                    return data.order_id;
                } catch (err) {
                    errorEl.style.display = 'block';
                    errorEl.textContent = err.message;
                    throw err;
                }
            },
            onApprove: async function(data) {
                const { orderID } = data;
                executePaypalCapture(orderID);
            },
            onError: function(err) {
                console.error("PayPal Buttons Error:", err);
                errorEl.style.display = 'block';
                errorEl.textContent = "Thao tác thanh toán thất bại hoặc đã bị huỷ.";
            }
        });
        
        await _paypalButtonsInstance.render('#paypal-buttons-mount');
    } catch (e) {
        console.error("PayPal buttons render failed:", e);
        mountEl.innerHTML = '<p style="color:var(--red);text-align:center;font-weight:600;padding:20px;">Lỗi: Không tải được thành phần thanh toán PayPal. Vui lòng thử lại.</p>';
    }
}

function hidePaypalButtons() {
    document.getElementById('paypal-button-container').style.display = 'none';
    // If we came from QuickPay, clicking back should close topupModal and open paymentChoiceModal again
    if (_activePaymentSession && _activePaymentSession.type === 'quickpay') {
        closeTopUpModal();
        openPaymentChoiceModal(_activePaymentSession.itemId, _activePaymentSession.itemTitle, _activePaymentSession.priceCredits);
    } else {
        document.getElementById('topup-method-choice-container').style.display = 'block';
    }
}

// ── Handle Auto-Capture for PayPal Express Checkout Return ──
async function handlePaypalRedirectReturn() {
    const params = new URLSearchParams(window.location.search);
    const token = params.get('token');
    const payerId = params.get('PayerID');
    
    if (token && payerId) {
        if (window.opener && !window.opener.closed) {
            try {
                window.opener.handlePaypalExpressSuccess(token);
                window.close();
                return;
            } catch (e) {}
        }
        await executePaypalCapture(token);
    }
}

async function executePaypalCapture(orderId) {
    // Show full screen loading overlay
    const overlay = document.createElement('div');
    overlay.id = 'paypal-loading-overlay';
    overlay.style.cssText = 'position:fixed;inset:0;background:var(--mk-overlay-bg);z-index:99999;display:flex;flex-direction:column;align-items:center;justify-content:center;color:var(--text);font-family:sans-serif;backdrop-filter:blur(10px);';
    overlay.innerHTML = `
        <div class="market-spinner" style="width:50px;height:50px;border-width:4px;margin-bottom:20px;"></div>
        <h3 style="margin:0;font-size:1.3rem;font-weight:800;">🔄 Đang xác thực giao dịch PayPal...</h3>
        <p style="margin:8px 0 0;color:var(--text-muted);font-size:0.9rem;">Hệ thống đang cộng Credits vào ví của bạn. Vui lòng không đóng tab này.</p>
    `;
    document.body.appendChild(overlay);
    
    const authToken = getAuthToken();
    try {
        const res = await fetch(`${API}/paypal/capture`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify({ order_id: orderId })
        });
        const result = await res.json();
        
        if (result.status === 'success') {
            showToast(`🎉 Nạp thành công +${fmtUsd(result.credits)} vào ví!`, "success");
            history.replaceState({}, '', window.location.pathname);
            await loadStripeBalance();
            closeTopUpModal();
        } else {
            showToast(result.error || "Giao dịch không thành công hoặc đã xử lý trước đó", "error");
            history.replaceState({}, '', window.location.pathname);
        }
    } catch (e) {
        showToast("Lỗi hệ thống khi capture giao dịch PayPal", "error");
        history.replaceState({}, '', window.location.pathname);
    } finally {
        overlay.remove();
    }
}

window.handlePaypalExpressSuccess = function(orderId) {
    executePaypalCapture(orderId);
};

let _selectedTopUpPackage = null;

async function startTopUp(packageId, cardEl) {
    const token = getAuthToken();
    if (!token) { showToast('Vui lòng đăng nhập', 'error'); return; }
    
    _selectedTopUpPackage = packageId;
    
    // Hide package selection grid
    document.getElementById('topupPackageGrid').style.display = 'none';
    
    // Set compact style when in payment steps
    const modal = document.getElementById('topupModal');
    if (modal) modal.classList.add('topup-compact');
    
    // Show payment choice container
    const choiceContainer = document.getElementById('topup-method-choice-container');
    choiceContainer.style.display = 'block';
    
    // Render package summary in choice modal
    const pkgMap = {
        'starter': 'Gói nạp: Starter (5,000 credits - $5.00 USD)',
        'pro': 'Gói nạp: Pro (15,000 credits - $12.00 USD)',
        'power': 'Gói nạp: Power (50,000 credits - $35.00 USD)',
        'ultimate': 'Gói nạp: Ultimate (150,000 credits - $90.00 USD)'
    };
    document.getElementById('choice-package-summary').textContent = pkgMap[packageId] || `${packageId} package`;
}

function cancelTopUpMethodSelection() {
    document.getElementById('topup-method-choice-container').style.display = 'none';
    document.getElementById('topupPackageGrid').style.display = 'grid';
    _selectedTopUpPackage = null;
    
    const modal = document.getElementById('topupModal');
    if (modal) modal.classList.remove('topup-compact');
}

function selectTopUpMethod(method) {
    document.getElementById('topup-method-choice-container').style.display = 'none';
    
    if (method === 'paypal') {
        showPaypalButtons({ type: 'topup', packageId: _selectedTopUpPackage });
    } else if (method === 'crypto') {
        showCryptoPayment(_selectedTopUpPackage);
    }
}

// ── Helper to dynamically update the dialog footer gateway branding ──
function updateTopUpFooter(gateway) {
    const footer = document.getElementById('topupModalFooter');
    if (!footer) return;
    if (gateway === 'crypto') {
        footer.innerHTML = `
            <span>🔒 Bảo mật bởi <b>NOWPayments</b></span>
            <span style="margin-left:8px;opacity:0.5;">· TLS 1.3 Encrypted</span>
        `;
    } else {
        footer.innerHTML = `
            <span>🔒 Bảo mật bởi</span>
            <svg width="48" height="20" viewBox="0 0 60 25" fill="none" xmlns="http://www.w3.org/2000/svg" style="margin-left:6px; vertical-align:middle;">
                <text x="0" y="18" font-size="18" font-family="Arial" font-weight="bold" fill="#003087">PayPal</text>
            </svg>
            <span style="margin-left:8px;opacity:0.5;">· TLS 1.3 Encrypted</span>
        `;
    }
}

// ── Crypto TopUp Flow ──
function showCryptoPayment(packageId) {
    const container = document.getElementById('crypto-payment-container');
    container.style.display = 'block';
    
    // Update footer to NOWPayments
    updateTopUpFooter('crypto');
    
    // Clear details mount
    document.getElementById('crypto-details-mount').style.display = 'none';
    document.getElementById('crypto-pay-btn').disabled = false;
    document.getElementById('crypto-pay-btn').style.display = 'flex';
    
    const pkgMap = {
        'starter': 'Gói nạp: Starter (5,000 credits - $5.00 USD)',
        'pro': 'Gói nạp: Pro (15,000 credits - $12.00 USD)',
        'power': 'Gói nạp: Power (50,000 credits - $35.00 USD)',
        'ultimate': 'Gói nạp: Ultimate (150,000 credits - $90.00 USD)'
    };
    document.getElementById('crypto-package-summary').textContent = pkgMap[packageId] || `${packageId} package`;
}

function hideCryptoPayment() {
    document.getElementById('crypto-payment-container').style.display = 'none';
    document.getElementById('crypto-details-mount').style.display = 'none';
    document.getElementById('crypto-pay-btn').style.display = 'flex';
    document.getElementById('crypto-pay-btn').disabled = false;
    document.getElementById('crypto-pay-btn').innerHTML = T('topup.crypto_pay_btn') || '⚡ Bấm để lấy mã QR thanh toán';
    document.getElementById('topup-method-choice-container').style.display = 'block';
    
    // Revert footer to PayPal
    updateTopUpFooter('paypal');
    
    if (window._cryptoTimerInterval) {
        clearInterval(window._cryptoTimerInterval);
        window._cryptoTimerInterval = null;
    }
}

function onCryptoCurrencyChange() {
    const mount = document.getElementById('crypto-details-mount');
    if (mount && mount.style.display === 'block') {
        startCryptoPaymentFlow();
    }
}

async function startCryptoPaymentFlow() {
    const payBtn = document.getElementById('crypto-pay-btn');
    payBtn.disabled = true;
    payBtn.innerHTML = '<span class="market-spinner" style="width:16px;height:16px;border-width:2px;margin:0;border-color:#fff transparent transparent transparent;"></span> ' + (T('topup.creating_wallet') || 'Đang tạo ví...');
    
    // If wallet details are already visible, show a premium loading indicator inside the mount
    const mount = document.getElementById('crypto-details-mount');
    if (mount && mount.style.display === 'block') {
        mount.innerHTML = `
            <div style="padding:40px 20px; text-align:center; background:var(--bg3, #1e1e2f); border:1px solid var(--border, #2e2e42); border-radius:12px; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:12px;">
                <span class="market-spinner" style="width:28px; height:28px; border-width:2.5px; border-color:var(--mk-violet-strong) transparent transparent transparent; margin:0;"></span>
                <span style="font-size:0.85rem; color:var(--text-muted, #8e8ea8); font-weight:600; letter-spacing:0.3px;">${T('topup.changing_network') || 'Đang đổi mạng lưới & tạo ví mới...'}</span>
            </div>
        `;
    }
    
    const currency = document.getElementById('crypto-currency-select').value;
    const user = getAuthUser();
    const username = user ? user.username : '';
    
    if (!username) {
        showToast(T('topup.login_first') || "Vui lòng đăng nhập lại", "error");
        payBtn.disabled = false;
        payBtn.innerHTML = T('topup.crypto_pay_btn') || '⚡ Bấm để lấy mã QR thanh toán';
        return;
    }
    
    // Chặn SỚM gói dưới mức tối thiểu crypto (NOWPayments theo ví payout, đo thật ~$19): báo rõ
    // và gợi ý gói đủ mức, thay vì tạo đơn rồi nhận lỗi.
    try {
        if (!window._cryptoCfg) {
            const cr = await fetch(`${API}/paypal/crypto-config`); window._cryptoCfg = await cr.json();
        }
        const cfgMin = Number(window._cryptoCfg?.min_usd || 0);
        const pkgs = _stripePackages.length ? _stripePackages : STRIPE_PACKAGES_DEFAULT;
        const pk = pkgs.find(p => p.id === _selectedTopUpPackage);
        if (cfgMin && pk && Number(pk.price_usd) < cfgMin) {
            const okPk = pkgs.filter(p => Number(p.price_usd) >= cfgMin).map(p => p.name).join(' / ');
            showToast(`Nạp crypto tối thiểu ${fmtUsd(cfgMin)} — gói ${pk.name} ($${pk.price_usd}) chưa đủ. Hãy chọn ${okPk || 'gói lớn hơn'} hoặc dùng PayPal/thẻ.`, 'warn');
            payBtn.disabled = false;
            payBtn.innerHTML = T('topup.crypto_pay_btn') || '⚡ Bấm để lấy mã QR thanh toán';
            return;
        }
    } catch (e) { /* không lấy được config thì để server quyết */ }

    try {
        // Bearer bắt buộc: Worker suy user từ token (bản cũ gửi username tự khai — giả được).
        const res = await fetch(`${API}/paypal/crypto-session`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${getAuthToken()}`
            },
            body: JSON.stringify({
                package_id: _selectedTopUpPackage,
                currency: currency
            })
        });
        
        const data = await res.json();
        if (!res.ok || !data.success) {
            throw new Error(data.error || data.detail || "Lỗi khởi tạo cổng thanh toán Crypto");
        }
        
        const mount = document.getElementById('crypto-details-mount');
        
        if (data.invoice_url) {
            // MODE 2: Invoice URL returned -> Embed the beautiful NOWPayments widget in an iframe directly inside our modal!
            mount.innerHTML = `
                <!-- Topbar status -->
                <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid var(--border); padding-bottom:12px; margin-bottom:16px;">
                    <span style="font-weight:800; color:var(--text); font-size:0.95rem; text-transform:uppercase; letter-spacing:0.5px; display:flex; align-items:center; gap:6px;">🪙 SEND DEPOSIT</span>
                    <a href="${data.invoice_url}" target="_blank" style="font-size:0.82rem; color:var(--mk-violet-text); font-weight:700; background:rgba(99,102,241,0.1); border:1px solid rgba(99,102,241,0.2); padding:4px 10px; border-radius:6px; text-decoration:none; display:inline-block; transition:all 0.2s;">
                        🔗 Mở trong tab mới ↗
                    </a>
                </div>
                <div style="width:100%; height:450px; background:#fff; border-radius:12px; overflow:hidden; border:1px solid var(--border); box-shadow:0 4px 20px var(--mk-k40); position:relative;">
                    <iframe src="${data.invoice_url}" style="width:100%; height:100%; border:none;" allow="clipboard-read; clipboard-write"></iframe>
                </div>
            `;
            mount.style.display = 'block';
            payBtn.style.display = 'none';
            showToast("Khởi tạo hóa đơn thanh toán Crypto thành công!", "success");
        } else {
            // MODE 1: Direct Payment returned -> Render the stunning custom dark-mode "SEND DEPOSIT" UI
            
            // Map pay_currency to dynamic full network name
            const currencyMap = {
                'usdttrc20': 'Tron Network (TRC20)',
                'usdtbsc': 'BNB Smart Chain (BEP20)',
                'usdterc20': 'Ethereum (ERC20)',
                'usdc': 'BNB Smart Chain (BEP20)',
                'bnb': 'BNB Smart Chain (BEP20)',
                'btc': 'Bitcoin Network',
                'eth': 'Ethereum Network'
            };
            const networkName = currencyMap[data.pay_currency] || 'Crypto Network';
            const displayCurrency = data.pay_currency ? data.pay_currency.toUpperCase().replace('TRC20', '').replace('BSC', '').replace('ERC20', '') : 'USDT';

            mount.innerHTML = `
                <!-- Topbar status -->
                <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid var(--border); padding-bottom:8px; margin-bottom:10px;">
                    <span style="font-weight:800; color:var(--text); font-size:0.85rem; text-transform:uppercase; letter-spacing:0.5px; display:flex; align-items:center; gap:6px;">🪙 SEND DEPOSIT</span>
                    <span id="crypto-timer" style="font-size:0.78rem; color:var(--mk-violet-strong); font-weight:700; background:rgba(167,139,250,0.1); padding:3px 6px; border-radius:6px; display:flex; align-items:center; gap:4px;">
                        ⏳ <span id="crypto-countdown-val">59:59</span>
                    </span>
                </div>

                <!-- Two-column grid -->
                <div style="display:grid; grid-template-columns: 1fr 1fr; gap:12px; text-align:left;">
                    
                    <!-- Left Column (QR & Wallet Details) -->
                    <div style="display:flex; flex-direction:column; align-items:center; border-right:1px solid var(--border); padding-right:12px;">
                        
                        <!-- Network selector lookalike -->
                        <div style="width:100%; padding:4px 8px; background:var(--bg2, #161622); border:1px solid var(--border, #2e2e42); border-radius:8px; color:var(--text); font-weight:700; font-size:0.78rem; text-align:center; margin-bottom:8px;">
                            ${networkName}
                        </div>

                        <!-- QR Code Frame -->
                        <div style="margin: 4px 0 6px 0; padding:6px; background:#fff; border-radius:12px; display:flex; justify-content:center; box-shadow: 0 4px 15px var(--mk-k30);">
                            <img id="crypto-qr-img" src="${data.qrCode}" style="width:115px; height:115px; display:block;" />
                        </div>

                        <!-- Network badge -->
                        <div style="margin-bottom:6px; text-align:center;">
                            <span style="font-size:0.65rem; color:var(--text-muted, #8e8ea8); font-weight:700; display:block; margin-bottom:2px; text-transform:uppercase; letter-spacing:0.5px;" data-i18n="topup.network_label">${T('topup.network_label') || 'NETWORK'}</span>
                            <span style="background:rgba(99,102,241,0.2); border:1px solid rgba(99,102,241,0.4); color:var(--mk-violet-text); font-size:0.68rem; font-weight:800; padding:2px 8px; border-radius:20px; text-transform:uppercase; display:inline-block; letter-spacing:0.5px;">
                                ${data.network ? data.network.replace(' (Tron)', '').replace(' (BNB Chain)', '').replace(' (Ethereum)', '') : 'USDT'}
                            </span>
                        </div>

                        <!-- Wallet Address input box with Copy -->
                        <div style="width:100%;">
                            <span style="font-size:0.65rem; color:var(--text-muted, #8e8ea8); font-weight:700; display:block; margin-bottom:2px; text-transform:uppercase; letter-spacing:0.5px;" data-i18n="topup.wallet_label">${T('topup.wallet_label') || 'WALLET ADDRESS'}</span>
                            <div style="display:flex; border:1px solid var(--border, #2e2e42); border-radius:8px; overflow:hidden; background:var(--bg2, #161622);">
                                <input id="crypto-pay-address" readonly value="${data.address || ''}" style="flex:1; padding:6px; background:transparent; border:none; color:var(--text); font-size:0.72rem; font-family:monospace; text-align:center; outline:none;" />
                                <button onclick="copyCryptoAddress()" style="background:var(--bg-hover); border:none; border-left:1px solid var(--border, #2e2e42); color:var(--mk-violet-text); padding:0 8px; cursor:pointer; font-weight:700; font-size:0.7rem; display:flex; align-items:center; justify-content:center; transition:all 0.2s;" onmouseover="this.style.background='rgba(99,102,241,0.1)'" onmouseout="this.style.background='var(--bg-hover)'">
                                    Copy
                                </button>
                            </div>
                        </div>

                    </div>

                    <!-- Right Column (Amount & Instructions) -->
                    <div style="display:flex; flex-direction:column; justify-content:space-between;">
                        
                        <!-- Amount Frame -->
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; padding:6px 10px; background:var(--bg2, #161622); border:1px solid var(--border, #2e2e42); border-radius:10px;">
                            <span style="font-size:0.75rem; font-weight:600; color:var(--text-muted, #8e8ea8);" data-i18n="topup.amount_label">${T('topup.amount_label') || 'Số tiền cần gửi:'}</span>
                            <div style="display:flex; align-items:center; gap:8px;">
                                <span id="crypto-pay-amount" style="font-size:1rem; font-weight:900; color:var(--mk-emerald-strong);">
                                    ${data.amount} <span style="font-size:0.8rem; font-weight:700; color:var(--text-muted);">${displayCurrency}</span>
                                </span>
                                <button onclick="copyCryptoAmount()" style="background:var(--bg-hover); border:1px solid var(--border, #2e2e42); border-radius:6px; color:var(--mk-violet-text); padding:2px 6px; cursor:pointer; font-size:0.65rem; font-weight:700; transition:all 0.2s;" onmouseover="this.style.background='rgba(99,102,241,0.1)'" onmouseout="this.style.background='var(--bg-hover)'">Copy</button>
                            </div>
                        </div>

                        <!-- Instructions Block -->
                        <div style="padding:8px; background:rgba(99,102,241,0.04); border:1px dashed rgba(99,102,241,0.2); border-radius:8px; margin-bottom:8px;">
                            <div style="font-weight:800; font-size:0.7rem; color:var(--mk-indigo-text); text-transform:uppercase; letter-spacing:0.5px; display:flex; align-items:center; gap:6px; margin-bottom:4px;" data-i18n="topup.instructions_title">
                                <span>📖</span> ${T('topup.instructions_title') || 'Crypto Transfer Instructions'}
                            </div>
                            <ul style="margin:0; padding:0; list-style:none; font-size:0.7rem; color:var(--text-muted, #8e8ea8); line-height:1.3; display:flex; flex-direction:column; gap:2px;">
                                <li><b style="color:var(--text);">${T('sell.step1') || 'Bước 1'}:</b> ${T('topup.step1')}</li>
                                <li><b style="color:var(--text);">${T('sell.step2') || 'Bước 2'}:</b> ${T('topup.step2')} <span style="color:var(--mk-violet-text);font-weight:700;">${data.network || 'TRC20'}</span></li>
                                <li><b style="color:var(--text);">Bước 3:</b> ${T('topup.step3')}</li>
                                <li><b style="color:var(--text);">Bước 4:</b> ${T('topup.step4')}</li>
                                <li><b style="color:var(--text);">Bước 5:</b> ${T('topup.step5')}</li>
                                <li><b style="color:var(--text);">Bước 6:</b> ${T('topup.step6')}</li>
                            </ul>
                        </div>

                        <!-- Transaction tracking badge -->
                        <div style="padding:6px; background:rgba(16,185,129,0.08); border:1px solid rgba(16,185,129,0.2); border-radius:8px;">
                            <p style="margin:0; font-size:0.7rem; color:var(--mk-emerald-text); font-weight:700; display:flex; align-items:center; justify-content:center; gap:6px;">
                                <span class="market-spinner" style="width:12px; height:12px; border-width:1.5px; border-color:var(--mk-emerald-text) transparent transparent transparent; margin:0;"></span>
                                <span id="crypto-track-text">${T('topup.tracking') || 'Hệ thống đang tự động theo dõi Blockchain...'}</span>
                            </p>
                        </div>

                    </div>

                </div>

                <!-- Footer Warnings -->
                <div style="margin-top:8px; padding:6px 10px; background:rgba(245,158,11,0.08); border:1px solid rgba(245,158,11,0.2); border-radius:6px; text-align:left;">
                    <p style="margin:0; font-size:0.65rem; color:var(--mk-amber-text); line-height:1.35; font-weight:500;">
                        ${T('topup.warning')}
                    </p>
                </div>
            `;
            mount.style.display = 'block';
            payBtn.style.display = 'none'; // hide payment creation button once created
            
            // Đếm ngược theo HẠN THẬT của đơn (expires_at từ NOWPayments); thiếu thì 60 phút.
            const expMs = data.expires_at ? Date.parse(data.expires_at) : 0;
            let timeLeft = expMs > Date.now() ? Math.floor((expMs - Date.now()) / 1000) : 60 * 60;
            if (window._cryptoTimerInterval) clearInterval(window._cryptoTimerInterval);
            if (window._cryptoPollInterval) clearInterval(window._cryptoPollInterval);

            window._cryptoTimerInterval = setInterval(() => {
                timeLeft--;
                if (timeLeft <= 0) {
                    clearInterval(window._cryptoTimerInterval);
                    const ex = document.getElementById('crypto-countdown-val');
                    if (ex) ex.textContent = 'EXPIRED';
                    return;
                }
                const mins = Math.floor(timeLeft / 60);
                const secs = timeLeft % 60;
                const displayEl = document.getElementById('crypto-countdown-val');
                if (displayEl) {
                    displayEl.textContent = `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
                }
            }, 1000);

            // Poll trạng thái mỗi 6s: Worker tự hỏi NOWPayments + cộng ví khi xong → người dùng
            // thấy "đã nhận" và số dư mới ngay, không phải reload. Bản cũ không poll, chữ
            // "đang theo dõi Blockchain" chỉ là spinner trang trí.
            const pid = data.payment_id;
            if (pid) {
                window._cryptoPollInterval = setInterval(async () => {
                    try {
                        const sr = await fetch(`${API}/paypal/crypto-status?payment_id=${encodeURIComponent(pid)}`, {
                            headers: { 'Authorization': `Bearer ${getAuthToken()}` }
                        });
                        const st = await sr.json();
                        if (!sr.ok) return;
                        const badge = document.getElementById('crypto-track-text');
                        if (st.done) {
                            clearInterval(window._cryptoPollInterval); clearInterval(window._cryptoTimerInterval);
                            if (badge) badge.textContent = '✅ ' + (T('topup.received') || 'Đã nhận tiền — ví đã được cộng!');
                            showToast(`🎉 ${T('topup.received') || 'Đã nhận tiền'} +${fmtUsd(st.credited_cents / 100)}`, 'success');
                            loadStripeBalance();
                        } else if (st.partially_paid) {
                            if (badge) badge.textContent = '⚠ ' + (T('topup.partial') || 'Nhận thiếu — đã cộng phần nhận được, gửi thêm phần còn lại');
                            loadStripeBalance();
                        } else if (st.failed) {
                            clearInterval(window._cryptoPollInterval);
                            if (badge) badge.textContent = '❌ ' + (T('topup.failed') || 'Đơn hết hạn hoặc thất bại — tạo đơn mới');
                        } else if (st.seen && badge) {
                            badge.textContent = '⏳ ' + (T('topup.confirming') || 'Đã thấy giao dịch — đang chờ tiền về ví…');
                        }
                    } catch (e) { /* rớt một nhịp thì thôi */ }
                }, 6000);
            }

            showToast(T('topup.crypto_success') || "Tạo yêu cầu thanh toán Crypto thành công! Vui lòng gửi tiền.", "success");
        }
        
    } catch (err) {
        showToast(err.message, "error");
        payBtn.disabled = false;
        payBtn.innerHTML = T('topup.crypto_pay_btn') || '⚡ Bấm để lấy mã QR thanh toán';
    }
}

function copyCryptoAddress() {
    const input = document.getElementById('crypto-pay-address');
    input.select();
    input.setSelectionRange(0, 99999);
    navigator.clipboard.writeText(input.value);
    showToast(T('topup.copied_address') || "Đã copy địa chỉ ví nhận!", "success");
}

function copyCryptoAmount() {
    const amountText = document.getElementById('crypto-pay-amount').textContent;
    // Extract numeric amount only (exclude currency part)
    const amountVal = parseFloat(amountText.trim());
    if (!isNaN(amountVal)) {
        navigator.clipboard.writeText(amountVal);
        showToast(T('topup.copied_amount') || "Đã copy số tiền thanh toán!", "success");
    }
}

function closeTopUpModal() {
    _dlgClose('topupModal');
    // Reset view
    const modal = document.getElementById('topupModal');
    if (modal) modal.classList.remove('topup-compact');
    
    // Revert footer to PayPal
    updateTopUpFooter('paypal');

    document.getElementById('paypal-button-container').style.display = 'none';
    document.getElementById('topup-method-choice-container').style.display = 'none';
    document.getElementById('crypto-payment-container').style.display = 'none';
    document.getElementById('crypto-details-mount').style.display = 'none';
    document.getElementById('topupPackageGrid').style.display = 'grid';
    document.getElementById('crypto-pay-btn').style.display = 'flex'; // restore pay button display
    document.getElementById('crypto-pay-btn').disabled = false;
    document.getElementById('crypto-pay-btn').innerHTML = '⚡ Bấm để lấy mã QR thanh toán';
    if (window._cryptoTimerInterval) {
        clearInterval(window._cryptoTimerInterval);
        window._cryptoTimerInterval = null;
    }
    _selectedTopUpPackage = null;
}

// ── Kick off Stripe init after DOM ready ──
document.addEventListener('DOMContentLoaded', () => {
    setTimeout(initStripe, 800);
});
