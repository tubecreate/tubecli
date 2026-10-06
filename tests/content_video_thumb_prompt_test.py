# -*- coding: utf-8 -*-
"""Prompt ảnh đại diện + ảnh vẽ bằng model (6/10/2026).

User: «thêm logic tạo prompt để tạo ảnh thumbnail phù hợp với nội dung, có button copy prompt thumbnail trên task,
thêm prompt vào sheet và cấu hình tự tạo ảnh thumbnail gửi lên drive qua model tạo ảnh» + «mỗi prompt có thể mang
style riêng… prompt nhấn mạnh phần nội dung còn chừa style người dùng tự tuỳ biến» + «tạo tự động dựa vào vibe của
video» + «dùng ảnh hook để làm tham chiếu khi tạo tự động». Kiểm (model, Studio, model ảnh đều GIẢ — không HTTP):
  1. cấu hình: form > mẫu (wizThumb*); mẫu bật wizThumbAuto ⇒ vẽ bằng model ảnh
  2. prompt = SUBJECT + HEADLINE + dòng STYLE riêng; style tự theo vibe (style mẫu + ảnh mở đầu đi vào lời nhờ);
     style người dùng thay NGUYÊN dòng; model trả rác ⇒ RuntimeError
  3. bước thumbnail mặc định: viết prompt, ghi checkpoint + meta, KHÔNG vẽ; viết hỏng ⇒ không gắn ⚠️
  4. bật vẽ bằng model ảnh: ảnh hook làm tham chiếu, ảnh vào checkpoint (bước Drive tải lên)
  5. draw_thumbnail: có ảnh hook ⇒ Muse trước + ảnh tham chiếu; nhà không nhận ảnh thì không gửi; không lùi FLUX;
     JPEG ⇒ đuôi .jpg
  6. ảnh hook: nhịp đầu CÓ ảnh trong DATA_DIR
  7. task cũ: trả prompt đã có; force / style mới thì viết lại; chưa có kịch bản ⇒ ValueError
  8. kế hoạch + bộ chạy: bước thumbnail luôn chạy, không cần Thumbnail Studio khi chỉ viết prompt
  9. Sheet: dòng «Thumbnail prompt» ở Overview

Run:  python tests/content_video_thumb_prompt_test.py
"""
import asyncio
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import tubecli.extensions.content_video.pipeline as P      # noqa: E402

PASS = FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", label)
    else:
        FAIL += 1
        print("  FAIL", label, "—", str(detail)[:400])


# Không HTTP nào ra ngoài: mọi lối gọi Studio/model đều giả.
def _no_http(*a, **k):
    raise AssertionError(f"unexpected HTTP: {a[:1]}")


P._post = _no_http
P._put = _no_http
PRESETS = {}
SHOTS = []
P._get = lambda path, timeout=60: {"presets": PRESETS} if path.endswith("/studio/presets") else _no_http(path)
P._storyboards = lambda ep: list(SHOTS)
META = []
P._task_meta = lambda task_id, **patch: META.append((task_id, patch))
ASKS = []
REPLY = {"text": ""}


def fake_ask(agent, system, user, budget):
    ASKS.append({"system": system, "user": user})
    return REPLY["text"]


P._ask_model = fake_ask
PLAN = {"subject": "A giant cross-section of the Sun on the left, a light ray leaving the core and reaching Earth "
                   "after 170,000 years, the number 170,000 large in the free right half",
        "headline": [{"text": "170.000 JAHRE", "color": "yellow"}, {"text": "ALTES LICHT?", "color": "white"}],
        "style": "Colored chalk on a dark green blackboard, warm orange and cool blue, hand-drawn, mysterious mood"}
REPLY["text"] = "```json\n" + json.dumps(PLAN) + "\n```"


class Agent:
    id, name, model = "a1", "Writer", "m"


