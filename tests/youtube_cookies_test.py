# -*- coding: utf-8 -*-
"""Cookie YouTube từ hồ sơ browser TubeCLI đang mở — tubecli/core/youtube_cookies.py (lõi .97, 15/9/2026).

Không đụng hồ sơ / cài đặt thật: PROFILES_DIR và TUBECLI_DATA_DIR trỏ sang thư mục tạm, kho cookie SQLite tự dựng,
phiên "đang mở" và việc đọc cookie qua CDP được giả.

Kiểm:
  A. candidates: chỉ hồ sơ có logo YouTube; đang mở trước, có cookie phiên youtube.com trước, không proxy trước;
     bỏ thư mục _bas; chọn đích danh; plan tách đang mở / đang tắt
  B. proxy_for: host:port:user:pass trần → URL có scheme, mật khẩu được mã hoá; không proxy → None; hỏng → lý do
  C. netscape_text / write_cookie_file: chỉ youtube.com + google.com, #HttpOnly_, cột subdomain khớp dấu chấm,
     phiên = hạn 0, bỏ giá trị có tab/xuống dòng; yt-dlp nạp được file thật
  D. export_attempt: file tạm + proxy; hồ sơ tắt / không có cookie YouTube → lý do; remove_file xoá
  E. is_blocked, blocked_hint theo tình huống; settings() đọc downloader_settings.json (mặc định bật)

Run:  python tests/youtube_cookies_test.py
"""
import json
import os
import shutil
import sqlite3
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

TMP = tempfile.mkdtemp(prefix="ytc_test_")
os.environ["TUBECLI_DATA_DIR"] = os.path.join(TMP, "data")

from tubecli.extensions.browser import profile_manager as PM  # noqa: E402
from tubecli.core import youtube_cookies as YC  # noqa: E402

PASS = FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", label)
    else:
        FAIL += 1
        print("  FAIL", label, "—", str(detail)[:300])


PM.PROFILES_DIR = os.path.join(TMP, "profiles")
PM._LOGIN_CACHE.clear()


def make_profile(name, cookies, proxy=""):
    root = os.path.join(PM.PROFILES_DIR, name)
    db = os.path.join(root, "Default", "Network", "Cookies")
    os.makedirs(os.path.dirname(db), exist_ok=True)
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE cookies (host_key TEXT, name TEXT, value TEXT)")
    conn.executemany("INSERT INTO cookies VALUES (?, ?, ?)", [(h, n, "never-read") for h, n in cookies])
    conn.commit()
    conn.close()
    with open(os.path.join(root, "config.json"), "w", encoding="utf-8") as f:
        json.dump({"proxy": proxy}, f)


make_profile("zeta_live", [(".youtube.com", "LOGIN_INFO"), (".google.com", "SID")])
make_profile("alpha_closed", [(".youtube.com", "LOGIN_INFO"), (".google.com", "SID")])
make_profile("beta_google_only", [(".google.com", "SID")])
make_profile("fb_only", [(".facebook.com", "c_user")])
make_profile("proxied_live", [("youtube.com", "__Secure-3PSID"), (".google.com", "SID")], proxy="1.2.3.4:8080:user1:pa$s")
os.makedirs(os.path.join(PM.PROFILES_DIR, "zeta_live_bas"), exist_ok=True)
LIVE = {"zeta_live", "proxied_live"}
YC._is_live = lambda name: name in LIVE

print("── A. candidates / plan ────────────────────────────────────")
c = YC.candidates()
ok([x["name"] for x in c] == ["zeta_live", "proxied_live", "alpha_closed", "beta_google_only"],
   "chỉ hồ sơ logo YouTube; đang mở → cookie phiên youtube.com → không proxy", [x["name"] for x in c])
byname = {x["name"]: x for x in c}
ok(byname["proxied_live"]["proxy"] and byname["proxied_live"]["youtube_session"] and not byname["beta_google_only"]["youtube_session"],
   "cờ proxy + cookie phiên youtube.com (host không dấu chấm vẫn khớp); chỉ google SID thì không", byname)
