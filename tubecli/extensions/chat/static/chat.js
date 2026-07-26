/**
 * ═══════════════════════════════════════════════════════════════════
 *  Chat — one place to talk to the whole system.
 *  Vanilla ES2020, one IIFE module, no framework, no bundler.
 *  API: /api/v1/chat   ·   Page: /chat
 * ═══════════════════════════════════════════════════════════════════
 */

const CHAT = (() => {
  'use strict';

  // ── Constants ──────────────────────────────────────────────────
  const API = '/api/v1/chat';
  const SESSION_LIMIT = 100;
  const MESSAGE_LIMIT = 200;
  const LS_LAST = 'tubecli_chat_last_session';
  const LS_AGENT = 'tubecli_chat_agent_choice';
  const LS_SIDEBAR = 'tubecli_chat_sidebar';
  const STICK_PX = 90;
  const AUTO = '__auto__';
  const DEFAULT_TITLES = ['', 'Cuộc trò chuyện mới'];

  // ── State ──────────────────────────────────────────────────────
  const state = {
    sessions: [],
    agents: [],
    agentsOk: false,
    models: [],          // providers from GET /models: {id, label, source, models[]}
    messages: [],
    activeId: '',
    search: '',
    sending: false,
    stick: true,
    booted: false,
    agentChoice: {},     // sessionId -> agent id | AUTO
    renameId: '',
    confirmFn: null,
    lastDraft: '',
    thinkStarted: 0,
  };

  let thinkTimer = null;

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

  function icon(name, cls) {
    return '<span class="material-symbols-outlined' + (cls ? ' ' + cls : '') + '">' + esc(name) + '</span>';
  }

  function toast(msg, type) {
    const el = document.createElement('div');
    el.className = 'toast ' + (type || 'info');
    el.textContent = String(msg == null ? '' : msg);
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 3000);
  }

  /** Python isoformat() has microseconds and no timezone — trim to ms, parse local. */
  function parseTs(s) {
    if (!s) return null;
    const d = new Date(String(s).replace(/(\.\d{3})\d+/, '$1'));
    return isNaN(d.getTime()) ? null : d;
  }

  function relTime(ts) {
    const d = parseTs(ts);
    if (!d) return '';
    const sec = Math.max(0, Math.floor((Date.now() - d.getTime()) / 1000));
    if (sec < 60) return t('chat.time_now');
    if (sec < 3600) return t('chat.time_min', { n: Math.floor(sec / 60) });
    if (sec < 86400) return t('chat.time_hour', { n: Math.floor(sec / 3600) });
    return t('chat.time_day', { n: Math.floor(sec / 86400) });
  }

  function clockTime(ts) {
    const d = parseTs(ts);
    if (!d) return '';
    const p = (n) => String(n).padStart(2, '0');
    return p(d.getHours()) + ':' + p(d.getMinutes());
  }

  function sessionTitle(s) {
    const title = (s && typeof s.title === 'string') ? s.title.trim() : '';
    return (!title || DEFAULT_TITLES.indexOf(title) >= 0) ? t('chat.untitled') : title;
  }

  function findSession(id) {
    for (let i = 0; i < state.sessions.length; i++) {
      if (state.sessions[i] && state.sessions[i].id === id) return state.sessions[i];
    }
    return null;
  }

  function activeSession() { return findSession(state.activeId); }

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

  function sUrl(id, suffix) {
    return '/sessions/' + encodeURIComponent(id || '') + (suffix || '');
  }

  // ═══════════════════════════════════════════════════════════════
  //  Markdown — escape FIRST, then format. Never inject raw output.
  // ═══════════════════════════════════════════════════════════════
  const TK = '\u0000';

  function safeUrl(url) {
    const raw = String(url || '').trim();
    if (!raw) return '';
    // `raw` is already HTML-escaped; decode just enough to test the scheme.
    const probe = raw.replace(/&amp;/g, '&').replace(/&#39;/g, "'").replace(/&quot;/g, '"');
    if (/^(https?:\/\/|mailto:|tel:|\/|#|\.\/|\.\.\/)/i.test(probe)) return raw;
    if (/^[a-z][a-z0-9+.-]*:/i.test(probe)) return '';   // javascript:, data:, …
    return raw;
  }

  function codeBlockHtml(lang, code) {
    const language = String(lang || '').trim().split(/\s+/)[0];
    const body = String(code || '').replace(/\n+$/, '');
    return '<div class="ch-code">' +
      '<div class="ch-code-bar">' +
        '<span class="ch-code-lang">' + (language || 'code') + '</span>' +
        '<button type="button" class="ch-code-copy" onclick="CHAT.copyCode(this)">' +
          icon('content_copy') + '<span>' + esc(t('chat.copy')) + '</span>' +
        '</button>' +
      '</div>' +
      '<pre><code>' + body + '</code></pre></div>';
  }

  function mdInline(s, keep) {
    let out = String(s);
    out = out.replace(/`([^`\n]+)`/g, (m, c) => keep('<code class="ch-ic">' + c + '</code>'));
    out = out.replace(/!?\[([^\]\n]*)\]\(([^)\s]+)[^)]*\)/g, (m, txt, url) => {
      const href = safeUrl(url);
      if (!href) return m;
      const label = txt && txt.trim() ? txt : href;
      return keep('<a href="' + href + '" target="_blank" rel="noopener noreferrer">' + label + '</a>');
    });
    out = out.replace(/\*\*(?=\S)([\s\S]*?\S)\*\*/g, '<strong>$1</strong>');
    out = out.replace(/(^|[^\w])__(?=\S)([\s\S]*?\S)__(?!\w)/g, '$1<strong>$2</strong>');
    out = out.replace(/(^|[^*\w])\*(?=\S)([^*\n]*?\S)\*(?!\*)/g, '$1<em>$2</em>');
    out = out.replace(/(^|[^_\w])_(?=\S)([^_\n]*?\S)_(?!\w)/g, '$1<em>$2</em>');
    out = out.replace(/~~(?=\S)([\s\S]*?\S)~~/g, '<del>$1</del>');
    out = out.replace(/(^|[\s(])(https?:\/\/[^\s<>()]*[^\s<>().,;:!?'"])/g,
      (m, pre, url) => pre + keep('<a href="' + url + '" target="_blank" rel="noopener noreferrer">' + url + '</a>'));
    return out;
  }

  function mdCells(line) {
    return String(line).replace(/^\s*\|/, '').replace(/\|\s*$/, '').split('|').map((c) => c.trim());
  }

  function mdRender(src) {
    if (src === null || src === undefined) return '';
    const store = [];
    const keep = (html) => { store.push(html); return TK + (store.length - 1) + TK; };

    let text = esc(String(src).replace(/\u0000/g, '')).replace(/\r\n?/g, '\n');
    text = text.replace(/```([^\n`]*)\n([\s\S]*?)```/g, (m, lang, code) => keep(codeBlockHtml(lang, code)));
    text = text.replace(/```([^\n`]*)\n([\s\S]*)$/, (m, lang, code) => keep(codeBlockHtml(lang, code)));

    const lines = text.split('\n');
    const out = [];
    const stack = [];           // { tag, indent, liOpen }
    let para = [];

    const flushPara = () => {
      if (!para.length) return;
      out.push('<p>' + para.join('<br>') + '</p>');
      para = [];
    };
    const closeLists = (toIndent) => {
      while (stack.length && (toIndent === null || stack[stack.length - 1].indent > toIndent)) {
        const f = stack.pop();
        if (f.liOpen) out.push('</li>');
        out.push('</' + f.tag + '>');
      }
    };

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];

      if (/^\s*$/.test(line)) {
        flushPara();
        let j = i + 1;
        while (j < lines.length && /^\s*$/.test(lines[j])) j++;
        const next = j < lines.length ? lines[j] : '';
        if (!/^\s*([-*+]|\d{1,9}[.)])\s+/.test(next)) closeLists(null);
        continue;
      }

      // A protected block (fenced code) sitting on its own line.
      if (new RegExp('^' + TK + '\\d+' + TK + '\\s*$').test(line)) {
        flushPara(); closeLists(null); out.push(line.trim());
        continue;
      }

      const h = line.match(/^(#{1,6})\s+(.*)$/);
      if (h) {
        flushPara(); closeLists(null);
        const lv = h[1].length;
        out.push('<h' + lv + '>' + mdInline(h[2].trim(), keep) + '</h' + lv + '>');
        continue;
      }

      if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
        flushPara(); closeLists(null); out.push('<hr>');
        continue;
      }

      if (/^\s*&gt;\s?/.test(line)) {
        flushPara(); closeLists(null);
        const quote = [];
        while (i < lines.length && /^\s*&gt;\s?/.test(lines[i])) {
          quote.push(mdInline(lines[i].replace(/^\s*&gt;\s?/, ''), keep));
          i++;
        }
        i--;
        out.push('<blockquote>' + quote.join('<br>') + '</blockquote>');
        continue;
      }

      // Table: a pipe row followed by a |---|---| separator.
      if (/^\s*\|.*\|\s*$/.test(line) && i + 1 < lines.length &&
          /^\s*\|[\s:|-]*\|\s*$/.test(lines[i + 1]) && lines[i + 1].indexOf('-') >= 0) {
        flushPara(); closeLists(null);
        const head = mdCells(line);
        const align = mdCells(lines[i + 1]).map((c) => {
          if (/^:.*:$/.test(c)) return ' style="text-align:center"';
          if (/:$/.test(c)) return ' style="text-align:right"';
          return '';
        });
        i += 2;
        const rows = [];
        while (i < lines.length && /^\s*\|/.test(lines[i])) { rows.push(mdCells(lines[i])); i++; }
        i--;
        let html = '<div class="ch-table-wrap"><table><thead><tr>';
        head.forEach((c, k) => { html += '<th' + (align[k] || '') + '>' + mdInline(c, keep) + '</th>'; });
        html += '</tr></thead><tbody>';
        rows.forEach((r) => {
          html += '<tr>';
          for (let k = 0; k < head.length; k++) {
            html += '<td' + (align[k] || '') + '>' + mdInline(r[k] || '', keep) + '</td>';
          }
          html += '</tr>';
        });
        out.push(html + '</tbody></table></div>');
        continue;
      }

      const li = line.match(/^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$/);
      if (li) {
        flushPara();
        const indent = li[1].replace(/\t/g, '  ').length;
        const tag = /^\d/.test(li[2]) ? 'ol' : 'ul';
        closeLists(indent);
        const top = stack[stack.length - 1];
        if (!top || indent > top.indent) {
          out.push('<' + tag + '>');
          stack.push({ tag: tag, indent: indent, liOpen: false });
        } else if (top.tag !== tag) {
          if (top.liOpen) out.push('</li>');
          out.push('</' + top.tag + '>');
          stack.pop();
          out.push('<' + tag + '>');
          stack.push({ tag: tag, indent: indent, liOpen: false });
        }
        const frame = stack[stack.length - 1];
        if (frame.liOpen) out.push('</li>');
        out.push('<li>' + mdInline(li[3], keep));
        frame.liOpen = true;
        continue;
      }

      // Continuation of the current list item, otherwise a paragraph line.
      if (stack.length && /^\s{2,}\S/.test(line) && stack[stack.length - 1].liOpen) {
        out.push('<br>' + mdInline(line.trim(), keep));
        continue;
      }
      closeLists(null);
      para.push(mdInline(line.trim(), keep));
    }
    flushPara();
    closeLists(null);

    let html = out.join('');
    let guard = 6;
    const re = new RegExp(TK + '(\\d+)' + TK, 'g');
    while (guard-- > 0 && html.indexOf(TK) >= 0) {
      html = html.replace(re, (m, n) => (store[Number(n)] !== undefined ? store[Number(n)] : ''));
    }
    return html.split(TK).join('');
  }

  // ═══════════════════════════════════════════════════════════════
  //  Sidebar — conversation list
  // ═══════════════════════════════════════════════════════════════
  function renderSessions() {
    const box = $('ch-sessions');
    const foot = $('ch-sb-foot');
    if (!box) return;

    const q = state.search.trim().toLowerCase();
    const list = state.sessions.filter((s) => {
      if (!s || !s.id) return false;
      if (!q) return true;
      return (sessionTitle(s) + ' ' + (s.last_preview || '')).toLowerCase().indexOf(q) >= 0;
    });

    if (foot) {
      foot.textContent = state.sessions.length
        ? t('chat.sessions_count', { n: state.sessions.length }) : '';
    }

    if (!list.length) {
      box.innerHTML = '<div class="ch-sb-empty">' +
        icon(q ? 'search_off' : 'chat_bubble') +
        '<div>' + esc(q ? t('chat.no_results') : t('chat.no_sessions')) + '</div>' +
        (q ? '' : '<span>' + esc(t('chat.no_sessions_hint')) + '</span>') +
        '</div>';
      return;
    }

    box.innerHTML = list.map((s) => {
      const id = esc(s.id);
      const active = s.id === state.activeId ? ' active' : '';
      const pinned = s.pinned ? ' pinned' : '';
      const count = Number(s.message_count) || 0;
      return '<div class="ch-srow' + active + pinned + '" onclick="CHAT.open(\'' + id + '\')" ' +
        'title="' + esc(sessionTitle(s)) + '">' +
        icon(s.pinned ? 'push_pin' : 'chat_bubble', 'ch-srow-icon') +
        '<div class="ch-srow-main">' +
          '<div class="ch-srow-title">' + esc(sessionTitle(s)) + '</div>' +
          '<div class="ch-srow-sub">' +
            '<span>' + esc(relTime(s.updated_at)) + '</span>' +
            (count ? '<span class="ch-dot-sep">·</span><span>' + esc(t('chat.messages_n', { n: count })) + '</span>' : '') +
          '</div>' +
        '</div>' +
        '<div class="ch-srow-actions">' +
          '<button type="button" class="ch-mini" onclick="CHAT.togglePin(event,\'' + id + '\')" ' +
            'title="' + esc(s.pinned ? t('chat.unpin') : t('chat.pin')) + '">' + icon('push_pin') + '</button>' +
          '<button type="button" class="ch-mini" onclick="CHAT.rename(event,\'' + id + '\')" ' +
            'title="' + esc(t('chat.rename')) + '">' + icon('edit') + '</button>' +
          '<button type="button" class="ch-mini danger" onclick="CHAT.confirmDelete(event,\'' + id + '\')" ' +
            'title="' + esc(t('chat.delete')) + '">' + icon('delete') + '</button>' +
        '</div>' +
      '</div>';
    }).join('');
  }

  // ═══════════════════════════════════════════════════════════════
  //  Header
  // ═══════════════════════════════════════════════════════════════
  function renderHeader() {
    const s = activeSession();
    const title = $('ch-title');
    const sub = $('ch-sub');
    const pin = $('ch-menu-pin');

    if (title) title.textContent = s ? sessionTitle(s) : t('chat.untitled');
    if (sub) {
      const bits = [];
      if (s && Number(s.message_count)) bits.push(t('chat.messages_n', { n: Number(s.message_count) }));
      if (s && s.agent_name) bits.push(t('chat.answered_by', { name: s.agent_name }));
      sub.textContent = bits.join('  ·  ');
    }
    if (pin) {
      const label = pin.querySelector('span:last-child');
      if (label) label.textContent = (s && s.pinned) ? t('chat.unpin') : t('chat.pin');
    }
    renderAgentPicker();
    renderModelPicker();
  }

  function renderAgentPicker() {
    const sel = $('ch-agent');
    if (!sel) return;
    const choice = state.agentChoice[state.activeId] || AUTO;
    const opts = ['<option value="' + AUTO + '">' + esc(t('chat.agent_auto')) + '</option>'];
    state.agents.forEach((a) => {
      if (!a || !a.id) return;
      const label = (a.name || a.id) + (a.role && a.role !== 'general' ? ' · ' + a.role : '');
      opts.push('<option value="' + esc(a.id) + '">' + esc(label) + '</option>');
    });
    sel.innerHTML = opts.join('');
    sel.value = choice;
    if (sel.value !== choice) sel.value = AUTO;
    sel.disabled = state.sending;
  }

  function renderModelPicker() {
    const sel = $('ch-model');
    if (!sel) return;
    const wrap = sel.closest('.ch-model');
    const label = t('chat.model_label');
    sel.setAttribute('aria-label', label);

    if (!state.models.length) {
      const hint = t('chat.no_models_hint');
      sel.innerHTML = '<option value="">' + esc(hint) + '</option>';
      sel.value = '';
      sel.disabled = true;
      sel.title = hint;
      if (wrap) { wrap.classList.add('disabled'); wrap.title = hint; }
      return;
    }

    const s = activeSession();
    const current = (s && typeof s.model === 'string') ? s.model : '';
    const opts = ['<option value="">' + esc(t('chat.model_default')) + '</option>'];
    let found = !current;
    state.models.forEach((p) => {
      if (!p || !Array.isArray(p.models) || !p.models.length) return;
      opts.push('<optgroup label="' + esc(p.label || p.id) + '">');
      p.models.forEach((m) => {
        if (!m) return;
        if (m === current) found = true;
        opts.push('<option value="' + esc(m) + '">' + esc(m) + '</option>');
      });
      opts.push('</optgroup>');
    });
    // A stored choice whose provider went away must still display.
    if (!found) opts.push('<option value="' + esc(current) + '">' + esc(current) + '</option>');

    sel.innerHTML = opts.join('');
    sel.value = current;
    if (sel.value !== current) sel.value = '';
    sel.disabled = state.sending;
    sel.title = label;
    if (wrap) { wrap.classList.remove('disabled'); wrap.title = label; }
  }

  // ═══════════════════════════════════════════════════════════════
  //  Thread
  // ═══════════════════════════════════════════════════════════════
  function metaHtml(meta) {
    if (!meta || typeof meta !== 'object') return '';
    const chips = [];
    if (meta.error) {
      chips.push('<span class="ch-chip err">' + icon('error') + esc(String(meta.error).slice(0, 160)) + '</span>');
    }
    if (meta.routed_to) {
      chips.push('<span class="ch-chip route">' + icon('alt_route') +
        esc(t('chat.meta_routed', { name: meta.routed_to })) + '</span>');
    } else if (meta.agent_name) {
      chips.push('<span class="ch-chip">' + icon('robot_2') + esc(meta.agent_name) + '</span>');
    }
    if (meta.model) {
      chips.push('<span class="ch-chip" title="' + esc(t('chat.model_label')) + '">' +
        icon('memory') + esc(meta.model) + '</span>');
    }
    if (meta.skill_used) {
      chips.push('<span class="ch-chip skill">' + icon('bolt') +
        esc(t('chat.meta_skill', { name: meta.skill_used })) + '</span>');
    }
    if (meta.action && meta.action !== 'run_skill' && meta.action !== 'reply') {
      chips.push('<span class="ch-chip act">' + icon('play_arrow') +
        esc(t('chat.meta_action', { name: meta.action })) + '</span>');
    }
    if (meta.intent) {
      chips.push('<span class="ch-chip intent" title="' + esc(t('chat.intent')) + '">' +
        icon('label') + esc(meta.intent) + '</span>');
    }
    return chips.length ? '<div class="ch-meta">' + chips.join('') + '</div>' : '';
  }

  function messageHtml(msg) {
    const m = msg || {};
    const id = esc(m.id || '');
    const time = esc(clockTime(m.ts));

    if (m.role === 'user') {
      return '<div class="ch-msg user" data-id="' + id + '">' +
        '<div class="ch-msg-body">' +
          '<div class="ch-bubble">' + esc(m.content || '') + '</div>' +
          '<div class="ch-foot"><span class="ch-time">' + time + '</span></div>' +
        '</div>' +
      '</div>';
    }

    const err = m.meta && m.meta.error ? ' err' : '';
    return '<div class="ch-msg ai' + err + '" data-id="' + id + '">' +
      '<div class="ch-avatar">' + icon('smart_toy') + '</div>' +
      '<div class="ch-msg-body">' +
        '<div class="ch-bubble ch-md">' + mdRender(m.content || '') + '</div>' +
        metaHtml(m.meta) +
        '<div class="ch-foot">' +
          '<span class="ch-time">' + time + '</span>' +
          '<button type="button" class="ch-mini" onclick="CHAT.copyMsg(this)" ' +
            'title="' + esc(t('chat.copy_message')) + '">' + icon('content_copy') + '</button>' +
        '</div>' +
      '</div>' +
    '</div>';
  }

  function emptyStateHtml() {
    const examples = ['chat.example_1', 'chat.example_2', 'chat.example_3', 'chat.example_4'];
    return '<div class="ch-empty">' +
      '<div class="ch-empty-icon">' + icon('auto_awesome') + '</div>' +
      '<h2>' + esc(t('chat.empty_title')) + '</h2>' +
      '<p>' + esc(t('chat.empty_desc')) + '</p>' +
      '<div class="ch-examples">' +
        examples.map((k) => {
          const text = t(k);
          return '<button type="button" class="ch-example" onclick="CHAT.useExample(this)">' +
            icon('arrow_forward') + '<span>' + esc(text) + '</span></button>';
        }).join('') +
      '</div>' +
    '</div>';
  }

  function renderThread() {
    const thread = $('ch-thread');
    if (!thread) return;
    if (!state.messages.length) {
      thread.innerHTML = emptyStateHtml();
    } else {
      thread.innerHTML = state.messages.map(messageHtml).join('');
    }
    state.stick = true;
    requestAnimationFrame(() => scrollToBottom(false));
  }

  function appendMessage(msg) {
    const thread = $('ch-thread');
    if (!thread) return;
    const empty = thread.querySelector('.ch-empty');
    if (empty) thread.innerHTML = '';
    state.messages.push(msg);
    const holder = document.createElement('div');
    holder.innerHTML = messageHtml(msg);
    const el = holder.firstElementChild;
    if (el) thread.appendChild(el);
    if (state.stick) requestAnimationFrame(() => scrollToBottom(false));
    return el;
  }

  function appendErrorBubble(text, draft) {
    const thread = $('ch-thread');
    if (!thread) return;
    const el = document.createElement('div');
    el.className = 'ch-msg ai err';
    el.innerHTML = '<div class="ch-avatar">' + icon('error') + '</div>' +
      '<div class="ch-msg-body">' +
        '<div class="ch-bubble ch-error">' +
          '<strong>' + esc(t('chat.error_title')) + '</strong>' +
          '<span>' + esc(text || '') + '</span>' +
        '</div>' +
        '<div class="ch-foot">' +
          (draft ? '<button type="button" class="ch-mini" onclick="CHAT.retryDraft()">' +
            icon('refresh') + '<span>' + esc(t('chat.error_retry')) + '</span></button>' : '') +
        '</div>' +
      '</div>';
    thread.appendChild(el);
    if (state.stick) requestAnimationFrame(() => scrollToBottom(false));
  }

  // ── Thinking indicator ─────────────────────────────────────────
  function showThinking() {
    const thread = $('ch-thread');
    if (!thread) return;
    hideThinking();
    const el = document.createElement('div');
    el.className = 'ch-msg ai ch-thinking-row';
    el.id = 'ch-thinking';
    el.innerHTML = '<div class="ch-avatar pulse">' + icon('smart_toy') + '</div>' +
      '<div class="ch-msg-body">' +
        '<div class="ch-bubble ch-thinking">' +
          '<span class="ch-dots"><i></i><i></i><i></i></span>' +
          '<span class="ch-think-label">' + esc(t('chat.thinking')) + '</span>' +
          '<span class="ch-think-elapsed" id="ch-elapsed"></span>' +
        '</div>' +
        '<div class="ch-think-hint">' + esc(t('chat.thinking_hint')) + '</div>' +
      '</div>';
    thread.appendChild(el);
    state.thinkStarted = Date.now();
    if (thinkTimer) clearInterval(thinkTimer);
    thinkTimer = setInterval(() => {
      const box = $('ch-elapsed');
      if (!box) return;
      box.textContent = Math.max(0, Math.round((Date.now() - state.thinkStarted) / 1000)) + 's';
    }, 1000);
    state.stick = true;
    requestAnimationFrame(() => scrollToBottom(false));
  }

  function hideThinking() {
    if (thinkTimer) { clearInterval(thinkTimer); thinkTimer = null; }
    const el = $('ch-thinking');
    if (el) el.remove();
  }

  // ── Scrolling ──────────────────────────────────────────────────
  function scrollToBottom(smooth) {
    const box = $('ch-scroll');
    if (!box) return;
    try {
      box.scrollTo({ top: box.scrollHeight, behavior: smooth ? 'smooth' : 'auto' });
    } catch (e) {
      box.scrollTop = box.scrollHeight;
    }
    state.stick = true;
    updateJump();
  }

  function onScroll() {
    const box = $('ch-scroll');
    if (!box) return;
    state.stick = (box.scrollHeight - box.scrollTop - box.clientHeight) < STICK_PX;
    updateJump();
  }

  function updateJump() {
    const btn = $('ch-jump');
    if (btn) btn.classList.toggle('hidden', state.stick);
  }

  // ═══════════════════════════════════════════════════════════════
  //  Data
  // ═══════════════════════════════════════════════════════════════
  async function loadAgents() {
    try {
      const data = await api('/agents');
      state.agents = Array.isArray(data.agents) ? data.agents.filter((a) => a && a.id) : [];
      state.agentsOk = true;
    } catch (e) {
      state.agents = [];
      state.agentsOk = false;     // the list is unknown — never block sending on it
    }
    renderAgentPicker();
  }

  async function loadModels() {
    try {
      const data = await api('/models');
      state.models = Array.isArray(data.providers)
        ? data.providers.filter((p) => p && p.id && Array.isArray(p.models) && p.models.length)
        : [];
    } catch (e) {
      state.models = [];   // picker falls back to its disabled hint state
    }
    renderModelPicker();
  }

  async function loadSessions() {
    try {
      const data = await api('/sessions?limit=' + SESSION_LIMIT);
      state.sessions = Array.isArray(data.sessions) ? data.sessions.filter((s) => s && s.id) : [];
    } catch (e) {
      state.sessions = [];
      toast(t('chat.load_failed'), 'error');
    }
    renderSessions();
  }

  function mergeSession(session) {
    if (!session || !session.id) return;
    const i = state.sessions.findIndex((s) => s && s.id === session.id);
    if (i >= 0) state.sessions[i] = Object.assign({}, state.sessions[i], session);
    else state.sessions.unshift(session);
    sortSessions();
  }

  function sortSessions() {
    state.sessions.sort((a, b) => {
      const pa = a && a.pinned ? 0 : 1;
      const pb = b && b.pinned ? 0 : 1;
      if (pa !== pb) return pa - pb;
      return String((b && b.updated_at) || '').localeCompare(String((a && a.updated_at) || ''));
    });
  }

  async function open(id) {
    if (!id) return;
    state.activeId = id;
    try { localStorage.setItem(LS_LAST, id); } catch (e) { /* private mode */ }
    if (location.hash.slice(1) !== id) {
      try { history.replaceState(null, '', '#' + id); } catch (e) { location.hash = id; }
    }
    renderSessions();
    renderHeader();
    closeSidebar();

    const thread = $('ch-thread');
    if (thread) thread.innerHTML = '<div class="ch-loading">' + icon('progress_activity', 'spin') +
      '<span>' + esc(t('chat.list_loading')) + '</span></div>';

    try {
      const data = await api(sUrl(id) + '?limit=' + MESSAGE_LIMIT);
      if (state.activeId !== id) return;
      state.messages = Array.isArray(data.messages) ? data.messages.filter((m) => m && m.role) : [];
      if (data.session) mergeSession(data.session);
      renderSessions();
      renderHeader();
      renderThread();
      focusInput();
    } catch (e) {
      if (state.activeId !== id) return;
      state.messages = [];
      if (thread) thread.innerHTML = '';
      appendErrorBubble(t('chat.session_load_failed') + ' — ' + e.message, false);
    }
  }

  async function newChat() {
    try {
      const data = await api('/sessions', { method: 'POST', body: JSON.stringify({}) });
      if (data && data.session && data.session.id) {
        mergeSession(data.session);
        renderSessions();
        await open(data.session.id);
        focusInput();
      }
    } catch (e) {
      toast(t('chat.create_failed') + ' — ' + e.message, 'error');
    }
  }

  // ═══════════════════════════════════════════════════════════════
  //  Sending
  // ═══════════════════════════════════════════════════════════════
  function setSending(on) {
    state.sending = !!on;
    const input = $('ch-input');
    const send = $('ch-send');
    const sendIcon = $('ch-send-icon');
    const composer = $('ch-composer');
    const sel = $('ch-agent');
    const modelSel = $('ch-model');
    if (input) input.disabled = !!on;
    if (send) send.disabled = !!on;
    if (sel) sel.disabled = !!on;
    if (modelSel) modelSel.disabled = !!on || !state.models.length;
    if (composer) composer.classList.toggle('busy', !!on);
    if (sendIcon) sendIcon.textContent = on ? 'progress_activity' : 'arrow_upward';
    if (sendIcon) sendIcon.classList.toggle('spin', !!on);
  }

  function focusInput() {
    const input = $('ch-input');
    if (input && !input.disabled && window.innerWidth > 900) {
      try { input.focus(); } catch (e) { /* ignore */ }
    }
  }

  function autoGrow(el) {
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 220) + 'px';
  }

  function onKey(event) {
    if (!event) return;
    if (event.key === 'Enter' && !event.shiftKey && !event.ctrlKey && !event.metaKey && !event.isComposing) {
      event.preventDefault();
      send();
    }
  }

  async function send() {
    if (state.sending) return;
    const input = $('ch-input');
    if (!input) return;
    const text = String(input.value || '').trim();
    if (!text) return;

    if (!state.activeId) {
      await newChat();
      if (!state.activeId) return;
    }
    const sid = state.activeId;

    if (state.agentsOk && !state.agents.length) {
      toast(t('chat.no_agents'), 'error');
      return;
    }

    state.lastDraft = text;
    input.value = '';
    autoGrow(input);
    setSending(true);

    appendMessage({ id: 'local-' + Date.now(), role: 'user', content: text, ts: new Date().toISOString() });
    showThinking();

    const choice = state.agentChoice[sid] || AUTO;
    const body = { message: text };
    if (choice === AUTO) {
      body.auto_route = true;
    } else {
      body.agent_id = choice;
      body.auto_route = false;
    }

    try {
      const data = await api(sUrl(sid, '/messages'), { method: 'POST', body: JSON.stringify(body) });
      hideThinking();
      if (state.activeId !== sid) {
        setSending(false);
        await loadSessions();
        return;
      }
      if (data && data.user_message && data.user_message.id) {
        const last = state.messages[state.messages.length - 1];
        if (last && last.role === 'user') { last.id = data.user_message.id; last.ts = data.user_message.ts; }
      }
      if (data && data.message) appendMessage(data.message);
      if (data && data.session) mergeSession(data.session);
      state.lastDraft = '';
      renderSessions();
      renderHeader();
    } catch (e) {
      hideThinking();
      appendErrorBubble(t('chat.send_failed') + ' — ' + e.message, true);
      const box = $('ch-input');
      if (box && !String(box.value || '').trim()) { box.value = text; autoGrow(box); }
      toast(t('chat.send_failed'), 'error');
    } finally {
      setSending(false);
      focusInput();
    }
  }

  function retryDraft() {
    const input = $('ch-input');
    if (!input || !state.lastDraft) return;
    input.value = state.lastDraft;
    autoGrow(input);
    input.focus();
  }

  function useExample(btn) {
    const input = $('ch-input');
    if (!input || !btn) return;
    const label = btn.querySelector('span');
    input.value = label ? label.textContent : '';
    autoGrow(input);
    input.focus();
    send();
  }

  // ═══════════════════════════════════════════════════════════════
  //  Session actions
  // ═══════════════════════════════════════════════════════════════
  async function updateSession(id, patch) {
    const data = await api(sUrl(id), { method: 'PUT', body: JSON.stringify(patch || {}) });
    if (data && data.session) mergeSession(data.session);
    renderSessions();
    renderHeader();
    return data;
  }

  async function togglePin(event, id) {
    if (event) event.stopPropagation();
    const s = findSession(id);
    if (!s) return;
    try {
      await updateSession(id, { pinned: !s.pinned });
    } catch (e) {
      toast(e.message, 'error');
    }
  }

  function togglePinActive() {
    closeMenu();
    if (state.activeId) togglePin(null, state.activeId);
  }

  function rename(event, id) {
    if (event) event.stopPropagation();
    const s = findSession(id);
    if (!s) return;
    state.renameId = id;
    const input = $('ch-rename-input');
    if (input) input.value = sessionTitle(s);
    openModal('ch-modal-rename');
    setTimeout(() => { if (input) { input.focus(); input.select(); } }, 40);
  }

  function renameActive() {
    closeMenu();
    if (state.activeId) rename(null, state.activeId);
  }

  function onRenameKey(event) {
    if (event && event.key === 'Enter') { event.preventDefault(); submitRename(); }
  }

  async function submitRename() {
    const input = $('ch-rename-input');
    const id = state.renameId;
    if (!id || !input) return closeModal('ch-modal-rename');
    const title = String(input.value || '').trim().slice(0, 60);
    closeModal('ch-modal-rename');
    if (!title) return;
    try {
      await updateSession(id, { title: title });
      toast(t('chat.renamed'), 'success');
    } catch (e) {
      toast(e.message, 'error');
    }
  }

  function confirmDelete(event, id) {
    if (event) event.stopPropagation();
    const s = findSession(id);
    if (!s) return;
    askConfirm(
      t('chat.confirm_delete_title'),
      t('chat.confirm_delete_desc', { title: sessionTitle(s) }),
      t('chat.btn_delete'),
      async () => {
        try {
          await api(sUrl(id), { method: 'DELETE' });
          state.sessions = state.sessions.filter((x) => x && x.id !== id);
          renderSessions();
          toast(t('chat.deleted'), 'success');
          if (state.activeId === id) {
            state.activeId = '';
            state.messages = [];
            if (state.sessions.length) await open(state.sessions[0].id);
            else await newChat();
          }
        } catch (e) {
          toast(e.message, 'error');
        }
      }
    );
  }

  function deleteActive() {
    closeMenu();
    if (state.activeId) confirmDelete(null, state.activeId);
  }

  function clearActive() {
    closeMenu();
    const id = state.activeId;
    if (!id) return;
    askConfirm(
      t('chat.confirm_clear_title'),
      t('chat.confirm_clear_desc'),
      t('chat.btn_clear'),
      async () => {
        try {
          await api(sUrl(id, '/clear'), { method: 'POST', body: JSON.stringify({}) });
          state.messages = [];
          renderThread();
          const s = findSession(id);
          if (s) { s.message_count = 0; s.last_preview = ''; }
          renderSessions();
          renderHeader();
          toast(t('chat.cleared'), 'success');
        } catch (e) {
          toast(e.message, 'error');
        }
      }
    );
  }

  async function onAgentChange(value) {
    const sid = state.activeId;
    if (!sid) return;
    state.agentChoice[sid] = value || AUTO;
    persistChoices();
    if (value && value !== AUTO) {
      try { await updateSession(sid, { agent_id: value }); } catch (e) { /* picker still applies per-turn */ }
    }
  }

  async function onModelChange(value) {
    const sid = state.activeId;
    if (!sid) return;
    const model = String(value || '');
    try {
      await updateSession(sid, { model: model });
      toast(t('chat.toast_model_changed', { name: model || t('chat.model_default') }), 'success');
    } catch (e) {
      toast(e.message, 'error');
      renderModelPicker();   // snap back to the stored choice
    }
  }

  function persistChoices() {
    try {
      const keys = Object.keys(state.agentChoice).slice(-60);
      const trimmed = {};
      keys.forEach((k) => { trimmed[k] = state.agentChoice[k]; });
      localStorage.setItem(LS_AGENT, JSON.stringify(trimmed));
    } catch (e) { /* ignore */ }
  }

  function loadChoices() {
    try {
      const raw = localStorage.getItem(LS_AGENT);
      const parsed = raw ? JSON.parse(raw) : null;
      if (parsed && typeof parsed === 'object') state.agentChoice = parsed;
    } catch (e) { state.agentChoice = {}; }
  }

  // ═══════════════════════════════════════════════════════════════
  //  Clipboard
  // ═══════════════════════════════════════════════════════════════
  function writeClipboard(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text);
    }
    return new Promise((resolve, reject) => {
      try {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        ta.remove();
        resolve();
      } catch (e) { reject(e); }
    });
  }

  function flashCopied(btn) {
    if (!btn) return;
    const label = btn.querySelector('span:not(.material-symbols-outlined)');
    if (label) {
      const old = label.textContent;
      label.textContent = t('chat.copied');
      setTimeout(() => { label.textContent = old; }, 1400);
    } else {
      btn.classList.add('ok');
      setTimeout(() => btn.classList.remove('ok'), 1400);
    }
  }

  function copyCode(btn) {
    if (!btn) return;
    const wrap = btn.closest('.ch-code');
    const code = wrap ? wrap.querySelector('code') : null;
    if (!code) return;
    writeClipboard(code.textContent || '')
      .then(() => flashCopied(btn))
      .catch(() => toast(t('chat.copy_failed'), 'error'));
  }

  function copyMsg(btn) {
    if (!btn) return;
    const row = btn.closest('.ch-msg');
    const id = row ? row.getAttribute('data-id') : '';
    const msg = state.messages.find((m) => m && m.id === id);
    const body = row ? row.querySelector('.ch-bubble') : null;
    const text = msg ? (msg.content || '') : (body ? body.textContent : '');
    writeClipboard(text)
      .then(() => flashCopied(btn))
      .catch(() => toast(t('chat.copy_failed'), 'error'));
  }

  // ═══════════════════════════════════════════════════════════════
  //  Chrome — sidebar, menu, modals
  // ═══════════════════════════════════════════════════════════════
  function toggleSidebar() {
    const app = $('ch-app');
    if (!app) return;
    if (window.innerWidth <= 900) {
      app.classList.toggle('sb-open');
    } else {
      app.classList.toggle('sb-hidden');
      try { localStorage.setItem(LS_SIDEBAR, app.classList.contains('sb-hidden') ? '0' : '1'); } catch (e) { /* ignore */ }
    }
  }

  function closeSidebar() {
    const app = $('ch-app');
    if (app && window.innerWidth <= 900) app.classList.remove('sb-open');
  }

  function onSearch(value) {
    state.search = String(value || '');
    renderSessions();
  }

  function toggleMenu(event) {
    if (event) event.stopPropagation();
    const menu = $('ch-menu');
    if (menu) menu.classList.toggle('hidden');
  }

  function closeMenu() {
    const menu = $('ch-menu');
    if (menu) menu.classList.add('hidden');
  }

  function openModal(id) {
    const el = $(id);
    if (el) el.classList.remove('hidden');
  }

  function closeModal(id) {
    const el = $(id);
    if (el) el.classList.add('hidden');
  }

  function onBackdrop(event, id) {
    if (event && event.target && event.target.id === id) closeModal(id);
  }

  function askConfirm(title, desc, okLabel, fn) {
    state.confirmFn = fn;
    const h = $('ch-confirm-title');
    const d = $('ch-confirm-desc');
    const ok = $('ch-confirm-ok');
    if (h) h.textContent = title;
    if (d) d.textContent = desc;
    if (ok) ok.textContent = okLabel;
    openModal('ch-modal-confirm');
  }

  function confirmYes() {
    const fn = state.confirmFn;
    state.confirmFn = null;
    closeModal('ch-modal-confirm');
    if (typeof fn === 'function') fn();
  }

  // ═══════════════════════════════════════════════════════════════
  //  Boot
  // ═══════════════════════════════════════════════════════════════
  function pickInitialSession() {
    const hash = decodeURIComponent(String(location.hash || '').slice(1));
    if (hash && findSession(hash)) return hash;
    let last = '';
    try { last = localStorage.getItem(LS_LAST) || ''; } catch (e) { last = ''; }
    if (last && findSession(last)) return last;
    return state.sessions.length ? state.sessions[0].id : '';
  }

  async function init() {
    if (typeof loadI18nFromApi === 'function') {
      try { await loadI18nFromApi(); } catch (e) { /* keys render as-is */ }
    }
    loadChoices();

    const app = $('ch-app');
    let pref = '1';
    try { pref = localStorage.getItem(LS_SIDEBAR) || '1'; } catch (e) { pref = '1'; }
    if (app && pref === '0') app.classList.add('sb-hidden');

    const scroll = $('ch-scroll');
    if (scroll) scroll.addEventListener('scroll', onScroll, { passive: true });

    document.addEventListener('click', (e) => {
      const menu = $('ch-menu');
      const target = e && e.target;
      const inside = target && typeof target.closest === 'function' && target.closest('.ch-menu-wrap');
      if (menu && !menu.classList.contains('hidden') && !inside) closeMenu();
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        closeMenu();
        closeModal('ch-modal-rename');
        closeModal('ch-modal-confirm');
        closeSidebar();
      }
    });
    window.addEventListener('hashchange', () => {
      const id = decodeURIComponent(String(location.hash || '').slice(1));
      if (id && id !== state.activeId && findSession(id)) open(id);
    });

    await Promise.all([loadAgents(), loadModels(), loadSessions()]);

    const id = pickInitialSession();
    if (id) await open(id);
    else await newChat();

    state.booted = true;
    renderHeader();
    focusInput();
  }

  document.addEventListener('DOMContentLoaded', init);

  // ── Public surface (referenced by inline onclick handlers) ─────
  return {
    init, open, newChat, send, onKey, autoGrow, useExample, retryDraft,
    onSearch, togglePin, togglePinActive, rename, renameActive, onRenameKey,
    submitRename, confirmDelete, deleteActive, clearActive, onAgentChange, onModelChange,
    copyCode, copyMsg, toggleSidebar, closeSidebar, toggleMenu,
    openModal, closeModal, onBackdrop, confirmYes, scrollToBottom,
  };
})();
