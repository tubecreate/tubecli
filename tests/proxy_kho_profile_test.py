"""Hồ sơ lấy proxy từ KHO (pool) thay cho một chuỗi gõ tay.

Chạy:  python tests/proxy_kho_profile_test.py      (mã thoát 0 = đạt)

Vì sao tệp này tồn tại. User 26/10/2026 gửi ảnh Profile Settings: «chưa có chỗ thêm nhóm proxy (pool
proxy)». Kho proxy có từ .73 nhưng hai form hồ sơ chỉ có ô gõ MỘT chuỗi, và ô «Xoay mỗi N phút» của kho
chỉ ghi proxy_rotate_minutes lên hồ sơ — không đường mở nào đọc lại (RelayManager.acquire không ai gọi).
Bài kiểm khoá: chọn / đổi proxy trước mỗi lần mở, route tạo / sửa hồ sơ nhận proxy_kho, móc vào cả ba
đường mở, và form trên bảng điều khiển gửi đúng trường.

Kho và thư mục hồ sơ đều trỏ sang thư mục tạm (TUBECLI_PROXY_STORE, TUBECLI_BROWSER_PROFILES_DIR): một
lượt kiểm định tự động từng ghi 419 proxy giả vào kho thật và gán cho 9 hồ sơ. Không gọi mạng nào.
"""
import asyncio
import io
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_TMP = tempfile.mkdtemp(prefix="tubecli_kho_prof_")
os.environ["TUBECLI_PROXY_STORE"] = os.path.join(_TMP, "proxy_center.json")
os.environ["TUBECLI_BROWSER_PROFILES_DIR"] = os.path.join(_TMP, "profiles")
os.makedirs(os.environ["TUBECLI_BROWSER_PROFILES_DIR"], exist_ok=True)

from tubecli.extensions.browser import proxy_pool as pool  # noqa: E402
from tubecli.extensions.browser import profile_manager as pm  # noqa: E402

failures = []
checks = 0


def check(label, ok, detail=""):
    global checks
    checks += 1
    print(("[PASS] " if ok else "[FAIL] ") + label + ("" if ok else f"  {detail}"))
    if not ok:
        failures.append(f"{label}: {detail}")


check("kho + hồ sơ kiểm thử KHÔNG trỏ vào dữ liệu thật",
      _TMP in pool.STORE and _TMP in pm.PROFILES_DIR, (pool.STORE, pm.PROFILES_DIR))


def make_profile(name, **cfg):
    os.makedirs(os.path.join(pm.PROFILES_DIR, name), exist_ok=True)
    base = {"tags": ["Windows", "Chrome"], "proxy": "", "browser_version": "ShardX 152.0.7977.65",
            "notes": "", "blacklist": []}
    base.update(cfg)
    pm._save_config(name, base)


def cfg(name):
    return pm._load_config(name)


def keys_in(kho):
    return {pool.key_of(p["proxy_str"]) for p in pool.list_proxies(kho)}


pool.create_kho("VN")
pool.create_kho("US")
pool.create_kho("Empty")
pool.add_proxies("VN", "10.0.0.1:8001:u1:p1\n10.0.0.2:8002:u2:p2\n10.0.0.3:8003:u3:p3")
pool.add_proxies("US", "20.0.0.1:9001:a:b")
VN = keys_in("VN")
check("kho VN có 3 proxy, US có 1", len(VN) == 3 and len(keys_in("US")) == 1, (VN, keys_in("US")))

# ── 1. clamp_rotate + kho_problem ───────────────────────────────────────────
check("clamp_rotate: rác → 0, âm → 0, quá trần → 1440, chuỗi số → số",
      pool.clamp_rotate(None) == 0 and pool.clamp_rotate("x") == 0 and pool.clamp_rotate(-5) == 0
      and pool.clamp_rotate(99999) == 1440 and pool.clamp_rotate("30") == 30 and pool.clamp_rotate(12.7) == 12)
check("kho_problem: kho tồn tại + có proxy → None", pool.kho_problem("VN") is None, pool.kho_problem("VN"))
check("kho_problem: kho không tồn tại → lý do", "does not exist" in (pool.kho_problem("Nope") or ""))
check("kho_problem: kho rỗng → lý do (chặn ngay lúc gắn)", "no usable proxy" in (pool.kho_problem("Empty") or ""))
check("kho_problem: tên rỗng → lý do", bool(pool.kho_problem("  ")))

