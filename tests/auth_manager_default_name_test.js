// Add Credential: ô Name có tên mặc định + cảnh báo đưa người dùng tới đúng ô (16/9/2026).
//
// User: "chỗ Add Credential thêm mặc định tên vào trường Name vì khi người dùng quên next qua kia có cảnh báo
// nhưng không thấy name ở đâu." Ô Name ở bước 1, nút Save ở bước 2 → cảnh báo "Please enter a name" chỉ vào
// một ô đang bị ẩn.
//
// Kiểm:
//   1. defaultCredName / fillDefaultCredName / credNameTouched / focusCredName chạy THẬT với DOM giả
//   2. gắn đúng chỗ: mở form, đổi Provider, sang bước 2, hai nhánh Save
//   3. bản sao hot-patch (tubecli-cloud/public/patch) giống hệt bản lõi + ?v= đã nâng
//   4. bản dịch: 2 khoá mới ở mọi file locale của extension và trong auth_locales.json của hot-patch
//
// Run: node tests/auth_manager_default_name_test.js
'use strict';
const fs = require('fs');
const path = require('path');

const CORE = path.join(__dirname, '..');
const STATIC = path.join(CORE, 'tubecli', 'extensions', 'webui', 'static');
const PATCH = path.join(CORE, '..', 'tubecli-cloud', 'public', 'patch');
const js = fs.readFileSync(path.join(STATIC, 'auth_manager.js'), 'utf-8').replace(/\r\n/g, '\n');
const html = fs.readFileSync(path.join(STATIC, 'auth_manager.html'), 'utf-8').replace(/\r\n/g, '\n');

let pass = 0, fail = 0;
function check(label, ok, detail) {
    if (ok) { pass++; console.log('  ok  ', label); }
    else { fail++; console.log('  FAIL', label, detail === undefined ? '' : JSON.stringify(detail).slice(0, 240)); }
}

console.log('── 1. chạy thật với DOM giả ────────────────────────────');
const a = js.indexOf('function defaultCredName(providerKey) {');
const b = js.indexOf('// ── Add Credential Modal ──');
check('cắt được khối tên mặc định', a > 0 && b > a, { a, b });

const PROVIDER_OPTIONS = [{ text: '🔵 Google' }, { text: '📘 Facebook / Meta' }, { text: '🎵 TikTok' }];

/** Dựng lại DOM giả + nạp đúng mã của auth_manager.js. */
function boot({ providers = [], creds = [], provider = 'google', name = '', auto = false } = {}) {
    const steps = [];
    const els = {
        'cred-provider': {
            value: provider, options: PROVIDER_OPTIONS,
            get selectedIndex() { return ['google', 'facebook', 'tiktok'].indexOf(this.value); },
        },
        'cred-name': { value: name, dataset: auto ? { autoName: '1' } : {}, focused: 0, scrolled: null,
            focus() { this.focused++; }, scrollIntoView(o) { this.scrolled = o || {}; } },
    };
    const api = new Function('document', 'providersData', 'credentialsData', 'goToCredStep',
        `${js.slice(a, b)}; return { defaultCredName, credNameTouched, fillDefaultCredName, focusCredName };`)(
        { getElementById: (id) => els[id] || null }, providers, creds, (s) => steps.push(s));
    return { api, els, steps, nameEl: els['cred-name'] };
}

const NAME_CASES = [
    ['chưa có credential nào → tên nhà cung cấp', {}, 'google', 'Google'],
    ['đã có "Google" → Google 2', { creds: [{ name: 'Google' }] }, 'google', 'Google 2'],
    ['đã có Google + Google 2 → Google 3', { creds: [{ name: 'Google' }, { name: 'Google 2' }] }, 'google', 'Google 3'],
    ['so tên KHÔNG phân biệt hoa thường', { creds: [{ name: 'google' }] }, 'google', 'Google 2'],
    ['nhảy qua chỗ trống: có Google 2 mà chưa có Google', { creds: [{ name: 'Google 2' }] }, 'google', 'Google'],
    ['nhãn <select> có emoji → cắt emoji', {}, 'facebook', 'Facebook / Meta'],
    ['tên từ /providers thắng nhãn <select>',
        { providers: [{ id: 'google', name: 'Google Workspace' }] }, 'google', 'Google Workspace'],
    ['tên có khoảng trắng thừa → cắt', { providers: [{ id: 'tiktok', name: '  TikTok  ' }] }, 'tiktok', 'TikTok'],
];
for (const [label, opts, provider, want] of NAME_CASES) {
    const { api, els } = boot({ ...opts, provider });
    els['cred-provider'].value = provider;
    const got = api.defaultCredName(provider);
    check(`${label} → ${want}`, got === want, got);
}
{
    const { api, els } = boot({ provider: 'zalo' });     // nhà lạ: không có trong <select> lẫn /providers
    els['cred-provider'].value = 'zalo';
    check('nhà cung cấp lạ → dùng chính mã nhà', api.defaultCredName('zalo') === 'zalo', api.defaultCredName('zalo'));
}

let t = boot({ creds: [{ name: 'Google' }] });
t.api.fillDefaultCredName('google');
check('ô trống → điền tên mặc định, đánh dấu là tên máy điền',
    t.nameEl.value === 'Google 2' && t.nameEl.dataset.autoName === '1', t.nameEl);

t = boot({ name: 'Kênh nhà tôi' });
t.api.fillDefaultCredName('google');
check('người dùng đã tự gõ → KHÔNG đè', t.nameEl.value === 'Kênh nhà tôi' && !t.nameEl.dataset.autoName, t.nameEl);

