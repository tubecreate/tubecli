# -*- coding: utf-8 -*-
"""Từ điển gộp /api/v1/i18n/{lang}: đệm theo mtime, quét đĩa ngoài event loop, ?ns=, ETag/304 (25/9/2026).

Vì sao: dashboard tiếng Việt mở lên là tải vi + en (~264 + 288 KB trên đĩa, 31 tệp mỗi ngôn ngữ), mỗi
lượt GET quét lại thư mục locales của MỌI extension và json.loads NGAY TRONG route async (chặn event
loop của cả máy chủ), client gắn ?v=Date.now() nên trình duyệt không đệm được gì, và trang đợi xong
mới vẽ dữ liệu. Đo 25/9: gói riêng codex ≈ 18–20 KB, tức ~8 % gói trọn bộ (234–259 KB).

Kiểm (TestClient thật trên app thật — client loopback nên qua được cổng đăng nhập; cây locales TẠM,
không đọc data thật; không có gì ra mạng: pip/git của ExtensionManager bị thay bằng hàm rỗng TRƯỚC
khi import server):
  A. hình dạng phản hồi không đổi: dict phẳng, en lót dưới + <lang> đè lên, extension sau đè extension
     trước, thân giống hệt cách tuần tự hoá cũ, ?v= bị bỏ qua, lang lạ → en, tệp JSON hỏng bị bỏ qua
  B. ?ns=codex,common → chỉ khoá «codex.» / «common.»; đảo thứ tự ns → cùng ETag; ns rỗng = trọn bộ
  C. ETag + If-None-Match → 304 không thân; Cache-Control: no-cache (KHÔNG no-store); ETag đổi theo ns
  D. đệm: lượt sau không đọc lại tệp; sửa tệp (mtime đổi) → từ điển mới + ETag mới, không cần restart;
     cài / gỡ extension → khoá xuất hiện / biến mất
  E. khoá thiếu ở vi → mượn en (máy chủ) — và i18n.js vẫn tra _fallback từng khoá (client)
  F. quét đĩa + parse chạy trong luồng phụ (không có event loop đang chạy ở đó)
  G. i18n.js (tĩnh + chạy thật bằng node, fetch giả): không còn ?v=Date.now(); ns= qua opts /
     window.I18N_NS; đã có ngôn ngữ trong localStorage thì xin từ điển NGAY, /settings/language chạy
     song song; máy chủ nói khác thì tải lại; tên hàm cũ T/applyI18n/loadI18nFromApi/changeLanguage
     còn nguyên

Run:  python tests/i18n_bundle_test.py     (exit 0 = pass)
"""
import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

PASS = FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", label)
    else:
        FAIL += 1
        print("  FAIL", label, "—", str(detail)[:400])


TMP = Path(tempfile.mkdtemp(prefix="i18n_bundle_"))

# ── Cách ly TRƯỚC khi import server ──────────────────────────────────────────
# server.py chạy extension_manager.discover_extensions() + register_api_routes() ngay lúc import.
# Trỏ mọi thư mục dữ liệu sang chỗ tạm và vô hiệu pip/git của ExtensionManager: bài này phải chạy
# offline và không được chạm vào data thật của máy đang phục vụ cổng 5295.
import tubecli.config as CFG  # noqa: E402

CFG.DATA_DIR = TMP / "data"
CFG.EXTENSIONS_EXTERNAL_DIR = CFG.DATA_DIR / "extensions_external"
CFG.EXTENSIONS_DATA_DIR = CFG.DATA_DIR / "extensions_data"
CFG.DATA_DIR.mkdir(parents=True)
import tubecli.core.extension_manager as EM  # noqa: E402

