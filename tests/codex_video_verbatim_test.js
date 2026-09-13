/**
 * Ô "Kịch bản" của cửa sổ Tạo video từ nội dung: AI viết lại / đọc NGUYÊN VĂN (13/9/2026).
 *
 *   1. codex.html có ô chọn + gợi ý; ô Độ dài có id để ẩn khi nguyên văn
 *   2. codex.js: nhớ lựa chọn (localStorage), gửi script_mode, nguyên văn thì ép
 *      length_mode=content và không gửi target_words; xuất onVideoScript cho onchange
 *   3. renderVideoScript chạy thật với DOM giả: mặc định viết lại; chọn nguyên văn thì
 *      gợi ý có số phút và ô Độ dài bị ẩn
 *   4. đủ khoá bản dịch ở 9 ngôn ngữ, gợi ý giữ {min}
 *
 * Run:  node tests/codex_video_verbatim_test.js     (exit 0 = pass)
 */
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const here = path.dirname(fileURLToPath(import.meta.url));
const dir = path.join(here, '..', 'tubecli', 'extensions', 'codex');
const read = (...p) => fs.readFileSync(path.join(dir, ...p), 'utf-8').replace(/\r\n/g, '\n');
const js = read('static', 'codex.js');
const html = read('static', 'codex.html');

let failed = 0;
const check = (name, ok, detail) => {
    if (ok) { console.log('  ok  ' + name); return; }
    failed++;
    console.log('  FAIL ' + name + (detail !== undefined ? ' — ' + JSON.stringify(detail).slice(0, 300) : ''));
};

console.log('── html ────────────────────────────────────────────────');
check('có ô chọn cx-v-script gọi CODEX.onVideoScript', /<select id="cx-v-script" onchange="CODEX\.onVideoScript\(\)">/.test(html));
check('có dòng gợi ý cx-v-script-hint', html.includes('id="cx-v-script-hint"'));
check('ô Độ dài có bọc cx-v-length-wrap để ẩn khi nguyên văn', html.includes('id="cx-v-length-wrap"') && html.indexOf('cx-v-script') < html.indexOf('cx-v-length-wrap'));

console.log('── js ──────────────────────────────────────────────────');
check('nhớ lựa chọn trong localStorage', js.includes("const CV_SCRIPT_KEY = 'codex.cvScript';") && js.includes('lsSet(CV_SCRIPT_KEY,'));
check('gửi script_mode; nguyên văn ép length_mode=content và bỏ target_words',
    js.includes('options.script_mode = scriptMode;') && /if \(scriptMode === 'verbatim'\) \{[\s\S]*?options\.length_mode = 'content';[\s\S]*?delete options\.target_words;/.test(js));
check('xuất onVideoScript', /onVideoLength, onVideoScript, planFromModal,/.test(js));
check('renderVideoLength ẩn ô Độ dài khi nguyên văn', js.includes("lenWrap.classList.toggle('hidden', verbatim)"));

// ── chạy thật renderVideoScript với DOM giả ──
const a = js.indexOf('  function renderVideoScript(have) {');
const b = js.indexOf('  function onVideoLength() {');
check('cắt được renderVideoScript/onVideoScript', a > 0 && b > a, { a, b });
const store = {};
const els = {};
const el = (id) => (els[id] ||= { value: '', innerHTML: '', textContent: '', classList: { hidden: false, toggle(c, v) { this.hidden = !!v; }, add(c) { this.hidden = true; } } });
const stubs = {
    CV_SCRIPT_KEY: 'codex.cvScript',
    $: (id) => el(id),
    t: (k, p) => k + (p ? JSON.stringify(p) : ''),
    esc: s => String(s),
    lsGet: k => store[k] || '',
    lsSet: (k, v) => { store[k] = v; },
    fmtMin: w => String(Math.round(w / 150)),
    renderVideoLength: () => {},
};
const api = new Function(...Object.keys(stubs), `${js.slice(a, b)}; return { renderVideoScript, onVideoScript };`)(...Object.values(stubs));
check('mặc định: viết lại, gợi ý trống, trả false', api.renderVideoScript(1500) === false && el('cx-v-script').value === 'rewrite' && el('cx-v-script-hint').textContent === '');
check('option có đủ hai lựa chọn từ bản dịch', el('cx-v-script').innerHTML.includes('codex.cv_script_rewrite') && el('cx-v-script').innerHTML.includes('codex.cv_script_verbatim'));
el('cx-v-script').value = 'verbatim';
api.onVideoScript();
check('chọn nguyên văn → nhớ lại', store['codex.cvScript'] === 'verbatim');
check('…gợi ý nguyên văn kèm số phút (1500 chữ ≈ 10)', api.renderVideoScript(1500) === true && el('cx-v-script-hint').textContent === 'codex.cv_script_hint_verbatim{"min":"10"}', el('cx-v-script-hint').textContent);
els['cx-v-script'].value = '';
check('mở lại form: lấy lựa chọn đã nhớ', api.renderVideoScript(0) === true && el('cx-v-script').value === 'verbatim');

console.log('── bản dịch ────────────────────────────────────────────');
for (const lang of ['en', 'vi', 'es', 'ja', 'ko', 'ru', 'tr', 'zh', 'zh-TW']) {
    const loc = JSON.parse(read('locales', lang + '.json'));
    check(`${lang}: đủ 4 khoá, gợi ý giữ {min}`,
        !!loc['codex.field_video_script'] && !!loc['codex.cv_script_rewrite'] && !!loc['codex.cv_script_verbatim']
        && String(loc['codex.cv_script_hint_verbatim'] || '').includes('{min}'));
}
const vi = JSON.parse(read('locales', 'vi.json'));
check('vi nói "nguyên văn"', vi['codex.cv_script_verbatim'].includes('nguyên văn'));

console.log(failed ? `\n${failed} FAIL` : '\nALL PASS');
process.exit(failed ? 1 : 0);
