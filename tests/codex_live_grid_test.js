/**
 * «Xem live» CHUNG của bảng việc (11/10/2026) — /taskboard/live, mở tab mới từ MỘT nút ở đầu bảng; bảng giữ nguyên.
 *
 * User: «taskboard nó vẫn như cũ, chỉ là thêm 1 chế độ xem live khi muốn mở lớn … bấm button mở trang mới full»;
 * «live view là trang chung task board luôn chứ không phải từng bài»; «link kiểu …/taskboard/live»;
 * «timeline, việc đang làm gần nhất lên đầu; đang tạo ảnh thì grid thumbnail, placeholder biết có bao nhiêu ảnh, xong
 * bước thì ẩn grid»; «tạo ảnh chạy song song nên loading ở nhiều vị trí»; «refresh liên tục có sao không? ban đầu 2s
 * rồi tăng dần».
 *
 *   1. liveDelay: 2 s × 1,5^streak, trần 30 s (hàm thuần cắt từ live.js).
 *   2. liveOrder: bước đang chạy trước, bước xong mới → cũ, bước chưa tới gom vào `next`.
 *   3. runStats: ba số của bước đang chạy (ảnh / clip / giọng / %) + còn bao lâu; recentOf / watchLink (vừa xong).
 *   4. Bảng việc: một nút «Live view» ở đầu bảng → /taskboard/live (tab mới), thẻ KHÔNG có nút; route /taskboard/live.
 *   5. live.js: ETag từng nhóm, events=0, Muse quick=1 hỏi nền, tab ẩn không hỏi, setInterval chỉ cho đồng hồ.
 *   6. live.html / live.css / codex.css; 9 ngôn ngữ có đủ khoá codex.* mà trang dùng.
 *
 * Run:  node tests/codex_live_grid_test.js     (exit 0 = pass)
 */
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const here = path.dirname(fileURLToPath(import.meta.url));
const dir = path.join(here, '..', 'tubecli', 'extensions', 'codex');
const read = (p) => fs.readFileSync(p, 'utf-8').replace(/\r\n/g, '\n');
const live = read(path.join(dir, 'static', 'live.js'));
const board = read(path.join(dir, 'static', 'codex.js'));
const html = read(path.join(dir, 'static', 'live.html'));
const lcss = read(path.join(dir, 'static', 'live.css'));
const bcss = read(path.join(dir, 'static', 'codex.css'));
const bhtml = read(path.join(dir, 'static', 'codex.html'));
const routes = read(path.join(dir, 'routes.py'));

let failed = 0;
function ok(cond, label, detail) {
  if (cond) console.log('  ok  ', label);
  else { failed++; console.log('  FAIL', label, detail === undefined ? '' : '— ' + String(detail).slice(0, 300)); }
}
function cut(src, name) {
  const m = new RegExp(`\\n  function ${name}\\([^)]*\\) \\{[\\s\\S]*?\\n  \\}\\n`).exec(src);
  if (!m) throw new Error('không thấy hàm ' + name);
  return m[0];
}

const parseTs = (s) => (s ? new Date(s) : null);
const FINAL = new Set(['review', 'done', 'failed', 'rejected', 'cancelled']);
const fns = new Function('MAX_MS', 'BASE_MS', 'GROW', 'parseTs', 'GRID_STEPS', 'FINAL_STATES', 'RECENT_HOURS', 'RECENT_MAX',
  cut(live, 'liveDelay') + cut(live, 'liveOrder') + cut(live, 'runStats') + cut(live, 'cellState') + cut(live, 'recentOf')
  + cut(live, 'watchLink') + '\nreturn { liveDelay, liveOrder, runStats, cellState, recentOf, watchLink };')(
  30000, 2000, 1.5, parseTs, new Set(['images', 'tts']), FINAL, 12, 6);

console.log('1. liveDelay');
ok(fns.liveDelay(0) === 2000 && fns.liveDelay(1) === 3000 && fns.liveDelay(2) === 4500 && fns.liveDelay(3) === 6750,
   'bắt đầu 2 s, mỗi lượt không đổi ×1,5', [0, 1, 2, 3].map(fns.liveDelay));
ok(fns.liveDelay(7) === 30000 && fns.liveDelay(50) === 30000 && fns.liveDelay(-3) === 2000 && fns.liveDelay('x') === 2000,
   'trần 30 s; streak âm / rác → 2 s');

console.log('2. liveOrder');
const steps = [
  { name: 'capabilities', status: 'success', started_at: '2026-10-11T15:23:00', ended_at: '2026-10-11T15:23:15' },
  { name: 'script', status: 'success', started_at: '2026-10-11T15:24:00', ended_at: '2026-10-11T15:24:14' },
  { name: 'studio', status: 'success', started_at: '2026-10-11T15:24:14', ended_at: '2026-10-11T15:26:00' },
  { name: 'images', status: 'running', started_at: '2026-10-11T15:26:00' },
  { name: 'tts', status: 'pending' },
  { name: 'render', status: 'pending' },
];
const o = fns.liveOrder(steps);
ok(o.main.map(s => s.name).join(',') === 'images,studio,script,capabilities' && o.next.map(s => s.name).join(',') === 'tts,render',
   'đang chạy trước, xong mới → cũ, chưa tới vào next', JSON.stringify(o));