# ── 2. refresh_profile_proxy ────────────────────────────────────────────────
make_profile("manual", proxy="socks5://x:y@1.1.1.1:1080")
r = pool.refresh_profile_proxy("manual")
check("hồ sơ KHÔNG gắn kho → không đụng proxy", r["reason"] == "no_kho" and cfg("manual")["proxy"] == "socks5://x:y@1.1.1.1:1080", r)

make_profile("p1", proxy="", proxy_kho="VN", proxy_rotate_minutes=0)
r = pool.refresh_profile_proxy("p1", now=1000)
c = cfg("p1")
check("gắn kho, proxy rỗng → lấy một proxy TRONG kho + ghi mốc",
      r["changed"] and r["reason"] == "not_in_kho" and pool.key_of(c["proxy"]) in VN and c.get("proxy_assigned_at") == 1000, (r, c))
first = c["proxy"]
r = pool.refresh_profile_proxy("p1", now=999999)
check("rotate 0 → giữ nguyên dù đã lâu (lặp lại an toàn)", r["reason"] == "kept" and cfg("p1")["proxy"] == first, r)

make_profile("p2", proxy="socks5://old:old@9.9.9.9:1", proxy_kho="VN")
r = pool.refresh_profile_proxy("p2", now=2000)
check("proxy hiện tại KHÔNG thuộc kho (đổi kho / gõ tay cũ) → thay bằng proxy trong kho",
      r["reason"] == "not_in_kho" and pool.key_of(cfg("p2")["proxy"]) in VN, (r, cfg("p2")))
check("chọn proxy ÍT hồ sơ dùng nhất: p2 không trùng p1", pool.key_of(cfg("p2")["proxy"]) != pool.key_of(first),
      (cfg("p2")["proxy"], first))

make_profile("p3", proxy_kho="VN", proxy_rotate_minutes=30)
pool.refresh_profile_proxy("p3", now=10_000)
p3a = cfg("p3")["proxy"]
r = pool.refresh_profile_proxy("p3", now=10_000 + 29 * 60)
check("rotate 30: mới dùng 29 phút → giữ", r["reason"] == "kept" and cfg("p3")["proxy"] == p3a, r)
r = pool.refresh_profile_proxy("p3", now=10_000 + 31 * 60)
c = cfg("p3")
check("rotate 30: đã dùng 31 phút → proxy KẾ TIẾP (khác cái cũ) + mốc mới",
      r["reason"] == "rotated" and r["changed"] and pool.key_of(c["proxy"]) in VN
      and pool.key_of(c["proxy"]) != pool.key_of(p3a) and c["proxy_assigned_at"] == 10_000 + 31 * 60, (r, c))
r = pool.refresh_profile_proxy("p3", now=10_000 + 31 * 60 + 5)
check("gọi lần hai trong cùng lần mở → kept (launch_refusal + spawn cùng gọi)", r["reason"] == "kept", r)

make_profile("legacy", proxy="", proxy_kho="VN", proxy_rotate_minutes=15)
pool.refresh_profile_proxy("legacy", now=5)
c = cfg("legacy"); c.pop("proxy_assigned_at", None); pm._save_config("legacy", c)
r = pool.refresh_profile_proxy("legacy", now=50_000)
check("hồ sơ gán từ bản cũ (có rotate, chưa có mốc) → bắt đầu đếm, CHƯA đổi",
      r["reason"] == "clock_started" and cfg("legacy").get("proxy_assigned_at") == 50_000, r)

# proxy bị xoá khỏi kho → thay
pid = next(p["id"] for p in pool.list_proxies("VN") if pool.key_of(p["proxy_str"]) == pool.key_of(first))
pool.remove_proxies([pid])
r = pool.refresh_profile_proxy("p1", now=3000)
check("proxy đang dùng bị XOÁ khỏi kho → lần mở sau đổi sang proxy còn trong kho",
      r["reason"] == "not_in_kho" and pool.key_of(cfg("p1")["proxy"]) in keys_in("VN"), (r, cfg("p1")))

# kho rỗng / bị xoá → GIỮ proxy (không mở trần)
make_profile("p4", proxy="http://20.0.0.1:9001", proxy_kho="US")
pool.refresh_profile_proxy("p4", now=1)
keep = cfg("p4")["proxy"]
for p in pool.list_proxies("US"):
    pool.remove_proxies([p["id"]])
r = pool.refresh_profile_proxy("p4", now=999_999)
check("kho hết proxy → GIỮ proxy đang có, không xoá (mở trần = lộ IP thật)",
      r["reason"] == "kho_empty" and cfg("p4")["proxy"] == keep and keep, (r, cfg("p4")))
