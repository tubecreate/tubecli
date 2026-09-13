/**
 * ═══════════════════════════════════════════════════════════════════
 *  Codex — Mission control task board
 *  Vanilla ES2020, one IIFE module, no framework, no bundler.
 *  API: /api/v1/codex   ·   Page: /codex
 * ═══════════════════════════════════════════════════════════════════
 */

const CODEX = (() => {
  'use strict';

  // ── Constants ──────────────────────────────────────────────────
  const API = '/api/v1/codex';
  const ACTOR = 'user:web';
  const TASK_LIMIT = 200;
  const BOARD_POLL_MS = 5000;
  const EVENT_POLL_MS = 2000;
  const ERR_TOAST_COOLDOWN = 20000;

  const STATES = [
    'pending_approval', 'backlog', 'queued', 'running', 'review',
    'done', 'failed', 'rejected', 'cancelled',
  ];
  const ACTIVE_STATES = new Set(['pending_approval', 'backlog', 'queued', 'running', 'review']);

  const STATUS_ICON = {
    pending_approval: 'pending_actions',
    backlog: 'stacks',
    queued: 'schedule',
    running: 'progress_activity',
    review: 'rate_review',
    done: 'task_alt',
    failed: 'error',
    rejected: 'block',
    cancelled: 'do_not_disturb_on',
  };
  const STEP_ICON = {
    pending: 'radio_button_unchecked',
    running: 'progress_activity',
    success: 'check_circle',
    error: 'cancel',
    skipped: 'remove_circle',
  };
  const EVENT_ICON = {
    created: 'add_circle', state: 'swap_horiz', step: 'list_alt', log: 'chat',
    approval: 'gavel', result: 'check_circle', error: 'error', plan: 'lightbulb',
  };
  const STAT_TILES = [
    { key: 'total', filter: 'all', icon: 'inbox', label: 'codex.stat_total' },
    { key: 'pending_approval', filter: 'pending_approval', icon: 'pending_actions', label: 'codex.stat_pending_approval' },
    { key: 'backlog', filter: 'backlog', icon: 'stacks', label: 'codex.stat_backlog' },
    { key: 'queued', filter: 'queued', icon: 'schedule', label: 'codex.stat_queued' },
    { key: 'running', filter: 'running', icon: 'bolt', label: 'codex.stat_running' },
    { key: 'review', filter: 'review', icon: 'rate_review', label: 'codex.stat_review' },
    { key: 'done', filter: 'done', icon: 'task_alt', label: 'codex.stat_done' },
    { key: 'failed', filter: 'failed', icon: 'error', label: 'codex.stat_failed' },
  ];

  // ── State ──────────────────────────────────────────────────────
  const state = {
    tasks: [],            // last good snapshot, newest first
    stats: {},
    worker: null,
    filter: 'all',
    search: '',
    expanded: new Set(),  // task ids
    // Đồng hồ MÁY CHỦ lúc lấy danh sách gần nhất ({iso, at}) — xem serverNow().
    clock: null,
    events: {},           // taskId -> [event]
    cursor: {},           // taskId -> last event ts
    eventsLoaded: {},     // taskId -> bool
    busy: {},             // taskId -> bool (action in flight)
    planning: {},         // taskId -> bool
    assignees: null,
    auto: true,
    loaded: false,
    createdTask: null,
    noteMode: '',
    noteTaskId: '',
    lastListHtml: '',
    lastErrToast: 0,
  };

  let boardTimer = null;
  let eventTimer = null;

  // ── Tiny helpers ───────────────────────────────────────────────
  function t(key, vars) {
    return (typeof T === 'function') ? T(key, vars) : key;
  }

  // ── Xem trước file trong kết quả ──────────────────────────────
  // Kết quả là văn bản; video/ảnh trong đó chỉ là một dòng đường dẫn. Nhận
  // diện link http(s), đường dẫn /api/... và đường dẫn tuyệt đối trên máy
  // (/root/… hay C:\…) có đuôi media; mỗi file một player/ảnh nhỏ.
  const MEDIA_EXT = /\.(mp4|webm|mov|m4v|png|jpe?g|webp|gif|mp3|wav)$/i;
  const MEDIA_REF = /(https?:\/\/[^\s`'"<>)\]]+|(?:\/|[A-Za-z]:[\\/])[^\s`'"<>)\]]+)/g;

  function mediaRefs(text) {
    const out = [];
    const seen = new Set();
    for (const m of String(text || '').matchAll(MEDIA_REF)) {
      let ref = m[1].replace(/[.,;:]+$/, '');
      if (!MEDIA_EXT.test(ref)) continue;
      const name = ref.split(/[\\/]/).pop();
      if (seen.has(name)) continue;               // "Video: /root/x.mp4" và "Watch: …/x.mp4" là một file
      seen.add(name);
      out.push({ ref, name });
    }
    return out;
  }

  function mediaSrc(ref, taskId) {
    // Link tới chính máy này (http://127.0.0.1:5295/api/...) chỉ đúng từ trong
    // máy; trình duyệt của người dùng đi qua proxy của dashboard → dùng đường
    // dẫn tương đối cùng gốc.
    const local = ref.match(/^https?:\/\/(?:127\.0\.0\.1|localhost|0\.0\.0\.0)(?::\d+)?(\/.*)$/i);
    if (local) return local[1];
    if (/^https?:\/\//i.test(ref) || ref.startsWith('/api/')) return ref;
    return `${API}/tasks/${encodeURIComponent(taskId)}/file?path=${encodeURIComponent(ref)}`;
  }

  function mediaPreviewHtml(task) {
    const refs = mediaRefs(task.result);
    if (!refs.length) return '';
    const items = refs.map(({ ref, name }) => {
      const src = mediaSrc(ref, task.id);
      const ext = (name.split('.').pop() || '').toLowerCase();
      let el;
      if (['mp4', 'webm', 'mov', 'm4v'].includes(ext)) el = `<video controls preload="metadata" src="${esc(src)}"></video>`;
      else if (['mp3', 'wav'].includes(ext)) el = `<audio controls preload="metadata" src="${esc(src)}"></audio>`;
      else el = `<a href="${esc(src)}" target="_blank" rel="noopener"><img src="${esc(src)}" alt="${esc(name)}" loading="lazy"></a>`;
      return `<figure class="cx-media-item">${el}<figcaption title="${esc(ref)}">${esc(name)}</figcaption></figure>`;
    });
    return `<div class="cx-media-head">${icon('preview')}${esc(t('codex.section_preview'))}</div>
      <div class="cx-media">${items.join('')}</div>`;
  }

  function esc(v) {
    if (v === null || v === undefined) return '';
    return String(v)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function $(id) { return document.getElementById(id); }

  function toast(msg, type) {
    const el = document.createElement('div');
    el.className = 'toast ' + (type || 'info');
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 3000);
  }

  /** Python isoformat() has microseconds and no timezone — trim to ms, parse local. */
  function parseTs(s) {
    if (!s) return null;
    const clean = String(s).replace(/(\.\d{3})\d+/, '$1');
    const d = new Date(clean);
    return isNaN(d.getTime()) ? null : d;
  }

  // "Mấy phút trước" phải đo bằng đồng hồ CỦA MÁY CHỦ: mốc trong task do máy chủ
  // ghi, nên đo bằng đồng hồ máy người xem là trộn hai đồng hồ khác nhau — máy chủ
  // ở múi giờ khác (hay máy khách sai giờ) làm task vừa tạo hiện thành "5 h ago".
  function serverNow() {
    const c = state.clock;
    if (!c) return Date.now();
    const base = parseTs(c.iso);
    if (!base) return Date.now();
    return base.getTime() + (Date.now() - c.at);
  }

  // Kết quả in trong <pre> nên địa chỉ web chỉ là chữ: muốn xem video vừa đăng phải
  // bôi đen rồi copy. Nhận CHUỖI ĐÃ ESCAPE và chỉ bọc thẻ <a> quanh http/https —
  // không mở cửa cho javascript: hay thẻ tự chế lọt vào.
  function linkify(escaped) {
    return String(escaped).replace(/https?:\/\/[^\s<]+/g, (m) => {
      let url = m, tail = '';
      // Cắt đuôi LẶP LẠI: dấu nháy trong chuỗi đã escape ("&quot;", "&#39;") và dấu
      // câu cuối câu đều không thuộc về địa chỉ, và chúng đứng lẫn nhau — một địa chỉ
      // trong ngoặc kép kết thúc bằng &quot; mà bên trong đã có sẵn dấu ';'.
      for (let i = 0; i < 6; i++) {
        const ent = /(&quot;|&#39;|&gt;)$/.exec(url);
        if (ent) { tail = ent[0] + tail; url = url.slice(0, -ent[0].length); continue; }
        const punct = /[.,;:!?)\]}]$/.exec(url);
        if (punct) { tail = punct[0] + tail; url = url.slice(0, -1); continue; }
        break;
      }
      if (!url) return m;
      return `<a href="${url}" target="_blank" rel="noopener noreferrer">${url}</a>${tail}`;
    });
  }

  function relTime(ts) {
    const d = parseTs(ts);
    if (!d) return '';
    const sec = Math.max(0, Math.floor((serverNow() - d.getTime()) / 1000));
    if (sec < 60) return t('codex.time_now');
    if (sec < 3600) return t('codex.time_min', { n: Math.floor(sec / 60) });
    if (sec < 86400) return t('codex.time_hour', { n: Math.floor(sec / 3600) });
    return t('codex.time_day', { n: Math.floor(sec / 86400) });
  }

  function clockTime(ts) {
    const d = parseTs(ts);
    if (!d) return '';
    const p = (n) => String(n).padStart(2, '0');
    return p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds());
  }

  function duration(from, to) {
    const a = parseTs(from), b = parseTs(to);
    if (!a || !b) return '';
    const sec = Math.max(0, Math.round((b.getTime() - a.getTime()) / 1000));
    if (sec < 60) return sec + 's';
    const m = Math.floor(sec / 60), s = sec % 60;
    if (m < 60) return m + 'm ' + s + 's';
    return Math.floor(m / 60) + 'h ' + (m % 60) + 'm';
  }

  function statusLabel(status) {
    return STATES.indexOf(status) >= 0 ? t('codex.status_' + status) : String(status || '');
  }

  function stepLabel(status) {
    return STEP_ICON[status] ? t('codex.step_' + status) : String(status || '');
  }

  function icon(name, cls) {
    return '<span class="material-symbols-outlined' + (cls ? ' ' + cls : '') + '">' + esc(name) + '</span>';
  }

  // ── HTTP ───────────────────────────────────────────────────────
  /** fetch → JSON → lỗi đọc được. Dùng chung cho route của Codex và route ngoài
      (Content Studio, content-video) để cả hai báo lỗi cùng một kiểu. */
  async function request(url, opts) {
    const options = Object.assign({ headers: { 'Content-Type': 'application/json' } }, opts || {});
    const resp = await fetch(url, options);
    const text = await resp.text();
    let data = null;
    if (text) {
      try { data = JSON.parse(text); } catch (e) { data = { detail: text }; }
    }
    if (!resp.ok) {
      let msg = (data && (data.detail || data.message)) || ('HTTP ' + resp.status);
      if (typeof msg !== 'string') { try { msg = JSON.stringify(msg); } catch (e) { msg = 'HTTP ' + resp.status; } }
      throw new Error(msg);
    }
    return data || {};
  }

  function api(path, opts) { return request(API + path, opts); }

  function taskUrl(id, suffix) {
    return '/tasks/' + encodeURIComponent(id) + (suffix || '');
  }

  // ── Data loading ───────────────────────────────────────────────
  async function refresh(manual) {
    const btn = $('cx-refresh-btn');
    if (manual && btn) btn.classList.add('cx-spin');

    const results = await Promise.allSettled([
      api('/stats'),
      api('/tasks?limit=' + TASK_LIMIT),
      api('/worker'),
    ]);

    if (results[0].status === 'fulfilled') state.stats = results[0].value || {};
    if (results[1].status === 'fulfilled') {
      const payload = results[1].value || {};
      // Máy chủ bản cũ không gửi `now` → giữ nguyên đồng hồ máy khách như trước.
      state.clock = payload.now ? { iso: payload.now, at: Date.now() } : null;
      const list = payload.tasks || [];
      list.sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')));
      state.tasks = list;
      state.loaded = true;
      pruneState();
    }
    state.worker = results[2].status === 'fulfilled' ? (results[2].value || {}) : null;

    const failed = results.filter(r => r.status === 'rejected');
    if (failed.length) {
      const now = Date.now();
      if (manual || now - state.lastErrToast > ERR_TOAST_COOLDOWN) {
        state.lastErrToast = now;
        toast(t('codex.toast_load_failed'), 'error');
      }
    }

    renderStats();
    renderChips();
    renderWorker();
    renderList();

    if (manual && btn) setTimeout(() => btn.classList.remove('cx-spin'), 400);
  }

  /** Drop cached events for tasks that no longer exist. */
  function pruneState() {
    const alive = new Set(state.tasks.map(x => x.id));
    Object.keys(state.events).forEach(id => {
      if (!alive.has(id)) {
        delete state.events[id]; delete state.cursor[id]; delete state.eventsLoaded[id];
        state.expanded.delete(id);
      }
    });
  }

  async function loadEvents(id, initial) {
    const after = initial ? '' : (state.cursor[id] || '');
    const qs = '/events?limit=200' + (after ? '&after=' + encodeURIComponent(after) : '');
    const data = await api(taskUrl(id, qs));
    const evs = (data && data.events) || [];
    if (initial) {
      state.events[id] = evs;
    } else if (evs.length) {
      state.events[id] = (state.events[id] || []).concat(evs).slice(-400);
    }
    if (evs.length) state.cursor[id] = evs[evs.length - 1].ts || state.cursor[id];
    state.eventsLoaded[id] = true;
    return evs.length;
  }

  async function pollEvents() {
    const ids = Array.from(state.expanded);
    if (!ids.length) return;
    for (const id of ids) {
      try {
        const fresh = await loadEvents(id, !state.eventsLoaded[id]);
        if (fresh) patchEvents(id);
      } catch (e) { /* transient — keep the last good log */ }
    }
  }

  function patchEvents(id) {
    const box = $('cx-ev-' + id);
    if (!box) return;
    const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
    box.innerHTML = eventsHtml(id);
    if (atBottom) box.scrollTop = box.scrollHeight;
    // Keep the render cache in sync so the next board tick does not redraw.
    state.lastListHtml = buildListHtml();
  }

  async function loadAssignees() {
    if (state.assignees) return state.assignees;
    try {
      const data = await api('/assignees');
      state.assignees = { agents: data.agents || [], teams: data.teams || [] };
    } catch (e) {
      state.assignees = { agents: [], teams: [] };
    }
    return state.assignees;
  }

  // ── Rendering: stats / chips / worker ──────────────────────────
  function renderStats() {
    const box = $('cx-stats');
    if (!box) return;
    box.innerHTML = STAT_TILES.map(tile => {
      const n = Number(state.stats[tile.key] || 0);
      const active = state.filter === tile.filter ? ' active' : '';
      const cls = tile.key === 'total' ? '' : ' st-' + tile.key;
      return `<button type="button" class="cx-stat${cls}${active}" onclick="CODEX.setFilter('${esc(tile.filter)}')">
          ${icon(tile.icon)}
          <span>
            <span class="cx-stat-num">${n}</span>
            <span class="cx-stat-label">${esc(t(tile.label))}</span>
          </span>
        </button>`;
    }).join('');
  }

  function renderChips() {
    const box = $('cx-chips');
    if (!box) return;
    const chips = [
      { f: 'all', label: t('codex.filter_all'), count: state.stats.total, cls: '' },
      { f: 'active', label: t('codex.filter_active'), count: state.stats.active, cls: '' },
    ].concat(STATES.map(s => ({
      f: s, label: statusLabel(s), count: state.stats[s], cls: ' st-' + s,
    })));

    box.innerHTML = chips.map(c => {
      const active = state.filter === c.f ? ' active' : '';
      const n = Number(c.count || 0);
      return `<button type="button" class="cx-chip${c.cls}${active}" onclick="CODEX.setFilter('${esc(c.f)}')">
          ${esc(c.label)}<span class="cx-chip-count">${n}</span>
        </button>`;
    }).join('');
  }

  function renderWorker() {
    const dot = $('cx-worker-dot');
    const txt = $('cx-worker-text');
    const wrap = $('cx-worker');
    if (!dot || !txt || !wrap) return;
    if (!state.worker) {
      dot.className = 'cx-dot';
      txt.textContent = t('codex.worker_unknown');
      wrap.title = '';
      return;
    }
    const running = !!state.worker.running;
    const inflight = (state.worker.inflight || []).length;
    dot.className = 'cx-dot ' + (running ? 'on' : 'off');
    txt.textContent = running ? t('codex.worker_running') : t('codex.worker_stopped');
    wrap.title = t('codex.worker_detail', {
      inflight: inflight,
      concurrency: Number(state.worker.concurrency || 0),
    });
  }

  // ── Rendering: board ───────────────────────────────────────────
  function visibleTasks() {
    let items = state.tasks.slice();
    if (state.filter === 'active') items = items.filter(x => ACTIVE_STATES.has(x.status));
    else if (state.filter !== 'all') items = items.filter(x => x.status === state.filter);

    const q = state.search.trim().toLowerCase();
    if (q) {
      items = items.filter(x => {
        const hay = ((x.title || '') + ' ' + (x.goal || '') + ' ' + (x.assignee_name || '') + ' #' + (x.seq || '')).toLowerCase();
        return hay.indexOf(q) >= 0;
      });
    }
    return items;
  }

  function renderList(force) {
    const box = $('cx-list');
    if (!box) return;
    const html = buildListHtml();
    if (force || html !== state.lastListHtml) {
      box.innerHTML = html;
      state.lastListHtml = html;
      // Pin every visible event log to the newest line.
      state.expanded.forEach(id => {
        const ev = $('cx-ev-' + id);
        if (ev) ev.scrollTop = ev.scrollHeight;
      });
    }
  }

  function buildListHtml() {
    if (!state.loaded) {
      return '<div class="cx-skeleton" aria-busy="true">' +
        '<div class="cx-skel-row"></div><div class="cx-skel-row"></div><div class="cx-skel-row"></div>' +
        '</div>';
    }
    const items = visibleTasks();
    if (!items.length) {
      const filtered = state.tasks.length > 0;
      return `<div class="cx-empty">
          ${icon(filtered ? 'filter_alt_off' : 'rocket_launch')}
          <div class="cx-empty-title">${esc(t(filtered ? 'codex.empty_filtered_title' : 'codex.empty_title'))}</div>
          <div class="cx-empty-desc">${esc(t(filtered ? 'codex.empty_filtered_desc' : 'codex.empty_desc'))}</div>
        </div>`;
    }
    return items.map(cardHtml).join('');
  }

  function cardHtml(task) {
    const id = esc(task.id);
    const status = STATES.indexOf(task.status) >= 0 ? task.status : 'queued';
    const expanded = state.expanded.has(task.id);
    const assignee = task.assignee_name || (task.assignee_id ? task.assignee_id : t('codex.assignee_auto'));
    const assigneeIcon = task.assignee_type === 'team' ? 'groups' : 'smart_toy';

    const meta = [];
    const pos = task.status === 'backlog' ? backlogPosition(task) : 0;
    if (pos) meta.push(`<span class="cx-meta-pos">${icon('format_list_numbered')}${esc(t('codex.meta_backlog_pos', { n: pos }))}</span>`);
    meta.push(`<span title="${esc(assignee)}">${icon(assigneeIcon)}${esc(assignee)}</span>`);
    meta.push(`<span>${icon('schedule')}${esc(relTime(task.created_at))}</span>`);
    if (task.created_by) meta.push(`<span>${icon('person')}${esc(t('codex.meta_created_by', { actor: task.created_by }))}</span>`);
    if (Number(task.priority || 0) > 0) meta.push(`<span>${icon('low_priority')}${esc(t('codex.meta_priority', { n: Number(task.priority) }))}</span>`);
    if (Number(task.retry_count || 0) > 0) meta.push(`<span>${icon('replay')}${esc(t('codex.meta_retry', { n: Number(task.retry_count) }))}</span>`);
    if (task.skill_ref && task.skill_ref.skill_name) meta.push(`<span>${icon('extension')}${esc(task.skill_ref.skill_name)}</span>`);
    const dur = duration(task.started_at, task.finished_at);
    if (dur) meta.push(`<span>${icon('timer')}${esc(dur)}</span>`);

    return `<article class="cx-card st-${esc(status)}${expanded ? ' expanded' : ''}" id="cx-card-${id}">
        <div class="cx-card-head" onclick="CODEX.toggle('${id}')">
          <span class="cx-seq">#${esc(task.seq || '?')}</span>
          <span class="cx-badge">${icon(STATUS_ICON[status] || 'help')}${esc(statusLabel(status))}</span>
          <div class="cx-card-main">
            <div class="cx-card-title">${esc(task.title || task.goal || '')}</div>
            <div class="cx-card-meta">${meta.join('')}</div>
            ${stripHtml(task)}
          </div>
          <div class="cx-card-actions" onclick="event.stopPropagation()">${actionsHtml(task)}</div>
          ${icon('expand_more', 'cx-chevron')}
        </div>
        ${expanded ? bodyHtml(task) : ''}
      </article>`;
  }

  /** Thứ tự (từ 1) của task trong hàng đợi của làn nó — sắp y hệt _backlog_key bên
      manager.py: ưu tiên cao trước, rồi tạo trước, rồi số task. */
  function backlogPosition(task) {
    const lane = task.lane || '';
    const cmp = (a, b) => (a < b ? -1 : (a > b ? 1 : 0));
    const line = state.tasks
      .filter(x => x.status === 'backlog' && (x.lane || '') === lane)
      .sort((a, b) => (Number(b.priority || 0) - Number(a.priority || 0)) ||
        cmp(String(a.created_at || ''), String(b.created_at || '')) ||
        (Number(a.seq || 0) - Number(b.seq || 0)));
    return line.findIndex(x => x.id === task.id) + 1;
  }

  function stripHtml(task) {
    const steps = Array.isArray(task.steps) ? task.steps : [];
    if (!steps.length) return '';
    const done = steps.filter(s => s.status === 'success' || s.status === 'skipped').length;
    const bars = steps.map(s => `<span class="cx-seg ${esc(s.status || 'pending')}"></span>`).join('');
    return `<div class="cx-strip">
        <span class="cx-strip-bars">${bars}</span>
        <span class="cx-strip-label">${esc(t('codex.steps_progress', { done: done, total: steps.length }))}</span>
      </div>`;
  }

  function actionsHtml(task) {
    const id = esc(task.id);
    const dis = state.busy[task.id] ? ' disabled' : '';
    const b = (cls, fn, ic, label) =>
      `<button type="button" class="cx-btn cx-btn-sm ${cls}" onclick="CODEX.${fn}('${id}')"${dis}>${icon(ic)}${esc(t(label))}</button>`;

    switch (task.status) {
      case 'pending_approval':
        return b('cx-btn-success', 'approve', 'check', 'codex.action_approve') +
               b('cx-btn-danger', 'reject', 'close', 'codex.action_reject');
      case 'backlog':
        return b('cx-btn-ghost', 'runNow', 'play_arrow', 'codex.action_run_now') +
               b('cx-btn-ghost', 'cancel', 'stop_circle', 'codex.action_cancel');
      case 'queued':
      case 'running':
        return b('cx-btn-ghost', 'cancel', 'stop_circle', 'codex.action_cancel');
      case 'review':
        return b('cx-btn-success', 'accept', 'done_all', 'codex.action_accept') +
               b('cx-btn-warn', 'requestChanges', 'edit_note', 'codex.action_request_changes');
      case 'failed':
      case 'rejected':
        return b('cx-btn-ghost', 'retry', 'replay', 'codex.action_retry');
      default:
        return '';
    }
  }

  function bodyHtml(task) {
    const id = esc(task.id);
    const parts = [];

    // Goal
    parts.push(`<div class="cx-section">
        <div class="cx-section-title">${icon('flag')}${esc(t('codex.section_goal'))}</div>
        <div class="cx-goal">${esc(task.goal || '')}</div>
      </div>`);

    // Approval decision
    const ap = task.approval || {};
    if (ap.decided_by || ap.note) {
      parts.push(`<div class="cx-section">
          <div class="cx-section-title">${icon('gavel')}${esc(t('codex.section_approval'))}</div>
          <div class="cx-muted">${esc(t('codex.approval_decided', { actor: ap.decided_by || '—' }))}${ap.decided_at ? ' · ' + esc(clockTime(ap.decided_at)) : ''}</div>
          ${ap.note ? `<div class="cx-approval-note">${esc(ap.note)}</div>` : ''}
        </div>`);
    }

    // AI plan
    const plan = Array.isArray(task.plan) ? task.plan : [];
    const canPlan = ['pending_approval', 'backlog', 'queued', 'rejected', 'failed'].indexOf(task.status) >= 0;
    if (plan.length) {
      parts.push(`<div class="cx-section">
          <div class="cx-section-title">${icon('lightbulb')}${esc(t('codex.section_plan'))}</div>
          <div class="cx-plan">${plan.map((p, i) => {
            const agent = p.agent_name || p.agent_id || t('codex.plan_unassigned');
            return `<div class="cx-plan-item">
                <span class="cx-plan-n">${esc(p.step || (i + 1))}</span>
                <div class="cx-plan-body">
                  <div class="cx-plan-desc">${esc(p.description || '')}</div>
                  <div class="cx-plan-agent">${icon('smart_toy')}${esc(agent)}</div>
                </div>
              </div>`;
          }).join('')}</div>
        </div>`);
    } else if (canPlan) {
      const planning = !!state.planning[task.id];
      parts.push(`<div class="cx-section">
          <button type="button" class="cx-btn cx-btn-sm cx-btn-ai" onclick="CODEX.planTask('${id}')"${planning ? ' disabled' : ''}>
            ${icon(planning ? 'progress_activity' : 'auto_awesome', planning ? 'cx-spin' : '')}
            ${esc(t(planning ? 'codex.planning' : 'codex.action_plan'))}
          </button>
        </div>`);
    }

    // Steps
    const steps = Array.isArray(task.steps) ? task.steps : [];
    if (steps.length) {
      parts.push(`<div class="cx-section">
          <div class="cx-section-title">${icon('checklist')}${esc(t('codex.section_steps'))}</div>
          <div class="cx-timeline">${steps.map(s => {
            const st = STEP_ICON[s.status] ? s.status : 'pending';
            const d = duration(s.started_at, s.ended_at);
            // Long-running steps (download, encode) publish 0-100 so the user
            // sees movement instead of an indeterminate spinner.
            const pctRaw = (s.progress === null || s.progress === undefined)
              ? null : Number(s.progress);
            const pct = (pctRaw !== null && isFinite(pctRaw))
              ? Math.max(0, Math.min(100, pctRaw)) : null;
            const showBar = pct !== null && st === 'running';
            return `<div class="cx-step ${esc(st)}">
                <span class="cx-step-dot"></span>
                <div class="cx-step-head">
                  <span class="cx-step-label">${esc(s.label || s.name || '')}</span>
                  <span class="cx-step-status">${esc(stepLabel(st))}</span>
                  ${showBar ? `<span class="cx-step-pct">${esc(pct.toFixed(0))}%</span>` : ''}
                  ${d ? `<span class="cx-step-time">${esc(d)}</span>` : ''}
                </div>
                ${showBar ? `<div class="cx-step-bar"><span style="width:${pct.toFixed(1)}%"></span></div>` : ''}
                ${s.message ? `<div class="cx-step-msg">${esc(s.message)}</div>` : ''}
              </div>`;
          }).join('')}</div>
        </div>`);
    }

    // Result
    if (task.result) {
      parts.push(`<div class="cx-section">
          <div class="cx-section-head">
            <div class="cx-section-title">${icon('description')}${esc(t('codex.section_result'))}</div>
            <button type="button" class="cx-btn cx-btn-sm cx-btn-ghost" onclick="CODEX.copyResult('${id}')">
              ${icon('content_copy')}${esc(t('codex.action_copy_result'))}
            </button>
          </div>
          <pre class="cx-pre">${linkify(esc(task.result))}</pre>
          ${mediaPreviewHtml(task)}
        </div>`);
    }

    // Error
    if (task.error) {
      parts.push(`<div class="cx-section">
          <div class="cx-section-title">${icon('report')}${esc(t('codex.section_error'))}</div>
          <pre class="cx-pre error">${linkify(esc(task.error))}</pre>
        </div>`);
    }

    // Event log
    parts.push(`<div class="cx-section">
        <div class="cx-section-title">${icon('history')}${esc(t('codex.section_events'))}</div>
        <div class="cx-events" id="cx-ev-${id}">${eventsHtml(task.id)}</div>
      </div>`);

    // Chi tiết dài hơn màn hình: không có nút này thì phải kéo ngược lên tận đầu
    // thẻ mới bấm thu lại được.
    parts.push(`<div class="cx-card-foot">
        <button type="button" class="cx-btn cx-btn-sm cx-btn-ghost" onclick="CODEX.collapse('${id}')">
          ${icon('expand_less')}${esc(t('codex.action_collapse'))}
        </button>
      </div>`);

    return `<div class="cx-card-body">${parts.join('')}</div>`;
  }

  function eventsHtml(taskId) {
    if (!state.eventsLoaded[taskId]) {
      return `<div class="cx-muted">${esc(t('codex.events_loading'))}</div>`;
    }
    const evs = state.events[taskId] || [];
    if (!evs.length) return `<div class="cx-muted">${esc(t('codex.no_events'))}</div>`;
    return evs.map(ev => {
      const kind = EVENT_ICON[ev.kind] ? ev.kind : 'log';
      return `<div class="cx-ev k-${esc(kind)}">
          ${icon(EVENT_ICON[kind])}
          <span class="cx-ev-time">${esc(clockTime(ev.ts))}</span>
          <span class="cx-ev-actor">[${esc(ev.actor || 'system')}]</span>
          <span class="cx-ev-msg">${esc(ev.message || '')}</span>
        </div>`;
    }).join('');
  }

  // ── Interaction ────────────────────────────────────────────────
  function collapse(taskId) {
    if (!state.expanded.has(taskId)) return;
    state.expanded.delete(taskId);
    renderList(true);
    // Thu từ dưới lên: chỗ đang nhìn vừa biến mất, nên đưa chính thẻ đó về tầm mắt
    // thay vì để trang nhảy tới một nơi bất kỳ.
    const card = $('cx-card-' + taskId);
    if (card && card.scrollIntoView) card.scrollIntoView({ block: 'nearest' });
  }

  async function toggle(taskId) {
    if (state.expanded.has(taskId)) {
      state.expanded.delete(taskId);
      renderList(true);
      return;
    }
    state.expanded.add(taskId);
    renderList(true);
    try {
      await loadEvents(taskId, true);
      patchEvents(taskId);
    } catch (e) {
      state.eventsLoaded[taskId] = true;
      patchEvents(taskId);
      toast(t('codex.toast_load_failed'), 'error');
    }
  }

  function setFilter(f) {
    state.filter = f;
    renderStats();
    renderChips();
    renderList(true);
  }

  function onSearch(v) {
    state.search = v || '';
    renderList(true);
  }

  function setAuto(on) {
    state.auto = !!on;
    if (state.auto) refresh(false);
  }

  /** Policy switch: when on, new tasks skip the human approval gate. */
  async function setAutoApprove(on) {
    const box = $('cx-auto-approve');
    try {
      const data = await api('/settings', {
        method: 'PUT', body: JSON.stringify({ auto_approve: !!on }),
      });
      state.autoApprove = !!(data && data.auto_approve);
      toast(t(state.autoApprove ? 'codex.toast_auto_approve_on'
                                : 'codex.toast_auto_approve_off'), 'success');
    } catch (e) {
      if (box) box.checked = !on;          // put the switch back
      toast(t('codex.toast_action_failed', { error: e.message }), 'error');
    }
  }

  async function loadSettings() {
    try {
      const data = await api('/settings');
      state.autoApprove = !!(data && data.auto_approve);
    } catch (e) {
      state.autoApprove = false;
    }
    const box = $('cx-auto-approve');
    if (box) box.checked = state.autoApprove;
  }

  // ── Actions ────────────────────────────────────────────────────
  async function act(taskId, suffix, body, okKey) {
    if (state.busy[taskId]) return;
    state.busy[taskId] = true;
    renderList(true);
    try {
      const data = await api(taskUrl(taskId, suffix), {
        method: 'POST',
        body: JSON.stringify(body || {}),
      });
      const task = (data && data.task) || {};
      toast(t(okKey, { seq: task.seq !== undefined && task.seq !== null ? task.seq : '?' }), 'success');
    } catch (e) {
      toast(t('codex.toast_action_failed', { error: e.message }), 'error');
    } finally {
      delete state.busy[taskId];
      await refresh(false);
      renderList(true);
    }
  }

  function approve(id) { act(id, '/approve', { actor: ACTOR, note: '' }, 'codex.toast_approved'); }
  function cancel(id) { act(id, '/cancel', { actor: ACTOR }, 'codex.toast_cancelled'); }
  function retry(id) { act(id, '/retry', { actor: ACTOR }, 'codex.toast_retried'); }
  function runNow(id) { act(id, '/run-now', { actor: ACTOR }, 'codex.toast_run_now'); }
  function accept(id) { act(id, '/review', { accepted: true, actor: ACTOR, feedback: '' }, 'codex.toast_accepted'); }

  function reject(id) { openNote('reject', id); }
  function requestChanges(id) { openNote('changes', id); }

  function openNote(mode, taskId) {
    state.noteMode = mode;
    state.noteTaskId = taskId;
    const isReject = mode === 'reject';
    $('cx-note-title').textContent = t(isReject ? 'codex.modal_reject_title' : 'codex.modal_changes_title');
    $('cx-note-hint').textContent = t(isReject ? 'codex.modal_reject_hint' : 'codex.modal_changes_hint');
    const ta = $('cx-note-text');
    ta.value = '';
    ta.placeholder = t(isReject ? 'codex.note_placeholder' : 'codex.feedback_placeholder');
    const btn = $('cx-note-confirm');
    btn.textContent = t(isReject ? 'codex.btn_confirm_reject' : 'codex.btn_confirm_changes');
    btn.className = 'cx-btn ' + (isReject ? 'cx-btn-danger' : 'cx-btn-primary');
    btn.disabled = false;
    $('cx-modal-note').classList.remove('hidden');
    setTimeout(() => ta.focus(), 50);
  }

  async function confirmNote() {
    const text = ($('cx-note-text').value || '').trim();
    const id = state.noteTaskId;
    const mode = state.noteMode;
    closeModal('cx-modal-note');
    if (!id) return;
    if (mode === 'reject') {
      await act(id, '/reject', { actor: ACTOR, note: text }, 'codex.toast_rejected');
    } else {
      await act(id, '/review', { accepted: false, actor: ACTOR, feedback: text }, 'codex.toast_changes');
    }
  }

  async function copyResult(taskId) {
    const task = state.tasks.find(x => x.id === taskId);
    if (!task || !task.result) return;
    try {
      await navigator.clipboard.writeText(task.result);
      toast(t('codex.toast_copied'), 'success');
    } catch (e) {
      toast(t('codex.toast_action_failed', { error: e.message }), 'error');
    }
  }

  // ── Planning ───────────────────────────────────────────────────
  async function planTask(taskId) {
    if (state.planning[taskId]) return;
    state.planning[taskId] = true;
    renderList(true);
    try {
      const data = await api(taskUrl(taskId, '/plan'), { method: 'POST' });
      const plan = (data && data.task && data.task.plan) || [];
      toast(t('codex.toast_planned', { n: plan.length }), 'success');
    } catch (e) {
      toast(t('codex.toast_action_failed', { error: e.message }), 'error');
    } finally {
      delete state.planning[taskId];
      await refresh(false);
      renderList(true);
    }
  }

  // ── New task modal ─────────────────────────────────────────────
  async function openNewTask() {
    state.createdTask = null;
    $('cx-new-step-form').classList.remove('hidden');
    $('cx-new-step-done').classList.add('hidden');
    $('cx-f-goal').value = '';
    $('cx-f-title').value = '';
    $('cx-f-priority').value = '0';
    $('cx-f-approval').checked = true;
    $('cx-plan-preview').innerHTML = '';
    $('cx-plan-btn').classList.remove('hidden');
    $('cx-created-desc').textContent = t('codex.created_desc');
    $('cx-v-content').value = '';
    $('cx-v-title').value = '';
    $('cx-v-review').checked = true;
    $('cx-v-preset').innerHTML = '<option value="">…</option>';
    $('cx-v-preset').disabled = true;
    $('cx-v-length').innerHTML = '';          // rỗng → renderVideoLength lấy lựa chọn đã nhớ
    $('cx-v-minutes').value = String(clampMinutes(lsGet(CV_MINUTES_KEY) || 10));
    onVideoContent();
    renderVideoSummary();
    const btn = $('cx-create-btn');
    btn.disabled = false;
    $('cx-queue-btn').disabled = false;
    $('cx-modal-new').classList.remove('hidden');
    setNewKind(lsGet(NEW_KIND_KEY) || 'general');
    // Mẫu và agent là hai lời gọi độc lập — nạp song song, đừng bắt người dùng
    // chờ cái này xong mới thấy cái kia.
    const presetsReady = loadPresets();

    const sel = $('cx-f-assignee');
    sel.innerHTML = `<option value="">${esc(t('codex.assignee_auto_option'))}</option>`;
    const data = await loadAssignees();
    const groups = [];
    if (data.agents.length) {
      groups.push(`<optgroup label="${esc(t('codex.group_agents'))}">` + data.agents.map(a =>
        `<option value="agent:${esc(a.id)}">${esc(a.name || a.id)}${a.role ? ' — ' + esc(a.role) : ''}</option>`
      ).join('') + '</optgroup>');
    }
    if (data.teams.length) {
      groups.push(`<optgroup label="${esc(t('codex.group_teams'))}">` + data.teams.map(x =>
        `<option value="team:${esc(x.id)}">${esc(x.name || x.id)}${x.strategy ? ' — ' + esc(x.strategy) : ''}</option>`
      ).join('') + '</optgroup>');
    }
    sel.innerHTML += groups.join('');
    fillVideoAgents(data.agents);
    presetsReady.then(fillVideoPresets);
  }

  async function submitNewTask() {
    if (state.newKind === 'video') return submitVideo();
    const goal = ($('cx-f-goal').value || '').trim();
    if (!goal) {
      toast(t('codex.toast_goal_required'), 'error');
      $('cx-f-goal').focus();
      return;
    }
    const raw = $('cx-f-assignee').value || '';
    const sep = raw.indexOf(':');
    const assigneeType = sep > 0 ? raw.slice(0, sep) : 'agent';
    const assigneeId = sep > 0 ? raw.slice(sep + 1) : '';

    const payload = {
      goal: goal,
      title: ($('cx-f-title').value || '').trim(),
      assignee_type: assigneeType,
      assignee_id: assigneeId,
      assignee_name: '',
      approval_required: !!$('cx-f-approval').checked,
      priority: parseInt($('cx-f-priority').value, 10) || 0,
      created_by: 'user',
    };

    const btn = $('cx-create-btn');
    btn.disabled = true;
    try {
      const data = await api('/tasks', { method: 'POST', body: JSON.stringify(payload) });
      const task = (data && data.task) || {};
      state.createdTask = task;
      toast(t('codex.toast_created', { seq: task.seq || '?' }), 'success');
      $('cx-created-title').textContent = t('codex.created_title', { seq: task.seq || '?' });
      $('cx-new-step-form').classList.add('hidden');
      $('cx-new-step-done').classList.remove('hidden');
      const planBtn = $('cx-plan-btn');
      planBtn.disabled = false;
      await refresh(false);
    } catch (e) {
      toast(t('codex.toast_action_failed', { error: e.message }), 'error');
    } finally {
      btn.disabled = false;
    }
  }

  // ── New task: loại việc + "Tạo video từ nội dung" ──────────────
  const NEW_KIND_KEY = 'codex.newKind';
  const CV_PRESET_KEY = 'codex.cvPreset';
  const CV_AGENT_KEY = 'codex.cvAgent';
  // PHẢI khớp SOURCE_TEXT_MAX trong content_video/pipeline.py — lệch nhau thì
  // ô đếm cho qua mà máy chủ lại từ chối, hoặc ngược lại.
  const CV_MAX_CHARS = 60000;
  const CV_LEN_KEYS = {
    short_60s: 'codex.cv_len_short_60s', short_3m: 'codex.cv_len_short_3m',
    standard: 'codex.cv_len_standard', long_10m: 'codex.cv_len_long_10m',
  };
  const CV_ENGINES = { capcut: 'CapCut', edge: 'Edge TTS', vibevoice: 'VibeVoice' };

  function lsGet(k) { try { return localStorage.getItem(k) || ''; } catch (e) { return ''; } }
  function lsSet(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* chế độ riêng tư */ } }

  /** Tên ngôn ngữ theo NGÔN NGỮ GIAO DIỆN ("es" → "Tiếng Tây Ban Nha" / "Spanish"). */
  function langName(code) {
    if (!code) return '';
    try {
      const dn = new Intl.DisplayNames([document.documentElement.lang || 'en'], { type: 'language' });
      return dn.of(code) || code;
    } catch (e) {
      return code;
    }
  }

  function setNewKind(kind) {
    state.newKind = kind === 'video' ? 'video' : 'general';
    lsSet(NEW_KIND_KEY, state.newKind);
    const video = state.newKind === 'video';
    document.querySelectorAll('#cx-modal-new .cx-kind-opt').forEach(b =>
      b.setAttribute('aria-checked', String(b.dataset.kind === state.newKind)));
    $('cx-new-general').classList.toggle('hidden', video);
    $('cx-new-video').classList.toggle('hidden', !video);
    // "Đưa vào hàng đợi" chỉ có với video: việc chung không có làn để chờ tới lượt.
    $('cx-queue-btn').classList.toggle('hidden', !video);
    const label = $('cx-create-label');
    const key = video ? 'codex.btn_create_video' : 'codex.btn_create';
    label.setAttribute('data-i18n', key);
    label.textContent = t(key);
    setTimeout(() => $(video ? 'cx-v-content' : 'cx-f-goal').focus(), 30);
  }

  /** {tên: preset} của Content Studio; `false` khi Studio chưa cài / đang tắt. */
  async function loadPresets() {
    try {
      const data = await request('/api/v1/studio/presets');
      const p = data && data.presets;
      state.presets = (p && typeof p === 'object' && !Array.isArray(p)) ? p : {};
    } catch (e) {
      state.presets = false;
    }
    return state.presets;
  }

  function fillVideoPresets() {
    const sel = $('cx-v-preset');
    const names = state.presets ? Object.keys(state.presets).sort((a, b) => a.localeCompare(b)) : [];
    sel.innerHTML = `<option value="">${esc(t('codex.cv_pick_template'))}</option>` +
      names.map(n => `<option value="${esc(n)}">${esc(n)}</option>`).join('');
    sel.disabled = !names.length;
    const saved = lsGet(CV_PRESET_KEY);
    if (saved && names.includes(saved)) sel.value = saved;
    else if (names.length === 1) sel.value = names[0];
    renderVideoSummary();
  }

  function fillVideoAgents(agents) {
    const sel = $('cx-v-agent');
    if (!agents.length) {
      sel.innerHTML = `<option value="">${esc(t('codex.cv_no_agents'))}</option>`;
      sel.disabled = true;
      return;
    }
    sel.disabled = false;
    // Hiện model ngay trong tên: agent là "ai viết", và model của nó quyết định
    // kịch bản ra sao — người dùng phải thấy được trước khi bấm.
    sel.innerHTML = agents.map(a =>
      `<option value="${esc(a.id)}">${esc(a.name || a.id)} · ${esc(a.model || t('codex.cv_default_model'))}</option>`
    ).join('');
    const saved = lsGet(CV_AGENT_KEY);
    if (saved && agents.some(a => a.id === saved)) sel.value = saved;
  }

  /** Thẻ tóm tắt mẫu: NGÔN NGỮ đứng đầu — đó là thứ AI sẽ viết lại theo. */
  function renderVideoSummary() {
    renderVideoLength();          // nhãn "Theo mẫu · …" đổi theo mẫu đang chọn
    const box = $('cx-v-summary');
    const show = (warn, html) => { box.className = 'cx-tpl' + (warn ? ' warn' : ''); box.innerHTML = html; };
    if (state.presets === false) {
      show(true, `<div class="cx-tpl-hint">${esc(t('codex.cv_studio_missing'))}</div>`);
      return;
    }
    if (state.presets && !Object.keys(state.presets).length) {
      show(true, `<div class="cx-tpl-hint">${esc(t('codex.cv_templates_none'))}</div>`);
      return;
    }
    const name = $('cx-v-preset').value;
    const p = (name && state.presets) ? state.presets[name] : null;
    if (!p) { box.className = 'cx-tpl hidden'; box.innerHTML = ''; return; }
    const lang = String(p.wizLanguage || '').trim();
    const fixed = lang && lang !== 'auto';
    const meta = [];
    if (p.wizAspectRatio) meta.push(p.wizAspectRatio);
    // Độ dài có ô riêng bên dưới: "Standard" trong thẻ này từng làm người dùng
    // tưởng nó chỉ là nhãn, trong khi nó quyết độ dài video.
    if (p.wizTtsEngine) meta.push(CV_ENGINES[p.wizTtsEngine] || p.wizTtsEngine);
    if (p.wizVideoLayout) meta.push(t('codex.cv_layout', { id: p.wizVideoLayout }));
    show(false,
      `<div class="cx-tpl-lang">${icon('translate')}<span>${esc(fixed ? langName(lang) : t('codex.cv_lang_auto'))}</span></div>
       <div class="cx-tpl-hint">${esc(t(fixed ? 'codex.cv_writes_hint' : 'codex.cv_lang_auto_hint'))}</div>` +
      (meta.length ? `<div class="cx-tpl-meta">${esc(meta.join(' · '))}</div>` : ''));
  }

  function onVideoPreset() {
    lsSet(CV_PRESET_KEY, $('cx-v-preset').value || '');
    renderVideoSummary();
  }

  function onVideoAgent() {
    lsSet(CV_AGENT_KEY, $('cx-v-agent').value || '');
  }

  // ── Độ dài video: theo bài dán (mặc định) / theo mẫu / tự chọn phút ──
  const CV_LENGTH_KEY = 'codex.cvLength';
  const CV_MINUTES_KEY = 'codex.cvMinutes';
  // PHẢI khớp content_video/pipeline.py (WORDS_PER_MINUTE, _WORDS_MIN/_WORDS_MAX,
  // DEFAULT_WORDS, _VIDEO_LENGTH_WORDS, content_words) — lệch nhau là ô ước lượng
  // nói một đằng, video ra một nẻo. tests/codex_video_length_test.js canh.
  const CV_WPM = 150;
  const CV_WORDS_MIN = 120;
  const CV_WORDS_MAX = 4000;
  const CV_DEFAULT_WORDS = 260;
  const CV_LEN_WORDS = { short_60s: 150, short_3m: 450, standard: 800, long_10m: 1600 };
  const CV_CJK_RE = /[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]/g;
  const CV_THAI_RE = /[\u0e00-\u0e7f]/g;

  /** Số chữ ĐỌC của một bài — y hệt content_words() bên pipeline: chữ Hán/kana
   *  ~2 ký tự một chữ, chữ Thái ~5, dấu câu đứng riêng không tính. */
  function cvWords(txt) {
    const s = String(txt || '');
    const cjk = (s.match(CV_CJK_RE) || []).length;
    const thai = (s.match(CV_THAI_RE) || []).length;
    const rest = s.replace(CV_CJK_RE, ' ').replace(CV_THAI_RE, ' ')
      .split(/\s+/).filter(w => /[\p{L}\p{N}]/u.test(w)).length;
    return rest + Math.floor((cjk + 1) / 2) + Math.floor((thai + 2) / 5);
  }

  /** Số phút đọc của `words` chữ: "20" từ 10 phút trở lên, "5.3" dưới đó. */
  function fmtMin(words) {
    const m = words / CV_WPM;
    return (m >= 10 ? Math.round(m) : Math.round(m * 10) / 10).toLocaleString();
  }

  function clampMinutes(v) {
    const n = Math.round(Number(v));
    const max = Math.floor(CV_WORDS_MAX / CV_WPM);
    return Number.isFinite(n) && n > 0 ? Math.min(max, n) : 10;
  }

  /** Ô "Độ dài video". Mặc định THEO BÀI DÁN: trước đây độ dài lấy từ ô Video
   *  Length của mẫu, nên dán dài hay ngắn cũng ra ~14 shot (11/9/2026). */
  function renderVideoLength() {
    const sel = $('cx-v-length');
    if (!sel) return;
    const have = cvWords($('cx-v-content').value || '');
    const name = $('cx-v-preset').value;
    const p = (name && state.presets) ? state.presets[name] : null;
    const lenKey = (p && p.wizVideoLength) || '';
    const tplWords = CV_LEN_WORDS[lenKey] || CV_DEFAULT_WORDS;
    const tplLabel = lenKey ? (CV_LEN_KEYS[lenKey] ? t(CV_LEN_KEYS[lenKey]) : lenKey) : t('codex.cv_len_default');
    const fit = Math.max(CV_WORDS_MIN, Math.min(CV_WORDS_MAX, have));
    const want = sel.value || lsGet(CV_LENGTH_KEY) || 'content';
    sel.innerHTML =
      `<option value="content">${esc(have ? t('codex.cv_len_mode_content', { min: fmtMin(fit) })
                                          : t('codex.cv_len_mode_content_empty'))}</option>` +
      `<option value="template">${esc(t('codex.cv_len_mode_template', { len: tplLabel, min: fmtMin(tplWords) }))}</option>` +
      `<option value="minutes">${esc(t('codex.cv_len_mode_minutes'))}</option>`;
    sel.value = ['content', 'template', 'minutes'].includes(want) ? want : 'content';
    const mode = sel.value;
    $('cx-v-minutes-wrap').classList.toggle('hidden', mode !== 'minutes');
    let msg;
    let warn = false;
    if (mode === 'content' && have > CV_WORDS_MAX) {
      msg = t('codex.cv_len_hint_capped', {
        words: have.toLocaleString(), max: CV_WORDS_MAX.toLocaleString(), min: fmtMin(CV_WORDS_MAX),
      });
      warn = true;
    } else if (mode === 'content') {
      msg = t('codex.cv_len_hint_content');
    } else {
      const words = mode === 'template' ? tplWords : clampMinutes($('cx-v-minutes').value) * CV_WPM;
      msg = t('codex.cv_len_hint_fit', { min: fmtMin(words) });
      // Bài dán dài hơn hẳn độ dài đã chọn → nói trước là sẽ bị NÉN.
      warn = have > words * 1.3;
    }
    const hint = $('cx-v-length-hint');
    hint.textContent = msg;
    hint.classList.toggle('warn', warn);
  }

  function onVideoLength() {
    lsSet(CV_LENGTH_KEY, $('cx-v-length').value || 'content');
    lsSet(CV_MINUTES_KEY, String(clampMinutes($('cx-v-minutes').value)));
    renderVideoLength();
  }

  function onVideoContent() {
    const txt = ($('cx-v-content').value || '').trim();
    const chars = txt.length;
    const words = cvWords(txt);
    const box = $('cx-v-count');
    box.textContent = chars
      ? t('codex.cv_count', { words: words.toLocaleString(), chars: chars.toLocaleString() })
      : '';
    box.classList.toggle('warn', chars > CV_MAX_CHARS);
    renderVideoLength();
  }

  /** Nút "Đưa vào hàng đợi": như "Tạo video", nhưng task chờ tới lượt trong hàng đợi. */
  function queueVideo() { return submitVideo(true); }

  /** queue=true: vào hàng đợi — Codex tự chạy khi không còn video nào đang làm.
      Bỏ trống (nút "Tạo video"): chạy liền, chen trước hàng đợi. */
  async function submitVideo(queue) {
    const hold = queue === true;
    const content = ($('cx-v-content').value || '').trim();
    const preset = $('cx-v-preset').value || '';
    const agentId = $('cx-v-agent').value || '';
    if (!content) {
      toast(t('codex.toast_video_content_required'), 'error');
      $('cx-v-content').focus();
      return;
    }
    if (content.length > CV_MAX_CHARS) {
      toast(t('codex.toast_video_content_too_long', {
        n: content.length.toLocaleString(), max: CV_MAX_CHARS.toLocaleString(),
      }), 'error');
      $('cx-v-content').focus();
      return;
    }
    if (!preset) {
      toast(t(state.presets === false ? 'codex.cv_studio_missing' : 'codex.toast_video_template_required'), 'error');
      $('cx-v-preset').focus();
      return;
    }
    if (!agentId) {
      toast(t('codex.toast_video_agent_required'), 'error');
      return;
    }
    const review = !!$('cx-v-review').checked;
    const title = ($('cx-v-title').value || '').trim();
    const options = { preset: preset };
    if (title) options.title = title;
    const lengthMode = $('cx-v-length').value || 'content';
    options.length_mode = lengthMode;
    if (lengthMode === 'minutes') options.target_words = clampMinutes($('cx-v-minutes').value) * CV_WPM;

    const btns = [$('cx-create-btn'), $('cx-queue-btn')];
    btns.forEach(b => { b.disabled = true; });
    try {
      const data = await request('/api/v1/content-video/run', {
        method: 'POST',
        body: JSON.stringify({
          agent_id: agentId, content: content, review: review,
          options: options, created_by: 'user', queue: hold,
        }),
      });
      if (!data || data.status !== 'queued') {
        throw new Error((data && (data.report || data.detail)) || 'not queued');
      }
      const task = data.task || {};
      state.createdTask = task;
      const seq = task.seq || '?';
      // Nói theo trạng thái THẬT của task: máy chủ bản cũ không biết `queue` và cho
      // chạy liền — khi đó đừng báo "đã vào hàng đợi".
      if (task.status === 'backlog') {
        const pos = Math.max(1, Number(data.position) || 1);
        toast(t('codex.toast_video_backlog', { seq: seq, pos: pos }), 'success');
        $('cx-created-title').textContent = t('codex.created_backlog_title', { seq: seq, pos: pos });
        $('cx-created-desc').textContent = t(review ? 'codex.created_backlog_desc_review'
                                                    : 'codex.created_backlog_desc_auto');
      } else {
        toast(t('codex.toast_video_queued', { seq: seq }), 'success');
        $('cx-created-title').textContent = t('codex.created_video_title', { seq: seq });
        $('cx-created-desc').textContent = t(review ? 'codex.created_video_desc_review'
                                                    : 'codex.created_video_desc_auto');
      }
      // "Lên kế hoạch bằng AI" là của việc chung; dây chuyền video đã có sẵn các bước.
      $('cx-plan-btn').classList.add('hidden');
      $('cx-new-step-form').classList.add('hidden');
      $('cx-new-step-done').classList.remove('hidden');
      await refresh(false);
    } catch (e) {
      toast(t('codex.toast_action_failed', { error: e.message }), 'error');
    } finally {
      btns.forEach(b => { b.disabled = false; });
    }
  }

  async function planFromModal() {
    const task = state.createdTask;
    if (!task || !task.id) return;
    const btn = $('cx-plan-btn');
    const preview = $('cx-plan-preview');
    btn.disabled = true;
    btn.innerHTML = icon('progress_activity', 'cx-spin') + '<span>' + esc(t('codex.planning')) + '</span>';
    preview.innerHTML = `<div class="cx-muted">${esc(t('codex.planning'))}</div>`;
    try {
      const data = await api(taskUrl(task.id, '/plan'), { method: 'POST' });
      const plan = (data && data.task && data.task.plan) || [];
      state.createdTask = (data && data.task) || task;
      toast(t('codex.toast_planned', { n: plan.length }), 'success');
      preview.innerHTML = `<div class="cx-plan">${plan.map((p, i) => `
          <div class="cx-plan-item">
            <span class="cx-plan-n">${esc(p.step || (i + 1))}</span>
            <div class="cx-plan-body">
              <div class="cx-plan-desc">${esc(p.description || '')}</div>
              <div class="cx-plan-agent">${icon('smart_toy')}${esc(p.agent_name || p.agent_id || t('codex.plan_unassigned'))}</div>
            </div>
          </div>`).join('')}</div>`;
      await refresh(false);
    } catch (e) {
      preview.innerHTML = `<div class="cx-muted">${esc(e.message)}</div>`;
      toast(t('codex.toast_action_failed', { error: e.message }), 'error');
    } finally {
      btn.disabled = false;
      btn.innerHTML = icon('auto_awesome') + '<span>' + esc(t('codex.btn_plan_now')) + '</span>';
    }
  }

  function closeModal(id) {
    const el = $(id);
    if (el) el.classList.add('hidden');
  }

  function onBackdrop(event, id) {
    if (event && event.target && event.target.id === id) closeModal(id);
  }

  // ── Boot ───────────────────────────────────────────────────────
  function startTimers() {
    if (boardTimer) clearInterval(boardTimer);
    if (eventTimer) clearInterval(eventTimer);
    boardTimer = setInterval(() => {
      if (document.hidden || !state.auto) return;
      refresh(false);
    }, BOARD_POLL_MS);
    eventTimer = setInterval(() => {
      if (document.hidden || !state.auto) return;
      pollEvents();
    }, EVENT_POLL_MS);
  }

  async function init() {
    if (typeof loadI18nFromApi === 'function') {
      try { await loadI18nFromApi(); } catch (e) { /* keys render as-is */ }
    }
    const auto = $('cx-auto');
    if (auto) state.auto = !!auto.checked;
    loadSettings();

    renderStats();
    renderChips();
    renderList(true);

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        closeModal('cx-modal-note');
        closeModal('cx-modal-new');
      }
    });
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden && state.auto) refresh(false);
    });

    await refresh(false);
    startTimers();
  }

  document.addEventListener('DOMContentLoaded', init);

  // ── Public surface (referenced by inline onclick handlers) ─────
  return {
    init, refresh, toggle, collapse, setFilter, onSearch, setAuto, setAutoApprove,
    approve, reject, cancel, retry, runNow, accept, requestChanges,
    confirmNote, copyResult, planTask,
    openNewTask, submitNewTask, queueVideo, setNewKind, onVideoPreset, onVideoAgent, onVideoContent, onVideoLength, planFromModal, closeModal, onBackdrop,
  };
})();