TMP = tempfile.mkdtemp(prefix="cv_thumb_prompt_")
HOOK = os.path.join(TMP, "hook.jpg")
open(HOOK, "wb").write(b"\xff\xd8\xff\xe0" + b"\x00" * 64)

print("── 1. cấu hình ────────────────────────────────────────────────")
PRESETS.update({"Chalk": {"wizStyle": "Chalkboard Lecture", "wizAspectRatio": "16:9"},
                "Auto": {"wizThumbAuto": True, "wizThumbStyle": "Bold comic", "wizThumbModel": "muse|muse-image"}})
c = P.thumb_config("Chalk", {})
ok(c["image"] is False and c["style"] == "" and c["aspect"] == "16:9", "mặc định: chỉ prompt, style tự theo video", c)
c = P.thumb_config("Auto", {})
ok(c["image"] and c["engine"] == "image" and c["style"] == "Bold comic" and c["model"] == "muse|muse-image",
   "mẫu bật wizThumbAuto ⇒ vẽ bằng model ảnh, style + model của mẫu", c)
c = P.thumb_config("Auto", {"thumbnail_style": "Neon poster", "thumbnail_engine": "studio"})
ok(c["style"] == "Neon poster" and c["engine"] == "studio", "form thắng mẫu", c)
ok(P.thumb_config("", {"thumbnail": True})["image"], "form bật ảnh khi mẫu không khai")

print("── 2. prompt: nội dung + dòng STYLE riêng ─────────────────────")
ASKS.clear()
prompt, parts = P.write_thumbnail_prompt(Agent(), "Wie alt ist das Sonnenlicht?", "[SHOW: sun]\nDas Licht ist alt.",
                                         "de", "16:9", "Colored Chalk Cosmos: hand-drawn colored chalk",
                                         {"prompt": "cross-section of the Sun drawn in chalk"})
lines = prompt.splitlines()
ok(lines[0] == "YouTube thumbnail, 16:9." and lines[1].startswith("SUBJECT: A giant cross-section"),
   "mở bằng khổ ảnh rồi tới NỘI DUNG", lines[:2])
ok(any(ln.startswith("HEADLINE in German") and '"170.000 JAHRE" (yellow)' in ln for ln in lines),
   "tiêu đề đúng ngôn ngữ video, giữ nguyên chữ + màu", prompt)
ok(any(ln == "STYLE: " + PLAN["style"] for ln in lines) and parts["style_source"] == "auto",
   "STYLE đứng riêng một dòng, tự theo vibe", prompt)
u = ASKS[-1]["user"]
ok("VISUAL STYLE OF THE VIDEO: Colored Chalk Cosmos" in u and "OPENING PICTURE OF THE VIDEO: cross-section" in u,
   "vibe = style của mẫu + ảnh mở đầu đi vào lời nhờ", u[:300])
ok("The user fixed the style" not in ASKS[-1]["system"], "không có style người dùng thì model tự đặt")
prompt2, parts2 = P.write_thumbnail_prompt(Agent(), "T", "x y z", "en", "16:9", "", {}, "Retro 80s VHS poster")
ok("STYLE: Retro 80s VHS poster" in prompt2 and PLAN["style"] not in prompt2 and parts2["style_source"] == "user",
   "style người dùng thay NGUYÊN dòng STYLE", prompt2)
ok("Retro 80s VHS poster" in ASKS[-1]["system"], "model biết style người dùng để dựng bố cục hợp")
REPLY["text"] = "Sorry, I cannot help."
try:
    P.write_thumbnail_prompt(Agent(), "T", "x", "en", "16:9")
    ok(False, "model trả rác ⇒ lỗi")
except RuntimeError:
    ok(True, "model trả rác ⇒ RuntimeError")
REPLY["text"] = json.dumps(PLAN)

print("── 3. bước thumbnail mặc định ─────────────────────────────────")
CK = {}
P._checkpoint_merge = lambda state, extra: (CK.update(extra), state.__setitem__("checkpoint", dict(CK)))
DRAWS = []
_draw = P.draw_thumbnail
P.draw_thumbnail = lambda prompt, out, aspect, model="", reference="": DRAWS.append((prompt, out, aspect, model,
                                                                                    reference)) or (out, "fake/m")
