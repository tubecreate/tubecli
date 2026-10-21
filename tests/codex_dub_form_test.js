// Form «Nhiệm vụ mới» (video): ô «Re-dub the narration with Muse» + mô tả giọng (21/10/2026).
//
// User: «chỗ logic lồng giọng bạn để ở phần tạo task đi, template vẫn dùng model theo template». Kiểm:
//   1. codex.html có ô bật/tắt + ô mô tả giọng (ẩn khi tắt), codex.js nhớ lần gần nhất, chỉ gửi options.dub/dub_voice khi bật.
//   2. chạy thật onVideoDub / rememberNewTaskForm với DOM giả.
//   3. 9 ngôn ngữ có đủ 4 khoá.
//
// Run: node tests/codex_dub_form_test.js
'use strict';
const fs = require('fs');
const path = require('path');

const dir = path.join(__dirname, '..', 'tubecli', 'extensions', 'codex');
const js = fs.readFileSync(path.join(dir, 'static', 'codex.js'), 'utf-8').replace(/\r\n/g, '\n');
const html = fs.readFileSync(path.join(dir, 'static', 'codex.html'), 'utf-8').replace(/\r\n/g, '\n');

let pass = 0, fail = 0;
function check(label, ok, detail) {
  if (ok) { pass++; console.log('  ok  ', label); }
  else { fail++; console.log('  FAIL', label, detail === undefined ? '' : JSON.stringify(detail).slice(0, 200)); }
}

console.log('── tĩnh ──');
check('html: ô bật/tắt gọi onVideoDub', html.includes('<input type="checkbox" id="cx-v-dub" onchange="CODEX.onVideoDub()">'));
check('html: ô mô tả giọng ẩn mặc định, tối đa 1500 ký tự',
  html.includes('<div class="cx-field hidden" id="cx-v-dub-wrap">') && /id="cx-v-dub-voice" rows="3" maxlength="1500"/.test(html));
check('html: ô lồng giọng nằm sau ô style ảnh đại diện',
  html.indexOf('id="cx-v-dub"') > html.indexOf('id="cx-v-thumb-style"'));
check('js: khoá nhớ', js.includes("const CV_DUB_KEY = 'codex.cvDub';") && js.includes("const CV_DUB_VOICE_KEY = 'codex.cvDubVoice';"));
check('js: mô tả giọng mặc định = giọng nam chủ kênh chốt', /const CV_DUB_VOICE_DEFAULT = 'Male narrator: warm, calm, mid-range pitch/.test(js)
  && js.includes('1.2-1.5 seconds') && js.includes('second male voice'));
check('js: mở form trả lại lựa chọn + mô tả đã nhớ',
  js.includes("$('cx-v-dub').checked = lsGet(CV_DUB_KEY) === '1';")
  && js.includes("$('cx-v-dub-voice').value = lsGet(CV_DUB_VOICE_KEY) || CV_DUB_VOICE_DEFAULT;"));
const sub = js.indexOf("if (($('cx-v-dub') || {}).checked) {");
check('js: gửi options.dub + dub_voice CHỈ khi bật', sub > 0 && js.indexOf('options.dub = true;', sub) > sub
  && js.indexOf('if (dubVoice) options.dub_voice = dubVoice;', sub) > sub);
check('js: gửi lúc tạo video (cùng chỗ với scene_media)', sub > js.indexOf("options.scene_media = 'stills';"));
check('js: CODEX xuất onVideoDub', /onVideoInstructions, onVideoDub, planFromModal/.test(js));

console.log('── chạy thật ──');
function grab(name) {
  const i = js.indexOf('function ' + name + '(');
  let depth = 0, j = js.indexOf('{', i);
  for (let k = j; k < js.length; k++) {
    if (js[k] === '{') depth++;
    else if (js[k] === '}') { depth--; if (!depth) return js.slice(i, k + 1); }
  }
  return '';
}
const store = {};
const els = {
  'cx-v-dub': { checked: true },
  'cx-v-dub-voice': { value: '' },
  'cx-v-dub-wrap': { hidden: true, classList: { toggle(c, on) { els['cx-v-dub-wrap'].hidden = on; } } },
};
const consts = js.slice(js.indexOf("const CV_DUB_KEY"), js.indexOf("'story and talking to the listener, not reading a text.';") + 58);
const fn = new Function('$', 'lsSet', consts + '\n' + grab('onVideoDub') + '\nreturn { onVideoDub, CV_DUB_VOICE_DEFAULT };');
const api = fn((id) => els[id], (k, v) => { store[k] = v; });
api.onVideoDub();
check('bật → hiện ô mô tả, điền mô tả mặc định khi trống', els['cx-v-dub-wrap'].hidden === false
  && els['cx-v-dub-voice'].value === api.CV_DUB_VOICE_DEFAULT, els['cx-v-dub-voice'].value.slice(0, 40));
els['cx-v-dub-voice'].value = 'my own voice';
els['cx-v-dub'].checked = false;
api.onVideoDub();
check('tắt → ẩn ô mô tả, giữ chữ người dùng đã sửa', els['cx-v-dub-wrap'].hidden === true && els['cx-v-dub-voice'].value === 'my own voice');

console.log('── 9 ngôn ngữ ──');
const keys = ['codex.field_video_dub', 'codex.field_video_dub_hint', 'codex.field_video_dub_voice',
  'codex.field_video_dub_voice_placeholder'];
for (const lang of ['en', 'vi', 'ja', 'zh', 'zh-TW', 'ko', 'es', 'ru', 'tr']) {
  const d = JSON.parse(fs.readFileSync(path.join(dir, 'locales', lang + '.json'), 'utf-8'));
  check(lang + ': đủ 4 khoá', keys.every((k) => typeof d[k] === 'string' && d[k].trim()), keys.filter((k) => !d[k]));
}
const en = JSON.parse(fs.readFileSync(path.join(dir, 'locales', 'en.json'), 'utf-8'));
check('en: chữ hiện trùng chữ mặc định trong html', html.includes(en['codex.field_video_dub'])
  && html.includes(en['codex.field_video_dub_voice']));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
