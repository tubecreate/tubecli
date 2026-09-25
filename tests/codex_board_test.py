# -*- coding: utf-8 -*-
"""Bảng việc (25/9/2026): dòng gọn của task, nhóm trạng thái, set_title/set_meta, ETag của danh sách.

User: «tên nó giống hệt nhau», «load ban đầu quá chậm», «phải cuộn xuống nhiều quá mới thấy đang chạy tới bước
nào bao nhiêu %». Cam kết:
  1. board_row: KHÔNG mang goal/steps/plan/result; có summary {done,total,current{label,progress},failed} + meta.
  2. query_tasks: nhóm needs_you/working/backlog/done/stopped; lọc video/general, agent, ngôn ngữ, chữ tìm (cả
     thông số); phân trang offset/limit; total sau lọc.
  3. set_title đổi tên ở MỌI trạng thái (kể cả đang chạy), không đổi thì không ghi event; set_meta gộp, None/"" xoá,
     khoá lạ bỏ.
  4. Route view=board: ETag ổn định khi dữ liệu không đổi (dù `now` đổi) → If-None-Match nhận 304; đổi dữ liệu → ETag
     khác. File tĩnh: ETag theo mtime+size, 304 khi khớp.
Không đĩa, không mạng: manager giả _save/append_event.
"""
import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

from tubecli.extensions.codex import manager as M  # noqa: E402
from tubecli.extensions.codex import routes as R  # noqa: E402

PASS = FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", label)
    else:
        FAIL += 1
        print("  FAIL", label, "—", detail)


def task(seq, status, **kw):
    base = {"id": f"t{seq}", "seq": seq, "title": f"Task {seq}", "goal": "goal " * 50, "status": status,
            "created_by": "user", "origin": {}, "assignee_type": "agent", "assignee_id": "ag1",
            "assignee_name": "Doctor", "skill_ref": {}, "plan": [{"step": 1}] * 80, "approval": {"required": False},
            "result": "x" * 500, "error": "", "priority": 0, "retry_count": 0, "max_retries": 3,
            "steps": [], "created_at": f"2026-09-25T10:{seq:02d}:00", "updated_at": f"2026-09-25T10:{seq:02d}:00",
            "started_at": "", "finished_at": "", "lane": "video"}
    base.update(kw)
    return base


STEPS = [{"name": "capabilities", "label": "Check", "status": "success", "message": "", "progress": 100,
          "started_at": "2026-09-25T10:00:00", "ended_at": "2026-09-25T10:00:03"},
         {"name": "script", "label": "Write the script", "status": "success", "message": "60 scenes", "progress": 100,
          "started_at": "2026-09-25T10:00:03", "ended_at": "2026-09-25T10:01:15"},
         {"name": "images", "label": "Generate shot images", "status": "running", "message": "34/81", "progress": None,
          "started_at": "2026-09-25T10:01:15", "ended_at": ""},
         {"name": "tts", "label": "Voice", "status": "pending", "message": "", "progress": None,
          "started_at": "2026-09-25T10:01:15", "ended_at": ""}]

# ── 1. tóm tắt bước + dòng bảng ───────────────────────────────────────────────
ok(M.step_fraction({"progress": 42}) == 0.42 and M.step_fraction({"progress": None, "message": "34/81"}) == 34 / 81
   and M.step_fraction({"message": "scenes 7-12 of 60"}) == 6 / 60 and M.step_fraction({"message": "hello"}) is None,
   "phần đã xong: % máy chủ, «34/81», «7-12 of 60», không có → None")
run = task(3, "running", steps=STEPS, meta={"language": "vi", "text_model": "ag/gemini-3.8-flash",
                                             "voice": {"engine": "everai", "id": "vi_female_huyenanh_mb"}})
sm = M.step_summary(run)
ok(sm["done"] == 2 and sm["total"] == 4 and sm["current"]["label"] == "Generate shot images"
   and sm["current"]["index"] == 3 and abs(sm["current"]["progress"] - 34 / 81) < 1e-9 and "failed" not in sm,
   "summary: 2/4 xong, bước đang chạy = ảnh, 42 %", sm)
