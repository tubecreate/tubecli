# -*- coding: utf-8 -*-
"""Dọn ô review của Bảng việc (28/11/2026 — agent quản lý contabo: 92 task nằm review, phần lớn không có gì để duyệt).

Run:  PYTHONIOENCODING=utf-8 python -X utf8 tests/board_triage_test.py

  L. nhãn (meta.labels), set_result, close_tasks, close_safety
  U. lượt video KHÔNG ra sản phẩm (⚠ OFF-NICHE / ⚠ DUPLICATE TOPIC / «Nothing was rendered» / đăng bị chặn mà không có
     file) ⇒ FAILED + nhãn, không vào review; có video thì vẫn review; task kế hoạch không đổi
  N. agent chỉ trả lời chữ: câu #186 thật («…nhưng chưa thể tải lên được… Bạn cần kết nối Drive trước») ⇒ hỏng + nhãn
     NEEDS_INPUT; kết quả thật kết bằng «let me know» / «vui lòng góp ý» KHÔNG bị bắt
  B. bulk close-unproductive — chỉ task review không sản phẩm (video + trả lời chữ), có video / kế hoạch giữ nguyên;
     dry_run không đổi gì; older_than_days
  D. trùng chủ đề — bản trùng của bản đã đăng / có video / làm trước ⇒ DUPLICATE_OF #n; bản đã có video chỉ gắn nhãn
     (include_rendered mới đóng); khác agent không tính; bản đã đăng không bao giờ là bản thừa
  P. resolve-publish — API của kênh, rồi tìm kiếm công khai ĐÚNG kênh + ngày ±3; khác kênh / lệch ngày / không biết kênh /
     video của task khác ⇒ PUBLISH_UNVERIFIED; tìm thấy ⇒ bulk accept-published nhận được; dry_run không ghi gì
  S. đóng không cần duyệt — safe_close / is_dangerous / tool_approval(safe) / connector.call: task không video ⇒ chạy
     luôn, task có video ⇒ vẫn link duyệt, Codex làm model vẫn bị chặn
  H. routes — /bulk/close-unproductive, /bulk/close-duplicates, /bulk/resolve-publish, /tasks/{id}/resolve-publish,
     /tasks/{id}/close-safety, PUT /tasks/{id}/published

Kho tạm (không đụng tasks.json / sổ ngách / sổ trần ngày thật), không Telegram, không gọi YouTube / model / HTTP thật.
"""
import asyncio
import datetime
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

TMP = tempfile.mkdtemp(prefix="board-triage-")
import tubecli.extensions.content_video.niche_memory as NM  # noqa: E402

NM._store_path = lambda: Path(TMP) / "niche_memory.json"
NM.seed_from_tasks = lambda *a, **k: 0
NM._task_alive = lambda task_id: True

import tubecli.extensions.codex.manager as CMod  # noqa: E402

CMod.CODEX_DATA_DIR = TMP
CMod.TASKS_FILE = os.path.join(TMP, "tasks.json")
CMod.EVENTS_DIR = os.path.join(TMP, "events")
cm = CMod.CodexManager()
cm.notifications_enabled = False
cm.post_to_chat = lambda *a, **k: None
CMod.codex_manager = cm

from tubecli.extensions.content_video import autopublish as AP  # noqa: E402
from tubecli.extensions.content_video import board_triage as BT  # noqa: E402
from tubecli.extensions.content_video import publish_jobs as PJ  # noqa: E402
import tubecli.extensions.content_video.publish_schedule as PS  # noqa: E402

PJ._store_path = lambda: Path(TMP) / "publish_jobs.json"
PJ.start_worker = lambda: None
AP._store_path = lambda: Path(TMP) / "autopublish.json"
PS._store_path = lambda: Path(TMP) / "publish_slots.json"
from tubecli.core.agent import agent_manager  # noqa: E402

agent_manager.get_agent = lambda aid: None
for _k in BT.KINDS:
    cm.on_result(_k, BT.result_hook)

failures = []
checks = 0


def check(label, ok, detail=""):
    global checks
    checks += 1
    print(("  ok   " if ok else "  FAIL ") + label + ("" if ok else f" — {str(detail)[:300]}"))
    if not ok:
        failures.append(f"{label}: {detail}")


VIDEO = os.path.join(TMP, "episode_1_pipeline_export.mp4")
Path(VIDEO).write_bytes(b"\0" * 64)


def ago(days):
    return (datetime.datetime.now().astimezone() - datetime.timedelta(days=days)).isoformat()