EM.DATA_DIR = CFG.DATA_DIR
EM.EXTENSIONS_EXTERNAL_DIR = CFG.EXTENSIONS_EXTERNAL_DIR
EM.EXTENSIONS_CONFIG_FILE = str(CFG.DATA_DIR / "extensions.json")
EM.ExtensionManager._ensure_extension_deps = lambda self, ext: None          # không pip
EM.ExtensionManager.ensure_essential_extensions = lambda self: None          # không git clone
EM.ExtensionManager.install_from_git = lambda self, *a, **k: {"status": "error", "message": "offline test"}

from fastapi.testclient import TestClient  # noqa: E402
import tubecli.api.server as srv  # noqa: E402

# ── Cây locales tạm ──────────────────────────────────────────────────────────
LOC = TMP / "locales_root"


def write_locale(ext, lang, data):
    d = LOC / ext / "locales"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{lang}.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


write_locale("codex", "en", {"codex": "Codex", "codex.title": "Tasks", "codex.only_en": "English only"})
write_locale("codex", "vi", {"codex": "Codex", "codex.title": "Việc"})
write_locale("common_ext", "en", {"common.save": "Save", "common.cancel": "Cancel"})
write_locale("common_ext", "vi", {"common.save": "Lưu", "common.cancel": "Huỷ"})
write_locale("fm", "en", {"fm.upload": "Upload", "shared.key": "from fm"})
write_locale("fm", "vi", {"fm.upload": "Tải lên"})
write_locale("zz_last", "en", {"shared.key": "from zz_last"})
(LOC / "broken" / "locales").mkdir(parents=True)
(LOC / "broken" / "locales" / "en.json").write_text("{not json", encoding="utf-8")
(LOC / "no_locales").mkdir()
(LOC / "stray.txt").write_text("x", encoding="utf-8")

srv._i18n_locale_roots = lambda: [str(LOC), str(TMP / "does_not_exist")]
srv._I18N_CACHE.clear()
# Loopback: cổng đăng nhập của server miễn cho chính máy (không kèm header proxy).
c = TestClient(srv.app, client=("127.0.0.1", 50505))
URL = "/api/v1/i18n/"


def old_merge(lang):
    """Thuật toán CŨ của route (trước 25/9) chạy trên cây tạm — mốc so «hình dạng không đổi»."""
    merged = {}
    for entry in os.listdir(LOC):
        locales_dir = LOC / entry / "locales"
        if not locales_dir.is_dir():
            continue
        for try_lang in (["en", lang] if lang != "en" else ["en"]):
            p = locales_dir / f"{try_lang}.json"
            if not p.is_file():
                continue
            try:
                merged.update(json.loads(p.read_text(encoding="utf-8")))
            except Exception:
                pass
    return merged


def old_body(lang):
    return json.dumps(old_merge(lang), ensure_ascii=False, allow_nan=False, indent=None,
                      separators=(",", ":")).encode("utf-8")


print("── A. hình dạng phản hồi không đổi ─────────────────────────")
r = c.get(URL + "vi?v=1758700000000")
ok(r.status_code == 200 and r.headers.get("content-type", "").startswith("application/json"),
   "GET /api/v1/i18n/vi (kèm ?v= cũ) → 200 JSON", (r.status_code, r.headers.get("content-type")))
d = r.json()
ok(isinstance(d, dict) and all(isinstance(v, str) for v in d.values()) and len(d) == len(old_merge("vi")),
   "dict phẳng, đủ khoá như thuật toán cũ", (len(d), len(old_merge("vi"))))
ok(d.get("codex.title") == "Việc" and d.get("common.save") == "Lưu" and d.get("fm.upload") == "Tải lên",
   "vi đè lên en", d)
ok(d.get("codex") == "Codex" and d.get("codex.only_en") == "English only", "khoá không có ở vi vẫn còn (mượn en)")
ok(d.get("shared.key") == old_merge("vi")["shared.key"],
   "extension sau đè extension trước, đúng thứ tự os.listdir như cũ", d.get("shared.key"))
