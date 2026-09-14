// Codex «Nhiệm vụ mới» nhớ trọn cài đặt lần gửi gần nhất (14/9/2026).
//
// User: "nhớ lần gần nhất setup không phải chỉnh lại mỗi lần thêm mới". Form đã nhớ loại việc,
// mẫu, agent, độ dài, chế độ kịch bản; ô «Duyệt kịch bản trước khi dựng» thì bị tick lại mỗi
// lần mở, bên «Việc chung» người nhận / duyệt kế hoạch / ưu tiên cũng bị đặt lại.
//
// Kiểm:
//   1. codex.js: có 4 khoá mới; openNewTask trả lại từ localStorage thay vì hằng số; gửi (cả
//      việc chung lẫn video) thì lưu; người nhận chọn lại sau khi danh sách nạp xong.
//   2. chạy thật rememberNewTaskForm / pickSaved với DOM giả.
//
// Run: node tests/codex_form_memory_test.js
'use strict';
const fs = require('fs');
const path = require('path');

const dir = path.join(__dirname, '..', 'tubecli', 'extensions', 'codex', 'static');
const js = fs.readFileSync(path.join(dir, 'codex.js'), 'utf-8').replace(/\r\n/g, '\n');

let pass = 0, fail = 0;
function check(label, ok, detail) {
    if (ok) { pass++; console.log('  ok  ', label); }
    else { fail++; console.log('  FAIL', label, detail === undefined ? '' : JSON.stringify(detail).slice(0, 200)); }
}

console.log('── tĩnh ────────────────────────────────────────────────');
for (const k of ["const CV_REVIEW_KEY = 'codex.cvReview';", "const G_ASSIGNEE_KEY = 'codex.gAssignee';",
                 "const G_APPROVAL_KEY = 'codex.gApproval';", "const G_PRIORITY_KEY = 'codex.gPriority';"]) {
    check('khoá: ' + k.slice(6, 24), js.includes(k));
}
check('mở form: ưu tiên lấy từ bộ nhớ', js.includes("$('cx-f-priority').value = String(parseInt(lsGet(G_PRIORITY_KEY), 10) || 0);") && !js.includes("$('cx-f-priority').value = '0';"));
check('mở form: duyệt kế hoạch lấy từ bộ nhớ (mặc định bật)', js.includes("$('cx-f-approval').checked = lsGet(G_APPROVAL_KEY) !== '0';") && !js.includes("$('cx-f-approval').checked = true;"));
check('mở form: duyệt kịch bản lấy từ bộ nhớ (mặc định bật)', js.includes("$('cx-v-review').checked = lsGet(CV_REVIEW_KEY) !== '0';") && !js.includes("$('cx-v-review').checked = true;"));
check('người nhận: chọn lại SAU khi danh sách nạp', js.includes("sel.innerHTML += groups.join('');\n    pickSaved(sel, lsGet(G_ASSIGNEE_KEY));"));
const gi = js.indexOf("const assigneeId = sep > 0 ? raw.slice(sep + 1) : '';\n    rememberNewTaskForm();");
const vi = js.indexOf("const review = !!$('cx-v-review').checked;\n    rememberNewTaskForm();");
check('gửi việc chung → lưu', gi > 0);
check('gửi video (Tạo / Đưa vào hàng đợi) → lưu', vi > 0);
check('lưu TRƯỚC khi gọi API (huỷ giữa chừng vẫn nhớ)', gi > 0 && js.indexOf("api('/tasks', { method: 'POST'", gi) > gi);

console.log('── chạy thật với DOM giả ───────────────────────────────');
const a = js.indexOf('  function rememberNewTaskForm() {');
const b = js.indexOf('  function lsGet(k) {');
check('cắt được rememberNewTaskForm/pickSaved', a > 0 && b > a, { a, b });
const store = {};
const els = {
    'cx-f-assignee': { value: 'team:t1', options: [{ value: '' }, { value: 'agent:a1' }, { value: 'team:t1' }] },
    'cx-f-approval': { checked: false },
    'cx-f-priority': { value: '7' },
    'cx-v-review': { checked: false },
};
const stubs = {
    G_ASSIGNEE_KEY: 'codex.gAssignee', G_APPROVAL_KEY: 'codex.gApproval', G_PRIORITY_KEY: 'codex.gPriority', CV_REVIEW_KEY: 'codex.cvReview',
    $: (id) => els[id],
    lsGet: k => store[k] || '',
    lsSet: (k, v) => { store[k] = v; },
};
const api = new Function(...Object.keys(stubs), `${js.slice(a, b)}; return { rememberNewTaskForm, pickSaved };`)(...Object.values(stubs));
api.rememberNewTaskForm();
check('lưu đúng 4 giá trị (bỏ tick = "0")', store['codex.gAssignee'] === 'team:t1' && store['codex.gApproval'] === '0' && store['codex.gPriority'] === '7' && store['codex.cvReview'] === '0', store);
els['cx-f-priority'].value = 'abc';
api.rememberNewTaskForm();
check('ưu tiên không phải số → 0', store['codex.gPriority'] === '0');
const sel = { value: '', options: [{ value: '' }, { value: 'agent:a1' }] };
check('pickSaved: còn trong danh sách → chọn', api.pickSaved(sel, 'agent:a1') === true && sel.value === 'agent:a1');
check('pickSaved: agent đã bị xoá → giữ nguyên, trả false', api.pickSaved(sel, 'agent:gone') === false && sel.value === 'agent:a1');
check('pickSaved: chưa nhớ gì → false, không đụng ô', api.pickSaved({ value: 'x', options: [] }, '') === false);

console.log();
console.log(fail ? `${pass}/${pass + fail} PASS — ${fail} HỎNG` : `${pass}/${pass + fail} PASS`);
process.exit(fail ? 1 : 0);
