// Dọn bảng hàng loạt trên Codex (10/11/2026): «Nhận các video tự đăng đã lên kênh» + «Đóng các task lỗi cũ».
// Mỗi mục ĐẾM trước (dry_run) rồi mới hỏi xác nhận; nút xác nhận mang con số; 0 task ⇒ nút tắt.
//
// Run: node tests/codex_bulk_ui_test.js
'use strict';
const fs = require('fs');
const path = require('path');

const dir = path.join(__dirname, '..', 'tubecli', 'extensions', 'codex');
const js = fs.readFileSync(path.join(dir, 'static', 'codex.js'), 'utf-8').replace(/\r\n/g, '\n');
const html = fs.readFileSync(path.join(dir, 'static', 'codex.html'), 'utf-8');

let pass = 0, fail = 0;
function check(label, ok, detail) {
    if (ok) { pass++; console.log('  ok  ', label); }
    else { fail++; console.log('  FAIL', label, detail === undefined ? '' : JSON.stringify(detail).slice(0, 300)); }
}

const a = js.indexOf('  // ── Dọn bảng hàng loạt (10/11/2026)');
const b = js.indexOf('  /** Nút Xoá hỏi trước');
check('cắt được khối dọn bảng', a > 0 && b > a, { a, b });

function el(id) {
    return { id, value: '', textContent: '', innerHTML: '', disabled: false, className: '', open: true,
        classList: { set: new Set(['hidden']), add(c) { this.set.add(c); }, remove(c) { this.set.delete(c); },
            toggle(c, on) { if (on) this.set.add(c); else this.set.delete(c); } } };
}
const ELS = {};
['cx-cleanup', 'cx-bulk-title', 'cx-bulk-days-row', 'cx-bulk-days', 'cx-modal-bulk', 'cx-bulk-hint', 'cx-bulk-list', 'cx-bulk-go']
    .forEach((id) => { ELS[id] = el(id); });
ELS['cx-bulk-days'].value = '7';
const LOC = {
    'codex.bulk_accept_title': 'Nhận video', 'codex.bulk_close_title': 'Đóng task lỗi',
    'codex.bulk_accept_hint': '{n} task tự đăng', 'codex.bulk_close_hint': '{n} task lỗi', 'codex.bulk_none': 'Không có',
    'codex.bulk_more': '…và {n} task nữa', 'codex.bulk_confirm_accept': 'Nhận {n}', 'codex.bulk_confirm_close': 'Đóng {n}',
    'codex.toast_bulk_accepted': 'Đã nhận {n}', 'codex.toast_bulk_closed': 'Đã đóng {n}', 'codex.toast_action_failed': 'Lỗi: {error}',
};
const t = (k, p) => { let s = LOC[k] || k; Object.entries(p || {}).forEach(([x, v]) => { s = s.replace('{' + x + '}', v); }); return s; };
const esc = (s) => String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const W = { calls: [], toasts: [], refreshed: 0, closed: [], reply: null, fail: false };
const state = {};
const api = async (p, o) => { W.calls.push({ p, body: JSON.parse(o.body), method: o.method }); if (W.fail) throw new Error('boom'); return W.reply(JSON.parse(o.body)); };
const fns = new Function('$', 't', 'esc', 'state', 'api', 'toast', 'refresh', 'closeModal',
    `${js.slice(a, b)}; return { openBulk, bulkRecount, doBulk, BULK_PATH };`)(
    (id) => ELS[id] || null, t, esc, state, api, (m, k) => W.toasts.push([m, k]), async () => { W.refreshed++; },
    (id) => { W.closed.push(id); ELS[id] && ELS[id].classList.add('hidden'); });