ok(set(c[0]) == {"name", "live", "youtube_session", "proxy"}, "không có giá trị cookie nào trong kết quả", c[0])
ok([x["name"] for x in YC.candidates("alpha_closed")] == ["alpha_closed"] and YC.candidates("fb_only") == [] and YC.candidates("nope") == [],
   "chọn đích danh: chỉ hồ sơ đó, và chỉ khi nó đăng nhập YouTube")
ok(YC.plan() == {"live": ["zeta_live", "proxied_live"], "closed": ["alpha_closed", "beta_google_only"]}, "plan tách đang mở / đang tắt", YC.plan())

import socket  # noqa: E402
import time  # noqa: E402
srv = socket.socket()
srv.bind(("127.0.0.1", 0))
srv.listen(1)
open_port = srv.getsockname()[1]
ok(YC._port_open(open_port), "cổng đang nghe → sống")
srv.close()
t0 = time.time()
dead = YC._port_open(open_port)
ok(not dead and time.time() - t0 < 1.0, "cổng đã đóng → chết trong <1 s (không chờ 1,5 s như phép thử HTTP)", round(time.time() - t0, 2))
ok(not YC._port_open(None) and not YC._port_open("abc"), "cổng rỗng / hỏng → chết, không ném")

print("── B. proxy_for ────────────────────────────────────────────")
url, err = YC.proxy_for("proxied_live")
ok(url and url.endswith("://user1:pa%24s@1.2.3.4:8080") and "://" in url and not err, "host:port:user:pass → URL có scheme, mật khẩu mã hoá", (url, err))
ok(YC.proxy_for("zeta_live") == (None, ""), "không proxy → (None, '')")
make_profile("weird", [(".youtube.com", "LOGIN_INFO")], proxy="đây không phải proxy")
ok(YC.proxy_for("weird")[0] is None and "could not be read" in YC.proxy_for("weird")[1], "proxy hỏng → lý do, không đi thẳng lặng lẽ", YC.proxy_for("weird"))

print("── C. file cookie cho yt-dlp ───────────────────────────────")
COOKIES = [
    {"domain": ".youtube.com", "name": "LOGIN_INFO", "value": "abc", "path": "/", "expires": 1893456000.5, "httpOnly": True, "secure": True},
    {"domain": "accounts.google.com", "name": "SID2", "value": "v", "path": "/", "expires": -1, "httpOnly": False, "secure": False},
    {"domain": ".facebook.com", "name": "c_user", "value": "1", "path": "/"},
    {"domain": ".youtube.com", "name": "BAD", "value": "a\tb", "path": "/"},
    {"domain": ".notyoutube.com", "name": "X", "value": "y", "path": "/"},
]
text, kept = YC.netscape_text(COOKIES)
lines = [l for l in text.splitlines() if l and not l.startswith("# ")]
ok(kept == 2 and lines == ["#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t1893456000\tLOGIN_INFO\tabc",
                           "accounts.google.com\tFALSE\t/\tFALSE\t0\tSID2\tv"],
   "chỉ youtube.com + google.com; #HttpOnly_; cột subdomain khớp dấu chấm; phiên = 0; bỏ tab", lines)
path, n = YC.write_cookie_file(COOKIES)
try:
    from yt_dlp.cookies import YoutubeDLCookieJar
    jar = YoutubeDLCookieJar(path)
    jar.load()
    ok({ck.name for ck in jar} == {"LOGIN_INFO", "SID2"}, "yt-dlp nạp được file thật", {ck.name for ck in jar})
except ImportError:
    ok(True, "yt-dlp chưa cài — bỏ qua bước nạp thật")
YC.remove_file(path)
ok(not os.path.exists(path) and YC.write_cookie_file([COOKIES[2]]) == (None, 0), "remove_file xoá; không còn cookie nào → không ghi file")

print("── D. export_attempt ───────────────────────────────────────")
LIVE_COOKIES = {"zeta_live": (COOKIES, None), "proxied_live": (COOKIES, None), "alpha_closed": (None, "no_session"),
                "fbonly_live": ([COOKIES[2]], None)}
