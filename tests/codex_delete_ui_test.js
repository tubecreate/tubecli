/**
 * Codex UI: Chạy lại sau khi Huỷ, nút Xoá hỏi "chỉ Codex" hay "cả file" (13/9/2026).
 *
 *   1. actionsHtml thật: cancelled → Chạy lại + Xoá; done → Xoá; running/queued → không Xoá
 *   2. Hộp Xoá: có trong html, nút "cả file" chỉ hiện với task video (lane); JS gửi DELETE
 *      ?purge=1; xuất confirmDelete/doDelete
 *   3. Bước cancelled có icon + CSS; đủ khoá bản dịch 9 ngôn ngữ, giữ {seq}/{n}/{mb}/{error}
 *
 * Run:  node tests/codex_delete_ui_test.js     (exit 0 = pass)
 */
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const here = path.dirname(fileURLToPath(import.meta.url));
const dir = path.join(here, '..', 'tubecli', 'extensions', 'codex');
const read = (...p) => fs.readFileSync(path.join(dir, ...p), 'utf-8').replace(/\r\n/g, '\n');
const js = read('static', 'codex.js');
const html = read('static', 'codex.html');
const css = read('static', 'codex.css');

let failed = 0;
const check = (name, ok, detail) => {
    if (ok) { console.log('  ok  ' + name); return; }
    failed++;
    console.log('  FAIL ' + name + (detail !== undefined ? ' — ' + JSON.stringify(detail).slice(0, 300) : ''));
};

console.log('── actionsHtml ─────────────────────────────────────────');
const a = js.indexOf('  function actionsHtml(task) {');
const b = js.indexOf('  function bodyHtml(task) {');
check('cắt được actionsHtml', a > 0 && b > a, { a, b });
const stubs = { state: { busy: {} }, esc: s => String(s), t: k => k, icon: n => `<i>${n}</i>` };
const actionsHtml = new Function(...Object.keys(stubs), `${js.slice(a, b)}; return actionsHtml;`)(...Object.values(stubs));
const has = (status, fn) => actionsHtml({ id: 'x', status }).includes(`CODEX.${fn}('x')`);
check('cancelled → Chạy lại + Xoá (bệnh cũ: không nút nào)', has('cancelled', 'retry') && has('cancelled', 'confirmDelete'));
check('failed/rejected → Chạy lại + Xoá', has('failed', 'retry') && has('failed', 'confirmDelete') && has('rejected', 'confirmDelete'));
check('done → chỉ Xoá', has('done', 'confirmDelete') && !has('done', 'retry'));
check('running/queued → Huỷ, KHÔNG Xoá', has('running', 'cancel') && !has('running', 'confirmDelete') && !has('queued', 'confirmDelete'));
check('review → không Xoá (đang chờ nghiệm thu)', !has('review', 'confirmDelete'));
check('backlog/pending → có Xoá', has('backlog', 'confirmDelete') && has('pending_approval', 'confirmDelete'));

console.log('── hộp Xoá + DELETE ─────────────────────────────────────');
check('html có hộp cx-modal-delete với hai nút + nút "cả file" ẩn sẵn',
    html.includes('id="cx-modal-delete"') && html.includes('CODEX.doDelete(false)')
    && /id="cx-del-files"[^>]*onclick="CODEX\.doDelete\(true\)"/.test(html) && /class="cx-btn cx-btn-danger hidden" id="cx-del-files"/.test(html));
check('confirmDelete: nút "cả file" chỉ hiện với task video (lane)', /const video = task\.lane === 'video';[\s\S]*?\$\('cx-del-files'\)\.classList\.toggle\('hidden', !video\)/.test(js));
check('doDelete gửi DELETE, purge=1 khi chọn cả file', js.includes("api(taskUrl(id, purge ? '?purge=1' : ''), { method: 'DELETE' })"));
check('xoá xong bỏ task khỏi danh sách, báo số file/MB', js.includes("state.tasks = state.tasks.filter(x => x.id !== id)") && js.includes("codex.toast_deleted_files"));
check('xuất confirmDelete, doDelete', /confirmNote, confirmDelete, doDelete, copyResult, planTask,/.test(js));

console.log('── bước cancelled ──────────────────────────────────────');
check('STEP_ICON có cancelled', /cancelled: 'stop_circle',/.test(js));
check('CSS: cx-seg.cancelled + cx-step.cancelled', css.includes('.cx-seg.cancelled') && css.includes('.cx-step.cancelled .cx-step-dot'));

console.log('── bản dịch ────────────────────────────────────────────');
for (const lang of ['en', 'vi', 'es', 'ja', 'ko', 'ru', 'tr', 'zh', 'zh-TW']) {
    const loc = JSON.parse(read('locales', lang + '.json'));
    check(`${lang}: đủ khoá xoá/dừng, giữ chỗ trống`,
        !!loc['codex.action_delete'] && String(loc['codex.modal_delete_title']).includes('{seq}')
        && !!loc['codex.modal_delete_hint'] && !!loc['codex.modal_delete_hint_video']
        && !!loc['codex.btn_delete_codex'] && !!loc['codex.btn_delete_all']
        && String(loc['codex.toast_deleted']).includes('{seq}')
        && ['{seq}', '{n}', '{mb}'].every(x => String(loc['codex.toast_deleted_files']).includes(x))
        && ['{seq}', '{error}'].every(x => String(loc['codex.toast_deleted_purge_error']).includes(x))
        && !!loc['codex.step_cancelled']);
}

console.log(failed ? `\n${failed} FAIL` : '\nALL PASS');
process.exit(failed ? 1 : 0);