bad = task(4, "failed", steps=[dict(STEPS[0]), {**STEPS[2], "status": "error", "message": "TTS failed for every shot"}],
           error="RuntimeError: TTS failed for every shot (123).")
row = M.board_row(bad)
ok(row["summary"]["failed"]["label"] == "Generate shot images" and row["error"].startswith("RuntimeError")
   and "goal" not in row and "steps" not in row and "plan" not in row and "result" not in row and row["has_result"],
   "dòng bảng: có lỗi ngắn + bước hỏng, KHÔNG goal/steps/plan/result", sorted(row))
row3 = M.board_row(run)
ok(row3["meta"]["voice"]["id"] == "vi_female_huyenanh_mb" and row3["lane"] == "video" and row3["approval"] == {"required": False, "note": ""},
   "dòng bảng mang meta + lane + approval gọn", row3.get("meta"))
import json  # noqa: E402
ok(len(json.dumps(row3)) < len(json.dumps(run)) / 3, "dòng bảng nhỏ hơn task đầy đủ ít nhất 3 lần (dữ liệu giả; thật ≥10×)",
   (len(json.dumps(row3)), len(json.dumps(run))))

# ── 2. query_tasks ────────────────────────────────────────────────────────────
mgr = M.CodexManager()
mgr._loaded = True
mgr._save = lambda: None
EVENTS = []
mgr.append_event = lambda tid, kind, msg, actor="system", data=None: EVENTS.append((tid, kind, msg, data))
mgr._tasks = {t["id"]: t for t in [
    task(1, "review", title="Sau 60 tuổi, 6 thói quen", meta={"language": "vi", "stage": "auto", "text_model": "ag/gemini-3.8-flash"}),
    task(2, "pending_approval", lane="", assignee_id="ag2", assignee_name="Bot"),
    run,
    task(5, "backlog", meta={"language": "ja", "stage": "clone", "voice": {"engine": "capcut", "id": "ICL_jp", "name": "Yukiko"}}),
    task(6, "done", meta={"language": "en"}),
    bad,
    task(7, "cancelled"),
    task(8, "rejected", lane=""),
]}
rows, total = mgr.query_tasks(group="needs_you")
ok([r["seq"] for r in rows] == [2, 1] and total == 2, "nhóm «Cần bạn» = chờ duyệt + chờ nghiệm thu, mới nhất trước", [r["seq"] for r in rows])
ok(mgr.query_tasks(group="working")[1] == 1 and mgr.query_tasks(group="stopped")[1] == 3
   and mgr.query_tasks(group="backlog")[1] == 1 and mgr.query_tasks(group="done")[1] == 1
   and mgr.query_tasks(group="all")[1] == 8 and mgr.query_tasks(group="running")[1] == 1,
   "các nhóm đếm đúng; tên trạng thái thô vẫn dùng được")
ok(mgr.query_tasks(lane="video")[1] == 6 and mgr.query_tasks(lane="general")[1] == 2, "lọc video / việc chung")
ok(mgr.query_tasks(agent="ag2")[1] == 1 and mgr.query_tasks(language="ja")[1] == 1 and mgr.query_tasks(language="vi-VN")[1] == 2,
   "lọc agent, ngôn ngữ (so mã gốc vi ~ vi-VN)")
ok(mgr.query_tasks(q="yukiko")[1] == 1 and mgr.query_tasks(q="#6")[1] == 1 and mgr.query_tasks(q="gemini-3.8")[1] == 2
   and mgr.query_tasks(q="thói quen")[1] == 1, "tìm theo tên giọng, #số, model, chữ trong tên")
page1, tot = mgr.query_tasks(offset=0, limit=3)
page2, _ = mgr.query_tasks(offset=3, limit=3)
ok([r["seq"] for r in page1] == [8, 7, 6] and [r["seq"] for r in page2] == [5, 4, 3] and tot == 8, "phân trang offset/limit", ([r["seq"] for r in page1], [r["seq"] for r in page2]))
ok([r["seq"] for r in mgr.query_tasks(sort="oldest", limit=2)[0]] == [1, 2], "sắp xếp cũ nhất trước")
st = mgr.get_stats()
ok(st["needs_you"] == 2 and st["working"] == 1 and st["stopped"] == 3 and st["backlog"] == 1 and st["done"] == 1 and st["total"] == 8,
   "get_stats có đếm theo nhóm", st)

