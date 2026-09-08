/**
 * Hai thứ trong giao diện Codex:
 *
 * 1. "Mấy phút trước" phải đo bằng ĐỒNG HỒ MÁY CHỦ. Mốc trong task do máy chủ ghi;
 *    đo bằng đồng hồ máy người xem là trộn hai đồng hồ, nên máy chủ ở múi giờ khác
 *    (hoặc máy khách sai giờ) làm task vừa tạo hiện thành "5 h ago" — đúng thứ
 *    người dùng gặp ngày 8/9/2026.
 * 2. Chi tiết task dài hơn màn hình thì phải có nút thu gọn Ở CUỐI; thu xong phải
 *    đưa chính thẻ đó về tầm mắt, không để trang nhảy đi đâu.
 *
 * Run:  node tests/codex_ui_time_test.js     (exit 0 = pass)
 */
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const here = path.dirname(fileURLToPath(import.meta.url));
const dir = path.join(here, '..', 'tubecli', 'extensions', 'codex');
const js = fs.readFileSync(path.join(dir, 'static', 'codex.js'), 'utf-8');
const css = fs.readFileSync(path.join(dir, 'static', 'codex.css'), 'utf-8');

let failed = 0;
const check = (name, ok, detail) => {
    if (ok) { console.log('  ok  ' + name); return; }
    failed++;
    console.log('  FAIL ' + name + (detail !== undefined ? ' — ' + JSON.stringify(detail) : ''));
};

// ── 1. Đồng hồ máy chủ ───────────────────────────────────────────────────────
// Chạy thật hai hàm, không chỉ dò chuỗi: cắt đúng đoạn serverNow + relTime ra khỏi
// tệp rồi cấp cho nó vài phụ thuộc tối thiểu.
const slice = js.slice(js.indexOf('  function serverNow()'), js.indexOf('  function clockTime('));
const mk = (state) => new Function('state', 't', 'parseTs', `${slice}; return { serverNow, relTime };`)(
    state,
    (key, vars) => key + (vars && vars.n !== undefined ? ':' + vars.n : ''),
    (s) => { const d = new Date(String(s).replace(/(\.\d{3})\d+/, '$1')); return isNaN(d.getTime()) ? null : d; },
);

// Máy chủ ở UTC+2, người xem ở UTC+7, task tạo cách đây 2 phút theo giờ MÁY CHỦ.
const serverIso = '2026-09-08T04:00:00+02:00';
const madeIso = '2026-09-08T03:58:00+02:00';
let api = mk({ clock: { iso: serverIso, at: Date.now() } });
check('task tạo 2 phút trước → "2 phút"', api.relTime(madeIso) === 'codex.time_min:2', api.relTime(madeIso));
check('task tạo vài giây trước → "vừa xong"',
    api.relTime('2026-09-08T03:59:50+02:00') === 'codex.time_now', api.relTime('2026-09-08T03:59:50+02:00'));
check('mốc cũ hơn 1 ngày vẫn ra ngày',
    api.relTime('2026-09-06T04:00:00+02:00') === 'codex.time_day:2', api.relTime('2026-09-06T04:00:00+02:00'));

// Máy KHÁCH sai giờ (chạy nhanh 5 tiếng): mốc `at` được ghi bằng chính đồng hồ sai
// ấy, và ta chỉ dùng KHOẢNG CÁCH kể từ đó — nên con số vẫn đúng.
const realNow = Date.now;
try {
    Date.now = () => realNow() + 5 * 3600 * 1000;
    api = mk({ clock: { iso: serverIso, at: Date.now() } });
    check('đồng hồ máy khách sai 5 tiếng → vẫn "2 phút"',
        api.relTime(madeIso) === 'codex.time_min:2', api.relTime(madeIso));
} finally {
    Date.now = realNow;
}

// Máy chủ bản cũ (không gửi `now`) → quay về đồng hồ máy khách như trước, không vỡ.
api = mk({ clock: null });
const twoMinAgo = new Date(Date.now() - 120000).toISOString();
check('máy chủ cũ không gửi now → vẫn chạy bằng đồng hồ máy khách',
    api.relTime(twoMinAgo) === 'codex.time_min:2', api.relTime(twoMinAgo));
check('mốc rỗng → chuỗi rỗng', api.relTime('') === '' && api.relTime(null) === '');
check('mốc rác → chuỗi rỗng, không ném', api.relTime('không phải ngày') === '');

// Danh sách task phải ghi lại đồng hồ máy chủ khi tải về.
check('lưu đồng hồ máy chủ từ payload /tasks',
    /state\.clock = payload\.now \? \{ iso: payload\.now, at: Date\.now\(\) \} : null/.test(js));

// ── 2. Nút thu gọn ở cuối chi tiết ──────────────────────────────────────────
check('chi tiết có chân thẻ với nút thu gọn',
    /cx-card-foot[\s\S]{0,220}CODEX\.collapse\('\$\{id\}'\)/.test(js));
check('nút dùng nhãn dịch được, không phải chữ cứng',
    /codex\.action_collapse/.test(js));
check('collapse được xuất ra cho onclick', /\bcollapse,/.test(js.slice(js.indexOf('return {', js.indexOf('Public surface')))));
check('thu xong đưa thẻ về tầm mắt',
    /function collapse\(taskId\)[\s\S]{0,600}scrollIntoView\(\{ block: 'nearest' \}\)/.test(js));
check('thẻ chưa mở thì bấm không làm gì',
    /function collapse\(taskId\) \{\s*if \(!state\.expanded\.has\(taskId\)\) return;/.test(js));
check('có kiểu cho chân thẻ', /\.cx-card-foot\s*\{/.test(css));

// ── 3. Nhãn có đủ 9 ngôn ngữ ────────────────────────────────────────────────
const locales = fs.readdirSync(path.join(dir, 'locales')).filter((f) => f.endsWith('.json'));
check('có đủ 9 tệp ngôn ngữ', locales.length === 9, locales.length);
const missing = locales.filter((f) => {
    const d = JSON.parse(fs.readFileSync(path.join(dir, 'locales', f), 'utf-8'));
    return !d['codex.action_collapse'];
});
check('mọi ngôn ngữ đều có nhãn thu gọn', missing.length === 0, missing);
const vi = JSON.parse(fs.readFileSync(path.join(dir, 'locales', 'vi.json'), 'utf-8'));
check('tiếng Việt dịch đúng nghĩa', vi['codex.action_collapse'] === 'Thu gọn', vi['codex.action_collapse']);

console.log(failed === 0 ? '\nALL PASSED' : `\n${failed} FAILED`);
process.exit(failed === 0 ? 0 : 1);
