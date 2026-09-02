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
      // Chuẩn hoá về format Playwright. Nguồn phổ biến nhất người dùng dán vào là
      // Cookie-Editor / EditThisCookie (Chrome), khác Playwright ở HAI chỗ hay
      // làm import "thành công" mà cookie vô dụng:
      //   - expirationDate (giây, float) thay cho expires → thiếu là thành cookie
      //     phiên, đóng browser là mất → đăng nhập không giữ.
      //   - sameSite kiểu Chrome: no_restriction/lax/unspecified; Playwright chỉ
      //     nhận Strict/Lax/None → truyền thẳng là addCookies NÉM.
      const mapSameSite = (v) => {
        const s = String(v || '').toLowerCase();
        if (s === 'strict') return 'Strict';
        if (s === 'lax') return 'Lax';
        if (s === 'none' || s === 'no_restriction') return 'None';
        return undefined;   // unspecified/rỗng → Playwright mặc định
      };
      const clean = cookies.map((c) => {
        const o = { name: c.name, value: c.value, domain: c.domain,
          path: c.path || '/', secure: !!c.secure, httpOnly: !!c.httpOnly };
        const exp = (c.expires != null ? c.expires : c.expirationDate);
        if (exp && exp > 0 && !c.session) o.expires = Math.floor(exp);
        const ss = mapSameSite(c.sameSite);
        if (ss) {
          o.sameSite = ss;
          if (ss === 'None') o.secure = true;   // SameSite=None BẮT BUỘC secure, không thì Playwright ném
        }
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
