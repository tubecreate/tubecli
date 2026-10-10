// Mục «Upload to YouTube» trong form tạo video của Codex (10/10/2026).
//   node tests/codex_video_youtube_test.js        (exit 0 = pass)
// Chạy THẬT khối mã trong codex.js với DOM giả: khung giờ (cùng luật publish_schedule.parse_slots), options gửi
// pipeline theo từng đường (trình duyệt / API), các lỗi bắt buộc; đối chiếu id trong HTML + khoá i18n ở cả 9 locale.
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const DIR = path.join(ROOT, 'tubecli', 'extensions', 'codex');
const js = fs.readFileSync(path.join(DIR, 'static', 'codex.js'), 'utf8');
const html = fs.readFileSync(path.join(DIR, 'static', 'codex.html'), 'utf8');
let pass = 0, fail = 0;
function check(label, ok, detail) {
    if (ok) { pass++; console.log('  ok   ' + label); } else { fail++; console.log('  FAIL ' + label + '  → ' + JSON.stringify(detail)); }
}

const a = js.indexOf('  // ── «Upload to YouTube» khi video xong');
const b = js.indexOf('  function rememberYt() {');
check('cắt được khối YouTube', a > 0 && b > a, { a, b });

function el(v, extra) { return Object.assign({ value: v, checked: false, innerHTML: '', textContent: '', classList: { toggle() {}, add() {}, remove() {} } }, extra || {}); }
const els = {
    'cx-v-yt': el('', { checked: true }), 'cx-v-yt-method': el('script'), 'cx-v-yt-channel': el(''),
    'cx-v-yt-privacy': el('public'), 'cx-v-yt-when': el('now'), 'cx-v-yt-profile': el(''),
    'cx-v-yt-monetize': el('', { checked: true }), 'cx-v-yt-slots': el(''), 'cx-v-yt-at': el(''),
};
const state = { ytChannels: [{ token_id: 'tok1', channel_id: 'UC1', name: 'Chan One', email: 'a@x' }] };
const stubs = {
    $: id => els[id], t: (k, v) => k + (v ? JSON.stringify(v) : ''), esc: s => String(s), lsGet: () => '', lsSet: () => {},
    request: async () => ({}), state,
};
const api = new Function(...Object.keys(stubs), `${js.slice(a, b)}; return { ytParseSlots, ytOptions };`)(...Object.values(stubs));

console.log('── khung giờ ──');
check('định dạng hỗn hợp như parse_slots', JSON.stringify(api.ytParseSlots('19h30, 08:00 7pm; 25:00, 7:5, 12am')) === JSON.stringify(['00:00', '08:00', '19:00', '19:30']), api.ytParseSlots('19h30, 08:00 7pm; 25:00, 7:5, 12am'));
check('«19h, 7» → 07:00, 19:00', JSON.stringify(api.ytParseSlots('19h, 7')) === JSON.stringify(['07:00', '19:00']), api.ytParseSlots('19h, 7'));

console.log('── options ──');
let o = api.ytOptions();
check('trình duyệt, đăng ngay: publish + method + kiếm tiền + múi giờ', o.publish === true && o.publish_method === 'script'
    && o.publish_monetize === true && o.publish_when === 'now' && typeof o.publish_tz_offset === 'number' && !o.publish_channel_id, o);
els['cx-v-yt-profile'].value = 'muse2';
els['cx-v-yt-channel'].value = 'tok1|UC1';
o = api.ytOptions();
check('hồ sơ + kênh chọn → token/kênh/tên kênh', o.publish_profile === 'muse2' && o.publish_token_id === 'tok1'
    && o.publish_channel_id === 'UC1' && o.publish_channel_name === 'Chan One', o);
