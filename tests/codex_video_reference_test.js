/**
 * Form «Tạo video từ nội dung» (15/9/2026): link YouTube → phụ đề, «Tham khảo cấu trúc, viết mới»,
 * ô lời dặn riêng, thời lượng đọc dự đoán.
 *
 *   1. cvLinkOnly chạy thật: cùng bộ mẫu với tests/youtube_transcript_test.py
 *   2. renderVideoScript chạy thật: 3 lựa chọn, gợi ý đúng từng chế độ, hiện/ẩn ô giữ chủ đề + ô lời dặn
 *   3. tĩnh: markup, thăm dò link, dòng thời lượng dự đoán, gửi keep_theme/instructions, nhớ lần gần nhất, xuất CODEX
 *   4. bản dịch 9 ngôn ngữ × 13 khoá, đủ chỗ giữ
 *
 * Run:  node tests/codex_video_reference_test.js     (exit 0 = pass)
 */
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const here = path.dirname(fileURLToPath(import.meta.url));
const dir = path.join(here, '..', 'tubecli', 'extensions', 'codex');
const js = fs.readFileSync(path.join(dir, 'static', 'codex.js'), 'utf-8').replace(/\r\n/g, '\n');
const html = fs.readFileSync(path.join(dir, 'static', 'codex.html'), 'utf-8').replace(/\r\n/g, '\n');

let failed = 0;
const check = (name, ok, detail) => {
    if (ok) { console.log('  ok  ' + name); return; }
    failed++;
    console.log('  FAIL ' + name + (detail !== undefined ? ' — ' + JSON.stringify(detail).slice(0, 240) : ''));
};

console.log('── 1. nhận diện link ───────────────────────────────────');
const a = js.indexOf('  const CV_YT_ID_RE = ');
const b = js.indexOf('  /** Ô "Độ dài video"');
check('cắt được khối cvLinkOnly', a > 0 && b > a, { a, b });
const yt = new Function(`${js.slice(a, b)}; return { cvYoutubeIds, cvLinkOnly };`)();
const CASES = [
    ['https://www.youtube.com/watch?v=4Br45kOed_s', ['4Br45kOed_s']],
    ['video tham khảo kênh Paz en el Tao:\nhttps://youtu.be/4Br45kOed_s', ['4Br45kOed_s']],
    ['https://www.youtube.com/watch?feature=share&v=4Br45kOed_s&t=10', ['4Br45kOed_s']],
    ['https://www.youtube.com/shorts/abcdefghijk https://youtube.com/live/ABCDEFGHIJK', ['abcdefghijk', 'ABCDEFGHIJK']],
    ['La calma ordena tu vida. '.repeat(10) + 'Mira este vídeo https://youtu.be/4Br45kOed_s para más.', []],
    ['Hola, esto es un texto sin enlaces', []],
];
for (const [txt, want] of CASES) {
    check(`cvLinkOnly(${JSON.stringify(txt.slice(0, 40))}…) = ${JSON.stringify(want)}`, JSON.stringify(yt.cvLinkOnly(txt)) === JSON.stringify(want), yt.cvLinkOnly(txt));
}
const py = fs.readFileSync(path.join(here, '..', 'tubecli', 'core', 'youtube_transcript.py'), 'utf-8');
check('ngưỡng chữ kèm link khớp Python (12)', /LINK_EXTRA_WORDS = 12\b/.test(py) && js.includes('const CV_YT_EXTRA_WORDS = 12;'));

console.log('── 2. renderVideoScript ────────────────────────────────');
const s1 = js.indexOf('  function renderVideoScript(have, linkOnly) {');
const s2 = js.indexOf('  function onVideoScript() {');
check('cắt được renderVideoScript', s1 > 0 && s2 > s1, { s1, s2 });
const els = {};
const el = (id) => (els[id] ||= { value: '', innerHTML: '', textContent: '', classList: { hidden: false, warn: false, toggle(c, v) { this[c] = !!v; }, add(c) { this[c] = true; } } });
const store = {};
const api = new Function('CV_SCRIPT_KEY', '$', 't', 'esc', 'lsGet', 'lsSet', 'fmtMin',
    `${js.slice(s1, s2)}; return { renderVideoScript };`)(
    'codex.cvScript', el, (k, p) => k + (p ? JSON.stringify(p) : ''), s => String(s),
    k => store[k] || '', (k, v) => { store[k] = v; }, w => String(Math.round(w / 150)));
