// Nút «🖼 Test ảnh» trong bảng «Keys đã lưu» (Cloud API Keys) — 17/9/2026.
//
// User: "giúp tôi thêm logic test api ảnh ở đây".
//
// Kiểm:
//   1. nút chỉ có ở khoá vẽ được (cloudflare, gemini, 9router), gọi đúng khoá của dòng
//   2. dòng kết quả vẽ thử gần nhất trong cột Trạng thái (được / lỗi kèm lý do)
//   3. testImageKey: khoá nút khi đang vẽ, POST đúng route, mở hộp xem ảnh / lý do lỗi, vẽ lại bảng
//   4. bảng gắn nút + dòng kết quả; index.html đổi ?v= để trình duyệt lấy app.js mới; bản dịch 9 ngôn ngữ
//
// Run: node tests/cloud_key_image_ui_test.js
'use strict';
const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..', 'tubecli', 'extensions');
const js = fs.readFileSync(path.join(root, 'webui', 'static', 'app.js'), 'utf-8').replace(/\r\n/g, '\n');
const html = fs.readFileSync(path.join(root, 'webui', 'static', 'index.html'), 'utf-8');

let pass = 0, fail = 0;
function check(label, ok, detail) {
    if (ok) { pass++; console.log('  ok  ', label); }
    else { fail++; console.log('  FAIL', label, detail === undefined ? '' : JSON.stringify(detail).slice(0, 300)); }
}

const a = js.indexOf('const _IMAGE_KEY_PROVIDERS = ');
const b = js.indexOf('// Which container to re-render after a key mutation');
check('cắt được khối Test ảnh', a > 0 && b > a, { a, b });

const W = { calls: [], rendered: 0, els: {}, closed: [] };
const document = {
    getElementById: (id) => W.els[id] || null,
    createElement: () => ({ id: '', className: '', innerHTML: '', classList: { set: new Set(), remove(c) { this.set.delete(c); }, add(c) { this.set.add(c); } } }),
    body: { appendChild: (el) => { W.els[el.id] = el; } },
};
const esc = (s) => String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const T = (k) => k;
let reply = {};
const apiPost = async (url, body) => { W.calls.push({ url, body }); return reply; };
const api = new Function('document', 'esc', 'T', 'apiPost', 'renderCloudApiExt', '_cloudExtBody',
    `${js.slice(a, b)}; return { _IMAGE_KEY_PROVIDERS, _imageTestButton, _imageTestLine, testImageKey, _showImageTestResult };`)(
    document, esc, T, apiPost, () => { W.rendered++; }, () => ({}));

console.log('── 1. nút ──────────────────────────────────────────────');
check('chỉ nhà vẽ được', JSON.stringify(api._IMAGE_KEY_PROVIDERS) === JSON.stringify(['cloudflare', 'gemini', '9router']));
const btn = api._imageTestButton({ provider: 'cloudflare', label: 'ngockhe2004' });
check('Cloudflare có nút, gọi đúng khoá của dòng', btn.includes(`onclick="testImageKey('cloudflare', 'ngockhe2004', this)"`)
    && btn.includes('🖼 cloud_api.test_image') && btn.includes('title="cloud_api.test_image_hint"'), btn);
check('9Router + Gemini có nút', api._imageTestButton({ provider: '9router', label: 'k' }).includes('testImageKey')
    && api._imageTestButton({ provider: 'gemini', label: 'k' }).includes('testImageKey'));
check('OpenAI / DeepSeek KHÔNG có nút', api._imageTestButton({ provider: 'openai', label: 'k' }) === ''
    && api._imageTestButton({ provider: 'deepseek', label: 'k' }) === '');

console.log('── 2. dòng kết quả ─────────────────────────────────────');
const good = api._imageTestLine({ provider: 'cloudflare', image_test: { ok: true, model: '@cf/flux', seconds: 3.4, at: '2026-09-17T10:00:00' } });
check('vẽ được: model + giây, màu xanh', good.includes('🖼 cloud_api.image_ok · @cf/flux · 3.4s') && good.includes('var(--green)')
    && good.includes('title="2026-09-17T10:00:00"'), good);
const bad = api._imageTestLine({ provider: '9router', image_test: { ok: false, message: '9Router HTTP 502: <b>x</b>' } });
check('lỗi: lý do (đã escape), màu đỏ', bad.includes('🖼 cloud_api.image_fail: 9Router HTTP 502: &lt;b&gt;x&lt;/b&gt;') && bad.includes('var(--red)'), bad);
check('chưa thử / nhà không vẽ ảnh → không có dòng', api._imageTestLine({ provider: 'cloudflare' }) === ''
    && api._imageTestLine({ provider: 'openai', image_test: { ok: true } }) === '');

