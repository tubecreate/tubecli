# -*- coding: utf-8 -*-
"""yt-dlp của máy chủ: tự cài / tự cập nhật — tubecli/core/ytdlp_manager.py (lõi .98, 15/9/2026).

Không chạy pip, không ra mạng: _pip, bản đã cài, bản mới nhất trên PyPI đều giả; trạng thái ghi vào thư mục tạm.

Kiểm:
  A. is_newer (nightly, bằng nhau, rỗng), looks_outdated, cli_command dùng python -m yt_dlp
  B. ensure: thiếu → cài (và nạp lại module); cài hỏng → ok False kèm lý do pip
  C. tự cập nhật: lần đầu dò PyPI → có bản mới → pip --upgrade → updated; trong cửa sổ 6 giờ không hỏi PyPI; hết cửa sổ
     → hỏi lại; cập nhật hỏng → nhớ, không cài lại trong cửa sổ; force_check bỏ qua cả hai; tuỳ chọn tắt → không hỏi
  D. _reload_module xoá yt_dlp khỏi sys.modules; status(); auto_update_enabled đọc cài đặt Video Downloader (mặc định bật)

Run:  python tests/ytdlp_manager_test.py
"""
import json
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

TMP = tempfile.mkdtemp(prefix="ytdlp_mgr_test_")
os.environ["TUBECLI_DATA_DIR"] = os.path.join(TMP, "data")

from tubecli.core import ytdlp_manager as M  # noqa: E402

PASS = FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", label)
    else:
        FAIL += 1
        print("  FAIL", label, "—", str(detail)[:300])


M.STATE_FILE = os.path.join(TMP, "ytdlp_update.json")
ENV = {"version": "2026.08.19", "latest": "2026.09.01", "auto": True, "pip_ok": True, "after_pip": "2026.09.01", "ejs": True,
       "rt": {"node": {"path": "n"}}}
CALLS = {"pip": [], "latest": 0, "reload": 0}


def fake_pip(args, timeout=300):
    CALLS["pip"].append(list(args))
    if ENV["pip_ok"]:
        ENV["version"] = ENV["after_pip"]
        if any("[default" in a for a in args):
            ENV["ejs"] = True
        if any("deno" in a for a in args):
            ENV["rt"] = {"deno": {"path": "d"}}
        return True, ""
    return False, "ERROR: Could not install packages due to an OSError: [WinError 5] Access is denied"


def fake_latest(timeout=8):
    CALLS["latest"] += 1
    return ENV["latest"]


M._pip = fake_pip
M.installed_version = lambda: ENV["version"]
M.module_available = lambda: bool(ENV["version"])
M.latest_version = fake_latest
M.auto_update_enabled = lambda: ENV["auto"]
M.ejs_available = lambda: ENV["ejs"]
REAL_JS_RUNTIMES = M.js_runtimes
M.js_runtimes = lambda: dict(ENV["rt"])
real_reload = M._reload_module
M._reload_module = lambda: CALLS.__setitem__("reload", CALLS["reload"] + 1)


def reset(**env):
    ENV.update({"version": "2026.08.19", "latest": "2026.09.01", "auto": True, "pip_ok": True, "after_pip": "2026.09.01", "ejs": True,
                "rt": {"node": {"path": "n"}}})
    ENV.update(env)
    CALLS.update({"pip": [], "latest": 0, "reload": 0})


def state():
    try:
        return json.load(open(M.STATE_FILE, encoding="utf-8"))
    except Exception:      # noqa: BLE001
        return {}


print("── A. so bản, nhận lỗi bản cũ, lệnh CLI ───────────────────")
ok(M.is_newer("2026.09.01", "2026.08.19") and M.is_newer("2026.08.19.232150", "2026.08.19")
   and not M.is_newer("2026.08.19", "2026.08.19") and not M.is_newer("2026.8.19", "2026.08.19") and not M.is_newer("", "2026.08.19")
   and M.is_newer("2026.01.01", ""), "is_newer: bản mới, nightly, bằng nhau, rỗng")
ok(M.looks_outdated("ERROR: [youtube] x: Unable to extract yt initial data; please report this issue … Confirm you are on the latest version")
   and not M.looks_outdated("Sign in to confirm you’re not a bot") and not M.looks_outdated("Private video"), "looks_outdated")
ok(M.cli_command() == [sys.executable, "-m", "yt_dlp"], "cli_command: python -m yt_dlp của máy chủ", M.cli_command())

print("── B. thiếu yt-dlp ─────────────────────────────────────────")
reset(version="")
r = M.ensure()
ok(r["ok"] and r["action"] == "installed" and r["version"] == "2026.09.01" and CALLS["pip"] == [["install", "--upgrade", "yt-dlp[default]"]]
   and CALLS["reload"] == 1, "thiếu → pip install → nạp lại module", (r, CALLS))
