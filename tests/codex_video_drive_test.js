// Form «Tạo video từ nội dung» — ô «Lưu lên Google Drive» + chọn tài khoản theo tab Auth của agent (15/9/2026).
//
// User: "lưu nội dung đã tạo vào drive… sẽ chọn auth trong tạo task như đã chọn trong auth của agent" +
// "sao bạn ko cho task chọn tài khoản auth trực tiếp lúc tạo task luôn?".
//
// Kiểm:
//   1. markup: ô tick + ô chọn tài khoản (ẩn sẵn) nằm sau «Duyệt kịch bản», trước tiêu đề
//   2. pickDriveToken / driveCanWrite chạy thật: tài khoản đã cấp cho agent thắng, chỉ đọc/thu hồi không bao giờ chọn
//   3. renderDriveAccounts chạy thật với DOM giả: đang tải, không có tài khoản, tải hỏng, nhóm «Đã cấp cho…», khoá chỉ đọc
//   4. gửi: bắt chọn tài khoản, gửi drive + drive_token_id; nhớ lần gần nhất; mở form nạp lại tài khoản; xuất CODEX
//   5. can_write của JS khớp Python; /assignees trả auth_creds
//   6. bản dịch 9 ngôn ngữ × 12 khoá, đủ chỗ giữ
//
// Run: node tests/codex_video_drive_test.js
'use strict';
const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');
const dir = path.join(root, 'tubecli', 'extensions', 'codex');
const js = fs.readFileSync(path.join(dir, 'static', 'codex.js'), 'utf-8').replace(/\r\n/g, '\n');
const html = fs.readFileSync(path.join(dir, 'static', 'codex.html'), 'utf-8').replace(/\r\n/g, '\n');
const routes = fs.readFileSync(path.join(dir, 'routes.py'), 'utf-8').replace(/\r\n/g, '\n');
const py = fs.readFileSync(path.join(root, 'tubecli', 'extensions', 'content_video', 'drive_export.py'), 'utf-8');

let pass = 0, fail = 0;
function check(label, ok, detail) {
    if (ok) { pass++; console.log('  ok  ', label); }
    else { fail++; console.log('  FAIL', label, detail === undefined ? '' : JSON.stringify(detail).slice(0, 300)); }
}

console.log('── 1. markup ───────────────────────────────────────────');
const iReview = html.indexOf('id="cx-v-review"');
const iDrive = html.indexOf('<input type="checkbox" id="cx-v-drive" onchange="CODEX.onVideoDrive()">');
const iWrap = html.indexOf('<div class="cx-field-row hidden" id="cx-v-drive-wrap">');
const iTitle = html.indexOf('id="cx-v-title"');
check('ô tick «Lưu lên Google Drive» sau «Duyệt kịch bản», trước tiêu đề', iReview > 0 && iDrive > iReview && iWrap > iDrive && iTitle > iWrap, { iReview, iDrive, iWrap, iTitle });
check('ô chọn tài khoản + dòng gợi ý', html.includes('<select id="cx-v-drive-token" onchange="CODEX.onVideoDriveToken()"></select>')
    && html.includes('id="cx-v-drive-hint" aria-live="polite"') && html.includes('data-i18n="codex.field_video_drive_account"'));
check('ô chọn QUYỀN thư mục ngay trong form tạo task, mặc định ai có link xem + tải',
    html.includes('<select id="cx-v-drive-share" onchange="CODEX.onVideoDriveShare()">')
    && html.indexOf('<option value="public" data-i18n="codex.cv_drive_share_public">') < html.indexOf('<option value="private" data-i18n="codex.cv_drive_share_private">')
    && html.includes('data-i18n="codex.cv_drive_share_hint"'));

console.log('── 2. pickDriveToken ───────────────────────────────────');
const a = js.indexOf('  function driveCanWrite(scopes) {');
const b = js.indexOf('  function videoAgentGranted() {');
check('cắt được driveCanWrite + pickDriveToken', a > 0 && b > a, { a, b });
const P = new Function(`${js.slice(a, b)}; return { driveCanWrite, pickDriveToken };`)();
const CAN = [[['drive'], true], [['drive_file'], true], [['drive_readonly'], false], [['https://www.googleapis.com/auth/drive'], true],
    [['https://www.googleapis.com/auth/drive.readonly'], false], [['https://www.googleapis.com/auth/drive.file'], true], [[], false], [undefined, false]];