def mk(title, kind="content_video.auto", agent="agA", status="review", result="", steps=None, ck=None, days=2,
       goal=""):
    t = cm.create_task(goal=goal or f"Auto publish for {agent}", title=title, created_by="autopublish",
                       assignee_type="agent", assignee_id=agent, assignee_name=agent, approval_required=False,
                       lane="video" if kind else "")
    tid = t["id"]
    if kind:
        cm.append_event(tid, "log", "kind", actor="test", data={"kind": kind})
        cm.set_meta(tid, {"kind": kind})
    if ck:
        cm.append_event(tid, "log", "checkpoint", actor="test", data={"checkpoint": ck})
    with cm._lock:
        s = cm._tasks[tid]
        s.update(status=status, result=result, steps=steps or [], finished_at=ago(days), updated_at=ago(days))
        cm._save()
    return cm.get_task(tid)


def st(tid):
    return (cm.get_task(tid) or {}).get("status")


def labels(tid):
    return cm.labels_of(cm.get_task(tid))


OFF = ("⚠ OFF-NICHE SOURCES — only 0 of 30 sources fit the niche (at least 3 needed)\n\n- **Why**: Nothing was "
       "written.\n- **Nothing was rendered or published.** Fix the agent's niche settings or its sources, then Retry.")
DUP = ("⚠ DUPLICATE TOPIC — «You Are the Light of the World» was already made as task #221\n\n- **Nothing was "
       "rendered or published.** Fix the agent's niche settings or its sources, then Retry.")
RENDERED = f"## ✅ Auto publish rendered — 60 shots\n\n- **Video**: `{VIDEO}`\n- **Title**: X"
BLOCKED_STEPS = [{"name": "render", "status": "success"},
                 {"name": "publish", "status": "error", "message": "Publishing stopped: channel “R” matches no token"}]

print("── L. nhãn / kết quả / đóng / an toàn ─────────────────────")
t = mk("Label me", status="review", result="x")
cm.set_labels(t["id"], add=["A", "B", "A"])
check("L1 thêm nhãn, không trùng", labels(t["id"]) == ["A", "B"], labels(t["id"]))
cm.set_labels(t["id"], add=["DUPLICATE_OF #3"], remove=["A"])
cm.set_labels(t["id"], add=["DUPLICATE_OF #9"], remove_prefix="DUPLICATE_OF")
check("L2 gỡ theo tên + theo tiền tố", labels(t["id"]) == ["B", "DUPLICATE_OF #9"], labels(t["id"]))
cm.set_labels(t["id"], remove=["B", "DUPLICATE_OF #9"])
check("L3 hết nhãn ⇒ meta.labels bị xoá", "labels" not in (cm.get_task(t["id"]).get("meta") or {}),
      cm.get_task(t["id"]).get("meta"))
cm.set_result(t["id"], "new text", actor="tester")
check("L4 set_result đổi chữ, không đổi trạng thái", cm.get_task(t["id"])["result"] == "new text" and st(t["id"]) == "review")
safe, why = cm.close_safety(t["id"])
check("L5 review, không video, không đăng ⇒ an toàn", safe and not why, why)
tv = mk("Has video", result=RENDERED, ck={"video_path": VIDEO})
check("L6 có video ⇒ KHÔNG an toàn", cm.close_safety(tv["id"]) == (False, "it has a video file"), cm.close_safety(tv["id"]))
tp = mk("Published bad link", result="## x\n\n- **Published**: https://support.google.com/youtube?p=upload_videos",
        ck={"published": {"url": "https://support.google.com/youtube?p=upload_videos", "video_id": ""}})
check("L7 từng đăng (link chưa xác minh) ⇒ KHÔNG an toàn", not cm.close_safety(tp["id"])[0], cm.close_safety(tp["id"]))
tr = mk("Running", status="running")
check("L8 đang chạy ⇒ KHÔNG an toàn", not cm.close_safety(tr["id"])[0])
closed = cm.close_tasks([{"id": t["id"], "reason": "no product", "labels": ["UNPRODUCTIVE"]}], "tester", "Closed")
check("L9 close_tasks ⇒ CANCELLED + close_reason + nhãn", st(t["id"]) == "cancelled" and len(closed) == 1
      and cm.get_task(t["id"])["meta"].get("close_reason") == "no product" and "UNPRODUCTIVE" in labels(t["id"]))
check("L10 đóng lần hai = 0 (không ghi lại)", cm.close_tasks([{"id": t["id"]}], "tester", "Closed") == [])

print("── U. lượt video không ra sản phẩm ⇒ FAILED ──────────────")
u1 = mk("Auto publish: Deep Biblical", status="running")
cm.report_result(u1["id"], OFF)
u = cm.get_task(u1["id"])
check("U1 ⚠ OFF-NICHE ⇒ failed (không review)", u["status"] == "failed", u["status"])
check("U2 …error = dòng tiêu đề, kết quả còn nguyên để đọc", u["error"].startswith("⚠ OFF-NICHE SOURCES")
      and u["result"] == OFF, u["error"])
