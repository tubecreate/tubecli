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

// ── 3. Không còn nhờ AI đoán selector ───────────────────────────────────────
// Bản trước: mỗi bước HỎNG là 15.000 ký tự DOM + 3.000 ký tự chữ gửi sang
// /api/v1/scripts/ai-fix (thử deepseek trước tiên, không theo model của agent), rồi
// chạy lại bước bằng selector nó đoán. Đo trên YouTube Studio: chưa sửa được ca nào,
// mà đã có ca gõ mô tả video vào ô TÌM KIẾM. Bỏ hẳn — script đăng một lượt là ba lần
// gọi model như thế.
check('không còn gọi /scripts/ai-fix', !/scripts\/ai-fix/.test(src));
check('không còn Phase 2', !/AI Auto-Fix|AI fix worked|pre_action_clicks/.test(src));
check('không còn cờ ai_fix để phải nhớ', !/ai_fix|aiFix/.test(src));
check('smart-fix (dò selector tại chỗ, không tốn token) thì GIỮ',
    /Smart fix: probing page for element/.test(src));
check('bước hỏng vẫn theo on_error của chính nó',
    /if \(onError === 'skip'\)[\s\S]{0,120}return;[\s\S]{0,80}if \(onError === 'abort'\) throw err;/.test(src));

// ── 4. Ô nhập dài: DÁN chứ không gõ từng ký tự ──────────────────────────────
// humanType nghỉ 40–120 ms mỗi ký tự (+ dấu cách + quãng "nghĩ") ⇒ ~100 ms/ký tự.
// Mô tả video được phép tới 5000 ký tự ⇒ tới ~8 phút cho MỘT ô, và thẻ task chỉ hiện
// "step 9 type: Điền mô tả" nên trông như treo — đúng thứ người dùng gặp 8/9/26.
// Người thật cũng dán mô tả chứ không gõ tay.
const typeStep = src.slice(src.indexOf("case 'type': {"), src.indexOf("case 'wait': {"));
check('có ngưỡng gõ tay', /const HUMAN_TYPE_MAX = \d+;/.test(src));
check('dài hơn ngưỡng thì insertText (đúng sự kiện nhập của trình duyệt, như Ctrl+V)',
    /text\.length > HUMAN_TYPE_MAX/.test(typeStep) && /keyboard\.insertText\(text\)/.test(typeStep));
check('ngắn thì vẫn giữ nhịp gõ người (ô đăng nhập, ô tìm kiếm)',
    /else await humanType\(page, text\)/.test(typeStep));
check('ép gõ tay được bằng params.human', /params\.human !== true/.test(typeStep));
check('log nói rõ đã dán hay đã gõ', /\(dán một lượt\)/.test(typeStep));
const cap = /const HUMAN_TYPE_MAX = (\d+);/.exec(src);
check('ngưỡng đủ nhỏ để mô tả không bao giờ bị gõ tay', cap && Number(cap[1]) <= 400, cap && cap[1]);

console.log(failed === 0 ? '\nALL PASSED' : `\n${failed} FAILED`);
process.exit(failed === 0 ? 0 : 1);