make_profile("p5", proxy="http://7.7.7.7:7", proxy_kho="Deleted kho")
r = pool.refresh_profile_proxy("p5")
check("kho không tồn tại → giữ proxy", r["reason"] == "kho_empty" and cfg("p5")["proxy"] == "http://7.7.7.7:7", r)
r = pool.refresh_profile_proxy("no-such-profile")
check("hồ sơ không tồn tại → no_kho, không ném lỗi", r["reason"] == "no_kho", r)

# ── 3. route tạo / sửa hồ sơ ────────────────────────────────────────────────
from tubecli.extensions.browser import routes  # noqa: E402
from fastapi import HTTPException  # noqa: E402

pm.get_fingerprint = lambda name: None          # create_profile gọi API vân tay — không gọi mạng
run = asyncio.run

res = run(routes.api_update_profile("manual", routes.ProfileUpdateRequest(proxy_kho="VN", proxy_rotate_minutes=45, proxy="socks5://ignored:x@3.3.3.3:3")))
c = cfg("manual")
check("PUT proxy_kho=VN: gắn kho, bỏ chuỗi proxy gửi kèm, proxy mới thuộc kho, rotate lưu",
      res["status"] == "updated" and c["proxy_kho"] == "VN" and c["proxy_rotate_minutes"] == 45
      and pool.key_of(c["proxy"]) in keys_in("VN") and "3.3.3.3" not in c["proxy"], c)
check("PUT trả hồ sơ ĐÃ đổi proxy (đọc lại config)", res["profile"]["proxy"] == c["proxy"], res["profile"])

res = run(routes.api_update_profile("manual", routes.ProfileUpdateRequest(proxy_kho="", proxy="http://8.8.8.8:80")))
c = cfg("manual")
check("PUT proxy_kho='': về nhập tay, giữ chuỗi gõ tay, rotate về 0",
      c["proxy_kho"] == "" and c["proxy"] == "http://8.8.8.8:80" and c["proxy_rotate_minutes"] == 0, c)
r = pool.refresh_profile_proxy("manual")
check("… và lần mở sau KHÔNG lấy proxy từ kho nữa", r["reason"] == "no_kho" and cfg("manual")["proxy"] == "http://8.8.8.8:80", r)

res = run(routes.api_update_profile("manual", routes.ProfileUpdateRequest(proxy="http://9.9.9.9:90")))
check("PUT không có proxy_kho (client cũ / Flow) → không đụng kho, sửa chuỗi như cũ",
      cfg("manual")["proxy"] == "http://9.9.9.9:90" and cfg("manual")["proxy_kho"] == "", cfg("manual"))

for bad, why in (("Nope", "does not exist"), ("Empty", "no usable proxy")):
    try:
        run(routes.api_update_profile("manual", routes.ProfileUpdateRequest(proxy_kho=bad)))
        check(f"PUT kho «{bad}» → 400", False, "không ném lỗi")
    except HTTPException as e:
        check(f"PUT kho «{bad}» → 400 kèm lý do", e.status_code == 400 and why in str(e.detail), e.detail)
check("… và hồ sơ giữ nguyên sau lần từ chối", cfg("manual")["proxy"] == "http://9.9.9.9:90")

res = run(routes.api_create_profile(routes.ProfileCreateRequest(name="newkho", proxy_kho="VN", proxy_rotate_minutes=99999)))
c = cfg("newkho")
check("POST tạo hồ sơ với proxy_kho: proxy trong kho NGAY từ đầu + kho + rotate kẹp 1440 + mốc",
      res["status"] == "created" and pool.key_of(c["proxy"]) in keys_in("VN") and c["proxy_kho"] == "VN"
      and c["proxy_rotate_minutes"] == 1440 and isinstance(c.get("proxy_assigned_at"), int), c)
try:
    run(routes.api_create_profile(routes.ProfileCreateRequest(name="shouldnotexist", proxy_kho="Empty")))
    check("POST kho rỗng → 400", False, "không ném lỗi")
except HTTPException as e:
    check("POST kho rỗng → 400, KHÔNG tạo thư mục hồ sơ",
          e.status_code == 400 and not os.path.isdir(os.path.join(pm.PROFILES_DIR, "shouldnotexist")), e.detail)
