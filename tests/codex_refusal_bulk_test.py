# -*- coding: utf-8 -*-
"""Codex: agent trả lời thẳng mà TỪ CHỐI ⇒ task FAILED (không vào review) + dọn bảng hàng loạt (10/11/2026).

Run:  PYTHONIOENCODING=utf-8 python -X utf8 tests/codex_refusal_bulk_test.py

Sự cố thật (contabo, task #190): Orchestrator viết «Tôi không dựng được video Bài 14… không có thư mục, API không gọi
được» — bước «Agent suy nghĩ» báo «direct reply», task vào REVIEW như một kết quả xong.

  R. refusal_reason — từ chối en/vi/es (câu #190 thật) bị bắt; kết quả thật nhắc «cannot» ở câu sau, «không chỉ…
     được», câu hỏi «… được không?» KHÔNG bị bắt
  X. _execute_agent — trả lời thẳng từ chối ⇒ AgentRefused + bước reason=error; trả lời thường ⇒ trả về; skill không
     tồn tại ⇒ AgentRefused (trước đây trả reply ⇒ review)
  W. worker — AgentRefused ⇒ task FAILED, error mang lý do của agent
  B. bulk_accept_published — chỉ auto/render ĐÃ có video id thật; plan (có hook dựng+đăng) không bao giờ; link
     support.google.com không tính; dry_run không đổi gì; KHÔNG hook on_accept nào chạy; bấm lần hai = 0
  C. bulk_close_failed — chỉ FAILED cũ hơn N ngày ⇒ CANCELLED (dữ liệu còn, Retry được); N sai ⇒ lỗi
  H. routes — POST /bulk/accept-published, /bulk/close-failed (dry_run + thật)

Kho tạm (không đụng tasks.json thật), không Telegram, không gọi model / HTTP thật.
"""
import asyncio
import datetime
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
    print(("  ok   " if ok else "  FAIL ") + label + ("" if ok else f" — {str(detail)[:300]}"))
    if not ok:
        failures.append(f"{label}: {detail}")


TMP = tempfile.mkdtemp(prefix="codex-refusal-bulk-")
CMod.CODEX_DATA_DIR = TMP
CMod.TASKS_FILE = os.path.join(TMP, "tasks.json")
CMod.EVENTS_DIR = os.path.join(TMP, "events")

cm = CMod.CodexManager()
cm.notifications_enabled = False
cm.post_to_chat = lambda *a, **k: None          # không gửi gì vào chat thật
CMod.codex_manager = cm

from tubecli.extensions.codex import executor as E  # noqa: E402

print("── R. refusal_reason ──────────────────────────────────────")
T190 = ("Tôi không dựng được video Bài 14 theo đúng như yêu cầu trong môi trường này — và tôi sẽ không báo là đã "
        "tạo file/video khi chưa thực sự làm được. Phần “SYSTEM - AUTONOMOUS EXECUTION MODE” …\n\nKhông có nguồn để "
        "sao chép: /home/claude/sd6v/ không tồn tại…")
G190 = "Thiết lập thư mục `/root/tubecli/data/codex_gpt/workspace/sd6v/` … và dựng hoàn chỉnh video Bài 14." * 3
refusals = {
    "R1 câu #190 thật (vi)": (T190, G190),
    "R2 en: I can't access": ("I can't access that folder from here, so nothing was created.", "Build the folder"),
    "R3 en: I'm sorry, but I cannot": ("I'm sorry, but I cannot run that API from this machine.", "Call the API"),
    "R4 en: I am unable to": ("I am unable to render the video because ffmpeg is missing.", "Render the video"),
    "R5 es: No puedo": ("No puedo acceder al servidor, así que no generé el video.", "Genera el video"),
    "R6 es: Lo siento… no": ("Lo siento, pero no tengo acceso a esa carpeta.", "Crea la carpeta"),
    "R7 vi: không có quyền": ("Mình không có quyền truy cập thư mục đó.", "Tạo thư mục"),
    "R8 vi: Xin lỗi. + câu kế": ("Xin lỗi. Tôi không thể gọi API TTS từ máy này.", "Tạo giọng đọc"),
}
for label, (rep, goal) in refusals.items():
    why = E.refusal_reason(rep, goal)
    check(label, bool(why), why)
check("R9 lý do = mở đầu câu trả lời, gọn (≤ 401 ký tự)", 0 < len(E.refusal_reason(T190, G190)) <= 401
      and E.refusal_reason(T190, G190).startswith("Tôi không dựng được video Bài 14"))
