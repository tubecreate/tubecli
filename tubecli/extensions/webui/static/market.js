/**
 * TubeCLI Extension Market — Client Logic
 */

const API = '/api/v1/market';

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

// ── Init ──
document.addEventListener('DOMContentLoaded', async () => {
    // Start Market API calls immediately in parallel with i18n
    const categoriesPromise = loadCategories();
    const itemsPromise = loadItems();
    
    // Load i18n (local API, fast) — needed for UI labels
    await loadI18nFromApi();
    _marketLang = _lang || localStorage.getItem('tubecli_lang') || 'zh';
    
    // Wait for Market data if not done yet
    await Promise.all([categoriesPromise, itemsPromise]);
});

// ── Categories ──
async function loadCategories() {
    try {
        const res = await fetch(`${API}/categories`);
        const data = await res.json();
        if (data.status === 'success') {
            categoriesData = data;
            // Update tab counts
            const total = data.total_items || 0;
            setText('countAll', total);
            (data.categories || []).forEach(c => {
                const el = document.getElementById('count' + capitalize(c.key));
                if (el) el.textContent = c.count;
            });

            // Render popular tags
            const tagPills = document.getElementById('tagPills');
            tagPills.innerHTML = '';
            (data.popular_tags || []).forEach(tag => {
                const pill = document.createElement('span');
                pill.className = 'tag-pill';
                pill.textContent = tag;
                pill.onclick = () => toggleTag(tag, pill);
                tagPills.appendChild(pill);
            });
        }
    } catch (e) {
        console.error('[Market] Categories error:', e);
    }
}

// ── Load Items ──
async function loadItems() {
    showLoading();

    const params = new URLSearchParams();
    if (state.category) params.set('category', state.category);
    if (state.search) params.set('search', state.search);
    params.set('sort', state.sort);
    params.set('page', state.page);
    params.set('limit', state.limit);
    if (state.minPrice !== null) params.set('min_price', state.minPrice);
    if (state.maxPrice !== null) params.set('max_price', state.maxPrice);
    if (state.minRating !== null) params.set('min_rating', state.minRating);
    if (state.activeTags.length) params.set('tags', state.activeTags.join(','));

    try {
        const res = await fetch(`${API}/items?${params}`);
        const data = await res.json();

        if (data.status === 'success') {
            renderItems(data.data || []);
            renderPagination(data.pagination || {});
        } else {
            renderItems([]);
        }
    } catch (e) {
        console.error('[Market] Load error:', e);
        renderItems([]);
    }
}

