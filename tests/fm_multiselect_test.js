// File Manager: chọn nhiều + tải về / sao chép / di chuyển / xoá hàng loạt (14/9/2026).
//
// User: "thêm logo select nhiều file, tải về máy, xoá, copy, move..". FM chỉ có selectedItem
// đơn; tải về chỉ có trong trình xem media.
//
// Kiểm (tĩnh trên html/js/css/fm_actions + chạy thật hai helper thuần):
//   1. thanh công cụ có nút Chọn nhiều; thanh chọn có đủ đếm / chọn tất cả / bỏ chọn / tải về /
//      sao chép / di chuyển / xoá / xong; menu chuột phải có Tải về và Chọn nhiều
//   2. thẻ có ô tick đứng đầu, lớp is-checked; lưới mang is-selecting; CSS cho lưới lẫn danh sách
//   3. selectItem nhận sự kiện (Ctrl/Shift), Ctrl+A, Esc thoát, Delete/Ctrl+C/X dùng selectedPaths
//   4. xoá nhiều hỏi MỘT lần; clipboard mang .paths; dán lặp từng mục; menu chuột phải giữ nhóm
//   5. fm_actions: 6 hành động mới; download trên mục trong nhóm → cả nhóm
//   6. planDownloads: thư mục hay >8 file → zip; downloadUrl mã hoá từng path
//   7. bản dịch: 9 ngôn ngữ đủ 13 khoá; DEFAULTS trong html có khoá markup mới
//
// Run: node tests/fm_multiselect_test.js
'use strict';
const fs = require('fs');
const path = require('path');

const dir = path.join(__dirname, '..', 'tubecli', 'extensions', 'file_manager');
const read = (...p) => fs.readFileSync(path.join(dir, ...p), 'utf-8').replace(/\r\n/g, '\n');
const html = read('static', 'file_manager.html');
const js = read('static', 'file_manager.js');
const css = read('static', 'file_manager.css');
const fa = read('static', 'fm_actions.js');

let pass = 0, fail = 0;
function check(label, ok, detail) {
    if (ok) { pass++; console.log('  ok  ', label); }
    else { fail++; console.log('  FAIL', label, detail === undefined ? '' : JSON.stringify(detail).slice(0, 220)); }
}

console.log('── 1. markup ───────────────────────────────────────────');
check('nút Chọn nhiều trên thanh công cụ (aria-pressed)', html.includes('id="btnSelectMode" data-fm-action="select-mode"') && html.includes('aria-pressed="false"'));
check('thanh chọn: đếm + 7 nút', html.includes('id="fmSelectBar" hidden') && html.includes('id="fmSelectCount"')
    && ['select-all', 'select-none', 'bulk-download', 'copy', 'move', 'delete', 'select-done'].every(a => html.includes(`data-fm-action="${a}"`)));
check('nút hàng loạt tắt khi chưa chọn gì', ['btnBulkDownload', 'btnBulkCopy', 'btnBulkMove', 'btnBulkDelete'].every(id => new RegExp(`id="${id}"[^>]*disabled`).test(html)));
check('thanh chọn đứng TRƯỚC vùng cuộn của khu Files', html.indexOf('id="fmSelectBar"') < html.indexOf('<!-- List-view column headings'));
check('menu chuột phải: Tải về + Chọn nhiều', html.includes('data-fm-action="download"') && (html.match(/data-fm-action="select-mode"/g) || []).length === 2);

console.log('── 2. thẻ + CSS ────────────────────────────────────────');
check('ô tick đứng đầu thẻ', js.includes("var check = h('span', { class: 'fm-check', 'aria-hidden': 'true' });") && js.includes('var kids = [\n                    check,\n                    iconBox,'));
check('thẻ mang is-checked khi đã tick', js.includes("class: 'fm-file-card' + (FM.isSelected(item.path) ? ' is-checked' : '')"));
check('vẽ xong lưới → renderSelection', js.includes('grid.appendChild(frag);\n            this.renderSelection();'));
check('CSS: tick chỉ hiện khi lưới is-selecting; danh sách thêm cột 18px',
    css.includes('.fm-file-grid.is-selecting .fm-check { display: grid; }') && css.includes('grid-template-columns: 18px 26px minmax(0, 1fr) 96px 168px;'));
check('CSS: thanh chọn + nút bật', css.includes('.fm-select-bar {') && css.includes('.fm-btn[aria-pressed="true"]'));

console.log('── 3. chọn ─────────────────────────────────────────────');
check('bấm thẻ truyền sự kiện', js.includes("if (card) this.selectItem(card, card.getAttribute('data-path'), e);"));
check('selectItem: chế độ chọn / Ctrl / Shift → thêm bớt hay một dải', js.includes('if (ev && (this.selectMode || ev.ctrlKey || ev.metaKey || ev.shiftKey)) {') && js.includes('if (ev.shiftKey && this._selAnchor) this.selectRange(this._selAnchor, path);'));
check('Shift+bấm theo thứ tự TRÊN MÀN HÌNH', js.includes('var order = this.visiblePaths();\n            var a = order.indexOf(from), b = order.indexOf(to);'));
check('Ctrl+A chọn tất cả, Esc thoát', js.includes("(e.key === 'a' || e.key === 'A')) { e.preventDefault(); this.selectAll(); }") && js.includes('if (this.selection.length || this.selectMode) this.exitSelectMode();'));
check('Delete / Ctrl+C / Ctrl+X đi theo selectedPaths', js.includes("if (e.key === 'Delete' && picked)") && js.includes("e.key === 'c' && picked") && js.includes("e.key === 'x' && picked"));
check('đổi thư mục / xoá → mục biến mất rơi khỏi nhóm', js.includes('this.selection = this.selection.filter(function (p) { return known[p]; });'));
check('Đổi tên chỉ khi đúng 1 mục', js.includes("[['btnRename', n === 1], ['btnDelete', n > 0], ['btnCopy', n > 0]"));

