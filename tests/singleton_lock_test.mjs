// Khoá Singleton mồ côi phải được dọn; khoá CÓ CHỦ thì không.
//
// Vì sao đáng một test riêng: đây là thứ giết mọi lượt theo lịch trên Linux
// (Chromium "Failed to create a ProcessSingleton ... Aborting now to avoid
// profile corruption"), trong khi live view sống vì preview_server.cjs có dọn.
// Và cái bẫy dễ tái phát nhất nằm ở chỗ dùng existsSync: nó ĐI THEO symlink, nên
// một SingletonLock trỏ tới đích đã biến mất bị coi là "không tồn tại" và không
// bao giờ được xoá — đúng trạng thái của một hồ sơ vừa bị SIGTERM.
//
//   node tests/singleton_lock_test.mjs
import fs from 'fs';
import os from 'os';
import path from 'path';
import { fileURLToPath } from 'url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(HERE, '..', 'tubecli', 'extensions', 'browser', 'browser_manager.js');

// Trích đúng hai hàm khỏi file thật — cùng lối với tests/preview_preflight_test.py:
// hàm tự chứa, ngoặc đóng ở cột 0. Không mock lại logic, để test hỏng khi mã đổi.
const src = fs.readFileSync(SRC, 'utf8');
function extract(name) {
    const re = new RegExp('function ' + name + '\\([^)]*\\)\\s*\\{[\\s\\S]*?\\n\\}');
    const m = src.match(re);
    if (!m) throw new Error('không trích được hàm ' + name + ' — mã đã đổi?');
    return m[0];
}
const mod = new Function('fs', 'path', 'process', 'console',
    extract('singletonHolderPid') + '\n' + extract('clearStaleSingletonLocks')
    + '\nreturn { singletonHolderPid, clearStaleSingletonLocks };');

let pass = 0, fail = 0;
const quiet = { log() {}, warn() {}, error() {} };
const api = mod(fs, path, process, quiet);

function check(name, fn) {
    try { fn(); console.log('  ok   ' + name); pass++; }
    catch (e) { console.log('  FAIL ' + name + ' -> ' + e.message); fail++; }
}
function tmpProfile() {
    return fs.mkdtempSync(path.join(os.tmpdir(), 'sgl-'));
}
function assert(cond, msg) { if (!cond) throw new Error(msg); }

// Các case symlink là hành vi LINUX — đúng nơi lỗi này xảy ra — nhưng Windows
// không cho tạo symlink nếu thiếu quyền. Bỏ qua chúng nghĩa là không bao giờ kiểm
// được phần quan trọng nhất, nên thay vì vậy ta tiêm một `fs` giả vào chính hàm
// thật: logic đọc symlink + kiểm pid được chạy y nguyên trên mọi OS.
function fakeFs(entries) {
    const nameOf = (p) => String(p).split(/[\\/]/).pop();
    return {
        readlinkSync(p) {
            const e = entries[nameOf(p)];
            if (!e || e.type !== 'symlink') { const err = new Error('EINVAL'); err.code = 'EINVAL'; throw err; }
            return e.target;
        },
        lstatSync(p) {
            const e = entries[nameOf(p)];
            if (!e) { const err = new Error('ENOENT'); err.code = 'ENOENT'; throw err; }
            return { isSymbolicLink: () => e.type === 'symlink' };
        },
        unlinkSync(p) {
            const n = nameOf(p);
            if (!entries[n]) { const err = new Error('ENOENT'); err.code = 'ENOENT'; throw err; }
            delete entries[n];
        },
    };
}
const withFs = (entries) => mod(fakeFs(entries), path, process, quiet);

console.log('=== khoá Singleton ===');

check('khoá dạng FILE thường (kiểu Windows) được dọn', () => {
    const d = tmpProfile();
    for (const f of ['SingletonLock', 'SingletonSocket', 'SingletonCookie', 'LOCK']) {
        fs.writeFileSync(path.join(d, f), '');
    }
    api.clearStaleSingletonLocks(d);
    for (const f of ['SingletonLock', 'SingletonSocket', 'SingletonCookie', 'LOCK']) {
        assert(!fs.existsSync(path.join(d, f)), f + ' còn sót');
    }
});

check('thư mục sạch: không ném, không làm gì', () => {
    const d = tmpProfile();
    api.clearStaleSingletonLocks(d);
    assert(fs.readdirSync(d).length === 0, 'đã tạo thêm file lạ');
});

check('file khác trong hồ sơ không bị đụng', () => {
    const d = tmpProfile();
    fs.writeFileSync(path.join(d, 'SingletonLock'), '');
    fs.writeFileSync(path.join(d, 'config.json'), '{"browser_version":"ShardX 149"}');
    fs.mkdirSync(path.join(d, 'Default'));
    api.clearStaleSingletonLocks(d);
    assert(fs.existsSync(path.join(d, 'config.json')), 'config.json bị xoá');
    assert(fs.existsSync(path.join(d, 'Default')), 'Default/ bị xoá');
});