check("U3 …nhãn UNPRODUCTIVE", "UNPRODUCTIVE" in labels(u1["id"]), labels(u1["id"]))
check("U4 …Retry vẫn được (failed → queued)", "queued" in CMod.TRANSITIONS["failed"])
u2 = mk("You Are the Light of the World", status="running")
cm.report_result(u2["id"], DUP)
check("U5 ⚠ DUPLICATE TOPIC ⇒ failed + DUPLICATE_OF #221 + meta.duplicate_of",
      st(u2["id"]) == "failed" and "DUPLICATE_OF #221" in labels(u2["id"])
      and cm.get_task(u2["id"])["meta"].get("duplicate_of") == 221, (st(u2["id"]), labels(u2["id"])))
u3 = mk("Rendered fine", status="running", ck={"video_path": VIDEO})
cm.report_result(u3["id"], RENDERED)
check("U6 có file video ⇒ vẫn vào review", st(u3["id"]) == "review" and not labels(u3["id"]), st(u3["id"]))
u4 = mk("Blocked no file", status="running", steps=[dict(s) for s in BLOCKED_STEPS])
with cm._lock:
    cm._tasks[u4["id"]]["steps"] = [{"name": "publish", "status": "error", "message": "Publishing stopped: no token"}]
cm.report_result(u4["id"], "## ⚠️ Auto publish — completed with warning\n\n- **Title**: Blocked")
check("U7 đăng bị chặn mà không có file video ⇒ failed", st(u4["id"]) == "failed"
      and cm.get_task(u4["id"])["error"].startswith("Publishing was blocked and there is no video file"),
      cm.get_task(u4["id"]).get("error"))
u5 = mk("Blocked but rendered", status="running", ck={"video_path": VIDEO}, steps=[dict(s) for s in BLOCKED_STEPS])
cm.report_result(u5["id"], RENDERED + "\n- ⚠️ Upload to YouTube failed")
check("U8 đăng bị chặn NHƯNG có video (#226) ⇒ vẫn review (đăng tay được)", st(u5["id"]) == "review", st(u5["id"]))
u6 = mk("Plan held", kind="content_video.plan", status="running")
cm.report_result(u6["id"], OFF)
check("U9 task kế hoạch (duyệt kịch bản) lạc ngách ⇒ vẫn review như cũ", st(u6["id"]) == "review", st(u6["id"]))
try:
    cm.report_result(u1["id"], OFF)
    check("U10 báo kết quả lần hai cho task đã hỏng ⇒ bị từ chối như mọi task hỏng", False)
except ValueError:
    check("U10 báo kết quả lần hai cho task đã hỏng ⇒ bị từ chối như mọi task hỏng", st(u1["id"]) == "failed")
def _broken_hook(task, res):
    raise RuntimeError("hook broke")


cm.on_result("content_video.auto", _broken_hook)
u7 = mk("Hook breaks", status="running")
cm.report_result(u7["id"], OFF)
check("U11 hook hỏng ⇒ task vào review như cũ (không mất kết quả)", st(u7["id"]) == "review")
cm.on_result("content_video.auto", BT.result_hook)

print("── N. agent chỉ trả lời chữ ──────────────────────────────")
from tubecli.extensions.codex import executor as E  # noqa: E402

T186 = ("Tôi đã kiểm tra đúng việc bạn yêu cầu, nhưng chưa thể tải lên được vì có 2 trở ngại thực tế:\n\nFile không tồn "
        "tại ở đường dẫn đã cho.\n\nGoogle Drive chưa được kết nối.\n\nBạn cần kết nối Drive trước:\n\nSau khi bạn kết "
        "nối xong và đặt file vào một đường dẫn trong home directory, tôi sẽ tải nó lên.")
G186 = "Chỉ làm đúng một việc: tải file ls14_voice.ogg lên Google Drive. Xong thì báo lại file id và link Drive."
check("N1 #186 thật: là lời từ chối («nhưng chưa thể … được»)", bool(E.refusal_reason(T186, G186)))
ask = E.needs_input_reason(T186, G186, refused=True)
check("N2 #186 thật: xin bổ sung («Bạn cần kết nối Drive trước»)", ask.startswith("Bạn cần kết nối Drive"), ask)
for label, rep in {
    "N3 en «but I couldn't»": "I checked the folder, but I couldn't find the file you named.",
    "N4 en needs info": "I need more information: which channel should this go to?",
}.items():
    why = E.refusal_reason(rep, "Upload the file")
    nd = E.needs_input_reason(rep, "Upload the file", refused=bool(why))
    check(label, bool(why or nd), (why, nd))
for label, rep in {
    "N5 xong, kết «let me know»": "Done — the script has 1,200 words. Let me know if you want a shorter one.",
    "N6 xong, kết «vui lòng góp ý»": "Đã xong kịch bản 1.200 chữ. Vui lòng góp ý nếu bạn muốn sửa.",
    "N7 xong, nhắc «bạn cần» ở đoạn sau": "Đã tải lên: https://drive.google.com/file/d/x. Lần sau bạn cần đổi tên file.",
}.items():
    check(label + " ⇒ không bị bắt", not E.refusal_reason(rep, "Do it") and not E.needs_input_reason(rep, "Do it"),
          (E.refusal_reason(rep, "Do it"), E.needs_input_reason(rep, "Do it")))