res = run(routes.api_create_profile(routes.ProfileCreateRequest(name="plain", proxy="http://1.2.3.4:5")))
c = cfg("plain")
check("POST không có proxy_kho → y như cũ (chuỗi gõ tay, không trường kho)",
      c["proxy"] == "http://1.2.3.4:5" and not c.get("proxy_kho"), c)

make_profile("a1"); make_profile("a2")
res = run(routes.api_proxy_assign(routes.ProxyAssignRequest(profiles=["a1", "a2"], kho="VN", rotate_minutes=-3)))
check("assign (hộp Kho Proxy) ghi mốc proxy_assigned_at + kẹp rotate",
      res["success"] and all(isinstance(cfg(n).get("proxy_assigned_at"), int) and cfg(n)["proxy_rotate_minutes"] == 0 for n in ("a1", "a2")),
      [cfg(n) for n in ("a1", "a2")])

# ── 4. móc vào MỌI đường mở ─────────────────────────────────────────────────
RT = io.open(ROOT / "tubecli/extensions/browser/routes.py", encoding="utf-8").read().replace("\r\n", "\n")
PMG = io.open(ROOT / "tubecli/extensions/browser/process_manager.py", encoding="utf-8").read().replace("\r\n", "\n")
lr = RT[RT.index("def launch_refusal("):][:900]
check("launch_refusal làm mới proxy TRƯỚC khi xét check_launch_blockers (xét trên proxy SẼ dùng)",
      "_refresh_kho_proxy(profile_name)" in lr and lr.index("_refresh_kho_proxy(profile_name)") < lr.index("check_launch_blockers(profile_name)"))
sp = RT[RT.index("async def _spawn_preview_server("):][:1600]
check("preview MỚI làm mới proxy; xem ghép --attach-cdp thì KHÔNG (phiên đang chạy giữ proxy)",
      'if "--attach-cdp" not in tuple(extra_args or ()):\n        _refresh_kho_proxy(profile)' in sp)
spawn = PMG[PMG.index("    def spawn("):][:3500]
check("process_manager.spawn làm mới proxy TRƯỚC _build_args, lỗi không chặn việc mở",
      "refresh_profile_proxy(profile)" in spawn and spawn.index("refresh_profile_proxy(profile)") < spawn.index("self._build_args(")
      and "except Exception as e:" in spawn[spawn.index("refresh_profile_proxy(profile)"):][:200])
helper = RT[RT.index("def _refresh_kho_proxy("):][:900]
check("_refresh_kho_proxy nuốt mọi lỗi (kho hỏng không chặn mở)", "except Exception as e:" in helper)

# ── 5. bảng điều khiển ─────────────────────────────────────────────────────
APP = io.open(ROOT / "tubecli/extensions/webui/static/app.js", encoding="utf-8").read().replace("\r\n", "\n")
try:
    subprocess.run(["node", "--check", str(ROOT / "tubecli/extensions/webui/static/app.js")], check=True, capture_output=True, timeout=60)
    check("app.js cú pháp hợp lệ (node --check)", True)
except Exception as e:  # noqa: BLE001
    check("app.js cú pháp hợp lệ (node --check)", False, getattr(e, "stderr", e))
for fn in ("mountProxySource", "fillProxySources", "syncProxySource", "proxySourceValue", "openPoolFromProfile"):
    check(f"app.js có {fn}()", f"function {fn}(" in APP)
check("Profile Settings gắn ô chọn nguồn với kho + rotate đã lưu",
      "mountProxySource('settings', { kho: data.proxy_kho || '', rotate: data.proxy_rotate_minutes || 0 });" in APP)
check("form tạo hồ sơ gắn ô chọn nguồn", "mountProxySource('profile', { kho: '', rotate: 0 });" in APP)
sv = APP[APP.index("async function saveProfileSettings()"):][:2200]
check("lưu: gắn kho → proxy_kho + rotate, KHÔNG gửi chuỗi; nhập tay → chuỗi + proxy_kho ''",
      "if (src && src.kho) { payload.proxy_kho = src.kho; payload.proxy_rotate_minutes = src.rotate; }" in sv
      and "else { payload.proxy = proxy; if (src) payload.proxy_kho = ''; }" in sv
      and "proxy: proxy," not in sv)
check("chưa nạp xong ô chọn → proxySourceValue null (lưu sớm không gỡ kho)",
      "if (!sel || !sel.dataset.ready) return null;" in APP and "delete sel.dataset.ready;" in APP)
