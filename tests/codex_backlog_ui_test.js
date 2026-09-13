/**
 * Giao diện hàng đợi Codex (13/9/2026): nút "Đưa vào hàng đợi", trạng thái backlog, Chạy ngay.
 *
 *   1. backlogPosition sắp y hệt _backlog_key của manager.py (chạy Python thật để so)
 *   2. Bảng: STATES / ACTIVE_STATES / STATUS_ICON / STAT_TILES / nút trên thẻ / màu CSS
 *   3. Cửa sổ: #cx-queue-btn ẩn mặc định, chỉ hiện với video; submitVideo gửi queue;
 *      bước xong nói theo trạng thái THẬT của task
 *   4. Route /run-now có ở cả hai đầu
 *   5. Bản dịch: đủ 9 ngôn ngữ, đủ chỗ giữ {…}; "Hàng đợi" không đứng cạnh một nhãn na ná
 *
 * Run:  node tests/codex_backlog_ui_test.js     (exit 0 = pass)
 */
import fs from 'fs';
import path from 'path';
import { spawnSync } from 'child_process';
import { fileURLToPath } from 'url';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.join(here, '..');
const dir = path.join(root, 'tubecli', 'extensions', 'codex');
// Bản checkout trên Windows có thể là CRLF: chuẩn hoá trước khi so chuỗi nhiều dòng.
const read = (...p) => fs.readFileSync(path.join(dir, ...p), 'utf-8').replace(/\r\n/g, '\n');
const js = read('static', 'codex.js');
const html = read('static', 'codex.html');
const css = read('static', 'codex.css');
const routes = read('routes.py');
const manager = read('manager.py');

let failed = 0;
const check = (name, ok, detail) => {
    if (ok) { console.log('  ok  ' + name); return; }
    failed++;
    console.log('  FAIL ' + name + (detail !== undefined ? ' — ' + JSON.stringify(detail) : ''));
};

// ── 1. Thứ tự trong hàng: JS và Python phải ra cùng con số ────────────────────
console.log('── thứ tự trong hàng đợi ─────────────────────────────────');
const a = js.indexOf('  function backlogPosition(task) {');
const b = js.indexOf('  function stripHtml(task) {');
check('tìm được backlogPosition trong codex.js', a > 0 && b > a, { a, b });
const TASKS = [
    { id: 'v1', seq: 1, status: 'backlog', lane: 'video', created_at: '2026-09-13T10:00:00.000001+07:00' },
    { id: 'v2', seq: 2, status: 'backlog', lane: 'video', created_at: '2026-09-13T10:00:00.000001+07:00' },
    { id: 'v3', seq: 3, status: 'backlog', lane: 'video', created_at: '2026-09-13T09:00:00+07:00', priority: 0 },
    { id: 'p9', seq: 9, status: 'backlog', lane: 'video', created_at: '2026-09-13T11:00:00+07:00', priority: 5 },
    { id: 'x1', seq: 4, status: 'backlog', lane: 'x', created_at: '2026-09-13T08:00:00+07:00' },
    { id: 'g1', seq: 5, status: 'backlog', created_at: '2026-09-13T07:00:00+07:00' },
    { id: 'q1', seq: 6, status: 'queued', lane: 'video', created_at: '2026-09-13T06:00:00+07:00' },
];
const pos = new Function('state', `${js.slice(a, b)}; return backlogPosition;`)({ tasks: TASKS });
const byId = Object.fromEntries(TASKS.map(x => [x.id, pos(x)]));
check('ưu tiên cao đứng đầu, rồi tạo trước', byId.p9 === 1 && byId.v3 === 2, byId);
check('trùng mốc: số task nhỏ trước', byId.v1 === 3 && byId.v2 === 4, byId);
check('làn khác đếm riêng; không có lane = làn chung', byId.x1 === 1 && byId.g1 === 1, byId);
check('không nằm hàng đợi → 0', byId.q1 === 0, byId);

