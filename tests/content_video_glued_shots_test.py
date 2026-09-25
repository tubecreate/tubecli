# -*- coding: utf-8 -*-
"""Nhịp ÔM lời của nhiều cảnh → tách thành nhịp mới (25/9/2026, task #119 khi Chạy lại).

Bệnh: bản trước dồn lời các cảnh storyboard bỏ vào nhịp cuối cảnh trước (#19: 430 chữ = đuôi cảnh 6 + cảnh 7–12).
Đo độ phủ coi lời dồn là "đủ", nên Retry không sửa được — phải tách TRƯỚC khi đo. Cam kết:
  1. glued_scenes: nhận ra nhịp dài mà đuôi = nguyên văn chuỗi cảnh liên tiếp, so theo chữ trơn (bỏ [chỉ dẫn],
     dấu câu, hoa/thường); phần lời riêng giữ nguyên dấu câu; nhịp = đúng một cảnh hoặc nhịp ngắn → không tách.
  2. _split_glued_shots: chèn nhịp ≤ 26 chữ NGAY SAU nhịp ôm, rồi cắt lời nhịp cũ còn phần riêng (xoá giọng cũ);
     từ nhịp cuối về đầu; Studio cũ (404) → 0 và KHÔNG cắt lời.
  3. realign_to_captions: cửa sổ không lấn sang nhịp chưa có chữ bảng (nhịp vừa chèn giữ nguyên lời).
Mọi HTTP giả.
"""
import json
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


BANK = [a + b + c for a in "bdgklmnpstvx" for b in "aeiouy" for c in "mnt"]      # 216 chữ, mỗi câu 6 chữ riêng
_k = [0]


def sent(tag, n=6):
    i = _k[0]
    _k[0] += 1
    return f"{tag} {' '.join(BANK[i * 6:i * 6 + 6])} cần nhớ."


# Kịch bản 6 cảnh, cảnh 3 mở đầu bằng tiêu đề trong ngoặc vuông (như «[PHẦN 2 – NHỚ B.E. F.A.S.T.]» của #119).
S = [" ".join(sent(f"s{j}c{i}") for i in range(1, 4)) for j in range(6)]
S[3] = "[PHẦN 2 – NHỚ B.E. F.A.S.T.] " + S[3]
SCENES = [("", s) for s in S]
last_sentence_of_1 = S[1].split(". ")[-1]
own_part = "Câu riêng, có dấu phẩy; và dấu chấm hỏi? " + last_sentence_of_1
glued_text = own_part + " " + S[2] + " " + S[3] + " " + S[4]          # bản cũ dồn cảnh 2, 3, 4 vào đuôi nhịp
SHOTS = [{"id": 1, "storyboard_number": 1, "narration_text": S[0]},
         {"id": 2, "storyboard_number": 2, "narration_text": S[1].rsplit(". ", 1)[0] + "."},
         {"id": 3, "storyboard_number": 3, "narration_text": glued_text},
         {"id": 4, "storyboard_number": 4, "narration_text": S[5]}]

# 1. nhận diện
g = P.glued_scenes(SHOTS, SCENES)
ok(len(g) == 1 and g[0][0] == 2 and g[0][2] == [2, 3, 4], "nhịp 3 ôm cảnh 2, 3, 4 (0-based) dù cảnh 3 có [tiêu đề] và B.E. F.A.S.T.", g)
ok(g and g[0][1] == own_part, "lời riêng giữ nguyên dấu câu, cắt đúng trước cảnh dồn", g and g[0][1])
ok(P.glued_scenes([{"id": 9, "storyboard_number": 1, "narration_text": S[2] + " " + S[3]}], SCENES) == [(0, S[2], [3])],
   "nhịp = đúng hai cảnh trọn vẹn → cảnh sau tách ra, nhịp giữ cảnh đầu (mỗi cảnh một nhịp)")
ok(P.glued_scenes([{"id": 9, "storyboard_number": 1, "narration_text": "Ngắn. " + S[2]}], SCENES) == [],
   "nhịp ngắn (< 52 chữ) → không xét")
ok(P.glued_scenes([{"id": 9, "storyboard_number": 1, "narration_text": S[0]}], SCENES) == [], "nhịp = một cảnh → không tách")
ok(P.glued_scenes(SHOTS, []) == [] and P.glued_scenes([], SCENES) == [], "không cảnh / không nhịp → []")
ok(P._plain_words("[PHẦN 2 – NHỚ] B.E. F.A.S.T., xong.") == ["b", "e", "f", "a", "s", "t", "xong"], "chữ trơn bỏ ngoặc vuông và dấu câu")

# 2. tách
CALLS = []


def _post(path, payload, timeout=300):
    CALLS.append(("POST", path, payload))
    return {"success": True, "count": len(payload["shots"])}


