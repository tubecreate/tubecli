/**
 * fm_actions.js — the [data-fm-action] router, plus every CRUD / navigation
 * handler and the drive list in the left rail.
 *
 * WHY THIS FILE EXISTS
 * --------------------
 * file_manager.html and file_manager.css were rebuilt from scratch; the markup
 * now declares its behaviour with `data-fm-action` attributes. file_manager.js
 * was written for the previous markup and contains no reference to any of them,
 * so every button in the new page is inert. This file attaches behaviour to the
 * new markup WITHOUT editing file_manager.js — three sibling modules
 * (storage / cleanup / permissions) do the same for their own areas, which is
 * why the wiring lives in a shared registry instead of one big controller.
 *
 * LOAD ORDER (matters)
 * --------------------
 * This script defines window.FMActions.register(), so it must be the FIRST of
 * the four modules in the page. It must also load AFTER file_manager.js, whose
 * IIFE publishes window.FM and window.T that everything here builds on. Every
 * dependency is still probed rather than assumed: if window.FM is missing, the
 * handlers say so in a toast instead of throwing a TypeError that would take
 * the rest of the page down.
 *
 * THE REGISTRY CONTRACT
 * ---------------------
 *   FMActions.register({ 'storage-scan': fn }, 'storage')   // fn(element, event)
 *   FMActions.has(name) / FMActions.names() / FMActions.run(name, el, ev)
 * A name may be claimed once. A second claim is reported as an error and the
 * first handler is kept: silently overwriting one module's handler with
 * another's produces a page that half-works with no trace of why.
 *
 * CROSS-MODULE EVENTS (dispatched on `document`, all with .detail)
 * ---------------------------------------------------------------
 *   fm:navigate      {path}           the browser moved to another folder
 *   fm:view-change   {view, path}     files | storage | cleanup tab switched
 *   fm:pane-change   {pane, path}     details | perm pane of the right panel
 *   fm:scope-change  {path}           the path the storage/cleanup views act on
 * These are the only way this file talks to the other three modules. Listening
 * is optional; nothing here depends on anyone answering.
 *
 * NOT REGISTERED HERE, ON PURPOSE: every 'storage-*', 'cleanup-*' and 'perm-*'
 * name. The sibling modules own them.
 *
 * 'cleanup-back' used to be handled here on the theory that it was pure markup
 * state. It is not: going back has to refuse while a delete is in flight, and
 * from the confirm card it must step back to the dry-run rather than discard
 * it. Both facts live in fm_cleanup's state machine, so fm_cleanup owns the
 * name. Registering it here as well made this module win on load order and
 * silently downgrade the two-step destructive flow.
 */
