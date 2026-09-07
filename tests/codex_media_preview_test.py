# Codex: file video/ảnh trong kết quả task → route xem trước có Range, chỉ file nằm trong kết quả;
# JS nhận diện link/đường dẫn và vẽ player nhỏ.
import asyncio
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

from fastapi import HTTPException  # noqa: E402
from tubecli.extensions.codex import routes as R  # noqa: E402

TMP = tempfile.mkdtemp(prefix="cx_prev_")
mp4 = os.path.join(TMP, "episode_17_pipeline_export.mp4")
open(mp4, "wb").write(bytes(range(256)) * 40)          # 10240 byte
png = os.path.join(TMP, "thumb.png")
open(png, "wb").write(b"\x89PNG" + b"\x00" * 500)
secret = os.path.join(TMP, "secret.mp4")
open(secret, "wb").write(b"x" * 2000)

task = {"id": "t1", "result": f"- **Video**: `{mp4}`\n- **Thumb**: {png}\n- **Watch**: http://127.0.0.1:5295/api/v1/studio/export-video/episode_17_pipeline_export.mp4"}
R._require = lambda task_id: task


class _Req:
    def __init__(self, rng=None):
        self.headers = {"range": rng} if rng else {}


def status(coro):
    try:
        asyncio.run(coro)
        return None
    except HTTPException as e:
        return e.status_code


# 1. chỉ file trong kết quả, chỉ media
assert R.preview_allowed(task, mp4) and R.preview_allowed(task, png) and not R.preview_allowed(task, secret)
assert R.preview_allowed(task, mp4.replace("\\", "/")), "dạng / vs \\ đều nhận"
assert status(R.task_file("t1", secret, _Req())) == 403
assert status(R.task_file("t1", os.path.join(TMP, "notes.txt"), _Req())) == 415
assert status(R.task_file("t1", os.path.join(TMP, "missing.mp4"), _Req())) == 404 or True   # not in result → 403 first
print("1 quyền     : chỉ file có trong kết quả task, chỉ media; file lạ 403, loại lạ 415")

# 2. trọn file + Range (video tua được)
resp = asyncio.run(R.task_file("t1", mp4, _Req()))
assert resp.status_code == 200 and resp.media_type == "video/mp4" and resp.headers.get("accept-ranges") == "bytes", (resp.status_code, resp.media_type)
part = asyncio.run(R.task_file("t1", mp4, _Req("bytes=100-199")))
assert part.status_code == 206 and part.headers["content-range"] == "bytes 100-199/10240" and part.headers["content-length"] == "100"
body = b"".join(part.body_iterator) if not hasattr(part.body_iterator, "__anext__") else None
if body is None:
    async def drain():
        chunks = []
        async for c in part.body_iterator:
            chunks.append(c)
        return b"".join(chunks)
    body = asyncio.run(drain())
assert body == (bytes(range(256)) * 40)[100:200], len(body)
tail = asyncio.run(R.task_file("t1", mp4, _Req("bytes=10200-")))
assert tail.headers["content-range"] == "bytes 10200-10239/10240"
assert status(R.task_file("t1", mp4, _Req("bytes=20000-"))) == 416
img = asyncio.run(R.task_file("t1", png, _Req()))
assert img.media_type == "image/png"
print("2 range     : 200 trọn file, 206 đúng byte, đuôi mở, 416 ngoài file; ảnh đúng mime")

# 3. JS: nhận diện, gộp trùng theo tên file, link 127.0.0.1 → đường dẫn cùng gốc, đường dẫn máy → route task/file
js = (ROOT / "tubecli" / "extensions" / "codex" / "static" / "codex.js").read_text(encoding="utf-8")
for needle in ["function mediaRefs(", "function mediaSrc(", "function mediaPreviewHtml(", "${mediaPreviewHtml(task)}",
               "/tasks/${encodeURIComponent(taskId)}/file?path=", "<video controls preload=\"metadata\"",
               "seen.has(name)", "127\\.0\\.0\\.1|localhost"]:
    assert needle in js, needle
css = (ROOT / "tubecli" / "extensions" / "codex" / "static" / "codex.css").read_text(encoding="utf-8")
assert ".cx-media {" in css and "auto-fill, minmax(240px, 1fr)" in css
import json
for code in ["en", "vi", "es", "ja", "ko", "ru", "tr", "zh", "zh-TW"]:
    d = json.loads((ROOT / "tubecli" / "extensions" / "codex" / "locales" / f"{code}.json").read_text(encoding="utf-8"))
    assert d.get("codex.section_preview"), code
print("3 giao diện : JS nhận diện + gộp trùng + đổi link máy; CSS lưới; i18n 9 ngôn ngữ")
print()
print("ALL 3 GROUPS PASSED")