said = []
reset(version="", pip_ok=False)
r = M.ensure(progress=said.append)
ok(not r["ok"] and r["action"] == "install_failed" and "Access is denied" in r["message"] and "Could not install yt-dlp" in state().get("last_error", ""),
   "cài hỏng → ok False, lý do pip, ghi last_error", (r, state()))
ok(any("installing" in m for m in said), "câu tiến trình khi cài", said)

print("── C. tự cập nhật ───────────────────────────────────────────")
os.remove(M.STATE_FILE)
reset()
r = M.ensure()
ok(r["action"] == "updated" and r["version"] == "2026.09.01" and CALLS["latest"] == 1 and CALLS["pip"] == [["install", "--upgrade", "yt-dlp[default]"]]
   and CALLS["reload"] == 1 and state().get("latest") == "2026.09.01", "lần đầu: hỏi PyPI → có bản mới → nâng cấp", (r, CALLS))
reset(version="2026.09.01")
r = M.ensure()
ok(r["action"] == "none" and CALLS["latest"] == 0 and not CALLS["pip"], "trong cửa sổ 6 giờ → không hỏi PyPI, không pip", CALLS)
st = state()
st["checked_at"] = time.time() - M.CHECK_EVERY - 5
json.dump(st, open(M.STATE_FILE, "w", encoding="utf-8"))
reset(version="2026.09.01", latest="2026.09.01")
r = M.ensure()
ok(r["action"] == "none" and CALLS["latest"] == 1 and not CALLS["pip"], "hết cửa sổ → hỏi lại PyPI; đã mới nhất → không pip", CALLS)
st = state()
st["checked_at"] = 0
json.dump(st, open(M.STATE_FILE, "w", encoding="utf-8"))
reset(version="2026.09.01", latest="2026.09.08", pip_ok=False)
r = M.ensure()
ok(r["ok"] and r["action"] == "update_failed" and "2026.09.08" in r["message"] and state().get("failed_version") == "2026.09.08",
   "cập nhật hỏng → vẫn ok (còn bản cũ dùng được), nhớ bản hỏng", (r, state()))
reset(version="2026.09.01", latest="2026.09.08", pip_ok=False)
r = M.ensure()
ok(r["action"] == "none" and not CALLS["pip"] and "Access is denied" in r["message"], "trong cửa sổ → không cài lại bản vừa hỏng", (r, CALLS))
reset(version="2026.09.01", latest="2026.09.08", after_pip="2026.09.08")
r = M.ensure(force_check=True)
ok(r["action"] == "updated" and CALLS["latest"] == 1 and CALLS["pip"] and state().get("failed_version") == "" and state().get("last_error") == "",
   "force_check (nút Update / lỗi bản cũ) → hỏi ngay, thử lại, xoá lỗi cũ", (r, state()))
st = state()
st["checked_at"] = 0
json.dump(st, open(M.STATE_FILE, "w", encoding="utf-8"))
reset(version="2026.09.08", latest="2026.09.20", auto=False)
r = M.ensure()
ok(r["action"] == "none" and CALLS["latest"] == 0 and not CALLS["pip"], "tuỳ chọn tắt → không hỏi PyPI", CALLS)
reset(version="2026.09.08", latest="2026.09.20", auto=True, after_pip="2026.09.20")
r = M.ensure(update=False)
ok(r["action"] == "none" and not CALLS["pip"], "update=False (đang có lượt tải) → không nâng cấp", CALLS)

print("── C2. bộ giải thử thách JS (yt-dlp-ejs) + JS runtime ───────")
reset(version="2026.08.19", ejs=False, after_pip="2026.08.19", auto=False)
r = M.ensure()
ok(r["ok"] and CALLS["pip"] == [["install", "yt-dlp[default]==2026.08.19"]] and ENV["ejs"] and not CALLS["latest"],
   "có yt-dlp mà thiếu yt-dlp-ejs → cài kèm, GIỮ đúng bản yt-dlp (kể cả khi tắt tự cập nhật)", CALLS)
reset(version="2026.08.19", ejs=False, pip_ok=False, auto=False)
r = M.ensure()
ok(r["ok"] and "Could not install yt-dlp-ejs" in state().get("last_error", ""), "cài bộ giải hỏng → vẫn ok, ghi lỗi", state())
reset(version="2026.08.19", ejs=False, pip_ok=False, auto=False)
r = M.ensure()
ok(not CALLS["pip"], "trong cửa sổ → không cài lại bộ giải vừa hỏng", CALLS)
M.clear_install_failures()   # lượt ngay trước vừa ghi ejs_failed_at (cài hỏng) → cửa sổ 6 giờ sẽ chặn lượt này
reset(version="2026.08.19", rt={}, after_pip="2026.08.19", auto=False)
r = M.ensure()
ok(r["ok"] and CALLS["pip"] == [["install", "yt-dlp[default,deno]==2026.08.19"]] and ENV["rt"],
   "không có runtime yt-dlp chấp nhận (node < 22) → cài deno qua pip, GIỮ đúng bản yt-dlp", CALLS)