console.log('── 4. hành động hàng loạt ─────────────────────────────');
check('xoá nhiều: hỏi một lần, xoá từng mục có tiến độ', js.includes('if (targets.length > 1) return this.deleteMany(targets);') && js.includes("this.busy(T('fm.busy.deleting_many', { i: i + 1, n: targets.length }));"));
check('clipboard mang .paths (giữ .path cho mã cũ)', js.includes("this.clipboard = { action: 'copy', path: paths[0], paths: paths };") && js.includes("this.clipboard = { action: 'cut', path: paths[0], paths: paths };"));
check('dán lặp từng mục, cắt xong mới xoá clipboard', js.includes('var srcs = this.clipboard.paths || [this.clipboard.path];') && js.includes('if (!isCopy && ok) { this.clipboard = null; this.updateToolbarButtons(); }'));
check('menu chuột phải trên mục đã tick giữ nguyên nhóm', js.includes('if (this.isSelected(path)) this.selectedItem = path;\n            else this.selectItem(card, path, this.selectMode ? { ctrlKey: true } : null);'));
check('tải về: thư mục/nhiều → zip, còn lại từng file cách 400ms', js.includes('triggerDownload(downloadUrl(base, targets));') && js.includes("}, i * 400);"));

console.log('── 5. fm_actions ───────────────────────────────────────');
check('6 hành động mới đăng ký', ['select-mode', 'select-all', 'select-none', 'select-done', 'bulk-download', "'download': actDownload"].every(a => fa.includes(a)));
check('download trên mục trong nhóm → cả nhóm', fa.includes("callFM('downloadSelected', inGroup ? undefined : path)"));

console.log('── 6. helper thuần chạy thật ──────────────────────────');
const a = js.indexOf('    function planDownloads(paths, dirs) {');
const b = js.indexOf('    /** Một thẻ <a download> ẩn');
check('cắt được planDownloads/downloadUrl', a > 0 && b > a, { a, b });
const api = new Function(`${js.slice(a, b)}; return { planDownloads, downloadUrl };`)();
check('3 file → từng file', JSON.stringify(api.planDownloads(['/a', '/b', '/c'], {})) === JSON.stringify({ zip: false, files: ['/a', '/b', '/c'] }));
check('có thư mục → zip', api.planDownloads(['/a', '/d'], { '/d': true }).zip === true);
check('9 file → zip', api.planDownloads('123456789'.split('').map(x => '/' + x), {}).zip === true && api.planDownloads('12345678'.split('').map(x => '/' + x), {}).zip === false);
check('downloadUrl mã hoá từng path', api.downloadUrl('/api/v1/files', ['/root/tập 1.mp4', 'C:\\x y']) === '/api/v1/files/download?path=%2Froot%2Ft%E1%BA%ADp%201.mp4&path=C%3A%5Cx%20y');

console.log('── 7. bản dịch ─────────────────────────────────────────');
const KEYS = ['select_mode', 'select_all', 'select_none', 'select_done', 'clip_copy_many', 'clip_cut_many', 'pasted_many', 'delete_many_title', 'delete_many_body', 'deleted_many', 'download_many', 'download_zip'];
for (const lang of ['en', 'vi', 'es', 'ja', 'ko', 'ru', 'tr', 'zh', 'zh-TW']) {
    const loc = JSON.parse(read('locales', lang + '.json'));
    const missing = KEYS.filter(k => !loc['fm.browse.' + k]).concat(loc['fm.busy.deleting_many'] ? [] : ['busy.deleting_many']);
    check(`${lang}: đủ 13 khoá, giữ {n}/{ok}`, !missing.length && loc['fm.browse.deleted_many'].includes('{ok}') && loc['fm.browse.delete_many_title'].includes('{n}'), missing);
}
check('chữ dự phòng vi + en trong JS', js.includes("'fm.browse.delete_many_title': 'Xóa {n} mục?'") && js.includes("'fm.browse.delete_many_title': 'Delete {n} items?'"));
check('DEFAULTS của trang có khoá markup mới', ['"fm.browse.select_mode"', '"fm.browse.select_all"', '"fm.browse.select_none"', '"fm.browse.select_done"', '"fm.browse.download"'].every(k => html.includes(k + ': ')));

console.log();
console.log(fail ? `${pass}/${pass + fail} PASS — ${fail} HỎNG` : `${pass}/${pass + fail} PASS`);
process.exit(fail ? 1 : 0);
