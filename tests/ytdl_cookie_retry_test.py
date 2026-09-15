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
refreshes, REFRESH_OK = [], {}


def fake_refresh(name, progress=None):
    refreshes.append(name)
    if REFRESH_OK.get(name):
        return {"profile": name, "cookiefile": f"ck-{name}-refresh.txt", "proxy": None, "count": 5}, ""
    return None, "the profile is already opening or in use"


YC.refresh_attempt = fake_refresh
stored, STORED_OK = [], {}


def fake_stored(name):
    stored.append(name)
    if STORED_OK.get(name):
        return {"profile": name, "cookiefile": f"ck-{name}-saved.txt", "proxy": None, "count": 5, "stored": True}, ""
    return None, "no saved cookie store in the profile"


YC.stored_attempt = fake_stored
from tubecli.core import ytdlp_manager as YM  # noqa: E402
ENS = []


def ens_none(update=None, force_check=False, progress=None):
    ENS.append((update, force_check))
    return {"ok": True, "action": "none", "version": "2026.08.19"}


YM.ensure = ens_none
YT = "https://www.youtube.com/watch?v=4Br45kOed_s"


def run(url, opts, script, settings=None, plan=None, refresh_ok=None, stored_ok=None):
    FakeYDL.calls.clear()
    FakeYDL.script[:] = list(script)
    exports.clear(), removed.clear(), refreshes.clear(), ENS.clear(), stored.clear()
    REFRESH_OK.clear()
    REFRESH_OK.update(refresh_ok or {})
    STORED_OK.clear()
    STORED_OK.update(stored_ok or {})
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
err, _ = run(YT, {}, [BOT], plan={"closed": ["alpha", "beta"]})
ok(err and "Open a browser profile" in str(err) and "alpha" in str(err) and len(FakeYDL.calls) == 1 and refreshes == ["alpha"],
   "chỉ có hồ sơ tắt, mở ẩn không được → bảo mở, không thử cookie cũ", str(err))
err, task = run(YT, {}, [BOT, None], plan={"closed": ["alpha"]}, refresh_ok={"alpha": True})
ok(err is None and len(FakeYDL.calls) == 2 and FakeYDL.calls[1].get("cookiefile") == "ck-alpha-refresh.txt"
   and task.get("cookie_source") == "profile:alpha" and removed == ["ck-alpha-refresh.txt"], "mở ẩn hồ sơ đang tắt → cookie mới → tải được", (task, removed))
err, task = run(YT, {}, [BOT, None], plan={"closed": ["alpha"]}, stored_ok={"alpha": True}, refresh_ok={"alpha": True})
ok(err is None and FakeYDL.calls[1].get("cookiefile") == "ck-alpha-saved.txt" and task.get("cookie_source") == "saved:alpha"
   and not refreshes and removed == ["ck-alpha-saved.txt"], "cookie ĐÃ LƯU tải được → không mở browser", (task, refreshes, removed))
err, task = run(YT, {}, [BOT, BOT, BOT], plan={"closed": ["alpha"]}, stored_ok={"alpha": True}, refresh_ok={"alpha": True})
ok(err and len(FakeYDL.calls) == 3 and stored == ["alpha"] and refreshes == ["alpha"] and "Attempts: saved:alpha:" in str(err)
   and "refused the cookies of alpha" in str(err) and "alpha, alpha" not in str(err), "đã lưu hỏng → mở ẩn; hết cách → lỗi kể từng lượt", str(err))
OUTDATED = ("ERROR: [youtube] abc: Unable to extract yt initial data; please report this issue on https://github.com/yt-dlp/yt-dlp/issues . "
            "Confirm you are on the latest version using yt-dlp -U")


def ens_updates(update=None, force_check=False, progress=None):
    ENS.append((update, force_check))
    return {"ok": True, "action": "updated" if force_check else "none", "version": "2026.09.01"}