check('driveCanWrite: khoá ngắn + URL', CAN.every(([s, want]) => P.driveCanWrite(s) === want), CAN.map(([s]) => P.driveCanWrite(s)));
const T = [
    { token_id: 'A1', credential_id: 'cred_a', scopes: ['drive', 'sheets'], status: 'active' },
    { token_id: 'A2', credential_id: 'cred_a', scopes: ['drive_readonly'], status: 'active' },
    { token_id: 'B1', credential_id: 'cred_b', scopes: ['drive'], status: 'expired' },
    { token_id: 'R1', credential_id: 'cred_r', scopes: ['drive'], status: 'revoked' },
    { token_id: 'B2', credential_id: 'cred_b', scopes: ['drive'], status: 'active' },
];
const CASES = [
    ['agent cấp cred_b → tài khoản đang sống của cred_b', [T, ['cred_b'], '', ''], 'B2'],
    ['agent cấp b rồi a → đang sống trước, rồi theo thứ tự tick', [T, ['cred_a', 'cred_b'], '', ''], 'A1'],
    ['agent chưa cấp gì → lần gần nhất', [T, [], '', 'B1'], 'B1'],
    ['lần gần nhất không còn → tài khoản đầu tiên ghi được', [T, [], '', 'gone'], 'A1'],
    ['đang chọn tài khoản CHƯA cấp, đổi sang agent có cấp → theo tab Auth', [T, ['cred_a'], 'B1', ''], 'A1'],
    ['đang chọn một tài khoản đã cấp → giữ', [T, ['cred_b'], 'B1', ''], 'B1'],
    ['agent chưa cấp gì → giữ lựa chọn đang có', [T, [], 'B2', 'A1'], 'B2'],
    ['chỉ đọc không bao giờ được chọn, kể cả đã cấp/đã nhớ', [T, [], 'A2', 'A2'], 'A1'],
    ['đã thu hồi không bao giờ được chọn', [T, ['cred_r'], 'R1', 'R1'], 'A1'],
    ['không có tài khoản ghi được → rỗng', [[T[1], T[3]], ['cred_a'], '', ''], ''],
];
for (const [label, args, want] of CASES) {
    const got = P.pickDriveToken(...args);
    check(`${label} (${want || '""'})`, got === want, got);
}

console.log('── 3. renderDriveAccounts với DOM giả ──────────────────');
const r1 = js.indexOf('  function videoAgentGranted() {');
const r2 = js.indexOf('  function onVideoDrive() {');
check('cắt được khối render', r1 > 0 && r2 > r1, { r1, r2 });
const els = {};
const cls = () => ({ set: {}, toggle(c, v) { this.set[c] = !!v; }, add(c) { this.set[c] = true; }, remove(c) { this.set[c] = false; }, has(c) { return !!this.set[c]; } });
const el = (id) => (els[id] ||= { id, value: '', checked: false, disabled: false, innerHTML: '', textContent: '', classList: cls() });
const st = { assignees: { agents: [{ id: 'a1', name: 'MC', auth_creds: ['cred_b'] }, { id: 'a2', name: 'Solo', auth_creds: [] }] }, googleTokens: null, googleTokensError: '' };
const store = {};
const tt = (k, p) => k + (p ? JSON.stringify(p) : '');
const R = new Function('$', 't', 'esc', 'lsGet', 'state', 'request', 'CV_DRIVE_TOKEN_KEY', 'driveCanWrite', 'pickDriveToken',
    `${js.slice(r1, r2)}; return { renderDriveAccounts, renderDriveHint, loadGoogleTokens, videoAgentGranted };`)(
    el, tt, s => String(s), k => store[k] || '', st, async () => { throw new Error('boom'); }, 'codex.cvDriveToken', P.driveCanWrite, P.pickDriveToken);
el('cx-v-agent').value = 'a1';
el('cx-v-drive').checked = false;
R.renderDriveAccounts();
check('chưa tick → ẩn ô tài khoản', el('cx-v-drive-wrap').classList.has('hidden'));
el('cx-v-drive').checked = true;
R.renderDriveAccounts();
check('tick, đang tải → hiện ô, dòng «đang tải», khoá chọn',
    !el('cx-v-drive-wrap').classList.has('hidden') && el('cx-v-drive-token').innerHTML.includes('codex.cv_drive_loading') && el('cx-v-drive-token').disabled);
st.googleTokens = [{ token_id: 'C1', credential_id: 'cred_c', scopes: ['youtube_upload'], status: 'active' }];
R.renderDriveAccounts();
check('không tài khoản nào có Drive → gợi ý cấp quyền (cảnh báo), khoá chọn',
    el('cx-v-drive-hint').textContent === 'codex.cv_drive_none' && el('cx-v-drive-hint').classList.has('warn') && el('cx-v-drive-token').disabled);
