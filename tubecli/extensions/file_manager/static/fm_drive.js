/**
 * fm_drive.js — Google Drive tab for the File Manager.
 *
 * Talks to /api/v1/file-manager/drive/* (drive.py), which authenticates through
 * Auth Manager tokens. Registers its [data-fm-action] handlers with FMActions
 * like the other feature modules; loads after fm_actions.js in document order.
 */
(function () {
    'use strict';

    var LOG = '[fm_drive] ';

    // ── i18n ──────────────────────────────────────────────────────────
    // English strings for the keys this module renders through JS. Vietnamese
    // lives in the page's FMI18N defaults; the aggregated API dictionary (T)
    // wins over both when it knows a key.
    var EN = {
        'fm.nav.drive': 'Google Drive',
        'fm.drive.subtitle': 'Browse, upload, rename and share Google Drive files with the accounts authorized in Auth Manager',
        'fm.drive.account': 'Google account',
        'fm.drive.acting': 'Account: {email}',
        'fm.drive.root': 'My Drive',
        'fm.drive.loading': 'Loading Google Drive…',
        'fm.drive.empty': 'This Drive folder is empty.',
        'fm.drive.load_more': 'Load more…',
        'fm.drive.no_accounts': 'No Google account has authorized Drive yet',
        'fm.drive.no_accounts_hint': 'Open Auth Manager, click Authorize and pick the Google Drive scope. Come back here and hit Refresh.',
        'fm.drive.no_accounts_rail': 'No Drive account yet — authorize in Auth Manager.',
        'fm.drive.open_auth': 'Open Auth Manager',
        'fm.drive.readonly_badge': 'read-only',
        'fm.drive.search_placeholder': 'Search Drive…',
        'fm.drive.upload': 'Upload',
        'fm.drive.uploading': 'Uploading {name}… ({i}/{n})',
        'fm.drive.upload_done': 'Uploaded {n} file(s) to Drive.',
        'fm.drive.download': 'Download',
        'fm.drive.share': 'Share',
        'fm.drive.share_choice': 'Enter an email to share privately, or leave empty for a public link (anyone with the link can view):',
        'fm.drive.share_anyone': 'Public sharing enabled — the link was copied to your clipboard.',
        'fm.drive.share_anyone_link': 'Public sharing enabled. Copy the link: {url}',
        'fm.drive.shared_user': 'Shared with {email}.',
        'fm.drive.rename': 'Rename',
        'fm.drive.rename_prompt': 'New name',
        'fm.drive.renamed': 'Renamed to "{name}".',
        'fm.drive.delete': 'Delete (trash)',
        'fm.drive.confirm_trash': 'Move "{name}" to the Drive trash? (recoverable for 30 days)',
        'fm.drive.trashed': 'Moved "{name}" to the Drive trash.',
        'fm.drive.open': 'Open in Drive',
        'fm.drive.mkdir_prompt': 'New Drive folder name',
        'fm.browse.new_folder': 'New folder',
        'fm.common.refresh': 'Refresh',
    };

    function tr(key, vars) {
        var out = null;
        if (typeof window.T === 'function') {
            try {
                var viaT = window.T(key, vars);
                if (typeof viaT === 'string' && viaT !== key) return viaT;
            } catch (e) { /* fall through */ }
        }
        var lang = (window.FMI18N && window.FMI18N.lang) || 'vi';
        if (lang !== 'vi' && EN[key]) out = EN[key];
        if (out === null && window.FMI18N && typeof window.FMI18N.t === 'function') {
            try {
                var viaI18n = window.FMI18N.t(key);
                if (typeof viaI18n === 'string' && viaI18n !== key) out = viaI18n;
            } catch (e) { /* fall through */ }
        }
        if (out === null) out = EN[key] || key;
        if (vars) {
            Object.keys(vars).forEach(function (k) {
                out = out.split('{' + k + '}').join(String(vars[k]));
            });
        }
        return out;
    }

    function toast(msg, type) {
        if (window.FM && typeof window.FM.toast === 'function') { window.FM.toast(msg, type); return; }
        console.warn(LOG + (type || 'info') + ': ' + msg);
    }

    function byId(id) { return document.getElementById(id); }
    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
        });
    }
    function fmtBytes(n) {
        if (n == null || isNaN(n)) return '—';
        var units = ['B', 'KB', 'MB', 'GB', 'TB'], i = 0, v = Number(n);
        while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
        return v.toFixed(v >= 100 || i === 0 ? 0 : 1) + ' ' + units[i];
    }
    function fmtDate(iso) {
        if (!iso) return '—';
        return String(iso).slice(0, 16).replace('T', ' ');
    }
    function apiOrigin() {
        try { return (localStorage.getItem('tubecli_api') || '').replace(/\/+$/, ''); }
        catch (e) { return ''; }
    }

    // ── State ─────────────────────────────────────────────────────────
    var S = {
        loaded: false,        // accounts fetched at least once
        accounts: [],
        accountId: '',
        stack: [],            // breadcrumb: [{id, name}], [0] is My Drive
        files: [],
        nextToken: null,
        query: '',
        filtered: null,       // != null = đang lọc nhanh tại chỗ theo ô tìm chung
        busy: false,
    };
    try { S.accountId = localStorage.getItem('fm_drive_account') || ''; } catch (e) {}

    function currentFolder() {
        return S.stack.length ? S.stack[S.stack.length - 1] : { id: 'root', name: tr('fm.drive.root') };
    }
    function credQS() {
        return S.accountId ? '&cred_id=' + encodeURIComponent(S.accountId) : '';
    }

    async function driveFetch(method, path, body) {
        var base = await window.FM.featBase();
        var opts = { method: method, headers: { 'Content-Type': 'application/json' } };
        if (body) opts.body = JSON.stringify(body);
        var res = await fetch(apiOrigin() + base + '/drive' + path, opts);
        var data = null;
        try { data = await res.json(); } catch (e) { /* non-JSON error body */ }
        if (!res.ok) {
            var msg = (data && (data.detail || data.error)) || ('HTTP ' + res.status);
            throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
        }
        return data;
    }

    // Hộp thoại DÙNG CHUNG với phần local (window.prompt/confirm trần trông
    // như lỗi trình duyệt trong iframe canvas). Rơi về prompt gốc chỉ khi
    // file_manager.js chưa nạp xong — không bao giờ để thao tác chết câm.
    function askText(title, initial) {
        if (window.FM && window.FM.promptDialog) return window.FM.promptDialog(title, initial || '');
        return Promise.resolve(window.prompt(title, initial || ''));
    }
    function askConfirm(title, danger) {
        if (window.FM && window.FM.confirmDialog) return window.FM.confirmDialog({ title: title, danger: !!danger });
        return Promise.resolve(window.confirm(title));
    }

    // ── Rendering ─────────────────────────────────────────────────────

    function setState(msg) {
        var el = byId('fm-drive-state');
        if (!el) return;
        el.hidden = !msg;
        el.textContent = msg || '';
    }

    // Dropdown tài khoản ĐÃ BỎ: sidebar là nơi chọn duy nhất (bug cũ: đổi qua
    // dropdown không gọi renderRail nên highlight sidebar đứng ở tài khoản cũ).
    function renderAccounts() {
        var noauth = byId('fm-drive-noauth');
        if (noauth) noauth.hidden = S.accounts.length > 0;
        var card = byId('fm-drive-listcard');
        if (card) card.hidden = S.accounts.length === 0;
        renderRail();
    }

    // The left-rail Google Drive shortcut: one row per authorized account.
    function renderRail() {
        var rail = byId('fm-drive-rail');
        if (!rail) return;
        rail.innerHTML = S.accounts.map(function (a) {
            var label = a.email || a.name || a.id;
            var active = a.id === S.accountId ? ' is-active' : '';
            var ro = a.readonly ? '<span class="fm-drive-badge">' + esc(tr('fm.drive.readonly_badge')) + '</span>' : '';
            return '<button type="button" class="fm-rail-item fm-drive-rail-item' + active + '"' +
                ' data-fm-action="drive-pick-account" data-account-id="' + esc(a.id) + '"' +
                ' title="' + esc(label) + '">' +
                '<svg class="fm-ico" aria-hidden="true"><use href="#i-user"/></svg>' +
                '<span class="fm-rail-item-label">' + esc(label) + '</span>' + ro + '</button>';
        }).join('');
        var note = byId('fm-drive-rail-note');
        if (note) note.hidden = S.accounts.length > 0;
    }

    // Switch to a specific account and show the Drive tab.
    function selectAccount(id, openTab) {
        if (id && id !== S.accountId) {
            S.accountId = id;
            try { localStorage.setItem('fm_drive_account', S.accountId); } catch (e) {}
            S.stack = [{ id: 'root', name: tr('fm.drive.root') }];
        }
        if (window.FMSearch) { window.FMSearch.clear(); window.FMSearch.refreshScopeLabel(); }
        renderRail();
        if (window.FMSearch && window.FMSearch.paintPlace) setTimeout(window.FMSearch.paintPlace, 0);
        if (openTab && window.FMActions && typeof window.FMActions.setView === 'function') {
            window.FMActions.setView('drive');
        }
        return loadList();
    }

    function renderCrumbs() {
        var nav = byId('fm-drive-crumbs');
        if (!nav) return;
        var parts = [];
        S.stack.forEach(function (c, i) {
            if (i) parts.push('<span class="fm-drive-crumb-sep">›</span>');
            var last = i === S.stack.length - 1;
            parts.push('<button type="button" class="fm-drive-crumb" data-fm-action="drive-crumb" data-idx="' + i + '"' +
                (last ? ' aria-current="page"' : '') + '>' + esc(c.name || c.id) + '</button>');
        });
        nav.innerHTML = parts.join('');
    }

    function rowActions(f) {
        var id = ' data-id="' + esc(f.id) + '" data-name="' + esc(f.name) + '"' +
            (f.url ? ' data-url="' + esc(f.url) + '"' : '');
        var b = [];
        if (!f.is_folder) {
            b.push('<button type="button" class="fm-icon-btn" data-fm-action="drive-dl"' + id +
                ' title="' + esc(tr('fm.drive.download')) + '"><svg class="fm-ico" aria-hidden="true"><use href="#i-download"/></svg></button>');
        }
        b.push('<button type="button" class="fm-icon-btn" data-fm-action="drive-share"' + id +
            ' title="' + esc(tr('fm.drive.share')) + '"><svg class="fm-ico" aria-hidden="true"><use href="#i-share"/></svg></button>');
        b.push('<button type="button" class="fm-icon-btn" data-fm-action="drive-rename"' + id +
            ' title="' + esc(tr('fm.drive.rename')) + '"><svg class="fm-ico" aria-hidden="true"><use href="#i-edit"/></svg></button>');
        if (f.url) {
            b.push('<button type="button" class="fm-icon-btn" data-fm-action="drive-ext"' + id +
                ' title="' + esc(tr('fm.drive.open')) + '"><svg class="fm-ico" aria-hidden="true"><use href="#i-external"/></svg></button>');
        }
        b.push('<button type="button" class="fm-icon-btn" data-fm-action="drive-trash"' + id +
            ' title="' + esc(tr('fm.drive.delete')) + '"><svg class="fm-ico" aria-hidden="true"><use href="#i-trash"/></svg></button>');
        return '<span class="fm-drive-row-actions">' + b.join('') + '</span>';
    }

    // Kiểu xem lấy từ FM (một công tắc trên header cho cả hai nguồn) — trước
    // đây Drive luôn là bảng nên bấm "lưới" xong sang Drive thấy vẫn danh sách.
    function viewMode() {
        return (window.FM && window.FM.viewMode) === 'list' ? 'list' : 'grid';
    }

    function renderGrid(rows) {
        var grid = byId('fm-drive-grid');
        if (!grid) return;
        grid.innerHTML = rows.map(function (f) {
            var icon = f.is_folder ? '#i-folder' : '#i-file';
            var cls = f.is_folder ? 'folder' : 'file';
            // KHÔNG gắn data-fm-action: một cú bấm chỉ CHỌN. Mở là nháy đúp,
            // menu là chuột phải — đúng nếp Google Drive/Finder.
            return '<div class="fm-file-card fm-drive-item"' +
                ' data-id="' + esc(f.id) + '" data-name="' + esc(f.name) + '"' +
                ' data-folder="' + (f.is_folder ? '1' : '0') + '"' +
                (f.url ? ' data-url="' + esc(f.url) + '"' : '') +
                ' title="' + esc(f.name) + '">' +
                '<span class="fm-file-icon ' + cls + '"><svg class="fm-ico" aria-hidden="true"><use href="' + icon + '"/></svg></span>' +
                '<span class="fm-file-name">' + esc(f.name) + '</span>' +
                (f.is_folder ? '' : '<span class="fm-file-size">' + esc(fmtBytes(f.size)) + '</span>') +
                '</div>';
        }).join('');
    }

    function renderList(append) {
        var body = byId('fm-drive-body');
        if (!body) return;
        // S.filtered != null = đang lọc nhanh tại chỗ (ô tìm hợp nhất gõ chữ).
        var rows = S.filtered || S.files;
        if (window.FMSearch && window.FMSearch.applyBrowse) rows = window.FMSearch.applyBrowse(rows);
        var grid = viewMode() === 'grid';
        var gridEl = byId('fm-drive-grid'), tableEl = byId('fm-drive-tablewrap');
        if (gridEl) gridEl.hidden = !grid;
        if (tableEl) tableEl.hidden = grid;
        if (grid) renderGrid(rows);
        var html = rows.map(function (f) {
            var icon = f.is_folder ? '#i-folder' : '#i-file';
            var nameBtn = '<button type="button" class="fm-drive-name-btn fm-drive-item"' +
                ' data-id="' + esc(f.id) + '" data-name="' + esc(f.name) + '"' +
                ' data-folder="' + (f.is_folder ? '1' : '0') + '"' +
                (f.url ? ' data-url="' + esc(f.url) + '"' : '') + '>' +
                '<svg class="fm-ico" aria-hidden="true"><use href="' + icon + '"/></svg>' +
                '<span>' + esc(f.name) + '</span></button>';
            return '<tr><td>' + nameBtn + '</td>' +
                '<td class="fm-num">' + (f.is_folder ? '—' : fmtBytes(f.size)) + '</td>' +
                '<td>' + esc(fmtDate(f.modified)) + '</td>' +
                '<td>' + rowActions(f) + '</td></tr>';
        }).join('');
        body.innerHTML = html;
        var empty = byId('fm-drive-empty');
        if (empty) empty.hidden = rows.length > 0;
        var more = byId('fm-drive-more');
        if (more) more.hidden = !S.nextToken;
    }

    // ── Data loading ──────────────────────────────────────────────────

    async function loadAccounts() {
        var data = await driveFetch('GET', '/accounts');
        S.accounts = (data && data.accounts) || [];
        if (S.accounts.length && !S.accounts.some(function (a) { return a.id === S.accountId; })) {
            S.accountId = S.accounts[0].id;
        }
        renderAccounts();
    }

    async function loadList(opts) {
        S.filtered = null;   // tải lại danh sách = bỏ lọc nhanh cũ
        opts = opts || {};
        if (S.busy) return;
        S.busy = true;
        setState(tr('fm.drive.loading'));
        try {
            var folder = currentFolder();
            var qs = '?folder_id=' + encodeURIComponent(folder.id) + credQS() + '&page_size=100';
            if (S.query) qs += '&q=' + encodeURIComponent(S.query);
            if (opts.pageToken) qs += '&page_token=' + encodeURIComponent(opts.pageToken);
            var data = await driveFetch('GET', '/list' + qs);
            var files = (data && data.files) || [];
            S.files = opts.pageToken ? S.files.concat(files) : files;
            S.nextToken = data && data.next_page_token;
            renderCrumbs();
            renderList();
            setState('');
        } catch (e) {
            setState('');
            toast(String(e.message || e), 'error');
        } finally {
            S.busy = false;
        }
    }

    async function ensureLoaded(force) {
        if (S.loaded && !force) return;
        try {
            await loadAccounts();
        } catch (e) {
            toast(String(e.message || e), 'error');
            return;
        }
        S.loaded = true;
        if (!S.stack.length) S.stack = [{ id: 'root', name: tr('fm.drive.root') }];
        if (S.accounts.length) await loadList();
    }

    // ── Uploads ───────────────────────────────────────────────────────

    async function uploadFiles(fileList) {
        var files = Array.prototype.slice.call(fileList || []);
        if (!files.length) return;
        var base = await window.FM.featBase();
        var folder = currentFolder();
        var done = 0;
        for (var i = 0; i < files.length; i++) {
            var f = files[i];
            toast(tr('fm.drive.uploading', { name: f.name, i: i + 1, n: files.length }), 'info');
            var url = apiOrigin() + base + '/drive/upload-content' +
                '?name=' + encodeURIComponent(f.name) +
                '&folder_id=' + encodeURIComponent(folder.id) + credQS();
            var res = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/octet-stream', 'X-File-Type': f.type || 'application/octet-stream' },
                body: f,
            });
            if (!res.ok) {
                var msg = 'HTTP ' + res.status;
                try { var d = await res.json(); msg = d.detail || msg; } catch (e) {}
                toast(String(msg), 'error');
            } else {
                done++;
            }
        }
        if (done) toast(tr('fm.drive.upload_done', { n: done }), 'success');
        loadList();
    }

    // ── Actions ───────────────────────────────────────────────────────

    function needAccount() {
        if (!S.accounts.length) {
            var noauth = byId('fm-drive-noauth');
            if (noauth) noauth.hidden = false;
            return true;
        }
        return false;
    }

    var ACTIONS = {
        'drive-refresh': function () { return ensureLoaded(true); },

        'drive-open': function (el) {
            if (el.getAttribute('data-folder') === '1') {
                S.query = '';
                if (window.FMSearch) window.FMSearch.clear();
                S.stack.push({ id: el.getAttribute('data-id'), name: el.getAttribute('data-name') });
                return loadList();
            }
            var url = el.getAttribute('data-url');
            if (url) window.open(url, '_blank', 'noopener');
        },

        'drive-crumb': function (el) {
            var idx = parseInt(el.getAttribute('data-idx'), 10);
            if (isNaN(idx) || idx >= S.stack.length - 1) return;
            // Xoá query TRƯỚC khi load: thiếu dòng này thì loadList vẫn chạy
            // tìm-toàn-Drive nên bấm breadcrumb trông như nút chết.
            S.query = '';
            if (window.FMSearch) window.FMSearch.clear();
            S.stack = S.stack.slice(0, idx + 1);
            return loadList();
        },

        'dmenu-open': function () { hideDriveMenu(); var el = selectedEl(); if (el) openItem(el); },
        'dmenu-download': function () { hideDriveMenu(); var el = selectedEl(); if (el) ACTIONS['drive-dl'](el); },
        'dmenu-rename': function () { hideDriveMenu(); var el = selectedEl(); if (el) return ACTIONS['drive-rename'](el); },
        'dmenu-share': function () { hideDriveMenu(); var el = selectedEl(); if (el) return ACTIONS['drive-share'](el); },
        'dmenu-trash': function () { hideDriveMenu(); var el = selectedEl(); if (el) return ACTIONS['drive-trash'](el); },

        'drive-more': function () {
            if (S.nextToken) return loadList({ pageToken: S.nextToken });
        },

        'drive-upload': function () {
            if (needAccount()) return;
            var input = byId('fm-drive-file-input');
            if (input) input.click();
        },

        'drive-mkdir': async function () {
            if (needAccount()) return;
            var name = await askText(tr('fm.drive.mkdir_prompt'));
            if (!name || !name.trim()) return;
            await driveFetch('POST', '/mkdir', {
                name: name.trim(), parent_id: currentFolder().id, cred_id: S.accountId || null,
            });
            return loadList();
        },

        'drive-dl': async function (el) {
            var base = await window.FM.featBase();
            var a = document.createElement('a');
            a.href = apiOrigin() + base + '/drive/fetch?file_id=' +
                encodeURIComponent(el.getAttribute('data-id')) + credQS();
            // download hints the browser to save (same-origin, so it is honoured);
            // target=_blank means an ERROR response (plain JSON, no
            // Content-Disposition) opens a throwaway tab instead of navigating
            // the whole File Manager away to raw JSON.
            a.download = el.getAttribute('data-name') || '';
            a.target = '_blank';
            a.rel = 'noopener';
            document.body.appendChild(a);
            a.click();
            a.remove();
        },

        'drive-share': async function (el) {
            var email = await askText(tr('fm.drive.share_choice'), '');
            if (email === null) return;
            email = email.trim();
            var data = await driveFetch('POST', '/share', {
                file_id: el.getAttribute('data-id'),
                cred_id: S.accountId || null,
                type: email ? 'user' : 'anyone',
                role: 'reader',
                email: email,
            });
            if (email) {
                toast(tr('fm.drive.shared_user', { email: email }), 'success');
            } else {
                var url = (data && data.file && data.file.url) || el.getAttribute('data-url') || '';
                var copied = false;
                if (url && navigator.clipboard && navigator.clipboard.writeText) {
                    try { await navigator.clipboard.writeText(url); copied = true; } catch (e) {}
                }
                // navigator.clipboard only exists in secure contexts (https or
                // localhost); on http://<LAN-IP> it is absent, so don't claim a
                // copy that never happened — show the link to copy by hand.
                if (copied) toast(tr('fm.drive.share_anyone'), 'success');
                else toast(tr('fm.drive.share_anyone_link', { url: url }), 'success');
            }
        },

        'drive-rename': async function (el) {
            var name = await askText(tr('fm.drive.rename_prompt'), el.getAttribute('data-name') || '');
            if (!name || !name.trim()) return;
            var data = await driveFetch('POST', '/rename', {
                file_id: el.getAttribute('data-id'), new_name: name.trim(), cred_id: S.accountId || null,
            });
            toast(tr('fm.drive.renamed', { name: (data.file && data.file.name) || name.trim() }), 'success');
            return loadList();
        },

        'drive-trash': async function (el) {
            var name = el.getAttribute('data-name') || '';
            if (!(await askConfirm(tr('fm.drive.confirm_trash', { name: name }), true))) return;
            await driveFetch('POST', '/trash', {
                file_id: el.getAttribute('data-id'), cred_id: S.accountId || null,
            });
            toast(tr('fm.drive.trashed', { name: name }), 'success');
            return loadList();
        },

        'drive-ext': function (el) {
            var url = el.getAttribute('data-url');
            if (url) window.open(url, '_blank', 'noopener');
        },

        'drive-pick-account': function (el) {
            if (needAccount()) return;
            return selectAccount(el.getAttribute('data-account-id'), true);
        },
    };

    // ── Chọn · mở · menu chuột phải ───────────────────────────────────
    var selectedId = '';

    function itemOf(el) {
        var id = el.getAttribute('data-id');
        for (var i = 0; i < S.files.length; i++) {
            if (String(S.files[i].id) === String(id)) return S.files[i];
        }
        return { id: id, name: el.getAttribute('data-name') || '', url: el.getAttribute('data-url') || '',
                 is_folder: el.getAttribute('data-folder') === '1' };
    }

    function markSelected(el) {
        Array.prototype.forEach.call(document.querySelectorAll('.fm-drive-item.is-selected, #fm-drive-body tr.is-selected'),
            function (x) { x.classList.remove('is-selected'); });
        if (!el) { selectedId = ''; return; }
        selectedId = el.getAttribute('data-id') || '';
        el.classList.add('is-selected');
        var tr = el.closest ? el.closest('tr') : null;
        if (tr) tr.classList.add('is-selected');
    }

    function openItem(el) {
        var f = itemOf(el);
        if (el.getAttribute('data-folder') === '1') {
            S.query = '';
            if (window.FMSearch) window.FMSearch.clear();
            S.stack.push({ id: el.getAttribute('data-id'), name: el.getAttribute('data-name') });
            return loadList();
        }
        var url = f.url || el.getAttribute('data-url');
        if (url) window.open(url, '_blank', 'noopener');
    }

    function hideDriveMenu() {
        var m = byId('fm-drive-menu');
        if (m) m.hidden = true;
    }

    function showDriveMenu(e, el) {
        var m = byId('fm-drive-menu');
        if (!m) return;
        markSelected(el);
        var f = itemOf(el);
        // Thư mục Drive không tải về được — ẩn mục đó thay vì để bấm rồi lỗi.
        var dl = m.querySelector('[data-fm-action="dmenu-download"]');
        if (dl) dl.hidden = !!f.is_folder;
        m.hidden = false;
        // Đặt trong khung nhìn: mở sát mép phải/đáy thì lật ngược lại.
        var r = m.getBoundingClientRect();
        var x = Math.min(e.clientX, window.innerWidth - r.width - 8);
        var y = Math.min(e.clientY, window.innerHeight - r.height - 8);
        m.style.left = Math.max(4, x) + 'px';
        m.style.top = Math.max(4, y) + 'px';
    }

    function selectedEl() {
        return document.querySelector('.fm-drive-item.is-selected') ||
               (selectedId ? document.querySelector('.fm-drive-item[data-id="' + selectedId + '"]') : null);
    }

    // ── Wiring ────────────────────────────────────────────────────────

    function registerWhenReady(tries) {
        if (window.FMActions && typeof window.FMActions.register === 'function') {
            window.FMActions.register(ACTIONS, 'fm_drive');
            return;
        }
        if (tries > 100) { console.error(LOG + 'FMActions never appeared; drive tab dead.'); return; }
        setTimeout(function () { registerWhenReady(tries + 1); }, 50);
    }
    registerWhenReady(0);

        // API công khai cho ô tìm hợp nhất (fm_search.js). Giữ hẹp: chỉ đủ để
        // tìm, lọc tại chỗ và mở một thư mục — không lộ state ra ngoài.
        window.FMDrive = {
            accounts: function () { return S.accounts.slice(); },
            accountId: function () { return S.accountId; },
            folderId: function () { var f = currentFolder(); return f && f.id !== 'root' ? f.id : ''; },
            search: async function (q, credId, folderId) {
                var qs = '?q=' + encodeURIComponent(q) +
                    (credId ? '&cred_id=' + encodeURIComponent(credId) : '') +
                    (folderId ? '&folder_id=' + encodeURIComponent(folderId) : '');
                var data = await driveFetch('GET', '/list' + qs);
                return (data && data.files) || [];
            },
            // Lọc nhanh danh sách ĐANG hiện (không gọi mạng) — cùng luật với local.
            filter: function (q) {
                var qq = String(q || '').toLowerCase();
                if (!qq) { S.filtered = null; renderList(); return; }
                S.filtered = S.files.filter(function (f) {
                    return String(f.name || '').toLowerCase().indexOf(qq) !== -1;
                });
                renderList();
            },
            rerender: function () { try { renderList(); } catch (e) {} },
            openFolder: function (credId, folderId, name) {
                if (credId && credId !== S.accountId) return selectAccount(credId, true).then(function () {
                    S.stack.push({ id: folderId, name: name || '' });
                    return loadList();
                });
                S.stack.push({ id: folderId, name: name || '' });
                if (window.FMActions) window.FMActions.setView('drive');
                return loadList();
            },
        };

    document.addEventListener('fm:view-change', function (e) {
        if (e.detail && e.detail.view === 'drive') ensureLoaded(false);
    });

    // Populate the sidebar Drive shortcut on page load (only /accounts, no Drive
    // list call) so accounts show as folders as soon as File Manager appears.
    function initRail() {
        loadAccounts().then(function () {
            if (!S.stack.length) S.stack = [{ id: 'root', name: tr('fm.drive.root') }];
        }).catch(function () { /* no accounts / offline — rail note handles it */ });
    }

    document.addEventListener('DOMContentLoaded', function () {
        initRail();
        // Bấm = chọn; nháy đúp = mở; chuột phải = menu. Đặt ở document để
        // ăn cả bảng lẫn lưới, kể cả khi hai bên vẽ lại.
        document.addEventListener('click', function (e) {
            var el = e.target.closest ? e.target.closest('.fm-drive-item') : null;
            if (el) { markSelected(el); return; }
            if (!(e.target.closest && e.target.closest('#fm-drive-menu'))) hideDriveMenu();
        });
        document.addEventListener('dblclick', function (e) {
            var el = e.target.closest ? e.target.closest('.fm-drive-item') : null;
            if (el) { e.preventDefault(); openItem(el); }
        });
        document.addEventListener('contextmenu', function (e) {
            var el = e.target.closest ? e.target.closest('.fm-drive-item') : null;
            if (!el) return;
            e.preventDefault();
            showDriveMenu(e, el);
        });
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') hideDriveMenu();
        });

        var input = byId('fm-drive-file-input');
        if (input) {
            input.addEventListener('change', function () {
                uploadFiles(input.files).catch(function (e) { toast(String(e.message || e), 'error'); });
                input.value = '';
            });
        }

        // Kéo file Google Drive ra canvas Flow (giao thức chung như file local): pointer
        // capture + stream vị trí. FileRef source='drive' + drive_id + cred_id (không có path
        // VPS) — cloud xem trực tiếp qua /drive/fetch; thả vào agent/extension thì cloud tải
        // về VPS trước. Không kéo thư mục.
        var drvDrag = null;
        document.addEventListener('pointerdown', function (e) {
            if (e.button !== 0) return;
            // .fm-drive-item = nút tên trong bảng HOẶC thẻ trong lưới — trước
            // đây chỉ bảng kéo được, lưới thì kéo không ra gì.
            var btn = e.target.closest ? e.target.closest('.fm-drive-item') : null;
            if (!btn || btn.getAttribute('data-folder') === '1') return;
            var fid = btn.getAttribute('data-id');
            var f = null;
            for (var i = 0; i < S.files.length; i++) { if (String(S.files[i].id) === String(fid)) { f = S.files[i]; break; } }
            var nm = btn.getAttribute('data-name') || (f && f.name) || 'file';
            drvDrag = {
                id: e.pointerId, el: btn, x: e.clientX, y: e.clientY, started: false,
                ref: {
                    v: 1, source: 'drive', path: '', drive_id: fid, cred_id: S.accountId || null,
                    name: nm, ext: (nm.indexOf('.') >= 0 ? nm.split('.').pop() : null),
                    size: (f && f.size != null ? Number(f.size) : null),
                    // Canvas cần hai thứ này để nhận ra BẢNG TÍNH Google và dựng
                    // thẳng node Sheet (khỏi dán link): loại file + link mở được.
                    mime_type: (f && f.mime_type) || null,
                    url: (f && f.url) || btn.getAttribute('data-url') || null
                }
            };
        });
        window.addEventListener('pointermove', function (e) {
            if (!drvDrag || e.pointerId !== drvDrag.id) return;
            if (!drvDrag.started) {
                if (Math.abs(e.clientX - drvDrag.x) + Math.abs(e.clientY - drvDrag.y) < 6) return;
                drvDrag.started = true;
                try { drvDrag.el.setPointerCapture(drvDrag.id); } catch (x) {}
                document.body.style.userSelect = 'none';
                document.body.style.cursor = 'grabbing';
                try { window.parent.postMessage({ type: 'tubecli-fm-drag', ref: drvDrag.ref }, '*'); } catch (x) {}
            }
            try { window.parent.postMessage({ type: 'tubecli-fm-move', ix: e.clientX, iy: e.clientY }, '*'); } catch (x) {}
        });
        window.addEventListener('pointerup', function (e) {
            if (!drvDrag || e.pointerId !== drvDrag.id) return;
            var started = drvDrag.started, el = drvDrag.el, id = drvDrag.id;
            drvDrag = null;
            document.body.style.userSelect = ''; document.body.style.cursor = '';
            try { el.releasePointerCapture(id); } catch (x) {}
            if (started) { try { window.parent.postMessage({ type: 'tubecli-fm-drop', ix: e.clientX, iy: e.clientY }, '*'); } catch (x) {} }
        });
    });
})();
