// Đọc/ghi cookie THẬT của một phiên trình duyệt đang chạy, qua CDP.
//
// Vì sao không đụng cookies.json: open.js KHÔNG nạp file đó khi mở profile, nên
// ghi vào đó chẳng làm profile đăng nhập. Cookie chỉ "sống" trong session. Ta
// nối vào chính Chromium đang chiếu (connectOverCDP tới cổng DevToolsActivePort)
// rồi đọc/ghi qua context — Playwright giải mã sẵn, không phải mò SQLite mã hoá.
//
// connectOverCDP: TUYỆT ĐỐI không close() — đóng là giết luôn phiên người dùng
// đang xem. Chỉ disconnect (process.exit).
//
// Dùng:
//   node cookie_tool.cjs --cdp <port> --action export
//   node cookie_tool.cjs --cdp <port> --action import --file <cookies.json>
// In kết quả giữa __COOKIE_RESULT__ và __COOKIE_END__ để phía Python bóc.
const fs = require('fs');

function arg(name, def) {
  const i = process.argv.indexOf('--' + name);
  return i >= 0 && i + 1 < process.argv.length ? process.argv[i + 1] : def;
}

(async () => {
  const port = parseInt(arg('cdp', '0'), 10);
  const action = arg('action', 'export');
  if (!port) { console.error('cookie_tool: thiếu --cdp'); process.exit(2); }

  let chromium;
  try { ({ chromium } = require('playwright-core')); }
  catch { ({ chromium } = require('playwright')); }

  let browser;
  try {
    browser = await chromium.connectOverCDP(`http://127.0.0.1:${port}`, { timeout: 8000 });
  } catch (e) {
    console.error('cookie_tool: không nối được CDP cổng ' + port + ': ' + e.message);
    process.exit(3);
  }

  try {
    const ctx = browser.contexts()[0];
    if (!ctx) { console.error('cookie_tool: không có context'); process.exit(4); }

    if (action === 'export') {
      const cookies = await ctx.cookies();
      console.log('__COOKIE_RESULT__' + JSON.stringify(cookies) + '__COOKIE_END__');
    } else if (action === 'import') {
      const file = arg('file', '');
      const raw = JSON.parse(fs.readFileSync(file, 'utf-8'));
      const cookies = Array.isArray(raw) ? raw : (raw.cookies || []);
      // Playwright addCookies đòi url HOẶC (domain+path). File từ nơi khác có thể
      // thiếu path → vá path='/'; bỏ trường lạ khiến addCookies ném.
      const clean = cookies.map((c) => {
        const o = { name: c.name, value: c.value, domain: c.domain,
          path: c.path || '/', secure: !!c.secure, httpOnly: !!c.httpOnly };
        if (c.expires && c.expires > 0) o.expires = c.expires;
        if (c.sameSite && ['Strict', 'Lax', 'None'].includes(c.sameSite)) o.sameSite = c.sameSite;
        return o;
      }).filter((c) => c.name && c.domain);
      await ctx.addCookies(clean);   // MERGE: cookie cùng name+domain bị thay, khác thì giữ
      console.log('__COOKIE_RESULT__' + JSON.stringify({ imported: clean.length }) + '__COOKIE_END__');
    } else {
      console.error('cookie_tool: action lạ ' + action); process.exit(5);
    }
  } catch (e) {
    console.error('cookie_tool: lỗi ' + e.message);
    process.exit(6);
  } finally {
    // KHÔNG browser.close() — chỉ ngắt kết nối CDP.
    process.exit(0);
  }
})();