t = boot({ name: 'Google', auto: true });
t.els['cred-provider'].value = 'facebook';
t.api.fillDefaultCredName('facebook');
check('đổi Provider mà tên do máy điền → đổi theo nhà mới',
    t.nameEl.value === 'Facebook / Meta' && t.nameEl.dataset.autoName === '1', t.nameEl);

t = boot({ name: 'Google', auto: true });
t.api.credNameTouched();
t.els['cred-provider'].value = 'tiktok';
t.api.fillDefaultCredName('tiktok');
check('người dùng gõ vào ô (credNameTouched) → từ đó không tự đổi nữa', t.nameEl.value === 'Google', t.nameEl.value);

t = boot({ name: '   ', auto: false });
t.api.fillDefaultCredName('google');
check('ô chỉ có khoảng trắng cũng coi là trống', t.nameEl.value === 'Google', t.nameEl.value);

t = boot();
t.api.focusCredName();
check('cảnh báo thiếu tên: về bước 1, cuộn tới ô và focus',
    t.steps[0] === 1 && t.nameEl.focused === 1 && t.nameEl.scrolled && t.nameEl.scrolled.block === 'center',
    { steps: t.steps, focused: t.nameEl.focused, scrolled: t.nameEl.scrolled });

console.log('── 2. gắn đúng chỗ ────────────────────────────────────');
check('mở form: xoá dấu tên-máy-điền rồi để onProviderChange điền',
    js.includes("delete nameInput.dataset.autoName;") && js.indexOf('delete nameInput.dataset.autoName') < js.indexOf('onProviderChange();\n    switchCredTab'));
check('onProviderChange điền tên mặc định', /function onProviderChange[\s\S]{0,200}fillDefaultCredName\(providerKey\);/.test(js));
check('sửa credential cũ: giữ nguyên tên của người dùng',
    js.includes("document.getElementById('cred-name').value = cred.name;\n    delete document.getElementById('cred-name').dataset.autoName;"));
check('sang bước 2 luôn có tên (kể cả khi ô bị xoá trắng)',
    js.includes("fillDefaultCredName();      // sang bước 2 là luôn có tên") &&
    js.indexOf('fillDefaultCredName();      // sang bước 2') < js.indexOf("const name = document.getElementById('cred-name').value || T('auth.new_app');"));
check('Save thiếu tên → focusCredName + câu cảnh báo có i18n',
    js.includes("    if (!body.name) {\n        focusCredName();\n        showToast(T('auth.err_name_required') || 'Please enter a name', 'error');"));
check('tab Manual (Facebook): thiếu tên và thiếu token báo riêng',
    js.includes("if (!manualName) {\n            focusCredName();") && js.includes("T('auth.err_token_required') || 'Please paste the token'"));
check('không còn câu cảnh báo cứng tiếng Việt lẫn trong mã',
    !js.includes("'Vui lòng điền Name và Token!'"));
check('markup: ô Name gọi credNameTouched khi gõ', html.includes('oninput="credNameTouched()"'));

console.log('── 3. bản sao hot-patch ───────────────────────────────');
for (const f of ['auth_manager.js', 'auth_manager.html']) {
    const core = fs.readFileSync(path.join(STATIC, f), 'utf-8');
    const patch = fs.readFileSync(path.join(PATCH, f), 'utf-8');
    check(`${f}: bản public/patch giống hệt bản lõi (hot-patch không được lùi version)`, core === patch,
        { core: core.length, patch: patch.length });
}
const vm = html.match(/auth_manager\.js\?v=(\d+)/);
check('?v= của auth_manager.js đã nâng (≥33) để trình duyệt không dùng bản cache', vm && Number(vm[1]) >= 33, vm && vm[1]);
check('?v= trong bản patch cũng thế',
    (fs.readFileSync(path.join(PATCH, 'auth_manager.html'), 'utf-8').match(/auth_manager\.js\?v=(\d+)/) || [])[1] === (vm && vm[1]));

console.log('── 4. bản dịch ────────────────────────────────────────');
const LOC = path.join(CORE, 'tubecli', 'extensions', 'auth_manager', 'locales');
const KEYS = ['auth.err_name_required', 'auth.err_token_required'];
for (const f of fs.readdirSync(LOC).filter(x => x.endsWith('.json'))) {
    const loc = JSON.parse(fs.readFileSync(path.join(LOC, f), 'utf-8'));
    const missing = KEYS.filter(k => !String(loc[k] || '').trim());
    check(`locales/${f}: đủ 2 khoá mới`, !missing.length, missing);
}
const vi = JSON.parse(fs.readFileSync(path.join(LOC, 'vi.json'), 'utf-8'));
check('vi dịch thật, có chỉ đường tới ô',
    vi['auth.err_name_required'].includes('bước 1') && vi['auth.err_token_required'].includes('token'),
    vi['auth.err_name_required']);
const al = JSON.parse(fs.readFileSync(path.join(PATCH, 'auth_locales.json'), 'utf-8'));
const secs = Object.keys(al);
check('auth_locales.json: mọi khu × mọi ngôn ngữ đều có 2 khoá mới',
    secs.length > 0 && secs.every(s => Object.keys(al[s]).every(l => KEYS.every(k => al[s][l][k]))), secs);
check('auth_locales.json: vi đúng tiếng Việt',
    secs.every(s => String(al[s].vi['auth.err_name_required']).includes('credential')), al[secs[0]].vi['auth.err_name_required']);

console.log();
console.log(fail ? `${pass}/${pass + fail} PASS — ${fail} HỎNG` : `${pass}/${pass + fail} PASS`);
process.exit(fail ? 1 : 0);
