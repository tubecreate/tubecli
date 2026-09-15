# -*- coding: utf-8 -*-
"""Codex Activity kể AI đang làm gì (lõi .101, 15/9/2026).

User: "cái mục activity vô dụng thật sự, đúng ra nó phải load những gì đang chạy ở bước đang thực hiện" + "phải thể
hiện được AI nó đang làm cái gì tới bước nào hoặc làm tới đâu bao lâu xong chứ hiện mấy cái thông số vô dụng tốn ram".
Chạy trên kho tạm, đồng hồ giả.

Kiểm:
  A. chuyển trạng thái: dòng bắt đầu ghi TÊN bước; dòng xong có thời lượng + chi tiết; data mang label/elapsed/detail
  B. dòng tiến độ: câu đổi khi bước vẫn chạy → kind "progress"; câu lặp / chỉ nhảy % → không ghi; câu chỉ khác con số
     → tối đa một dòng mỗi PROGRESS_TICK_SEC; câu khác hẳn → ghi ngay; trần mỗi bước; hết bước thì quên
  C. route: sự kiện gửi lên trình duyệt bỏ data lớn, ẩn dòng checkpoint, giữ các khoá nhỏ
  D. pipeline gửi % cho các đợt viết cảnh; MAX_EVENT_LINES nới

Run:  python tests/codex_activity_test.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

import tubecli.extensions.codex.manager as CMod  # noqa: E402

PASS = FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", label)
    else:
        FAIL += 1
        print("  FAIL", label, "—", str(detail)[:300])


TMP = tempfile.mkdtemp(prefix="codex-activity-")
CMod.CODEX_DATA_DIR = TMP
CMod.TASKS_FILE = os.path.join(TMP, "tasks.json")
CMod.EVENTS_DIR = os.path.join(TMP, "events")
NOW = [1000.0]
CMod._clock = lambda: NOW[0]
cm = CMod.CodexManager()
cm.notifications_enabled = False
t = cm.create_task(goal="Video", title="Video", created_by="user", lane="video", approval_required=False)
cm.claim_next()
TID = t["id"]


def evs(kind=None):
    return [e for e in cm.get_events(TID, limit=0) if kind is None or e.get("kind") == kind]


print("── A. chuyển trạng thái ────────────────────────────────────")
cm.report_step(TID, "crawl", "running", "Crawl extra sources", "Crawl extra sources")
cm.report_step(TID, "crawl", "success", "", "")
steps = evs("step")
ok(steps[-2]["message"] == "▶ Crawl extra sources" and steps[-2]["data"]["label"] == "Crawl extra sources",
   "bắt đầu bước → ghi TÊN bước, không phải 'crawl'", steps[-2])
ok(steps[-1]["message"].startswith("Crawl extra sources — success (") and steps[-1]["data"].get("elapsed") == 0
   and steps[-1]["data"]["status"] == "success", "xong bước → tên + thời lượng", steps[-1])
cm.report_step(TID, "images", "running", "Generate shot images", "Generate shot images")
cm.report_step(TID, "images", "error", "Cloudflare quota exhausted", "")
last = evs("step")[-1]
ok("Cloudflare quota exhausted" in last["message"] and last["data"].get("detail") == "Cloudflare quota exhausted",
   "bước hỏng → lý do trong dòng + data.detail", last)

print("── B. dòng tiến độ của bước đang chạy ──────────────────────")
cm.report_step(TID, "script", "running", "Write the script", "Write the script")
n0 = len(evs("progress"))
cm.report_step(TID, "script", "running", "outline · 60 scenes")
p = evs("progress")
ok(len(p) == n0 + 1 and p[-1]["message"] == "outline · 60 scenes" and p[-1]["data"]["label"] == "Write the script",
   "câu đổi khi bước vẫn chạy → dòng 'progress' kèm tên bước", p[-1:])
cm.report_step(TID, "script", "running", "outline · 60 scenes")
cm.report_step(TID, "script", "running", "", progress=12)
ok(len(evs("progress")) == n0 + 1, "câu lặp / chỉ nhảy % → không ghi thêm")
NOW[0] += 40
cm.report_step(TID, "script", "running", "outline came back with 74 scenes, 60 planned — asking again")
ok(evs("progress")[-1]["message"].startswith("outline came back with 74 scenes"), "câu khác hẳn → ghi ngay")
cm.report_step(TID, "script", "running", "writing scenes 1-6 of 60", progress=0)
NOW[0] += 2
cm.report_step(TID, "script", "running", "writing scenes 7-12 of 60", progress=10)
msgs = [e["message"] for e in evs("progress")]
ok("writing scenes 1-6 of 60" in msgs and "writing scenes 7-12 of 60" not in msgs,
   "câu chỉ khác con số trong < PROGRESS_TICK_SEC → gộp", msgs[-3:])
NOW[0] += CMod.PROGRESS_TICK_SEC + 1
cm.report_step(TID, "script", "running", "writing scenes 13-18 of 60", progress=20)
ok(evs("progress")[-1]["message"] == "writing scenes 13-18 of 60" and evs("progress")[-1]["data"]["progress"] == 20.0,
   "hết cửa sổ → ghi, kèm %", evs("progress")[-1])
ok(("%s" % TID, "script") in cm._progress_last, "đang nhớ nhịp của bước đang chạy")
cm.report_step(TID, "script", "success", "")
ok((TID, "script") not in cm._progress_last, "hết bước → quên nhịp (không giữ RAM)")
old_max = CMod.PROGRESS_MAX_PER_STEP
CMod.PROGRESS_MAX_PER_STEP = 3
cm.report_step(TID, "tts", "running", "Voice the narration", "Voice the narration")
before = len(evs("progress"))
for i, word in enumerate(["alpha", "beta", "gamma", "delta", "epsilon"]):
    cm.report_step(TID, "tts", "running", f"voice {word}")
ok(len(evs("progress")) - before == 3, "trần dòng tiến độ mỗi bước", len(evs("progress")) - before)
CMod.PROGRESS_MAX_PER_STEP = old_max

print("── C. route gửi lên trình duyệt ────────────────────────────")
from tubecli.extensions.codex import routes as R  # noqa: E402
big = {"checkpoint": {"script": "x" * 50000, "title": "T"}}
raw = [
    {"ts": "1", "kind": "log", "actor": "content_video", "message": "checkpoint", "data": big},
    {"ts": "2", "kind": "progress", "actor": "worker", "message": "writing scenes 7-12 of 60",
     "data": {"step": "script", "label": "Write the script", "progress": 10, "huge": "y" * 10000}},
    {"ts": "3", "kind": "state", "actor": "user", "message": "→ queued"},
]
pub = R._public_events(raw)
ok(len(pub) == 2 and pub[0]["data"] == {"step": "script", "label": "Write the script", "progress": 10}
   and "data" not in pub[1] and len(str(pub)) < 400, "bỏ dòng checkpoint + data lớn, giữ khoá nhỏ", pub)

print("── D. pipeline gửi %, giữ nhiều dòng hơn ───────────────────")
src = open(os.path.join(ROOT, "tubecli", "extensions", "content_video", "pipeline.py"), encoding="utf-8").read()
ok(src.count("round(100 * a / max(1, len(") == 3, "ba vòng viết/sửa/dịch cảnh gửi phần trăm")
ok(CMod.MAX_EVENT_LINES == 1500, "MAX_EVENT_LINES = 1500")

print()
print(f"{PASS}/{PASS + FAIL} PASS" if not FAIL else f"{PASS}/{PASS + FAIL} PASS — {FAIL} HỎNG")
sys.exit(1 if FAIL else 0)
