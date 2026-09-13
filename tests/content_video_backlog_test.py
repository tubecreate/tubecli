# -*- coding: utf-8 -*-
"""content_video → hàng đợi Codex: nút "Đưa vào hàng đợi" đi hết đường ống (13/9/2026).

Run:  PYTHONIOENCODING=utf-8 python -X utf8 tests/content_video_backlog_test.py

Không gọi mạng, không đụng bảng Codex thật: create_task / append_event / get_events,
describe_plan (dò Studio qua HTTP) và các hàm tạo task mà route gọi đều bị thay.
  1. create_plan_task / create_auto_task chuyển hold + làn "video" sang Codex; mặc
     định vẫn chạy liền; create_render_task cũng vào làn video (giữ làn, không hold)
  2. queued_reply: task trong hàng đợi không bị nói là "bắt đầu ngay" hay "chờ duyệt"
  3. POST /run: queue=true → hold, trả vị trí; không có queue → lời gọi y như cũ
"""
import asyncio
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

import tubecli.extensions.content_video.pipeline as P  # noqa: E402
import tubecli.extensions.content_video.routes as R  # noqa: E402
from tubecli.core.agent import agent_manager  # noqa: E402
from tubecli.core.bot_i18n import t as bot_t  # noqa: E402
from tubecli.extensions.codex.manager import codex_manager  # noqa: E402

failures = []
checks = 0


def check(label, ok, detail=""):
    global checks
    checks += 1
    print(("  ok   " if ok else "  FAIL ") + label + ("" if ok else f" — {detail}"))
    if not ok:
        failures.append(f"{label}: {detail}")


# ── Thay mọi thứ chạm tới bảng Codex thật / mạng ──────────────────────
made = []


def fake_create_task(**kw):
    made.append(kw)
    return {"id": f"t{len(made)}", "seq": len(made), "status": "backlog" if kw.get("hold") else "queued"}


codex_manager.create_task = fake_create_task
codex_manager.append_event = lambda *a, **k: None
codex_manager.get_events = lambda task_id, limit=1000: [
    {"data": {"kind": P.KIND_PLAN, "agent_id": "a1", "options": {"preset": "x"}}}]
agent_manager.get = lambda aid: None
P.describe_plan = lambda options: "PLAN"
P._read_checkpoint = lambda task_id: {"script": "[SHOW: x]\ny", "title": "T"}

print("── 1. pipeline → Codex ────────────────────────────────────")
check("1a làn của video là 'video'", P.CODEX_LANE == "video", P.CODEX_LANE)
P.create_plan_task("a1", {"source_text": "Hola"}, created_by="user", approval_required=False, hold=True)
check("1b kịch bản + hàng đợi: hold=True, làn video",
      made[-1].get("hold") is True and made[-1].get("lane") == "video", made[-1])
P.create_plan_task("a1", {"source_text": "Hola"}, created_by="user", approval_required=False)
check("1c mặc định vẫn chạy liền (hold=False), vẫn làn video",
      made[-1].get("hold") is False and made[-1].get("lane") == "video", made[-1])
P.create_auto_task("a1", {"source_text": "Hola"}, created_by="user", job_label="Video from content", hold=True)
check("1d tự động + hàng đợi: hold=True, làn video, không cổng duyệt",
      made[-1].get("hold") is True and made[-1].get("lane") == "video"
      and made[-1].get("approval_required") is False, made[-1])
P.create_auto_task("a1", {"publish": True}, created_by="autopublish")
check("1e lịch tự đăng không xin hàng đợi: hold=False", made[-1].get("hold") is False, made[-1])
P.create_render_task({"id": "p1", "seq": 1, "assignee_id": "a1", "assignee_name": "MC"}, "owner")
check("1f lượt dựng vào làn video (giữ làn), không hold",
      made[-1].get("lane") == "video" and not made[-1].get("hold"), made[-1])

