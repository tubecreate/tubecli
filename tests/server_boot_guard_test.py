# -*- coding: utf-8 -*-
"""Hai cửa chặn lúc máy chủ khởi động.

1. `tubecli api start` không được bật bản THỨ HAI khi cổng đã có người giữ.
   Đo thật 11/9/2026: 5 bản thứ hai trong 3 phút; mỗi bản nạp toàn bộ extension và
   chạy recover_orphans() trên kho task DÙNG CHUNG trước khi uvicorn kịp báo cổng
   bận — task đang dựng video của máy chủ thật bị đánh dấu "Orphaned".
2. ensure_on_path() phải đưa ffmpeg TỐT lên ĐẦU PATH, không chỉ "có mặt đâu đó".
   Cùng ngày: bản chết của miniconda đứng trước, bản tốt đứng sau; hàm cũ thấy bản
   tốt "đã có" nên thoát, và mọi lời gọi "ffmpeg" trần trúng bản chết.
"""
import os
import shutil
import socket
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

from tubecli.cli.api_cmd import _port_taken  # noqa: E402
from tubecli.extensions.video_studio import ffmpeg_utils as FU  # noqa: E402

PASS = FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", label)
    else:
        FAIL += 1
        print("  FAIL", label, "—", detail)


print("── cổng đã có người giữ ──────────────────────────────────────")
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.bind(("127.0.0.1", 0))
port = s.getsockname()[1]
s.listen(1)
ok(_port_taken("127.0.0.1", port), f"cổng {port} đang có máy nghe → bị giữ")
s.close()
ok(not _port_taken("127.0.0.1", port), f"cổng {port} vừa nhả → trống (không kẹt TIME_WAIT)")
ok(not _port_taken("127.0.0.1", port), "hỏi hai lần không làm cổng 'bị giữ' (phép thử tự nhả)")

print("── ffmpeg tốt phải đứng ĐẦU PATH ─────────────────────────────")
ORIG = os.environ.get("PATH", "")
FU._RESOLVED.clear()
good = FU.find_ffmpeg()
if not good:
    print("SKIP: máy này không có ffmpeg chạy được")
else:
    good_dir = os.path.dirname(good)
    bad_dir = tempfile.mkdtemp(prefix="ff_chet_")
    if os.name == "nt":
        shutil.copy(os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "where.exe"),
                    os.path.join(bad_dir, "ffmpeg.exe"))
    else:
        p = os.path.join(bad_dir, "ffmpeg")
        with open(p, "w") as f:
            f.write("#!/bin/sh\nexit 1\n")
        os.chmod(p, 0o755)
    norm = lambda p: os.path.normcase(os.path.normpath(p))
    try:
        # Đúng hình dạng hôm ấy: bản chết TRƯỚC, bản tốt SAU, cả hai trên PATH.
        os.environ["PATH"] = os.pathsep.join([bad_dir, good_dir, ORIG])
        FU._RESOLVED.clear()
        ok(norm(os.path.dirname(shutil.which("ffmpeg"))) == norm(bad_dir),
           "(tiền đề) tên trần đang trúng bản chết")
        added = FU.ensure_on_path()
        ok(added and norm(added) == norm(good_dir), "ensure_on_path() trả thư mục bản tốt", str(added))
        first = shutil.which("ffmpeg") or ""
        ok(norm(os.path.dirname(first)) == norm(good_dir), "giờ tên trần trúng bản TỐT", first)
        parts = [norm(p) for p in os.environ["PATH"].split(os.pathsep) if p]
        ok(parts.count(norm(good_dir)) == 1, "thư mục bản tốt chỉ còn MỘT lần trên PATH (bỏ chỗ cũ)")
        before = os.environ["PATH"]
        FU.ensure_on_path()
        ok(os.environ["PATH"] == before, "gọi lại lần hai: PATH không đổi (đã đứng đầu thì thôi)")
    finally:
        os.environ["PATH"] = ORIG
        FU._RESOLVED.clear()

print()
print("=" * 62)
print(f"{PASS}/{PASS + FAIL} PASS" if not FAIL else f"{PASS}/{PASS + FAIL} PASS — {FAIL} HỎNG")
sys.exit(1 if FAIL else 0)
