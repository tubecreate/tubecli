/**
 * Codex nạp nhanh (20/9/2026): danh sách GỌN + vẽ khung chờ trước khi đợi i18n + mở thẻ mới tải chi tiết.
 *
 * VÌ SAO CÓ FILE NÀY
 *   User mở node Codex trong Flow: «load nội dung khá lâu, không có loading, cảm giác như bị treo». Đo được hai
 *   nguyên nhân, cả hai đều ở trang này:
 *     a) `await loadI18nFromApi()` (228 KB, 1,4 giây ngay trên máy) chạy TRƯỚC lượt vẽ đầu tiên → vùng danh sách
 *        trống trơn suốt thời gian đó, dù khung xương (cx-skeleton) đã có sẵn từ lâu.
 *     b) /tasks trả TOÀN BỘ task: 50 task = 790 KB, riêng `plan` 582 KB (74 %) và `result` 47 KB — hai trường chỉ
 *        dùng khi MỞ thẻ ra.
 *
 *   1. init: vẽ khung chờ trước, rồi mới đợi i18n
 *   2. refresh: xin ?slim=1 và gắn lại chi tiết của thẻ đang mở sau mỗi nhịp làm mới
 *   3. toggle: mở thẻ → một lượt lấy cả task đầy đủ lẫn nhật ký; có dòng «đang tải»
 *   4. thẻ ĐÓNG không đụng plan/result; thẻ MỞ mới đụng
 *   5. CSS + bản dịch 9 ngôn ngữ
 *
 * Run:  node tests/codex_slim_load_test.js     (exit 0 = pass)
 */
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const here = path.dirname(fileURLToPath(import.meta.url));
const dir = path.join(here, '..', 'tubecli', 'extensions', 'codex');
const js = fs.readFileSync(path.join(dir, 'static', 'codex.js'), 'utf-8').replace(/\r\n/g, '\n');
const css = fs.readFileSync(path.join(dir, 'static', 'codex.css'), 'utf-8').replace(/\r\n/g, '\n');
const py = fs.readFileSync(path.join(dir, 'routes.py'), 'utf-8').replace(/\r\n/g, '\n');

let failed = 0;
const check = (name, ok, detail) => {
  if (ok) { console.log('  ok   ' + name); return; }
  failed++;
  console.log('  FAIL ' + name + (detail !== undefined ? ' — ' + JSON.stringify(detail).slice(0, 300) : ''));
};
const slice = (a, b) => {
  const i = js.indexOf(a), j = js.indexOf(b, i + 1);
  if (i < 0 || j < 0) throw new Error('không cắt được ' + a);
  return js.slice(i, j);
};

console.log('── 1. Vẽ khung chờ TRƯỚC khi đợi i18n ──────────────────────');
const init = slice('async function init() {', 'document.addEventListener(\'DOMContentLoaded\'');
check('renderList chạy trước loadI18nFromApi', init.indexOf('renderList(true)') < init.indexOf('loadI18nFromApi'),
  [init.indexOf('renderList(true)'), init.indexOf('loadI18nFromApi')]);
