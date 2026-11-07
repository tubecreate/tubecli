# -*- coding: utf-8 -*-
"""Bài dán dạng PHỤ ĐỀ (.srt / .vtt) → chỉ còn lời đọc (7/11/2026).

  A. .srt tiếng Trung: bỏ số thứ tự + mốc thời gian; khoảng trắng gỡ băng → «，»; lặng ≥ 0,6 s → xuống đoạn
  B. .vtt tiếng Anh: bỏ WEBVTT, NOTE, thẻ <i>; câu nối bằng dấu cách
  C. bài thường (có một dòng «-->» lẻ) → trả NGUYÊN
  D. chế độ nguyên văn cắt cảnh từ lời đã làm sạch: không cảnh nào còn mốc thời gian

Run:  python tests/subtitle_paste_test.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from tubecli.extensions.content_video import pipeline as P  # noqa: E402

PASS = FAIL = 0


def check(label, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + bool(ok), FAIL + (not ok)
    print(("[PASS] " if ok else "[FAIL] ") + label + ("" if ok else f"  → {detail}"))


SRT = """1
00:00:00,000 --> 00:00:03,520
大家都知道 深藍帶本營就是大安宇文山區沈碧洋

2
00:00:03,520 --> 00:00:05,800
少爺 車隊才剛轉進入口

3
00:00:05,800 --> 00:00:07,840
街頭卻港縣母子勁的人潮

14
00:00:30,140 --> 00:00:33,000
一場發生在對手眼中 鐵票倉的選舉

15
00:00:33,000 --> 00:00:35,620
到底為什麼會掀起如此驚人的風暴

16
00:00:36,660 --> 00:00:38,840
大家都知道 大安 文山這一帶

101
00:04:03,580 --> 00:04:05,040
難道只剩下每週給小孩發一瓶鮮奶嗎?
"""
out = P.subtitle_to_text(SRT)
check("A1 không còn mốc thời gian / số thứ tự", "-->" not in out and "00:00" not in out
      and not any(l.strip().isdigit() for l in out.splitlines()), out)
paras = out.split("\n\n")
check("A2 lặng (07,84 → 30,14 · 35,62 → 36,66 · 38,84 → 4:03) → 4 đoạn; liền mạch thì cùng đoạn", len(paras) == 4, paras)
check("A3 khoảng trắng gỡ băng → «，», hết đoạn → «。»",
      paras[0].startswith("大家都知道，深藍帶本營就是大安宇文山區沈碧洋，少爺，車隊才剛轉進入口") and paras[0].endswith("。"),
      paras[0])
check("A4 câu đã có dấu hỏi thì không thêm «。»", paras[3].endswith("嗎?") and paras[2].endswith("帶。"), paras)
check("A5 giữ nguyên chữ (không mất / thêm chữ Hán)",
      "".join(c for c in out if "一" <= c <= "鿿")
      == "".join(c for l in SRT.splitlines() if "-->" not in l for c in l if "一" <= c <= "鿿"))

VTT = """WEBVTT

NOTE made by a transcriber

00:01.000 --> 00:03.000
<i>Hello there,</i>

00:03.000 --> 00:05.000
this is a test.

00:06.500 --> 00:08.000
New paragraph here
"""
out = P.subtitle_to_text(VTT)
check("B1 .vtt: bỏ WEBVTT / NOTE / thẻ, nối dấu cách, xuống đoạn chỗ lặng",
      out == "Hello there, this is a test.\n\nNew paragraph here", repr(out))

PLAIN = "Một bài viết bình thường.\nCó mũi tên a --> b ở đây.\n\nĐoạn hai."
check("C1 bài thường → nguyên vẹn", P.subtitle_to_text(PLAIN) == PLAIN)
check("C2 rỗng / None an toàn", P.subtitle_to_text("") == "" and P.subtitle_to_text(None) is None)

scenes = P.verbatim_scenes(P.spoken_text(P.subtitle_to_text(SRT)))
check("D1 cảnh nguyên văn không còn mốc thời gian", scenes and not any("-->" in s or "00:0" in s for s in scenes), scenes)

print(f"\n{PASS}/{PASS + FAIL} PASS")
sys.exit(1 if FAIL else 0)
