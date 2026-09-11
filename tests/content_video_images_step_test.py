# -*- coding: utf-8 -*-
"""Bước ảnh của dây chuyền video.

Cam kết:
  1. Shot chỉ có LỜI THOẠI (không trường hình nào) được dựng prompt từ phong cách
     của mẫu + chữ của chính nó — không thì bộ dựng bỏ hẳn shot, kéo theo lời thoại
     (tập 302, 11/9/2026: mất câu mở màn).
  2. Chỉ chặn cả lượt khi KHÔNG shot nào vẽ được (tập 298: 0/14). Có shot vẽ được
     thì đi tiếp, và nói ra shot nào sẽ vắng.
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
        print("  FAIL", label, "—", detail)


STYLE = "Visual Style: Simple 2D stick figure animation, doodle style, thick black lines"
SHOTS = [
    {"id": 1, "narration_text": "Aprender un nuevo idioma solía ser una tarea interminable."},   # chỉ lời thoại
    {"id": 2, "image_prompt": "Simple 2D stick figure… a hand", "composed_image": r"C:\img\2.jpg"},
    {"id": 3, "description": "Un estudiante sonríe frente a su escritorio"},                      # có mô tả
    {"id": 4},                                                                                    # không một chữ
    {"id": 5, "composed_image": r"C:\img\5.jpg"},                                                 # có ảnh, không prompt
]
puts = []
P._storyboards = lambda ep_id: [dict(s) for s in SHOTS]
P._put = lambda path, body, **k: puts.append((path, body)) or {}
P._get = lambda path, **k: {"items": [{"id": 302, "style": STYLE}]}


def state(preset_style=STYLE):
    said = []
    st = {"episode_id": 302, "drama_id": 302, "warnings": [],
          "preset": {"name": "nguoi que", "fields": {"style": preset_style}} if preset_style else None,
          "_say": lambda step, status, msg="", *a: said.append(msg)}
    return st, said


print("── lấp prompt ────────────────────────────────────────────────")
st, said = state()
n = P._fill_missing_prompts(st)
byid = {int(p.rsplit("/", 1)[1]): b["image_prompt"] for p, b in puts}
ok(n == 2 and set(byid) == {1, 3}, "lấp đúng hai shot: chỉ-lời-thoại và có-mô-tả", str(byid))
ok(byid.get(1, "").startswith("Visual Style: Simple 2D stick figure") and "Aprender un nuevo" in byid.get(1, ""),
   "prompt = phong cách của MẪU + lời thoại của chính shot", byid.get(1, "")[:90])
ok("Un estudiante" in byid.get(3, "") and "Aprender" not in byid.get(3, ""),
   "có mô tả thì dùng mô tả, không lấy lời thoại", byid.get(3, "")[:90])
ok(2 not in byid and 5 not in byid, "shot đã có prompt hoặc đã có ảnh thì không đụng")
ok(4 not in byid, "shot không một chữ nào thì không bịa prompt")

puts.clear()
st, _ = state(preset_style="")
P._fill_missing_prompts(st)
byid = {int(p.rsplit("/", 1)[1]): b["image_prompt"] for p, b in puts}
ok(byid.get(1, "").startswith(STYLE), "mẫu không mang style → lấy style của drama", byid.get(1, "")[:70])

print("── chỉ chặn khi không shot nào vẽ được ──────────────────────")
P._fill_missing_prompts = lambda st: 0


def run_images(res):
    P._post = lambda path, body, **k: res
    P._poll_studio = lambda *a, **k: {"errors": []}
    st, said = state()
    err = ""
    try:
        P._step_images(st, {})
    except RuntimeError as e:
        err = str(e)
    return st, said, err


st, said, err = run_images({"task_id": "t", "total": 0, "shots": 14, "with_prompt": 0, "no_prompt": 14})
ok("14/14 shots have no image prompt" in err, "0/14 có prompt (tập 298) → vẫn chặn, nói đúng chỗ", err[:80])

st, said, err = run_images({"task_id": "t", "total": 0, "shots": 10, "with_prompt": 9, "no_prompt": 1})
ok(not err, "9/10 đã có ảnh, 1 shot thiếu (tập 302) → ĐI TIẾP", err[:80])
ok(any("missing from the video" in w for w in st["warnings"]), "…và NÓI RA shot nào sẽ vắng", str(st["warnings"]))

st, said, err = run_images({"task_id": "t", "total": 3, "shots": 10, "with_prompt": 9, "no_prompt": 1})
ok(not err and any("missing from the video" in w for w in st["warnings"]),
   "còn shot để vẽ + 1 shot thiếu → vẽ, và vẫn cảnh báo", str(st["warnings"]))

st, said, err = run_images({"task_id": "t", "total": 0})
ok(not err and not st["warnings"], "Content Studio cũ (không có with_prompt/no_prompt) → hành vi cũ, không chặn")

print()
print("=" * 62)
print(f"{PASS}/{PASS + FAIL} PASS" if not FAIL else f"{PASS}/{PASS + FAIL} PASS — {FAIL} HỎNG")
sys.exit(1 if FAIL else 0)
