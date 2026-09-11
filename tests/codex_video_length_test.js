/**
 * Ô "Độ dài video" của cửa sổ Tạo video từ nội dung (11/9/2026).
 *
 * Bệnh: dán dài hay ngắn cũng ra ~14 shot, vì độ dài lấy từ ô Video Length của
 * MẪU. Giờ mặc định là theo bài dán, và ô ước lượng trong form phải nói ĐÚNG con
 * số pipeline sẽ dùng:
 *   1. cvWords đếm y hệt content_words() bên pipeline — cùng bộ mẫu với
 *      tests/content_video_length_mode_test.py, cùng con số.
 *   2. Hằng số độ dài khớp pipeline.py.
 *   3. Đủ khoá bản dịch ở cả 9 ngôn ngữ, đủ chỗ giữ {…}; form gửi length_mode.
 *
 * Run:  node tests/codex_video_length_test.js     (exit 0 = pass)
 */
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const here = path.dirname(fileURLToPath(import.meta.url));
const dir = path.join(here, '..', 'tubecli', 'extensions', 'codex');
const js = fs.readFileSync(path.join(dir, 'static', 'codex.js'), 'utf-8');
const html = fs.readFileSync(path.join(dir, 'static', 'codex.html'), 'utf-8');
const py = fs.readFileSync(path.join(here, '..', 'tubecli', 'extensions', 'content_video', 'pipeline.py'), 'utf-8');

let failed = 0;
const check = (name, ok, detail) => {
    if (ok) { console.log('  ok  ' + name); return; }
    failed++;
    console.log('  FAIL ' + name + (detail !== undefined ? ' — ' + JSON.stringify(detail) : ''));
};

// Chạy thật các hàm: cắt đúng khối hằng số + cvWords/fmtMin/clampMinutes ra khỏi tệp.
const a = js.indexOf('  const CV_WPM = ');
const b = js.indexOf('  /** Ô "Độ dài video"');
check('tìm được khối độ dài trong codex.js', a > 0 && b > a, { a, b });
const api = new Function(`${js.slice(a, b)}; return { cvWords, fmtMin, clampMinutes,
    CV_WPM, CV_WORDS_MIN, CV_WORDS_MAX, CV_DEFAULT_WORDS, CV_LEN_WORDS };`)();

// ── 1. Đếm chữ: CÙNG bộ mẫu với test Python ─────────────────────────────────
console.log('── đếm chữ ─────────────────────────────────────────────');
const SAMPLES = [
    ['Hola mundo, esto es una prueba.', 6],
    ['Xin chào — thế giới !', 4],
    ['你好世界，这是测试。', 4],
    ['日本語のテキストです', 5],
    ['สวัสดีครับ', 2],
    ['AI 你好 test', 3],
    ['', 0],
];
for (const [text, want] of SAMPLES) {
    check(`cvWords(${JSON.stringify(text)}) = ${want}`, api.cvWords(text) === want, api.cvWords(text));
}
const w2943 = Array.from({ length: 2943 }, (_, i) => 'w' + i).join(' ');
check('bài 2943 chữ → 2943', api.cvWords(w2943) === 2943, api.cvWords(w2943));
check('1600 chữ Hán → 800 (split cũ đếm ra 1)', api.cvWords('你好世界'.repeat(400)) === 800);

console.log('── phút ─────────────────────────────────────────────────');
check('2943 chữ ≈ 20 phút', api.fmtMin(2943) === (20).toLocaleString(), api.fmtMin(2943));
check('800 chữ ≈ 5.3 phút', api.fmtMin(800) === (5.3).toLocaleString(), api.fmtMin(800));
check('tự chọn 30 phút → kẹp 26 (4000 chữ)', api.clampMinutes('30') === 26);
check('ô trống / chữ → 10 phút', api.clampMinutes('') === 10 && api.clampMinutes('abc') === 10);
check('3 phút giữ nguyên', api.clampMinutes('3') === 3);

