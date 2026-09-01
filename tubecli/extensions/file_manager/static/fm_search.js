/**
 * fm_search.js — MỘT ô tìm kiếm cho cả máy chủ lẫn mọi tài khoản Google Drive
 * (phương án "Tìm trước, duyệt sau").
 *
 * Vì sao có file này: trước đây có HAI ô tìm rời rạc, khác cả ngữ nghĩa lẫn
 * hành vi phím — ô header lọc client trong thư mục local (Enter = /search đệ
 * quy), ô trong pane Drive chỉ Enter và tìm TOÀN Drive bỏ qua thư mục đang
 * đứng. Tệ nhất: gõ vào ô header khi đang xem Drive thì nó lọc lưới local đang
 * display:none — người dùng gõ mà không có gì xảy ra.
 *
 * Luật thống nhất ở đây:
 *   GÕ    → lọc nhanh ngay trong danh sách ĐANG XEM (local hay Drive tuỳ view).
 *   ENTER → tìm sâu theo PHẠM VI đang chọn, kết quả gộp theo nguồn, mỗi dòng
 *           mang huy hiệu nguồn + đường dẫn chứa nó.
 *   ESC / ✕ / bấm breadcrumb → thoát tìm (bug cũ: clearSearch() được viết ra
 *           nhưng không nơi nào gọi, kết quả tìm sâu dính vĩnh viễn).
 *
 * Module đứng NGOÀI file_manager.js/fm_drive.js và chỉ gọi API công khai của
 * chúng (window.FM, window.FMDrive), nên không phải mổ hai file lớn đó.
 */
