// Nút «Drive» trên thẻ task video + «Đồng bộ lên Drive rồi xoá» trong hộp Delete (16/9/2026).
//
// User: "các task chưa up drive nếu muốn upload lên drive, bên cạnh button delete thêm button sync lên drive, bấm vào
// chọn drive để đồng bộ project lên / ở button delete thêm delete + đồng bộ lên drive".
//
// Kiểm:
//   1. markup: hộp Drive (tài khoản, quyền), nút «Đồng bộ rồi xoá» trong hộp Delete, nút xoá file nói rõ project Studio
//   2. actionsHtml chạy thật: nút Drive chỉ cho task VIDEO đã xong / đang Review
//   3. openDriveSync / startDriveSync / syncThenDelete chạy thật với DOM + request giả
//   4. bản dịch 9 ngôn ngữ × 21 khoá
//   5. (16/9/2026) "những task đã upload driver thì đánh dấu đã upload drive màu xanh, chỉ bấm vào khi muốn đồng bộ lại
//      hoặc chọn lại drive khác" — nút xanh «Đã lên Drive», hộp chọn sẵn tài khoản lần trước + link mở thư mục
//
// Run: node tests/codex_drive_sync_test.js
'use strict';
const fs = require('fs');
const path = require('path');

const dir = path.join(__dirname, '..', 'tubecli', 'extensions', 'codex');
const js = fs.readFileSync(path.join(dir, 'static', 'codex.js'), 'utf-8').replace(/\r\n/g, '\n');
const html = fs.readFileSync(path.join(dir, 'static', 'codex.html'), 'utf-8').replace(/\r\n/g, '\n');
const css = fs.readFileSync(path.join(dir, 'static', 'codex.css'), 'utf-8').replace(/\r\n/g, '\n');

let pass = 0, fail = 0;
function check(label, ok, detail) {
    if (ok) { pass++; console.log('  ok  ', label); }
    else { fail++; console.log('  FAIL', label, detail === undefined ? '' : JSON.stringify(detail).slice(0, 260)); }
}

console.log('── 1. markup ───────────────────────────────────────────');
check('hộp Drive: tài khoản + quyền (ẩn tới khi máy chủ trả lời) + nút chạy khoá sẵn',
    html.includes('<div class="cx-modal hidden" id="cx-modal-drive"') && html.includes('<div id="cx-ds-form" class="hidden">')
    && html.includes('<select id="cx-ds-token"></select>') && html.includes('<select id="cx-ds-share">')
    && html.includes('id="cx-ds-go" onclick="CODEX.startDriveSync()" disabled'));