// ── 2. Hằng số khớp pipeline.py ─────────────────────────────────────────────
console.log('── khớp pipeline.py ─────────────────────────────────────');
const num = (re) => { const m = py.match(re); return m ? m.slice(1).map(Number) : null; };
check('WORDS_PER_MINUTE', JSON.stringify(num(/^WORDS_PER_MINUTE = (\d+)/m)) === JSON.stringify([api.CV_WPM]));
check('_WORDS_MIN, _WORDS_MAX', JSON.stringify(num(/^_WORDS_MIN, _WORDS_MAX = (\d+), (\d+)/m))
    === JSON.stringify([api.CV_WORDS_MIN, api.CV_WORDS_MAX]));
check('DEFAULT_WORDS', JSON.stringify(num(/^DEFAULT_WORDS = (\d+)/m)) === JSON.stringify([api.CV_DEFAULT_WORDS]));
const block = (py.match(/^_VIDEO_LENGTH_WORDS = \{([\s\S]*?)^\}/m) || [])[1] || '';
const pyLen = Object.fromEntries([...block.matchAll(/"(\w+)":\s*(\d+)/g)].map(m => [m[1], Number(m[2])]));
check('_VIDEO_LENGTH_WORDS', JSON.stringify(pyLen) === JSON.stringify(api.CV_LEN_WORDS), { py: pyLen, js: api.CV_LEN_WORDS });
check('biểu thức chữ Hán/Thái giống nhau hai bên',
    py.includes('[\\u3040-\\u30ff\\u3400-\\u4dbf\\u4e00-\\u9fff\\uf900-\\ufaff]') &&
    js.includes('[\\u3040-\\u30ff\\u3400-\\u4dbf\\u4e00-\\u9fff\\uf900-\\ufaff]') &&
    py.includes('[\\u0e00-\\u0e7f]') && js.includes('[\\u0e00-\\u0e7f]'));

// ── 3. Bản dịch + form ──────────────────────────────────────────────────────
console.log('── bản dịch + form ──────────────────────────────────────');
const KEYS = {
    'codex.field_video_length': [], 'codex.field_video_minutes': [],
    'codex.cv_len_mode_content': ['{min}'], 'codex.cv_len_mode_content_empty': [],
    'codex.cv_len_mode_template': ['{len}', '{min}'], 'codex.cv_len_mode_minutes': [],
    'codex.cv_len_hint_content': [], 'codex.cv_len_hint_capped': ['{words}', '{max}', '{min}'],
    'codex.cv_len_hint_fit': ['{min}'], 'codex.cv_len_default': [],
};
for (const lang of ['en', 'vi', 'es', 'ja', 'ko', 'ru', 'tr', 'zh', 'zh-TW']) {
    const loc = JSON.parse(fs.readFileSync(path.join(dir, 'locales', lang + '.json'), 'utf-8'));
    const bad = Object.entries(KEYS).filter(([k, ph]) => !loc[k] || ph.some(p => !loc[k].includes(p)));
    check(`${lang}.json: đủ 10 khoá và chỗ giữ`, !bad.length, bad.map(x => x[0]));
}
const vi = JSON.parse(fs.readFileSync(path.join(dir, 'locales', 'vi.json'), 'utf-8'));
check('vi dịch thật', vi['codex.cv_len_mode_content'].includes('phút'));
check('form có ô chọn độ dài + ô số phút',
    html.includes('id="cx-v-length"') && html.includes('id="cx-v-minutes"') &&
    html.includes('onchange="CODEX.onVideoLength()"'));
check('onVideoLength được xuất ra CODEX', /onVideoContent, onVideoLength,/.test(js));
check('Tạo video gửi length_mode (+ target_words khi tự chọn phút)',
    js.includes('options.length_mode = lengthMode') && js.includes('options.target_words = clampMinutes('));
check('thẻ tóm tắt mẫu thôi hiện độ dài (nó có ô riêng)', !/meta\.push\([^)]*wizVideoLength/.test(js));

console.log(failed ? `\n${failed} FAIL` : '\nALL PASS');
process.exit(failed ? 1 : 0);
