# -*- coding: utf-8 -*-
"""Tự tải ffmpeg + ffprobe khi máy Windows thiếu (19/11/2026, VPS mới: «[WinError 2]»).

Kiểm (KHÔNG mạng — «tải» một zip dựng tại chỗ qua file://, LOCALAPPDATA trỏ thư mục tạm):
  1. thư mục tự quản nằm trong danh sách dò (_known_dirs)
  2. đủ ffmpeg + ffprobe ⇒ không tải gì
  3. thiếu ⇒ giải nén đúng bin/ffmpeg.exe + bin/ffprobe.exe, chạy được, ghi dấu ok, xoá cache dò
  4. zip hỏng (thiếu ffprobe) ⇒ thử nguồn sau; mọi nguồn hỏng ⇒ failed + 6 giờ sau mới thử lại (trừ force)

Run:  python tests/ffmpeg_selfheal_test.py   (Windows; cần một ffmpeg + ffprobe chạy được để làm «hàng mẫu»)
"""
import json
import os
import shutil
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")

from tubecli.extensions.video_studio import ffmpeg_utils as FU  # noqa: E402

PASS = FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", label)
    else:
        FAIL += 1
        print("  FAIL", label, "—", str(detail)[:300])


if os.name != "nt":
    print("Windows only — skipped")
    sys.exit(0)

real_ffmpeg, real_ffprobe = FU.find_ffmpeg(), FU.find_ffprobe()
if not (real_ffmpeg and real_ffprobe and real_ffmpeg.lower().endswith("ffmpeg.exe")):
    print("needs a working ffmpeg.exe + ffprobe.exe on this machine to build the sample zip — skipped")
    sys.exit(0)

work = tempfile.mkdtemp(prefix="ffheal-")
os.environ["LOCALAPPDATA"] = os.path.join(work, "local")
good_zip = os.path.join(work, "good.zip")
with zipfile.ZipFile(good_zip, "w", zipfile.ZIP_STORED) as z:
    z.write(real_ffmpeg, "ffmpeg-7.1-essentials_build/bin/ffmpeg.exe")
    z.write(real_ffprobe, "ffmpeg-7.1-essentials_build/bin/ffprobe.exe")
    z.writestr("ffmpeg-7.1-essentials_build/README.txt", "sample")
bad_zip = os.path.join(work, "bad.zip")
with zipfile.ZipFile(bad_zip, "w") as z:
    z.write(real_ffmpeg, "x/bin/ffmpeg.exe")          # thiếu ffprobe
url = lambda p: "file:///" + p.replace("\\", "/")  # noqa: E731

print("── 1. thư mục tự quản ───────────────────────────────────────────")
md = FU.managed_dir()
ok(md == os.path.join(work, "local", "Programs", "ffmpeg", "bin"), "managed_dir theo LOCALAPPDATA", md)
ok(md in FU._known_dirs(), "nằm trong danh sách dò")

print("── 2. đủ rồi thì không tải ──────────────────────────────────────")
calls = []
orig_download = FU._download
FU._download = lambda u, d, timeout=60: (calls.append(u), orig_download(u, d, timeout))[1]
FU.needs_install = lambda: False
st = FU.install_ffmpeg(urls=[url(good_zip)])
ok(st["status"] == "ok" and not calls, "needs_install False ⇒ không tải", (st, calls))

print("── 3. thiếu ⇒ cài ───────────────────────────────────────────────")
state = {"missing": True}
FU.needs_install = lambda: state["missing"]
FU._RESOLVED["ffmpeg"] = "C:/stale/ffmpeg.exe"
st = FU.install_ffmpeg(urls=[url(bad_zip), url(good_zip)])
ok(st["status"] == "ok", "cài xong", st)
ok(len(calls) == 2, "zip hỏng ⇒ thử nguồn kế tiếp", calls)
ok(os.path.isfile(os.path.join(md, "ffmpeg.exe")) and os.path.isfile(os.path.join(md, "ffprobe.exe")),
   "có bin/ffmpeg.exe + bin/ffprobe.exe")
ok(not os.path.exists(os.path.join(md, "README.txt")), "chỉ giữ hai file exe")
ok(FU._runs(os.path.join(md, "ffprobe.exe")), "ffprobe vừa cài chạy được")
ok(FU._RESOLVED.get("ffmpeg") != "C:/stale/ffmpeg.exe", "xoá cache dò cũ")
marker = json.load(open(FU._marker_file(), encoding="utf-8"))
ok(marker.get("ok") is True, "ghi dấu ok", marker)

print("── 4. mọi nguồn hỏng ⇒ failed, nghỉ 6 giờ ───────────────────────")
shutil.rmtree(os.path.dirname(md), ignore_errors=True)
calls.clear()
st = FU.install_ffmpeg(urls=[url(bad_zip), url(os.path.join(work, "khong-co.zip"))])
ok(st["status"] == "failed" and len(calls) == 2, "failed sau 2 nguồn", (st, calls))
ok("ffprobe" in st["error"], "lỗi nói rõ thiếu gì", st["error"])
calls.clear()
st = FU.install_ffmpeg(urls=[url(good_zip)])
ok(st["status"] == "failed" and not calls, "trong 6 giờ không thử lại", (st, calls))
st = FU.install_ffmpeg(urls=[url(good_zip)], force=True)
ok(st["status"] == "ok" and len(calls) == 1, "force ⇒ thử ngay", (st, calls))

shutil.rmtree(work, ignore_errors=True)
print(f"\n{PASS}/{PASS + FAIL} PASS")
sys.exit(1 if FAIL else 0)
