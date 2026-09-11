# -*- coding: utf-8 -*-
"""Bộ dò ffmpeg của lõi (video_studio.ffmpeg_utils) — hai bệnh gặp trên máy PC của user, 11/9/2026.

  1. Nhớ luôn kết quả "không có ffmpeg": cài xong bấm Retry vẫn báo thiếu, phải
     khởi động lại TubeCLI. Giờ chỉ nhớ khi THẤY.
  2. winget cài ffmpeg vào %LOCALAPPDATA%\\Microsoft\\WinGet\\Packages\\Gyan.FFmpeg_…\\<bản>\\bin
     và chỉ thêm vào PATH người dùng — máy chủ bật từ Connect không thấy. Giờ thư
     mục đó nằm trong danh sách dò.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

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


print("── không nhớ 'không có' ──────────────────────────────────────")
real = FU._which_uncached
calls = []
seq = [None, r"C:\ff\ffmpeg.exe"]
FU._RESOLVED.clear()
FU._which_uncached = lambda name: (calls.append(name), seq.pop(0))[1]
try:
    ok(FU.find_ffmpeg() is None, "lần đầu: máy chưa có ffmpeg")
    ok(FU.find_ffmpeg() == r"C:\ff\ffmpeg.exe", "cài xong: lần gọi sau THẤY NGAY, không cần khởi động lại")
    ok(FU.find_ffmpeg() == r"C:\ff\ffmpeg.exe" and len(calls) == 2, "thấy rồi thì nhớ — không dò lại mỗi lần", calls)
finally:
    FU._which_uncached = real
    FU._RESOLVED.clear()

if os.name == "nt":
    print("── thư mục winget Packages ───────────────────────────────────")
    tmp = tempfile.mkdtemp(prefix="ff_winget_")
    b = os.path.join(tmp, "Microsoft", "WinGet", "Packages",
                     "Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe", "ffmpeg-9.0.1-full_build", "bin")
    os.makedirs(b)
    old = os.environ.get("LOCALAPPDATA")
    os.environ["LOCALAPPDATA"] = tmp
    try:
        ok(b in FU._known_dirs(), "…\\WinGet\\Packages\\Gyan.FFmpeg…\\bin nằm trong danh sách dò", FU._known_dirs()[-3:])
    finally:
        if old is None:
            os.environ.pop("LOCALAPPDATA", None)
        else:
            os.environ["LOCALAPPDATA"] = old

print("── máy thật ──────────────────────────────────────────────────")
ok(bool(FU.find_ffmpeg()), "máy này vẫn tìm thấy ffmpeg như trước", FU.find_ffmpeg())

print()
print("=" * 62)
print(f"{PASS}/{PASS + FAIL} PASS" if not FAIL else f"{PASS}/{PASS + FAIL} PASS — {FAIL} HỎNG")
sys.exit(1 if FAIL else 0)
