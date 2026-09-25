# -*- coding: utf-8 -*-
"""Storyboard bỏ sót cảnh → CHÈN nhịp mới đúng chỗ (25/9/2026, task #119).

Bệnh: storyboard rơi 6 cảnh liên tiếp (7–12); restore_narration nối lời của chúng vào nhịp cuối cảnh 6 → một nhịp
430 chữ, giọng đọc 2 phút trên một khung chữ đứng yên. Cam kết:
  1. _insert_beats: nhịp ≤ 26 chữ, không cắt giữa câu, ghép lại đúng từng chữ.
  2. _insert_missing_scene_shots: mỗi cụm cảnh rơi → một lượt chèn NGAY SAU nhịp cuối của cảnh liền trước còn shot;
     cụm rơi ở đầu tập → chèn trước nhịp đầu của cảnh sau; chèn từ cụm cuối về đầu; `missing` lấy đúng từ
     missing_scenes như trong _step_studio.
  3. Studio cũ (route 404) → 0, không ném lỗi — lõi rơi về chia khối.
  4. restore_narration (đường rơi về): cảnh rơi chia đều cho KHỐI shot lân cận, không khối nào nặng gấp 2,5 lần
     trung bình; tổng chữ giữ nguyên, thứ tự giữ nguyên.
Mọi HTTP giả.
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


# Mỗi câu một bộ từ RIÊNG, không câu nào dùng lại chữ của câu khác: gióng shot↔cảnh không mơ hồ và mọi chữ đều là
# chữ đặc trưng của cảnh (scene_coverage chỉ xét cảnh có ≥ 6 chữ đặc trưng; chữ có số như "a1" bị _tokens bỏ).
BANK = [a + b + c for a in "bdgklmnpst" for b in "aeiou" for c in "mnt"]
_k = [0]


def sent(tag):
    i = _k[0]
    _k[0] += 1
    return f"{tag} {' '.join(BANK[i * 6:i * 6 + 6])} cần nhớ."


def scene(tag, n):
    return " ".join(sent(f"{tag}{i}") for i in range(1, n + 1))


# Kịch bản 8 cảnh; storyboard chỉ có shot cho cảnh 1, 2, 6, 7 (cảnh 0 rơi ở đầu, 3–5 rơi giữa).
SCENES = [("", scene("a", 1)), ("", scene("b", 2)), ("", scene("c", 2)), ("", scene("d", 3)), ("", scene("e", 3)),
          ("", scene("f", 2)), ("", scene("g", 2)), ("", scene("h", 1))]
SCRIPT = "\n".join(f"[SHOW: hình {i}]\n{n}" for i, (_, n) in enumerate(SCENES))
SHOTS = [{"id": 11, "storyboard_number": 1, "narration_text": SCENES[1][1]},
         {"id": 12, "storyboard_number": 2, "narration_text": SCENES[2][1]},
         {"id": 16, "storyboard_number": 3, "narration_text": SCENES[6][1]},
         {"id": 17, "storyboard_number": 4, "narration_text": SCENES[7][1]}]

# 1. cắt nhịp
beats = P._insert_beats(SCENES[3][1])
ok(len(beats) == 2 and all(P.content_words(b) <= 26 for b in beats) and " ".join(beats).split() == SCENES[3][1].split(),
   "3 câu × 12 chữ → 2 nhịp ≤ 26 chữ, không cắt giữa câu, ghép lại đúng chữ", beats)
long = " ".join(["chữ"] * 60)
ok(all(P.content_words(b) <= 26 for b in P._insert_beats(long)) and " ".join(P._insert_beats(long)).split() == long.split(),
   "câu 60 chữ không dấu chấm → cắt theo khoảng trắng, không nhịp nào > 26")
ok(P._insert_beats("") == [] and P._insert_beats("   \n ") == [], "lời trống → không nhịp")

# 2. chèn đúng chỗ
missing = P.missing_scenes(SHOTS, SCRIPT)
ok(missing == [0, 3, 4, 5], "missing_scenes thấy đúng cảnh 0, 3, 4, 5", missing)
POSTS = []
P._post = lambda path, payload, timeout=300: POSTS.append((path, payload)) or {"success": True, "count": len(payload["shots"])}
st = {"_say": lambda *a, **k: None}
added = P._insert_missing_scene_shots(9, st, SHOTS, SCENES, missing)
ok(added == 1 + 2 + 2 + 1, "chèn đủ nhịp: cảnh 0 (1 câu) → 1; cảnh 3, 4 (3 câu) → 2 mỗi cảnh; cảnh 5 (2 câu) → 1", added)
ok([p[1]["after_number"] for p in POSTS] == [2, 0], "cụm 3–5 chèn sau nhịp 2 (cảnh 2); cụm đầu chèn trước nhịp 1; cụm cuối trước",
   [p[1]["after_number"] for p in POSTS])
ok(all(p[0] == "/api/v1/studio/episodes/9/storyboards/insert" for p in POSTS), "đúng route")
first = POSTS[0][1]["shots"]
ok(first[0]["narration_text"].startswith("d1") and first[-1]["narration_text"].startswith("f1")
   and " ".join(b["narration_text"] for b in first).split() == " ".join(SCENES[j][1] for j in (3, 4, 5)).split(),
   "nhịp chèn đúng thứ tự và đủ từng chữ của cảnh 3–5", [b["narration_text"][:14] for b in first])
ok(all(b["title"] == "" and b["image_prompt"] == "" and b["description"] for b in first), "nhịp chèn: title/prompt trống, description có")
ok(st.get("storyboard_inserted") is None, "hàm không tự ghi state (bên gọi ghi)")

# 3. Studio cũ


def _404(path, payload, timeout=300):
    raise RuntimeError(path + " → HTTP 404: Not Found")


P._post = _404
ok(P._insert_missing_scene_shots(9, st, SHOTS, SCENES, missing) == 0, "Studio cũ (404) → 0, không ném lỗi")


def _500(path, payload, timeout=300):
    raise RuntimeError(path + " → HTTP 500: boom")


P._post = _500
try:
    P._insert_missing_scene_shots(9, st, SHOTS, SCENES, missing)
    ok(False, "lỗi khác 404 phải ném ra")
except RuntimeError as e:
    ok("500" in str(e), "lỗi khác 404 ném ra (không nuốt)")
ok(P._insert_missing_scene_shots(9, st, SHOTS, SCENES, []) == 0 and P._insert_missing_scene_shots(9, st, [], SCENES, missing) == 0,
   "không cảnh rơi / không shot → 0, không gọi mạng")

# 4. đường rơi về: chia khối
fixed = dict(P.restore_narration(SHOTS, SCRIPT))
words = {sid: len(t.split()) for sid, t in fixed.items()}
total = sum(len(n.split()) for _, n in SCENES)
ok(sum(words.values()) == total, "tổng chữ giữ nguyên", (sum(words.values()), total))
ok(max(words.values()) <= 2.5 * total / len(SHOTS) + 8, "không nhịp nào ôm quá 2,5 lần trung bình (dung sai một câu)", words)
ok(fixed[11].startswith("a1") and "h1" in fixed[17], "cảnh rơi ở đầu vào nhịp đầu; cảnh cuối vẫn ở nhịp cuối", (fixed[11][:20], fixed[17][-40:]))
joined = " ".join(fixed[s["id"]] for s in SHOTS).split()
ok(joined == " ".join(n for _, n in SCENES).split(), "ghép lại đúng từng chữ kịch bản theo thứ tự")

print()
print("=" * 62)
print(f"{PASS}/{PASS + FAIL} PASS" if not FAIL else f"{PASS}/{PASS + FAIL} PASS — {FAIL} HỎNG")
sys.exit(1 if FAIL else 0)
