# -*- coding: utf-8 -*-
"""Chế độ NGUYÊN VĂN của «Tạo video từ nội dung» (script_mode="verbatim", 13/9/2026).

Tập 337: dù đã dặn "giữ đủ", kịch bản viết lại vẫn mất 13 % câu và thêm 16 % câu tự bịa.
Cam kết canh ở đây, đối chiếu code thật trong extensions/content_video/pipeline.py:
  A. verbatim_scenes  — cắt theo ranh giới câu, ~60 chữ/cảnh, nối lại = đúng bài; chữ Hán
                        cắt sau 。！？; bài không dấu chấm vẫn được chia
  B. parse_verbatim   — khối "N. [SHOW: …]\\n<lời>", có/không số, TITLE
  C. _step_script     — cùng ngôn ngữ: lời đọc = ĐÚNG bài, model chỉ tả hình; thẻ nói rõ
  D. góp ý khi duyệt  — lời giữ nguyên, chỉ hình đổi
  E. khác ngôn ngữ    — dịch sát từng câu, đủ cảnh; dịch thiếu → hỏi lại → rơi về viết lại + cảnh báo

Run:  python tests/content_video_verbatim_test.py     (exit 0 = pass)
"""
import math
import re
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
        print("  FAIL", label, "—", str(detail)[:400])


ES = ["Hay una pregunta que puede revelar hacia dónde va realmente tu vida.",
      "No es cuánto dinero ganas, ni qué puesto tienes, ni cuántas personas te conocen.",
      "Lo que pones en primer lugar termina ordenando todo lo demás en tu casa y en tu trabajo.",
      "Por eso las prioridades importan tanto, y por eso hoy quiero hablarte de orden y de dirección."]
# Bài dán kiểu người dùng: mỗi câu một dòng, dòng trống xen kẽ, có điệp khúc ngắn và trích dẫn
PASTE = "\n\n".join(
    [ES[i % 4] + f" Tema{i}." for i in range(1, 41)]
    + ["Reino primero."] * 11
    + ["Mateo 6:33 dice:", "“Buscad primeramente el reino de Dios y su justicia.”"]
    + [ES[i % 4] + f" Tema{i}." for i in range(41, 61)])