YM.ensure = ens_updates
R._reload_ytdlp = lambda old: FakeYtDlp
err, task = run(YT, {}, [OUTDATED, None], plan={})
ok(err is None and len(FakeYDL.calls) == 2 and ENS == [(None, True)] and task.get("ytdlp_updated") == "2026.09.01", "lỗi kiểu yt-dlp cũ → cập nhật rồi tải lại", (ENS, task))
YM.ensure = ens_none
err, _ = run(YT, {}, [BOT], plan={"live": ["unreadable"]})
ok(err and len(FakeYDL.calls) == 1 and "Could not read YouTube cookies" in str(err) and removed == [], "không đọc được cookie → không có lượt thử thứ hai", str(err))

print("── B. cài đặt + /cookie-profiles ───────────────────────────")
g = asyncio.run(R.ytdl_get_settings())["data"]
ok(g["cookie_auto_browser"] is True and g["cookie_profile"] == "", "mặc định: tự động bật, tự chọn hồ sơ", g)
ok(g.get("ytdlp_auto_update") is True, "mặc định: tự cập nhật yt-dlp bật", g)
asyncio.run(R.ytdl_update_settings(R.YtdlSettingsUpdate(cookie_auto_browser=False, cookie_profile="p1")))
saved = json.load(open(os.path.join(TMP, "downloader_settings.json"), encoding="utf-8"))
g = asyncio.run(R.ytdl_get_settings())["data"]
ok(saved["cookie_auto_browser"] is False and saved["cookie_profile"] == "p1" and g["cookie_auto_browser"] is False and g["cookie_profile"] == "p1",
   "PUT lưu vào file của thư mục tạm, GET trả lại", (saved, g))
YC.candidates = lambda preferred="": [{"name": "p1", "live": True, "youtube_session": True, "proxy": False, "secret": "x"}]
d = asyncio.run(R.ytdl_cookie_profiles())["data"]
ok(d == [{"name": "p1", "live": True, "youtube_session": True, "proxy": False}], "/cookie-profiles chỉ trả tên + trạng thái", d)
ok("/api/v1/ytdl/cookie-profiles" in [getattr(r, "path", "") for r in R.router.routes], "route đã gắn")

print("── B2. trạng thái / cài / cập nhật / Info ──────────────────")
R.DOWNLOAD_TASKS["t1"] = {"status": "downloading"}
real_ff = R._get_ffmpeg_path
R._get_ffmpeg_path = lambda: "ff"
ENS.clear()
R._ensure_deps()
ok(ENS == [(False, False)], "đang có lượt tải → chỉ cài khi thiếu, không nâng cấp giữa chừng", ENS)
R.DOWNLOAD_TASKS.clear()
ENS.clear()
R._ensure_deps()
ok(ENS == [(None, False)], "không bận → theo tuỳ chọn tự cập nhật", ENS)
YM.status = lambda: {"installed": False, "version": "", "cli": None, "auto_update": True, "latest": "", "checked_at": 0, "last_error": ""}
R._get_ffmpeg_path = lambda: None
s = asyncio.run(R.ytdl_status())
ok(s["installed"] is False and s["ffmpeg_available"] is False and s["auto_update"] is True, "status đọc thư viện của máy chủ", s)
pipcalls = []
YM.pip_install = lambda pkgs, upgrade=False, timeout=300: (pipcalls.append(list(pkgs)) or (True, ""))
FF = iter([None, "C:/ff/ffmpeg.exe"])
R._get_ffmpeg_path = lambda: next(FF, "C:/ff/ffmpeg.exe")


def ens_installed(update=None, force_check=False, progress=None):
    ENS.append((update, force_check))
    return {"ok": True, "action": "installed", "version": "2026.09.01", "message": "Installed yt-dlp 2026.09.01"}


YM.ensure = ens_installed
ENS.clear()
d = asyncio.run(R.ytdl_install())
ok(d["status"] == "success" and d["installed"] and d["ffmpeg_available"] and pipcalls == [["imageio-ffmpeg"]] and ENS == [(False, False)],
   "nút Install: cài yt-dlp (không nâng cấp) + FFmpeg khi thiếu", (d, pipcalls, ENS))


def ens_install_failed(update=None, force_check=False, progress=None):
    return {"ok": False, "action": "install_failed", "version": "", "message": "Could not install yt-dlp: no pip"}


YM.ensure = ens_install_failed
R._get_ffmpeg_path = lambda: "ff"
d = asyncio.run(R.ytdl_install())
ok(d["status"] == "error" and "Could not install yt-dlp" in d["message"], "cài hỏng → trả lý do để hiện cạnh nút", d)