cp = APP[APP.index("async function createProfile()"):][:2600]
check("tạo: gửi proxy_kho khi chọn kho; lỗi giữ form mở + nói lý do",
      "body.proxy_kho = src.kho" in cp and "if (!res || res.detail || res.error) {" in cp
      and cp.index("if (!res || res.detail || res.error) {") < cp.index("closeModal('modal-profile');"))
check("nút «Quản lý kho» mở hộp Kho Proxy và nạp lại kho khi hộp đóng",
      "await showProxyPoolModal();" in APP and "if (document.getElementById('modal-proxy-pool')) return;" in APP)
check("ô chọn chèn bằng JS (index.html không đổi): không có id proxy-src tĩnh",
      "proxy-src" not in io.open(ROOT / "tubecli/extensions/webui/static/index.html", encoding="utf-8").read())

# ── 5b. thẻ hồ sơ: proxy không tràn, không lộ mật khẩu (user 26/10/2026, ảnh thẻ bas-001) ──────────
card = APP[APP.index("else h += '<div class=\"cards-grid\">' + profiles.map(p => {"):][:4000]
check("thẻ hồ sơ KHÔNG còn in nguyên p.proxy", "esc(p.proxy||T('browser.no_proxy'))" not in card)
check("thẻ hồ sơ: một dòng, cắt «…», hiện bản đã che + tên kho",
      'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%' in card
      and "maskProxy(p.proxy)" in card and "p.proxy_kho ?" in card)
_mask_js = APP[APP.index("function maskProxy("):APP.index("function getBrowserBody(")]
_cases = ["socks5://snqswdvxag:SECRETPW@mobile.socksnode.com:29694", "u:p@1.2.3.4:8080",
          "103.179.188.215:30981:5o7y:5o7y", "http://1.2.3.4:8080", "socks5://user:p@ss@host.com:1080", ""]
try:
    _out = subprocess.run(["node", "-e", _mask_js + ";\nconsole.log(JSON.stringify(" + json.dumps(_cases) + ".map(maskProxy)))"],
                          capture_output=True, text=True, encoding="utf-8", timeout=60).stdout
    _res = json.loads(_out)
except Exception as e:  # noqa: BLE001
    _res = [str(e)] * len(_cases)
check("maskProxy che đăng nhập ở cả ba dạng, giữ scheme + host:port",
      _res[:3] == ["socks5://•••@mobile.socksnode.com:29694", "•••@1.2.3.4:8080", "103.179.188.215:30981:•••"], _res)
check("maskProxy: không đăng nhập → giữ nguyên; mật khẩu có «@» vẫn che; rỗng → rỗng",
      _res[3] == "http://1.2.3.4:8080" and _res[4] == "socks5://•••@host.com:1080" and _res[5] == "", _res)
check("maskProxy không để lọt mật khẩu", not any("SECRETPW" in r or "5o7y" in r for r in _res), _res)

# ── 6. 9 locale ─────────────────────────────────────────────────────────────
KEYS = ["proxy_src_manual", "proxy_src_kho", "proxy_manage_pool", "proxy_rotate_after", "proxy_rotate_unit",
        "proxy_from_pool_ph", "proxy_kho_empty", "proxy_kho_hint", "proxy_kho_missing"]
for lang in ["en", "vi", "zh", "zh-TW", "ja", "ko", "es", "tr", "ru"]:
    d = json.load(io.open(ROOT / f"tubecli/extensions/browser/locales/{lang}.json", encoding="utf-8"))
    miss = [k for k in KEYS if f"browser.{k}" not in d]
    check(f"locale {lang}: đủ {len(KEYS)} khoá mới", not miss, miss)
    check(f"locale {lang}: placeholder {{name}}/{{live}}/{{total}}",
          all(x in d.get("browser.proxy_src_kho", "") for x in ("{name}", "{live}", "{total}"))
          and "{name}" in d.get("browser.proxy_kho_empty", ""))
    if lang != "en":
        check(f"locale {lang}: ô xoay của hộp Kho Proxy đã dịch (hết «Rotate every» tiếng Anh)",
              d.get("browser.pp_rotate_every") != "Rotate every" and d.get("browser.pp_minutes_zero_off") != "minutes (0 = never)")
    check(f"locale {lang}: ô xoay nói rõ đổi ở LẦN MỞ kế tiếp (không hứa đổi giữa phiên)",
          d.get("browser.pp_minutes_zero_off") != "minutes (0 = never)")

print(f"\n{checks - len(failures)}/{checks} PASS")
sys.exit(1 if failures else 0)