// ── Render Items ──
async function renderItems(items) {
    const grid = document.getElementById('marketGrid');
    const empty = document.getElementById('marketEmpty');
    const loading = document.getElementById('marketLoading');

    loading.style.display = 'none';

    const countEl = document.getElementById('vsx-result-count');
    if (countEl) {
        countEl.innerHTML = `${items.length} <span data-i18n="market.results">Kết quả</span>`;
        if (typeof applyI18n === 'function') applyI18n();
    }

    if (!items.length) {
        grid.style.display = 'none';
        empty.style.display = 'block';
        return;
    }

    empty.style.display = 'none';
    grid.style.display = 'grid';
    grid.innerHTML = '';

    // Check installed status for all items concurrently (batch API)
    let installedData = {};
    try {
        const payload = items.map(item => ({
            public_id: item.public_id,
            item_name: item.title,
            category: item.category || 'extension'
        }));
        
        const checkRes = await fetch(`${API}/items/batch-check-installed`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const checkData = await checkRes.json();
        if (checkData.status === 'success') {
            installedData = checkData.data;
        }
    } catch(e) {
        console.warn('[Market] Batch check installed failed', e);
    }

    items.forEach(item => {
        const card = createCard(item, installedData[item.public_id]);
        grid.appendChild(card);
    });
}

const EXTENSION_FEATURES = {
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

function createCard(item, installData) {
    const price = parseFloat(item.price || 0);
    const isFree = price <= 0;
    const rating = parseFloat(item.rating_avg || 0);
    const downloads = parseInt(item.downloads || 0);
    const category = item.category || 'extension';
    const icons = { extension: '🧩', node: '🔗', skill: '⚡', model3d: '🎨' };
    
    const extName = (item.title || '').toLowerCase().replace(/[^a-z0-9_-]/g, '_');
    const knownLogo = EXTENSION_FEATURES[extName] ? `/static/market_logos/${extName}_logo.png` : null;
    
    let thumbUrl = item.thumbnail_url;
    if (thumbUrl && thumbUrl.startsWith('/images/')) {
        const imgName = thumbUrl.replace('/images/', '').replace('.png', '');
        if (imgName === 'edu_studio' || imgName === 'pod_ad_studio') {
            thumbUrl = '/static/market_logos/pod_studio_logo.png';
        } else {
            thumbUrl = `/static/market_logos/${imgName}_logo.png`;
        }
    }
    
    const iconContent = thumbUrl
        ? `<img src="${escapeHtml(thumbUrl)}" alt="icon" loading="lazy">`
        : (knownLogo ? `<img src="${knownLogo}" alt="icon" loading="lazy">` : (icons[category] || '📦'));

    const featInfo = EXTENSION_FEATURES[extName] || { tagline: item.description || 'No description available', features: ['✨ New', '📦 ' + category] };

    const card = document.createElement('div');
    card.className = 'vsx-card';
    card.onclick = () => openDetailModal(item.public_id);

    const priceBadge = `<span class="card-price ${isFree ? 'free' : 'paid'}">${isFree ? 'Free' : formatCredits(price)}</span>`;
    let quickBtnHtml = '';
    
    if (installData && installData.installed) {
        let hasUpdate = false;
        try {
            if (installData.local_version && cmpVersions(item.version, installData.local_version) > 0) {
                hasUpdate = true;
            }
        } catch(e) {}
        
        if (hasUpdate && category === 'extension') {
            quickBtnHtml = `<button id="cardUpdateBtn_${item.public_id}" class="card-price paid" style="cursor:pointer; background: linear-gradient(135deg, #f59e0b, #d97706); color: white; border:none;" onclick="event.stopPropagation(); updateLocalItem('${item.public_id}', '${escapeHtml(item.title).replace(/'/g, '\\\'')}', '${escapeHtml(category)}')">Cập nhật</button>`;
        } else {
            quickBtnHtml = `<button class="card-price free" style="cursor:default; background: rgba(255,255,255,0.05); border: 1px solid var(--border); color: var(--text-muted);" onclick="event.stopPropagation();">Đã cài</button>`;
        }
    } else if (isFree) {
        quickBtnHtml = `<button id="cardInstallBtn_${item.public_id}" class="card-price free" style="cursor:pointer; background: var(--accent); color: white; border:none;" onclick="event.stopPropagation(); installItem('${item.public_id}', '${escapeHtml(item.title).replace(/'/g, '\\\'')}', '${escapeHtml(category)}')">Cài đặt</button>`;
    }

    card.innerHTML = `
        <div class="vsx-card-inner">
            <span class="card-badge ${category}">${category}</span>
            <div class="card-header">
                <div class="card-icon">${iconContent}</div>
                <div class="card-header-info">
                    <h3 class="card-title" title="${escapeHtml(item.title)}">${escapeHtml(item.title)}</h3>
                    <div class="card-author">\u{1F464} ${escapeHtml(item.seller_name || item.author || 'Unknown')}</div>
                </div>
            </div>
            
            <div class="card-tagline">${escapeHtml(featInfo.tagline).substring(0, 80)}</div>
            
            <div class="card-feature-chips">
                ${featInfo.features.slice(0, 3).map(f => `<span class="feature-chip">${escapeHtml(f)}</span>`).join('')}
            </div>
            
            <div class="card-footer">
                <div class="card-stats">
                    <span class="stat-item">⭐ ${rating.toFixed(1)}</span>
                    <span class="stat-item">⬇ ${formatNumber(downloads)}</span>
                </div>
                <div style="display:flex; align-items:center; gap:8px;">
                    ${priceBadge}
                    ${quickBtnHtml}
                </div>
            </div>
        </div>
    `;

    return card;
}

// setCategoryFromSelect — syncs the dropdown with category state
function setCategoryFromSelect(val) {
    state.category = val;
    state.page = 1;
    applyFilters();
}

// ── Pagination ──
function renderPagination(pagination) {
    const container = document.getElementById('marketPagination');
    if (!pagination.total_pages || pagination.total_pages <= 1) {
        container.style.display = 'none';
        return;
    }

    container.style.display = 'flex';
    container.innerHTML = '';

    // Prev
    const prevBtn = document.createElement('button');
    prevBtn.className = 'page-btn';
    prevBtn.textContent = '← Prev';
    prevBtn.disabled = state.page <= 1;
    prevBtn.onclick = () => { state.page--; loadItems(); };
    container.appendChild(prevBtn);

    // Page numbers
    const total = pagination.total_pages;
    const current = state.page;
    const start = Math.max(1, current - 2);
    const end = Math.min(total, current + 2);

    for (let i = start; i <= end; i++) {
        const btn = document.createElement('button');
        btn.className = 'page-btn' + (i === current ? ' active' : '');
        btn.textContent = i;
        btn.onclick = () => { state.page = i; loadItems(); };
        container.appendChild(btn);
    }

    // Info
    const info = document.createElement('span');
    info.className = 'page-info';
    info.textContent = `${pagination.total} items`;
    container.appendChild(info);

    // Next
    const nextBtn = document.createElement('button');
    nextBtn.className = 'page-btn';
    nextBtn.textContent = 'Next →';
    nextBtn.disabled = state.page >= total;
    nextBtn.onclick = () => { state.page++; loadItems(); };
    container.appendChild(nextBtn);
}

// ── Category Switch ──
function switchCategory(btn, category) {
    state.category = category;
    state.page = 1;

    document.querySelectorAll('.market-tab').forEach(t => t.classList.remove('active'));
    btn.classList.add('active');

    loadItems();
}

// ── Filters ──
function applyFilters() {
    state.sort = document.getElementById('sortSelect').value;
    state.page = 1;

    const priceRadio = document.querySelector('input[name="price"]:checked');
    if (priceRadio) {
        if (priceRadio.value === 'free') {
            state.minPrice = null;
            state.maxPrice = 0;
        } else if (priceRadio.value === 'paid') {
            state.minPrice = 0.01;
            state.maxPrice = null;
        } else {
            state.minPrice = null;
            state.maxPrice = null;
        }
    }

    loadItems();
}

function setMinRating(rating) {
    const stars = document.querySelectorAll('#starFilter .star');
    const label = document.getElementById('ratingLabel');

    if (state.minRating === rating) {
        state.minRating = null;
        stars.forEach(s => s.classList.remove('filled'));
        label.textContent = 'Any rating';
    } else {
        state.minRating = rating;
        stars.forEach(s => {
            s.classList.toggle('filled', parseInt(s.dataset.rating) <= rating);
        });
        label.textContent = `${rating}★ and above`;
    }
    state.page = 1;
    loadItems();
}

function toggleTag(tag, pill) {
    const idx = state.activeTags.indexOf(tag);
    if (idx >= 0) {
        state.activeTags.splice(idx, 1);
        pill.classList.remove('active');
    } else {
        state.activeTags.push(tag);
        pill.classList.add('active');
    }
    state.page = 1;
    loadItems();
}

// ── Search ──
function debounceSearch() {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
        state.search = document.getElementById('marketSearch').value.trim();
        state.page = 1;
        loadItems();
    }, 400);
}

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
            fetch(`https://api.tubecreate.com/api/market-cli/get-media.php?public_id=${publicId}`).catch(() => null)
        ]);
        
        const data = await res.json();
        let mediaData = { screenshots: [], videos: [] };
        if (mediaRes && mediaRes.ok) {
            const m = await mediaRes.json();
            if (m.status === 'success') mediaData = m;
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
                                <h4 style="margin:0 0 16px 0;font-size:1.1rem;color:#fff;">💖 Author & Support</h4>
                                <div style="display:flex;flex-wrap:wrap;gap:16px;align-items:center;font-size:0.95rem;">
                                    ${auth.name ? `<div><strong style="color:var(--text2);">Author:</strong> <span style="font-weight:600;color:#fff;">${escapeHtml(auth.name)}</span></div>` : ''}
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
                        <h3 style="margin-bottom: 16px; color: #fff;">🎬 Demo Video</h3>
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
                        <h3 style="margin-top: 32px; margin-bottom: 16px; color: #fff;">📸 Screenshots</h3>
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
                                <span class="review-author" style="font-weight:600;color:#fff;">${escapeHtml(r.reviewer_name || r.reviewer_id)}</span>
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
                    installBtn.style.background = 'linear-gradient(135deg, #22c55e, #10b981)';
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
                showToast('Mua thành công! Bạn có thể cài đặt ngay.', 'success');
                // Show Install button
                const installBtn = document.getElementById('installBtn_' + publicId);
                if (installBtn) installBtn.style.display = '';
                // Refresh balance in header
                loadStripeBalance();
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
async function installItem(publicId, itemName, category, forceUpdate = false) {
    const modalBtn = document.getElementById('installBtn_' + publicId);
    const cardInstallBtn = document.getElementById('cardInstallBtn_' + publicId);
    const cardUpdateBtn = document.getElementById('cardUpdateBtn_' + publicId);
    const btns = [modalBtn, cardInstallBtn, cardUpdateBtn].filter(Boolean);
    
    let originalTexts = [];
    btns.forEach((btn, i) => {
        originalTexts[i] = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<div class="market-spinner" style="width:14px;height:14px;border-width:2px;margin:0 6px 0 0;display:inline-block;vertical-align:middle;"></div> ' + (forceUpdate ? 'Cập nhật...' : 'Đang cài...');
    });

    clearTerm();
    termLog(`Initializing installation for ${itemName}...`, '#88aaff');

    const steps = [
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

            // Derive extension slug for navigation
            const extSlug = itemName.toLowerCase().replace(/[^a-z0-9_-]/g, '_');
            const extTabId = 'ext-' + extSlug;

            // Refresh sidebar to show the new extension
            if (window.parent && typeof window.parent.loadDynamicExtensionsToSidebar === 'function') {
                try { await window.parent.loadDynamicExtensionsToSidebar(); } catch(e) {}
            } else if (typeof loadDynamicExtensionsToSidebar === 'function') {
                try { await loadDynamicExtensionsToSidebar(); } catch(e) {}
            }

            btns.forEach((btn) => {
                if (btn.id.startsWith('card')) {
                    btn.innerHTML = 'Đã cài';
                    btn.style.background = 'rgba(255,255,255,0.05)';
                    btn.style.border = '1px solid var(--border)';
                    btn.style.color = 'var(--text-muted)';
                    btn.style.boxShadow = 'none';
                    btn.disabled = true;
                } else {
                    btn.innerHTML = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:middle;margin-right:4px;"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg> Open ${itemName}`;
                    btn.style.background = 'linear-gradient(135deg, #22c55e, #10b981)';
                    btn.style.boxShadow = '0 2px 12px rgba(34,197,94,0.25)';
                    btn.disabled = false;
                    btn.onclick = () => {
                        closeDetailModal();
                        if (window.parent && typeof window.parent.navigateTo === 'function') {
                            window.parent.navigateTo(extTabId);
                        } else if (typeof navigateTo === 'function') {
                            navigateTo(extTabId);
                        } else {
                            if (window.parent) window.parent.location.hash = '#/' + extTabId;
                            else window.location.hash = '#/' + extTabId;
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
                    btn.style.background = 'rgba(255,255,255,0.05)';
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
            termLog("❌ Installation Failed: " + (data.detail || data.message || 'Unknown error'), '#ff4444');
            btns.forEach((btn, i) => {
                btn.disabled = false;
                btn.innerHTML = originalTexts[i];
            });
            showToast(data.detail || data.message || 'Install failed', 'error');
            throw new Error(data.detail || data.message || 'Install failed');
        }
    } catch (e) {
        clearInterval(termInterval);
        termLog("❌ Network / Execution Error: " + e.message, '#ff4444');
        btns.forEach((btn, i) => {
            btn.disabled = false;
            btn.innerHTML = originalTexts[i];
        });
        showToast('Install error: ' + e.message, 'error');
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
        'linear-gradient(135deg, #ef4444, #dc2626)',
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
                        btn.style.background = 'rgba(255,255,255,0.05)';
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
                    btn.style.background = 'rgba(255,255,255,0.05)';
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
                    const formData = new FormData();
                    formData.append('public_id', publicId);
                    formData.append('token', token);
                    
                    uploadMediaFiles.screenshots.forEach(f => formData.append('screenshots[]', f));
                    if (uploadMediaFiles.video) formData.append('video', uploadMediaFiles.video);
                    if (ytUrl) formData.append('youtube_url', ytUrl);

                    updateProgressLog("Đang bắt đầu tải lên media server...", "info");
                    
                    await new Promise((resolve, reject) => {
                        const xhr = new XMLHttpRequest();
                        xhr.open('POST', 'https://api.tubecreate.com/api/market-cli/upload-media.php');
                        
                        xhr.upload.onprogress = (evt) => {
                            if (evt.lengthComputable) {
                                const percentComplete = Math.round((evt.loaded / evt.total) * 100);
                                updateProgressLog(`Đang tải lên media: ${percentComplete}%...`, "progress");
                            }
                        };
                        
                        xhr.onload = () => {
                            if (xhr.status >= 200 && xhr.status < 300) {
                                try {
                                    const resData = JSON.parse(xhr.responseText);
                                    if (resData.status === 'success') {
                                        updateProgressLog("Đã tải lên media thành công!", "success");
                                        resolve(resData);
                                    } else {
                                        updateProgressLog("Cảnh báo media: " + (resData.message || "Unknown error"), "warn");
                                        resolve(resData);
                                    }
                                } catch(e) {
                                    updateProgressLog("Không thể parse kết quả trả về từ media server", "warn");
                                    resolve(null);
                                }
                            } else {
                                updateProgressLog("Tải lên media thất bại với status code: " + xhr.status, "warn");
                                resolve(null);
                            }
                        };
                        
                        xhr.onerror = () => {
                            updateProgressLog("Lỗi kết nối mạng trong quá trình tải lên media", "warn");
                            resolve(null);
                        };
                        
                        xhr.send(formData);
                    });
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

function showToast(message, type = 'success') {
    const toast = document.getElementById('marketToast');
    toast.textContent = message;
    toast.className = 'market-toast ' + type + ' show';
    setTimeout(() => {
        toast.classList.remove('show');
    }, 3000);
}

// ── Auth System ──

const AUTH_API = 'https://api.tubecreate.com/api/user';
let marketIsRegisterMode = false;
let pendingSellAction = false;

function requireAuth(callback) {
    if (isLoggedIn()) {
        callback();
    } else {
        pendingSellAction = true;
        showLoginModal();
    }
}

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
        let apiUrl = `${AUTH_API}/validate-user.php`;
        let payload = { email, password };

        if (marketIsRegisterMode) {
            apiUrl = `${AUTH_API}/create-user.php`;
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

            closeLoginModal();
            updateMarketAuthUI();
            showToast(marketIsRegisterMode ? 'Đăng ký thành công!' : 'Đăng nhập thành công!', 'success');

            // Resume sell action if pending
            if (pendingSellAction) {
                pendingSellAction = false;
                setTimeout(() => openUploadModal(), 300);
            }

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
    } else {
        if (userInfo) userInfo.style.display = 'none';
        if (myListingsBtn) myListingsBtn.style.display = 'none';
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
        'linear-gradient(135deg, #f59e0b, #d97706)',
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
                okBtn.style.background = 'linear-gradient(135deg, #ef4444, #dc2626)';
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
        'linear-gradient(135deg, #ef4444, #dc2626)',
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


const STRIPE_PACKAGES_DEFAULT = [
    { id: 'starter',  name: 'Starter',  credits: 5000,   price_usd: 5.00,  badge: null,          color: '#6366f1' },
    { id: 'pro',      name: 'Pro',       credits: 15000,  price_usd: 12.00, badge: 'Popular',     color: '#8b5cf6' },
    { id: 'power',    name: 'Power',     credits: 50000,  price_usd: 35.00, badge: 'Best Value',  color: '#a855f7' },
    { id: 'ultimate', name: 'Ultimate',  credits: 150000, price_usd: 90.00, badge: 'Pro',         color: '#ec4899' },
];


// ── Init: Load Stripe config + balance on page load ──
async function initStripe() {
    try {
        const res = await fetch(`${API}/stripe/config`);
        const cfg = await res.json();
        _stripePublishableKey = cfg.publishable_key;
        _stripePackages       = cfg.packages || [];
    } catch (e) {
        console.warn('[Stripe] Failed to load config:', e);
    }
    await loadStripeBalance();
    renderCreditBadge();
    handleStripeReturn();
}

async function loadStripeBalance() {
    const token = getAuthToken();
    if (!token) { _stripeBalance = null; renderCreditBadge(); return; }
    try {
        const res = await fetch(`${API}/stripe/balance`, {
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
        <span id="creditBalanceVal" style="font-weight:700;">${Math.floor(_stripeBalance)}</span>
        <span style="opacity:0.6;font-size:0.75rem;">credits</span>
        <button onclick="openTopUpModal()" style="margin-left:6px;padding:2px 10px;font-size:0.72rem;background:linear-gradient(135deg,#6366f1,#8b5cf6);border:none;border-radius:8px;color:#fff;cursor:pointer;font-weight:600;transition:all 0.2s;" onmouseover="this.style.transform='translateY(-1px)'" onmouseout="this.style.transform=''">+ Nạp</button>
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

    const priceUsd  = (priceCredits * 0.10).toFixed(2);
    const balance   = _stripeBalance !== null ? Math.floor(_stripeBalance) : null;
    const canAfford = balance !== null && balance >= priceCredits;

    const dlg = document.getElementById('paymentChoiceModal');
    if (!dlg) { buyItemWithCredits(publicId); return; }

    document.getElementById('paymentChoiceBody').innerHTML = `
        <div class="pmc-item-info">
            <div class="pmc-item-icon">🧩</div>
            <div>
                <div style="font-weight:700;font-size:1rem;color:#fff">${escapeHtml(title)}</div>
                <div style="font-size:0.8rem;color:var(--text-muted);margin-top:3px">
                    Giá: <strong style="color:#818cf8">${priceCredits} credits</strong>
                    &nbsp;≈&nbsp; <strong>$${priceUsd} USD</strong>
                </div>
            </div>
        </div>

        ${balance !== null ? `
        <div class="pmc-balance">
            <span>💎 Số dư của bạn:</span>
            <strong style="color:${canAfford ? '#4ade80' : '#f87171'}">${balance} credits</strong>
            ${!canAfford ? `<span style="color:#f87171;font-size:0.74rem;margin-left:6px;">⚠ Thiếu ${priceCredits - balance} credits</span>` : ''}
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

            <div class="pmc-option pmc-stripe" onclick="startQuickPay('${publicId}', ${priceCredits})">
                <div class="pmc-opt-icon">💳</div>
                <div class="pmc-opt-body">
                    <div class="pmc-opt-title">Thanh toán nhanh qua Stripe</div>
                    <div class="pmc-opt-desc">Trả $${priceUsd} USD bằng thẻ quốc tế — không cần credits</div>
                </div>
                <span class="pmc-opt-badge badge-stripe">⚡ Quick Pay</span>
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
        fetch(`${API}/stripe/config`)
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
    if (dlg) dlg.onclick = (e) => { if (e.target === dlg) _dlgClose('topupModal'); };
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
            <div class="topup-credits-num">${pkg.credits.toLocaleString()}</div>
            <div class="topup-credits-lbl">credits</div>
            <div class="topup-price-tag">$${pkg.price_usd.toFixed(2)} <span style="font-size:0.7rem;opacity:0.6;">USD</span></div>
            <div class="topup-rate">${Math.round(pkg.credits / pkg.price_usd).toLocaleString()} credits / $1</div>
            <button class="topup-go-btn">Nạp ngay →</button>
        </div>`;
    }).join('');
}


async function startTopUp(packageId, cardEl) {
    const token = getAuthToken();
    if (!token) { showToast('Vui lòng đăng nhập', 'error'); return; }

    const btn = cardEl ? cardEl.querySelector('.topup-go-btn') : null;
    if (btn) { btn.textContent = 'Đang chuyển...'; btn.disabled = true; }

    try {
        const res = await fetch(`${API}/stripe/topup-session`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
            body: JSON.stringify({
                package_id:  packageId,
                success_url: window.location.href.split('?')[0],
                cancel_url:  window.location.href.split('?')[0],
            }),
        });
        const data = await res.json();
        if (data.checkout_url) {
            // Stripe cannot run inside an iframe — open in new tab
            window.open(data.checkout_url, '_blank');
            closeTopUpModal();
            if (btn) { btn.textContent = 'Nạp ngay →'; btn.disabled = false; }
        } else {
            showToast(data.detail || 'Không tạo được phiên thanh toán', 'error');
            if (btn) { btn.textContent = 'Nạp ngay →'; btn.disabled = false; }
        }
    } catch (e) {
        showToast('Lỗi kết nối Stripe', 'error');
        if (btn) { btn.textContent = 'Nạp ngay →'; btn.disabled = false; }
    }
}

// ── Quick Pay ──
async function startQuickPay(publicId, priceCredits) {
    closePaymentChoiceModal();
    const token = getAuthToken();
    if (!token) { showToast('Vui lòng đăng nhập', 'error'); return; }

    showToast('Đang chuyển đến Stripe...', 'info');

    try {
        const res = await fetch(`${API}/stripe/quickpay-session`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
            body: JSON.stringify({
                item_public_id:     publicId,
                item_title:         _paymentChoiceTitle,
                item_price_credits: priceCredits,
                success_url: window.location.href.split('?')[0],
                cancel_url:  window.location.href.split('?')[0],
            }),
        });
        const data = await res.json();
        if (data.checkout_url) {
            // Stripe cannot run inside an iframe — open in new tab
            window.open(data.checkout_url, '_blank');
            closePaymentChoiceModal();
            if (btn) { btn.textContent = 'Thanh toán'; btn.disabled = false; }
        } else {
            showToast(data.detail || 'Không tạo được phiên thanh toán', 'error');
        }
    } catch (e) {
        showToast('Lỗi kết nối Stripe', 'error');
    }
}

// ── Kick off Stripe init after DOM ready ──
document.addEventListener('DOMContentLoaded', () => {
    setTimeout(initStripe, 800);
});
