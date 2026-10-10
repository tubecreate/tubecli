# -*- coding: utf-8 -*-
"""Thanh tiến độ cho pha SAU khi đủ ảnh (8/10/2026 — user xem #302 đứng «29/29 · about 20s left» hàng chục phút:
«chỗ này chưa có pipeline bar không biết đang làm gì»). _poll_studio đọc `phase`/`phase_done`/`phase_total`/`phase_note`
của Studio → báo «shot videos 3/29 · scene 5: Muse is filming the clip» + % theo clip. Không HTTP thật (_get giả).

Run:  python tests/content_video_phase_progress_test.py
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


seq = [
    {"status": "running", "done": 28, "total": 29},
    {"status": "running", "done": 29, "total": 29},
    {"status": "making the opening video", "done": 29, "total": 29, "phase": "opening video", "phase_done": 0, "phase_total": 1,
     "phase_note": "director board + Muse clip of scene 1"},
    {"status": "making shot videos 1/28", "done": 29, "total": 29, "phase": "shot videos", "phase_done": 0, "phase_total": 28,
     "phase_note": "scene 2: drawing the director board"},
    {"status": "making shot videos 3/28", "done": 29, "total": 29, "phase": "shot videos", "phase_done": 2, "phase_total": 28,
     "phase_note": "scene 4: Muse is filming the clip"},
    {"status": "completed", "done": 29, "total": 29, "phase": "shot videos", "phase_done": 28, "phase_total": 28,
     "phase_note": "25 clip(s) made, 3 kept as stills"},
]
calls = []
P._get = lambda path, timeout=30: seq.pop(0)
P.POLL_SEC = 0
said = []
state = {"_cancelled": lambda: False, "_say": lambda step, st, msg="", pct=None: said.append((step, msg, pct))}
out = P._poll_studio("/api/v1/studio/gen-images/status/x", 60, state, "images", done_statuses=("completed",))
msgs = [m for _, m, _ in said]
ok(out["status"] == "completed", "xong như cũ")
ok("28/29" in msgs and "29/29" in msgs, "pha vẽ ảnh vẫn báo done/total", msgs)
ok("opening video 0/1 · director board + Muse clip of scene 1" in msgs
   and "shot videos 2/28 · scene 4: Muse is filming the clip" in msgs, "pha clip báo rõ đang làm gì, cảnh nào", msgs)
pcts = [p for _, m, p in said if m.startswith("shot videos")]
ok(pcts and pcts[1] == int(2 * 100 / 28) and max(pcts) <= 99, "% theo số clip, không chạm 100 trước khi xong", pcts)


# Pha clip đứng yên lâu hơn timeout_sec (một cảnh kẹt: lõi chờ 15 phút rồi đóng phiên thử lại) KHÔNG bị cắt — #332
# 10/10/2026 hỏng «No progress for 1800s» khi lô clip còn chạy. Pha vẽ ảnh vẫn cắt ở timeout_sec. Đồng hồ giả, mỗi lượt
# hỏi = 10 phút.
class _Clock:
    t = 0.0

    def time(self):
        return self.t

    def sleep(self, s):
        self.t += 600


real_time = P.time
P.time = _Clock()
P.POLL_SEC = 1
clip = {"status": "making shot videos 11/16", "done": 17, "total": 17, "phase": "shot videos", "phase_done": 11,
        "phase_total": 16, "current_shot": "19300"}
seq2 = [dict(clip) for _ in range(5)] + [dict(clip, status="completed", phase_done=16)]
P._get = lambda path, timeout=30: seq2.pop(0)
try:
    out2 = P._poll_studio("/api/v1/studio/gen-images/status/y", 1800, state, "images", done_statuses=("completed",))
    ok(out2["status"] == "completed", "pha clip đứng yên 50 phút vẫn chờ tới xong")
except RuntimeError as e:
    ok(False, "pha clip đứng yên 50 phút vẫn chờ tới xong", e)

P.time = _Clock()
seq3 = [dict(clip) for _ in range(9)]
P._get = lambda path, timeout=30: seq3.pop(0)
try:
    P._poll_studio("/api/v1/studio/gen-images/status/y", 1800, state, "images", done_statuses=("completed",))
    ok(False, "pha clip đứng yên quá CLIP_STALL_SEC thì cắt")
except RuntimeError as e:
    ok(str(e).startswith(f"No progress for {P.CLIP_STALL_SEC}s") and "19300" in str(e), "pha clip đứng yên quá CLIP_STALL_SEC thì cắt", e)

P.time = _Clock()
seq4 = [{"status": "running", "done": 5, "total": 17} for _ in range(9)]
P._get = lambda path, timeout=30: seq4.pop(0)
try:
    P._poll_studio("/api/v1/studio/gen-images/status/z", 1800, state, "images", done_statuses=("completed",))
    ok(False, "pha vẽ ảnh vẫn cắt ở timeout_sec")
except RuntimeError as e:
    ok(str(e).startswith("No progress for 1800s"), "pha vẽ ảnh vẫn cắt ở timeout_sec", e)
P.time = real_time
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
