# -*- coding: utf-8 -*-
"""TubeCLI Connect: nút Đổi mật khẩu, nút Cài lại, và cửa chặn máy chủ ma.

Những gì phải đúng mà không ai nhìn thấy khi chúng sai:
  * mật khẩu KHÔNG BAO GIỜ vào connect.log;
  * đổi qua route API khi biết mật khẩu cũ (huỷ được phiên), rơi về `tubecli
    password --new` chỉ khi mật khẩu đã nhớ không còn đúng;
  * cloud được báo, và nếu cloud không nhận thì câu trả về NÓI RA;
  * cổng đang bị giữ thì không bật máy chủ thứ hai — từ BẤT KỲ đường nào.
"""
import io
import json
import os
import sys
import tempfile
import types
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

SRC = ROOT / "client" / "tubecli_connect.pyw"
TMP = tempfile.mkdtemp(prefix="tc_connect_pw_")
os.environ["APPDATA"] = TMP            # cấu hình/log của test không chạm máy thật

mod = types.ModuleType("tubecli_connect")
mod.__file__ = str(SRC)
exec(compile(SRC.read_text(encoding="utf-8"), str(SRC), "exec"), mod.__dict__)

checks = failures = 0


def check(name, ok, detail=""):
    global checks, failures
    checks += 1
    if ok:
        print(f"  ok  {name}")
        return
    failures += 1
    print(f"  FAIL {name} — {detail}")


LOGS = []
mod.log = lambda m: LOGS.append(str(m))
NEW = "mat-khau-moi-9x"


class Resp:
    def __init__(self, status=200, body=b"{}"):
        self.status, self._b = status, body

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def http_error(url, code, body):
    return urllib.error.HTTPError(url, code, "x", {}, io.BytesIO(json.dumps(body).encode()))


# ── 1. luật ô mật khẩu ─────────────────────────────────────────────────────
print("── ô mật khẩu ────────────────────────────────────────────────")
check("dưới 6 ký tự → báo", "6 ký tự" in mod.password_problem("12345", "12345"))
check("hai lần không khớp → báo", "không khớp" in mod.password_problem("abcdef", "abcdeg"))
check("đặt lại 123456 → báo", "123456" in mod.password_problem("123456", "123456"))
check("hợp lệ → rỗng", mod.password_problem(NEW, NEW) == "")

# ── 2. đường 1: route API khi biết mật khẩu cũ ─────────────────────────────
print("── đổi mật khẩu ──────────────────────────────────────────────")
seen = {}


def fake_urlopen_ok(req, timeout=0):
    seen["url"], seen["body"] = req.full_url, json.loads(req.data.decode())
    return Resp(200)


mod.urllib.request.urlopen = fake_urlopen_ok
ran = []
mod.subprocess.run = lambda *a, **k: ran.append(a) or types.SimpleNamespace(returncode=0, stdout="")
ok, msg, how = mod.change_node_password(NEW, current="cu-123456x")
check("biết mật khẩu cũ → đổi qua route API", ok and how == "api", f"{ok} {how} {msg}")
check("…gửi đúng current_password + new_password",
      seen["url"].endswith("/api/v1/auth/password")
      and seen["body"] == {"current_password": "cu-123456x", "new_password": NEW}, str(seen))
check("…và KHÔNG chạy lệnh CLI", not ran)

# ── 3. mật khẩu nhớ sai (401) → đường 2: `tubecli password --new` ──────────
mod.urllib.request.urlopen = lambda req, timeout=0: (_ for _ in ()).throw(
    http_error(req.full_url, 401, {"detail": "Mật khẩu hiện tại không đúng."}))
mod.server_cmd = lambda: ([r"C:\Py\Scripts\tubecli.exe"] + mod.SERVE_ARGS, r"C:\TubeCLI")
calls = []


def fake_run(args, **kw):
    calls.append((args, kw))
    return types.SimpleNamespace(returncode=0, stdout="Đã đổi mật khẩu.")


mod.subprocess.run = fake_run
ok, msg, how = mod.change_node_password(NEW, current="da-doi-o-cho-khac")
check("401 → rơi về CLI", ok and how == "cli", f"{ok} {how} {msg}")
check("…lệnh là `tubecli password --new <mới>`, bỏ đuôi `api start …`",
      calls and calls[0][0] == [r"C:\Py\Scripts\tubecli.exe", "password", "--new", NEW], str(calls[:1]))
check("…chạy trong thư mục cài, không mở cửa sổ", calls and calls[0][1].get("cwd") == r"C:\TubeCLI")
check("…và NÓI RA phiên đang mở còn sống tới lần khởi động lại", "khởi động lại" in msg, msg)

# pythonw không có stdout → đổi sang python.exe cạnh nó
calls.clear()
mod.server_cmd = lambda: ([r"C:\v\Scripts\pythonw.exe", "-m", "tubecli.main"] + mod.SERVE_ARGS, r"C:\T")
real_isfile = mod.os.path.isfile
mod.os.path.isfile = lambda p: p == r"C:\v\Scripts\python.exe" or real_isfile(p)
mod.change_node_password(NEW)
mod.os.path.isfile = real_isfile
check("venv pythonw → chạy bằng python.exe cùng thư mục (pythonw nuốt stdout rồi ngã)",
      calls and calls[0][0][:3] == [r"C:\v\Scripts\python.exe", "-m", "tubecli.main"], str(calls[:1]))

# CLI từ chối → trả nguyên câu của lõi
mod.subprocess.run = lambda *a, **k: types.SimpleNamespace(returncode=1, stdout="Mật khẩu phải có ít nhất 6 ký tự.")
ok, msg, how = mod.change_node_password("abc")
check("CLI từ chối → trả đúng câu của lõi", not ok and "6 ký tự" in msg, msg)