check('symlink trỏ tới PID đã chết -> dọn (case của VPS sau SIGTERM)', () => {
    // PID chắc chắn không tồn tại: vượt xa pid_max mặc định của Linux (4194304).
    const entries = {
        SingletonLock: { type: 'symlink', target: 'some-host-2147480000' },
        SingletonSocket: { type: 'symlink', target: '/tmp/.org.chromium.x' },
        SingletonCookie: { type: 'symlink', target: '4242' },
    };
    const a = withFs(entries);
    assert(a.singletonHolderPid('/p') === 0, 'coi nhầm khoá mồ côi là còn sống');
    a.clearStaleSingletonLocks('/p');
    assert(Object.keys(entries).length === 0,
        'còn sót: ' + Object.keys(entries).join(', '));
});

check('symlink trỏ tới PID CÒN SỐNG -> từ chối, KHÔNG xoá', () => {
    const entries = { SingletonLock: { type: 'symlink', target: 'some-host-' + process.pid } };
    const a = withFs(entries);
    assert(a.singletonHolderPid('/p') === process.pid, 'không nhận ra chủ khoá');
    let code = '';
    try { a.clearStaleSingletonLocks('/p'); } catch (e) { code = e.code; }
    assert(code === 'PROFILE_IN_USE', 'phải ném PROFILE_IN_USE, nhận: ' + (code || 'không ném'));
    // Quan trọng hơn cả thông báo: khoá THẬT phải còn nguyên. Xoá nó là mở đè lên
    // hồ sơ đang được dùng — đúng cái Chromium cảnh báo sẽ làm hỏng hồ sơ.
    assert(entries.SingletonLock, 'đã xoá khoá đang có chủ');
});

check('pid rác trong symlink -> coi là mồ côi, không nổ', () => {
    // Lưu ý: 'host--5' KHÔNG nằm đây. split('-').pop() cho "5" — một pid hợp lệ,
    // và pid 5 tồn tại thật trên nhiều máy. Mã coi đó là khoá có chủ và từ chối, đúng
    // hướng an toàn: thà không mở còn hơn mở đè lên hồ sơ đang dùng. Tên máy có dấu
    // gạch ("my-server-4242") cũng buộc phải lấy cụm cuối, nên đây là đánh đổi có ý thức.
    for (const target of ['khong-co-so', 'host-', 'host-0', 'host-abc', '']) {
        const entries = { SingletonLock: { type: 'symlink', target } };
        const a = withFs(entries);
        assert(a.singletonHolderPid('/p') === 0, 'target ' + JSON.stringify(target) + ' bị coi là còn sống');
        a.clearStaleSingletonLocks('/p');
        assert(!entries.SingletonLock, 'target ' + JSON.stringify(target) + ': không dọn');
    }
});

check('không đọc được symlink (file thường) -> vẫn dọn', () => {
    const entries = { SingletonLock: { type: 'file' }, LOCK: { type: 'file' } };
    const a = withFs(entries);
    assert(a.singletonHolderPid('/p') === 0, 'file thường không được coi là mồ côi');
    a.clearStaleSingletonLocks('/p');
    assert(Object.keys(entries).length === 0, 'còn sót: ' + Object.keys(entries).join(', '));
});

check('dùng lstat chứ không existsSync — symlink TREO vẫn bị dọn', () => {
    // Đây là bẫy dễ tái phát nhất: existsSync ĐI THEO symlink, nên một SingletonLock
    // trỏ tới đích đã biến mất (đúng trạng thái sau khi tiến trình bị SIGTERM) sẽ bị
    // coi là "không tồn tại" và không bao giờ được xoá. fakeFs không có existsSync,
    // nên nếu ai đó sửa mã sang existsSync thì hàm sẽ ném ngay tại đây.
    const entries = { SingletonLock: { type: 'symlink', target: 'host-2147480001' } };
    const a = withFs(entries);
    a.clearStaleSingletonLocks('/p');
    assert(!entries.SingletonLock, 'symlink treo còn sót');
    // Soi LỜI GỌI thật, không phải chữ trong chú thích (chú thích của hàm có nhắc
    // tên existsSync để giải thích vì sao không dùng nó).
    const body = extract('clearStaleSingletonLocks').split('\n')
        .map((ln) => ln.replace(/\/\/.*$/, '')).join('\n');
    assert(!/\bfs\.existsSync\s*\(/.test(body),
        'mã đã quay lại dùng fs.existsSync — symlink treo sẽ không bao giờ được dọn');
    assert(/\bfs\.lstatSync\s*\(/.test(body), 'không còn dùng fs.lstatSync');
});

console.log(`\n${pass} pass, ${fail} fail`);
process.exit(fail ? 1 : 0);
