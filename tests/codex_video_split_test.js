// Dán nhiều link YouTube → mỗi dòng một video, cả loạt vào hàng đợi (16/9/2026).
//
// User: "tôi muốn thêm logic ví dụ nhập nhiều link thì sẽ tạo nhiều task vào queue mỗi link xuống hàng là 1 video".
// Trước đây nhiều link = MỘT video (pipeline đọc phụ đề nhiều video rồi gộp).
//
// Kiểm:
//   1. cvLinkLines chạy thật: tách theo dòng, và KHÔNG tách khi không phải danh sách link thuần
//   2. renderVideoSplit: ô tick chỉ hiện khi ≥2 dòng link, câu gợi ý nói số video
//   3. submitVideo: gửi từng link một, cả loạt vào hàng đợi, tiêu đề thêm số, hỏng giữa đường vẫn nói rõ
//   4. bản dịch 9 ngôn ngữ × 7 khoá, đủ chỗ giữ {n} / {error}
//
// Run: node tests/codex_video_split_test.js
'use strict';
const fs = require('fs');
const path = require('path');

const dir = path.join(__dirname, '..', 'tubecli', 'extensions', 'codex');
const js = fs.readFileSync(path.join(dir, 'static', 'codex.js'), 'utf-8').replace(/\r\n/g, '\n');
const html = fs.readFileSync(path.join(dir, 'static', 'codex.html'), 'utf-8').replace(/\r\n/g, '\n');

let pass = 0, fail = 0;
function check(label, ok, detail) {
    if (ok) { pass++; console.log('  ok  ', label); }
    else { fail++; console.log('  FAIL', label, detail === undefined ? '' : JSON.stringify(detail).slice(0, 260)); }
}

const L1 = 'https://www.youtube.com/watch?v=k4UucPuG6Mo';
const L2 = 'https://www.youtube.com/watch?v=i6GHiEPng6o';
const L3 = 'https://youtu.be/4Br45kOed_s';

console.log('── 1. cvLinkLines ──────────────────────────────────────');
const a = js.indexOf('  const CV_YT_ID_RE = ');
const b = js.indexOf('  /** Ô "Độ dài video"');
check('cắt được khối link', a > 0 && b > a, { a, b });
const API = new Function(`${js.slice(a, b)}; return { cvLinkLines, cvLinkOnly, cvYoutubeIds };`)();
const CASES = [
    ['hai dòng hai link → hai video', `${L1}\n${L2}`, [L1, L2]],
    ['ba dòng, có khoảng trắng và dòng rỗng', `  ${L1}  \n\n${L2}\n${L3}\n`, [L1, L2, L3]],
    ['một link → không tách (vẫn một video như cũ)', L1, []],
    ['hai link CÙNG một dòng → một video (xuống hàng mới là ranh giới)', `${L1} ${L2}`, []],
    ['một dòng nhiều link + một dòng một link → hai video', `${L1} ${L2}\n${L3}`, [`${L1} ${L2}`, L3]],
    ['có dòng ghi chú không chứa link → không tách', `tham khảo hai video\n${L1}\n${L2}`, []],
    ['bài dán tay kèm link → không tách', `${'La calma ordena tu vida. '.repeat(10)}\n${L1}\n${L2}`, []],
    ['không có link nào → không tách', 'dòng một\ndòng hai', []],
];
for (const [label, txt, want] of CASES) {
    const got = API.cvLinkLines(txt);
    check(label, JSON.stringify(got) === JSON.stringify(want), got);
}

console.log('── 2. ô tick + markup ──────────────────────────────────');
check('markup: ô tick ẩn sẵn, bật sẵn, có dòng gợi ý',
    html.includes('<label class="cx-check hidden" id="cx-v-split-wrap">')
    && html.includes('<input type="checkbox" id="cx-v-split" checked onchange="CODEX.onVideoSplit()">')
    && html.includes('id="cx-v-split-hint"') && html.includes('data-i18n="codex.field_video_split"'));
const r1 = js.indexOf('  /** Ô tick «Mỗi link một video»');
const r2 = js.indexOf('  function onVideoSplit()');
check('cắt được renderVideoSplit', r1 > 0 && r2 > r1, { r1, r2 });
const els = {};
const cls = () => ({ set: {}, toggle(c, v) { this.set[c] = !!v; }, has(c) { return !!this.set[c]; } });
const el = (id) => (els[id] ||= { id, value: '', textContent: '', classList: cls() });
const R = new Function('$', 't', 'cvLinkLines', `${js.slice(r1, r2)}; return renderVideoSplit;`)(
    el, (k, p) => k + (p ? JSON.stringify(p) : ''), API.cvLinkLines);
