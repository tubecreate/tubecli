/**
 * Bảng việc nạp nhanh (20/9 → 25/9/2026): khung chờ trước, danh sách dòng GỌN có ETag, mở thẻ mới tải chi tiết.
 *
 * VÌ SAO CÓ FILE NÀY
 *   User: «load ban đầu quá chậm», «cuộn xuống nhiều quá mới thấy đang chạy tới bước nào». Đo 25/9: /tasks?slim=1
 *   = 371 KB cho 119 task (steps 52 %, goal 20 %), tải lại MỖI 5 GIÂY; chữ giao diện 262 KB; init đợi chữ rồi mới
 *   lấy danh sách. Nay:
 *     1. init: vẽ khung chờ trước; chữ và danh sách tải SONG SONG.
 *     2. refresh: xin ?view=board (mỗi task một dòng: tên, meta, tóm tắt bước — không goal/steps/plan/result), gửi
 *        If-None-Match → 304 rỗng khi không đổi; gắn lại chi tiết của thẻ đang mở.
 *     3. toggle: mở thẻ → một lượt lấy task đầy đủ + nhật ký (loadDetail); có dòng «đang tải».
 *     4. thẻ ĐÓNG có dòng «Đang: bước · k/N · %»; thẻ MỞ có dải Đang, rồi các bước, kết quả/lỗi, hoạt động, chi tiết.
 *     5. Chữ: trang chỉ xin phần `codex` (window.I18N_NS); 9 ngôn ngữ có khoá mới; tiếng Việt là «Bảng việc».
 *
 * Run:  node tests/codex_slim_load_test.js     (exit 0 = pass)
 */
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const here = path.dirname(fileURLToPath(import.meta.url));
const dir = path.join(here, '..', 'tubecli', 'extensions', 'codex');
const read = (p) => fs.readFileSync(p, 'utf-8').replace(/\r\n/g, '\n');
const js = read(path.join(dir, 'static', 'codex.js'));
const css = read(path.join(dir, 'static', 'codex.css'));
const html = read(path.join(dir, 'static', 'codex.html'));
const py = read(path.join(dir, 'routes.py'));
const mg = read(path.join(dir, 'manager.py'));

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

console.log('── 1. Khung chờ trước, chữ + danh sách song song ───────────');
const init = slice('async function init() {', 'document.addEventListener(\'DOMContentLoaded\'');
check('renderList chạy trước mọi lượt gọi mạng', init.indexOf('renderList(true)') < init.indexOf('loadI18nFromApi')
  && init.indexOf('renderList(true)') < init.indexOf('refresh(false)'));
check('không await i18n trước danh sách: cả hai trong một Promise.allSettled',
  /Promise\.allSettled\(\[refresh\(false\), loadSettings\(\), loadAssignees\(\), i18nReady\]\)/.test(init)
  && !/await loadI18nFromApi\(\)/.test(init));
