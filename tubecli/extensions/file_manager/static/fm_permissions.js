/**
 * fm_permissions.js — behaviour for the Permissions pane (#fm-pane-perm).
 *
 * WHY THIS FILE EXISTS
 * --------------------
 * file_manager.js was written for the previous markup: its FM.openPermissions()
 * builds a modal out of elements this page no longer has. The new page carries a
 * permissions pane inside the right-hand panel instead, so the fetch/format
 * logic is re-used here and pointed at the inline markup. file_manager.js is not
 * modified — three sibling modules attach to the same page at the same time, and
 * a shared file would be a merge conflict by design.
 *
 * WHAT IT REFUSES TO DO
 * ---------------------
 * Nothing here invents a fact the server did not report. When the backend says a
 * platform cannot express a control (Windows has no POSIX mode; a symlink cannot
 * be chmod-ed without hitting its target), its own explanation is shown verbatim
 * and the control is disabled — a live control that quietly does nothing is the
 * failure mode this page was rebuilt to remove.
 */
(function () {
    'use strict';

    var LOG = '[fm_permissions]';

    // ══════════════════════════════════════════════════════════════════
    // Borrowed plumbing
    //
    // file_manager.js runs in an IIFE and publishes only window.FM, window.T and
    // window.applyI18n. Everything else it owns (byId, fmtBytes, confirmDialog…)
    // is private to that closure, so anything needed here is implemented here.
    // Every lookup is late-bound: this file may parse before file_manager.js and
    // must not capture an undefined global at load time.
    // ══════════════════════════════════════════════════════════════════

    var _warnedKeys = {};

    /** i18n. Falls back to the key itself so a missing dictionary cannot blank the UI. */
    function T(key, vars) {
        if (typeof window.T === 'function') return window.T(key, vars);
        if (!_warnedKeys[key]) {
            _warnedKeys[key] = true;
            console.warn(LOG, 'window.T is not available yet; showing raw key:', key);
        }
        return key;
    }

    function toast(message, kind) {
        var fm = window.FM;
        if (fm && typeof fm.toast === 'function') { fm.toast(message, kind); return; }
        // Losing the server's explanation is worse than a plain console line.
        (kind === 'error' ? console.error : console.warn)(LOG, message);
    }

    /**
     * One network entry point. FM.feat resolves the API prefix (the server may
     * mount /api/v1/file-manager or /api/v1/files) and throws carrying the
     * server's own message for any non-ok response — reproducing that here would
     * give two copies of one rule, and the copy that drifts is the one that stops
     * checking.
     */
    function feat(method, endpoint, body) {
        var fm = window.FM;
        if (!fm || typeof fm.feat !== 'function') {
            return Promise.reject(new Error(
                T('fm.err.generic', { message: 'window.FM.feat (file_manager.js)' })
            ));
        }
        return fm.feat(method, endpoint, body);
    }

    var _missing = {};

    /** A missing element degrades to a console warning; it never throws. */
    function byId(id) {
        var el = document.getElementById(id);
        if (!el && !_missing[id]) {
            _missing[id] = true;
            console.warn(LOG, 'markup element not found:', id);
        }
        return el;
    }

    function qsa(selector) {
        var root = byId('fm-pane-perm');
        if (!root) return [];
        return Array.prototype.slice.call(root.querySelectorAll(selector));
    }

    function setHidden(id, hidden) {
        var el = byId(id);
        if (el) el.hidden = !!hidden;
        return el;
    }

    function setText(id, text) {
        var el = byId(id);
        if (el) el.textContent = (text === null || text === undefined) ? '' : String(text);
        return el;
    }

    function clear(node) {
        while (node && node.firstChild) node.removeChild(node.firstChild);
    }

    function el(tag, attrs, text) {
        var node = document.createElement(tag);
        if (attrs) {
            Object.keys(attrs).forEach(function (k) {
                if (attrs[k] === null || attrs[k] === undefined) return;
                node.setAttribute(k, String(attrs[k]));
            });
        }
        if (text !== null && text !== undefined) node.textContent = String(text);
        return node;
    }

    // ══════════════════════════════════════════════════════════════════
    // POSIX mode arithmetic
    // ══════════════════════════════════════════════════════════════════

    // data-perm attributes in the markup are u/g/o × r/w/x; the API returns the
    // same three groups under user / group_perms / other.
    var GROUPS = [
        { prefix: 'u', field: 'user',        bits: { r: 0o400, w: 0o200, x: 0o100 } },
        { prefix: 'g', field: 'group_perms', bits: { r: 0o40,  w: 0o20,  x: 0o10  } },
        { prefix: 'o', field: 'other',       bits: { r: 0o4,   w: 0o2,   x: 0o1   } }
    ];

    var SPECIAL_MASK = 0o7000;
    var OCTAL_RE = /^[0-7]{3,4}$/;

    function pad4Octal(n) {
        var s = (n >>> 0).toString(8);
        while (s.length < 4) s = '0' + s;
        return s;
    }

    /**
     * "-rwxr-xr-x" style. Rendered from the live mode rather than echoing the
     * server's `filemode` string, because it has to track the checkboxes; the
     * leading type character is still the server's, since the mode alone cannot
     * say whether the item is a directory, a link or a socket.
     */
    function symbolic(mode, typeChar) {
        var out = typeChar || '-';
        var special = [0o4000, 0o2000, 0o1000];
        var specialChar = ['s', 's', 't'];
        for (var i = 0; i < GROUPS.length; i++) {
            var bits = GROUPS[i].bits;
            out += (mode & bits.r) ? 'r' : '-';
            out += (mode & bits.w) ? 'w' : '-';
            var x = !!(mode & bits.x);
            var sp = !!(mode & special[i]);
            out += sp ? (x ? specialChar[i] : specialChar[i].toUpperCase()) : (x ? 'x' : '-');
        }
        return out;
    }

    /**
     * The mode directories will actually receive, copied bit-for-bit from
     * permissions.py::_apply_posix. The UI must predict the backend's refusal
     * with the same formula: a naive "owner has no x" test would wrongly block
     * 0644, which the backend happily turns into 0755 for directories.
     */
    function directoryModeFor(mode) {
        return mode | ((mode & 0o444) >> 2);
    }

    // ══════════════════════════════════════════════════════════════════
    // State
    // ══════════════════════════════════════════════════════════════════

    var state = {
        path: '',          // item the pane currently describes
        data: null,        // last GET /permissions payload
        special: 0,        // setuid/setgid/sticky, kept out of the 9 checkboxes
        baseMode: null,    // mode as read from disk, for "nothing to change"
        inflight: null,    // path of a GET in progress
        busy: false,       // a POST is in progress
        pendingResult: null,
        wired: false
    };

    // ══════════════════════════════════════════════════════════════════
    // Pane plumbing
    // ══════════════════════════════════════════════════════════════════

    /**
     * Rendering into a hidden pane is indistinguishable from doing nothing, so
     * load() opens the panel itself instead of trusting the caller to have done
     * it. Every step is idempotent — the router's own tab handler may have run
     * already.
     */
    function revealPane() {
        var app = document.getElementById('fm-app');
        if (app) app.setAttribute('data-panel', 'open');

        setHidden('fm-panel-empty', true);
        setHidden('fm-pane-details', true);
        setHidden('fm-pane-perm', false);

        var details = byId('fm-ptab-details');
        if (details) {
            details.classList.remove('is-active');
            details.setAttribute('aria-selected', 'false');
        }
        var perm = byId('fm-ptab-perm');
        if (perm) {
            perm.classList.add('is-active');
            perm.setAttribute('aria-selected', 'true');
        }
    }

    function paneVisible() {
        var pane = document.getElementById('fm-pane-perm');
        return !!pane && !pane.hidden;
    }

    function boxes() {
        return qsa('[data-perm]');
    }

    function boxFor(prefix, bit) {
        var found = null;
        boxes().forEach(function (cb) {
            if (cb.getAttribute('data-perm') === prefix + '-' + bit) found = cb;
        });
        return found;
    }

    function recursiveChecked() {
        var cb = byId('fm-perm-recursive');
        return !!(cb && cb.checked);
    }

    function octalField() {
        return byId('fm-perm-octal');
    }

    function octalValid() {
        var input = octalField();
        return !!input && OCTAL_RE.test(String(input.value).trim());
    }

    /** Mode currently expressed by the checkboxes, plus the untouched special bits. */
    function currentMode() {
        var mode = state.special & SPECIAL_MASK;
        GROUPS.forEach(function (g) {
            ['r', 'w', 'x'].forEach(function (bit) {
                var cb = boxFor(g.prefix, bit);
                if (cb && cb.checked) mode |= g.bits[bit];
            });
        });
        return mode;
    }

    function showError(message) {
        var node = setText('fm-perm-error', message);
        if (node) node.hidden = !message;
    }

    function clearError() {
        showError('');
    }

    // ══════════════════════════════════════════════════════════════════
    // Rendering
    // ══════════════════════════════════════════════════════════════════

    /**
     * Chips are label + value as two nodes rather than one interpolated string:
     * there is no locale key of the form "Owner: {name}", and inventing the
     * separator inside JS would be a hardcoded user-visible string.
     */
    function chip(id, labelKey, value) {
        var node = byId(id);
        if (!node) return;
        if (value === null || value === undefined || value === '') {
            clear(node);
            node.hidden = true;
            return;
        }
        clear(node);
        node.appendChild(el('span', null, T(labelKey)));
        node.appendChild(el('span', null, value));
        node.title = T(labelKey) + ' ' + value;   // the chip ellipsizes when narrow
        node.hidden = false;
    }

    /**
     * data-state drives the colour: "unknown" is dashed and grey on purpose. A
     * probe that could not run is not the same answer as a confirmed "no", and
     * the CSS refuses to let them look alike.
     */
    function renderEffective(data) {
        var checks = (data && data.checks) || {};
        [['fm-eff-read', 'readable'], ['fm-eff-write', 'writable'], ['fm-eff-exec', 'executable']]
            .forEach(function (pair) {
                var node = byId(pair[0]);
                if (!node) return;
                var value = data ? data[pair[1]] : null;
                node.setAttribute('data-state',
                    value === true ? 'true' : (value === false ? 'false' : 'unknown'));
                // The server names the exact probe it ran ("os.access (effective
                // ids)", "opened O_WRONLY|O_APPEND", …). That is its answer to
                // "how do you know", so it is carried verbatim.
                if (checks[pair[1]]) node.title = String(checks[pair[1]]);
                else node.removeAttribute('title');
            });
    }

    /**
     * The API's own `reason`, then anything it flagged separately. Never a
     * paraphrase: the reason string is the only place the backend explains a
     * refusal, and rewriting it into something vaguer is how the previous UI
     * managed to report "not supported" with no way to find out why.
     */
    function renderReason(data) {
        var parts = [];
        if (data.reason) parts.push(String(data.reason));
        if (Array.isArray(data.notes)) {
            data.notes.forEach(function (n) { if (n) parts.push(String(n)); });
        }
        if (data.is_symlink) parts.push(T('fm.perm.symlink_note'));
        // The payload carries no "running as root" boolean; the backend states it
        // inside `reason` in its own words. Matching that specific phrase is the
        // only signal available, so a miss means the translated note is simply
        // omitted — the server's own sentence above still says it.
        if (data.reason && String(data.reason).indexOf('chạy bằng root') !== -1) {
            parts.push(T('fm.perm.root_note'));
        }
        setText('fm-perm-reason', parts.join(' '));
    }

    /** For a directory the x bit means "may enter", which is what the locale says. */
    function swapExecuteLabels(isDir) {
        var key = isDir ? 'fm.perm.execute_dir' : 'fm.perm.execute';
        qsa('[data-i18n="fm.perm.execute"], [data-i18n="fm.perm.execute_dir"]')
            .forEach(function (node) {
                // The attribute is rewritten too, so a later applyI18n() pass
                // cannot quietly put "Execute" back on a directory.
                node.setAttribute('data-i18n', key);
                node.textContent = T(key);
            });
    }

    function renderPosix(data) {
        var p = data.posix;

        // The payload carries the mode twice: as a number and as nine booleans
        // that the backend derives from that same number. Everything on screen is
        // rendered from the number alone, so the matrix, the octal field and the
        // symbolic string can never disagree with each other — and so the
        // "nothing to change" comparison has one value to compare against. The
        // booleans are the fallback for the case where neither numeric form
        // survived the trip.
        var mode = Number(p.octal);
        if (isNaN(mode) || p.octal === null || p.octal === undefined) {
            mode = /^[0-7]{1,4}$/.test(String(p.mode || '')) ? parseInt(String(p.mode), 8) : NaN;
        }
        if (isNaN(mode)) {
            mode = 0;
            GROUPS.forEach(function (g) {
                var src = p[g.field] || {};
                ['r', 'w', 'x'].forEach(function (bit) { if (src[bit]) mode |= g.bits[bit]; });
            });
            console.warn(LOG, 'payload had no usable octal mode; rebuilt', pad4Octal(mode), 'from the r/w/x flags');
        }

        state.special = mode & SPECIAL_MASK;
        state.baseMode = mode;

        GROUPS.forEach(function (g) {
            ['r', 'w', 'x'].forEach(function (bit) {
                var cb = boxFor(g.prefix, bit);
                if (cb) cb.checked = (mode & g.bits[bit]) !== 0;
            });
        });

        var input = octalField();
        if (input) {
            input.value = pad4Octal(mode);
            input.classList.remove('is-invalid');
        }
        swapExecuteLabels(!!data.is_dir);
        renderSymbolic();

        var recursive = byId('fm-perm-recursive');
        if (recursive) recursive.checked = false;

        // An ACL overrides the mode, so the matrix is not the whole truth. Both
        // "has one" and "could not check" have to be said out loud; only a
        // confirmed absence may stay quiet.
        var aclNote = byId('fm-perm-acl-note');
        if (aclNote) {
            if (p.acl_present === true || p.acl_present === null || p.acl_present === undefined) {
                var text = (p.acl_present === true) ? T('fm.perm.acl_present') : T('fm.perm.acl_unknown');
                if (p.acl_note) text += ' ' + String(p.acl_note);
                setText('fm-perm-acl-note-text', text);
                aclNote.hidden = false;
            } else {
                aclNote.hidden = true;
            }
        }

        setHidden('fm-perm-posix', false);
        setHidden('fm-perm-windows', true);
    }

    function renderSymbolic() {
        var node = byId('fm-perm-symbolic');
        if (!node) return;
        var mode = currentMode();
        var typeChar = '-';
        var p = state.data && state.data.posix;
        if (p && typeof p.filemode === 'string' && p.filemode.length) typeChar = p.filemode.charAt(0);
        else if (state.data && state.data.is_dir) typeChar = 'd';
        node.textContent = symbolic(mode, typeChar);

        var flags = [];
        if (mode & 0o4000) flags.push(T('fm.perm.setuid'));
        if (mode & 0o2000) flags.push(T('fm.perm.setgid'));
        if (mode & 0o1000) flags.push(T('fm.perm.sticky'));
        if (flags.length) node.title = flags.join(', ');
        else node.removeAttribute('title');
    }

    /** Windows is read-only here by design — see the notice in the markup. */
    function renderWindows(data) {
        var w = data.windows;
        var body = byId('fm-perm-acl-body');
        var entries = Array.isArray(w.entries) ? w.entries : [];

        if (body) {
            clear(body);
            entries.forEach(function (entry) {
                var deny = String(entry.type || '').toLowerCase().indexOf('den') !== -1;
                var row = el('tr');
                row.appendChild(el('td', null, entry.identity || T('fm.common.unknown')));
                row.appendChild(el('td', { class: 'fm-mono' }, entry.rights || T('fm.common.unknown')));

                var typeCell = el('td');
                typeCell.appendChild(el(
                    'span',
                    { class: 'fm-risk ' + (deny ? 'fm-risk-review' : 'fm-risk-safe') },
                    deny ? T('fm.perm.win_deny') : T('fm.perm.win_allow')
                ));
                row.appendChild(typeCell);

                row.appendChild(el('td', null, entry.inherited ? T('fm.common.yes') : T('fm.perm.win_explicit')));
                // "applies_to" is the server's own scope wording (this object /
                // subfolders / inherit-only) and has no column of its own.
                if (entry.applies_to) row.title = String(entry.applies_to);
                body.appendChild(row);
            });
        }

        // Three different facts, three different lines. Collapsing them would let
        // "everyone has full access" be read as "nobody does".
        setHidden('fm-perm-null-dacl', !w.null_dacl);
        setHidden('fm-perm-empty-dacl', !w.empty_dacl);

        var skipped = Array.isArray(w.skipped_aces) ? w.skipped_aces : [];
        var skippedEl = byId('fm-perm-skipped-ace');
        if (skippedEl) {
            if (skipped.length) {
                // data-i18n-template is deliberately not handled by applyI18n:
                // the count only exists here.
                var key = skippedEl.getAttribute('data-i18n-template') || 'fm.perm.win_skipped_ace';
                skippedEl.textContent = T(key, { n: skipped.length });
                skippedEl.title = skipped.join(' | ');
                skippedEl.hidden = false;
            } else {
                skippedEl.hidden = true;
            }
        }

        // An empty list with no DACL verdict attached means the read did not
        // actually tell us anything; saying "no permissions" there would be a
        // fabricated fact.
        var unexplained = !entries.length && !w.null_dacl && !w.empty_dacl;
        var aclError = byId('fm-perm-acl-error');
        if (aclError) {
            aclError.textContent = unexplained ? T('fm.perm_win_no_entries') : '';
            aclError.hidden = !unexplained;
        }

        setHidden('fm-perm-windows', false);
        setHidden('fm-perm-posix', true);
    }

    /** Everything the pane can show, driven from one payload. */
    function render(data) {
        state.data = data;

        chip('fm-perm-platform', 'fm.perm.platform', data.platform || T('fm.common.unknown'));

        var owner = null, group = null, ownerUnknown = false;
        if (data.posix) {
            owner = data.posix.owner;
            group = data.posix.group;
            // pwd/grp missing: the backend hands back the raw numeric id rather
            // than a name, and says so.
            ownerUnknown = /^\d+$/.test(String(owner || ''));
        } else if (data.windows) {
            owner = data.windows.owner;
            group = data.windows.group;
        }
        chip('fm-perm-owner', 'fm.perm.owner', owner);
        chip('fm-perm-group', 'fm.perm.group', group);
        if (ownerUnknown) {
            var ownerChip = byId('fm-perm-owner');
            if (ownerChip) ownerChip.title = T('fm.perm.unknown_owner');
        }

        renderEffective(data);
        renderReason(data);

        if (data.supported === false) {
            // The server always explains a refusal; if it somehow did not, say
            // that instead of showing an empty warning box.
            setText('fm-perm-unsupported-reason',
                data.reason || T('fm.err.unsupported_platform', { platform: data.platform || '' }));
            setHidden('fm-perm-unsupported', false);
            setHidden('fm-perm-posix', true);
            setHidden('fm-perm-windows', true);
            setEditable(false);
            return;
        }
        setHidden('fm-perm-unsupported', true);

        if (data.posix) {
            renderPosix(data);
            // can_edit is false for a symlink: chmod would silently retarget the
            // link's destination. The controls go dead and the server's sentence
            // explaining it is shown next to them.
            var editable = data.can_edit !== false;
            setEditable(editable);
            if (!editable && data.reason) showError(String(data.reason));
        } else if (data.windows) {
            renderWindows(data);
            setEditable(false);
        } else {
            setHidden('fm-perm-posix', true);
            setHidden('fm-perm-windows', true);
            setEditable(false);
            showError(T('fm.err.generic', { message: 'posix / windows' }));
            console.error(LOG, 'payload has neither posix nor windows:', data);
        }
    }

    /** Disabling beats leaving a control clickable that cannot do anything. */
    function setEditable(enabled) {
        boxes().forEach(function (cb) { cb.disabled = !enabled; });

        var input = octalField();
        if (input) input.disabled = !enabled;

        var recursive = byId('fm-perm-recursive');
        if (recursive) recursive.disabled = !enabled;

        // Reset only re-reads the server, so it stays usable as long as a path is
        // known — it is the way out of a half-edited matrix.
        qsa('[data-fm-action="perm-reset"]').forEach(function (btn) { btn.disabled = !state.path; });

        refreshGuards();
    }

    /**
     * Re-evaluates everything that can block Save, every time the form changes,
     * so the button's state is always the true answer to "would this work".
     */
    function refreshGuards() {
        var data = state.data;
        var editable = !!(data && data.posix && data.supported !== false && data.can_edit !== false);
        var valid = octalValid();

        var refuse = false;
        if (editable && valid && recursiveChecked() && data.is_dir) {
            // Same arithmetic as the backend, so the UI never offers a request the
            // server is certain to reject.
            refuse = !(directoryModeFor(currentMode()) & 0o100);
        }
        setHidden('fm-perm-recursive-refuse', !refuse);

        var apply = byId('fm-perm-apply');
        if (apply) apply.disabled = !editable || !valid || refuse || state.busy;
    }

    // ══════════════════════════════════════════════════════════════════
    // Live editing
    // ══════════════════════════════════════════════════════════════════

    function onMatrixChange() {
        var input = octalField();
        if (input) {
            input.value = pad4Octal(currentMode());
            input.classList.remove('is-invalid');
        }
        renderSymbolic();
        clearError();
        refreshGuards();
    }

    function onOctalInput() {
        var input = octalField();
        if (!input) return;
        var raw = String(input.value).trim();

        if (!OCTAL_RE.test(raw)) {
            // Mid-typing "7" is not an error worth shouting about; the field is
            // marked and Save stays disabled until it parses.
            input.classList.add('is-invalid');
            refreshGuards();
            return;
        }
        input.classList.remove('is-invalid');

        var value = parseInt(raw, 8);
        // Three digits carry no special bits, so the ones already on the file are
        // kept: typing "755" on a setuid binary must not silently strip setuid.
        // Four digits are taken literally, which is how those bits get cleared.
        if (raw.length === 4) state.special = value & SPECIAL_MASK;

        GROUPS.forEach(function (g) {
            ['r', 'w', 'x'].forEach(function (bit) {
                var cb = boxFor(g.prefix, bit);
                if (cb) cb.checked = (value & g.bits[bit]) !== 0;
            });
        });

        renderSymbolic();
        clearError();
        refreshGuards();
    }

    function onOctalCommit() {
        var input = octalField();
        if (!input) return;
        if (!OCTAL_RE.test(String(input.value).trim())) {
            showError(T('fm.perm_invalid_mode'));
            refreshGuards();
            return;
        }
        // Normalised to 4 digits so what is displayed is exactly what will be
        // sent, special bits included.
        input.value = pad4Octal(currentMode());
        renderSymbolic();
        refreshGuards();
    }

    function wire() {
        if (state.wired) return;
        state.wired = true;

        boxes().forEach(function (cb) { cb.addEventListener('change', onMatrixChange); });

        var input = octalField();
        if (input) {
            input.addEventListener('input', onOctalInput);
            input.addEventListener('blur', onOctalCommit);
            input.addEventListener('keydown', function (e) {
                if (e.key === 'Enter') { e.preventDefault(); onOctalCommit(); }
            });
        }

        var recursive = byId('fm-perm-recursive');
        if (recursive) recursive.addEventListener('change', function () { clearError(); refreshGuards(); });
    }

    // ══════════════════════════════════════════════════════════════════
    // Read
    // ══════════════════════════════════════════════════════════════════

    function showLoading() {
        chip('fm-perm-platform', 'fm.perm.platform', T('fm.common.loading'));
        chip('fm-perm-owner', 'fm.perm.owner', null);
        chip('fm-perm-group', 'fm.perm.group', null);
        renderEffective(null);
        setText('fm-perm-reason', '');
        setHidden('fm-perm-unsupported', true);
        setHidden('fm-perm-posix', true);
        setHidden('fm-perm-windows', true);
        setHidden('fm-perm-acl-note', true);
        setHidden('fm-perm-recursive-refuse', true);
        clearError();
        var apply = byId('fm-perm-apply');
        if (apply) apply.disabled = true;
    }

    function clearResultBlock() {
        var body = byId('fm-perm-failed-body');
        if (body) clear(body);
        setHidden('fm-perm-failed-block', true);
    }

    /**
     * GET /permissions and render it.
     *
     * @param {string}  path   item to describe; falls back to the current selection
     * @param {object}  opts   keepResult: leave the last apply result on screen
     *                         quietErrors: report a read failure as a toast, so a
     *                         reload triggered by apply cannot overwrite the apply
     *                         result in the inline error slot
     */
    async function load(path, opts) {
        opts = opts || {};
        var fm = window.FM;
        var target = path || (fm && (fm.selectedItem || fm.currentPath)) || '';
        if (!target) {
            toast(T('fm.no_selection'), 'warn');
            return;
        }

        wire();
        revealPane();
        if (!opts.keepResult) {
            state.pendingResult = null;
            clearResultBlock();
        }

        // A second read of the same path while one is in flight would race, and
        // the loser could paint stale data last.
        if (state.inflight === target) return;
        state.inflight = target;
        state.path = target;
        showLoading();

        var data = null, failure = null;
        try {
            data = await feat('GET', '/permissions?path=' + encodeURIComponent(target));
        } catch (e) {
            failure = e;
        } finally {
            if (state.inflight === target) state.inflight = null;
        }

        // Another target was requested while this was in flight.
        if (state.path !== target) return;

        if (failure) {
            console.error(LOG, 'GET /permissions failed for', target, failure);
            state.data = null;
            setEditable(false);
            chip('fm-perm-platform', 'fm.perm.platform', T('fm.common.unknown'));
            // The server's own message, never a generic "failed to load".
            if (opts.quietErrors) toast(failure.message || String(failure), 'error');
            else showError(failure.message || String(failure));
            return;
        }

        if (!data || typeof data !== 'object') {
            state.data = null;
            setEditable(false);
            showError(T('fm.err.generic', { message: String(data) }));
            return;
        }

        render(data);
    }

    // ══════════════════════════════════════════════════════════════════
    // Write
    // ══════════════════════════════════════════════════════════════════

    /** The Save button holds an icon plus a label span; only the label changes. */
    function applyButtonLabel(key) {
        var apply = byId('fm-perm-apply');
        if (!apply) return;
        var label = apply.querySelector('[data-i18n]');
        if (label) label.textContent = T(key);
    }

    /**
     * Renders the outcome of a POST. Every failed entry is listed; nothing is
     * folded into "and N more". A recursive chmod that touches 4000 files and
     * fails on 3 of them has to name those 3, or the user is told a lie by
     * omission.
     */
    function renderResult(result) {
        var failed = Array.isArray(result.failed) ? result.failed : [];
        var body = byId('fm-perm-failed-body');

        if (body) {
            clear(body);
            failed.forEach(function (item) {
                var row = el('tr');
                if (typeof item === 'string') {
                    var cell = el('td', { colspan: '2' }, item);
                    row.appendChild(cell);
                } else {
                    row.appendChild(el('td', { class: 'fm-cell-path' }, item.path || ''));
                    // A walk error is a different failure from a chmod error: the
                    // folder was never entered, so nothing inside it was touched
                    // either. The locale has a sentence that says so.
                    var reason = item.source === 'walk'
                        ? T('fm.perm.walk_error', { error: item.error || '' })
                        : (item.error || '');
                    row.appendChild(el('td', null, reason));
                }
                body.appendChild(row);
            });
        }
        setHidden('fm-perm-failed-block', !failed.length);

        var message = result.message ||
            T('fm.perm.applied', { applied: result.applied || '' });

        if (result.ok) {
            toast(message, 'success');
        } else {
            showError(message);
        }

        // Warnings are the server telling us it did something other than exactly
        // what was asked (directories given the traverse bit, recursive ignored
        // on a file). Dropping them would make the result look cleaner than it is.
        (Array.isArray(result.warnings) ? result.warnings : []).forEach(function (w) {
            if (w) toast(String(w), 'warn');
        });
    }

    async function applyPermissions() {
        if (state.busy) return;

        var data = state.data;
        if (!state.path || !data) {
            toast(T('fm.no_selection'), 'warn');
            return;
        }
        // Windows and unsupported platforms: the backend refuses a POSIX mode and
        // explains why in its own words. That text is already on screen; repeat it
        // in the error slot rather than paraphrasing it into "not supported".
        if (data.supported === false || !data.posix || data.can_edit === false) {
            showError(String(data.reason ||
                T('fm.err.unsupported_platform', { platform: data.platform || '' })));
            return;
        }
        if (!octalValid()) {
            showError(T('fm.perm_invalid_mode'));
            return;
        }

        var mode = currentMode();
        var recursive = recursiveChecked();

        if (recursive && data.is_dir && !(directoryModeFor(mode) & 0o100)) {
            showError(T('fm.perm.recursive_refuse'));
            setHidden('fm-perm-recursive-refuse', false);
            return;
        }
        // A recursive run still has work to do even when the top item already has
        // the mode, so only the single-item case is a no-op.
        if (!recursive && state.baseMode !== null && mode === state.baseMode) {
            showError(T('fm.perm.no_change'));
            return;
        }

        var payload = {
            path: state.path,
            recursive: recursive,
            posix_mode: pad4Octal(mode),
            windows: null
        };

        state.busy = true;
        refreshGuards();
        applyButtonLabel('fm.perm_applying');
        clearError();
        clearResultBlock();

        var result = null;
        try {
            var res = await feat('POST', '/permissions', payload);
            var failed = Array.isArray(res.failed) ? res.failed : [];
            result = {
                ok: res.status === 'ok' && failed.length === 0,
                message: res.message,
                applied: res.applied,
                failed: failed,
                warnings: res.warnings
            };
        } catch (e) {
            console.error(LOG, 'POST /permissions failed for', state.path, e);
            // requestJson has already unwrapped the server's explanation.
            result = { ok: false, message: e.message || String(e), failed: [], warnings: [] };
        } finally {
            state.busy = false;
            applyButtonLabel('fm.perm.save');
        }

        state.pendingResult = result;
        try {
            // Re-read rather than assume: after a partial failure the matrix must
            // show what is on disk now, not what was requested.
            await load(state.path, { keepResult: true, quietErrors: true });
        } finally {
            if (state.pendingResult === result) {
                renderResult(result);
                state.pendingResult = null;
            }
        }
    }

    function resetPermissions() {
        if (!state.path) {
            toast(T('fm.no_selection'), 'warn');
            return;
        }
        // Reset means "show me what is actually stored", so it re-reads instead of
        // restoring a cached copy that may already be out of date.
        load(state.path);
    }

    // ══════════════════════════════════════════════════════════════════
    // Public surface + action registration
    // ══════════════════════════════════════════════════════════════════

    var FMPermissions = {
        load: function (path) { return load(path); },
        reset: resetPermissions,
        apply: applyPermissions,
        isVisible: paneVisible
    };
    window.FMPermissions = FMPermissions;

    /**
     * Same resolution order the router uses for a clicked node, so both entry
     * points below can never disagree about which item is being described.
     */
    function pathFromNode(node) {
        if (node && typeof node.closest === 'function') {
            var owner = node.closest('[data-path]');
            if (owner) {
                var p = owner.getAttribute('data-path');
                if (p) return p;
            }
        }
        var fm = window.FM;
        return (fm && fm.selectedItem) || '';
    }

    var HANDLERS = {
        'perm-apply': function () { applyPermissions(); },
        'perm-reset': function () { resetPermissions(); },
        // Not a data-fm-action hook in the markup: the router calls this through
        // FMActions.run() as its second, explicit route into this module. It is
        // registered so that route is never a no-op; the event listener below is
        // the first route, and load() de-duplicates when both fire.
        'perm-load': function (node) { load(pathFromNode(node)); }
    };

    /**
     * The router announces a pane switch rather than calling in directly, so the
     * pane is loaded whether it was opened from the context menu, the panel tab
     * or anywhere added later. Only reached from explicit user actions, which is
     * why "nothing selected" is worth saying out loud here.
     */
    document.addEventListener('fm:pane-change', function (e) {
        var detail = (e && e.detail) || {};
        if (detail.pane !== 'perm') return;
        load(detail.path || '');
    });

    var registered = false;

    function tryRegister() {
        if (registered) return true;
        var bus = window.FMActions;
        if (!bus || typeof bus.register !== 'function') return false;
        // The second argument is the owner name the router quotes when two
        // modules claim one action; "unnamed module" would make that report
        // useless. A router that ignores the argument is unaffected.
        bus.register(HANDLERS, 'permissions');
        registered = true;
        return true;
    }

    /**
     * register() belongs to the router module, which may be parsed after this
     * file. Retrying on the milestones that mean "every page script has run" is
     * cheap; the alternative — assuming an order the markup does not guarantee —
     * is a pane whose buttons do nothing with no clue as to why.
     */
    if (!tryRegister()) {
        window.FMActions = window.FMActions || {};

        var retry = function () { tryRegister(); };
        document.addEventListener('DOMContentLoaded', retry);
        window.addEventListener('load', retry);
        setTimeout(retry, 0);

        window.addEventListener('load', function () {
            setTimeout(function () {
                if (!registered) {
                    console.error(LOG, 'FMActions.register() never appeared — the ' +
                        'perm-apply / perm-reset buttons are not wired. Is the router ' +
                        'module loaded on this page?');
                }
            }, 0);
        });
    }

    // The pane's own inputs are bound as soon as the markup exists; the delegated
    // [data-fm-action] clicks belong to the router and are not touched here.
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () { wire(); });
    } else {
        wire();
    }
})();
