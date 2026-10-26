# -*- coding: utf-8 -*-
"""Mẫu MANGA DRAMA ở lõi content_video: viết kịch bản khung + lời theo người nói, tách khung ở Studio (không AI),
bỏ TTS một giọng / lồng giọng. Mọi HTTP và model đều giả."""
import json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from tubecli.extensions.content_video import pipeline as P     # noqa: E402
from tubecli.extensions.content_video import manga_script as MS     # noqa: E402

PASS = FAIL = 0


def ok(cond, name, info=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", name)
    else:
        FAIL += 1
        print("  FAIL", name, "—", info)


def boom(*a, **k):
    raise AssertionError("must not be called in manga mode")


PLAN = {"title": "【漫画】義妹が見下す兄の正体は…【胸キュン漫画】", "logline": "x",
        "cast": [{"id": "Minato", "name": "篠宮 湊", "reading": "しのみや みなと", "call": "湊", "call_reading": "みなと",
                  "gender": "male", "age": "teen", "role": "lead", "look": "messy black hair | navy blazer"},
                 {"id": "hiyori", "name": "篠宮 ひより", "reading": "しのみや ひより", "call": "ひより", "call_reading": "",
                  "gender": "female", "age": "teen", "role": "heroine", "look": "chestnut hair"}],
        "locations": [{"id": "kitchen", "name": "キッチン", "look": "a small kitchen"}],
        "parts": [{"title": "朝", "beats": "morning", "panels": 2}, {"title": "夜", "beats": "night", "panels": 2}]}
PANELS = ("Here are the panels:\n```\n[SHOW: kitchen | minato, hiyori | two-shot]\nひより: また朝まで起きてたの？\n湊: ああ\n\n"
          "[SHOW: kitchen | hiyori | close-up]\nひより（心）: この人、毎晩なにしてるんだろ\n```")

print("── ngân sách / dàn ý ──")
b = MS.budget(13)
ok(85 <= b["panels"] <= 100 and 7 <= b["parts"] <= 9, "13 phút ≈ 95 khung / 8 phần", b)
ok(MS.budget(3)["panels"] >= 12 and MS.budget(3)["cast"] == 3, "tập ngắn vẫn đủ khung", MS.budget(3))
plan = MS.parse_plan("```json\n" + json.dumps(PLAN, ensure_ascii=False) + "\n```")
ok(plan["cast"][0]["id"] == "minato" and len(plan["parts"]) == 2, "dàn ý trong khối ``` + id chữ thường", plan["cast"][0])
try:
    MS.parse_plan('{"cast": []}')
    ok(False, "dàn ý thiếu nhân vật → lỗi")
except ValueError:
    ok(True, "dàn ý thiếu nhân vật → lỗi")
ok(MS.panels_only(PANELS).startswith("[SHOW:") and "```" not in MS.panels_only(PANELS), "bỏ câu dẫn + ```")
hd = MS.header(plan)
ok("minato | 篠宮 湊（しのみや みなと） | 湊（みなと） | male | teen | messy black hair / navy blazer" in hd
   and "LOCATIONS:\nkitchen | キッチン | a small kitchen" in hd, "dàn nhân vật: cách đọc trong ngoặc, «|» trong mô tả bị thay", hd)

print("── viết kịch bản ──")
calls = []


def fake_ask(sysm, user, budget):
    calls.append(user)
    return json.dumps(PLAN, ensure_ascii=False) if len(calls) == 1 else PANELS


said = []
title, script = MS.write(fake_ask, "MATERIAL", "Write in Japanese.", 3, say=said.append)
ok(title.startswith("【漫画】") and script.startswith("CAST:\n"), "tiêu đề + kịch bản bắt đầu bằng dàn nhân vật", script[:40])
ok(script.count("[SHOW:") == 4 and len(calls) == 3, "2 phần × 2 khung, 3 lượt model", (script.count("[SHOW:"), len(calls)))
ok("The previous panels ended with" in calls[2] and "ひより（心）" in calls[2], "phần sau thấy cuối phần trước", calls[2][-200:])
ok("Write in Japanese." in calls[0] and "MATERIAL" in calls[0], "dàn ý mang tài liệu + ngôn ngữ")
ok(MS.dialogue_chars(script) == 2 * (len("また朝まで起きてたの？") + len("ああ") + len("この人、毎晩なにしてるんだろ")),
   "đếm chữ thoại (bỏ dàn nhân vật / tiêu đề khung)", MS.dialogue_chars(script))
ok(any("planning" in s for s in said) and any("part 2/2" in s for s in said), "báo tiến độ", said)

print("── cờ manga + các bước ──")
st_m = {"preset": {"name": "Manga", "fields": {"metadata": {"script_format": "manga"}}}}
ok(P._manga_mode(st_m) and not P._manga_mode({"preset": {"fields": {"metadata": {}}}}) and not P._manga_mode({}),
   "_manga_mode theo metadata.script_format")

said2, merged, plans = [], [], []
P._ask_model = lambda agent, sysm, user, budget: fake_ask(sysm, user, budget)
calls.clear()
P._task_title = lambda *a, **k: None
P._task_meta = lambda *a, **k: None
P._checkpoint_merge = lambda state, d: merged.append(d)
P._publish_plan = lambda tid, name, title, text: plans.append(text) or text.count("[SHOW:")
P._checkpoint_sources = lambda state, limit=10: []


class Agent:
    name = "Manga Writer"
    id = "a1"


st = dict(st_m, task_id="t1", corpus=[{"content": "x"}], _say=lambda step, status, msg="", *a: said2.append(msg),
          _cancelled=lambda: False, language="ja")
P._step_script_manga(st, {}, Agent(), ["BLOCK"], False, "Write in Japanese.", 900)
ok(st["script"].count("[SHOW:") == 4 and st["title"].startswith("【漫画】"), "_step_script_manga ghi kịch bản + tiêu đề")
ok(merged and merged[-1]["script"] == st["script"] and st["scene_count"] == 4, "checkpoint + kế hoạch", merged[-1].keys())
ok(st["estimated_minutes"] > 0 and any("panels" in m for m in said2), "ước phút theo chữ thoại", said2[-1:])
ok(P._step_script_manga.__doc__ and "manga_script" in P._step_script_manga.__doc__, "docstring")

posts = []
P._post = lambda path, body, timeout=60: posts.append(path) or {"kept": False, "cast": [{"name": "篠宮 湊"}], "warnings": []}
P._storyboards = lambda ep: [{"id": 1}, {"id": 2}]
P._stream_storyboard = boom
said3 = []
st2 = dict(st_m, agent=Agent(), checkpoint={"drama_id": 7, "episode_id": 9, "title": "T"}, task_id="t2",
           _say=lambda step, status, msg="", *a: said3.append(msg))
P._step_studio(st2, {})
ok(posts == ["/api/v1/studio/episodes/9/manga/storyboard"] and st2["shot_count"] == 2, "studio: tách khung bằng route manga",
   posts)
ok(any("2 panels" in m and "篠宮 湊" in m for m in said3), "báo số khung + dàn nhân vật", said3)

P._join_tts_prefetch = boom
P._tts_prepare = boom
said4 = []
P._step_tts(dict(st_m, _say=lambda step, status, msg="", *a: said4.append(msg)), {})
ok(said4 and "per character" in said4[0], "TTS một giọng bị bỏ", said4)
P._step_dub(dict(st_m, episode_id=9, _say=lambda step, status, msg="", *a: said4.append(msg)), {"dub": True})
ok("re-dub" in said4[-1], "lồng giọng Muse bị bỏ", said4[-1])

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(0 if FAIL == 0 else 1)
