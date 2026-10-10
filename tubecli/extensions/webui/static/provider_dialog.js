// Hộp cài đặt provider (Cloud API Keys → ⚙ / «Set up») — một khung cho mọi provider (9/10/2026).
//
// Thay hộp 420px cũ (checkbox trần + textarea «url | key | seats») bằng hộp rộng có tab:
//   Accounts (Muse) · Videos at once (Muse) · Other machines (Muse) · Endpoint (9Router) · Models (mọi provider).
// Người dùng góp ý: «bề ngang to mà dialog xài tiết kiệm, checkbox classic». 4 vai chấm mockup → chốt: xương B
// (bảng tài khoản + cột tóm tắt) + thẻ máy khác của C; huy hiệu nói thật; Discard chỉ khi có thay đổi; chỉ-remote.
//
// Ghi đè editProviderSettings của app.js (hàm cũ vẫn còn để các helper như _renderEndpointPanel, renderEditModelsList
// dùng chung). Mọi chữ qua T('cloud_api.pv_*') — locales của cloud_api (en + vi).
(function () {
    'use strict';
    const PV = { provider: '', meta: {}, st: null, status: null, orig: '', origModels: [], tab: '', search: '',
                 showAll: false, nodeStatus: {}, lastTest: null, newKey: '', saving: false, helpHidden: false,
                 addError: '' };
    const $ = (id) => document.getElementById(id);
    const tr = (k, vars) => T('cloud_api.pv_' + k, vars);
    const E = (s) => esc(String(s == null ? '' : s));

    // ── helpers ───────────────────────────────────────────────────────────
    function hostOf(url) { try { return new URL(url).host; } catch (e) { return url; } }
    function ago(ts) {
        if (!ts) return '—';
        const s = Math.max(0, Date.now() / 1000 - ts);
        if (s < 60) return tr('ago_now');
        if (s < 3600) return tr('ago_min', { n: Math.round(s / 60) });
        if (s < 86400) return tr('ago_hour', { n: Math.round(s / 3600) });
        return tr('ago_day', { n: Math.round(s / 86400) });
    }
    function pendingPool() {
        const st = PV.st || {};
        const main = st.profile || '';
        const extra = (st.extra_profiles || []).filter(n => n && n !== main);
        return main ? [main].concat(extra) : extra;
    }
    function remoteSeats() { return (PV.st?.remotes || []).reduce((a, r) => a + (parseInt(r.seats, 10) || 1), 0); }
    function snapshot() {
        const st = PV.st || {};
        return JSON.stringify({ p: st.profile || '', e: (st.extra_profiles || []).slice().sort(), l: st.lanes || 1,
                                t: st.turns_per_chat || 0, r: (st.remotes || []).map(r => [r.base_url, r.key || '', r.seats || 1]) });
    }
    function museDirty() { return !!PV.meta.browser_session && PV.st && snapshot() !== PV.orig; }
    function modelsDirty() { return JSON.stringify(currentEditModels) !== JSON.stringify(PV.origModels); }
    function dirty() { return museDirty() || modelsDirty(); }
    function changeList() {
        const out = [];
        if (museDirty()) {
            const o = JSON.parse(PV.orig), st = PV.st;
            const was = (o.p ? [o.p] : []).concat(o.e), now = pendingPool();
            now.filter(n => !was.includes(n)).forEach(n => out.push(tr('chg_on', { name: n })));
            was.filter(n => !now.includes(n)).forEach(n => out.push(tr('chg_off', { name: n })));
            if (o.p !== (st.profile || '') && st.profile && was.includes(st.profile)) out.push(tr('chg_main', { name: st.profile }));
            if (o.l !== (st.lanes || 1)) out.push(tr('chg_lanes', { a: o.l, b: st.lanes || 1 }));
            if (o.t !== (st.turns_per_chat || 0)) out.push(tr('chg_turns'));
            const wasR = o.r.map(r => r[0]), nowR = (st.remotes || []).map(r => r.base_url);
            const added = nowR.filter(u => !wasR.includes(u)).length, removed = wasR.filter(u => !nowR.includes(u)).length;
            if (added) out.push(tr('chg_node_add', { n: added }));
            if (removed) out.push(tr('chg_node_del', { n: removed }));
            if (!added && !removed && JSON.stringify(o.r) !== JSON.stringify((st.remotes || []).map(r => [r.base_url, r.key || '', r.seats || 1]))) out.push(tr('chg_node_edit'));
        }
        if (modelsDirty()) out.push(tr('chg_models'));
        return out;
    }
    function statusRow(name) { return ((PV.status && PV.status.pool) || []).find(r => r.profile === name) || null; }
    function savedPool() { const o = PV.orig ? JSON.parse(PV.orig) : { p: '', e: [] }; return (o.p ? [o.p] : []).concat(o.e); }

    // ── mount: biến hộp «Models» cũ thành khung tab, giữ các phần tử cũ của danh sách model ──
    function mount() {
        const modal = $('modal-edit-models');
        const content = modal.querySelector('.modal-content');
        content.classList.add('modal-provider');
        content.style.maxWidth = '';
        const body = modal.querySelector('.modal-body');
        if ($('pv-shell')) return;
        body.removeAttribute('style');
        const legacy = Array.from(body.children);
        const shell = document.createElement('div');
        shell.id = 'pv-shell';
        shell.innerHTML = `
            <div id="pv-head"></div>
            <div id="pv-tabs" role="tablist"></div>
            <div id="pv-panes">
                <div id="pv-pane-accounts" class="pv-pane" role="tabpanel"></div>
                <div id="pv-pane-lanes" class="pv-pane" role="tabpanel"></div>
                <div id="pv-pane-machines" class="pv-pane" role="tabpanel"></div>
                <div id="pv-pane-endpoint" class="pv-pane" role="tabpanel"></div>
                <div id="pv-pane-models" class="pv-pane" role="tabpanel"><div id="pv-models-intro" class="pv-hint"></div></div>
            </div>`;
        body.appendChild(shell);
        const mp = $('pv-pane-models');
        legacy.forEach(el => {
            if (el.id === 'provider-muse-panel') { el.remove(); return; }
            if (el.id === 'provider-endpoint-panel') { $('pv-pane-endpoint').appendChild(el); return; }
            mp.appendChild(el);
        });
        const foot = modal.querySelector('.modal-actions');
        foot.className = 'modal-actions pv-foot';
        foot.removeAttribute('style');
        foot.innerHTML = `
            <div id="pv-foot-status" class="pv-foot-status"></div>
            <div style="flex:1"></div>
            <button type="button" class="btn-secondary" id="pv-btn-discard" onclick="window.pvDiscard()"></button>
            <button type="button" class="btn-secondary" id="pv-btn-test" onclick="window.pvTestChat(this)"></button>
            <button type="button" class="btn-primary" id="pv-btn-save" onclick="window.pvSave(this)"></button>`;
        const closeBtn = modal.querySelector('.modal-header .btn-close');
        if (closeBtn) closeBtn.setAttribute('onclick', 'window.pvClose()');
    }

    // ── mở hộp ────────────────────────────────────────────────────────────
    window.editProviderSettings = async function (provider, currentModelsStr) {
        currentEditProvider = provider;
        currentEditModels = currentModelsStr ? currentModelsStr.split(',').map(m => m.trim()).filter(Boolean) : [];
        PV.provider = provider;
        PV.meta = (window._cloudProviders || []).find(p => p.id === provider) || { id: provider, name: provider.toUpperCase(), models: [] };
        PV.origModels = currentEditModels.slice();
        PV.st = null; PV.status = null; PV.orig = ''; PV.search = ''; PV.showAll = false; PV.nodeStatus = {};
        PV.lastTest = null; PV.newKey = ''; PV.addError = '';
        try { PV.helpHidden = localStorage.getItem('pv_help_hidden_' + provider) === '1'; } catch (e) { PV.helpHidden = false; }
        mount();
        PV.tab = PV.meta.browser_session ? 'accounts' : (PV.meta.base_url_editable ? 'endpoint' : 'models');
        const inp = $('add-model-input');
        if (inp) { inp.value = ''; inp.placeholder = currentEditModels[0] || (PV.meta.models || [])[0] || 'model-id'; }
        const tp = $('model-test-panel'); if (tp) tp.style.display = 'none';
        $('modal-edit-models').classList.remove('hidden');
        // Provider chỉ có tab Models (Gemini, OpenAI…) → hộp cao vừa nội dung, không cao 86vh trống.
        $('modal-edit-models').querySelector('.modal-content').classList.toggle('pv-compact', !PV.meta.browser_session);
        renderHead(); renderTabs(); renderPanes(); renderFoot();
        if (PV.meta.base_url_editable) { _renderEndpointPanel(); const ep = $('provider-endpoint-panel'); if (ep) $('pv-pane-endpoint').appendChild(ep); }
        _renderModelsSourceNote();
        renderEditModelsList();
        if (PV.meta.browser_session) {
            // Cài đặt về nhanh → vẽ ngay; trạng thái đăng nhập (hỏi từng hồ sơ đang mở, có thể vài giây) về sau → vẽ lại dòng.
            const opened = ++PV.openSeq;
            await loadMuse();
            if (opened !== PV.openSeq) return;
            renderHead(); renderTabs(); renderPanes(); renderFoot();
            refreshStatus().then(() => { if (opened === PV.openSeq) { renderHead(); renderAccountRows(); } });
        }
    };
    PV.openSeq = 0;

    async function loadMuse() {
        try { PV.st = await apiGet('/api/v1/muse/settings') || {}; } catch (e) { PV.st = {}; }
        PV.st.extra_profiles = (PV.st.extra_profiles || []).slice();
        PV.st.remotes = (PV.st.remotes || []).map(r => ({ base_url: r.base_url, key: r.key || '', seats: r.seats || 1 }));
        PV.orig = snapshot();
    }
    async function refreshStatus() {
        try { PV.status = await apiGet('/api/v1/muse/status') || {}; } catch (e) { PV.status = {}; }
    }

    // ── header + badge nói thật ───────────────────────────────────────────
    function badge() {
        const m = PV.meta;
        if (!m.browser_session) {
            return m.has_key ? ['green', tr('badge_key_ok', { n: m.key_count || 1 })] : ['grey', tr('badge_no_key')];
        }
        if (!PV.st) return ['grey', tr('badge_loading')];
        const saved = savedPool();
        const remotes = (PV.st.remotes || []).length;
        if (!saved.length && remotes) return ['purple', tr('badge_remote_only', { n: remotes, s: remoteSeats() })];
        if (!saved.length) return ['grey', tr('badge_not_set')];
        const rows = (PV.status && PV.status.pool) || [];
        const bad = rows.filter(r => r.logged_in === false).length;
        if (bad) return ['red', tr('badge_need_signin', { n: bad })];
        const total = saved.length * (PV.st.lanes || 1) + remoteSeats();
        // Hồ sơ đang ĐÓNG không có trạng thái (tự mở khi cần) — có ít nhất một hồ sơ «Yes» và không hồ sơ nào «No» là chạy được.
        if (rows.some(r => r.logged_in === true)) return ['green', tr('badge_working', { n: total })];
        return ['grey', tr('badge_unchecked')];
    }
    function renderHead() {
        const m = PV.meta;
        const [kind, text] = badge();
        const title = $('edit-models-title');
        if (title) title.innerHTML = `<span class="pv-avatar">${E((m.name || m.id || '?').slice(0, 1).toUpperCase())}</span>${E(m.name || m.id)} <span class="pv-badge pv-badge-${kind}"><span class="pv-dot"></span>${E(text)}</span>`;
        const sub = m.browser_session ? tr('sub_muse') : (m.base_url_editable ? tr('sub_endpoint') : tr('sub_key'));
        $('pv-head').innerHTML = `<div class="pv-sub">${E(sub)}</div>`;
    }
    function tabs() {
        const m = PV.meta, out = [];
        if (m.browser_session) {
            out.push(['accounts', tr('tab_accounts'), pendingPool().length ? tr('tab_count_on', { n: pendingPool().length }) : '']);
            out.push(['lanes', tr('tab_lanes'), '']);
            out.push(['machines', tr('tab_machines'), (PV.st?.remotes || []).length ? String((PV.st.remotes || []).length) : '']);
        }
        if (m.base_url_editable) out.push(['endpoint', tr('tab_endpoint'), '']);
        out.push(['models', tr('tab_models'), String(currentEditModels.length)]);
        return out;
    }
    function renderTabs() {
        const list = tabs();
        $('pv-tabs').innerHTML = list.length > 1 ? list.map(([id, label, count]) =>
            `<button type="button" role="tab" class="pv-tab ${PV.tab === id ? 'on' : ''}" aria-selected="${PV.tab === id}" onclick="window.pvTab('${id}')">${E(label)}${count ? ` <span class="pv-count">${E(count)}</span>` : ''}</button>`).join('') : '';
        document.querySelectorAll('#pv-panes .pv-pane').forEach(p => { p.classList.toggle('on', p.id === 'pv-pane-' + PV.tab); });
    }
    window.pvTab = function (id) { PV.tab = id; renderTabs(); renderPanes(); };

    function renderPanes() {
        if (PV.meta.browser_session) { renderAccounts(); renderLanes(); renderMachines(); }
        const intro = $('pv-models-intro');
        if (intro) intro.textContent = PV.meta.browser_session ? tr('models_intro_muse') : tr('models_intro');
        const refresh = $('btn-refresh-models');
        if (refresh) refresh.style.display = PV.meta.browser_session ? 'none' : '';
        const note = $('models-source-note');          // «bấm Lấy từ API» vô nghĩa với provider không có API
        if (note) note.style.display = PV.meta.browser_session ? 'none' : '';
    }

    // ── Accounts ──────────────────────────────────────────────────────────
    function renderAccounts() {
        const pane = $('pv-pane-accounts');
        if (!PV.st) { pane.innerHTML = `<div class="pv-hint">${E(tr('loading'))}</div>`; return; }
        const st = PV.st, pool = pendingPool(), remotes = (st.remotes || []).length;
        let banner = '';
        if (!pool.length && remotes) banner = `<div class="pv-banner pv-banner-info">${E(tr('acc_remote_only', { n: remotes, s: remoteSeats() }))}</div>`;
        else if (!pool.length) banner = `<div class="pv-banner pv-banner-warn">${E(tr('acc_none'))} <a href="#" onclick="window.pvTab('machines');return false;">${E(tr('acc_none_link'))}</a></div>`;
        pane.innerHTML = `
            ${banner}
            <div class="pv-two">
              <div class="pv-main">
                <div class="pv-toolbar">
                  <div>
                    <div class="pv-h">${E(tr('acc_title'))}</div>
                    <div class="pv-hint">${E(tr('acc_hint'))}</div>
                  </div>
                  <div style="flex:1"></div>
                  <label class="pv-search"><span class="material-symbols-outlined" style="font-size:16px">search</span>
                    <input type="search" id="pv-acc-search" value="${E(PV.search)}" placeholder="${E(tr('acc_search', { n: (st.profiles || []).length }))}" oninput="window.pvSearch(this.value)" aria-label="${E(tr('acc_search', { n: (st.profiles || []).length }))}"></label>
                  <button type="button" class="pv-btn" onclick="window.pvCheck(this)">${E(tr('acc_check'))}</button>
                </div>
                <div class="pv-table">
                  <div class="pv-row pv-row-head">
                    <div class="pv-th">${E(tr('col_use'))}</div><div class="pv-th">${E(tr('col_profile'))}</div><div class="pv-th">${E(tr('col_signed'))}</div>
                    <div class="pv-th">${E(tr('col_role'))}</div><div class="pv-th">${E(tr('col_last'))}</div>
                  </div>
                  <div id="pv-acc-rows"></div>
                </div>
                <div class="pv-hint pv-note"><span class="material-symbols-outlined" style="font-size:15px;color:var(--orange)">info</span>${E(tr('acc_note'))}</div>
              </div>
              <div class="pv-side" id="pv-acc-side"></div>
            </div>`;
        renderAccountRows();
        renderSide();
    }
    function renderAccountRows() {
        const st = PV.st, box = $('pv-acc-rows');
        if (!box) return;
        const pool = pendingPool(), saved = savedPool();
        const all = (st.profiles || []).slice();
        pool.forEach(n => { if (!all.includes(n)) all.unshift(n); });
        const q = PV.search.trim().toLowerCase();
        let rows = all.filter(n => !q || n.toLowerCase().includes(q));
        rows.sort((a, b) => (pool.indexOf(a) === -1 ? 1 : 0) - (pool.indexOf(b) === -1 ? 1 : 0) || (pool.indexOf(a) - pool.indexOf(b)) || a.localeCompare(b));
        const others = rows.filter(n => !pool.includes(n));
        let hidden = 0;
        if (!q && !PV.showAll && others.length > 6) { hidden = others.length - 6; rows = rows.filter(n => pool.includes(n) || others.indexOf(n) < 6); }
        const html = rows.map(n => {
            const on = pool.includes(n), isMain = n === st.profile, s = statusRow(n), inSaved = saved.includes(n);
            let signed;
            if (!inSaved) signed = `<span class="pv-mut">${E(on ? tr('signed_after_save') : tr('signed_unknown'))}</span>`;
            else if (!s) signed = `<span class="pv-mut">${E(tr('signed_unknown'))}</span>`;
            else if (s.logged_in === true) signed = `<span class="pv-ok"><span class="pv-dot"></span>${E(tr('signed_yes'))}</span>`;
            else if (s.logged_in === false) signed = `<span class="pv-bad"><span class="pv-dot"></span>${E(tr('signed_no'))}</span> <a href="#" class="pv-link" onclick="window.pvOpenProfile('${E(n)}', this);return false;">${E(tr('signed_open'))}</a>`;
            else if (!s.running) signed = `<span class="pv-mut"><span class="pv-dot"></span>${E(tr('signed_closed'))}</span>`;
            else signed = `<span class="pv-mut">${E(s.message || tr('signed_unknown'))}</span>`;
            const role = isMain ? `<span class="pv-tag pv-tag-main">${E(tr('role_main'))}</span>`
                : on ? `<button type="button" class="pv-link-btn" onclick="window.pvSetMain('${E(n)}')">${E(tr('role_set_main'))}</button>`
                : `<span class="pv-mut">—</span>`;
            return `<div class="pv-row ${on ? 'on' : ''}">
                <div><label class="toggle-switch" title="${E(tr('col_use'))} ${E(n)}"><input type="checkbox" ${on ? 'checked' : ''} onchange="window.pvToggle('${E(n)}', this.checked)" aria-label="${E(tr('col_use'))} ${E(n)}"><span class="toggle-slider"></span></label></div>
                <div class="pv-name" title="${E(n)}">${E(n)}</div>
                <div>${signed}</div>
                <div>${role}</div>
                <div class="pv-mut" title="${E(tr('col_last_hint'))}">${E(s ? (s.busy_for > 600 ? tr('busy_for', { n: Math.round(s.busy_for / 60) }) : ago(s.last_ok)) : '—')}</div>
            </div>`;
        }).join('');
        box.innerHTML = (html || `<div class="pv-empty">${E(tr('acc_empty'))}</div>`) +
            (hidden ? `<a href="#" class="pv-more" onclick="window.pvShowAll();return false;">${E(tr('acc_more', { n: hidden }))}</a>` : '');
    }
    function renderSide() {
        const box = $('pv-acc-side');
        if (!box || !PV.st) return;
        const st = PV.st, pool = pendingPool(), lanes = st.lanes || 1;
        const local = pool.length * lanes, remote = remoteSeats(), total = local + remote;
        const bars = Array.from({ length: Math.min(12, total) }, (_, i) => `<span class="pv-seat ${i < local ? 'local' : 'remote'}"></span>`).join('');
        const lt = PV.lastTest;
        const testLine = !lt ? tr('side_no_test') : lt.ok ? tr('side_test_ok', { s: lt.seconds }) : tr('side_test_fail', { m: lt.message || '' });
        box.innerHTML = `
            <div class="pv-card">
              <div class="pv-th">${E(tr('side_now'))}</div>
              <div class="pv-big">${E(tr('side_total', { n: total }))}</div>
              <div class="pv-seats">${bars || `<span class="pv-mut">${E(tr('side_zero'))}</span>`}</div>
              <div class="pv-hint"><span class="pv-dot pv-dot-local"></span>${E(tr('side_local', { n: pool.length, l: lanes }))}</div>
              <div class="pv-hint"><span class="pv-dot pv-dot-remote"></span>${E(tr('side_remote', { n: (st.remotes || []).length, s: remote }))}</div>
              <div class="pv-hint pv-sep ${lt ? (lt.ok ? 'pv-ok' : 'pv-bad') : ''}">${E(testLine)}</div>
            </div>
            ${PV.helpHidden ? `<button type="button" class="pv-link-btn" onclick="window.pvHelp(true)">${E(tr('help_show'))}</button>` : `
            <div class="pv-card">
              <div class="pv-th" style="display:flex;align-items:center"><span>${E(tr('help_title'))}</span><span style="flex:1"></span><button type="button" class="pv-link-btn" onclick="window.pvHelp(false)">${E(tr('help_hide'))}</button></div>
              <ol class="pv-steps">
                <li>${E(tr('help_1'))}</li><li>${E(tr('help_2'))}</li><li>${E(tr('help_3'))}</li><li>${E(tr('help_4'))}</li>
              </ol>
            </div>`}
            <div class="pv-card">
              <div class="pv-th">${E(tr('speed_title'))}</div>
              <div class="pv-hint">${E(tr('speed_hint'))}</div>
              <button type="button" class="pv-btn" onclick="window.pvTab('machines')">${E(tr('speed_btn'))}</button>
            </div>`;
    }
    window.pvSearch = function (v) { PV.search = v || ''; renderAccountRows(); };
    window.pvShowAll = function () { PV.showAll = true; renderAccountRows(); };
    window.pvHelp = function (show) {
        PV.helpHidden = !show;
        try { localStorage.setItem('pv_help_hidden_' + PV.provider, show ? '0' : '1'); } catch (e) { /* riêng tư */ }
        renderSide();
    };
    window.pvToggle = function (name, on) {
        const st = PV.st;
        if (on) { if (!st.profile) st.profile = name; else if (!st.extra_profiles.includes(name)) st.extra_profiles.push(name); }
        else if (name === st.profile) { st.profile = st.extra_profiles.shift() || ''; }
        else st.extra_profiles = st.extra_profiles.filter(n => n !== name);
        renderTabs(); renderAccountRows(); renderSide(); renderFoot();
    };
    window.pvSetMain = function (name) {
        const st = PV.st;
        st.extra_profiles = st.extra_profiles.filter(n => n !== name);
        if (st.profile && st.profile !== name) st.extra_profiles.unshift(st.profile);
        st.profile = name;
        renderAccountRows(); renderFoot();
    };
    window.pvCheck = async function (btn) {
        const orig = btn.textContent; btn.disabled = true; btn.textContent = '⏳';
        await refreshStatus();
        btn.disabled = false; btn.textContent = orig;
        renderHead(); renderAccountRows();
        foot(tr('checked_at', { t: new Date().toLocaleTimeString() }), null);
    };
    window.pvOpenProfile = async function (name, a) {
        if (a) a.textContent = '⏳';
        try {
            const r = await apiPost('/api/v1/browser/launch', { profile: name, manual: true });
            const bad = r && (r.error || (r.detail && (r.detail.message || r.detail)));
            foot(bad ? '❌ ' + (typeof bad === 'string' ? bad : JSON.stringify(bad)) : tr('opened', { name }), !bad);
        } catch (e) { foot('❌ ' + e.message, false); }
        if (a) a.textContent = tr('signed_open');
    };

    // ── Videos at once ────────────────────────────────────────────────────
    function renderLanes() {
        const pane = $('pv-pane-lanes');
        if (!PV.st) { pane.innerHTML = ''; return; }
        const st = PV.st, lanes = st.lanes || 1, max = st.max_lanes || 3, pool = pendingPool().length;
        pane.innerHTML = `
            <div class="pv-card pv-narrow">
              <div class="pv-h">${E(tr('lanes_title'))}</div>
              <div class="pv-hint">${E(tr('lanes_hint'))}</div>
              <div class="pv-stepper-row">
                <div class="pv-stepper">
                  <button type="button" aria-label="${E(tr('fewer'))}" onclick="window.pvLanes(-1)" ${lanes <= 1 ? 'disabled' : ''}>−</button>
                  <span>${lanes}</span>
                  <button type="button" aria-label="${E(tr('more'))}" onclick="window.pvLanes(1)" ${lanes >= max ? 'disabled' : ''}>+</button>
                </div>
                <div class="pv-hint">${E(tr('lanes_math', { a: pool, l: lanes, n: pool * lanes, r: remoteSeats(), t: pool * lanes + remoteSeats() }))}</div>
              </div>
            </div>
            <div class="pv-card pv-narrow">
              <div class="pv-h">${E(tr('turns_title'))}</div>
              <div class="pv-hint">${E(tr('turns_hint'))}</div>
              <input type="number" class="pv-input" style="width:110px" min="1" max="${st.max_turns_per_chat || 100}" value="${st.turns_per_chat || st.default_turns_per_chat || 10}" onchange="window.pvTurns(this.value)" aria-label="${E(tr('turns_title'))}">
            </div>`;
    }
    window.pvLanes = function (d) {
        const st = PV.st; st.lanes = Math.max(1, Math.min(st.max_lanes || 3, (st.lanes || 1) + d));
        renderLanes(); renderSide(); renderFoot();
    };
    window.pvTurns = function (v) { PV.st.turns_per_chat = parseInt(v, 10) || PV.st.turns_per_chat; renderFoot(); };

    // ── Other machines ────────────────────────────────────────────────────
    function renderMachines() {
        const pane = $('pv-pane-machines');
        if (!PV.st) { pane.innerHTML = ''; return; }
        const st = PV.st, nodes = st.remotes || [];
        const cards = nodes.map((r, i) => {
            const s = PV.nodeStatus[r.base_url];
            const stat = !s ? `<span class="pv-mut">${E(tr('node_untested'))}</span>`
                : s.pending ? `<span class="pv-mut">⏳</span>`
                : s.ok ? `<span class="pv-ok"><span class="pv-dot"></span>${E(tr('node_ok', { s: s.seconds }))}</span>`
                : `<span class="pv-bad"><span class="pv-dot"></span>${E(tr('node_fail', { m: s.message || '' }))}</span>`;
            const tail = (r.key || '').includes('…') ? r.key.slice(r.key.indexOf('…')) : (r.key ? '…' + r.key.slice(-3) : tr('node_no_key'));
            return `<div class="pv-node">
                <span class="material-symbols-outlined pv-node-ic">dns</span>
                <div class="pv-node-main">
                  <div class="pv-name">${E(hostOf(r.base_url))}</div>
                  <div class="pv-hint pv-mono">${E(r.base_url)} · ${E(tr('node_key_tail', { k: tail }))} · ${E(tr('node_seats_n', { n: r.seats || 1 }))}</div>
                  <div class="pv-hint">${stat}</div>
                </div>
                <button type="button" class="pv-btn" onclick="window.pvTestNode(${i}, this)">${E(tr('node_test'))}</button>
                <button type="button" class="pv-btn pv-btn-ghost" aria-label="${E(tr('node_remove'))} ${E(hostOf(r.base_url))}" onclick="window.pvRemoveNode(${i})"><span class="material-symbols-outlined" style="font-size:16px">delete</span></button>
            </div>`;
        }).join('');
        const keyCard = PV.newKey
            ? `<div class="pv-key-new"><input type="text" class="pv-input pv-mono" readonly value="${E(PV.newKey)}" onclick="this.select()" aria-label="${E(tr('key_title'))}"><button type="button" class="pv-btn" onclick="window.pvCopyKey(this)">${E(tr('key_copy'))}</button></div>
               <div class="pv-hint pv-ok">${E(tr('key_made'))}</div>`
            : `<div class="pv-key-row"><span class="pv-mono pv-mut">${E(st.node_key_set ? tr('key_tail', { k: st.node_key_tail || '' }) : tr('key_none'))}</span>
               <button type="button" class="pv-btn" onclick="window.pvNewKey(this)">${E(st.node_key_set ? tr('key_new') : tr('key_make'))}</button></div>`;
        pane.innerHTML = `
            <div class="pv-two">
              <div class="pv-main">
                <div class="pv-h">${E(tr('mach_title'))}</div>
                <div class="pv-hint">${E(tr('mach_hint'))}</div>
                <div class="pv-nodes">${cards || `<div class="pv-empty">${E(tr('mach_empty'))}</div>`}</div>
                <div class="pv-add">
                  <div class="pv-th">${E(tr('add_title'))}</div>
                  <label class="pv-lbl">${E(tr('add_url'))}<input type="text" id="pv-add-url" class="pv-input pv-mono" placeholder="https://vps2.tubecreate.com" autocomplete="off"></label>
                  <div class="pv-add-grid">
                    <label class="pv-lbl">${E(tr('add_key'))}<input type="text" id="pv-add-key" class="pv-input pv-mono" placeholder="${E(tr('add_key_ph'))}" autocomplete="off"></label>
                    <label class="pv-lbl">${E(tr('add_seats'))}<input type="number" id="pv-add-seats" class="pv-input pv-mono" min="1" max="${st.max_remote_seats || 6}" value="2"></label>
                  </div>
                  <div class="pv-hint">${E(tr('add_hint'))}</div>
                  <div class="pv-add-actions">
                    <button type="button" class="btn-primary pv-btn-primary" onclick="window.pvTestAdd(this)">${E(tr('add_test'))}</button>
                    ${PV.addError ? `<button type="button" class="pv-btn" onclick="window.pvAddAnyway()">${E(tr('add_anyway'))}</button>` : ''}
                    <span id="pv-add-msg" class="pv-hint ${PV.addError ? 'pv-bad' : ''}">${E(PV.addError)}</span>
                  </div>
                </div>
              </div>
              <div class="pv-side">
                <div class="pv-card">
                  <div class="pv-th">${E(tr('key_title'))}</div>
                  <div class="pv-hint">${E(tr('key_hint'))}</div>
                  ${keyCard}
                </div>
                <div class="pv-card">
                  <div class="pv-th">${E(tr('how_title'))}</div>
                  <ol class="pv-steps"><li>${E(tr('how_1'))}</li><li>${E(tr('how_2'))}</li><li>${E(tr('how_3'))}</li></ol>
                </div>
              </div>
            </div>`;
    }
    function addInputs() {
        return { base_url: ($('pv-add-url')?.value || '').trim(), key: ($('pv-add-key')?.value || '').trim(),
                 seats: Math.max(1, parseInt($('pv-add-seats')?.value || '1', 10) || 1) };
    }
    window.pvTestNode = async function (i, btn) {
        const r = PV.st.remotes[i]; if (!r) return;
        PV.nodeStatus[r.base_url] = { pending: true }; renderMachines();
        try { PV.nodeStatus[r.base_url] = await apiPost('/api/v1/muse/remotes/test', { base_url: r.base_url, key: r.key || '' }) || { ok: false, message: '?' }; }
        catch (e) { PV.nodeStatus[r.base_url] = { ok: false, message: e.message }; }
        renderMachines();
    };
    window.pvRemoveNode = function (i) { PV.st.remotes.splice(i, 1); renderTabs(); renderMachines(); renderFoot(); };
    window.pvTestAdd = async function (btn) {
        const a = addInputs();
        if (!a.base_url) { PV.addError = tr('add_need_url'); renderMachines(); $('pv-add-url')?.focus(); return; }
        const orig = btn.textContent; btn.disabled = true; btn.textContent = '⏳ ' + tr('testing');
        let r;
        try { r = await apiPost('/api/v1/muse/remotes/test', { base_url: a.base_url, key: a.key }) || { ok: false, message: '?' }; }
        catch (e) { r = { ok: false, message: e.message }; }
        btn.disabled = false; btn.textContent = orig;
        if (r.ok) { pushNode({ base_url: r.base_url || a.base_url, key: a.key, seats: a.seats }, r); PV.addError = ''; }
        else { PV.addError = tr('add_fail', { m: r.message || r.detail || '?' }); renderMachines(); keep(a); }
    };
    window.pvAddAnyway = function () { const a = addInputs(); if (!a.base_url) return; pushNode(a, null); PV.addError = ''; };
    function keep(a) { if ($('pv-add-url')) { $('pv-add-url').value = a.base_url; $('pv-add-key').value = a.key; $('pv-add-seats').value = a.seats; } }
    function pushNode(node, test) {
        PV.st.remotes = (PV.st.remotes || []).filter(r => r.base_url !== node.base_url).concat([node]);
        if (test) PV.nodeStatus[node.base_url] = test;
        renderTabs(); renderMachines(); renderSide(); renderFoot();
    }
    window.pvNewKey = async function (btn) {
        if (PV.st.node_key_set && !confirm(tr('key_confirm'))) return;
        btn.disabled = true;
        try {
            const r = await apiPost('/api/v1/muse/node-key', {});
            if (r && r.node_key) { PV.newKey = r.node_key; PV.st.node_key_set = true; PV.st.node_key_tail = r.node_key.slice(-4); }
            else foot('❌ ' + ((r && (r.detail || r.message)) || 'failed'), false);
        } catch (e) { foot('❌ ' + e.message, false); }
        btn.disabled = false; renderMachines();
    };
    window.pvCopyKey = async function (btn) {
        try { await navigator.clipboard.writeText(PV.newKey); btn.textContent = tr('key_copied'); setTimeout(() => { btn.textContent = tr('key_copy'); }, 1500); }
        catch (e) { const inp = btn.parentElement.querySelector('input'); if (inp) { inp.select(); document.execCommand('copy'); } }
    };

    // ── footer: thay đổi chưa lưu, Discard, Test chat, Save ────────────────
    function foot(text, ok) {
        const el = $('pv-foot-status'); if (!el) return;
        el.className = 'pv-foot-status ' + (ok === true ? 'pv-ok' : ok === false ? 'pv-bad' : '');
        el.textContent = text;
    }
    function renderFoot() {
        const ch = changeList();
        const d = $('pv-btn-discard'), s = $('pv-btn-save'), tb = $('pv-btn-test');
        if (d) { d.textContent = tr('discard'); d.style.display = ch.length ? '' : 'none'; }
        if (s) { s.textContent = tr('save'); s.disabled = !ch.length; }
        if (tb) { tb.textContent = tr('test_chat'); tb.style.display = PV.meta.browser_session ? '' : 'none'; }
        if (ch.length) { foot(tr('unsaved', { list: ch.join(' · ') }), null); const el = $('pv-foot-status'); if (el) el.classList.add('pv-warn'); }
        else foot(tr('no_changes'), null);
    }
    window.pvDiscard = function () {
        currentEditModels = PV.origModels.slice();
        if (PV.meta.browser_session && PV.orig) {
            const o = JSON.parse(PV.orig);
            PV.st.profile = o.p; PV.st.extra_profiles = o.e.slice(); PV.st.lanes = o.l; PV.st.turns_per_chat = o.t;
            PV.st.remotes = o.r.map(r => ({ base_url: r[0], key: r[1], seats: r[2] }));
        }
        PV.addError = '';
        renderEditModelsList(); renderTabs(); renderPanes(); renderFoot();
    };
    window.pvSave = async function (btn) {
        if (PV.saving) return;
        PV.saving = true; btn.disabled = true;
        const orig = btn.textContent; btn.textContent = '⏳ ' + tr('saving');
        let ok = true, why = '';
        try {
            if (museDirty()) {
                const st = PV.st;
                const r = await apiPut('/api/v1/muse/settings', { profile: st.profile || '', extra_profiles: st.extra_profiles, lanes: st.lanes,
                                                                   turns_per_chat: st.turns_per_chat, remotes: st.remotes });
                if (r && r.profile !== undefined && !r.detail) {
                    Object.assign(PV.st, r); PV.st.extra_profiles = (r.extra_profiles || []).slice();
                    PV.st.remotes = (r.remotes || []).map(x => ({ base_url: x.base_url, key: x.key || '', seats: x.seats || 1 }));
                    PV.orig = snapshot();
                    PV.meta.profile = r.profile; PV.meta.has_key = !!r.profile || !!(r.remotes || []).length;
                    await refreshStatus();
                } else { ok = false; why = (r && (r.detail || r.message)) || 'save failed'; }
            }
            if (ok && modelsDirty()) {
                const r = await apiPut(`/api/v1/cloud-api/providers/${currentEditProvider}/settings`, { models: currentEditModels });
                if (r && r.status === 'success') { PV.origModels = currentEditModels.slice(); PV.meta.models = currentEditModels.slice(); PV.meta.models_source = 'custom'; }
                else { ok = false; why = (r && (r.error || r.message || r.detail)) || 'save failed'; }
            }
        } catch (e) { ok = false; why = e.message; }
        PV.saving = false; btn.disabled = false; btn.textContent = orig;
        renderHead(); renderTabs(); renderPanes(); renderFoot(); _renderModelsSourceNote();
        if (ok) foot(tr('saved_at', { t: new Date().toLocaleTimeString() }), true); else foot('❌ ' + why, false);
        try { renderCloudApiExt(_cloudExtBody()); } catch (e) { /* tab khác đang mở */ }
    };
    window.pvTestChat = async function (btn) {
        const orig = btn.textContent; btn.disabled = true; btn.textContent = '⏳ ' + tr('testing');
        foot(tr('test_running'), null);
        try { PV.lastTest = await apiPost('/api/v1/muse/test', {}) || { ok: false, message: '?' }; }
        catch (e) { PV.lastTest = { ok: false, message: e.message }; }
        btn.disabled = false; btn.textContent = orig;
        const lt = PV.lastTest;
        foot(lt.ok ? tr('test_ok', { s: lt.seconds, reply: lt.reply || '' }) : '❌ ' + (lt.message || lt.detail || '?'), !!lt.ok);
        renderSide();
    };
    window.pvClose = function () {
        if (dirty() && !confirm(tr('close_unsaved'))) return;
        closeModal('modal-edit-models');
    };
    // Lưu danh sách model từ nút cũ (nếu còn chỗ gọi) → đi qua Save chung.
    window.saveProviderModels = function () { const b = $('pv-btn-save'); if (b) window.pvSave(b); };
})();
