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
    'pending_approval', 'queued', 'running', 'review',
    'done', 'failed', 'rejected', 'cancelled',
  ];
  const ACTIVE_STATES = new Set(['pending_approval', 'queued', 'running', 'review']);

  const STATUS_ICON = {
    pending_approval: 'pending_actions',
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

  function relTime(ts) {
    const d = parseTs(ts);
    if (!d) return '';
    const sec = Math.max(0, Math.floor((Date.now() - d.getTime()) / 1000));
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
  async function api(path, opts) {
    const options = Object.assign({ headers: { 'Content-Type': 'application/json' } }, opts || {});
    const resp = await fetch(API + path, options);
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
      const list = (results[1].value && results[1].value.tasks) || [];
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
    const canPlan = ['pending_approval', 'queued', 'rejected', 'failed'].indexOf(task.status) >= 0;
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
            return `<div class="cx-step ${esc(st)}">
                <span class="cx-step-dot"></span>
                <div class="cx-step-head">
                  <span class="cx-step-label">${esc(s.label || s.name || '')}</span>
                  <span class="cx-step-status">${esc(stepLabel(st))}</span>
                  ${d ? `<span class="cx-step-time">${esc(d)}</span>` : ''}
                </div>
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
          <pre class="cx-pre">${esc(task.result)}</pre>
        </div>`);
    }

    // Error
    if (task.error) {
      parts.push(`<div class="cx-section">
          <div class="cx-section-title">${icon('report')}${esc(t('codex.section_error'))}</div>
          <pre class="cx-pre error">${esc(task.error)}</pre>
        </div>`);
    }

    // Event log
    parts.push(`<div class="cx-section">
        <div class="cx-section-title">${icon('history')}${esc(t('codex.section_events'))}</div>
        <div class="cx-events" id="cx-ev-${id}">${eventsHtml(task.id)}</div>
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
    const btn = $('cx-create-btn');
    btn.disabled = false;
    $('cx-modal-new').classList.remove('hidden');

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
    setTimeout(() => $('cx-f-goal').focus(), 50);
  }

  async function submitNewTask() {
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
    init, refresh, toggle, setFilter, onSearch, setAuto,
    approve, reject, cancel, retry, accept, requestChanges,
    confirmNote, copyResult, planTask,
    openNewTask, submitNewTask, planFromModal, closeModal, onBackdrop,
  };
})();
