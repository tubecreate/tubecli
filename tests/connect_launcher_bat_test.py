# -*- coding: utf-8 -*-
"""Client Connect trên Windows: máy khách 9/11/2026 hỏng dây chuyền.

  1. lõi .230/.231 lỗi cú pháp trên Python 3.11 → máy chủ thoát ngay
  2. client coi mọi lần bật hỏng là «thiếu thư viện» → `pip install -e .` → pip gỡ dở bản cũ, không khôi phục được
     Scripts\\tubecli.exe (file đang bị giữ)
  3. `which("tubecli")` vớ TubeCLI.bat (install.ps1) → menu tương tác «Chọn một tùy chọn: Aborted!» rồi `pause`

  A. launcher chỉ nhận .exe trên Windows (.bat / .cmd bị bỏ qua → lùi về python -m tubecli.main)
  B. crash_needs_deps: chỉ thiếu module mới chạy pip; SyntaxError / menu Aborted! thì không
  C. prepare_node: lỗi cú pháp → KHÔNG gọi repair_deps

Run:  python tests/connect_launcher_bat_test.py
"""
import os
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
SRC = ROOT / "client" / "tubecli_connect.pyw"
TMP = tempfile.mkdtemp(prefix="tc_launcher_")
os.environ["APPDATA"] = TMP

PASS = FAIL = 0


def check(label, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + bool(ok), FAIL + (not ok)
    print(("[PASS] " if ok else "[FAIL] ") + label + ("" if ok else f"  → {detail}"))


def load(plat):
    old = sys.platform
    try:
        sys.platform = plat
        m = types.ModuleType("tc_" + plat)
        m.__file__ = str(SRC)
        exec(compile(SRC.read_text(encoding="utf-8"), str(SRC), "exec"), m.__dict__)
        return m
    finally:
        sys.platform = old


W = load("win32")
d = os.path.join(TMP, "TubeCLI")
os.makedirs(d, exist_ok=True)
open(os.path.join(d, "TubeCLI.bat"), "w").close()
W.find_install = lambda: d
W.python_with_tubecli = lambda _d="": r"C:\Py311\python.exe"

print("A. launcher")
W.shutil.which = lambda name: os.path.join(d, "TubeCLI.BAT") if name == "tubecli" else None
check("A1 which() trả TubeCLI.bat → không nhận", W.tubecli_launcher() == "")
cmd, cwd = W.server_cmd()
check("A2 server_cmd lùi về python -m tubecli.main api start (không chạy .bat)",
      cmd[:3] == [r"C:\Py311\python.exe", "-m", "tubecli.main"] and "api" in cmd, cmd)
W.shutil.which = lambda name: r"C:\Py\Scripts\tubecli.cmd" if name == "tubecli" else None
check("A3 .cmd cũng không nhận", W.tubecli_launcher() == "")
W.shutil.which = lambda name: r"C:\Py\Scripts\tubecli.exe" if name == "tubecli" else None
cmd, _ = W.server_cmd()
check("A4 tubecli.exe thì vẫn dùng launcher như cũ", cmd[0] == r"C:\Py\Scripts\tubecli.exe" and "api" in cmd, cmd)
L = load("linux")
L.shutil.which = lambda name: "/usr/local/bin/tubecli" if name == "tubecli" else None
check("A5 Linux: launcher không đuôi vẫn nhận", L.tubecli_launcher() == "/usr/local/bin/tubecli")

print("B. crash_needs_deps")
log = os.path.join(TMP, "server.log")


def write(*lines):
    with open(log, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


write("==== 2026-11-09 09:00:00 old run", "ModuleNotFoundError: No module named 'click'",
      "==== 2026-11-09 09:16:30 tubecli.exe api start", "Traceback (most recent call last):",
      '  File "C:\\Users\\PC\\tubecli\\tubecli\\core\\muse.py", line 1292',
      "SyntaxError: f-string: expecting '}'")
check("B1 SyntaxError (lượt cuối) → không phải thiếu thư viện", W.crash_needs_deps(log) is False)
write("==== 2026-11-09 09:16:30 x", "Traceback (most recent call last):", "ModuleNotFoundError: No module named 'click'")
check("B2 thiếu module → chạy pip", W.crash_needs_deps(log) is True)
write("==== 2026-11-09 09:48:45 x", "║  9. Cập nhật TubeCLI ║", "Chọn một tùy chọn: Aborted!", "C:\\Users\\PC\\TubeCLI>pause")
check("B3 menu tương tác «Aborted!» → không chạy pip", W.crash_needs_deps(log) is False)
check("B4 không có log → như cũ (chạy pip)", W.crash_needs_deps(os.path.join(TMP, "none.log")) is True)
write("==== 2026-11-09 09:16:30 x", "port 5295 busy?", "exit")
check("B5 không có dấu lỗi rõ → như cũ (chạy pip)", W.crash_needs_deps(log) is True)

print("C. prepare_node")
called = []
W.tubecli_up = lambda timeout=2.0: False
W.refresh_path_win = lambda: None
W.start_tubecli = lambda: False
W.repair_deps = lambda dd, say=None: called.append(dd) or True
W.HOME = TMP
write("==== 2026-11-09 09:16:30 x", "SyntaxError: f-string: expecting '}'")
said = []
ok, _ = W.prepare_node(said.append)
check("C1 lỗi cú pháp → không gọi pip, báo cần cập nhật", ok is False and not called
      and any("cập nhật" in s for s in said), (called, said))
write("==== 2026-11-09 09:16:30 x", "ModuleNotFoundError: No module named 'fastapi'")
ok, _ = W.prepare_node(said.append)
check("C2 thiếu module → vẫn tự cài phụ thuộc như cũ", called == [d], called)

print(f"\n{PASS}/{PASS + FAIL} PASS")
sys.exit(1 if FAIL else 0)
