/**
 * Agent tự đóng popup che trang: hộp xin phép cookie (CMP), hộp đăng ký, lớp phủ (user 18/10/2026).
 *
 * Run:  node tests/browser_popups_test.js     (exit 0 = pass)
 *
 * VÌ SAO CÓ FILE NÀY
 *   Live view 17/10: agent «The Wordful Tales» đọc informador.mx với hộp «Consentir / No consentir» phủ giữa
 *   trang, body khoá cuộn — lượt đọc cuộn vào khoảng không, nội dung lấy về lẫn chữ hộp thoại. Trước đó chỉ
 *   hộp Google «Before you continue» được đóng (search.js).
 *
 *   Luật canh:
 *     1. Nhãn khớp TRỌN: «Consentir», «Accept all cookies», «Đồng ý», «同意する» → đồng ý; «No, gracias» → đóng;
 *        «No consentir» → từ chối. KHÔNG khớp «Subscribe», «Sign in», «Accept and pay», «Comprar».
 *     2. Ưu tiên đồng ý > đóng > từ chối (agent chỉ cần đọc trang, nút đồng ý luôn có và không mở hộp con).
 *     3. Không chạy ở trang ứng dụng / đăng nhập / thanh toán, about:blank.
 *     4. Chạy thật trên Chromium (nếu máy có): modal có nút, modal chỉ có ×, lớp phủ không nút (gỡ + mở khoá cuộn),
 *        CMP trong iframe, và KHÔNG bấm nút thường của trang (Subscribe / Sign in trong header cố định).
 *     5. open.js nối sau mỗi lần tải trang (chỉ lượt có prompt / không phải mở tay); browse / extract_content /
 *        navigate / search gọi trước khi đọc; __version__ ≥ .204.
 */
import fs from 'fs';
import path from 'path';
import { createRequire } from 'module';
import { fileURLToPath, pathToFileURL } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, '..');
const BROWSER = path.join(ROOT, 'tubecli', 'extensions', 'browser');
const M = await import(pathToFileURL(path.join(BROWSER, 'actions', 'dismiss_popups.js')).href);

