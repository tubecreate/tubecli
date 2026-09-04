/**
 * "Thu thập dữ liệu" phải thu thật trên đường chạy bằng script.
 *
 * Run:  node tests/scripted_scrape_test.js     (exit 0 = pass)
 *
 * Anh em với scrape_trigger_test.js: file kia lo đường AI (model được bảo ưu
 * tiên lướt hơn thu). Đây là đường CÒN LẠI — chạy bằng script, nay là mặc định
 * vì "hành vi giống người thật" mặc định TẮT. Trên đường đó extract_content chỉ
 * chạy khi câu lệnh có đúng chữ "extract content", mà không prompt hành vi nào
 * nói vậy. Nên ô tích bật, lượt chạy diễn ra, và không ai lưu gì cả.
 */
//
// The first attempt at this helper referenced `session`, a binding that exists
// only inside the manual-mode branch — it would have thrown mid-run. So this
// does not read the code and hope: it lifts the helper out of open.js, RUNS it
// against fakes, and checks both that every name resolves and that it makes the
// right call on each kind of page.
const fs = require('fs');
const assert = require('assert');

const path = require('path');
const FILE = path.join(__dirname, '..', 'tubecli', 'extensions', 'browser', 'open.js');
const SRC = fs.readFileSync(FILE, 'utf8');

// ── 1. the helper exists and is wired to page-ending steps only ──────
// Cat tu 'let scrapeSession' — bien do thuoc ve helper; bo qua thi doc no nem
// ReferenceError va bi chinh khoi catch cua helper nuot mat.
const start = SRC.indexOf('let scrapeSession = null;');
assert(start > 0, 'không thấy khai báo scrapeSession');
assert(SRC.indexOf('const harvestIfContentPage = async (whence) => {') > start, 'helper phải đứng sau khai báo');
const end = SRC.indexOf('\n      };\n', start) + '\n      };'.length;
const helper = SRC.slice(start, end);
assert(SRC.includes('await harvestIfContentPage(step.action)'), 'helper không được gọi ở đâu cả');
const guard = SRC.split('\n').find((l) => l.includes("['browse', 'navigate', 'click'"));
assert(guard && guard.includes('includes(step.action)'), 'phải chỉ gọi sau các bước kết thúc trên một trang');
assert(!guard.includes("'search'") && !guard.includes('extract_content'),
  'không gọi sau search (trang kết quả) và sau extract_content (vừa thu xong)');
console.log('1 noi day    : gọi sau browse/navigate/click… — không sau search, không sau extract_content');

// ── 2. every binding it uses is declared BEFORE it (the bug last time) ──
const declLine = (name) => {
  const re = new RegExp(`^\\s*(?:import[^\\n]*\\b${name}\\b|(?:let|const|var|function|async function)\\s+${name}\\b)`, 'm');
  const m = re.exec(SRC);
  return m ? SRC.slice(0, m.index).split('\n').length : -1;
};
const helperLine = SRC.slice(0, start).split('\n').length;
const OUTER = ['SessionManager', 'minSessionMinutes', 'aiModel', 'prompt', 'profileName',
  'agentContext', 'extractContentAction', 'page'];
for (const name of OUTER) {
  const at = declLine(name);
  assert(at > 0, `${name}: không tìm thấy khai báo`);
  assert(at < helperLine, `${name} khai báo ở dòng ${at}, sau helper (dòng ${helperLine})`);
}
assert(!/\bsession\./.test(helper), 'helper KHÔNG được dùng `session` — biến đó nằm trong nhánh khác');
assert(helper.includes('scrapeSession'), 'phải dùng SessionManager riêng của đường script');
console.log(`2 tam vuc    : ${OUTER.length} biến đều khai báo trước dòng ${helperLine} | không đụng \`session\` của nhánh khác`);

// ── 3+4. run it ──────────────────────────────────────────────────────
const factory = new Function(
  'agentContext', 'page', 'profileName', 'SessionManager', 'minSessionMinutes',
  'aiModel', 'prompt', 'extractContentAction', 'console',
  helper + '\nreturn harvestIfContentPage;');

