// Thêm task video khi đang có video chạy → hỏi: đưa vào hàng đợi hay chạy song song (16/9/2026).
//
// User: "khi tôi add task mới nếu có task đang running thì hiện cảnh báo đưa vào queue hay là làm luồng song song."
// Nút "Tạo video" vốn chạy liền và chen trước hàng đợi, nên hai lượt dựng có thể cùng chạy — chia nhau CPU/RAM/ffmpeg.
//
// Kiểm:
//   1. markup hộp thoại: nhan đề, câu giải thích, ba nút (Huỷ · Chạy song song · Đưa vào hàng đợi)
//   2. laneBusyTask / askLaneChoice / laneChoice chạy THẬT với DOM giả, kể cả đóng hộp bằng X (huỷ)
//   3. submitVideo hỏi TRƯỚC khi gửi, chỉ khi bấm "Tạo video" (nút hàng đợi thì khỏi hỏi)
//   4. bản dịch 9 ngôn ngữ × 5 khoá, đủ chỗ giữ {seq}
//
// Run: node tests/codex_lane_busy_test.js
'use strict';
const fs = require('fs');
const path = require('path');

const dir = path.join(__dirname, '..', 'tubecli', 'extensions', 'codex');
const js = fs.readFileSync(path.join(dir, 'static', 'codex.js'), 'utf-8').replace(/\r\n/g, '\n');
const html = fs.readFileSync(path.join(dir, 'static', 'codex.html'), 'utf-8').replace(/\r\n/g, '\n');
const manager = fs.readFileSync(path.join(dir, 'manager.py'), 'utf-8').replace(/\r\n/g, '\n');

let pass = 0, fail = 0;
function check(label, ok, detail) {
    if (ok) { pass++; console.log('  ok  ', label); }
    else { fail++; console.log('  FAIL', label, detail === undefined ? '' : JSON.stringify(detail).slice(0, 260)); }
}

console.log('── 1. markup ───────────────────────────────────────────');
check('có hộp thoại riêng, đóng được bằng backdrop',
    html.includes('<div class="cx-modal hidden" id="cx-modal-busy" onclick="CODEX.onBackdrop(event,\'cx-modal-busy\')">')
    && html.includes('id="cx-busy-title"') && html.includes('id="cx-busy-hint"'));
const iCancel = html.indexOf("CODEX.laneChoice('')");
const iPar = html.indexOf("CODEX.laneChoice('parallel')");
const iQueue = html.indexOf("CODEX.laneChoice('queue')");
check('ba nút, «Đưa vào hàng đợi» là nút chính đứng cuối (mắt đi từ phải sang)',
    iCancel > 0 && iPar > iCancel && iQueue > iPar
    && html.includes('data-i18n="codex.btn_busy_queue"') && html.includes('data-i18n="codex.btn_busy_parallel"'), { iCancel, iPar, iQueue });
check('nút X cũng đóng hộp', html.includes("onclick=\"CODEX.closeModal('cx-modal-busy')\""));

console.log('── 2. chạy thật với DOM giả ────────────────────────────');
const a = js.indexOf('  /** Task đang giữ làn');
const b = js.indexOf('  /** queue=true: vào hàng đợi');
const c1 = js.indexOf('  function closeModal(id) {');
const c2 = js.indexOf('  function onBackdrop(event, id) {');
check('cắt được khối làn + closeModal', a > 0 && b > a && c1 > 0 && c2 > c1, { a, b, c1, c2 });
const els = {};
const cls = () => ({ set: {}, add(c) { this.set[c] = true; }, remove(c) { this.set[c] = false; }, has(c) { return !!this.set[c]; } });
const el = (id) => (els[id] ||= { id, textContent: '', classList: cls() });
const state = { tasks: [], laneChoice: null };
const tt = (k, p) => k + (p ? JSON.stringify(p) : '');
const API = new Function('$', 't', 'state',
    `${js.slice(a, b)}\n${js.slice(c1, c2)}; return { laneBusyTask, askLaneChoice, laneChoice, closeModal };`)(el, tt, state);

state.tasks = [
    { id: 'a', seq: 1, lane: 'video', status: 'done' },
    { id: 'b', seq: 2, lane: '', status: 'running' },
    { id: 'c', seq: 3, lane: 'video', status: 'backlog' },
    { id: 'd', seq: 7, lane: 'video', status: 'running' },
    { id: 'e', seq: 8, lane: 'video', status: 'queued' },
];
check('tìm task đang giữ làn video: bỏ done/backlog và làn khác', (API.laneBusyTask('video') || {}).id === 'd', API.laneBusyTask('video'));
state.tasks = [{ id: 'e', seq: 8, lane: 'video', status: 'queued' }];
check('chỉ có task queued cũng là làn đang bận', (API.laneBusyTask('video') || {}).id === 'e');
state.tasks = [{ id: 'a', seq: 1, lane: 'video', status: 'review' }, { id: 'b', seq: 2, lane: 'video', status: 'done' }];
check('video nằm ở Review / Done thì làn RẢNH (không giữ hàng)', API.laneBusyTask('video') === undefined, API.laneBusyTask('video'));
check('trạng thái coi là bận khớp LANE_BUSY của manager.py', /LANE_BUSY = \(QUEUED, RUNNING\)/.test(manager)
    && js.includes("x.status === 'running' || x.status === 'queued'"));