SHOTS[:] = [{"storyboard_number": 1, "composed_image": HOOK, "image_prompt": "the Sun in chalk",
             "narration_text": "Light is old."}]
P._data_file = lambda v: str(v) if v and os.path.isfile(str(v)) else ""
said = []


def st_new(**kw):
    s = {"agent": Agent(), "task_id": "t1", "title": "Sunlight", "script": "[SHOW: a]\nLight is old.",
         "language": "en", "episode_id": 9, "aspect_ratio": "16:9", "preset_name": "Chalk",
         "_say": lambda *a: said.append(a), "_cancelled": lambda: False, "checkpoint": {}}
    s.update(kw)
    return s


st = st_new()
P._step_thumbnail(st, {})
ok(st.get("thumbnail_prompt", "").startswith("YouTube thumbnail") and CK.get("thumbnail_prompt") == st["thumbnail_prompt"]
   and CK.get("thumbnail_parts", {}).get("style"), "viết prompt + ghi checkpoint (cả các phần)", CK)
ok(("t1", {"thumb_prompt": 1}) in META, "meta chỉ gắn cờ nhỏ (danh sách gọn không chở cả prompt)", META)
ok(not DRAWS and not st.get("thumbnail_path") and "image off" in said[-1][2], "ảnh mặc định tắt ⇒ không vẽ", said[-1])
REPLY["text"] = "nope"
CK.clear()
st = st_new()
P._step_thumbnail(st, {})
ok(not st.get("warnings") and not st.get("thumbnail_prompt") and any("not written" in str(a[2]) for a in said),
   "viết hỏng ⇒ chỉ ghi lên dòng bước, KHÔNG gắn ⚠️ cho video", st.get("warnings"))
REPLY["text"] = json.dumps(PLAN)
said.clear()
P._step_thumbnail(st_new(), {"thumbnail_prompt": False})
ok(said and said[-1][1] == "skipped", "tắt prompt + tắt ảnh ⇒ bỏ bước", said)

print("── 4. vẽ bằng model ảnh ───────────────────────────────────────")
CK.clear()
st = st_new()
P._step_thumbnail(st, {"thumbnail": True, "thumbnail_engine": "image"})
ok(DRAWS and DRAWS[-1][4] == HOOK and DRAWS[-1][0] == st["thumbnail_prompt"],
   "vẽ từ chính prompt đó, ảnh hook làm tham chiếu", DRAWS[-1:] and DRAWS[-1][3:])
ok(st.get("thumbnail_path") == DRAWS[-1][1] and CK.get("thumbnail_path") == DRAWS[-1][1]
   and os.sep + "thumbs" + os.sep + "ep9" in DRAWS[-1][1], "ảnh vào checkpoint (bước Drive tải lên)", st.get("thumbnail_path"))
ok(st.get("thumbnail_template_used") == "fake/m", "ghi model đã vẽ")
DRAWS.clear()
st = st_new(checkpoint={"thumbnail_prompt": "YouTube thumbnail, 16:9.\nSUBJECT: old", "thumbnail_path": HOOK})
P._step_thumbnail(st, {"thumbnail": True, "thumbnail_engine": "image"})
ok(not DRAWS and st["thumbnail_path"] == HOOK and st["thumbnail_prompt"].endswith("old"),
   "chạy tiếp từ checkpoint: không viết lại, không vẽ lại")
P.draw_thumbnail = _draw

print("── 5. draw_thumbnail ──────────────────────────────────────────")
import tubecli.core.image_gen as IG      # noqa: E402

calls = []
fail = {"muse"}


def fake_resolve(provider=None, model=None):
    return {"ok": True, "provider": provider, "model": model, "fallback": {"provider": "cloudflare"}}