check("N8 việc là câu hỏi ⇒ không coi là xin bổ sung",
      not E.needs_input_reason("Bạn cần kết nối Drive trước.", "Tải file lên Drive được không?"))
from tubecli.core.brain import AgentBrain  # noqa: E402


class _Agent:
    id, name = "ag1", "Video Agent"

    def to_dict(self):
        return {"id": self.id, "name": self.name, "model": "fake"}


E._resolve_agent = lambda task: _Agent()
E._select_skills = lambda goal, agent: []
E._get_skill = lambda sid: None
BRAIN = {"r": {}}
AgentBrain.chat_targeted = staticmethod(lambda *a, **k: dict(BRAIN["r"]))
gt = mk("Tải giọng đọc LS.14 lên Google Drive", kind="", status="running", goal=G186)


def run_agent(task):
    steps = []
    try:
        return asyncio.run(E._execute_agent(task, lambda n, s, m="", label="", progress=None: steps.append((n, s, m)),
                                            lambda: False)), steps, None
    except Exception as e:      # noqa: BLE001
        return None, steps, e


BRAIN["r"] = {"reply": T186, "action": None}
out, steps, err = run_agent(cm.get_task(gt["id"]))
check("N9 _execute_agent: #186 ⇒ AgentRefused (task sẽ hỏng, không review)", isinstance(err, E.AgentRefused), (out, err))
check("N10 …task mang nhãn NEEDS_INPUT", "NEEDS_INPUT" in labels(gt["id"]), labels(gt["id"]))
check("N11 …lỗi nói rõ cần gì", err is not None and "Bạn cần kết nối Drive" in str(err), err)
BRAIN["r"] = {"reply": "Để làm việc này, vui lòng cung cấp tên kênh YouTube.", "action": None}
gt2 = mk("Đăng video", kind="", status="running", goal="Đăng video mới lên kênh")
out, steps, err = run_agent(cm.get_task(gt2["id"]))
check("N12 chỉ xin bổ sung (không từ chối) ⇒ cũng hỏng + NEEDS_INPUT", isinstance(err, E.AgentRefused)
      and "needs more from you" in str(err) and "NEEDS_INPUT" in labels(gt2["id"]), (err, labels(gt2["id"])))

print("── B. bulk close-unproductive ────────────────────────────")
for tid in list(cm._tasks):
    with cm._lock:
        cm._tasks[tid]["status"] = "done"
cm._save()
b_off = mk("Auto publish: Deep Biblical Echoes", result=OFF, days=5)
b_dup = mk("Ask Seek Knock", result=DUP.replace("#221", "#213"), days=5)
b_vid = mk("Real video", result=RENDERED, ck={"video_path": VIDEO}, days=5)
b_plan = mk("Script held", kind="content_video.plan", result=OFF, days=5)
DR = [{"name": "resolve", "status": "success"}, {"name": "select_skills", "status": "success"},
      {"name": "reason", "status": "success", "message": "Action: direct reply"}]
b_reply = mk("Tải giọng đọc LS.14 lên Google Drive", kind="", result=T186, steps=DR, days=5, goal=G186)
b_ok = mk("Write a summary", kind="", result="Here is the summary: the market grew 5%.", steps=DR, days=5,
          goal="Summarize the article")
b_new = mk("Auto publish: fresh", result=OFF, days=0.1)
dry = BT.bulk_close_unproductive(older_than_days=1, dry_run=True)
ids = {h["id"] for h in dry["tasks"]}
check("B1 dry_run liệt kê: lạc ngách + trùng + trả lời chữ xin bổ sung", ids == {b_off["id"], b_dup["id"], b_reply["id"]},
      [h["title"] for h in dry["tasks"]])
check("B2 …dry_run không đổi gì", all(st(x) == "review" for x in ids))
check("B3 …có video / kế hoạch / kết quả thật / mới hơn 1 ngày KHÔNG vào", not ids & {b_vid["id"], b_plan["id"],
                                                                                    b_ok["id"], b_new["id"]})
real = BT.bulk_close_unproductive(older_than_days=1, actor="contabo-agent")
check("B4 chạy thật ⇒ 3 task CANCELLED", real["closed"] == 3 and all(st(x) == "cancelled" for x in ids), real)
check("B5 …nhãn đúng: UNPRODUCTIVE / DUPLICATE_OF #213 / NEEDS_INPUT",
      "UNPRODUCTIVE" in labels(b_off["id"]) and "DUPLICATE_OF #213" in labels(b_dup["id"])
      and "NEEDS_INPUT" in labels(b_reply["id"]), (labels(b_off["id"]), labels(b_dup["id"]), labels(b_reply["id"])))
check("B6 …lý do đóng ghi vào meta.close_reason", (cm.get_task(b_off["id"])["meta"].get("close_reason") or "")
      .startswith("⚠ OFF-NICHE"))
