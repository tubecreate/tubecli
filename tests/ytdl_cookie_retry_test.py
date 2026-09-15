# -*- coding: utf-8 -*-
"""Video Downloader: tuỳ chọn «Tự động lấy cookie từ browser TubeCLI» (lõi .97, 15/9/2026).

Không tải thật, không đụng cài đặt thật: yt_dlp giả, lớp cookie giả, TUBECLI_DATA_DIR trỏ thư mục tạm.

Kiểm:
  A. _download_with_browser_cookies: tải được → một lượt; lỗi khác / link không phải YouTube / tuỳ chọn tắt → ném
     nguyên lỗi; bị chặn → thử lại bằng cookie hồ sơ đang mở (bỏ cookiesfrombrowser cũ, proxy của hồ sơ khi người
     dùng không chọn proxy), tối đa 2 hồ sơ, file tạm luôn bị xoá, task ghi nguồn cookie; hết cách → lỗi kèm chỉ đường
  B. cài đặt: mặc định bật, PUT lưu cookie_auto_browser / cookie_profile; /cookie-profiles chỉ trả tên + trạng thái
  C. giao diện: ô tick + ô chọn hồ sơ, nạp /cookie-profiles, gửi hai trường khi lưu; nhãn cũ đổi tên cho khỏi trùng

Run:  python tests/ytdl_cookie_retry_test.py
"""
import asyncio
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

TMP = tempfile.mkdtemp(prefix="ytdl_ck_test_")
os.environ["TUBECLI_DATA_DIR"] = TMP

from tubecli.extensions.video_downloader import routes as R  # noqa: E402
from tubecli.core import youtube_cookies as YC  # noqa: E402

R._settings_cache = None
PASS = FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", label)
    else:
        FAIL += 1
        print("  FAIL", label, "—", str(detail)[:300])


class FakeYDL:
    calls = []
    script = []

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def download(self, urls):
        FakeYDL.calls.append(dict(self.opts))
        out = FakeYDL.script.pop(0) if FakeYDL.script else None
        if out:
            raise Exception(out)


class FakeYtDlp:
    YoutubeDL = FakeYDL


BOT = "ERROR: [youtube] abc: Sign in to confirm you’re not a bot. Use --cookies-from-browser or --cookies"
STATE = {"settings": {"auto": True, "profile": "", "pasted": False, "browser": ""}, "plan": {"live": [], "closed": []}}
exports, removed = [], []
YC.settings = lambda: dict(STATE["settings"])
YC.plan = lambda preferred="": {k: list(v) for k, v in STATE["plan"].items()}


def fake_export(name):
    exports.append(name)
    if name == "unreadable":
        return None, "could not read its cookies"
    return {"profile": name, "cookiefile": f"ck-{name}.txt", "proxy": "socks5://h:1080" if name == "proxied" else None, "count": 5}, ""


YC.export_attempt = fake_export
YC.remove_file = lambda p: removed.append(p)
YT = "https://www.youtube.com/watch?v=4Br45kOed_s"


def run(url, opts, script, settings=None, plan=None):
    FakeYDL.calls.clear()
    FakeYDL.script[:] = list(script)
    exports.clear(), removed.clear()
    STATE["settings"] = {"auto": True, "profile": "", "pasted": False, "browser": "", **(settings or {})}
    STATE["plan"] = {"live": [], "closed": [], **(plan or {})}
    task = {}
    try:
        R._download_with_browser_cookies(FakeYtDlp, dict(opts), url, task)
        return None, task
    except Exception as e:      # noqa: BLE001
        return e, task


print("── A. tải + thử lại bằng cookie hồ sơ ──────────────────────")
err, task = run(YT, {"format": "best"}, [None], plan={"live": ["p1"]})
ok(err is None and len(FakeYDL.calls) == 1 and not exports and "cookie_source" not in task, "tải được → một lượt, không đọc hồ sơ")
err, _ = run(YT, {}, ["ERROR: HTTP Error 404: Not Found"], plan={"live": ["p1"]})
ok(err and "404" in str(err) and len(FakeYDL.calls) == 1 and not exports, "lỗi không phải chặn → ném nguyên lỗi")
err, _ = run("https://www.tiktok.com/@a/video/1", {}, [BOT], plan={"live": ["p1"]})
ok(err and len(FakeYDL.calls) == 1 and not exports, "link không phải YouTube → không thử cookie YouTube")
err, _ = run(YT, {}, [BOT], settings={"auto": False}, plan={"live": ["p1"]})
ok(err and str(err) == BOT and not exports, "tuỳ chọn tắt → lỗi như cũ", str(err))
err, task = run(YT, {"cookiesfrombrowser": ("chrome",), "format": "best"}, [BOT, None], plan={"live": ["proxied"]})
second = FakeYDL.calls[1] if len(FakeYDL.calls) > 1 else {}
ok(err is None and second.get("cookiefile") == "ck-proxied.txt" and "cookiesfrombrowser" not in second
   and second.get("proxy") == "socks5://h:1080" and second.get("format") == "best", "bị chặn → cookie hồ sơ đang mở, bỏ cookiesfrombrowser, đi proxy của hồ sơ", second)