YC.read_live_cookies = lambda name: LIVE_COOKIES.get(name, (None, "no_session"))
att, why = YC.export_attempt("zeta_live")
ok(att and os.path.isfile(att["cookiefile"]) and att["count"] == 2 and att["proxy"] is None and not why, "hồ sơ đang mở → file tạm, không proxy", (att, why))
YC.remove_file(att["cookiefile"])
att2, _ = YC.export_attempt("proxied_live")
ok(att2 and att2["proxy"] and att2["proxy"].endswith("@1.2.3.4:8080"), "hồ sơ có proxy → kèm URL proxy", att2)
YC.remove_file(att2 and att2["cookiefile"])
ok(YC.export_attempt("alpha_closed") == (None, "the browser is not open"), "hồ sơ đang tắt → không dùng")
ok(YC.export_attempt("fbonly_live")[0] is None and "no YouTube/Google cookies" in YC.export_attempt("fbonly_live")[1], "phiên không có cookie YouTube → lý do")
LIVE_COOKIES["weird"] = (COOKIES, None)
ok(YC.export_attempt("weird")[0] is None and "proxy" in YC.export_attempt("weird")[1], "proxy hỏng → không thử (tránh lộ IP thật với phiên)")

print("── E. chặn, câu chỉ đường, cài đặt ─────────────────────────")
ok(YC.is_blocked("ERROR: [youtube] x: Sign in to confirm you’re not a bot. Use --cookies-from-browser")
   and YC.is_blocked("Sign in to confirm your age") and not YC.is_blocked("Private video") and not YC.is_blocked("HTTP Error 404"),
   "is_blocked: bot-check / tuổi có; riêng tư / 404 không")
on = {"auto": True, "profile": ""}
ok("Turn on «Auto cookies" in YC.blocked_hint({"auto": False}, None, []), "tắt → chỉ chỗ bật")
ok("refused the cookies of zeta_live" in YC.blocked_hint(on, {"live": ["zeta_live"], "closed": []}, ["zeta_live"]), "đã thử → nói hồ sơ bị từ chối")
ok("Could not read YouTube cookies from the open browser profile(s) zeta_live" in YC.blocked_hint(on, {"live": ["zeta_live"], "closed": []}, []), "đang mở mà không đọc được")
ok("Open a browser profile" in YC.blocked_hint(on, {"live": [], "closed": ["a", "b"]}, []) and "a, b" in YC.blocked_hint(on, {"live": [], "closed": ["a", "b"]}, []), "chỉ có hồ sơ tắt → kể tên để mở")
ok("«x» chosen" in YC.blocked_hint({"auto": True, "profile": "x"}, {"live": [], "closed": []}, []), "hồ sơ đã chọn không đăng nhập YouTube")
ok("No browser profile is logged into YouTube" in YC.blocked_hint(on, {"live": [], "closed": []}, []), "không hồ sơ nào")

from tubecli.extensions.video_downloader import routes as VD  # noqa: E402
VD._settings_cache = None
s = YC.settings()
ok(s == {"auto": True, "profile": "", "pasted": False, "browser": ""}, "chưa có file cài đặt → tự động BẬT", s)
os.makedirs(os.environ["TUBECLI_DATA_DIR"], exist_ok=True)
with open(os.path.join(os.environ["TUBECLI_DATA_DIR"], "downloader_settings.json"), "w", encoding="utf-8") as f:
    json.dump({"cookie_auto_browser": False, "cookie_profile": "zeta_live", "cookie_youtube": "a=b", "cookies_from_browser": "firefox"}, f)
VD._settings_cache = None
s = YC.settings()
ok(s == {"auto": False, "profile": "zeta_live", "pasted": True, "browser": "firefox"}, "đọc đúng cài đặt đã lưu", s)
VD._settings_cache = None

print("── F. mở ẩn hồ sơ đang tắt để làm mới cookie ───────────────")