(async () => {
    await R.loadGoogleTokens();
    R.renderDriveAccounts();
    check('tải tài khoản hỏng → nói lý do', st.googleTokens === false && el('cx-v-drive-hint').textContent === 'codex.cv_drive_load_failed{"msg":"boom"}', el('cx-v-drive-hint').textContent);

    st.googleTokens = T.map(x => ({ ...x, authorized_email: x.token_id.toLowerCase() + '@x.com', credential_name: 'Main' }))
        .concat([{ token_id: 'C1', credential_id: 'cred_c', scopes: ['youtube_upload'], status: 'active', authorized_email: 'c@x.com' }]);
    el('cx-v-drive-token').value = '';
    R.renderDriveAccounts();
    const h = el('cx-v-drive-token').innerHTML;
    check('agent có cấp → nhóm «Đã cấp cho MC» đứng trước «Tài khoản khác»',
        h.indexOf('codex.cv_drive_group_granted{"agent":"MC"}') >= 0 && h.indexOf('codex.cv_drive_group_granted') < h.indexOf('codex.cv_drive_group_other'), h.slice(0, 200));
    check('chọn sẵn tài khoản đã cấp đang sống (B2), gợi ý «đã cấp»',
        el('cx-v-drive-token').value === 'B2' && !el('cx-v-drive-token').disabled && el('cx-v-drive-hint').textContent === 'codex.cv_drive_granted_hint{"agent":"MC"}');
    check('chỉ đọc hiện nhưng khoá; thu hồi và tài khoản không có Drive bị ẩn',
        h.includes('<option value="A2" disabled>a2@x.com · Main — codex.cv_drive_readonly</option>') && !h.includes('value="R1"') && !h.includes('value="C1"'), h);
    el('cx-v-drive-token').value = 'A1';
    R.renderDriveHint();
    check('tự đổi sang tài khoản chưa cấp → nói «chỉ dùng cho task này»', el('cx-v-drive-hint').textContent === 'codex.cv_drive_not_granted_hint{"agent":"MC"}');
    el('cx-v-agent').value = 'a2';
    store['codex.cvDriveToken'] = 'B1';
    R.renderDriveAccounts();
    check('agent chưa cấp gì → không có nhóm, giữ lựa chọn đang có',
        !el('cx-v-drive-token').innerHTML.includes('optgroup') && el('cx-v-drive-token').value === 'A1', el('cx-v-drive-token').value);

    console.log('── 4. gửi / nhớ / mở form ──────────────────────────────');
    check('gửi: tick mà chưa có tài khoản → báo lỗi, không gửi (kiểm TRƯỚC khi lưu form)',
        js.includes("if (drive && !driveToken) {\n      toast(t('codex.toast_video_drive_account_required'), 'error');")
        && js.indexOf("const drive = !!$('cx-v-drive').checked;") < js.indexOf("const review = !!$('cx-v-review').checked;\n    rememberNewTaskForm();"));
    check('gửi drive + drive_token_id (token_id cụ thể) + quyền thư mục',
        js.includes('options.drive_token_id = driveToken;') && js.includes("options.drive_public = (($('cx-v-drive-share') || {}).value || 'public') !== 'private';")
        && js.indexOf('options.drive_token_id = driveToken') < js.indexOf("request('/api/v1/content-video/run'"));
    check('mở form: quyền lấy lại lựa chọn lần trước, mặc định public',
        js.includes("$('cx-v-drive-share').value = lsGet(CV_DRIVE_SHARE_KEY) === 'private' ? 'private' : 'public';")
        && js.includes("const CV_DRIVE_SHARE_KEY = 'codex.cvDriveShare';"));
    check('mở form: nhớ ô tick, nạp lại tài khoản mỗi lần, chọn sẵn sau khi có danh sách agent',
        js.includes("$('cx-v-drive').checked = lsGet(CV_DRIVE_KEY) === '1';") && js.includes('state.googleTokens = null;')
        && js.includes('const driveReady = loadGoogleTokens();') && js.indexOf('driveReady.then(renderDriveAccounts);') > js.indexOf('fillVideoAgents(data.agents);'));
    check('đổi agent → chọn lại tài khoản theo tab Auth', /function onVideoAgent\(\) \{\n    lsSet\(CV_AGENT_KEY[^\n]*\n    renderDriveAccounts\(\);/.test(js));
    check('danh sách tài khoản lấy từ Auth Manager', js.includes("request('/api/v1/auth-manager/tokens?provider=google')"));
    check('xuất onVideoDrive + onVideoDriveToken + onVideoDriveShare',
        js.includes('planFromModal, closeModal, onBackdrop,\n    onVideoDrive, onVideoDriveToken, onVideoDriveShare,\n  };'));
    const m1 = js.indexOf('  function rememberNewTaskForm() {');
    const m2 = js.indexOf('  function lsGet(k) {');
    const mem = {};
    const mels = { 'cx-f-assignee': { value: '' }, 'cx-f-approval': { checked: true }, 'cx-f-priority': { value: '0' }, 'cx-v-review': { checked: true },
        'cx-v-drive': { checked: true }, 'cx-v-drive-token': { value: 'B2' }, 'cx-v-drive-share': { value: 'private' } };
    const remember = new Function('G_ASSIGNEE_KEY', 'G_APPROVAL_KEY', 'G_PRIORITY_KEY', 'CV_REVIEW_KEY', 'CV_DRIVE_KEY', 'CV_DRIVE_TOKEN_KEY', 'CV_DRIVE_SHARE_KEY', '$', 'lsGet', 'lsSet',
        `${js.slice(m1, m2)}; return rememberNewTaskForm;`)('g1', 'g2', 'g3', 'cv', 'codex.cvDrive', 'codex.cvDriveToken', 'codex.cvDriveShare', id => mels[id], k => mem[k] || '', (k, v) => { mem[k] = v; });
    remember();
    check('nhớ: tick + tài khoản', mem['codex.cvDrive'] === '1' && mem['codex.cvDriveToken'] === 'B2', mem);
    mels['cx-v-drive'].checked = false;
    mels['cx-v-drive-token'].value = 'A1';
    remember();
    check('bỏ tick → nhớ "0", không đè tài khoản đã nhớ', mem['codex.cvDrive'] === '0' && mem['codex.cvDriveToken'] === 'B2', mem);
    check('nhớ cả quyền thư mục', mem['codex.cvDriveShare'] === 'private', mem);

    console.log('── 5. khớp máy chủ ─────────────────────────────────────');
    check('can_write của JS khớp drive_export.py',
        py.includes('" drive " in joined or " drive_file " in joined') && py.includes('"auth/drive " in joined or "auth/drive.file" in joined')
        && js.includes("joined.includes(' drive ') || joined.includes(' drive_file ')") && js.includes("joined.includes('auth/drive ') || joined.includes('auth/drive.file')"));
    check('/assignees trả auth_creds (không gửi cả system_prompt)', routes.includes('"auth_creds": granted_auth_creds(getattr(a, "system_prompt", "") or "")'));

    console.log('── 6. bản dịch ─────────────────────────────────────────');
    const KEYS = {
        'codex.field_video_drive': [], 'codex.field_video_drive_hint': [], 'codex.field_video_drive_account': [], 'codex.cv_drive_loading': [],
        'codex.cv_drive_none': [], 'codex.cv_drive_load_failed': ['{msg}'], 'codex.cv_drive_readonly': [], 'codex.cv_drive_group_granted': ['{agent}'],
        'codex.cv_drive_group_other': [], 'codex.cv_drive_granted_hint': ['{agent}'], 'codex.cv_drive_not_granted_hint': ['{agent}'],
        'codex.toast_video_drive_account_required': [], 'codex.field_video_drive_share': [], 'codex.cv_drive_share_public': [],
        'codex.cv_drive_share_private': [], 'codex.cv_drive_share_hint': [],
    };
    for (const lang of ['en', 'vi', 'es', 'ja', 'ko', 'ru', 'tr', 'zh', 'zh-TW']) {
        const loc = JSON.parse(fs.readFileSync(path.join(dir, 'locales', lang + '.json'), 'utf-8'));
        const bad = Object.entries(KEYS).filter(([k, ph]) => !loc[k] || ph.some(p => !loc[k].includes(p)));
        check(`${lang}.json: đủ 16 khoá + chỗ giữ`, !bad.length, bad.map(x => x[0]));
        const used = Object.keys(KEYS).filter(k => !js.includes(`'${k}'`) && !html.includes(`"${k}"`));
        if (lang === 'en') check('mọi khoá đều được dùng trong codex.js / codex.html', !used.length, used);
    }
    const vi = JSON.parse(fs.readFileSync(path.join(dir, 'locales', 'vi.json'), 'utf-8'));
    check('vi dịch thật', vi['codex.field_video_drive'] === 'Lưu lên Google Drive' && vi['codex.cv_drive_not_granted_hint'].includes('chỉ dùng cho task này')
        && vi['codex.cv_drive_share_public'].includes('xem và tải'));

    console.log();
    console.log(fail ? `${pass}/${pass + fail} PASS — ${fail} HỎNG` : `${pass}/${pass + fail} PASS`);
    process.exit(fail ? 1 : 0);
})();
