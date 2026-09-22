/**
 * Phụ đề kiểu video giải thích Nhật: câu TÁCH ĐÔI quanh hình (layout.split) + chữ Nhật/Trung viết liền.
 *
 * VÌ SAO CÓ FILE NÀY
 *   User gửi ảnh mẫu (21/9/2026): chữ đen rất to, dòng đầu của câu nằm ở ĐỈNH khung, phần còn lại ở ĐÁY, hình ở giữa —
 *   «có 2 hàng ở top và bottom». Bộ phụ đề vốn viết cho kiểu CapCut: trên khung ngang nó ÉP mọi mẫu về MỘT dòng (arLines
 *   = 1) và mỗi dòng dài gấp 1,9 — mẫu tách đôi vì thế không bao giờ có dòng thứ hai để đưa lên đỉnh. Ba bẫy tiếng Nhật
 *   đi kèm đã gặp trong cùng ngày: chèn dấu cách giữa các «từ», cả câu thành một «từ» khổng lồ (dựng chậm 6 lần), dấu
 *   、。 rơi xuống đầu dòng.
 *
 *   1. mẫu jp_telop: 2–3 dòng → dòng 0 ở đỉnh, các dòng sau ở đáy; 1 dòng → ở đáy
 *   2. mẫu khác trên khung ngang vẫn MỘT dòng, không tách (không đổi pixel nào của video cũ)
 *   3. chữ Nhật không mốc từ: tách theo VẾ, xếp SÁT nhau; có mốc từ: dấu câu dính vào chữ trước
 *   4. word.kind = none → từ đang đọc vẫn được blit (đường vẽ sống là thứ làm dựng chậm)
 *
 * Run:  node tests/subtitle_split_test.js     (exit 0 = pass; thiếu node-canvas thì bỏ qua, exit 0)
 */
const path = require('path');
const R = path.join(__dirname, '..', 'renderer');
let createCanvas;
try { ({ createCanvas } = require(path.join(R, 'node_modules', 'canvas'))); } catch (e) {
  console.log('(bỏ qua: chưa cài node-canvas trong renderer/node_modules)');
  process.exit(0);
}
const E = require(path.join(R, 'engines', 'subtitle_engine.js'));
const fs = require('fs');
const src = fs.readFileSync(path.join(R, 'engines', 'subtitle_engine.js'), 'utf8');

let failed = 0;
const ok = (cond, label, detail) => {
  if (cond) { console.log('  ok   ' + label); return; }
  failed++;
  console.log('  FAIL ' + label + (detail !== undefined ? ' — ' + JSON.stringify(detail).slice(0, 300) : ''));
};

const presets = E.loadPresets(path.join(R, 'engines', 'subtitle_presets.json'));
const W = 1920, H = 1080;
const layout = (presetId, scale, text, words) => {
  const eng = E.makeSubtitle(E.getPreset(presets, presetId), { fontScale: scale, yPct: 0.9, maxLines: null });
  const ctx = createCanvas(W, H).getContext('2d');
  const step = { id: presetId + scale + text.length, start: 0, end: 9, duration: 9, voice_text: text };
  if (words) step.words = words;
  return eng.layoutFor(ctx, W, H, step);
};
const lineTexts = (ph) => ph.lines.map((l) => l.items.map((i) => i.text).join(''));

console.log('── 1. jp_telop: tách TRÊN + DƯỚI ──────────────────────────');
const LONG = '送る前に、文章を十回読み直したのに、送ったあとで、もう一度読み直してしまう。';
const L = layout('jp_telop', 0.8, LONG);
const ph = L.phrases[0];
ok(L.phrases.length === 1 && ph.lines.length >= 2, 'CẢ CÂU là một cụm, nhiều dòng (trước: khung ngang ép 1 dòng → không bao giờ có dòng trên)',
  L.phrases.map(lineTexts));
ok(lineTexts(ph).join('') === LONG, 'đủ chữ, đúng thứ tự', lineTexts(ph));
ok(ph.split === true && ph.lines[0].baseY < H * 0.25 && ph.lines[1].baseY > H * 0.70,
  'dòng 0 ở ĐỈNH khung, dòng 1 ở ĐÁY — hình nằm giữa', ph.lines.map((l) => l.baseY));
