# -*- coding: utf-8 -*-
"""Prompt nghiên cứu + ba trường mới của agent (10/10/2026).

Kiểm (KHÔNG mạng — model giả):
  1. trường agent: auto_video / youtube_subs_per_run (0–5) / research_prompt (≤2000) ép kiểu ở cả hai cửa
  2. từ khoá hằng ngày: lời nhờ model mang RESEARCH BRIEF khi có, không mang khi trống
  3. kịch bản từ kho: research_note mang đề bài; trống thì không thêm gì

Run:  python tests/agent_research_prompt_test.py
"""
import json
import os
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")

from tubecli.core import agent as AG     # noqa: E402

PASS = FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", label)
    else:
        FAIL += 1
        print("  FAIL", label, "—", str(detail)[:300])


print("── 1. trường agent ────────────────────────────────────────────")
a = AG.Agent(name="R", youtube_subs_per_run="9", research_prompt="  x " * 900, auto_video="yes")
ok(a.youtube_subs_per_run == 5 and a.auto_video is True, "nạp: số video kẹp 0–5, công tắc thành bool",
   (a.youtube_subs_per_run, a.auto_video))
ok(len(a.research_prompt) <= AG.RESEARCH_PROMPT_MAX and not a.research_prompt.startswith(" "), "prompt cắt + bỏ khoảng trắng")
d = a.to_dict()
ok(all(k in d for k in ("auto_video", "youtube_subs_per_run", "research_prompt")), "to_dict có đủ 3 trường")
ok(AG.Agent(name="D").youtube_subs_per_run == 2 and AG.Agent(name="D").auto_video is False, "mặc định: 2 video, tự dựng tắt")
ok(AG.coerce_publish_fields({"youtube_subs_per_run": "rác", "research_prompt": None}) ==
   {"youtube_subs_per_run": 2, "research_prompt": ""}, "cửa PUT: rác ⇒ mặc định")

print("── 2. từ khoá hằng ngày ───────────────────────────────────────")
from tubecli.api import server as SV         # noqa: E402
from tubecli.core import brain as BR         # noqa: E402
from tubecli.core import scraped_store as SS  # noqa: E402

asked = []


def fake_llm(agent_dict, messages, temperature=0.7, **k):
    asked.append(messages[-1]["content"])
    return json.dumps({p: ["q1", "q2", "q3", "q4", "q5"] for p in ("morning", "afternoon", "evening", "night")})


BR.AgentBrain._call_llm = staticmethod(fake_llm)
SS.resolve_profiles = lambda profiles: []
saved = []
AG.agent_manager.get = lambda aid: ag
AG.agent_manager.update = lambda aid, **kw: saved.append(kw)
ag = AG.Agent(name="Lab", description="AI researcher", research_prompt="GPU efficiency tricks for small labs",
              language="en")
SV.check_and_generate_daily_keywords(ag, datetime(2026, 10, 10, 9))
ok(asked and 'RESEARCH BRIEF from the owner' in asked[-1] and "GPU efficiency tricks for small labs" in asked[-1],
   "lời nhờ sinh từ khoá mang đề bài nghiên cứu", asked[-1][:400] if asked else "")
ok(saved and saved[-1]["routine"]["daily_keywords"]["date"] == "2026-10-10", "vẫn lưu từ khoá như cũ")
ag2 = AG.Agent(name="Lab2", description="x", language="en")
AG.agent_manager.get = lambda aid: ag2
SV.check_and_generate_daily_keywords(ag2, datetime(2026, 10, 10, 9))
ok("RESEARCH BRIEF" not in asked[-1], "không có đề bài ⇒ lời nhờ như cũ")

print("── 3. kịch bản từ kho ─────────────────────────────────────────")
from tubecli.extensions.content_video import pipeline as P   # noqa: E402

n = P.research_note(ag)
ok(n.startswith("\n\n") and "GPU efficiency tricks for small labs" in n and "only facts from the material" in n,
   "research_note mang đề bài + giữ luật chỉ dùng dữ kiện", n)
ok(P.research_note(ag2) == "", "trống ⇒ không thêm gì")
src = open(P.__file__, encoding="utf-8").read()
ok("if not pasted and not reference:\n        system_prompt += research_note(agent)" in src,
   "chỉ gắn khi video làm TỪ KHO (không phải nội dung dán / tham khảo cấu trúc)")

print()
print(f"{PASS}/{PASS + FAIL} PASS" if not FAIL else f"{PASS}/{PASS + FAIL} PASS — {FAIL} HỎNG")
sys.exit(1 if FAIL else 0)
