/**
 * Codex: mục «AI plan» THU GỌN mặc định, bấm tiêu đề mới mở (13/9/2026).
 *
 * Người dùng: "cái phần kịch bản AI Plan bạn giúp tôi mặc định thu gọn lại, khi cần xem chi
 * tiết thì mới bấm mở ra xem cho gọn". Kế hoạch của «Tạo video từ nội dung» là cả kịch bản
 * (hàng chục cảnh dài) nên mở thẻ ra là phải kéo qua cả trang mới tới các bước và nhật ký.
 *
 *   1. bodyHtml thật (cắt từ codex.js): chưa mở → chỉ tiêu đề + số bước, KHÔNG có cảnh nào;
 *      đã mở → đủ mọi cảnh; tiêu đề là nút có aria-expanded
 *   2. togglePlan lật trạng thái và vẽ lại; trạng thái nằm trong state nên lượt tự làm mới
 *      (vẽ lại cả danh sách) không đóng lại; task biến mất thì được dọn
 *   3. CSS + bản dịch đủ 9 ngôn ngữ, đủ chỗ giữ {n}
 *
 * Run:  node tests/codex_plan_collapse_test.js     (exit 0 = pass)
 */
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const here = path.dirname(fileURLToPath(import.meta.url));
const dir = path.join(here, '..', 'tubecli', 'extensions', 'codex');
const read = (...p) => fs.readFileSync(path.join(dir, ...p), 'utf-8').replace(/\r\n/g, '\n');
const js = read('static', 'codex.js');
const css = read('static', 'codex.css');

let failed = 0;
const check = (name, ok, detail) => {
    if (ok) { console.log('  ok  ' + name); return; }
    failed++;
    console.log('  FAIL ' + name + (detail !== undefined ? ' — ' + JSON.stringify(detail).slice(0, 300) : ''));
};

// ── 1. bodyHtml thật ─────────────────────────────────────────────────────────
console.log('── bodyHtml: thu gọn mặc định ───────────────────────────────');
const a = js.indexOf('  function bodyHtml(task) {');
const b = js.indexOf('  function collapse(taskId) {');
check('cắt được bodyHtml khỏi codex.js', a > 0 && b > a, { a, b });
// detailBusy: bodyHtml đọc state.detailBusy[task.id] từ bản «mở thẻ mới tải chi tiết» — thiếu nó
// thì test ném TypeError chứ không phải báo sai kết quả.
const state = { planOpen: new Set(), planning: {}, busy: {}, detailBusy: {}, events: {}, eventsLoaded: {} };
const stubs = {
    state,
    t: (k, p) => k + (p ? JSON.stringify(p) : ''),
    esc: s => String(s == null ? '' : s),
    icon: (n, c) => `<i class="${c || ''}">${n}</i>`,
    eventsHtml: () => '', mediaPreviewHtml: () => '', duration: () => '',
    stepLabel: s => s, STEP_ICON: {}, clockTime: s => s, linkify: s => s,
};
const bodyHtml = new Function(...Object.keys(stubs), `${js.slice(a, b)}; return bodyHtml;`)(...Object.values(stubs));
const plan = Array.from({ length: 12 }, (_, i) => ({ step: i + 1, description: `SHOW: cảnh ${i + 1} rất dài`, agent_name: 'Orchestrator' }));
const task = { id: 't1', status: 'review', goal: 'Video from content', plan, steps: [] };

let html = bodyHtml(task);
check('chưa mở: có tiêu đề AI plan là NÚT bấm được', html.includes('onclick="CODEX.togglePlan(\'t1\')"')
    && html.includes('aria-expanded="false"') && html.includes('codex.section_plan'), html.slice(0, 400));
check('chưa mở: KHÔNG vẽ cảnh nào', !html.includes('cx-plan-item') && !html.includes('cảnh 1 rất dài'));
check('chưa mở: nói số bước để biết có gì bên trong', html.includes('codex.plan_count{"n":12}'));
check('chưa mở: gợi ý "xem kế hoạch" + mũi tên mở', html.includes('codex.plan_show') && html.includes('>expand_more<'));

state.planOpen.add('t1');
html = bodyHtml(task);
check('đã mở: đủ 12 cảnh', (html.match(/cx-plan-item/g) || []).length === 12 && html.includes('cảnh 12 rất dài'));
check('đã mở: aria-expanded=true, gợi ý thu gọn + mũi tên đóng', html.includes('aria-expanded="true"')
    && html.includes('codex.plan_hide') && html.includes('>expand_less<'));
check('task khác vẫn thu gọn', !bodyHtml({ ...task, id: 't2' }).includes('cx-plan-item'));
check('không có kế hoạch mà lập được: vẫn là nút "Lập kế hoạch"',
    bodyHtml({ id: 't3', status: 'failed', goal: '', plan: [], steps: [] }).includes('CODEX.planTask(\'t3\')'));

// ── 2. togglePlan + giữ qua lượt làm mới + dọn ───────────────────────────────
console.log('── togglePlan / làm mới / dọn ───────────────────────────────');
const c = js.indexOf('  function togglePlan(taskId) {');
const d = js.indexOf('  async function toggle(taskId) {');
check('có togglePlan', c > 0 && d > c, { c, d });
let renders = 0;
const st2 = { planOpen: new Set() };
const togglePlan = new Function('state', 'renderList', `${js.slice(c, d)}; return togglePlan;`)(st2, () => { renders++; });
togglePlan('x');
check('bấm lần 1 → mở + vẽ lại', st2.planOpen.has('x') && renders === 1);
togglePlan('x');
check('bấm lần 2 → đóng + vẽ lại', !st2.planOpen.has('x') && renders === 2);
check('trạng thái nằm trong state (lượt tự làm mới vẽ lại từ state, không đóng lại)',
    js.includes('planOpen: new Set(),') && js.includes('const open = state.planOpen.has(task.id);'));
check('xuất ra CODEX để onclick gọi được', /init, refresh, toggle, collapse, togglePlan,/.test(js));
const e = js.indexOf('  function pruneState() {');
const f = js.indexOf('  async function loadEvents(id, initial) {');
const st3 = { tasks: [{ id: 'keep' }], events: {}, cursor: {}, eventsLoaded: {}, expanded: new Set(), planOpen: new Set(['keep', 'gone']) };
new Function('state', `${js.slice(e, f)}; return pruneState;`)(st3)();
check('task biến mất thì bỏ khỏi planOpen', st3.planOpen.has('keep') && !st3.planOpen.has('gone'), [...st3.planOpen]);

// ── 3. CSS + bản dịch ────────────────────────────────────────────────────────
console.log('── CSS + bản dịch ───────────────────────────────────────────');
check('CSS: nút tiêu đề không viền/nền, có con trỏ + focus nhìn thấy được',
    /\.cx-section-toggle \{[^}]*cursor: pointer/.test(css) && css.includes('.cx-section-toggle:focus-visible')
    && css.includes('.cx-section-count') && css.includes('.cx-section-chev'));
for (const lang of ['en', 'vi', 'zh', 'zh-TW', 'ja', 'ko', 'ru', 'tr', 'es']) {
    const loc = JSON.parse(read('locales', lang + '.json'));
    check(`${lang}: plan_count có {n}, có plan_show/plan_hide`,
        String(loc['codex.plan_count'] || '').includes('{n}') && !!loc['codex.plan_show'] && !!loc['codex.plan_hide']);
}

console.log(failed ? `\n${failed} FAIL` : '\nALL PASS');
process.exit(failed ? 1 : 0);
