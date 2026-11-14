// Bảng XEM TRƯỚC của form «Tạo video từ nội dung» (14/11/2026) — mối nối giao diện.
//   1. Nút Xem trước / Quay lại ở dòng tiêu đề; Xem trước chỉ hiện với video; CSS đổi bộ nút theo bước.
//   2. previewVideo đi qua ĐÚNG submitVideo (cờ state.videoPreview, queue=true để khỏi hỏi làn) và dừng TRƯỚC khi gửi /run.
//   3. showVideoReview gọi /preview + /preview/check; kết quả của lần mở cũ bị bỏ (reviewSeq); 404 → câu «cập nhật».
//   4. Tạo xong thì ẩn bảng; mở lại hộp thì về form.
//   5. Khoá dịch đủ 9 ngôn ngữ, giữ {n} / {what}.
// Chạy: node tests/codex_video_preview_ui_test.js   (exit 0 = pass)
const fs = require('fs');
const path = require('path');

const dir = path.join(__dirname, '..', 'tubecli', 'extensions', 'codex');
const js = fs.readFileSync(path.join(dir, 'static', 'codex.js'), 'utf-8');
const html = fs.readFileSync(path.join(dir, 'static', 'codex.html'), 'utf-8');
const css = fs.readFileSync(path.join(dir, 'static', 'codex.css'), 'utf-8');
let pass = 0, fail = 0;
function check(name, cond, info) {
  if (cond) { pass++; console.log('  ok  ', name); } else { fail++; console.log('  FAIL', name, info === undefined ? '' : JSON.stringify(info).slice(0, 300)); }
}

console.log('── 1. nút + bước ─────────────────────────────────────────');
const head = html.slice(html.indexOf('id="cx-modal-new"'), html.indexOf('id="cx-new-step-form"'));
check('Quay lại, Huỷ, Xem trước, hàng đợi, Tạo đều ở dòng tiêu đề',
  ['cx-review-back', 'cx-new-cancel', 'cx-preview-btn', 'cx-queue-btn', 'cx-create-btn'].every(id => head.includes(`id="${id}"`)));
const pbtn = (html.match(/<button[^>]*id="cx-preview-btn"[\s\S]*?<\/button>/) || [''])[0];
check('Xem trước ẩn mặc định, gọi CODEX.previewVideo()', /class="[^"]*\bhidden\b/.test(pbtn) && pbtn.includes('onclick="CODEX.previewVideo()"'));
check('Quay lại gọi CODEX.backFromReview()', head.includes('onclick="CODEX.backFromReview()"'));
check('bước xem trước có khung kiểm + thông số + các bước',
  ['cx-new-step-review', 'cx-rv-checks', 'cx-rv-rows', 'cx-rv-steps', 'cx-rv-warn'].every(id => html.includes(`id="${id}"`)));
check('setNewKind: Xem trước chỉ với video', js.includes("$('cx-preview-btn').classList.toggle('hidden', !video);"));
check('CSS: bước xem trước hiện Quay lại, giấu Huỷ + Xem trước',
  css.includes('#cx-modal-new:has(#cx-new-step-review:not(.hidden)) #cx-review-back { display: inline-flex; }')
  && css.includes('#cx-modal-new:has(#cx-new-step-review:not(.hidden)) #cx-new-cancel,')
  && css.includes('#cx-modal-new:has(#cx-new-step-review:not(.hidden)) #cx-preview-btn { display: none; }'));
check('CSS: bộ nút chỉ ẩn ở bước «đã tạo» (bước xem trước vẫn có nút Tạo)',
  css.includes('#cx-modal-new:has(#cx-new-step-done:not(.hidden)) #cx-new-actions { display: none; }')
  && !css.includes('#cx-modal-new:has(#cx-new-step-form.hidden) #cx-new-actions'));

console.log('── 2. đi qua submitVideo ─────────────────────────────────');
const pv = js.slice(js.indexOf('async function previewVideo('), js.indexOf('function backFromReview('));
check('previewVideo: cờ + submitVideo(true) + luôn tắt cờ', pv.includes('state.videoPreview = true;')
  && pv.includes('await submitVideo(true);') && pv.includes('finally { state.videoPreview = false; }'));
const sv = js.slice(js.indexOf('async function submitVideo('), js.indexOf('async function planFromModal('));
const iHook = sv.indexOf('if (state.videoPreview) {');
check('chặn ở SAU khi gom xong options (cả YouTube) và TRƯỚC khi gửi /run',
  iHook > sv.indexOf('if (yt) Object.assign(options, yt);') && iHook < sv.indexOf("request('/api/v1/content-video/run'")
  && iHook < sv.indexOf("const btns = [$('cx-create-btn'), $('cx-queue-btn')];"));
