// Xem theo tầm nhìn: client ngoài màn KHÔNG nhận frame, và hết người-xem-thực thì
// vòng chụp phải dừng. Đây là hai điều làm nên lời hứa "không ai xem thì không tốn".
//
// Trích thẳng activeViewerCount + broadcastFrame khỏi preview_server.cjs (hàm tự
// chứa, ngoặc đóng ở cột 0) và chạy với clients/pausedClients giả — để test hỏng
// nếu ai đó lỡ bỏ nhánh bỏ-frame hoặc đổi cách đếm.
//
//   node tests/preview_visibility_test.mjs
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(HERE, '..', 'tubecli', 'extensions', 'browser', 'preview_server.cjs');
const src = fs.readFileSync(SRC, 'utf8');

function extract(name) {
    const re = new RegExp('function ' + name + '\\([^)]*\\)\\s*\\{[\\s\\S]*?\\n\\}');
    const m = src.match(re);
    if (!m) throw new Error('không trích được ' + name + ' — mã đã đổi?');
    return m[0];
}

let pass = 0, fail = 0;
function check(name, fn) {
    try { fn(); console.log('  ok   ' + name); pass++; }
    catch (e) { console.log('  FAIL ' + name + ' -> ' + e.message); fail++; }
}
function assert(c, m) { if (!c) throw new Error(m); }

// Một ws giả: đủ trường broadcastFrame đọc (readyState, bufferedAmount, send).
function fakeWs() {
    const w = { readyState: 1, bufferedAmount: 0, sent: 0 };
    w.send = () => { w.sent++; };
    return w;
}

const makeCount = new Function('clients', 'pausedClients',
    extract('activeViewerCount') + '\nreturn activeViewerCount;');
const makeFrame = new Function('clients', 'pausedClients', 'MAX_BUFFERED_BYTES', 'markReady',
    extract('broadcastFrame') + '\nreturn broadcastFrame;');

console.log('=== xem theo tầm nhìn ===');

check('activeViewerCount: không ai ẩn -> đếm hết', () => {
    const clients = new Set([fakeWs(), fakeWs(), fakeWs()]);
    const paused = new Set();
    assert(makeCount(clients, paused)() === 3, 'phải là 3');
});

check('activeViewerCount: bớt người ẩn', () => {
    const a = fakeWs(), b = fakeWs(), c = fakeWs();
    const clients = new Set([a, b, c]);
    const paused = new Set([b]);
    assert(makeCount(clients, paused)() === 2, 'ẩn 1 -> còn 2');
});

check('activeViewerCount: ẩn HẾT -> 0 (đây là lúc server ngừng chụp)', () => {
    const a = fakeWs(), b = fakeWs();
    const clients = new Set([a, b]);
    const paused = new Set([a, b]);
    assert(makeCount(clients, paused)() === 0, 'ẩn hết phải là 0');
});

check('broadcastFrame: client ẩn KHÔNG nhận frame, client hiện thì có', () => {
    const on = fakeWs(), off = fakeWs();
    const clients = new Set([on, off]);
    const paused = new Set([off]);
    const bf = makeFrame(clients, paused, 512 * 1024, () => {});
    bf(Buffer.from('x'.repeat(100)));
    assert(on.sent === 1, 'client trong tầm phải nhận 1 frame, có ' + on.sent);
    assert(off.sent === 0, 'client ngoài tầm KHÔNG được nhận frame, có ' + off.sent);
});

check('broadcastFrame: vẫn bỏ frame khi buffer đầy (giữ luật cũ)', () => {
    const slow = fakeWs(); slow.bufferedAmount = 999 * 1024;   // trên MAX
    const clients = new Set([slow]);
    const bf = makeFrame(clients, new Set(), 512 * 1024, () => {});
    const r = bf(Buffer.from('y'.repeat(100)));
    assert(slow.sent === 0 && r.skipped === 1, 'buffer đầy phải skip');
});

console.log(`\n${pass} pass, ${fail} fail`);
process.exit(fail ? 1 : 0);