const o2 = fns.liveOrder([{ name: 'a', status: 'success' }, { name: 'b', status: 'error' }, { name: 'c' }]);
ok(o2.main.map(s => s.name).join(',') === 'b,a' && o2.next.map(s => s.name).join(',') === 'c',
   'không có mốc giờ → theo thứ tự ngược của danh sách; bước không status = chưa tới');
ok(fns.liveOrder(null).main.length === 0, 'steps rỗng / null không vỡ');

console.log('3. runStats + vừa xong');
const shot = (state, extra) => Object.assign({ state, image: ['image', 'clip', 'queued', 'board', 'filming', 'still'].includes(state) }, extra || {});
const drawing = { shots: [shot('image'), shot('image'), shot('drawing'), shot('drawing'), shot('waiting')], clip_plan: 0 };
let r = fns.runStats({ name: 'images', progress: 40 }, drawing, 120);
ok(r.kind === 'images' && r.done === 2 && r.total === 5 && r.busy === 2 && r.eta === 180,
   'đang vẽ: 2/5 ảnh, 2 ô vẽ cùng lúc, còn ~180 s (120 s cho 40 %)', JSON.stringify(r));
const filming = { shots: [shot('clip'), shot('filming'), shot('board'), shot('queued'), shot('image')], clip_plan: 4 };
r = fns.runStats({ name: 'images', progress: 80 }, filming, 300);
ok(r.kind === 'clips' && r.done === 1 && r.total === 4 && r.busy === 2,
   'vẽ xong + có kế hoạch clip: 1/4 clip, 2 đang quay/bảng đạo diễn', JSON.stringify(r));
const halfDrawnPlan = { shots: [shot('image'), shot('drawing')], clip_plan: 3 };
ok(fns.runStats({ name: 'images' }, halfDrawnPlan, 10).kind === 'images', 'còn ảnh chưa vẽ → vẫn đếm ảnh dù đã có kế hoạch clip');
r = fns.runStats({ name: 'tts' }, { shots: [{ tts: true }, { tts: true }, { tts: false }, { tts: false }] }, 20);
ok(r.kind === 'voice' && r.done === 2 && r.total === 4 && r.eta === 20, 'giọng đọc: 2/4 cảnh, còn ~20 s', JSON.stringify(r));
r = fns.runStats({ name: 'render', progress: 25 }, drawing, 60);
ok(r.kind === 'pct' && r.frac === 0.25 && r.eta === 180, 'bước khác: % của bước, còn ~180 s', JSON.stringify(r));
r = fns.runStats({ name: 'render', progress: 0 }, null, 60);
ok(r.kind === 'pct' && r.frac === null && r.eta === null, 'chưa có % → không đoán (thanh chạy vô định)', JSON.stringify(r));
ok(fns.runStats({ name: 'render', progress: 2 }, null, 60).eta === null, 'dưới 5 % → chưa đoán còn bao lâu');
ok(fns.cellState({ state: 'filming', tts: false }, false) === 'filming' && fns.cellState({ tts: true }, true) === 'voiced'
   && fns.cellState({}, false) === 'waiting', 'trạng thái ô: ảnh theo Studio, giọng có/không');
const now = Date.parse('2026-10-11T21:00:00');
const rows = [
  { id: 'a', status: 'review', updated_at: '2026-10-11T20:00:00' }, { id: 'b', status: 'running', updated_at: '2026-10-11T20:59:00' },
  { id: 'c', status: 'failed', updated_at: '2026-10-11T20:30:00' }, { id: 'd', status: 'review', updated_at: '2026-10-10T20:00:00' },
];
ok(fns.recentOf(rows, now).map(x => x.id).join(',') === 'c,a', 'vừa xong: chỉ trạng thái cuối, trong 12 giờ, mới nhất trước');
ok(fns.recentOf(Array.from({ length: 10 }, (_, i) => ({ id: 'x' + i, status: 'done', updated_at: '2026-10-11T20:0' + i + ':00' })), now).length === 6,
   'vừa xong: tối đa 6');
ok(fns.watchLink('- **Watch**: http://127.0.0.1:5295/api/v1/studio/export-video/ep1.mp4\n- **Share**: https://tuan4-13.tubecreate.com/s/ju-jyc_09yr')
   === 'https://tuan4-13.tubecreate.com/s/ju-jyc_09yr', 'link xem: ưu tiên link chia sẻ /s/<mã>');
ok(fns.watchLink('Watch: http://127.0.0.1:5295/api/v1/studio/export-video/ep1.mp4') === '/api/v1/studio/export-video/ep1.mp4'
   && fns.watchLink('') === '', 'không có link chia sẻ → mp4 cùng gốc (bỏ 127.0.0.1); không có gì → rỗng');

