"""Trình duyệt KHÔNG khôi phục tab của lần trước (user 30/10/2026: «trình duyệt chạy ngầm nó tới 200… bỏ
--restore-last-session đi»).

Chạy:  python tests/no_session_restore_test.py      (mã thoát 0 = đạt)

Hồ sơ ShardX testphienbansharr149 của agent «chuyên gia it» (lịch 10 lượt/ngày) lưu 202 tab trong phiên; mỗi lần
mở cờ --restore-last-session mở lại cả 202 tab ≈ 200 tiến trình → máy treo. Khoá: không đường mở nào trong extension
browser (và bản vá nóng của cloud nếu có repo cạnh bên) truyền cờ đó.
"""
import io
import os
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent.parent
BR = ROOT / "tubecli" / "extensions" / "browser"
fails = 0
checks = 0
flag = re.compile(r"""['"]--restore-last-session['"]""")
files = [p for p in list(BR.glob("*.js")) + list(BR.glob("*.cjs")) + list(BR.glob("actions/*.js")) + list(BR.glob("*.py"))]
patch = ROOT.parent / "tubecli-cloud" / "public" / "patch" / "browser_manager.js"
if patch.is_file():
    files.append(patch)
for p in files:
    checks += 1
    txt = io.open(p, encoding="utf-8", errors="replace").read()
    if flag.search(txt):
        fails += 1
        print(f"[FAIL] {p} vẫn truyền --restore-last-session")
bm = io.open(BR / "browser_manager.js", encoding="utf-8").read()
checks += 1
if "'--hide-crash-restore-bubble'," not in bm or "'--no-first-run'," not in bm:
    fails += 1
    print("[FAIL] mất cờ khởi động khác khi bỏ --restore-last-session")
print(f"{checks - fails}/{checks} PASS ({len(files)} tệp đã soát)")
sys.exit(1 if fails else 0)
