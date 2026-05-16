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
function renderItems(items) {
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

    items.forEach(item => {
        const card = createCard(item);
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

function createCard(item) {
    const price = parseFloat(item.price || 0);
    const isFree = price <= 0;
    const rating = parseFloat(item.rating_avg || 0);
    const downloads = parseInt(item.downloads || 0);
    const category = item.category || 'extension';
    const icons = { extension: '🧩', node: '🔗', skill: '⚡', model3d: '🎨' };
    
    const extName = (item.title || '').toLowerCase().replace(/[^a-z0-9_-]/g, '_');
    const knownLogo = EXTENSION_FEATURES[extName] ? `/static/market_logos/${extName}_logo.png` : null;
    
    const iconContent = item.thumbnail_url
        ? `<img src="${escapeHtml(item.thumbnail_url)}" alt="icon" loading="lazy">`
        : (knownLogo ? `<img src="${knownLogo}" alt="icon" loading="lazy">` : (icons[category] || '📦'));

    const featInfo = EXTENSION_FEATURES[extName] || { tagline: item.description || 'No description available', features: ['✨ New', '📦 ' + category] };

    const card = document.createElement('div');
    card.className = 'vsx-card';
    card.onclick = () => openDetailModal(item.public_id);

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
                <span class="card-price ${isFree ? 'free' : 'paid'}">${isFree ? 'Free' : formatCredits(price)}</span>
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
        if (item.thumbnail_url || knownLogo) {
            heroIcon.innerHTML = `<img src="${escapeHtml(item.thumbnail_url || knownLogo)}" alt="Logo" style="width:100%;height:100%;object-fit:cover;">`;
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

// ── Buy Item ──
async function buyItem(publicId) {
    const btn = document.getElementById('buyBtn_' + publicId);
    if (!btn) return;

    const originalText = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<div class="market-spinner" style="width:18px;height:18px;border-width:2px;margin:0;"></div> Processing...';

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
            btn.innerHTML = '✅ Purchased';
            btn.classList.add('free');
            showToast('Item purchased successfully!', 'success');

            // Show Install button after successful purchase
            const installBtn = document.getElementById('installBtn_' + publicId);
            if (installBtn) {
                installBtn.style.display = '';
            }
        } else {
            btn.disabled = false;
            btn.innerHTML = originalText;
            showToast(data.message || data.detail || 'Purchase failed', 'error');
        }
    } catch (e) {
        btn.disabled = false;
        btn.innerHTML = originalText;
        showToast('Network error', 'error');
    }
}

// ── Install Item ──
async function installItem(publicId, itemName, category, forceUpdate = false) {
    const btn = document.getElementById('installBtn_' + publicId);
    let originalText = '';
    if (btn) {
        originalText = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<div class="market-spinner" style="width:18px;height:18px;border-width:2px;margin:0;"></div> Installing...';
    }

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
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = originalText;
            }
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
            if (btn) {
                btn.innerHTML = '✅ Installed';
                btn.style.background = 'linear-gradient(135deg, #22c55e, #10b981)';
            }
            showToast(data.message || 'Installed successfully!', 'success');
        } else if (res.status === 409 || data.detail?.already_installed) {
            termLog("Item is already installed.", '#ffaa00');
            if (btn) {
                btn.innerHTML = '✅ Installed';
                btn.disabled = true;
            }
            showToast(data.detail?.message || 'This item is already installed', 'error');
        } else {
            termLog("❌ Installation Failed: " + (data.detail || data.message || 'Unknown error'), '#ff4444');
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = originalText;
            }
            showToast(data.detail || data.message || 'Install failed', 'error');
            throw new Error(data.detail || data.message || 'Install failed');
        }
    } catch (e) {
        clearInterval(termInterval);
        termLog("❌ Network / Execution Error: " + e.message, '#ff4444');
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = originalText;
        }
        showToast('Install error: ' + e.message, 'error');
        throw e;
    }
}

