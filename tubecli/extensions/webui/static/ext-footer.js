/**
 * TubeCLI Extension Footer — auto-inject at the bottom of any extension page.
 * 
 * Usage: Add to any extension HTML:
 *   <script src="/static/ext-footer.js"></script>
 * 
 * It fetches extension metadata from the API and renders a subtle inline footer.
 */
(function () {
    'use strict';

    const pathname = window.location.pathname;
    const API_BASE = window.location.origin;

    async function init() {
        try {
            const res = await fetch(`${API_BASE}/api/v1/extensions`);
            if (!res.ok) return;
            const data = await res.json();
            const extensions = data.extensions || [];

            // Find matching extension by page_url
            let ext = null;
            for (const e of extensions) {
                if (e.page_url && pathname.startsWith(e.page_url)) { ext = e; break; }
            }
            // Fallback: match by name in path
            if (!ext) {
                for (const e of extensions) {
                    const slug = e.name.replace(/_/g, '-');
                    if (pathname.includes(slug) || pathname.includes(e.name)) { ext = e; break; }
                }
            }
            if (!ext) return;
            renderFooter(ext);
            checkForUpdate(ext);
        } catch (err) {
            console.debug('[ext-footer]', err.message);
        }
    }

    function renderFooter(ext) {
        const name = ext.display_name || ext.name;
        const ver = ext.version || '?';
        const author = ext.author || 'TubeCreate';
        const donate = ext.donate || '';
        const homepage = ext.homepage || '';
        const license = ext.license || '';

        let parts = [];
        parts.push(`<span class="tcf-i">📦 ${esc(name)} <span class="tcf-v">v${esc(ver)}</span></span>`);
        parts.push(`<span class="tcf-i">👤 ${esc(author)}</span>`);
        if (license) parts.push(`<span class="tcf-i">📄 ${esc(license)}</span>`);
        if (homepage) parts.push(`<a class="tcf-i tcf-a" href="${escA(homepage)}" target="_blank">🔗 Homepage</a>`);
        if (donate) parts.push(`<a class="tcf-i tcf-d" href="${escA(donate)}" target="_blank">☕ Donate</a>`);

        // Create a non-fixed footer element appended to body
        const el = document.createElement('div');
        el.id = 'tcf';
        el.innerHTML = parts.join('<span class="tcf-s">·</span>');

        const style = document.createElement('style');
        style.textContent = `
            /* Footer palette lives in #tcf-scoped custom properties: the dark
               values are the defaults, and the two light blocks below (one for
               data-theme="light" set from ?theme=, one for prefers-color-scheme
               when a page is opened standalone) are verbatim copies of each
               other — CSS cannot share a declaration list between them. */
            #tcf {
                --tcf-bg: rgba(15,15,30,0.6);
                --tcf-line: rgba(100,100,180,0.1);
                --tcf-fg: rgba(180,180,200,0.45);
                --tcf-fg-hover: rgba(200,200,220,0.75);
                --tcf-ver-bg: rgba(99,102,241,0.12);
                --tcf-ver-fg: rgba(160,155,255,0.8);
                --tcf-sep: rgba(100,100,150,0.3);
                --tcf-link: rgba(100,200,255,0.6);
                --tcf-link-hover: rgba(100,200,255,1);
                --tcf-donate: rgba(251,191,36,0.85);
                display: flex;
                align-items: center;
                justify-content: center;
                gap: 8px;
                padding: 3px 12px;
                background: var(--tcf-bg);
                border-top: 1px solid var(--tcf-line);
                font-family: 'Inter', -apple-system, sans-serif;
                font-size: 0.68rem;
                color: var(--tcf-fg);
                flex-wrap: wrap;
            }
            :root[data-theme="light"] #tcf {
                --tcf-bg: rgba(255,255,255,0.6);
                --tcf-line: rgba(15,23,42,0.1);
                --tcf-fg: #64748b;
                --tcf-fg-hover: #1e293b;
                --tcf-ver-bg: rgba(82,118,235,0.12);
                --tcf-ver-fg: #7c5ce7;
                --tcf-sep: rgba(15,23,42,0.25);
                --tcf-link: #2563eb;
                --tcf-link-hover: #5276EB;
                --tcf-donate: #a16207;
            }
            @media (prefers-color-scheme: light) {
                :root:not([data-theme="dark"]) #tcf {
                    --tcf-bg: rgba(255,255,255,0.6);
                    --tcf-line: rgba(15,23,42,0.1);
                    --tcf-fg: #64748b;
                    --tcf-fg-hover: #1e293b;
                    --tcf-ver-bg: rgba(82,118,235,0.12);
                    --tcf-ver-fg: #7c5ce7;
                    --tcf-sep: rgba(15,23,42,0.25);
                    --tcf-link: #2563eb;
                    --tcf-link-hover: #5276EB;
                    --tcf-donate: #a16207;
                }
            }
            #tcf:hover { color: var(--tcf-fg-hover); }
            .tcf-i { display:inline-flex; align-items:center; gap:3px; white-space:nowrap; }
            .tcf-v { background:var(--tcf-ver-bg); color:var(--tcf-ver-fg); padding:0 4px; border-radius:3px; font-size:0.6rem; font-weight:600; }
            .tcf-s { color:var(--tcf-sep); margin:0 1px; }
            .tcf-a { color:var(--tcf-link); text-decoration:none; }
            .tcf-a:hover { color:var(--tcf-link-hover); }
            .tcf-d { color:var(--tcf-donate); text-decoration:none; background:rgba(245,158,11,0.1); padding:1px 7px; border-radius:4px; border:1px solid rgba(245,158,11,0.2); font-weight:600; }
            .tcf-d:hover { background:rgba(245,158,11,0.2); border-color:rgba(245,158,11,0.4); }
        `;
        document.head.appendChild(style);
        document.body.appendChild(el);
    }

    function esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
    function escA(s) { return s.replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;'); }

    function getSkippedExts() {
        try { return JSON.parse(localStorage.getItem('tcf_skip_updates') || '[]'); } catch(e) { return []; }
    }
    function skipExtUpdate(name) {
        var list = getSkippedExts();
        var key = (name || '').toLowerCase().replace(/ /g, '_');
        if (!list.includes(key)) { list.push(key); localStorage.setItem('tcf_skip_updates', JSON.stringify(list)); }
    }

    async function checkForUpdate(ext) {
        try {
            const notifyEnabled = localStorage.getItem('ext_update_notifications') === 'true';
            if (!notifyEnabled) return;

            var extName = (ext.name || '').toLowerCase().replace(/ /g, '_');
            if (getSkippedExts().includes(extName)) return;
            const res = await fetch(`${API_BASE}/api/v1/market/check-updates`);
            if (!res.ok) return;
            const data = await res.json();
            const updates = data.updates || [];
            const match = updates.find(u => (u.name || '').toLowerCase().replace(/ /g, '_') === extName);
            if (!match) return;
            renderUpdateBanner(ext, match);
        } catch (err) {
            console.debug('[ext-footer] update check:', err.message);
        }
    }

    function renderUpdateBanner(ext, update) {
        const banner = document.createElement('div');
        banner.id = 'tcf-update';
        banner.innerHTML = '<div class="tcf-upd-left">'
            + '<span class="tcf-upd-icon">⬆️</span>'
            + '<div class="tcf-upd-info">'
            + '<div class="tcf-upd-title">Bản cập nhật mới có sẵn!</div>'
            + '<div class="tcf-upd-ver">v' + esc(update.local_version) + ' → v' + esc(update.market_version) + '</div>'
            + '</div></div>'
            + '<div class="tcf-upd-right">'
            + '<button id="tcf-update-btn" class="tcf-upd-btn">⬆️ Cập nhật ngay</button>'
            + '<button class="tcf-upd-never" title="Không bao giờ cập nhật extension này">🚫 Không cập nhật nữa</button>'
            + '<button class="tcf-upd-dismiss" title="Bỏ qua lần này">✕</button>'
            + '</div>';

        const style = document.createElement('style');
        style.textContent = `
            /* Same two-block light pattern as #tcf: dark defaults on the
               element, verbatim light copies for data-theme and the OS query. */
            #tcf-update {
                --tcf-upd-fg: #e8e8f0;
                --tcf-upd-fg-soft: rgba(200,200,220,0.65);
                --tcf-upd-fg-dim: rgba(200,200,220,0.5);
                --tcf-upd-never: rgba(239,130,130,0.85);
                --tcf-upd-red: #ef4444;
                display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:10px;
                padding:10px 20px;
                background:linear-gradient(135deg,rgba(245,158,11,0.15),rgba(59,130,246,0.08));
                border-bottom:1px solid rgba(245,158,11,0.3);
                font-family:'Inter',-apple-system,sans-serif; font-size:0.85rem; color:var(--tcf-upd-fg);
                position:sticky; top:0; z-index:9999;
                animation: tcfSlideDown 0.3s ease;
            }
            :root[data-theme="light"] #tcf-update {
                --tcf-upd-fg: #1e293b;
                --tcf-upd-fg-soft: #475569;
                --tcf-upd-fg-dim: #64748b;
                --tcf-upd-never: #dc2626;
                --tcf-upd-red: #dc2626;
            }
            @media (prefers-color-scheme: light) {
                :root:not([data-theme="dark"]) #tcf-update {
                    --tcf-upd-fg: #1e293b;
                    --tcf-upd-fg-soft: #475569;
                    --tcf-upd-fg-dim: #64748b;
                    --tcf-upd-never: #dc2626;
                    --tcf-upd-red: #dc2626;
                }
            }
            @keyframes tcfSlideDown { from{transform:translateY(-100%);opacity:0} to{transform:translateY(0);opacity:1} }
            .tcf-upd-left { display:flex; align-items:center; gap:10px; }
            .tcf-upd-icon { font-size:1.3rem; }
            .tcf-upd-title { font-weight:600; font-size:0.88rem; }
            .tcf-upd-ver { font-size:0.75rem; color:var(--tcf-upd-fg-soft); margin-top:1px; }
            .tcf-upd-right { display:flex; align-items:center; gap:8px; }
            .tcf-upd-btn {
                padding:6px 16px; border:none; border-radius:8px; font-size:0.82rem; font-weight:600;
                background:linear-gradient(135deg,#22c55e,#10b981); color:#fff; cursor:pointer;
                transition:all 0.2s; box-shadow:0 2px 8px rgba(34,197,94,0.3);
            }
            .tcf-upd-btn:hover { transform:translateY(-1px); box-shadow:0 4px 16px rgba(34,197,94,0.4); }
            .tcf-upd-btn:disabled { opacity:0.6; cursor:default; transform:none; }
            .tcf-upd-never {
                padding:6px 12px; border:1px solid rgba(239,68,68,0.3); border-radius:8px; font-size:0.75rem; font-weight:500;
                background:rgba(239,68,68,0.08); color:var(--tcf-upd-never); cursor:pointer; transition:all 0.2s;
            }
            .tcf-upd-never:hover { background:rgba(239,68,68,0.18); border-color:rgba(239,68,68,0.5); color:var(--tcf-upd-red); }
            .tcf-upd-dismiss {
                background:none; border:none; color:var(--tcf-upd-fg-dim); font-size:1rem; cursor:pointer;
                padding:4px 8px; border-radius:4px; transition:all 0.2s;
            }
            .tcf-upd-dismiss:hover { color:var(--tcf-upd-red); background:rgba(239,68,68,0.1); }
        `;
        document.head.appendChild(style);

        // Insert at very top of body
        if (document.body.firstChild) {
            document.body.insertBefore(banner, document.body.firstChild);
        } else {
            document.body.appendChild(banner);
        }

        // Dismiss button (skip this time)
        banner.querySelector('.tcf-upd-dismiss').addEventListener('click', function() {
            banner.style.animation = 'none';
            banner.style.transition = 'transform 0.2s, opacity 0.2s';
            banner.style.transform = 'translateY(-100%)';
            banner.style.opacity = '0';
            setTimeout(function() { banner.remove(); }, 200);
        });

        // Never update button
        banner.querySelector('.tcf-upd-never').addEventListener('click', function() {
            if (!confirm('Bạn chắc chắn muốn tắt thông báo cập nhật vĩnh viễn cho "' + (ext.display_name || ext.name) + '"?\n\nBạn vẫn có thể bật lại trong Settings.')) return;
            skipExtUpdate(ext.name);
            banner.style.animation = 'none';
            banner.style.transition = 'transform 0.2s, opacity 0.2s';
            banner.style.transform = 'translateY(-100%)';
            banner.style.opacity = '0';
            setTimeout(function() { banner.remove(); }, 200);
        });

        // Update button
        banner.querySelector('#tcf-update-btn').addEventListener('click', async function() {
            const btn = this;
            btn.disabled = true;
            btn.textContent = '\u23f3 \u0110ang c\u1eadp nh\u1eadt...';

            try {
                // Try git pull first
                let result = await fetch(`${API_BASE}/api/v1/market/items/${encodeURIComponent(ext.name)}/update-local`, {
                    method: 'POST', headers: {'Content-Type':'application/json'}, body: '{}'
                }).then(r => r.json()).catch(() => null);

                if (!result || result.status === 'error') {
                    // Fallback: re-download from market
                    if (update.public_id) {
                        const detail = await fetch(`${API_BASE}/api/v1/market/items/${update.public_id}`).then(r=>r.json()).catch(()=>null);
                        if (detail && detail.item) {
                            result = await fetch(`${API_BASE}/api/v1/market/items/${update.public_id}/install`, {
                                method: 'POST',
                                headers: {'Content-Type':'application/json'},
                                body: JSON.stringify({
                                    item_data: JSON.stringify(detail.item.item_data || {}),
                                    item_name: ext.name,
                                    category: 'extension',
                                    force_update: true
                                })
                            }).then(r=>r.json()).catch(()=>null);
                        }
                    }
                }

                if (result && result.status === 'success') {
                    btn.textContent = '\u2705 C\u1eadp nh\u1eadt th\u00e0nh c\u00f4ng!';
                    btn.style.background = '#22c55e';
                    // Update version display in footer
                    const vEl = document.querySelector('.tcf-v');
                    if (vEl) vEl.textContent = 'v' + update.market_version;
                    setTimeout(() => {
                        banner.querySelector('.tcf-upd-title').textContent = '\u2705 \u0110\u00e3 c\u1eadp nh\u1eadt! Refresh trang \u0111\u1ec3 s\u1eed d\u1ee5ng b\u1ea3n m\u1edbi.';
                        banner.querySelector('.tcf-upd-ver').textContent = 'v' + update.market_version;
                        btn.textContent = '\ud83d\udd04 Refresh';
                        btn.disabled = false;
                        btn.onclick = () => window.location.reload();
                    }, 1500);
                } else {
                    const msg = (result && (result.message || result.detail)) || 'Update failed';
                    btn.textContent = '\u274c L\u1ed7i: ' + msg;
                    btn.style.background = '#ef4444';
                    setTimeout(() => { btn.textContent = '\u2b06\ufe0f Th\u1eed l\u1ea1i'; btn.style.background = ''; btn.disabled = false; }, 3000);
                }
            } catch (e) {
                btn.textContent = '\u274c L\u1ed7i k\u1ebft n\u1ed1i';
                btn.style.background = '#ef4444';
                setTimeout(() => { btn.textContent = '\u2b06\ufe0f Th\u1eed l\u1ea1i'; btn.style.background = ''; btn.disabled = false; }, 3000);
            }
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
