/**
 * fm_cleanup.js — behaviour for the Cleanup view (#fm-view-cleanup).
 *
 * WHY this file exists at all: file_manager.js was written against the previous
 * markup and drives everything through modals it builds itself. The rebuilt page
 * is inline and id-based, so its 52 data-fm-action hooks had nothing listening.
 * Rather than rewrite that file (four modules are being attached in parallel),
 * this one binds the cleanup ids and registers its buttons with the shared
 * FMActions router.
 *
 * WHY it re-implements byte/duration formatting, toasts and the i18n lookup:
 * file_manager.js keeps fmtBytes, toast, requestJson and friends inside its IIFE
 * and exports only window.FM, window.T and window.applyI18n (verified at the
 * bottom of that file). Calling the unexported names would throw on the first
 * click. window.FM.feat IS a method on the exported object, so the two API calls
 * go through it and inherit its prefix probing and its "throw the server's own
 * message" contract.
 *
 * The order of the flow is a safety property, not a UX preference:
 *   scan -> select -> dry run -> typed confirmation -> apply
 * Apply refuses to run unless a dry run for THIS exact selection was returned by
 * the server and shown on screen. Any change to the selection throws the preview
 * away, because a confirmation that describes a different set of files than the
 * one being deleted is worse than no confirmation at all.
 */
