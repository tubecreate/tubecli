// Dòng báo «Hàng đợi Video đang tạm dừng (hết quota)» trên bảng Codex + nút «Tiếp tục ngay» (17/9/2026).
//
// User: "đối với video luồng hết quota không tạo được video thì tạm dừng tất cả các luồng đợi xử lý".
//
// Run: node tests/codex_lane_pause_ui_test.js
'use strict';
const fs = require('fs');
const path = require('path');

const dir = path.join(__dirname, '..', 'tubecli', 'extensions', 'codex');
const js = fs.readFileSync(path.join(dir, 'static', 'codex.js'), 'utf-8').replace(/\r\n/g, '\n');
const html = fs.readFileSync(path.join(dir, 'static', 'codex.html'), 'utf-8');
const css = fs.readFileSync(path.join(dir, 'static', 'codex.css'), 'utf-8');

let pass = 0, fail = 0;
function check(label, ok, detail) {
    if (ok) { pass++; console.log('  ok  ', label); }
    else { fail++; console.log('  FAIL', label, detail === undefined ? '' : JSON.stringify(detail).slice(0, 300)); }
}

const a = js.indexOf('  function pauseClock(until) {');
const b = js.indexOf('  /** Drop cached events for tasks that no longer exist. */');
check('cắt được khối tạm dừng làn', a > 0 && b > a, { a, b });

const box = { innerHTML: '', classList: { set: new Set(['hidden']), add(c) { this.set.add(c); }, remove(c) { this.set.delete(c); } } };
const W = { calls: [], toasts: [], refreshed: 0, fail: false };
const LOC = { 'codex.lane_video': 'Video', 'codex.lane_paused_title': 'Hàng đợi {lane} đang tạm dừng (hết quota)',
    'codex.lane_paused_until': 'tự chạy lại lúc {time}', 'codex.lane_paused_manual': 'tới khi bạn bấm tiếp tục',
    'codex.lane_resume': 'Tiếp tục ngay', 'codex.toast_lane_resumed': 'Đã chạy lại hàng đợi', 'codex.toast_action_failed': 'Lỗi: {error}' };
const t = (k, p) => { let s = LOC[k] || k; Object.entries(p || {}).forEach(([x, v]) => { s = s.replace('{' + x + '}', v); }); return s; };
const esc = (s) => String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
const state = { lanePauses: {} };
const api = async (p, o) => { W.calls.push({ p, o }); if (W.fail) throw new Error('boom'); return { ok: true }; };
const fns = new Function('$', 't', 'esc', 'icon', 'state', 'api', 'toast', 'refresh',
    `${js.slice(a, b)}; return { pauseClock, renderLanePauses, resumeLane };`)(
    (id) => (id === 'cx-lane-pauses' ? box : null), t, esc, (n) => `<i>${n}</i>`, state, api,
    (m, k) => W.toasts.push([m, k]), async () => { W.refreshed++; });

(async () => {
    fns.renderLanePauses();
    check('không làn nào dừng → ẩn', box.classList.set.has('hidden') && box.innerHTML === '');
    const until = Date.UTC(2026, 8, 18, 0, 0) / 1000;
    state.lanePauses = { video: { lane: 'video', until, reason: 'Generate shot images: 5/177 shot(s) not drawn — HTTP 429 <x>' } };
    fns.renderLanePauses();
    const d = new Date(until * 1000);
    const pad = n => String(n).padStart(2, '0');
    const clock = `${pad(d.getHours())}:${pad(d.getMinutes())} ${pad(d.getDate())}/${pad(d.getMonth() + 1)}`;
    check('hiện: tên làn dịch, giờ tự chạy lại theo giờ máy, lý do đã escape',
        !box.classList.set.has('hidden') && box.innerHTML.includes(`Hàng đợi Video đang tạm dừng (hết quota) · tự chạy lại lúc ${clock}`)
        && box.innerHTML.includes('HTTP 429 &lt;x&gt;'), box.innerHTML);
    check('nút «Tiếp tục ngay» gọi đúng làn', box.innerHTML.includes(`onclick="CODEX.resumeLane('video')"`) && box.innerHTML.includes('Tiếp tục ngay'));
    state.lanePauses = { other: { lane: 'other', until: null, reason: '' } };
    fns.renderLanePauses();
    check('làn chưa có tên dịch + không hạn → tên gốc, «tới khi bạn bấm tiếp tục»',
        box.innerHTML.includes('Hàng đợi other đang tạm dừng (hết quota) · tới khi bạn bấm tiếp tục'), box.innerHTML);
    await fns.resumeLane('video');
    check('bấm tiếp tục: POST /lanes/video/resume, báo, tải lại bảng',
        W.calls[0].p === '/lanes/video/resume' && W.calls[0].o.method === 'POST'
        && W.toasts[0][0] === 'Đã chạy lại hàng đợi' && W.refreshed === 1, { calls: W.calls, toasts: W.toasts });
    W.fail = true;
    await fns.resumeLane('video');
    check('lỗi → báo lỗi, vẫn tải lại', W.toasts[1][0] === 'Lỗi: boom' && W.toasts[1][1] === 'error' && W.refreshed === 2, W.toasts);

    check('refresh đọc lane_pauses + vẽ dòng báo', js.includes('state.lanePauses = payload.lane_pauses || {};')
        && js.includes('    renderStats();\n    renderLanePauses();'));
    check('xuất resumeLane ra CODEX', js.includes('syncThenDelete, resumeLane,'));
    check('codex.html có ô dòng báo (ẩn sẵn) dưới ô thống kê',
        html.includes('<section class="cx-lane-pauses hidden" id="cx-lane-pauses" aria-live="polite"></section>')
        && html.indexOf('id="cx-lane-pauses"') > html.indexOf('id="cx-stats"'));
    check('CSS tông cam cảnh báo', /\.cx-pause \{[^}]*--cx-orange/.test(css));
    const KEYS = Object.keys(LOC).filter(k => k !== 'codex.toast_action_failed');
    for (const lang of ['en', 'vi', 'es', 'ja', 'ko', 'ru', 'tr', 'zh', 'zh-TW']) {
        const loc = JSON.parse(fs.readFileSync(path.join(dir, 'locales', lang + '.json'), 'utf-8'));
        const bad = KEYS.filter(k => !loc[k]);
        check(`${lang}.json: đủ ${KEYS.length} khoá, giữ chỗ {lane}/{time}`, !bad.length
            && loc['codex.lane_paused_title'].includes('{lane}') && loc['codex.lane_paused_until'].includes('{time}'), bad);
    }
    console.log();
    console.log(fail ? `${pass}/${pass + fail} PASS — ${fail} HỎNG` : `${pass}/${pass + fail} PASS`);
    process.exit(fail ? 1 : 0);
})();
