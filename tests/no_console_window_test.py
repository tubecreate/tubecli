# Tiến trình con KHÔNG được nháy cửa sổ đen lên mặt người dùng.
#
# Chạy:  python tests/no_console_window_test.py      (exit 0 = pass)
#
# VÌ SAO CÓ FILE NÀY
#   Trên Windows, mỗi chương trình console (node.exe, git, cmd, ffmpeg…) chạy bằng
#   subprocess được hệ điều hành cấp một cửa sổ đen — trừ khi truyền CREATE_NO_WINDOW.
#   TubeCLI sinh rất nhiều tiến trình node, nên mở một phiên trình duyệt là vài khung
#   đen nhảy lên che màn hình rồi nằm đó tới hết phiên (người dùng chụp ảnh 9/9/2026).
#
#   Đếm được 111 chỗ gọi subprocess không truyền cờ. Vá từng chỗ thì vừa sót vừa hỏng
#   lại ở dòng code tiếp theo ai đó viết, nên cờ được đặt MẶC ĐỊNH ngay tại Popen —
#   subprocess.run/call/check_output đều đi qua đó. Test này canh đúng hai thứ:
#   quyết định cờ có đúng không, và cái hook có thật sự nằm trên Popen không.
import io
import os
import subprocess
import sys
from pathlib import Path

# Console Windows mặc định cp1252: in tiếng Việt vào đó là UnicodeEncodeError.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} -> {detail}")


from tubecli.core import proc  # noqa: E402

# ── 1. Quyết định cờ ────────────────────────────────────────────────────────
check("POSIX không đụng gì tới cờ", proc.no_window_flags(0, windows=False) == 0)
check("Windows thêm CREATE_NO_WINDOW",
      proc.no_window_flags(0, windows=True) == proc.CREATE_NO_WINDOW)
check("giữ nguyên cờ có sẵn của người gọi",
      proc.no_window_flags(proc.CREATE_NEW_PROCESS_GROUP, windows=True)
      == (proc.CREATE_NO_WINDOW | proc.CREATE_NEW_PROCESS_GROUP))

# Ba cờ console loại trừ nhau; ai đã nói rõ ý muốn thì phải được tôn trọng, ghép
# thêm vào là hành vi không xác định chứ không phải "an toàn hơn".
check("người gọi xin console riêng → KHÔNG ghép thêm",
      proc.no_window_flags(proc.CREATE_NEW_CONSOLE, windows=True) == proc.CREATE_NEW_CONSOLE)
check("người gọi xin tách hẳn console → KHÔNG ghép thêm",
      proc.no_window_flags(proc.DETACHED_PROCESS, windows=True) == proc.DETACHED_PROCESS)
check("đã có sẵn NO_WINDOW thì không nhân đôi",
      proc.no_window_flags(proc.CREATE_NO_WINDOW, windows=True) == proc.CREATE_NO_WINDOW)

# ── 2. Hook nằm đúng chỗ và không cài chồng ─────────────────────────────────
first = proc.install_no_window_default()
again = proc.install_no_window_default()
if os.name == "nt":
    check("cài được trên Windows", first is True or getattr(subprocess.Popen, "_tc_no_window", False))
    check("gọi lần hai không cài chồng", again is False)
    check("dấu vết nằm trên chính Popen", getattr(subprocess.Popen, "_tc_no_window", False))
else:
    check("không phải Windows thì không đụng vào Popen", first is False and again is False)

# ── 3. Cờ THẬT mà một tiến trình thật nhận được ─────────────────────────────
# Không tin lời hàm: cắm một điệp viên xuống DƯỚI hook rồi chạy lệnh thật.
if os.name == "nt":
    seen = {}
    original = subprocess.Popen.__init__

    def _spy(self, *a, **kw):
        seen["flags"] = kw.get("creationflags", 0)
        return original(self, *a, **kw)

    subprocess.Popen.__init__ = _spy
    proc.install_no_window_default.__wrapped__ = None       # cho phép cắm lại
    subprocess.Popen._tc_no_window = False
    proc.install_no_window_default()
    try:
        r = subprocess.run(["cmd", "/c", "echo tubecli"], capture_output=True, text=True, timeout=60)
        check("lệnh vẫn chạy đúng", r.stdout.strip() == "tubecli", r.stdout)
        check("và nó nhận CREATE_NO_WINDOW",
              bool(seen.get("flags", 0) & proc.CREATE_NO_WINDOW), hex(seen.get("flags", 0)))
    finally:
        subprocess.Popen.__init__ = original
        subprocess.Popen._tc_no_window = False

# ── 4. Cắm từ lúc khởi động, ở CẢ máy chủ lẫn CLI ───────────────────────────
for rel in ("tubecli/api/server.py", "tubecli/main.py"):
    src = io.open(ROOT / rel, encoding="utf-8").read()
    check(f"{rel} gọi install_no_window_default()", "_tc_proc.install_no_window_default()" in src)

# ── 5. Trình duyệt: ẩn cửa sổ NHƯNG vẫn giữ nhóm tiến trình riêng ───────────
# Nhóm riêng để Ctrl+C ở console máy chủ không giật mất trình duyệt giữa phiên;
# bỏ mất nó khi đi thêm cờ ẩn là làm hỏng một tính năng khác.
from tubecli.extensions.browser.process_manager import _process_group_kwargs  # noqa: E402

win = _process_group_kwargs(windows=True)["creationflags"]
check("trình duyệt: có CREATE_NO_WINDOW", bool(win & proc.CREATE_NO_WINDOW), hex(win))
check("trình duyệt: VẪN có CREATE_NEW_PROCESS_GROUP",
      bool(win & proc.CREATE_NEW_PROCESS_GROUP), hex(win))
check("POSIX vẫn dùng start_new_session",
      _process_group_kwargs(windows=False) == {"start_new_session": True})

# ── 6. Ba tiến trình node của browser_scripts ───────────────────────────────
sr = io.open(ROOT / "tubecli/extensions/browser_scripts/script_routes.py", encoding="utf-8").read()
check("cả ba lần chạy node đều truyền cờ ẩn",
      sr.count("_proc.hidden_kwargs()") >= 3, sr.count("_proc.hidden_kwargs()"))

print("=" * 62)
print(f"{PASS}/{PASS + FAIL} PASS" if not FAIL else f"{FAIL} FAIL / {PASS + FAIL}")
sys.exit(1 if FAIL else 0)
