"""POST /api/v1/muse/v1/videos/generations lưu clip thành FILE (output_path) — 4/11/2026.

Chạy:  python tests/muse_video_output_test.py      (mã thoát 0 = đạt)

Bên gọi qua MCP/HTTP không ghi được base64 ra đĩa, còn file tạm bị xoá ngay sau khi trả. output_path = tên file trần →
<DATA_DIR>/videos/muse/<tên>.mp4 (+ ảnh poster), data[0].path trả đường dẫn; b64 chỉ kèm khi include_b64=true. Không
truyền output_path → hành vi cũ (b64). Áp cho cả wait=true lẫn job nền. Muse giả — không mở trình duyệt.
"""
import base64
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import tubecli.config as CFG  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="muse_out_"))
CFG.DATA_DIR = TMP / "data"
from tubecli.api import muse_routes as MR  # noqa: E402

checks = fails = 0


def check(name, ok, detail=""):
    global checks, fails
    checks += 1
    print(("[PASS] " if ok else "[FAIL] ") + name + ("" if ok else f"  {str(detail)[:300]}"))
    if not ok:
        fails += 1


src = TMP / "clip.mp4"
src.write_bytes(b"MP4DATA-1234")
poster = TMP / "clip.jpg"
poster.write_bytes(b"JPEG")
clip = {"path": str(src), "poster": str(poster), "thread_id": "th1", "width": 720, "height": 1280, "duration": 6}
base = CFG.DATA_DIR / "videos" / "muse"

old = MR._clip_payload(clip)
check("A1 không output_path → giữ hành vi cũ (b64, không có path)", "b64_json" in old["data"][0] and "path" not in old["data"][0]
      and base64.b64decode(old["data"][0]["b64_json"]) == b"MP4DATA-1234")
out = MR._clip_payload(clip, "b10_bong.mp4")
item = out["data"][0]
check("A2 output_path → file nằm ở <DATA_DIR>/videos/muse/b10_bong.mp4", item.get("path") == str(base / "b10_bong.mp4")
      and (base / "b10_bong.mp4").read_bytes() == b"MP4DATA-1234", item)
check("A3 kèm ảnh poster cùng tên", item.get("poster") == str(base / "b10_bong.jpg") and (base / "b10_bong.jpg").is_file(), item)
check("A4 có file thì KHÔNG kèm b64 (mặc định)", "b64_json" not in item)
item = MR._clip_payload(clip, "x.mp4", include_b64=True)["data"][0]
check("A5 include_b64=true → kèm cả b64", "b64_json" in item and item.get("path"))
check("A6 tên thiếu đuôi → thêm .mp4", MR._save_target("noi_dung") == str(base / "noi_dung.mp4"))
check("A7 ../ không thoát khỏi thư mục muse", os.path.dirname(MR._save_target("../../etc/passwd")) == str(base)
      and os.path.dirname(MR._save_target("/tmp/evil.mp4")) == str(base))
check("A8 tên rỗng → không lưu", MR._save_target("") == "" and MR._save_target("   ") == "")

# ── job nền (wait=false) ─────────────────────────────────────────────────────
MR.muse.generate_video_clip = lambda *a, **k: dict(clip)
MR._VIDEO_JOBS["j1"] = {"status": "running", "created": time.time()}
MR._job_run("j1", "a red balloon floating", str(TMP / "t"), [], "9:16", False, "", 60, "test_muse.mp4", None)
job = MR._VIDEO_JOBS["j1"]
check("B1 job nền xong: file test_muse.mp4 đã có + path trong kết quả", job.get("status") == "done"
      and job["result"]["data"][0].get("path") == str(base / "test_muse.mp4") and (base / "test_muse.mp4").is_file(), job)
check("B2 model nhận output_path + include_b64", "output_path" in MR.VideosRequest.model_fields
      and "include_b64" in MR.VideosRequest.model_fields)

shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{checks - fails}/{checks} PASS")
sys.exit(1 if fails else 0)