const py = spawnSync('python', ['-X', 'utf8', '-c', [
    'import json, sys',
    `sys.path.insert(0, ${JSON.stringify(root)})`,
    'from tubecli.extensions.codex.manager import _backlog_key',
    'tasks = json.loads(sys.stdin.read())',
    'lanes = {}',
    'for t in tasks:',
    '    if t["status"] == "backlog":',
    '        lanes.setdefault(t.get("lane") or "", []).append(t)',
    'out = {t["id"]: 0 for t in tasks}',
    'for line in lanes.values():',
    '    for i, t in enumerate(sorted(line, key=_backlog_key), 1):',
    '        out[t["id"]] = i',
    'print(json.dumps(out))',
].join('\n')], { input: JSON.stringify(TASKS), encoding: 'utf-8' });
let pyPos = null;
try { pyPos = JSON.parse(String(py.stdout).trim().split('\n').pop()); } catch (e) { /* báo bên dưới */ }
check('Python _backlog_key cho đúng cùng thứ tự', pyPos && JSON.stringify(pyPos) === JSON.stringify(byId),
    { py: pyPos, js: byId, err: String(py.stderr || '').slice(-400) });

// ── 2. Bảng ──────────────────────────────────────────────────────────────────
console.log('── bảng ──────────────────────────────────────────────────');
check('STATES: backlog ngay sau pending_approval', js.includes("'pending_approval', 'backlog', 'queued', 'running', 'review',"));
check('ACTIVE_STATES có backlog', js.includes("new Set(['pending_approval', 'backlog', 'queued', 'running', 'review'])"));
check('STATUS_ICON có backlog', /\n\s+backlog: 'stacks',\n/.test(js));
check('ô thống kê Hàng đợi', js.includes("{ key: 'backlog', filter: 'backlog', icon: 'stacks', label: 'codex.stat_backlog' }"));
const actions = js.slice(js.indexOf('function actionsHtml('), js.indexOf('function bodyHtml('));
check('thẻ trong hàng đợi: Chạy ngay + Huỷ',
    /case 'backlog':\s*return b\('cx-btn-ghost', 'runNow', 'play_arrow', 'codex\.action_run_now'\) \+\s*b\('cx-btn-ghost', 'cancel',/.test(actions));
check('runNow gọi /run-now', js.includes("act(id, '/run-now', { actor: ACTOR }, 'codex.toast_run_now')"));
check('thẻ hiện "thứ N trong hàng"', js.includes("t('codex.meta_backlog_pos', { n: pos })"));
const exported = js.slice(js.lastIndexOf('return {'));
check('xuất runNow + queueVideo cho onclick', /\brunNow\b/.test(exported) && /\bqueueVideo\b/.test(exported), exported);
check('CSS: màu riêng cho backlog', css.includes('.cx-card.st-backlog, .cx-stat.st-backlog, .cx-chip.st-backlog'));

// ── 3. Cửa sổ tạo video ──────────────────────────────────────────────────────
console.log('── cửa sổ tạo video ──────────────────────────────────────');
const btn = (html.match(/<button[^>]*id="cx-queue-btn"[\s\S]*?<\/button>/) || [''])[0];
check('có #cx-queue-btn, ẩn mặc định, gọi CODEX.queueVideo()',
    /class="[^"]*\bhidden\b[^"]*"/.test(btn) && btn.includes('onclick="CODEX.queueVideo()"'), btn);
const iCancel = html.indexOf('data-i18n="codex.btn_cancel">Cancel</button>');
check('nút nằm giữa Huỷ và Tạo', iCancel > 0 && iCancel < html.indexOf('id="cx-queue-btn"')
    && html.indexOf('id="cx-queue-btn"') < html.indexOf('id="cx-create-btn"'));
check('nhãn + gợi ý dùng khoá dịch',
    btn.includes('data-i18n="codex.btn_queue_video"') && btn.includes('data-i18n-title="codex.btn_queue_video_hint"'));
const kind = js.slice(js.indexOf('function setNewKind('), js.indexOf('async function loadPresets('));
check('setNewKind: nút chỉ hiện với video', kind.includes("$('cx-queue-btn').classList.toggle('hidden', !video);"));
const sv = js.slice(js.indexOf('async function submitVideo('), js.indexOf('async function planFromModal('));
check('submitVideo gửi queue', sv.includes("created_by: 'user', queue: hold,"));
check('chỉ queue === true mới là hàng đợi; "Tạo video" gọi submitVideo() không đối số',
    sv.includes('const hold = queue === true;') && js.includes("if (state.newKind === 'video') return submitVideo();"));
check('bước xong nói theo trạng thái THẬT (máy chủ cũ trả queued thì không báo hàng đợi)',
    sv.includes("if (task.status === 'backlog')") && sv.includes("'codex.created_backlog_title'")
    && sv.includes("'codex.created_video_title'"));
check('khoá cả hai nút lúc đang gửi, mở lại khi xong',
    sv.includes("const btns = [$('cx-create-btn'), $('cx-queue-btn')];") && sv.includes('btns.forEach(b => { b.disabled = false; });'));

// ── 4. Route ở cả hai đầu ────────────────────────────────────────────────────
console.log('── route ─────────────────────────────────────────────────');
check('POST /tasks/{task_id}/run-now → codex_manager.run_now',
    routes.includes('@router.post("/tasks/{task_id}/run-now")') && routes.includes('codex_manager.run_now'));
check('claim_next thả hàng đợi trước khi chọn',
    /def claim_next[\s\S]*?released = self\._release_backlog\(\)[\s\S]*?candidates = /.test(manager));

// ── 5. Bản dịch ──────────────────────────────────────────────────────────────
console.log('── bản dịch ──────────────────────────────────────────────');
const LANGS = ['en', 'vi', 'es', 'ja', 'ko', 'ru', 'tr', 'zh-TW', 'zh'];
const KEYS = {
    'codex.stat_backlog': [], 'codex.status_backlog': [], 'codex.action_run_now': [],
    'codex.meta_backlog_pos': ['n'], 'codex.toast_run_now': ['seq'],
    'codex.btn_queue_video': [], 'codex.btn_queue_video_hint': [],
    'codex.toast_video_backlog': ['seq'], 'codex.created_backlog_title': ['pos', 'seq'],
    'codex.created_backlog_desc_review': [], 'codex.created_backlog_desc_auto': [],
};
const vars = s => [...String(s).matchAll(/\{(\w+)\}/g)].map(m => m[1]).sort();
const used = [...js.matchAll(/'(codex\.[a-z_]+backlog[a-z_]*|codex\.[a-z_]*run_now|codex\.btn_queue_video[a-z_]*)'/g)].map(m => m[1]);
check('mọi khoá hàng đợi trong codex.js đều có trong danh sách kiểm', used.every(k => k in KEYS), used);
for (const lang of LANGS) {
    const L = JSON.parse(read('locales', lang + '.json'));
    const missing = Object.keys(KEYS).filter(k => !L[k]);
    check(`${lang}: đủ khoá`, !missing.length, missing);
    const bad = Object.entries(KEYS).filter(([k, want]) => L[k] && JSON.stringify(vars(L[k])) !== JSON.stringify(want)).map(([k]) => k);
    check(`${lang}: đủ chỗ giữ {…}`, !bad.length, bad);
    const q = L['codex.status_backlog'];
    check(`${lang}: nhãn hàng đợi khác nhãn queued / chờ duyệt`,
        q !== L['codex.status_queued'] && q !== L['codex.status_pending_approval']
        && L['codex.stat_backlog'] !== L['codex.stat_queued'], [q, L['codex.status_queued']]);
}
const VI = JSON.parse(read('locales', 'vi.json'));
check('vi: "Hàng đợi" + nút "Đưa vào hàng đợi"', VI['codex.status_backlog'] === 'Hàng đợi' && VI['codex.btn_queue_video'] === 'Đưa vào hàng đợi');
check('vi: queued đổi "Hàng chờ" → "Sắp chạy" (khỏi na ná "Hàng đợi")',
    VI['codex.status_queued'] === 'Sắp chạy' && VI['codex.stat_queued'] === 'Sắp chạy');

console.log(failed ? `\n${failed} HỎNG` : '\nALL PASS');
process.exit(failed ? 1 : 0);