ok(r.content == old_body("vi"), "thân phản hồi giống hệt từng byte cách tuần tự hoá cũ (JSONResponse)")
r_en = c.get(URL + "en")
ok(r_en.status_code == 200 and r_en.json().get("codex.title") == "Tasks" and r_en.content == old_body("en"),
   "en: chỉ en.json, giống hệt cũ", r_en.text[:200])
r_bad = c.get(URL + "DROP%20TABLE")
ok(r_bad.status_code == 200 and r_bad.content == r_en.content, "lang lạ → coi như en (như cũ)", r_bad.status_code)
r_tw = c.get(URL + "zh-TW")
ok(r_tw.status_code == 200 and r_tw.content == r_en.content, "zh-TW hợp lệ, không có tệp → rơi về en")
ok("broken" not in r.text and len(d) > 0, "tệp JSON hỏng bị bỏ qua, không làm gãy từ điển")

print("── B. ?ns= ─────────────────────────────────────────────────")
full = d
r = c.get(URL + "vi", params={"ns": "codex,common"})
d = r.json()
want = {k: v for k, v in full.items() if k.startswith(("codex.", "common."))}
ok(r.status_code == 200 and d == want, "ns=codex,common → chỉ khoá codex./common.", (r.status_code, d))
ok("codex" not in d and "fm.upload" not in d, "khoá trần «codex» và khoá nhóm khác không lọt vào")
ok(list(d) == [k for k in full if k in want], "thứ tự khoá giữ như từ điển gộp")
etag_ns = r.headers.get("etag")
r2 = c.get(URL + "vi", params={"ns": " common , codex. ,,"})
ok(r2.json() == d and r2.headers.get("etag") == etag_ns,
   "đảo thứ tự / khoảng trắng / chấm thừa → cùng thân, cùng ETag", (r2.headers.get("etag"), etag_ns))
r3 = c.get(URL + "vi", params={"ns": ""})
ok(r3.content == old_body("vi"), "ns rỗng → trọn bộ như không có ns")
r4 = c.get(URL + "vi", params={"ns": "no_such_prefix"})
ok(r4.status_code == 200 and r4.json() == {}, "ns không khớp gì → {} (200)", r4.text)
r5 = c.get(URL + "en", params={"ns": "codex"})
ok(r5.json() == {"codex.title": "Tasks", "codex.only_en": "English only"}, "ns trên en cũng lọc", r5.text)

print("── C. ETag / If-None-Match / Cache-Control ─────────────────")
r1 = c.get(URL + "vi")
etag = r1.headers.get("etag")
ok(bool(etag) and etag == '"%s"' % hashlib.sha1(r1.content).hexdigest(),
   "ETag = sha1 của thân, có ngoặc kép", etag)
ok(r1.headers.get("cache-control") == "no-cache", "Cache-Control: no-cache (hỏi lại, giữ bản đã tải)",
   r1.headers.get("cache-control"))
ok("no-store" not in r1.headers.get("cache-control", ""), "không no-store")
r2 = c.get(URL + "vi", headers={"If-None-Match": etag})
ok(r2.status_code == 304 and r2.content == b"", "If-None-Match khớp → 304 không thân", (r2.status_code, r2.content[:50]))
ok(r2.headers.get("etag") == etag and r2.headers.get("cache-control") == "no-cache",
   "304 vẫn mang ETag + Cache-Control", dict(r2.headers))
r3 = c.get(URL + "vi", headers={"If-None-Match": 'W/%s, "something-else"' % etag})
ok(r3.status_code == 304, "dạng yếu W/… trong danh sách cũng khớp", r3.status_code)
r4 = c.get(URL + "vi", headers={"If-None-Match": '"stale"'})
ok(r4.status_code == 200 and r4.content == r1.content, "ETag cũ → 200 thân đầy đủ", r4.status_code)
ok(etag != etag_ns and etag != r_en.headers.get("etag"), "ETag khác nhau giữa trọn bộ / ns / ngôn ngữ")
ok(c.get(URL + "vi?v=123", headers={"If-None-Match": etag}).status_code == 304,
   "?v= của client cũ không làm lệch ETag")

