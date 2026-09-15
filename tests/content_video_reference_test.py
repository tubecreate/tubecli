# -*- coding: utf-8 -*-
"""Codex «Tạo video từ nội dung»: link YouTube → phụ đề, «Tham khảo cấu trúc, viết mới», lời dặn riêng,
thời lượng đọc vào prompt + chặn kịch bản dài (15/9/2026). Không gọi model, không ra mạng.

Kiểm:
  A. describe_plan: link → "subtitles of 1 YouTube video"; tham khảo + giữ chủ đề; lời dặn; thời lượng mục tiêu;
     bài dán tay → dòng cũ
  B. _step_gather: chỉ link → corpus = phụ đề (source pasted), youtube_sources; hỏng hết → lỗi kể lý do; hỏng một
     → cảnh báo; bài có lẫn link → LỐI CŨ (corpus = bài dán)
  C. «Tham khảo cấu trúc»: lượt 1 thấy nguồn; MỌI lượt viết không thấy câu nguồn, chỉ thấy bản cấu trúc; quy tắc
     viết mới + giữ/bỏ chủ đề; lời dặn ở prompt hệ thống; độ dài theo PHỤ ĐỀ; bản cấu trúc ghi checkpoint và
     được dùng lại
  D. độ dài: dàn ý 92 cảnh cho 60 → hỏi lại → gộp còn 60; câu ±10 % trong prompt dàn ý + mỗi đợt; lượt viết
     một lần dài quá → rút gọn; vẫn dài → cảnh báo; merge_outline giữ thứ tự và mọi ý
  E. «AI viết lại» bài dán tay giữ nguyên: không có lượt cấu trúc, vẫn dặn "Cover ALL of the content"

Run:  python tests/content_video_reference_test.py
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
from tubecli.core import youtube_transcript as YT  # noqa: E402

PASS = FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", label)
    else:
        FAIL += 1
        print("  FAIL", label, "—", str(detail)[:300])


BASE = "la calma nos ayuda a vivir con más paz y claridad cada día que pasa en la vida de cada persona".split()
MARKER = "barquero anciano remaba despacio junto al río"


def es(n):
    return " ".join((BASE * (n // len(BASE) + 1))[:n]) + "."


SOURCE = (MARKER + ". ") + es(4480)          # ~4500 chữ phụ đề, có một câu đánh dấu
LINK = "https://www.youtube.com/watch?v=4Br45kOed_s"


class Agent:
    id = "a1"
    name = "Orchestrator"
    model = "fake"
    language = "auto"

    def to_dict(self):
        return {"id": self.id, "name": self.name, "model": self.model}


merged = []
P._checkpoint_merge = lambda state, extra: (merged.append(dict(extra)), state.setdefault("checkpoint", {}).update(extra))
P._publish_plan = lambda task_id, name, title, text: len([s for s in P.scenes_of(text) if s[1]])
P._get = lambda *a, **k: {}


def new_state(content=None, checkpoint=None):
    said = []
    st = {"agent": Agent(), "task_id": "t1", "warnings": [], "feedback": [], "checkpoint": dict(checkpoint or {}),
          "preset": {"fields": {"language": "es", "metadata": {}}}, "_cancelled": lambda: False,
          "_say": lambda step, status, msg, pct=None: said.append(msg)}
    if content is not None:
        st["corpus"] = [{"title": "", "url": "", "content": content, "source": "pasted", "scraped_at": ""}]
    return st, said


print("── A. describe_plan ────────────────────────────────────────")
d = P.describe_plan({"source_text": LINK, "script_mode": "reference", "keep_theme": True,
                     "instructions": "tono cálido, tutear al espectador", "target_words": 1500})
ok("- Source: subtitles of 1 YouTube video(s), read when the task runs" in d, "link → nguồn là phụ đề YouTube", d)
ok("a NEW script built on the source's structure" in d and "its theme and references are kept" in d, "tham khảo + giữ chủ đề")
ok("- Extra instructions: tono cálido, tutear al espectador" in d and "- Target read-aloud duration: ~10.0 min (~1500 words)" in d, "lời dặn + thời lượng mục tiêu", d)
d2 = P.describe_plan({"source_text": "Un artículo largo " * 30 + LINK, "script_mode": "reference", "keep_theme": False})
ok("- Source: pasted content (~" in d2 and "its tradition and names are left out" in d2, "bài dán có lẫn link → dòng cũ; bỏ chủ đề", d2)

print("── B. _step_gather ─────────────────────────────────────────")
fetched = []


def fake_fetch(ref, prefer_lang="", timeout=60, use_cache=True):
    fetched.append((ref, prefer_lang))
    if ref == "badbadbad01":
        return {"ok": False, "id": ref, "message": "This video has no subtitles"}
    return {"ok": True, "id": ref, "url": f"https://www.youtube.com/watch?v={ref}", "title": "La Calma", "channel": "Paz en el Tao",
            "language": "es-orig", "kind": "auto", "text": SOURCE, "words": P.content_words(SOURCE), "minutes": 30.0}


YT.fetch_transcript = fake_fetch
st, said = new_state()
P._step_gather(st, {"source_text": LINK, "language": "es"})
ok(st["corpus"][0]["content"] == SOURCE and st["corpus"][0]["source"] == "pasted" and st["corpus"][0]["title"] == "La Calma",
   "chỉ link → corpus là phụ đề, đánh dấu pasted", st["corpus"][0]["title"])
ok(st["youtube_sources"][0]["channel"] == "Paz en el Tao" and fetched[-1] == ("4Br45kOed_s", "es"), "youtube_sources + xin đúng ngôn ngữ", fetched[-1])
ok(any("YouTube subtitles · 1 video(s)" in m and "min read aloud" in m for m in said), "câu trạng thái kể số chữ và phút đọc", said)
st, said = new_state()
try:
    P._step_gather(st, {"source_text": "https://youtu.be/badbadbad01"}); ok(False, "phải ném")
except RuntimeError as e:
    ok("no subtitles" in str(e) and "Paste the video's text" in str(e), "hỏng hết → lỗi kể lý do", e)
st, said = new_state()
P._step_gather(st, {"source_text": "https://youtu.be/badbadbad01 " + LINK})
ok(len(st["corpus"]) == 1 and any("Skipped YouTube link" in w for w in st["warnings"]), "hỏng một link → vẫn chạy, có cảnh báo", st["warnings"])
article = "La calma ordena tu vida. " * 30 + "Mira https://youtu.be/4Br45kOed_s"
st, said = new_state()
n_before = len(fetched)
P._step_gather(st, {"source_text": article})
ok(st["corpus"][0]["content"] == article.strip() and len(fetched) == n_before and "youtube_sources" not in st, "bài có lẫn link → LỐI CŨ, không tải phụ đề")

print("── C. «Tham khảo cấu trúc» ─────────────────────────────────")
calls = []
BLUEPRINT = "THEME & REFERENCES: Taoism, Lao Tzu. BEATS: " + " ".join(f"beat{i} hook reframe story practice ending" for i in range(30))


def fake_ask(agent, system_prompt, user_prompt, budget_words):
    calls.append({"system": system_prompt, "user": user_prompt, "budget": budget_words})
    if "Extract the structural blueprint" in user_prompt:
        return BLUEPRINT
    if "then one line per scene" in user_prompt:
        n = FAKE_OUTLINE_N[0]
        return "TITLE: La Calma Nueva\n" + "\n".join(f"[SHOW: escena {i}] — idea {i}" for i in range(1, n + 1))
    if "Write the narration for scenes" in user_prompt:
        import re
        m = re.search(r"scenes (\d+)-(\d+) ONLY", user_prompt)
        a, b = int(m.group(1)), int(m.group(2))
        per = int(re.search(r"about (\d+) words, never more than", user_prompt).group(1))
        return "\n\n".join(f"[SHOW: escena {i}]\n{es(per)}" for i in range(a, b + 1))
    if "This script is too long" in user_prompt:
        return "TITLE: Corta\n\n" + "\n\n".join(f"[SHOW: e{i}]\n{es(SHORTEN_PER[0])}" for i in range(6))
    if "Rewrite this content as the narration script" in user_prompt or "Write the narration script" in user_prompt:
        return "TITLE: Larga\n\n" + "\n\n".join(f"[SHOW: e{i}]\n{es(150)}" for i in range(6))
    return "TITLE: X\n\n[SHOW: x]\n" + es(60)


FAKE_OUTLINE_N = [60]
SHORTEN_PER = [75]
P._ask_model = fake_ask
st, said = new_state(SOURCE)
st["youtube_sources"] = [{"words": P.content_words(SOURCE)}]
opts = {"source_text": LINK, "script_mode": "reference", "keep_theme": True, "language": "es",
        "instructions": "tono cálido, tutear al espectador"}
P._step_script(st, opts)
ok(calls[0]["user"].count(MARKER) == 1 and "Extract the structural blueprint" in calls[0]["user"], "lượt 1 (cấu trúc) thấy nguồn")
writer = calls[1:]
ok(writer and all(MARKER not in c["user"] and MARKER not in c["system"] for c in writer), "MỌI lượt viết không thấy câu nguồn", len(writer))
ok(all("STRUCTURAL BLUEPRINT" in c["user"] and "beat0" in c["user"] for c in writer), "lượt viết chỉ thấy bản cấu trúc")
ok(all("ORIGINAL" in c["system"] and "you may name the tradition" in c["system"] for c in writer), "quy tắc viết mới + giữ chủ đề ở prompt hệ thống")
ok(all("Instructions from the channel owner" in c["system"] and "tutear al espectador" in c["system"] for c in writer), "lời dặn ở prompt hệ thống của mọi lượt viết")
ok(st["target_words"] == 4000 and st["words_from"] == "content", "độ dài theo PHỤ ĐỀ (kẹp 4000), không theo 43 ký tự link", (st["target_words"], st["words_from"]))
ok(not st.get("keep_all") and not any("condenses" in w for w in st["warnings"]), "tham khảo: không 'keep all', không báo 'nén'", st["warnings"])
ok(any(m.get("blueprint") == BLUEPRINT for m in merged) and st["blueprint"] == BLUEPRINT, "bản cấu trúc ghi checkpoint")
ok(any("min read aloud" in m for m in said) and st.get("estimated_minutes"), "câu kết kể phút đọc", said[-1])
calls.clear()
st, said = new_state(SOURCE, checkpoint={"blueprint": BLUEPRINT})
st["youtube_sources"] = [{"words": 4500}]
P._step_script(st, {**opts, "keep_theme": False})
ok(not any("Extract the structural blueprint" in c["user"] for c in calls), "checkpoint có bản cấu trúc → không bóc lại")
ok(all("do not name the source's tradition" in c["system"] for c in calls), "bỏ chủ đề → dặn không nêu tên truyền thống")

print("── D. độ dài ───────────────────────────────────────────────")
calls.clear()
FAKE_OUTLINE_N[0] = 92
st, said = new_state(SOURCE)
st["youtube_sources"] = [{"words": 4500}]
P._step_script(st, opts)
outlines = [c for c in calls if "then one line per scene" in c["user"]]
batches = [c for c in calls if "Write the narration for scenes" in c["user"]]
ok(len(outlines) == 2 and "IMPORTANT: your previous outline had 92 scenes" in outlines[1]["user"], "dàn ý 92 cho 60 → hỏi lại một lần", len(outlines))
ok(len(batches) == 10 and "writing scenes 55-60 of 60" in said, "gộp còn 60 cảnh → 10 đợt viết", len(batches))
ok(any("merging 92 outline scenes into 60" in m for m in said), "báo đã gộp dàn ý", [m for m in said if "outline" in m])
ok("Target read-aloud duration: about 26.7 minutes" in outlines[0]["user"] and "between 3600 and 4400 words" in outlines[0]["user"], "câu ±10 % ở prompt dàn ý")
ok(all("never more than" in c["user"] for c in batches), "mỗi đợt có trần chữ mỗi cảnh")
FAKE_OUTLINE_N[0] = 60
mo = P.merge_outline([(f"s{i}", f"g{i}") for i in range(92)], 60)
ok(len(mo) == 60 and mo[0][0] == "s0" and " ".join(g for _, g in mo).split() == [f"g{i}" for i in range(92)], "merge_outline: đúng 60, giữ thứ tự và mọi ý")

calls.clear()
st, said = new_state("Un artículo corto sobre la calma. " * 40)
P._step_script(st, {"source_text": "x", "script_mode": "rewrite", "length_mode": "minutes", "target_words": 450, "language": "es"})
shorten = [c for c in calls if "This script is too long" in c["user"]]
single = [c for c in calls if "Rewrite this content as the narration script" in c["user"]]
ok(single and "Target read-aloud duration: about 3.0 minutes" in single[0]["user"], "lượt viết một lần có câu thời lượng đọc", single[0]["user"][-400:] if single else "")
ok(len(shorten) == 1 and "TITLE: Corta" not in st["script"] and st["title"] == "Corta", "900 chữ cho 450 → rút gọn một lần, dùng bản ngắn", (len(shorten), st["title"]))
ok(not any("came out at" in w and "against" in w and "shorten it" in w for w in st["warnings"]), "bản ngắn vừa → không cảnh báo dài", st["warnings"])
calls.clear()
SHORTEN_PER[0] = 130
st, said = new_state("Un artículo corto sobre la calma. " * 40)
P._step_script(st, {"source_text": "x", "script_mode": "rewrite", "length_mode": "minutes", "target_words": 450, "language": "es"})
ok(any("shorten it to about 3.0 minutes" in w for w in st["warnings"]), "rút gọn rồi vẫn dài → cảnh báo có số phút", st["warnings"])
ok(P.long_script_warning(5739, 4000) and not P.long_script_warning(4400, 4000), "long_script_warning: >20 % mới báo")

print("── E. lối cũ giữ nguyên ────────────────────────────────────")
calls.clear()
SHORTEN_PER[0] = 75
st, said = new_state(es(2000))
P._step_script(st, {"source_text": es(2000), "script_mode": "rewrite", "language": "es"})
ok(not any("Extract the structural blueprint" in c["user"] for c in calls), "«AI viết lại» bài dán tay: không có lượt cấu trúc")
ok(any("Cover ALL of the content" in c["user"] for c in calls) and st["keep_all"], "vẫn dặn giữ hết ý như cũ")
ok(all("Instructions from the channel owner" not in c["system"] for c in calls), "không có lời dặn → prompt hệ thống như cũ")

print()
print(f"{PASS}/{PASS + FAIL} PASS" if not FAIL else f"{PASS}/{PASS + FAIL} PASS — {FAIL} HỎNG")
sys.exit(1 if FAIL else 0)
