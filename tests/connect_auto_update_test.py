"""TubeCLI Connect tự cập nhật TubeCLI ngay trong bước ghép nối khi lõi là bản cũ (14/11/2026).

Chạy:  python tests/connect_auto_update_test.py      (mã thoát 0 = đạt)

Vì sao: máy đang chạy lõi trước .234 không có lệnh `tubecli cloud-key`, cửa sổ ghép nối báo «bản cũ … nhập mật
khẩu». User: «bạn cho client cập nhật luôn trong chỗ ghép nối chứ» / «làm luôn để máy khác không sửa thủ công nữa».

Kiểm bằng REPO GIT TẠM thật (origin + bản cài clone từ nó): chỉ tiến nhanh, không đụng thư mục có file sửa tay hay
commit riêng, dừng máy chủ trước khi đổi mã, bản mới không bật được thì lùi về bản cũ. Máy chủ / pip / lệnh tubecli
đều GIẢ — không chạm bản TubeCLI cài thật của máy, không mạng.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass
SRC = ROOT / "client" / "tubecli_connect.pyw"
TXT = SRC.read_text(encoding="utf-8")
TMP = tempfile.mkdtemp(prefix="tc_autoupd_")
os.environ["APPDATA"] = os.path.join(TMP, "appdata")

if not shutil.which("git"):
    print("SKIP: máy không có git")
    sys.exit(0)

mod = types.ModuleType("tubecli_connect")
mod.__file__ = str(SRC)
exec(compile(TXT, str(SRC), "exec"), mod.__dict__)

checks = failures = 0


def check(name, ok, detail=""):
    global checks, failures
    checks += 1
    print(("[PASS] " if ok else "[FAIL] ") + name + ("" if ok else f"  {str(detail)[:300]}"))
    if not ok:
        failures += 1


LOGS = []
mod.log = lambda m: LOGS.append(str(m))
ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid", GIT_COMMITTER_NAME="t",
           GIT_COMMITTER_EMAIL="t@example.invalid", GIT_CONFIG_NOSYSTEM="1")
mod.clean_env = lambda: dict(ENV)


def git(cwd, *args):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env=ENV)
    assert r.returncode == 0, (args, r.stderr)
    return r.stdout.strip()


def make_pair(name):
    """origin (bản phát hành) + install (clone ở bản cũ). Trả (origin, install)."""
    origin = os.path.join(TMP, name + "_origin")
    install = os.path.join(TMP, name + "_install")
    os.makedirs(origin)
    git(origin, "init", "-q", "-b", "main")
    Path(origin, "pyproject.toml").write_text("[project]\nname='x'\nversion='1'\n", encoding="utf-8")
    Path(origin, "core.py").write_text("VERSION = 233\n", encoding="utf-8")
    git(origin, "add", "-A")
    git(origin, "commit", "-q", "-m", "old")
    git(TMP, "clone", "-q", origin, install)
    Path(origin, "core.py").write_text("VERSION = 234\n", encoding="utf-8")
    git(origin, "add", "-A")
    git(origin, "commit", "-q", "-m", "new")
    return origin, install


EVENTS = []


def wire(install, start_ok=True, stop_ok=True, port_pid=0):
    EVENTS.clear()
    mod.server_cmd = lambda: (["python", "-m", "tubecli"] + list(mod.SERVE_ARGS), install)
    mod.node_stop = lambda timeout=12.0: EVENTS.append("stop") or stop_ok
    mod._pid_of_port = lambda port: port_pid
    seq = list(start_ok) if isinstance(start_ok, (list, tuple)) else None

    def _start():
        EVENTS.append("start:" + Path(install, "core.py").read_text(encoding="utf-8").strip())
        return seq.pop(0) if seq else bool(start_ok)
    mod.start_tubecli = _start
    mod.repair_deps = lambda d, say=None: EVENTS.append("deps") or True


# ── A. đường thẳng ────────────────────────────────────────────────────────────
origin, install = make_pair("a")
wire(install)
said = []
ok, msg = mod.update_tubecli(said.append)
check("A1 thư mục cài sạch, bản cũ → cập nhật được", ok, msg)
check("A2 mã trên đĩa là bản mới", Path(install, "core.py").read_text(encoding="utf-8").strip() == "VERSION = 234")
check("A3 thứ tự: TẮT máy chủ → đổi mã → BẬT lại (bật thấy mã mới)", EVENTS == ["stop", "start:VERSION = 234"], EVENTS)
check("A4 thư viện không đổi → không chạy pip", "deps" not in EVENTS)
check("A5 người dùng thấy từng bước", any("đang tải bản mới" in m for m in said) and any("đã cập nhật" in m for m in said), said)
ok, msg = mod.update_tubecli()
check("A6 đã ở bản mới nhất → không làm gì, không tắt máy chủ lần nữa", (not ok) and "đã ở bản mới nhất" in msg
      and EVENTS == ["stop", "start:VERSION = 234"], (msg, EVENTS))

# thư viện đổi → cài sau khi đã tắt máy chủ
origin, install = make_pair("b")
Path(origin, "pyproject.toml").write_text("[project]\nname='x'\nversion='2'\n", encoding="utf-8")
git(origin, "add", "-A")
git(origin, "commit", "-q", "-m", "deps")
wire(install)
ok, msg = mod.update_tubecli()
check("A7 pyproject đổi → cài thư viện SAU khi tắt, TRƯỚC khi bật", ok and EVENTS[0] == "stop" and EVENTS[1] == "deps"
      and EVENTS[2].startswith("start:"), EVENTS)

# ── B. những lúc KHÔNG được đụng ──────────────────────────────────────────────
origin, install = make_pair("c")
Path(install, "core.py").write_text("VERSION = 233  # sửa tay\n", encoding="utf-8")
wire(install)
ok, msg = mod.update_tubecli()
check("B1 có file sửa tay → từ chối, nói tên file, KHÔNG tắt máy chủ, không mất chỗ sửa", (not ok) and "sửa tay" in msg
      and "core.py" in msg and EVENTS == [] and "sửa tay" in Path(install, "core.py").read_text(encoding="utf-8"), (msg, EVENTS))

origin, install = make_pair("d")
Path(install, "mine.py").write_text("x = 1\n", encoding="utf-8")
git(install, "add", "-A")
git(install, "commit", "-q", "-m", "local commit")
wire(install)
ok, msg = mod.update_tubecli()
check("B2 có commit riêng (không tiến nhanh được) → từ chối, không tắt máy chủ, commit còn nguyên", (not ok)
      and "commit riêng" in msg and EVENTS == [] and os.path.isfile(os.path.join(install, "mine.py")), (msg, EVENTS))

origin, install = make_pair("e")
Path(install, "ghi_chu.txt").write_text("file chưa theo dõi\n", encoding="utf-8")
wire(install)
ok, msg = mod.update_tubecli()
check("B3 file CHƯA theo dõi (dữ liệu, ghi chú) không cản cập nhật và còn nguyên", ok
      and os.path.isfile(os.path.join(install, "ghi_chu.txt")), msg)

plain = os.path.join(TMP, "plain")
os.makedirs(plain)
wire(plain)
ok, msg = mod.update_tubecli()
check("B4 bản cài không phải git → từ chối", (not ok) and "không phải bản git" in msg and EVENTS == [], msg)

origin, install = make_pair("f")
wire(install, stop_ok=False, port_pid=4242)
ok, msg = mod.update_tubecli()
check("B5 máy chủ đang bận, chưa tắt được → KHÔNG đổi mã", (not ok) and "chưa tắt được" in msg
      and Path(install, "core.py").read_text(encoding="utf-8").strip() == "VERSION = 233", msg)

origin, install = make_pair("g")
git(install, "remote", "set-url", "origin", os.path.join(TMP, "khong_ton_tai"))     # không tải được
wire(install)
ok, msg = mod.update_tubecli()
check("B6 không tải được bản mới → từ chối, không tắt máy chủ", (not ok) and "không tải được bản mới" in msg and EVENTS == [], (msg, EVENTS))

# ── C. bản mới không bật được → lùi ───────────────────────────────────────────
origin, install = make_pair("h")
wire(install, start_ok=[False, True])
ok, msg = mod.update_tubecli()
check("C1 bản mới không bật được → quay về bản cũ rồi bật lại", (not ok) and "quay về bản cũ" in msg
      and Path(install, "core.py").read_text(encoding="utf-8").strip() == "VERSION = 233"
      and EVENTS == ["stop", "start:VERSION = 234", "start:VERSION = 233"], (msg, EVENTS))

# ── D. pairing_credential ─────────────────────────────────────────────────────
KEY = "tck_" + "A1b2C3d4" * 5 + "xyz"
ST = {"cred": [("", "legacy", ""), (KEY, "key", "")], "upd": (True, "ok"), "calls": 0}
mod.cloud_credential = lambda: ST["cred"].pop(0) if len(ST["cred"]) > 1 else ST["cred"][0]


def _upd(say=None):
    ST["calls"] += 1
    return ST["upd"]


mod.update_tubecli = _upd
mod.UPDATE_STATE.update(tried=False, note="")
check("D1 lõi cũ → tự cập nhật → xin lại được khoá: không hỏi mật khẩu", mod.pairing_credential() == (KEY, "key", "")
      and ST["calls"] == 1)
ST.update(cred=[("", "legacy", "")], upd=(False, "thư mục cài có 2 file đã sửa tay"), calls=0)
mod.UPDATE_STATE.update(tried=False, note="")
check("D2 cập nhật không được → vẫn «legacy» (hỏi mật khẩu)", mod.pairing_credential() == ("", "legacy", "") and ST["calls"] == 1)
check("D3 …và lời nhắc nói rõ vì sao chưa tự cập nhật", mod.old_core_hint().startswith(mod.OLD_CORE_HINT)
      and "2 file đã sửa tay" in mod.old_core_hint(), mod.old_core_hint())
mod.pairing_credential()
mod.pairing_credential()
check("D4 chỉ thử cập nhật MỘT lần mỗi lượt chạy (bấm Kết nối lại không tắt máy chủ lần nữa)", ST["calls"] == 1, ST["calls"])
ST.update(cred=[(KEY, "key", "")], calls=0)
mod.UPDATE_STATE.update(tried=False, note="")
check("D5 lõi mới → không bao giờ gọi cập nhật", mod.pairing_credential() == (KEY, "key", "") and ST["calls"] == 0)

# ── E. tĩnh ───────────────────────────────────────────────────────────────────
up = TXT[TXT.index("def update_tubecli"):TXT.index("def pairing_credential")]
check("E1 chỉ tiến nhanh: merge --ff-only, không pull / rebase", '"merge", "--ff-only", "FETCH_HEAD"' in up
      and '"pull"' not in up and "rebase" not in up)
check("E2 reset --hard chỉ dùng để LÙI về đúng commit cũ khi bản mới không bật được",
      up.count('"reset", "--hard"') == 1 and '["reset", "--hard", before]' in up)
check("E3 ba chỗ ghép nối đều đi qua pairing_credential", TXT.count("pairing_credential(") >= 4
      and "cred, kind, err = cloud_credential()" not in TXT[TXT.index("def ask_pairing_console"):])

print(f"\n{checks - failures}/{checks} PASS")
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(1 if failures else 0)
