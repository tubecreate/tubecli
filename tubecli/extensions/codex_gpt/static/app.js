/* Codex GPT — trang chat của Codex CLI trên máy, nhiều gói đăng ký, phiên dùng chung.
   Nói chuyện với lõi qua REST /api/v1/codex-gpt/* và WebSocket /api/v1/codex-gpt/ws (sự kiện của
   `codex app-server` chuyển nguyên). Không thư viện ngoài. */
(function () {
  'use strict';

  const API = '/api/v1/codex-gpt';
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  /* ── i18n — cùng giao kèo T()/data-i18n với bảng điều khiển (khoá «cg.*») ───────────── */
  let _lang = 'en', _dict = {}, _en = {};
  function T(key, vars, def) {
    let s = _dict[key];
    if (s === undefined) s = _en[key];
    if (typeof s !== 'string') s = def !== undefined ? def : key;
    if (vars) Object.keys(vars).forEach((k) => { s = s.split('{' + k + '}').join(String(vars[k])); });
    return s;
  }
  function applyI18n(root) {
    const scope = root || document;
    const put = (attr, set) => scope.querySelectorAll('[' + attr + ']').forEach((n) => {
      const k = n.getAttribute(attr);
      let v = _dict[k]; if (typeof v !== 'string') v = _en[k];
      if (typeof v === 'string') set(n, v);
    });
    put('data-i18n', (n, v) => { n.textContent = v; });
    put('data-i18n-placeholder', (n, v) => { n.placeholder = v; });
    put('data-i18n-title', (n, v) => { n.title = v; });
    put('data-i18n-aria-label', (n, v) => { n.setAttribute('aria-label', v); });
    if (!root) document.documentElement.lang = _lang;
  }
  async function loadI18n() {
    const q = new URLSearchParams(location.search).get('lang');
    if (q) _lang = q;
    else {
      try {
        const r = await fetch('/api/v1/settings/language');
        if (r.ok) { const d = await r.json(); if (d && d.language) _lang = d.language; }
      } catch (e) { /* dùng mặc định */ }
    }
    try { const r = await fetch('/api/v1/i18n/' + encodeURIComponent(_lang)); if (r.ok) _dict = await r.json(); } catch (e) { /* chữ tiếng Anh viết sẵn */ }
    if (_lang === 'en') _en = _dict;
    else { try { const r = await fetch('/api/v1/i18n/en'); if (r.ok) _en = await r.json(); } catch (e) { /* bỏ qua */ } }
    applyI18n();
  }

  /* ── trạng thái ────────────────────────────────────────────────────────────── */
  const S = {
    status: null, threads: [], archived: false, q: '', cur: null, thread: null, turns: [],
    running: {}, approvals: {}, models: [], usage: null, draftCwd: '', notices: {},
    plans: {}, diffs: {}, itemEls: new Map(), loginPoll: null,
  };

  async function api(path, opts) {
    opts = opts || {};
    const init = { method: opts.method || 'GET', credentials: 'same-origin', headers: {} };
    if (opts.body !== undefined) { init.headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(opts.body); }
    const r = await fetch(API + path, init);
    let d = {};
    try { d = await r.json(); } catch (e) { /* trả lỗi bên dưới */ }
    if (!r.ok || d.ok === false) {
      const e = new Error((d && d.error) || ('HTTP ' + r.status));
      e.code = d && d.code; e.status = r.status;
      throw e;
    }
    return d;
  }

  function toast(msg, ms) {
    const t = $('toast');
    t.textContent = msg; t.hidden = false;
    clearTimeout(toast._t); toast._t = setTimeout(() => { t.hidden = true; }, ms || 3200);
  }
  function errText(e) {
    const map = { not_installed: 'cg.err.not_installed', no_account: 'cg.err.no_account', busy: 'cg.err.busy',
      cwd_missing: 'cg.err.cwd_missing', bad_key: 'cg.err.bad_key', bad_auth: 'cg.err.bad_auth', start_failed: 'cg.err.start_failed',
      outside_roots: 'cg.err.outside_roots' };
    return e && e.code && map[e.code] ? T(map[e.code], null, e.message) : (e && e.message) || String(e);
  }

  /* ── thời gian / số ────────────────────────────────────────────────────────── */
  const ms = (t) => (!t ? 0 : t < 1e12 ? t * 1000 : t);
  function rel(t) {
    const d = (Date.now() - ms(t)) / 1000;
    let rtf; try { rtf = new Intl.RelativeTimeFormat(_lang, { numeric: 'auto' }); } catch (e) { rtf = new Intl.RelativeTimeFormat('en', { numeric: 'auto' }); }
    if (d < 45) return T('cg.just_now', null, 'just now');
    if (d < 3600) return rtf.format(-Math.round(d / 60), 'minute');
    if (d < 86400) return rtf.format(-Math.round(d / 3600), 'hour');
    if (d < 86400 * 7) return rtf.format(-Math.round(d / 86400), 'day');
    return new Date(ms(t)).toLocaleDateString(_lang);
  }
  function until(t) {
    if (!t) return '';
    const d = ms(t) - Date.now();
    if (d <= 0) return T('cg.now', null, 'now');
    const h = Math.floor(d / 3600000), m = Math.round((d % 3600000) / 60000);
    if (h >= 48) return new Date(ms(t)).toLocaleString(_lang, { weekday: 'short', hour: '2-digit', minute: '2-digit' });
    return h ? T('cg.in_hm', { h, m }, 'in {h} h {m} min') : T('cg.in_m', { m }, 'in {m} min');
  }
  const kfmt = (n) => (n >= 1000 ? (n / 1000).toFixed(n >= 10000 ? 0 : 1) + 'k' : String(n || 0));
  const base = (p) => String(p || '').replace(/[\\/]+$/, '').split(/[\\/]/).pop() || p || '';
  function winLabel(mins) {
    if (!mins) return T('cg.window', null, 'Limit');
    if (mins <= 360) return T('cg.window_h', { h: Math.round(mins / 60) }, '{h} h');
    if (mins >= 10000 && mins <= 10200) return T('cg.window_week', null, 'Week');
    return T('cg.window_d', { d: Math.round(mins / 1440) }, '{d} d');
  }

  /* ── markdown gọn (đã thoát HTML trước) ───────────────────────────────────── */
  function inline(s) {
    return s
      .replace(/`([^`\n]+)`/g, (m, c) => '<code>' + c + '</code>')
      .replace(/\*\*([^*\n]+)\*\*/g, '<b>$1</b>')
      .replace(/\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
      .replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g, '$1<a href="$2" target="_blank" rel="noopener">$2</a>');
  }
  function md(text) {
    const src = String(text || '').replace(/\r\n/g, '\n');
    const out = [];
    const parts = src.split(/```/);
    parts.forEach((part, i) => {
      if (i % 2 === 1) {
        const nl = part.indexOf('\n');
        const body = nl >= 0 ? part.slice(nl + 1) : part;
        out.push('<pre><code>' + esc(body.replace(/\n$/, '')) + '</code></pre>');
        return;
      }
      const lines = esc(part).split('\n');
      let list = null, para = [];
      const flushPara = () => { if (para.length) { out.push('<p>' + inline(para.join('<br>')) + '</p>'); para = []; } };
      const flushList = () => { if (list) { out.push('<' + list.tag + '>' + list.items.map((x) => '<li>' + inline(x) + '</li>').join('') + '</' + list.tag + '>'); list = null; } };
      lines.forEach((ln) => {
        const h = ln.match(/^(#{1,3})\s+(.*)$/);
        const ul = ln.match(/^\s*[-*•]\s+(.*)$/);
        const ol = ln.match(/^\s*\d+[.)]\s+(.*)$/);
        if (h) { flushPara(); flushList(); out.push('<h' + (h[1].length + 1) + '>' + inline(h[2]) + '</h' + (h[1].length + 1) + '>'); }
        else if (ul || ol) {
          flushPara();
          const tag = ul ? 'ul' : 'ol';
          if (!list || list.tag !== tag) { flushList(); list = { tag, items: [] }; }
          list.items.push((ul || ol)[1]);
        } else if (!ln.trim()) { flushPara(); flushList(); }
        else { flushList(); para.push(ln); }
      });
      flushPara(); flushList();
    });
    return out.join('');
  }
  function diffHtml(diff) {
    return String(diff || '').split('\n').map((l) => {
      const c = l.startsWith('@@') ? 'hunk' : l.startsWith('+') && !l.startsWith('+++') ? 'add' : l.startsWith('-') && !l.startsWith('---') ? 'del' : '';
      return c ? '<span class="' + c + '">' + esc(l) + '</span>' : esc(l);
    }).join('\n');
  }

  /* ── tài khoản trên thanh trên cùng ───────────────────────────────────────── */
  const plan = (p) => (p ? String(p).replace(/_/g, ' ') : '');
  function sev(used) { return used >= 90 ? 'bad' : used >= 70 ? 'warn' : ''; }
  function activeAcc() { const st = S.status; return st && (st.accounts || []).find((a) => a.id === st.active); }
  function renderPill() {
    const b = $('btnAccount');
    const st = S.status;
    if (!st || !st.installed || !(st.accounts || []).length) { b.hidden = true; return; }
    const a = activeAcc();
    b.hidden = false;
    if (!a) { b.innerHTML = '<span class="dot warn"></span><span class="name">' + esc(T('cg.pick_account', null, 'Choose an account')) + '</span>'; return; }
    const p = (a.limits || {}).primary;
    const used = p ? p.used : 0;
    const limited = a.limited_until && ms(a.limited_until) > Date.now();
    b.innerHTML = '<span class="dot ' + (limited ? 'bad' : sev(used)) + '"></span>'
      + '<span class="name">' + esc(a.label || a.email || 'Codex') + '</span>'
      + (a.plan ? '<span class="cg-plan">' + esc(plan(a.plan)) + '</span>' : '')
      + (p ? '<span class="cg-bar bar ' + sev(used) + '" title="' + esc(winLabel(p.window_mins) + ' ' + used + '%') + '"><i style="width:' + Math.min(100, used) + '%"></i></span>' : '');
    b.title = T('cg.accounts', null, 'Accounts') + ' · ' + (a.email || a.label || '');
  }

  /* ── trạng thái chung → chọn màn ──────────────────────────────────────────── */
  async function refreshStatus() {
    try { S.status = await api('/status'); } catch (e) { S.status = null; showOnboard('error', errText(e)); return; }
    renderPill();
    const st = S.status;
    if (!st.installed) { showOnboard('install'); return; }
    if (!(st.accounts || []).length) { showOnboard('account'); return; }
    $('onboard').hidden = true;
    $('chat').hidden = false;
    S.running = st.running || {};
    if (!S.models.length) loadModels();
    checkWinSandbox();
  }

  /* ── sandbox Codex trên Windows ───────────────────────────────────────────
     Chưa cài thì Codex lặng lẽ hạ «chỉ sửa thư mục làm việc» thành CHỈ ĐỌC và chặn mọi lệnh (3/10/2026: Codex
     không đọc nổi Bảng việc vì thế) → nói thẳng, kèm hai lối ra. */
  async function checkWinSandbox() {
    const st = S.status || {};
    if (st.platform !== 'windows' || (st.settings || {}).sandbox === 'danger-full-access') { S.winsb = null; renderWinBar(); return; }
    try { S.winsb = await api('/windows-sandbox'); } catch (e) { S.winsb = null; }
    renderWinBar();
  }
  function renderWinBar() {
    const bar = $('notice');
    const w = S.winsb;
    const st = S.status || {};
    if (!w || w.status === 'ready' || w.status === 'unsupported' || (st.settings || {}).sandbox === 'danger-full-access') { bar.hidden = true; bar.innerHTML = ''; return; }
    const running = w.setup === 'running';
    bar.hidden = false;
    bar.className = 'cg-notice cg-winbar';
    bar.innerHTML = '<div class="cg-winbar-txt"><b>⚠ ' + esc(T('cg.winsb_title', null, "Codex's Windows sandbox isn't set up")) + '</b>'
      + '<span>' + esc(w.setup === 'failed' ? T('cg.winsb_failed', { e: w.error || '' }, 'Setup failed: {e}') : T('cg.winsb_desc', null, 'Without it Codex can only read — every command is blocked.')) + '</span></div>'
      + '<div class="cg-winbar-acts"><button type="button" class="cg-btn cg-btn-pri cg-btn-sm" id="wbSetup"' + (running ? ' disabled' : '') + '>'
      + (running ? '<span class="cg-spin"></span> ' + esc(T('cg.winsb_running', null, 'Setting up…')) : esc(T('cg.winsb_setup', null, 'Set up Windows sandbox'))) + '</button>'
      + '<button type="button" class="cg-btn cg-btn-sm" id="wbFull"' + (running ? ' disabled' : '') + '>' + esc(T('cg.winsb_full', null, 'Use full access')) + '</button></div>';
    $('wbSetup').onclick = async () => {
      try { S.winsb = await api('/windows-sandbox/setup', { method: 'POST', body: { mode: 'unelevated' } }); }
      catch (e) { S.winsb = Object.assign({}, S.winsb, { setup: 'failed', error: errText(e) }); }
      renderWinBar();
    };
    $('wbFull').onclick = async () => {
      if (!confirm(T('cg.winsb_full_confirm', null, 'Codex will be able to change any file on this machine. Continue?'))) return;
      try { await api('/settings', { method: 'PUT', body: { sandbox: 'danger-full-access' } }); await refreshStatus(); renderHead(); }
      catch (e) { toast(errText(e), 5000); }
    };
  }

  function showOnboard(kind, extra) {
    $('chat').hidden = true;
    const box = $('onboard');
    box.hidden = false;
    const st = S.status || {};
    let html = '';
    if (kind === 'install') {
      const ins = st.install || {};
      const running = ins.state === 'running';
      html = '<div class="cg-onboard-card"><h2>' + esc(T('cg.install_title', null, 'Install Codex CLI')) + '</h2>'
        + '<p>' + esc(T('cg.install_desc', null, 'Codex GPT runs the official Codex CLI on this machine. It installs into TubeCLI\'s own folder — no sudo, and it does not touch a codex you installed yourself.')) + '</p>'
        + (st.node ? '' : '<div class="cg-err">' + esc(T('cg.need_node', null, 'Node.js 18+ is required — install Node.js on this machine first.')) + '</div>')
        + '<div class="cg-row"><button type="button" class="cg-btn cg-btn-pri" id="obInstall" ' + (running || !st.node ? 'disabled' : '') + '>'
        + esc(running ? T('cg.installing', null, 'Installing…') : T('cg.install_btn', null, 'Install Codex CLI')) + '</button>'
        + (running ? '<span class="cg-spin"></span>' : '') + '</div>'
        + (ins.log ? '<pre class="cg-log">' + esc(ins.log) + '</pre>' : '') + '</div>';
    } else if (kind === 'account') {
      html = '<div class="cg-onboard-card"><h2>' + esc(T('cg.add_first_title', null, 'Add your first Codex account')) + '</h2>'
        + '<p>' + esc(T('cg.add_first_desc', null, 'Sign in with a ChatGPT plan (Plus, Pro, Team…) or an OpenAI API key. Add several accounts and Codex GPT switches to the next one when a plan hits its usage limit — your chats continue.')) + '</p>'
        + '<div class="cg-row"><button type="button" class="cg-btn cg-btn-pri" id="obAdd">' + esc(T('cg.add_account', null, 'Add account')) + '</button></div>'
        + '<p class="cg-hint">' + esc(T('cg.cli_version', { v: st.version || '?' }, 'Codex CLI {v}')) + '</p></div>';
    } else {
      html = '<div class="cg-onboard-card"><h2>Codex GPT</h2><div class="cg-err">' + esc(extra || '') + '</div>'
        + '<div class="cg-row"><button type="button" class="cg-btn" id="obRetry">' + esc(T('cg.retry', null, 'Try again')) + '</button></div></div>';
    }
    box.innerHTML = html;
    const ins = $('obInstall'); if (ins) ins.onclick = installCli;
    const add = $('obAdd'); if (add) add.onclick = () => openAddAccount();
    const rt = $('obRetry'); if (rt) rt.onclick = () => boot2();
    if (kind === 'install' && (st.install || {}).state === 'running') setTimeout(pollInstall, 2500);
  }

  async function installCli() {
    try { await api('/install', { method: 'POST' }); } catch (e) { toast(errText(e)); }
    await refreshStatus();
  }
  async function pollInstall() {
    await refreshStatus();
    const st = S.status;
    if (st && st.installed && (st.install || {}).state !== 'running' && (st.accounts || []).length) boot2();
  }

  /* ── danh sách phiên ──────────────────────────────────────────────────────── */
  async function loadThreads() {
    const st = S.status;
    if (!st || !st.installed || !(st.accounts || []).length) return;
    try {
      const d = await api('/threads?archived=' + (S.archived ? '1' : '0') + (S.q ? '&q=' + encodeURIComponent(S.q) : ''));
      S.threads = d.threads || [];
      S.running = Object.assign({}, d.running || {});
    } catch (e) {
      S.threads = [];
      $('list').innerHTML = '<div class="cg-empty-list">' + esc(errText(e)) + '</div>';
      return;
    }
    renderList();
  }
  const loadThreadsSoon = (() => { let t; return () => { clearTimeout(t); t = setTimeout(loadThreads, 700); }; })();

  function threadTitle(t) { return (t && (t.name || t.preview)) || T('cg.untitled', null, 'New chat'); }
  function renderList() {
    const box = $('list');
    $('btnArchived').textContent = S.archived ? T('cg.back_to_chats', null, '← Back to chats') : T('cg.show_archived', null, 'Archived chats');
    if (!S.threads.length) {
      box.innerHTML = '<div class="cg-empty-list">' + esc(S.archived ? T('cg.no_archived', null, 'No archived chats') : S.q ? T('cg.no_match', null, 'No chat matches') : T('cg.no_chats', null, 'No chats yet — start one.')) + '</div>';
      return;
    }
    const now = new Date(); const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
    const groups = [[T('cg.today', null, 'Today'), []], [T('cg.yesterday', null, 'Yesterday'), []], [T('cg.week', null, 'Previous 7 days'), []], [T('cg.older', null, 'Older'), []]];
    S.threads.forEach((t) => {
      const ts = ms(t.updatedAt || t.createdAt);
      const g = ts >= startToday ? 0 : ts >= startToday - 86400000 ? 1 : ts >= startToday - 7 * 86400000 ? 2 : 3;
      groups[g][1].push(t);
    });
    box.innerHTML = groups.filter((g) => g[1].length).map((g) => '<div class="cg-group">' + esc(g[0]) + '</div>' + g[1].map((t) =>
      '<div class="cg-item' + (t.id === S.cur ? ' on' : '') + '" role="listitem" data-id="' + esc(t.id) + '" tabindex="0">'
      + (S.running[t.id] ? '<span class="cg-run-dot" title="' + esc(T('cg.running', null, 'Working…')) + '"></span>' : '')
      + '<div class="cg-item-main"><div class="cg-item-title">' + esc(threadTitle(t)) + '</div>'
      + '<div class="cg-item-meta">' + esc(base(t.cwd)) + ' · ' + esc(rel(t.updatedAt || t.createdAt)) + '</div></div>'
      + '<button type="button" class="cg-icon-btn" data-menu="' + esc(t.id) + '" aria-label="' + esc(T('cg.more', null, 'More')) + '">⋯</button></div>').join('')).join('');
  }

  /* ── một phiên ────────────────────────────────────────────────────────────── */
  async function openThread(id) {
    S.cur = id;
    S.itemEls = new Map();
    S.usage = null;
    try { history.replaceState(null, '', '#' + id); } catch (e) { /* sandbox */ }
    renderList();
    closeSide();
    $('msgs').innerHTML = '<div class="cg-thinking"><span class="cg-spin"></span>' + esc(T('cg.loading', null, 'Loading…')) + '</div>';
    try {
      const d = await api('/threads/' + encodeURIComponent(id));
      if (S.cur !== id) return;
      S.thread = d.thread || {};
      S.turns = (S.thread.turns || []).map((t) => ({ id: t.id, status: t.status, error: t.error, items: t.items || [] }));
      if (!S.thread.name && !S.thread.preview) S.thread.preview = firstUserText(S.turns);
      if (d.running) S.running[id] = d.running; else delete S.running[id];
      (d.approvals || []).forEach((a) => { S.approvals[a.key] = a; });
    } catch (e) {
      $('msgs').innerHTML = '<div class="cg-err">' + esc(errText(e)) + '</div>';
      return;
    }
    renderChat(true);
  }

  function firstUserText(turns) {
    for (const t of turns || []) {
      for (const i of t.items || []) {
        if (i.type === 'userMessage') return (i.content || []).map((c) => c.text || '').join(' ').slice(0, 160);
      }
    }
    return '';
  }

  function newChat() {
    S.cur = null; S.thread = null; S.turns = []; S.itemEls = new Map(); S.usage = null;
    try { history.replaceState(null, '', '#'); } catch (e) { /* sandbox */ }
    renderList(); closeSide();
    renderChat(true);
    $('input').focus();
  }

  function renderHead() {
    const t = S.thread;
    $('title').textContent = t ? threadTitle(t) : T('cg.new_chat', null, 'New chat');
    const cwd = t ? t.cwd : (S.draftCwd || ((S.status || {}).settings || {}).cwd || (S.status || {}).workspace || '');
    $('sub').textContent = [cwd, t && t.model].filter(Boolean).join(' · ');
    $('btnThreadMenu').hidden = !t;
    $('usage').textContent = S.usage ? T('cg.tokens', { n: kfmt(S.usage) }, '{n} tokens') : '';
    $('chipCwd').textContent = '📁 ' + (base(cwd) || '~');
    $('chipCwd').title = cwd + (t ? '' : ' — ' + T('cg.change_folder', null, 'click to change'));
    $('chipCwd').disabled = !!t;
    const run = !!(S.cur && S.running[S.cur]);
    $('btnStop').hidden = !run;
    $('btnSend').textContent = run ? T('cg.steer', null, 'Add to reply') : T('cg.send', null, 'Send');
  }

  function renderChat(scroll) {
    renderHead();
    const box = $('msgs');
    S.itemEls = new Map();
    if (!S.cur) {
      const sug = [T('cg.sug1', null, 'Explain the structure of this folder'), T('cg.sug2', null, 'Find and fix the failing tests'),
        T('cg.sug3', null, 'Write a script that renames files by date'), T('cg.sug4', null, 'Review the latest git changes')];
      box.innerHTML = '<div class="cg-onboard-card" style="margin:auto;max-width:560px"><h2>' + esc(T('cg.welcome', null, 'What should Codex do?')) + '</h2>'
        + '<p>' + esc(T('cg.welcome_desc', null, 'Codex reads files, runs commands and edits code in the working folder. Pick a folder, then type a task.')) + '</p>'
        + '<div class="cg-suggest">' + sug.map((s) => '<button type="button" data-sug="' + esc(s) + '">' + esc(s) + '</button>').join('') + '</div></div>';
      return;
    }
    box.innerHTML = '';
    S.turns.forEach((turn) => box.appendChild(turnEl(turn)));
    renderTail();
    if (scroll) box.scrollTop = box.scrollHeight;
  }

  function renderTail() {
    const box = $('msgs');
    box.querySelectorAll('.cg-tail').forEach((n) => n.remove());
    const tail = document.createElement('div');
    tail.className = 'cg-tail cg-turn';
    const notes = S.notices[S.cur] || [];
    notes.forEach((n) => { const d = document.createElement('div'); d.className = n.kind === 'err' ? 'cg-err' : 'cg-info'; d.textContent = n.text; tail.appendChild(d); });
    Object.keys(S.approvals).forEach((k) => {
      const a = S.approvals[k];
      if (approvalHere(a)) tail.appendChild(approvalEl(k, a));
    });
    if (S.running[S.cur]) {
      const th = document.createElement('div');
      th.className = 'cg-thinking';
      th.innerHTML = '<span class="cg-spin"></span>' + esc(T('cg.working', null, 'Codex is working…'));
      tail.appendChild(th);
    }
    if (tail.childNodes.length) box.appendChild(tail);
  }

  function turnEl(turn) {
    const el = document.createElement('div');
    el.className = 'cg-turn';
    el.dataset.turn = turn.id;
    (turn.items || []).forEach((it) => { const n = itemEl(it); if (n) el.appendChild(n); });
    regroupCmds(el);
    const pl = S.plans[turn.id];
    if (pl && pl.length) el.appendChild(planEl(pl));
    const df = S.diffs[turn.id];
    if (df) el.appendChild(cardEl('🧾 ' + T('cg.turn_changes', null, 'Changes in this reply'), '', '<pre class="cg-diff">' + diffHtml(df) + '</pre>'));
    if (turn.error && turn.error.message) {
      const e = document.createElement('div'); e.className = 'cg-err'; e.textContent = turn.error.message; el.appendChild(e);
    } else if (turn.status === 'interrupted') {
      const e = document.createElement('div'); e.className = 'cg-divider'; e.textContent = T('cg.interrupted', null, 'Stopped'); el.appendChild(e);
    }
    return el;
  }

  function cardEl(label, tag, body, open, tagCls) {
    const d = document.createElement('details');
    d.className = 'cg-card';
    if (open) d.open = true;
    d.innerHTML = '<summary><span class="lbl">' + esc(label) + '</span>' + (tag ? '<span class="tag ' + (tagCls || '') + '">' + esc(tag) + '</span>' : '') + '</summary>' + (body || '');
    return d;
  }

  // Dồn các lệnh ĐÃ CHẠY XONG liên tiếp vào một khối thu gọn: Codex dò file là chạy hàng
  // chục lệnh, mỗi lệnh một dòng thì chat thành bức tường và chữ của nó bị đẩy đi mất
  // (user 5/10/2026). Chạy SAU khi vẽ để không đụng vào cơ chế vá từng thẻ (S.itemEls):
  // các thẻ cũ được CHUYỂN vào khối, nên old.replaceWith(fresh) vẫn chạy đúng chỗ.
  const CMD_GROUP_MIN = 3;
  function regroupCmds(tEl) {
    if (!tEl) return;
    // Bung các khối cũ ra trước rồi dựng lại — đơn giản và luôn đúng khi lệnh mới chảy vào.
    tEl.querySelectorAll('.cg-cmdgroup').forEach((g) => {
      const body = g.querySelector('.cg-cmdgroup-body');
      while (body && body.firstChild) tEl.insertBefore(body.firstChild, g);
      g.remove();
    });
    const kids = Array.from(tEl.children);
    let i = 0;
    while (i < kids.length) {
      if (!kids[i].classList.contains('cg-cmd') || !kids[i].dataset.done) { i += 1; continue; }
      let j = i;
      while (j < kids.length && kids[j].classList.contains('cg-cmd') && kids[j].dataset.done) j += 1;
      const run = kids.slice(i, j);
      i = j;
      if (run.length < CMD_GROUP_MIN) continue;
      const bad = run.filter((x) => x.dataset.exit && x.dataset.exit !== '0').length;
      const key = run[0].dataset.item || run[0].querySelector('.lbl')?.textContent || '';
      const g = document.createElement('details');
      g.className = 'cg-card cg-cmdgroup';
      if (S.cmdOpen && S.cmdOpen.has(key)) g.open = true;
      g.innerHTML = '<summary><span class="lbl">⌨ '
        + esc(T('cg.cmds_n', { n: run.length }, '{n} commands')) + '</span>'
        + '<span class="tag ' + (bad ? 'err' : 'ok') + '">'
        + esc(bad ? T('cg.cmds_bad', { n: bad }, '{n} failed') : T('cg.cmds_ok', null, 'all fine'))
        + '</span></summary><div class="cg-cmdgroup-body"></div>';
      g.addEventListener('toggle', () => {
        S.cmdOpen = S.cmdOpen || new Set();
        if (g.open) S.cmdOpen.add(key); else S.cmdOpen.delete(key);
      });
      run[0].replaceWith(g);
      const body = g.querySelector('.cg-cmdgroup-body');
      run.forEach((x) => body.appendChild(x));
    }
  }

  function planEl(steps) {
    const d = cardEl('🗺 ' + T('cg.plan', null, 'Plan'), steps.filter((s) => s.status === 'completed').length + '/' + steps.length, '', true);
    const ol = document.createElement('ol'); ol.className = 'cg-plan-list';
    steps.forEach((s) => { const li = document.createElement('li'); li.textContent = s.step || ''; li.className = s.status === 'completed' ? 'done' : s.status === 'inProgress' ? 'now' : ''; ol.appendChild(li); });
    d.appendChild(ol);
    return d;
  }

  function stLabel(s) {
    return { completed: T('cg.st_done', null, 'done'), failed: T('cg.st_failed', null, 'failed'),
      inProgress: T('cg.st_running', null, 'running'), declined: T('cg.st_declined', null, 'declined') }[s] || s || '';
  }
  function cmdText(c) { return Array.isArray(c) ? c.join(' ') : String(c || ''); }
  function itemEl(it) {
    if (!it || !it.type) return null;
    let el = null;
    const t = it.type;
    if (t === 'userMessage') {
      const txt = (it.content || []).map((c) => (c.type === 'text' ? c.text : c.type === 'image' ? '[image]' : '')).join('\n');
      el = document.createElement('div');
      if (S.status && txt === S.status.continue_text) {
        // Lời «làm tiếp» TubeCLI tự gửi sau khi đổi tài khoản — không phải người dùng gõ.
        el.className = 'cg-divider'; el.textContent = '— ' + T('cg.continued', null, 'Continued on another account') + ' —';
      } else { el.className = 'cg-user'; el.textContent = txt; }
    } else if (t === 'agentMessage') {
      el = document.createElement('div');
      el.className = 'cg-agent' + (it.phase === 'commentary' ? ' commentary' : '') + (it._streaming ? ' cg-caret' : '');
      el.innerHTML = md(it.text || '');
    } else if (t === 'reasoning') {
      const txt = [].concat(it.summary || []).join('\n').replace(/\*\*/g, '').trim();
      if (!txt) return null;
      // Nhãn = dòng đầu; thân chỉ hiện khi còn chữ khác (tóm tắt một dòng khỏi lặp hai lần).
      const first = txt.split('\n')[0];
      const more = txt.slice(first.length).trim() || first.length > 120;
      el = cardEl('💭 ' + (first.slice(0, 120) || T('cg.thinking', null, 'Thinking')), '', more ? '<div class="body">' + esc(txt) + '</div>' : '');
      el.classList.add('cg-reason');
    } else if (t === 'commandExecution') {
      const st = it.status === 'inProgress' ? T('cg.st_running', null, 'running') : it.status === 'declined' ? T('cg.st_declined', null, 'declined')
        : it.exitCode != null ? T('cg.st_exit', { c: it.exitCode }, 'exit {c}') : stLabel(it.status);
      const cls = it.status === 'inProgress' ? 'run' : it.exitCode === 0 ? 'ok' : (it.exitCode != null || it.status === 'failed' || it.status === 'declined') ? 'err' : '';
      const out = it.aggregatedOutput || '';
      el = cardEl('$ ' + cmdText(it.command), st, out ? '<pre>' + esc(out.slice(-20000)) + '</pre>' : '', false, cls);
      // Dấu để regroupCmds() dồn các lệnh ĐÃ XONG liên tiếp lại; lệnh đang chạy thì để riêng
      // cho chủ máy thấy Codex đang làm gì.
      el.classList.add('cg-cmd');
      if (it.status !== 'inProgress') el.dataset.done = '1';
      if (it.exitCode != null) el.dataset.exit = String(it.exitCode);
    } else if (t === 'fileChange') {
      const ch = it.changes || [];
      const files = ch.map((c) => {
        const k = (c.kind || {}).type || 'update';
        return '<div class="cg-file"><span class="k ' + (k === 'add' ? 'add' : k === 'delete' ? 'del' : 'upd') + '">' + (k === 'add' ? '+' : k === 'delete' ? '−' : '~') + '</span>' + esc(c.path) + '</div>';
      }).join('');
      const diffs = ch.map((c) => c.diff ? diffHtml(c.diff) : '').filter(Boolean).join('\n');
      el = cardEl('✎ ' + T('cg.files_changed', { n: ch.length }, '{n} file(s) changed'), stLabel(it.status),
        '<div class="cg-files">' + files + '</div>' + (diffs ? '<pre class="cg-diff">' + diffs + '</pre>' : ''), false, it.status === 'completed' ? 'ok' : it.status === 'failed' ? 'err' : 'run');
    } else if (t === 'plan') {
      el = cardEl('🗺 ' + T('cg.plan', null, 'Plan'), '', '<div class="cg-files" style="white-space:pre-wrap">' + esc(it.text || '') + '</div>', true);
    } else if (t === 'webSearch') {
      el = cardEl('🔎 ' + (it.query || T('cg.web_search', null, 'Web search')), '', '');
    } else if (t === 'mcpToolCall' || t === 'dynamicToolCall') {
      el = toolCardEl(it);
    } else if (t === 'imageView' || t === 'imageGeneration') {
      el = cardEl('🖼 ' + (it.path || it.savedPath || it.revisedPrompt || T('cg.image', null, 'Image')), it.status || '', '');
    } else if (t === 'contextCompaction') {
      el = document.createElement('div'); el.className = 'cg-divider'; el.textContent = '— ' + T('cg.compacted', null, 'Earlier context was summarised') + ' —';
    } else if (t === 'enteredReviewMode' || t === 'exitedReviewMode') {
      el = document.createElement('div'); el.className = 'cg-divider'; el.textContent = t === 'enteredReviewMode' ? T('cg.review_start', null, '— Review —') : T('cg.review_end', null, '— Review done —');
    } else if (t === 'collabAgentToolCall' || t === 'subAgentActivity') {
      el = cardEl('🤝 ' + (it.tool || it.kind || T('cg.sub_agent', null, 'Sub-agent')), it.status || '', it.prompt ? '<pre>' + esc(it.prompt) + '</pre>' : '');
    } else {
      return null;
    }
    if (it.id) { el.dataset.item = it.id; S.itemEls.set(it.id, el); }
    return el;
  }

  // Thẻ duyệt của công cụ TubeCLI có thể không biết phiên (gọi từ terminal, hoặc chưa khớp item) → hiện ở phiên đang mở.
  function approvalHere(a) {
    const p = a.params || {};
    return p.threadId === S.cur || (a.method === 'tubecli/tool' && !p.threadId && !!S.cur);
  }
  function toolName(n) { return T('cg.tool.' + n, null, n); }
  function toolCardEl(it) {
    const isTc = it.server === 'tubecli';
    const label = isTc ? '🧰 TubeCLI · ' + toolName(it.tool) : '🔧 ' + [it.server, it.tool, it.namespace].filter(Boolean).join(' · ');
    const args = it.arguments && typeof it.arguments === 'object' && Object.keys(it.arguments).length ? JSON.stringify(it.arguments, null, 1) : '';
    const res = it.result || {};
    const texts = (res.content || []).filter((c) => c && c.type === 'text').map((c) => c.text).join('\n');
    const imgs = (res.content || []).filter((c) => c && c.type === 'image' && c.data && /^image\/(png|jpe?g|webp|gif)$/.test(c.mimeType || ''));
    let body = '';
    if (args) body += '<pre class="cg-tool-args">' + esc(args.slice(0, 4000)) + '</pre>';
    if (it.error) body += '<pre class="cg-tool-err">' + esc(it.error.message || JSON.stringify(it.error)) + '</pre>';
    if (texts) body += '<pre>' + esc(texts.slice(0, 12000)) + '</pre>';
    imgs.forEach((c) => { body += '<img class="cg-tool-img" alt="" src="data:' + esc(c.mimeType) + ';base64,' + esc(c.data) + '">'; });
    const bad = it.status === 'failed' || (res && res.isError);
    const el = cardEl(label, bad ? T('cg.st_failed', null, 'failed') : stLabel(it.status), body, imgs.length > 0, it.status === 'inProgress' ? 'run' : bad ? 'err' : 'ok');
    el.classList.add('cg-tool');
    return el;
  }

  function approvalEl(key, a) {
    const p = a.params || {};
    const el = document.createElement('div');
    el.className = 'cg-approval';
    if (a.method === 'tubecli/tool') {
      el.innerHTML = '<b>⚠ ' + esc(T('cg.ask_tool', null, 'Codex wants to use TubeCLI')) + ': ' + esc(toolName(p.tool || '')) + '</b>'
        + (p.detail ? '<div class="cmd">' + esc(p.detail) + '</div>' : '')
        // once = công cụ LUÔN hỏi (đưa agent lên Agent Town): không có «Cho phép trong phiên này», gợi ý «Không cần hỏi» sai ở đây
        + '<div class="cg-hint">' + esc(p.once
          ? T('cg.ask_once_hint', null, 'Codex always asks you before this — it puts an agent in front of strangers and sets prices.')
          : T('cg.ask_tool_hint', null, 'Turn on «Don\'t ask» in Settings to let Codex do this without asking.')) + '</div>'
        + '<div class="acts"><button type="button" class="cg-btn cg-btn-pri cg-btn-sm" data-ap="accept">' + esc(T('cg.allow', null, 'Allow')) + '</button>'
        + (p.threadId && !p.once ? '<button type="button" class="cg-btn cg-btn-sm" data-ap="acceptForSession">' + esc(T('cg.allow_session', null, 'Allow for this chat')) + '</button>' : '')
        + (p.threadId ? '<button type="button" class="cg-btn cg-btn-sm" data-ap="acceptAlways" title="' + esc(T('cg.allow_always_hint', null, 'Every later request in this chat is approved automatically, until the app restarts.')) + '">' + esc(T('cg.allow_always', null, 'Allow, stop asking')) + '</button>' : '')
        + '<button type="button" class="cg-btn cg-btn-danger cg-btn-sm" data-ap="decline">' + esc(T('cg.deny', null, 'Deny')) + '</button></div>';
      bindApproval(el, key);
      return el;
    }
    const isFile = /fileChange|applyPatch/.test(a.method);
    const what = isFile ? T('cg.ask_file', null, 'Codex wants to change files') : T('cg.ask_cmd', null, 'Codex wants to run a command');
    el.innerHTML = '<b>⚠ ' + esc(what) + '</b>'
      + (p.command ? '<div class="cmd">' + esc(cmdText(p.command)) + '</div>' : '')
      + (p.cwd ? '<div class="cg-hint">📁 ' + esc(p.cwd) + '</div>' : '')
      + (p.reason ? '<div>' + esc(p.reason) + '</div>' : '')
      + '<div class="acts"><button type="button" class="cg-btn cg-btn-pri cg-btn-sm" data-ap="accept">' + esc(T('cg.allow', null, 'Allow')) + '</button>'
      + '<button type="button" class="cg-btn cg-btn-sm" data-ap="acceptForSession">' + esc(T('cg.allow_session', null, 'Allow for this chat')) + '</button>'
      + '<button type="button" class="cg-btn cg-btn-sm" data-ap="acceptAlways" title="' + esc(T('cg.allow_always_hint', null, 'Every later request in this chat is approved automatically, until the app restarts.')) + '">' + esc(T('cg.allow_always', null, 'Allow, stop asking')) + '</button>'
      + '<button type="button" class="cg-btn cg-btn-danger cg-btn-sm" data-ap="decline">' + esc(T('cg.deny', null, 'Deny')) + '</button></div>';
    bindApproval(el, key);
    return el;
  }
  function bindApproval(el, key) {
    el.querySelectorAll('[data-ap]').forEach((b) => {
      b.onclick = async () => {
        el.querySelectorAll('button').forEach((x) => { x.disabled = true; });
        try { await api('/approvals/' + encodeURIComponent(key), { method: 'POST', body: { decision: b.dataset.ap } }); }
        catch (e) { toast(errText(e)); }
        delete S.approvals[key];
        renderTail();
      };
    });
  }

  /* ── cập nhật trực tiếp từ sự kiện ────────────────────────────────────────── */
  function curTurn(turnId) {
    let t = S.turns.find((x) => x.id === turnId);
    if (!t) { t = { id: turnId, status: 'inProgress', items: [] }; S.turns.push(t); }
    return t;
  }
  function findItem(turnId, itemId) {
    const t = S.turns.find((x) => x.id === turnId);
    return t && t.items.find((i) => i.id === itemId);
  }
  const atBottom = () => { const b = $('msgs'); return b.scrollHeight - b.scrollTop - b.clientHeight < 80; };
  function stick(was) { if (was) { const b = $('msgs'); b.scrollTop = b.scrollHeight; } }

  function putItem(turnId, item) {
    const was = atBottom();
    const turn = curTurn(turnId);
    const i = turn.items.findIndex((x) => x.id === item.id);
    if (i >= 0) turn.items[i] = Object.assign(turn.items[i], item); else turn.items.push(item);
    const box = $('msgs');
    let tEl = box.querySelector('.cg-turn[data-turn="' + CSS.escape(turnId) + '"]');
    if (!tEl) { tEl = turnEl({ id: turnId, items: [] }); const tail = box.querySelector('.cg-tail'); box.insertBefore(tEl, tail); }
    const old = S.itemEls.get(item.id);
    const fresh = itemEl(i >= 0 ? turn.items[i] : item);
    if (old && fresh) { if (old.open && fresh.tagName === 'DETAILS') fresh.open = true; old.replaceWith(fresh); }
    else if (fresh) tEl.appendChild(fresh);
    regroupCmds(tEl);
    stick(was);
  }

  const reRender = (() => {
    const q = new Map(); let raf = 0;
    return (turnId, itemId) => {
      q.set(itemId, turnId);
      if (raf) return;
      raf = requestAnimationFrame(() => {
        raf = 0;
        const was = atBottom();
        q.forEach((tId, iId) => {
          const it = findItem(tId, iId); const old = S.itemEls.get(iId);
          if (!it) return;
          const fresh = itemEl(it);
          if (old && fresh) { if (old.open && fresh.tagName === 'DETAILS') fresh.open = true; old.replaceWith(fresh); }
          else if (fresh) putItem(tId, it);
        });
        q.forEach((tId) => regroupCmds($('msgs').querySelector('.cg-turn[data-turn="' + CSS.escape(tId) + '"]')));
        q.clear();
        stick(was);
      });
    };
  })();

  function onEvent(m, p) {
    const tid = p.threadId || (p.thread && p.thread.id);
    if (m === 'turn/started' && tid) { S.running[tid] = (p.turn || {}).id || '1'; if (tid !== S.cur) renderList(); }
    if (m === 'turn/completed' && tid) { delete S.running[tid]; loadThreadsSoon(); if (tid !== S.cur) renderList(); }
    if (m === 'thread/name/updated' && tid) { const t = S.threads.find((x) => x.id === tid); if (t) { t.name = p.threadName || p.name || t.name; renderList(); } }
    if (m === 'account/rateLimits/updated') { refreshStatusSoon(); }
    if (m === 'windowsSandbox/setupCompleted') {
      S.winsb = Object.assign({}, S.winsb, { setup: p.success ? 'done' : 'failed', error: p.error || '', status: p.success ? 'ready' : (S.winsb || {}).status });
      renderWinBar();
      if (p.success) toast(T('cg.winsb_done', null, 'Windows sandbox is ready'));
    }
    if (!tid || tid !== S.cur) return;
    if (m === 'turn/started') {
      curTurn((p.turn || {}).id);
      renderTail(); renderHead();
    } else if (m === 'item/started' || m === 'item/completed') {
      const it = Object.assign({}, p.item || {});
      if (it.type === 'userMessage' && S.thread && !S.thread.name && !S.thread.preview) {
        S.thread.preview = (it.content || []).map((c) => c.text || '').join(' ').slice(0, 160);
        renderHead();
      }
      if (m === 'item/started' && it.type === 'agentMessage') it._streaming = true;
      putItem(p.turnId, it);
    } else if (m === 'item/agentMessage/delta') {
      const it = findItem(p.turnId, p.itemId);
      if (it) { it.text = (it.text || '') + (p.delta || ''); it._streaming = true; reRender(p.turnId, p.itemId); }
    } else if (m === 'item/reasoning/summaryTextDelta') {
      const it = findItem(p.turnId, p.itemId);
      if (it) { const idx = p.summaryIndex || 0; it.summary = [].concat(it.summary || []); it.summary[idx] = (it.summary[idx] || '') + (p.delta || ''); reRender(p.turnId, p.itemId); }
    } else if (m === 'item/commandExecution/outputDelta') {
      const it = findItem(p.turnId, p.itemId);
      if (it) { it.aggregatedOutput = (it.aggregatedOutput || '') + (p.delta || ''); reRender(p.turnId, p.itemId); }
    } else if (m === 'turn/plan/updated') {
      S.plans[p.turnId] = p.plan || [];
      rerenderTurn(p.turnId);
    } else if (m === 'turn/diff/updated') {
      S.diffs[p.turnId] = p.diff || '';
    } else if (m === 'turn/completed') {
      const turn = curTurn((p.turn || {}).id);
      turn.status = (p.turn || {}).status; turn.error = (p.turn || {}).error;
      turn.items.forEach((i) => { delete i._streaming; });
      rerenderTurn(turn.id);
      renderTail(); renderHead();
    } else if (m === 'thread/tokenUsage/updated') {
      S.usage = ((p.tokenUsage || {}).total || {}).totalTokens || 0; renderHead();
    } else if (m === 'thread/name/updated') {
      if (S.thread) S.thread.name = p.threadName || p.name || S.thread.name; renderHead();
    }
  }
  function rerenderTurn(turnId) {
    const box = $('msgs');
    const old = box.querySelector('.cg-turn[data-turn="' + CSS.escape(turnId) + '"]');
    const t = S.turns.find((x) => x.id === turnId);
    if (!t) return;
    const was = atBottom();
    const fresh = turnEl(t);
    if (old) old.replaceWith(fresh); else box.insertBefore(fresh, box.querySelector('.cg-tail'));
    stick(was);
  }
  const refreshStatusSoon = (() => { let t; return () => { clearTimeout(t); t = setTimeout(async () => { try { S.status = await api('/status'); renderPill(); } catch (e) { /* bỏ qua */ } }, 1500); }; })();

  function addNotice(tid, kind, text) {
    (S.notices[tid] = S.notices[tid] || []).push({ kind, text });
    if (tid === S.cur) { renderTail(); stick(true); }
  }

  /* ── WebSocket ────────────────────────────────────────────────────────────── */
  let ws = null, wsTry = 0, pingT = 0;
  function connectWs() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    try { ws = new WebSocket(proto + '://' + location.host + API + '/ws'); } catch (e) { return scheduleWs(); }
    ws.onopen = () => { wsTry = 0; clearInterval(pingT); pingT = setInterval(() => { try { ws.send('{"type":"ping"}'); } catch (e) { /* đóng */ } }, 25000); };
    ws.onmessage = (ev) => {
      let msg; try { msg = JSON.parse(ev.data); } catch (e) { return; }
      handleWs(msg);
    };
    ws.onclose = () => { clearInterval(pingT); scheduleWs(); };
    ws.onerror = () => { try { ws.close(); } catch (e) { /* đã đóng */ } };
  }
  function scheduleWs() { wsTry++; setTimeout(connectWs, Math.min(15000, 800 * wsTry)); }

  function accName(id) { const a = ((S.status || {}).accounts || []).find((x) => x.id === id); return a ? (a.label || a.email || 'Codex') : ''; }
  function handleWs(msg) {
    if (msg.type === 'hello') {
      S.approvals = {};
      (msg.approvals || []).forEach((a) => { S.approvals[a.key] = a; });
      S.running = Object.assign({}, msg.running || {});
      if (S.cur) { renderTail(); renderHead(); }
      renderList();
    } else if (msg.type === 'event') {
      onEvent(msg.method, msg.params || {});
    } else if (msg.type === 'approval') {
      S.approvals[msg.key] = { key: msg.key, method: msg.method, params: msg.params };
      if (approvalHere(S.approvals[msg.key])) { renderTail(); stick(true); }
      else toast(T('cg.approval_other', null, 'Another chat is waiting for your approval'));
    } else if (msg.type === 'approval_done') {
      delete S.approvals[msg.key]; renderTail();
    } else if (msg.type === 'switched') {
      addNotice(msg.threadId, 'info', T('cg.switched', { name: msg.label || accName(msg.to) }, 'The account hit its usage limit — switched to {name}; Codex continues.'));
      refreshStatusSoon();
    } else if (msg.type === 'limit') {
      addNotice(msg.threadId, 'err', msg.auto ? T('cg.limit_none', null, 'Every account has hit its usage limit. Add another account or wait for the reset.')
        : T('cg.limit_off', null, 'This account hit its usage limit. Turn on auto-switch or pick another account.'));
      refreshStatusSoon();
    } else if (msg.type === 'account') {
      (msg.interrupted || []).forEach((tid) => { delete S.running[tid]; addNotice(tid, 'info', T('cg.interrupted_switch', null, 'Stopped because the account was switched — send again to continue.')); });
      refreshStatusSoon(); S.models = []; loadModels();
    } else if (msg.type === 'bridge') {
      (msg.interrupted || []).forEach((tid) => { delete S.running[tid]; addNotice(tid, 'err', T('cg.bridge_exit', null, 'Codex stopped unexpectedly.') + ' ' + (msg.error || '')); });
      renderHead();
    } else if (msg.type === 'login') {
      if (S.loginPoll) S.loginPoll();
    }
  }

  /* ── gửi / dừng ───────────────────────────────────────────────────────────── */
  async function send() {
    const box = $('input');
    const text = box.value.trim();
    if (!text) return;
    const model = $('selModel').value, effort = $('selEffort').value;
    $('btnSend').disabled = true;
    try {
      if (!S.cur) {
        const d = await api('/threads', { method: 'POST', body: { text, cwd: S.draftCwd || '', model, effort } });
        box.value = ''; autosize();
        S.draftCwd = '';
        await loadThreads();
        await openThread(d.thread.id);
      } else {
        const id = S.cur;
        const d = await api('/threads/' + encodeURIComponent(id) + '/turns', { method: 'POST', body: { text, model, effort } });
        box.value = ''; autosize();
        if (d.turnId) S.running[id] = d.turnId;
        if (d.steered) toast(T('cg.steered', null, 'Added to the running reply'));
        renderHead(); renderTail();
      }
    } catch (e) { toast(errText(e), 5000); }
    finally { $('btnSend').disabled = false; }
  }
  async function stop() {
    if (!S.cur) return;
    try { await api('/threads/' + encodeURIComponent(S.cur) + '/interrupt', { method: 'POST' }); } catch (e) { toast(errText(e)); }
  }
  function autosize() { const t = $('input'); t.style.height = 'auto'; t.style.height = Math.min(220, t.scrollHeight) + 'px'; }

  /* ── model / mức suy luận ─────────────────────────────────────────────────── */
  async function loadModels() {
    try { const d = await api('/models'); S.models = d.models || []; } catch (e) { S.models = []; }
    renderModelSel();
  }
  function renderModelSel() {
    const set = ((S.status || {}).settings) || {};
    const sel = $('selModel');
    const cur = sel.value || set.model || '';
    sel.innerHTML = '<option value="">' + esc(T('cg.model_default', null, 'Default model')) + '</option>'
      + S.models.map((m) => '<option value="' + esc(m.id) + '">' + esc(m.name || m.id) + '</option>').join('');
    sel.value = S.models.some((m) => m.id === cur) ? cur : '';
    renderEffortSel();
  }
  function renderEffortSel() {
    const set = ((S.status || {}).settings) || {};
    const m = S.models.find((x) => x.id === $('selModel').value) || S.models.find((x) => x.isDefault);
    const list = (m && m.efforts && m.efforts.length ? m.efforts : ['low', 'medium', 'high']).filter(Boolean);
    const sel = $('selEffort');
    const cur = sel.value || set.effort || '';
    sel.innerHTML = '<option value="">' + esc(T('cg.effort_default', null, 'Effort: default')) + '</option>'
      + list.map((e) => '<option value="' + esc(e) + '">' + esc(T('cg.effort_' + e, null, e)) + '</option>').join('');
    sel.value = list.includes(cur) ? cur : '';
  }

  /* ── ngăn kéo / hộp thoại ─────────────────────────────────────────────────── */
  function openPanel(html, center) {
    const p = $('panel');
    p.className = 'cg-panel' + (center ? ' center' : '');
    p.innerHTML = html; p.hidden = false; $('overlay').hidden = false;
    applyI18n(p);
    const f = p.querySelector('[autofocus]'); if (f) f.focus();
    const c = p.querySelector('[data-close]'); if (c) c.onclick = closePanel;
    return p;
  }
  function closePanel() { $('panel').hidden = true; $('overlay').hidden = true; if (S.loginPoll) { S.loginStop = true; S.loginPoll = null; } }
  const head = (title) => '<div class="cg-panel-head"><h2>' + esc(title) + '</h2><button type="button" class="cg-icon-btn" data-close aria-label="Close">✕</button></div>';

  function limitRow(w) {
    if (!w) return '';
    const used = Math.min(100, w.used || 0);
    return '<div class="cg-limit"><span>' + esc(winLabel(w.window_mins)) + '</span><div class="cg-bar ' + sev(used) + '"><i style="width:' + used + '%"></i></div>'
      + '<span class="reset">' + used + '%' + (w.resets_at ? ' · ' + esc(T('cg.resets', { t: until(w.resets_at) }, 'resets {t}')) : '') + '</span></div>';
  }
  function openAccounts() {
    const st = S.status || {};
    const accs = st.accounts || [];
    const html = head(T('cg.accounts', null, 'Accounts'))
      + '<div class="cg-panel-body">'
      + '<label class="cg-switch"><input type="checkbox" id="pAuto" ' + (st.auto_switch ? 'checked' : '') + '><span><b>' + esc(T('cg.auto_switch', null, 'Switch automatically')) + '</b><br><span class="cg-hint">'
      + esc(T('cg.auto_switch_desc', null, 'When an account hits its usage limit, continue the chat on the account with the most quota left.')) + '</span></span></label>'
      + '<div class="cg-row"><button type="button" class="cg-btn cg-btn-pri" id="pAdd">＋ ' + esc(T('cg.add_account', null, 'Add account')) + '</button>'
      + '<button type="button" class="cg-btn" id="pRefresh">↻ ' + esc(T('cg.refresh_limits', null, 'Check limits')) + '</button></div>'
      + '<div class="cg-accts">' + accs.map((a) => {
        const lim = a.limits || {};
        const limited = a.limited_until && ms(a.limited_until) > Date.now();
        return '<div class="cg-acct' + (a.active ? ' on' : '') + (a.disabled ? ' off' : '') + '" data-acc="' + esc(a.id) + '">'
          + '<div class="cg-acct-head"><div style="flex:1;min-width:0"><div class="cg-acct-name">' + esc(a.label || a.email || 'Codex') + '</div>'
          + '<div class="cg-acct-mail">' + esc(a.kind === 'apiKey' ? T('cg.api_key', null, 'API key') : (a.email || '')) + (lim.at ? ' · ' + esc(T('cg.checked', { t: rel(lim.at) }, 'checked {t}')) : '') + '</div></div>'
          + (a.plan ? '<span class="cg-plan">' + esc(plan(a.plan)) + '</span>' : '')
          + (a.active ? '<span class="cg-badge on">' + esc(T('cg.in_use', null, 'In use')) + '</span>' : '')
          + (limited ? '<span class="cg-badge lim" title="' + esc(T('cg.resets', { t: until(a.limited_until) }, 'resets {t}')) + '">' + esc(T('cg.limited', null, 'Limit reached')) + '</span>' : '') + '</div>'
          + limitRow(lim.primary) + limitRow(lim.secondary)
          + '<div class="cg-acct-acts">'
          + (!a.active && !a.disabled ? '<button type="button" class="cg-btn cg-btn-sm cg-btn-pri" data-act="use">' + esc(T('cg.use', null, 'Use this account')) + '</button>' : '')
          + '<button type="button" class="cg-btn cg-btn-sm" data-act="rename">' + esc(T('cg.rename', null, 'Rename')) + '</button>'
          + '<button type="button" class="cg-btn cg-btn-sm" data-act="toggle">' + esc(a.disabled ? T('cg.turn_on', null, 'Turn on') : T('cg.turn_off', null, 'Turn off')) + '</button>'
          + '<button type="button" class="cg-btn cg-btn-sm cg-btn-danger" data-act="remove">' + esc(T('cg.remove', null, 'Remove')) + '</button></div></div>';
      }).join('') + '</div>'
      + '<p class="cg-hint">' + esc(T('cg.accounts_note', null, 'Login keys stay on this machine and are never shown here. All accounts share the same chat history.')) + '</p></div>';
    const p = openPanel(html);
    $('pAuto').onchange = async (e) => { try { await api('/settings', { method: 'PUT', body: { auto_switch: e.target.checked } }); S.status.auto_switch = e.target.checked; } catch (er) { toast(errText(er)); } };
    $('pAdd').onclick = () => openAddAccount();
    $('pRefresh').onclick = async (e) => {
      e.target.disabled = true; e.target.textContent = T('cg.checking', null, 'Checking…');
      try { await api('/accounts/refresh-limits', { method: 'POST' }); } catch (er) { toast(errText(er)); }
      await refreshStatus(); openAccounts();
    };
    p.querySelectorAll('[data-acc] [data-act]').forEach((b) => {
      b.onclick = async () => {
        const id = b.closest('[data-acc]').dataset.acc;
        const act = b.dataset.act;
        const a = accs.find((x) => x.id === id) || {};
        try {
          if (act === 'use') {
            try { await api('/accounts/' + id + '/activate', { method: 'POST', body: {} }); }
            catch (e) {
              if (e.code !== 'busy' || !confirm(T('cg.switch_busy', null, 'A reply is still running. Stop it and switch now?'))) throw e;
              await api('/accounts/' + id + '/activate', { method: 'POST', body: { force: true } });
            }
            toast(T('cg.switched_manual', { name: a.label || a.email || '' }, 'Now using {name}'));
          } else if (act === 'rename') {
            const v = prompt(T('cg.rename_account', null, 'Account name'), a.label || '');
            if (v == null) return;
            await api('/accounts/' + id, { method: 'PATCH', body: { label: v } });
          } else if (act === 'toggle') {
            await api('/accounts/' + id, { method: 'PATCH', body: { disabled: !a.disabled } });
          } else if (act === 'remove') {
            if (!confirm(T('cg.remove_confirm', { name: a.label || a.email || '' }, 'Remove {name} from this machine? Chats stay.'))) return;
            await api('/accounts/' + id, { method: 'DELETE' });
          }
        } catch (e) { toast(errText(e), 5000); }
        await refreshStatus();
        if ((S.status.accounts || []).length) openAccounts(); else { closePanel(); boot2(); }
      };
    });
  }

  function openAddAccount(tab) {
    tab = tab || 'chatgpt';
    const tabs = [['chatgpt', T('cg.tab_chatgpt', null, 'ChatGPT plan')], ['apiKey', T('cg.tab_apikey', null, 'API key')], ['import', T('cg.tab_import', null, 'Import auth.json')]];
    let body = '';
    if (tab === 'chatgpt') {
      body = '<p class="cg-hint">' + esc(T('cg.chatgpt_desc', null, 'Sign in with a device code: open the link on any device (phone, laptop), type the code, approve. Works on servers without a browser.')) + '</p>'
        + '<div class="cg-field"><label>' + esc(T('cg.label', null, 'Name (optional)')) + '</label><input class="cg-input" id="aLabel" placeholder="Plus — work" autofocus></div>'
        + '<button type="button" class="cg-btn cg-btn-pri" id="aGo">' + esc(T('cg.get_code', null, 'Get sign-in code')) + '</button>'
        + '<p class="cg-hint">' + esc(T('cg.device_note', null, 'If ChatGPT refuses the code, turn on «Device code authorization for Codex» in ChatGPT → Settings → Security, then try again.')) + '</p>';
    } else if (tab === 'apiKey') {
      body = '<div class="cg-field"><label>' + esc(T('cg.label', null, 'Name (optional)')) + '</label><input class="cg-input" id="aLabel" autofocus></div>'
        + '<div class="cg-field"><label>OpenAI API key</label><input class="cg-input mono" id="aKey" type="password" autocomplete="off" placeholder="sk-…"></div>'
        + '<button type="button" class="cg-btn cg-btn-pri" id="aGo">' + esc(T('cg.save', null, 'Save')) + '</button>'
        + '<p class="cg-hint">' + esc(T('cg.apikey_note', null, 'API usage is billed per token on your OpenAI account and has no 5-hour / weekly limit.')) + '</p>';
    } else {
      body = '<p class="cg-hint">' + esc(T('cg.import_desc', null, 'Already signed in to Codex on another computer? Paste the content of ~/.codex/auth.json from there.')) + '</p>'
        + '<div class="cg-field"><label>' + esc(T('cg.label', null, 'Name (optional)')) + '</label><input class="cg-input" id="aLabel" autofocus></div>'
        + '<div class="cg-field"><label>auth.json</label><textarea class="cg-input mono" id="aJson" rows="6" spellcheck="false" placeholder="{ &quot;tokens&quot;: { … } }"></textarea></div>'
        + '<button type="button" class="cg-btn cg-btn-pri" id="aGo">' + esc(T('cg.import', null, 'Import')) + '</button>';
    }
    const p = openPanel(head(T('cg.add_account', null, 'Add account')) + '<div class="cg-panel-body"><div class="cg-tabs">'
      + tabs.map((t) => '<button type="button" class="cg-tab' + (t[0] === tab ? ' on' : '') + '" data-tab="' + t[0] + '">' + esc(t[1]) + '</button>').join('')
      + '</div><div id="aBody" style="display:flex;flex-direction:column;gap:10px">' + body + '</div></div>', true);
    p.querySelectorAll('[data-tab]').forEach((b) => { b.onclick = () => openAddAccount(b.dataset.tab); });
    $('aGo').onclick = async () => {
      const btn = $('aGo'); btn.disabled = true;
      const label = ($('aLabel') || {}).value || '';
      try {
        const bodyReq = { kind: tab, label };
        if (tab === 'apiKey') bodyReq.api_key = $('aKey').value;
        if (tab === 'import') bodyReq.auth_json = $('aJson').value;
        const d = await api('/accounts/login', { method: 'POST', body: bodyReq });
        const lg = d.login || {};
        if (lg.state === 'done') { await loginDone(lg); return; }
        if (lg.state === 'error') throw new Error(lg.error || 'Login failed');
        showDeviceCode(lg);
      } catch (e) { btn.disabled = false; toast(errText(e), 6000); }
    };
  }

  // Chép chữ: Clipboard API (iframe Flow có allow clipboard-write) → bị chặn thì execCommand → vẫn hụt thì bôi đen để bấm Ctrl+C
  async function copyText(text, selectEl) {
    try { await navigator.clipboard.writeText(text); return true; } catch (e) { /* bị chặn → thử cách cũ */ }
    const ta = document.createElement('textarea');
    ta.value = text; ta.setAttribute('readonly', ''); ta.style.cssText = 'position:fixed;top:0;left:0;opacity:0';
    document.body.appendChild(ta); ta.select();
    let ok = false;
    try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
    ta.remove();
    if (!ok && selectEl) { const r = document.createRange(); r.selectNodeContents(selectEl); const s = getSelection(); s.removeAllRanges(); s.addRange(r); }
    return ok;
  }
  async function copyWithToast(text, selectEl) {
    const ok = await copyText(text, selectEl);
    toast(ok ? T('cg.copied', null, 'Copied') : T('cg.copy_manual', null, 'Couldn\'t copy — press Ctrl+C'), ok ? 2500 : 5000);
  }

  // Mã thiết bị: trình duyệt đang mở Flow thường KHÔNG phải trình duyệt đăng nhập ChatGPT → bước 1 là CHÉP link, mở tại đây chỉ là phụ
  function showDeviceCode(lg) {
    const p = openPanel(head(T('cg.sign_in', null, 'Sign in to ChatGPT')) + '<div class="cg-panel-body">'
      + '<p>' + esc(T('cg.step1', null, '1. Copy this link and open it in the browser where you\'re signed in to ChatGPT:')) + '</p>'
      + '<div class="cg-devlink"><span class="cg-devlink-url" id="dUrl" title="' + esc(lg.url) + '">' + esc(lg.url) + '</span>'
      + '<button type="button" class="cg-btn cg-btn-pri" id="dCopyUrl">' + esc(T('cg.copy_link', null, 'Copy link')) + '</button></div>'
      + '<a class="cg-link cg-devlink-open" href="' + esc(lg.url) + '" target="_blank" rel="noopener">' + esc(T('cg.open_here', null, 'Open in this browser')) + ' ↗</a>'
      + '<p>' + esc(T('cg.step2', null, '2. Enter this code:')) + '</p>'
      + '<div class="cg-code" id="dCode">' + esc(lg.code) + '</div>'
      + '<button type="button" class="cg-btn" id="dCopy">' + esc(T('cg.copy_code', null, 'Copy code')) + '</button>'
      + '<div class="cg-thinking" id="dWait"><span class="cg-spin"></span>' + esc(T('cg.waiting_login', null, 'Waiting for you to approve… (code valid 15 minutes)')) + '</div>'
      + '<button type="button" class="cg-link" id="dCancel">' + esc(T('cg.cancel', null, 'Cancel')) + '</button></div>', true);
    $('dCopyUrl').onclick = () => copyWithToast(lg.url, $('dUrl'));
    $('dCopy').onclick = () => copyWithToast(lg.code, $('dCode'));
    $('dCancel').onclick = async () => { try { await api('/accounts/login/' + lg.id + '/cancel', { method: 'POST' }); } catch (e) { /* đã xong */ } closePanel(); };
    S.loginStop = false;
    const poll = async () => {
      if (S.loginStop) return;
      let d;
      try { d = (await api('/accounts/login/' + lg.id)).login; } catch (e) { return; }
      if (d.state === 'done') { S.loginPoll = null; await loginDone(d); }
      else if (d.state === 'error' || d.state === 'cancelled') {
        S.loginPoll = null;
        const w = $('dWait'); if (w) { w.className = 'cg-err'; w.textContent = d.error === 'expired' ? T('cg.code_expired', null, 'The code expired — get a new one.') : (d.error || 'Login failed'); }
      }
    };
    S.loginPoll = poll;
    const tick = () => { if (S.loginPoll === poll) { poll(); setTimeout(tick, 4000); } };
    setTimeout(tick, 4000);
    void p;
  }

  async function loginDone(lg) {
    const a = lg.account || {};
    toast(T('cg.added', { name: a.label || a.email || 'Codex' }, 'Added {name}'), 4000);
    closePanel();
    await boot2();
    openAccounts();
  }

  function openSettings() {
    const st = S.status || {}; const s = st.settings || {};
    const sel = (id, val, opts) => '<select class="cg-select-full" id="' + id + '">' + opts.map((o) => '<option value="' + esc(o[0]) + '"' + (o[0] === val ? ' selected' : '') + '>' + esc(o[1]) + '</option>').join('') + '</select>';
    const ins = st.install || {};
    const tgStatusText = (tg) => {
      if (!tg) return '';
      if (!tg.enabled || !tg.token_set) return T('cg.tg_status_off', null, 'Off');
      const who = tg.bot ? '@' + tg.bot : '';
      const base = tg.running ? T('cg.tg_status_on', null, 'Running {bot} · {chats} chat(s) allowed · {threads} chat(s) linked', { bot: who, chats: tg.chats || 0, threads: tg.threads || 0 })
        : T('cg.tg_status_stopped', null, 'Stopped');
      return tg.error ? base + ' · ' + T('cg.tg_status_err', null, 'error: {err}', { err: tg.error }) : base;
    };
    const homeCmd = (st.platform === 'windows' ? 'set CODEX_HOME=' + (st.home || '') + ' && codex' : 'CODEX_HOME="' + (st.home || '') + '" codex');
    const p = openPanel(head(T('cg.settings', null, 'Settings')) + '<div class="cg-panel-body">'
      + '<div class="cg-field"><label>' + esc(T('cg.approval', null, 'When Codex wants to run commands')) + '</label>'
      + sel('sAppr', s.approval, [['never', T('cg.appr_never', null, 'Just do it (inside the sandbox)')], ['on-request', T('cg.appr_req', null, 'Ask me when it needs more access')], ['untrusted', T('cg.appr_untrusted', null, 'Ask me before most commands')]]) + '</div>'
      + '<div class="cg-field"><label>' + esc(T('cg.sandbox', null, 'Sandbox')) + '</label>'
      + sel('sBox', s.sandbox, [['workspace-write', T('cg.sb_ws', null, 'Can edit the working folder only')], ['read-only', T('cg.sb_ro', null, 'Read-only')], ['danger-full-access', T('cg.sb_full', null, 'Full access to the machine (careful)')]])
      + (st.platform === 'windows' ? '<span class="cg-hint">' + esc(T('cg.win_sandbox', null, 'On Windows the sandbox may block commands — choose full access if Codex cannot read files.')) + '</span>' : '') + '</div>'
      + '<div class="cg-field"><label>' + esc(T('cg.default_folder', null, 'Default working folder')) + '</label><input class="cg-input mono" id="sCwd" value="' + esc(s.cwd || '') + '" placeholder="' + esc(st.default_cwd || st.workspace || '') + '">'
      + '<span class="cg-hint">' + esc(T('cg.default_folder_hint', null, 'Applies to NEW chats - a chat already open keeps the folder it started with.')) + '</span></div>'
      + '<div class="cg-field"><span class="cg-field-label">' + esc(T('cg.writable', null, 'Codex can write to')) + '</span>'
      + '<div class="cg-roots">' + (st.writable_roots || []).map((r) => '<code>' + esc(r) + '</code>').join('') + '</div>'
      + '<span class="cg-hint">' + esc(T('cg.writable_note', null, 'The same areas TubeCLI lets its AI use. TubeCLI data stays read-only for Codex.')) + '</span></div>'
      + '<hr style="border:0;border-top:1px solid var(--border-subtle);width:100%">'
      + '<div class="cg-field"><span class="cg-field-label">' + esc(T('cg.tools_title', null, 'TubeCLI tools')) + '</span>'
      + '<label class="cg-check"><input type="checkbox" id="sTools"' + (s.tools !== false ? ' checked' : '') + '> ' + esc(T('cg.tools_on', null, 'Let Codex use TubeCLI (Task Board, browser, extensions…)')) + '</label></div>'
      + '<div class="cg-field"><label>' + esc(T('cg.tools_ask_label', null, 'When Codex wants to change something in TubeCLI')) + '</label>'
      + sel('sToolsAuto', s.tools_auto ? 'auto' : 'ask', [['ask', T('cg.tools_ask', null, 'Ask me first (recommended)')], ['auto', T('cg.tools_auto', null, "Just do it — don't ask")]])
      + '<span class="cg-hint" id="sAutoWarn"' + (s.tools_auto ? '' : ' hidden') + '>' + esc(T('cg.tools_auto_warn', null, 'Codex will open browsers, create tasks and call TubeCLI without asking. A web page it reads could try to trick it.')) + '</span></div>'
      + '<hr style="border:0;border-top:1px solid var(--border-subtle);width:100%">'
      /* Telegram chatbot (18/10/2026): bot riêng của Codex GPT; chat được phép ↔ phiên Codex; token không bao giờ
         quay lại trang (chỉ cờ telegram_token_set) nên ô token để trống, có chữ là THAY. */
      + '<div class="cg-field"><span class="cg-field-label">' + esc(T('cg.tg_title', null, 'Telegram chatbot')) + '</span>'
      + '<label class="cg-check"><input type="checkbox" id="sTgOn"' + (s.telegram_enabled ? ' checked' : '') + '> ' + esc(T('cg.tg_on', null, 'Chat with Codex from Telegram — each allowed chat is one Codex chat on this machine')) + '</label>'
      + '<span class="cg-hint">' + esc(T('cg.tg_hint', null, 'Create a bot with @BotFather and paste its token. Then message the bot: it answers with your chat id until you allow it below. Use a bot no agent uses.')) + '</span></div>'
      + '<div class="cg-field"><label>' + esc(T('cg.tg_token', null, 'Bot token')) + '</label><input class="cg-input mono" id="sTgTok" value="" autocomplete="off" placeholder="' + esc(s.telegram_token_set ? T('cg.tg_token_set', null, 'saved — paste a new token to replace it') : '123456789:ABC-DEF…') + '"></div>'
      + '<div class="cg-field"><label>' + esc(T('cg.tg_chats', null, 'Allowed chat ids (comma-separated)')) + '</label><input class="cg-input mono" id="sTgChats" value="' + esc((s.telegram_chat_ids || []).join(', ')) + '" placeholder="123456789, -1001234567890"></div>'
      + '<div class="cg-field"><span class="cg-hint" id="sTgStatus">' + esc(tgStatusText(st.telegram)) + '</span><div class="cg-row">'
      + '<button type="button" class="cg-btn cg-btn-sm" id="sTgTest">' + esc(T('cg.tg_test', null, 'Send a test message')) + '</button>'
      + (s.telegram_token_set ? '<button type="button" class="cg-btn cg-btn-sm cg-btn-danger" id="sTgClear">' + esc(T('cg.tg_clear', null, 'Remove token')) + '</button>' : '') + '</div></div>'
      + '<button type="button" class="cg-btn cg-btn-pri" id="sSave">' + esc(T('cg.save', null, 'Save')) + '</button>'
      + '<hr style="border:0;border-top:1px solid var(--border-subtle);width:100%">'
      + '<div class="cg-field"><span class="cg-field-label">Codex CLI</span><div class="cg-row"><span>' + esc(st.version ? 'v' + st.version : '—') + ' · ' + esc(st.source === 'private' ? T('cg.src_private', null, 'TubeCLI copy') : st.source === 'global' ? T('cg.src_global', null, 'system copy') : st.source || '') + '</span>'
      + '<button type="button" class="cg-btn cg-btn-sm" id="sUpd" ' + (ins.state === 'running' ? 'disabled' : '') + '>' + esc(ins.state === 'running' ? T('cg.installing', null, 'Installing…') : T('cg.update_cli', null, 'Update to latest')) + '</button></div>'
      + (ins.log && ins.state !== 'idle' ? '<pre class="cg-log">' + esc(ins.log) + '</pre>' : '') + '</div>'
      + '<div class="cg-field"><span class="cg-field-label">' + esc(T('cg.use_terminal', null, 'Use the same chats and account in a terminal')) + '</span><pre class="cg-log">' + esc(homeCmd) + '</pre></div>'
      + '</div>');
    $('sSave').onclick = async () => {
      try {
        const tok = $('sTgTok').value.trim();
        await api('/settings', { method: 'PUT', body: { approval: $('sAppr').value, sandbox: $('sBox').value, cwd: $('sCwd').value.trim(),
          tools: $('sTools').checked, tools_auto: $('sToolsAuto').value === 'auto',
          telegram_enabled: $('sTgOn').checked, telegram_chat_ids: $('sTgChats').value, ...(tok ? { telegram_token: tok } : {}) } });
        toast(T('cg.saved', null, 'Saved')); await refreshStatus(); closePanel(); renderHead();
      } catch (e) { toast(errText(e), 5000); }
    };
    $('sToolsAuto').onchange = () => { $('sAutoWarn').hidden = $('sToolsAuto').value !== 'auto'; };
    $('sTgTest').onclick = async () => {
      try { const r = await api('/telegram/test', { method: 'POST' }); toast(T('cg.tg_sent', null, 'Sent to {n} chat(s)', { n: r.sent })); await refreshStatus(); $('sTgStatus').textContent = tgStatusText((S.status || {}).telegram); }
      catch (e) { toast(errText(e), 5000); }
    };
    if ($('sTgClear')) $('sTgClear').onclick = async () => {
      try { await api('/settings', { method: 'PUT', body: { telegram_token: '', telegram_enabled: false } }); await refreshStatus(); openSettings(); }
      catch (e) { toast(errText(e), 5000); }
    };
    $('sUpd').onclick = async () => { try { await api('/install', { method: 'POST' }); } catch (e) { toast(errText(e)); } await refreshStatus(); openSettings(); };
    void p;
  }

  function chooseFolder() {
    const st = S.status || {};
    const recent = (st.recent_cwds || []).filter(Boolean);
    const p = openPanel(head(T('cg.folder', null, 'Working folder')) + '<div class="cg-panel-body">'
      + '<p class="cg-hint">' + esc(T('cg.folder_desc', null, 'Codex reads and edits files in this folder (absolute path on the machine).')) + '</p>'
      + '<input class="cg-input mono" id="fPath" autofocus value="' + esc(S.draftCwd || (st.settings || {}).cwd || '') + '" placeholder="' + esc(st.workspace || '') + '">'
      + (recent.length ? '<div class="cg-field"><span class="cg-field-label">' + esc(T('cg.recent', null, 'Recent')) + '</span>' + recent.map((r) => '<button type="button" class="cg-chip" style="max-width:100%;text-align:left" data-cwd="' + esc(r) + '">' + esc(r) + '</button>').join('') + '</div>' : '')
      + '<div class="cg-row"><button type="button" class="cg-btn cg-btn-pri" id="fOk">' + esc(T('cg.use_folder', null, 'Use this folder')) + '</button>'
      + '<button type="button" class="cg-btn" id="fWs">' + esc(T('cg.use_workspace', null, 'Use the TubeCLI workspace')) + '</button></div></div>', true);
    p.querySelectorAll('[data-cwd]').forEach((b) => { b.onclick = () => { $('fPath').value = b.dataset.cwd; }; });
    $('fOk').onclick = () => { S.draftCwd = $('fPath').value.trim(); closePanel(); renderHead(); };
    $('fWs').onclick = () => { S.draftCwd = ''; closePanel(); renderHead(); };
  }

  /* ── menu ⋯ của phiên ─────────────────────────────────────────────────────── */
  function openMenu(anchor, id) {
    const t = S.threads.find((x) => x.id === id) || (S.thread && S.thread.id === id ? S.thread : { id });
    const pop = $('pop');
    pop.innerHTML = '<button type="button" data-m="rename">' + esc(T('cg.rename', null, 'Rename')) + '</button>'
      + '<button type="button" data-m="' + (S.archived ? 'unarchive' : 'archive') + '">' + esc(S.archived ? T('cg.unarchive', null, 'Restore') : T('cg.archive', null, 'Archive')) + '</button>'
      + '<button type="button" data-m="delete" class="danger">' + esc(T('cg.delete', null, 'Delete')) + '</button>';
    const r = anchor.getBoundingClientRect();
    pop.hidden = false;
    pop.style.top = Math.min(window.innerHeight - pop.offsetHeight - 8, r.bottom + 4) + 'px';
    pop.style.left = Math.max(8, Math.min(window.innerWidth - pop.offsetWidth - 8, r.right - pop.offsetWidth)) + 'px';
    pop.querySelectorAll('[data-m]').forEach((b) => {
      b.onclick = async () => {
        pop.hidden = true;
        const m = b.dataset.m;
        try {
          if (m === 'rename') {
            const v = prompt(T('cg.rename_chat', null, 'Chat name'), threadTitle(t));
            if (v == null) return;
            await api('/threads/' + encodeURIComponent(id), { method: 'PATCH', body: { name: v } });
            if (S.thread && S.thread.id === id) { S.thread.name = v; renderHead(); }
          } else if (m === 'archive' || m === 'unarchive') {
            await api('/threads/' + encodeURIComponent(id) + '/' + m, { method: 'POST' });
            if (S.cur === id) newChat();
          } else if (m === 'delete') {
            if (!confirm(T('cg.delete_confirm', null, 'Delete this chat for good?'))) return;
            await api('/threads/' + encodeURIComponent(id), { method: 'DELETE' });
            if (S.cur === id) newChat();
          }
        } catch (e) { toast(errText(e), 5000); }
        loadThreads();
      };
    });
  }

  /* ── cột phiên trên màn hẹp ───────────────────────────────────────────────── */
  function openSide() { $('app').classList.add('side-open'); $('sideScrim').hidden = false; }
  function closeSide() { $('app').classList.remove('side-open'); $('sideScrim').hidden = true; }

  function renameInline() {
    if (!S.thread) return;
    const h = $('title');
    const old = threadTitle(S.thread);
    h.innerHTML = '<input class="cg-input" maxlength="120">';
    const inp = h.querySelector('input'); inp.value = old; inp.focus(); inp.select();
    let done = false;
    const finish = async (save) => {
      if (done) return; done = true;
      const v = inp.value.trim();
      if (save && v && v !== old) {
        try { await api('/threads/' + encodeURIComponent(S.thread.id), { method: 'PATCH', body: { name: v } }); S.thread.name = v; loadThreadsSoon(); }
        catch (e) { toast(errText(e)); }
      }
      renderHead();
    };
    inp.onkeydown = (e) => { if (e.key === 'Enter') finish(true); else if (e.key === 'Escape') finish(false); };
    inp.onblur = () => finish(true);
  }

  function bindUi() {
    $('btnMenu').onclick = openSide;
    $('sideScrim').onclick = closeSide;
    $('btnNew').onclick = newChat;
    $('btnAccount').onclick = openAccounts;
    $('btnSettings').onclick = () => (S.status && S.status.installed ? openSettings() : null);
    $('overlay').onclick = closePanel;
    $('btnArchived').onclick = () => { S.archived = !S.archived; loadThreads(); };
    let st;
    $('search').oninput = (e) => { clearTimeout(st); st = setTimeout(() => { S.q = e.target.value.trim(); loadThreads(); }, 300); };
    $('list').onclick = (e) => {
      const mb = e.target.closest('[data-menu]');
      if (mb) { e.stopPropagation(); openMenu(mb, mb.dataset.menu); return; }
      const it = e.target.closest('[data-id]');
      if (it) openThread(it.dataset.id);
    };
    $('list').onkeydown = (e) => { const it = e.target.closest('[data-id]'); if (it && e.key === 'Enter') openThread(it.dataset.id); };
    $('btnThreadMenu').onclick = (e) => { if (S.cur) openMenu(e.currentTarget, S.cur); };
    $('title').onclick = renameInline;
    $('title').onkeydown = (e) => { if (e.key === 'Enter') renameInline(); };
    $('composer').onsubmit = (e) => { e.preventDefault(); send(); };
    $('input').onkeydown = (e) => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); } };
    $('input').oninput = autosize;
    $('btnStop').onclick = stop;
    $('chipCwd').onclick = () => { if (!S.cur) chooseFolder(); };
    $('selModel').onchange = renderEffortSel;
    $('msgs').onclick = (e) => { const s = e.target.closest('[data-sug]'); if (s) { $('input').value = s.dataset.sug; autosize(); $('input').focus(); } };
    document.addEventListener('click', (e) => { if (!e.target.closest('#pop') && !e.target.closest('[data-menu]') && !e.target.closest('#btnThreadMenu')) $('pop').hidden = true; });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { $('pop').hidden = true; if (!$('panel').hidden) closePanel(); } });
  }

  async function boot2() {
    await refreshStatus();
    const st = S.status;
    if (!st || !st.installed || !(st.accounts || []).length) return;
    await loadThreads();
    const want = decodeURIComponent((location.hash || '').slice(1));
    if (want && S.threads.some((t) => t.id === want)) openThread(want);
    else if (S.cur) openThread(S.cur);
    else newChat();
  }

  async function boot() {
    await loadI18n();
    bindUi();
    connectWs();
    await boot2();
  }
  boot();
})();