check('khung xương vẫn là thứ vẽ ra khi chưa có dữ liệu',
  /if \(!state\.loaded\) \{\s*return '<div class="cx-skeleton"/.test(js));
check('trang chỉ xin phần chữ của bảng (window.I18N_NS) TRƯỚC i18n.js',
  html.indexOf("window.I18N_NS = ['codex']") >= 0 && html.indexOf("window.I18N_NS") < html.indexOf('/static/i18n.js'));

console.log('── 2. Danh sách dòng gọn + ETag ────────────────────────────');
check('route nhận view=board và giao cho _board_response', /if view == "board":\s*return _board_response\(/.test(py));
check('_board_response tính ETag không kể `now` và trả 304 khi khớp',
  /digest = hashlib\.sha1\(_json\.dumps\(body/.test(py) && /body\["now"\] = codex_manager\.server_now\(\)/.test(py)
  && py.indexOf('body["now"]') > py.indexOf('if request.headers.get("if-none-match") == etag:'));
check('dòng bảng KHÔNG mang goal/steps/plan/result', /BOARD_KEYS = \(/.test(mg)
  && !/BOARD_KEYS = \([^)]*"goal"/.test(mg) && !/BOARD_KEYS = \([^)]*"steps"/.test(mg) && /row\["summary"\] = step_summary\(t\)/.test(mg));
check('route file tĩnh: ETag + no-cache thay no-store', /def _static\(filepath: str, media: str, request: Request\)/.test(py)
  && /"Cache-Control": "no-cache"\}/.test(py));
const fb = slice('async function fetchBoard(offset, etag)', 'function applyBoard(data, append)');
check('trang gửi If-None-Match và hiểu 304', /headers\['If-None-Match'\] = etag/.test(fb) && /resp\.status === 304\) return \{ unchanged: true \}/.test(fb));
check('boardQuery xin view=board với nhóm/lọc/phân trang', /p\.set\('view', 'board'\)/.test(js) && /p\.set\('group'/.test(js) && /p\.set\('offset'/.test(js));
const apply = slice('function applyBoard(data, append)', 'function pickFirstFilter()');
check('mỗi nhịp gắn LẠI chi tiết của thẻ đang mở, nhưng trạng thái lấy của DÒNG BẢNG; lệch trạng thái thì bỏ chi tiết cũ',
  /if \(d\.status && x\.status && d\.status !== x\.status\) \{ delete state\.detail\[x\.id\]; return; \}/.test(apply)
  && /Object\.assign\(x, d, x\.status \? \{ status: x\.status \} : \{\}\)/.test(apply));
const after = slice('async function afterAction(taskId)', 'function approve(id)');
check('sau hành động: bỏ chi tiết cũ, tải bảng không ETag, thẻ mở tải lại chi tiết (26/9/2026: bấm Chạy lại phải F5)',
  /delete state\.detail\[taskId\];\s*state\.etag = '';/.test(after) && /loadDetail\(taskId, true\)/.test(after)
  && /delete state\.busy\[taskId\];\s*await afterAction\(taskId\);/.test(js) && /toast_retried[\s\S]{0,120}await afterAction\(rb\.id\);/.test(js));
check('không có gì chạy thì hỏi thưa hơn', /state\.tick % 4 !== 0\) return;/.test(js));

console.log('── 3. Mở thẻ mới tải chi tiết ──────────────────────────────');
const detail = slice('async function loadDetail(taskId, withEvents)', 'async function toggle(taskId)');
check('MỘT lượt lấy cả task lẫn nhật ký', /api\(taskUrl\(taskId, withEvents \? '\?events=200' : '\?events=0'\)\)/.test(detail));
check('nhớ chi tiết (goal, steps, plan, result…) để nhịp sau gắn lại', /state\.detail\[taskId\] = \{ goal: full\.goal/.test(detail));
check('cờ «đang tải» luôn được dọn (finally)', /\} finally \{\s*delete state\.detailBusy\[taskId\];/.test(detail));
const toggle = slice('async function toggle(taskId)', 'function setFilter(f)');
check('mở thẻ: vẽ ngay rồi mới tải', /state\.expanded\.add\(taskId\);\s*renderList\(true\);\s*try \{\s*await loadDetail\(taskId, true\);/.test(toggle));
check('thân thẻ báo đang tải', /if \(state\.detailBusy\[task\.id\] && !state\.detail\[task\.id\]\) \{[\s\S]{0,200}cx-detail-wait/.test(js));
check('CSS vòng xoay của dòng ấy', css.includes('.cx-detail-wait') && css.includes('.cx-spin-dot'));

console.log('── 4. Thẻ đóng 3 dòng, thẻ mở đúng thứ tự ─────────────────');
const card = slice('function cardHtml(task)', 'function metaChips(task)');
const body = slice('function bodyHtml(task)', '/** Phần đã xong của một bước');
check('thẻ ĐÓNG không đọc plan/result', !/task\.plan|task\.result/.test(card));
check('thẻ đóng: tên · thông số · dòng «Đang»', /metaChips\(task\)/.test(card) && /nowLineHtml\(task\)/.test(card));
const now = slice('function nowLineHtml(task)', 'function backlogPosition(task)');
check('dòng «Đang» có bước, k/N, %, thanh, và câu lỗi khi hỏng', /codex\.now_prefix/.test(now) && /cx-now-bar/.test(now)
  && /codex\.now_step/.test(now) && /st === 'failed'/.test(now));
check('thẻ MỞ: dải Đang → các bước → lỗi/kết quả → hoạt động → chi tiết (gấp)',
  body.indexOf('cx-now') < body.indexOf('section_steps') && body.indexOf('section_steps') < body.indexOf('section_error')
  && body.indexOf('section_error') < body.indexOf('section_result') && body.indexOf('section_result') < body.indexOf('section_events')
  && body.indexOf('section_events') < body.indexOf('section_details'));
check('mục tiêu + kế hoạch AI nằm trong «Chi tiết» gấp mặc định',
  /<details class="cx-section cx-fold">\s*<summary class="cx-section-title cx-fold-title">\$\{icon\('info'\)\}/.test(body)
  && /detailBits\.push\(`<div class="cx-section"><div class="cx-section-title">\$\{icon\('flag'\)\}\$\{esc\(t\('codex\.section_goal'\)\)\}/.test(body)
  && /section_details[\s\S]{0,400}detailBits\.join\(''\)/.test(body));
check('nút Chạy lại nằm cạnh ô lỗi', /section_error[\s\S]{0,400}openRetry/.test(body));
check('dải Đang ghim khi cuộn (CSS sticky)', /\.cx-now \{[^}]*position: sticky/.test(css));
check('không còn 8 ô thống kê; có thanh nhóm + bộ lọc', !/id="cx-stats"/.test(html) && /id="cx-segments"/.test(html) && /id="cx-filters"/.test(html));
check('đường về dashboard mở ở khung ngoài (không lồng trong iframe)', /class="cx-icon-btn cx-back" href="\/dashboard" target="_top"/.test(html));
check('một icon cho bảng: checklist', /cx-brand-icon">checklist</.test(html));

console.log('── 5. Bản dịch ─────────────────────────────────────────────');
const langs = ['en', 'vi', 'es', 'ja', 'ko', 'ru', 'tr', 'zh', 'zh-TW'];
const need = ['codex.loading_detail', 'codex.group_needs_you', 'codex.now_prefix', 'codex.stage_render', 'codex.action_accept_plan',
  'codex.section_details', 'codex.list_more', 'codex.meta_parent', 'codex.title', 'codex.subtitle', 'codex.nav'];
const missing = [];
for (const c of langs) {
  const d = JSON.parse(fs.readFileSync(path.join(dir, 'locales', `${c}.json`), 'utf-8'));
  for (const k of need) if (!d[k]) missing.push(`${c}:${k}`);
}
check('khoá mới có ở cả 9 ngôn ngữ', missing.length === 0, missing);
const vi = JSON.parse(fs.readFileSync(path.join(dir, 'locales', 'vi.json'), 'utf-8'));
check('tiếng Việt: «Bảng việc», không còn «Codex» ở tên trang', vi['codex.title'] === 'Bảng việc' && vi['codex.nav'] === 'Bảng việc');
check('tiếng Việt: trạng thái bằng lời thường', vi['codex.status_review'] === 'Chờ bạn duyệt' && vi['codex.status_backlog'] === 'Chờ đến lượt');
check('bản tiếng Việt của dòng đang tải viết bằng tiếng Việt', /Đang tải/.test(vi['codex.loading_detail']));

console.log(failed ? `\n${failed} HỎNG` : '\nTẤT CẢ ĐỀU PASS');
process.exit(failed ? 1 : 0);