ok(ph.lines[ph.lines.length - 1].baseY < H * 0.91 && ph.lines[0].baseY > H * 0.09, 'cả hai vùng chữ nằm trong vùng an toàn của khung');
const last = ph.lines.length - 1;
ok(last < 2 || Math.abs((ph.lines[2].baseY - ph.lines[1].baseY) - L.px * 1.2) < 3, 'các dòng DƯỚI xếp liền nhau theo giãn dòng của mẫu');
const S1 = layout('jp_telop', 0.8, '濁っている。').phrases[0];
ok(S1.lines.length === 1 && !S1.split && S1.lines[0].baseY > H * 0.75, 'cụm MỘT dòng thì nằm ở đáy như phụ đề thường', S1.lines[0].baseY);
const BIG = layout('jp_telop', 0.8 * 1.9, '調べる手段は、人生でいちばん増えたのに、決めることは、人生でいちばん難しくなっている。');
ok(Math.abs(BIG.px - 104) <= 3 && Math.abs(L.px - 55) <= 2,
  'cỡ chữ: mặc định ~55 px (cỡ user đang xem), «rất lớn» ×1,9 ~104 px (cỡ ảnh mẫu)', [L.px, BIG.px]);
ok(BIG.phrases.length >= 2 && BIG.phrases.every((p) => p.lines.length <= 3) && BIG.phrases.map(lineTexts).flat().join('').length === 43,
  'chữ cỡ đại: câu dài tự chia thành vài cụm, mỗi cụm ≤ 3 dòng, không mất chữ', BIG.phrases.map(lineTexts));
const maxW = Math.max.apply(null, BIG.phrases.map((p) => Math.max.apply(null, p.lines.map((l) => l.w))));
ok(maxW <= W * 0.82, 'không dòng nào tràn vùng an toàn ngang', maxW);

console.log('── 2. mẫu khác không đổi ───────────────────────────────────');
const EN = 'The old woman simply set the bucket down and waited for the mud to settle before she drank the water';
const C = layout('capcut_bold', 0.8, EN);
ok(C.phrases.every((p) => p.lines.length === 1 && !p.split), 'capcut_bold trên khung ngang vẫn MỘT dòng mỗi cụm, không tách', C.phrases.map((p) => p.lines.length));
ok(E.normalizePreset(E.getPreset(presets, 'capcut_bold')).layout.split === false
  && E.normalizePreset(E.getPreset(presets, 'jp_telop')).layout.split === true, 'chỉ jp_telop khai layout.split');
ok(/if \(P\.layout\.split === true\) \{ arLines = 0; arChars = 1; \}/.test(src), 'luật «khung ngang ép một dòng» chỉ được gỡ cho mẫu split');

console.log('── 3. chữ Nhật viết liền ───────────────────────────────────');
const items = ph.lines.map((l) => l.items.map((i) => i.text));
ok(items.flat().every((t) => /[、。]$/.test(t)), 'không có mốc từ → mỗi VẾ (tới hết 、。) là một «từ»: dòng ngắt ở dấu câu', items);
const l0 = ph.lines[0];
ok(l0.items.length < 2 || Math.abs((l0.items[1].x) - (l0.items[0].x + l0.items[0].w)) < 1.5, 'các vế xếp SÁT nhau — không chèn bề rộng dấu cách', l0.items.map((i) => [i.x, i.w]));
const marks = Array.from('水は、澄む。').map((c, i) => ({ word: c, start: i * 0.4, end: i * 0.4 + 0.4 }));
const M = layout('jp_telop', 0.8, '水は、澄む。', marks).phrases[0];
const mt = M.lines.map((l) => l.items.map((i) => i.text)).flat();
ok(mt.join('') === '水は、澄む。' && mt.every((t) => !/^[、。]/.test(t)) && mt.includes('は、') && mt.includes('む。'),
  'có mốc từ theo TỪNG CHỮ → dấu 、。 dính vào chữ đứng trước (không bao giờ đứng đầu dòng)', mt);

const giant = [{ word: 'その横で、一人の老いた女が、桶に水を汲み、地面に置きました。', start: 0, end: 8 }];
const G = layout('jp_telop', 0.8, giant[0].word, giant).phrases[0];
const gl = G.lines.map((l) => l.items.map((i) => i.text).join(''));
ok(gl.every((t) => /[、。]$/.test(t)) && gl.join('') === giant[0].word,
  '«từ» là CẢ CÂU (người gọi tách theo khoảng trắng) → tự chia theo vế: không dòng nào gãy giữa chữ («…置きま / した。»)', gl);

console.log('── 4. đường vẽ nhanh ───────────────────────────────────────');
ok(/\(env <= 0 \|\| P\.word\.kind === 'none'\)/.test(src), "word.kind 'none': từ đang đọc vẫn được blit ảnh dựng sẵn");
ok(/ink !== 'text' && !ph\.split/.test(src), 'cụm tách đôi KHÔNG vẽ hộp nền (một tấm nền trùm từ đỉnh tới đáy là che cả hình)');

console.log(failed ? `\n${failed} HỎNG` : '\nTẤT CẢ ĐỀU PASS');
process.exit(failed ? 1 : 0);
