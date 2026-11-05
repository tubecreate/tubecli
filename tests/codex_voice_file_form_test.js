// Ô «File giọng của bạn» trong form video của Codex (5/11/2026): chọn file → tải lên /api/v1/content-video/voice-file →
// gửi options.voice_file (lời nguyên văn, không TTS). Kiểm tĩnh HTML / JS / 9 locale. Chạy: node tests/codex_voice_file_form_test.js
const fs = require('fs');
const path = require('path');
const D = path.join(__dirname, '..', 'tubecli', 'extensions', 'codex');
const html = fs.readFileSync(path.join(D, 'static', 'codex.html'), 'utf8');
const js = fs.readFileSync(path.join(D, 'static', 'codex.js'), 'utf8');
let pass = 0, fail = 0;
function check(name, cond) { if (cond) { pass++; console.log('  ok  ', name); } else { fail++; console.log('  FAIL', name); } }

check('html: file input for the voice, audio only', /id="cx-v-voice"[^>]*accept="audio\/\*/.test(html.replace(/\s+/g, ' ')));
check('html: the field sits right after the content box', html.indexOf('id="cx-v-voice-wrap"') > html.indexOf('id="cx-v-count"')
  && html.indexOf('id="cx-v-voice-wrap"') < html.indexOf('id="cx-v-split-wrap"'));
check('js: uploads to the content-video voice-file route', js.includes("fetch('/api/v1/content-video/voice-file'"));
check('js: sends voice_file + verbatim', /options\.voice_file = state\.voiceFile\.path;\s*options\.script_mode = 'verbatim';/.test(js));
check('js: drops Muse re-dub when a file is given', /if \(state\.voiceFile\) \{[\s\S]{0,400}delete options\.dub;/.test(js));
check('js: waits for an upload in progress', js.includes("toast(t('codex.toast_voice_wait'), 'error');"));
check('js: one voice file = one video (no link batch)', js.includes("t('codex.toast_voice_one_video')"));
check('js: the form reset clears the chosen file', /\$\('cx-v-content'\)\.value = '';\s*resetVoiceFile\(\);/.test(js));
check('js: CODEX exports onVideoVoiceFile', /planFromModal, onVideoVoiceFile,/.test(js));

const KEYS = ['codex.field_video_voice_file', 'codex.field_video_voice_file_hint', 'codex.cv_voice_uploading',
  'codex.cv_voice_ready', 'codex.toast_voice_upload_failed', 'codex.toast_voice_wait', 'codex.toast_voice_one_video'];
for (const lang of ['en', 'vi', 'es', 'ja', 'ko', 'ru', 'tr', 'zh', 'zh-TW']) {
  const L = JSON.parse(fs.readFileSync(path.join(D, 'locales', lang + '.json'), 'utf8'));
  const missing = KEYS.filter(k => !String(L[k] || '').trim());
  check(`locale ${lang}: all 7 voice-file strings`, !missing.length);
  check(`locale ${lang}: placeholders kept`, L['codex.cv_voice_ready'].includes('{name}') && L['codex.cv_voice_ready'].includes('{dur}')
    && L['codex.toast_voice_upload_failed'].includes('{msg}'));
}
console.log(`${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
