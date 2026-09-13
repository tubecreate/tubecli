# -*- coding: utf-8 -*-
"""Hàng đợi của Codex — nút "Đưa vào hàng đợi" thay vì chạy liền (13/9/2026).

Run:  PYTHONIOENCODING=utf-8 python -X utf8 tests/codex_backlog_test.py

Luật người dùng chốt:
  • Tự chạy từng cái: không còn video nào queued/running thì Codex thả video kế tiếp.
  • "Tạo video" vẫn chạy liền, chen trước hàng đợi.
  • Video dừng ở bước duyệt (review) KHÔNG giữ hàng.

Chạy trên kho tạm (không đụng tasks.json thật, không đẩy Telegram), đối chiếu code thật:
  A. Tạo      — hold → backlog; lane/hold ghi vào task; thống kê + active có nó
  B. Thả      — làn rảnh: claim_next thả rồi nhận luôn; sự kiện đúng thứ tự
  C. Giữ làn  — running giữ, review không; mỗi lần thả MỘT cái
  D. Thứ tự   — tạo trước chạy trước; ưu tiên cao chen lên; trùng mốc thì số task
  E. Chen     — "Tạo video" (queued thẳng) chạy trước, hàng đợi chờ nó xong;
                task lỗi không giữ làn
  F. Làn      — task chung không giữ làn video; hai làn độc lập
  G. Nút      — Huỷ, Chạy ngay (bấm hai lần = no-op), sửa khi còn chờ;
                backlog → running là nước cấm
  H. Duyệt    — cần duyệt + hold: duyệt xong vào hàng đợi, không chạy liền
  I. Đĩa      — nạp lại còn backlog + lane; task không xin hàng đợi giữ hình dạng cũ
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

import tubecli.extensions.codex.manager as CMod  # noqa: E402

failures = []
checks = 0


def check(label, ok, detail=""):
    global checks
    checks += 1
    print(("  ok   " if ok else "  FAIL ") + label + ("" if ok else f" — {detail}"))
    if not ok:
        failures.append(f"{label}: {detail}")


print("=" * 70)
print("HÀNG ĐỢI CODEX — TỰ CHẠY TỪNG VIDEO, TẠO VIDEO CHEN TRƯỚC, REVIEW KHÔNG GIỮ HÀNG")
print("=" * 70)

TMP = tempfile.mkdtemp(prefix="codex-backlog-")
CMod.CODEX_DATA_DIR = TMP
CMod.TASKS_FILE = os.path.join(TMP, "tasks.json")
CMod.EVENTS_DIR = os.path.join(TMP, "events")

cm = CMod.CodexManager()
cm.notifications_enabled = False   # không đẩy gì vào Telegram thật


def mk(title, lane="video", hold=False, approval=False, priority=0):
    # approval_required tường minh: để None là đọc cài đặt thật của máy.
    return cm.create_task(goal=title, title=title, created_by="user", lane=lane, hold=hold,
                          approval_required=approval, priority=priority)


def status(task):
    return cm.get_task(task["id"])["status"]


def messages(task):
    return [e.get("message", "") for e in cm.get_events(task["id"], limit=0)]


def claimed(task):
    got = cm.claim_next()
    return bool(got) and got["id"] == task["id"]


print("── A. tạo ─────────────────────────────────────────────────")
a = mk("A", hold=True)
check("A1 hold → backlog", a["status"] == CMod.BACKLOG, a["status"])
check("A2 lane + hold ghi vào task", a.get("lane") == "video" and a.get("hold") is True, a)
stats = cm.get_stats()
check("A3 thống kê có backlog, active tính cả nó", stats.get("backlog") == 1 and stats.get("active") == 1, stats)
check("A4 list_tasks('backlog') và ('active') đều thấy",
      [t["id"] for t in cm.list_tasks(status="backlog")] == [a["id"]]
      and a["id"] in [t["id"] for t in cm.list_tasks(status="active")])
check("A5 sự kiện '→ backlog'", "→ backlog" in messages(a), messages(a))
check("A6 ALL_STATES có backlog, ngay sau pending_approval",
      CMod.ALL_STATES[:3] == ["pending_approval", "backlog", "queued"], CMod.ALL_STATES)

print("── B. thả ─────────────────────────────────────────────────")
check("B1 làn rảnh: claim_next thả A rồi nhận luôn", claimed(a) and status(a) == "running", status(a))
ms = messages(a)
i_rel = next((i for i, m in enumerate(ms) if m.startswith("backlog → queued")), -1)
i_run = next((i for i, m in enumerate(ms) if m == "queued → running"), -1)
check("B2 sự kiện: backlog → queued TRƯỚC queued → running", 0 <= i_rel < i_run, ms)

print("── C. giữ làn ─────────────────────────────────────────────")
b = mk("B", hold=True)
c = mk("C", hold=True)
check("C1 A đang chạy: claim_next không nhận gì", cm.claim_next() is None)
check("C2 B, C vẫn nằm hàng đợi", status(b) == status(c) == "backlog", (status(b), status(c)))
check("D1 vị trí: B thứ 1, C thứ 2",
      cm.backlog_position(b["id"]) == 1 and cm.backlog_position(c["id"]) == 2,
      (cm.backlog_position(b["id"]), cm.backlog_position(c["id"])))
cm.report_result(a["id"], "## kịch bản")            # A → review
check("C3 A nằm review KHÔNG giữ hàng: B được thả + nhận", claimed(b), status(b))
check("C4 mỗi lần một cái: C vẫn chờ", status(c) == "backlog", status(c))
check("D2 C lên thứ 1", cm.backlog_position(c["id"]) == 1, cm.backlog_position(c["id"]))

print("── E. chen hàng ───────────────────────────────────────────")
now = mk("NOW")                                      # nút "Tạo video": làn video, không hold
check("E1 'Tạo video' vào queued thẳng", now["status"] == "queued", now["status"])
cm.report_failure(b["id"], "boom")                    # B lỗi: làn chỉ còn NOW (queued)
check("E2 'Tạo video' được nhận trước, C vẫn chờ (queued cũng giữ làn)",
      claimed(now) and status(c) == "backlog", status(c))
check("E3 B lỗi không giữ làn, nhưng NOW đang chạy → C vẫn chờ",
      cm.claim_next() is None and status(c) == "backlog", status(c))
cm.report_result(now["id"], "xong")
check("E4 không còn video queued/running → C chạy", claimed(c), status(c))

print("── F. làn ─────────────────────────────────────────────────")
cm.report_result(c["id"], "xong")                     # làn video trống
g = mk("G", lane="")                                  # task chung, queued
check("F0 task chung được nhận", claimed(g))
d = mk("D", hold=True)
check("F1 task chung đang chạy KHÔNG giữ làn video: D được thả", claimed(d), status(d))
x1 = mk("X1", lane="x", hold=True)
v1 = mk("V1", hold=True)
check("F2 làn x rảnh thì thả dù làn video đang bận", claimed(x1) and status(v1) == "backlog", status(v1))
check("F3 vị trí tính theo từng làn", cm.backlog_position(v1["id"]) == 1, cm.backlog_position(v1["id"]))

print("── G. nút trên thẻ ────────────────────────────────────────")
cm.cancel(v1["id"])
check("G1 Huỷ ngay trong hàng đợi", status(v1) == "cancelled", status(v1))
v2 = mk("V2", hold=True)
v3 = mk("V3", hold=True)
upd = cm.update_task(v2["id"], title="V2 đã sửa")
check("G2 còn chờ thì sửa được", bool(upd) and upd["title"] == "V2 đã sửa", upd)
r1 = cm.run_now(v3["id"], actor="owner")
check("G3 Chạy ngay: queued liền dù D đang chạy", r1["status"] == "queued", r1["status"])
n = len(messages(v3))
r2 = cm.run_now(v3["id"], actor="owner")
check("G4 bấm Chạy ngay lần hai là no-op", r2["status"] == "queued" and len(messages(v3)) == n,
      (r2["status"], messages(v3)))
check("G5 V3 được nhận, V2 vẫn chờ (V3 giữ làn)", claimed(v3) and status(v2) == "backlog", status(v2))
try:
    cm.run_now(d["id"])
    refused = False
except ValueError as e:
    refused = "not waiting in the backlog" in str(e)
check("G6 Chạy ngay task đang chạy bị từ chối, câu lỗi nói rõ", refused)
try:
    cm._transition(v2["id"], "running", "test")
    illegal = False
except ValueError:
    illegal = True
check("G7 backlog → running là nước cấm (phải qua queued)", illegal)

print("── D. ưu tiên + trùng mốc ─────────────────────────────────")
p = mk("P", hold=True, priority=5)
check("D3 ưu tiên cao chen lên đầu hàng",
      cm.backlog_position(p["id"]) == 1 and cm.backlog_position(v2["id"]) == 2,
      (cm.backlog_position(p["id"]), cm.backlog_position(v2["id"])))
check("D4 không nằm hàng đợi → 0", cm.backlog_position(d["id"]) == 0 and cm.backlog_position("khong-co") == 0)
cm.report_result(d["id"], "xong")
cm.report_result(v3["id"], "xong")
check("D5 thả theo ưu tiên: P trước V2", claimed(p) and status(v2) == "backlog", status(v2))
e1 = mk("E1", lane="tie", hold=True)
e2 = mk("E2", lane="tie", hold=True)
with cm._lock:
    cm._tasks[e1["id"]]["created_at"] = cm._tasks[e2["id"]]["created_at"]
check("D6 trùng mốc thời gian: số task nhỏ đứng trước",
      cm.backlog_position(e1["id"]) == 1 and cm.backlog_position(e2["id"]) == 2,
      (cm.backlog_position(e1["id"]), cm.backlog_position(e2["id"])))

print("── H. cần duyệt ───────────────────────────────────────────")
h = mk("H", hold=True, approval=True)
check("H1 cần duyệt: chờ duyệt trước đã", h["status"] == "pending_approval", h["status"])
ap = cm.approve(h["id"], actor="owner")
check("H2 duyệt xong → hàng đợi, không chạy liền", ap["status"] == "backlog", ap["status"])
ap2 = cm.approve(h["id"], actor="owner")
check("H3 duyệt lần hai là no-op", ap2["status"] == "backlog", ap2["status"])
pa = mk("PA", lane="", approval=True)
check("H4 task thường duyệt xong vẫn queued như cũ", cm.approve(pa["id"], actor="owner")["status"] == "queued")

print("── I. nạp lại từ đĩa ──────────────────────────────────────")
cm2 = CMod.CodexManager()
cm2.notifications_enabled = False
t2 = cm2.get_task(v2["id"])
check("I1 còn backlog + lane + hold sau khi nạp lại",
      bool(t2) and t2["status"] == "backlog" and t2.get("lane") == "video" and t2.get("hold") is True, t2)
# P đã được nhận ở D5, nên làn video còn V2 (tạo trước) rồi H (duyệt xong mới vào hàng).
check("I2 vị trí sau khi nạp lại vẫn đúng: V2 thứ 1, H thứ 2",
      cm2.backlog_position(v2["id"]) == cm.backlog_position(v2["id"]) == 1
      and cm2.backlog_position(h["id"]) == cm.backlog_position(h["id"]) == 2,
      (cm2.backlog_position(v2["id"]), cm2.backlog_position(h["id"])))
plain = cm.create_task(goal="plain", created_by="user", approval_required=False)
check("I3 task không xin hàng đợi giữ hình dạng cũ (không lane/hold, queued)",
      "lane" not in plain and "hold" not in plain and plain["status"] == "queued", plain)

print()
print(f"{checks - len(failures)}/{checks} ok")
if failures:
    print("HỎNG:")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("ALL PASS")