# ── 3. set_title / set_meta ──────────────────────────────────────────────────
EVENTS.clear()
mgr.set_title("t3", "  Vì sao người trên 60   hay tỉnh giấc  ", actor="pipeline")
ok(mgr._tasks["t3"]["title"] == "Vì sao người trên 60 hay tỉnh giấc" and EVENTS[-1][3]["old_title"] == "Task 3",
   "đổi tên task ĐANG CHẠY, gọn khoảng trắng, ghi event kèm tên cũ", EVENTS[-1:])
n = len(EVENTS)
mgr.set_title("t3", "Vì sao người trên 60 hay tỉnh giấc")
ok(len(EVENTS) == n and mgr.set_title("t3", "") is None and mgr.set_title("nope", "x") is None,
   "tên không đổi / rỗng / task lạ → không ghi gì")
mgr.set_meta("t2", {"stage": "plan", "language": "vi", "voice": {"engine": "edge", "id": "", "name": None}, "hack": 1})
ok(mgr._tasks["t2"]["meta"] == {"stage": "plan", "language": "vi", "voice": {"engine": "edge"}},
   "set_meta: chỉ META_KEYS, dict bỏ giá trị rỗng", mgr._tasks["t2"]["meta"])
mgr.set_meta("t2", {"language": "", "text_model": "cx/gpt-5.5", "voice": None})
ok(mgr._tasks["t2"]["meta"] == {"stage": "plan", "text_model": "cx/gpt-5.5"}, "None/\"\" xoá khoá, gộp khoá mới", mgr._tasks["t2"]["meta"])

# ── 4. route view=board: ETag / 304 ──────────────────────────────────────────
R.codex_manager = mgr


class _Req:
    def __init__(self, headers=None):
        self.headers = headers or {}


r1 = R._board_response(_Req(), "needs_you", "", "", "", "", "newest", 0, 50)
etag = r1.headers.get("etag")
body = json.loads(r1.body)
ok(r1.status_code == 200 and etag and body["total"] == 2 and body["tasks"][0]["seq"] == 2 and body["stats"]["needs_you"] == 2
   and "now" in body and r1.headers.get("cache-control") == "no-cache", "danh sách bảng: ETag + đếm nhóm + now", (r1.status_code, etag))
time.sleep(0.01)
r2 = R._board_response(_Req({"if-none-match": etag}), "needs_you", "", "", "", "", "newest", 0, 50)
ok(r2.status_code == 304 and r2.headers.get("etag") == etag, "không đổi gì (dù `now` khác) → 304 rỗng", r2.status_code)
mgr.set_title("t1", "Tên mới")
r3 = R._board_response(_Req({"if-none-match": etag}), "needs_you", "", "", "", "", "newest", 0, 50)
ok(r3.status_code == 200 and r3.headers.get("etag") != etag, "đổi tên → ETag khác, trả 200")
r4 = R._board_response(_Req(), "all", "", "", "", "", "newest", 0, 3)
b4 = json.loads(r4.body)
ok(b4["has_more"] is True and b4["count"] == 3 and b4["total"] == 8, "phân trang: has_more", (b4["has_more"], b4["count"]))

tmp = tempfile.mkdtemp()
fp = os.path.join(tmp, "a.js")
open(fp, "w").write("x")
s1 = R._static(fp, "application/javascript", _Req())
et = s1.headers.get("etag")
s2 = R._static(fp, "application/javascript", _Req({"if-none-match": et}))
ok(s1.status_code == 200 and et and s2.status_code == 304 and s1.headers.get("cache-control") == "no-cache",
   "file tĩnh: ETag + 304, no-cache (không còn no-store)", (et, s2.status_code))

print()
print("=" * 62)
print(f"{PASS}/{PASS + FAIL} PASS" if not FAIL else f"{PASS}/{PASS + FAIL} PASS — {FAIL} HỎNG")
sys.exit(1 if FAIL else 0)