# route API trả lỗi khác 401 → dừng ở đó, không đổi lén bằng CLI
calls.clear()
mod.subprocess.run = fake_run
mod.urllib.request.urlopen = lambda req, timeout=0: (_ for _ in ()).throw(
    http_error(req.full_url, 400, {"detail": "Không thể đặt lại đúng mật khẩu mặc định."}))
ok, msg, how = mod.change_node_password(NEW, current="cu-123456x")
check("route API 400 → trả câu ấy, KHÔNG rơi xuống CLI", not ok and "mặc định" in msg and not calls, msg)

# ── 4. báo cloud ──────────────────────────────────────────────────────────
print("── báo cloud ─────────────────────────────────────────────────")
seen.clear()


def cloud_ok(req, timeout=0):
    seen["url"], seen["body"] = req.full_url, json.loads(req.data.decode())
    return Resp(200, b'{"ok": true}')


mod.urllib.request.urlopen = cloud_ok
c_ok, c_msg = mod.sync_cloud_password({"tunnel_token": "TOKEN"}, NEW)
check("gửi tunnel token + mật khẩu mới tới /api/servers/pair/password",
      c_ok and seen["url"].endswith("/api/servers/pair/password")
      and seen["body"] == {"tunnel_token": "TOKEN", "tubecli_password": NEW}, str(seen))
check("chưa ghép nối → nói rõ, không gọi", mod.sync_cloud_password({}, NEW)[0] is False)
mod.urllib.request.urlopen = lambda req, timeout=0: (_ for _ in ()).throw(
    http_error(req.full_url, 409, {"error": "Mật khẩu này chưa đăng nhập được vào máy"}))
c_ok, c_msg = mod.sync_cloud_password({"tunnel_token": "TOKEN"}, NEW)
check("cloud từ chối → trả đúng câu của cloud", not c_ok and "chưa đăng nhập được" in c_msg, c_msg)

# ── 5. Bridge.change_password: nhớ mật khẩu, báo cloud, không để lộ vào log ─
print("── Bridge ────────────────────────────────────────────────────")
b = mod.Bridge({"name": "may", "tunnel_token": "TOKEN", "password": "cu-123456x"})
written = []
mod.conf_write = lambda c: written.append(dict(c))
mod.change_node_password = lambda new, current="": (True, "Đã đổi mật khẩu.", "api")
mod.sync_cloud_password = lambda conf, new: (False, "không gọi được cloud: timeout")
res = []
b.change_password(NEW, done=lambda ok, msg: res.append((ok, msg)))
check("đổi xong → cấu hình nhớ mật khẩu mới", written and written[-1].get("password") == NEW)
check("cloud không nhận → câu trả về NÓI RA", res and res[0][0] and "CHƯA nhận" in res[0][1], str(res))
check("busy trả về rỗng sau khi xong", b.busy == "")
b.busy = "đang bận việc khác"
res.clear()
b.change_password(NEW, done=lambda ok, msg: res.append((ok, msg)))
check("đang bận → không đổi, báo bận", res and res[0][0] is False and "bận" in res[0][1], str(res))
b.busy = ""
check("mật khẩu mới KHÔNG xuất hiện trong bất kỳ dòng log nào", not any(NEW in ln for ln in LOGS),
      [ln for ln in LOGS if NEW in ln][:2])

# ── 6. Bridge.reinstall: tắt → cài (giữ busy) → bật ────────────────────────
order = []
mod.node_stop = lambda *a, **k: order.append("stop") or True
mod.install_tubecli = lambda lang="vi", reason="": order.append(("install", reason, b.busy)) or True
mod.start_tubecli = lambda: order.append("start") or True
mod.notify = lambda *a, **k: order.append("notify")
b.reinstall()
check("cài lại theo đúng thứ tự: tắt → cài → bật → báo",
      [o if isinstance(o, str) else o[0] for o in order] == ["stop", "install", "start", "notify"], str(order))
inst = [o for o in order if isinstance(o, tuple)][0]
check("…trình cài chạy với lý do 'Cài lại' (log không nói 'chưa có TubeCLI')", "Cài lại" in inst[1], str(inst))
check("…busy GIỮ suốt lúc cài (vòng canh không bật chen vào)", bool(inst[2]), str(inst))
check("…và trả về rỗng khi xong", b.busy == "")

# ── 7. cửa chặn máy chủ ma ─────────────────────────────────────────────────
print("── máy chủ ma ────────────────────────────────────────────────")
LOGS.clear()
mod.tubecli_up = lambda timeout=2.0: False
mod._pid_of_port = lambda port: 4242
mod.subprocess.Popen = lambda *a, **k: (_ for _ in ()).throw(AssertionError("không được bật máy chủ"))
check("cổng đang bị giữ → không bật thêm, coi như đang chạy", mod._start_tubecli_locked() is True)
check("…và ghi log vì sao", any("không bật thêm" in ln for ln in LOGS), LOGS[-2:])
started = []
mod.node_stop = lambda *a, **k: False
mod.start_tubecli = lambda: started.append(1) or True
check("khởi động lại mà máy cũ chưa nhả cổng → báo hỏng, không bật chồng",
      mod.node_restart() is False and not started)

# ── 8. menu khay ───────────────────────────────────────────────────────────
keys = [k for k, _ in mod.TRAY_ITEMS]
check("menu khay có Đổi mật khẩu + Cài lại", "password" in keys and "reinstall" in keys, str(keys))

print()
print(f"{checks - failures}/{checks} PASS" if not failures else f"{checks - failures}/{checks} PASS — {failures} HỎNG")
sys.exit(1 if failures else 0)
