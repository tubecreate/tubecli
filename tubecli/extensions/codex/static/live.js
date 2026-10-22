/**
 * ═══════════════════════════════════════════════════════════════════
 *  «Xem live» CHUNG của bảng việc — /taskboard/live, mở tab mới từ nút ở đầu bảng (user 11/10/2026: «taskboard vẫn
 *  như cũ, chỉ thêm một chế độ xem live khi muốn mở lớn», «live view là trang chung task board luôn chứ không phải
 *  từng bài», «link kiểu …/taskboard/live»).
 *  Cột trái: MỌI task đang chạy, mỗi task một khối theo mockup A «Dòng việc» — bước mới nhất trên cùng, bước đang
 *  chạy mở rộng (ba số to + lưới ảnh / clip / giọng từng cảnh, nhiều ô đang vẽ cùng lúc), bước xong một dòng (bước
 *  «Vẽ ảnh» có dải 5 ảnh), «Tiếp theo» mờ ở cuối. Cột phải: hàng đợi, chỗ ngồi Muse, chỗ dành cho trình duyệt đang
 *  chạy (giai đoạn sau), vừa xong / vừa lỗi kèm lý do.
 *  API: /api/v1/codex/tasks?view=board (ETag), /api/v1/codex/tasks/{id}, /api/v1/studio/episodes/{ep}/live (ETag)
 * ═══════════════════════════════════════════════════════════════════
 */