print("── D. đệm theo mtime ───────────────────────────────────────")
calls = []
_orig_merge = srv._i18n_merge
srv._i18n_merge = lambda files: (calls.append(len(files)), _orig_merge(files))[1]
srv._I18N_CACHE.clear()
c.get(URL + "vi")
c.get(URL + "vi")
c.get(URL + "vi", params={"ns": "codex"})
c.get(URL + "vi", headers={"If-None-Match": etag})
# 8 tệp: 7 tệp lành + en.json «hỏng» (vẫn được quét, chỉ bị bỏ qua khi parse).
N_FILES = len(srv._i18n_locale_files("vi"))
ok(N_FILES == 8 and calls == [N_FILES], "bốn lượt (trọn bộ, ns, 304) → đọc + parse tệp đúng MỘT lần", (N_FILES, calls))
p = LOC / "codex" / "locales" / "vi.json"
p.write_text(json.dumps({"codex": "Codex", "codex.title": "Việc cần làm"}, ensure_ascii=False), encoding="utf-8")
st = p.stat()
os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))   # chắc chắn mtime đổi, kể cả FS thô
r = c.get(URL + "vi", headers={"If-None-Match": etag})
ok(r.status_code == 200 and r.json().get("codex.title") == "Việc cần làm",
   "sửa tệp locale → từ điển mới ngay, không cần restart", (r.status_code, r.text[:120]))
ok(r.headers.get("etag") != etag, "ETag đổi theo nội dung", r.headers.get("etag"))
ok(calls == [N_FILES, N_FILES], "dựng lại đúng một lần", calls)
etag2 = r.headers.get("etag")
ok(c.get(URL + "vi", params={"ns": "codex"}).json().get("codex.title") == "Việc cần làm",
   "bản đệm theo ns cũng được làm mới")
write_locale("new_ext", "en", {"newext.hello": "Hello"})
ok(c.get(URL + "vi").json().get("newext.hello") == "Hello", "cài extension mới → khoá xuất hiện")
shutil.rmtree(LOC / "new_ext")
r = c.get(URL + "vi")
ok("newext.hello" not in r.json() and r.headers.get("etag") == etag2,
   "gỡ extension → khoá biến mất, ETag quay về như trước khi cài", r.headers.get("etag"))
ok(calls == [N_FILES, N_FILES, N_FILES + 1, N_FILES], "mỗi lần cây đổi mới đọc lại; không đổi thì không", calls)
srv._i18n_merge = _orig_merge

print("── E. rơi về tiếng Anh từng khoá ───────────────────────────")
d = c.get(URL + "vi").json()
ok(d.get("codex.only_en") == "English only" and d.get("codex.title") == "Việc cần làm",
   "khoá vi thiếu → chuỗi en; khoá vi có → chuỗi vi")
ok(c.get(URL + "vi", params={"ns": "codex"}).json().get("codex.only_en") == "English only",
   "lọc ns vẫn giữ khoá mượn en")

print("── F. quét đĩa ngoài event loop ───────────────────────────")
where = []
_orig_bundle = srv._i18n_bundle


def _spy_bundle(lang, ns_key):
    try:
        asyncio.get_running_loop()
        where.append("event-loop")
    except RuntimeError:
        where.append("worker-thread")
    return _orig_bundle(lang, ns_key)


srv._i18n_bundle = _spy_bundle
srv._I18N_CACHE.clear()
c.get(URL + "vi")
ok(where == ["worker-thread"], "quét + parse chạy trong luồng phụ (asyncio.to_thread), không trong event loop", where)
srv._i18n_bundle = _orig_bundle
ok(isinstance(srv._I18N_LOCK, type(__import__("threading").Lock())), "có khoá chống dựng đúp")

