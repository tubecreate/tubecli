// Ô ảnh của form loại việc do extension khai (Pod Studio «Video from reference images»): chọn MẪU → ảnh nhân vật có sẵn
// của mẫu hiện trong ô, xoá từng ảnh, thêm file thì CỘNG vào, đổi mẫu thì thay ảnh của mẫu cũ (giữ ảnh tự thêm); gửi ảnh
// có sẵn nguyên {url, filepath}, chỉ file mới được tải lên. User 6/11/2026. Chạy: node tests/codex_ext_template_images_test.js
const fs = require('fs');
const path = require('path');
const dir = path.join(__dirname, '..', 'tubecli', 'extensions', 'codex');
const js = fs.readFileSync(path.join(dir, 'static', 'codex.js'), 'utf8');
const css = fs.readFileSync(path.join(dir, 'static', 'codex.css'), 'utf8');
let pass = 0, fail = 0;
function check(name, cond, info) { if (cond) { pass++; console.log('  ok  ', name); } else { fail++; console.log('  FAIL', name, info === undefined ? '' : JSON.stringify(info).slice(0, 300)); } }
function grab(name, src) {
  src = src || js;
  const i = src.indexOf((name.startsWith('async ') ? '' : 'function ') + name + '(');
  if (i < 0) return '';
  let depth = 0;
  const j = src.indexOf('{', src.indexOf(')', i));
  for (let k = j; k < src.length; k++) {
    if (src[k] === '{') depth++;
    else if (src[k] === '}') { depth--; if (!depth) return src.slice(i, k + 1); }
  }
  return '';
}

// ── môi trường giả: File, DOM tối thiểu, t(), toast() ────────────────────────────────────────────────────────────────
class FakeFile { constructor(name, size) { this.name = name; this.size = size; } }
const els = {};
function el(id, props) { els[id] = Object.assign({ id, value: '', innerHTML: '', type: 'text' }, props || {}); return els[id]; }
el('cx-x-template', { type: 'select-one', value: 'POD · Girl' });
el('cx-x-model_images', { type: 'file' });
el('cx-x-model_images-p');
el('cx-x-format', { type: 'select-one', value: 'ad' });
const toasts = [];
const ls = {};
const state = {
  extFiles: {}, extOpts: {},
  extKind: { id: 'pod', template_field: 'template', fields: [
    { key: 'template', type: 'select' }, { key: 'model_images', type: 'images', max: 3, required: true },
    { key: 'format', type: 'select' }] },
};
const env = {
  $: (id) => els[id], state, lsSet: (k, v) => { ls[k] = v; }, EXT_LS: (a, b) => a + ':' + b,
  extFieldId: (k) => 'cx-x-' + String(k).replace(/[^\w-]/g, '_'),
  t: (k, p) => k + (p ? JSON.stringify(p) : ''), esc: (s) => String(s), toast: (m, kind) => toasts.push([m, kind]),
  URL: { createObjectURL: (f) => 'blob:' + f.name }, File: FakeFile,
};
const names = Object.keys(env);
const code = ['applyExtImageFills', 'applyExtFills', 'onExtFiles', 'renderExtImages', 'removeExtImage'].map((n) => grab(n)).join('\n');
check('codex.js has the image-fill helpers', code.includes('function applyExtImageFills') && code.includes('function removeExtImage'));
const api = new Function(...names, code + '\nreturn { applyExtImageFills, applyExtFills, onExtFiles, removeExtImage };')(...names.map((n) => env[n]));

const GIRL = { format: 'short', model_images: [{ url: '/m/0', filepath: 'C:/t/m0.png', name: 'm0' }, { url: '/m/2', filepath: 'C:/t/m2.png', name: 'm2' }] };
const NEWS = { format: 'ad', model_images: [] };
const DRAGON = { model_images: [{ url: '/c/maren', filepath: 'C:/c/maren.png', name: 'Maren' }] };