(function () {
    'use strict';

    function byId(id) { return document.getElementById(id); }
    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
        });
    }
    function T(key, vars) {
        if (window.FM && typeof window.FM.t === 'function') return window.FM.t(key, vars);
        return key;
    }
    function toast(msg, kind) {
        if (window.FM && typeof window.FM.toast === 'function') return window.FM.toast(msg, kind);
    }

    // ── Trạng thái ────────────────────────────────────────────────────
    var S = {
        scope: 'folder',     // folder | server | drive | all
        query: '',
        active: false,       // đang ở màn hình kết quả tìm sâu
        rows: [],            // kết quả đã chuẩn hoá
        filters: { kind: '', time: '', size: '' },
        busy: false,
    };

    // Loại tệp → nhóm cho chip lọc. Chỉ vài nhóm dân văn phòng thật sự dùng.
    var KIND_EXT = {
        doc: ['doc', 'docx', 'pdf', 'txt', 'rtf', 'odt', 'md', 'xls', 'xlsx', 'csv', 'ods', 'ppt', 'pptx', 'zip', 'rar', '7z', 'tar', 'gz'],
        sheet: ['xls', 'xlsx', 'csv', 'ods'],
        image: ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'bmp', 'heic'],
        video: ['mp4', 'mov', 'mkv', 'avi', 'webm', 'flv', 'm4v', 'wmv', 'ts', 'mpg', 'mpeg'],
        audio: ['mp3', 'wav', 'flac', 'aac', 'm4a', 'ogg', 'wma', 'opus'],
    };
    var KIND_MIME = {
        doc: ['document', 'pdf', 'text'],
        sheet: ['spreadsheet', 'csv'],
        image: ['image'],
        video: ['video'],
        audio: ['audio'],
    };

    function extOf(name) {
        var m = String(name || '').toLowerCase().match(/\.([a-z0-9]+)$/);
        return m ? m[1] : '';
    }
    function kindOf(row) {
        if (row.isDir) return 'folder';
        if (row.mime) {
            for (var k in KIND_MIME) {
                for (var i = 0; i < KIND_MIME[k].length; i++) {
                    if (row.mime.indexOf(KIND_MIME[k][i]) !== -1) return k;
                }
            }
        }
        var e = extOf(row.name);
        for (var k2 in KIND_EXT) if (KIND_EXT[k2].indexOf(e) !== -1) return k2;
        return 'other';
    }

    // ── Phạm vi ───────────────────────────────────────────────────────
    function driveAccounts() {
        var D = window.FMDrive;
        return (D && D.accounts && D.accounts()) || [];
    }
    function currentAccount() {
        var D = window.FMDrive;
        var id = D && D.accountId && D.accountId();
        var list = driveAccounts();
        for (var i = 0; i < list.length; i++) if (list[i].id === id) return list[i];
        return list[0] || null;
    }
    function accountLabel(a) { return a ? (a.email || a.name || a.id) : ''; }
    function inDriveView() {
        var root = byId('fm-app');
        return !!root && root.getAttribute('data-view') === 'drive';
    }
    function scopeLabel(scope) {
        var acc = currentAccount();
        if (scope === 'folder') return T('fm.scope_folder');
        if (scope === 'server') return T('fm.scope_server');
        if (scope === 'drive') return acc ? T('fm.scope_drive_acc', { email: accountLabel(acc) }) : T('fm.scope_drive');
        return T('fm.scope_all');
    }
    // Phạm vi mặc định bám theo chỗ người dùng đang đứng: đang duyệt thư mục
    // nào thì "Thư mục này" nghĩa là đúng thư mục đó (local hay Drive).
    function defaultScope() { return 'folder'; }

    // ── Chuẩn hoá một dòng kết quả ────────────────────────────────────
    function localRow(m) {
        var p = String(m.path || '');
        var dir = p.replace(/\\/g, '/').replace(/\/[^/]*$/, '') || '/';
        return {
            source: 'local', name: m.name || p.split(/[\\/]/).pop(), path: p, dir: dir,
            isDir: !!(m.is_dir || m.isDir || m.type === 'dir'),
            size: Number(m.size || 0), mtime: m.modified || m.mtime || '',
            mime: '', raw: m,
        };
    }
    function driveRow(f, acc) {
        return {
            source: 'drive', accountId: acc.id, accountLabel: accountLabel(acc),
            name: f.name || '', path: '', dir: T('fm.drive.root'),
            isDir: String(f.mimeType || '').indexOf('folder') !== -1,
            size: Number(f.size || 0), mtime: f.modifiedTime || '',
            mime: String(f.mimeType || ''), id: f.id, url: f.webViewLink || '', raw: f,
        };
    }

    // ── Tìm sâu theo phạm vi ──────────────────────────────────────────
    async function searchLocal(q, path) {
        var FM = window.FM;
        if (!FM || typeof FM.api !== 'function') return [];
        var base = path || FM.currentPath || '/';
        var data = await FM.api('GET', '/search?path=' + encodeURIComponent(base) +
            '&pattern=' + encodeURIComponent('*' + q + '*') + '&recursive=true');
        var matches = (data && data.matches) || [];
        if (matches.length >= 200) toast(T('fm.search_capped'), 'warn');
        return matches.map(localRow);
    }
    async function searchDrive(q, acc, folderId) {
        var D = window.FMDrive;
        if (!D || typeof D.search !== 'function' || !acc) return [];
        var files = await D.search(q, acc.id, folderId);
        return (files || []).map(function (f) { return driveRow(f, acc); });
    }

    async function runDeep() {
        var q = S.query.trim();
        if (!q) return;
        S.busy = true; S.active = true;
        render();
        var jobs = [];
        var D = window.FMDrive;
        var driveFolder = (D && D.folderId && D.folderId()) || '';
        if (S.scope === 'folder') {
            // "Thư mục này" = đúng nơi đang đứng, kể cả khi đó là thư mục Drive.
            if (inDriveView()) jobs.push(searchDrive(q, currentAccount(), driveFolder));
            else jobs.push(searchLocal(q, null));
        } else if (S.scope === 'server') {
            jobs.push(searchLocal(q, '/'));
        } else if (S.scope === 'drive') {
            jobs.push(searchDrive(q, currentAccount(), ''));
        } else {
            // "Mọi nơi": chạy song song, MỖI NGUỒN LỖI RIÊNG — một tài khoản
            // Drive hết hạn token không được phép nuốt cả trang kết quả.
            jobs.push(searchLocal(q, '/'));
            driveAccounts().forEach(function (a) { jobs.push(searchDrive(q, a, '')); });
        }
        var settled = await Promise.allSettled(jobs);
        var rows = [], errs = [];
        settled.forEach(function (r) {
            if (r.status === 'fulfilled') rows = rows.concat(r.value || []);
            else errs.push(String((r.reason && r.reason.message) || r.reason));
        });
        S.rows = rows; S.errors = errs; S.busy = false;
        render();
    }

    // ── Lọc nhanh khi GÕ (không gọi mạng) ─────────────────────────────
    function quickFilter() {
        var q = S.query.trim().toLowerCase();
        if (inDriveView()) {
            var D = window.FMDrive;
            if (D && typeof D.filter === 'function') D.filter(q);
            return;
        }
        var FM = window.FM;
        if (!FM || !FM.items) return;
        if (!q) { FM.renderFiles(FM.items); return; }
        FM.renderFiles(FM.items.filter(function (i) {
            return String(i.name).toLowerCase().indexOf(q) !== -1;
        }));
    }

    // ── Lọc chip trên kết quả ─────────────────────────────────────────
    function passFilters(row) {
        var f = S.filters;
        if (f.kind && kindOf(row) !== f.kind) return false;
        if (f.size) {
            var mb = row.size / (1024 * 1024);
            if (f.size === 'sm' && mb >= 1) return false;
            if (f.size === 'md' && (mb < 1 || mb > 100)) return false;
            if (f.size === 'lg' && mb <= 100) return false;
        }
        if (f.time && row.mtime) {
            var t = Date.parse(row.mtime);
            if (!isNaN(t)) {
                var days = (Date.now() - t) / 86400000;
                if (f.time === 'd1' && days > 1) return false;
                if (f.time === 'd7' && days > 7) return false;
                if (f.time === 'd30' && days > 30) return false;
            }
        }
        return true;
    }

    // ── Render kết quả ────────────────────────────────────────────────
    function groupRows(rows) {
        var groups = [];
        var byKey = {};
        rows.forEach(function (r) {
            var key = r.source === 'local' ? 'local' : 'drive:' + r.accountId;
            if (!byKey[key]) {
                byKey[key] = { key: key, source: r.source, label: r.source === 'local' ? T('fm.src_server') : r.accountLabel, rows: [] };
                groups.push(byKey[key]);
            }
            byKey[key].rows.push(r);
        });
        return groups;
    }

    function rowHtml(r) {
        var badge = r.source === 'local'
            ? '<span class="fm-src fm-src-local">' + esc(T('fm.src_server')) + '</span>'
            : '<span class="fm-src fm-src-drive">Drive · ' + esc(r.accountLabel) + '</span>';
        var icon = r.isDir ? 'i-folder' : 'i-file';
        var where = esc(r.source === 'local' ? r.dir : (r.accountLabel + ' › ' + T('fm.drive.root')));
        var size = r.isDir ? '—' : (window.FM && window.FM.fmtSize ? window.FM.fmtSize(r.size) : (r.size || ''));
        return '<button type="button" class="fm-sr-row" data-fm-action="search-open"' +
            ' data-source="' + esc(r.source) + '"' +
            ' data-path="' + esc(r.path || '') + '"' +
            ' data-id="' + esc(r.id || '') + '"' +
            ' data-account="' + esc(r.accountId || '') + '"' +
            ' data-url="' + esc(r.url || '') + '"' +
            ' data-dir="' + (r.isDir ? '1' : '0') + '">' +
            '<svg class="fm-ico" aria-hidden="true"><use href="#' + icon + '"/></svg>' +
            '<span class="fm-sr-main"><span class="fm-sr-name">' + esc(r.name) + '</span>' +
            '<span class="fm-sr-where">' + where + '</span></span>' +
            badge +
            '<span class="fm-sr-size">' + esc(size) + '</span></button>';
    }

    function render() {
        var root = byId('fm-app');
        if (root) root.setAttribute('data-searching', S.active ? '1' : '0');
        var box = byId('fm-search-results');
        if (!box) return;
        var chips = byId('fm-search-filters');
        if (chips) chips.hidden = !S.active;
        if (!S.active) { box.innerHTML = ''; return; }
        if (S.busy) {
            box.innerHTML = '<div class="fm-sr-note">' + esc(T('fm.search_running')) + '</div>';
            return;
        }
        var rows = S.rows.filter(passFilters);
        var head = '<div class="fm-sr-head">' +
            esc(T('fm.search_results', { q: S.query, n: rows.length })) +
            ' · <span class="fm-sr-scope">' + esc(scopeLabel(S.scope)) + '</span></div>';
        var errHtml = (S.errors && S.errors.length)
            ? '<div class="fm-sr-err">' + S.errors.map(function (e) { return esc(e); }).join('<br>') + '</div>' : '';
        if (!rows.length) {
            box.innerHTML = head + errHtml + '<div class="fm-sr-note">' + esc(T('fm.search_empty')) + '</div>';
            return;
        }
        var html = head + errHtml;
        groupRows(rows).forEach(function (g) {
            html += '<div class="fm-sr-group"><div class="fm-sr-group-head">' + esc(g.label) +
                ' <span class="fm-sr-count">' + g.rows.length + '</span></div>' +
                g.rows.map(rowHtml).join('') + '</div>';
        });
        box.innerHTML = html;
    }

    // ── Điều khiển ────────────────────────────────────────────────────
    function setScope(scope) {
        S.scope = scope;
        var btn = byId('fm-scope-btn');
        if (btn) {
            var lab = btn.querySelector('.fm-scope-label');
            if (lab) lab.textContent = scopeLabel(scope);
        }
        var menu = byId('fm-scope-menu');
        if (menu) {
            menu.hidden = true;
            Array.prototype.forEach.call(menu.querySelectorAll('[data-scope]'), function (el) {
                el.classList.toggle('is-active', el.getAttribute('data-scope') === scope);
            });
        }
        if (S.active) runDeep();
    }

    function clearSearch() {
        S.query = ''; S.active = false; S.rows = []; S.errors = [];
        S.filters = { kind: '', time: '', size: '' };
        var input = byId('searchInput');
        if (input) input.value = '';
        var clr = byId('fm-search-clear');
        if (clr) clr.hidden = true;
        Array.prototype.forEach.call(document.querySelectorAll('#fm-search-filters .is-active'), function (el) {
            el.classList.remove('is-active');
        });
        render();
        // Trả danh sách đang xem về nguyên trạng — cả hai nguồn.
        if (inDriveView()) { var D = window.FMDrive; if (D && D.filter) D.filter(''); }
        else if (window.FM) { window.FM.searchResults = null; if (window.FM.items) window.FM.renderFiles(window.FM.items); }
    }

    function openRow(el) {
        var source = el.getAttribute('data-source');
        var isDir = el.getAttribute('data-dir') === '1';
        if (source === 'local') {
            var p = el.getAttribute('data-path');
            if (!p) return;
            var target = isDir ? p : p.replace(/\\/g, '/').replace(/\/[^/]*$/, '');
            clearSearch();
            if (window.FM && window.FM.navigate) window.FM.navigate(target || '/');
            return;
        }
        var D = window.FMDrive;
        var acc = el.getAttribute('data-account');
        if (isDir) {
            clearSearch();
            if (D && D.openFolder) D.openFolder(acc, el.getAttribute('data-id'), el.querySelector('.fm-sr-name').textContent);
            return;
        }
        var url = el.getAttribute('data-url');
        if (url) window.open(url, '_blank', 'noopener');
    }

    // ── Gắn sự kiện ───────────────────────────────────────────────────
    function debounce(fn, ms) {
        var t = null;
        return function () {
            var self = this, args = arguments;
            clearTimeout(t);
            t = setTimeout(function () { fn.apply(self, args); }, ms);
        };
    }

    function bind() {
        var input = byId('searchInput');
        if (!input) return;
        input.addEventListener('input', debounce(function () {
            S.query = input.value;
            var clr = byId('fm-search-clear');
            if (clr) clr.hidden = !S.query;
            // Xoá sạch chữ = thoát hẳn khỏi kết quả tìm sâu (bug cũ: dính mãi).
            if (!S.query.trim()) { clearSearch(); return; }
            if (!S.active) quickFilter();
        }, 200));
        input.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') { e.preventDefault(); S.query = input.value; runDeep(); }
            else if (e.key === 'Escape') { e.preventDefault(); clearSearch(); input.blur(); }
        });
        // Phím "/" đưa con trỏ vào ô tìm — trừ khi đang gõ trong ô khác.
        document.addEventListener('keydown', function (e) {
            if (e.key !== '/' || e.ctrlKey || e.metaKey || e.altKey) return;
            var t = e.target;
            if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
            e.preventDefault(); input.focus(); input.select();
        });
        document.addEventListener('click', function (e) {
            var menu = byId('fm-scope-menu');
            if (menu && !menu.hidden && !e.target.closest('.fm-scope')) menu.hidden = true;
        });
        setScope(defaultScope());
        syncBrowseChips();
        paintPlace();
        // Đổi view (tab hoặc bấm tài khoản Drive ở sidebar) → vẽ lại chỉ báo.
        document.addEventListener('fm:view-change', function () { setTimeout(paintPlace, 0); });
    }

    var ACTIONS = {
        'search-scope-toggle': function () {
            var menu = byId('fm-scope-menu');
            if (menu) menu.hidden = !menu.hidden;
        },
        'search-scope-pick': function (el) { setScope(el.getAttribute('data-scope')); },
        'search-clear': function () { clearSearch(); },
        'search-open': function (el) { openRow(el); },
        'browse-filter': function (el) {
            var v = el.getAttribute('data-value');
            B.kind = B.kind === v ? '' : v;
            repaintBrowse();
        },
        'browse-sort': function (el) {
            var v = el.getAttribute('data-sort');
            B.sort = B.sort === v ? '' : v;
            repaintBrowse();
        },
        'browse-reset': function () { B.kind = ''; B.sort = ''; repaintBrowse(); },
        'search-filter': function (el) {
            var group = el.getAttribute('data-filter');   // kind | time | size
            var val = el.getAttribute('data-value');
            S.filters[group] = S.filters[group] === val ? '' : val;
            Array.prototype.forEach.call(
                document.querySelectorAll('#fm-search-filters [data-filter="' + group + '"]'),
                function (b) { b.classList.toggle('is-active', b.getAttribute('data-value') === S.filters[group]); });
            render();
        },
    };

    document.addEventListener('DOMContentLoaded', function () {
        bind();
        if (window.FMActions && typeof window.FMActions.register === 'function') {
            window.FMActions.register(ACTIONS, 'fm_search');
        }
    });

    // Điều hướng bất kỳ (bấm breadcrumb, mở thư mục, đổi tài khoản) phải thoát
    // trạng thái tìm — nếu không, danh sách bên dưới đổi mà màn hình vẫn đứng ở
    // kết quả cũ, đúng cái làm breadcrumb trông như nút chết.
    // ── "Đang ở đâu" ──────────────────────────────────────────────────
    // Một chỗ duy nhất quyết định: chip nguồn cạnh breadcrumb, mục sidebar
    // sáng lên, và breadcrumb local ẩn đi khi đang ở Drive (trước đây nó vẫn
    // chỉ đường dẫn máy chủ trong lúc màn hình hiện nội dung Drive).
    function paintPlace() {
        var drive = inDriveView();
        var chip = byId('fm-place'), label = byId('fm-place-label'), ico = byId('fm-place-ico');
        if (chip) chip.setAttribute('data-source', drive ? 'drive' : 'local');
        if (ico) ico.setAttribute('href', drive ? '#i-cloud' : '#i-hard-drive');
        if (label) {
            var acc = currentAccount();
            label.textContent = drive
                ? (acc ? accountLabel(acc) : T('fm.place_drive'))
                : T('fm.place_local');
        }
        var crumb = byId('breadcrumb');
        if (crumb) crumb.hidden = drive;
        // Sidebar: mục "Google Drive" sáng khi đang ở Drive; các mục Truy cập
        // nhanh chỉ sáng khi đang ở máy chủ.
        var head = byId('fm-rail-drive-head');
        if (head) head.classList.toggle('is-active', drive && !currentAccount());
        if (drive) {
            Array.prototype.forEach.call(document.querySelectorAll('#quickAccess .fm-rail-item'), function (el) {
                el.classList.remove('is-active', 'active');
            });
        } else {
            Array.prototype.forEach.call(document.querySelectorAll('.fm-drive-rail-item'), function (el) {
                el.classList.remove('is-active');
            });
        }
    }

    // ── LỌC + SẮP XẾP KHI DUYỆT ───────────────────────────────────────
    // Khác hàng chip của màn hình tìm: cái này áp lên danh sách ĐANG DUYỆT,
    // cho cả tệp máy chủ lẫn Drive, và giữ nguyên khi đi qua lại giữa hai nguồn.
    var B = { kind: '', sort: '' };

    function kindOfItem(it) {
        // Chuẩn hoá hai shape khác nhau (local: is_dir/extension; Drive:
        // is_folder/mime_type) về đúng một hàm phân loại.
        return kindOf({
            isDir: !!(it.is_dir || it.is_folder),
            name: it.name || '',
            mime: it.mime_type || it.mimeType || '',
        });
    }
    function timeOf(it, field) {
        var v = field === 'created' ? (it.created || it.modified) : (it.modified || it.created);
        var t = Date.parse(v || '');
        return isNaN(t) ? 0 : t;
    }

    // Áp cho MỘT mảng item (đã chuẩn hoá tên trường ở trên).
    function applyBrowse(items) {
        var out = (items || []).slice();
        if (B.kind) {
            out = out.filter(function (it) {
                // Thư mục luôn ở lại: lọc theo loại tệp mà giấu luôn thư mục thì
                // không đi sâu vào đâu được nữa.
                return (it.is_dir || it.is_folder) || kindOfItem(it) === B.kind;
            });
        }
        if (B.sort) {
            var dirFirst = function (a, b) {
                var da = (a.is_dir || a.is_folder) ? 0 : 1, db = (b.is_dir || b.is_folder) ? 0 : 1;
                return da - db;
            };
            out.sort(function (a, b) {
                var d = dirFirst(a, b);
                if (d) return d;
                if (B.sort === 'size') return (Number(b.size) || 0) - (Number(a.size) || 0);
                return timeOf(b, B.sort) - timeOf(a, B.sort);   // mới nhất lên đầu
            });
        }
        return out;
    }

    function syncBrowseChips() {
        var on = !!(B.kind || B.sort);
        Array.prototype.forEach.call(document.querySelectorAll('#fm-browse-filters [data-filter="kind"]'), function (el) {
            el.classList.toggle('is-active', el.getAttribute('data-value') === B.kind);
        });
        Array.prototype.forEach.call(document.querySelectorAll('#fm-browse-filters [data-sort]'), function (el) {
            el.classList.toggle('is-active', el.getAttribute('data-sort') === B.sort);
        });
        var reset = byId('fm-browse-reset');
        if (reset) reset.hidden = !on;
    }

    // Vẽ lại CẢ HAI nguồn: người dùng đổi chip xong chuyển tab là thấy nhất quán.
    function repaintBrowse() {
        syncBrowseChips();
        try { if (window.FM && window.FM.items) window.FM.renderFiles(window.FM.items); } catch (e) {}
        try { if (window.FMDrive && window.FMDrive.rerender) window.FMDrive.rerender(); } catch (e) {}
    }

    window.FMSearch = {
        clear: clearSearch,
        // file_manager.js / fm_drive.js gọi ngay trước khi vẽ danh sách.
        applyBrowse: applyBrowse,
        paintPlace: paintPlace,
        browseState: function () { return { kind: B.kind, sort: B.sort }; },
        isActive: function () { return S.active; },
        scope: function () { return S.scope; },
        refreshScopeLabel: function () { setScope(S.scope); },
    };
})();