print("── 2. câu trả lời khi xếp việc ────────────────────────────")
starting, waiting = bot_t("vs.starting_now"), bot_t("vs.awaiting_approval")
rep_b = P.queued_reply({"id": "t9", "seq": 9, "status": "backlog"})
rep_q = P.queued_reply({"id": "t9", "seq": 9, "status": "queued"})
rep_p = P.queued_reply({"id": "t9", "seq": 9, "status": "pending_approval"})
check("2a hàng đợi: không 'bắt đầu ngay', không 'chờ duyệt'", starting not in rep_b and waiting not in rep_b, rep_b)
check("2b queued vẫn 'bắt đầu ngay'", starting in rep_q, rep_q)
check("2c chờ duyệt vẫn 'chờ bạn duyệt'", waiting in rep_p, rep_p)
check("2d dấu codex cho thẻ chat vẫn còn", "<!--codex:t9:9:backlog-->" in rep_b, rep_b)

print("── 3. POST /api/v1/content-video/run ──────────────────────")
calls = []


def fake_plan(agent_id, options=None, **kw):
    calls.append(("plan", agent_id, kw))
    return {"id": "t50", "seq": 50, "status": "backlog" if kw.get("hold") else "queued"}


def fake_auto(agent_id, options=None, **kw):
    calls.append(("auto", agent_id, kw))
    return {"id": "t51", "seq": 51, "status": "backlog" if kw.get("hold") else "queued"}


def fake_digest(*args, **kw):
    calls.append(("digest", args, kw))
    return {"id": "t52", "seq": 52, "status": "backlog" if kw.get("hold") else "queued"}


P.create_plan_task = fake_plan
P.create_auto_task = fake_auto
P.create_digest_task = fake_digest
codex_manager.backlog_position = lambda task_id: 3
REQ = types.SimpleNamespace(state=types.SimpleNamespace())


def run(**body):
    return asyncio.run(R.run_route(R.RunRequest(**body), REQ))


check("3a RunRequest mặc định queue=False", R.RunRequest(agent_id="a1").queue is False)
out = run(agent_id="a1", content="Hola mundo", options={"preset": "x"}, created_by="user", queue=True)
check("3b Đưa vào hàng đợi (duyệt kịch bản): create_plan_task nhận hold=True, không cổng duyệt",
      calls[-1][0] == "plan" and calls[-1][2].get("hold") is True
      and calls[-1][2].get("approval_required") is False, calls[-1])
check("3c trả status 'queued' + task backlog + vị trí 3",
      out["status"] == "queued" and out["task"]["status"] == "backlog" and out.get("position") == 3, out)
out = run(agent_id="a1", content="Hola mundo", options={"preset": "x"}, created_by="user", review=False, queue=True)
check("3d làm thẳng + hàng đợi: create_auto_task nhận hold=True",
      calls[-1][0] == "auto" and calls[-1][2].get("hold") is True and out.get("position") == 3, calls[-1])
out = run(agent_id="a1", content="Hola mundo", options={"preset": "x"}, created_by="user")
check("3e nút Tạo video: KHÔNG gửi hold, không có vị trí",
      calls[-1][0] == "plan" and "hold" not in calls[-1][2] and "position" not in out, (calls[-1], out))
out = run(agent_id="a1", input="làm video", created_by="user")
check("3f đường cũ không nội dung: create_digest_task nhận đúng 5 đối số như trước",
      calls[-1][0] == "digest" and len(calls[-1][1]) == 5 and calls[-1][2] == {}, calls[-1])
out = run(agent_id="a1", input="làm video", created_by="user", queue=True)
check("3g đường cũ + hàng đợi: thêm đúng hold=True", calls[-1][0] == "digest" and calls[-1][2] == {"hold": True},
      calls[-1])


def boom(task_id):
    raise RuntimeError("không đọc được kho")


codex_manager.backlog_position = boom
out = run(agent_id="a1", content="Hola", options={"preset": "x"}, created_by="user", queue=True)
check("3h không đọc được vị trí: task vẫn tạo, position=0",
      out.get("position") == 0 and out["task"]["status"] == "backlog", out)

print()
print(f"{checks - len(failures)}/{checks} ok")
if failures:
    print("HỎNG:")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("ALL PASS")
