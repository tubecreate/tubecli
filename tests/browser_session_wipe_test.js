// Mở trình duyệt không khôi phục tab cũ (user 30/10/2026: «shardx đang làm một mớ khung nữa»). Bỏ cờ
// --restore-last-session KHÔNG đủ: ShardX vẫn tự mở lại, hồ sơ testphienbansharr149 lên 205 tab ≈ 27 GB RAM. Khoá:
// launch() xoá tệp phiên ĐÚNG sau khi kiểm hồ sơ không có chủ; chỉ xoá tệp phiên, không đụng cookie / đăng nhập.
//
// Chạy:  node tests/browser_session_wipe_test.js      (exit 0 = pass)
// Có ShardX trên máy (SHARDX_EXE hoặc đường cài mặc định) thì thử thật trên hồ sơ TẠM với trang local; không có thì bỏ qua.
import fs from 'fs';
import os from 'os';
import path from 'path';
import http from 'http';
import { createRequire } from 'module';
import { fileURLToPath, pathToFileURL } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const BROWSER = path.join(__dirname, '..', 'tubecli', 'extensions', 'browser');
let pass = 0, fail = 0;
const check = (n, ok, d = '') => { if (ok) { pass++; console.log(`[PASS] ${n}`); } else { fail++; console.log(`[FAIL] ${n}  ${d}`); } };

const src = fs.readFileSync(path.join(BROWSER, 'browser_manager.js'), 'utf8').replace(/\r\n/g, '\n');
const at = src.indexOf('async launch(profileName, options = {}) {');
const lockAt = src.indexOf('clearStaleSingletonLocks(profilePath);', at);
const wipeAt = src.indexOf('clearSavedSession(profilePath);', at);
check('launch(): xoá phiên SAU khi kiểm khoá hồ sơ', at > 0 && lockAt > at && wipeAt > lockAt && wipeAt - at < 700);
// Bản vá nóng của cloud chỉ thay browser_manager.js → hàm phải nằm ngay trong file này, không import file mới.
const fnAt = src.indexOf('export function clearSavedSession(profilePath) {');
check('clearSavedSession nằm trong browser_manager.js', fnAt > 0 && fnAt < at);

const fn = src.slice(fnAt, src.indexOf('\nexport class BrowserManager', fnAt)).replace('export function', 'function');
const clearSavedSession = new Function('fs', 'path', `${fn}\nreturn clearSavedSession;`)(fs, path);
const log = console.log;
const quiet = (f) => { console.log = () => {}; try { return f(); } finally { console.log = log; } };

const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'tcwipe-'));
try {
  const d = path.join(dir, 'Default');
  fs.mkdirSync(path.join(d, 'Sessions'), { recursive: true });
  const keep = ['Cookies', 'Login Data', 'Preferences', path.join('Sessions', 'Apps_1')];
  const drop = [path.join('Sessions', 'Session_1'), path.join('Sessions', 'Tabs_1'), 'Current Session', 'Last Tabs'];
  for (const f of [...keep, ...drop]) fs.writeFileSync(path.join(d, f), 'x');
  check('xoá đủ tệp phiên, trả số tệp', quiet(() => clearSavedSession(dir)) === drop.length);
  check('tệp phiên đã biến mất', drop.every((f) => !fs.existsSync(path.join(d, f))));
  check('cookie, đăng nhập, cài đặt còn nguyên', keep.every((f) => fs.existsSync(path.join(d, f))));
  check('gọi lại = 0, không lỗi', quiet(() => clearSavedSession(dir)) === 0);
  check('hồ sơ mới chưa có thư mục: không lỗi', quiet(() => clearSavedSession(path.join(dir, 'nope'))) === 0);
} finally {
  fs.rmSync(dir, { recursive: true, force: true });
}

// ── Thử thật: hồ sơ tạm, 5 tab trang local ───────────────────────────────────
const EXE = process.env.SHARDX_EXE || path.join(process.env.APPDATA || '', 'shardx-launcher', 'runtime', 'engines',
  '152.0.7977.65', 'ShardX-Windows', 'chrome.exe');
if (fs.existsSync(EXE)) {
  const { chromium } = createRequire(path.join(BROWSER, 'package.json'))('playwright');
  const srv = http.createServer((q, s) => { s.setHeader('Content-Type', 'text/html'); s.end(`tab ${q.url}`); });
  await new Promise((r) => srv.listen(0, '127.0.0.1', r));
  const base = `http://127.0.0.1:${srv.address().port}`;
  const launch = (p) => chromium.launchPersistentContext(p, { executablePath: EXE, headless: true, viewport: null,
    args: ['--no-first-run', '--hide-crash-restore-bubble', '--remote-debugging-port=0', '--test-type'],
    ignoreDefaultArgs: ['--enable-automation'] });
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const reopen = async (wipe) => {
    const p = fs.mkdtempSync(path.join(os.tmpdir(), 'tcwipe-'));
    try {
      let ctx = await launch(p);
      for (let i = 0; i < 5; i++) await (await ctx.newPage()).goto(`${base}/t${i}`);
      await sleep(14000);                 // Chrome ghi tệp phiên theo nhịp ~10 s
      await ctx.close();
      if (wipe) quiet(() => clearSavedSession(p));
      ctx = await launch(p);
      await sleep(5000);
      const n = ctx.pages().filter((x) => x.url().startsWith(base)).length;
      await ctx.close();
      return n;
    } finally {
      await sleep(800);
      fs.rmSync(p, { recursive: true, force: true, maxRetries: 5, retryDelay: 500 });
    }
  };
  check('ShardX thật: không xoá thì mở lại đủ 5 tab (đúng lỗi user gặp)', (await reopen(false)) === 5);
  check('ShardX thật: xoá tệp phiên thì 0 tab cũ', (await reopen(true)) === 0);
  srv.close();
} else {
  console.log('[SKIP] máy này không có ShardX — bỏ qua phần thử thật');
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
