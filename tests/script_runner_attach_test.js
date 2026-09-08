/**
 * Lượt chạy GẮN vào khung Browser (attach qua CDP) phải làm được hai việc mà bản
 * cũ không làm được — cả hai đo được trên máy thật ngày 8/9/2026, trong lúc thử
 * đăng video lên YouTube Studio bằng hồ sơ testshardx:
 *
 * 1. NẠP FILE LỚN. Playwright coi browser nối qua connectOverCDP là "không cùng
 *    máy" nên setInputFiles đọc cả file vào bộ nhớ rồi từ chối:
 *      "Cannot transfer files larger than 50Mb to a browser not co-located with
 *       the server"
 *    Một video 10 phút của Content Studio vượt mốc đó, nên đường đăng trong live
 *    view chết ngay bước nạp file. Browser thật ra vẫn ở 127.0.0.1, nên đưa
 *    ĐƯỜNG DẪN qua CDP (DOM.setFileInputFiles) là xong, không giới hạn dung lượng.
 *
 * 2. KHÔNG CHẾT VÌ HỘP THOẠI TRÌNH DUYỆT. Rời trang Studio đang mở dở làm Chrome
 *    hiện "Leave site?"; khung Browser và runner cùng nối CDP nên cả hai cùng đóng
 *    nó, và kẻ chậm chân nhận Protocol error "No dialog is showing". Lời hứa đó
 *    không ai bắt ⇒ tiến trình node chết giữa lượt đăng, video treo lại ở nháp.
 *
 * Run:  node tests/script_runner_attach_test.js     (exit 0 = pass)
 */
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const here = path.dirname(fileURLToPath(import.meta.url));
const src = fs.readFileSync(
    path.join(here, '..', 'tubecli', 'extensions', 'browser_scripts', 'runner', 'script_runner.js'),
    'utf-8');

let failed = 0;
const check = (name, ok, detail) => {
    if (ok) { console.log('  ok  ' + name); return; }
    failed++;
    console.log('  FAIL ' + name + (detail ? ' — ' + detail : ''));
};

// ── 1. Nạp file: nhánh CDP chỉ dùng khi attach, và vẫn còn đường lui ──────────
const upload = src.slice(src.indexOf("case 'upload': {"), src.indexOf("case 'keyboard': {"));
check('bước upload có nhánh CDP', upload.includes('DOM.setFileInputFiles'), 'không thấy DOM.setFileInputFiles');
const iAttach = upload.indexOf('if (attach) {');
const iCdp = upload.indexOf('DOM.setFileInputFiles');
check('nhánh CDP nằm TRONG điều kiện attach (lượt thường vẫn đi đường Playwright)',
    iAttach >= 0 && iCdp > iAttach && upload.slice(iAttach, iCdp).split('\n').length < 12,
    `if(attach) ở ${iAttach}, setFileInputFiles ở ${iCdp}`);
check('CDP lấy nodeId từ chính selector của bước',
    /DOM\.querySelector'?,\s*\{\s*nodeId: doc\.root\.nodeId,\s*selector: upSel/.test(upload));
check('CDP hỏng thì vẫn nạp bằng Playwright (đường lui)',
    /if \(!loaded\) await inp\.setInputFiles\(filePath\)/.test(upload));
check('phiên CDP luôn được đóng lại', /finally \{[\s\S]{0,120}client\.detach\(\)/.test(upload));
check('nói rõ trong log là đã nạp bằng CDP', /Đã nạp file lên input\$\{loaded \? ' \(CDP\)' : ''\}/.test(upload));

// ── 2. Hộp thoại trình duyệt không được giết lượt chạy ───────────────────────
check('có hàm tự nhận hộp thoại', /function acceptDialogs\(target\)/.test(src));
check('nuốt lỗi khi client kia đóng trước',
    /d\.accept\(\)[\s\S]{0,80}catch \(e\) \{/.test(src));
check('gắn cho tab đang chạy và cho tab mở sau',
    /acceptDialogs\(page\);[\s\S]{0,80}context\.on\('page', acceptDialogs\)/.test(src));
check('lượt attach gắn cho mọi tab đang mở', /ps\.forEach\(acceptDialogs\)/.test(src));
check('lỗi nền lẻ chỉ được ghi lại, không làm chết tiến trình',
    /process\.on\('unhandledRejection'/.test(src) && /Bỏ qua lỗi nền/.test(src));

// ── 3. AI Auto-Fix: lượt tự động không được gửi cả trang sang model ──────────
// Mỗi bước hỏng là 15.000 ký tự DOM + 3.000 ký tự chữ gửi sang /scripts/ai-fix, mà
// route ấy thử DEEPSEEK trước tiên. Script đăng YouTube từng có ba bước luôn hỏng mỗi
// lượt (gõ ngày, gõ giờ, bấm Xuất bản) ⇒ ba lượt gọi model cho MỖI lần đăng, không ai
// ngồi xem, và selector nó đoán ra từng gõ mô tả video vào ô tìm kiếm.
check('cờ ai_fix mặc định BẬT (nút Chạy thử của người dùng giữ nếp cũ)',
    /const aiFix = execData\.ai_fix === undefined \? true : !!execData\.ai_fix;/.test(src));
const phase2 = src.slice(src.indexOf('Phase 2: AI Fix'), src.indexOf('AI Auto-Fix: analyzing page'));
check('tắt thì chặn TRƯỚC khi gọi model', /if \(!aiFix\)/.test(phase2), phase2.slice(0, 120));
check('tắt mà bước đó on_error=skip thì vẫn skip như thường',
    /if \(!aiFix\)[\s\S]{0,220}onError === 'skip'[\s\S]{0,90}return;/.test(src));
check('tắt mà bước bắt buộc thì vẫn hỏng ra hỏng', /if \(!aiFix\)[\s\S]{0,300}throw err;/.test(src));

console.log(failed === 0 ? '\nALL PASSED' : `\n${failed} FAILED`);
process.exit(failed === 0 ? 0 : 1);