console.log('4. Bảng việc: MỘT nút ở đầu bảng → /taskboard/live');
const link = cut(board, 'liveLinkHref');
ok(/<a class="cx-btn cx-btn-ghost" id="cx-live-open" href="\/taskboard\/live" target="_blank" rel="noopener"/.test(bhtml)
   && /data-i18n="codex\.live_open"/.test(bhtml), 'codex.html: nút «Live view» ở đầu bảng, mở tab mới /taskboard/live');
ok(/'\/taskboard\/live'/.test(link) && /theme=/.test(link) && /liveLink\.href = liveLinkHref\(\)/.test(board), 'codex.js gắn ?theme= của bảng');
ok(!/liveLinkHtml|live\.html\?task=/.test(board), 'thẻ task KHÔNG có nút live riêng');
ok(!/episodes\/\$\{[^}]*\}\/live|function liveHtml|function patchLive|cx-live-grid/.test(board),
   'codex.js KHÔNG vẽ lưới / không hỏi /live (bảng giữ như cũ)');
ok(/a\.cx-btn \{ text-decoration: none; \}/.test(bcss), 'nút dạng link không gạch chân');
ok(/@ui_router\.get\("\/taskboard\/live"\)/.test(routes) && /"live\.html"/.test(routes) && /@ui_router\.get\("\/taskboard"\)/.test(routes)
   && /live\.js\?v=/.test(routes), 'route /taskboard/live (live.html, ?v= cho live.js / live.css) + /taskboard');

console.log('5. live.js — nhịp hỏi');
ok(/If-None-Match/.test(live) && /\?events=0/.test(live), 'hỏi kèm If-None-Match; task không kèm nhật ký');
ok(/group=working/.test(live) && /group=backlog/.test(live) && /group=all&sort=updated/.test(live),
   'trang chung: đang chạy + hàng đợi + mới đổi (ETag từng nhóm)');
ok(/muse\/status\?quick=1/.test(live) && /MUSE_MS = 15000/.test(live) && !/await fetchMuse|await pollMuse/.test(live),
   'chỗ ngồi Muse: quick=1, tối đa 15 s một lần, hỏi nền (không chặn nhịp chính)');
ok(/if \(document\.hidden\) \{ schedule\(BASE_MS\); return; \}/.test(live) && /visibilitychange/.test(live),
   'tab ẩn không hỏi; hiện lại → hỏi ngay');
const intervals = live.match(/setInterval\(/g) || [];
ok(intervals.length === 1 && /setInterval\(\(\) => \{ if \(!document\.hidden\) tickClock\(\); \}, 1000\)/.test(live),
   'setInterval duy nhất là đồng hồ 1 s (không request)');
ok(!/state\.stopped/.test(live) && /schedule\(liveDelay\(state\.streak\)\)/.test(live), 'trang chung không thôi hẳn — chỉ giãn tới 30 s');
ok(/text === cur\.text/.test(live) && /cur\.text === r\.text/.test(live), 'thân không đổi = không đổi (nhịp giãn dần)');
ok(/\['pointerdown', 'keydown', 'wheel', 'touchstart'\]/.test(live), 'chạm trang → về 2 s');

console.log('6. Trang + CSS + chữ');
ok(/src="\/codex\/live\.js"/.test(html) && /href="\/codex\/live\.css"/.test(html) && /href="\/codex\/codex\.css"/.test(html)
   && /I18N_NS = \['codex'\]/.test(html) && /\/static\/i18n\.js/.test(html), 'live.html nạp codex.css + live.css + i18n (ns codex) + live.js');
ok(/\.cx-live-grid \{/.test(lcss) && /\.cx-cell-spin \{/.test(lcss) && /\.cx-cell\.no-img/.test(lcss) && /\.lv-task \{/.test(lcss)
   && /@media \(max-width: 640px\)[\s\S]*repeat\(2, minmax\(0, 1fr\)\)/.test(lcss) && /prefers-reduced-motion/.test(lcss),
   'live.css: lưới, vòng xoay, ô chưa ảnh, khối task, điện thoại 2 ô/hàng, giảm chuyển động');
const used = new Set();
for (const m of (live + link).matchAll(/'(codex\.[a-z_]+)'/g)) if (!m[1].endsWith('_')) used.add(m[1]);
for (const m of bhtml.matchAll(/data-i18n(?:-title)?="(codex\.live_[a-z_]+)"/g)) used.add(m[1]);
for (const st of ['pending_approval', 'backlog', 'queued', 'running', 'review', 'done', 'failed', 'rejected', 'cancelled']) used.add('codex.status_' + st);
const langs = fs.readdirSync(path.join(dir, 'locales')).filter(f => f.endsWith('.json'));
ok(langs.length === 9, '9 ngôn ngữ', langs);
for (const f of langs) {
  const d = JSON.parse(read(path.join(dir, 'locales', f)));
  const miss = [...used].filter(k => !d[k]);
  ok(!miss.length, `${f}: đủ ${used.size} khoá`, miss);
}

console.log(failed ? `\n${failed} FAILED` : '\nall passed');
process.exit(failed ? 1 : 0);