(async () => {
    let p = API.askLaneChoice({ seq: 7, status: 'running' });
    check('mở hộp: nhan đề + câu cho task ĐANG DỰNG, kèm số task',
        el('cx-busy-title').textContent === 'codex.modal_busy_title{"seq":7}'
        && el('cx-busy-hint').textContent === 'codex.modal_busy_hint_running{"seq":7}'
        && el('cx-modal-busy').classList.has('hidden') === false, el('cx-busy-hint').textContent);
    API.laneChoice('queue');
    check('bấm «Đưa vào hàng đợi» → trả queue, đóng hộp', await p === 'queue' && el('cx-modal-busy').classList.has('hidden'));

    p = API.askLaneChoice({ seq: 8, status: 'queued' });
    check('task đang CHỜ trong làn → câu khác', el('cx-busy-hint').textContent === 'codex.modal_busy_hint_queued{"seq":8}');
    API.laneChoice('parallel');
    check('bấm «Chạy song song» → trả parallel', await p === 'parallel');

    p = API.askLaneChoice({ seq: 9, status: 'running' });
    API.laneChoice('');
    check('bấm «Huỷ» → trả null (không tạo task)', await p === null);

    p = API.askLaneChoice({ seq: 9, status: 'running' });
    API.closeModal('cx-modal-busy');
    check('đóng bằng X / bấm ra ngoài → cũng trả null, không treo lời gọi đang chờ', await p === null);
    check('sau khi chọn thì quên hàm chờ (không trả lời hai lần)', state.laneChoice === null);

    console.log('── 3. gắn vào submitVideo ──────────────────────────────');
    check('hold đổi được (let) để chuyển sang hàng đợi sau khi hỏi', js.includes('  async function submitVideo(queue) {\n    let hold = queue === true;'));
    check('chỉ hỏi khi bấm "Tạo video" (nút hàng đợi thì thôi)', js.includes("    if (!hold) {\n      const busy = laneBusyTask('video');"));
    check('huỷ → dừng, không gửi; chọn hàng đợi → hold = true',
        js.includes('        const choice = await askLaneChoice(busy);\n        if (!choice) return;\n        hold = choice === \'queue\';'));
    const iAsk = js.indexOf("const choice = await askLaneChoice(busy);");
    const iPost = js.indexOf("request('/api/v1/content-video/run'");
    const iRemember = js.indexOf("const review = !!$('cx-v-review').checked;\n    rememberNewTaskForm();");
    check('hỏi TRƯỚC khi lưu form và gửi API', iAsk > 0 && iAsk < iRemember && iRemember < iPost, { iAsk, iRemember, iPost });
    check('xuất laneChoice cho nút trong HTML', js.includes('onVideoDrive, onVideoDriveToken, onVideoDriveShare, laneChoice,'));
    check('closeModal trả lời hộ khi người dùng đóng hộp',
        js.includes("if (id === 'cx-modal-busy' && state.laneChoice) {"));

    console.log('── 4. bản dịch ────────────────────────────────────────');
    const KEYS = {
        'codex.modal_busy_title': ['{seq}'], 'codex.modal_busy_hint_running': ['{seq}'],
        'codex.modal_busy_hint_queued': ['{seq}'], 'codex.btn_busy_queue': [], 'codex.btn_busy_parallel': [],
    };
    for (const lang of ['en', 'vi', 'es', 'ja', 'ko', 'ru', 'tr', 'zh', 'zh-TW']) {
        const loc = JSON.parse(fs.readFileSync(path.join(dir, 'locales', lang + '.json'), 'utf-8'));
        const bad = Object.entries(KEYS).filter(([k, ph]) => !loc[k] || ph.some(p => !loc[k].includes(p)));
        check(`${lang}.json: đủ 5 khoá + chỗ giữ {seq}`, !bad.length, bad.map(x => x[0]));
    }
    const vi = JSON.parse(fs.readFileSync(path.join(dir, 'locales', 'vi.json'), 'utf-8'));
    check('vi dịch thật, nói rõ vì sao nên xếp hàng',
        vi['codex.btn_busy_queue'] === 'Đưa vào hàng đợi' && vi['codex.btn_busy_parallel'] === 'Chạy song song'
        && vi['codex.modal_busy_hint_running'].includes('RAM'), vi['codex.modal_busy_hint_running']);
    check('tên khoá không mượn chữ backlog (giao diện nói "hàng đợi")',
        !Object.keys(KEYS).some(k => k.includes('backlog')));

    console.log();
    console.log(fail ? `${pass}/${pass + fail} PASS — ${fail} HỎNG` : `${pass}/${pass + fail} PASS`);
    process.exit(fail ? 1 : 0);
})();