const makeEnv = ({ url, isContentPage = true, scraping = true, scraped = new Set(), extractOk = true }) => {
  const calls = { extract: 0, recorded: 0, scanned: 0, built: 0, params: null, warns: [] };
  function FakeSM() {
    calls.built++;
    this.scrapedUrls = scraped;
    this.scanPageContent = async () => { calls.scanned++; return { isContentPage }; };
    this.addScrapedUrl = (u) => scraped.add(u);
    this.recordPageVisit = async () => { calls.recorded++; };
  }
  const fn = factory(
    { enable_scraping: scraping, scraper_text_limit: 4321, agent_id: 'a1', agent_name: 'MC' },
    { url: () => url, title: async () => 'Tiêu đề' },
    'tuan002', FakeSM, 10, 'model', 'goal',
    { extract_content: async (_p, params) => { calls.extract++; calls.params = params; return extractOk; } },
    { log() {}, warn: (m) => calls.warns.push(m) });
  return { fn, calls, scraped };
};

(async () => {
  // bài viết thật → thu
  let e = makeEnv({ url: 'https://vnexpress.net/bai-viet.html' });
  await e.fn('browse');
  assert.strictEqual(e.calls.warns.length, 0, 'không được có lỗi bị nuốt: ' + e.calls.warns.join(' | '));
  assert.strictEqual(e.calls.extract, 1, 'trang bài viết phải được thu');
  assert.strictEqual(e.calls.recorded, 1, 'phải ghi lại lượt ghé để đánh dấu isScraped');
  assert(e.scraped.has('https://vnexpress.net/bai-viet.html'), 'URL phải vào danh sách đã thu');
  assert.strictEqual(e.calls.params.scraper_text_limit, 4321, 'phải truyền giới hạn ký tự của agent');
  assert.strictEqual(e.calls.params.agentId, 'a1', 'phải gắn agent để kho có chủ');
  assert.strictEqual(e.calls.params.profileName, 'tuan002', 'phải lưu vào đúng hồ sơ');

  // tắt ô tích → không dựng cả SessionManager
  e = makeEnv({ url: 'https://vnexpress.net/x.html', scraping: false });
  await e.fn('browse');
  assert.strictEqual(e.calls.built + e.calls.extract + e.calls.scanned, 0, 'tắt thu thập thì không làm gì cả');

  // youtube / google → bỏ, không tốn một lần quét
  for (const u of ['https://www.youtube.com/watch?v=x', 'https://www.google.com/search?q=x']) {
    e = makeEnv({ url: u });
    await e.fn('browse');
    assert.strictEqual(e.calls.scanned, 0, 'tên miền bị chặn không được quét: ' + u);
  }

  // không phải bài viết → quét rồi thôi
  e = makeEnv({ url: 'https://vnexpress.net/trang-chu', isContentPage: false });
  await e.fn('browse');
  assert.strictEqual(e.calls.scanned, 1);
  assert.strictEqual(e.calls.extract, 0, 'trang không phải bài viết thì không thu');

  // đã thu rồi → không thu lại
  e = makeEnv({ url: 'https://vnexpress.net/a.html', scraped: new Set(['https://vnexpress.net/a.html']) });
  await e.fn('browse');
  assert.strictEqual(e.calls.extract, 0, 'một URL chỉ thu một lần');

  // about:blank → bỏ
  e = makeEnv({ url: 'about:blank' });
  await e.fn('navigate');
  assert.strictEqual(e.calls.scanned, 0);

  // dựng SessionManager đúng MỘT lần cho nhiều trang
  const shared = new Set();
  const many = makeEnv({ url: 'https://vnexpress.net/1.html', scraped: shared });
  await many.fn('browse');
  await many.fn('click');
  assert.strictEqual(many.calls.built, 1, 'SessionManager chỉ dựng một lần (constructor đọc đĩa)');
  console.log('3 quyet dinh : thu bài viết | tắt thì im | bỏ youtube+google, trang thường, URL đã thu, about:blank | dựng 1 lần');

  // lỗi giữa chừng không được phá lượt chạy
  const boom = factory(
    { enable_scraping: true }, { url: () => { throw new Error('trang đã đóng'); } },
    'p', function () {}, 1, '', '', { extract_content: async () => true }, { log() {}, warn() {} });
  await boom('browse');
  assert(helper.includes('catch (e)') && helper.includes('console.warn'), 'phải nuốt lỗi và ghi log');
  console.log('4 khong pha  : trang đóng giữa chừng → chỉ ghi log, lượt chạy vẫn tiếp');

  console.log('\nALL 4 GROUPS PASSED');
})().catch((e) => { console.error('FAILED:', e.message); process.exit(1); });
