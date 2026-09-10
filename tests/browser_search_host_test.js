/**
 * AI search phải ra MÁY TÌM KIẾM, không gõ câu tìm vào ô tìm thư của Gmail.
 *
 * Run:  node tests/browser_search_host_test.js     (exit 0 = pass)
 *
 * VÌ SAO CÓ FILE NÀY
 *   Lượt lịch 10/9/2026: hồ sơ vừa chạy hành vi email nên tab còn đang ở
 *   mail.google.com. Hành vi kế tiếp là "work/research/study", lệnh sinh ra chỉ
 *   có "Search for '<chủ đề>'", và agent gõ câu ấy vào ô TÌM THƯ của Gmail.
 *
 *   Ba mắt của chuỗi, mỗi mắt tự nó vô hại:
 *     1. open.js dùng lại tab thật gần nhất của hồ sơ, và CHỈ tự vào Google khi
 *        tab đang là about:blank — tab Gmail thì giữ nguyên.
 *     2. search.js hỏi "đang ở máy tìm kiếm chưa?" bằng
 *        currentUrl.includes('google.com'). 'mail.google.com' CHỨA 'google.com',
 *        nên cờ bật, nhánh tìm-trong-site bị bỏ qua.
 *     3. Cùng phép thử chuỗi con ở "chưa ở Google thì mới goto" cũng bảo là đã
 *        ở rồi, nên KHÔNG mở www.google.com. Đoạn sau gõ vào input[name="q"] —
 *        trên Gmail đó là ô tìm thư.
 *
 *   Không có gì báo lỗi: mã chờ #search (khung kết quả Google), không thấy thì
 *   chỉ in cảnh báo rồi đi tiếp, và lượt chạy vẫn tính là thành công. Vì vậy mọi
 *   luật dưới đây phải có test — hỏng lần nữa cũng sẽ im lặng y như vậy.
 */
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, '..');
const SEARCH_JS = path.join(ROOT, 'tubecli', 'extensions', 'browser', 'actions', 'search.js');

let pass = 0, fail = 0;
const check = (name, ok, detail = '') => {
  if (ok) { pass++; console.log(`[PASS] ${name}${detail ? `  (${detail})` : ''}`); }
  else { fail++; console.log(`[FAIL] ${name} -> ${detail}`); }
};

const { isSearchEngineHost, isAppHost } = await import(
  'file://' + SEARCH_JS.replace(/\\/g, '/'));

// ── 1. Máy tìm kiếm thật: nhận, và mọi subdomain khác của google thì KHÔNG ──
for (const h of ['google.com', 'bing.com', 'duckduckgo.com', 'search.yahoo.com',
                 'google.de', 'google.co.uk', 'google.com.vn']) {
  check(`máy tìm kiếm: ${h}`, isSearchEngineHost(h) === true);
}
// Đây là cả cái bug: mấy host này CHỨA 'google.com' nhưng không phải Google Search.
for (const h of ['mail.google.com', 'drive.google.com', 'docs.google.com',
                 'calendar.google.com', 'accounts.google.com', 'news.google.com',
                 'photos.google.com', 'notgoogle.com', 'google.com.evil.example']) {
  check(`KHÔNG phải máy tìm kiếm: ${h}`, isSearchEngineHost(h) === false);
}
check('host rỗng → false', isSearchEngineHost('') === false && isSearchEngineHost(undefined) === false);

// ── 2. Trang ứng dụng: ô tìm ở đây tìm thư/tệp, không phải tìm web ──
for (const h of ['mail.google.com', 'drive.google.com', 'calendar.google.com',
                 'outlook.live.com', 'mail.yahoo.com', 'web.whatsapp.com',
                 'teams.microsoft.com', 'app.slack.com']) {
  check(`trang ứng dụng: ${h}`, isAppHost(h) === true);
}
for (const h of ['vnexpress.net', 'wikipedia.org', 'github.com', 'google.com', 'youtube.com']) {
  check(`trang nội dung: ${h}`, isAppHost(h) === false);
}