(function () {
    'use strict';

    var LOG = '[fm_actions] ';

    // ══════════════════════════════════════════════════════════════════
    // DOM access — a missing element degrades, never throws
    // ══════════════════════════════════════════════════════════════════

    var _warnedIds = Object.create(null);

    /**
     * getElementById with a one-shot warning. `optional` suppresses the warning
     * for elements that legitimately may not be on the page (the picker banner
     * outside picker mode, for instance).
     */
    function byId(id, optional) {
        var el = document.getElementById(id);
        if (!el && !optional && !_warnedIds[id]) {
            _warnedIds[id] = true;
            console.warn(LOG + 'element #' + id + ' is not in the page; the feature that needs it is skipped.');
        }
        return el;
    }

    function app() { return byId('fm-app'); }

    function clearNode(node) {
        while (node && node.firstChild) node.removeChild(node.firstChild);
    }

    /** Same construction rule as file_manager.js: text always via textContent, so
     *  a filename containing quotes or angle brackets can never become markup. */
    function el(tag, cls, text) {
        var n = document.createElement(tag);
        if (cls) n.className = cls;
        if (text !== undefined && text !== null) n.textContent = String(text);
        return n;
    }

    /** <svg class="fm-ico"><use href="#i-…"/></svg> against the inline sprite. */
    function icon(symbolId, cls) {
        var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.setAttribute('class', cls || 'fm-ico');
        svg.setAttribute('aria-hidden', 'true');
        var use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
        // Both spellings: `href` is the SVG2 attribute every current browser
        // honours, `xlink:href` keeps older engines from rendering an empty box.
        use.setAttribute('href', '#' + symbolId);
        use.setAttributeNS('http://www.w3.org/1999/xlink', 'xlink:href', '#' + symbolId);
        svg.appendChild(use);
        return svg;
    }

    function emit(name, detail) {
        try {
            document.dispatchEvent(new CustomEvent(name, { detail: detail || {} }));
        } catch (e) {
            console.warn(LOG + 'could not dispatch ' + name + ':', e);
        }
    }

    // ══════════════════════════════════════════════════════════════════
    // i18n — no user-visible string is ever written literally
    // ══════════════════════════════════════════════════════════════════

    var _warnedKeys = Object.create(null);

    /**
     * Two dictionaries exist on this page and neither covers the whole key set:
     * window.FMI18N (the inline bootstrap in file_manager.html) carries the
     * dotted keys the new markup uses plus a bundled offline default for each,
     * while window.T (file_manager.js) carries the legacy flat keys and the
     * aggregated /api/v1/i18n payload. Both answer a miss by returning the key
     * itself, so a miss is detectable — ask the markup dictionary first, fall
     * back to the legacy one, and only then surrender to the raw key (loudly,
     * because a raw dotted key on screen is a bug worth seeing).
     */
    function lookup(key) {
        var i18n = window.FMI18N;
        if (i18n && typeof i18n.t === 'function') {
            var a = i18n.t(key);
            if (typeof a === 'string' && a && a !== key) return a;
        }
        if (typeof window.T === 'function') {
            // Deliberately called without vars: substitution happens once, below.
            var b = window.T(key);
            if (typeof b === 'string' && b && b !== key) return b;
        }
        return null;
    }

    function T(key, vars) {
        var s = lookup(key);
        if (s === null) {
            if (!_warnedKeys[key]) {
                _warnedKeys[key] = true;
                console.warn(LOG + 'no translation for key: ' + key);
            }
            s = key;
        }
        if (vars) {
            Object.keys(vars).forEach(function (k) {
                s = s.split('{' + k + '}').join(String(vars[k]));
            });
        }
        return s;
    }

    // ══════════════════════════════════════════════════════════════════
    // Formatting + messages
    // ══════════════════════════════════════════════════════════════════

    var UNITS = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];

    function fmtBytes(n) {
        if (n === null || n === undefined || n === '' || isNaN(n)) return '—';
        var v = Number(n), i = 0;
        while (v >= 1024 && i < UNITS.length - 1) { v /= 1024; i++; }
        return (i === 0 ? v.toFixed(0) : v.toFixed(1)) + ' ' + UNITS[i];
    }

    function fmtInt(n) {
        if (n === null || n === undefined || isNaN(n)) return '0';
        return Number(n).toLocaleString();
    }

    /** The reason an operation failed, in the words the source used. */
    function errText(e) {
        if (!e) return T('fm.err.generic', { message: String(e) });
        if (typeof e === 'string') return e;
        if (e.message) return e.message;
        return T('fm.err.generic', { message: String(e) });
    }

    /** file_manager.js owns the toast styling; reuse it so severities match. */
    function toast(msg, kind) {
        var f = window.FM;
        if (f && typeof f.toast === 'function') return f.toast(msg, kind || 'info');
        // file_manager.js is not loaded. A silent failure here would hide the
        // very message that explains why the page is broken.
        console[(kind === 'error') ? 'error' : 'warn'](LOG + msg);
        return null;
    }

    // ══════════════════════════════════════════════════════════════════
    // Paths — file_manager.js keeps its helpers inside its IIFE
    // ══════════════════════════════════════════════════════════════════

    function baseName(p) {
        var s = String(p || '');
        var i = Math.max(s.lastIndexOf('/'), s.lastIndexOf('\\'));
        // Trailing separator: step back one level so "C:\data\" reports "data".
        if (i === s.length - 1 && s.length > 1) {
            s = s.slice(0, -1);
            i = Math.max(s.lastIndexOf('/'), s.lastIndexOf('\\'));
        }
        return i === -1 ? s : s.slice(i + 1);
    }

    function currentPath() {
        var f = window.FM;
        return (f && f.currentPath) || '';
    }

    /** The listing entry for a path, or null when it is not in the current view. */
    function itemFor(path) {
        var f = window.FM;
        if (!f || !Array.isArray(f.items)) return null;
        for (var i = 0; i < f.items.length; i++) {
            if (f.items[i] && f.items[i].path === path) return f.items[i];
        }
        return null;
    }

    /** undefined when unknown — openItem() then resolves it from its own list. */
    function isDirOf(path) {
        var it = itemFor(path);
        return it ? !!it.is_dir : undefined;
    }

    /**
     * The path an action applies to: the element's own data-path when it carries
     * one (rail items, volume rows), otherwise the current selection. The context
     * menu carries none, but showContextMenu() selects the item before opening,
     * so FM.selectedItem is authoritative there.
     */
    function targetPath(node) {
        if (node && node.closest) {
            var owner = node.closest('[data-path]');
            if (owner) {
                var p = owner.getAttribute('data-path');
                if (p) return p;
            }
        }
        var f = window.FM;
        return (f && f.selectedItem) || '';
    }

    function requireTarget(node) {
        var p = targetPath(node);
        if (!p) toast(T('fm.no_selection'), 'warn');
        return p;
    }

    // ══════════════════════════════════════════════════════════════════
    // Calling into file_manager.js
    // ══════════════════════════════════════════════════════════════════

    /**
     * Invoke an FM method, reporting its absence rather than throwing. Returns
     * whatever the method returns (often a promise), so callers can await the
     * real completion of a delete before refreshing the drive figures.
     */
    function callFM(method) {
        var args = Array.prototype.slice.call(arguments, 1);
        var f = window.FM;
        if (!f || typeof f[method] !== 'function') {
            console.error(LOG + 'FM.' + method + '() is unavailable — file_manager.js did not load, ' +
                'or it no longer exports that method.');
            toast(T('fm.err.generic', { message: 'FM.' + method + '()' }), 'error');
            return undefined;
        }
        return f[method].apply(f, args);
    }

    function settle(value) {
        return (value && typeof value.then === 'function') ? value : Promise.resolve(value);
    }

    // ══════════════════════════════════════════════════════════════════
    // The registry
    // ══════════════════════════════════════════════════════════════════

    var handlers = Object.create(null);
    var owners = Object.create(null);

    var FMActions = window.FMActions || {};
    window.FMActions = FMActions;

    // Published so file_manager.js can draw sprite icons too. It fell back to emoji
    // glyphs, which render in the OS colour font and look nothing like the outlined
    // icons used everywhere else on the page. Assigned here rather than beside
    // icon()'s definition: `var FMActions` is hoisted but undefined until this
    // line, so an earlier assignment would throw at load.
    FMActions.icon = icon;

    // A sibling module that loaded first may already have stashed handlers on
    // the object. Adopt them instead of discarding them, so a wrong script order
    // degrades to "works" rather than "half the page is dead".
    if (FMActions._handlers && typeof FMActions._handlers === 'object') {
        Object.keys(FMActions._handlers).forEach(function (k) {
            if (typeof FMActions._handlers[k] === 'function') {
                handlers[k] = FMActions._handlers[k];
                owners[k] = 'pre-registered';
            }
        });
    }

    FMActions._handlers = handlers;
    FMActions.conflicts = FMActions.conflicts || [];

    /**
     * @param {Object.<string,Function>} map  action name -> fn(element, event)
     * @param {string} [moduleName]           shown in the duplicate-name report
     */
    FMActions.register = function (map, moduleName) {
        if (!map || typeof map !== 'object') {
            console.error(LOG + 'register() needs an object of {name: function}; got:', map);
            return FMActions;
        }
        var who = moduleName || 'unnamed module';
        Object.keys(map).forEach(function (name) {
            var fn = map[name];
            if (typeof fn !== 'function') {
                console.error(LOG + 'register("' + name + '") from ' + who + ' is not a function; ignored.');
                return;
            }
            if (handlers[name]) {
                // Never silently overwrite: the loser would be a whole feature
                // that stops working with nothing on screen to explain it.
                var note = 'duplicate handler for data-fm-action="' + name + '" — kept the one from ' +
                    owners[name] + ', REJECTED the one from ' + who + '.';
                FMActions.conflicts.push({ name: name, kept: owners[name], rejected: who });
                console.error(LOG + note);
                return;
            }
            handlers[name] = fn;
            owners[name] = who;
        });
        return FMActions;
    };

    FMActions.has = function (name) { return typeof handlers[name] === 'function'; };

    FMActions.names = function () { return Object.keys(handlers).sort(); };

    FMActions.owner = function (name) { return owners[name] || null; };

    function reportActionError(name, e) {
        // An abort is the user's own cancel; a toast for it would read as a fault.
        if (e && e.aborted) return;
        console.error(LOG + 'handler "' + name + '" failed:', e);
        toast(errText(e), 'error');
    }

    /** Always resolves; true when the handler ran to completion. */
    FMActions.run = function (name, node, ev) {
        var fn = handlers[name];
        if (typeof fn !== 'function') {
            console.error(LOG + 'no handler registered for data-fm-action="' + name + '". ' +
                'Registered: ' + FMActions.names().join(', '));
            toast(T('fm.err.generic', { message: 'data-fm-action="' + name + '"' }), 'error');
            return Promise.resolve(false);
        }
        var out;
        try {
            out = fn(node, ev);
        } catch (e) {
            reportActionError(name, e);
            return Promise.resolve(false);
        }
        if (out && typeof out.then === 'function') {
            return out.then(function () { return true; }, function (e) {
                reportActionError(name, e);
                return false;
            });
        }
        return Promise.resolve(true);
    };

    // ══════════════════════════════════════════════════════════════════
    // View / rail / panel state — the attributes the stylesheet reads
    // ══════════════════════════════════════════════════════════════════

    var VIEWS = ['files', 'storage', 'cleanup'];
    var PANES = { details: 'fm-pane-details', perm: 'fm-pane-perm' };

    function setView(view) {
        if (VIEWS.indexOf(view) === -1) {
            console.error(LOG + 'unknown view "' + view + '"; expected one of ' + VIEWS.join(', '));
            return;
        }
        var root = app();
        if (!root) return;
        // data-view on #fm-app is the sole switch the stylesheet reads; the view
        // sections carry no `hidden` attribute precisely so there is no second
        // gate to forget.
        root.setAttribute('data-view', view);
        document.querySelectorAll('.fm-tab[data-fm-view]').forEach(function (tab) {
            var on = tab.getAttribute('data-fm-view') === view;
            tab.classList.toggle('is-active', on);
            tab.setAttribute('aria-selected', on ? 'true' : 'false');
        });
        emit('fm:view-change', { view: view, path: currentPath() });
    }

    function setRail(state) {
        var root = app();
        if (!root) return;
        root.setAttribute('data-rail', state);
        document.querySelectorAll('[data-fm-action="toggle-rail"]').forEach(function (b) {
            b.setAttribute('aria-expanded', state === 'open' ? 'true' : 'false');
        });
    }

    function setPanel(state) {
        var root = app();
        if (!root) return;
        root.setAttribute('data-panel', state);
        document.querySelectorAll('[data-fm-action="toggle-panel"]').forEach(function (b) {
            b.setAttribute('aria-expanded', state === 'open' ? 'true' : 'false');
        });
    }

    function panelState() {
        var root = app();
        return (root && root.getAttribute('data-panel')) || 'closed';
    }

    function setPane(pane, path) {
        if (!Object.prototype.hasOwnProperty.call(PANES, pane)) {
            console.error(LOG + 'unknown panel pane "' + pane + '"; expected ' + Object.keys(PANES).join(' or '));
            return;
        }
        Object.keys(PANES).forEach(function (key) {
            var node = byId(PANES[key], true);
            if (node) node.hidden = (key !== pane);
        });
        document.querySelectorAll('.fm-panel-tab[data-fm-pane]').forEach(function (tab) {
            var on = tab.getAttribute('data-fm-pane') === pane;
            tab.classList.toggle('is-active', on);
            tab.setAttribute('aria-selected', on ? 'true' : 'false');
        });
        var placeholder = byId('fm-panel-empty', true);
        if (placeholder) placeholder.hidden = true;
        emit('fm:pane-change', { pane: pane, path: path || targetPath(null) });
    }

    /** The folder the storage and cleanup views act on. */
    function setScope(path) {
        var label = byId('fm-scope-path', true);
        if (label) {
            label.textContent = path || '';
            // .fm-scope draws a bordered pill even with no text; an empty one on
            // first paint reads as a broken control rather than "no folder yet".
            label.hidden = !path;
        }
        emit('fm:scope-change', { path: path || '' });
    }

    // ══════════════════════════════════════════════════════════════════
    // Right panel — selection header
    // ══════════════════════════════════════════════════════════════════

    function fillSelectionHead(path) {
        var name = byId('fm-sel-name', true);
        var kind = byId('fm-sel-kind', true);
        var host = byId('fm-sel-icon', true);
        var dir = isDirOf(path);

        if (name) name.textContent = baseName(path);
        if (kind) kind.textContent = dir === undefined ? T('fm.common.unknown') : T(dir ? 'fm.common.folder' : 'fm.common.file');
        if (host) {
            clearNode(host);
            host.appendChild(icon(dir ? 'i-folder' : 'i-file', 'fm-ico fm-ico-lg'));
        }

        // GET /info returns null for a directory's size by contract, so the hint
        // that explains why (and offers the scan) belongs only to directories.
        var hint = byId('fm-dirsize-hint', true);
        if (hint) hint.hidden = (dir !== true);
    }

    // ══════════════════════════════════════════════════════════════════
    // The #fm-prompt dialog
    //
    // file_manager.js builds its own overlay for prompts, so this dialog in the
    // markup has no driver at all. It is exported as FMActions.prompt() rather
    // than left as dead markup — the sibling modules need a translated
    // single-field prompt and would otherwise each grow their own.
    // ══════════════════════════════════════════════════════════════════

    var _prompt = null;

    function closePrompt(value) {
        var box = byId('fm-prompt', true);
        if (box) box.hidden = true;
        var pending = _prompt;
        _prompt = null;
        if (pending) pending.resolve(value);
    }

    /** @returns {Promise<string|null>} null when cancelled. */
    FMActions.prompt = function (opts) {
        var o = opts || {};
        var box = byId('fm-prompt', true);
        if (!box) {
            console.warn(LOG + '#fm-prompt is not in the page; falling back to the file_manager.js dialog.');
            var f = window.FM;
            if (f && typeof f.promptDialog === 'function') return f.promptDialog(o.title || '', o.value || '');
            return Promise.resolve(null);
        }
        // A second prompt over an unanswered one would strand the first promise.
        if (_prompt) closePrompt(null);

        var title = byId('fm-prompt-title', true);
        var desc = byId('fm-prompt-desc', true);
        var label = byId('fm-prompt-label', true);
        var input = byId('fm-prompt-input', true);
        var error = byId('fm-prompt-error', true);
        var okBtn = byId('fm-prompt-ok', true);

        if (title) title.textContent = o.title || '';
        if (desc) { desc.textContent = o.desc || ''; desc.hidden = !o.desc; }
        if (label) label.textContent = o.label || '';
        if (error) { error.textContent = ''; error.hidden = true; }
        if (input) input.value = o.value || '';
        if (okBtn && o.okLabel) {
            // The default label lives in a child <span data-i18n>. Writing to the
            // button itself would delete that span, and the next applyI18n() pass
            // would then have nothing to translate.
            var slot = okBtn.querySelector('[data-i18n]') || okBtn;
            slot.removeAttribute('data-i18n');
            slot.textContent = o.okLabel;
        }

        box.hidden = false;
        if (input) setTimeout(function () { input.focus(); input.select(); }, 30);

        return new Promise(function (resolve) {
            _prompt = { resolve: resolve, validate: typeof o.validate === 'function' ? o.validate : null };
        });
    };

    function submitPrompt() {
        var input = byId('fm-prompt-input', true);
        var error = byId('fm-prompt-error', true);
        var value = input ? input.value : '';
        if (_prompt && _prompt.validate) {
            var problem = _prompt.validate(value);
            if (problem) {
                // Refuse in place, with the reason. Closing the dialog on invalid
                // input throws the typed text away and explains nothing.
                if (error) { error.textContent = problem; error.hidden = false; }
                if (input) input.focus();
                return;
            }
        }
        closePrompt(value);
    }

    // ══════════════════════════════════════════════════════════════════
    // Drive list — GET /api/v1/file-manager/disk
    // ══════════════════════════════════════════════════════════════════

    function serverMessage(data, res, raw) {
        if (data && typeof data === 'object') {
            var d = data.detail;
            if (typeof d === 'string' && d) return d;
            if (Array.isArray(d) && d.length) {
                return d.map(function (it) {
                    if (typeof it === 'string') return it;
                    var loc = Array.isArray(it.loc) ? it.loc.join('.') : '';
                    return (loc ? loc + ': ' : '') + (it.msg || JSON.stringify(it));
                }).join('\n');
            }
            if (typeof data.message === 'string' && data.message) return data.message;
            if (typeof data.error === 'string' && data.error) return data.error;
        }
        if (raw && raw.trim()) return raw.trim().slice(0, 400);
        return res.status + ' ' + (res.statusText || '');
    }

    /**
     * Standalone fetch used only when file_manager.js is absent. FM.feat() is
     * preferred because it probes which prefix the server actually mounted; this
     * one has to assume the documented prefix, but it applies the same rule —
     * every non-ok response throws carrying the server's own words.
     */
    async function requestJson(path) {
        var origin = '';
        try { origin = (localStorage.getItem('tubecli_api') || '').replace(/\/+$/, ''); } catch (e) { origin = ''; }
        var url = origin + '/api/v1/file-manager' + path;
        var res;
        try {
            res = await fetch(url);
        } catch (e) {
            throw new Error(T('fm.err.network') + '\n' + url + '\n' + (e && e.message ? e.message : e));
        }
        var text = await res.text();
        var data = null, parsed = true;
        if (text) { try { data = JSON.parse(text); } catch (e2) { parsed = false; } }
        if (!res.ok) throw new Error(parsed ? serverMessage(data, res, text) : serverMessage(null, res, text));
        if (!parsed) throw new Error(serverMessage(null, res, text));
        if (data && typeof data === 'object' && typeof data.error === 'string' && data.error) throw new Error(data.error);
        return data;
    }

    function fetchDisk() {
        var f = window.FM;
        if (f && typeof f.feat === 'function') return f.feat('GET', '/disk');
        return requestJson('/disk');
    }

    function setVolumeState(text, isError, withRetry) {
        var state = byId('fm-volumes-state', true);
        if (!state) return;
        // The element ships with data-i18n="fm.disk.reading". Both applyI18n()
        // passes on this page rewrite every [data-i18n] element's textContent, so
        // leaving the attribute in place would silently replace a real error with
        // "Reading volumes…" the moment the language dictionary arrives.
        state.removeAttribute('data-i18n');
        clearNode(state);
        state.hidden = false;
        state.classList.toggle('is-error', !!isError);
        state.appendChild(document.createTextNode(text));
        if (withRetry) {
            var btn = el('button', 'fm-btn fm-btn-quiet', T('fm.common.retry'));
            btn.type = 'button';
            // Reuses the action the refresh icon in the rail heading already
            // carries, so there is one code path for "read the drives again".
            btn.setAttribute('data-fm-action', 'volumes-refresh');
            btn.style.marginTop = '8px';
            state.appendChild(btn);
        }
    }

    function hideVolumeState() {
        var state = byId('fm-volumes-state', true);
        if (state) { state.hidden = true; state.classList.remove('is-error'); }
    }

    function volumePercent(v) {
        var pct = Number(v.percent);
        if (!isFinite(pct)) {
            var used = Number(v.used), free = Number(v.free);
            var denom = used + free;
            pct = denom > 0 ? (used / denom) * 100 : 0;
        }
        return Math.max(0, Math.min(100, pct));
    }

    function volumeRow(v) {
        var pct = volumePercent(v);
        // Thresholds are the ones the markup documents: warn crosses 80, crit 92.
        var state = pct >= 92 ? 'crit' : (pct >= 80 ? 'warn' : 'ok');
        var unreadable = !!v.error;

        var row = el('div', 'fm-vol');
        row.setAttribute('role', 'button');
        row.setAttribute('tabindex', '0');
        row.setAttribute('data-path', v.path || '');
        // An unreadable volume is a problem, not a full disk, but it shares the
        // alarm colour because both need the eye before anything else does.
        row.setAttribute('data-state', unreadable ? 'crit' : state);

        var title = [v.path || ''];
        if (v.fstype) title.push(T('fm.disk.fstype') + ': ' + v.fstype);
        if (!unreadable) {
            title.push(T('fm.disk.used') + ': ' + fmtBytes(v.used));
            title.push(T('fm.disk.total') + ': ' + fmtBytes(v.total));
            title.push(T('fm.disk.free') + ': ' + fmtBytes(v.free));
            if (state === 'crit') title.push(T('fm.disk.nearly_full'));
        } else {
            title.push(v.error);
        }
        row.title = title.join('\n');

        var top = el('div', 'fm-vol-top');
        top.appendChild(icon('i-hard-drive'));
        top.appendChild(el('span', 'fm-vol-label', v.label || v.path || ''));
        // A percentage for a drive that did not answer would be a fabricated
        // fact; the em dash says "not known" and the row title says why.
        top.appendChild(el('span', 'fm-vol-pct', unreadable ? '—' : (Math.round(pct) + '%')));
        row.appendChild(top);

        var track = el('div', 'fm-vol-track');
        var fill = el('div', 'fm-vol-fill');
        fill.style.width = (unreadable ? 0 : Math.round(pct * 10) / 10) + '%';
        track.appendChild(fill);
        row.appendChild(track);

        var meta = el('div', 'fm-vol-meta');
        if (unreadable) {
            // The server's own sentence, not a generic "unavailable".
            meta.appendChild(el('span', null, v.error));
        } else {
            meta.appendChild(el('span', null, fmtBytes(v.used) + ' / ' + fmtBytes(v.total)));
            meta.appendChild(el('span', null, T('fm.disk.free') + ' ' + fmtBytes(v.free)));
        }
        row.appendChild(meta);

        row.setAttribute('aria-label', (v.label || v.path || '') + ' — ' + row.title.split('\n').join(', '));
        row.__fmVolume = v;
        return row;
    }

    var _volumesBusy = false;
    var _volumesBound = false;

    async function loadVolumes() {
        var host = byId('fm-volumes', true);
        if (!host) return;
        if (_volumesBusy) return;           // a second click must not race the first
        _volumesBusy = true;

        bindVolumeHost(host);
        setVolumeState(T('fm.disk.reading'), false, false);

        try {
            var data = await fetchDisk();
            var vols = Array.isArray(data) ? data : (data && data.volumes);
            if (!Array.isArray(vols)) {
                throw new Error(T('fm.err.no_disk_info', {
                    message: JSON.stringify(data === undefined ? null : data).slice(0, 200)
                }));
            }
            clearNode(host);
            vols.forEach(function (v) {
                if (v && typeof v === 'object') host.appendChild(volumeRow(v));
            });
            if (!vols.length) setVolumeState(T('fm.disk.no_volumes'), false, true);
            else hideVolumeState();
        } catch (e) {
            // The list is cleared on purpose: leaving stale rows next to an error
            // reads as "these figures are current", which is the lie to avoid.
            clearNode(host);
            setVolumeState(T('fm.err.no_disk_info', { message: errText(e) }), true, true);
        } finally {
            _volumesBusy = false;
        }
    }

    function openVolumeRow(row) {
        var v = row.__fmVolume || { path: row.getAttribute('data-path') };
        if (!v.path) return;
        // openVolume() probes the path first and explains the allowed-roots
        // refusal, which is the usual answer for a drive outside the sandbox.
        callFM('openVolume', v);
    }

    function bindVolumeHost(host) {
        if (_volumesBound) return;
        _volumesBound = true;
        host.addEventListener('click', function (e) {
            var row = e.target.closest('.fm-vol');
            if (row && host.contains(row)) openVolumeRow(row);
        });
        host.addEventListener('keydown', function (e) {
            if (e.key !== 'Enter' && e.key !== ' ' && e.key !== 'Spacebar') return;
            var row = e.target.closest('.fm-vol');
            if (!row || !host.contains(row)) return;
            e.preventDefault();
            openVolumeRow(row);
        });
    }

    /**
     * file_manager.js still runs its own loadVolumes() at boot and after a
     * delete. It looks for #fmVolumes and, finding none, creates one and appends
     * it to <body> — a stray second drive list glued under the app. Giving it a
     * hidden element to write into is the only way to stop that without editing
     * that file. The visible list is the one rendered above.
     */
    function installLegacyVolumeSink() {
        var sink = document.getElementById('fmVolumes');
        if (!sink) {
            sink = document.createElement('div');
            sink.id = 'fmVolumes';
        }
        sink.hidden = true;
        sink.setAttribute('aria-hidden', 'true');
        var section = document.querySelector('.fm-rail-volumes') || document.body;
        // appendChild also MOVES an element that was already dumped on <body>,
        // so this repairs the page even when FM.init() ran first.
        if (section && sink.parentNode !== section) section.appendChild(sink);
    }

    // ══════════════════════════════════════════════════════════════════
    // Legacy visibility bridge
    //
    // The rebuilt stylesheet backs the `hidden` attribute with
    // `[hidden]{display:none!important}`. file_manager.js predates that markup
    // and reveals these five elements by writing element.style.display, which
    // !important now defeats — the preview modal, the context menu, the picker
    // banner and the empty/loading placeholders would all open invisibly and
    // read as a dead click. Dropping the attribute and expressing the same
    // initial state as inline display:none hands those elements back to the
    // mechanism file_manager.js actually drives, with no observer in the middle
    // (the context menu measures its own offsetWidth immediately after showing
    // itself, so the reveal has to be synchronous).
    // ══════════════════════════════════════════════════════════════════

    var LEGACY_DISPLAY_IDS = ['previewModal', 'contextMenu', 'pickerBanner', 'emptyState', 'loading'];

    function installLegacyDisplayBridge() {
        LEGACY_DISPLAY_IDS.forEach(function (id) {
            var node = byId(id, true);
            if (!node || !node.hasAttribute('hidden')) return;
            node.removeAttribute('hidden');
            // Only when nothing is set: if FM.init() already revealed the picker
            // banner, re-hiding it here would undo a correct decision.
            if (!node.style.display) node.style.display = 'none';
        });
    }

    /**
     * showProperties() finishes with panel.style.display = 'block'. The rebuilt
     * panel is a flex column inside a grid track sized by data-panel, so that
     * inline value collapses its header/body layout while leaving the track at
     * zero width — the properties would render into a strip nobody can see.
     * Translate the write into the attribute the stylesheet reads and drop it.
     */
    function installPanelDisplayBridge() {
        var panel = byId('propertiesPanel', true);
        if (!panel || typeof MutationObserver !== 'function') return;
        var obs = new MutationObserver(function () {
            var d = panel.style.display;
            if (d === '') return;                 // our own reset; nothing to do
            panel.style.display = '';
            setPanel(d === 'none' ? 'closed' : 'open');
        });
        obs.observe(panel, { attributes: true, attributeFilter: ['style'] });
    }

    // ══════════════════════════════════════════════════════════════════
    // Selection-driven chrome that file_manager.js does not know about
    // ══════════════════════════════════════════════════════════════════

    /**
     * selectItem() dims #btnPickerSelect with opacity and pointer-events but
     * never clears the `disabled` attribute the markup ships with, so in picker
     * mode the confirm button can never be pressed. Keep it in step with the
     * selection here.
     */
    function syncSelectionChrome() {
        var f = window.FM;
        var btn = byId('btnPickerSelect', true);
        // Guarded by pickerMode because isDirOf() is a linear scan of the current
        // listing and this runs on every click on the page.
        if (btn && f && f.pickerMode) {
            var sel = f.selectedItem;
            btn.disabled = !sel || isDirOf(sel) === true;
        }
        var placeholder = byId('fm-panel-empty', true);
        if (placeholder && f && !f.selectedItem) {
            var details = byId(PANES.details, true);
            var perm = byId(PANES.perm, true);
            // Only when both panes are closed: a pane that is open owns the body.
            if ((!details || details.hidden) && (!perm || perm.hidden)) placeholder.hidden = false;
        }
    }

    /**
     * navigate() is the one funnel every path change goes through, and it does
     * not exist as an event. Decorating the published object (not the file) is
     * the only way to keep the scope label and the picker button truthful.
     */
    function wrapNavigate() {
        var f = window.FM;
        if (!f || typeof f.navigate !== 'function' || f.__fmActionsNavWrapped) return;
        var original = f.navigate;
        f.__fmActionsNavWrapped = true;
        f.navigate = function () {
            var out = original.apply(this, arguments);
            // Read from the instance rather than the argument: navigate() assigns
            // currentPath before its first await, so this is the folder being
            // entered, not the one being left.
            setScope(this.currentPath);
            syncSelectionChrome();
            emit('fm:navigate', { path: this.currentPath });
            return out;
        };
    }

    // ══════════════════════════════════════════════════════════════════
    // Handlers
    // ══════════════════════════════════════════════════════════════════

    function actNewFolder() { return settle(callFM('createFolder')); }
    function actNewFile() { return settle(callFM('createFile')); }
    function actRename() { return settle(callFM('renameSelected')); }
    function actCopy() { return callFM('copySelected'); }
    function actMove() { return callFM('moveSelected'); }
    function actPaste() { return settle(callFM('pasteClipboard')); }
    function actUp() { return callFM('goUp'); }
    function actPickerConfirm() { return callFM('confirmPick'); }

    async function actDelete() {
        await settle(callFM('deleteSelected'));
        // Free space moved. FM.deleteSelected() refreshes its own (now hidden)
        // list; this refreshes the one on screen.
        await loadVolumes();
    }

    function actRefresh() {
        var errBlock = byId('fm-files-error', true);
        if (errBlock) errBlock.hidden = true;
        var f = window.FM;
        // With no current path the first listing never succeeded, so re-running
        // refresh() would do nothing at all; go back to the roots instead.
        if (f && !f.currentPath) return settle(callFM('loadRoots'));
        return settle(callFM('refresh'));
    }

    function actOpen(node) {
        var path = requireTarget(node);
        if (!path) return;
        return callFM('openItem', path, isDirOf(path));
    }

    /**
     * Show the file inside the page. A folder has nothing to preview, so it
     * falls through to navigation — the same behaviour openItem() already
     * implements, which is why this does not branch on the type itself.
     */
    function actPreview(node) {
        var path = requireTarget(node);
        if (!path) return;
        return settle(callFM('openItem', path, isDirOf(path)));
    }

    function actCopyPath(node) {
        var path = requireTarget(node);
        if (!path) return;
        return settle(callFM('copyPath', path));
    }

    async function actProperties(node) {
        var path = requireTarget(node);
        if (!path) return;
        setPanel('open');
        setPane('details', path);
        fillSelectionHead(path);
        await settle(callFM('showProperties'));
        // Belt and braces for browsers without MutationObserver, where the panel
        // bridge above cannot run.
        var panel = byId('propertiesPanel', true);
        if (panel && panel.style.display) { panel.style.display = ''; setPanel('open'); }
    }

    function actPermissions(node) {
        var path = requireTarget(node);
        if (!path) return;
        setPanel('open');
        fillSelectionHead(path);
        // setPane emits fm:pane-change{pane:'perm', path}, which is how the
        // permissions module learns what to load. If it also registered an
        // explicit loader, call that too — both routes, neither assumed.
        setPane('perm', path);
        if (FMActions.has('perm-load')) return FMActions.run('perm-load', node, null);
    }

    function actView(node) {
        var view = node && node.getAttribute('data-fm-view');
        if (!view) {
            console.error(LOG + 'a data-fm-action="view" element is missing its data-fm-view value.');
            return;
        }
        setView(view);
        // The scope pill names the folder the storage and cleanup views act on;
        // it has to be right the moment the tab appears, not after the next
        // navigation.
        setScope(currentPath());
    }

    function setFileLayout(mode) {
        callFM('setView', mode);
        // setView() toggles a legacy `.active` class; the rebuilt stylesheet
        // reads `.is-active` on .fm-seg-btn, and the pair is a radio group.
        var grid = byId('viewGrid', true), list = byId('viewList', true);
        [[grid, 'grid'], [list, 'list']].forEach(function (pair) {
            if (!pair[0]) return;
            var on = pair[1] === mode;
            pair[0].classList.toggle('is-active', on);
            pair[0].setAttribute('aria-pressed', on ? 'true' : 'false');
        });
    }

    function actViewGrid() { setFileLayout('grid'); }
    function actViewList() { setFileLayout('list'); }

    /** Send the storage view at a folder, then start it if its module is loaded. */
    async function analyzeFolder(node, ev, path) {
        var target = path;
        if (!target) { toast(T('fm.common.choose_folder'), 'warn'); return; }

        if (isDirOf(target) === false) {
            // A file was selected. Its own folder is the only thing a directory
            // walk can answer for, so say what is being measured by moving there.
            var cut = Math.max(target.lastIndexOf('/'), target.lastIndexOf('\\'));
            target = (cut > 0 ? target.slice(0, cut) : '') || currentPath();
        }
        if (target && target !== currentPath()) await settle(callFM('navigate', target));

        setView('storage');
        setScope(target || currentPath());

        if (FMActions.has('storage-scan')) return FMActions.run('storage-scan', node, ev);
        console.warn(LOG + 'no "storage-scan" handler is registered yet; the storage view is open ' +
            'but the walk has to be started from its own button.');
    }

    function actAnalyze(node, ev) {
        return analyzeFolder(node, ev, targetPath(node) || currentPath());
    }

    function actScanSelected(node, ev) {
        var path = requireTarget(node);
        if (!path) return;
        return analyzeFolder(node, ev, path);
    }

    function actClosePreview() {
        var modal = byId('previewModal', true);
        if (modal) { modal.hidden = false; modal.style.display = 'none'; }
        var body = byId('previewContent', true);
        // Dropping the text stops a stale file showing for a frame the next time
        // the modal opens, before the new content lands.
        if (body) body.textContent = '';
        var binary = byId('previewBinary', true);
        if (binary) binary.hidden = true;
    }

    function actClosePanel() { setPanel('closed'); }

    function actToggleRail() {
        var root = app();
        if (!root) return;
        setRail(root.getAttribute('data-rail') === 'open' ? 'closed' : 'open');
    }

    function actTogglePanel(node) {
        if (panelState() === 'open') { setPanel('closed'); return; }
        setPanel('open');
        var path = targetPath(node);
        // Opening onto an empty details pane is a dead end, so with a selection
        // this is the Properties action; without one the placeholder stands and
        // says so.
        if (path) return actProperties(node);
        var placeholder = byId('fm-panel-empty', true);
        if (placeholder) placeholder.hidden = false;
    }

    function actPanelTab(node) {
        var pane = node && node.getAttribute('data-fm-pane');
        if (!pane) {
            console.error(LOG + 'a data-fm-action="panel-tab" element is missing its data-fm-pane value.');
            return;
        }
        var path = targetPath(node);
        setPane(pane, path);
        if (path) fillSelectionHead(path);
        if (pane === 'perm' && path && FMActions.has('perm-load')) return FMActions.run('perm-load', node, null);
    }

    function actPromptOk() {
        if (!_prompt) {
            // Nothing is waiting on it — closing is still what the click asked for.
            console.warn(LOG + 'prompt-ok with no prompt open; closing the dialog.');
            closePrompt(null);
            return;
        }
        submitPrompt();
    }

    function actPromptCancel() { closePrompt(null); }

    function actVolumesRefresh() { return loadVolumes(); }

    /**
     * Step back from the dry-run / typed-confirmation cards to the category list.
     * Deliberately DOM-only — it makes no assumption about the cleanup module's
     * internal state, and it announces the retreat so that module can reset its
     * own. The selection bar comes back only if a category is genuinely still
     * ticked, read from the checkboxes rather than from a remembered count.
     */
    FMActions.register({
        'new-folder': actNewFolder,
        'new-file': actNewFile,
        'rename': actRename,
        'delete': actDelete,
        'copy': actCopy,
        'move': actMove,
        'paste': actPaste,
        'up': actUp,
        'refresh': actRefresh,
        'open': actOpen,
        'preview': actPreview,
        'properties': actProperties,
        'copy-path': actCopyPath,
        'view': actView,
        'view-list': actViewList,
        'view-grid': actViewGrid,
        'scan-selected': actScanSelected,
        'close-preview': actClosePreview,
        'close-panel': actClosePanel,
        'toggle-rail': actToggleRail,
        'toggle-panel': actTogglePanel,
        'panel-tab': actPanelTab,
        'prompt-ok': actPromptOk,
        'prompt-cancel': actPromptCancel,
        'picker-confirm': actPickerConfirm,
        'volumes-refresh': actVolumesRefresh,
        'analyze': actAnalyze,
        'permissions': actPermissions
    }, 'fm_actions');

    // ══════════════════════════════════════════════════════════════════
    // The single delegated listener
    // ══════════════════════════════════════════════════════════════════

    function actionNodeFor(target) {
        if (!target || typeof target.closest !== 'function') return null;
        return target.closest('[data-fm-action]');
    }

    function isInert(node) {
        if (node.disabled) return true;
        if (node.getAttribute('aria-disabled') === 'true') return true;
        // A fieldset switched off as a whole does not set .disabled on its
        // descendants, so the ancestor has to be checked too.
        return !!(node.closest && node.closest('fieldset[disabled]'));
    }

    document.addEventListener('click', function (ev) {
        // Runs on every click, before the early return: the selection may have
        // changed on a file card, which carries no action of its own.
        syncSelectionChrome();

        var node = actionNodeFor(ev.target);
        if (!node) return;
        if (isInert(node)) return;
        var name = node.getAttribute('data-fm-action');
        if (!name) return;
        // Anchors and submit buttons would otherwise navigate away mid-action.
        if (node.tagName === 'A' || node.type === 'submit') ev.preventDefault();
        FMActions.run(name, node, ev);
    });

    document.addEventListener('keydown', function (ev) {
        var tag = ev.target && ev.target.tagName;
        var typing = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' ||
            (ev.target && ev.target.isContentEditable);

        // The prompt dialog is not on file_manager.js's modal stack, so its
        // Escape handler cannot close it.
        if (ev.key === 'Escape' && _prompt) { ev.preventDefault(); closePrompt(null); return; }
        if (ev.key === 'Enter' && _prompt && ev.target === byId('fm-prompt-input', true)) {
            ev.preventDefault();
            submitPrompt();
            return;
        }
        if (typing) return;
        if (ev.key !== 'Enter' && ev.key !== ' ' && ev.key !== 'Spacebar') return;

        var node = actionNodeFor(ev.target);
        if (!node) return;
        // Buttons and links already fire a click from these keys; acting here too
        // would run the handler twice.
        if (node.tagName === 'BUTTON' || (node.tagName === 'A' && node.hasAttribute('href'))) return;
        if (isInert(node)) return;
        var name = node.getAttribute('data-fm-action');
        if (!name) return;
        ev.preventDefault();
        FMActions.run(name, node, ev);
    });

    /** Non-button action carriers need a tab stop and a role to be reachable. */
    function makeActionsFocusable(root) {
        (root || document).querySelectorAll('[data-fm-action]').forEach(function (node) {
            if (node.tagName === 'BUTTON' || node.tagName === 'A' || node.tagName === 'INPUT') return;
            if (!node.hasAttribute('tabindex')) node.setAttribute('tabindex', '0');
            if (!node.hasAttribute('role')) node.setAttribute('role', 'button');
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // Exported helpers — the sibling modules would otherwise each reimplement
    // these, and three copies of an error path is three chances to swallow one.
    // ══════════════════════════════════════════════════════════════════

    FMActions.util = {
        T: T,
        toast: toast,
        byId: byId,
        emit: emit,
        errText: errText,
        fmtBytes: fmtBytes,
        fmtInt: fmtInt,
        baseName: baseName,
        currentPath: currentPath,
        request: requestJson,
        serverMessage: serverMessage,
        setView: setView,
        setPane: setPane,
        setPanel: setPanel,
        setScope: setScope,
        refreshVolumes: loadVolumes
    };

    // ══════════════════════════════════════════════════════════════════
    // Boot
    // ══════════════════════════════════════════════════════════════════

    var _booted = false;

    /**
     * Run once the language dictionary is usable. Every string in a generated
     * drive row is resolved at build time and has no data-i18n attribute for a
     * later pass to correct, so building before the dictionary lands would paint
     * raw dotted keys into the rail. The timeout is the other half of that rule:
     * a hung /api/v1/i18n request must not leave the drives permanently unread,
     * because the bundled defaults are already a complete UI.
     */
    function whenI18nReady(fn) {
        if (window.FMI18N && window.FMI18N.ready) { fn(); return; }
        var done = false;
        var go = function () { if (done) return; done = true; fn(); };
        document.addEventListener('fm:i18n-ready', go);
        setTimeout(go, 5000);
    }

    function boot() {
        if (_booted) return;
        if (!document.getElementById('fm-app')) return;   // markup not parsed yet
        _booted = true;

        installLegacyDisplayBridge();
        installLegacyVolumeSink();
        installPanelDisplayBridge();
        makeActionsFocusable(document);
        catchUp();
        whenI18nReady(loadVolumes);
    }

    /** The parts that need window.FM, which may be published after this script. */
    function catchUp() {
        wrapNavigate();
        setScope(currentPath());
        syncSelectionChrome();
    }

    /*
     * Two entry points on purpose. The first runs while file_manager.html is
     * still being parsed (this script sits at the end of <body>), which is what
     * puts the #fmVolumes sink and the display bridge in place BEFORE FM.init()
     * fires on DOMContentLoaded. The listener is the fallback for any other load
     * order; boot() and catchUp() are both idempotent, so running twice costs
     * nothing.
     */
    boot();
    document.addEventListener('DOMContentLoaded', function () {
        boot();
        catchUp();
    });
})();
