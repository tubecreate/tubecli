// Dọn tab Muse (8/10/2026 — user: «muse quá tải là quá nhiều tab, xoá bớt tab không cần mỗi lần tạo xong»).
// Kiểm pruneTabs với ctx/page giả (không trình duyệt thật):
//   1. giữ MỘT tab muse.ai (tab đầu), đóng tab muse.ai thừa + tab trống; tab trang khác giữ nguyên
//   2. keep = tab việc đang dùng: không đóng nó, vẫn giữ thêm một tab muse.ai «nhà»
//   3. không có tab muse.ai nào → không đóng gì ngoài tab trống
//   4. page.close() ném → không đổ, đếm vẫn đúng
// Run:  node tests/muse_tool_tabs_test.js
const path = require('path');
const { pruneTabs } = require(path.join(__dirname, '..', 'tubecli', 'extensions', 'browser', 'muse_tool.cjs'));

let PASS = 0, FAIL = 0;
function ok(cond, label, detail) {
  if (cond) { PASS++; console.log('  ok  ', label); } else { FAIL++; console.log('  FAIL', label, '—', JSON.stringify(detail || '')); }
}
function fakePage(url, throwOnClose) {
  const p = { _url: url, closed: false };
  p.url = () => p._url;
  p.close = async () => { if (throwOnClose) throw new Error('gone'); p.closed = true; };
  return p;
}
function ctxOf(pages) { return { pages: () => pages.filter((p) => !p.closed) }; }

(async () => {
  const home = fakePage('https://muse.ai/');
  const t1 = fakePage('https://muse.ai/thread/aaa');
  const t2 = fakePage('https://muse.ai/thread/bbb');
  const blank = fakePage('about:blank');
  const other = fakePage('https://www.youtube.com/');
  let n = await pruneTabs(ctxOf([home, t1, t2, blank, other]), null);
  ok(n === 3 && !home.closed && t1.closed && t2.closed && blank.closed && !other.closed,
     'giữ tab muse.ai đầu, đóng 2 tab muse.ai thừa + tab trống, tab YouTube giữ nguyên', { n, home: home.closed, other: other.closed });

  const h2 = fakePage('https://muse.ai/');
  const work = fakePage('https://muse.ai/thread/work');
  const extra = fakePage('https://muse.ai/thread/extra');
  n = await pruneTabs(ctxOf([h2, work, extra]), work);
  ok(n === 1 && !work.closed && !h2.closed && extra.closed, 'keep = tab việc: không đóng nó, giữ thêm tab nhà, đóng tab thừa', { n });

  const b1 = fakePage('about:blank'), o1 = fakePage('https://example.com/');
  n = await pruneTabs(ctxOf([b1, o1]), null);
  ok(n === 1 && b1.closed && !o1.closed, 'không có tab muse.ai → chỉ đóng tab trống', { n });

  const h3 = fakePage('https://muse.ai/'), bad = fakePage('https://muse.ai/thread/x', true);
  n = await pruneTabs(ctxOf([h3, bad]), null);
  ok(n === 1 && !h3.closed, 'close() ném → không đổ', { n });

  console.log(`\n${PASS} passed, ${FAIL} failed`);
  process.exit(FAIL ? 1 : 0);
})();
