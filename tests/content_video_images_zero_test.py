# -*- coding: utf-8 -*-
"""Bước vẽ ảnh của pipeline không báo XONG khi 0 ảnh (15/9/2026).

User: Codex "Generate shot images XONG · 10 shot(s) without image" rồi "Assemble the video LỖI
None of the shots have valid videos or images generated yet".

Kiểm (_step_images với Studio giả):
  A. Studio trả completed nhưng 0 ảnh (kể cả Studio cũ không có ok/last_error) → RuntimeError kể số
     shot hỏng + lý do (last_error nếu có)
  B. Studio đánh "error: stopped after the first shot failed: …" → _poll_studio ném → bước lỗi kèm lý do
  C. thiếu vài tấm → không lỗi, có cảnh báo và câu trạng thái kèm lý do
  D. đủ ảnh → im lặng

Run:  python tests/content_video_images_zero_test.py
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

from tubecli.extensions.content_video import pipeline as P  # noqa: E402

PASS = FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", label)
    else:
        FAIL += 1
        print("  FAIL", label, "—", str(detail)[:300])


P._fill_missing_prompts = lambda state: 0
P._post = lambda path, payload, timeout=300: {"task_id": "job1", "total": 10, "shots": 10, "with_prompt": 10, "no_prompt": 0}


def state():
    said = []
    return {"episode_id": 5, "aspect_ratio": "16:9", "warnings": [],
            "_say": lambda step, st, msg, pct=None: said.append((step, st, msg))}, said


def with_poll(result):
    P._poll_studio = lambda *a, **k: result


print("── A. completed nhưng 0 ảnh ────────────────────────────────")
with_poll({"status": "completed", "done": 10, "total": 10, "errors": list(range(1, 11)), "ok": 0,
           "last_error": "HTTP 401: Unauthorized"})
st, said = state()
try:
    P._step_images(st, {}); ok(False, "phải ném RuntimeError")
except RuntimeError as e:
    ok("no image was generated (10/10 shots failed)" in str(e) and "HTTP 401" in str(e), "0 ảnh → lỗi kể số shot + lý do", e)
with_poll({"status": "completed", "done": 10, "total": 10, "errors": list(range(1, 11))})
st, said = state()
try:
    P._step_images(st, {}); ok(False, "phải ném RuntimeError (Studio cũ)")
except RuntimeError as e:
    ok("no image was generated (10/10" in str(e) and "check the image provider" in str(e), "Studio cũ (không có ok/last_error) → vẫn chặn, chỉ đường", e)

print("── B. Studio dừng sớm ──────────────────────────────────────")


def poll_err(*a, **k):
    raise RuntimeError("stopped after the first shot failed: HTTP 403: model not available")


P._poll_studio = poll_err
st, said = state()
try:
    P._step_images(st, {}); ok(False, "phải ném")
except RuntimeError as e:
    ok("stopped after the first shot failed" in str(e) and "403" in str(e), "lỗi dừng sớm đi thẳng lên thẻ bước", e)

print("── C. thiếu vài tấm ────────────────────────────────────────")
with_poll({"status": "completed", "done": 10, "total": 10, "errors": [3, 7], "ok": 8, "last_error": "content policy"})
st, said = state()
P._step_images(st, {})
ok(any("2 shot(s) without image — content policy" in m for _, _, m in said), "câu trạng thái kèm lý do", said)
ok(st["warnings"] and "2/10 shot(s) could not be drawn: content policy" in st["warnings"][0], "cảnh báo ghi vào lượt", st["warnings"])
ok(st["image_errors"] == 2, "image_errors = 2")

print("── D. đủ ảnh ───────────────────────────────────────────────")
with_poll({"status": "completed", "done": 10, "total": 10, "errors": [], "ok": 10})
st, said = state()
P._step_images(st, {})
ok(not st["warnings"] and not any("without image" in m for _, _, m in said), "đủ ảnh → không cảnh báo")

print()
print(f"{PASS}/{PASS + FAIL} PASS" if not FAIL else f"{PASS}/{PASS + FAIL} PASS — {FAIL} HỎNG")
sys.exit(1 if FAIL else 0)
