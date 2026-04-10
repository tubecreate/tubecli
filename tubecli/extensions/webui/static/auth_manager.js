/**
 * Auth Manager — Frontend Logic
 */

const API_BASE = '/api/v1/auth-manager';

// ── State ───────────────────────────────────────────────────────
let providersData = [];
let credentialsData = [];
let tokensData = [];
let profilesData = [];
let _jsonContent = '';

// ── Init ────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    loadProviders();
    loadCredentials();
    loadTokens();
    loadBrowserProfiles();
});

// ── API Helpers ─────────────────────────────────────────────────
async function apiGet(path) {
    const r = await fetch(`${API_BASE}${path}`);
    return r.json();
}

async function apiPost(path, body) {
    const r = await fetch(`${API_BASE}${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    return r.json();
}

async function apiPut(path, body) {
    const r = await fetch(`${API_BASE}${path}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    return r.json();
}

async function apiDelete(path) {
    const r = await fetch(`${API_BASE}${path}`, { method: 'DELETE' });
    return r.json();
}

// ── Load Providers ──────────────────────────────────────────────
async function loadProviders() {
    try {
        const data = await apiGet('/providers');
        providersData = data.providers || [];
        renderProviders();
    } catch (e) {
        document.getElementById('providers-grid').innerHTML = `<div class="am-empty">Failed to load providers: ${e.message}</div>`;
    }
}

function renderProviders() {
    const grid = document.getElementById('providers-grid');
    if (!providersData.length) {
        grid.innerHTML = '<div class="am-empty">No providers configured</div>';
        return;
    }

    grid.innerHTML = providersData.map(p => {
        const scopeChips = Object.entries(p.scopes || {}).slice(0, 5).map(
            ([k, v]) => `<span class="am-scope-chip">${v}</span>`
        ).join('');
        const moreScopes = Object.keys(p.scopes || {}).length > 5 
            ? `<span class="am-scope-chip">+${Object.keys(p.scopes).length - 5}</span>` : '';

        return `
        <div class="am-provider-card" data-provider="${p.id}" onclick="filterByProvider('${p.id}')">
            <div class="am-provider-header">
                <span class="am-provider-icon">${p.icon}</span>
                <span class="am-provider-name">${p.name}</span>
            </div>
            <div class="am-provider-stats">
                <div class="am-stat">
                    <span class="am-stat-value">${p.credential_count}</span>
                    <span class="am-stat-label">Credentials</span>
                </div>
                <div class="am-stat">
                    <span class="am-stat-value">${p.token_count}</span>
                    <span class="am-stat-label">Tokens</span>
                </div>
            </div>
            <div class="am-provider-scopes">${scopeChips}${moreScopes}</div>
        </div>`;
    }).join('');
}

function filterByProvider(providerId) {
    document.getElementById('filter-provider').value = providerId;
    loadCredentials();
}

// ── Load Credentials ────────────────────────────────────────────
async function loadCredentials() {
    try {
        const provider = document.getElementById('filter-provider').value;
        const query = provider ? `?provider=${provider}` : '';
        const data = await apiGet(`/credentials${query}`);
        credentialsData = data.credentials || [];
        renderCredentials();
    } catch (e) {
        document.getElementById('credentials-tbody').innerHTML =
            `<tr><td colspan="6" class="am-empty">Failed to load: ${e.message}</td></tr>`;
    }
}

function renderCredentials() {
    const tbody = document.getElementById('credentials-tbody');
    if (!credentialsData.length) {
        tbody.innerHTML = '<tr><td colspan="6" class="am-empty">No credentials. Click "+ Add Credential" to get started.</td></tr>';
        return;
    }

    tbody.innerHTML = credentialsData.map(c => {
        const provBadge = `<span class="am-badge am-badge-${c.provider}">${c.provider}</span>`;
        const tokenBadge = {
            active: '<span class="am-badge am-badge-active">✅ Active</span>',
            expired: '<span class="am-badge am-badge-expired">⏰ Expired</span>',
            none: '<span class="am-badge am-badge-none">— None</span>',
            revoked: '<span class="am-badge am-badge-revoked">❌ Revoked</span>',
        }[c.token_status] || '<span class="am-badge am-badge-none">—</span>';

        const hasJson = c.has_json ? '<span class="am-badge am-badge-active" title="Service Account JSON">📄 JSON</span>' : '';

        return `<tr>
            <td><code style="font-size:0.78rem;color:#8b5cf6">${c.id}</code></td>
            <td>${provBadge}</td>
            <td>${c.name} ${hasJson}</td>
            <td><code style="font-size:0.78rem">${c.client_id || '—'}</code></td>
            <td>${tokenBadge}</td>
            <td class="am-actions">
                <button class="am-btn-sm" onclick="openAuthorizeModal('${c.id}')">🔓 Authorize</button>
                <button class="am-btn-sm" onclick="editCredential('${c.id}')">✏️</button>
                <button class="am-btn-sm danger" onclick="deleteCredential('${c.id}', '${c.name}')">🗑</button>
            </td>
        </tr>`;
    }).join('');
}

// ── Load Tokens ─────────────────────────────────────────────────
async function loadTokens() {
    try {
        const data = await apiGet('/tokens');
        tokensData = data.tokens || [];
        renderTokens();
    } catch (e) {
        document.getElementById('tokens-tbody').innerHTML =
            `<tr><td colspan="7" class="am-empty">Failed to load: ${e.message}</td></tr>`;
    }
}

function renderTokens() {
    const tbody = document.getElementById('tokens-tbody');
    if (!tokensData.length) {
        tbody.innerHTML = '<tr><td colspan="7" class="am-empty">No authorized tokens yet. Authorize a credential to get started.</td></tr>';
        return;
    }

    tbody.innerHTML = tokensData.map(t => {
        const provBadge = `<span class="am-badge am-badge-${t.provider}">${t.provider}</span>`;
        const statusBadge = {
            active: '<span class="am-badge am-badge-active">✅ Active</span>',
            expired: '<span class="am-badge am-badge-expired">⏰ Expired</span>',
            revoked: '<span class="am-badge am-badge-revoked">❌ Revoked</span>',
        }[t.status] || '<span class="am-badge am-badge-none">?</span>';

        const scopes = (t.scopes || []).join(', ');
        const profile = t.browser_profile 
            ? `<code style="font-size:0.78rem">${t.browser_profile}</code>` 
            : '<span style="color:#64748b">—</span>';

        return `<tr>
            <td><code style="font-size:0.78rem;color:#8b5cf6">${t.credential_id}</code>
                <br><span style="color:#94a3b8;font-size:0.8rem">${t.credential_name}</span></td>
            <td>${provBadge}</td>
            <td>${t.authorized_email || '—'}</td>
            <td>${profile}</td>
            <td style="font-size:0.8rem;max-width:200px;overflow:hidden;text-overflow:ellipsis">${scopes}</td>
            <td>${statusBadge}</td>
            <td class="am-actions">
                ${t.has_refresh ? `<button class="am-btn-sm" onclick="refreshToken('${t.token_id}')">🔄 Refresh</button>` : ''}
                <button class="am-btn-sm danger" onclick="revokeToken('${t.token_id}')">❌ Revoke</button>
            </td>
        </tr>`;
    }).join('');
}

// ── Load Browser Profiles ───────────────────────────────────────
async function loadBrowserProfiles() {
    try {
        const r = await fetch('/api/v1/browser/profiles');
        const data = await r.json();
        profilesData = data.profiles || [];
    } catch (e) {
        profilesData = [];
    }
}

// ── Add Credential Modal ────────────────────────────────────────
function openAddCredentialModal() {
    document.getElementById('credential-modal-title').textContent = 'Add Credential';
    document.getElementById('cred-edit-id').value = '';
    document.getElementById('cred-provider').value = 'google';
    document.getElementById('cred-name').value = '';
    document.getElementById('cred-client-id').value = '';
    document.getElementById('cred-client-secret').value = '';
    document.getElementById('cred-sa-email').value = '';
    const manualIdInput = document.getElementById('cred-manual-id');
    if (manualIdInput) manualIdInput.value = '';
    const manualTokenInput = document.getElementById('cred-manual-token');
    if (manualTokenInput) manualTokenInput.value = '';
    document.getElementById('cred-json-filename').textContent = '';
    _jsonContent = '';
    onProviderChange();
    switchCredTab('oauth');
    goToCredStep(1);
    openModal('modal-credential');
}

function editCredential(credId) {
    const cred = credentialsData.find(c => c.id === credId);
    if (!cred) return;

    document.getElementById('credential-modal-title').textContent = 'Edit Credential';
    document.getElementById('cred-edit-id').value = credId;
    document.getElementById('cred-provider').value = cred.provider;
    document.getElementById('cred-name').value = cred.name;
    document.getElementById('cred-client-id').value = ''; // masked
    document.getElementById('cred-client-secret').value = '';
    document.getElementById('cred-sa-email').value = cred.service_account_email || '';
    
    if (cred.provider === 'facebook') {
        // Recover manual ID (it might be masked, but better than nothing)
        const rawId = cred.client_id || '';
        document.getElementById('cred-manual-id').value = rawId.replace('***', '');
        document.getElementById('cred-manual-token').value = '********'; // Dummy token placeholder
    } else {
        document.getElementById('cred-manual-id').value = '';
        document.getElementById('cred-manual-token').value = '';
    }

    _jsonContent = '';
    onProviderChange(cred.scopes || []);
    goToCredStep(1);
    openModal('modal-credential');
}

function onProviderChange(selectedScopes = []) {
    const providerKey = document.getElementById('cred-provider').value;
    const jsonTab = document.querySelector('.am-tab[data-tab="json"]');
    const manualTab = document.querySelector('.am-tab[data-tab="manual"]');
    
    // Manage Tabs visibility
    if (providerKey === 'google') {
        jsonTab.style.display = '';
        if (manualTab) manualTab.style.display = 'none';
        switchCredTab('oauth');
    } else if (providerKey === 'facebook') {
        // Facebook: show both OAuth (for FB App users) and Manual (for token paste)
        jsonTab.style.display = 'none';
        if (manualTab) manualTab.style.display = '';
        switchCredTab('manual'); // Default to manual — simpler for most users
    } else {
        jsonTab.style.display = 'none';
        if (manualTab) manualTab.style.display = 'none';
        switchCredTab('oauth');
    }

    // Render service cards for this provider
    renderCredServiceCards(providerKey, selectedScopes);
}

function renderCredServiceCards(providerKey, selectedScopes = []) {
    const container = document.getElementById('cred-services-list');
    const provider = providersData.find(p => p.id === providerKey);
    const services = provider?.services || {};
    const scopes = provider?.scopes || {};

    if (!Object.keys(services).length) {
        container.innerHTML = '<div class="am-empty" style="padding:12px">No services defined</div>';
        return;
    }
    let html = Object.entries(services).map(([svcId, svc]) => {
        const svcScopes = svc.scopes || [];
        const isChecked = svcScopes.length > 0 && svcScopes.some(s => selectedScopes.includes(s));
        const checkedAttr = isChecked ? 'checked' : '';
        const selectedClass = isChecked ? 'selected' : '';
        
        return `
        <div class="am-service-card wizard-card ${selectedClass}" data-service="${svcId}" onclick="toggleCredService(this)">
            <div class="am-service-row">
                <input type="checkbox" class="am-service-check" 
                    data-scopes="${svcScopes.join(',')}" 
                    ${checkedAttr}
                    onclick="event.stopPropagation()">
                <div class="am-service-info">
                    <div class="am-service-label">${svc.label}</div>
                    <div class="am-service-desc">${svc.description || ''}</div>
                </div>
            </div>
        </div>`;
    }).join('');

    // Extra Custom Scope box
    const customScopesList = selectedScopes.filter(s => {
        // Find if s is in predefined services
        for (let sv of Object.values(services)) {
            if (sv.scopes && sv.scopes.includes(s)) return false;
        }
        return true;
    });
    const hasCustom = customScopesList.length > 0;
    
    html += `
    <div class="am-service-card wizard-card ${hasCustom ? 'selected' : ''}" style="margin-top:12px" onclick="toggleCustomScopeCard(this)">
        <div class="am-service-row">
            <input type="checkbox" class="am-service-check am-custom-check" ${hasCustom ? 'checked' : ''} onclick="event.stopPropagation()">
            <div class="am-service-info">
                <div class="am-service-label">➕ Thêm Scope Tùy Chỉnh</div>
                <div class="am-service-desc">Tuỳ biến nhập thêm các URL API Scope khác</div>
            </div>
        </div>
        <div class="am-custom-body" style="display:${hasCustom ? 'block' : 'none'}; padding-top:12px">
            <input type="text" id="am-custom-scopes-input" class="am-input" 
                value="${customScopesList.join(', ')}"
                placeholder="https://www.googleapis.com/auth/analytics.readonly, ..." 
                onclick="event.stopPropagation()">
        </div>
    </div>`;
    
    container.innerHTML = html;
}

window.toggleCustomScopeCard = function(card) {
    const check = card.querySelector('.am-service-check');
    check.checked = !check.checked;
    card.classList.toggle('selected', check.checked);
    card.querySelector('.am-custom-body').style.display = check.checked ? 'block' : 'none';
};

function goToCredStep(step) {
    if (step === 1) {
        document.getElementById('cred-step-1').style.display = 'block';
        document.getElementById('cred-step-2').style.display = 'none';
        
        // Reset title
        const editId = document.getElementById('cred-edit-id').value;
        document.getElementById('credential-modal-title').textContent = editId ? 'Edit Credential' : 'Add Credential';
    } else if (step === 2) {
        // Collect required scopes
        const scopes = getSelectedCredScopes();
        const providerKey = document.getElementById('cred-provider').value;
        const provider = providersData.find(p => p.id === providerKey);
        const provScopes = provider?.scopes || {};
        
        const redirectUri = `${window.location.origin}/api/v1/auth-manager/oauth/callback`;
        document.getElementById('cred-setup-redirect-uri').textContent = redirectUri;
        
        // Provider-specific labels for OAuth Client tab
        const clientIdInput = document.getElementById('cred-client-id');
        const clientSecretInput = document.getElementById('cred-client-secret');
        const clientIdLabel = clientIdInput.closest('.form-group').querySelector('label');
        const clientSecretLabel = clientSecretInput.closest('.form-group').querySelector('label');
        const redirectUriDesc = document.querySelector('#cred-setup-redirect-uri + .am-scope-desc');
        
        if (providerKey === 'facebook') {
            clientIdLabel.textContent = 'App ID';
            clientIdInput.placeholder = '123456789012345';
            clientSecretLabel.textContent = 'App Secret';
            clientSecretInput.placeholder = 'abc123def456...';
            if (redirectUriDesc) redirectUriDesc.textContent = '(Facebook App > Settings > Valid OAuth Redirect URIs)';
        } else if (providerKey === 'tiktok') {
            clientIdLabel.textContent = 'Client Key';
            clientIdInput.placeholder = 'awXXXXXXXXXX';
            clientSecretLabel.textContent = 'Client Secret';
            clientSecretInput.placeholder = 'xxxxxxxxxxxxx';
            if (redirectUriDesc) redirectUriDesc.textContent = '(TikTok Developer Portal > Configuration)';
        } else {
            clientIdLabel.textContent = 'Client ID';
            clientIdInput.placeholder = 'xxx.apps.googleusercontent.com';
            clientSecretLabel.textContent = 'Client Secret';
            clientSecretInput.placeholder = 'GOCSPX-xxx';
            if (redirectUriDesc) redirectUriDesc.textContent = '(T\u1ea1i tab Credentials > OAuth Client ID)';
        }
        
        const scopesContainer = document.getElementById('cred-required-scopes');
        if (scopes.length === 0) {
            scopesContainer.innerHTML = '<div class="am-empty am-scope-row" style="color:var(--text2)">ℹ️ Không có quyền nào được yêu cầu</div>';
        } else {
            scopesContainer.innerHTML = scopes.map(s => `
                <div class="am-scope-row">
                    <code class="am-scope-key">${s}</code>
                    <span class="am-scope-desc">${provScopes[s] || ''}</span>
                </div>
            `).join('');
        }
        
        // Determine required APIs for Cloud Console
        const apiContainerWrapper = document.getElementById('cred-setup-apis-container');
        const apiContainer = document.getElementById('cred-required-apis');
        if (providerKey === 'google' && scopes.length > 0) {
            const requiredApis = new Set();
            scopes.forEach(s => {
                if (s.includes('youtube')) requiredApis.add('YouTube Data API v3');
                if (s.includes('sheets')) requiredApis.add('Google Sheets API');
                if (s.includes('drive')) requiredApis.add('Google Drive API');
                if (s.includes('gmail')) requiredApis.add('Gmail API');
                if (s.includes('calendar')) requiredApis.add('Google Calendar API');
            });
            
            if (requiredApis.size > 0) {
                apiContainer.innerHTML = Array.from(requiredApis).map(api => `
                    <div class="am-scope-row" style="align-items:center; margin-bottom:4px;">
                        <span style="color:#00d4ff; font-size:1rem; line-height:1">🔌</span>
                        <span style="color:#e8e8f0; font-weight:600">${api}</span>
                    </div>
                `).join('');
                apiContainerWrapper.style.display = 'block';
            } else {
                apiContainerWrapper.style.display = 'none';
            }
        } else {
            if (apiContainerWrapper) apiContainerWrapper.style.display = 'none';
        }
        
        document.getElementById('cred-step-1').style.display = 'none';
        document.getElementById('cred-step-2').style.display = 'block';
        
        // Update Title
        const name = document.getElementById('cred-name').value || 'New App';
        document.getElementById('credential-modal-title').innerHTML = `Setup API: <span style="color:var(--cyan)">${name}</span>`;
    }
}

function toggleCredService(card) {
    const check = card.querySelector('.am-service-check');
    check.checked = !check.checked;
    card.classList.toggle('selected', check.checked);
}

function getSelectedCredScopes() {
    // Collect unique scopes from all selected services in the cred modal
    const scopes = new Set();
    document.querySelectorAll('#cred-services-list .am-service-check:checked').forEach(cb => {
        if (!cb.classList.contains('am-custom-check')) {
            (cb.dataset.scopes || '').split(',').filter(Boolean).forEach(s => scopes.add(s));
        }
    });
    
    // Add custom scopes if expanded
    const customInput = document.getElementById('am-custom-scopes-input');
    if (customInput && customInput.value.trim()) {
        const customCheck = customInput.closest('.am-service-card').querySelector('.am-custom-check');
        if (customCheck && customCheck.checked) {
            customInput.value.split(',').map(s => s.trim()).filter(Boolean).forEach(s => scopes.add(s));
        }
    }
    return [...scopes];
}

function copyAmText(text) {
    navigator.clipboard.writeText(text).then(() => {
        showToast('Đã copy vào clipboard!', 'success');
    }).catch(err => {
        showToast('Lỗi copy, vui lòng thử lại', 'error');
    });
}

function switchCredTab(tab) {
    document.querySelectorAll('.am-tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
    document.querySelectorAll('.am-tab-pane').forEach(p => p.classList.remove('active'));
    
    if (tab === 'oauth') document.getElementById('cred-tab-oauth').classList.add('active');
    else if (tab === 'json') document.getElementById('cred-tab-json').classList.add('active');
    else if (tab === 'manual') document.getElementById('cred-tab-manual').classList.add('active');
}

function handleJsonUpload(e) {
    const file = e.target.files[0];
    if (!file) return;
    document.getElementById('cred-json-filename').textContent = file.name;
    const reader = new FileReader();
    reader.onload = (ev) => {
        _jsonContent = ev.target.result;
        try {
            const parsed = JSON.parse(_jsonContent);
            if (parsed.client_email) {
                document.getElementById('cred-sa-email').value = parsed.client_email;
            }
        } catch (ex) {}
    };
    reader.readAsText(file);
}

async function saveCredential() {
    const editId = document.getElementById('cred-edit-id').value;
    const provider = document.getElementById('cred-provider').value;
    
    // Check if the manual tab is currently active
    const manualTabPane = document.getElementById('cred-tab-manual');
    const isManualTabActive = manualTabPane && manualTabPane.classList.contains('active');
    
    if (isManualTabActive && provider === 'facebook') {
        const manualId = document.getElementById('cred-manual-id').value.trim();
        const manualToken = document.getElementById('cred-manual-token').value.trim();
        const manualName = document.getElementById('cred-name').value.trim();
        
        if (!manualName || !manualToken) {
            showToast('Vui lòng điền Name và Token!', 'error');
            return;
        }
        
        let finalManualId = manualId;
        // Auto-extract ID/Username if user pastes a full Facebook link
        if (finalManualId.includes('facebook.com')) {
            try {
                const urlStr = finalManualId.startsWith('http') ? finalManualId : 'https://' + finalManualId;
                const url = new URL(urlStr);
                if (url.searchParams.has('id')) {
                    finalManualId = url.searchParams.get('id');
                } else {
                    const parts = url.pathname.split('/').filter(Boolean);
                    if (parts.length > 0) {
                        if (parts[0] === 'pages' || parts[0] === 'groups') {
                            finalManualId = parts[1] || parts[0];
                        } else if (parts[0] !== 'profile.php') {
                            finalManualId = parts[0];
                        }
                    }
                }
                document.getElementById('cred-manual-id').value = finalManualId;
            } catch (e) {
                console.log('FB URL parse skipped:', e);
            }
        }

        try {
            if (editId) {
                // Editing an existing manual credential. We update Name, Identifier (as client_id) and Scopes.
                // Modifying the actual token is not supported here directly, but they can update scopes.
                const putBody = {
                    name: manualName,
                    client_id: finalManualId,
                    scopes: getSelectedCredScopes()
                };
                const result = await apiPut(`/credentials/${editId}`, putBody);
                if (result.status === 'success') {
                    showToast('Cập nhật thành công!', 'success');
                    closeModal('modal-credential');
                    loadCredentials();
                    loadTokens();
                    loadProviders();
                } else {
                    showToast(result.message || result.detail || 'Error', 'error');
                }
            } else {
                // Creating new
                const body = {
                    provider: provider,
                    name: manualName,
                    identifier: finalManualId,
                    access_token: manualToken
                };
                const result = await apiPost('/credentials/manual', body);
                
                if (result.status === 'success') {
                    showToast(result.message || 'Saved successfully', 'success');
                    closeModal('modal-credential');
                    loadCredentials();
                    loadTokens();
                    loadProviders();
                } else {
                    showToast(result.message || result.detail || 'Error', 'error');
                }
            } // End of else (editId)
        } catch (e) {
            showToast(`Error: ${e.message}`, 'error');
        }
        return; // Exit early
    }

    const body = {
        provider: provider,
        name: document.getElementById('cred-name').value.trim(),
        client_id: document.getElementById('cred-client-id').value.trim(),
        client_secret: document.getElementById('cred-client-secret').value.trim(),
        credentials_json: _jsonContent,
        service_account_email: document.getElementById('cred-sa-email').value.trim(),
        scopes: getSelectedCredScopes(),
    };

    if (!body.name) {
        showToast('Please enter a name', 'error');
        return;
    }

    try {
        let result;
        if (editId) {
            result = await apiPut(`/credentials/${editId}`, body);
        } else {
            result = await apiPost('/credentials', body);
        }

        if (result.status === 'success') {
            showToast(result.message || 'Saved successfully', 'success');
            closeModal('modal-credential');
            loadCredentials();
            loadProviders();
        } else {
            showToast(result.message || result.detail || 'Error', 'error');
        }
    } catch (e) {
        showToast(`Error: ${e.message}`, 'error');
    }
}

async function deleteCredential(credId, name) {
    if (!confirm(`Delete credential "${name}"? This will also remove any associated token.`)) return;
    try {
        const result = await apiDelete(`/credentials/${credId}`);
        if (result.status === 'success') {
            showToast('Credential deleted', 'success');
            loadCredentials();
            loadTokens();
            loadProviders();
        } else {
            showToast(result.message || 'Error', 'error');
        }
    } catch (e) {
        showToast(`Error: ${e.message}`, 'error');
    }
}

// ── Authorize Modal (Simplified) ────────────────────────────────
function openAuthorizeModal(credId) {
    const cred = credentialsData.find(c => c.id === credId);
    if (!cred) return;

    document.getElementById('auth-cred-id').value = credId;
    document.getElementById('auth-cred-name').textContent = cred.name;
    document.getElementById('auth-cred-provider').textContent = cred.provider;

    // Get redirect URI
    const redirectUri = `${window.location.origin}/api/v1/auth-manager/oauth/callback`;
    document.getElementById('auth-redirect-uri').textContent = redirectUri;

    // Show saved scopes as read-only chips
    const provider = providersData.find(p => p.id === cred.provider);
    const provScopes = provider?.scopes || {};
    const chipsContainer = document.getElementById('auth-scopes-chips');
    const savedScopes = cred.scopes || [];
    
    if (savedScopes.length > 0) {
        chipsContainer.innerHTML = savedScopes.map(s => {
            const label = provScopes[s] || s;
            return `<span class="am-scope-chip-readonly">${label}</span>`;
        }).join('');
    } else {
        chipsContainer.innerHTML = '<span style="color:#ef4444;font-size:0.85rem">⚠️ Chưa cấu hình scopes. Chỉnh sửa credential để thêm quyền.</span>';
    }

    // Load browser profiles
    const profileSelect = document.getElementById('auth-browser-profile');
    profileSelect.innerHTML = '<option value="">🌐 Default Browser</option>';
    profilesData.forEach(p => {
        const name = p.name || p.profile_name || '';
        profileSelect.innerHTML += `<option value="${name}">${name}</option>`;
    });

    openModal('modal-authorize');
}

async function startAuthorize(action = 'open') {
    const credId = document.getElementById('auth-cred-id').value;
    const profile = document.getElementById('auth-browser-profile').value;
    const cred = credentialsData.find(c => c.id === credId);

    // Use credential's saved scopes directly
    const scopes = cred?.scopes || [];

    if (!scopes.length) {
        showToast('Credential chưa có scopes. Hãy chỉnh sửa credential và chọn dịch vụ trước.', 'error');
        return;
    }

    try {
        const result = await apiPost(`/credentials/${credId}/authorize`, {
            scopes,
            // Don't spawn playwright if user just wants to copy URL
            browser_profile: action === 'copy' ? '' : profile,
        });

        if (result.status === 'success') {
            closeModal('modal-authorize');
            const authUrl = result.auth_url;

            if (action === 'copy') {
                copyAmText(authUrl);
                // The copyAmText function already shows a toast, but we can override or add context
                pollForToken(credId, action, authUrl); 
                return;
            }

            if (profile) {
                // Playwright profile was requested — check server-side launch result
                const launch = result.browser_launch || {};
                if (launch.status === 'error') {
                    showToast(`❌ Không mở được profile "${profile}": ${launch.error}. Đang mở trình duyệt...`, 'error');
                    // Fallback: open from client-side
                    if (authUrl) window.open(authUrl, '_blank') || (window.location.href = authUrl);
                } else {
                    showToast(`⏳ Đã mở profile "${profile}". Vui lòng cấp quyền trên trang Google...`, 'success');
                }
            } else {
                // No profile — open from client-side
                if (authUrl) {
                    const popup = window.open(authUrl, '_blank');
                    if (!popup) {
                        // Popup blocked — redirect
                        window.location.href = authUrl;
                        return;
                    }
                }
                showToast('⏳ Đã mở trình duyệt. Vui lòng cấp quyền trên trang Google...', 'success');
            }

            // Poll for token arrival
            pollForToken(credId, 'open', authUrl);
        } else {
            showToast(result.message || result.detail || 'Error', 'error');
        }
    } catch (e) {
        showToast(`Error: ${e.message}`, 'error');
    }
}

let _pollTimer = null;
let _pollStartTime = null;

function cancelPolling() {
    if (_pollTimer) clearInterval(_pollTimer);
    _pollTimer = null;
    closeModal('modal-auth-waiting');
    showToast('Đã dừng chờ cấp quyền.', 'info');
}

function pollForToken(credId, action = 'open', authUrl = '') {
    let attempts = 0;
    const maxAttempts = 180; // 3 minutes
    if (_pollTimer) clearInterval(_pollTimer);
    
    // Pass to global so html onclick can use it
    window._currentAuthUrl = authUrl;

    // Capture all existing tokens' authorized_at times before we poll
    const prevTokens = typeof tokensData !== 'undefined' ? tokensData.filter(t => t.credential_id === credId) : [];
    const prevAuthTimes = prevTokens.map(t => t.authorized_at).filter(Boolean);

    // Update UI text based on action
    const msgEl = document.getElementById('am-waiting-message');
    const copyBtn = document.getElementById('am-waiting-copy-btn');
    if (msgEl) {
        if (action === 'copy') {
            msgEl.innerHTML = `Vui lòng dán (paste) đường link vừa copy vào trình duyệt của bạn và hoàn tất thủ tục đăng nhập.<br>Hệ thống sẽ tự nhận dạng sau khi hoàn thành...`;
        } else {
            msgEl.innerHTML = `Vui lòng đợi trình duyệt tự động mở và hoàn tất màn hình cấp quyền.<br>Cửa sổ này sẽ tự nhận dạng và đóng lại khi quá trình hoàn tất.`;
        }
    }
    if (copyBtn) {
        if (action === 'copy') copyBtn.classList.remove('hidden');
        else copyBtn.classList.add('hidden');
    }

    openModal('modal-auth-waiting');

    _pollTimer = setInterval(async () => {
        attempts++;
        if (attempts > maxAttempts) {
            clearInterval(_pollTimer);
            _pollTimer = null;
            closeModal('modal-auth-waiting');
            showToast('⏰ Đã quá thời gian chờ (Timeout).', 'error');
            return;
        }
        if (attempts < 3) return;

        try {
            const data = await apiGet('/tokens');
            const found = (data.tokens || []).find(t => {
                if (t.credential_id !== credId) return false;
                if (t.status !== 'active') return false;
                
                if (prevAuthTimes.length === 0) {
                    return true; 
                } else {
                    return t.authorized_at && !prevAuthTimes.includes(t.authorized_at);
                }
            });
            if (found) {
                clearInterval(_pollTimer);
                _pollTimer = null;
                closeModal('modal-auth-waiting');
                showToast(`✅ Authorized! Email: ${found.authorized_email || 'N/A'}`, 'success');
                loadCredentials();
                loadTokens();
                loadProviders();
            }
        } catch (e) {}
    }, 1000);
}

// ── Token Actions ───────────────────────────────────────────────
async function refreshToken(tokenId) {
    try {
        const result = await apiPost(`/tokens/${tokenId}/refresh`, {});
        if (result.status === 'success') {
            showToast('Token refreshed', 'success');
            loadTokens();
        } else {
            showToast(result.message || result.detail || 'Error', 'error');
        }
    } catch (e) {
        showToast(`Error: ${e.message}`, 'error');
    }
}

async function revokeToken(tokenId) {
    if (!confirm('Revoke this token? You will need to re-authorize.')) return;
    try {
        const result = await apiDelete(`/tokens/${tokenId}`);
        if (result.status === 'success') {
            showToast('Token revoked', 'success');
            loadTokens();
            loadCredentials();
            loadProviders();
        } else {
            showToast(result.message || result.detail || 'Error', 'error');
        }
    } catch (e) {
        showToast(`Error: ${e.message}`, 'error');
    }
}

// ── Modal Helpers ───────────────────────────────────────────────
function openModal(id) {
    document.getElementById(id).classList.remove('hidden');
}

function closeModal(id) {
    document.getElementById(id).classList.add('hidden');
}

// ── Toast ───────────────────────────────────────────────────────
function showToast(msg, type = 'success') {
    const el = document.createElement('div');
    el.className = `am-toast ${type}`;
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(() => { if (el.parentNode) el.parentNode.removeChild(el); }, 3000);
}