// ── Uninstall Item ──
async function uninstallItem(publicId, itemName, category) {
    const confirmed = await customConfirm('Gỡ cài đặt extension', `Bạn có chắc muốn gỡ cài đặt "${itemName}"?<br>Hành động này sẽ xóa toàn bộ source files của extension này khỏi máy.`);
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
    const upBtn = document.getElementById('updateBtn_' + publicId);
    if (!upBtn) return;
    
    const originalText = upBtn.innerHTML;
    upBtn.innerHTML = '<div class="market-spinner" style="width:18px;height:18px;border-width:2px;margin:0;"></div> Updating...';
    upBtn.disabled = true;

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
                upBtn.innerHTML = '✅ Updated';
                upBtn.style.boxShadow = 'none';
            }, 1000);
        } else if (res.status === 400 && (data.detail === "Currently only extensions installed via Git can be updated." || 
                                         data.message === "Currently only extensions installed via Git can be updated.")) {
            // ZIP Fallback Update Overwrite
            termLog("Extension was not installed via Git. Triggering Market ZIP Fallback Force Update...", '#ffaa00');
            showToast('Fetching latest ZIP update from Market...', 'info');
            await installItem(publicId, itemName, category, true);
            upBtn.innerHTML = '✅ Updated';
            upBtn.style.boxShadow = 'none';
        } else {
            termLog("❌ Update Failed: " + (data.detail || data.message || 'Unknown'), '#ff4444');
            throw new Error(data.message || data.detail || 'Update failed');
        }
    } catch (e) {
        clearInterval(updateInterval);
        termLog("❌ Error: " + e.message, '#ff4444');
        showToast(e.message || 'Update error', 'error');
        upBtn.innerHTML = originalText;
        upBtn.disabled = false;
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
    uploadState.category = 'skill';
    goToUploadStep(1);
    document.getElementById('uploadModal').classList.add('active');
    loadUploadItems('skill');
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
                            // Auto-fill dependencies from manifest
                            const depsInput = document.getElementById('uploadDeps');
                            if (depsInput && pkg.manifest?.dependencies?.length) {
                                depsInput.value = pkg.manifest.dependencies.join(', ');
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
    btn.innerHTML = '⏳ Publishing...';

    const tagsInput = document.getElementById('uploadTags').value;
    const tags = tagsInput ? tagsInput.split(',').map(t => t.trim()).filter(Boolean) : [];

    const payload = {
        title: document.getElementById('uploadDisplayName').value || document.getElementById('uploadTitle').value,
        category: document.getElementById('uploadCategory').value,
        price: parseFloat(document.getElementById('uploadPrice').value) || 0,
        visibility: document.getElementById('uploadVisibility').value,
        version: document.getElementById('uploadVersion').value || '1.0.0',
        thumbnail_url: document.getElementById('uploadAvatar') ? document.getElementById('uploadAvatar').value.trim() : undefined,
        tags: tags,
        description: document.getElementById('uploadDesc').value,
        item_data: (() => {
            // For extensions: merge user-declared dependencies into item_data
            let raw = document.getElementById('uploadData').value;
            const category = document.getElementById('uploadCategory').value;
            const gitUrl = document.getElementById('uploadGitUrl') ? document.getElementById('uploadGitUrl').value : undefined;
            const authorName = document.getElementById('uploadAuthorName') ? document.getElementById('uploadAuthorName').value.trim() : '';
            const authorContact = document.getElementById('uploadAuthorContact') ? document.getElementById('uploadAuthorContact').value.trim() : '';
            const authorDonate = document.getElementById('uploadAuthorDonate') ? document.getElementById('uploadAuthorDonate').value.trim() : '';
            
            try {
                const parsed = JSON.parse(raw);
                
                // Inject git_url straight into the item_data JSON so PHP API doesn't lose it
                if (gitUrl) {
                    parsed.git_url = gitUrl;
                    if (parsed.manifest) parsed.manifest.git_url = gitUrl;
                }

                // Inject author_info
                if (authorName || authorContact || authorDonate) {
                    parsed.author_info = {
                        name: authorName,
                        contact: authorContact,
                        donate_qr: authorDonate
                    };
                    if (parsed.manifest) parsed.manifest.author_info = parsed.author_info;
                }
                
                if (category === 'extension') {
                    const depsInput = document.getElementById('uploadDeps')?.value || '';
                    const deps = depsInput.split(',').map(d => d.trim()).filter(Boolean);
                    if (deps.length > 0) {
                        if (parsed.manifest) {
                            parsed.manifest.dependencies = deps;
                        } else {
                            parsed.dependencies = deps;
                        }
                    }
                }
                raw = JSON.stringify(parsed);
            } catch(e) {}
            return raw;
        })(),
        git_url: document.getElementById('uploadGitUrl') ? document.getElementById('uploadGitUrl').value : undefined,
    };

    try {
        const token = getAuthToken();
        const isEdit = !!editingPublicId;
        const url = isEdit ? `${API}/items/${editingPublicId}` : `${API}/items`;
        const method = isEdit ? 'PUT' : 'POST';
        btn.innerHTML = isEdit ? '⏳ Saving changes...' : '⏳ Publishing...';
        
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
            // Name conflict — another author owns this name
            const errMsg = typeof data.detail === 'string' ? data.detail : (data.message || 'Extension name already taken');
            showToast(errMsg, 'error');
        } else if (data.status === 'success' || data.public_id) {
            
            // --- UPLOAD MEDIA ---
            const publicId = data.public_id || data.item?.public_id || editingPublicId;
            const ytUrl = document.getElementById('uploadVideoUrl')?.value.trim();
            if (publicId && (uploadMediaFiles.screenshots.length > 0 || uploadMediaFiles.video || ytUrl)) {
                btn.innerHTML = '? Uploading Media...';
                try {
                    const formData = new FormData();
                    formData.append('public_id', publicId);
                    formData.append('token', token);
                    
                    uploadMediaFiles.screenshots.forEach(f => formData.append('screenshots[]', f));
                    if (uploadMediaFiles.video) formData.append('video', uploadMediaFiles.video);
                    if (ytUrl) formData.append('youtube_url', ytUrl);

                    const mediaRes = await fetch('https://api.tubecreate.com/api/market-cli/upload-media.php', {
                        method: 'POST',
                        body: formData
                    });
                    const mediaData = await mediaRes.json();
                    if(mediaData.status !== 'success') {
                        console.error('[Market] Media upload failed:', mediaData.message);
                    }
                } catch(me) {
                    console.error('[Market] Media upload error:', me);
                }
            }
            // --------------------

            if (data.auto_updated) {
                showToast(`✅ Version updated! "${payload.title}" v${payload.version} has been published.`, 'success');
            } else {
                showToast(isEdit ? 'Listing updated successfully!' : 'Item published to Market!', 'success');
            }
            closeUploadModal();
            loadItems();
            loadCategories();
            
            // Clear media state
            uploadMediaFiles = { screenshots: [], video: null };
            const uvUrl = document.getElementById('uploadVideoUrl');
            if (uvUrl) uvUrl.value = '';
            renderUploadMediaPreviews();
        } else {
            // Extract error message from various response formats
            let errMsg = isEdit ? 'Update failed' : 'Upload failed';
            if (typeof data.detail === 'string') errMsg = data.detail;
            else if (typeof data.detail === 'object' && data.detail?.msg) errMsg = data.detail.msg;
            else if (data.error) errMsg = data.error;
            else if (data.message) errMsg = data.message;
            console.error('[Market] Submit error:', data);
            showToast(errMsg, 'error');
        }
    } catch (e) {
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

async function loadMyListings() {
    const container = document.getElementById('myListingsContent');
    container.innerHTML = '<div class="market-loading" style="padding:40px 0;"><div class="market-spinner"></div><span style="color:var(--text-muted)">Loading your listings...</span></div>';

    try {
        const token = getAuthToken();
        const res = await fetch(`${API}/my-items`, {
            headers: token ? { 'Authorization': `Bearer ${token}` } : {},
        });
        const data = await res.json();

        if (data.status === 'success' && data.data && data.data.length > 0) {
            renderMyListings(data.data);
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

function renderMyListings(items) {
    const container = document.getElementById('myListingsContent');
    const categoryIcons = { extension: '🧩', node: '🔗', skill: '⚡', model3d: '🎨' };

    container.innerHTML = items.map(item => {
        const icon = categoryIcons[item.category] || '📦';
        const price = parseFloat(item.price || 0);
        const isFree = price <= 0;

        return `
            <div class="my-listing-item" id="myListing_${item.public_id}">
                <div class="my-listing-icon">${icon}</div>
                <div class="my-listing-info">
                    <div class="my-listing-title">${escapeHtml(item.title)}</div>
                    <div class="my-listing-meta">
                        <span class="my-listing-category">${escapeHtml(item.category)}</span>
                        <span>·</span>
                        <span>${isFree ? '🆓 Free' : '💰 ' + formatCredits(price)}</span>
                        <span>·</span>
                        <span>⬇️ ${item.downloads || 0}</span>
                        <span>·</span>
                        <span>⭐ ${parseFloat(item.rating_avg || 0).toFixed(1)}</span>
                    </div>
                </div>
                <div class="my-listing-actions">
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

    // Event delegation for View/Delete buttons
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
        }
    };
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
            document.getElementById('uploadCategory').value = item.category || 'extension';
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

            // Depopulate specific meta fields for UI rendering
            try {
                const parsed = typeof item.item_data === 'string' ? JSON.parse(item.item_data) : item.item_data;
                const gitUrlField = document.getElementById('uploadGitUrl');
                if(gitUrlField) gitUrlField.value = parsed.git_url || '';

                if (parsed.author_info) {
                    const aName = document.getElementById('uploadAuthorName');
                    const aContact = document.getElementById('uploadAuthorContact');
                    const aDonate = document.getElementById('uploadAuthorDonate');
                    if(aName) aName.value = parsed.author_info.name || '';
                    if(aContact) aContact.value = parsed.author_info.contact || '';
                    if(aDonate) aDonate.value = parsed.author_info.donate_qr || '';
                }
            } catch(e) {}
            
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
function customConfirm(title, message) {
    return new Promise((resolve) => {
        const modal = document.getElementById('confirmModal');
        document.getElementById('confirmTitle').innerHTML = title;
        document.getElementById('confirmMessage').innerHTML = message;
        
        modal.style.display = 'flex';
        // Add subtle animation
        modal.querySelector('.market-modal').style.animation = 'marketModalFadeIn 0.2s cubic-bezier(0.16, 1, 0.3, 1)';

        const cleanup = () => {
            modal.style.display = 'none';
            document.getElementById('confirmOkBtn').onclick = null;
            document.getElementById('confirmCancelBtn').onclick = null;
        };

        document.getElementById('confirmOkBtn').onclick = () => { cleanup(); resolve(true); };
        document.getElementById('confirmCancelBtn').onclick = () => { cleanup(); resolve(false); };
    });
}

async function confirmDeleteListing(publicId, title) {
    const confirmed = await customConfirm('Xoá Listing', `Bạn có chắc muốn xoá <b>"${title}"</b> khỏi Market?<br>Hành động này không thể hoàn tác.`);
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
