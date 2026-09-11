# -*- coding: utf-8 -*-
"""Cảnh báo của KHÂU DỰNG phải lên thẻ kết quả (11/9/2026).

Bệnh: tập 330 dựng hai lượt, một đoạn lượt 2 hỏng nên Studio bỏ MC ở 5 phút đầu và
ghi "MC bị bỏ ở 1/5 đoạn…" vào báo cáo export — pipeline chép báo cáo vào
state["subtitles"] rồi thôi, thẻ Codex vẫn xanh, không một dòng nào. Cam kết:
  1. Mỗi cảnh báo của báo cáo export thành một dòng "Render: …" trong state["warnings"].
  2. Không nhân đôi khi cùng một cảnh báo xuất hiện lại (Retry bám export cũ).
  3. Báo cáo không có cảnh báo → không thêm gì.
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


# Mọi đường ra mạng đều giả — test không được chạm máy chủ đang chạy.
P._finished_video = lambda state, ep_id: None
P._running_export = lambda task_id: None
P._post = lambda path, payload=None, timeout=60, **k: {"task_id": "t1"}
P._get = lambda path, timeout=60, **k: {"video_url": "C:/x/episode_330_pipeline_export.mp4"}
P._put = lambda path, payload=None, timeout=60, **k: {}
P._checkpoint_merge = lambda state, data: None
P.media_seconds = lambda path: 1407.0
P.planned_seconds = lambda state: 0
REPORT = {}
P._poll_studio = lambda *a, **k: {"status": "completed", "subtitles": REPORT}


def render(state=None):
    st = state or {"episode_id": 330, "checkpoint": {}, "_say": lambda *a: None, "warnings": []}
    P._step_render(st, {})
    return st


REPORT.clear()
REPORT.update({"style": "capcut_bold", "warnings": [
    "MC bị bỏ ở 1/5 đoạn vì dựng lỗi: Conversion failed!"], "layout": {"mode": "two_pass"}})
st = render()
ok(st["warnings"] == ["Render: MC bị bỏ ở 1/5 đoạn vì dựng lỗi: Conversion failed!"],
   "cảnh báo khâu dựng lên thẻ (bệnh cũ: nằm im trong báo cáo, thẻ xanh)", st["warnings"])
ok(st.get("subtitles", {}).get("style") == "capcut_bold", "báo cáo phụ đề vẫn được giữ như trước")
st2 = render(st)
ok(len(st2["warnings"]) == 1, "gặp lại cùng cảnh báo (Retry bám export cũ): không nhân đôi", st2["warnings"])
out = P._render_result(st, {}, [], [], 1.0)
ok("⚠️ Render: MC bị bỏ" in out, "thẻ kết quả in dòng cảnh báo",
   [l for l in out.splitlines() if "⚠️" in l])
REPORT.clear()
REPORT.update({"style": "capcut_bold"})
ok(render()["warnings"] == [], "báo cáo sạch → không thêm dòng nào")

print()
print("=" * 62)
print(f"{PASS}/{PASS + FAIL} PASS" if not FAIL else f"{PASS}/{PASS + FAIL} PASS — {FAIL} HỎNG")
sys.exit(1 if FAIL else 0)
