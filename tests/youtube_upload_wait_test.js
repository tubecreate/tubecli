/**
 * Điều kiện "đã tải xong, bấm Xuất bản được chưa" chạy TRONG TRÌNH DUYỆT, nên nó
 * phải được thử bằng chính những chuỗi YouTube Studio thật sự hiển thị. Các mẫu
 * dưới đây lấy 1 giây/lần trên hồ sơ testshardx ngày 8/9/2026, trong một lượt đăng
 * video 54 MB: nối vào khung Browser qua CDP rồi đọc ytcp-video-upload-progress
 * cùng nhãn #done-button mỗi giây.
 *
 * Vì sao có bài test này: bản đầu tiên coi chữ "processing" là dấu hiệu tải xong.
 * Nhưng NGAY TỪ 0%, Studio đã ghi "Processing will start after video is uploaded"
 * — nên vòng chờ thoát ngay lập tức, và trên máy chậm thì cú bấm rơi vào lúc nút
 * còn mang nhãn "Save" ⇒ video bị LƯU NHÁP trong khi lượt chạy báo thành công.
 *
 * Run:  node tests/youtube_upload_wait_test.js     (exit 0 = pass)
 */
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const here = path.dirname(fileURLToPath(import.meta.url));
const asset = JSON.parse(fs.readFileSync(
    path.join(here, '..', 'tubecli', 'extensions', 'content_video', 'assets', 'youtube_upload.json'), 'utf-8'));

const waitStep = asset.steps.find((s) => String(s.label || '').startsWith('t2:wait-upload'));
if (!waitStep) { console.log('FAIL: bản mẫu không có bước t2:wait-upload'); process.exit(1); }

// Biến được thay như runner làm (interpolate {{...}}) trước khi trang chạy code.
const fill = (code, vars) => code.replace(/\{\{(\w+)\}\}/g, (_, k) => (vars[k] !== undefined ? vars[k] : `{{${k}}}`));

// DOM giả tối thiểu: đủ cho querySelector/querySelectorAll mà biểu thức dùng.
function makeDom({ progress, radioChecked, hasButton, buttonText }) {
    const el = (text) => ({ textContent: text, getBoundingClientRect: () => ({ width: 100, height: 30 }) });
    const radio = radioChecked === null ? null : {
        getAttribute: (n) => (n === 'aria-checked' ? String(radioChecked) : null),
        querySelector: () => null,
        clicked: false,
        click() { this.clicked = true; },
    };
    const button = hasButton ? el(buttonText || 'Publish') : null;
    const doc = {
        querySelector(sel) {
            if (sel.includes('ytcp-video-upload-progress')) return progress === null ? null : el(progress);
            if (sel.includes('tp-yt-paper-radio-button')) return radio;
            if (sel.includes('done-button')) return button;
            return null;
        },
        querySelectorAll(sel) {
            if (sel.includes('done-button')) return button ? [button] : [];
            return [];
        },
    };
    return { doc, radio };
}

const run = (code, state, vars) => {
    const { doc, radio } = makeDom(state);
    const fn = new Function('document', `return (${fill(code, vars)});`);
    return { value: fn(doc), radio };
};

const VARS = { schedule: '0', visibility_radio: 'PUBLIC' };
const CHECK = waitStep.params.break_on;
const INNER = waitStep.params.steps[0].params.code;

let failed = 0;
const check = (name, ok, detail) => {
    if (ok) { console.log('  ok  ' + name); return; }
    failed++;
    console.log('  FAIL ' + name + (detail !== undefined ? ' — ' + JSON.stringify(detail) : ''));
};

// ── Mẫu THẬT trong lúc đang tải: PHẢI chờ ────────────────────────────────────
const uploading0 = 'Video uploading0% uploaded Processing will start after video is uploaded Checks will begin when SD processing completes Uploading 0% ...';
const uploading59 = 'Video uploading59% uploaded Processing will start after video is uploaded Checks will begin when SD processing completes Uploading 59% ...';
for (const [name, text] of [['0%', uploading0], ['59%', uploading59]]) {
    const r = run(CHECK, { progress: text, radioChecked: true, hasButton: true }, VARS);
    check(`đang tải ${name} → chờ (dù chuỗi đã có chữ "Processing")`, r.value === false, r.value);
}

// ── Tải xong / đang xử lý / xong hẳn: đi tiếp khi chế độ hiển thị đã chọn ────
const done1 = 'Checks will begin when SD processing completes Upload complete ... Processing will begin shortly';
const done2 = 'Video upload complete Video processingYour video is processed at 2 quality levels ... 3 minutes left';
const done3 = 'Video upload complete Video processingProcessing complete Copyright check completeNo issues found Checks complete. No issues found.';
for (const [name, text] of [['ngay khi tải xong', done1], ['đang xử lý', done2], ['xong hẳn', done3]]) {
    const r = run(CHECK, { progress: text, radioChecked: true, hasButton: true }, VARS);
    check(`${name} → bấm được`, r.value === true, r.value);
}

// ── Cái bẫy sinh ra NHÁP: chưa chọn chế độ hiển thị thì nút vẫn là "Lưu" ─────
let r = run(CHECK, { progress: done3, radioChecked: false, hasButton: true, buttonText: 'Save' }, VARS);
check('chưa chọn chế độ hiển thị → CHỜ (nút lúc này là "Save" = lưu nháp)', r.value === false, r.value);
r = run(CHECK, { progress: done3, radioChecked: false, hasButton: true }, { schedule: '1', visibility_radio: 'PUBLIC' });
check('lượt HẸN GIỜ không chọn radio → không bắt chờ vô ích', r.value === true, r.value);
r = run(CHECK, { progress: done3, radioChecked: true, hasButton: false }, VARS);
check('chưa thấy nút Xuất bản → chờ', r.value === false, r.value);
r = run(CHECK, { progress: null, radioChecked: true, hasButton: true }, VARS);
check('không có thanh tiến độ (video ngắn, xong từ lâu) → đi tiếp', r.value === true, r.value);

// ── Bước trong vòng lặp: báo tiến độ + tự chọn lại chế độ hiển thị ───────────
r = run(INNER, { progress: uploading59, radioChecked: false, hasButton: true, buttonText: 'Save' }, VARS);
check('log có tiến độ và nhãn nút', /59%/.test(r.value) && /nút: Save/.test(r.value), r.value);
check('tự bấm lại ô chế độ hiển thị khi chưa được chọn', r.radio.clicked === true && / chọn lại /.test(r.value), r.value);
r = run(INNER, { progress: done3, radioChecked: true, hasButton: true }, VARS);
check('đã chọn rồi thì KHÔNG bấm lại', r.radio.clicked === false && !/chọn lại/.test(r.value), r.value);
r = run(INNER, { progress: null, radioChecked: null, hasButton: false }, VARS);
check('thiếu cả thanh tiến độ lẫn nút → vẫn trả log, không ném', /no upload progress bar/.test(r.value) && /chưa có nút/.test(r.value), r.value);

// ── Vòng lặp phải đủ dài cho máy chậm ────────────────────────────────────────
check('chờ được tối đa 30 phút', waitStep.params.count * waitStep.params.delay >= 30 * 60 * 1000,
    waitStep.params.count * waitStep.params.delay);

console.log(failed === 0 ? '\nALL PASSED' : `\n${failed} FAILED`);
process.exit(failed === 0 ? 0 : 1);