console.log('── 3. bấm Test ảnh ─────────────────────────────────────');
(async () => {
    const button = { disabled: false, innerHTML: '🖼 cloud_api.test_image' };
    reply = { ok: true, model: '@cf/flux', seconds: 2.5, width: 1024, height: 1024, url: '/api/v1/images/file/keytest_cloudflare_ab.png' };
    let seenDuring = null;
    const origPost = apiPost;
    const p = api.testImageKey('cloudflare', 'cf1', button);
    seenDuring = { disabled: button.disabled, text: button.innerHTML };
    await p;
    const modal = W.els['modal-image-key-test'];
    check('đang vẽ: khoá nút + chữ «đang vẽ»', seenDuring.disabled === true && seenDuring.text.includes('cloud_api.test_image_running'), seenDuring);
    check('POST đúng route với đúng khoá', W.calls[0].url === '/api/v1/cloud-api/keys/test-image'
        && JSON.stringify(W.calls[0].body) === JSON.stringify({ provider: 'cloudflare', label: 'cf1' }), W.calls[0]);
    check('xong: mở khoá nút, trả chữ cũ, vẽ lại bảng', button.disabled === false && button.innerHTML === '🖼 cloud_api.test_image' && W.rendered === 1);
    check('hộp kết quả: ảnh vừa vẽ + model · giây · cỡ', modal && !modal.classList.set.has('hidden')
        && modal.innerHTML.includes('<img src="/api/v1/images/file/keytest_cloudflare_ab.png?t=')
        && modal.innerHTML.includes('@cf/flux · 2.5s · 1024×1024') && modal.innerHTML.includes('cloud_api.image_ok'), modal && modal.innerHTML.slice(0, 300));
    reply = { ok: false, model: 'ag/gemini-3.1-flash-image', seconds: 15.4, message: '9Router HTTP 502: error code: 502', url: '' };
    await api.testImageKey('9router', 'nr', null);
    const m2 = W.els['modal-image-key-test'];
    check('lỗi: không có ảnh, hiện lý do', !m2.innerHTML.includes('<img') && m2.innerHTML.includes('9Router HTTP 502: error code: 502')
        && m2.innerHTML.includes('cloud_api.image_fail'), m2.innerHTML.slice(0, 300));
    reply = null;
    await api.testImageKey('gemini', 'g', null);
    check('máy chủ không trả lời → vẫn mở hộp lỗi, không văng', W.els['modal-image-key-test'].innerHTML.includes('cloud_api.image_fail'));

    console.log('── 4. gắn vào bảng + bản dịch ───────────────────────────');
    check('bảng: dòng kết quả trong cột Trạng thái + nút cạnh ▶ Test',
        js.includes('<td>${st}${_imageTestLine(k)}</td>') && js.includes("▶ Test</button>\n                ${_imageTestButton(k)}"));
    check('index.html đổi ?v= để trình duyệt lấy app.js mới', html.includes('/static/app.js?v=39'));
    const KEYS = ['cloud_api.test_image', 'cloud_api.test_image_hint', 'cloud_api.test_image_running', 'cloud_api.test_image_title',
        'cloud_api.image_ok', 'cloud_api.image_fail'];
    for (const lang of ['en', 'vi', 'es', 'ja', 'ko', 'ru', 'tr', 'zh', 'zh-TW']) {
        const loc = JSON.parse(fs.readFileSync(path.join(root, 'cloud_api', 'locales', lang + '.json'), 'utf-8'));
        const miss = KEYS.filter(k => !loc[k]);
        check(`${lang}.json: đủ ${KEYS.length} khoá`, !miss.length, miss);
    }
    const vi = JSON.parse(fs.readFileSync(path.join(root, 'cloud_api', 'locales', 'vi.json'), 'utf-8'));
    check('vi dịch thật', vi['cloud_api.test_image'] === 'Test ảnh' && vi['cloud_api.image_fail'] === 'Vẽ ảnh lỗi');

    console.log();
    console.log(fail ? `${pass}/${pass + fail} PASS — ${fail} HỎNG` : `${pass}/${pass + fail} PASS`);
    process.exit(fail ? 1 : 0);
})();