print("── G. i18n.js ─────────────────────────────────────────────")
JS_PATH = ROOT / "tubecli" / "extensions" / "webui" / "static" / "i18n.js"
JS = JS_PATH.read_text(encoding="utf-8")
# Chỉ soát MÃ, không soát chú thích (chú thích có nhắc tới Date.now() để kể vì sao bỏ).
import re  # noqa: E402

JS_CODE = re.sub(r"/\*.*?\*/", "", JS, flags=re.S)
JS_CODE = re.sub(r"(^|[^:'\"])//[^\n]*", r"\1", JS_CODE)
ok("new Date()" not in JS_CODE and "Date.now(" not in JS_CODE, "không còn ?v=Date.now() phá cache")
ok("'ns='" in JS and "window.I18N_NS" in JS, "gửi ns=, nhận window.I18N_NS")
ok("TUBECLI_VERSION" in JS, "phiên bản ổn định (nếu trang khai) thay cho mốc giờ")
for sig in ("function T(key, vars)", "function applyI18n()", "async function loadI18nFromApi(",
            "async function changeLanguage(lang)", "function _resolves(key)",
            "if (_resolves(key)) el.textContent = T(key);"):
    ok(sig in JS, f"giữ nguyên {sig}")

# Chạy thật i18n.js trong node với DOM + fetch giả: fetch chỉ ghi lại URL và đợi test trả lời,
# nên thứ tự phát request (song song hay nối đuôi) đo được chính xác.
HARNESS = r"""
const fs = require('fs'), vm = require('vm');
const src = fs.readFileSync(process.argv[2], 'utf8');
const store = {};
global.localStorage = {
  getItem: k => (k in store ? store[k] : null),
  setItem: (k, v) => { store[k] = String(v); },
  removeItem: k => { delete store[k]; },
};
global.window = global;
global.location = { origin: 'http://127.0.0.1:5295', reload() { global._reloaded = true; } };
global.document = { documentElement: { lang: '' }, querySelectorAll: () => [], querySelector: () => null };
let calls = [];
global.fetch = (url) => new Promise((resolve, reject) => { calls.push({ url, resolve, reject }); });
vm.runInThisContext(src);
const okJson = obj => ({ ok: true, json: async () => obj });
const tick = async () => { for (let i = 0; i < 5; i++) await new Promise(r => setImmediate(r)); };
const find = part => calls.find(c => c.url.includes(part));
const urls = () => calls.map(c => c.url.replace('http://127.0.0.1:5295', ''));
const out = {};

(async () => {
  // 1. localStorage đã có 'vi', máy chủ cũng nói 'vi' → cả ba request đi CÙNG LÚC, trước khi có trả lời
  calls = []; store.tubecli_lang = 'vi';
  let p = loadI18nFromApi({ ns: ['codex', 'common'] });
  await tick();
  out.s1_urls_before_any_reply = urls();
  find('/settings/language').resolve(okJson({ language: 'vi' }));
  find('/i18n/vi').resolve(okJson({ 'codex.title': 'Việc' }));
  find('/i18n/en').resolve(okJson({ 'codex.title': 'Tasks', 'common.only_en': 'English only' }));
  await p;
  out.s1 = { t_vi: T('codex.title'), t_fallback: T('common.only_en'), t_missing: T('nope.key'),
             lang: vm.runInThisContext('_lang'), stored: store.tubecli_lang, calls: calls.length,
             doc_lang: document.documentElement.lang };

  // 2. localStorage 'vi' nhưng máy chủ nói 'ja' → tải lại đúng ngôn ngữ, ghi nhớ 'ja'
  calls = []; store.tubecli_lang = 'vi';
  p = loadI18nFromApi({ ns: 'codex' });
  await tick();
  find('/i18n/vi').resolve(okJson({ 'codex.title': 'Việc' }));
  find('/i18n/en').resolve(okJson({ 'codex.title': 'Tasks' }));
  find('/settings/language').resolve(okJson({ language: 'ja' }));
  await tick();
  out.s2_urls = urls();
  const ja = find('/i18n/ja');
  if (ja) ja.resolve(okJson({ 'codex.title': 'タスク' }));
  const en2 = calls.filter(c => c.url.includes('/i18n/en'))[1];
  if (en2) en2.resolve(okJson({ 'codex.title': 'Tasks' }));
  await p;
  out.s2 = { t: T('codex.title'), lang: vm.runInThisContext('_lang'), stored: store.tubecli_lang };

  // 3. localStorage trống (lần đầu) → hỏi máy chủ TRƯỚC, rồi mới xin từ điển; ghi nhớ ngôn ngữ
  calls = []; delete store.tubecli_lang;
  p = loadI18nFromApi();
  await tick();
  out.s3_urls_before_reply = urls();
  find('/settings/language').resolve(okJson({ language: 'vi' }));
  await tick();
  out.s3_urls_after_reply = urls();
  find('/i18n/vi').resolve(okJson({ 'codex.title': 'Việc' }));
  find('/i18n/en').resolve(okJson({ 'codex.title': 'Tasks' }));
  await p;
  out.s3 = { lang: vm.runInThisContext('_lang'), stored: store.tubecli_lang, t: T('codex.title') };

  // 4. /settings/language hỏng, localStorage 'vi' → vẫn có từ điển vi
  calls = []; store.tubecli_lang = 'vi';
  p = loadI18nFromApi();
  await tick();
  find('/settings/language').reject(new Error('offline'));
  find('/i18n/vi').resolve(okJson({ 'codex.title': 'Việc' }));
  find('/i18n/en').resolve(okJson({ 'codex.title': 'Tasks' }));
  await p;
  out.s4 = { lang: vm.runInThisContext('_lang'), t: T('codex.title'), stored: store.tubecli_lang };

  // 5. window.I18N_NS (chuỗi) không cần opts; không khai → không có ns=; TUBECLI_VERSION → v= ổn định
  calls = []; global.I18N_NS = 'codex';
  p = loadI18nFromApi();
  await tick();
  out.s5_ns_urls = urls();
  find('/settings/language').resolve(okJson({ language: 'vi' }));
  find('/i18n/vi').resolve(okJson({})); find('/i18n/en').resolve(okJson({}));
  await p;
  delete global.I18N_NS; calls = [];
  p = loadI18nFromApi();
  await tick();
  out.s5_plain_urls = urls();
  find('/settings/language').resolve(okJson({ language: 'vi' }));
  find('/i18n/vi').resolve(okJson({})); find('/i18n/en').resolve(okJson({}));
  await p;
  global.TUBECLI_VERSION = '2026.08.09.155'; calls = [];
  p = loadI18nFromApi();
  await tick();
  out.s5_version_urls = urls();
  find('/settings/language').resolve(okJson({ language: 'vi' }));
  find('/i18n/vi').resolve(okJson({})); find('/i18n/en').resolve(okJson({}));
  await p;
  delete global.TUBECLI_VERSION;

  // 6. từ điển vi hỏng (HTTP lỗi) nhưng en tải được → dùng trọn en, như cũ
  calls = []; store.tubecli_lang = 'vi';
  p = loadI18nFromApi();
  await tick();
  find('/settings/language').resolve(okJson({ language: 'vi' }));
  find('/i18n/vi').resolve({ ok: false, status: 500, json: async () => ({}) });
  find('/i18n/en').resolve(okJson({ 'codex.title': 'Tasks' }));
  await p;
  out.s6 = { t: T('codex.title') };

  console.log('RESULT ' + JSON.stringify(out));
})().catch(e => { console.log('RESULT ' + JSON.stringify({ error: String(e && e.stack || e) })); });
"""
node = shutil.which("node")
if not node:
    print("  (bỏ qua phần chạy node: không tìm thấy node trên PATH)")