const iSync = html.indexOf('id="cx-del-sync" onclick="CODEX.syncThenDelete()"');
const iFiles = html.indexOf('id="cx-del-files" onclick="CODEX.doDelete(true)"');
check('hộp Delete: nút «Đồng bộ lên Drive rồi xoá» (ẩn sẵn) đứng trước nút xoá file', iSync > 0 && iFiles > iSync, { iSync, iFiles });
check('nút xoá file nói rõ xoá cả project Content Studio', html.includes('>Delete files and the Content Studio project</button>'));
check('mở hộp Delete cho task video → hiện nút đồng bộ rồi xoá', js.includes("$('cx-del-sync').classList.toggle('hidden', !video);"));
check('hộp Drive: dòng «đã lưu bằng … · Mở thư mục» (ẩn sẵn)', html.includes('<p class="cx-hint cx-ds-where hidden" id="cx-ds-where"></p>'));
check('nút «Đã lên Drive»: chữ + viền xanh trên nền thường (khác Accept nền xanh)',
    /\.cx-btn-drive-done \{ background: var\(--bg3\); color: var\(--cx-green\);/.test(css));

console.log('── 2. actionsHtml ──────────────────────────────────────');
const a1 = js.indexOf('  function actionsHtml(task) {');
const a2 = js.indexOf('  function bodyHtml(task) {');
check('cắt được actionsHtml', a1 > 0 && a2 > a1, { a1, a2 });
const actions = new Function('esc', 'icon', 't', 'state', `${js.slice(a1, a2)}; return actionsHtml;`)(
    s => String(s), () => '', k => k, { busy: {} });
const done = actions({ id: 'x', status: 'done', lane: 'video' });
check('video đã xong: Drive + Delete, Drive đứng trước',
    done.includes("CODEX.openDriveSync('x')") && done.indexOf('openDriveSync') < done.indexOf('confirmDelete'), done);
const review = actions({ id: 'x', status: 'review', lane: 'video' });
check('video ở Review: Accept, Request changes + Drive', review.includes('accept') && review.includes('requestChanges') && review.includes('openDriveSync'));
check('task việc chung đã xong: KHÔNG có nút Drive', !actions({ id: 'y', status: 'done', lane: '' }).includes('openDriveSync'));
check('video đang chạy: KHÔNG có nút Drive', !actions({ id: 'z', status: 'running', lane: 'video' }).includes('openDriveSync'));
const onDrive = { folder_url: 'https://drive.google.com/f1', email: 'b@x.com', files: 12 };
const synced = actions({ id: 'x', status: 'done', lane: 'video', drive: onDrive });
check('đã lên Drive: nút xanh «Đã lên Drive» vẫn bấm được (đồng bộ lại / đổi tài khoản), không còn nút Drive thường',
    synced.includes(`class="cx-btn cx-btn-sm cx-btn-drive-done" onclick="CODEX.openDriveSync('x')"`)
    && synced.includes('codex.action_drive_synced</button>') && synced.includes('title="codex.drive_synced_title"')
    && !synced.includes('cx-btn-ghost" onclick="CODEX.openDriveSync') && synced.includes('confirmDelete'), synced);
const reviewSynced = actions({ id: 'x', status: 'review', lane: 'video', drive: onDrive });
check('Review + đã lên Drive: Accept, Request changes + nút xanh',
    reviewSynced.includes('accept') && reviewSynced.includes('requestChanges') && reviewSynced.includes('cx-btn-drive-done'), reviewSynced);
check('dấu rỗng {} (đã kiểm, chưa lên Drive) → nút Drive thường',
    actions({ id: 'x', status: 'done', lane: 'video', drive: {} }).includes('cx-btn-ghost" onclick="CODEX.openDriveSync'));
const busyBtn = new Function('esc', 'icon', 't', 'state', `${js.slice(a1, a2)}; return actionsHtml;`)(
    s => String(s), () => '', k => k, { busy: { x: true } })({ id: 'x', status: 'done', lane: 'video', drive: onDrive });
check('đang bận thao tác → nút xanh cũng khoá', busyBtn.includes(`onclick="CODEX.openDriveSync('x')" disabled title=`), busyBtn);

console.log('── 3. hộp Drive chạy thật ──────────────────────────────');
const d1 = js.indexOf('  // ── Đồng bộ project lên Google Drive');
const d2 = js.indexOf('  function openNote(mode, taskId) {');
const p1 = js.indexOf('  function driveCanWrite(scopes) {');
const p2 = js.indexOf('  function videoAgentGranted() {');
check('cắt được khối Drive + pickDriveToken', d1 > 0 && d2 > d1 && p1 > 0 && p2 > p1, { d1, d2, p1, p2 });
const PICK = new Function(`${js.slice(p1, p2)}; return { driveCanWrite, pickDriveToken };`)();

function world(opts) {
    const els = {};
    const cls = () => ({ set: {}, add(c) { this.set[c] = true; }, remove(c) { this.set[c] = false; }, toggle(c, v) { this.set[c] = !!v; }, has(c) { return !!this.set[c]; } });
    const el = (id) => (els[id] ||= { id, value: '', textContent: '', innerHTML: '', disabled: false, classList: cls() });
    el('cx-ds-form').classList.add('hidden');
    el('cx-modal-drive').classList.add('hidden');
    const W = { els, el, calls: [], toasts: [], store: {}, refreshed: 0 };
    const state = {
        tasks: [{ id: 'src', seq: 21, lane: 'video', status: 'done', assignee_id: 'a1' },
                { id: 'plan', seq: 20, lane: 'video', status: 'review', assignee_id: 'a1' }],
        assignees: { agents: [{ id: 'a1', name: 'Orchestrator', auth_creds: ['cred_b'] }] },
        googleTokens: null, googleTokensError: '', deleteTaskId: '', driveSync: null,
    };
    W.state = state;
    const tokens = opts.tokens !== undefined ? opts.tokens : [
        { token_id: 'A1', credential_id: 'cred_a', authorized_email: 'a@x.com', scopes: ['drive'], status: 'active' },
        { token_id: 'B1', credential_id: 'cred_b', authorized_email: 'b@x.com', scopes: ['drive'], status: 'active' },
        { token_id: 'R1', credential_id: 'cred_r', authorized_email: 'r@x.com', scopes: ['drive_readonly'], status: 'active' },
    ];
    const request = async (url, o) => {
        W.calls.push({ url, method: (o && o.method) || 'GET', body: o && o.body ? JSON.parse(o.body) : null });
        if (o && o.method === 'POST') return { status: 'queued', task: { seq: 31 } };
        return opts.info[url.split('/tasks/')[1].split('/')[0]];
    };
    W.api = new Function('$', 't', 'esc', 'state', 'request', 'loadAssignees', 'loadGoogleTokens', 'pickDriveToken', 'driveCanWrite',
        'lsGet', 'lsSet', 'CV_DRIVE_TOKEN_KEY', 'CV_DRIVE_SHARE_KEY', 'toast', 'refresh', 'closeModal',
        `${js.slice(d1, d2)}; return { openDriveSync, renderDriveSyncAccounts, startDriveSync, syncThenDelete };`)(
        el, (k, p) => k + (p ? JSON.stringify(p) : ''), s => String(s), state, request,
        async () => state.assignees, async () => { state.googleTokens = tokens; },
        PICK.pickDriveToken, PICK.driveCanWrite,
        k => W.store[k] || '', (k, v) => { W.store[k] = v; }, 'codex.cvDriveToken', 'codex.cvDriveShare',
        (m, kind) => W.toasts.push([m, kind]), async () => { W.refreshed++; },
        (id) => el(id).classList.add('hidden'));
    return W;
}

(async () => {
    let W = world({ info: { plan: { ok: false, reason: 'script_only', message: 'x' } } });
    await W.api.openDriveSync('plan');
    check('task chỉ viết kịch bản: nói video ở task dựng, không hiện form, nút chạy khoá',
        W.el('cx-ds-hint').textContent === 'codex.ds_reason_script_only' && W.el('cx-ds-form').classList.has('hidden')
        && W.el('cx-ds-go').disabled === true && !W.el('cx-modal-drive').classList.has('hidden'), W.el('cx-ds-hint').textContent);
    check('hỏi máy chủ đúng route', W.calls[0].url === '/api/v1/content-video/tasks/plan/drive-sync' && W.calls[0].method === 'GET', W.calls);

    W = world({ info: { src: { ok: true, seq: 21, title: 'Zen', drive: {} } } });
    await W.api.openDriveSync('src');
    check('video đã xong: hiện form, tiêu đề + câu giải thích, chọn sẵn tài khoản đã cấp cho agent (✓)',
        !W.el('cx-ds-form').classList.has('hidden') && W.el('cx-ds-title').textContent === 'codex.ds_title{"seq":21}'
        && W.el('cx-ds-hint').textContent === 'codex.ds_hint{"title":"Zen"}' && W.el('cx-ds-token').value === 'B1'
        && W.el('cx-ds-token').innerHTML.includes('b@x.com ✓') && W.el('cx-ds-go').disabled === false
        && W.el('cx-ds-go').textContent === 'codex.ds_go', { hint: W.el('cx-ds-hint').textContent, v: W.el('cx-ds-token').value });
    check('tài khoản chỉ đọc hiện nhưng khoá', W.el('cx-ds-token').innerHTML.includes('<option value="R1" disabled>'));
    W.el('cx-ds-share').value = 'private';
    await W.api.startDriveSync();
    const post = W.calls.find(c => c.method === 'POST');
    check('bấm Đồng bộ: POST đúng tài khoản + quyền, không xoá',
        post && post.url === '/api/v1/content-video/tasks/src/drive-sync'
        && JSON.stringify(post.body) === JSON.stringify({ drive_token_id: 'B1', drive_public: false, delete_after: false }), post);
    check('xong: đóng hộp, báo task mới, nhớ tài khoản + quyền, vẽ lại bảng',
        W.el('cx-modal-drive').classList.has('hidden') && W.toasts[0][0] === 'codex.toast_ds_queued{"seq":31,"src":21}'
        && W.store['codex.cvDriveToken'] === 'B1' && W.store['codex.cvDriveShare'] === 'private' && W.refreshed === 1, W.toasts);

    W = world({ info: { src: { ok: true, seq: 21, title: 'Zen', drive: { folder_url: 'https://drive.google.com/f1' } } } });
    await W.api.openDriveSync('src');
    check('đã từng đồng bộ → câu «đồng bộ lại dùng thư mục cũ»', W.el('cx-ds-hint').textContent === 'codex.ds_hint_again{"title":"Zen"}');

    console.log('── 5. đã lên Drive: đồng bộ lại / đổi tài khoản ─────────');
    W = world({ info: { src: { ok: true, seq: 21, title: 'Zen',
        drive: { folder_url: 'https://drive.google.com/f1', email: 'a@x.com', token_id: 'A1' } } } });
    await W.api.openDriveSync('src');
    check('chọn sẵn ĐÚNG tài khoản lần trước (A1) dù agent được cấp B1 — bấm Đồng bộ là cập nhật thư mục cũ',
        W.el('cx-ds-token').value === 'A1', W.el('cx-ds-token').value);
    check('câu dưới ô tài khoản: cùng tài khoản cập nhật thư mục, tài khoản khác tạo thư mục mới',
        W.el('cx-ds-token-hint').textContent === 'codex.ds_account_hint · codex.ds_account_hint_again', W.el('cx-ds-token-hint').textContent);
    check('hiện tài khoản đã lưu + link mở thư mục',
        !W.el('cx-ds-where').classList.has('hidden') && W.el('cx-ds-where').innerHTML
        === 'codex.ds_where{"email":"a@x.com"} · <a href="https://drive.google.com/f1" target="_blank" rel="noopener">codex.ds_open_folder</a>',
        W.el('cx-ds-where').innerHTML);
    W = world({ info: { src: { ok: true, seq: 21, title: 'Zen', drive: { folder_url: 'https://drive.google.com/f1', token_id: 'GONE' } } } });
    await W.api.openDriveSync('src');
    check('tài khoản lần trước đã bị gỡ → chọn theo luật thường (B1 của agent)', W.el('cx-ds-token').value === 'B1', W.el('cx-ds-token').value);
    W = world({ info: { src: { ok: true, seq: 21, title: 'Zen', drive: { folder_url: 'https://drive.google.com/f1', token_id: 'R1' } } } });
    await W.api.openDriveSync('src');
    check('tài khoản lần trước nay chỉ đọc → không chọn nó', W.el('cx-ds-token').value === 'B1', W.el('cx-ds-token').value);
    W = world({ info: { src: { ok: true, seq: 21, title: 'Zen', drive: { folder_url: 'javascript:alert(1)' } } } });
    await W.api.openDriveSync('src');
    check('link không phải https → không dựng link', W.el('cx-ds-where').classList.has('hidden') && !W.el('cx-ds-where').innerHTML);
    W = world({ info: { src: { ok: true, seq: 21, title: 'Zen', drive: {} } } });
    await W.api.openDriveSync('src');
    check('chưa từng lên Drive → không có dòng tài khoản/link, câu dưới ô tài khoản như cũ',
        W.el('cx-ds-where').classList.has('hidden') && W.el('cx-ds-token-hint').textContent === 'codex.ds_account_hint');

    W = world({ info: { src: { ok: true, seq: 21, title: 'Zen', drive: {} } } });
    W.state.deleteTaskId = 'src';
    W.el('cx-modal-delete').classList.remove('hidden');
    W.api.syncThenDelete();
    await new Promise(r => setTimeout(r, 0));
    await new Promise(r => setTimeout(r, 0));
    check('hộp Delete → «Đồng bộ rồi xoá»: đóng hộp xoá, mở hộp Drive chế độ xoá',
        W.el('cx-modal-delete').classList.has('hidden') && W.state.deleteTaskId === ''
        && W.el('cx-ds-title').textContent === 'codex.ds_title_delete{"seq":21}'
        && W.el('cx-ds-go').textContent === 'codex.ds_go_delete' && W.el('cx-ds-hint').textContent === 'codex.ds_hint_delete{"title":"Zen"}',
        W.el('cx-ds-title').textContent);
    await W.api.startDriveSync();
    const post2 = W.calls.find(c => c.method === 'POST');
    check('gửi delete_after = true, báo «tải rồi xoá»', post2 && post2.body.delete_after === true
        && W.toasts[0][0] === 'codex.toast_ds_queued_delete{"seq":31,"src":21}', { post2, toasts: W.toasts });

    W = world({ info: { src: { ok: true, seq: 21, title: 'Zen', drive: {} } }, tokens: [] });
    await W.api.openDriveSync('src');
    check('chưa có tài khoản Drive nào → gợi ý cấp quyền, khoá nút chạy',
        W.el('cx-ds-token-hint').textContent === 'codex.cv_drive_none' && W.el('cx-ds-go').disabled === true);

    check('xuất ra CODEX', js.includes('openDriveSync, startDriveSync, syncThenDelete,'));

    console.log('── 4. bản dịch ─────────────────────────────────────────');
    const KEYS = {
        'codex.action_drive_sync': [], 'codex.btn_delete_sync': [], 'codex.ds_title': ['{seq}'], 'codex.ds_title_delete': ['{seq}'],
        'codex.ds_hint': ['{title}'], 'codex.ds_hint_again': ['{title}'], 'codex.ds_hint_delete': ['{title}'],
        'codex.ds_account_hint': [], 'codex.ds_go': [], 'codex.ds_go_delete': [], 'codex.ds_reason_script_only': [],
        'codex.ds_reason_no_video': [], 'codex.ds_reason_busy': [], 'codex.ds_reason_not_video': [],
        'codex.toast_ds_queued': ['{seq}', '{src}'], 'codex.toast_ds_queued_delete': ['{seq}', '{src}'],
        'codex.action_drive_synced': [], 'codex.drive_synced_title': ['{email}', '{files}'], 'codex.ds_where': ['{email}'],
        'codex.ds_open_folder': [], 'codex.ds_account_hint_again': [],
    };
    for (const lang of ['en', 'vi', 'es', 'ja', 'ko', 'ru', 'tr', 'zh', 'zh-TW']) {
        const loc = JSON.parse(fs.readFileSync(path.join(dir, 'locales', lang + '.json'), 'utf-8'));
        const bad = Object.entries(KEYS).filter(([k, ph]) => !loc[k] || ph.some(p => !loc[k].includes(p)));
        check(`${lang}.json: đủ 21 khoá + chỗ giữ, nút xoá file nhắc Content Studio`,
            !bad.length && loc['codex.btn_delete_all'].includes('Content Studio'), bad.map(x => x[0]));
    }
    const vi = JSON.parse(fs.readFileSync(path.join(dir, 'locales', 'vi.json'), 'utf-8'));
    check('vi dịch thật', vi['codex.btn_delete_sync'] === 'Đồng bộ lên Drive rồi xoá' && vi['codex.ds_hint_delete'].includes('Chỉ khi tải xong')
        && vi['codex.action_drive_synced'] === 'Đã lên Drive');

    console.log();
    console.log(fail ? `${pass}/${pass + fail} PASS — ${fail} HỎNG` : `${pass}/${pass + fail} PASS`);
    process.exit(fail ? 1 : 0);
})();
