# -*- coding: utf-8 -*-
"""Dự án CANVAS (bộ cảnh chữ/phấn): bước vẽ ảnh phải đi SAU bước viết cảnh, và chỉ vẽ nhịp cần vẽ.

Vì sao có file này (24/9/2026): task #100 vẽ 595 tấm gpt-image-2 cho một tập mà kho đã có 210 tranh — user:
«chẳng lẽ nó tạo luôn 500 ảnh bằng chatgpt?». Ba lỗi chồng nhau:
  1. bước vẽ chạy trước bước viết cảnh (viết cảnh chỉ chạy lúc dựng) nên vẽ mọi nhịp theo prompt chung;
  2. bước vẽ còn «bịa prompt» cho nhịp chưa có prompt — nhịp câu trơn / hình kho cũng bị vẽ;
  3. storyboard bị ĐÚP sau một lượt Chạy lại (595 nhịp, 289 câu trùng) — vẽ và đọc gấp đôi.

Run: python tests/content_video_canvas_order_test.py   (không gọi mạng)
"""
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


calls = []


def fake_post(path, body, **k):
    calls.append(("POST", path))
    if path.endswith("/scenes/generate"):
        return {"success": True, "shots": 290, "written": 290, "to_draw": 5, "no_draw": 250, "diagrams": 4}
    if path.endswith("/gen-images"):
        return {"success": True, "task_id": "t1", "total": 5, "shots": 290, "with_prompt": 5, "no_prompt": 285}
    return {}


def fake_get_canvas(path, **k):
    calls.append(("GET", path))
    if "/dramas/" in path:
        return {"id": 370, "metadata": '{"scene_kit": "chalk_text", "render_engine": "canvas"}'}
    return {}


def fake_get_plain(path, **k):
    calls.append(("GET", path))
    return {"id": 1, "metadata": "{}"} if "/dramas/" in path else {}


said = []
P._poll_studio = lambda *a, **k: {"errors": [], "status": "completed"}
P._images_done = lambda ep: (5, 5)
P._shots_without_media = lambda ep: [7, 8, 9]
filled_calls = []
P._fill_missing_prompts = lambda st: filled_calls.append(1) or 0

print("\nA. dự án canvas: viết cảnh TRƯỚC, không bịa prompt, không cảnh báo oan")
P._post, P._get = fake_post, fake_get_canvas
st = {"episode_id": 535, "drama_id": 370, "_say": lambda step, status, msg="", *a: said.append(msg)}
P._step_images(st, {})
order = [p for m, p in calls if m == "POST"]
ok(order and order[0].endswith("/scenes/generate") and order[1].endswith("/gen-images"),
   "scenes/generate được gọi TRƯỚC gen-images", order)
ok(not filled_calls, "KHÔNG bịa prompt cho nhịp trống — nhịp trống là câu trơn / hình kho, cố ý")
ok(st.get("scenes_report", {}).get("to_draw") == 5 and any("5 to draw" in m for m in said),
   "báo cáo nói rõ bao nhiêu nhịp phải vẽ / bao nhiêu lấy kho", said)
ok(not st.get("warnings"), "không cảnh báo «shot sẽ thiếu» cho nhịp câu trơn của dự án canvas", st.get("warnings"))

print("\nB. dự án thường: y như cũ")
calls.clear(); said.clear(); filled_calls.clear()
P._post, P._get = fake_post, fake_get_plain
st = {"episode_id": 1, "drama_id": 1, "_say": lambda step, status, msg="", *a: said.append(msg)}
P._step_images(st, {})
order = [p for m, p in calls if m == "POST"]
ok(not any(p.endswith("/scenes/generate") for p in order), "không gọi viết cảnh cho dự án không phải canvas", order)
ok(filled_calls, "vẫn bịa prompt cho shot trống như trước (tập 302)")
ok(st.get("warnings"), "vẫn cảnh báo shot thiếu ảnh như trước (tập 454)")

print("\nC. canvas mà KHÔNG có gì để vẽ (cả tập lấy từ kho) là kết quả tốt, không phải lỗi")


def fake_post_zero(path, body, **k):
    if path.endswith("/scenes/generate"):
        return {"success": True, "shots": 40, "written": 40, "to_draw": 0, "no_draw": 40}
    if path.endswith("/gen-images"):
        return {"success": True, "task_id": "t2", "total": 0, "shots": 40, "with_prompt": 0, "no_prompt": 40}
    return {}


P._post, P._get = fake_post_zero, fake_get_canvas
st = {"episode_id": 9, "drama_id": 370, "_say": lambda step, status, msg="", *a: said.append(msg)}
try:
    P._step_images(st, {})
    ok(True, "total=0 với dự án canvas ⇒ đi tiếp, không ném «nothing to draw»")
except RuntimeError as e:
    ok(False, "total=0 với dự án canvas ⇒ đi tiếp, không ném «nothing to draw»", e)

print("\nD. storyboard đúp sau Chạy lại")
dup = [{"id": i, "narration_text": "câu %d" % (i % 10)} for i in range(20)]     # mỗi câu 2 lần
ok(P._duplicate_ratio(dup) >= 0.5 and P._duplicate_ratio(dup[:10]) == 0.0,
   "đo được tỉ lệ câu trùng: 20 nhịp/10 câu ⇒ 0,5; 10 câu khác nhau ⇒ 0", (P._duplicate_ratio(dup), P._duplicate_ratio(dup[:10])))
src = (ROOT / "tubecli" / "extensions" / "content_video" / "pipeline.py").read_text(encoding="utf-8")
ok("if shots and _duplicate_ratio(shots) >= 0.3:" in src and '_delete(f"/api/v1/studio/episodes/{ep_id}/storyboards")' in src,
   "bước storyboard: đúp ≥ 30% ⇒ xoá sạch rồi cắt lại, không giữ một nửa")

print(f"\n{PASS}/{PASS + FAIL} PASS" if not FAIL else f"\n{PASS}/{PASS + FAIL} PASS — {FAIL} HỎNG")
sys.exit(1 if FAIL else 0)
