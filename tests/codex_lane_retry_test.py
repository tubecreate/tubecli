# -*- coding: utf-8 -*-
"""Chạy lại / Yêu cầu sửa / Duyệt tôn trọng làn video (14/9/2026).

User: "đưa vào hàng đợi mà nó vẫn chạy trong khi đang có luồng khác đang chạy" — #5 lỗi,
#7 đưa vào hàng đợi (làn rảnh nên chạy), bấm Chạy lại #5 → hai video dựng song song.

Kiểm:
  A. Chạy lại lúc làn bận → backlog (chờ), có ghi lý do; bấm lại không tăng retry_count;
     claim_next không thả khi làn còn bận; làn rảnh thì được thả và chạy
  B. Yêu cầu sửa lúc làn bận → backlog; rảnh → chạy
  C. Duyệt task cần duyệt lúc làn bận → backlog
  D. Việc chung (không làn) và làn rảnh: nếp cũ — queued ngay
  E. Task xin hàng đợi (hold) huỷ rồi chạy lại → vẫn xếp hàng
  F. pipeline: lượt DỰNG tạo với hold=True, ưu tiên = kế hoạch + 1

Run:  python tests/codex_lane_retry_test.py
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


TMP = tempfile.mkdtemp(prefix="codex-lane-")
CMod.CODEX_DATA_DIR = TMP
CMod.TASKS_FILE = os.path.join(TMP, "tasks.json")
CMod.EVENTS_DIR = os.path.join(TMP, "events")

cm = CMod.CodexManager()
cm.notifications_enabled = False


def mk(title, lane="video", hold=False, approval=False, priority=0):
    return cm.create_task(goal=title, title=title, created_by="user", lane=lane, hold=hold,
                          approval_required=approval, priority=priority)


def status(t):
    return cm.get_task(t["id"])["status"]


def messages(t):
    return [e.get("message", "") for e in cm.get_events(t["id"], limit=0)]


def claimed(t):
    got = cm.claim_next()
    return bool(got) and got["id"] == t["id"]


print("── A. Chạy lại lúc làn bận ────────────────────────────────")
a = mk("A")
b = mk("B")
assert claimed(a) and claimed(b)            # hai task "Tạo video" trực tiếp chạy song song — chủ ý
cm.report_failure(b["id"], "ngã")
check("A1 B lỗi, A đang chạy", status(a) == "running" and status(b) == "failed", (status(a), status(b)))
r = cm.retry(b["id"], actor="owner")
check("A2 Chạy lại B → backlog (không chen vào làn đang bận)", r["status"] == "backlog", r["status"])
check("A3 retry_count +1 và ghi rõ đang chờ lượt",
      cm.get_task(b["id"])["retry_count"] == 1 and any("waiting for its turn" in m for m in messages(b)),
      (cm.get_task(b["id"])["retry_count"], messages(b)[-2:]))
check("A4 vị trí hàng đợi: B thứ 1", cm.backlog_position(b["id"]) == 1, cm.backlog_position(b["id"]))
cm.retry(b["id"], actor="owner")
check("A5 bấm Chạy lại lần nữa: không tăng retry_count, vẫn backlog",
      cm.get_task(b["id"])["retry_count"] == 1 and status(b) == "backlog", (cm.get_task(b["id"])["retry_count"], status(b)))
check("A6 A còn chạy: claim_next không nhận gì", cm.claim_next() is None)
cm.report_result(a["id"], "## xong")        # A → review: làn rảnh
check("A7 A xong: B được thả và chạy", claimed(b) and status(b) == "running", status(b))

print("── B. Yêu cầu sửa lúc làn bận ─────────────────────────────")
c = mk("C")
assert claimed(c)                            # C chạy song song với B (trực tiếp)
cm.report_result(b["id"], "## bản 1")      # B → review
r = cm.complete_review(b["id"], False, actor="owner", feedback="ngắn hơn")
check("B1 Yêu cầu sửa khi C đang chạy → backlog", r["status"] == "backlog", r["status"])
check("B2 góp ý đã nối vào goal", "ngắn hơn" in cm.get_task(b["id"])["goal"])
check("B3 C còn chạy: không thả", cm.claim_next() is None)
cm.report_result(c["id"], "## xong")
check("B4 C xong: B chạy lại", claimed(b) and status(b) == "running", status(b))

print("── C. Duyệt lúc làn bận ───────────────────────────────────")
e = mk("E", approval=True)
check("C1 task cần duyệt: pending_approval", e["status"] == "pending_approval", e["status"])
r = cm.approve(e["id"], actor="owner")
check("C2 duyệt khi B đang chạy → backlog", r["status"] == "backlog", r["status"])
cm.report_result(b["id"], "## bản 2")
check("C3 B xong: E được thả", claimed(e) and status(e) == "running", status(e))

print("── D. Không làn / làn rảnh: nếp cũ ────────────────────────")
g = mk("G", lane="")
assert claimed(g)
cm.report_failure(g["id"], "ngã")
check("D1 việc chung lỗi → Chạy lại → queued ngay dù làn video bận", cm.retry(g["id"])["status"] == "queued")
assert claimed(g)                            # G vào chạy trước, khỏi tranh lượt claim với F
cm.report_result(e["id"], "## xong")        # làn video rảnh
f = mk("F")
assert claimed(f)
cm.report_failure(f["id"], "ngã")
check("D2 làn rảnh: Chạy lại → queued ngay", cm.retry(f["id"])["status"] == "queued")
assert claimed(f)

print("── E. Task xin hàng đợi huỷ rồi chạy lại ──────────────────")
h = mk("H", hold=True)
check("E1 hold → backlog", h["status"] == "backlog")
cm.cancel(h["id"])
check("E2 huỷ → cancelled", status(h) == "cancelled", status(h))
r = cm.retry(h["id"])
check("E3 Chạy lại → vẫn xếp hàng (hold), không chen F", r["status"] == "backlog", r["status"])
cm.report_result(f["id"], "## xong")
check("E4 F xong: H chạy", claimed(h) and status(h) == "running", status(h))

print("── F. pipeline: lượt dựng chờ làn ─────────────────────────")
src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "tubecli", "extensions", "content_video", "pipeline.py"), encoding="utf-8").read()
i = src.find("approval_required=False,          # the script IS the approval")
blk = src[i:i + 500]
check("F1 lượt dựng: lane video + hold=True + ưu tiên kế hoạch + 1",
      "lane=CODEX_LANE" in blk and "hold=True," in blk and 'priority=int(plan_task.get("priority") or 0) + 1' in blk, blk[:300])
check("F2 TRANSITIONS: về backlog từ review/failed/rejected/cancelled",
      all(CMod.BACKLOG in CMod.TRANSITIONS[s] for s in (CMod.REVIEW, CMod.FAILED, CMod.REJECTED, CMod.CANCELLED)))

print()
if failures:
    print(f"{checks - len(failures)}/{checks} PASS — {len(failures)} HỎNG")
    sys.exit(1)
print(f"{checks}/{checks} PASS")