els['cx-v-yt-method'].value = 'api';
els['cx-v-yt-channel'].value = '';
o = api.ytOptions();
check('API mà chưa chọn kênh → lỗi + focus ô kênh', o.error && o.focus === 'cx-v-yt-channel', o);
els['cx-v-yt-channel'].value = 'tok1|UC1';
o = api.ytOptions();
check('API: không gửi hồ sơ/kiếm tiền', o.publish_method === 'api' && !('publish_profile' in o) && !('publish_monetize' in o), o);
els['cx-v-yt-when'].value = 'slots';
els['cx-v-yt-slots'].value = '';
check('khung rỗng → lỗi', (api.ytOptions() || {}).focus === 'cx-v-yt-slots');
els['cx-v-yt-slots'].value = '7pm, 8';
o = api.ytOptions();
check('khung → chuỗi chuẩn hoá', o.publish_when === 'slots' && o.publish_slots === '08:00, 19:00', o);
els['cx-v-yt-privacy'].value = 'unlisted';
check('hẹn giờ mà không công khai → lỗi ô hiển thị', (api.ytOptions() || {}).focus === 'cx-v-yt-privacy');
els['cx-v-yt-privacy'].value = 'public';
els['cx-v-yt-when'].value = 'at';
els['cx-v-yt-at'].value = '2000-01-01T10:00';
check('giờ tự chọn đã qua → lỗi', (api.ytOptions() || {}).focus === 'cx-v-yt-at');
const soon = new Date(Date.now() + 3 * 86400000);
const pad = n => (n < 10 ? '0' : '') + n;
els['cx-v-yt-at'].value = `${soon.getFullYear()}-${pad(soon.getMonth() + 1)}-${pad(soon.getDate())}T09:30`;
o = api.ytOptions();
check('giờ tự chọn → mốc ms tuyệt đối', o.publish_when === 'at' && o.publish_at_ms === new Date(els['cx-v-yt-at'].value).getTime(), o);
els['cx-v-yt'].checked = false;
check('tắt → null', api.ytOptions() === null);

console.log('── HTML + i18n ──');
const ids = [...new Set((js.slice(a, js.indexOf('  function resetYtForm() {') + 2000).match(/\$\('(cx-v-yt[\w-]*)'\)/g) || [])
    .map(s => s.slice(3, -2)))];
const missingIds = ids.filter(id => !html.includes(`id="${id}"`));
check('mọi id cx-v-yt-* mà JS dùng đều có trong HTML', ids.length > 8 && !missingIds.length, { ids: ids.length, missingIds });
const exportsBlock = js.slice(js.lastIndexOf('  return {'));
check('nút gọi đúng hàm đã xuất', ['onVideoYt', 'onVideoYtMethod', 'onVideoYtWhen'].every(f =>
    html.includes('CODEX.' + f + '()') && new RegExp('\\b' + f + ',').test(exportsBlock)), {});
const keys = new Set([...(js.slice(a, js.indexOf('  function resetYtForm() {')).match(/t\('(codex\.[\w.]+)'/g) || []).map(s => s.slice(3, -1)),
    ...(html.match(/data-i18n="(codex\.(?:field_video_yt|cv_yt)[\w.]*)"/g) || []).map(s => s.slice(11, -1)),
    'codex.toast_video_yt_channel_required']);
for (const lang of ['en', 'vi', 'es', 'ja', 'ko', 'ru', 'tr', 'zh', 'zh-TW']) {
    const loc = JSON.parse(fs.readFileSync(path.join(DIR, 'locales', lang + '.json'), 'utf8'));
    const miss = [...keys].filter(k => !(k in loc));
    check(`${lang}: đủ ${keys.size} khoá`, !miss.length, miss);
    const badVars = ['codex.cv_yt_slots_hint', 'codex.cv_yt_at_hint', 'codex.cv_yt_at_bad'].filter(k => !String(loc[k] || '').includes('{tz}'));
    check(`${lang}: giữ biến {tz}`, !badVars.length, badVars);
}

console.log('\n' + '='.repeat(60));
console.log(fail ? `${pass}/${pass + fail} PASS — ${fail} HỎNG` : `${pass}/${pass + fail} PASS`);
process.exit(fail ? 1 : 0);