async def fake_gen(prompt, out_path, provider=None, model=None, aspect_ratio="16:9", reference_images=None,
                   timeout=180, resolved=None):
    calls.append({"prov": resolved["provider"], "refs": reference_images, "prompt": prompt,
                  "fallback": "fallback" in resolved, "ratio": aspect_ratio})
    if resolved["provider"] in fail:
        return {"status": "error", "message": "busy"}
    open(out_path, "wb").write(b"\xff\xd8\xff\xe0" + b"\x00" * 32)
    return {"status": "success", "path": out_path, "provider": resolved["provider"], "model": resolved["model"]}


IG.resolve_provider, IG.generate_image = fake_resolve, fake_gen
out = os.path.join(TMP, "thumbnail.png")
path, drew = P.draw_thumbnail("YouTube thumbnail, 16:9.\nSUBJECT: x", out, "16:9", "", HOOK)
ok([c["prov"] for c in calls] == ["muse", "9router"], "có ảnh hook ⇒ Muse trước, hỏng thì gpt-image-2", calls)
ok(calls[0]["refs"] == [HOOK] and P.THUMB_REF_NOTE.strip() in calls[0]["prompt"],
   "Muse nhận ảnh hook + câu dặn giữ look", calls[0])
ok(calls[1]["refs"] is None and P.THUMB_REF_NOTE.strip() not in calls[1]["prompt"],
   "nhà không nhận ảnh ⇒ không gửi ảnh, không nhắc ảnh", calls[1])
ok(not any(c["fallback"] for c in calls), "bỏ đường lùi FLUX (schnell không viết nổi tiêu đề)")
ok(path.endswith("thumbnail.jpg") and os.path.isfile(path) and not os.path.exists(out) and drew == "9router/cx/gpt-image-2",
   "JPEG ⇒ đuôi .jpg, báo đúng nhà đã vẽ", (path, drew))
calls.clear()
fail.clear()
P.draw_thumbnail("p", out, "16:9", "", "")
ok([c["prov"] for c in calls] == ["9router"], "không ảnh hook ⇒ gpt-image-2 trước", calls)
calls.clear()
P.draw_thumbnail("p", out, "9:16", "muse|muse-image", HOOK)
ok([c["prov"] for c in calls] == ["muse"] and calls[0]["ratio"] == "9:16", "chỉ định «nhà|model» ⇒ chỉ nhà đó", calls)
fail.update({"muse", "9router"})
try:
    P.draw_thumbnail("p", out, "16:9", "", HOOK)
    ok(False, "hỏng hết ⇒ lỗi")
except RuntimeError as e:
    ok("muse" in str(e) and "9router" in str(e), "hỏng hết ⇒ RuntimeError kể từng nhà", e)

print("── 6. ảnh hook ────────────────────────────────────────────────")
SHOTS[:] = [{"storyboard_number": 2, "composed_image": HOOK, "image_prompt": "second"},
            {"storyboard_number": 1, "composed_image": os.path.join(TMP, "missing.jpg"), "image_prompt": "first"}]
h = P._hook_shot(9)
ok(h["image"] == HOOK and h["prompt"] == "second", "nhịp đầu chưa có ảnh ⇒ lấy nhịp kế có ảnh", h)
ok(P._hook_shot(None) == {} and P._hook_shot("x") == {}, "không có tập ⇒ {}")

print("── 7. task cũ (nút trên thẻ) ──────────────────────────────────")
from tubecli.core import agent as AG                       # noqa: E402
from tubecli.extensions.codex import manager as CM         # noqa: E402

STORE = {"t9": {"script": "[SHOW: a]\nOld light.", "title": "Old", "language": "de", "episode_id": 9,
                "preset": "Chalk", "drama_id": 3}}
