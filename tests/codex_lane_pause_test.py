# -*- coding: utf-8 -*-
"""Hết quota giữa lượt dựng video → task quay lại hàng đợi + làn video TẠM DỪNG tới lúc quota mở lại (17/9/2026).

User: "đối với video luồng hết quota không tạo được video thì tạm dừng tất cả các luồng đợi xử lý" (ảnh: bước ảnh
«Xong · 5 shot(s) without image — HTTP 429 … daily free allocation of 10,000 neurons» rồi vẫn đọc giọng tiếp).

Kiểm (kho tạm, không Telegram, không HTTP thật):
  A. CodexManager: pause_lane → hàng đợi của làn không thả, task queued của làn không được nhận; làn khác + task
     chung vẫn chạy; hết hạn → tự chạy tiếp; resume_lane; tạm dừng lại lấy hạn muộn hơn; nạp lại từ đĩa
  B. report_failure: «LanePaused: …» của task trong làn đang dừng → BACKLOG (không FAILED), đứng đầu hàng; làn không
     dừng / task không làn → FAILED như cũ
  C. route: /tasks trả lane_pauses; POST /lanes/{lane}/resume
  D. pipeline: bước ảnh thiếu shot vì 429 → pause_lane (hạn = account Cloudflare mở lại sớm nhất) + LanePaused;
     thiếu shot vì lý do khác → chỉ cảnh báo như cũ; bước bắt buộc hỏng vì quota → LanePaused; bước tuỳ chọn /
     task không làn → lỗi thường

Run:  python tests/codex_lane_pause_test.py     (exit 0 = pass)
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

import tubecli.config as CFG  # noqa: E402

ROOT_TMP = tempfile.mkdtemp(prefix="codex-lane-pause-")
CFG.DATA_DIR = type(CFG.DATA_DIR)(os.path.join(ROOT_TMP, "data"))
CFG.EXTENSIONS_DATA_DIR = CFG.DATA_DIR / "extensions_data"
os.makedirs(str(CFG.DATA_DIR), exist_ok=True)

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


TMP = os.path.join(ROOT_TMP, "codex")
CMod.CODEX_DATA_DIR = TMP
CMod.TASKS_FILE = os.path.join(TMP, "tasks.json")
CMod.EVENTS_DIR = os.path.join(TMP, "events")
if os.path.commonpath([os.path.realpath(CMod._lane_pauses_file()), os.path.realpath(ROOT_TMP)]) != os.path.realpath(ROOT_TMP):
    print("ABORT — lane_pauses.json không nằm trong thư mục tạm:", CMod._lane_pauses_file())
    sys.exit(2)

cm = CMod.CodexManager()
cm.notifications_enabled = False


def mk(title, lane="video", hold=False, priority=0):
    return cm.create_task(goal=title, title=title, created_by="user", lane=lane, hold=hold,
                          approval_required=False, priority=priority)


def st(task):
    return cm.get_task(task["id"])["status"]


print("── A. tạm dừng làn ─────────────────────────────────────────")
v1 = mk("video 1")                          # queued thẳng, chiếm làn
v2 = mk("video 2", hold=True)
v3 = mk("video 3", hold=True)
g1 = mk("việc chung", lane="")
o1 = mk("làn khác", lane="other", hold=True)
first = cm.claim_next()
ok(first and first["id"] in (v1["id"], g1["id"]), "chưa dừng: nhận task như cũ", first)
running = [first]
cm.pause_lane("video", time.time() + 3600, "Generate shot images: HTTP 429 daily free allocation")
claimed = []
while True:
    nxt = cm.claim_next()
    if not nxt:
        break
    claimed.append(nxt["id"])
ok(v1["id"] not in claimed or first["id"] == v1["id"], "task QUEUED của làn video không được nhận khi làn dừng", claimed)
ok(st(v2) == CMod.BACKLOG and st(v3) == CMod.BACKLOG, "hàng đợi làn video không thả", (st(v2), st(v3)))
ok(g1["id"] in claimed + [first["id"]] and o1["id"] in claimed, "việc chung + làn khác vẫn chạy", claimed)
p = cm.lane_pauses()
ok(list(p) == ["video"] and p["video"]["reason"].startswith("Generate shot images") and p["video"]["until"] > time.time(),
   "lane_pauses trả làn đang dừng + lý do + hạn", p)
cm.pause_lane("video", time.time() + 60, "shorter")
ok(cm.lane_pauses()["video"]["until"] > time.time() + 3000, "tạm dừng lại với hạn SỚM hơn → giữ hạn muộn", cm.lane_pauses())
cm2 = CMod.CodexManager()
ok("video" in cm2.lane_pauses(), "nạp lại từ đĩa vẫn còn tạm dừng")
with cm._lock:
    cm._pauses["video"]["until"] = time.time() - 1
if first["id"] == v1["id"]:
    cm.report_result(v1["id"], "done")      # v1 xong → làn rảnh
nxt = cm.claim_next()
ok("video" not in cm.lane_pauses() and nxt and nxt["id"] in (v1["id"], v2["id"]),
   "hết hạn → làn tự chạy tiếp (task kế được nhận)", (cm.lane_pauses(), nxt))
cm.pause_lane("video", None, "manual")
ok(cm.lane_pauses()["video"]["until"] is None and cm.resume_lane("video") is True and not cm.lane_pauses()
   and cm.resume_lane("video") is False, "dừng không hạn → chỉ mở khi resume_lane; mở hai lần = no-op")

print("── B. report_failure ───────────────────────────────────────")
# dọn: task đang chạy → xong, task còn chờ (queued/backlog) → huỷ, để làn rảnh và hàng đợi trống
for t in cm.list_tasks(limit=0):
    if t["status"] == CMod.RUNNING:
        cm.report_result(t["id"], "done")
    elif t["status"] in (CMod.QUEUED, CMod.BACKLOG):
        cm._transition(t["id"], CMod.CANCELLED, "test")
w1 = mk("video 10")
w2 = mk("video 11", hold=True)
got = cm.claim_next()
while got and got["id"] != w1["id"]:
    cm.report_result(got["id"], "done")
    got = cm.claim_next()
ok(got and got["id"] == w1["id"] and st(w1) == CMod.RUNNING, "video 10 đang chạy", got)
cm.pause_lane("video", time.time() + 3600, "quota")
res = cm.report_failure(w1["id"], "LanePaused: quota used up at «Generate shot images» — the video queue is paused")
ok(res["status"] == CMod.BACKLOG and st(w1) == CMod.BACKLOG and "quota used up" in cm.get_task(w1["id"])["error"],
   "LanePaused + làn đang dừng → BACKLOG (không đánh hỏng)", res.get("status"))
ok(cm.backlog_position(w1["id"]) == 1 and cm.backlog_position(w2["id"]) == 2,
   "task dừng đứng ĐẦU hàng (tạo trước)", (cm.backlog_position(w1["id"]), cm.backlog_position(w2["id"])))
evs = cm.get_events(w1["id"], limit=50)
ok(any(e.get("kind") == "log" and str(e.get("message", "")).startswith("⏸") for e in evs), "sổ sự kiện có dòng ⏸")
ok(cm.claim_next() is None, "làn đang dừng → không nhận lại ngay")
cm.resume_lane("video")
again = cm.claim_next()
ok(again and again["id"] == w1["id"], "mở làn → task dừng chạy tiếp TRƯỚC", again)
cm.report_failure(w1["id"], "LanePaused: quota — nhưng làn không dừng")
ok(st(w1) == CMod.FAILED, "LanePaused mà làn KHÔNG dừng → FAILED như cũ", st(w1))
n1 = mk("chung", lane="")
got = cm.claim_next()
while got and got["id"] != n1["id"]:
    cm.report_result(got["id"], "done")
    got = cm.claim_next()
cm.pause_lane("video", time.time() + 3600, "quota")
cm.report_failure(n1["id"], "LanePaused: x")
ok(st(n1) == CMod.FAILED, "task không làn → FAILED", st(n1))
cm.resume_lane("video")

print("── C. route ────────────────────────────────────────────────")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
import tubecli.extensions.codex.routes as CR  # noqa: E402

CR.codex_manager = cm
app = FastAPI()
app.include_router(CR.router)
c = TestClient(app)
cm.pause_lane("video", time.time() + 600, "HTTP 429")
prefix = CR.router.prefix
r = c.get(prefix + "/tasks").json()
ok(r.get("lane_pauses", {}).get("video", {}).get("reason") == "HTTP 429", "GET /tasks trả lane_pauses", list(r))
r = c.post(prefix + "/lanes/video/resume").json()
ok(r == {"ok": True, "lane": "video", "resumed": True} and not cm.lane_pauses(), "POST /lanes/video/resume mở làn", r)

print("── D. pipeline ─────────────────────────────────────────────")
from tubecli.extensions.content_video import pipeline as P  # noqa: E402
from tubecli.core import image_gen as IG  # noqa: E402

PAUSES = []
TASKS = {"t-video": {"id": "t-video", "lane": "video"}, "t-free": {"id": "t-free", "lane": ""}}


class FakeCM:
    def get_task(self, tid):
        return TASKS.get(tid)

    def pause_lane(self, lane, until=None, reason="", actor="system"):
        PAUSES.append((lane, until, reason, actor))


CMod.codex_manager = FakeCM()
P._fill_missing_prompts = lambda state: 0
PARKED = time.time() + 5 * 3600
IG._cf_accounts = lambda: [{"label": "a", "active": False, "disable_reason": "transient", "disabled_until": PARKED + 60},
                           {"label": "b", "active": False, "disable_reason": "transient", "disabled_until": PARKED}]
said = []


def state_for(tid):
    said.clear()
    return {"episode_id": 7, "task_id": tid, "_say": lambda *a: said.append(a), "_cancelled": lambda: False}


GEN = {"errors": [1, 2, 3, 4, 5], "total": 177, "ok": 172,
       "last_error": 'HTTP 429: {"errors":[{"message":"AiError: AiError: you have used up your daily free allocation of 10,000 neurons, please"}]}'}
P._post = lambda path, payload, timeout=300: {"task_id": "g1", "total": 177, "with_prompt": 177}
P._poll_studio = lambda *a, **k: dict(GEN)
st_v = state_for("t-video")
try:
    P._step_images(st_v, {})
    ok(False, "hết quota ở bước ảnh phải ném LanePaused")
except CMod.LanePaused as e:
    ok(PAUSES and PAUSES[-1][0] == "video" and abs(PAUSES[-1][1] - PARKED) < 1
       and PAUSES[-1][2].startswith("Generate shot images: 5/177 shot(s) not drawn"),
       "thiếu 5/177 ảnh vì 429 → tạm dừng làn video tới lúc account Cloudflare mở lại SỚM nhất", PAUSES[-1:])
    ok("quota used up at «Generate shot images»" in str(e) and "continues from this step" in str(e)
       and not any("without image" in str(a[2]) for a in said), "LanePaused nói rõ; không đi tiếp như «Xong»", str(e))
IG._cf_accounts = lambda: [{"label": "a", "active": True}]
PAUSES.clear()
try:
    P._step_images(state_for("t-video"), {})
except CMod.LanePaused:
    pass
ok(PAUSES and 29 * 60 < PAUSES[-1][1] - time.time() <= 30 * 60 + 5,
   "không biết hạn (Cloudflare còn account chạy / nhà khác) → thử lại sau 30 phút", PAUSES[-1:])
PAUSES.clear()
GEN = {"errors": [1], "total": 10, "ok": 9, "last_error": "refused: content policy"}
st_warn = state_for("t-video")
P._step_images(st_warn, {})
ok(not PAUSES and any("could not be drawn" in w for w in st_warn["warnings"]),
   "thiếu ảnh vì lý do KHÁC → chỉ cảnh báo như cũ", st_warn.get("warnings"))
GEN = {"errors": [1, 2], "total": 10, "ok": 8, "last_error": "HTTP 429: quota exceeded"}
st_free = state_for("t-free")
P._step_images(st_free, {})
ok(not PAUSES and st_free.get("warnings"), "task KHÔNG thuộc làn → không dừng gì, cảnh báo như cũ")

P.check_job = lambda job: {"ready": True, "missing": [], "disabled": [], "missing_tools": []}
P._HANDLERS["quota_step"] = lambda s, o: (_ for _ in ()).throw(RuntimeError("HTTP 429: You exceeded your current quota"))
P._HANDLERS["plain_step"] = lambda s, o: (_ for _ in ()).throw(RuntimeError("storyboard JSON broken"))
say_log = []
say = lambda *a: say_log.append(a)  # noqa: E731
try:
    P._run_steps([("quota_step", "Write the script", "text", False)], state_for("t-video"), {}, say, lambda: False, [], [])
    ok(False, "bước bắt buộc hết quota phải ném LanePaused")
except CMod.LanePaused as e:
    errs = [a for a in say_log if a[1] == "error"]
    ok(len(errs) == 1 and "the video queue is paused" in errs[0][2] and PAUSES[-1][2].startswith("Write the script: HTTP 429"),
       "bước bắt buộc hỏng vì quota → LanePaused, thẻ bước báo MỘT lần", (errs, PAUSES[-1:]))
PAUSES.clear()
say_log.clear()
try:
    P._run_steps([("quota_step", "Write the script", "text", False)], state_for("t-free"), {}, say, lambda: False, [], [])
except CMod.LanePaused:
    ok(False, "task không làn không được LanePaused")
except RuntimeError as e:
    ok("exceeded your current quota" in str(e) and len([a for a in say_log if a[1] == "error"]) == 1 and not PAUSES,
       "task không làn → lỗi thường, báo một lần", say_log)
try:
    P._run_steps([("plain_step", "Storyboard", "text", False)], state_for("t-video"), {}, say, lambda: False, [], [])
except CMod.LanePaused:
    ok(False, "lỗi không phải quota không được dừng làn")
except RuntimeError:
    ok(not PAUSES, "lỗi không phải quota → hỏng như cũ")
PAUSES.clear()
say_log.clear()
notes = []
try:
    P._run_steps([("quota_step", "Optional thing", "text", True)], state_for("t-video"), {}, say, lambda: False, notes, [])
except CMod.LanePaused:
    ok(False, "bước TUỲ CHỌN hết quota không được dừng cả làn")
except RuntimeError:
    ok(not PAUSES, "bước tuỳ chọn hết quota → không dừng làn (lỗi như cũ)", PAUSES)
ok(all(P._looks_like_quota(x) for x in (GEN["last_error"], "RESOURCE_EXHAUSTED", "rate limit reached", "daily free allocation"))
   and not any(P._looks_like_quota(x) for x in ("storyboard JSON broken", "HTTP 502: error code: 502", "")),
   "nhận diện quota: 429/quota/rate limit/RESOURCE_EXHAUSTED/daily allocation; 502 thường thì không")

print()
print(f"{PASS}/{PASS + FAIL} PASS" if not FAIL else f"{PASS}/{PASS + FAIL} PASS — {FAIL} HỎNG")
sys.exit(1 if FAIL else 0)
