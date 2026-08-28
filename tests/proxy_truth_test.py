"""Proxy nào THẬT SỰ chạy được, và lượt mở hỏng phải bị từ chối chứ không vào sổ "running".

Run:  python tests/proxy_truth_test.py     (exit 0 = pass)

Bối cảnh (2026-08-28): lịch chạy 23/23 lượt mở 0 trang, nhưng run_log ghi "running" cho
tất cả — process_manager.spawn() chỉ chờ 1 giây rồi tuyên bố thành công, còn lỗi khoá BAS
nổ ở giây thứ ~10. Đo trên 102 thư mục profile: 76 có config.json, 14 có proxy, trong đó
12 là SOCKS5 CÓ MẬT KHẨU.

Sự thật về proxy, đo bằng chính engine đã cài (149.0.7827.103, chrome.exe --headless
--dump-dom https://api.ipify.org):
  • socks5://host:port:user:pass (dạng nhà cung cấp) -> ERR_NO_SUPPORTED_PROXIES
  • sock5s://...  (gõ nhầm scheme)                   -> ERR_NO_SUPPORTED_PROXIES
  • socks5://host:port  (mật khẩu đã rụng)           -> ERR_PROXY_CONNECTION_FAILED
  • http://host:port    (mật khẩu đã rụng)           -> ERR_PROXY_CONNECTION_FAILED
  • không proxy                                      -> mở được, trả IP thật
KHÔNG có ca nào rò IP: Chromium từ chối hẳn chứ không âm thầm đi thẳng.

Kiểm ở đây:
  A. parse_proxy đọc đúng BA dạng, và KHÔNG lặp lại lỗi đảo thứ tự của
     browser_manager.normalizeProxy (regex :1790 gán [user,pass,host,port] cho một chuỗi
     thật ra là [host,port,user,pass]).
  B. proxy_blocker chỉ chặn nhánh ShardX — nhánh BAS tự cắm proxy nên không đoán thay.
  C. Ngoại lệ has_local_fp KHÔNG được thắng bằng chứng: một lượt mở thật chết vì khoá thì
     chặn, kể cả profile có fingerprint_saved.json.
  D. note_launch_output nhận ra các câu lỗi khoá, kể cả "FingerprintSwitcher key is
     missing" — ca chưa test nào phủ.
"""
import os
import sys
import json
import shutil
import asyncio
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tubecli.extensions.browser import routes as R
from tubecli.extensions.browser import profile_manager as PM
from tubecli.extensions.browser import shardx_runtime as SX

checks = 0
failures = []


def ok(label, cond, detail=""):
    global checks
    checks += 1
    if cond:
        print(f"[PASS] {label}" + (f"  ({detail})" if detail else ""))
    else:
        print(f"[FAIL] {label}  ({detail})")
        failures.append(label)


def eq(label, got, want):
    ok(label, got == want, f"got={got!r} want={want!r}")


print("=" * 70)
print("PROXY TRUTH + TU CHOI THAT THA")
print("=" * 70)

# -- A. parse_proxy ---------------------------------------------------------
print("\n=== 1. ba dang proxy co that trong config ===")
p = R.parse_proxy("socks5://fKql6G5O:kPZaaWI8R8eX@ipv4-vt-02.resvn.net:23152")
eq("dang '@' : form", p["form"], "creds_at")
eq("dang '@' : host", p["host"], "ipv4-vt-02.resvn.net")
eq("dang '@' : port", p["port"], 23152)
eq("dang '@' : user", p["user"], "fKql6G5O")
ok("dang '@' : co mat khau", p["has_credentials"])

p = R.parse_proxy("socks5://127.0.0.1:1080")
eq("dang tran : form", p["form"], "bare")
ok("dang tran : khong mat khau", not p["has_credentials"])

# Day la cho normalizeProxy doc SAI: no se gan host->user, port->pass.
p = R.parse_proxy("socks5://ipv4-vnpt-01.resvn.net:24146:sObgXjw1:rC5CCCO5mIMz")
eq("dang nha cung cap : form", p["form"], "colon")
eq("dang nha cung cap : host KHONG bi doc thanh user", p["host"], "ipv4-vnpt-01.resvn.net")
eq("dang nha cung cap : port", p["port"], 24146)
eq("dang nha cung cap : user", p["user"], "sObgXjw1")
eq("dang nha cung cap : pass", p["password"], "rC5CCCO5mIMz")

p = R.parse_proxy("sock5s://ipv4-vnpt-01.resvn.net:24146:sObgXjw1:rC5CCCO5mIMz")
ok("scheme go nham van doc duoc phan con lai", p is not None)
ok("...nhung bi danh dau scheme la nao", not p["scheme_known"], p["scheme"])

ok("rong -> None", R.parse_proxy("") is None)
ok("rac -> None", R.parse_proxy("khong-phai-proxy") is None)
ok("thieu port -> None", R.parse_proxy("socks5://host-khong-co-port") is None)

# -- B. proxy_blocker -------------------------------------------------------
print("\n=== 2. chan dung nhanh, chan dung ly do ===")
SH = "ShardX 149.0.7827.103"
eq("ShardX + socks5 co mat khau -> chan",
   R.proxy_blocker(SH, "socks5://u:p@h.example:1080"), "PROXY_SOCKS5_AUTH_UNSUPPORTED")