el('cx-v-content').value = L1;
R();
check('một link → ẩn ô tick', el('cx-v-split-wrap').classList.has('hidden'));
el('cx-v-content').value = `${L1}\n${L2}\n${L3}`;
R();
check('ba link → hiện ô tick, gợi ý nói 3 video',
    !el('cx-v-split-wrap').classList.has('hidden') && el('cx-v-split-hint').textContent === 'codex.cv_split_hint{"n":3}',
    el('cx-v-split-hint').textContent);
check('ô nội dung đổi là vẽ lại (onVideoContent gọi renderVideoSplit)',
    /function onVideoContent\(\)[\s\S]{0,320}renderVideoSplit\(\);/.test(js));
check('mở form mới: bật lại ô tick', js.includes("$('cx-v-split').checked = true;"));
check('xuất onVideoSplit', js.includes('laneChoice, onVideoSplit,'));

console.log('── 3. gửi từng link ────────────────────────────────────');
const sv = js.slice(js.indexOf('async function submitVideo('), js.indexOf('async function planFromModal('));
check('bỏ tick → gộp lại như cũ (một task, nội dung nguyên văn)',
    sv.includes("const links = (($('cx-v-split') || {}).checked === false) ? [] : cvLinkLines(content);")
    && sv.includes('const batch = links.length >= 2 ? links : [content];'));
check('loạt nhiều link luôn vào HÀNG ĐỢI (không dựng song song)', sv.includes('if (batch.length > 1) hold = true;'));
check('hỏi «song song hay hàng đợi» chỉ còn cho lượt MỘT video',
    sv.indexOf('if (batch.length > 1) hold = true;') < sv.indexOf("const busy = laneBusyTask('video');"));
check('gửi lần lượt từng link, mỗi lần một task',
    sv.includes('for (let i = 0; i < batch.length; i++)') && sv.includes('content: batch[i], review: review,')
    && sv.includes("queue: hold,"));
check('tiêu đề đã gõ: link đầu giữ nguyên, các link sau thêm số',
    sv.includes("if (title && batch.length > 1) opts.title = i === 0 ? title : `${title} (${i + 1})`;"));
check('options của mỗi task là bản SAO (không dùng chung một đối tượng)', sv.includes('const opts = Object.assign({}, options);'));
check('xong: báo số video đã vào hàng đợi',
    sv.includes("toast(t('codex.toast_video_many', { n: made }), 'success');")
    && sv.includes("$('cx-created-title').textContent = t('codex.created_many_title', { n: made });"));
check('một video thì vẫn giữ nguyên câu cũ (backlog / chạy liền)',
    sv.includes("} else if (task.status === 'backlog') {") && sv.includes("'codex.created_video_title'"));
check('đứt giữa loạt: nói rõ đã tạo được mấy cái',
    sv.includes("toast(made ? t('codex.toast_video_many_partial', { n: made, error: e.message })"));

console.log('── 4. bản dịch ─────────────────────────────────────────');
const KEYS = {
    'codex.field_video_split': [], 'codex.cv_split_hint': ['{n}'], 'codex.toast_video_many': ['{n}'],
    'codex.toast_video_many_partial': ['{n}', '{error}'], 'codex.created_many_title': ['{n}'],
    'codex.created_many_desc_review': [], 'codex.created_many_desc_auto': [],
};
for (const lang of ['en', 'vi', 'es', 'ja', 'ko', 'ru', 'tr', 'zh', 'zh-TW']) {
    const loc = JSON.parse(fs.readFileSync(path.join(dir, 'locales', lang + '.json'), 'utf-8'));
    const bad = Object.entries(KEYS).filter(([k, ph]) => !loc[k] || ph.some(p => !loc[k].includes(p)));
    check(`${lang}.json: đủ 7 khoá + chỗ giữ`, !bad.length, bad.map(x => x[0]));
}
const vi = JSON.parse(fs.readFileSync(path.join(dir, 'locales', 'vi.json'), 'utf-8'));
check('vi dịch thật, nói cả cách gộp lại',
    vi['codex.field_video_split'] === 'Mỗi link một video' && vi['codex.cv_split_hint'].includes('Bỏ tick'),
    vi['codex.cv_split_hint']);

console.log();
console.log(fail ? `${pass}/${pass + fail} PASS — ${fail} HỎNG` : `${pass}/${pass + fail} PASS`);
process.exit(fail ? 1 : 0);
