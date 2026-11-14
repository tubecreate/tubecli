// Bước «t2:publish-click» + «t2:verify-publish» của script đăng YouTube, chạy trong TRÌNH DUYỆT THẬT trên trang giả lập.
//
// Chạy:  node tests/publish_click_dom_test.js      (exit 0 = đạt; không có Playwright thì SKIP)
//
// Vì sao (tuan4, 14/11/2026): 3 trong 30 lượt đăng ra NHÁP (lượt 678 / 693 / 700). Nút Xuất bản bật, đúng bước Hiển
// thị, bấm 4 lần mà Studio đứng yên; bản cũ bấm một lần rồi đi tiếp, không nhìn hộp nào khác, và chỉ ghi 160 ký tự đầu
// của hộp tải lên nên không ai biết vì sao. Nay: bấm nút «xuất bản» của hộp xác nhận phụ nếu có, bấm lại khi nút còn
// bật, và khi vẫn không ăn thì trả về dòng lỗi đọc được trên trang.
//
// Trang giả chỉ dùng tên thẻ / id mà script dò (ytcp-uploads-dialog, #done-button, ytcp-video-share-dialog…). Không mạng.
const { execFileSync } = require('child_process');
const path = require('path');
const fs = require('fs');

const ROOT = path.resolve(__dirname, '..');
let PASS = 0, FAIL = 0;
const check = (name, ok, detail = '') => {
  if (ok) { PASS++; console.log(`[PASS] ${name}`); } else { FAIL++; console.log(`[FAIL] ${name}  ${String(detail).slice(0, 300)}`); }
};

function loadPlaywright() {
  const here = path.join(ROOT, 'tubecli', 'extensions', 'browser', 'node_modules', 'playwright');
  const sibling = path.join(ROOT, '..', 'tubecli', 'tubecli', 'extensions', 'browser', 'node_modules', 'playwright');
  for (const p of [here, sibling]) { if (fs.existsSync(p)) { try { return require(p); } catch (_) { /* thử chỗ kế */ } } }
  return null;
}

const out = execFileSync('python', ['-c',
  'import sys, json; sys.path.insert(0, sys.argv[1]); '
  + 'from tubecli.extensions.content_video import pipeline as P; '
  + 'print("@@" + json.dumps([P.PUBLISH_CLICK_CODE, P.VERIFY_PUBLISH_CODE]))', ROOT],
{ env: { ...process.env, PYTHONIOENCODING: 'utf-8' }, maxBuffer: 1e8 }).toString();
const [CLICK, VERIFY] = JSON.parse(out.slice(out.lastIndexOf('@@') + 2));

check('A1 hai đoạn JS là biểu thức hợp lệ, không có «{{» (bộ chạy script thay {{biến}})',
  (() => { try { new Function('return ' + CLICK); new Function('return ' + VERIFY); return !CLICK.includes('{{') && !VERIFY.includes('{{'); } catch (e) { return false; } })());