eq("ShardX + dang nha cung cap -> chan",
   R.proxy_blocker(SH, "socks5://h.example:1080:u:p"), "PROXY_FORMAT_UNSUPPORTED")
eq("ShardX + scheme go nham -> chan",
   R.proxy_blocker(SH, "sock5s://h.example:1080:u:p"), "PROXY_FORMAT_UNSUPPORTED")
eq("ShardX + rac -> chan",
   R.proxy_blocker(SH, "khong-phai-proxy"), "PROXY_FORMAT_UNSUPPORTED")
eq("ShardX + socks5 KHONG mat khau -> cho qua",
   R.proxy_blocker(SH, "socks5://127.0.0.1:1080"), None)
eq("ShardX + khong proxy -> cho qua", R.proxy_blocker(SH, ""), None)
# http CO mat khau sua duoc that (chuyen sang tuy chon `proxy` cua Playwright),
# nen KHONG chan -- chan mot thu sap chay duoc chi to phai go ra ngay sau do.
eq("ShardX + http co mat khau -> cho qua (Builder B va duoc)",
   R.proxy_blocker(SH, "http://u:p@h.example:8080"), None)
# Nhanh BAS: plugin native tu cam proxy, khong doan thay.
for pin in ("148.0.7778.97", "default", ""):
    eq(f"ghim BAS {pin!r} + socks5 co mat khau -> KHONG chan",
       R.proxy_blocker(pin, "socks5://u:p@h.example:1080"), None)

# -- C. ngoai le has_local_fp vs bang chung ---------------------------------
print("\n=== 3. bang chung thang suy doan ===")
tmp = tempfile.mkdtemp(prefix="proxytruth_")
_orig_dir = PM.PROFILES_DIR
_orig_state = SX._read_engine_state()
try:
    PM.PROFILES_DIR = tmp

    def mkprofile(name, version, with_fp=True, proxy=""):
        d = os.path.join(tmp, name)
        os.makedirs(d, exist_ok=True)
        cfg = {"browser_version": version}
        if proxy:
            cfg["proxy"] = proxy
        with open(os.path.join(d, "config.json"), "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        if with_fp:
            with open(os.path.join(d, "fingerprint_saved.json"), "w", encoding="utf-8") as f:
                f.write("{}")
        return name

    mkprofile("bas_co_vantay", "148.0.7778.97", with_fp=True)

    if SX.supports_bas():
        SX.mark_bas_key_ok()   # khoa dang song
        eq("khoa song + co vantay -> cho qua",
           R.check_launch_blockers("bas_co_vantay"), None)

        SX.mark_bas_key_bad("Key expired! Please buy a new one.")
        eq("khoa CHET + co vantay -> VAN chan (vantay khong cuu duoc khoa)",
           R.check_launch_blockers("bas_co_vantay"), "BAS_KEY_EXPIRED")
        ok("ma chan co cau chu cho nguoi dung",
           "BAS_KEY_EXPIRED" in R.LAUNCH_BLOCKER_MESSAGES)
        ref = R.launch_refusal("bas_co_vantay")
        ok("launch_refusal tra ca message", bool(ref and ref.get("message")))

        SX.mark_bas_key_ok()   # mot luot mo thanh cong tu go chan
        eq("mot luot mo BAS thanh cong -> tu bo chan",
           R.check_launch_blockers("bas_co_vantay"), None)
    else:
        ok("host khong chay duoc BAS -> chan ngay o tang engine",
           R.check_launch_blockers("bas_co_vantay") == "ENGINE_WINDOWS_ONLY")
finally:
    PM.PROFILES_DIR = _orig_dir
    SX._write_engine_state(_orig_state)
    shutil.rmtree(tmp, ignore_errors=True)

# -- D. note_launch_output --------------------------------------------------
print("\n=== 4. doc log ra phan quyet khoa ===")
_orig_state = SX._read_engine_state()
try:
    for msg in ("Error: Key expired! Please buy a new one.",
                "FingerprintSwitcher key is missing",
                "Invalid key supplied",
                "Query limit reached"):
        SX._write_engine_state({})
        eq(f"nhan ra {msg[:32]!r}", R.note_launch_output(msg), "bad")
    SX._write_engine_state({})
    eq("log binh thuong -> khong ket luan gi",
       R.note_launch_output("[Launch] Spawning ShardX... page loaded"), None)
    eq("log rong -> khong ket luan gi", R.note_launch_output(""), None)
finally:
    SX._write_engine_state(_orig_state)

# -- E. route kiem ke -------------------------------------------------------
print("\n=== 5. route kiem ke chi doc ===")
inv = asyncio.run(R.api_engine_inventory())
for k in ("engines", "default_pin", "usable_count", "bas", "shardx", "summary", "success"):
    ok(f"co khoa {k!r}", k in inv)
ok("summary la cau tieng Anh in thang duoc",
   isinstance(inv["summary"], str) and len(inv["summary"]) > 20)
ok("summary khong lan chu tieng Viet cua why_not",
   not any(ch in inv["summary"] for ch in "\u01a1\u01b0\u0103\u00e2\u00ea\u00f4\u0111"),
   inv["summary"][:80])
ok("serialise duoc sang JSON", bool(json.dumps(inv)))

print()
for f in failures:
    print("  FAIL", f)
print(f"{checks - len(failures)}/{checks} PASS")
sys.exit(1 if failures else 0)