(async () => {
    const tasks = Array.from({ length: 10 }, (_, i) => ({ id: 'id' + i, seq: 100 + i, title: 'Video <' + i + '>' }));
    W.reply = (body) => (body.dry_run ? { dry_run: true, matched: 10, tasks } : { dry_run: false, accepted: 10, tasks });
    await fns.openBulk('accept');
    check('mở «nhận»: POST /bulk/accept-published dry_run, đóng menu, hiện hộp',
        W.calls[0].p === '/bulk/accept-published' && W.calls[0].body.dry_run === true && ELS['cx-cleanup'].open === false
        && !ELS['cx-modal-bulk'].classList.set.has('hidden'), W.calls);
    check('ô số ngày ẩn với «nhận»', ELS['cx-bulk-days-row'].classList.set.has('hidden'));
    check('hộp: tiêu đề + đếm + 8 dòng đầu (escape) + «…và 2 task nữa»',
        ELS['cx-bulk-title'].textContent === 'Nhận video' && ELS['cx-bulk-hint'].textContent === '10 task tự đăng'
        && (ELS['cx-bulk-list'].innerHTML.match(/<li>/g) || []).length === 8 && ELS['cx-bulk-list'].innerHTML.includes('Video &lt;0&gt;')
        && ELS['cx-bulk-list'].innerHTML.includes('…và 2 task nữa'), ELS['cx-bulk-list'].innerHTML);
    check('nút xác nhận mang con số, bật', ELS['cx-bulk-go'].textContent === 'Nhận 10' && !ELS['cx-bulk-go'].disabled);
    await fns.doBulk();
    check('xác nhận: POST thật (dry_run false), đóng hộp, báo «Đã nhận 10», tải lại bảng',
        W.calls[1].body.dry_run === false && W.closed.includes('cx-modal-bulk') && W.toasts[0][0] === 'Đã nhận 10'
        && W.refreshed === 1, { calls: W.calls, toasts: W.toasts });

    W.calls.length = 0;
    W.reply = (body) => ({ dry_run: body.dry_run, matched: 0, tasks: [] });
    await fns.openBulk('close');
    check('mở «đóng»: gửi older_than_days 7, hiện ô số ngày',
        W.calls[0].p === '/bulk/close-failed' && W.calls[0].body.older_than_days === 7
        && !ELS['cx-bulk-days-row'].classList.set.has('hidden'), W.calls);
    check('0 task ⇒ «Không có», nút tắt, nút kiểu nguy hiểm',
        ELS['cx-bulk-hint'].textContent === 'Không có' && ELS['cx-bulk-go'].disabled === true
        && ELS['cx-bulk-go'].className.includes('cx-btn-danger'));
    const before = W.calls.length;
    await fns.doBulk();
    check('nút tắt ⇒ bấm không gửi gì', W.calls.length === before);
    ELS['cx-bulk-days'].value = '30';
    W.reply = (body) => (body.dry_run ? { dry_run: true, matched: 3, tasks: tasks.slice(0, 3) } : { closed: 3, tasks: [] });
    await fns.bulkRecount();
    check('đổi số ngày ⇒ đếm lại với 30', W.calls[W.calls.length - 1].body.older_than_days === 30
        && ELS['cx-bulk-go'].textContent === 'Đóng 3' && !ELS['cx-bulk-go'].disabled);
    ELS['cx-bulk-days'].value = '0';
    await fns.bulkRecount();
    check('số ngày sai (0) ⇒ dùng 7', W.calls[W.calls.length - 1].body.older_than_days === 7);
    W.fail = true;
    await fns.doBulk();
    check('lỗi API ⇒ toast lỗi, nút bật lại', W.toasts[W.toasts.length - 1][0] === 'Lỗi: boom' && !ELS['cx-bulk-go'].disabled);

    check('HTML: menu dọn bảng + 2 mục gọi CODEX.openBulk', html.includes('id="cx-cleanup"')
        && html.includes(`CODEX.openBulk('accept')`) && html.includes(`CODEX.openBulk('close')`));
    check('HTML: hộp #cx-modal-bulk có ô số ngày + nút xác nhận', html.includes('id="cx-modal-bulk"')
        && html.includes('id="cx-bulk-days"') && html.includes('onclick="CODEX.doBulk()"'));
    check('CODEX công khai openBulk / bulkRecount / doBulk', /openBulk, bulkRecount, doBulk,/.test(js));
    const locDir = path.join(dir, 'locales');
    const keys = Object.keys(LOC).filter((k) => k !== 'codex.toast_action_failed').concat(['codex.cleanup_menu', 'codex.bulk_accept_btn',
        'codex.bulk_close_btn', 'codex.bulk_days']);
    const missing = [];
    let backlogWord = '';
    for (const f of fs.readdirSync(locDir)) {
        const data = JSON.parse(fs.readFileSync(path.join(locDir, f), 'utf-8'));
        keys.forEach((k) => { if (!data[k]) missing.push(f + ':' + k); });
        keys.forEach((k) => { if (/backlog/i.test(data[k] || '')) backlogWord = f + ':' + k; });
    }
    check('đủ khoá ở 9 ngôn ngữ', missing.length === 0, missing);
    check('không chữ «backlog» hiển thị', !backlogWord, backlogWord);

    console.log(`\n${pass}/${pass + fail} passed`);
    process.exit(fail ? 1 : 0);
})();