def _put(path, payload, timeout=300):
    CALLS.append(("PUT", path, payload))
    return {"success": True}


P._post, P._put = _post, _put
st = {"_say": lambda *a, **k: None}
n = P._split_glued_shots(9, st, SHOTS, SCENES, g)
posts = [c for c in CALLS if c[0] == "POST"]
puts = [c for c in CALLS if c[0] == "PUT"]
ok(n == 6 and len(posts) == 1 and posts[0][2]["after_number"] == 3, "chèn 6 nhịp (3 cảnh × 27 chữ → 18 + 9 mỗi cảnh) ngay sau nhịp 3", (n, posts and posts[0][2]["after_number"]))
beats = posts[0][2]["shots"] if posts else []
ok(all(P.content_words(b["narration_text"]) <= 26 for b in beats)
   and " ".join(b["narration_text"] for b in beats).split() == " ".join(S[2:5]).split(),
   "nhịp chèn ≤ 26 chữ, ghép lại = nguyên văn cảnh 2–4 (giữ cả [tiêu đề])", [b["narration_text"][:30] for b in beats])
ok(len(puts) == 1 and puts[0][1].endswith("/storyboards/3") and puts[0][2] == {"narration_text": own_part, "tts_audio_url": ""},
   "nhịp cũ cắt còn lời riêng + xoá giọng cũ", puts)
ok(CALLS.index(posts[0]) < CALLS.index(puts[0]), "chèn trước, cắt sau (Studio cũ thì không cắt)")

# nhiều nhịp ôm: xử lý từ cuối về đầu
CALLS.clear()
S2 = [("", sent(f"t{j}a") + " " + sent(f"t{j}b")) for j in range(8)]          # 8 cảnh × 18 chữ
SH2 = [{"id": 1, "storyboard_number": 1, "narration_text": S2[0][1]},
       {"id": 2, "storyboard_number": 2, "narration_text": "Riêng a. " + " ".join(S2[j][1] for j in (1, 2, 3, 4))},
       {"id": 3, "storyboard_number": 3, "narration_text": "Riêng b. " + " ".join(S2[j][1] for j in (5, 6, 7))}]
g2 = P.glued_scenes(SH2, S2)
ok([x[0] for x in g2] == [1, 2] and [x[2] for x in g2] == [[1, 2, 3, 4], [5, 6, 7]] and [x[1] for x in g2] == ["Riêng a.", "Riêng b."],
   "hai nhịp ôm, đúng chuỗi cảnh và lời riêng", g2)
P._split_glued_shots(9, st, SH2, S2, g2)
order = [(c[0], c[2].get("after_number")) for c in CALLS if c[0] == "POST"]
ok(order == [("POST", 3), ("POST", 2)], "chèn nhịp cuối trước (sau nhịp 3), rồi nhịp 2 — số nhịp trước không đổi", order)

# 3. Studio cũ
CALLS.clear()


def _404(path, payload, timeout=300):
    raise RuntimeError(path + " → HTTP 404: Not Found")


P._post = _404
ok(P._split_glued_shots(9, st, SHOTS, SCENES, g) == 0 and not CALLS, "Studio cũ (404) → 0, không cắt lời", CALLS)

# 4. realign không lấn sang nhịp chưa có chữ bảng
def capped(i, text, head):
    return {"id": i, "storyboard_number": i, "narration_text": text, "metadata": json.dumps({"scene": {"type": "board", "head": head, "hot": ""}})}


plain = {"id": 2, "storyboard_number": 2, "narration_text": "Huyết áp cao là kẻ thù thầm lặng của mạch máu.", "metadata": "{}"}
a = capped(1, "Câu đầu về não bộ. Câu hai về tế bào.", "Câu đầu não bộ")
b = capped(3, "Câu ba nói về giấc ngủ.", "huyết áp mạch máu")      # chữ bảng của nhịp 3 khớp lời nhịp chèn hơn lời riêng
ok(P._dice(P._cap_words(b), plain["narration_text"]) > P._dice(P._cap_words(b), b["narration_text"]) + P._REALIGN_MARGIN,
   "tiền đề: nhịp 3 bị nghi lệch vì chữ bảng khớp nhịp chèn")
moved = dict(P.realign_to_captions([a, plain, b]))
ok(plain["id"] not in moved and not moved, "nhịp không chữ bảng nằm ngoài cửa sổ gióng lại — không nhịp nào bị dồn lời", moved)

print()
print("=" * 62)
print(f"{PASS}/{PASS + FAIL} PASS" if not FAIL else f"{PASS}/{PASS + FAIL} PASS — {FAIL} HỎNG")
sys.exit(1 if FAIL else 0)
