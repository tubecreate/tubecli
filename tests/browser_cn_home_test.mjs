/**
 * Trình duyệt trên máy ở Trung Quốc: trang đầu Bing, Google bị chặn thì báo lỗi NGAY, tab khôi phục hỏng thì về trang đầu.
 *
 * Run:  node tests/browser_cn_home_test.mjs     (exit 0 = pass)
 *
 * VÌ SAO CÓ FILE NÀY
 *   Máy Aliyun Bắc Kinh 6/10/2026. Trang đầu mặc định là google.com → goto hết hạn 30 s, Flow báo «No frames
 *   received». Đổi sang www.bing.com (ở Trung Quốc tự sang cn.bing.com) rồi vẫn còn: tab Google của phiên trước
 *   được Chromium KHÔI PHỤC, DNS trả IP giả (www.google.com → 2001::1), kết nối treo tới hết hạn TCP của hệ điều
 *   hành, và launchPersistentContext chờ theo — Spawning → launched mất 136 s MỖI lần mở, rồi dừng ở trang lỗi
 *   chrome-error://. Sau bản sửa: 10,9 s, tab đang xem là cn.bing.com.
 */
import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import assert from 'node:assert';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const B = path.join(HERE, '..', 'tubecli', 'extensions', 'browser');
const bm = fs.readFileSync(path.join(B, 'browser_manager.js'), 'utf8');
const ps = fs.readFileSync(path.join(B, 'preview_server.cjs'), 'utf8');

// 1. probeTcp: mở được → true; bị từ chối / tên miền không có → false; không trả lời → false đúng hạn
const { probeTcp, GOOGLE_HOSTS } = await import('../tubecli/extensions/browser/browser_manager.js');
const srv = net.createServer((s) => s.end());
await new Promise((r) => srv.listen(0, '127.0.0.1', r));
assert.strictEqual(await probeTcp('127.0.0.1', srv.address().port, 2000), true, 'cổng đang mở phải = true');
srv.close();
assert.strictEqual(await probeTcp('127.0.0.1', 1, 2000), false, 'bị từ chối = false');
assert.strictEqual(await probeTcp('no-such-host.invalid', 443, 2000), false, 'tên miền không có = false');
const t0 = Date.now();
assert.strictEqual(await probeTcp('10.255.255.1', 443, 800), false, 'không trả lời = false');
assert(Date.now() - t0 < 2500, 'probeTcp phải dừng theo timeout');
console.log('1 probeTcp  : mở = true | từ chối / không có tên / im lặng = false, dừng đúng hạn');

// 2. Google chỉ bị cho «không có tên miền» khi: Trung Quốc + không proxy + không cô lập + dò thật không tới
assert.deepStrictEqual(GOOGLE_HOSTS, ['google.com', '*.google.com', 'google.com.hk', '*.google.com.hk']);
assert(bm.includes("if (!proxy && !isolate && this.lastIpDetails && String(this.lastIpDetails.countryCode).toUpperCase() === 'CN') {"),
  'chỉ áp dụng ở Trung Quốc, không proxy, không cô lập');
assert(bm.includes("const reachable = await probeTcp('www.google.com', 443, 3000);"), 'phải dò thật, không đoán theo quốc gia');
assert(bm.includes("launchArgs.push('--host-resolver-rules=' + GOOGLE_HOSTS.map((h) => `MAP ${h} ~NOTFOUND`).join(', '));"));
const iRule = bm.indexOf("launchArgs.push('--host-resolver-rules='");
assert(iRule > 0 && iRule < bm.indexOf("console.log(`[ShardX] Spawning:"), 'cờ phải thêm TRƯỚC khi spawn');
assert(bm.indexOf('this.lastIpDetails = ipDetails || null;') < iRule, 'quốc gia phải dò xong trước');
console.log('2 chặn nhanh: CN + không proxy + dò 3 s không tới → --host-resolver-rules MAP google ~NOTFOUND trước spawn');

// 3. preview_server: trang đầu Bing, tab khôi phục hỏng không phải trang để nhìn
assert(ps.includes("const DEFAULT_HOME = { home: 'https://www.bing.com', search: 'https://www.bing.com/search?q=' };"));
assert(!/goto\('https:\/\/www\.google\.com'/.test(ps), 'không còn goto Google cứng');
assert(ps.includes("const loaded = real.filter((p) => !p.url().startsWith('chrome-error://'));"), 'ưu tiên tab tải được');
assert(/\} else if \(real\.length\) \{\n\s+await switchToPage\(real\[real\.length - 1\]\);\n\s+pendingHome = browserHome\.home;/.test(ps),
  'tab nào cũng hỏng → đưa về trang đầu');
assert(ps.indexOf('const ntUrl = msg.url || browserHome.home;') > 0, 'tab mới không URL → trang đầu');
console.log('3 trang đầu : www.bing.com | tab hỏng (chrome-error) → chọn tab tải được, không có thì về trang đầu');
// 4. Nhật ký mở hỏng: dòng «<launching> <~1.900 ký tự cờ>» đẩy lý do thật (exitCode) ra ngoài trần 2.000 ký tự
//    của detail (máy Windows 7/10/2026) → rút về tên exe + số cờ, giữ nguyên các dòng sau
const mt = /function trimLaunchLog\(text\) \{\n([\s\S]*?)\n\}/.exec(ps);
assert(mt, 'thiếu trimLaunchLog');
// eslint-disable-next-line no-new-func
const trimLaunchLog = new Function('text', mt[1]);
const flags = Array.from({ length: 60 }, (_, i) => `--flag-${i}=value-${i}`).join(' ');
const raw = 'browserType.launchPersistentContext: Failed to launch the browser process.\nBrowser logs:\n\n'
  + `<launching> C:\\Users\\USER\\AppData\\Roaming\\shardx-launcher\\chrome.exe ${flags}\n`
  + '<launched> pid=5120\n[pid=5120] <process did exit: exitCode=21, signal=null>';
const out = trimLaunchLog(raw);
assert(out.includes('<launching> C:\\Users\\USER\\AppData\\Roaming\\shardx-launcher\\chrome.exe … (60 args)'), out);
assert(out.includes('[pid=5120] <process did exit: exitCode=21, signal=null>'), 'giữ dòng lý do thoát');
assert(!out.includes('--flag-59'), 'bỏ cờ');
assert(out.length < 400, 'ngắn lại: ' + out.length);
assert.strictEqual(trimLaunchLog('no launching line'), 'no launching line');
assert(ps.includes('Last error: ${trimLaunchLog(lastError?.message || lastError)}'), 'detail dùng trimLaunchLog');
console.log('4 nhật ký   : <launching> rút về exe + số cờ, giữ exitCode');
console.log('OK browser_cn_home_test');
