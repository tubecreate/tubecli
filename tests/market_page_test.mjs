// Trang Chợ của máy (webui/static/market.js) — cài MẪU từ Chợ, thông báo, đăng nhập (user 14/10/2026).
//
// Chạy:  node tests/market_page_test.mjs      (exit 0 = pass)
//
// Chuyện thật: trong Flow, bấm «Install» trên thẻ mẫu miễn phí → không cài được và KHÔNG thấy thông báo gì. Ba
// lỗi chồng nhau: (1) market.css mất kiểu .market-toast từ 16/5/2026 → mọi thông báo thành chữ trơn cuối trang;
// (2) mẫu cần tài khoản Chợ mà trang không hỏi đăng nhập; (3) cloud đòi «mua» cả mẫu miễn phí (sửa ở cloud).
// Thêm: đăng nhập / đăng ký / media còn gọi PHP api.tubecreate.com đã bỏ.
//
// Nạp market.js THẬT vào một vm với DOM giả tối thiểu; fetch, localStorage, postMessage đều giả. Không mạng.
import { readFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const STATIC = join(ROOT, 'tubecli', 'extensions', 'webui', 'static');
let pass = 0, fail = 0;
const check = (name, ok, detail = '') => {
  if (ok) { pass++; console.log(`[PASS] ${name}`); } else { fail++; console.log(`[FAIL] ${name}  ${detail}`); }
};

const SRC = readFileSync(join(STATIC, 'market.js'), 'utf8');
const CSS = readFileSync(join(STATIC, 'market.css'), 'utf8');
const HTML = readFileSync(join(STATIC, 'market.html'), 'utf8');

// ── A. tĩnh: không còn gọi PHP; toast có kiểu ──────────────────────────────────────────────────────────
const code = SRC.split('\n').filter((l) => !/^\s*(\/\/|\*|\/\*)/.test(l)).join('\n');
check('A1 market.js không còn gọi api.tubecreate.com (PHP đã bỏ)', !/api\.tubecreate\.com/.test(code),
  (code.match(/.*api\.tubecreate\.com.*/g) || []).join(' | ').slice(0, 200));
check('A2 không còn validate-user.php / create-user.php / get-media.php / upload-media.php', !/\.php\b/.test(code));
check('A3 .market-toast có kiểu: fixed + lớp .show + .error', /\.market-toast\s*\{[^}]*position:\s*fixed/.test(CSS)
  && /\.market-toast\.show\s*\{/.test(CSS) && /\.market-toast\.error\s*\{/.test(CSS));
check('A4 thẻ <div id="marketToast" class="market-toast"> còn trong trang', /class="market-toast" id="marketToast"/.test(HTML));

// ── DOM giả ────────────────────────────────────────────────────────────────────────────────────────────
function el(id) {
  const cls = new Set();
  const e = {
    id, value: '', innerHTML: '', textContent: '', disabled: false, dataset: {}, style: {}, children: [],
    classList: { add: (...c) => c.forEach((x) => cls.add(x)), remove: (...c) => c.forEach((x) => cls.delete(x)),
      contains: (c) => cls.has(c), toggle: (c, on) => ((on ?? !cls.has(c)) ? cls.add(c) : cls.delete(c)) },
    get className() { return [...cls].join(' '); },
    set className(v) { cls.clear(); String(v).split(/\s+/).filter(Boolean).forEach((x) => cls.add(x)); },
    addEventListener() {}, removeEventListener() {}, appendChild() {}, focus() {}, click() {}, remove() {},
    setAttribute() {}, getAttribute() { return null; }, querySelector: () => el(''), querySelectorAll: () => [],
  };
  return e;
}
const ELS = {};
const document = {
  getElementById: (id) => (ELS[id] ||= el(id)),
  querySelector: () => el(''), querySelectorAll: () => [], createElement: () => el(''),
  addEventListener() {}, body: el('body'), documentElement: el('html'),
};
const store = new Map();
const localStorage = {
  getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)),
  removeItem: (k) => store.delete(k),
};
const FETCHES = [];
let route = () => ({ status: 200, body: { status: 'success' } });
async function fetch(url, opts = {}) {
  FETCHES.push({ url: String(url), opts });
  const r = route(String(url), opts) || { status: 404, body: {} };
  return { status: r.status, ok: r.status >= 200 && r.status < 300, json: async () => r.body, text: async () => JSON.stringify(r.body) };
}
const LISTENERS = {};
const TIMERS = [];
const ctx = {
  document, localStorage, fetch, console,
  setTimeout: (fn, ms) => { if ((ms || 0) < 3000) TIMERS.push(fn); return TIMERS.length; },
  clearTimeout() {}, setInterval: () => 1, clearInterval() {},
  T: () => '', location: { origin: 'https://box.example', hash: '' }, navigator: { userAgent: 'node' },
  URLSearchParams, FormData: class { append() {} }, Blob: class {}, alert() {}, confirm: () => true,
};
ctx.window = ctx;
ctx.addEventListener = (type, fn) => { (LISTENERS[type] ||= []).push(fn); };
ctx.window.parent = null;
vm.createContext(ctx);
try {
  vm.runInContext(SRC, ctx, { filename: 'market.js' });
} catch (e) {
  check('B0 market.js nạp được trong DOM giả', false, e.stack);
  process.exit(1);
}
const run = (s) => vm.runInContext(s, ctx);
const flush = async () => { for (let i = 0; i < 5; i++) { while (TIMERS.length) TIMERS.shift()(); await new Promise((r) => setImmediate(r)); } };
const toast = () => ELS.marketToast || el('');
const loginOpen = () => (ELS.loginModal ? ELS.loginModal.classList.contains('active') : false);
const installCalls = () => FETCHES.filter((f) => /\/items\/[^/]+\/install$/.test(f.url) && f.opts.method === 'POST');

const DETAIL = { status: 'success', item: { public_id: 'tplFree001', title: 'Paper Brief', category: 'template', price: 0, item_data: '' } };

// ── B. mẫu, CHƯA đăng nhập Chợ → hỏi đăng nhập, không gọi cài ──────────────────────────────────────────
FETCHES.length = 0;
await run(`installItem('tplFree001', 'Paper Brief', 'template')`);
check('B1 chưa đăng nhập → mở hộp đăng nhập, KHÔNG gọi lệnh cài', loginOpen() && installCalls().length === 0,
  JSON.stringify(FETCHES.map((f) => f.url)));
check('B2 … và hiện thông báo lỗi nhìn thấy được (lớp show + error, có chữ)',
  /show/.test(toast().className) && /error/.test(toast().className) && /Sign in/.test(toast().textContent), toast().className + ' | ' + toast().textContent);
check('B3 … và nhớ việc cài để làm tiếp', run(`typeof pendingAfterLogin`) === 'function');

// ── C. đăng nhập bằng tài khoản Cloud (SSO) → tự cài tiếp, kèm khoá Chợ ───────────────────────────────
route = (url, opts) => {
  if (url.endsWith('/api/v1/market/items/tplFree001')) return { status: 200, body: DETAIL };
  if (url.endsWith('/install') && opts.method === 'POST') return { status: 200, body: { status: 'success', type: 'template', message: 'Template installed', open: 'content_studio' } };
  return { status: 200, body: { status: 'success' } };
};
FETCHES.length = 0;
for (const fn of LISTENERS.message || []) fn({ origin: 'https://cloud.tubecreate.com', data: { type: 'tubecli-market-sso', token: 'tok-cloud', user: { username: 'khach' } } });
await flush();
const ic = installCalls()[0];
check('C1 SSO xong → hộp đóng, khoá lưu, tự gọi cài', !loginOpen() && store.get('user_token') === 'tok-cloud' && !!ic,
  JSON.stringify(FETCHES.map((f) => f.url)));
check('C2 lệnh cài mang Authorization: Bearer <khoá Chợ>', ic && (ic.opts.headers || {}).Authorization === 'Bearer tok-cloud',
  JSON.stringify(ic && ic.opts.headers));
check('C3 việc chờ đã xoá (không cài hai lần)', run(`pendingAfterLogin`) === null);

// ── D. khoá Chợ hết hạn: 401 từ Chợ → bỏ khoá, hỏi đăng nhập lại ───────────────────────────────────────
route = (url, opts) => {
  if (url.endsWith('/api/v1/market/items/tplFree001')) return { status: 200, body: DETAIL };
  if (url.endsWith('/install') && opts.method === 'POST') return { status: 401, body: { detail: 'Sign in to the Market first' } };
  return { status: 200, body: {} };
};
await run(`installItem('tplFree001', 'Paper Brief', 'template').catch(() => 'threw')`);
check('D1 401 của Chợ → xoá khoá cũ, mở lại hộp đăng nhập, nhớ việc cài',
  !store.has('user_token') && loginOpen() && run(`typeof pendingAfterLogin`) === 'function');
run(`closeLoginModal()`);
check('D2 đóng hộp (huỷ) → bỏ việc chờ', run(`pendingAfterLogin`) === null);

// ── E. lỗi khác: thông báo ĐỌC ĐƯỢC, detail dạng đối tượng không thành [object Object] ──────────────────
store.set('user_token', 'tok-cloud');
route = (url, opts) => {
  if (url.endsWith('/api/v1/market/items/tplFree001')) return { status: 200, body: DETAIL };
  if (url.endsWith('/install') && opts.method === 'POST') return { status: 409, body: { detail: { message: 'Content Studio is not installed', builtin: false } } };
  return { status: 200, body: {} };
};
await run(`installItem('tplFree001', 'Paper Brief', 'template').catch(() => 'threw')`);
check('E1 409 kèm detail đối tượng → báo «đã cài» hoặc câu của server, không «[object Object]»',
  !/object Object/.test(toast().textContent) && toast().textContent.length > 0, toast().textContent);
route = (url, opts) => {
  if (url.endsWith('/api/v1/market/items/tplFree001')) return { status: 200, body: DETAIL };
  if (url.endsWith('/install') && opts.method === 'POST') return { status: 403, body: { detail: 'Buy this template first' } };
  return { status: 200, body: {} };
};
const r = await run(`installItem('tplFree001', 'Paper Brief', 'template').then(() => 'ok', (e) => 'threw:' + e.message)`);
check('E2 403 → thông báo đúng câu server, lỗi vẫn ném cho bên gọi', toast().textContent === 'Buy this template first'
  && /error/.test(toast().className) && r === 'threw:Buy this template first', toast().textContent + ' | ' + r);

// ── F. đăng nhập email → Chợ trên cloud (không PHP), xong làm tiếp việc chờ ────────────────────────────
store.delete('user_token');
let resumed = 0;
ctx.__resume = () => { resumed++; };
run(`pendingAfterLogin = () => __resume()`);
ELS.authEmail = el('authEmail'); ELS.authEmail.value = 'k@x.com';
ELS.authPassword = el('authPassword'); ELS.authPassword.value = 'secret123';
route = (url) => (url.startsWith('https://market.tubecreate.com/api/market-cli/login')
  ? { status: 200, body: { status: 'success', ok: true, token: 'tok-mail', username: 'khach', name: 'Khách' } }
  : { status: 200, body: { status: 'success' } });
FETCHES.length = 0;
await run(`handleMarketAuth()`);
await flush();
const lg = FETCHES.find((f) => /market-cli\/login$/.test(f.url));
check('F1 đăng nhập email gọi market.tubecreate.com/api/market-cli/login', !!lg && lg.opts.method === 'POST',
  JSON.stringify(FETCHES.map((f) => f.url)));
check('F2 lưu khoá + làm tiếp việc chờ đúng một lần', store.get('user_token') === 'tok-mail' && resumed === 1, `resumed=${resumed}`);

// ── G. mẫu có phiên bản (15/10/2026): người bán đăng bản mới → người đã cài thấy «Cập nhật» ───────────────
const TPL = { public_id: 'tplFree001', title: 'Paper Brief', category: 'template', price: 0, version: '2026.10.15.1429' };
const cardOf = (installData) => run(`createCard(${JSON.stringify(TPL)}, ${JSON.stringify(installData)})`).innerHTML;
let html = cardOf({ installed: true, local_version: '2026.10.06.0543' });
check('G1 bản đã cài cũ hơn → thẻ có nút Cập nhật gọi installItem(…, "template", true)',
  /id="cardUpdateBtn_tplFree001"/.test(html) && /installItem\('tplFree001', 'Paper Brief', 'template', true\)/.test(html),
  html.slice(html.indexOf('card-footer'), html.indexOf('card-footer') + 600));
html = cardOf({ installed: true, local_version: '2026.10.15.1429' });
check('G2 đã là bản mới nhất → «Đã cài», không có nút Cập nhật', !/cardUpdateBtn_/.test(html) && /Đã cài/.test(html));
html = cardOf({ installed: true, local_version: '' });
check('G3 không rõ bản đã cài (máy người bán / mẫu trùng tên tự tạo) → không mời cập nhật', !/cardUpdateBtn_/.test(html));
html = cardOf({ installed: true, local_version: '', version_unknown: true });
check('G3b mua qua Content Studio, không rõ bản → thẻ không giục (nút Update chỉ trong chi tiết)', !/cardUpdateBtn_/.test(html));
const DSRC = SRC.slice(SRC.indexOf('async function openDetailModal'), SRC.indexOf('function closeDetailModal'));
check('G3c chi tiết: nút Update mẫu hiện khi có bản mới HOẶC version_unknown, gọi installItem(…, true)',
  /item\.category === 'template'[\s\S]{0,200}tplNewer \|\| \(!checkData\.local_version && checkData\.version_unknown\)/.test(DSRC)
  && /installItem\(publicId, item\.title, 'template', true\)/.test(DSRC));
store.set('user_token', 'tok-cloud');
route = (url, opts) => {
  if (url.endsWith('/api/v1/market/items/tplFree001')) return { status: 200, body: { status: 'success', item: TPL } };
  if (url.endsWith('/install') && opts.method === 'POST') return { status: 200, body: { status: 'success', type: 'template', message: 'Template installed', open: 'content_studio' } };
  return { status: 200, body: { status: 'success' } };
};
FETCHES.length = 0;
await run(`installItem('tplFree001', 'Paper Brief', 'template', true)`);
const up = installCalls()[0];
const upBody = up ? JSON.parse(up.opts.body) : {};
check('G4 bấm Cập nhật → lệnh cài force_update=true, item_data mang phiên bản mới (lõi ghi vào sổ)',
  upBody.force_update === true && JSON.parse(upBody.item_data).version === '2026.10.15.1429', up && up.opts.body);

console.log(`\n${pass}/${pass + fail} PASS`);
process.exit(fail ? 1 : 0);