P._read_checkpoint = lambda tid: dict(STORE.get(tid) or {})
P._write_checkpoint = lambda tid, d: STORE.__setitem__(tid, dict(d))
CM.codex_manager.get_task = lambda tid: {"id": tid, "assignee_id": "a1", "title": "Old"}
AG.agent_manager.get = lambda aid: Agent() if aid == "a1" else None
P._template_style = lambda state: "Chalkboard Lecture" if state.get("drama_id") == 3 else ""
ASKS.clear()
got = P.thumbnail_prompt_for_task("t9")
ok(got["prompt"].startswith("YouTube thumbnail") and STORE["t9"]["thumbnail_prompt"] == got["prompt"]
   and "VISUAL STYLE OF THE VIDEO: Chalkboard Lecture" in ASKS[-1]["user"], "viết từ checkpoint + style của tập", got)
n = len(ASKS)
ok(P.thumbnail_prompt_for_task("t9")["prompt"] == got["prompt"] and len(ASKS) == n, "đã có ⇒ trả lại, không gọi model")
again = P.thumbnail_prompt_for_task("t9", style="Watercolor Edo print")
ok("STYLE: Watercolor Edo print" in again["prompt"] and len(ASKS) == n + 1, "style mới ⇒ viết lại", again["prompt"])
info = P.thumbnail_prompt_info("t9")
ok(info["prompt"] == again["prompt"] and info["can_write"], "GET trả prompt đã lưu")
STORE["t0"] = {"title": "no script"}
try:
    P.thumbnail_prompt_for_task("t0")
    ok(False, "chưa có kịch bản ⇒ lỗi")
except ValueError:
    ok(not P.thumbnail_prompt_info("t0")["can_write"], "chưa có kịch bản ⇒ ValueError, GET báo can_write false")

print("── 8. kế hoạch + bộ chạy ──────────────────────────────────────")
P.check_job = lambda job: {"ready": job != "thumbnail", "missing": ["thumbnail_studio"] if job == "thumbnail" else [],
                           "disabled": []}
row = next(r for r in P.plan({}) if r["step"] == "thumbnail")
ok(row["will_run"], "mặc định: bước thumbnail chạy (viết prompt), không cần Thumbnail Studio", row)
row = next(r for r in P.plan({"thumbnail": True}) if r["step"] == "thumbnail")
ok(not row["available"], "vẽ bằng Thumbnail Studio mà thiếu ⇒ báo thiếu", row)
row = next(r for r in P.plan({"thumbnail": True, "thumbnail_engine": "image"}) if r["step"] == "thumbnail")
ok(row["available"], "vẽ bằng model ảnh ⇒ không cần Thumbnail Studio", row)
ran = []
_h = P._HANDLERS["thumbnail"]
P._HANDLERS["thumbnail"] = lambda s, o: ran.append(o)
P._run_steps([("thumbnail", "Design the thumbnail", "thumbnail", True)], {}, {"thumbnail": False},
             lambda *a: None, lambda: False, [], [])
ok(ran, "options.thumbnail = False vẫn chạy bước (để viết prompt)")
P._HANDLERS["thumbnail"] = _h

print("── 9. Sheet ───────────────────────────────────────────────────")
tabs = dict(P._drive_tabs({"title": "T", "thumbnail_prompt": "YouTube thumbnail, 16:9.\nSUBJECT: s"}, [], {}, {}))
rows = {r[0]: r[1] for r in tabs.get("Overview", [])}
ok(rows.get("Thumbnail prompt", "").startswith("YouTube thumbnail"), "Overview có dòng Thumbnail prompt", list(rows))
tabs = dict(P._drive_tabs({"title": "T", "checkpoint": {"thumbnail_prompt": "from checkpoint"}}, [], {}, {}))
ok({r[0]: r[1] for r in tabs.get("Overview", [])}.get("Thumbnail prompt") == "from checkpoint",
   "đồng bộ Drive task cũ: lấy prompt từ checkpoint")

print()
print(f"{PASS}/{PASS + FAIL} PASS" if not FAIL else f"{PASS}/{PASS + FAIL} PASS — {FAIL} HỎNG")
sys.exit(1 if FAIL else 0)