// ── 3. Hai phép thử chuỗi con phải biến mất khỏi search.js ──
const src = fs.readFileSync(SEARCH_JS, 'utf8');
// Bỏ dòng chú thích trước khi soi: phần "VÌ SAO" ở đầu file cố ý viết lại đúng
// câu bug ('mail.google.com'.includes('google.com')) để người sau đọc mà hiểu.
const code = src.split('\n').filter((l) => !/^\s*(\/\/|\*|\/\*)/.test(l)).join('\n');
const badLine = (code.match(/.*includes\(['"]google\.com['"]\).*/) || [''])[0].trim();
check("không còn includes('google.com') trong MÃ", !badLine, badLine);
check('cờ máy-tìm-kiếm tính theo host', /const onSearchEngine = isSearchEngineHost\(currentHost\)/.test(src));
check('nhánh tìm-trong-site loại trang ứng dụng',
  /if \(!onSearchEngine && !onAppSite && currentUrl !== 'about:blank'\)/.test(src));
check('bước goto Google hỏi lại host LÚC ĐÓ (không dùng biến cũ)',
  /if \(!isSearchEngineHost\(hostOf\(page\.url\(\)\)\)\) \{/.test(src));
// hostOf phải nuốt URL rác thay vì ném — page.url() có thể là '' hoặc chrome://
check('hostOf chịu được URL rác', /catch \(_\) \{\s*return '';/.test(src));

// ── 4. Lệnh của lịch: hành vi chung phải khai bước vào Google ──
// Tầng dưới đã chặn, nhưng ý định thuộc về câu lệnh: watchVideos/morningCheck từ
// đầu đã khai Navigate, chỉ nhánh chung là thiếu.
const server = fs.readFileSync(path.join(ROOT, 'tubecli', 'api', 'server.py'), 'utf8');
check('nhánh chung có "Navigate to google.com, then search for"',
  /prompt = \(f"Navigate to google\.com, then search for '\{base_query\}'"/.test(server));
check('không còn lệnh "Search for" trơ trọi ở nhánh chung',
  !/prompt = f"Search for '\{base_query\}'" \+ random\.choice/.test(server));
// Bộ tách bước của open.js chỉ hiểu "navigate to " / "search for " ở ĐẦU bước,
// và ranh giới là ", then " — lệnh mới phải khớp cả hai.
const openJs = fs.readFileSync(path.join(ROOT, 'tubecli', 'extensions', 'browser', 'open.js'), 'utf8');
check("open.js tách bước bằng ', then '", /prompt\.split\(\/, then \|/.test(openJs));
check("open.js hiểu 'navigate to '", /s\.startsWith\('navigate to '\)/.test(openJs));
check("open.js hiểu 'search for '", /s\.startsWith\('search for '\)/.test(openJs));

// Lệnh thật, chạy qua đúng bộ tách của open.js: phải ra navigate → search → click.
const sample = "Navigate to google.com, then search for 'cách trồng rau', then click the most relevant result, then browse for 120 seconds. Do NOT search again.";
const steps = sample.split(/, then |, and then |, and /).map((step) => {
  const s = step.trim().toLowerCase();
  if (s.startsWith('navigate to ')) return { action: 'navigate', url: s.replace('navigate to ', '').trim() };
  if (s.startsWith('search for ')) return { action: 'search', keyword: s.replace('search for ', '').replace(/'/g, '') };
  if (s.includes('click')) return { action: 'click' };
  return { action: 'browse' };
});
check('lệnh mới tách ra navigate → search → click → browse',
  steps.map((x) => x.action).join(',') === 'navigate,search,click,browse', JSON.stringify(steps.map((x) => x.action)));
check('bước navigate trỏ google.com', steps[0].url === 'google.com', steps[0].url);
check('bước search giữ nguyên chủ đề', steps[1].keyword === 'cách trồng rau', steps[1].keyword);

console.log(`\n${pass}/${pass + fail} PASS`);
if (fail) process.exit(1);