normal = {
    "N1 «Done. … I cannot verify» ở câu thứ hai": (
        "Done. I created 3 files: a.py, b.py, c.py. Note: I cannot verify the GPU path, check it later.", "Create files"),
    "N2 «không chỉ tạo được»": ("Tôi không chỉ tạo được video mà còn viết mô tả SEO.", "Tạo video"),
    "N3 tóm tắt bình thường": ("Here is the summary of the article: the market grew 5%.", "Summarize the article"),
    "N4 câu hỏi «… được không?» → «Không thể» là câu trả lời":
        ("Không thể, vì YouTube giới hạn 15 phút với kênh chưa xác minh.", "Kênh chưa xác minh đăng video 20 phút được không?"),
    "N5 đã xong, «không thể» ở câu sau": (
        "Đã xong: tôi đã tạo thư mục sd6v với 6 thư mục con. Phần Muse không thể chạy vì thiếu khoá.", "Tạo thư mục"),
    "N6 «không cần … được»": ("Bạn không cần làm gì thêm được nữa, mọi thứ đã chạy xong.", "Kiểm tra"),
    "N7 rỗng": ("", "x"),
    "N8 es bình thường": ("Listo: el guion tiene 1.200 palabras y no hay errores.", "Escribe el guion"),
}
for label, (rep, goal) in normal.items():
    why = E.refusal_reason(rep, goal)
    check(label, not why, why)
check("R10 mọi mẫu ở MỘT bảng (_REFUSAL_PATTERNS) biên dịch được",
      isinstance(E._REFUSAL_PATTERNS, tuple) and len(E._REFUSAL_PATTERNS) >= 8 and E._REFUSAL_RE.pattern)

print("── X. _execute_agent ──────────────────────────────────────")
from tubecli.core.brain import AgentBrain  # noqa: E402


class _Agent:
    id, name = "ag1", "Orchestrator"

    def to_dict(self):
        return {"id": self.id, "name": self.name, "model": "fake"}


E._resolve_agent = lambda task: _Agent()
E._select_skills = lambda goal, agent: []
E._get_skill = lambda sid: None
BRAIN = {"r": {}}
AgentBrain.chat_targeted = staticmethod(lambda *a, **k: dict(BRAIN["r"]))


def run_agent(task):
    steps = []

    def report(name, status, message="", label="", progress=None):
        steps.append((name, status, message))
    try:
        return asyncio.run(E._execute_agent(task, report, lambda: False)), steps, None
    except Exception as e:      # noqa: BLE001
        return None, steps, e


BRAIN["r"] = {"reply": T190, "action": None}
out, steps, err = run_agent({"goal": G190, "title": "Bài 14"})
check("X1 trả lời thẳng từ chối ⇒ AgentRefused", isinstance(err, E.AgentRefused), (out, err))
check("X2 …lỗi nói rõ «The agent did not do the task — Tôi không dựng được…»",
      err is not None and str(err).startswith("The agent did not do the task — Tôi không dựng được video Bài 14"), err)
check("X3 …bước «reason» kết thúc bằng error", steps and steps[-1][0] == "reason" and steps[-1][1] == "error", steps)
BRAIN["r"] = {"reply": "Here is the plan: 1) write the script 2) render.", "action": None}
out, steps, err = run_agent({"goal": "Plan the video", "title": "Plan"})
check("X4 trả lời thường ⇒ trả về nguyên văn, không lỗi", err is None and out.startswith("Here is the plan"), (out, err))
BRAIN["r"] = {"reply": "Running it now", "action": "run_skill", "skill_id": "ghost-skill"}
out, steps, err = run_agent({"goal": "Do X", "title": "X"})
check("X5 skill không tồn tại ⇒ AgentRefused (trước đây trả reply ⇒ review)",
      isinstance(err, E.AgentRefused) and "ghost-skill" in str(err), (out, err))

print("── W. worker: AgentRefused ⇒ FAILED ───────────────────────")
import tubecli.extensions.codex.worker as WMod  # noqa: E402

WMod.codex_manager = cm


async def _refuse(task, report, is_cancelled):
    raise E.AgentRefused("The agent did not do the task — Tôi không dựng được video Bài 14.")