class FakePM:
    def __init__(self, spawn_result=None, exit_status=None):
        self.spawned, self.terminated = [], []
        self.spawn_result, self.exit_status = spawn_result, exit_status

    def spawn(self, **kw):
        self.spawned.append(kw)
        return self.spawn_result or {"instance_id": "browser-1", "status": "running"}

    def get_status(self, iid):
        return {"status": self.exit_status or "running"}

    def terminate(self, iid):
        self.terminated.append(iid)
        return True


fpm = FakePM()
YC._pmgr = lambda: fpm
YC._launch_block = lambda name: ""
polls = {"n": 0}


def live_on_third_poll(name):
    polls["n"] += 1
    return polls["n"] >= 3


YC._is_live = live_on_third_poll
LIVE_COOKIES["alpha_closed"] = (COOKIES, None)
said, slept = [], []
att, why = YC.refresh_attempt("alpha_closed", progress=said.append, sleep=slept.append)
ok(att and att.get("refreshed") and os.path.isfile(att["cookiefile"]) and att["count"] == 2 and not why, "mở ẩn → phiên sống → xuất cookie mới", (att, why))
kw = fpm.spawned[0] if fpm.spawned else {}
ok(kw.get("profile") == "alpha_closed" and kw.get("headless") is True and kw.get("url") == "https://www.youtube.com/"
   and kw.get("manual") is True and kw.get("max_duration") == YC.REFRESH_MAX_RUN, "spawn ẩn, vào youtube.com, có trần thời gian", kw)
ok(fpm.terminated == ["browser-1"] and YC.REFRESH_SETTLE in slept, "chờ trang YouTube chạy xong rồi LUÔN đóng hồ sơ", (fpm.terminated, slept))
ok(any("opening browser profile alpha_closed in the background" in m for m in said), "câu tiến trình", said)
YC.remove_file(att and att["cookiefile"])

YC._launch_block = lambda name: "the profile is already opening or in use"
fpm = FakePM()
ok(YC.refresh_attempt("alpha_closed", sleep=lambda s: None) == (None, "the profile is already opening or in use") and not fpm.spawned,
   "hồ sơ đang bận / bị chặn mở → lý do, không spawn")
YC._launch_block = lambda name: ""
fpm = FakePM(spawn_result={"instance_id": "browser-2", "status": "error", "error": "Node.js not found"})
att, why = YC.refresh_attempt("alpha_closed", sleep=lambda s: None)
ok(att is None and "Node.js not found" in why and fpm.terminated == [], "spawn lỗi → lý do", why)
fpm = FakePM(exit_status="stopped")
att, why = YC.refresh_attempt("alpha_closed", sleep=lambda s: None)
ok(att is None and "closed before it was ready" in why and fpm.terminated == ["browser-1"], "browser thoát sớm → lý do, vẫn dọn", why)
fpm = FakePM()
YC._is_live = lambda name: False
YC.REFRESH_WAIT = 0.05
att, why = YC.refresh_attempt("alpha_closed", sleep=lambda s: time.sleep(0.01))
ok(att is None and "did not become ready" in why and fpm.terminated == ["browser-1"], "không sống kịp → lý do, vẫn đóng hồ sơ", why)
ok(YC._REFRESH_LOCK.acquire(blocking=False), "khoá được nhả sau mỗi lượt")
YC._REFRESH_LOCK.release()
hint = YC.blocked_hint({"auto": True, "profile": ""}, {"live": [], "closed": ["a"]}, [], ["a (the browser did not become ready within 45 s)"])
ok("Opening a (the browser did not become ready within 45 s) in the background did not work" in hint and "Open a browser profile" in hint, "câu chỉ đường kể lượt mở ẩn hỏng", hint)

shutil.rmtree(TMP, ignore_errors=True)
print()
print(f"{PASS}/{PASS + FAIL} PASS" if not FAIL else f"{PASS}/{PASS + FAIL} PASS — {FAIL} HỎNG")
sys.exit(1 if FAIL else 0)