check('…và vẫn trước lượt lấy dữ liệu', init.indexOf('renderList(true)') < init.indexOf('await refresh(false)'));
check('khung xương vẫn là thứ vẽ ra khi chưa có dữ liệu',
  /if \(!state\.loaded\) \{\s*return '<div class="cx-skeleton"/.test(js));
check('CSS khung xương còn nguyên', css.includes('.cx-skel-row') && css.includes('cx-shimmer'));

console.log('── 2. Danh sách GỌN ────────────────────────────────────────');
check('route nhận ?slim và bỏ đúng hai trường nặng',
  /async def list_tasks\(status: str = "", limit: int = 50, created_by: str = "", slim: int = 0\)/.test(py)
  && /DETAIL_ONLY_FIELDS = \("plan", "result"\)/.test(py));
check('route giữ dấu hiệu «có kết quả / có kế hoạch» cho thẻ đóng',
  /has_result=bool\(t\.get\("result"\)\)/.test(py) && /has_plan=bool\(t\.get\("plan"\)\)/.test(py));
check('route nói rõ đã gọn (máy khách cũ vẫn chạy như trước)', /"slim": bool\(slim\)/.test(py));
check('trang xin bản gọn', /api\('\/tasks\?slim=1&limit=' \+ TASK_LIMIT\)/.test(js));
const refresh = slice('async function refresh(manual)', 'function pauseClock');
check('nhớ cờ slim của máy chủ', /state\.slim = !!payload\.slim;/.test(refresh));
check('mỗi nhịp làm mới gắn LẠI chi tiết của thẻ đang mở (không xoá trắng kế hoạch đang xem)',
  /if \(state\.slim\) list\.forEach\(\(x\) => \{ const d = state\.detail\[x\.id\]; if \(d\) Object\.assign\(x, d\); \}\);/.test(refresh));

console.log('── 3. Mở thẻ mới tải chi tiết ──────────────────────────────');
const toggle = slice('async function toggle(taskId)', 'function setFilter(f)');
check('chỉ tải khi máy chủ gọn VÀ chưa có chi tiết', /if \(state\.slim && !state\.detail\[taskId\]\)/.test(toggle));
check('MỘT lượt lấy cả task lẫn nhật ký', /api\(taskUrl\(taskId, '\?events=200'\)\)/.test(toggle)
  && !/loadEvents\(taskId, true\);[\s\S]{0,80}api\(taskUrl/.test(toggle));
check('nhớ chi tiết để nhịp sau gắn lại', /state\.detail\[taskId\] = \{ plan: full\.plan \|\| \[\], result: full\.result \|\| '' \}/.test(toggle));
check('cờ «đang tải» luôn được dọn (finally)', /\} finally \{\s*delete state\.detailBusy\[taskId\];/.test(toggle));
check('vẽ lại ngay khi bật cờ để thấy dòng đang tải', /state\.detailBusy\[taskId\] = true;\s*renderList\(true\);/.test(toggle));
check('máy chủ CŨ (không gọn) vẫn đi đường cũ', /await loadEvents\(taskId, true\);/.test(toggle));
check('thân thẻ báo đang tải', /if \(state\.detailBusy\[task\.id\]\) \{[\s\S]{0,200}cx-detail-wait/.test(js));
check('CSS vòng xoay của dòng ấy', css.includes('.cx-detail-wait') && css.includes('.cx-spin-dot'));

console.log('── 4. Thẻ đóng không cần plan/result ───────────────────────');
const card = slice('function cardHtml(task)', 'function bodyHtml(task)');
const body = slice('function bodyHtml(task)', 'function eventsHtml');
check('thẻ ĐÓNG không đọc plan/result', !/task\.plan|task\.result/.test(card));
check('thẻ đóng vẫn vẽ dải bước (steps ở lại trong bản gọn)', /stripHtml\(task\)/.test(card) || /stripHtml\(/.test(js));
check('thẻ MỞ mới đọc plan/result', /task\.plan/.test(body) && /task\.result/.test(body));
check('state có ba ô mới', /slim: false,/.test(js) && /detail: \{\},/.test(js) && /detailBusy: \{\},/.test(js));

console.log('── 5. Bản dịch ─────────────────────────────────────────────');
const langs = ['en', 'vi', 'es', 'ja', 'ko', 'ru', 'tr', 'zh', 'zh-TW'];
const missing = langs.filter((c) => {
  const d = JSON.parse(fs.readFileSync(path.join(dir, 'locales', `${c}.json`), 'utf-8'));
  return !d['codex.loading_detail'];
});
check('codex.loading_detail có ở cả 9 ngôn ngữ', missing.length === 0, missing);
check('bản tiếng Việt viết bằng tiếng Việt',
  /Đang tải/.test(JSON.parse(fs.readFileSync(path.join(dir, 'locales', 'vi.json'), 'utf-8'))['codex.loading_detail']));

console.log(failed ? `\n${failed} HỎNG` : '\nTẤT CẢ ĐỀU PASS');
process.exit(failed ? 1 : 0);
