# -*- coding: utf-8 -*-
"""Retry sau khi DỰNG lỗi phải chạy tiếp — không viết lại kịch bản, storyboard, ảnh, giọng.

Bệnh (máy PC của user, 11/9/2026): task auto 102 shot hỏng ở bước ghép video; bấm
Retry thì nó "writing scenes 19-24 of 79" — viết bài MỚI từ đầu. Vì checkpoint chỉ
đọc sự kiện MỚI NHẤT, mà bước studio ghi {drama_id, episode_id} đè lên {script} của
bước kịch bản. Cam kết được canh ở đây:
  1. _read_checkpoint gộp mọi sự kiện (bản sau thắng) — cứu cả task cũ đã lỡ ghi đè.
  2. Luồng auto: bản sổ MỚI NHẤT đã đủ kịch bản lẫn tập Studio.
  3. Retry: không gọi model, dùng đúng kịch bản cũ, dùng lại tập Studio (không tạo
     drama mới ⇒ không vẽ lại storyboard / ảnh / giọng).
  4. Sổ mất kịch bản mà còn tập → lấy kịch bản từ chính tập Studio.
  5. Có góp ý (Request changes) → vẫn viết lại theo góp ý như cũ.
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
# Bước dựng có gọi _put — KHÔNG để test gửi PUT thật tới máy chủ đang chạy.
P._put = lambda path, payload=None, timeout=60, **k: {}
import tubecli.extensions.codex.manager as CM  # noqa: E402

PASS = FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", label)
    else:
        FAIL += 1
        print("  FAIL", label, "—", detail)


# Sổ sự kiện giả, theo thứ tự thời gian như get_events thật.
EVENTS = {}
CM.codex_manager.get_events = lambda task_id, limit=1000: list(EVENTS.get(task_id, []))
CM.codex_manager.append_event = lambda task_id, kind, message, actor="", data=None, **k: \
    EVENTS.setdefault(task_id, []).append({"kind": kind, "message": message, "data": data or {}})

print("── 1. đọc sổ: gộp mọi sự kiện ────────────────────────────────")
EVENTS["old"] = [{"data": {"checkpoint": {"script": "S1", "title": "T"}}},
                 {"data": {}},
                 {"data": {"checkpoint": {"drama_id": 5, "episode_id": 7, "title": "T2"}}}]
ck = P._read_checkpoint("old")
ok(ck.get("script") == "S1" and ck.get("episode_id") == 7 and ck.get("title") == "T2",
   "task CŨ đã lỡ ghi đè: vẫn còn cả kịch bản lẫn tập, bản sau thắng", ck)
ok(P._read_checkpoint("") == {} and P._read_checkpoint("khong-co") == {}, "task rỗng / không có sổ → {}")

print("── 2. luồng auto: bản sổ mới nhất đủ cả hai ──────────────────")
calls = []


def fake_ask(agent, system_prompt, user_prompt, budget_words):
    calls.append(user_prompt)
    return "TITLE: Uno\n\n[SHOW: a]\nFrase uno.\n\n[SHOW: b]\nFrase dos."


class Agent:
    name, language, id, model = "MC", "auto", "a1", "x"


P._ask_model = fake_ask
P._publish_plan = lambda task_id, agent_name, title, script: len(P.scenes_of(script))
P.resolve_language = lambda *a, **k: ("es", "preset")
P.detect_language = lambda text: ""
PASTED = "palabra " * 300


def st_for(task_id, feedback=None):
    return {"agent": Agent(), "corpus": [{"title": "", "url": "", "content": PASTED, "source": "pasted"}],
            "preset": None, "task_id": task_id, "checkpoint": P._read_checkpoint(task_id),
            "_say": lambda *a: None, "_cancelled": lambda: False, "warnings": [], "feedback": feedback or []}


posts = []


def fake_post(path, payload, timeout=300):
    posts.append(path)
    return {"id": 5} if path.endswith("/dramas") else {"id": 7}


P._post = fake_post
P._storyboards = lambda ep: [{"id": 1, "storyboard_number": 1, "narration_text": "Frase uno.", "image_prompt": "a"},
                             {"id": 2, "storyboard_number": 2, "narration_text": "Frase dos.", "image_prompt": "b"}]
P._stream_storyboard = lambda *a, **k: None
P._template_style = lambda state: ""

st = st_for("auto1")
P._step_script(st, {"source_text": PASTED})
P._step_studio(st, {})
newest = EVENTS["auto1"][-1]["data"]["checkpoint"]
ok(len(calls) == 1 and posts[-2:] == ["/api/v1/studio/dramas", "/api/v1/studio/dramas/5/episodes"],
   "lần đầu: model viết kịch bản, tạo drama + tập", (len(calls), posts))
ok(str(newest.get("script") or "").startswith("[SHOW: a]") and newest.get("episode_id") == 7,
   "bản sổ MỚI NHẤT đã đủ cả kịch bản lẫn tập Studio (bệnh cũ: chỉ còn tập)", newest)

print("── 3. Retry sau khi dựng lỗi ─────────────────────────────────")
calls.clear()
posts.clear()
st2 = st_for("auto1")
P._step_script(st2, {"source_text": PASTED})
ok(calls == [], "KHÔNG gọi model viết lại (bệnh cũ: 'writing scenes 19-24 of 79')", len(calls))
ok(st2.get("script") == st["script"], "dùng đúng kịch bản của lượt trước")
P._step_studio(st2, {})
ok(posts == [] and st2.get("episode_id") == 7,
   "dùng lại tập Studio — không tạo drama mới ⇒ không vẽ lại storyboard / ảnh / giọng", posts)

print("── 4. sổ mất kịch bản mà còn tập ─────────────────────────────")
EVENTS["pruned"] = [{"data": {"checkpoint": {"drama_id": 5, "episode_id": 7, "title": "T"}}}]
P._get = lambda path, timeout=60: ({"id": 7, "script_content": "[SHOW: a]\nFrase uno."}
                                   if path.endswith("/episodes/7") else {})
calls.clear()
st3 = st_for("pruned")
P._step_script(st3, {"source_text": PASTED})
ok(calls == [] and str(st3.get("script")).startswith("[SHOW: a]"),
   "lấy kịch bản từ chính tập Studio, không viết bài mới", (len(calls), st3.get("script")))

print("── 5. có góp ý thì vẫn viết lại ──────────────────────────────")
EVENTS["fb"] = [{"data": {"checkpoint": {"script": "TITLE: x\n\n[SHOW: a]\nuno", "title": "x"}}}]
calls.clear()
st4 = st_for("fb", feedback=["ngắn quá"])
P._step_script(st4, {"source_text": PASTED})
ok(len(calls) == 1 and "ngắn quá" in calls[0], "Request changes → viết lại theo góp ý như trước", len(calls))

print()
print("=" * 62)
print(f"{PASS}/{PASS + FAIL} PASS" if not FAIL else f"{PASS}/{PASS + FAIL} PASS — {FAIL} HỎNG")
sys.exit(1 if FAIL else 0)