st = state()
st["ejs_failed_at"] = time.time()
json.dump(st, open(M.STATE_FILE, "w", encoding="utf-8"))
M.clear_install_failures()
ok(state().get("ejs_failed_at") == 0 and state().get("failed_version") == "", "nút Install xoá ghi nhớ lần cài hỏng → thử lại ngay", state())
import platform  # noqa: E402
real_which, real_ver, real_pipdeno = M.shutil.which, M._runtime_version, M._pip_deno_bin
ok(real_ver(sys.executable) == platform.python_version(), "_runtime_version đọc được bản từ `--version` thật", real_ver(sys.executable))
M.js_runtimes = REAL_JS_RUNTIMES
VERS = {}
M._runtime_version = lambda path: VERS.get(path, "")
try:
    M.shutil.which = lambda name: {"node": "/usr/bin/node"}.get(name)
    M._pip_deno_bin = lambda: None
    VERS["/usr/bin/node"] = "20.19.0"
    ok(M.js_runtimes() == {} and M.js_runtime_opts() == {} and M.cli_js_args() == []
       and M.js_runtime_notes() == ["node 20.19.0 is too old for yt-dlp (needs 22.0.0+)"],
       "node 20 (VPS tungho2) → không runtime nào hợp lệ, ghi rõ bản quá cũ", M.js_runtime_notes())
    VERS["/usr/bin/node"] = "22.14.0"
    ok(M.js_runtime_opts() == {"js_runtimes": {"node": {"path": "/usr/bin/node"}}} and M.cli_js_args() == ["--js-runtimes", "node:/usr/bin/node"],
       "node 22 → dùng node kèm đường dẫn", M.cli_js_args())
    M._pip_deno_bin = lambda: "/srv/tubecli/.venv/bin/deno"
    VERS.update({"/usr/bin/node": "20.19.0", "/srv/tubecli/.venv/bin/deno": "2.9.6"})
    ok(list(M.js_runtimes()) == ["deno"] and M.js_runtimes()["deno"]["path"] == "/srv/tubecli/.venv/bin/deno"
       and M.cli_js_args() == ["--js-runtimes", "deno:/srv/tubecli/.venv/bin/deno"],
       "deno của pip (ngoài PATH systemd) → dùng, kèm đường dẫn; node 20 bị bỏ", M.js_runtimes())
    M.shutil.which = lambda name: None
    M._pip_deno_bin = lambda: None
    ok(M.js_runtime_opts() == {} and M.cli_js_args() == [] and M.js_runtime_notes() == [], "không runtime nào → để yt-dlp tự lo")
finally:
    M.shutil.which, M._runtime_version, M._pip_deno_bin = real_which, real_ver, real_pipdeno
    M.js_runtimes = lambda: dict(ENV["rt"])

print("── D. nạp lại module, status, tuỳ chọn ─────────────────────")
sys.modules["yt_dlp.fake_sub_for_test"] = object()
real_reload()
ok("yt_dlp.fake_sub_for_test" not in sys.modules and "yt_dlp" not in sys.modules, "_reload_module xoá yt_dlp khỏi sys.modules")
reset(version="2026.09.20")
s = M.status()
ok(s["installed"] and s["version"] == "2026.09.20" and s["cli"] and set(s) >= {"auto_update", "latest", "checked_at", "last_error"}, "status()", s)
del M.auto_update_enabled
import importlib  # noqa: E402
M2 = importlib.reload(M)
from tubecli.extensions.video_downloader import routes as VD  # noqa: E402
VD._settings_cache = None
ok(M2.auto_update_enabled() is True, "chưa có file cài đặt → tự cập nhật BẬT")
os.makedirs(os.environ["TUBECLI_DATA_DIR"], exist_ok=True)
json.dump({"ytdlp_auto_update": False}, open(os.path.join(os.environ["TUBECLI_DATA_DIR"], "downloader_settings.json"), "w", encoding="utf-8"))
VD._settings_cache = None
ok(M2.auto_update_enabled() is False, "đọc tuỳ chọn đã tắt ở Video Downloader")
VD._settings_cache = None

shutil.rmtree(TMP, ignore_errors=True)
print()
print(f"{PASS}/{PASS + FAIL} PASS" if not FAIL else f"{PASS}/{PASS + FAIL} PASS — {FAIL} HỎNG")
sys.exit(1 if FAIL else 0)