check("B7 …task có video vẫn nằm review", st(b_vid["id"]) == "review" and st(b_plan["id"]) == "review")
check("B8 bấm lần hai = 0", BT.bulk_close_unproductive(older_than_days=1)["closed"] == 0)
try:
    BT.bulk_close_unproductive(older_than_days=-1)
    check("B9 older_than_days âm ⇒ lỗi 400", False)
except PJ.JobError as e:
    check("B9 older_than_days âm ⇒ lỗi 400", e.status == 400)

print("── D. trùng chủ đề ───────────────────────────────────────")
for tid in list(cm._tasks):
    with cm._lock:
        cm._tasks[tid]["status"] = "cancelled"
cm._save()
d_pub = mk("Ask, Seek, Knock: What Matthew 7:7 Really Means", status="done", days=8,
           ck={"published": {"video_id": "AAAAAAAAAAA", "url": "https://youtu.be/AAAAAAAAAAA"}})
d1 = mk("Ask, Seek, Knock: What Jesus Really Meant in Matthew 7", days=6)
d2 = mk("You Are the Light of the World", result=RENDERED, ck={"video_path": VIDEO}, days=4)
d3 = mk("You Are the Light of the World", days=2)
d4 = mk("You Are the Light of the World", agent="agB", days=2)
d5 = mk("Do Unto Others: What Matthew 7:12 Really Means", days=3)
d6 = mk("You Are the Light of the World", result=RENDERED, ck={"video_path": VIDEO}, days=1)
scan = {h["id"]: h for h in BT.scan_duplicates()}
check("D1 bản chưa đăng của chủ đề đã đăng ⇒ trùng #<bản đã đăng>", scan.get(d1["id"], {}).get("duplicate_of")
      == d_pub["seq"], scan.get(d1["id"]))
check("D2 bản không video ⇒ trùng bản đã có video", scan.get(d3["id"], {}).get("duplicate_of") == d2["seq"],
      scan.get(d3["id"]))
check("D3 hai bản cùng có video ⇒ bản làm SAU là bản trùng", scan.get(d6["id"], {}).get("duplicate_of") == d2["seq"]
      and d2["id"] not in scan, (scan.get(d6["id"]), d2["id"] in scan))
check("D4 khác agent không tính; câu Kinh Thánh khác (7:12 ≠ 7:7) không tính", d4["id"] not in scan
      and d5["id"] not in scan)
check("D5 bản đã đăng không bao giờ là bản thừa", d_pub["id"] not in scan)
dry = BT.bulk_close_duplicates(dry_run=True)
check("D6 dry_run: liệt kê, không gắn nhãn, không đóng", dry["matched"] == 3 and not labels(d1["id"])
      and st(d1["id"]) == "review", dry)
real = BT.bulk_close_duplicates(actor="contabo-agent")
check("D7 chạy thật: 3 nhãn, đóng 2 bản KHÔNG video", real["labelled"] == 3 and real["closed"] == 2
      and st(d1["id"]) == "cancelled" and st(d3["id"]) == "cancelled", real)
check("D8 …bản trùng ĐÃ có video chỉ gắn nhãn, vẫn review", st(d6["id"]) == "review"
      and f"DUPLICATE_OF #{d2['seq']}" in labels(d6["id"]), (st(d6["id"]), labels(d6["id"])))
real2 = BT.bulk_close_duplicates(include_rendered=True)
check("D9 include_rendered=true ⇒ đóng cả bản đã dựng", st(d6["id"]) == "cancelled" and real2["closed"] == 1, real2)
check("D10 meta.duplicate_of = số task gốc", cm.get_task(d1["id"])["meta"].get("duplicate_of") == d_pub["seq"])

print("── P. resolve-publish ────────────────────────────────────")
for tid in list(cm._tasks):
    with cm._lock:
        cm._tasks[tid]["status"] = "cancelled"
cm._save()
HELP = "https://support.google.com/youtube?p=upload_videos&hl=en"
PUB_STEPS = [{"name": "publish", "status": "success", "message": "published via YouTube Studio",
              "ended_at": "2026-11-07T04:44:35+01:00"}]


def pub_task(title, yt_title, channel="Radhika Singh", days=20):
    res = (f"## ⚠️ Auto publish rendered\n\n- **Published**: {HELP} (public) → {channel}\n- **Video**: `{VIDEO}`\n"
           f"- **Title on YouTube**: {yt_title}\n- **Title**: {title}")
    return mk(title, result=res, steps=[dict(s) for s in PUB_STEPS], days=days,
              ck={"video_path": VIDEO, "published": {"video_id": "", "url": HELP, "title": yt_title,
                                                     "channel_name": channel, "channel_id": ""}})


