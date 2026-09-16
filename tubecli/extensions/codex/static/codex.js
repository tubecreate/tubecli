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
    cancelled: 'stop_circle',
  };
  // Activity trong trình duyệt giữ tối đa chừng này dòng (RAM) — dòng cũ hơn vẫn nằm trong sổ của máy chủ.
  const EVENTS_KEEP = 150;
  const EVENT_ICON = {
    created: 'add_circle', state: 'swap_horiz', step: 'list_alt', log: 'chat',
    approval: 'gavel', result: 'check_circle', error: 'error', plan: 'lightbulb',
    progress: 'arrow_right',
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
    eventsBusy: {},       // taskId -> một lượt tải sự kiện đang chạy (chặn tải chồng → dòng lặp)
    busy: {},             // taskId -> bool (action in flight)
    planning: {},         // taskId -> bool
    planOpen: new Set(),  // task ids whose AI plan is expanded — collapsed by default
    assignees: null,
    googleTokens: null,       // tài khoản Google của Auth Manager cho «Lưu lên Google Drive»; false = tải hỏng
    googleTokensError: '',
    driveSync: null,          // hộp «Đồng bộ lên Drive»: { id, deleteAfter, info }
    laneChoice: null,         // hàm resolve của hộp «đang có video chạy» (đợi người dùng chọn)
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

  function fmtSecs(sec) {
    const n = Math.max(0, Math.round(Number(sec) || 0));
    if (n < 60) return n + 's';
    const m = Math.floor(n / 60), s = n % 60;
    if (m < 60) return m + 'm ' + s + 's';
    return Math.floor(m / 60) + 'h ' + (m % 60) + 'm';
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
    state.planOpen.forEach(id => { if (!alive.has(id)) state.planOpen.delete(id); });
  }

  async function loadEvents(id, initial) {
    // Hai lượt tải chồng nhau (nhịp tự làm mới + mở thẻ) cùng mốc "after" từng nối CÙNG một lô hai lần: Activity
    // lặp nguyên đoạn "crawl: success / Write the script" cùng một giây (15/9/2026). Chặn tải chồng + lọc trùng.
    if (state.eventsBusy[id]) return 0;
    state.eventsBusy[id] = true;
    try {
      const after = initial ? '' : (state.cursor[id] || '');
      const qs = '/events?limit=200' + (after ? '&after=' + encodeURIComponent(after) : '');
      const data = await api(taskUrl(id, qs));
      const evs = (data && data.events) || [];
      if (initial) {
        state.events[id] = evs.slice(-EVENTS_KEEP);
      } else if (evs.length) {
        const seen = new Set((state.events[id] || []).map(evKey));
        const fresh = evs.filter(ev => !seen.has(evKey(ev)));
        state.events[id] = (state.events[id] || []).concat(fresh).slice(-EVENTS_KEEP);
      }
      if (evs.length) state.cursor[id] = evs[evs.length - 1].ts || state.cursor[id];
      state.eventsLoaded[id] = true;
      return evs.length;
    } finally {
      state.eventsBusy[id] = false;
    }
  }

  function evKey(ev) {
    return (ev.ts || '') + '|' + (ev.kind || '') + '|' + (ev.message || '');
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
    patchNow();
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

    // Xoá: mọi task không còn chạy/chờ chạy. Nút hỏi trước (chỉ Codex hay cả file).
    const del = b('cx-btn-ghost cx-btn-del', 'confirmDelete', 'delete', 'codex.action_delete');
    // Đồng bộ lên Drive: task VIDEO đã xong. Máy chủ kiểm lại lúc bấm (task chỉ viết kịch bản thì nói rõ video ở đâu).
    const sync = task.lane === 'video'
      ? b('cx-btn-ghost', 'openDriveSync', 'add_to_drive', 'codex.action_drive_sync') : '';
    switch (task.status) {
      case 'pending_approval':
        return b('cx-btn-success', 'approve', 'check', 'codex.action_approve') +
               b('cx-btn-danger', 'reject', 'close', 'codex.action_reject') + del;
      case 'backlog':
        return b('cx-btn-ghost', 'runNow', 'play_arrow', 'codex.action_run_now') +
               b('cx-btn-ghost', 'cancel', 'stop_circle', 'codex.action_cancel') + del;
      case 'queued':
      case 'running':
        return b('cx-btn-ghost', 'cancel', 'stop_circle', 'codex.action_cancel');
      case 'review':
        return b('cx-btn-success', 'accept', 'done_all', 'codex.action_accept') +
               b('cx-btn-warn', 'requestChanges', 'edit_note', 'codex.action_request_changes') + sync;
      case 'failed':
      case 'rejected':
      case 'cancelled':
        // Huỷ xong vẫn Chạy lại được: pipeline tiếp từ bước đã dừng (checkpoint).
        return b('cx-btn-ghost', 'retry', 'replay', 'codex.action_retry') + del;
      case 'done':
        return sync + del;
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
      // Thu gọn MẶC ĐỊNH: kế hoạch của «Tạo video từ nội dung» là cả kịch bản (hàng chục cảnh),
      // mở thẻ ra là phải kéo qua cả trang mới tới các bước và nhật ký. Bấm tiêu đề để mở; trạng
      // thái nằm trong state.planOpen nên lượt tự làm mới không đóng lại (13/9/2026).
      const open = state.planOpen.has(task.id);
      parts.push(`<div class="cx-section">
          <button type="button" class="cx-section-title cx-section-toggle" aria-expanded="${open ? 'true' : 'false'}"
            title="${esc(t(open ? 'codex.plan_hide' : 'codex.plan_show'))}" onclick="CODEX.togglePlan('${id}')">
            ${icon('lightbulb')}${esc(t('codex.section_plan'))}
            <span class="cx-section-count">${esc(t('codex.plan_count', { n: plan.length }))}</span>
            ${icon(open ? 'expand_less' : 'expand_more', 'cx-section-chev')}
          </button>
          ${open ? `<div class="cx-plan">${plan.map((p, i) => {
            const agent = p.agent_name || p.agent_id || t('codex.plan_unassigned');
            return `<div class="cx-plan-item">
                <span class="cx-plan-n">${esc(p.step || (i + 1))}</span>
                <div class="cx-plan-body">
                  <div class="cx-plan-desc">${esc(p.description || '')}</div>
                  <div class="cx-plan-agent">${icon('smart_toy')}${esc(agent)}</div>
                </div>
              </div>`;
          }).join('')}</div>` : ''}
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
            // Bước đang chạy là NƠI DUY NHẤT kể "đang làm gì / tới đâu / còn bao lâu" — một thanh tiến độ, một câu,
            // một dòng thời gian (user 15/9/2026: "trùng bar, thiết kế tối ưu dễ theo dõi hơn"). Phần đã xong: %
            // máy chủ gửi, không có thì đọc "12/69" / "scenes 7-12 of 60".
            const frac = st === 'running' ? stepFraction(s) : null;
            const showBar = frac !== null;
            return `<div class="cx-step ${esc(st)}">
                <span class="cx-step-dot"></span>
                <div class="cx-step-head">
                  <span class="cx-step-label">${esc(s.label || s.name || '')}</span>
                  <span class="cx-step-status">${esc(stepLabel(st))}</span>
                  ${showBar ? `<span class="cx-step-pct">${esc(String(Math.round(frac * 100)))}%</span>` : ''}
                  ${d ? `<span class="cx-step-time">${esc(d)}</span>` : ''}
                </div>
                ${showBar ? `<div class="cx-step-bar"><span style="width:${(frac * 100).toFixed(1)}%"></span></div>` : ''}
                ${s.message && s.message !== s.label ? `<div class="cx-step-msg">${esc(s.message)}</div>` : ''}
                ${st === 'running' ? stepEtaHtml(s, frac) : ''}
              </div>`;
          }).join('')}${waitingHtml(task)}</div>
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

  /** Phần đã xong của một bước (0..1) hay null: % máy chủ gửi, không có thì đọc "12/69" / "scenes 7-12 of 60". */
  function stepFraction(s) {
    const p = Number(s && s.progress);
    if (s && s.progress !== null && s.progress !== undefined && isFinite(p) && p > 0) {
      return Math.max(0, Math.min(1, p / 100));
    }
    const m = /(\d+)\s*(?:-\s*(\d+))?\s*(?:\/|\bof\b)\s*(\d+)/i.exec(String((s && s.message) || ''));
    if (m) {
      const total = Number(m[3]);
      const done = m[2] !== undefined ? Number(m[1]) - 1 : Number(m[1]);
      if (total > 0 && done >= 0 && done <= total) return done / total;
    }
    return null;
  }

  /** Chỗ trống "đã chạy … · còn khoảng …" dưới bước đang chạy — patchNow() điền mỗi nhịp, để danh sách không phải
   *  vẽ lại mỗi giây. */
  function stepEtaHtml(s, frac) {
    const f = (frac === null || frac === undefined) ? '' : Number(frac).toFixed(4);
    return `<div class="cx-step-eta" data-start="${esc(s.started_at || '')}" data-frac="${f}"></div>`;
  }

  /** Task đang chạy mà chưa bước nào chạy (giữa hai bước): nói ra thay vì để trống. */
  function waitingHtml(task) {
    const steps = Array.isArray(task.steps) ? task.steps : [];
    if (task.status !== 'running' || steps.some(s => s.status === 'running')) return '';
    return `<div class="cx-step-wait">${icon('hourglass_top')}<span>${esc(t('codex.now_waiting'))}</span></div>`;
  }

  /** "đã chạy 1m 40s · còn khoảng 5m 0s" — ước tính từ thời gian đã chạy của bước và phần đã xong. */
  function nowTimeText(el) {
    const start = parseTs(el.getAttribute('data-start'));
    if (!start) return '';
    const elapsed = Math.max(0, (serverNow() - start.getTime()) / 1000);
    const frac = parseFloat(el.getAttribute('data-frac'));
    let txt = t('codex.now_elapsed', { t: fmtSecs(elapsed) });
    if (isFinite(frac) && frac >= 0.03 && frac < 1 && elapsed >= 5) {
      txt += ' · ' + t('codex.now_eta', { t: fmtSecs(elapsed * (1 - frac) / frac) });
    } else {
      txt += ' · ' + t('codex.now_eta_unknown');
    }
    return txt;
  }

  function patchNow() {
    state.expanded.forEach(id => {
      const card = $('cx-card-' + id);
      if (!card || !card.querySelectorAll) return;
      card.querySelectorAll('.cx-step-eta[data-start]').forEach(el => { el.textContent = nowTimeText(el); });
    });
  }

  /** Dòng của Activity = LỊCH SỬ gọn: bỏ "bắt đầu" (bước đang chạy đã hiện ở danh sách bước), gộp bước chỉ có MỘT câu
   *  vào dòng kết thúc ("[Crawl extra sources] Xong · 0s · no extra sources"), ẩn checkpoint. Bước dài vẫn liệt kê
   *  từng việc AI đã làm. */
  function activityRows(evs) {
    const rows = [];
    const lastProgress = {};   // step → {count, idx}
    for (const ev of evs || []) {
      if (ev.actor === 'content_video' && ev.message === 'checkpoint') continue;
      const kind = EVENT_ICON[ev.kind] ? ev.kind : 'log';
      const d = ev.data || {};
      const step = d.step || '';
      if (kind === 'step' && d.label && d.status === 'running') {
        if (d.detail) {
          lastProgress[step] = { count: 1, idx: rows.length };
          rows.push({ ev, kind: 'progress', who: d.label, msg: d.detail });
        }
        continue;
      }
      if (kind === 'progress') {
        const info = lastProgress[step] || { count: 0, idx: -1 };
        info.count += 1;
        info.idx = rows.length;
        lastProgress[step] = info;
        rows.push({ ev, kind, who: d.label || step || ev.actor || 'system', msg: ev.message || '' });
        continue;
      }
      if (kind === 'step' && d.label && d.status) {
        let detail = d.detail || '';
        const info = lastProgress[step];
        if (info && info.count === 1 && info.idx === rows.length - 1) {
          detail = detail || rows[info.idx].msg;
          rows.pop();
        }
        delete lastProgress[step];
        const head = stepLabel(d.status) + (typeof d.elapsed === 'number' ? ' · ' + fmtSecs(d.elapsed) : '');
        rows.push({ ev, kind, who: d.label, msg: head + (detail ? ' · ' + detail : ''), status: d.status });
        continue;
      }
      rows.push({ ev, kind, who: ev.actor || 'system', msg: ev.message || '' });
    }
    return rows;
  }

  function eventsHtml(taskId) {
    if (!state.eventsLoaded[taskId]) {
      return `<div class="cx-muted">${esc(t('codex.events_loading'))}</div>`;
    }
    const rows = activityRows(state.events[taskId] || []);
    if (!rows.length) return `<div class="cx-muted">${esc(t('codex.no_events'))}</div>`;
    return rows.map(r => `<div class="cx-ev k-${esc(r.kind)}${r.status ? ' s-' + esc(r.status) : ''}">
          ${icon(EVENT_ICON[r.kind])}
          <span class="cx-ev-time">${esc(clockTime(r.ev.ts))}</span>
          <span class="cx-ev-actor">[${esc(r.who)}]</span>
          <span class="cx-ev-msg">${esc(r.msg)}</span>
        </div>`).join('');
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

  // AI plan thu gọn mặc định (xem bodyHtml): bấm tiêu đề mở/đóng, giữ qua các lượt tự làm mới.
  function togglePlan(taskId) {
    if (state.planOpen.has(taskId)) state.planOpen.delete(taskId);
    else state.planOpen.add(taskId);
    renderList(true);
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

  /** Nút Xoá hỏi trước: chỉ bỏ khỏi bảng, hay xoá cả file (tập Studio, ảnh, giọng, video)
   *  của task video. Bấm nhầm là mất hàng trăm MB không lấy lại được (13/9/2026). */
  function confirmDelete(id) {
    const task = state.tasks.find(x => x.id === id);
    if (!task) return;
    state.deleteTaskId = id;
    const video = task.lane === 'video';
    $('cx-del-title').textContent = t('codex.modal_delete_title', { seq: task.seq });
    $('cx-del-hint').textContent = t(video ? 'codex.modal_delete_hint_video' : 'codex.modal_delete_hint');
    $('cx-del-files').classList.toggle('hidden', !video);
    $('cx-del-sync').classList.toggle('hidden', !video);
    $('cx-modal-delete').classList.remove('hidden');
  }

  async function doDelete(purge) {
    const id = state.deleteTaskId;
    if (!id || state.busy[id]) return;
    closeModal('cx-modal-delete');
    state.busy[id] = true;
    renderList(true);
    try {
      const data = await api(taskUrl(id, purge ? '?purge=1' : ''), { method: 'DELETE' });
      const task = (data && data.task) || {};
      const p = (data && data.purge) || null;
      state.expanded.delete(id);
      state.tasks = state.tasks.filter(x => x.id !== id);
      if (p && p.error) {
        toast(t('codex.toast_deleted_purge_error', { seq: task.seq, error: p.error }), 'error');
      } else if (p && p.files !== undefined) {
        toast(t('codex.toast_deleted_files', { seq: task.seq, n: p.files, mb: Math.round((p.bytes || 0) / 1048576) }), 'success');
      } else {
        toast(t('codex.toast_deleted', { seq: task.seq }), 'success');
      }
    } catch (e) {
      toast(t('codex.toast_action_failed', { error: e.message }), 'error');
    } finally {
      delete state.busy[id];
      state.deleteTaskId = '';
      await refresh(false);
      renderList(true);
    }
  }

  // ── Đồng bộ project lên Google Drive (nút trên thẻ + «Đồng bộ rồi xoá» trong hộp Delete, 16/9/2026) ──
  const DS_REASONS = {
    script_only: 'codex.ds_reason_script_only', no_video: 'codex.ds_reason_no_video',
    busy: 'codex.ds_reason_busy', not_video: 'codex.ds_reason_not_video',
  };

  /** Mở hộp: hỏi máy chủ task này có video để đẩy lên không, rồi mới hiện chọn tài khoản + quyền. */
  async function openDriveSync(id, deleteAfter) {
    const task = (state.tasks || []).find(x => x.id === id);
    if (!task) return;
    state.driveSync = { id: id, deleteAfter: !!deleteAfter, info: null };
    $('cx-ds-title').textContent = t(deleteAfter ? 'codex.ds_title_delete' : 'codex.ds_title', { seq: task.seq });
    $('cx-ds-hint').textContent = t('codex.cv_drive_loading');
    $('cx-ds-form').classList.add('hidden');
    $('cx-ds-go').disabled = true;
    $('cx-ds-go').textContent = t(deleteAfter ? 'codex.ds_go_delete' : 'codex.ds_go');
    $('cx-ds-share').value = lsGet(CV_DRIVE_SHARE_KEY) === 'private' ? 'private' : 'public';
    $('cx-modal-drive').classList.remove('hidden');
    let info;
    try {
      state.googleTokens = null;          // có thể vừa cấp quyền tài khoản mới
      const res = await Promise.all([
        request('/api/v1/content-video/tasks/' + encodeURIComponent(id) + '/drive-sync'),
        loadAssignees(), loadGoogleTokens(),
      ]);
      info = res[0] || {};
    } catch (e) {
      $('cx-ds-hint').textContent = t('codex.toast_action_failed', { error: e.message });
      return;
    }
    if (!state.driveSync || state.driveSync.id !== id) return;     // người dùng đã mở hộp của task khác
    state.driveSync.info = info;
    if (!info.ok) {
      $('cx-ds-hint').textContent = DS_REASONS[info.reason] ? t(DS_REASONS[info.reason]) : (info.message || '');
      return;
    }
    const again = !!(info.drive && info.drive.folder_url);
    $('cx-ds-hint').textContent = t(deleteAfter ? 'codex.ds_hint_delete' : (again ? 'codex.ds_hint_again' : 'codex.ds_hint'),
                                    { title: info.title || ('#' + task.seq) });
    $('cx-ds-form').classList.remove('hidden');
    renderDriveSyncAccounts(task);
  }

  /** Ô tài khoản của hộp: cùng luật chọn sẵn với form tạo task (tài khoản đã cấp cho agent ở tab Auth thắng). */
  function renderDriveSyncAccounts(task) {
    const sel = $('cx-ds-token');
    const hint = $('cx-ds-token-hint');
    const a = ((state.assignees && state.assignees.agents) || []).find(x => x.id === task.assignee_id);
    const creds = (a && a.auth_creds) || [];
    const tokens = state.googleTokens;
    const list = (tokens || []).filter(x => x.status !== 'revoked' && (x.scopes || []).join(' ').includes('drive'));
    const pick = pickDriveToken(list, creds, '', lsGet(CV_DRIVE_TOKEN_KEY));
    hint.classList.remove('warn');
    if (!pick) {
      sel.innerHTML = '<option value="">—</option>';
      sel.disabled = true;
      hint.textContent = tokens === false
        ? t('codex.cv_drive_load_failed', { msg: state.googleTokensError || '' }) : t('codex.cv_drive_none');
      hint.classList.add('warn');
      $('cx-ds-go').disabled = true;
      return;
    }
    const label = x => (x.authorized_email || x.credential_name || x.token_id)
      + (creds.includes(x.credential_id) ? ' ✓' : '');
    sel.innerHTML = list.map(x => {
      const ro = !driveCanWrite(x.scopes);
      return `<option value="${esc(x.token_id)}"${ro ? ' disabled' : ''}>${esc(label(x))}`
        + `${ro ? ' — ' + esc(t('codex.cv_drive_readonly')) : ''}</option>`;
    }).join('');
    sel.disabled = false;
    sel.value = pick;
    hint.textContent = t('codex.ds_account_hint');
    $('cx-ds-go').disabled = false;
  }

  async function startDriveSync() {
    const ds = state.driveSync;
    if (!ds || !ds.info || !ds.info.ok) return;
    const token = $('cx-ds-token').value || '';
    if (!token) {
      toast(t('codex.toast_video_drive_account_required'), 'error');
      return;
    }
    const pub = $('cx-ds-share').value !== 'private';
    lsSet(CV_DRIVE_TOKEN_KEY, token);
    lsSet(CV_DRIVE_SHARE_KEY, pub ? 'public' : 'private');
    $('cx-ds-go').disabled = true;
    try {
      const data = await request('/api/v1/content-video/tasks/' + encodeURIComponent(ds.id) + '/drive-sync', {
        method: 'POST',
        body: JSON.stringify({ drive_token_id: token, drive_public: pub, delete_after: ds.deleteAfter }),
      });
      closeModal('cx-modal-drive');
      state.driveSync = null;
      toast(t(ds.deleteAfter ? 'codex.toast_ds_queued_delete' : 'codex.toast_ds_queued',
              { seq: (data && data.task && data.task.seq) || '?', src: ds.info.seq }), 'success');
      await refresh(false);
    } catch (e) {
      toast(t('codex.toast_action_failed', { error: e.message }), 'error');
      $('cx-ds-go').disabled = false;
    }
  }

  /** Nút «Đồng bộ lên Drive rồi xoá» trong hộp Delete: đóng hộp xoá, mở hộp Drive ở chế độ xoá-sau-khi-tải. */
  function syncThenDelete() {
    const id = state.deleteTaskId;
    closeModal('cx-modal-delete');
    state.deleteTaskId = '';
    if (id) openDriveSync(id, true);
  }

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
    $('cx-f-priority').value = String(parseInt(lsGet(G_PRIORITY_KEY), 10) || 0);
    $('cx-f-approval').checked = lsGet(G_APPROVAL_KEY) !== '0';
    $('cx-plan-preview').innerHTML = '';
    $('cx-plan-btn').classList.remove('hidden');
    $('cx-created-desc').textContent = t('codex.created_desc');
    $('cx-v-content').value = '';
    $('cx-v-split').checked = true;     // nhiều link = nhiều video; ô này chỉ hiện khi dán ≥2 dòng link
    $('cx-v-title').value = '';
    $('cx-v-review').checked = lsGet(CV_REVIEW_KEY) !== '0';
    state.ytProbe = null;
    $('cx-v-keeptheme').checked = lsGet(CV_KEEP_THEME_KEY) !== '0';
    $('cx-v-instructions').value = lsGet(CV_INSTR_KEY) || '';
    $('cx-v-drive').checked = lsGet(CV_DRIVE_KEY) === '1';
    $('cx-v-drive-share').value = lsGet(CV_DRIVE_SHARE_KEY) === 'private' ? 'private' : 'public';
    state.googleTokens = null;          // nạp lại mỗi lần mở: có thể vừa cấp quyền tài khoản mới
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
    const driveReady = loadGoogleTokens();
    renderDriveAccounts();

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
    pickSaved(sel, lsGet(G_ASSIGNEE_KEY));
    fillVideoAgents(data.agents);
    presetsReady.then(fillVideoPresets);
    driveReady.then(renderDriveAccounts);   // sau fillVideoAgents: chọn sẵn theo tab Auth của agent
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
    rememberNewTaskForm();

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
  // Phần còn lại của form cũng phải nhớ: người dùng từng phải bỏ tick «Duyệt kịch bản» và
  // chọn lại người nhận / ưu tiên MỖI lần thêm việc (14/9/2026). Lưu lúc gửi, trả lại lúc mở.
  // Nội dung và tiêu đề thì không: mỗi việc một khác.
  const CV_REVIEW_KEY = 'codex.cvReview';        // '1' | '0'
  const G_ASSIGNEE_KEY = 'codex.gAssignee';      // 'agent:<id>' | 'team:<id>' | ''
  const G_APPROVAL_KEY = 'codex.gApproval';      // '1' | '0'
  const G_PRIORITY_KEY = 'codex.gPriority';

  /** Lưu cài đặt của form lúc gửi — «lần gần nhất» là lần thật sự tạo việc. */
  function rememberNewTaskForm() {
    lsSet(G_ASSIGNEE_KEY, $('cx-f-assignee').value || '');
    lsSet(G_APPROVAL_KEY, $('cx-f-approval').checked ? '1' : '0');
    lsSet(G_PRIORITY_KEY, String(parseInt($('cx-f-priority').value, 10) || 0));
    lsSet(CV_REVIEW_KEY, $('cx-v-review').checked ? '1' : '0');
    const keepTheme = $('cx-v-keeptheme');
    if (keepTheme) lsSet(CV_KEEP_THEME_KEY, keepTheme.checked ? '1' : '0');
    const instr = $('cx-v-instructions');
    if (instr) lsSet(CV_INSTR_KEY, (instr.value || '').slice(0, CV_INSTR_MAX));
    const drive = $('cx-v-drive');
    if (drive) lsSet(CV_DRIVE_KEY, drive.checked ? '1' : '0');
    const driveToken = $('cx-v-drive-token');
    if (drive && drive.checked && driveToken && driveToken.value) lsSet(CV_DRIVE_TOKEN_KEY, driveToken.value);
    const driveShare = $('cx-v-drive-share');
    if (driveShare) lsSet(CV_DRIVE_SHARE_KEY, driveShare.value === 'private' ? 'private' : 'public');
  }

  /** Chọn lại giá trị đã nhớ nếu nó vẫn còn trong danh sách (agent/nhóm có thể đã bị xoá). */
  function pickSaved(sel, saved) {
    if (!saved) return false;
    const ok = Array.from(sel.options || []).some(o => o.value === saved);
    if (ok) sel.value = saved;
    return ok;
  }
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
    renderDriveAccounts();          // tài khoản Drive chọn sẵn theo tab Auth của agent vừa chọn
  }

  // ── «Lưu lên Google Drive»: tài khoản Google nhận Sheet nội dung + ảnh + giọng + video ──
  /** Ghi được Drive không — PHẢI khớp content_video/drive_export.py can_write (drive_readonly thì không). */
  function driveCanWrite(scopes) {
    const joined = ' ' + (scopes || []).join(' ') + ' ';
    return joined.includes(' drive ') || joined.includes(' drive_file ')
      || joined.includes('auth/drive ') || joined.includes('auth/drive.file');
  }

  /** Tài khoản chọn sẵn. Tab Auth của agent thắng (user: "chọn auth trong tạo task như đã chọn trong auth của
   *  agent"): đang chọn một tài khoản đã cấp → giữ; không thì tài khoản đã cấp đầu tiên (đang sống trước).
   *  Agent chưa cấp tài khoản Drive nào → giữ lựa chọn hiện tại / lần gần nhất / tài khoản đầu tiên. */
  function pickDriveToken(tokens, granted, current, saved) {
    const creds = granted || [];
    const usable = (tokens || []).filter(x => x.status !== 'revoked' && driveCanWrite(x.scopes));
    const has = id => !!id && usable.some(x => x.token_id === id);
    const mine = usable.filter(x => creds.includes(x.credential_id))
      .sort((p, q) => ((p.status !== 'active') - (q.status !== 'active'))
        || (creds.indexOf(p.credential_id) - creds.indexOf(q.credential_id)));
    if (current && mine.some(x => x.token_id === current)) return current;
    if (mine.length) return mine[0].token_id;
    if (has(current)) return current;
    if (has(saved)) return saved;
    return usable.length ? usable[0].token_id : '';
  }

  function videoAgentGranted() {
    const id = $('cx-v-agent').value || '';
    const a = ((state.assignees && state.assignees.agents) || []).find(x => x.id === id);
    return { name: a ? (a.name || a.id) : '', creds: (a && a.auth_creds) || [] };
  }

  async function loadGoogleTokens() {
    try {
      const data = await request('/api/v1/auth-manager/tokens?provider=google');
      state.googleTokens = (data && data.tokens) || [];
      state.googleTokensError = '';
    } catch (e) {
      state.googleTokens = false;
      state.googleTokensError = (e && e.message) || String(e);
    }
  }

  function renderDriveAccounts() {
    const on = !!$('cx-v-drive').checked;
    $('cx-v-drive-wrap').classList.toggle('hidden', !on);
    const sel = $('cx-v-drive-token');
    const hint = $('cx-v-drive-hint');
    const tokens = state.googleTokens;
    hint.classList.remove('warn');
    if (tokens === null) {
      sel.innerHTML = `<option value="">${esc(t('codex.cv_drive_loading'))}</option>`;
      sel.disabled = true;
      hint.textContent = '';
      return;
    }
    // Tài khoản dính tới Drive, kể cả chỉ đọc: hiện nhưng khoá, để người dùng hiểu vì sao không chọn được.
    const list = (tokens || []).filter(x => x.status !== 'revoked' && (x.scopes || []).join(' ').includes('drive'));
    const agent = videoAgentGranted();
    const pick = pickDriveToken(list, agent.creds, sel.value || '', lsGet(CV_DRIVE_TOKEN_KEY));
    if (!pick) {
      sel.innerHTML = '<option value="">—</option>';
      sel.disabled = true;
      hint.textContent = tokens === false
        ? t('codex.cv_drive_load_failed', { msg: state.googleTokensError || '' })
        : t('codex.cv_drive_none');
      hint.classList.add('warn');
      return;
    }
    const label = x => (x.authorized_email || x.credential_name || x.token_id)
      + (x.authorized_email && x.credential_name ? ' · ' + x.credential_name : '');
    const opt = x => {
      const ro = !driveCanWrite(x.scopes);
      return `<option value="${esc(x.token_id)}"${ro ? ' disabled' : ''}>${esc(label(x))}`
        + `${ro ? ' — ' + esc(t('codex.cv_drive_readonly')) : ''}</option>`;
    };
    const mine = list.filter(x => agent.creds.includes(x.credential_id));
    const others = list.filter(x => !agent.creds.includes(x.credential_id));
    sel.innerHTML = mine.length
      ? `<optgroup label="${esc(t('codex.cv_drive_group_granted', { agent: agent.name }))}">${mine.map(opt).join('')}</optgroup>`
        + (others.length ? `<optgroup label="${esc(t('codex.cv_drive_group_other'))}">${others.map(opt).join('')}</optgroup>` : '')
      : others.map(opt).join('');
    sel.disabled = false;
    sel.value = pick;
    renderDriveHint();
  }

  function renderDriveHint() {
    const hint = $('cx-v-drive-hint');
    const sel = $('cx-v-drive-token');
    const tok = (state.googleTokens || []).find(x => x.token_id === sel.value);
    hint.classList.remove('warn');
    if (!tok) { hint.textContent = ''; return; }
    const agent = videoAgentGranted();
    hint.textContent = t(agent.creds.includes(tok.credential_id)
      ? 'codex.cv_drive_granted_hint' : 'codex.cv_drive_not_granted_hint', { agent: agent.name });
  }

  function onVideoDrive() { renderDriveAccounts(); }
  function onVideoDriveToken() { renderDriveHint(); }
  function onVideoDriveShare() { lsSet(CV_DRIVE_SHARE_KEY, $('cx-v-drive-share').value === 'private' ? 'private' : 'public'); }

  // ── Độ dài video: theo bài dán (mặc định) / theo mẫu / tự chọn phút ──
  const CV_LENGTH_KEY = 'codex.cvLength';
  const CV_MINUTES_KEY = 'codex.cvMinutes';
  const CV_SCRIPT_KEY = 'codex.cvScript';     // rewrite | verbatim | reference
  const CV_KEEP_THEME_KEY = 'codex.cvKeepTheme';   // '1' | '0' — «Tham khảo cấu trúc» giữ chủ đề nguồn
  const CV_INSTR_KEY = 'codex.cvInstructions';     // lời dặn thêm cho AI (nhớ lần gần nhất)
  const CV_INSTR_MAX = 2000;
  // «Lưu lên Google Drive»: bật/tắt + tài khoản nhận file (token_id của Auth Manager) — nhớ lần gần nhất.
  const CV_DRIVE_KEY = 'codex.cvDrive';              // '1' | '0'
  const CV_DRIVE_TOKEN_KEY = 'codex.cvDriveToken';
  const CV_DRIVE_SHARE_KEY = 'codex.cvDriveShare';   // 'public' (ai có link xem+tải) | 'private'
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

  // PHẢI khớp tubecli/core/youtube_transcript.py (youtube_ids / link_only, LINK_EXTRA_WORDS = 12).
  const CV_YT_ID_RE = /(?:youtube\.com\/(?:watch\?(?:[^\s#]*?&)?v=|shorts\/|live\/|embed\/|v\/)|youtu\.be\/)([A-Za-z0-9_-]{11})/g;
  const CV_YT_EXTRA_WORDS = 12;

  function cvYoutubeIds(txt) {
    const out = [];
    for (const m of String(txt || '').matchAll(CV_YT_ID_RE)) if (!out.includes(m[1])) out.push(m[1]);
    return out;
  }

  /** Id video khi nội dung CHỈ là link YouTube (vài chữ ghi chú kèm theo được); [] cho bài dán tay. */
  function cvLinkOnly(txt) {
    const ids = cvYoutubeIds(txt);
    if (!ids.length) return [];
    const words = String(txt || '').replace(/https?:\/\/\S+/g, ' ').split(/\s+/)
      .filter(w => /[\p{L}\p{N}]/u.test(w)).length;
    return words <= CV_YT_EXTRA_WORDS ? ids : [];
  }

  /** Danh sách link khi người dùng dán MỖI DÒNG MỘT LINK → mỗi dòng một video (user 16/9/2026).
   *  Trả [] khi không phải danh sách link thuần: bài dán tay, chỉ một link, hay có dòng không chứa link
   *  (ví dụ dòng ghi chú) — những lượt đó vẫn gộp thành MỘT video như trước. Một dòng nhiều link thì cả dòng
   *  là một video: người dùng xuống hàng ở đâu, ranh giới video ở đó. */
  function cvLinkLines(txt) {
    const lines = String(txt || '').split(/\r?\n/).map(s => s.trim()).filter(Boolean);
    if (lines.length < 2 || !cvLinkOnly(txt).length) return [];
    for (const line of lines) if (!cvYoutubeIds(line).length) return [];
    return lines;
  }

  /** Ô "Độ dài video". Mặc định THEO BÀI DÁN: trước đây độ dài lấy từ ô Video
   *  Length của mẫu, nên dán dài hay ngắn cũng ra ~14 shot (11/9/2026). */
  function renderVideoLength() {
    const sel = $('cx-v-length');
    if (!sel) return;
    const txt = $('cx-v-content').value || '';
    const linkOnly = cvLinkOnly(txt).length > 0;
    const probe = linkOnly ? state.ytProbe : null;
    // Link YouTube: độ dài nguồn là số chữ PHỤ ĐỀ đã thăm dò, không phải số chữ của đường link.
    const have = linkOnly ? ((probe && probe.status === 'ok') ? probe.words : 0) : cvWords(txt);
    // Nguyên văn: độ dài là của chính bài dán → ô "Độ dài video" không có tác dụng, ẩn đi.
    const verbatim = renderVideoScript(have, linkOnly);
    const lenWrap = $('cx-v-length-wrap');
    if (lenWrap) lenWrap.classList.toggle('hidden', verbatim);
    const est = $('cx-v-estimate');
    if (verbatim) {
      $('cx-v-minutes-wrap').classList.add('hidden');
      if (est) est.textContent = '';
      return;
    }
    const name = $('cx-v-preset').value;
    const p = (name && state.presets) ? state.presets[name] : null;
    const lenKey = (p && p.wizVideoLength) || '';
    const tplWords = CV_LEN_WORDS[lenKey] || CV_DEFAULT_WORDS;
    const tplLabel = lenKey ? (CV_LEN_KEYS[lenKey] ? t(CV_LEN_KEYS[lenKey]) : lenKey) : t('codex.cv_len_default');
    const fit = Math.max(CV_WORDS_MIN, Math.min(CV_WORDS_MAX, have));
    const want = sel.value || lsGet(CV_LENGTH_KEY) || 'content';
    sel.innerHTML =
      `<option value="content">${esc(have ? t(linkOnly ? 'codex.cv_len_mode_source' : 'codex.cv_len_mode_content', { min: fmtMin(fit) })
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
    // Thời lượng đọc DỰ ĐOÁN của kịch bản sẽ viết — pipeline đưa đúng con số này vào prompt (±10 %).
    const target = mode === 'content' ? fit
      : (mode === 'template' ? tplWords : clampMinutes($('cx-v-minutes').value) * CV_WPM);
    if (est) {
      est.textContent = (mode !== 'content' || have)
        ? t('codex.cv_len_estimate', { words: target.toLocaleString(), min: fmtMin(target) }) : '';
    }
  }

  /** Ô "Kịch bản": AI viết lại (mặc định) / đọc NGUYÊN VĂN bài dán. Tập 337 (13/9/2026)
   *  mất 13 % câu và thêm 16 % câu tự bịa dù đã dặn giữ đủ — ai dán bài hoàn chỉnh thì
   *  muốn video đọc đúng bài ấy. Trả true khi đang chọn nguyên văn. */
  function renderVideoScript(have, linkOnly) {
    const sel = $('cx-v-script');
    if (!sel) return false;
    const want = sel.value || lsGet(CV_SCRIPT_KEY) || 'rewrite';
    sel.innerHTML =
      `<option value="rewrite">${esc(t('codex.cv_script_rewrite'))}</option>` +
      `<option value="verbatim">${esc(t('codex.cv_script_verbatim'))}</option>` +
      `<option value="reference">${esc(t('codex.cv_script_reference'))}</option>`;
    sel.value = ['rewrite', 'verbatim', 'reference'].includes(want) ? want : 'rewrite';
    const mode = sel.value;
    const hint = $('cx-v-script-hint');
    if (hint) {
      // Viết lại một video YouTube = xào lại câu chuyện/ẩn dụ của người khác (thử 15/9/2026) → nhắc chọn tham khảo.
      hint.textContent = mode === 'verbatim' ? t('codex.cv_script_hint_verbatim', { min: fmtMin(have || 0) })
        : mode === 'reference' ? t('codex.cv_script_hint_reference')
          : (linkOnly ? t('codex.cv_script_hint_rewrite_link') : '');
      if (hint.classList) hint.classList.toggle('warn', mode === 'rewrite' && !!linkOnly);
    }
    const keep = $('cx-v-keeptheme-wrap');
    if (keep) keep.classList.toggle('hidden', mode !== 'reference');
    // Nguyên văn không có lượt viết để dặn → ẩn ô lời dặn.
    const instr = $('cx-v-instructions-wrap');
    if (instr) instr.classList.toggle('hidden', mode === 'verbatim');
    return mode === 'verbatim';
  }

  function onVideoScript() {
    lsSet(CV_SCRIPT_KEY, $('cx-v-script').value || 'rewrite');
    renderVideoLength();
  }

  function onVideoLength() {
    lsSet(CV_LENGTH_KEY, $('cx-v-length').value || 'content');
    lsSet(CV_MINUTES_KEY, String(clampMinutes($('cx-v-minutes').value)));
    renderVideoLength();
  }

  let _ytProbeTimer = null;

  function onVideoContent() {
    const txt = ($('cx-v-content').value || '').trim();
    const ids = cvLinkOnly(txt);
    if (ids.length) scheduleYoutubeProbe(ids);
    else { state.ytProbe = null; clearTimeout(_ytProbeTimer); }
    renderVideoCount();
    renderVideoLength();
    renderVideoSplit();
  }

  /** Ô tick «Mỗi link một video» chỉ hiện khi dán ≥2 dòng link, kèm số video sẽ tạo. */
  function renderVideoSplit() {
    const wrap = $('cx-v-split-wrap');
    if (!wrap) return;
    const n = cvLinkLines($('cx-v-content').value || '').length;
    wrap.classList.toggle('hidden', n < 2);
    if (n >= 2) $('cx-v-split-hint').textContent = t('codex.cv_split_hint', { n: n });
  }

  function onVideoSplit() { renderVideoCount(); }

  /** Dòng dưới ô nội dung: số chữ của bài dán — hay, khi chỉ có link YouTube, tên video và số chữ phụ đề
   *  đã thăm dò (15/9/2026: link từng bị đếm "1 words · 43 characters" rồi thành kịch bản 120 chữ bịa). */
  function renderVideoCount() {
    const txt = ($('cx-v-content').value || '').trim();
    const box = $('cx-v-count');
    const p = cvLinkOnly(txt).length ? state.ytProbe : null;
    if (p) {
      box.textContent = p.status === 'loading' ? t('codex.cv_yt_loading')
        : p.status === 'ok'
          ? t('codex.cv_yt_ok', { title: p.title || '?', words: (p.words || 0).toLocaleString(), min: fmtMin(p.words || 0) })
          : t('codex.cv_yt_error', { msg: p.message || '?' });
      box.classList.toggle('warn', p.status === 'error');
      return;
    }
    const chars = txt.length;
    const words = cvWords(txt);
    box.textContent = chars
      ? t('codex.cv_count', { words: words.toLocaleString(), chars: chars.toLocaleString() })
      : '';
    box.classList.toggle('warn', chars > CV_MAX_CHARS);
  }

  /** Thăm dò link YouTube (tên video, số chữ phụ đề) khi người dùng ngừng gõ 0,5 giây. Máy chủ nhớ kết
   *  quả 1 giờ nên lượt chạy ngay sau đó không tải lại. Máy chủ cũ không có route → hiện lỗi, không chặn gửi. */
  function scheduleYoutubeProbe(ids) {
    const key = ids.join(',');
    if (state.ytProbe && state.ytProbe.key === key) return;
    clearTimeout(_ytProbeTimer);
    state.ytProbe = { key: key, status: 'loading' };
    _ytProbeTimer = setTimeout(async () => {
      let next;
      try {
        const data = await request('/api/v1/content-video/youtube-probe?url=' +
          encodeURIComponent('https://youtu.be/' + ids[0]));
        next = data && data.ok
          ? { key: key, status: 'ok', words: data.words || 0, title: data.title || '', channel: data.channel || '' }
          : { key: key, status: 'error', message: (data && data.message) || '?' };
      } catch (e) {
        next = { key: key, status: 'error', message: (e && e.message) || String(e) };
      }
      if (!state.ytProbe || state.ytProbe.key !== key) return;   // nội dung đã đổi trong lúc chờ
      state.ytProbe = next;
      renderVideoCount();
      renderVideoLength();
    }, 500);
  }

  function onVideoKeepTheme() {
    lsSet(CV_KEEP_THEME_KEY, $('cx-v-keeptheme').checked ? '1' : '0');
  }

  function onVideoInstructions() {
    lsSet(CV_INSTR_KEY, ($('cx-v-instructions').value || '').slice(0, CV_INSTR_MAX));
  }

  /** Nút "Đưa vào hàng đợi": như "Tạo video", nhưng task chờ tới lượt trong hàng đợi. */
  function queueVideo() { return submitVideo(true); }

  /** Task đang giữ làn `lane` (queued hoặc running) — khớp LANE_BUSY của codex/manager.py. */
  function laneBusyTask(lane) {
    return (state.tasks || []).find(x => (x.lane || '') === lane && (x.status === 'running' || x.status === 'queued'));
  }

  /** Hỏi: đưa vào hàng đợi hay chạy song song. Trả 'queue' | 'parallel' | null (huỷ / đóng hộp). */
  function askLaneChoice(task) {
    return new Promise((resolve) => {
      state.laneChoice = resolve;
      $('cx-busy-title').textContent = t('codex.modal_busy_title', { seq: task.seq || '?' });
      $('cx-busy-hint').textContent = t(task.status === 'running' ? 'codex.modal_busy_hint_running'
                                                                  : 'codex.modal_busy_hint_queued',
                                        { seq: task.seq || '?' });
      $('cx-modal-busy').classList.remove('hidden');
    });
  }

  function laneChoice(choice) {
    const resolve = state.laneChoice;
    state.laneChoice = null;
    $('cx-modal-busy').classList.add('hidden');
    if (resolve) resolve(choice || null);
  }

  /** queue=true: vào hàng đợi — Codex tự chạy khi không còn video nào đang làm.
      Bỏ trống (nút "Tạo video"): chạy liền, chen trước hàng đợi. */
  async function submitVideo(queue) {
    let hold = queue === true;
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
    const drive = !!$('cx-v-drive').checked;
    const driveToken = drive ? ($('cx-v-drive-token').value || '') : '';
    if (drive && !driveToken) {
      toast(t('codex.toast_video_drive_account_required'), 'error');
      $('cx-v-drive-token').focus();
      return;
    }
    // Mỗi dòng một link → mỗi link một video. Cả loạt vào HÀNG ĐỢI: chạy lần lượt, không dựng song song.
    const links = (($('cx-v-split') || {}).checked === false) ? [] : cvLinkLines(content);
    const batch = links.length >= 2 ? links : [content];
    if (batch.length > 1) hold = true;
    // Bấm "Tạo video" khi làn video đang có task: hỏi trước. Hai lượt dựng song song chia nhau CPU/RAM/ffmpeg
    // và trên máy nhỏ thì cả hai chậm đi hoặc hết RAM (user 16/9/2026). Loạt nhiều link đã xếp hàng nên khỏi hỏi.
    if (!hold) {
      const busy = laneBusyTask('video');
      if (busy) {
        const choice = await askLaneChoice(busy);
        if (!choice) return;
        hold = choice === 'queue';
      }
    }
    const review = !!$('cx-v-review').checked;
    rememberNewTaskForm();
    const title = ($('cx-v-title').value || '').trim();
    const options = { preset: preset };
    if (title) options.title = title;
    const lengthMode = $('cx-v-length').value || 'content';
    options.length_mode = lengthMode;
    if (lengthMode === 'minutes') options.target_words = clampMinutes($('cx-v-minutes').value) * CV_WPM;
    const scriptMode = ($('cx-v-script') && $('cx-v-script').value) || 'rewrite';
    options.script_mode = scriptMode;
    if (scriptMode === 'reference') options.keep_theme = !!$('cx-v-keeptheme').checked;
    // Lời dặn đi RIÊNG (options.instructions): gõ vào ô nội dung thì pipeline coi là dữ liệu ngoài.
    const instructions = ($('cx-v-instructions').value || '').trim().slice(0, CV_INSTR_MAX);
    if (instructions && scriptMode !== 'verbatim') options.instructions = instructions;
    if (scriptMode === 'verbatim') {
      // Nguyên văn: độ dài là của chính bài dán; ô "Độ dài video" đang ẩn, không gửi.
      options.length_mode = 'content';
      delete options.target_words;
    }
    // Lưu lên Google Drive khi xong: token_id cụ thể — một credential giữ được nhiều tài khoản Google.
    if (drive) {
      options.drive = true;
      options.drive_token_id = driveToken;
      // Quyền của thư mục: mặc định ai có link xem + tải được (file nằm trên Drive của tài khoản đã cấp quyền).
      options.drive_public = (($('cx-v-drive-share') || {}).value || 'public') !== 'private';
    }

    const btns = [$('cx-create-btn'), $('cx-queue-btn')];
    btns.forEach(b => { b.disabled = true; });
    let made = 0;
    try {
      let data = null;
      for (let i = 0; i < batch.length; i++) {
        // Tiêu đề đã gõ: link đầu giữ nguyên, các link sau thêm số — khỏi trùng tên thư mục Drive và thẻ Codex.
        const opts = Object.assign({}, options);
        if (title && batch.length > 1) opts.title = i === 0 ? title : `${title} (${i + 1})`;
        data = await request('/api/v1/content-video/run', {
          method: 'POST',
          body: JSON.stringify({
            agent_id: agentId, content: batch[i], review: review,
            options: opts, created_by: 'user', queue: hold,
          }),
        });
        if (!data || data.status !== 'queued') {
          throw new Error((data && (data.report || data.detail)) || 'not queued');
        }
        made++;
      }
      const task = data.task || {};
      state.createdTask = task;
      const seq = task.seq || '?';
      // Nói theo trạng thái THẬT của task: máy chủ bản cũ không biết `queue` và cho
      // chạy liền — khi đó đừng báo "đã vào hàng đợi".
      if (made > 1) {
        toast(t('codex.toast_video_many', { n: made }), 'success');
        $('cx-created-title').textContent = t('codex.created_many_title', { n: made });
        $('cx-created-desc').textContent = t(review ? 'codex.created_many_desc_review'
                                                    : 'codex.created_many_desc_auto');
      } else if (task.status === 'backlog') {
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
      // Loạt nhiều link đứt giữa đường: nói rõ đã tạo được mấy cái, kẻo bấm lại là có task trùng.
      toast(made ? t('codex.toast_video_many_partial', { n: made, error: e.message })
                 : t('codex.toast_action_failed', { error: e.message }), 'error');
      if (made) {
        $('cx-created-title').textContent = t('codex.created_many_title', { n: made });
        $('cx-created-desc').textContent = t('codex.toast_video_many_partial', { n: made, error: e.message });
        $('cx-plan-btn').classList.add('hidden');
        $('cx-new-step-form').classList.add('hidden');
        $('cx-new-step-done').classList.remove('hidden');
        await refresh(false);
      }
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
    // Đóng hộp «đang có video chạy» bằng nút X hay bấm ra ngoài = huỷ: phải trả lời cho submitVideo đang chờ,
    // kẻo nó treo mãi và người dùng bấm Tạo video không thấy gì xảy ra.
    if (id === 'cx-modal-busy' && state.laneChoice) {
      const resolve = state.laneChoice;
      state.laneChoice = null;
      resolve(null);
    }
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
      patchNow();
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
    init, refresh, toggle, collapse, togglePlan, setFilter, onSearch, setAuto, setAutoApprove,
    approve, reject, cancel, retry, runNow, accept, requestChanges,
    confirmNote, confirmDelete, doDelete, copyResult, planTask,
    openNewTask, submitNewTask, queueVideo, setNewKind, onVideoPreset, onVideoAgent, onVideoContent, onVideoLength, onVideoScript, onVideoKeepTheme, onVideoInstructions, planFromModal, closeModal, onBackdrop,
    onVideoDrive, onVideoDriveToken, onVideoDriveShare, laneChoice, onVideoSplit, openDriveSync, startDriveSync, syncThenDelete,
  };
})();
