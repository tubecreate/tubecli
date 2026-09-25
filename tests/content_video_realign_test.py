# -*- coding: utf-8 -*-
"""Gióng lời đọc theo CHỮ TRÊN BẢNG (25/9/2026) — realign_to_captions.

Bệnh (task #115, máy local): Studio cắt một câu dài của kịch bản thành HAI nhịp (mỗi nửa một chữ trên bảng);
restore_narration chia lời theo CÂU nên gán nguyên câu cho một nhịp ⇒ cả cụm đọc sớm hơn chữ một câu, nhịp cuối cụm
lời rỗng (im 5 giây). 3 cụm như vậy trong một video 168 nhịp. Cam kết:
  1. Cụm lệch được chia lại: mỗi nhịp đọc đúng câu/nửa câu mà chữ của nó nói; hết nhịp rỗng.
  2. Ghép lời cả tập vẫn đúng từng chữ như cũ (không thêm, không bớt).
  3. Tập không lệch → không đổi gì (đo trên 3 tập thật: 0 thay đổi).
  4. Tiếng Nhật (không dấu cách giữa câu) không bị chèn dấu cách khi ghép.
  5. Không có chữ trên bảng (dự án không dựng canvas) → không đụng.
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


def shot(n, narration, head, kind="board"):
    return {"id": 1000 + n, "storyboard_number": n, "narration_text": narration,
            "metadata": json.dumps({"scene": {"type": kind, "head": head, "hot": ""}})}


# Đúng hình dạng cụm 66–69 của #115: câu 66 dài bị Studio cắt làm hai nhịp (66, 67), lời lệch một nhịp, 69 rỗng.
DRIFT = [
    shot(65, "Đáng sợ nhất là người bệnh vẫn đang chìm sâu trong giấc ngủ.",
         "Đáng sợ nhất là người bệnh vẫn chìm sâu trong giấc ngủ"),
    shot(66, "Vì vậy, giải pháp bảo vệ nhịp đập con tim tối nay là cực kỳ dứt khoát: hãy đặt điểm dừng cho cồn "
             "trước giờ ngủ ít nhất năm tiếng.",
         "Vì vậy, giải pháp bảo vệ nhịp đập con tim tối nay là cực kỳ dứt khoát"),
    shot(67, "Quý vị có thể thay thế ly rượu muộn bằng một tách trà hoa cúc ấm vào đầu giờ tối.",
         "Hãy đặt điểm dừng cho cồn trước giờ ngủ ít nhất năm tiếng."),
    shot(68, "Thói quen nhỏ này giúp làm dịu hệ thần kinh một cách hoàn toàn tự nhiên.",
         "Có thể thay thế ly rượu muộn bằng một tách trà hoa cúc ấm"),
    shot(69, "", "Thói quen nhỏ này giúp làm dịu hệ thần kinh một cách hoàn toàn tự nhiên"),
    shot(70, "Nguy cơ thứ hai lại ẩn nấp ngay trong ngăn kéo đầu giường.",
         "Nguy cơ thứ hai ẩn nấp ngay trong ngăn kéo đầu giường"),
]
fx = dict(P.realign_to_captions(DRIFT))
new = {s["id"]: fx.get(s["id"], s["narration_text"]) for s in DRIFT}
ok(new[1066].endswith("dứt khoát:") and new[1067].startswith("hãy đặt điểm dừng"),
   "câu dài Studio cắt làm hai nhịp → lời cắt đúng chỗ ấy", (new[1066][-30:], new[1067][:30]))
ok(new[1068].startswith("Quý vị có thể thay thế") and new[1069].startswith("Thói quen nhỏ này"),
   "các nhịp sau đọc đúng câu của chữ mình, hết nhịp rỗng", (new[1068][:30], new[1069][:30]))
ok(1065 not in fx and 1070 not in fx, "nhịp đúng ở hai đầu cụm không bị đụng", sorted(fx))
old_words = " ".join(s["narration_text"] for s in DRIFT).split()
new_words = " ".join(new[s["id"]] for s in DRIFT).split()
ok(old_words == new_words, "ghép lời cả cụm đúng từng chữ như cũ")

# 3: tập không lệch → không đổi gì.
GOOD = [shot(i, f"Câu số {i} nói về giấc ngủ của người lớn tuổi.", f"Câu số {i} về giấc ngủ người lớn tuổi")
        for i in range(1, 9)]
ok(P.realign_to_captions(GOOD) == [], "không lệch → không đổi gì")

# 5: không có chữ trên bảng → không đụng (kể cả nhịp rỗng).
PLAIN = [{"id": i, "storyboard_number": i, "narration_text": "" if i == 2 else f"Câu {i}.", "metadata": "{}"}
         for i in range(1, 4)]
ok(P.realign_to_captions(PLAIN) == [], "dự án không có chữ trên bảng → không đụng")

# 4: tiếng Nhật — không dấu cách giữa câu; ghép lại không được chèn dấu cách.
JA = [
    shot(1, "夜のお茶は体を温めます。", "夜のお茶は体を温める"),
    shot(2, "しかし、カフェインは眠りを浅くします。寝る前のスマホも同じです。", "カフェインは眠りを浅くする"),
    shot(3, "", "寝る前のスマホも同じ"),
]
fj = dict(P.realign_to_captions(JA))
ok(fj.get(1002) == "しかし、カフェインは眠りを浅くします。" and fj.get(1003) == "寝る前のスマホも同じです。",
   "tiếng Nhật: tách đúng câu, không chèn dấu cách", fj)

print()
print("=" * 62)
print(f"{PASS}/{PASS + FAIL} PASS" if not FAIL else f"{PASS}/{PASS + FAIL} PASS — {FAIL} HỎNG")
sys.exit(1 if FAIL else 0)
