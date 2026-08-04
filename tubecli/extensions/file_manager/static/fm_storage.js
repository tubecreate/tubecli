/*
 * ─────────────────────────────────────────────────────────────────────────────
 * fm_storage.js — behaviour for the inline "Storage analysis" view.
 *
 * Drives #fm-storage-* in file_manager.html. file_manager.js still carries the
 * older modal implementation (FM.openScan / FM._pollScan / FM._renderScanResult)
 * which targets markup that no longer exists; the fetch sequence and the
 * formatting rules below are lifted from it, but nothing here calls it.
 *
 * The one idea this file is built around: GET /usage/scan/{id} publishes
 * `children` and `largest` WHILE the walk is still running. Waiting for
 * status === "done" before drawing them throws away the entire point of a
 * background scan — on a multi-minute walk the user would stare at a percentage
 * for ten minutes with nothing to look at. So every poll paints the breakdown.
 * ─────────────────────────────────────────────────────────────────────────────
 */
(function () {
    'use strict';

    // ══════════════════════════════════════════════════════════════════
    // Tunables
    // ══════════════════════════════════════════════════════════════════

    var POLL_FAST = 600;        // first 30 s: the tree is small or just starting
    var POLL_MID = 1500;        // after 30 s
    var POLL_SLOW = 3000;       // after 5 min — a 600 ms poll for half an hour is
                                // thousands of requests that tell nobody anything
    var MID_AFTER_MS = 30000;
    var SLOW_AFTER_MS = 300000;

    var MAX_POLL_FAILURES = 3;  // transient blips happen; a dead server does not recover
    var TICK_MS = 1000;         // elapsed clock, independent of poll responses
    var STALL_AFTER_S = 8;

    var MAX_BARS = 40;          // a root with 900 entries must not build 900 rows
    var MAX_ERROR_SAMPLES = 12;

    // ══════════════════════════════════════════════════════════════════
    // Local helpers
    //
    // file_manager.js keeps fmtBytes/fmtInt/fmtDuration/middleTrim/byId inside
    // its IIFE — only FM, T and applyI18n reach window. Verified by reading the
    // file, not assumed. So they are reimplemented here rather than referenced.
    // ══════════════════════════════════════════════════════════════════

    var UNITS = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];

    function fmtBytes(n) {
        if (n === null || n === undefined || isNaN(n)) return '—';
        var v = Number(n), i = 0;
        while (v >= 1024 && i < UNITS.length - 1) { v /= 1024; i++; }
        return (i === 0 ? v.toFixed(0) : v.toFixed(1)) + ' ' + UNITS[i];
    }

    function fmtBytesExact(n) {
        if (n === null || n === undefined || isNaN(n)) return '—';
        return Number(n).toLocaleString('en-US') + ' B';
    }

    function fmtInt(n) {
        if (n === null || n === undefined || isNaN(n)) return '0';
        return Number(n).toLocaleString('en-US');
    }

    function fmtDuration(ms) {
        var s = Math.max(0, Math.floor(ms / 1000));
        var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
        if (h) return h + 'h ' + m + 'm ' + sec + 's';
        if (m) return m + 'm ' + sec + 's';
        return sec + 's';
    }

    function middleTrim(str, max) {
        var s = String(str === null || str === undefined ? '' : str);
        var cap = max || 60;
        if (s.length <= cap) return s;
        var keep = Math.floor((cap - 1) / 2);
        return s.slice(0, keep) + '…' + s.slice(s.length - keep);
    }

    function clamp01to100(n) {
        var v = Number(n);
        if (isNaN(v)) return 0;
        return Math.max(0, Math.min(100, v));
    }

    /** A missing element degrades to a console warning; it never throws and takes
     *  the rest of the page down with it. */
    var _warnedIds = {};
    function byId(id) {
        var el = document.getElementById(id);
        if (!el && !_warnedIds[id]) {
            _warnedIds[id] = true;
            console.warn('[fm_storage] missing element #' + id + ' — that part of the storage view will not update');
        }
        return el;
    }

    function setText(el, value) { if (el) el.textContent = value; }
    function show(el, visible) { if (el) el.hidden = !visible; }

    /**
     * Two translation layers exist on this page and they resolve different key
     * sets: file_manager.js's T() flattens the nested API dictionary and supports
     * {var} substitution, while the markup's FMI18N.t() carries bundled defaults
     * for exactly the keys the HTML uses. Trying T() first and falling back to
     * FMI18N means a key that only one of them knows still renders a sentence
     * instead of a raw dotted key.
     */
    function tr(key, vars) {
        var out = null;
        if (typeof window.T === 'function') {
            try {
                var viaT = window.T(key, vars);
                if (typeof viaT === 'string' && viaT !== key) return viaT;
            } catch (e) { /* fall through to FMI18N */ }
        }
        if (window.FMI18N && typeof window.FMI18N.t === 'function') {
            try {
                var viaI18n = window.FMI18N.t(key);
                if (typeof viaI18n === 'string' && viaI18n !== key) out = viaI18n;
            } catch (e) { /* fall through to the key */ }
        }
        if (out === null) return key;
        if (vars) {
            Object.keys(vars).forEach(function (k) {
                out = out.split('{' + k + '}').join(String(vars[k]));
            });
        }
        return out;
    }

    /** Derived from the name the server already gave us, so it never has to guess
     *  what separates path components — "\" is a legal character in a POSIX
     *  filename and guessing from the string has burned this codebase before. */
    function parentOfNamed(path, name) {
        var p = String(path || ''), n = String(name || '');
        if (!p || !n || p.length <= n.length || p.slice(-n.length) !== n) return '';
        var cut = p.slice(0, p.length - n.length);
        var last = cut.slice(-1);
        if (cut.length > 1 && (last === '/' || last === '\\')) {
            var trimmed = cut.slice(0, -1);
            // "/" and "C:\" ARE the parent; stripping their separator leaves ""
            // or "C:", neither of which names a directory.
            if (trimmed && !/^[A-Za-z]:$/.test(trimmed)) cut = trimmed;
        }
        return cut;
    }

    function toast(msg, type) {
        if (window.FM && typeof window.FM.toast === 'function') {
            window.FM.toast(msg, type);
            return;
        }
        console.warn('[fm_storage] ' + (type || 'info') + ': ' + msg);
    }

    // ══════════════════════════════════════════════════════════════════
    // Transport
    // ══════════════════════════════════════════════════════════════════

    var PREFIXES = ['/api/v1/file-manager', '/api/v1/files'];
    var _localPrefix = null;

    function apiOrigin() {
        try { return (localStorage.getItem('tubecli_api') || '').replace(/\/+$/, ''); }
        catch (e) { return ''; }
    }

    function serverMessage(data, res, rawText) {
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
        if (rawText && rawText.trim()) return middleTrim(rawText.trim(), 400);
        return 'HTTP ' + res.status + ' ' + (res.statusText || '');
    }

    /**
     * Fallback transport, used only when file_manager.js did not load. Every
     * failure carries the SERVER's own words: this project has repeatedly shipped
     * views that swallowed the reason and left a spinner turning forever.
     */
    async function localRequest(url, opts) {
        var full = apiOrigin() + url;
        var res;
        try {
            res = await fetch(full, opts || {});
        } catch (e) {
            var netErr = new Error(tr('fm.err.network') + '\n' + full + '\n(' + (e && e.message ? e.message : e) + ')');
            throw netErr;
        }
        var text = await res.text();
        var data = null, parsed = true;
        if (text) { try { data = JSON.parse(text); } catch (e) { parsed = false; } }
        if (!res.ok) {
            var err = new Error(parsed ? serverMessage(data, res, text) : middleTrim(text, 400) || ('HTTP ' + res.status));
            err.status = res.status;
            throw err;
        }
        if (!parsed) throw new Error(middleTrim(text, 400));
        if (data && typeof data === 'object' && typeof data.error === 'string' && data.error) throw new Error(data.error);
        return data;
    }

    async function localFeat(method, endpoint, body) {
        var opts = { method: method, headers: { 'Content-Type': 'application/json' } };
        if (body) opts.body = JSON.stringify(body);
        if (_localPrefix) return localRequest(_localPrefix + endpoint, opts);
        var lastErr = null;
        for (var i = 0; i < PREFIXES.length; i++) {
            try {
                var out = await localRequest(PREFIXES[i] + endpoint, opts);
                _localPrefix = PREFIXES[i];
                return out;
            } catch (e) {
                lastErr = e;
                // Only a 404/405 means "not mounted here". Anything else — including
                // no status at all, i.e. the request never landed — is the real
                // failure, and retrying the other prefix would hide it behind a
                // bogus "API not found".
                if (e.status !== 404 && e.status !== 405) throw e;
            }
        }
        throw lastErr || new Error('HTTP 404');
    }

    /** FM.feat is preferred: it shares the prefix that file_manager.js already
     *  probed, so the two halves of the page cannot disagree about the base URL. */
    function feat(method, endpoint, body) {
        if (window.FM && typeof window.FM.feat === 'function') {
            return window.FM.feat(method, endpoint, body);
        }
        return localFeat(method, endpoint, body);
    }

    function resolvedPrefix() {
        if (window.FM && window.FM._featPrefix && window.FM._featPrefix.value) return window.FM._featPrefix.value;
        return _localPrefix;
    }

    // ══════════════════════════════════════════════════════════════════
    // View state
    // ══════════════════════════════════════════════════════════════════

    var S = {
        path: '',
        id: null,
        status: 'idle',       // idle | running | done | error | cancelled
        token: 0,             // invalidates in-flight polls from a superseded run
        startedAt: 0,
        snapshot: null,
        ticker: null,
        lastFiles: -1,
        lastBytes: -1,
        lastChangeAt: 0,
        barsSig: '',
        largestSig: '',
        errorsSig: ''
    };

    // Elements created lazily because the markup has no slot for them. Both reuse
    // classes the stylesheet already defines — no new colours, no new rules.
    var _stallEl = null;
    var _errListEl = null;

    function stallEl() {
        if (_stallEl) return _stallEl;
        var anchor = byId('fm-storage-partial');
        if (!anchor || !anchor.parentNode) return null;
        _stallEl = document.createElement('p');
        _stallEl.className = 'fm-inline-warn';
        _stallEl.id = 'fm-storage-stall';
        _stallEl.hidden = true;
        anchor.parentNode.insertBefore(_stallEl, anchor);
        return _stallEl;
    }

    /** fm.usage.partial_warning promises "They are listed below". Without this
     *  list that sentence is a lie and the unreadable folders stay invisible. */
    function errListEl() {
        if (_errListEl) return _errListEl;
        var anchor = byId('fm-storage-partial');
        if (!anchor || !anchor.parentNode) return null;
        _errListEl = document.createElement('ul');
        _errListEl.className = 'fm-samples-list';
        _errListEl.id = 'fm-storage-walk-errors';
        _errListEl.hidden = true;
        anchor.parentNode.insertBefore(_errListEl, anchor.nextSibling);
        return _errListEl;
    }

    // ══════════════════════════════════════════════════════════════════
    // Rendering
    // ══════════════════════════════════════════════════════════════════

    var STATUS_KEY = {
        idle: 'fm.common.ready',
        running: 'fm.usage.status_running',
        done: 'fm.usage.status_done',
        error: 'fm.usage.status_error',
        cancelled: 'fm.usage.status_cancelled'
    };

    function setState(status) {
        S.status = status;
        var card = byId('fm-storage-progress');
        if (card) card.setAttribute('data-state', status);
        setText(byId('fm-storage-status'), tr(STATUS_KEY[status] || 'fm.common.unknown'));

        var startBtn = byId('fm-storage-start');
        var cancelBtn = byId('fm-storage-cancel');
        var running = status === 'running';
        if (startBtn) startBtn.disabled = running;
        show(cancelBtn, running);
        if (cancelBtn) cancelBtn.disabled = !running || !S.id;

        show(byId('fm-storage-cancelled-note'), status === 'cancelled');
    }

    function setProgressBar(pct, indeterminate) {
        var bar = byId('fm-storage-bar');
        if (!bar) return;
        if (indeterminate) {
            bar.classList.add('fm-progress-indeterminate');
            bar.removeAttribute('aria-valuenow');
            return;
        }
        bar.classList.remove('fm-progress-indeterminate');
        var v = clamp01to100(pct);
        bar.style.width = v + '%';
        bar.setAttribute('aria-valuenow', String(Math.round(v)));
    }

    /**
     * Runs on a 1 s timer as well as on every poll response. A single scandir
     * call can block the server for half a minute; if the elapsed clock only
     * advanced when a response arrived, the panel would sit frozen and every user
     * would conclude it had hung.
     */
    function renderTick() {
        var d = S.snapshot || {};
        var elapsed = S.startedAt ? Date.now() - S.startedAt : 0;
        var files = Number(d.scanned_files || 0);
        var dirs = d.scanned_dirs;
        var bytes = Number(d.total_bytes || 0);

        var totalEl = byId('fm-storage-total');
        setText(totalEl, S.status === 'idle' && !S.snapshot ? '' : fmtBytes(bytes));
        if (totalEl) totalEl.title = fmtBytesExact(bytes);

        setText(byId('fm-storage-files'), S.status === 'idle' && !S.snapshot ? '' : fmtInt(files));
        setText(byId('fm-storage-dirs'),
            (dirs === undefined || dirs === null) ? '' : fmtInt(dirs));

        var currentEl = byId('fm-storage-current');
        var current = d.current || (S.status === 'running' ? S.path : '');
        setText(currentEl, current ? middleTrim(current, 110) : '');
        if (currentEl) currentEl.title = current || '';

        // The percentage never stands on its own: elapsed time (and, while
        // running, throughput) prove the job is alive even when percent is stuck
        // at 0 because the walker is deep inside one enormous subtree.
        var parts = [];
        var pct = Number(d.percent);
        var haveP = !isNaN(pct) && pct > 0;
        if (haveP) {
            parts.push(S.status === 'running'
                ? tr('fm.scan_percent', { p: Math.round(pct) })
                : Math.round(pct) + '%');
        }
        if (S.startedAt) parts.push(tr('fm.scan_elapsed', { t: fmtDuration(elapsed) }));
        if (S.status === 'running' && files > 0) {
            var secs = Math.max(1, elapsed / 1000);
            parts.push(tr('fm.scan_rate', { n: fmtInt(Math.round(files / secs)) }));
        }
        var pctEl = byId('fm-storage-pct');
        setText(pctEl, parts.join('  ·  '));
        if (pctEl) pctEl.title = tr('fm.usage.scanned_files', { n: fmtInt(files) }) + ' · ' + fmtBytesExact(bytes);

        setProgressBar(haveP ? pct : 0, S.status === 'running' && !haveP);

        var stall = stallEl();
        if (stall) {
            var stalledFor = S.lastChangeAt ? Math.floor((Date.now() - S.lastChangeAt) / 1000) : 0;
            var stalled = S.status === 'running' && stalledFor >= STALL_AFTER_S;
            if (stalled) stall.textContent = tr('fm.scan_stalled', { s: stalledFor });
            stall.hidden = !stalled;
        }
    }

    function renderErrors(d) {
        var count = Number(d.error_count || 0);
        var list = Array.isArray(d.errors) ? d.errors : [];
        show(byId('fm-storage-partial'), count > 0);

        var ul = errListEl();
        if (!ul) return;
        if (!count || !list.length) { ul.hidden = true; return; }

        var sig = String(count) + '|' + list.length;
        if (sig !== S.errorsSig) {
            S.errorsSig = sig;
            ul.textContent = '';
            list.slice(0, MAX_ERROR_SAMPLES).forEach(function (item) {
                var li = document.createElement('li');
                li.textContent = (item.path || '?') + ' — ' + (item.error || '');
                li.title = (item.path || '') + '\n' + (item.error || '');
                ul.appendChild(li);
            });
            var hidden = count - Math.min(list.length, MAX_ERROR_SAMPLES);
            if (hidden > 0) {
                var more = document.createElement('li');
                more.textContent = tr('fm.cleanup_more', { n: fmtInt(hidden) });
                ul.appendChild(more);
            }
        }
        ul.hidden = false;
    }

    /** Colours come from the stylesheet's :nth-child(8n+k) rules over
     *  --fm-seg-1..8, so segments and rows only have to be appended in rank
     *  order. Nothing here picks a colour. */
    function buildBarRow() {
        var row = document.createElement('button');
        row.type = 'button';
        row.className = 'fm-bar-row';

        var swatch = document.createElement('span');
        swatch.className = 'fm-bar-swatch';
        swatch.setAttribute('aria-hidden', 'true');

        var main = document.createElement('div');
        main.className = 'fm-bar-main';
        var name = document.createElement('div');
        name.className = 'fm-bar-name';
        var track = document.createElement('div');
        track.className = 'fm-bar-track';
        var fill = document.createElement('div');
        fill.className = 'fm-bar-fill';
        track.appendChild(fill);
        main.appendChild(name);
        main.appendChild(track);

        var size = document.createElement('span');
        size.className = 'fm-bar-size';
        var pct = document.createElement('span');
        pct.className = 'fm-bar-pct';

        row.appendChild(swatch);
        row.appendChild(main);
        row.appendChild(size);
        row.appendChild(pct);
        row._fm = { name: name, fill: fill, size: size, pct: pct };
        row.addEventListener('click', function () {
            var c = row._fmChild;
            if (!c) return;
            if (c.is_dir) { startScan(c.path); return; }
            revealInFiles(parentOfNamed(c.path, c.name));
        });
        return row;
    }

    /**
     * Rows are updated in place and only added/removed on a length change.
     * A full teardown every poll would rebuild ~40 rows plus their bars several
     * times a minute for the whole scan — the reflow cost this codebase has
     * already paid for once elsewhere.
     */
    function renderChildren(d) {
        var card = byId('fm-storage-breakdown');
        var strip = byId('fm-storage-strip');
        var bars = byId('fm-storage-bars');
        var none = byId('fm-storage-no-children');
        if (!card || !bars) return;

        var all = Array.isArray(d.children) ? d.children : [];
        // Zero-byte entries carry no information in a size breakdown and would
        // render as invisible slivers that still consume a colour slot.
        var items = all.filter(function (c) { return Number(c.bytes) > 0; });
        var total = Number(d.total_bytes || 0);
        var shown = items.slice(0, MAX_BARS);

        // "There are no sub-folders with anything in them" is a claim about a
        // FINISHED walk. For the first seconds of every scan `children` is empty
        // simply because nothing has been measured yet, and asserting it then is
        // just false — so stay silent until there is something to say.
        var settled = S.status !== 'running';
        var visible = items.length > 0 || settled;

        var sig = shown.map(function (c) { return c.path + ':' + c.bytes; }).join('|') +
            '#' + total + '#' + items.length + '#' + (settled ? '1' : '0');
        if (sig === S.barsSig) { show(card, visible); return; }
        S.barsSig = sig;

        show(card, visible);
        show(none, items.length === 0 && settled);

        while (bars.children.length > shown.length) bars.removeChild(bars.lastChild);
        while (bars.children.length < shown.length) bars.appendChild(buildBarRow());
        if (strip) {
            while (strip.children.length > shown.length) strip.removeChild(strip.lastChild);
            while (strip.children.length < shown.length) {
                var seg = document.createElement('div');
                seg.className = 'fm-treemap-seg';
                strip.appendChild(seg);
            }
        }

        shown.forEach(function (c, i) {
            var pct = Number(c.percent);
            if (isNaN(pct)) pct = total > 0 ? (Number(c.bytes) / total) * 100 : 0;
            pct = clamp01to100(pct);

            var row = bars.children[i];
            if (row && row._fm) {
                row._fmChild = c;
                row._fm.name.textContent = c.name || c.path || '';
                // The fill is scaled against the TOTAL, the same number printed in
                // the percent column. Scaling to the largest child would look
                // better and make a bar drawn at full width read "38%".
                row._fm.fill.style.width = pct + '%';
                row._fm.size.textContent = fmtBytes(c.bytes);
                row._fm.pct.textContent = (pct < 0.1 && pct > 0 ? '<0.1' : pct.toFixed(1)) + '%';
                row.title = (c.path || '') + '\n' +
                    fmtBytesExact(c.bytes) + '\n' +
                    tr('fm.common.percent_of_total', { percent: pct.toFixed(1) }) + '\n' +
                    (c.is_dir ? tr('fm.scan_drill') : tr('fm.scan_reveal'));
            }
            var s = strip && strip.children[i];
            if (s) {
                s.style.width = Math.max(0.2, pct) + '%';
                s.title = (c.name || '') + ' — ' + fmtBytes(c.bytes);
            }
        });

        var extra = items.length - shown.length;
        if (none && extra > 0) {
            // The element still carries data-i18n="fm.usage.no_children", and any
            // later applyI18n() pass would stamp "there are no sub-folders" back
            // over a populated list. Dropping the attribute while we own the text
            // is what stops a flatly false sentence from reappearing.
            none.removeAttribute('data-i18n');
            none.textContent = tr('fm.cleanup_more', { n: fmtInt(extra) });
            none.hidden = false;
        } else if (none && items.length > 0) {
            none.hidden = true;
        } else if (none) {
            none.setAttribute('data-i18n', 'fm.usage.no_children');
            none.textContent = tr('fm.usage.no_children');
        }
    }

    function buildLargestRow() {
        var tr_ = document.createElement('tr');
        var nameTd = document.createElement('td');
        var link = document.createElement('button');
        link.type = 'button';
        link.className = 'fm-link-btn';
        nameTd.appendChild(link);
        var sizeTd = document.createElement('td');
        sizeTd.className = 'fm-num';
        var modTd = document.createElement('td');
        var pathTd = document.createElement('td');
        pathTd.className = 'fm-cell-path';
        tr_.appendChild(nameTd);
        tr_.appendChild(sizeTd);
        tr_.appendChild(modTd);
        tr_.appendChild(pathTd);
        tr_._fm = { link: link, size: sizeTd, mod: modTd, path: pathTd };
        link.addEventListener('click', function () {
            var f = tr_._fmFile;
            if (f) revealInFiles(parentOfNamed(f.path, f.name));
        });
        return tr_;
    }

    function renderLargest(d) {
        var card = byId('fm-storage-largest');
        var body = byId('fm-storage-largest-body');
        var none = byId('fm-storage-no-largest');
        if (!card || !body) return;

        var files = Array.isArray(d.largest) ? d.largest : [];
        // Same reasoning as renderChildren: "No files were found" is only true of
        // a walk that has stopped looking.
        var settled = S.status !== 'running';
        var visible = files.length > 0 || settled;

        var sig = files.map(function (f) { return f.path + ':' + f.bytes; }).join('|') +
            '#' + (settled ? '1' : '0');
        if (sig === S.largestSig) { show(card, visible); return; }
        S.largestSig = sig;

        show(card, visible);
        show(none, files.length === 0 && settled);

        while (body.children.length > files.length) body.removeChild(body.lastChild);
        while (body.children.length < files.length) body.appendChild(buildLargestRow());

        files.forEach(function (f, i) {
            var row = body.children[i];
            if (!row || !row._fm) return;
            row._fmFile = f;
            row._fm.link.textContent = f.name || f.path || '';
            row._fm.link.title = tr('fm.usage.open_in_files');
            row._fm.size.textContent = fmtBytes(f.bytes);
            row._fm.size.title = fmtBytesExact(f.bytes);
            row._fm.mod.textContent = f.modified || '—';
            row._fm.path.textContent = middleTrim(f.path || '', 70);
            row._fm.path.title = f.path || '';
        });
    }

    /** Called on EVERY poll, not only on completion — see the file header. */
    function renderSnapshot(d) {
        var files = Number(d.scanned_files || 0);
        var bytes = Number(d.total_bytes || 0);
        if (files !== S.lastFiles || bytes !== S.lastBytes) {
            S.lastFiles = files;
            S.lastBytes = bytes;
            S.lastChangeAt = Date.now();
        }
        S.snapshot = d;
        renderTick();
        renderErrors(d);
        renderChildren(d);
        renderLargest(d);
    }

    function showFailure(msg) {
        setState('error');
        stopTicker();
        setProgressBar(0, false);
        var el = byId('fm-storage-error');
        if (el) {
            el.textContent = tr('fm.usage.error_prefix') + ' ' + msg;
            el.hidden = false;
        }
        // Standard: never fail silently. If the inline slot is gone the reason
        // still has to reach the user somehow.
        if (!el) toast(msg, 'error');
        // Whatever was measured before the failure is now final, so re-render it
        // as a settled result rather than leaving it dressed as work in progress.
        if (S.snapshot) renderSnapshot(S.snapshot);
    }

    function clearFailure() {
        var el = byId('fm-storage-error');
        if (el) { el.textContent = ''; el.hidden = true; }
    }

    function revealInFiles(path) {
        if (!path) return;
        if (window.FM && typeof window.FM.navigate === 'function') {
            window.FM.navigate(path);
        }
        // Switching views belongs to the tab handler, so trigger its own button
        // rather than duplicating (and eventually diverging from) its logic.
        var tab = document.querySelector('[data-fm-action="view"][data-fm-view="files"]');
        if (tab) tab.click();
    }

    // ══════════════════════════════════════════════════════════════════
    // Scan lifecycle
    // ══════════════════════════════════════════════════════════════════

    function stopTicker() {
        if (S.ticker) { clearInterval(S.ticker); S.ticker = null; }
    }

    function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

    function targetPath(explicit) {
        if (explicit) return explicit;
        if (window.FM) return window.FM.selectedItem || window.FM.currentPath || '';
        return '';
    }

    async function startScan(explicitPath) {
        var path = targetPath(explicitPath);
        if (!path) { toast(tr('fm.common.choose_folder'), 'warn'); return; }

        // Drilling into a bar row (or any FMStorage.scan call) can land while a
        // walk is still running. Bumping the token only orphans OUR poll loop —
        // the server would keep walking the old tree forever. Release it first.
        if (S.id && S.status === 'running') {
            var stale = S.id;
            feat('POST', '/usage/scan/' + encodeURIComponent(stale) + '/cancel', {})
                .catch(function (e) {
                    console.warn('[fm_storage] could not cancel superseded scan ' + stale + ': ' +
                        (e && e.message ? e.message : e));
                });
        }

        S.token++;
        var token = S.token;
        S.path = path;
        S.id = null;
        S.startedAt = Date.now();
        S.lastChangeAt = Date.now();
        S.lastFiles = -1;
        S.lastBytes = -1;
        S.snapshot = null;
        // Forces a redraw of the previous run's rows instead of leaving them on
        // screen because the new signature happens to match.
        S.barsSig = S.largestSig = S.errorsSig = '\u0000';

        clearFailure();
        show(byId('fm-storage-empty'), false);
        show(byId('fm-storage-partial'), false);
        if (_errListEl) _errListEl.hidden = true;
        setState('running');

        // On the pill, not the card: a title on the card would follow the pointer
        // across every metric and bury the per-value tooltips underneath it.
        var pill = byId('fm-storage-status');
        if (pill) pill.title = tr('fm.scan_for', { path: path });

        stopTicker();
        S.ticker = setInterval(renderTick, TICK_MS);
        renderTick();   // paint the zero state now; a blank half-second reads as a hang

        var res;
        try {
            res = await feat('POST', '/usage/scan', { path: path });
        } catch (e) {
            if (S.token !== token) return;
            showFailure(e && e.message ? e.message : String(e));
            return;
        }
        if (S.token !== token) return;

        if (!res || !res.scan_id) {
            showFailure(tr('fm.err.scan_failed', {
                message: 'scan_id: ' + middleTrim(JSON.stringify(res), 200)
            }));
            return;
        }
        S.id = res.scan_id;
        var cancelBtn = byId('fm-storage-cancel');
        if (cancelBtn) cancelBtn.disabled = false;
        pollScan(token);
    }

    async function pollScan(token) {
        var failures = 0;
        var interval = POLL_FAST;

        while (S.token === token && S.status === 'running') {
            var data;
            try {
                data = await feat('GET', '/usage/scan/' + encodeURIComponent(S.id));
                failures = 0;
            } catch (e) {
                if (S.token !== token) return;
                var msg = e && e.message ? e.message : String(e);
                if (e && e.status === 404) {
                    // The id expired or the server restarted. Retrying can never
                    // recover it, so say so now instead of after three silent tries.
                    showFailure(tr('fm.usage.expired') + '\n' + msg);
                    return;
                }
                failures++;
                if (failures >= MAX_POLL_FAILURES) {
                    showFailure(tr('fm.scan_poll_failed', { n: failures, msg: msg }));
                    return;
                }
                await sleep(interval);
                continue;
            }
            if (S.token !== token) return;

            var terminal = data.status === 'done' || data.status === 'error' || data.status === 'cancelled';

            // State is committed BEFORE the render, because the renderers ask
            // S.status whether the walk has stopped looking — that is what decides
            // if an empty list means "nothing there" or "not measured yet".
            if (terminal) {
                stopTicker();
                setState(data.status);
            }

            renderSnapshot(data);

            if (terminal) {
                if (data.status === 'error') {
                    // The breakdown rendered above stays on screen: partial numbers
                    // beat none, as long as the failure is stated next to them.
                    showFailure(data.error || tr('fm.usage.status_error'));
                } else if (data.status === 'done') {
                    setProgressBar(100, false);
                } else {
                    setProgressBar(Number(data.percent) || 0, false);
                }
                return;
            }

            var age = Date.now() - S.startedAt;
            interval = age > SLOW_AFTER_MS ? POLL_SLOW : (age > MID_AFTER_MS ? POLL_MID : POLL_FAST);
            await sleep(interval);
        }
    }

    async function cancelScan() {
        if (!S.id || S.status !== 'running') return;
        var btn = byId('fm-storage-cancel');
        if (btn) btn.disabled = true;
        try {
            await feat('POST', '/usage/scan/' + encodeURIComponent(S.id) + '/cancel', {});
        } catch (e) {
            if (btn) btn.disabled = false;
            toast(tr('fm.scan_cancel_failed', { msg: e && e.message ? e.message : String(e) }), 'error');
            return;
        }
        // The poll loop observes status "cancelled" on its next tick, but the
        // button must not stay pressed-but-alive for up to three seconds.
        S.token++;
        stopTicker();
        setState('cancelled');
        if (S.snapshot) renderSnapshot(S.snapshot); else renderTick();
    }

    /** A walk abandoned by a closing tab keeps burning server I/O with nobody
     *  watching, so hand the server a cancel on the way out. */
    function abandonOnUnload() {
        if (!S.id || S.status !== 'running') return;
        var prefix = resolvedPrefix();
        if (!prefix) return;
        var url = apiOrigin() + prefix + '/usage/scan/' + encodeURIComponent(S.id) + '/cancel';
        try {
            if (navigator.sendBeacon) {
                navigator.sendBeacon(url, new Blob(['{}'], { type: 'application/json' }));
                return;
            }
            fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}', keepalive: true });
        } catch (e) {
            // Nothing can be reported from a page that is going away.
        }
    }

    // ══════════════════════════════════════════════════════════════════
    // Registration
    // ══════════════════════════════════════════════════════════════════

    var HANDLERS = {
        'storage-scan': function () { startScan(); },
        'storage-cancel': function () { cancelScan(); }
    };

    /**
     * Script order must not decide whether a button works. If the router has not
     * been parsed yet, retry briefly rather than dropping the handlers — and clear
     * `pending` BEFORE calling register(), so a duplicate-name error thrown by the
     * router is never retried into a second registration.
     */
    var pending = HANDLERS;
    var attempts = 0;

    function flushRegistration() {
        if (!pending) return true;
        var A = window.FMActions;
        if (!A || typeof A.register !== 'function') return false;
        var handlers = pending;
        pending = null;
        A.register(handlers, 'fm_storage');
        return true;
    }

    function retryRegistration() {
        if (flushRegistration()) return;
        if (++attempts > 100) {          // ~5 s: the router is genuinely absent
            console.error('[fm_storage] FMActions.register() never appeared — ' +
                'the storage scan and stop buttons are inert.');
            return;
        }
        setTimeout(retryRegistration, 50);
    }

    window.FMActions = window.FMActions || {};
    retryRegistration();

    // Public entry point for the other modules' "analyse this folder" affordances
    // (data-fm-action="analyze" / "scan-selected"), which are owned elsewhere.
    window.FMStorage = {
        scan: function (path) { startScan(path); },
        cancel: cancelScan,
        get state() { return S.status; }
    };

    // Generated text is written by tr() at render time, so a late-arriving
    // dictionary would leave the idle panel in the bootstrap language.
    document.addEventListener('fm:i18n-ready', function () {
        setState(S.status);
        renderTick();
        if (S.snapshot) {
            S.barsSig = S.largestSig = S.errorsSig = '\u0000';
            renderSnapshot(S.snapshot);
        }
    });

    window.addEventListener('pagehide', abandonOnUnload);
})();
