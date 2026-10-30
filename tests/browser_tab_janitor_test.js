// Lượt agent tự dọn tab (user 30/10/2026: «cho agent tự đóng khi chạy xong»). Hồ sơ testphienbansharr149 của agent
// «chuyên gia it» từng dồn 202 tab ≈ 200 tiến trình. Khoá: trong lượt agent giữ tối đa MAX_AGENT_TABS (đóng tab
// CŨ NHẤT, không đóng tab đang dùng); chạy xong chỉ còn một tab; mở tay không đụng. Chạy Chromium THẬT (Playwright).
//
// Chạy:  node tests/browser_tab_janitor_test.js      (exit 0 = pass)
import fs from 'fs';
import path from 'path';
import { createRequire } from 'module';
import { fileURLToPath, pathToFileURL } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const BROWSER = path.join(__dirname, '..', 'tubecli', 'extensions', 'browser');
const M = await import(pathToFileURL(path.join(BROWSER, 'actions', 'tab_janitor.js')).href);
let pass = 0, fail = 0;
const check = (n, ok, d = '') => { if (ok) { pass++; console.log(`[PASS] ${n}`); } else { fail++; console.log(`[FAIL] ${n}  ${d}`); } };

const open = fs.readFileSync(path.join(BROWSER, 'open.js'), 'utf8').replace(/\r\n/g, '\n');
check('open.js nạp tab_janitor', open.includes("import { trimTabs, closeExtraTabs, MAX_AGENT_TABS } from './actions/tab_janitor.js';"));
const tm = open.slice(open.indexOf("context.on('page', async (newPage) => {"));
check('tab mới trong lượt agent → trimTabs giữ tab vừa chuyển sang', tm.slice(0, 1200).includes('if (!isManual) {')
  && tm.slice(0, 1200).includes('await trimTabs(context, newPage, MAX_AGENT_TABS)'));
const fin = open.slice(open.indexOf("console.log('Closing browser in 5 seconds...');"));
check('chạy xong (không phải mở tay) → closeExtraTabs TRƯỚC khi đóng context',
  fin.indexOf('await closeExtraTabs(context, page)') > 0 && fin.indexOf('await closeExtraTabs(context, page)') < fin.indexOf('await context.close()'));
check('MAX_AGENT_TABS = 4', M.MAX_AGENT_TABS === 4);

const require = createRequire(pathToFileURL(path.join(BROWSER, 'package.json')).href);
const { chromium } = require('playwright');
const browser = await chromium.launch({ headless: true });
try {
  const ctx = await browser.newContext();
  const pages = [];
  for (let i = 0; i < 7; i++) {
    const p = await ctx.newPage();
    await p.setContent(`<title>t${i}</title>`);
    pages.push(p);
  }
  const keep = pages[6];
  const n = await M.trimTabs(ctx, keep, 4);
  const left = ctx.pages().filter((p) => !p.isClosed());
  check('7 tab → đóng 3 tab CŨ NHẤT, còn 4', n === 3 && left.length === 4 && pages.slice(0, 3).every((p) => p.isClosed()), `${n} / ${left.length}`);
  check('tab đang dùng không bị đóng', !keep.isClosed());

  const keep2 = pages[3];                         // tab cũ nhất còn lại cũng có thể là tab đang dùng
  const p8 = await ctx.newPage();
  await M.trimTabs(ctx, keep2, 4);
  check('tab đang dùng là tab cũ nhất → bỏ qua nó, đóng tab cũ kế tiếp', !keep2.isClosed() && pages[4].isClosed() && !p8.isClosed());

  const m = await M.closeExtraTabs(ctx, keep2);
  const rest = ctx.pages().filter((p) => !p.isClosed());
  check('chạy xong → chỉ còn đúng tab đang dùng', m >= 1 && rest.length === 1 && rest[0] === keep2, `${rest.length}`);
  check('closeExtraTabs khi tab đang dùng đã đóng → giữ tab mới nhất', await (async () => {
    const a = await ctx.newPage(); const b = await ctx.newPage();
    await a.close();
    await M.closeExtraTabs(ctx, a);
    const r = ctx.pages().filter((p) => !p.isClosed());
    return r.length === 1 && r[0] === b;
  })());
  check('dưới ngưỡng → không đóng gì', (await M.trimTabs(ctx, null, 4)) === 0);
  await ctx.close();
  check('context đã đóng → không ném lỗi', (await M.trimTabs(ctx, null, 1)) === 0);
} finally {
  await browser.close();
}
console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
