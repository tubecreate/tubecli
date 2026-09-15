/**
 * Codex Activity (lõi .101, 15/9/2026): ô «Đang làm» (bước, việc AI đang làm, %, đã chạy, còn lại), không lặp dòng
 * khi hai lượt tải chồng nhau, ẩn checkpoint, dòng của bước ghi tên bước.
 *
 *   1. stepFraction: % máy chủ gửi / "12/69" / "scenes 7-12 of 60" / không có
 *   2. nowHtml + nowTimeText: bước đang chạy, việc đang làm, %, "đã chạy … · còn khoảng …"; chờ bước; task xong
 *   3. eventsHtml: ẩn checkpoint, tên bước thay "[worker]", dòng xong có thời lượng + chi tiết
 *   4. loadEvents: hai lượt chồng nhau không nhân đôi; lô trùng một phần chỉ nối phần mới; giữ tối đa EVENTS_KEEP
 *   5. tĩnh + bản dịch 9 ngôn ngữ
 *
 * Run:  node tests/codex_activity_ui_test.js     (exit 0 = pass)
 */
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const here = path.dirname(fileURLToPath(import.meta.url));
const dir = path.join(here, '..', 'tubecli', 'extensions', 'codex');
const js = fs.readFileSync(path.join(dir, 'static', 'codex.js'), 'utf-8').replace(/\r\n/g, '\n');

let failed = 0;
const check = (name, ok, detail) => {
  if (ok) { console.log('  ok  ' + name); return; }
  failed++;
  console.log('  FAIL ' + name + (detail !== undefined ? ' — ' + JSON.stringify(detail).slice(0, 300) : ''));
};

function slice(start, end) {
  const a = js.indexOf(start), b = js.indexOf(end, a + 1);
  if (a < 0 || b < 0) throw new Error('cannot slice ' + start + ' … ' + end);
  return js.slice(a, b);
}

const NOW = Date.parse('2026-09-15T14:31:40+07:00');
const state = { events: {}, cursor: {}, eventsLoaded: {}, eventsBusy: {}, expanded: new Set() };
const T = {
  'codex.now_title': 'Now', 'codex.now_elapsed': 'running {t}', 'codex.now_eta': 'about {t} left',
  'codex.now_eta_unknown': 'estimating time left', 'codex.now_waiting': 'Waiting for the next step…',
  'codex.ev_started': 'started', 'codex.events_loading': 'Loading…', 'codex.no_events': 'No activity',
  'codex.step_success': 'Success', 'codex.step_error': 'Error',
};
const t = (k, vars) => String(T[k] || k).replace(/\{(\w+)\}/g, (_, n) => (vars && vars[n] !== undefined ? vars[n] : ''));
const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const icon = (n) => `<i>${n}</i>`;
const parseTs = (s) => { const v = Date.parse(s); return isNaN(v) ? null : new Date(v); };
const stepLabel = (s) => T['codex.step_' + s] || s;
const clockTime = () => '14:31:40';
let apiCalls = 0;
let apiImpl = async () => ({ events: [] });
const api = async (url) => { apiCalls++; return apiImpl(url); };
const taskUrl = (id, qs) => '/tasks/' + id + qs;
const EVENT_ICON = { created: 'a', state: 'b', step: 'c', log: 'd', approval: 'e', result: 'f', error: 'g', plan: 'h', progress: 'i' };
const EVENTS_KEEP = 150;
const $ = () => null;

const code = [
  slice('  function fmtSecs(sec) {', '  function duration(from, to) {'),
  slice('  async function loadEvents(id, initial) {', '  async function pollEvents() {'),
  slice('  function stepFraction(s) {', '  // ── Interaction'),
].join('\n');
const api2 = new Function('state', 't', 'esc', 'icon', 'parseTs', 'serverNow', 'stepLabel', 'clockTime', 'api', 'taskUrl',
  'EVENT_ICON', 'EVENTS_KEEP', '$',
  `${code}; return { fmtSecs, loadEvents, evKey, stepFraction, nowHtml, nowTimeText, patchNow, eventsHtml };`)(
  state, t, esc, icon, parseTs, () => NOW, stepLabel, clockTime, api, taskUrl, EVENT_ICON, EVENTS_KEEP, $);

console.log('── 1. stepFraction ─────────────────────────────────────');
check('% máy chủ gửi', api2.stepFraction({ progress: 20, message: 'writing scenes 13-18 of 60' }) === 0.2);
check('"12/69"', Math.abs(api2.stepFraction({ progress: null, message: '12/69 · CapCut' }) - 12 / 69) < 1e-9);
check('"scenes 7-12 of 60" → 6 cảnh đã xong', api2.stepFraction({ message: 'writing scenes 7-12 of 60' }) === 0.1);
check('không có gì → null', api2.stepFraction({ message: 'outline came back with 74 scenes, 60 planned — asking again' }) === null
  && api2.stepFraction({ progress: 0, message: 'Write the script' }) === null);

console.log('── 2. ô «Đang làm» ─────────────────────────────────────');
const task = {
  status: 'running',
  steps: [
    { name: 'gather', label: "Read the agent's corpus", status: 'success', started_at: '2026-09-15T14:30:00+07:00' },
    { name: 'script', label: 'Write the script', status: 'running', message: 'writing scenes 13-18 of 60', progress: 20,
      started_at: '2026-09-15T14:30:00+07:00' },
  ],
};
const html = api2.nowHtml(task);
check('ghi bước đang chạy + việc AI đang làm + %', html.includes('Write the script') && html.includes('writing scenes 13-18 of 60')
  && html.includes('20%') && html.includes('data-start="2026-09-15T14:30:00+07:00"'), html);
