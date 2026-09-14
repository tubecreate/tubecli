# -*- coding: utf-8 -*-
"""Codex: Huỷ dừng sạch bước đang làm rồi Chạy lại tiếp từ đó; nút Xoá hỏi "chỉ Codex"
hay "cả file" (13/9/2026).

User: "cancel không retry được (nếu cancel thì huỷ clear bước đang làm, thêm nút retry để
làm lại bước đó), nút xoá thì xoá luôn — hiện lên chỉ xoá trên codex hay xoá luôn tất cả
các file". Chạy trên kho tạm, đối chiếu code thật:
  A. Huỷ     — bước running → cancelled với lời "Retry continues"; tiến độ muộn không đè
  B. Chạy lại — cancelled → queued được (nước đi mới), cờ huỷ được xoá
  C. Xoá     — đang chạy thì từ chối; xoá xong mất task + sổ sự kiện
  D. Xoá cả file — hook theo tiền tố kind chạy TRƯỚC khi mất sổ; hook hỏng không chặn xoá
  E. Route   — DELETE /tasks/{id}?purge=1

Run:  PYTHONIOENCODING=utf-8 python tests/codex_cancel_delete_test.py     (exit 0 = pass)
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

PASS = FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", label)
    else:
        FAIL += 1
        print("  FAIL", label, "—", str(detail)[:300])


TMP = tempfile.mkdtemp(prefix="codex-cancel-")
CMod.CODEX_DATA_DIR = TMP
CMod.TASKS_FILE = os.path.join(TMP, "tasks.json")
CMod.EVENTS_DIR = os.path.join(TMP, "events")
cm = CMod.CodexManager()
cm.notifications_enabled = False


def mk(title="Video", lane="video"):
    return cm.create_task(goal=title, title=title, created_by="user", lane=lane, approval_required=False)


# ── A. Huỷ ──────────────────────────────────────────────────────────────────
print("── A. Huỷ dừng sạch bước đang làm ───────────────────────────")
t = mk()
claimed = cm.claim_next()
ok(claimed and claimed["id"] == t["id"] and cm.get_task(t["id"])["status"] == CMod.RUNNING, "task đang chạy")
cm.report_step(t["id"], "images", "success", "69/69", "Generate shot images")
cm.report_step(t["id"], "tts", "running", "5/69 · CapCut", "Voice the narration", progress=7)
cm.cancel(t["id"], actor="user:web")
task = cm.get_task(t["id"])
steps = {s["name"]: s for s in task["steps"]}
ok(task["status"] == CMod.CANCELLED, "trạng thái đã huỷ")
ok(steps["images"]["status"] == "success", "bước đã xong giữ nguyên")
ok(steps["tts"]["status"] == CMod.STEP_CANCELLED and "Retry continues from this step" in steps["tts"]["message"]
   and steps["tts"]["ended_at"], "bước đang làm → cancelled, nói rõ Chạy lại tiếp từ đây", steps["tts"])
cm.report_step(t["id"], "tts", "running", "10/69 · CapCut", progress=14)     # tiến trình còn chạy vài giây
task = cm.get_task(t["id"])
tts = next(s for s in task["steps"] if s["name"] == "tts")
ok(tts["status"] == CMod.STEP_CANCELLED and tts["progress"] == 7.0, "tiến độ muộn sau khi huỷ không đè dấu đã dừng", tts)
ok(any("stopped by cancel" in e.get("message", "") for e in cm.get_events(t["id"], limit=50)), "sổ sự kiện ghi bước đã dừng")
ok(cm.is_cancel_requested(t["id"]), "cờ huỷ còn để tiến trình dừng")

# ── B. Chạy lại sau khi huỷ ─────────────────────────────────────────────────
print("── B. Chạy lại sau khi huỷ ──────────────────────────────────")
ok(CMod.TRANSITIONS[CMod.CANCELLED] == {CMod.QUEUED, CMod.BACKLOG}, "cancelled → queued/backlog là nước đi hợp lệ (bệnh cũ: rỗng; backlog = chờ làn, 14/9)")
again = cm.retry(t["id"], actor="user:web")
ok(again["status"] == CMod.QUEUED and again["steps"] == [] and again["retry_count"] == 1, "Chạy lại → vào hàng, bước làm mới, đếm lượt", again["status"])
ok(not cm.is_cancel_requested(t["id"]), "cờ huỷ đã xoá — lượt mới không bị dừng ngay")
claimed = cm.claim_next()
ok(claimed and claimed["id"] == t["id"], "worker nhận lại đúng task")
cm.report_step(t["id"], "tts", "running", "6/69", progress=8)
ok(next(s for s in cm.get_task(t["id"])["steps"] if s["name"] == "tts")["status"] == "running", "…và bước lại chạy bình thường")

# ── C. Xoá ───────────────────────────────────────────────────────────────────
print("── C. Xoá ───────────────────────────────────────────────────")
try:
    cm.delete(t["id"])
    ok(False, "xoá task đang chạy phải bị từ chối")
except ValueError as e:
    ok("cancel it first" in str(e), "đang chạy → từ chối, chỉ đường Huỷ trước", str(e))
cm.cancel(t["id"])
ev_path = cm._events_path(t["id"])
ok(os.path.isfile(ev_path), "sổ sự kiện có trên đĩa trước khi xoá")
res = cm.delete(t["id"], purge=False, actor="user:web")
ok(cm.get_task(t["id"]) is None and not os.path.isfile(ev_path) and res["purge"] is None,
   "xoá xong: mất task, mất sổ, không đụng file (purge=False)", res)
ok(t["id"] not in cm._cancel_requested, "cờ huỷ dọn theo")
cm2 = CMod.CodexManager()
ok(cm2.get_task(t["id"]) is None, "nạp lại từ đĩa cũng không còn")

# ── D. Xoá cả file qua hook ─────────────────────────────────────────────────
print("── D. Xoá cả file: hook theo loại task ──────────────────────")
calls = []


def hook(task):
    calls.append(task["id"])
    return {"files": 71, "bytes": 612 * 1024 * 1024, "episode": 337}


cm.on_delete("content_video.", hook)
v = mk("Video from content")
cm.append_event(v["id"], "log", "queued", actor="content_video", data={"kind": "content_video.auto", "task_id": v["id"]})
cm.cancel(v["id"])
res = cm.delete(v["id"], purge=True)
ok(calls == [v["id"]] and res["purge"]["files"] == 71 and res["purge"]["episode"] == 337, "hook được gọi với task, tóm tắt trả về", res["purge"])
ok(cm.get_task(v["id"]) is None, "task mất sau hook")
g = mk("Việc chung", lane="general")
cm.cancel(g["id"])
res = cm.delete(g["id"], purge=True)
ok(res["purge"].get("skipped") and cm.get_task(g["id"]) is None, "task không có hook → báo skipped, vẫn xoá", res["purge"])


def bad_hook(task):
    raise RuntimeError("disk is locked")


cm.on_delete("content_video.", bad_hook)
v2 = mk("Video 2")
cm.append_event(v2["id"], "log", "queued", actor="content_video", data={"kind": "content_video.render"})
cm.cancel(v2["id"])
res = cm.delete(v2["id"], purge=True)
ok("disk is locked" in res["purge"].get("error", "") and cm.get_task(v2["id"]) is None, "hook hỏng → báo lỗi, task vẫn xoá khỏi Codex", res["purge"])

# ── E. Route ─────────────────────────────────────────────────────────────────
print("── E. Route DELETE ───────────────────────────────────────────")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
import tubecli.extensions.codex.routes as R  # noqa: E402

R.codex_manager = cm
cm.on_delete("content_video.", hook)
app = FastAPI()
app.include_router(R.router)
client = TestClient(app)
v3 = mk("Video 3")
cm.append_event(v3["id"], "log", "queued", actor="content_video", data={"kind": "content_video.auto"})
cm.claim_next()
r = client.delete(f"/api/v1/codex/tasks/{v3['id']}")
ok(r.status_code == 400 and "cancel it first" in r.text, "đang chạy → 400 với lời chỉ đường", (r.status_code, r.text[:120]))
client.post(f"/api/v1/codex/tasks/{v3['id']}/cancel", json={"actor": "user:web"})
calls.clear()
r = client.delete(f"/api/v1/codex/tasks/{v3['id']}?purge=1")
ok(r.status_code == 200 and r.json()["status"] == "deleted" and r.json()["purge"]["files"] == 71 and calls == [v3["id"]],
   "DELETE ?purge=1 → xoá + tóm tắt file", (r.status_code, r.text[:200]))
ok(client.get(f"/api/v1/codex/tasks/{v3['id']}").status_code == 404, "task không còn")
v4 = mk("Video 4")
cm.cancel(v4["id"])
r = client.delete(f"/api/v1/codex/tasks/{v4['id']}")
ok(r.status_code == 200 and r.json()["purge"] is None, "DELETE không purge → chỉ Codex")

print()
print("=" * 62)
print(f"{PASS}/{PASS + FAIL} PASS" if not FAIL else f"{PASS}/{PASS + FAIL} PASS — {FAIL} HỎNG")
sys.exit(1 if FAIL else 0)