WMod.execute_task = _refuse
w = cm.create_task(goal="Dựng video Bài 14", title="Bài 14", created_by="user", approval_required=False)
got = cm.claim_next()
check("W0 claim task", got and got["id"] == w["id"], got)
worker = WMod.CodexWorker()
worker._sem = None
asyncio.run(worker._run_one(got))
wt = cm.get_task(w["id"])
check("W1 task → failed (không phải review)", wt["status"] == CMod.FAILED, wt["status"])
check("W2 error mang lý do của agent", "Tôi không dựng được video Bài 14" in str(wt.get("error")), wt.get("error"))

print("── B. bulk_accept_published ───────────────────────────────")
HOOKS = []
cm.on_accept("content_video.plan", lambda task, actor: HOOKS.append(("plan", task["id"])))
cm.on_accept("content_video.auto", lambda task, actor: HOOKS.append(("auto", task["id"])))
cm.on_accept("content_video.render", lambda task, actor: HOOKS.append(("render", task["id"])))


def to_review(kind, published=None, extra_ck=None, title=""):
    t = cm.create_task(goal=title or kind, title=title or kind, created_by="content_video", approval_required=False)
    cm.append_event(t["id"], "log", "kind", data={"kind": kind, "task_id": t["id"]})
    if extra_ck:
        cm.append_event(t["id"], "log", "checkpoint", data={"checkpoint": extra_ck})
    if published is not None:
        cm.append_event(t["id"], "log", "checkpoint", data={"checkpoint": {"published": published}})
    got = cm.claim_next()
    assert got and got["id"] == t["id"], got
    cm.report_result(t["id"], "## rendered")
    return t


VID = "dQw4w9WgXcQ"
a1 = to_review("content_video.auto", {"video_id": VID, "url": f"https://youtu.be/{VID}"}, title="auto ok",
               extra_ck={"script": "…", "episode_id": "e1"})
a2 = to_review("content_video.auto", {"video_id": "", "url": "https://support.google.com/youtube?p=upload_videos"},
               title="auto support link")
a3 = to_review("content_video.plan", {"video_id": VID, "url": f"https://youtu.be/{VID}"}, title="plan")
a4 = to_review("content_video.render", {"video_id": "AbCdEfGhIj0"}, title="render ok")
a5 = to_review("content_video.auto", None, title="auto not published")
a6 = to_review("content_video.auto", {"video_id": "not-a-real-id-xx"}, title="auto bad id")
ids = {x["id"] for x in (a1, a2, a3, a4, a5, a6)}
check("B0 cả sáu ở review", all(cm.get_task(i)["status"] == CMod.REVIEW for i in ids))
check("B1 checkpoint gộp nhiều sự kiện (bản sau thắng, khoá cũ còn)",
      cm.checkpoint_of(a1["id"]).get("episode_id") == "e1" and cm.checkpoint_of(a1["id"])["published"]["video_id"] == VID)
check("B2 published_video: id hợp lệ → có; link support.google.com → không; id sai dạng → không",
      cm.published_video(a1["id"]).get("video_id") == VID and cm.published_video(a2["id"]) == {}
      and cm.published_video(a6["id"]) == {})
dry = cm.bulk_accept_published(dry_run=True)
check("B3 dry_run: đúng 2 task (auto ok + render ok)",
      dry["matched"] == 2 and {t["id"] for t in dry["tasks"]} == {a1["id"], a4["id"]}, dry)
check("B4 dry_run không đổi trạng thái", all(cm.get_task(i)["status"] == CMod.REVIEW for i in ids))
res = cm.bulk_accept_published(actor="tester")
check("B5 chạy thật: nhận 2", res["accepted"] == 2 and not res["dry_run"], res)
check("B6 auto ok + render ok → done", cm.get_task(a1["id"])["status"] == CMod.DONE
      and cm.get_task(a4["id"])["status"] == CMod.DONE)
check("B7 plan (có hook dựng + đăng) / link trợ giúp / chưa đăng / id sai → vẫn review",
      all(cm.get_task(x["id"])["status"] == CMod.REVIEW for x in (a2, a3, a5, a6)))
check("B8 KHÔNG hook on_accept nào chạy (không dựng / đăng lần hai)", HOOKS == [], HOOKS)
check("B9 bấm lần hai = 0", cm.bulk_accept_published()["accepted"] == 0)
check("B10 sự kiện ghi link đã đăng",
      any(f"https://youtu.be/{VID}" in (e.get("message") or "") for e in cm.get_events(a1["id"], limit=0)))
check("B11 BULK_ACCEPT_KINDS không có plan", "content_video.plan" not in CMod.BULK_ACCEPT_KINDS)

