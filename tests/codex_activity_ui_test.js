/**
 * Codex Activity (lõi .101 → .102, 15/9/2026): bước đang chạy trong danh sách bước là nơi DUY NHẤT kể đang làm gì /
 * tới đâu / còn bao lâu (bỏ ô «Đang làm» trùng thanh tiến độ); Activity là lịch sử gọn, không lặp dòng.
 *
 *   1. stepFraction: % máy chủ gửi / "12/69" / "scenes 7-12 of 60" / không có
 *   2. stepEtaHtml + nowTimeText + patchNow: "đã chạy … · còn khoảng …" dưới bước đang chạy; chờ bước tiếp
 *   3. activityRows / eventsHtml: bỏ "bắt đầu", gộp bước một câu vào dòng Xong, bước dài giữ từng câu, ẩn checkpoint
 *   4. loadEvents: hai lượt chồng nhau không nhân đôi; lô trùng một phần chỉ nối phần mới; giữ tối đa EVENTS_KEEP
 *   5. tĩnh: một thanh tiến độ duy nhất, không còn ô «Đang làm»; CSS; bản dịch
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
  'codex.now_elapsed': 'running {t}', 'codex.now_eta': 'about {t} left', 'codex.now_eta_unknown': 'estimating time left',
  'codex.now_waiting': 'Waiting for the next step…', 'codex.events_loading': 'Loading…', 'codex.no_events': 'No activity',
  'codex.step_success': 'Done', 'codex.step_error': 'Error',
};
const t = (k, vars) => String(T[k] || k).replace(/\{(\w+)\}/g, (_, n) => (vars && vars[n] !== undefined ? vars[n] : ''));
const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const icon = (n) => `<i>${n}</i>`;
const parseTs = (s) => { const v = Date.parse(s); return isNaN(v) ? null : new Date(v); };
const stepLabel = (s) => T['codex.step_' + s] || s;
const clockTime = () => '14:53:25';
let apiCalls = 0;
let apiImpl = async () => ({ events: [] });
const api = async (url) => { apiCalls++; return apiImpl(url); };
const taskUrl = (id, qs) => '/tasks/' + id + qs;
const EVENT_ICON = { created: 'a', state: 'b', step: 'c', log: 'd', approval: 'e', result: 'f', error: 'g', plan: 'h', progress: 'i' };
const EVENTS_KEEP = 150;
const ETA_EL = { textContent: '', getAttribute: (n) => (n === 'data-start' ? '2026-09-15T14:30:00+07:00' : '0.2000') };
const $ = (id) => (id === 'cx-card-x' ? { querySelectorAll: (sel) => (sel === '.cx-step-eta[data-start]' ? [ETA_EL] : []) } : null);

const code = [
  slice('  function fmtSecs(sec) {', '  function duration(from, to) {'),
  slice('  async function loadEvents(id, initial) {', '  async function pollEvents() {'),
  slice('  function stepFraction(s) {', '  // ── Interaction'),
].join('\n');
const U = new Function('state', 't', 'esc', 'icon', 'parseTs', 'serverNow', 'stepLabel', 'clockTime', 'api', 'taskUrl',
  'EVENT_ICON', 'EVENTS_KEEP', '$',
  `${code}; return { fmtSecs, loadEvents, evKey, stepFraction, stepEtaHtml, waitingHtml, nowTimeText, patchNow, activityRows, eventsHtml };`)(
  state, t, esc, icon, parseTs, () => NOW, stepLabel, clockTime, api, taskUrl, EVENT_ICON, EVENTS_KEEP, $);

console.log('── 1. stepFraction ─────────────────────────────────────');
check('% máy chủ gửi', U.stepFraction({ progress: 23, message: 'writing scenes 7-12 of 26' }) === 0.23);
check('"12/69"', Math.abs(U.stepFraction({ progress: null, message: '12/69 · CapCut' }) - 12 / 69) < 1e-9);
check('"scenes 7-12 of 60" → 6 cảnh đã xong', U.stepFraction({ message: 'writing scenes 7-12 of 60' }) === 0.1);
check('không có gì → null', U.stepFraction({ message: 'outline came back with 74 scenes, 60 planned — asking again' }) === null
  && U.stepFraction({ progress: 0, message: 'Write the script' }) === null);

console.log('── 2. thời gian dưới bước đang chạy ────────────────────');
const eta = U.stepEtaHtml({ started_at: '2026-09-15T14:30:00+07:00' }, 0.2);
check('chỗ trống mang mốc bắt đầu + phần đã xong', eta === '<div class="cx-step-eta" data-start="2026-09-15T14:30:00+07:00" data-frac="0.2000"></div>', eta);
check('đã chạy 1m 40s · còn khoảng 6m 40s (100 s cho 20 %)', U.nowTimeText(ETA_EL) === 'running 1m 40s · about 6m 40s left', U.nowTimeText(ETA_EL));
const noFrac = { getAttribute: (n) => (n === 'data-start' ? '2026-09-15T14:30:00+07:00' : '') };
check('chưa biết phần đã xong → đang ước tính', U.nowTimeText(noFrac) === 'running 1m 40s · estimating time left');
state.expanded = new Set(['x']);
U.patchNow();
check('patchNow điền dòng thời gian của thẻ đang mở', ETA_EL.textContent === 'running 1m 40s · about 6m 40s left', ETA_EL.textContent);
check('task chạy mà chưa bước nào chạy → chờ bước tiếp', U.waitingHtml({ status: 'running', steps: [{ status: 'success' }] }).includes('Waiting for the next step'));
check('có bước đang chạy / task xong → không có dòng chờ', U.waitingHtml({ status: 'running', steps: [{ status: 'running' }] }) === ''
  && U.waitingHtml({ status: 'done', steps: [] }) === '');

console.log('── 3. Activity = lịch sử gọn ───────────────────────────');
const S = (step, label, status, extra) => ({ kind: 'step', actor: 'worker', message: 'x', data: Object.assign({ step, label, status }, extra || {}) });
const P = (step, label, message) => ({ kind: 'progress', actor: 'worker', message, data: { step, label } });
const evs = [
  S('transcripts', 'Transcripts of watched videos', 'running'),
  P('transcripts', 'Transcripts of watched videos', 'no watched videos without text'),
  S('transcripts', 'Transcripts of watched videos', 'success', { elapsed: 0 }),
  S('crawl', 'Crawl extra sources', 'running'),
  P('crawl', 'Crawl extra sources', 'no extra sources'),
  S('crawl', 'Crawl extra sources', 'success', { elapsed: 0 }),
  { kind: 'log', actor: 'content_video', message: 'checkpoint' },
  S('script', 'Write the script', 'running'),
  P('script', 'Write the script', "structure reference: mapping the source's structure (no sentences kept)"),
  P('script', 'Write the script', 'outline · 26 scenes'),
  P('script', 'Write the script', 'writing scenes 1-6 of 26'),
].map((e, i) => Object.assign({ ts: 't' + i }, e));
const rows = U.activityRows(evs);
check('5 dòng: 2 bước ngắn gộp + 3 việc của bước đang chạy (trước: 11 dòng)', rows.length === 5, rows.map(r => r.who + ' ' + r.msg));
check('bước ngắn một câu → một dòng "Xong · 0s · câu"', rows[0].who === 'Transcripts of watched videos' && rows[0].msg === 'Done · 0s · no watched videos without text'
  && rows[1].msg === 'Done · 0s · no extra sources', rows.slice(0, 2));
check('không còn dòng "bắt đầu", không checkpoint', !rows.some(r => /start|checkpoint/i.test(r.msg)), rows);
check('bước đang chạy giữ từng việc AI đã làm', rows.slice(2).map(r => r.msg).join(' | ').includes('outline · 26 scenes | writing scenes 1-6 of 26'));
const longStep = [
  S('images', 'Generate shot images', 'running'), P('images', 'Generate shot images', '10/69'), P('images', 'Generate shot images', '40/69'),
  S('images', 'Generate shot images', 'success', { elapsed: 123, detail: '69/69' }),
].map((e, i) => Object.assign({ ts: 'i' + i }, e));
const r2 = U.activityRows(longStep);
check('bước nhiều câu → giữ từng câu + dòng Xong có thời lượng', r2.length === 3 && r2[2].msg === 'Done · 2m 3s · 69/69', r2.map(r => r.msg));
state.eventsLoaded.x = true;
state.events.x = evs;
const eh = U.eventsHtml('x');
check('eventsHtml vẽ đúng các dòng gọn, tên bước thay [worker]', !eh.includes('[worker]') && (eh.match(/cx-ev k-/g) || []).length === 5, eh);

console.log('── 4. loadEvents không lặp ─────────────────────────────');
(async () => {
  const batch = [{ ts: 'a', kind: 'step', message: 'gather' }, { ts: 'b', kind: 'step', message: 'script' }];
  state.events.y = [{ ts: '0', kind: 'state', message: '→ running' }];
  state.cursor.y = '0';
  state.eventsLoaded.y = true;
  let release;
  apiImpl = () => new Promise(res => { release = () => res({ events: batch }); });
  const p1 = U.loadEvents('y', false);
  const p2 = U.loadEvents('y', false);
  release();
  const [n1, n2] = await Promise.all([p1, p2]);
  check('lượt chồng bị bỏ, không nối lô hai lần', n1 === 2 && n2 === 0 && state.events.y.length === 3 && apiCalls === 1, { n1, n2, len: state.events.y.length, apiCalls });
  apiImpl = async () => ({ events: [batch[1], { ts: 'c', kind: 'progress', message: 'outline · 60 scenes' }] });
  await U.loadEvents('y', false);
  check('lô trùng một phần → chỉ nối phần mới', state.events.y.map(e => e.ts).join(',') === '0,a,b,c', state.events.y.map(e => e.ts));
  apiImpl = async () => ({ events: Array.from({ length: 300 }, (_, i) => ({ ts: 'z' + i, kind: 'log', message: 'm' + i })) });
  await U.loadEvents('y', true);
  check('giữ tối đa EVENTS_KEEP dòng trong trình duyệt', state.events.y.length === 150 && state.events.y[149].ts === 'z299');

  console.log('── 5. tĩnh + bản dịch ──────────────────────────────────');
  check('không còn ô «Đang làm» riêng', !js.includes('cx-now-${id}') && !js.includes('function nowHtml'));
  check('một thanh tiến độ duy nhất ở bước đang chạy + dòng thời gian + dòng chờ',
    js.includes("const frac = st === 'running' ? stepFraction(s) : null;") && js.includes("${st === 'running' ? stepEtaHtml(s, frac) : ''}")
    && js.includes("}).join('')}${waitingHtml(task)}</div>"));
  check('nhịp sự kiện + renderList điền thời gian', /pollEvents\(\);\n\s+patchNow\(\);/.test(js) && /\n    patchNow\(\);\n  \}\n\n  function buildListHtml/.test(js));
  const css = fs.readFileSync(path.join(dir, 'static', 'codex.css'), 'utf-8');
  check('CSS: dòng thời gian + dòng chờ, bỏ .cx-now', css.includes('.cx-step-eta {') && css.includes('.cx-step-wait {') && !css.includes('.cx-now {'));
  const KEYS = ['codex.now_elapsed', 'codex.now_eta', 'codex.now_eta_unknown', 'codex.now_waiting'];
  for (const lang of ['en', 'vi', 'es', 'ja', 'ko', 'ru', 'tr', 'zh', 'zh-TW']) {
    const loc = JSON.parse(fs.readFileSync(path.join(dir, 'locales', lang + '.json'), 'utf-8'));
    const bad = KEYS.filter(k => !loc[k] || (['codex.now_elapsed', 'codex.now_eta'].includes(k) && !loc[k].includes('{t}')));
    check(`${lang}.json: đủ khoá thời gian`, !bad.length, bad);
  }
  console.log(failed ? `\n${failed} FAIL` : '\nALL PASS');
  process.exit(failed ? 1 : 0);
})();