check('gửi đúng thân /run (agent, nội dung, duyệt, options) + tên file giọng gốc',
  sv.includes('showVideoReview({ agent_id: agentId, content: batch[0], review: review, options: options,')
  && sv.includes("voice_name: state.voiceFile ? (state.voiceFile.name || '') : '' }, batch.length);"));

console.log('── 3. bảng ───────────────────────────────────────────────');
const sh = js.slice(js.indexOf('function showVideoReview('), js.indexOf('function queueVideo('));
check('hỏi /preview và /preview/check', sh.includes("request('/api/v1/content-video/preview', {")
  && sh.includes("request('/api/v1/content-video/preview/check', {"));
check('kết quả của lần mở cũ bị bỏ', (sh.match(/seq === state\.reviewSeq|seq !== state\.reviewSeq/g) || []).length >= 4);
check('Quay lại / mở lại hộp làm mới reviewSeq', js.includes('state.reviewSeq = (state.reviewSeq || 0) + 1;      // kết quả còn đang về thì bỏ')
  && js.includes('state.reviewSeq = (state.reviewSeq || 0) + 1;     // kết quả xem trước của lần mở trước thì bỏ'));
check('lõi cũ (404) → câu «cập nhật TubeCLI»', js.includes("return /^not found$/i.test(msg.trim()) ? t('codex.rv_old_server') : msg;"));
check('nhiều link → báo số video', sh.includes("count > 1 ? [t('codex.rv_many', { n: count })] : []"));
check('chữ server qua esc()', js.includes('`<b>${esc(r.value || \'—\')}</b>${r.detail ? `<small>${esc(r.detail)}</small>` : \'\'}</dd>`'));
check('xuất previewVideo + backFromReview', /previewVideo, backFromReview,/.test(js.slice(js.lastIndexOf('return {'))));

console.log('── 4. chuyển bước ────────────────────────────────────────');
check('tạo xong (cả lượt đứt giữa loạt) → ẩn bảng xem trước',
  (sv.match(/\$\('cx-new-step-review'\)\.classList\.add\('hidden'\);/g) || []).length === 2);
const open = js.slice(js.indexOf('async function openNewTask('), js.indexOf('async function openNewTask(') + 600);
check('mở hộp → về form', open.includes("$('cx-new-step-review').classList.add('hidden');"));

console.log('── 5. bản dịch ───────────────────────────────────────────');
const KEYS = ['codex.btn_review_back', 'codex.btn_preview_video', 'codex.btn_preview_video_hint', 'codex.rv_title',
  'codex.rv_hint', 'codex.rv_checks', 'codex.rv_settings', 'codex.rv_steps', 'codex.rv_loading', 'codex.rv_checking',
  'codex.rv_old_server', 'codex.rv_many', 'codex.rv_step_needs', 'codex.rv_step_off',
  ...['content_ai', 'image_ai', 'voice', 'studio'].map(k => 'codex.rv_check_' + k),
  ...['template', 'content_ai', 'image_ai', 'voice', 'source', 'script', 'media', 'subtitles', 'cast', 'thumbnail',
      'review', 'publish', 'drive', 'watermark'].map(k => 'codex.rv_row_' + k)];
const PH = { 'codex.rv_many': ['{n}'], 'codex.rv_step_needs': ['{what}'] };
const en = JSON.parse(fs.readFileSync(path.join(dir, 'locales', 'en.json'), 'utf-8'));
for (const lang of ['en', 'vi', 'es', 'ja', 'ko', 'ru', 'tr', 'zh', 'zh-TW']) {
  const loc = JSON.parse(fs.readFileSync(path.join(dir, 'locales', lang + '.json'), 'utf-8'));
  const bad = KEYS.filter(k => !loc[k] || (PH[k] || []).some(p => !loc[k].includes(p)));
  check(`${lang}.json: đủ ${KEYS.length} khoá + chỗ giữ`, !bad.length, bad);
  check(`${lang}.json: cùng bộ khoá với en.json`, Object.keys(loc).length === Object.keys(en).length);
}
const vi = JSON.parse(fs.readFileSync(path.join(dir, 'locales', 'vi.json'), 'utf-8'));
check('vi đã dịch (không để tiếng Anh)', vi['codex.btn_preview_video'] === 'Xem trước' && vi['codex.btn_review_back'] === 'Quay lại');

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