let pass = 0, fail = 0, skipped = 0;
const check = (name, ok, detail = '') => { if (ok) { pass++; console.log(`  ok  ${name}`); } else { fail++; console.log(`  FAIL ${name}  ${detail}`); } };
// Worktree checkout trên Windows ra CRLF (autocrlf) → so chuỗi nhiều dòng phải bỏ  trước.
const read = (p) => fs.readFileSync(path.join(ROOT, p), 'utf8').replace(/
/g, '
');

console.log('1. nhãn nút');
for (const t of ['Consentir', 'Aceptar todo', 'Accept all cookies', 'Accept', 'I agree', 'Got it', 'OK', 'Đồng ý', 'Chấp nhận tất cả', 'Đã hiểu', '同意する', 'すべて同意する', '모두 동의', 'Alle akzeptieren', 'Tout accepter', 'Принять все', 'Tümünü kabul et', 'Aceitar tudo', 'Accetta tutto', 'Accept & close']) {
  check(`đồng ý: «${t}»`, M.ACCEPT_TEXT.test(t));
}
for (const t of ['No, gracias', 'Not now', 'Close', 'Để sau', 'Không, cảm ơn', '关闭', '閉じる', 'Fermer', 'Schließen', '×', 'Continue without accepting']) {
  check(`đóng: «${t}»`, M.CLOSE_TEXT.test(t));
}
for (const t of ['No consentir', 'Reject all', 'Rechazar todo', 'Từ chối tất cả', 'Tout refuser', '拒否', 'Alle ablehnen']) {
  check(`từ chối: «${t}»`, M.REJECT_TEXT.test(t));
}
for (const t of ['Subscribe', 'Sign in', 'Suscribirse', 'Iniciar sesión', 'Accept and pay', 'Comprar ahora', 'Buy now', 'Accept terms and continue to checkout', 'Agree to receive marketing emails and continue']) {
  check(`KHÔNG khớp: «${t}»`, !M.ACCEPT_TEXT.test(t) && !M.CLOSE_TEXT.test(t) && !M.REJECT_TEXT.test(t));
}
check('pickLabel ưu tiên đồng ý > đóng > từ chối', JSON.stringify(M.pickLabel(['No consentir', 'Gestionar opciones', 'Consentir'])) === JSON.stringify({ index: 2, how: 'accept' })
  && JSON.stringify(M.pickLabel(['No consentir', 'Cerrar'])) === JSON.stringify({ index: 1, how: 'close' })
  && JSON.stringify(M.pickLabel(['Gestionar', 'No consentir'])) === JSON.stringify({ index: 1, how: 'reject' })
  && M.pickLabel(['Subscribe', 'Learn more']) === null);
check('pickLabel bỏ nhãn dài (> 48) và gộp khoảng trắng', M.pickLabel(['  Accept   all  ']).how === 'accept' && M.pickLabel(['Accept all ' + 'x'.repeat(60)]) === null);

console.log('2. trang bỏ qua');
for (const u of ['about:blank', 'https://mail.google.com/mail/u/0/', 'https://accounts.google.com/signin', 'https://example.com/login', 'https://shop.example.com/checkout/step1', 'chrome://newtab', 'https://login.microsoftonline.com/x']) {
  check(`bỏ qua ${u}`, M.shouldSkipUrl(u) === true);
}
for (const u of ['https://www.informador.mx/estilo/por-que', 'https://www.youtube.com/watch?v=abc', 'https://consent.youtube.com/m?continue=x', 'https://news.ycombinator.com/']) {
  check(`chạy ở ${u}`, M.shouldSkipUrl(u) === false);
}

console.log('3. nối vào hành vi');
const open = read('tubecli/extensions/browser/open.js');
check('open.js nối sau TabManager, chỉ lượt có prompt / không phải mở tay', open.includes("import { attachPopupDismisser } from './actions/dismiss_popups.js';")
  && open.includes("if (!isManual || (prompt && String(prompt).trim())) {\n        attachPopupDismisser(context, page);"));
for (const [f, via] of [['browse', 'browse'], ['extract_content', 'extract'], ['navigate', 'navigate'], ['search', 'search-url']]) {
  const src = read(`tubecli/extensions/browser/actions/${f}.js`);
  check(`${f}.js gọi dismissPopups(${via})`, src.includes("import { dismissPopups } from './dismiss_popups.js';") && src.includes(`await dismissPopups(page, { via: '${via}' });`));
}
const extract = read('tubecli/extensions/browser/actions/extract_content.js');
check('extract: đóng popup SAU kiểm trang chặn, TRƯỚC khi đọc DOM', extract.indexOf("await dismissPopups(page") > extract.indexOf('isSecurityPage') && extract.indexOf("await dismissPopups(page") < extract.indexOf('0.5. RAW TEXT EXTRACTION'));
check('search.js bỏ đoạn consent tự chế cũ', !read('tubecli/extensions/browser/actions/search.js').includes("name: /Accept|Agree|Consent|Đồng ý/i"));
const mv = /^__version__ = "2026\.08\.09\.(\d+)"/m.exec(read('tubecli/__init__.py'));
check('__version__ >= .204', mv && Number(mv[1]) >= 204, mv && mv[0]);

console.log('4. chạy thật trên Chromium');
let browser = null;
try {
  const require = createRequire(pathToFileURL(path.join(BROWSER, 'package.json')).href);
  const { chromium } = require('playwright');
  browser = await chromium.launch({ headless: true });
} catch (e) {
  skipped++;
  console.log(`  skip  không mở được Chromium của playwright: ${String(e.message || e).split('\n')[0]}`);
}
if (browser) {
  const ctx = await browser.newContext({ viewport: { width: 1200, height: 800 } });
  const pages = {
    '/article': `<html><body class="modal-open" style="overflow:hidden">
      <header style="position:fixed;top:0;left:0;right:0;height:60px;z-index:50;background:#fff"><button id="sub">Subscribe</button><button id="signin">Sign in</button></header>
      <article><h1>¿Por qué nos cuesta tanto perdonar?</h1><p>${'texto '.repeat(400)}</p></article>
      <div id="cmp" style="position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,.5)"><div role="dialog" style="margin:120px auto;width:400px;background:#fff;padding:20px">
        <p>informador.mx solicita tu consentimiento para usar tus datos personales</p>
        <button onclick="document.getElementById('cmp').remove();document.body.style.overflow='';document.body.classList.remove('modal-open')">No consentir</button>
        <button onclick="document.getElementById('cmp').remove();document.body.style.overflow='';document.body.classList.remove('modal-open')">Consentir</button>
        <a href="#">Gestionar opciones</a></div></div></body></html>`,
    '/newsletter': `<html><body><article><p>${'news '.repeat(300)}</p></article>
      <div class="newsletter-popup" style="position:fixed;inset:0;z-index:2000;background:rgba(0,0,0,.6)"><div style="margin:100px auto;width:360px;background:#fff;padding:16px">
        <button aria-label="Cerrar" onclick="this.closest('.newsletter-popup').remove()">×</button><h2>Suscríbete</h2><button>Suscribirse</button></div></div></body></html>`,
    '/paywall': `<html><body class="no-scroll" style="overflow:hidden"><article><p>${'wall '.repeat(300)}</p></article>
      <div class="paywall-overlay" style="position:fixed;inset:0;z-index:1000;background:rgba(0,0,0,.7)"><p>Suscríbete para seguir leyendo</p></div></body></html>`,
    '/framed': `<html><body><article><p>${'frame '.repeat(300)}</p></article>
      <iframe id="cmpframe" src="https://example.test/cmp" style="position:fixed;bottom:0;left:0;width:100%;height:200px;z-index:999"></iframe></body></html>`,
    '/cmp': `<html><body><div id="onetrust-banner-sdk"><p>We use cookies</p><button id="onetrust-accept-btn-handler" onclick="document.body.innerHTML='<p id=done>accepted</p>'">Accept All Cookies</button></div></body></html>`,
    '/plain': `<html><body><header style="position:fixed;top:0;left:0;right:0;height:60px;z-index:50"><button id="sub">Subscribe</button><button id="signin">Sign in</button></header><article><p>${'plain '.repeat(300)}</p></article></body></html>`,
    '/login': `<html><body><div role="dialog"><button id="agree">I agree</button></div></body></html>`,
  };
  await ctx.route('https://example.test/**', (route) => {
    const u = new URL(route.request().url());
    const body = pages[u.pathname] || '<html><body>404</body></html>';
    route.fulfill({ status: 200, contentType: 'text/html; charset=utf-8', body });
  });
  const run = async (p, via) => { const page = await ctx.newPage(); await page.goto('https://example.test' + p, { waitUntil: 'domcontentloaded' }); const r = await M.dismissPopups(page, { via }); return { page, r }; };
  try {
    let { page, r } = await run('/article', 'test');
    check('modal cookie: bấm «Consentir» (đồng ý thắng từ chối)', r.clicked.includes('Consentir') && !r.clicked.includes('No consentir'), JSON.stringify(r));
    check('modal cookie: hộp biến mất, cuộn mở khoá', await page.evaluate(() => !document.getElementById('cmp') && document.body.style.overflow === '' && !document.body.classList.contains('modal-open')));
    check('modal cookie: KHÔNG bấm Subscribe / Sign in của header', await page.evaluate(() => !!document.getElementById('sub') && !!document.getElementById('signin')));
    await page.close();

    ({ page, r } = await run('/newsletter', 'test'));
    check('modal đăng ký: bấm nút × (aria-label Cerrar), không bấm «Suscribirse»', r.clicked.length === 1 && /cerrar|×/i.test(r.clicked[0]) && await page.evaluate(() => !document.querySelector('.newsletter-popup')), JSON.stringify(r));
    await page.close();

    ({ page, r } = await run('/paywall', 'test'));
    check('lớp phủ không nút: gỡ + mở khoá cuộn', r.removed === 1 && await page.evaluate(() => !document.querySelector('.paywall-overlay') && document.body.style.overflow === '' && !document.body.classList.contains('no-scroll')), JSON.stringify(r));
    await page.close();

    ({ page, r } = await run('/framed', 'test'));
    await page.waitForTimeout(300);
    const framed = page.frames().find((f) => f.url().endsWith('/cmp'));
    check('CMP trong iframe: bấm nút OneTrust', r.clicked.some((c) => /accept all cookies/i.test(c)) && framed && await framed.evaluate(() => !!document.getElementById('done')), JSON.stringify(r));
    await page.close();

    ({ page, r } = await run('/plain', 'test'));
    check('trang thường: không bấm gì, không gỡ gì', r.clicked.length === 0 && r.removed === 0 && await page.evaluate(() => !!document.getElementById('sub')), JSON.stringify(r));
    await page.close();

    ({ page, r } = await run('/login', 'test'));
    check('trang /login: bỏ qua hoàn toàn', r.clicked.length === 0 && await page.evaluate(() => !!document.getElementById('agree')), JSON.stringify(r));
    await page.close();
  } catch (e) {
    check('chạy thật', false, e.stack || String(e));
  } finally {
    await browser.close().catch(() => {});
  }
}

console.log(`\n${pass} pass, ${fail} fail${skipped ? `, ${skipped} skip` : ''}`);
process.exit(fail ? 1 : 0);
