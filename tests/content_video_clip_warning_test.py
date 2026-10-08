# -*- coding: utf-8 -*-
"""Bước «images» NÓI RA khi lô clip Muse dừng giữa chừng / nhiều cảnh giữ ảnh tĩnh (8/10/2026).

#306 báo ✅ «31 shots · video 06:41» mà chỉ 4/30 cảnh có clip Muse (trình duyệt treo ở cảnh 6) — user: «chỉ hook đầu
video còn đâu toàn ảnh fade zoom». _clip_warnings(data) đọc `shot_videos` Studio ghi vào lượt vẽ. Không HTTP.

Run:  python tests/content_video_clip_warning_test.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from tubecli.extensions.content_video import pipeline as P      # noqa: E402

PASS = FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", label)
    else:
        FAIL += 1
        print("  FAIL", label, "—", str(detail)[:300])


ok(P._clip_warnings({}) == [] and P._clip_warnings({"errors": []}) == [], "tập không làm clip → không cảnh báo")
ok(P._clip_warnings({"shot_videos": {"picked": 10, "made": 10, "failed": 0}}) == [], "đủ clip → không cảnh báo")
w = P._clip_warnings({"shot_videos": {"picked": 30, "made": 4, "failed": 1,
                                      "errors": [{"shot_id": 18833, "error": "cannot attach to the browser on CDP port 52056"}],
                                      "stopped": "Muse is not usable (browser) — the remaining shots keep their still image"}})
ok(len(w) == 1 and "4/30" in w[0] and "browser" in w[0] and "shot-videos" in w[0],
   "lô dừng → «Only 4/30 scenes got a Muse clip … (browser)» + chỉ cách làm bù", w)
w2 = P._clip_warnings({"shot_videos": {"picked": 28, "made": 14, "failed": 5,
                                       "errors": [{"shot_id": 18751, "error": "Muse did not make a video: I couldn't generate that video."}]}})
ok(len(w2) == 1 and "14/28" in w2[0] and "scene 18751" in w2[0], "không dừng nhưng thiếu nhiều → nêu ví dụ cảnh hỏng", w2)
ok(P._clip_warnings({"shot_videos": {"error": "boom"}}) == ["Scene clips were not made: boom"], "lỗi cả lô → một dòng")
ok(P._clip_warnings({"shot_videos": {"picked": 0, "made": 0}}) == [], "không cảnh nào được chọn → im")

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