ok(task.get("cookie_source") == "profile:proxied" and removed == ["ck-proxied.txt"], "task ghi nguồn cookie; file tạm bị xoá", (task, removed))
err, _ = run(YT, {"proxy": "http://mine:1"}, [BOT, None], plan={"live": ["proxied"]})
ok(err is None and FakeYDL.calls[1].get("proxy") == "http://mine:1", "người dùng đã chọn proxy → giữ proxy đó", FakeYDL.calls[1])
err, task = run(YT, {}, [BOT, "ERROR: The page needs to be reloaded.", None], plan={"live": ["p1", "p2", "p3"]})
ok(err is None and exports == ["p1", "p2"] and task.get("cookie_source") == "profile:p2" and removed == ["ck-p1.txt", "ck-p2.txt"],
   "hồ sơ 1 bị từ chối → hồ sơ 2; cả hai file xoá", (exports, removed, task))
err, _ = run(YT, {}, [BOT, BOT, BOT, BOT], plan={"live": ["p1", "p2", "p3"]})
ok(err and exports == ["p1", "p2"] and "refused the cookies of p1, p2" in str(err) and str(err).startswith(BOT), "tối đa 2 hồ sơ; hết cách → lỗi gốc kèm chỉ đường", str(err))
err, _ = run(YT, {}, [BOT], plan={"closed": ["alpha"]})
ok(err and "Open a browser profile" in str(err) and "alpha" in str(err) and len(FakeYDL.calls) == 1, "chỉ có hồ sơ tắt → bảo mở, không thử cookie cũ", str(err))
err, _ = run(YT, {}, [BOT], plan={"live": ["unreadable"]})
ok(err and len(FakeYDL.calls) == 1 and "Could not read YouTube cookies" in str(err) and removed == [], "không đọc được cookie → không có lượt thử thứ hai", str(err))

print("── B. cài đặt + /cookie-profiles ───────────────────────────")
g = asyncio.run(R.ytdl_get_settings())["data"]
ok(g["cookie_auto_browser"] is True and g["cookie_profile"] == "", "mặc định: tự động bật, tự chọn hồ sơ", g)
asyncio.run(R.ytdl_update_settings(R.YtdlSettingsUpdate(cookie_auto_browser=False, cookie_profile="p1")))
saved = json.load(open(os.path.join(TMP, "downloader_settings.json"), encoding="utf-8"))
g = asyncio.run(R.ytdl_get_settings())["data"]
ok(saved["cookie_auto_browser"] is False and saved["cookie_profile"] == "p1" and g["cookie_auto_browser"] is False and g["cookie_profile"] == "p1",
   "PUT lưu vào file của thư mục tạm, GET trả lại", (saved, g))
YC.candidates = lambda preferred="": [{"name": "p1", "live": True, "youtube_session": True, "proxy": False, "secret": "x"}]
d = asyncio.run(R.ytdl_cookie_profiles())["data"]
ok(d == [{"name": "p1", "live": True, "youtube_session": True, "proxy": False}], "/cookie-profiles chỉ trả tên + trạng thái", d)
ok("/api/v1/ytdl/cookie-profiles" in [getattr(r, "path", "") for r in R.router.routes], "route đã gắn")

print("── C. giao diện Settings ───────────────────────────────────")
html = open(os.path.join(ROOT, "tubecli", "extensions", "video_downloader", "static", "index.html"), encoding="utf-8").read()
ok('id="set-auto-browser" checked' in html and 'id="set-cookie-profile"' in html and "Tự động lấy cookie từ browser TubeCLI" in html, "ô tick + ô chọn hồ sơ")
ok("fetch(API_BASE + '/cookie-profiles')" in html and "loadCookieProfiles(s.cookie_profile || '');" in html
   and "document.getElementById('set-auto-browser').checked = s.cookie_auto_browser !== false;" in html, "nạp danh sách hồ sơ + trạng thái đã lưu")
ok("body.cookie_auto_browser = document.getElementById('set-auto-browser').checked;" in html
   and "body.cookie_profile = document.getElementById('set-cookie-profile').value;" in html, "lưu gửi hai trường")
ok("Auto Cookies from Browser" not in html and "Cookie từ trình duyệt cài trên máy" in html, "nhãn cũ đổi tên, không trùng với tuỳ chọn mới")
ok("${esc(p.name)}" in html, "tên hồ sơ được escape")

R._settings_cache = None
shutil.rmtree(TMP, ignore_errors=True)
print()
print(f"{PASS}/{PASS + FAIL} PASS" if not FAIL else f"{PASS}/{PASS + FAIL} PASS — {FAIL} HỎNG")
sys.exit(1 if FAIL else 0)
