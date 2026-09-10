# Tự khởi động lại khi KHÔNG có ai dựng lại hộ — chạy thật, không chỉ đọc mã.
#
# Chạy:  python tests/restart_selfheal_test.py     (exit 0 = pass)
#
# VÌ SAO CÓ FILE NÀY
#   Máy Windows chạy TubeCLI bằng TubeCLI.bat (một cửa sổ console): không systemd,
#   và có thể cũng không có TubeCLI Connect canh nhịp tim. Khi đó `_schedule_restart`
#   trả False — cố ý, vì thoát mà không ai dựng lại thì máy chết im. Hệ quả: nút cập
#   nhật `git pull` được code xuống đĩa nhưng tiến trình vẫn giữ mã cũ trong RAM.
#   Người dùng bấm cập nhật, máy báo xong, số phiên bản KHÔNG ĐỔI (báo 10/9/2026).
#
#   Nay có đường lui cuối: `_spawn_relauncher` sinh một tiến trình RỜI, nó đợi rồi
#   chạy lại chính dòng lệnh đang chạy; chỉ khi sinh được thì mới thoát.
#
#   Test này CHẠY THẬT cơ chế đó: tiến trình cha thoát bằng os._exit, và một tiến
#   trình khác phải sống sót rồi chạy lại đúng dòng lệnh. Đọc mã không đủ — điều dễ
#   sai nhất ở đây là tiến trình con chết theo console của cha, mà chuyện đó chỉ lộ
#   ra khi chạy.
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

failures, checks = [], 0


def check(label, ok, detail=""):
    global checks
    checks += 1
    print(("  ok  " if ok else "  FAIL") + " " + label + (f"  ({detail})" if detail else ""))
    if not ok:
        failures.append(label)


SRC = ROOT / "tubecli" / "api" / "server.py"
src = SRC.read_text(encoding="utf-8")

# ── A. fail-safe: chỉ thoát khi đã sinh được tiến trình khởi động lại ──────
i = src.index("    if _spawn_relauncher(delay):")
tail = src[i:i + 240]
check("A chỉ thoát khi _spawn_relauncher thành công",
      "threading.Thread(target=_bye" in tail and "return False" in tail, tail.split("\n")[0])
check("A sinh không được thì vẫn trả False", src.count("    return False\n") >= 1)

# ── B. chạy thật: cha thoát, tiến trình rời chạy lại ──────────────────────
j = src.index("def _spawn_relauncher(delay: float) -> bool:")
k = src.index("\ndef _schedule_restart", j)
fn = src[j:k]

work = Path(tempfile.mkdtemp(prefix="tubecli_relaunch_"))
mark = work / "mark.txt"
child = work / "child.py"
child.write_text(
    "import os, sys, time\n"
    "from pathlib import Path\n"
    f"MARK = Path(r'{mark}')\n"
    + fn +
    "\n"
    "if __name__ == '__main__':\n"
    "    with MARK.open('a', encoding='utf-8') as f:\n"
    "        f.write('run pid=%d\\n' % os.getpid())\n"
    # Chỉ lượt ĐẦU mới sinh bản chạy lại: bản chạy lại nhận cùng argv, nên phải
    # có mốc trong file để nó không đẻ vô hạn.
    "    if MARK.read_text(encoding='utf-8').count('run pid=') == 1:\n"
    "        ok = _spawn_relauncher(0.2)\n"
    "        with MARK.open('a', encoding='utf-8') as f:\n"
    "            f.write('spawn_ok=%s\\n' % ok)\n"
    "        time.sleep(0.3)\n"
    "        os._exit(0)\n",
    encoding="utf-8")

p = subprocess.run([sys.executable, str(child)], capture_output=True, text=True, timeout=60)
check("B tiến trình cha thoát sạch", p.returncode == 0, f"exit={p.returncode} {(p.stderr or '')[:120]}")

deadline = time.time() + 30
lines = []
while time.time() < deadline:
    if mark.exists():
        lines = [x for x in mark.read_text(encoding="utf-8").split("\n") if x.strip()]
        if sum(1 for x in lines if x.startswith("run pid=")) >= 2:
            break
    time.sleep(0.5)

runs = [x for x in lines if x.startswith("run pid=")]
pids = {x.split("pid=")[1] for x in runs}
check("B sinh được tiến trình rời", any("spawn_ok=True" in x for x in lines), lines[:3])
check("B nó THỰC SỰ chạy lại sau khi cha thoát", len(runs) >= 2 and len(pids) >= 2,
      f"{len(runs)} lượt, {len(pids)} pid")

import shutil  # noqa: E402
shutil.rmtree(work, ignore_errors=True)

print("=" * 70)
if failures:
    print(f"{len(failures)} FAIL / {checks}")
    sys.exit(1)
print(f"{checks}/{checks} PASS")