# ── A. verbatim_scenes ────────────────────────────────────────────────────────
print("── A. cắt cảnh nguyên văn ───────────────────────────────────")
scenes = P.verbatim_scenes(PASTE)
norm = " ".join(PASTE.split())
ok(" ".join(scenes) == norm, "nối các cảnh lại = đúng bài dán (không mất, không thêm, không đảo)")
ws = [P.content_words(s) for s in scenes]
ok(40 <= sorted(ws)[len(ws) // 2] <= 95 and max(ws) <= 130, "~60 chữ/cảnh (trung vị 40–95, tối đa 130)", (sorted(ws)[len(ws) // 2], max(ws)))
ok(all(re.search(r"[.!?…”\"]$", s) for s in scenes[:-1]), "không cảnh nào cắt giữa câu", [s[-30:] for s in scenes if not re.search(r"[.!?…”\"]$", s)][:2])
ok(any(s.count("Reino primero.") >= 5 for s in scenes), "điệp khúc ngắn được gom vào một cảnh", [s for s in scenes if "Reino" in s][:1])
ok(ws[-1] >= P._VERBATIM_MIN_SCENE, "cảnh đuôi không lẻ loi vài chữ", ws[-1])
ok(P.verbatim_scenes("") == [] and P.verbatim_scenes("\n \n") == [], "rỗng → không cảnh")
zh = "这是第一句话。这是第二句话！这是第三句话？" * 30
zs = P.verbatim_scenes(zh)
ok(len(zs) >= 3 and all(s.endswith(("。", "！", "？")) for s in zs) and "".join(zs) == zh,
   "chữ Hán: cắt sau 。！？ (không có dấu cách), nối lại đúng bài", (len(zs), zs[0][-6:] if zs else ""))
nodots = " ".join(f"w{i}" for i in range(300))
ns = P.verbatim_scenes(nodots)
ok(3 <= len(ns) <= 6 and " ".join(ns) == nodots, "300 chữ không dấu chấm → vẫn chia ~60 chữ", len(ns))
ok(P.split_sentences("Ver www.x.com y el Salmo 6.33 hoy. Luego sigue.") == ["Ver www.x.com y el Salmo 6.33 hoy.", "Luego sigue."],
   "chấm trong tên miền/số không phải kết câu", P.split_sentences("Ver www.x.com y el Salmo 6.33 hoy. Luego sigue."))

# ── B. parse_verbatim ─────────────────────────────────────────────────────────
print("── B. đọc trả lời của model ──────────────────────────────────")
title, blocks = P.parse_verbatim("TITLE: La pregunta\n\n1. [SHOW: una ventana]\n2. [SHOW: una agenda]\n3. [SHOW: un camino]\n", 1, 3)
ok(title == "La pregunta" and blocks == {1: ("una ventana", ""), 2: ("una agenda", ""), 3: ("un camino", "")}, "SHOW theo số, có tiêu đề", blocks)
_, blocks = P.parse_verbatim("[SHOW: a]\nLínea uno.\nLínea dos.\n\n[SHOW: b]\nOtra.\n", 5, 2)
ok(blocks == {5: ("a", "Línea uno. Línea dos."), 6: ("b", "Otra.")}, "khối không đánh số → theo thứ tự, lời nhiều dòng gộp lại", blocks)
_, blocks = P.parse_verbatim("7. [SHOW: x]\ntexto\n9. [SHOW: y]\n", 7, 2)
ok(blocks == {7: ("x", "texto")}, "số ngoài khoảng bị bỏ", blocks)
ok(P._fallback_show("Hay una pregunta que puede revelar. Otra frase.") == "Hay una pregunta que puede revelar.", "không có SHOW → câu đầu làm gợi ý hình")

# ── C. _step_script nguyên văn cùng ngôn ngữ ──────────────────────────────────
print("── C. lời đọc = đúng bài, model chỉ tả hình ─────────────────")


class Agent:
    id, name, language, model = "a1", "MC", "auto", "x"

    def to_dict(self):
        return {"id": self.id, "name": self.name, "model": self.model}


calls = []


def fake_ask(agent, system_prompt, user_prompt, budget_words):
    calls.append((system_prompt, user_prompt, budget_words))
    m = re.search(r"Passages (\d+)-(\d+) of (\d+)", user_prompt)
    if not m:                                                   # đường viết lại như cũ
        mo = re.search(r"in exactly (\d+) scenes", user_prompt)
        if "Plan a" in user_prompt and mo:
            return "TITLE: R\n" + "\n".join(f"{i}. [SHOW: f{i}] — gist {i}" for i in range(1, int(mo.group(1)) + 1))
        mb = re.search(r"scenes (\d+)-(\d+) ONLY", user_prompt)
        if mb:
            return "\n\n".join(f"[SHOW: f{i}]\n{ES[i % 4]} R{i}." for i in range(int(mb.group(1)), int(mb.group(2)) + 1))
        return "TITLE: R\n\n[SHOW: f]\n" + " ".join(ES) + " " + " ".join(ES)
    a, b = int(m.group(1)), int(m.group(2))
    out = ("TITLE: La pregunta\n" if "TITLE:" in user_prompt else "")
    if "translate it into" in user_prompt:
        return out + "\n\n".join(f"{n}. [SHOW: escena {n}]\n{ES[n % 4]} Pasaje {n}." for n in range(a, b + 1))
    return out + "\n".join(f"{n}. [SHOW: escena {n}]" for n in range(a, b + 1))


P._ask_model = fake_ask
P._write_checkpoint = lambda *a, **k: None
P._read_checkpoint = lambda tid: {}
P._checkpoint_sources = lambda state: []
P._publish_plan = lambda task_id, agent_name, title, script: len(P.scenes_of(script))


def run(options, text, feedback=None, checkpoint=None):
    calls.clear()
    st = {"agent": Agent(), "corpus": [{"title": "", "url": "", "content": text, "source": "pasted"}],
          "preset": {"name": "ink", "fields": {"language": "es"}}, "task_id": "", "checkpoint": checkpoint or {},
          "_say": lambda *a: None, "_cancelled": lambda: False, "warnings": [], "feedback": feedback or []}
    P._step_script(st, {"source_text": text, **options})
    return st


st = run({"script_mode": "verbatim"}, PASTE)
got = [n for _, n in P.scenes_of(st["script"]) if n]
ok(got == scenes, "lời đọc của từng cảnh = ĐÚNG các cảnh đã cắt (không qua model)", (len(got), len(scenes)))
ok(len(calls) == math.ceil(len(scenes) / P._VERBATIM_BATCH), f"model chỉ được hỏi tả hình theo đợt {P._VERBATIM_BATCH} cảnh", len(calls))
ok(all("word for word" in s and "describe what is on screen" in s for s, _, _ in calls)
   and "Do not repeat or rewrite the passage" in calls[0][1] and "translate" not in calls[0][1],
   "đề bài: lời cố định, chỉ tả hình, không dịch (cùng ngôn ngữ)", calls[0][1][:300])
ok(all(sh.startswith("escena ") for sh, _ in P.scenes_of(st["script"]) if sh), "dòng [SHOW] lấy từ model")
ok(st["title"] == "La pregunta" and st["words_from"] == "verbatim" and st["target_words"] == P.content_words(PASTE),
   "tiêu đề từ model; độ dài = chính bài, lý do 'verbatim'", (st["title"], st["words_from"], st["target_words"]))
ok(st["verbatim"] == {"scenes": len(scenes), "translated_from": ""} and not st["warnings"], "state.verbatim, không cảnh báo", (st.get("verbatim"), st["warnings"]))
card = P._plan_result(st, {}, [], [])
ok("**Script**: read word for word as pasted" in card and "the AI only wrote the visuals" in card and "read word for word as pasted)" in card,
   "thẻ kế hoạch nói rõ nguyên văn", [l for l in card.splitlines() if "Script" in l or "Scenes" in l])
ok("read word for word" in P.describe_plan({"source_text": PASTE, "script_mode": "verbatim", "preset": "ink"})
   and "read word for word" not in P.describe_plan({"source_text": PASTE, "preset": "ink"}), "mô tả task nói nguyên văn chỉ khi chọn")
st2 = run({}, PASTE)
ok(st2["words_from"] == "content" and any("Rewrite this content" in u or "Plan a" in u for _, u, _ in calls),
   "không chọn → viết lại như cũ", (st2["words_from"], len(calls)))
big = "\n".join(ES[i % 4] + f" Tema{i}." for i in range(1, 400))          # ~6000 chữ
st3 = run({"script_mode": "verbatim"}, big)
ok(st3["target_words"] == P.content_words(big) > P._WORDS_MAX and not any("condenses" in w for w in st3["warnings"]),
   "bài dài hơn 4000 chữ: nguyên văn KHÔNG kẹp trần, không cảnh báo rút gọn", (st3["target_words"], st3["warnings"]))

# ── D. góp ý khi duyệt: lời giữ nguyên, chỉ hình đổi ─────────────────────────
print("── D. góp ý → chỉ đổi hình ──────────────────────────────────")
prev = st["script"]
st4 = run({"script_mode": "verbatim"}, PASTE, feedback=["more close-ups"], checkpoint={"script": prev, "title": "La pregunta"})
ok([n for _, n in P.scenes_of(st4["script"]) if n] == got, "lời đọc y nguyên lượt trước")
ok(all("more close-ups" in u and "the narration is fixed" in u for _, u, _ in calls), "đề bài mang góp ý, nói rõ lời cố định")
ok(st4["title"] == "La pregunta" and not any("TITLE:" in u for _, u, _ in calls), "giữ tiêu đề cũ, không hỏi lại tiêu đề")

# ── E. khác ngôn ngữ: dịch sát từng câu ──────────────────────────────────────
print("── E. bài tiếng Việt + mẫu Tây Ban Nha → dịch sát ───────────")
VI = "\n".join(f"Có một câu hỏi có thể cho thấy cuộc đời bạn đang đi về đâu, và đó là chủ đề {i} của chúng ta hôm nay." for i in range(1, 31))
st5 = run({"script_mode": "verbatim"}, VI)
vi_scenes = P.verbatim_scenes(VI)
got5 = [n for _, n in P.scenes_of(st5["script"]) if n]
ok(len(got5) == len(vi_scenes) and all(n.startswith(("Hay una", "No es", "Lo que", "Por eso")) for n in got5),
   "số cảnh giữ nguyên, lời là bản dịch tiếng Tây Ban Nha", (len(got5), len(vi_scenes), got5[:1]))
ok(st5["verbatim"]["translated_from"] == "Vietnamese" and "translated sentence by sentence from Vietnamese" in P._plan_result(st5, {}, [], []),
   "ghi rõ đã dịch từ tiếng Việt", st5.get("verbatim"))
ok(all("translate it into Spanish faithfully" in u and "nothing added, nothing dropped" in u for _, u, _ in calls)
   and all("translate it faithfully" in s for s, _, _ in calls), "đề bài dịch: sát từng câu, không thêm bớt")
ok(not st5["warnings"], "bản dịch đúng ngôn ngữ → không cảnh báo", st5["warnings"])


def bad_ask(agent, system_prompt, user_prompt, budget_words):
    calls.append((system_prompt, user_prompt, budget_words))
    if "Passages" in user_prompt:
        return "Lo siento, no puedo."                       # không ra khuôn, cả khi hỏi lại
    m = re.search(r"in exactly (\d+) scenes", user_prompt)
    if "Plan a" in user_prompt and m:
        return "TITLE: Reescrito\n" + "\n".join(f"{i}. [SHOW: f{i}] — gist {i}" for i in range(1, int(m.group(1)) + 1))
    m = re.search(r"scenes (\d+)-(\d+) ONLY", user_prompt)
    if m:
        return "\n\n".join(f"[SHOW: f{i}]\n{ES[i % 4]} Reescrito {i}." for i in range(int(m.group(1)), int(m.group(2)) + 1))
    return "TITLE: Reescrito\n\n[SHOW: f]\n" + " ".join(ES) + " " + " ".join(ES)


P._ask_model = bad_ask
st6 = run({"script_mode": "verbatim"}, VI)
retries = [u for s, u, _ in calls if "previous answer was incomplete" in s]
ok(len(retries) == 1, "dịch thiếu → hỏi lại đúng MỘT lần", len(retries))
ok(any("could not translate the content sentence by sentence" in w for w in st6["warnings"]) and "Reescrito" in st6["script"],
   "vẫn thiếu → rơi về viết lại và cảnh báo rõ", (st6["warnings"], st6["script"][:80]))
P._ask_model = fake_ask
ok(P.DEFAULTS["script_mode"] == "rewrite" and P._LEN_FROM["verbatim"], "mặc định vẫn là viết lại")

# Kịch bản soạn thảo dán nguyên (25/9/2026): tiêu đề, mốc giờ, thông số in đậm, ghi chú sản xuất KHÔNG được đọc.
DRAFT = """# Bác sĩ cảnh báo: Người trên 60 nên tắm bao nhiêu lần một tuần?

**Thời lượng dự kiến: 22–26 phút (~4.200 từ) / kịch bản đọc**
**Giọng: bác sĩ điềm đạm, không nêu tên. Nhịp chậm.**

---

## [0:00 MỞ ĐẦU]

Cô chú thử hình dung.
Hiện giờ, cô chú có tắm **mỗi ngày** không?

## [22:00 SỰ THẬT 7 – VỆ SINH SAU 60]

**Năm vùng cần rửa mỗi ngày:** mặt; nách; bàn chân.
- Rửa tay trước khi ăn.

### Ghi chú sản xuất
- Giọng bác sĩ, **không nêu tên**.
- Mốc comment: "có/không" → "2".
"""
sp = P.spoken_text(DRAFT)
ok(sp == ("Cô chú thử hình dung.\nHiện giờ, cô chú có tắm mỗi ngày không?\n\n"
          "Năm vùng cần rửa mỗi ngày: mặt; nách; bàn chân.\nRửa tay trước khi ăn."),
   "kịch bản soạn thảo → chỉ còn lời đọc, giữ nguyên chữ", sp)
ok(P.spoken_text(VI) == VI, "bài không markdown giữ nguyên từng ký tự")
ok(" ".join(P.verbatim_scenes(P.spoken_text(DRAFT))).count("Thời lượng") == 0, "cảnh nguyên văn không còn thông số")

print()
print("=" * 62)
print(f"{PASS}/{PASS + FAIL} PASS" if not FAIL else f"{PASS}/{PASS + FAIL} PASS — {FAIL} HỎNG")
sys.exit(1 if FAIL else 0)