CALLS = {"api": [], "search": []}
API_ROWS = {"rows": None}
SEARCH_ROWS = {"rows": []}
BT.API_VIDEOS = lambda cid, name, tid: (CALLS["api"].append((cid, name)), API_ROWS["rows"])[1]
BT.SEARCH = lambda q, n=15: (CALLS["search"].append(q), list(SEARCH_ROWS["rows"]))[1]
YT = "How to Stop Overthinking: The Weight She Learned to Put Down"
p1 = pub_task("The Weight She Learned to Put Down", YT)
check("P1 needs_resolve: ghi «Published» mà link không phải video", BT.needs_resolve(cm.get_task(p1["id"])))
API_ROWS["rows"] = [{"id": "vidAPI00001", "title": YT, "published_at": "2026-11-07T03:50:00Z"},
                    {"id": "vidOTHER001", "title": "Another story", "published_at": "2026-11-06T03:50:00Z"}]
dry = BT.resolve_publish(p1["id"], dry_run=True)
check("P2 dry_run: tìm thấy qua API, không ghi gì", dry["status"] == "found" and dry["url"] == "https://youtu.be/vidAPI00001"
      and not cm.published_video(p1["id"]), dry)
r = BT.resolve_publish(p1["id"], actor="contabo-agent")
check("P3 tìm thấy ⇒ checkpoint.published có id thật", cm.published_video(p1["id"]).get("video_id") == "vidAPI00001", r)
check("P4 …meta.published_url + dòng Published trong kết quả", cm.get_task(p1["id"])["meta"].get("published_url")
      == "https://youtu.be/vidAPI00001" and "- **Published**: https://youtu.be/vidAPI00001" in cm.get_task(p1["id"])["result"]
      and HELP not in cm.get_task(p1["id"])["result"].split("\n")[2], cm.get_task(p1["id"])["result"][:300])
check("P5 …trạng thái giữ review (người / bulk accept quyết)", st(p1["id"]) == "review")
acc = cm.bulk_accept_published(actor="contabo-agent")
check("P6 bulk accept-published giờ nhận task này", st(p1["id"]) == "done" and acc["accepted"] == 1, acc)
check("P7 gọi lại task đã có link ⇒ already", BT.resolve_publish(p1["id"])["status"] == "already")

p2 = pub_task("Sara and the Saturday Stall", "Sara and the Saturday Stall: Stop Overthinking, Start Small")
API_ROWS["rows"] = None                       # kênh không có token API ở máy này (đúng ca Radhika)
SEARCH_ROWS["rows"] = [{"id": "vidSTRANGER", "title": "Sara and the Saturday Stall: Stop Overthinking, Start Small",
                        "channel": "Someone Else", "published_at": "20261107"},
                       {"id": "vidRADHIKA1", "title": "Sara and the Saturday Stall: Stop Overthinking, Start Small",
                        "channel": "Radhika Singh", "published_at": "20261107"}]
r = BT.resolve_publish(p2["id"])
check("P8 không token ⇒ tìm công khai, CHỈ nhận đúng kênh", r["status"] == "found" and r["video_id"] == "vidRADHIKA1"
      and r["how"] == "YouTube search", r)
p3 = pub_task("Lena's First Leaf", "How to Stop Overthinking: Lena's First Leaf")
SEARCH_ROWS["rows"] = [{"id": "vidSTRANGER", "title": "How to Stop Overthinking: Lena's First Leaf",
                        "channel": "Someone Else", "published_at": "20261107"}]
r = BT.resolve_publish(p3["id"])
check("P9 chỉ video kênh khác trùng tên ⇒ not_found + PUBLISH_UNVERIFIED", r["status"] == "not_found"
      and "PUBLISH_UNVERIFIED" in labels(p3["id"]), (r, labels(p3["id"])))
SEARCH_ROWS["rows"] = [{"id": "vidLATE0001", "title": "How to Stop Overthinking: Lena's First Leaf",
                        "channel": "Radhika Singh", "published_at": "20261125"}]
r = BT.resolve_publish(p3["id"])
check("P10 đúng kênh nhưng lệch ngày > 3 ngày ⇒ not_found", r["status"] == "not_found", r)
SEARCH_ROWS["rows"] = [{"id": "vidLENA0001", "title": "How to Stop Overthinking: Lena's First Leaf",
                        "channel": "Radhika Singh", "published_at": "20261108"}]
r = BT.resolve_publish(p3["id"])
check("P11 tìm lại được ⇒ gỡ nhãn PUBLISH_UNVERIFIED", r["status"] == "found"
      and "PUBLISH_UNVERIFIED" not in labels(p3["id"]), (r, labels(p3["id"])))
p4 = pub_task("Lena again", "How to Stop Overthinking: Lena's First Leaf")
r = BT.resolve_publish(p4["id"])
check("P12 video đã ghi cho task khác ⇒ không nhận", r["status"] == "not_found"
      and any("already recorded" in x for x in r["tried"]), r)
p5 = pub_task("No channel story", "No channel story on YouTube", channel="")
CALLS["search"].clear()
r = BT.resolve_publish(p5["id"])
check("P13 task không ghi kênh ⇒ KHÔNG tìm công khai (có thể là video người khác)", r["status"] == "not_found"
      and not CALLS["search"], (r, CALLS["search"]))