api.applyExtFills(GIRL);
let list = state.extFiles.model_images || [];
check('choosing a template shows its characters', list.length === 2 && list.every((x) => x.preset) && list[0].url === '/m/0', list);
check('…and the other fields still fill', els['cx-x-format'].value === 'short');
check('previews have a remove button per image', (els['cx-x-model_images-p'].innerHTML.match(/cx-x-thumb-del/g) || []).length === 2,
  els['cx-x-model_images-p'].innerHTML.slice(0, 200));
check('template photos are marked in the preview', els['cx-x-model_images-p'].innerHTML.includes('is-preset'));

api.removeExtImage('model_images', 0);
list = state.extFiles.model_images;
check('remove one template photo', list.length === 1 && list[0].url === '/m/2', list);

const inp = Object.assign(els['cx-x-model_images'], { files: [new FakeFile('me.jpg', 10)], value: 'C:\\fakepath\\me.jpg' });
api.onExtFiles('model_images', inp);
list = state.extFiles.model_images;
check('adding a file APPENDS to the template photos', list.length === 2 && list[1] instanceof FakeFile, list);
check('the file input is cleared so the same file can be picked again', inp.value === '');
inp.files = [new FakeFile('me.jpg', 10)];
api.onExtFiles('model_images', inp);
check('the same file is not added twice', state.extFiles.model_images.length === 2);
inp.files = [new FakeFile('a.jpg', 1), new FakeFile('b.jpg', 2)];
api.onExtFiles('model_images', inp);
check('capped at the field max (3) with a warning', state.extFiles.model_images.length === 3
  && toasts.some(([m, k]) => m.startsWith('codex.ext_images_max') && k === 'error'), [state.extFiles.model_images.length, toasts]);

api.applyExtFills(DRAGON);
list = state.extFiles.model_images;
check('switching template replaces the old template photos, keeps own files',
  list.length === 3 && list[0].url === '/c/maren' && list.slice(1).every((x) => x instanceof FakeFile), list);
api.applyExtFills(NEWS);
list = state.extFiles.model_images;
check('a template without characters removes the template photos only', list.length === 2 && list.every((x) => x instanceof FakeFile), list);
api.removeExtImage('model_images', 0); api.removeExtImage('model_images', 0);
check('empty list shows the pick hint again', els['cx-x-model_images-p'].innerHTML.startsWith('<span class="cx-field-meta">codex.ext_images_pick'));

// ── gửi: ảnh có sẵn đi nguyên, file mới mới tải lên ─────────────────────────────────────────────────────────────────
const submit = grab('async function submitExt'.replace('async function ', 'async ')) || js.slice(js.indexOf('async function submitExt('), js.indexOf('/** {tên: preset} của Content Studio'));
check('submit: template photos are sent without uploading', /if \(file && file\.preset\) \{[\s\S]{0,200}out\.push\(\{ url: file\.url \|\| '', filepath: file\.filepath \|\| ''/.test(submit));
check('submit: the upload counter counts only new files', submit.includes(".filter(x => !(x && x.preset)).length"));
check('open form: a remembered template re-fills its photos', js.includes('if (tplOpt && tplOpt.fills) applyExtImageFills(tplOpt.fills);'));
check('CODEX exports removeExtImage (inline onclick)', /onVideoVoiceFile, removeExtImage,/.test(js));
check('css: thumb + remove button styles', css.includes('.cx-x-thumb-del') && css.includes('.cx-x-thumb.is-preset'));

for (const lang of ['en', 'vi', 'es', 'ja', 'ko', 'ru', 'tr', 'zh', 'zh-TW']) {
  const L = JSON.parse(fs.readFileSync(path.join(dir, 'locales', lang + '.json'), 'utf8'));
  check(lang + ': 3 new strings', ['codex.ext_images_from_template', 'codex.ext_images_remove', 'codex.ext_images_max'].every((k) => String(L[k] || '').trim())
    && L['codex.ext_images_max'].includes('{n}') && L['codex.ext_images_from_template'].includes('{name}'));
}
console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
