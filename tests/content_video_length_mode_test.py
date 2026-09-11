# -*- coding: utf-8 -*-
"""Độ dài video theo NỘI DUNG DÁN (11/9/2026).

Bệnh: dán 300 hay 3000 chữ cũng ra ~13 cảnh / 14 shot — độ dài lấy từ ô Video
Length của MẪU (Standard = 800 chữ), nên bài dài bị nén còn một phần ba, bài
ngắn bị kéo dài. Cam kết được canh ở đây:
  1. Có nội dung dán → mặc định độ dài = độ dài bài dán (kẹp 120..4000 chữ).
  2. length_mode="template" → mẫu quyết như cũ; target_words (tự chọn phút) thắng tất.
  3. Đếm chữ đúng cả với tiếng Trung/Nhật/Thái — codex.js (cvWords) cho CÙNG con số
     trên CÙNG bộ mẫu (tests/codex_video_length_test.js).
  4. Bài vượt trần → cảnh báo nói rõ là sẽ rút gọn, và KHÔNG hứa "giữ đủ".
  5. Đề bài nói "giữ đủ, đúng thứ tự — viết lại chứ không tóm tắt", cả khi viết theo đợt.
"""
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
        print("  FAIL", label, "—", detail)


# CÙNG bộ mẫu với tests/codex_video_length_test.js — sửa một bên phải sửa bên kia.
SAMPLES = [
    ("Hola mundo, esto es una prueba.", 6),
    ("Xin chào — thế giới !", 4),
    ("你好世界，这是测试。", 4),
    ("日本語のテキストです", 5),
    ("สวัสดีครับ", 2),
    ("AI 你好 test", 3),
    ("", 0),
]


def words(n):
    return " ".join(f"w{i}" for i in range(n))


STD = {"name": "nguoi que", "fields": {"language": "es", "metadata": {"video_length": "standard"}}}

print("── đếm chữ ───────────────────────────────────────────────────")
for text, want in SAMPLES:
    ok(P.content_words(text) == want, f"content_words({text!r}) = {want}", P.content_words(text))
ok(P.content_words(words(2943)) == 2943, "bài 2943 chữ Latin → 2943")

print("── resolve_words ─────────────────────────────────────────────")
ok(P.resolve_words({"source_text": words(2943)}, STD) == (2943, "content"),
   "dán 2943 chữ + mẫu Standard → 2943 chữ, lý do 'content' (bệnh cũ: 800)",
   P.resolve_words({"source_text": words(2943)}, STD))
ok(P.resolve_words({"source_text": words(300)}, STD) == (300, "content"),
   "dán 300 chữ → 300, không bị kéo lên 800")
ok(P.resolve_words({"source_text": words(2943), "length_mode": "template"}, STD) == (800, "template"),
   "chọn 'theo mẫu' → Standard 800 như cũ")
ok(P.resolve_words({"source_text": words(300), "length_mode": "TEMPLATE"}, STD)[1] == "template",
   "length_mode không phân biệt hoa thường")
ok(P.resolve_words({"source_text": words(2943), "length_mode": "minutes", "target_words": 1500}, STD)
   == (1500, "asked for"), "tự chọn phút (target_words) thắng cả bài dán")
ok(P.resolve_words({"source_text": words(50)}, STD) == (120, "content"), "bài quá ngắn → kẹp 120 chữ")
ok(P.resolve_words({"source_text": words(6000)}, STD) == (4000, "content"), "bài quá dài → kẹp 4000 chữ")
ok(P.resolve_words({"source_text": "   "}, STD) == (800, "template"), "nội dung toàn khoảng trắng → như không dán")
ok(P.resolve_words({}, STD) == (800, "template") and P.resolve_words({}, None) == (260, "default"),
   "không dán → đường cũ y nguyên (mẫu → mặc định)")
ok(P.resolve_words({"source_text": "你好世界" * 400}, None) == (800, "content"),
   "1600 chữ Hán → ~800 chữ đọc (split() cũ đếm ra 1)")

print("── số cảnh ───────────────────────────────────────────────────")
ok(P.scene_budget(800) == (13, 3, 5), "Standard giữ nguyên 13 cảnh", P.scene_budget(800))
ok(P.scene_budget(2943)[0] == 49, "2943 chữ → 49 cảnh (~60 chữ/cảnh), không kẹt ở 26", P.scene_budget(2943))
ok(P.scene_budget(4000)[0] == 60, "4000 chữ → trần 60 cảnh", P.scene_budget(4000))
ok(P.scene_budget(100)[0] == 6, "sàn 6 cảnh giữ nguyên")

print("── bước viết kịch bản ────────────────────────────────────────")
prompts = []