plan = mk("Plan", kind="content_video.plan", result="x")
try:
    BT.resolve_publish(plan["id"])
    check("P14 task kế hoạch ⇒ lỗi 400", False)
except PJ.JobError as e:
    check("P14 task kế hoạch ⇒ lỗi 400", e.status == 400 and e.code == "not_a_rendered_video")
never = mk("Never published", result=RENDERED, ck={"video_path": VIDEO})
try:
    BT.resolve_publish(never["id"])
    check("P15 chưa từng đăng ⇒ lỗi 409", False)
except PJ.JobError as e:
    check("P15 chưa từng đăng ⇒ lỗi 409", e.status == 409 and e.code == "not_published")
SEARCH_ROWS["rows"] = [{"id": "vidBULK0001", "title": "Bulk one on YouTube", "channel": "Radhika Singh",
                        "published_at": "20261107"}]
pb = pub_task("Bulk one", "Bulk one on YouTube")
st_ = BT.start_bulk_resolve(actor="contabo-agent", background=False)
check("P16 bulk (chạy nền) dò mọi task cần dò: tìm 1, không thấy 2", not st_["running"]
      and [x["task"] for x in st_["found"]] == [pb["seq"]] and len(st_["not_found"]) == 2, st_)
check("P17 GET tiến độ trả cùng số liệu", BT.bulk_resolve_status()["found"] == st_["found"])

print("── S. đóng không cần duyệt ───────────────────────────────")
from tubecli.extensions.codex_gpt import tools as T  # noqa: E402
from tubecli.core import claude_connector as CC  # noqa: E402

api = T.TOOLS["tubecli_api"]
s_safe = mk("Nothing here", result=OFF)
s_vid = mk("Video here", result=RENDERED, ck={"video_path": VIDEO})


def cancel_args(task):
    return {"method": "POST", "path": f"/api/v1/codex/tasks/{task['id']}/cancel"}


check("S1 safe_close: huỷ task không video ⇒ True", T.safe_close(api, cancel_args(s_safe)))
check("S2 safe_close: huỷ task CÓ video ⇒ False", not T.safe_close(api, cancel_args(s_vid)))
check("S3 safe_close: số task (#n) cũng được", T.safe_close(api, {"method": "POST",
                                                                   "path": f"/api/v1/codex/tasks/{s_safe['seq']}/cancel"}))
check("S4 safe_close: bulk close-unproductive ⇒ True", T.safe_close(api, {"method": "POST",
                                                                            "path": "/api/v1/codex/bulk/close-unproductive"}))
check("S5 safe_close: close-duplicates include_rendered ⇒ False",
      not T.safe_close(api, {"method": "POST", "path": "/api/v1/codex/bulk/close-duplicates",
                             "body": {"include_rendered": True}}))
check("S6 safe_close: DELETE task ⇒ False", not T.safe_close(api, {"method": "DELETE",
                                                                     "path": f"/api/v1/codex/tasks/{s_safe['id']}"}))
check("S7 is_dangerous vẫn coi «cancel» là nguy hiểm (lưới cũ giữ nguyên)", CC.is_dangerous(api, cancel_args(s_safe)))
check("S8 is_dangerous: close-duplicates include_rendered ⇒ nguy hiểm",
      CC.is_dangerous(api, {"method": "POST", "path": "/api/v1/codex/bulk/close-duplicates",
                            "body": {"include_rendered": True}}))
CALLED = []


async def fake_call_tool(name, args, app, approve, **k):
    CALLED.append(args["path"])
    return {"content": [{"type": "text", "text": "ok"}]}


real_call_tool = T.call_tool
T.call_tool = fake_call_tool
try:
    out = asyncio.run(CC.call("tubecli_api", cancel_args(s_safe), "write", False, None))
    check("S9 connector: huỷ task không video ⇒ chạy luôn, không link duyệt", "result" in out and CALLED, out)
    CALLED.clear()
    out = asyncio.run(CC.call("tubecli_api", cancel_args(s_vid), "write", False, None))
    check("S10 connector: huỷ task có video ⇒ vẫn needs_approval", "needs_approval" in out and not CALLED, out)
    out = asyncio.run(CC.call("tubecli_api", cancel_args(s_safe), "read", False, None))
    check("S11 connector chỉ-đọc vẫn không huỷ được", "result" in out and out["result"].get("isError")
          and not CALLED, out)
finally:
    T.call_tool = real_call_tool
SEEN = []


async def approve(tool, summary, args, **kw):
    SEEN.append(kw)
    return False, "declined in test", None


async def run_codex(args):
    return await T.call_tool("tubecli_api", args, None, approve)


