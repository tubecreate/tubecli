/**
 * TubeCLI Extension Market — Client Logic
 */

const API = '/api/v1/market';

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

// ── Init ──
document.addEventListener('DOMContentLoaded', () => {
    loadCategories();
    loadItems();
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

function createCard(item) {
    const price = parseFloat(item.price || 0);
    const isFree = price <= 0;
    const rating = parseFloat(item.rating_avg || 0);
    const downloads = parseInt(item.downloads || 0);
    const category = item.category || 'extension';
    const tags = item.tags || [];

    const card = document.createElement('div');
    card.className = 'market-card';
    card.onclick = () => openDetailModal(item.public_id);

    const categoryIcons = { extension: '🧩', node: '🔗', skill: '⚡', model3d: '🎨' };
    const categoryColors = { extension: 'badge-extension', node: 'badge-node', skill: 'badge-skill', model3d: 'badge-model3d' };

    card.innerHTML = `
        <div class="card-thumbnail">
            ${item.thumbnail_url 
                ? `<img src="${escapeHtml(item.thumbnail_url)}" alt="${escapeHtml(item.title)}" loading="lazy">` 
                : `<span class="thumb-icon">${categoryIcons[category] || '📦'}</span>`}
            <span class="card-category-badge ${categoryColors[category] || 'badge-extension'}">${category}</span>
        </div>
        <div class="card-body">
            <div class="card-title">${escapeHtml(item.title)}</div>
            <div class="card-desc">${escapeHtml(item.description || 'No description')}</div>
            <div class="card-meta">
                <span class="card-price ${isFree ? 'free' : 'paid'}">${isFree ? 'Free' : formatCredits(price)}</span>
                <div class="card-stats">
                    <span><span class="star-icon">★</span> ${rating.toFixed(1)}</span>
                    <span>⬇ ${formatNumber(downloads)}</span>
                </div>
            </div>
            ${tags.length ? `<div class="card-tags">${tags.slice(0, 3).map(t => `<span class="card-tag">${escapeHtml(t)}</span>`).join('')}</div>` : ''}
        </div>
    `;

    return card;
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
        const res = await fetch(`${API}/items/${publicId}`);
        const data = await res.json();

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

        const categoryIcons = { extension: '🧩', node: '🔗', skill: '⚡', model3d: '🎨' };
        heroIcon.textContent = categoryIcons[item.category] || '📦';

        body.innerHTML = `
            <h2 class="modal-title">${escapeHtml(item.title)}</h2>
            <div class="modal-seller">
                ${item.seller_avatar ? `<img src="${escapeHtml(item.seller_avatar)}" alt="avatar">` : '<span>👤</span>'}
                <span class="seller-name">${escapeHtml(item.seller_name || item.seller_id)}</span>
                <span>·</span>
                <span>${data.seller_item_count || 0} other items</span>
            </div>
            <div class="modal-stats-row">
                <div class="modal-stat"><span class="stat-icon">⬇️</span> ${formatNumber(item.downloads || 0)} downloads</div>
                <div class="modal-stat"><span class="stat-icon">⭐</span> ${rating.toFixed(1)} (${item.rating_count || 0} reviews)</div>
                <div class="modal-stat"><span class="stat-icon">📦</span> v${escapeHtml(item.version || '1.0.0')}</div>
                <div class="modal-stat"><span class="stat-icon">🏷️</span> ${escapeHtml(item.category)}</div>
            </div>
            <div class="modal-description">${escapeHtml(item.description || 'No description provided.')}</div>
            ${tags.length ? `<div class="modal-tags">${tags.map(t => `<span class="modal-tag">${escapeHtml(t)}</span>`).join('')}</div>` : ''}
            <div class="modal-action-row">
                <button class="btn-buy ${isFree ? 'free' : ''}" onclick="buyItem('${publicId}')" id="buyBtn_${publicId}">
                    ${isFree ? '⬇️ Get Free' : `🛒 Buy for ${formatCredits(price)}`}
                </button>
                <button class="btn-install" onclick="installItem('${publicId}', '${escapeHtml(item.title)}', '${escapeHtml(item.category)}')" id="installBtn_${publicId}">
                    📦 Install
                </button>
            </div>
            <div class="reviews-section">
                <h3>⭐ Reviews (${reviews.length})</h3>
                ${reviews.length ? reviews.map(r => `
                    <div class="review-card">
                        <div class="review-header">
                            <span class="review-author">${escapeHtml(r.reviewer_name || r.reviewer_id)}</span>
                            <span class="review-date">${formatDate(r.created_at)}</span>
                        </div>
                        <div class="review-stars">${renderStars(r.rating)}</div>
                        ${r.comment ? `<div class="review-text">${escapeHtml(r.comment)}</div>` : ''}
                    </div>
                `).join('') : '<p style="color:var(--text-muted);font-size:0.85rem;">No reviews yet</p>'}
            </div>
        `;
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
async function installItem(publicId, itemName, category) {
    const btn = document.getElementById('installBtn_' + publicId);
    if (!btn) return;

    const originalText = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<div class="market-spinner" style="width:18px;height:18px;border-width:2px;margin:0;"></div> Installing...';

    try {
        // First get the item detail to access item_data
        const detailRes = await fetch(`${API}/items/${publicId}`);
        const detailData = await detailRes.json();

        if (detailData.status !== 'success' || !detailData.item) {
            showToast('Failed to get item data', 'error');
            btn.disabled = false;
            btn.innerHTML = originalText;
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
            }),
        });
        const data = await res.json();

        if (data.status === 'success') {
            btn.innerHTML = '✅ Installed';
            btn.style.background = 'linear-gradient(135deg, #22c55e, #10b981)';
            showToast(data.message || 'Installed successfully!', 'success');
        } else {
            btn.disabled = false;
            btn.innerHTML = originalText;
            showToast(data.detail || data.message || 'Install failed', 'error');
        }
    } catch (e) {
        btn.disabled = false;
        btn.innerHTML = originalText;
        showToast('Network error', 'error');
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
            document.getElementById('uploadData').value = JSON.stringify(item._rawData);
            document.getElementById('uploadDesc').value = item._description || '';
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
            items = (Array.isArray(raw) ? raw : []).map(e => ({
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
        tags: tags,
        description: document.getElementById('uploadDesc').value,
        item_data: document.getElementById('uploadData').value,
    };

    try {
        const token = getAuthToken();
        const res = await fetch(`${API}/items`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
            },
            body: JSON.stringify(payload),
        });
        const data = await res.json();

        if (data.status === 'success' || data.public_id) {
            showToast('Item published to Market!', 'success');
            closeUploadModal();
            loadItems();
            loadCategories();
        } else {
            showToast(data.error || data.detail || 'Upload failed', 'error');
        }
    } catch (e) {
        showToast('Network error', 'error');
    }

    btn.disabled = false;
    btn.innerHTML = '📤 Publish to Market';
}

// ── Helpers ──
function showLoading() {
    document.getElementById('marketLoading').style.display = 'flex';
    document.getElementById('marketGrid').style.display = 'none';
    document.getElementById('marketEmpty').style.display = 'none';
    document.getElementById('marketPagination').style.display = 'none';
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

    if (isLoggedIn()) {
        const user = JSON.parse(localStorage.getItem('market_user') || '{}');
        const displayName = user.name || user.username || user.email || 'User';
        if (userInfo) {
            userInfo.style.display = 'flex';
            userName.textContent = '👤 ' + displayName;
        }
    } else {
        if (userInfo) userInfo.style.display = 'none';
    }
}

function logoutMarket() {
    localStorage.removeItem('user_token');
    localStorage.removeItem('market_user');
    updateMarketAuthUI();
    showToast('Đã đăng xuất', 'success');
    // Reload to clear any cached auth state
    setTimeout(() => location.reload(), 500);
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

// Close modals on Escape
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        closeDetailModal();
        closeUploadModal();
        closeLoginModal();
    }
});

// Submit on Enter in login modal
document.getElementById('authPassword').addEventListener('keypress', (e) => {
    if (e.key === 'Enter') handleMarketAuth();
});

// Init auth UI on load
updateMarketAuthUI();
