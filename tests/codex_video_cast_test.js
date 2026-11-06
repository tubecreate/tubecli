// Ô «Characters» của form video Content Studio (Codex, 6/11/2026): chọn mẫu → dàn nhân vật (wizCast) hiện sẵn bằng sheet của
// kho nhân vật ĐÚNG style của mẫu; xoá ✕; thêm từ kho; options.cast chỉ gửi khi người dùng đổi dàn. Chạy: node tests/codex_video_cast_test.js
const fs = require('fs');
const path = require('path');
const dir = path.join(__dirname, '..', 'tubecli', 'extensions', 'codex');
const js = fs.readFileSync(path.join(dir, 'static', 'codex.js'), 'utf8');
const html = fs.readFileSync(path.join(dir, 'static', 'codex.html'), 'utf8');
let pass = 0, fail = 0;
function check(name, cond, info) { if (cond) { pass++; console.log('  ok  ', name); } else { fail++; console.log('  FAIL', name, info === undefined ? '' : JSON.stringify(info).slice(0, 300)); } }
function grab(name) {
  const i = js.indexOf(name + '(');
  const j = js.indexOf('{', js.indexOf(')', i));
  let depth = 0;
  for (let k = j; k < js.length; k++) {
    if (js[k] === '{') depth++;
    else if (js[k] === '}') { depth--; if (!depth) return js.slice(js.lastIndexOf('\n', i) + 1, k + 1); }
  }
  return '';
}

const els = {};
function el(id, props) { els[id] = Object.assign({ id, value: '', innerHTML: '', disabled: false,
  classList: { _h: true, toggle(c, on) { this._h = on; }, add() { this._h = true; } } }, props || {}); return els[id]; }
el('cx-v-cast-wrap'); el('cx-v-cast'); el('cx-v-cast-pick'); el('cx-v-preset', { value: 'Dragon' });
const state = { presets: {
  Dragon: { wizStyle: 'Dark Fantasy Epic', wizCast: 'maren, rhosyn' },
  News: { wizStyle: 'Cartoon News Recap', wizCast: '' },
} };
const LIB = [{ slug: 'maren', name: 'Maren', sheet_url: '/s/maren' }, { slug: 'rhosyn', name: 'Rhosyn', sheet_url: '/s/rhosyn' },
  { slug: 'kael', name: 'Kael', sheet_url: '/s/kael' }];
const asked = [];
const env = { $: (id) => els[id], state, t: (k, p) => k + (p ? JSON.stringify(p) : ''), esc: (s) => String(s),
  request: async (u) => { asked.push(u); return { characters: u.includes('Dark%20Fantasy') ? LIB : [] }; } };
const names = Object.keys(env);
const code = ['function castSlugs', 'async function loadVideoCast', 'function renderVideoCast', 'function removeVideoCast',
  'function onVideoCastPick', 'function videoCastOption'].map(grab).join('\n');
check('codex.js has the cast helpers', code.includes('async function loadVideoCast') && code.includes('function videoCastOption'));
const api = new Function(...names, code + '\nreturn { loadVideoCast, removeVideoCast, onVideoCastPick, videoCastOption };')(...names.map((n) => env[n]));

(async () => {
  await api.loadVideoCast('Dragon');
  check('asks the character library of the template\'s style', asked[0] === '/api/v1/characters?style=Dark%20Fantasy%20Epic', asked);
  check('the field is shown', els['cx-v-cast-wrap'].classList._h === false);
  const box = els['cx-v-cast'].innerHTML;
  check('both cast members with their sheets', box.includes('/s/maren') && box.includes('/s/rhosyn') && box.includes('<em>Maren</em>'), box.slice(0, 200));
  check('each one has a remove button', (box.match(/cx-x-thumb-del/g) || []).length === 2);
  check('the picker lists only characters not in the cast', els['cx-v-cast-pick'].innerHTML.includes('value="kael"')
    && !els['cx-v-cast-pick'].innerHTML.includes('value="maren"'));
  check('unchanged cast → no options.cast (the template decides)', api.videoCastOption() === null);
  api.removeVideoCast(1);
  check('remove one → options.cast = the rest', JSON.stringify(api.videoCastOption()) === '["maren"]', api.videoCastOption());
  els['cx-v-cast-pick'].value = 'kael';
  api.onVideoCastPick();
  check('add from the library', JSON.stringify(api.videoCastOption()) === '["maren","kael"]', api.videoCastOption());
  api.removeVideoCast(0); api.removeVideoCast(0);
  check('remove everyone → options.cast = [] (no fixed characters)', JSON.stringify(api.videoCastOption()) === '[]');
  check('empty cast shows the hint', els['cx-v-cast'].innerHTML.includes('codex.cv_cast_none'));
  els['cx-v-preset'].value = 'News';
  check('switching template without reloading → no stale cast is sent', api.videoCastOption() === null);
  await api.loadVideoCast('News');
  check('template without cast → empty list, still editable', els['cx-v-cast-wrap'].classList._h === false
    && els['cx-v-cast'].innerHTML.includes('codex.cv_cast_none'));

  check('html: Characters field under the template summary', html.indexOf('id="cx-v-cast-wrap"') > html.indexOf('id="cx-v-summary"'));
  check('submit sends options.cast only when changed', /const castOpt = videoCastOption\(\);\s*if \(castOpt\) options\.cast = castOpt;/.test(js));
  check('new character from a photo → POST /api/v1/characters in the template\'s style',
    /request\('\/api\/v1\/characters', \{ method: 'POST',[\s\S]{0,140}style: cv\.style/.test(js));
  check('CODEX exports the cast handlers', /removeVideoCast, onVideoCastPick, onVideoCastFile,/.test(js));
  for (const lang of ['en', 'vi', 'es', 'ja', 'ko', 'ru', 'tr', 'zh', 'zh-TW']) {
    const L = JSON.parse(fs.readFileSync(path.join(dir, 'locales', lang + '.json'), 'utf8'));
    const keys = ['codex.field_video_cast', 'codex.field_video_cast_hint', 'codex.cv_cast_upload', 'codex.cv_cast_add',
      'codex.cv_cast_none', 'codex.cv_cast_name', 'codex.cv_cast_added'];
    check(lang + ': 7 cast strings', keys.every((k) => String(L[k] || '').trim()) && L['codex.cv_cast_added'].includes('{name}'));
  }
  console.log(`\n${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})();