else:
    harness = TMP / "i18n_harness.js"
    harness.write_text(HARNESS, encoding="utf-8")
    proc = subprocess.run([node, str(harness), str(JS_PATH)], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=60)
    line = next((ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT ")), None)
    res = json.loads(line[len("RESULT "):]) if line else {"error": (proc.stdout + proc.stderr)[-800:]}
    ok("error" not in res, "i18n.js chạy trong node không lỗi", res.get("error"))
    if "error" not in res:
        u1 = res["s1_urls_before_any_reply"]
        ok(len(u1) == 3 and any("/settings/language" in u for u in u1) and any("/i18n/vi?" in u for u in u1)
           and any("/i18n/en?" in u for u in u1),
           "đã có ngôn ngữ trong localStorage → /settings/language + hai từ điển đi CÙNG LÚC", u1)
        ok(all("ns=codex%2Ccommon" in u for u in u1 if "/i18n/" in u), "cả hai từ điển mang ns=codex,common", u1)
        ok(not any("v=" in u for u in u1), "không gắn v= khi trang không khai phiên bản", u1)
        s1 = res["s1"]
        ok(s1["t_vi"] == "Việc" and s1["t_fallback"] == "English only" and s1["t_missing"] == "nope.key",
           "T(): vi → en → chính khoá (rơi về từng khoá như cũ)", s1)
        ok(s1["lang"] == "vi" and s1["stored"] == "vi" and s1["calls"] == 3 and s1["doc_lang"] == "vi",
           "máy chủ đồng ý → không tải thêm; _lang, localStorage, <html lang> đúng", s1)
        u2 = res["s2_urls"]
        ok(any("/i18n/ja?ns=codex" in u for u in u2) and len(u2) == 5,
           "máy chủ nói 'ja' khác localStorage → tải lại đúng ngôn ngữ (một lượt thêm)", u2)
        ok(res["s2"] == {"t": "タスク", "lang": "ja", "stored": "ja"}, "kết quả cuối theo máy chủ, localStorage ghi 'ja'", res["s2"])
        ok(res["s3_urls_before_reply"] == ["/api/v1/settings/language"],
           "localStorage trống → chỉ hỏi máy chủ trước (như cũ)", res["s3_urls_before_reply"])
        ok(len(res["s3_urls_after_reply"]) == 3 and any("/i18n/vi" in u for u in res["s3_urls_after_reply"]),
           "máy chủ trả lời xong mới xin từ điển", res["s3_urls_after_reply"])
        ok(res["s3"] == {"lang": "vi", "stored": "vi", "t": "Việc"}, "lần đầu: ghi nhớ ngôn ngữ để lần sau khỏi đợi", res["s3"])
        ok(res["s4"] == {"lang": "vi", "t": "Việc", "stored": "vi"}, "/settings/language hỏng → vẫn dùng ngôn ngữ đã nhớ", res["s4"])
        ok(all("ns=codex" in u for u in res["s5_ns_urls"] if "/i18n/" in u), "window.I18N_NS = 'codex' → ns=codex", res["s5_ns_urls"])
        ok(all("ns=" not in u and "?" not in u for u in res["s5_plain_urls"] if "/i18n/" in u),
           "không khai ns → URL trần, trọn bộ như cũ", res["s5_plain_urls"])
        ok(all("v=2026.08.09.155" in u for u in res["s5_version_urls"] if "/i18n/" in u),
           "window.TUBECLI_VERSION → ?v=<phiên bản> ổn định", res["s5_version_urls"])
        ok(res["s6"] == {"t": "Tasks"}, "từ điển vi hỏng → dùng trọn tiếng Anh (như cũ)", res["s6"])

# ── dọn ──────────────────────────────────────────────────────────────────────
shutil.rmtree(TMP, ignore_errors=True)

print()
print("=" * 62)
print(f"{PASS}/{PASS + FAIL} PASS" if not FAIL else f"{PASS}/{PASS + FAIL} PASS — {FAIL} HỎNG")
sys.exit(1 if FAIL else 0)