def ens_updated(update=None, force_check=False, progress=None):
    ENS.append((update, force_check))
    return {"ok": True, "action": "updated", "version": "2026.09.01", "message": "yt-dlp updated 2026.08.19 → 2026.09.01"}


YM.ensure = ens_updated
YM.installed_version = lambda: "2026.08.19"
ENS.clear()
d = asyncio.run(R.ytdl_update())
ok(d["status"] == "success" and d["new_version"] == "2026.09.01" and d["previous_version"] == "2026.08.19" and ENS == [(None, True)],
   "nút Update: dò ngay + nâng cấp", (d, ENS))
captured = {}


class FakeRun:
    returncode = 0
    stdout = json.dumps({"id": "abc", "title": "T", "formats": []}) + "\n"
    stderr = ""


real_run = R.subprocess.run
R.subprocess.run = lambda cmd, **kw: (captured.setdefault("cmd", cmd) and FakeRun())
real_ensure_deps = R._ensure_deps
R._ensure_deps = lambda: None
YM.cli_command = lambda: ["PYEXE", "-m", "yt_dlp"]
try:
    d = asyncio.run(R.get_video_info(R.VideoInfoRequest(url=YT)))
finally:
    R.subprocess.run = real_run
    R._ensure_deps = real_ensure_deps
    R._get_ffmpeg_path = real_ff
ok(captured.get("cmd", [])[:3] == ["PYEXE", "-m", "yt_dlp"] and d["data"]["title"] == "T",
   "Info gọi yt-dlp CỦA máy chủ (python -m yt_dlp), không lệnh trần trên PATH", captured)
ok("/api/v1/ytdl/install" in [getattr(r, "path", "") for r in R.router.routes], "route /install đã gắn")

print("── C. giao diện Settings ───────────────────────────────────")
html = open(os.path.join(ROOT, "tubecli", "extensions", "video_downloader", "static", "index.html"), encoding="utf-8").read()
ok('id="set-auto-browser" checked' in html and 'id="set-cookie-profile"' in html and "Tự động lấy cookie từ browser TubeCLI" in html, "ô tick + ô chọn hồ sơ")
ok("fetch(API_BASE + '/cookie-profiles')" in html and "loadCookieProfiles(s.cookie_profile || '');" in html
   and "document.getElementById('set-auto-browser').checked = s.cookie_auto_browser !== false;" in html, "nạp danh sách hồ sơ + trạng thái đã lưu")
ok("body.cookie_auto_browser = document.getElementById('set-auto-browser').checked;" in html
   and "body.cookie_profile = document.getElementById('set-cookie-profile').value;" in html, "lưu gửi hai trường")
ok("Auto Cookies from Browser" not in html and "Cookie từ trình duyệt cài trên máy" in html, "nhãn cũ đổi tên, không trùng với tuỳ chọn mới")
ok("${esc(p.name)}" in html, "tên hồ sơ được escape")
ok('onclick="installDeps()"' in html and "fetch(API_BASE + '/install', { method: 'POST' })" in html and "Install yt-dlp" in html,
   "huy hiệu thiếu yt-dlp có nút Install gọi /install")
src = open(os.path.join(ROOT, "tubecli", "extensions", "video_downloader", "routes.py"), encoding="utf-8").read()
ok(src.count("ydl_opts.update(_ym.js_runtime_opts())") == 2 and "_ym.cli_js_args()" in src, "tải / tìm / Info đều truyền JS runtime cho yt-dlp")
ok('id="set-ytdlp-auto" checked' in html and "body.ytdlp_auto_update = document.getElementById('set-ytdlp-auto').checked;" in html
   and "document.getElementById('set-ytdlp-auto').checked = s.ytdlp_auto_update !== false;" in html, "ô tự cập nhật yt-dlp")

R._settings_cache = None
shutil.rmtree(TMP, ignore_errors=True)
print()
print(f"{PASS}/{PASS + FAIL} PASS" if not FAIL else f"{PASS}/{PASS + FAIL} PASS — {FAIL} HỎNG")
sys.exit(1 if FAIL else 0)