check('mặc định viết lại, không link → gợi ý trống', api.renderVideoScript(1500, false) === false && el('cx-v-script').value === 'rewrite' && el('cx-v-script-hint').textContent === '');
check('3 lựa chọn, có «tham khảo»', ['codex.cv_script_rewrite', 'codex.cv_script_verbatim', 'codex.cv_script_reference'].every(k => el('cx-v-script').innerHTML.includes(k)));
check('viết lại + link → nhắc chọn tham khảo (cảnh báo)', (api.renderVideoScript(0, true), el('cx-v-script-hint').textContent === 'codex.cv_script_hint_rewrite_link' && el('cx-v-script-hint').classList.warn === true));
el('cx-v-script').value = 'reference';
check('tham khảo → gợi ý riêng, hiện ô giữ chủ đề, hiện ô lời dặn',
    api.renderVideoScript(4500, true) === false && el('cx-v-script-hint').textContent === 'codex.cv_script_hint_reference'
    && el('cx-v-keeptheme-wrap').classList.hidden === false && el('cx-v-instructions-wrap').classList.hidden === false);
el('cx-v-script').value = 'verbatim';
check('nguyên văn → trả true, ẩn ô giữ chủ đề và ô lời dặn',
    api.renderVideoScript(1500, false) === true && el('cx-v-keeptheme-wrap').classList.hidden === true && el('cx-v-instructions-wrap').classList.hidden === true);

console.log('── 3. tĩnh ─────────────────────────────────────────────');
check('markup: ô giữ chủ đề (ẩn sẵn), ô lời dặn, dòng dự đoán',
    html.includes('<label class="cx-check hidden" id="cx-v-keeptheme-wrap">') && html.includes('id="cx-v-keeptheme" checked onchange="CODEX.onVideoKeepTheme()"')
    && html.includes('id="cx-v-instructions" rows="2" maxlength="2000" oninput="CODEX.onVideoInstructions()"') && html.includes('id="cx-v-estimate"'));
check('placeholder nói có thể dán link YouTube', html.includes('or a YouTube link to work from its subtitles'));
check('thăm dò link qua route youtube-probe, bỏ kết quả cũ khi nội dung đổi',
    js.includes("request('/api/v1/content-video/youtube-probe?url=' +") && js.includes("if (!state.ytProbe || state.ytProbe.key !== key) return;"));
check('link → độ dài nguồn = số chữ phụ đề, nhãn «theo video nguồn»',
    js.includes("const have = linkOnly ? ((probe && probe.status === 'ok') ? probe.words : 0) : cvWords(txt);") && js.includes("t(linkOnly ? 'codex.cv_len_mode_source' : 'codex.cv_len_mode_content'"));
check('dòng thời lượng đọc dự đoán', js.includes("t('codex.cv_len_estimate', { words: target.toLocaleString(), min: fmtMin(target) })"));
check('gửi keep_theme (tham khảo) + instructions (trừ nguyên văn)',
    js.includes("if (scriptMode === 'reference') options.keep_theme = !!$('cx-v-keeptheme').checked;") && js.includes("if (instructions && scriptMode !== 'verbatim') options.instructions = instructions;"));
check('nhớ lần gần nhất: mở form trả lại, gửi thì lưu',
    js.includes("$('cx-v-keeptheme').checked = lsGet(CV_KEEP_THEME_KEY) !== '0';") && js.includes("$('cx-v-instructions').value = lsGet(CV_INSTR_KEY) || '';")
    && js.includes("if (keepTheme) lsSet(CV_KEEP_THEME_KEY, keepTheme.checked ? '1' : '0');"));
check('xuất onVideoKeepTheme + onVideoInstructions', js.includes('onVideoScript, onVideoKeepTheme, onVideoInstructions, planFromModal'));

console.log('── 4. bản dịch ─────────────────────────────────────────');
const KEYS = {
    'codex.field_video_content_placeholder': [], 'codex.cv_script_reference': [], 'codex.cv_script_hint_reference': [],
    'codex.cv_script_hint_rewrite_link': [], 'codex.field_video_keep_theme': [], 'codex.field_video_keep_theme_hint': [],
    'codex.field_video_instructions': [], 'codex.field_video_instructions_placeholder': [], 'codex.cv_yt_loading': [],
    'codex.cv_yt_ok': ['{title}', '{words}', '{min}'], 'codex.cv_yt_error': ['{msg}'], 'codex.cv_len_mode_source': ['{min}'],
    'codex.cv_len_estimate': ['{words}', '{min}'],
};
for (const lang of ['en', 'vi', 'es', 'ja', 'ko', 'ru', 'tr', 'zh', 'zh-TW']) {
    const loc = JSON.parse(fs.readFileSync(path.join(dir, 'locales', lang + '.json'), 'utf-8'));
    const bad = Object.entries(KEYS).filter(([k, ph]) => !loc[k] || ph.some(p => !loc[k].includes(p)));
    check(`${lang}.json: đủ 13 khoá + chỗ giữ`, !bad.length, bad.map(x => x[0]));
}
const vi = JSON.parse(fs.readFileSync(path.join(dir, 'locales', 'vi.json'), 'utf-8'));
check('vi dịch thật', vi['codex.cv_script_reference'].includes('Tham khảo cấu trúc') && vi['codex.cv_len_estimate'].includes('phút'));

console.log(failed ? `\n${failed} FAIL` : '\nALL PASS');
process.exit(failed ? 1 : 0);