const PAGE = (mode) => `<!doctype html><html><body>
<style>ytcp-uploads-dialog, ytcp-prechecks-warning-dialog, ytcp-video-share-dialog, tp-yt-paper-dialog { display:block; padding:8px; }
[hidden] { display:none !important; }</style>
<ytcp-uploads-dialog id="up">
  <div>El arte del wu wei Saved as private Details Video elements Initial check Visibility</div>
  <div id="privacy-radios"><tp-yt-paper-radio-button name="PUBLIC">Public</tp-yt-paper-radio-button></div>
  <div class="error-short" ${mode === 'error' ? '' : 'hidden'}>Daily upload limit reached. You can upload more videos in 24 hours.</div>
  <ytcp-button id="done-button"><button>Publish</button></ytcp-button>
</ytcp-uploads-dialog>
<ytcp-prechecks-warning-dialog id="pre" hidden>
  <div>We're still checking your content</div>
  <ytcp-button id="go-back"><button>Go back</button></ytcp-button>
  <ytcp-button id="anyway"><button>Publish anyway</button></ytcp-button>
</ytcp-prechecks-warning-dialog>
<ytcp-video-share-dialog id="share" hidden>
  <div>Video published</div>
  <a href="https://support.google.com/youtube?p=upload_videos">Learn more</a>
  <a href="https://youtu.be/abcdefghijk">https://youtu.be/abcdefghijk</a>
</ytcp-video-share-dialog>
<script>
  window.clicks = { done: 0, anyway: 0, goback: 0 };
  const done = document.querySelector('#done-button'), up = document.querySelector('#up');
  const pre = document.querySelector('#pre'), share = document.querySelector('#share');
  const publish = () => { up.hidden = true; pre.hidden = true; share.hidden = false; };
  done.addEventListener('click', () => {
    window.clicks.done++;
    const mode = ${JSON.stringify(mode)};
    if (mode === 'normal') { done.setAttribute('aria-disabled', 'true'); setTimeout(publish, 1500); }
    if (mode === 'confirm') { pre.hidden = false; }
    if (mode === 'second-click' && window.clicks.done >= 2) { done.setAttribute('aria-disabled', 'true'); setTimeout(publish, 500); }
  });
  document.querySelector('#anyway').addEventListener('click', () => { window.clicks.anyway++; setTimeout(publish, 400); });
  document.querySelector('#go-back').addEventListener('click', () => { window.clicks.goback++; pre.hidden = true; });
</script></body></html>`;

(async () => {
  const pw = loadPlaywright();
  if (!pw) { console.log('SKIP: không có Playwright (tubecli/extensions/browser/node_modules) — chỉ kiểm cú pháp'); process.exit(FAIL ? 1 : 0); }
  let browser;
  try { browser = await pw.chromium.launch({ headless: true }); } catch (e) {
    console.log('SKIP: không mở được Chromium của Playwright — ' + String(e.message).split('\n')[0]); process.exit(FAIL ? 1 : 0);
  }
  const run = async (mode, withVerify = true) => {
    const page = await browser.newPage();
    await page.setContent(PAGE(mode));
    const click = await page.evaluate(CLICK);
    const verify = withVerify ? await page.evaluate(VERIFY) : null;
    const clicks = await page.evaluate(() => window.clicks);
    await page.close();
    return { click, verify, clicks };
  };
  try {
    let r = await run('normal');
    check('B1 bình thường: bấm một lần, nút mờ đi → «clicked»', r.click === 'clicked' && r.clicks.done === 1, JSON.stringify(r));
    check('B2 …verify thấy đã đăng và lấy đúng link VIDEO (không phải link trợ giúp)',
      r.verify.state === 'published' && r.verify.url === 'https://youtu.be/abcdefghijk', JSON.stringify(r.verify));

    r = await run('confirm');
    check('C1 Studio bật hộp xác nhận phụ → script bấm nút «Publish anyway» của hộp đó',
      r.clicks.anyway === 1 && /^clicked\+confirmed: Publish anyway/.test(r.click), JSON.stringify(r));
    check('C2 …KHÔNG bấm «Go back»', r.clicks.goback === 0);
    check('C3 …và video được đăng', r.verify.state === 'published', JSON.stringify(r.verify));

    r = await run('second-click');
    check('D1 cú bấm đầu không ăn, nút còn bật → bấm lại và đăng được', r.click === 'clicked' && r.clicks.done >= 2
      && r.verify.state === 'published', JSON.stringify(r));

    r = await run('error');
    check('E1 bấm không ăn + trang có dòng lỗi → «no-effect: <dòng lỗi>»', /^no-effect: .*Daily upload limit reached/.test(r.click), r.click);
    check('E2 …bấm lại tối đa 3 lần, không bấm vô hạn', r.clicks.done === 3, JSON.stringify(r.clicks));
    check('E3 …verify báo nháp KÈM lý do đọc được trên trang', r.verify.state === 'draft' && /Daily upload limit reached/.test(r.verify.why || ''),
      JSON.stringify(r.verify));
  } finally {
    await browser.close();
  }
  console.log(`\n${PASS}/${PASS + FAIL} PASS`);
  process.exit(FAIL ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