const el = { getAttribute: (n) => (n === 'data-start' ? '2026-09-15T14:30:00+07:00' : '0.2000') };
check('đã chạy 1m 40s · còn khoảng 6m 40s (100 s cho 20 %)', api2.nowTimeText(el) === 'running 1m 40s · about 6m 40s left', api2.nowTimeText(el));
const el0 = { getAttribute: (n) => (n === 'data-start' ? '2026-09-15T14:30:00+07:00' : '') };
check('chưa biết phần đã xong → đang ước tính', api2.nowTimeText(el0) === 'running 1m 40s · estimating time left', api2.nowTimeText(el0));
check('không bước nào chạy nhưng task đang chạy → chờ bước tiếp', api2.nowHtml({ status: 'running', steps: [] }).includes('Waiting for the next step'));
check('task xong → không có ô', api2.nowHtml({ status: 'done', steps: [{ status: 'success' }] }) === '');

console.log('── 3. eventsHtml ───────────────────────────────────────');
state.eventsLoaded.x = true;
state.events.x = [
  { ts: '1', kind: 'log', actor: 'content_video', message: 'checkpoint' },
  { ts: '2', kind: 'step', actor: 'worker', message: '▶ Write the script', data: { step: 'script', status: 'running', label: 'Write the script' } },
  { ts: '3', kind: 'progress', actor: 'worker', message: 'outline came back with 74 scenes, 60 planned — asking again', data: { step: 'script', label: 'Write the script' } },
  { ts: '4', kind: 'step', actor: 'worker', message: 'Generate shot images — success (2m 3s) · 69/69', data: { step: 'images', status: 'success', label: 'Generate shot images', elapsed: 123, detail: '69/69' } },
];
const eh = api2.eventsHtml('x');
check('ẩn checkpoint', !eh.includes('checkpoint'), eh);
check('tên bước thay [worker]', !eh.includes('[worker]') && eh.includes('[Write the script]') && eh.includes('[Generate shot images]'), eh);
check('dòng bắt đầu / việc đang làm / xong có thời lượng', eh.includes('>started<') && eh.includes('asking again')
  && eh.includes('Success · 2m 3s · 69/69') && eh.includes('k-progress'), eh);

console.log('── 4. loadEvents không lặp ─────────────────────────────');
(async () => {
  const batch = [
    { ts: 'a', kind: 'step', message: 'gather: success' },
    { ts: 'b', kind: 'step', message: 'Write the script' },
  ];
  state.events.y = [{ ts: '0', kind: 'state', message: '→ running' }];
  state.cursor.y = '0';
  state.eventsLoaded.y = true;
  let release;
  apiImpl = () => new Promise(res => { release = () => res({ events: batch }); });
  const p1 = api2.loadEvents('y', false);
  const p2 = api2.loadEvents('y', false);          // nhịp thứ hai tới khi lượt đầu còn chờ
  release();
  const [n1, n2] = await Promise.all([p1, p2]);
  check('lượt chồng bị bỏ, không nối lô hai lần', n1 === 2 && n2 === 0 && state.events.y.length === 3 && apiCalls === 1,
    { n1, n2, len: state.events.y.length, apiCalls });
  apiImpl = async () => ({ events: [batch[1], { ts: 'c', kind: 'progress', message: 'outline · 60 scenes' }] });
  await api2.loadEvents('y', false);
  check('lô trùng một phần → chỉ nối phần mới', state.events.y.map(e => e.ts).join(',') === '0,a,b,c', state.events.y.map(e => e.ts));
  apiImpl = async () => ({ events: Array.from({ length: 300 }, (_, i) => ({ ts: 'z' + i, kind: 'log', message: 'm' + i })) });
  await api2.loadEvents('y', true);
  check('giữ tối đa EVENTS_KEEP dòng trong trình duyệt', state.events.y.length === 150 && state.events.y[149].ts === 'z299');

  console.log('── 5. tĩnh + bản dịch ──────────────────────────────────');
  check('ô «Đang làm» nằm trên Activity', js.includes('<div id="cx-now-${id}">${nowHtml(task)}</div>\n        <div class="cx-events" id="cx-ev-${id}">'));
  check('nhịp sự kiện + renderList điền thời gian', /pollEvents\(\);\n\s+patchNow\(\);/.test(js) && /\n    patchNow\(\);\n  \}\n\n  function buildListHtml/.test(js));
  const css = fs.readFileSync(path.join(dir, 'static', 'codex.css'), 'utf-8');
  check('CSS ô «Đang làm» + dòng tiến độ', css.includes('.cx-now {') && css.includes('.cx-ev.k-progress'));
  const KEYS = ['codex.now_title', 'codex.now_elapsed', 'codex.now_eta', 'codex.now_eta_unknown', 'codex.now_waiting', 'codex.ev_started'];
  for (const lang of ['en', 'vi', 'es', 'ja', 'ko', 'ru', 'tr', 'zh', 'zh-TW']) {
    const loc = JSON.parse(fs.readFileSync(path.join(dir, 'locales', lang + '.json'), 'utf-8'));
    const bad = KEYS.filter(k => !loc[k] || (['codex.now_elapsed', 'codex.now_eta'].includes(k) && !loc[k].includes('{t}')));
    check(`${lang}.json: đủ 6 khoá`, !bad.length, bad);
  }
  console.log(failed ? `\n${failed} FAIL` : '\nALL PASS');
  process.exit(failed ? 1 : 0);
})();