def fake_ask(agent, system_prompt, user_prompt, budget_words):
    prompts.append(user_prompt)
    m = re.search(r"in exactly (\d+) scenes", user_prompt)
    if user_prompt.count("Plan a") and m:
        n = int(m.group(1))
        return "TITLE: Largo\n" + "\n".join(f"{i}. [SHOW: frame {i}] — gist {i}" for i in range(1, n + 1))
    m = re.search(r"scenes (\d+)-(\d+) ONLY", user_prompt)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        return "\n\n".join(f"[SHOW: frame {i}]\n" + " ".join([f"s{i}"] * 60) + "." for i in range(a, b + 1))
    return "TITLE: Corto\n\n[SHOW: uno]\nUno dos tres."


class Agent:
    name, language, id = "MC", "auto", "a1"


P._ask_model = fake_ask
P._write_checkpoint = lambda *a, **k: None
P._checkpoint_sources = lambda state: []
P._publish_plan = lambda task_id, agent_name, title, script: len(P.scenes_of(script))
P.resolve_language = lambda *a, **k: ("es", "preset")
P.detect_language = lambda text: ""


def run(options, text, preset=STD):
    prompts.clear()
    st = {"agent": Agent(), "corpus": [{"title": "", "url": "", "content": text, "source": "pasted"}],
          "preset": preset, "task_id": "t", "checkpoint": {}, "_say": lambda *a: None,
          "_cancelled": lambda: False, "warnings": [], "feedback": []}
    P._step_script(st, options)
    return st


short = words(300)
st = run({"source_text": short}, short)
ok(st["target_words"] == 300 and st["words_from"] == "content", "dán 300 chữ → kịch bản 300 chữ", st["target_words"])
ok(len(prompts) == 1 and "about 300 words" in prompts[0], "một lượt, đề bài 'about 300 words'")
ok("Keep all of it" in prompts[0] and "not a summary" in prompts[0], "đề bài nói giữ đủ, không tóm tắt")
ok("matches the pasted content" in P._plan_result(st, {}, [], []), "bản kế hoạch nói độ dài theo bài dán")

long_text = words(2943)
st = run({"source_text": long_text}, long_text)
ok(st["target_words"] == 2943 and st["words_from"] == "content", "dán 2943 chữ → kịch bản 2943 chữ")
ok("about 2943 words" in prompts[0] and "exactly 49 scenes" in prompts[0], "dàn ý: 2943 chữ, 49 cảnh", prompts[0][-400:])
ok("Cover ALL of the content" in prompts[0], "dàn ý nói phủ HẾT bài, theo thứ tự")
ok(len(prompts) == 1 + 9, "viết theo đợt: dàn ý + 9 đợt ≤6 cảnh", len(prompts))
ok(st["scene_count"] == 49, "49 cảnh vào kịch bản (bệnh cũ: ~13)", st.get("scene_count"))

st = run({"source_text": short, "length_mode": "template"}, short)
ok(st["target_words"] == 800 and st["words_from"] == "template", "chọn 'theo mẫu' → 800 chữ như cũ")
ok("about 800 words" in prompts[0] and "Keep all of it" not in prompts[0], "…và không hứa giữ đủ")

st = run({"source_text": short, "length_mode": "minutes", "target_words": 1500}, short)
ok(st["target_words"] == 1500 and st["words_from"] == "asked for", "tự chọn 10 phút → 1500 chữ")
ok("exactly 25 scenes" in prompts[0] and "Cover ALL" not in prompts[0], "…25 cảnh, không hứa giữ đủ")

huge = words(6000)
st = run({"source_text": huge}, huge)
ok(st["target_words"] == 4000, "6000 chữ → kẹp 4000")
ok(any("The pasted content is ~6,000 words" in w and "Split it" in w for w in st["warnings"]),
   "…và NÓI RA là sẽ rút gọn", st["warnings"])
ok("Cover ALL" not in prompts[0] and "exactly 60 scenes" in prompts[0], "vượt trần → không hứa giữ đủ; 60 cảnh")

st = run({}, short)
ok(st["target_words"] == 300 and st["words_from"] == "content",
   "options không mang source_text (chỉ có corpus dán) → vẫn đo trên bài dán")

zh = "你好世界" * 400
st = run({"source_text": zh}, zh, preset=None)
ok(st["target_words"] == 800, "bài tiếng Trung 1600 ký tự → ~800 chữ đọc", st["target_words"])

ok("~800 words" in P.describe_plan({"source_text": zh}), "mô tả task đếm chữ Hán đúng",
   [l for l in P.describe_plan({"source_text": zh}).splitlines() if "Source" in l])

print()
print("=" * 62)
print(f"{PASS}/{PASS + FAIL} PASS" if not FAIL else f"{PASS}/{PASS + FAIL} PASS — {FAIL} HỎNG")
sys.exit(1 if FAIL else 0)