(function () {
    'use strict';

    var LOG = '[fm_cleanup]';

    // Rows are capped so a preview of a 200k-file node_modules tree cannot lock
    // the tab building DOM. The count in the metrics row is always the real one.
    var DELETED_ROW_CAP = 500;
    var FAILED_ROW_CAP = 200;
    var SAMPLE_CAP = 12;

    // ══════════════════════════════════════════════════════════════════
    // i18n
    // ══════════════════════════════════════════════════════════════════

    var _warnedKeys = {};

    /**
     * Two translators exist on this page: window.FMI18N (declared inline in
     * file_manager.html, carries bundled defaults so no raw key is ever painted)
     * and window.T (file_manager.js). FMI18N is asked first because it is the
     * one shipped with this markup; neither substitutes {vars}, so that is done
     * here after the lookup.
     */
    function t(key, vars) {
        var s = null;
        var i18n = window.FMI18N;
        if (i18n && typeof i18n.t === 'function') {
            var a = i18n.t(key);
            if (typeof a === 'string' && a && a !== key) s = a;
        }
        if (s === null && typeof window.T === 'function') {
            var b = window.T(key);
            if (typeof b === 'string' && b && b !== key) s = b;
        }
        if (s === null) {
            if (!_warnedKeys[key]) {
                _warnedKeys[key] = true;
                console.warn(LOG, 'no translation for key:', key);
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
    // Formatting
    // ══════════════════════════════════════════════════════════════════

    var UNITS = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];

    function fmtBytes(n) {
        if (n === null || n === undefined || isNaN(n)) return '—';
        var v = Number(n), i = 0;
        while (v >= 1024 && i < UNITS.length - 1) { v /= 1024; i++; }
        return (i === 0 ? v.toFixed(0) : v.toFixed(1)) + ' ' + UNITS[i];
    }

    /** The exact figure, for the title attribute: "1.2 GB" hides 300 MB. */
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
        var cap = max || 200;
        if (s.length <= cap) return s;
        var keep = Math.floor((cap - 1) / 2);
        return s.slice(0, keep) + '…' + s.slice(s.length - keep);
    }

    // ══════════════════════════════════════════════════════════════════
    // DOM
    // ══════════════════════════════════════════════════════════════════

    var _warnedIds = {};

    /** Never throws on a missing node: one absent id must not kill the view. */
    function byId(id) {
        var node = document.getElementById(id);
        if (!node && !_warnedIds[id]) {
            _warnedIds[id] = true;
            console.warn(LOG, 'element #' + id + ' is missing from the page — ' +
                'that part of the cleanup view cannot update.');
        }
        return node;
    }

    /** Every text value goes through textContent: a filename is never markup. */
    function el(tag, attrs, children) {
        var node = document.createElement(tag);
        if (attrs) {
            Object.keys(attrs).forEach(function (k) {
                var v = attrs[k];
                if (v === null || v === undefined || v === false) return;
                if (k === 'class') node.className = v;
                else if (k === 'text') node.textContent = v;
                else if (k === 'html') throw new Error('fm_cleanup: raw html is not allowed');
                else node.setAttribute(k, v);
            });
        }
        (Array.isArray(children) ? children : (children ? [children] : [])).forEach(function (c) {
            if (c === null || c === undefined || c === false) return;
            node.appendChild(c.nodeType ? c : document.createTextNode(String(c)));
        });
        return node;
    }

    function icon(id) {
        var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.setAttribute('class', 'fm-ico');
        svg.setAttribute('aria-hidden', 'true');
        var use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
        use.setAttribute('href', '#' + id);
        svg.appendChild(use);
        return svg;
    }

    function clearNode(node) {
        while (node && node.firstChild) node.removeChild(node.firstChild);
    }

    function setHidden(node, hidden) {
        if (node) node.hidden = !!hidden;
    }

    function setDisabled(node, disabled) {
        if (node) node.disabled = !!disabled;
    }

    /**
     * Buttons in this markup are <svg> + <span data-i18n="…">. `sticky` drops the
     * data-i18n attribute so a later i18n pass cannot repaint the original label
     * over a state this module now owns (Scan -> Scan again).
     */
    function btnLabel(btn, text, sticky) {
        if (!btn) return;
        var span = btn.querySelector('span');
        if (!span) { btn.textContent = text; return; }
        if (sticky) span.removeAttribute('data-i18n');
        span.textContent = text;
    }

    function scrollTo(node) {
        if (!node) return;
        try {
            node.scrollIntoView({ behavior: 'smooth', block: 'start' });
        } catch (e) {
            // Older engines reject the options object; position is cosmetic.
            try { node.scrollIntoView(); } catch (e2) { /* nothing to do */ }
        }
    }

    // ══════════════════════════════════════════════════════════════════
    // Toast — matches the .fm-toast markup the rebuilt stylesheet expects
    // ══════════════════════════════════════════════════════════════════

    var TOAST_ICON = { success: 'i-check-circle', error: 'i-x-circle', warn: 'i-alert', info: 'i-info' };

    function toast(msg, kind) {
        var type = TOAST_ICON[kind] ? kind : 'info';
        var host = document.getElementById('toastContainer');
        if (!host) {
            // Without a host the message would vanish; the console is the last
            // place it can still be read.
            console.warn(LOG, '#toastContainer is missing. Message:', msg);
            return;
        }
        var node = el('div', { class: 'fm-toast ' + type }, [
            icon(TOAST_ICON[type]),
            el('span', { text: String(msg) })
        ]);
        host.appendChild(node);
        // Errors stay longer: a server refusal is several lines and unreadable
        // in three seconds.
        var life = (type === 'error' || type === 'warn') ? 9000 : 4500;
        var kill = function () {
            if (!node.parentNode) return;
            node.classList.add('is-leaving');
            setTimeout(function () { if (node.parentNode) node.parentNode.removeChild(node); }, 260);
        };
        node.addEventListener('click', kill);
        setTimeout(kill, life);
    }

    // ══════════════════════════════════════════════════════════════════
    // API
    // ══════════════════════════════════════════════════════════════════

    /**
     * FM.feat resolves /api/v1/file-manager vs /api/v1/files once, checks
     * response.ok, and throws carrying the server's own detail — the whole
     * reason this module does not fetch directly.
     */
    function call(method, endpoint, body, signal) {
        var fm = window.FM;
        if (!fm || typeof fm.feat !== 'function') {
            return Promise.reject(new Error(t('fm.err.generic', {
                message: 'window.FM.feat is unavailable — file_manager.js did not load.'
            })));
        }
        return fm.feat(method, endpoint, body, signal);
    }

    /** The folder the browse view is standing in; there is no path box here. */
    function currentPath() {
        var fm = window.FM;
        if (fm && typeof fm.currentPath === 'string' && fm.currentPath) return fm.currentPath;
        return '';
    }

    // ══════════════════════════════════════════════════════════════════
    // State
    // ══════════════════════════════════════════════════════════════════

    var S = {
        path: '',            // the folder that was scanned — never re-read from FM
        categories: [],      // as returned, minus the empty ones
        selected: {},        // id -> category
        scanning: false,
        busy: false,         // a dry run or a real delete is in flight
        started: 0,
        timer: null,
        token: 0,            // supersedes the answer of an abandoned scan
        controller: null,
        dry: null            // {sig, ids, planned, freed, failed} — the licence to delete
    };

    /**
     * Identifies exactly which files a preview described. Apply compares this
     * against the live selection and refuses on any difference.
     */
    function selectionSignature() {
        return S.path + ' ' + Object.keys(S.selected).sort().join(',');
    }

    function selectionTotals() {
        var ids = Object.keys(S.selected), bytes = 0, count = 0, review = false;
        ids.forEach(function (id) {
            var c = S.selected[id];
            bytes += Number(c.bytes || 0);
            count += Number(c.count || 0);
            if (c.risk === 'review') review = true;
        });
        return { ids: ids, bytes: bytes, count: count, review: review };
    }

    // ══════════════════════════════════════════════════════════════════
    // Inline error line
    // ══════════════════════════════════════════════════════════════════

    /**
     * `kind` picks between the two classes the stylesheet defines on purpose:
     * "the numbers above are incomplete" must not be painted the same red as
     * "the operation failed".
     */
    function showNotice(msg, kind) {
        var text = Array.isArray(msg) ? msg.filter(Boolean).join('\n') : String(msg);
        var node = byId('fm-cleanup-error');
        if (!node) { console.error(LOG, text); return; }
        node.className = kind === 'warn' ? 'fm-inline-warn' : 'fm-inline-error';
        // A server refusal is several lines (the ValueError lists the allowed
        // roots); collapsed into one they run together and the actionable half
        // is the half that gets lost.
        node.style.whiteSpace = 'pre-line';
        node.textContent = text;
        node.hidden = false;
    }

    function showError(msg) { showNotice(msg, 'error'); }

    function clearError() {
        var node = byId('fm-cleanup-error');
        if (node) { node.textContent = ''; node.hidden = true; }
    }

    // ══════════════════════════════════════════════════════════════════
    // Progress card
    // ══════════════════════════════════════════════════════════════════

    function setProgressState(name) {
        var card = byId('fm-cleanup-progress');
        if (card) { card.hidden = false; card.setAttribute('data-state', name); }
    }

    function setStatusPill(key) {
        var pill = byId('fm-cleanup-status');
        if (!pill) return;
        // The markup pins this pill to fm.clean.scanning with data-i18n. Left in
        // place, the next i18n pass would repaint "Scanning…" over a finished or
        // failed scan.
        pill.removeAttribute('data-i18n');
        pill.textContent = t(key);
    }

    function setCurrentLine(text) {
        var node = byId('fm-cleanup-current');
        if (node) { node.textContent = text; node.title = text; }
    }

    /**
     * GET /cleanup/scan is one blocking request with no progress channel, so
     * elapsed time is the only true number there is. A bare bar with no figure
     * is indistinguishable from a hung one.
     */
    function tickElapsed() {
        var pct = byId('fm-cleanup-pct');
        if (pct) pct.textContent = fmtDuration(Date.now() - S.started);
    }

    function stopTicker() {
        if (S.timer) { clearInterval(S.timer); S.timer = null; }
    }

    // ══════════════════════════════════════════════════════════════════
    // Category cards
    // ══════════════════════════════════════════════════════════════════

    function riskPill(risk) {
        if (risk === 'safe') {
            return el('span', { class: 'fm-risk fm-risk-safe', title: t('fm.risk.safe_desc'), text: t('fm.risk.safe') });
        }
        if (risk === 'review') {
            return el('span', { class: 'fm-risk fm-risk-review', title: t('fm.risk.review_desc'), text: t('fm.risk.review') });
        }
        // An unknown risk is never dressed up as safe.
        return el('span', { class: 'fm-risk', text: t('fm.cleanup_risk_unknown') });
    }

    function samplesBlock(cat) {
        var samples = Array.isArray(cat.samples) ? cat.samples : [];
        if (!samples.length) return null;
        var list = el('ul', { class: 'fm-samples-list' });
        var shown = Math.min(samples.length, SAMPLE_CAP);
        for (var i = 0; i < shown; i++) {
            var s = String(samples[i]);
            list.appendChild(el('li', { title: s, text: s }));
        }
        var block = el('div', { class: 'fm-samples' }, [
            el('div', { class: 'fm-samples-title', text: t('fm.clean.samples') }),
            list
        ]);
        if (samples.length > shown) {
            block.appendChild(el('div', {
                class: 'fm-cat-count',
                text: t('fm.clean.samples_more', { n: fmtInt(samples.length - shown) })
            }));
        }
        return block;
    }

    function categoryCard(cat, index) {
        var inputId = 'fm-cat-' + index;
        var checkbox = el('input', { type: 'checkbox', id: inputId });
        checkbox.addEventListener('change', function () {
            if (checkbox.checked) S.selected[cat.id] = cat;
            else delete S.selected[cat.id];
            onSelectionChanged();
        });

        var card = el('div', { class: 'fm-cat-card' }, [
            el('div', { class: 'fm-cat-head' }, [
                el('label', { class: 'fm-check' }, [checkbox, el('span', { 'aria-hidden': 'true' })]),
                // The server's own label, not a locale copy: the description it
                // ships carries per-scan warnings (truncated walk, duplicate
                // hashing limits) that a static string cannot, and a locale key
                // that drifts would mislabel a destructive category.
                el('label', { class: 'fm-cat-title', for: inputId, text: String(cat.label || cat.id) }),
                riskPill(cat.risk)
            ]),
            el('div', { class: 'fm-cat-stats' }, [
                el('span', {
                    class: 'fm-cat-bytes',
                    title: fmtBytesExact(cat.bytes),
                    text: fmtBytes(cat.bytes)
                }),
                el('span', {
                    class: 'fm-cat-count',
                    text: t('fm.common.items', { n: fmtInt(cat.count) })
                })
            ]),
            cat.description ? el('p', { class: 'fm-cat-desc', text: String(cat.description) }) : null,
            samplesBlock(cat)
        ]);
        // Nothing is ticked by default. Duplicates in particular are
        // byte-identical yet load-bearing (locale packs, render frame
        // sequences), so a pre-selected box would invite a destructive click.
        return card;
    }

    function renderCategories() {
        var grid = byId('fm-cleanup-categories');
        if (grid) clearNode(grid);

        var usable = S.categories;
        setHidden(byId('fm-cleanup-nothing'), usable.length > 0);
        setHidden(byId('fm-cleanup-empty'), true);

        if (!usable.length) {
            setHidden(byId('fm-cleanup-select-safe'), true);
            return;
        }
        if (grid) {
            usable.forEach(function (cat, i) { grid.appendChild(categoryCard(cat, i)); });
        }
        var anySafe = usable.some(function (c) { return c.risk === 'safe'; });
        setHidden(byId('fm-cleanup-select-safe'), !anySafe);
    }

    // ══════════════════════════════════════════════════════════════════
    // Selection bar
    // ══════════════════════════════════════════════════════════════════

    function onSelectionChanged() {
        // A preview describes one exact set of files. The moment the set moves,
        // the preview is a lie and the route to delete has to close.
        if (S.dry && S.dry.sig !== selectionSignature()) invalidateDry();
        updateSelectionBar();
    }

    function updateSelectionBar() {
        var totals = selectionTotals();
        var bar = byId('fm-cleanup-selbar');
        var summary = byId('fm-cleanup-sel-summary');
        setHidden(bar, totals.ids.length === 0);
        if (summary) {
            summary.textContent = totals.ids.length
                ? t('fm.clean.selected_total', { count: fmtInt(totals.count), size: fmtBytes(totals.bytes) })
                : '';
            summary.title = totals.ids.length ? fmtBytesExact(totals.bytes) : '';
        }
        setDisabled(byId('fm-cleanup-dry'), totals.ids.length === 0 || S.busy);
    }

    function invalidateDry() {
        S.dry = null;
        setHidden(byId('fm-cleanup-dryrun'), true);
        hideConfirm();
    }

    function hideConfirm() {
        setHidden(byId('fm-cleanup-confirm'), true);
        var input = byId('fm-cleanup-confirm-input');
        if (input) input.value = '';
        setHidden(byId('fm-cleanup-confirm-error'), true);
        setDisabled(byId('fm-cleanup-apply'), true);
    }

    // ══════════════════════════════════════════════════════════════════
    // Result card (used for both the preview and the real run)
    // ══════════════════════════════════════════════════════════════════

    /** Notes and walk errors the server sends have no slot in the markup, and
     *  dropping them would hide "the scan never finished the tree". */
    function notesHost() {
        var card = byId('fm-cleanup-dryrun');
        if (!card) return null;
        var host = card.querySelector('[data-fm-notes]');
        if (!host) {
            host = el('div', { 'data-fm-notes': '' });
            card.insertBefore(host, card.querySelector('.fm-table-wrap'));
        }
        clearNode(host);
        return host;
    }

    function renderNotes(res) {
        var host = notesHost();
        if (!host) return;
        host.appendChild(el('p', {
            class: 'fm-perm-note fm-mono fm-ellipsis',
            title: S.path,
            text: t('fm.scan_for', { path: S.path })
        }));
        var notes = Array.isArray(res.notes) ? res.notes : [];
        notes.forEach(function (n) {
            if (typeof n === 'string' && n.trim()) {
                host.appendChild(el('p', { class: 'fm-perm-note', text: n }));
            }
        });
        var errors = Array.isArray(res.errors) ? res.errors : [];
        if (errors.length) {
            host.appendChild(el('p', {
                class: 'fm-perm-note',
                text: t('fm.err.walk_partial', { n: fmtInt(errors.length) })
            }));
            errors.slice(0, 20).forEach(function (e) {
                var line = typeof e === 'string' ? e
                    : ((e && e.path ? e.path + ' — ' : '') + (e && e.error ? e.error : JSON.stringify(e)));
                host.appendChild(el('p', { class: 'fm-perm-note fm-mono', text: middleTrim(line, 300) }));
            });
        }
    }

    /**
     * `mode` is 'preview' or 'result'. After a real delete the badge must stop
     * saying "nothing was deleted" — a green light over work that did happen is
     * the same class of lie as one over work that did not.
     */
    function setCardMode(mode, summaryText) {
        var card = byId('fm-cleanup-dryrun');
        if (!card) return;
        var badge = card.querySelector('.fm-step-badge');
        var desc = card.querySelector('.fm-card-desc');
        var goto = card.querySelector('[data-fm-action="cleanup-goto-confirm"]');
        if (badge) {
            badge.removeAttribute('data-i18n');
            badge.classList.toggle('fm-step-badge-danger', mode === 'result');
            badge.textContent = mode === 'result' ? t('fm.clean.deleted') : t('fm.clean.dry_run_badge');
        }
        if (desc) {
            desc.removeAttribute('data-i18n');
            desc.textContent = mode === 'result' ? String(summaryText || '') : t('fm.clean.dry_run_note');
        }
        // The plan is spent once it has run; there is nothing left to confirm.
        setHidden(goto, mode === 'result');
    }

    function renderMetrics(res, deleted, failed) {
        var freed = byId('fm-dry-freed');
        if (freed) {
            freed.textContent = fmtBytes(res.freed);
            freed.title = fmtBytesExact(res.freed);
        }
        var count = byId('fm-dry-count');
        if (count) count.textContent = fmtInt(deleted.length);
        var failedEl = byId('fm-dry-failed');
        if (failedEl) failedEl.textContent = fmtInt(failed.length);
    }

    function renderDeletedRows(deleted) {
        var body = byId('fm-dry-body');
        if (!body) return;
        clearNode(body);
        var shown = Math.min(deleted.length, DELETED_ROW_CAP);
        for (var i = 0; i < shown; i++) {
            var d = deleted[i] || {};
            var path = String(d.path === undefined ? d : d.path);
            var bytes = Number(d.bytes || 0);
            // The server reports 0 bytes with a note when the name is gone but a
            // process still holds the file open, so the size cell carries it.
            var sizeCell = el('td', {
                class: 'fm-num',
                title: d.note ? String(d.note) : fmtBytesExact(bytes),
                text: fmtBytes(bytes)
            });
            body.appendChild(el('tr', {}, [
                el('td', { class: 'fm-cell-path', title: path, text: path }),
                sizeCell
            ]));
        }
        if (deleted.length > shown) {
            body.appendChild(el('tr', {}, [
                el('td', { colspan: '2', class: 'fm-muted', text: t('fm.cleanup_more', { n: fmtInt(deleted.length - shown) }) })
            ]));
        }
    }

    function renderFailedRows(failed) {
        var block = byId('fm-dry-failed-block');
        var body = byId('fm-dry-failed-body');
        setHidden(block, failed.length === 0);
        if (!body) return;
        clearNode(body);
        var shown = Math.min(failed.length, FAILED_ROW_CAP);
        for (var i = 0; i < shown; i++) {
            var f = failed[i] || {};
            var path = String(f.path === undefined ? f : f.path);
            // Every failure names its reason. "Some items were skipped" with no
            // cause is the bug this project keeps paying for.
            var reason = f.error ? String(f.error) : t('fm.common.unknown');
            body.appendChild(el('tr', {}, [
                el('td', { class: 'fm-cell-path', title: path, text: path }),
                el('td', { title: reason, text: reason })
            ]));
        }
        if (failed.length > shown) {
            body.appendChild(el('tr', {}, [
                el('td', { colspan: '2', class: 'fm-muted', text: t('fm.cleanup_more', { n: fmtInt(failed.length - shown) }) })
            ]));
        }
    }

    // ══════════════════════════════════════════════════════════════════
    // Busy state
    // ══════════════════════════════════════════════════════════════════

    function setBusy(busy) {
        S.busy = !!busy;
        setDisabled(byId('fm-cleanup-scan'), busy || S.scanning);
        setDisabled(byId('fm-cleanup-select-safe'), busy);
        setDisabled(byId('fm-cleanup-dry'), busy || Object.keys(S.selected).length === 0);
        var card = byId('fm-cleanup-dryrun');
        var goto = card ? card.querySelector('[data-fm-action="cleanup-goto-confirm"]') : null;
        setDisabled(goto, busy);
    }

    // ══════════════════════════════════════════════════════════════════
    // Action: scan
    // ══════════════════════════════════════════════════════════════════

    async function actScan() {
        if (S.scanning || S.busy) return;

        var target = currentPath();
        if (!target) {
            showError(t('fm.common.choose_folder'));
            toast(t('fm.common.choose_folder'), 'warn');
            return;
        }

        // A new scan invalidates everything the old one licensed.
        var token = ++S.token;
        if (S.controller) { try { S.controller.abort(); } catch (e) { /* already done */ } }
        S.controller = (typeof AbortController !== 'undefined') ? new AbortController() : null;
        S.scanning = true;
        S.path = target;
        S.categories = [];
        S.selected = {};
        S.dry = null;

        clearError();
        setHidden(byId('fm-cleanup-dryrun'), true);
        hideConfirm();
        setHidden(byId('fm-cleanup-selbar'), true);
        setHidden(byId('fm-cleanup-select-safe'), true);
        setHidden(byId('fm-cleanup-nothing'), true);
        setHidden(byId('fm-cleanup-empty'), true);
        var grid = byId('fm-cleanup-categories');
        if (grid) clearNode(grid);

        S.started = Date.now();
        setProgressState('running');
        setStatusPill('fm.clean.scanning');
        setCurrentLine(t('fm.scan_for', { path: target }));
        tickElapsed();
        stopTicker();
        S.timer = setInterval(tickElapsed, 1000);
        setBusy(false);
        setDisabled(byId('fm-cleanup-scan'), true);

        var data;
        try {
            data = await call('GET', '/cleanup/scan?path=' + encodeURIComponent(target), null,
                S.controller ? S.controller.signal : undefined);
        } catch (e) {
            if (token !== S.token) return;          // superseded — its own run reports
            stopTicker();
            tickElapsed();
            S.scanning = false;
            setDisabled(byId('fm-cleanup-scan'), false);
            if (e && e.aborted) {
                setProgressState('cancelled');
                setStatusPill('fm.usage.status_cancelled');
                return;
            }
            setProgressState('error');
            setStatusPill('fm.scan_error');
            showError(e && e.message ? e.message : String(e));
            toast(e && e.message ? e.message : String(e), 'error');
            setHidden(byId('fm-cleanup-empty'), false);
            return;
        }
        if (token !== S.token) return;

        stopTicker();
        tickElapsed();
        S.scanning = false;
        setDisabled(byId('fm-cleanup-scan'), false);

        var list = data && data.categories;
        if (!Array.isArray(list)) {
            setProgressState('error');
            setStatusPill('fm.scan_error');
            var shapeMsg = t('fm.err_shape', {
                field: 'categories',
                got: middleTrim(JSON.stringify(data), 200)
            });
            showError(shapeMsg);
            toast(shapeMsg, 'error');
            return;
        }

        // The backend returns every known category, including the ones with
        // nothing in them. A card offering to delete 0 items is noise that
        // buries the one category actually worth 4 GB.
        S.categories = list.filter(function (c) {
            return c && Number(c.count || 0) > 0;
        }).sort(function (a, b) {
            return Number(b.bytes || 0) - Number(a.bytes || 0);
        });

        setProgressState('done');
        setStatusPill('fm.scan_done');
        renderCategories();
        updateSelectionBar();
        btnLabel(byId('fm-cleanup-scan'), t('fm.clean.rescan'), true);

        if (!S.categories.length) toast(t('fm.clean.nothing'), 'info');
    }

    // ══════════════════════════════════════════════════════════════════
    // Actions: selection
    // ══════════════════════════════════════════════════════════════════

    function actSelectSafe() {
        if (S.busy) return;
        S.categories.forEach(function (cat, i) {
            // Only the safe ones, and only ever adding: a button labelled
            // "select every safe category" must not silently drop a reviewed
            // category the user ticked deliberately.
            if (cat.risk !== 'safe') return;
            S.selected[cat.id] = cat;
            // By id rather than by index into the grid's checkboxes: the card
            // owns the id it was built with, whatever else lands in that grid.
            var box = document.getElementById('fm-cat-' + i);
            if (box) box.checked = true;
        });
        onSelectionChanged();
    }

    function actClear() {
        if (S.busy) return;
        S.selected = {};
        var grid = byId('fm-cleanup-categories');
        if (grid) {
            grid.querySelectorAll('input[type="checkbox"]').forEach(function (b) { b.checked = false; });
        }
        onSelectionChanged();
    }

    // ══════════════════════════════════════════════════════════════════
    // Action: dry run
    // ══════════════════════════════════════════════════════════════════

    async function actDry() {
        if (S.busy || S.scanning) return;
        var totals = selectionTotals();
        if (!totals.ids.length) {
            showError(t('fm.clean.no_selection'));
            toast(t('fm.clean.no_selection'), 'warn');
            return;
        }

        clearError();
        setBusy(true);
        var btn = byId('fm-cleanup-dry');
        btnLabel(btn, t('fm.cleanup_previewing'));
        setDisabled(btn, true);

        var res;
        try {
            res = await call('POST', '/cleanup/apply', {
                path: S.path, category_ids: totals.ids, dry_run: true
            });
        } catch (e) {
            S.dry = null;
            setHidden(byId('fm-cleanup-dryrun'), true);
            showError(e && e.message ? e.message : String(e));
            toast(e && e.message ? e.message : String(e), 'error');
            return;
        } finally {
            btnLabel(btn, t('fm.clean.preview'));
            setBusy(false);
            updateSelectionBar();
        }

        var deleted = Array.isArray(res.deleted) ? res.deleted : [];
        var failed = Array.isArray(res.failed) ? res.failed : [];

        setCardMode('preview');
        renderNotes(res);
        renderMetrics(res, deleted, failed);
        renderDeletedRows(deleted);
        renderFailedRows(failed);
        setHidden(byId('fm-cleanup-dryrun'), false);
        hideConfirm();

        var card = byId('fm-cleanup-dryrun');
        var goto = card ? card.querySelector('[data-fm-action="cleanup-goto-confirm"]') : null;

        if (res.dry_run === false) {
            // The server was asked for a preview and reported a real run. The
            // files below may already be gone; nothing here may claim otherwise
            // and no delete may be offered on top of it.
            S.dry = null;
            setDisabled(goto, true);
            showError(t('fm.cleanup_dryrun_ignored'));
            toast(t('fm.cleanup_dryrun_ignored'), 'error');
            scrollTo(card);
            return;
        }

        if (!deleted.length) {
            S.dry = null;
            setDisabled(goto, true);
            toast(t('fm.cleanup_preview_empty'), 'warn');
            scrollTo(card);
            return;
        }

        setDisabled(goto, false);
        S.dry = {
            sig: selectionSignature(),
            ids: totals.ids.slice(),
            planned: deleted.length,
            freed: Number(res.freed || 0),
            failed: failed.length,
            review: totals.review
        };
        scrollTo(card);
    }

    // ══════════════════════════════════════════════════════════════════
    // Action: reveal the typed confirmation
    // ══════════════════════════════════════════════════════════════════

    function confirmWord() {
        var input = byId('fm-cleanup-confirm-input');
        var key = (input && input.getAttribute('data-fm-confirm-word')) || 'fm.confirm.cleanup_word';
        return t(key);
    }

    function wordMatches() {
        var input = byId('fm-cleanup-confirm-input');
        var word = confirmWord();
        if (!input || !word) return false;
        return input.value.trim().toLowerCase() === word.trim().toLowerCase();
    }

    var _confirmWired = false;

    function wireConfirmInput() {
        if (_confirmWired) return;
        var input = byId('fm-cleanup-confirm-input');
        if (!input) return;
        _confirmWired = true;
        input.addEventListener('input', function () {
            var ok = wordMatches();
            setDisabled(byId('fm-cleanup-apply'), !ok || !S.dry || S.busy);
            // The mismatch line only appears once something has been typed;
            // shouting at an empty box is noise.
            setHidden(byId('fm-cleanup-confirm-error'), ok || !input.value.trim());
        });
        input.addEventListener('keydown', function (ev) {
            if (ev.key !== 'Enter') return;
            ev.preventDefault();
            var btn = byId('fm-cleanup-apply');
            if (btn && !btn.disabled) actApply();
        });
    }

    function actGotoConfirm() {
        if (S.busy) return;
        if (!S.dry || S.dry.sig !== selectionSignature()) {
            // Either no preview has been seen, or the selection moved after it.
            invalidateDry();
            updateSelectionBar();
            toast(t('fm.clean.dry_run_note'), 'warn');
            return;
        }

        var title = byId('fm-cleanup-confirm-title');
        if (title) {
            title.textContent = t('fm.confirm.cleanup_title', {
                count: fmtInt(S.dry.planned),
                size: fmtBytes(S.dry.freed)
            });
            title.title = fmtBytesExact(S.dry.freed);
        }
        if (S.dry.review) toast(t('fm.risk.review_desc'), 'warn');

        wireConfirmInput();
        var input = byId('fm-cleanup-confirm-input');
        if (input) input.value = '';
        setHidden(byId('fm-cleanup-confirm-error'), true);
        setDisabled(byId('fm-cleanup-apply'), true);
        var card = byId('fm-cleanup-confirm');
        setHidden(card, false);
        scrollTo(card);
        if (input) { try { input.focus(); } catch (e) { /* focus is a nicety */ } }
    }

    // ══════════════════════════════════════════════════════════════════
    // Action: apply for real
    // ══════════════════════════════════════════════════════════════════

    async function actApply() {
        if (S.busy || S.scanning) return;

        // Re-checked at the moment of the click. A disabled attribute is a hint
        // to the user, not a guarantee to the code.
        if (!S.dry) {
            hideConfirm();
            toast(t('fm.clean.dry_run_note'), 'warn');
            return;
        }
        if (S.dry.sig !== selectionSignature()) {
            invalidateDry();
            updateSelectionBar();
            toast(t('fm.clean.dry_run_note'), 'warn');
            return;
        }
        if (!wordMatches()) {
            setHidden(byId('fm-cleanup-confirm-error'), false);
            toast(t('fm.confirm.cleanup_mismatch'), 'warn');
            return;
        }

        var plan = S.dry;
        clearError();
        setBusy(true);
        var applyBtn = byId('fm-cleanup-apply');
        setDisabled(applyBtn, true);
        btnLabel(applyBtn, t('fm.cleanup_applying'));

        var res;
        try {
            // plan.ids, not the live selection: the two are identical by the
            // signature check above, and sending the previewed list keeps them
            // that way even if something mutates state during the await.
            res = await call('POST', '/cleanup/apply', {
                path: S.path, category_ids: plan.ids, dry_run: false
            });
        } catch (e) {
            showError(e && e.message ? e.message : String(e));
            toast(e && e.message ? e.message : String(e), 'error');
            btnLabel(applyBtn, t('fm.clean.apply'));
            setBusy(false);
            setDisabled(applyBtn, !wordMatches());
            return;
        }

        btnLabel(applyBtn, t('fm.clean.apply'));
        setBusy(false);

        var deleted = Array.isArray(res.deleted) ? res.deleted : [];
        var failed = Array.isArray(res.failed) ? res.failed : [];
        var freed = Number(res.freed || 0);

        var summary, kind;
        if (res.dry_run === true) {
            // Reporting a successful delete here would be a green tick over work
            // that never happened.
            summary = t('fm.cleanup_dryrun_flag');
            kind = 'error';
        } else if (failed.length && !deleted.length) {
            summary = t('fm.cleanup_all_failed', { f: fmtInt(failed.length) });
            kind = 'error';
        } else if (failed.length) {
            summary = t('fm.cleanup_partial', { n: fmtInt(deleted.length), b: fmtBytes(freed), f: fmtInt(failed.length) });
            kind = 'warn';
        } else {
            summary = t('fm.cleanup_done', { n: fmtInt(deleted.length), b: fmtBytes(freed) });
            kind = 'success';
        }

        setCardMode('result', summary);
        renderNotes(res);
        renderMetrics(res, deleted, failed);
        renderDeletedRows(deleted);
        renderFailedRows(failed);
        setHidden(byId('fm-cleanup-dryrun'), false);

        // The preview and the real run must describe the same plan. When they do
        // not, the tree changed underneath and files were deleted that the user
        // never saw listed — that is stated, not averaged away.
        var lines = [];
        var handled = deleted.length + failed.length;
        if (plan.planned !== handled) {
            var divergence = t('fm.cleanup_divergence', { p: fmtInt(plan.planned), a: fmtInt(handled) });
            lines.push(divergence);
            toast(divergence, 'warn');
        }
        // Both messages go into the one notice line; showing them one at a time
        // would let the second silently erase the first.
        if (kind === 'error' || kind === 'warn') lines.push(summary);
        if (lines.length) showNotice(lines, kind === 'error' ? 'error' : 'warn');
        toast(summary, kind);

        // The plan has been spent and the category figures now describe files
        // that are gone. Leaving them tickable would let a second delete run
        // against numbers that are no longer true.
        S.dry = null;
        S.selected = {};
        S.categories = [];
        var grid = byId('fm-cleanup-categories');
        if (grid) clearNode(grid);
        hideConfirm();
        setHidden(byId('fm-cleanup-selbar'), true);
        setHidden(byId('fm-cleanup-select-safe'), true);
        setHidden(byId('fm-cleanup-nothing'), true);
        btnLabel(byId('fm-cleanup-scan'), t('fm.clean.rescan'), true);
        setDisabled(byId('fm-cleanup-scan'), false);
        scrollTo(byId('fm-cleanup-dryrun'));

        // Space and file list both changed; both are guarded because either may
        // be absent while the other modules are still being wired up.
        var fm = window.FM;
        if (fm && typeof fm.refresh === 'function') {
            try { fm.refresh(); } catch (e) { console.warn(LOG, 'FM.refresh() failed:', e); }
        }
        if (fm && typeof fm.loadVolumes === 'function') {
            try { fm.loadVolumes(); } catch (e) { console.warn(LOG, 'FM.loadVolumes() failed:', e); }
        }
    }

    // ══════════════════════════════════════════════════════════════════
    // Action: back out of a step
    // ══════════════════════════════════════════════════════════════════

    /**
     * Both card footers use this name. Cancelling the confirmation returns to
     * the preview; cancelling the preview returns to the category list. The
     * selection survives either way — backing out is not a reason to lose it.
     */
    function actBack(node) {
        if (S.busy) return;
        if (node && typeof node.closest === 'function' && node.closest('#fm-cleanup-confirm')) {
            hideConfirm();
            scrollTo(byId('fm-cleanup-dryrun'));
            return;
        }
        hideConfirm();
        setHidden(byId('fm-cleanup-dryrun'), true);
    }

    // ══════════════════════════════════════════════════════════════════
    // Registration with the shared router
    // ══════════════════════════════════════════════════════════════════

    var ACTIONS = {
        'cleanup-scan': function () { actScan(); },
        'cleanup-select-safe': function () { actSelectSafe(); },
        'cleanup-clear': function () { actClear(); },
        'cleanup-dry': function () { actDry(); },
        'cleanup-goto-confirm': function () { actGotoConfirm(); },
        'cleanup-apply': function () { actApply(); },
        // Declared in the markup inside both cleanup cards. No other module owns
        // a cleanup-* name, and an unregistered button is a dead button.
        'cleanup-back': function (node) { actBack(node); }
    };

    var _registered = false;

    function tryRegister() {
        if (_registered) return true;
        var reg = window.FMActions;
        if (!reg || typeof reg.register !== 'function') return false;
        _registered = true;
        reg.register(ACTIONS, 'fm_cleanup');
        return true;
    }

    if (!tryRegister()) {
        // Script order between the four modules is not guaranteed, and the
        // router owns register(). Poll briefly rather than install a second
        // delegated listener, which would fire every handler twice.
        var attempts = 0;
        var poll = setInterval(function () {
            attempts++;
            if (tryRegister()) { clearInterval(poll); return; }
            if (attempts >= 60) {                 // ~9 s
                clearInterval(poll);
                console.error(LOG, 'window.FMActions.register() never appeared. ' +
                    'Every Cleanup button on this page is inert. Check that the ' +
                    'router module is loaded before or alongside fm_cleanup.js.');
            }
        }, 150);
        document.addEventListener('DOMContentLoaded', function () {
            if (tryRegister()) clearInterval(poll);
        });
    }
})();