const LIVE = (() => {
  'use strict';

  const API = '/api/v1/codex';
  // Nhịp hỏi THÍCH NGHI (user 11/10/2026: «refresh liên tục thì có sao không? … ban đầu 2s nhưng càng lâu thì càng
  // tăng»): 2 s; mỗi lượt KHÔNG có gì đổi thì nhân 1,5 (2 → 3 → 4,5 → … → 30 s); có đổi, người dùng chạm trang, hay
  // tab hiện lại → về 2 s. Tab ẩn thì không hỏi. Trang chung không bao giờ thôi hẳn (task mới có thể vào bất cứ lúc
  // nào) — chỉ giãn tới 30 s.
  const BASE_MS = 2000;
  const MAX_MS = 30000;
  const GROW = 1.5;
  const MUSE_MS = 15000;
  const RECENT_MAX = 6;
  const RECENT_HOURS = 12;
  const LIVE_STATES = new Set(['queued', 'running']);
  const FINAL_STATES = new Set(['review', 'done', 'failed', 'rejected', 'cancelled']);
  const STATES = ['pending_approval', 'backlog', 'queued', 'running', 'review', 'done', 'failed', 'rejected', 'cancelled'];
  const STATUS_ICON = {
    pending_approval: 'pending_actions', backlog: 'stacks', queued: 'schedule', running: 'progress_activity',
    review: 'rate_review', done: 'task_alt', failed: 'error', rejected: 'block', cancelled: 'do_not_disturb_on',
  };
  // Bước có lưới từng cảnh: «Vẽ ảnh» (ảnh rồi clip Muse) và «Giọng đọc».
  const GRID_STEPS = new Set(['images', 'tts']);
  const BADGE = {
    image: ['image', 'codex.live_image'], drawing: ['progress_activity', 'codex.live_drawing'],
    clip: ['play_arrow', 'codex.live_clip'], board: ['draw', 'codex.live_board'], filming: ['videocam', 'codex.live_filming'],
    still: ['photo', 'codex.live_still'], queued: ['schedule', 'codex.live_queued'], waiting: ['', 'codex.live_waiting'],
    failed: ['error', 'codex.live_failed'], voiced: ['record_voice_over', 'codex.live_voiced'],
    unvoiced: ['', 'codex.live_unvoiced'],
  };
  const BUSY = new Set(['drawing', 'board', 'filming']);
  const LEGEND_ORDER = ['clip', 'filming', 'board', 'queued', 'still', 'drawing', 'image', 'failed', 'waiting', 'voiced', 'unvoiced'];

  const state = {
    clock: null,           // {iso, at}: «đã chạy …» đo bằng đồng hồ MÁY CHỦ (mốc trong task do máy chủ ghi)
    lists: {},             // nhóm → {etag, tasks}: working (đang chạy) · backlog (hàng đợi) · recent (mới đổi)
    details: {},           // taskId → {text, task}: task đang chạy, có steps
    finals: {},            // taskId → {updated_at, task}: task vừa xong — kết quả / lỗi, hỏi MỘT lần mỗi lần đổi
    lives: {},             // episodeId → {etag, text, data, missing}
    muse: null,
    museText: '',
    museAt: 0,
    museBusy: false,
    streak: 0,
    nextAt: 0,
    error: '',
    showGrid: {},          // taskId → bước «Vẽ ảnh» đã xong mà người dùng vẫn muốn xem cả lưới
    busy: false,
    loaded: false,
    updatedAt: 0,
  };
  let timer = null;

  // ── Tiny helpers (cùng kiểu codex.js) ─────────────────────────
  function t(key, vars) { return (typeof T === 'function') ? T(key, vars) : key; }

  function esc(v) {
    if (v === null || v === undefined) return '';
    return String(v)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function icon(name, cls) {
    return '<span class="material-symbols-outlined' + (cls ? ' ' + cls : '') + '" aria-hidden="true">' + esc(name) + '</span>';
  }

  /** Python isoformat() có micro giây — cắt còn ms rồi parse. */
  function parseTs(s) {
    if (!s) return null;
    const d = new Date(String(s).replace(/(\.\d{3})\d+/, '$1'));
    return isNaN(d.getTime()) ? null : d;
  }

  function serverNow() {
    const c = state.clock;
    const base = c && parseTs(c.iso);
    return base ? base.getTime() + (Date.now() - c.at) : Date.now();
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
    return a && b ? fmtSecs((b.getTime() - a.getTime()) / 1000) : '';
  }

  function clockOf(ts) {
    const d = parseTs(ts);
    if (!d) return '';
    const p = n => String(n).padStart(2, '0');
    return p(d.getHours()) + ':' + p(d.getMinutes());
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

  /** Nhịp hỏi tiếp theo: 2 s × 1,5^streak, trần 30 s. Hàm thuần — test cắt theo tên. */
  function liveDelay(streak) {
    return Math.min(MAX_MS, Math.round(BASE_MS * Math.pow(GROW, Math.max(0, Number(streak) || 0))));
  }

  /** Dòng việc: bước đang chạy trước, rồi bước đã xong mới nhất → cũ; `next` = bước chưa tới (giữ thứ tự chạy). */
  function liveOrder(steps) {
    const list = Array.isArray(steps) ? steps : [];
    const running = list.filter(s => s.status === 'running');
    const finished = list.map((s, i) => ({ s, i })).filter(x => x.s.status && x.s.status !== 'running' && x.s.status !== 'pending');
    finished.sort((a, b) => {
      const ta = parseTs(a.s.ended_at || a.s.started_at), tb = parseTs(b.s.ended_at || b.s.started_at);
      if (ta && tb && ta.getTime() !== tb.getTime()) return tb.getTime() - ta.getTime();
      return b.i - a.i;
    });
    const next = list.filter(s => !s.status || s.status === 'pending');
    return { main: running.concat(finished.map(x => x.s)), next };
  }

  /** Trạng thái một ô: lưới ảnh dùng state của Studio; lưới giọng chỉ có/không có giọng. */
  function cellState(c, voice) {
    return voice ? (c.tts ? 'voiced' : 'unvoiced') : (c.state || 'waiting');
  }

  /** Ba số to của bước đang chạy. Bước «Vẽ ảnh»: đang quay clip (có kế hoạch clip) thì clip xong / kế hoạch, không thì
   *  ảnh xong / tổng; số ô đang chạy cùng lúc; còn khoảng bao lâu. Hàm thuần — test cắt theo tên. */
  function runStats(step, live, elapsedSec) {
    const shots = (live && Array.isArray(live.shots)) ? live.shots : [];
    const voice = step && step.name === 'tts';
    let done = 0, total = 0, busy = 0, kind = 'pct';
    if (shots.length && step && GRID_STEPS.has(step.name)) {
      total = shots.length;
      if (voice) {
        kind = 'voice';
        done = shots.filter(c => c.tts).length;
      } else if ((live.clip_plan || 0) > 0 && shots.some(c => c.image) && shots.every(c => c.image || c.state === 'failed')) {
        kind = 'clips';
        total = live.clip_plan;
        done = shots.filter(c => c.state === 'clip').length;
        busy = shots.filter(c => c.state === 'board' || c.state === 'filming').length;
      } else {
        kind = 'images';
        done = shots.filter(c => c.image).length;
        busy = shots.filter(c => c.state === 'drawing').length;
      }
    }
    let frac = total > 0 ? Math.min(1, done / total) : Math.max(0, Math.min(1, (Number(step && step.progress) || 0) / 100));
    if (kind === 'pct' && !(Number(step && step.progress) > 0)) frac = null;
    let eta = null;
    if (frac !== null && frac >= 0.05 && frac < 1 && elapsedSec > 5) eta = Math.round(elapsedSec * (1 - frac) / frac);
    return { kind, done, total, busy, frac, eta };
  }

  /** Task «vừa xong» đáng hiện: trạng thái cuối, đổi trong RECENT_HOURS giờ, mới nhất trước, tối đa RECENT_MAX. */
  function recentOf(tasks, nowMs) {
    const list = Array.isArray(tasks) ? tasks : [];
    return list
      .filter(x => FINAL_STATES.has(x.status))
      .filter((x) => { const d = parseTs(x.updated_at); return d && nowMs - d.getTime() <= RECENT_HOURS * 3600 * 1000; })
      .sort((a, b) => (parseTs(b.updated_at) || 0) - (parseTs(a.updated_at) || 0))
      .slice(0, RECENT_MAX);
  }

  /** Link xem video trong kết quả: ưu tiên link chia sẻ /s/<mã>, rồi link «Watch». */
  function watchLink(result) {
    const text = String(result || '');
    const share = /https?:\/\/[^\s)`'"<>]+\/s\/[A-Za-z0-9_-]+/.exec(text);
    if (share) return share[0];
    const watch = /https?:\/\/[^\s)`'"<>]+\.mp4/.exec(text);
    return watch ? watch[0].replace(/^https?:\/\/(?:127\.0\.0\.1|localhost)(?::\d+)?/, '') : '';
  }

  // ── Vá DOM theo khoá ───────────────────────────────────────────
  // Mỗi mục {k, h, kids?}: h không đổi thì giữ nguyên phần tử (ảnh không nạp lại, không chớp); đổi thì thay đúng phần tử
  // đó. `kids` là danh sách con vá vào phần tử [data-kids] bên trong — lưới 13–100 ô đổi một ô thì chỉ ô đó được vẽ lại.
  function patchKeyed(box, items) {
    if (!box) return;
    const old = new Map();
    Array.from(box.children).forEach(el => old.set(el.getAttribute('data-k'), el));
    let prev = null;
    items.forEach((it) => {
      let el = old.get(it.k);
      if (el) old.delete(it.k);
      if (!el || el.__h !== it.h) {
        const tpl = document.createElement('template');
        tpl.innerHTML = it.h.trim();
        const nu = tpl.content.firstElementChild;
        nu.setAttribute('data-k', it.k);
        nu.__h = it.h;
        if (el) el.replaceWith(nu);
        el = nu;
      }
      const want = prev ? prev.nextElementSibling : box.firstElementChild;
      if (want !== el) box.insertBefore(el, want);
      if (it.kids) patchKeyed(el.matches('[data-kids]') ? el : el.querySelector('[data-kids]'), it.kids);
      prev = el;
    });
    old.forEach(el => el.remove());
  }

  // ── Vẽ ─────────────────────────────────────────────────────────
  function statusLabel(st) { return STATES.indexOf(st) >= 0 ? t('codex.status_' + st) : String(st || ''); }

  function themeQs() {
    const th = new URLSearchParams(location.search).get('theme');
    return th ? '?theme=' + encodeURIComponent(th) : '';
  }

  function runningTasks() {
    return ((state.lists.working && state.lists.working.tasks) || []).filter(x => x.status === 'running');
  }

  function queueTasks() {
    const w = ((state.lists.working && state.lists.working.tasks) || []).filter(x => x.status === 'queued');
    return w.concat((state.lists.backlog && state.lists.backlog.tasks) || []);
  }

  function liveOf(task) {
    const ep = Number((task && task.meta && task.meta.episode_id) || 0);
    const L = ep ? state.lives[ep] : null;
    return (L && L.data) || null;
  }

  function headHtml() {
    const run = runningTasks().length;
    const q = queueTasks().length;
    const mu = state.muse;
    const seats = mu && Array.isArray(mu.pool) && mu.pool.length
      ? `<span class="lv-chip">${icon('event_seat')}${esc(t('codex.live_seats_hint', { n: mu.pool.filter(p => p.busy).length, total: mu.pool.length }))}</span>` : '';
    return `<div class="lv-top">
        <a class="lv-back" href="/taskboard${esc(themeQs())}">${icon('arrow_back')}${esc(t('codex.live_back'))}</a>
        <span class="lv-spacer"></span>
        <span class="lv-badge ${run ? 'st-running' : ''}">${icon(run ? 'progress_activity' : 'pause_circle')}${esc(t('codex.live_running_n', { n: run }))}</span>
      </div>
      <h1 class="lv-title">${esc(t('codex.live_open'))}</h1>
      <div class="lv-chips">
        <span class="lv-chip">${icon('stacks')}${esc(t('codex.live_queue_n', { n: q }))}</span>
        ${seats}
      </div>`;
  }

  function taskHeadHtml(task) {
    const steps = Array.isArray(task.steps) ? task.steps : [];
    const ok = steps.filter(s => s.status === 'success' || s.status === 'skipped').length;
    const m = task.meta || {};
    const chips = [];
    if (task.assignee_name) chips.push(['smart_toy', task.assignee_name]);
    if (m.preset) chips.push(['style', m.preset]);
    if (m.language) chips.push(['translate', m.language]);
    if (Number(m.episode_id) > 0) chips.push(['movie', t('codex.live_episode', { n: m.episode_id })]);
    const segs = steps.map(s => {
      const c = s.status === 'success' ? 'ok' : s.status === 'running' ? 'run' : (s.status === 'error' || s.status === 'cancelled') ? 'err' : s.status === 'skipped' ? 'skip' : '';
      return `<span class="${c}" title="${esc(s.label || s.name || '')}"></span>`;
    }).join('');
    const since = task.started_at || task.created_at;
    return `<header class="lv-task-head">
        <div class="lv-top"><span class="lv-seq">#${esc(task.seq || '')}</span>
          <span class="lv-badge st-${esc(task.status)}">${icon(STATUS_ICON[task.status] || 'help')}${esc(statusLabel(task.status))}</span>
          <h2 class="lv-task-title">${esc(task.title || task.goal || '')}</h2></div>
        ${chips.length ? `<div class="lv-chips">${chips.map(c => `<span class="lv-chip">${icon(c[0])}${esc(c[1])}</span>`).join('')}</div>` : ''}
        ${steps.length ? `<div class="lv-strip"><div class="lv-segs">${segs}</div>
          <span class="lv-mono">${esc(t('codex.live_steps_done', { n: ok, total: steps.length }))} · ${esc(t('codex.live_ran'))} <span data-since="${esc(since)}"></span></span></div>` : ''}
      </header>`;
  }

  function badgeHtml(st, since) {
    const b = BADGE[st] || BADGE.waiting;
    return `<span class="cx-cell-badge">${b[0] ? icon(b[0]) : ''}<span>${esc(t(b[1]))}</span>`
      + (since ? `<span class="cx-cell-since">· <span data-since="${esc(since)}"></span></span>` : '') + '</span>';
  }

  /** «cx/gpt-image-2» → «gpt-image-2», «@cf/black-forest-labs/flux-1-schnell» → «flux-1-schnell». */
  function shortModel(m) {
    const s = String(m || '');
    return s.slice(s.lastIndexOf('/') + 1) || s;
  }

  /** Máy chủ: «local» = máy này; tên miền thì lấy phần đầu (tungho2-23.tubecreate.com → tungho2-23), IP giữ nguyên. */
  function serverName(s) {
    if (!s) return '';
    if (s === 'local') return t('codex.live_who_local');
    return /^[\d.:]+$/.test(s) ? s : s.split('.')[0];
  }

  /** Ô đang vẽ / quay (user 22/10/2026): model nào · ghế nào · máy nào — Studio ghi `who` vào dòng cảnh. */
  function whoHtml(w) {
    const model = w.model ? shortModel(w.model) : (w.provider === 'muse' ? 'Muse' : (w.provider || ''));
    const waitSeat = w.provider === 'muse' && !w.seat;
    const where = waitSeat ? t('codex.live_who_wait_seat') : [w.seat, serverName(w.server)].filter(Boolean).join(' · ');
    const tip = [
      model && `${t('codex.live_who_model')}: ${w.model || model}`,
      w.seat && `${t('codex.live_who_seat')}: ${w.seat}`,
      w.server && `${t('codex.live_who_server')}: ${w.server === 'local' ? t('codex.live_who_local') : w.server}`,
    ].filter(Boolean).join('\n');
    return `<span class="cx-cell-who" title="${esc(tip)}">
        <span class="cx-who-model"><span class="cx-cell-spin" aria-hidden="true"></span><b>${esc(model)}</b></span>
        ${where ? `<span class="cx-who-where">${esc(where)}</span>` : ''}
      </span>`;
  }

  function cellItem(c, voice) {
    const st = cellState(c, voice);
    const title = `${c.n}${c.title ? ' · ' + c.title : ''}`;
    const who = BUSY.has(st) && c.who && (c.who.model || c.who.provider || c.who.seat) ? c.who : null;
    return {
      k: 'c' + c.id,
      h: `<div class="lv-cellwrap" role="listitem">
          <div class="cx-cell st-${esc(st)}${c.thumb ? '' : ' no-img'}${c.sketch ? ' is-sketch' : ''}${who ? ' has-who' : ''}" title="${esc(title)}">
            ${c.thumb ? `<img loading="lazy" decoding="async" src="${esc(c.thumb)}" alt="">`
              : (BUSY.has(st) ? '' : `<span class="cx-cell-wait">${esc(String(c.n))}</span>`)}
            ${c.sketch ? `<span class="cx-cell-sketch">${esc(t('codex.live_sketch'))}</span>` : ''}
            <span class="cx-cell-n">${esc(String(c.n))}</span>
            ${who ? whoHtml(who) : (BUSY.has(st) ? '<span class="cx-cell-spin" aria-hidden="true"></span>' : '')}
            ${badgeHtml(st, who && who.since)}
          </div>
          ${c.title ? `<div class="lv-cap" title="${esc(c.title)}">${esc(c.title)}</div>` : ''}
        </div>`,
    };
  }

  function legendHtml(shots, voice) {
    const counts = {};
    shots.forEach(c => { const st = cellState(c, voice); counts[st] = (counts[st] || 0) + 1; });
    const keys = Object.keys(counts).sort((a, b) => LEGEND_ORDER.indexOf(a) - LEGEND_ORDER.indexOf(b));
    return `<div class="cx-live-legend">${keys.map(st => {
      const b = BADGE[st] || BADGE.waiting;
      return `<span class="st-${esc(st)}">${b[0] ? icon(b[0]) : ''}${esc(t(b[1]))} · ${counts[st]}</span>`;
    }).join('')}</div>`;
  }

  function gridItems(shots, voice, key) {
    return [
      { k: key + ':grid', h: `<div class="cx-live-grid" role="list" aria-label="${esc(t('codex.live_grid_aria'))}" data-kids></div>`,
        kids: shots.map(c => cellItem(c, voice)) },
      { k: key + ':legend', h: legendHtml(shots, voice) },
    ];
  }

  function railHtml(s) {
    const dur = s.status === 'running' ? '' : duration(s.started_at, s.ended_at);
    return `<div class="lv-rail"><span class="lv-time">${esc(clockOf(s.started_at) || '··:··')}</span>${dur ? `<span class="lv-dur">${esc(dur)}</span>` : ''}</div>
      <span class="lv-dot" aria-hidden="true"></span>`;
  }

  function statHtml(big, unit, label, hot) {
    return `<div class="lv-stat${hot ? ' hot' : ''}"><b>${big}</b>${unit ? `<span class="lv-unit">${esc(unit)}</span>` : ''}<small>${esc(label)}</small></div>`;
  }

  function etaHtml(eta) {
    return `<span data-eta="${eta === null ? '' : eta}">${esc(eta === null ? '—' : fmtSecs(eta))}</span>`;
  }

  /** Bước đang chạy: thẻ to — đầu, ba số, thanh %, lời nhắn của bước, lưới từng cảnh. */
  function runningItem(s, live) {
    const shots = (live && Array.isArray(live.shots)) ? live.shots : [];
    const start = parseTs(s.started_at);
    const elapsed = start ? Math.max(0, (serverNow() - start.getTime()) / 1000) : 0;
    const r = runStats(s, live, elapsed);
    const key = 'run:' + (s.name || '');
    const kids = [{
      k: key + ':head',
      h: `<div class="lv-run-head"><span class="lv-kicker">${esc(t('codex.live_now'))}</span>
          <span class="lv-run-label">${esc(s.label || s.name || '')}</span>
          <span class="lv-mono">${start ? `<span data-since="${esc(s.started_at)}"></span>` : ''}</span></div>`,
    }];
    const pct = r.frac === null ? '—' : String(Math.round(r.frac * 100));
    let stats;
    if (r.kind === 'clips') {
      stats = statHtml(r.done, '/' + r.total, t('codex.live_stat_clips'), true)
        + statHtml(r.busy, '', t('codex.live_stat_parallel')) + statHtml(etaHtml(r.eta), '', t('codex.live_stat_eta'));
    } else if (r.kind === 'images') {
      stats = statHtml(r.done, '/' + r.total, t('codex.live_stat_images'), true)
        + statHtml(r.busy, '', t('codex.live_stat_parallel')) + statHtml(etaHtml(r.eta), '', t('codex.live_stat_eta'));
    } else if (r.kind === 'voice') {
      stats = statHtml(r.done, '/' + r.total, t('codex.live_stat_voiced'), true)
        + statHtml(pct, pct === '—' ? '' : '%', t('codex.live_stat_progress')) + statHtml(etaHtml(r.eta), '', t('codex.live_stat_eta'));
    } else {
      stats = statHtml(pct, pct === '—' ? '' : '%', t('codex.live_stat_progress'), true)
        + statHtml(`<span data-since="${esc(s.started_at || '')}"></span>`, '', t('codex.live_stat_elapsed'))
        + statHtml(etaHtml(r.eta), '', t('codex.live_stat_eta'));
    }
    kids.push({ k: key + ':stats', h: `<div class="lv-stats">${stats}</div>` });
    kids.push({ k: key + ':bar', h: `<div class="lv-bar${r.frac === null ? ' indeterminate' : ''}"><span style="width:${r.frac === null ? 30 : Math.round(r.frac * 100)}%"></span></div>` });
    const note = live && live.running && live.phase_note ? live.phase_note : '';
    const msg = [s.message, note].filter(Boolean).join(' · ');
    if (msg) kids.push({ k: key + ':msg', h: `<div class="lv-msg">${esc(msg)}</div>` });
    if (GRID_STEPS.has(s.name) && shots.length) kids.push(...gridItems(shots, s.name === 'tts', key));
    return {
      k: 'step:' + (s.name || ''),
      h: `<div class="lv-row st-running">${railHtml(s)}<div class="lv-run" data-kids></div></div>`,
      kids,
    };
  }

  function doneItem(task, s, live) {
    const st = s.status || 'pending';
    const key = 'step:' + (s.name || '');
    const shots = (live && Array.isArray(live.shots)) ? live.shots : [];
    let extra = '', kids = null;
    if (s.name === 'images' && shots.length) {
      if (state.showGrid[task.id]) {
        extra = `<div class="lv-grid-done" data-kids></div>`;
        kids = gridItems(shots, false, key).concat([{ k: key + ':hide',
          h: `<div><button type="button" class="cx-btn cx-btn-sm cx-btn-ghost" data-act="grid" data-task="${esc(task.id)}">${icon('unfold_less')}${esc(t('codex.live_hide_grid'))}</button></div>` }]);
      } else {
        // ảnh thật trước, ảnh tạm (ô phác thô) sau
        const pics = shots.filter(c => c.thumb && !c.sketch).concat(shots.filter(c => c.thumb && c.sketch)).slice(0, 5);
        const more = shots.length - pics.length;
        if (pics.length) {
          extra = `<div class="cx-filmstrip">
              ${pics.map(c => `<img loading="lazy" decoding="async" src="${esc(c.thumb)}" alt="" title="${esc(String(c.n) + (c.title ? ' · ' + c.title : ''))}">`).join('')}
              ${more > 0 ? `<span class="cx-filmstrip-more">${esc(t('codex.live_more', { n: more }))}</span>` : ''}
              <button type="button" class="cx-btn cx-btn-sm cx-btn-ghost" data-act="grid" data-task="${esc(task.id)}">${icon('grid_view')}${esc(t('codex.live_show_grid'))}</button>
            </div>`;
        }
      }
    }
    const msg = s.message && s.message !== s.label ? s.message : '';
    const item = {
      k: key,
      h: `<div class="lv-row st-${esc(st)}">${railHtml(s)}
          <div><div class="lv-line"><span class="lv-label">${esc(s.label || s.name || '')}</span>${msg ? `<span class="lv-msg">${esc(msg)}</span>` : ''}</div>${extra}</div>
        </div>`,
    };
    if (kids) item.kids = kids;
    return item;
  }

  function stepItems(task) {
    const live = liveOf(task);
    const ord = liveOrder(task.steps);
    const items = ord.main.map(s => (s.status === 'running' ? runningItem(s, live) : doneItem(task, s, live)));
    if (ord.next.length) {
      items.push({ k: 'next', h: `<div class="lv-row lv-next"><div class="lv-rail"></div><span class="lv-dot" aria-hidden="true"></span>
          <div class="lv-line"><span class="lv-label">${esc(t('codex.live_next'))}</span>
          <span class="lv-msg">${ord.next.map(s => esc(s.label || s.name || '')).join('<span class="arr">→</span>')}</span></div></div>` });
    }
    if (!items.length) items.push({ k: 'empty', h: `<div class="lv-empty">${esc(t('codex.live_no_steps'))}</div>` });
    return items;
  }

  function feedItems() {
    const run = runningTasks();
    if (!run.length) {
      const q = queueTasks();
      return [{ k: 'idle', h: `<div class="lv-empty">${icon('bedtime')}<br>${esc(t('codex.live_nothing'))}${q.length
        ? `<br>${esc(t('codex.live_next'))}: #${esc(q[0].seq)} ${esc(q[0].title || '')}` : ''}</div>` }];
    }
    return run.map((row) => {
      const task = (state.details[row.id] && state.details[row.id].task) || row;
      return { k: 'task:' + row.id, h: `<section class="lv-task">${taskHeadHtml(task)}<div class="lv-task-rows" data-kids></div></section>`,
        kids: stepItems(task) };
    });
  }

  function seatHtml(p) {
    let cls = 'closed', txt = t('codex.live_seat_closed');
    if (p.down) { cls = 'down'; txt = p.message || t('codex.live_seat_down'); }
    else if (p.video_blocked) { cls = 'down'; txt = t('codex.live_seat_video_blocked'); }
    else if (p.busy) { cls = 'busy'; txt = t('codex.live_seat_busy', { t: fmtSecs(p.busy_for || 0) }); }
    else if (p.running && p.logged_in === false) { cls = 'down'; txt = t('codex.live_seat_logged_out'); }
    else if (p.running) { cls = 'idle'; txt = t('codex.live_seat_idle'); }
    return `<div class="lv-seat ${cls}"><span class="lv-seat-dot" aria-hidden="true"></span><span>${esc(p.profile || '')}</span>
      <span class="lv-seat-state" title="${esc(txt)}">${esc(txt)}</span></div>`;
  }

  function recentHtml(row) {
    const full = (state.finals[row.id] && state.finals[row.id].task) || row;
    const failed = (row.summary && row.summary.failed) || null;
    const why = full.error || (failed && failed.status !== 'cancelled' ? `${failed.label || failed.name}: ${failed.message || ''}` : '');
    const link = watchLink(full.result);
    return `<div class="lv-recent st-${esc(row.status)}">
        <div class="lv-line"><span class="lv-seq">#${esc(row.seq)}</span>
          <span class="lv-badge st-${esc(row.status)}">${icon(STATUS_ICON[row.status] || 'help')}${esc(statusLabel(row.status))}</span>
          <span class="lv-hint">${esc(relTime(row.updated_at))}</span></div>
        <div class="lv-recent-title">${esc(row.title || '')}</div>
        ${why ? `<div class="lv-box err">${esc(String(why).slice(0, 400))}</div>` : ''}
        ${link ? `<a class="cx-btn cx-btn-sm cx-btn-ghost" href="${esc(link)}" target="_blank" rel="noopener">${icon('play_circle')}${esc(t('codex.live_watch'))}</a>` : ''}
      </div>`;
  }

  function sideItems() {
    const items = [];
    const q = queueTasks();
    items.push({ k: 'queue', h: `<section class="lv-card"><div class="lv-sec-head"><h2>${esc(t('codex.live_queue'))}</h2>
        <span class="lv-hint">${esc(t('codex.live_queue_n', { n: q.length }))}</span></div>
        ${q.length ? q.slice(0, 8).map(x => `<div class="lv-qrow"><span class="lv-seq">#${esc(x.seq)}</span><span class="lv-qtitle">${esc(x.title || '')}</span></div>`).join('')
          : `<div class="lv-hint">${esc(t('codex.live_queue_empty'))}</div>`}</section>` });
    const mu = state.muse;
    if (mu && mu.configured && Array.isArray(mu.pool) && mu.pool.length) {
      const remote = Number(mu.remote_seats) || 0;
      items.push({ k: 'muse', h: `<section class="lv-card"><div class="lv-sec-head"><h2>${esc(t('codex.live_seats'))}</h2>
          <span class="lv-hint">${esc(t('codex.live_seats_hint', { n: mu.pool.filter(p => p.busy).length, total: mu.pool.length }))}</span></div>
          ${mu.pool.map(seatHtml).join('')}
          ${remote ? `<div class="lv-hint">${esc(t('codex.live_seats_remote', { n: remote }))}</div>` : ''}</section>` });
    }
    items.push({ k: 'browsers', h: `<section class="lv-card"><div class="lv-sec-head"><h2>${esc(t('codex.live_browsers'))}</h2></div>
        <div class="lv-empty">${icon('web')}<br>${esc(t('codex.live_browsers_soon'))}</div></section>` });
    const recent = recentOf((state.lists.recent && state.lists.recent.tasks) || [], serverNow());
    items.push({ k: 'recent', h: `<section class="lv-card"><div class="lv-sec-head"><h2>${esc(t('codex.live_recent'))}</h2></div>
        ${recent.length ? recent.map(recentHtml).join('') : `<div class="lv-hint">${esc(t('codex.live_recent_empty'))}</div>`}</section>` });
    return items;
  }

  function footHtml() {
    return `<span data-next></span>${state.error ? `<span class="lv-err">${esc(state.error)}</span>` : ''}
      <button type="button" class="cx-btn cx-btn-sm cx-btn-ghost" data-act="refresh">${icon('refresh')}${esc(t('codex.live_refresh'))}</button>`;
  }

  function shell() {
    const app = document.getElementById('lv-app');
    if (app.querySelector('.lv-head')) return app;
    app.innerHTML = `<header class="lv-head" id="lv-head"></header>
      <div class="lv-main">
        <section class="lv-feed" aria-live="polite"><div class="lv-sec-head"><h2>${esc(t('codex.live_timeline'))}</h2>
          <span class="lv-hint">${esc(t('codex.live_newest_first'))}</span></div><div id="lv-rows"></div></section>
        <aside class="lv-side" id="lv-side"></aside>
      </div>
      <footer class="lv-foot" id="lv-foot"></footer>`;
    app.removeAttribute('aria-busy');
    return app;
  }

  function setHtml(el, html) {
    if (el && el.__h !== html) { el.innerHTML = html; el.__h = html; }
  }

  function render() {
    if (!state.loaded) return;
    shell();
    const run = runningTasks().length;
    document.title = (run ? '(' + run + ') ' : '') + t('codex.live_open') + ' — TubeCLI';
    setHtml(document.getElementById('lv-head'), headHtml());
    patchKeyed(document.getElementById('lv-rows'), feedItems());
    patchKeyed(document.getElementById('lv-side'), sideItems());
    setHtml(document.getElementById('lv-foot'), footHtml());
    tickClock();
  }

  /** Đồng hồ 1 giây trong trình duyệt: «đã chạy …», «còn khoảng …», «làm mới sau …» — không tốn request. */
  function tickClock() {
    const now = serverNow();
    document.querySelectorAll('[data-since]').forEach((el) => {
      const d = parseTs(el.getAttribute('data-since'));
      el.textContent = d ? fmtSecs((now - d.getTime()) / 1000) : '';
    });
    const sinceFetch = (Date.now() - (state.updatedAt || Date.now())) / 1000;
    document.querySelectorAll('[data-eta]').forEach((el) => {
      const v = el.getAttribute('data-eta');
      if (v === '') return;
      const left = Number(v) - sinceFetch;
      el.textContent = left > 0 ? fmtSecs(left) : t('codex.live_soon');
    });
    const nx = document.querySelector('[data-next]');
    if (nx) {
      const left = Math.max(0, Math.ceil((state.nextAt - Date.now()) / 1000));
      nx.textContent = state.busy ? t('codex.live_refreshing') : t('codex.live_next_refresh', { s: left });
    }
  }

  // ── Dữ liệu ────────────────────────────────────────────────────
  function noteClock(resp) {
    const date = resp.headers.get('Date');
    if (date) { const d = new Date(date); if (!isNaN(d.getTime())) state.clock = { iso: d.toISOString(), at: Date.now() }; }
  }

  async function fetchJsonText(url, etag) {
    const headers = {};
    if (etag) headers['If-None-Match'] = etag;
    const resp = await fetch(url, { headers, cache: 'no-store' });
    noteClock(resp);
    if (resp.status === 304) return { unchanged: true };
    const text = await resp.text();
    if (!resp.ok) {
      let msg = 'HTTP ' + resp.status;
      try { const d = JSON.parse(text); msg = (d && (d.detail || d.message)) || msg; } catch (e) { /* chữ thô */ }
      const err = new Error(typeof msg === 'string' ? msg : 'HTTP ' + resp.status);
      err.status = resp.status;
      throw err;
    }
    return { text, etag: resp.headers.get('ETag') || '' };
  }

  /** Một nhóm của bảng (ETag → 304 khi không đổi). Trả true khi có đổi. */
  async function fetchList(name, query) {
    const cur = state.lists[name];
    const r = await fetchJsonText(`${API}/tasks?view=board&${query}`, cur && cur.etag);
    if (r.unchanged || (cur && cur.text === r.text)) return false;
    const d = JSON.parse(r.text);
    state.lists[name] = { etag: r.etag, text: r.text, tasks: (d && d.tasks) || [] };
    return true;
  }

  async function fetchDetail(id) {
    const r = await fetchJsonText(`${API}/tasks/${encodeURIComponent(id)}?events=0`);
    const cur = state.details[id];
    if (cur && cur.text === r.text) return false;
    const d = JSON.parse(r.text);
    state.details[id] = { text: r.text, task: (d && d.task) || d };
    return true;
  }

  async function fetchFinal(row) {
    const cur = state.finals[row.id];
    if (cur && cur.updated_at === row.updated_at) return false;
    const r = await fetchJsonText(`${API}/tasks/${encodeURIComponent(row.id)}?events=0`);
    const d = JSON.parse(r.text);
    state.finals[row.id] = { updated_at: row.updated_at, task: (d && d.task) || d };
    return true;
  }

  async function fetchLive(ep) {
    const cur = state.lives[ep] || (state.lives[ep] = {});
    if (cur.missing) return false;
    const resp = await fetch(`/api/v1/studio/episodes/${encodeURIComponent(ep)}/live`,
      { headers: cur.etag ? { 'If-None-Match': cur.etag } : {}, cache: 'no-store' });
    if (resp.status === 304) return false;
    if (resp.status === 404) { cur.missing = true; return false; }
    if (!resp.ok) return false;
    cur.etag = resp.headers.get('ETag') || '';
    const text = await resp.text();                  // lớp đệm giữa đường bỏ ETag thì vẫn biết «không đổi»
    if (text === cur.text) return false;
    cur.data = JSON.parse(text);
    cur.text = text;
    return true;
  }

  /** Chỗ ngồi Muse: hỏi NỀN (không bắt nhịp chính đợi), tối đa MUSE_MS một lần, `quick=1` = chỉ sổ trong bộ nhớ —
   *  bản đủ hỏi trang muse.ai của từng hồ sơ ~5–6 s (lõi cũ không biết quick thì vẫn chậm, nhưng không chặn trang). */
  function pollMuse(force) {
    if (state.museBusy || (!force && Date.now() - state.museAt < MUSE_MS)) return;
    state.museBusy = true;
    state.museAt = Date.now();
    fetch('/api/v1/muse/status?quick=1', { cache: 'no-store' })
      .then(r => (r.ok ? r.text() : ''))
      .then((text) => {
        if (!text || text === state.museText) return;
        state.muse = JSON.parse(text);
        state.museText = text;
        render();
      })
      .catch(() => { /* máy không có Muse */ })
      .finally(() => { state.museBusy = false; });
  }

  function schedule(ms) {
    if (timer) clearTimeout(timer);
    state.nextAt = Date.now() + ms;
    timer = setTimeout(tick, ms);
  }

  /** Một nhịp: danh sách (đang chạy / hàng đợi / mới đổi) → chi tiết + tiến độ từng cảnh của task đang chạy → kết quả
   *  task vừa xong → chỗ ngồi Muse (nền); có đổi thì vẽ lại phần đổi, rồi tự hẹn nhịp sau. */
  async function tick() {
    if (document.hidden) { schedule(BASE_MS); return; }
    if (state.busy) return;
    state.busy = true;
    tickClock();
    let changed = false;
    try {
      const lists = await Promise.all([
        fetchList('working', 'group=working&limit=20'),
        fetchList('backlog', 'group=backlog&limit=20'),
        fetchList('recent', 'group=all&sort=updated&limit=20'),
      ]);
      changed = lists.some(Boolean);
      state.error = '';
      const run = runningTasks();
      const alive = new Set(run.map(x => x.id));
      Object.keys(state.details).forEach((id) => { if (!alive.has(id)) delete state.details[id]; });
      const res = await Promise.all(run.map(x => fetchDetail(x.id).catch(() => false)));
      changed = res.some(Boolean) || changed;
      const eps = Array.from(new Set(run.map((x) => {
        const d = state.details[x.id];
        return Number(((d && d.task) || x).meta && ((d && d.task) || x).meta.episode_id) || 0;
      }).filter(Boolean)));
      const lv = await Promise.all(eps.map(ep => fetchLive(ep).catch(() => false)));
      changed = lv.some(Boolean) || changed;
      // Task vừa xong: tải kết quả / lỗi một lần, cùng tiến độ cảnh lần cuối để dải ảnh còn đúng.
      const recent = recentOf((state.lists.recent && state.lists.recent.tasks) || [], serverNow());
      const fin = await Promise.all(recent.map(x => fetchFinal(x).catch(() => false)));
      changed = fin.some(Boolean) || changed;
    } catch (e) {
      state.error = e.message || String(e);
      changed = true;
    }
    state.busy = false;
    state.loaded = true;
    state.updatedAt = Date.now();
    pollMuse(!state.museText);
    state.streak = changed ? 0 : state.streak + 1;
    render();
    schedule(liveDelay(state.streak));
  }

  /** Người dùng chạm trang (bấm, cuộn, gõ) → coi như đang xem: về nhịp 2 s. */
  function touch() {
    const slow = state.streak > 1;
    state.streak = 0;
    if (slow && !state.busy && state.nextAt - Date.now() > BASE_MS) schedule(BASE_MS);
  }

  function refreshNow() {
    state.streak = 0;
    Object.values(state.lives).forEach((L) => { L.missing = false; });
    schedule(0);
  }

  function onClick(ev) {
    const btn = ev.target.closest('[data-act]');
    if (!btn) return;
    const act = btn.getAttribute('data-act');
    if (act === 'refresh') refreshNow();
    else if (act === 'grid') {
      const id = btn.getAttribute('data-task') || '';
      state.showGrid[id] = !state.showGrid[id];
      render();
    }
  }

  function init() {
    document.addEventListener('click', onClick);
    ['pointerdown', 'keydown', 'wheel', 'touchstart'].forEach(ev => document.addEventListener(ev, touch, { passive: true }));
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) { state.streak = 0; schedule(50); }
    });
    setInterval(() => { if (!document.hidden) tickClock(); }, 1000);
    // Chữ giao diện và dữ liệu tải SONG SONG (như codex.js); chữ về sau thì dựng lại khung một lần cho đúng tiếng.
    const i18nReady = (typeof loadI18nFromApi === 'function') ? loadI18nFromApi().catch(() => {}) : Promise.resolve();
    tick();
    i18nReady.then(() => {
      if (!state.loaded) return;
      document.getElementById('lv-app').innerHTML = '';
      render();
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();

  return { liveDelay, liveOrder, runStats, cellState, recentOf, watchLink, refreshNow };
})();