SEEN.clear()
asyncio.run(run_codex(cancel_args(s_vid)))
check("S12 Codex GPT: huỷ task có video ⇒ hỏi chủ như cũ (không safe)", SEEN == [{}], SEEN)
SEEN.clear()
asyncio.run(run_codex(cancel_args(s_safe)))
check("S13 Codex GPT: huỷ task không video ⇒ approve(safe=True)", SEEN == [{"safe": True}], SEEN)
from tubecli.extensions.codex_gpt import service as SV  # noqa: E402

svc = SV.CodexGptService.__new__(SV.CodexGptService) if hasattr(SV, "CodexGptService") else None
if svc is not None:
    svc.llm_threads, svc.tool_session_ok, svc.subscribers = {"thr-llm"}, set(), []
    svc._thread_for_tool = lambda tool, args: args.get("_t")
    svc.state = lambda: {"settings": {}}
    ok, why, _ = asyncio.run(svc.tool_approval("tubecli_api", "x", {"_t": "thr-1"}, safe=True))
    check("S14 tool_approval(safe) ⇒ được, không thẻ duyệt", ok and not why, why)
    ok, why, _ = asyncio.run(svc.tool_approval("tubecli_api", "x", {"_t": "thr-llm"}, safe=True))
    check("S15 …nhưng luồng «Codex làm model» vẫn bị chặn", not ok and "model calls" in why, why)
    ok, why, _ = asyncio.run(svc.tool_approval("tubecli_api", "x", {"_t": "thr-1"}))
    check("S16 không safe + không ai xem ⇒ vẫn từ chối như cũ", not ok, why)
else:
    check("S14 có CodexService để thử tool_approval", False, [n for n in dir(SV) if "Service" in n])

print("── H. routes ─────────────────────────────────────────────")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
import tubecli.extensions.codex.routes as R  # noqa: E402

R.codex_manager = cm
app = FastAPI()
app.include_router(R.router)
c = TestClient(app)
h_off = mk("Auto publish: route", result=OFF, days=3)
j = c.post("/api/v1/codex/bulk/close-unproductive", json={"dry_run": True}).json()
check("H1 POST /bulk/close-unproductive dry_run", any(x["id"] == h_off["id"] for x in j.get("tasks", [])), j)
j = c.get(f"/api/v1/codex/tasks/{h_off['seq']}/close-safety").json()
check("H2 GET /tasks/{n}/close-safety", j.get("safe") is True and j.get("task") == h_off["seq"], j)
j = c.post("/api/v1/codex/bulk/close-duplicates", json={"dry_run": True}).json()
check("H3 POST /bulk/close-duplicates dry_run", j.get("dry_run") is True and "tasks" in j, j)
h_pub = pub_task("Route story", "Route story on YouTube")
SEARCH_ROWS["rows"] = [{"id": "vidROUTE001", "title": "Route story on YouTube", "channel": "Radhika Singh",
                        "published_at": "20261107"}]
j = c.post(f"/api/v1/codex/tasks/{h_pub['id']}/resolve-publish", json={"dry_run": True}).json()
check("H4 POST /tasks/{id}/resolve-publish dry_run", j.get("status") == "found" and j.get("video_id") == "vidROUTE001", j)
r = c.post(f"/api/v1/codex/tasks/{plan['id']}/resolve-publish", json={})
check("H5 …task kế hoạch ⇒ 400 có mã lỗi", r.status_code == 400 and r.json()["detail"]["code"] == "not_a_rendered_video",
      r.text)
BT._BULK.clear()
BT._BULK["running"] = False
j = c.post("/api/v1/codex/bulk/resolve-publish", json={"dry_run": True}).json()
check("H6 POST /bulk/resolve-publish trả ngay (chạy nền)", "running" in j and "total" in j, j)
for _ in range(200):
    if not BT.bulk_resolve_status().get("running"):
        break
    import time
    time.sleep(0.05)
j = c.get("/api/v1/codex/bulk/resolve-publish").json()
check("H7 GET /bulk/resolve-publish: xong, có kết quả", j.get("running") is False and "found" in j, j)
h_hand = mk("Hand published", result=RENDERED, ck={"video_path": VIDEO})
r = c.put(f"/api/v1/codex/tasks/{h_hand['id']}/published",
          json={"url": "https://youtu.be/vidHAND0001", "actor": "contabo-agent"})
check("H8 PUT /tasks/{id}/published {url, actor} ⇒ done", r.status_code == 200 and st(h_hand["id"]) == "done", r.text)
ev = [e for e in cm.get_events(h_hand["id"], limit=0) if "Marked as published" in str(e.get("message"))]
check("H9 …ghi đúng người đánh dấu (actor)", ev and ev[-1].get("actor") == "contabo-agent", ev[-1:] if ev else ev)
check("H10 …tính vào trần ngày của kênh", AP.get_mark("agA")["published_today"] >= 1, AP.get_mark("agA"))

print(f"\n{checks - len(failures)}/{checks} passed")
if failures:
    print("\nFAILURES:")
    for f in failures:
        print("  - " + f)
sys.exit(1 if failures else 0)