print("── C. bulk_close_failed ───────────────────────────────────")


def to_failed(title, days_ago):
    t = cm.create_task(goal=title, title=title, created_by="user", approval_required=False)
    got = cm.claim_next()
    assert got and got["id"] == t["id"], got
    cm.report_failure(t["id"], f"boom {title}")
    when = (datetime.datetime.now().astimezone() - datetime.timedelta(days=days_ago)).isoformat()
    with cm._lock:
        cm._tasks[t["id"]]["finished_at"] = when
        cm._save()
    return t


f_old = to_failed("old fail", 10)
f_mid = to_failed("mid fail", 5)
f_new = to_failed("new fail", 0.2)
check("C0 W-task (từ chối) cũng đang failed — tính theo finished_at thật (vừa xong)",
      cm.get_task(w["id"])["status"] == CMod.FAILED)
dry = cm.bulk_close_failed(7, dry_run=True)
check("C1 dry_run 7 ngày: chỉ task 10 ngày", dry["matched"] == 1 and dry["tasks"][0]["id"] == f_old["id"], dry)
check("C2 dry_run không đổi gì", cm.get_task(f_old["id"])["status"] == CMod.FAILED)
res = cm.bulk_close_failed(3, actor="tester")
check("C3 chạy thật 3 ngày: đóng 10 + 5 ngày", res["closed"] == 2
      and {t["id"] for t in res["tasks"]} == {f_old["id"], f_mid["id"]}, res)
check("C4 → cancelled; task mới vẫn failed",
      cm.get_task(f_old["id"])["status"] == CMod.CANCELLED and cm.get_task(f_mid["id"])["status"] == CMod.CANCELLED
      and cm.get_task(f_new["id"])["status"] == CMod.FAILED)
check("C5 dữ liệu còn: error giữ nguyên, có closed_at",
      cm.get_task(f_old["id"]).get("error") == "boom old fail" and cm.get_task(f_old["id"]).get("closed_at"))
check("C6 task review cũ không bị đụng", cm.get_task(a2["id"])["status"] == CMod.REVIEW)
rt = cm.retry(f_old["id"], actor="tester")
check("C7 task đã đóng vẫn Chạy lại được", rt["status"] in (CMod.QUEUED, CMod.BACKLOG), rt["status"])
cm.cancel(f_old["id"], actor="tester")          # ra khỏi hàng đợi, kẻo phần H nhận nhầm nó
for bad in (0, -1, "x", 99999):
    try:
        cm.bulk_close_failed(bad)
        check(f"C8 N={bad!r} bị từ chối", False, "no error")
    except ValueError:
        check(f"C8 N={bad!r} bị từ chối", True)

print("── H. routes ──────────────────────────────────────────────")
try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import tubecli.extensions.codex.routes as RMod

    RMod.codex_manager = cm
    app = FastAPI()
    app.include_router(RMod.router)
    client = TestClient(app)          # không `with` ⇒ không chạy startup (không bật worker thật)
    prefix = RMod.router.prefix or ""
    h_pub = to_review("content_video.auto", {"video_id": "ZZZZZZZZZZZ"}, title="route auto")
    r = client.post(prefix + "/bulk/accept-published", json={"dry_run": True})
    check("H1 accept dry_run → 200, matched 1", r.status_code == 200 and r.json()["matched"] == 1, r.text)
    r = client.post(prefix + "/bulk/accept-published", json={})
    check("H2 accept → accepted 1, task done", r.status_code == 200 and r.json()["accepted"] == 1
          and cm.get_task(h_pub["id"])["status"] == CMod.DONE, r.text)
    to_failed("route fail", 30)
    r = client.post(prefix + "/bulk/close-failed", json={"older_than_days": 14, "dry_run": True})
    check("H3 close dry_run 14 ngày → matched 1", r.status_code == 200 and r.json()["matched"] == 1, r.text)
    r = client.post(prefix + "/bulk/close-failed", json={"older_than_days": 0})
    check("H4 close N=0 → 400", r.status_code == 400, r.text)
    r = client.post(prefix + "/bulk/close-failed", json={"older_than_days": 14})
    check("H5 close → closed 1", r.status_code == 200 and r.json()["closed"] == 1, r.text)
except ImportError as e:
    print(f"  skip routes ({e})")

print()
print(f"{checks - len(failures)}/{checks} passed")
if failures:
    for f in failures:
        print("  -", f)
    sys.exit(1)
