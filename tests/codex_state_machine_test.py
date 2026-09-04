# -*- coding: utf-8 -*-
"""Máy trạng thái codex — bấm "Chấp nhận" hai lần KHÔNG được đăng thêm video.

Run:  PYTHONIOENCODING=utf-8 python -X utf8 tests/codex_state_machine_test.py

Lỗi thật đã tái hiện được trước khi sửa: _transition bỏ qua mọi nước đi
"đứng yên tại chỗ" (`if new_status != old and new_status not in TRANSITIONS…`),
nên done → done âm thầm THÀNH CÔNG, và complete_review đi tiếp xuống
_fire_on_accept vô điều kiện. Với dây chuyền content_video, hook đó xếp bước
render ⇒ lần bấm thứ hai = một video CÔNG KHAI thứ hai của đúng cùng kịch bản.
Không có gì rút lại được sau khi YouTube nhận.

Kiểm, đối chiếu code thật:
  A. Cò súng     — accept hai lần: hook nổ ĐÚNG một lần, task vẫn done
  B. Đứng yên    — _transition từ chối mọi nước X → X, câu lỗi nói "already"
  C. Bấm lại     — approve/reject/cancel/retry/rework/report_* là no-op:
                   không thêm sự kiện, không tăng retry_count, không đè kết quả
  D. Đường đi    — các chuyển trạng thái HỢP LỆ vẫn chạy; nước cấm vẫn ném
  E. Đua nhau    — hai luồng cùng bấm Accept: vẫn đúng một lần nổ
"""
import os
import sys
import tempfile
import threading

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
    if not ok:
        failures.append("%s: %s" % (label, detail))


print("=" * 70)
print("MÁY TRẠNG THÁI CODEX — CHẤP NHẬN HAI LẦN KHÔNG ĐƯỢC ĐĂNG HAI VIDEO")
print("=" * 70)

TMP = tempfile.mkdtemp(prefix="codex-state-")
CMod.CODEX_DATA_DIR = TMP
CMod.TASKS_FILE = os.path.join(TMP, "tasks.json")
CMod.EVENTS_DIR = os.path.join(TMP, "events")

cm = CMod.CodexManager()
cm.notifications_enabled = False   # không đẩy gì vào chat thật của người dùng

FIRED = []
cm.on_accept("content_video.plan", lambda task, actor: FIRED.append((task["id"], actor)))


PRIO = [0]


def new_task(goal, approval_required=False):
    """Ưu tiên tăng dần: claim_next() xếp theo priority nên task mới nhất luôn
    được nhận trước, kể cả khi vài task của nhóm kiểm trước còn nằm trong hàng."""
    PRIO[0] += 1
    return cm.create_task(goal=goal, title=goal, created_by="user",
                          approval_required=approval_required, priority=PRIO[0])


def task_in_review(kind="content_video.plan", goal="g"):
    """Một task đã chạy xong và đang chờ duyệt — đúng chỗ nút Accept hiện ra."""
    t = new_task(goal)
    cm.append_event(t["id"], "log", "queued", actor="test", data={"kind": kind})
    claimed = cm.claim_next()
    assert claimed["id"] == t["id"], "claim_next nhận nhầm task"
    cm.report_result(t["id"], "## kịch bản xong")
    return t["id"]


def events_of(task_id):
    return cm.get_events(task_id, limit=1000)


# ── A. Cò súng: accept hai lần ──────────────────────────────────────────────
FIRED[:] = []
tid = task_in_review()
check("A trước khi bấm, task đang ở review", cm.get_task(tid)["status"] == "review")
first = cm.complete_review(tid, True, actor="owner")
check("A lần bấm đầu: task done + hook nổ",
      first["status"] == "done" and FIRED == [(tid, "owner")], FIRED)
n_events = len(events_of(tid))
second = cm.complete_review(tid, True, actor="owner")
check("A lần bấm hai: KHÔNG nổ lại hook (không có video thứ hai)",
      FIRED == [(tid, "owner")], FIRED)
check("A lần bấm hai vẫn trả về task done, không ném", second["status"] == "done", second)
check("A và không đẻ thêm sự kiện nào vào sổ", len(events_of(tid)) == n_events,
      len(events_of(tid)))
check("A dấu thời điểm kết thúc không bị viết lại",
      second["finished_at"] == first["finished_at"], (first["finished_at"], second["finished_at"]))
# người khác bấm lại cũng vậy — không phải chỉ cùng một actor
cm.complete_review(tid, True, actor="somebody-else")
check("A người thứ hai bấm cũng không nổ lại", FIRED == [(tid, "owner")], FIRED)
print("A cò súng    : accept hai lần → hook đúng 1 lần, không sự kiện thừa, không ném")

# ── B. Không state nào được tự trỏ về mình ─────────────────────────────────
for state, allowed in CMod.TRANSITIONS.items():
    check("B %s không nằm trong danh sách đích của chính nó" % state,
          state not in allowed, allowed)
tid2 = task_in_review()
try:
    cm._transition(tid2, CMod.REVIEW, "test")
    check("B _transition từ chối review → review", False, "không ném")
except ValueError as e:
    check("B _transition từ chối review → review", True)
    check("B câu lỗi nói rõ 'already'", "already" in str(e).lower(), str(e))
cm.complete_review(tid2, True, actor="owner")
try:
    cm._transition(tid2, CMod.DONE, "test")
    check("B _transition từ chối done → done", False, "không ném")
except ValueError as e:
    check("B _transition từ chối done → done", True, str(e))
src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "tubecli", "extensions", "codex", "manager.py"),
           encoding="utf-8").read()
check("B cửa hậu 'new_status != old' đã bị bịt",
      "if new_status != old and new_status not in TRANSITIONS" not in src, "")
print("B đứng yên   : mọi nước X → X bị từ chối ở đúng một chỗ (_transition)")

# ── C. Bấm lại nút nào cũng là no-op ───────────────────────────────────────
# approve
t = new_task("a", approval_required=True)
cm.approve(t["id"], actor="owner", note="ok")
n = len(events_of(t["id"]))
again = cm.approve(t["id"], actor="owner", note="ok")
check("C approve lần hai: không ném, vẫn queued", again["status"] == "queued", again["status"])
check("C approve lần hai: không thêm sự kiện", len(events_of(t["id"])) == n, len(events_of(t["id"])))

# retry — thủ phạm âm thầm: mỗi cú bấm thừa đẩy task tới gần max_retries
before = cm.get_task(t["id"])["retry_count"]
cm.retry(t["id"], actor="owner")
check("C retry trên task ĐANG XẾP HÀNG không tăng retry_count",
      cm.get_task(t["id"])["retry_count"] == before, cm.get_task(t["id"])["retry_count"])

# reject
t2 = new_task("b", approval_required=True)
cm.reject(t2["id"], actor="owner", note="no")
n2 = len(events_of(t2["id"]))
cm.reject(t2["id"], actor="owner", note="no")
check("C reject lần hai: không thêm sự kiện", len(events_of(t2["id"])) == n2, len(events_of(t2["id"])))

# cancel
t3 = new_task("c", approval_required=False)
cm.cancel(t3["id"], actor="owner")
fin = cm.get_task(t3["id"])["finished_at"]
n3 = len(events_of(t3["id"]))
cm.cancel(t3["id"], actor="owner")
check("C cancel lần hai: không ném, giờ kết thúc giữ nguyên",
      cm.get_task(t3["id"])["finished_at"] == fin, cm.get_task(t3["id"])["finished_at"])
check("C cancel lần hai: không thêm sự kiện", len(events_of(t3["id"])) == n3, len(events_of(t3["id"])))

# report_result / report_failure của worker
t4 = new_task("d", approval_required=False)
assert cm.claim_next()["id"] == t4["id"]
cm.report_result(t4["id"], "kết quả thật")
cm.report_result(t4["id"], "kết quả ĐÈ LÊN")
check("C kết quả thứ hai không đè lên cái người duyệt đang đọc",
      cm.get_task(t4["id"])["result"] == "kết quả thật", cm.get_task(t4["id"])["result"])
t5 = new_task("e", approval_required=False)
assert cm.claim_next()["id"] == t5["id"]
cm.report_failure(t5["id"], "lỗi thật")
cm.report_failure(t5["id"], "lỗi ĐÈ LÊN")
check("C lỗi thứ hai không đè lên lỗi đầu",
      cm.get_task(t5["id"])["error"] == "lỗi thật", cm.get_task(t5["id"])["error"])

# "yêu cầu sửa" hai lần: câu góp ý không được dán vào goal hai lần
t6 = task_in_review(kind="content_video.plan", goal="f")
cm.complete_review(t6, False, actor="owner", feedback="ngắn hơn")
goal_once = cm.get_task(t6)["goal"]
cm.complete_review(t6, False, actor="owner", feedback="ngắn hơn")
check("C yêu cầu sửa lần hai: goal không bị dán góp ý hai lần",
      cm.get_task(t6)["goal"] == goal_once and goal_once.count("ngắn hơn") == 1, goal_once)
print("C bấm lại    : approve/reject/cancel/retry/rework/report_* — no-op, không tác dụng phụ")

# ── D. Đường đi hợp lệ vẫn nguyên vẹn ──────────────────────────────────────
FIRED[:] = []
t7 = new_task("g", approval_required=True)
check("D tạo ra ở pending_approval", t7["status"] == "pending_approval")
check("D approve → queued", cm.approve(t7["id"], actor="owner")["status"] == "queued")
_claimed = cm.claim_next()
check("D claim_next → running", _claimed["status"] == "running" and _claimed["id"] == t7["id"])
check("D report_result → review", cm.report_result(t7["id"], "xong")["status"] == "review")
check("D yêu cầu sửa → queued lại",
      cm.complete_review(t7["id"], False, actor="owner", feedback="thêm cảnh")["status"] == "queued")
check("D góp ý được nối vào goal", "thêm cảnh" in cm.get_task(t7["id"])["goal"])
assert cm.claim_next()["id"] == t7["id"]
cm.report_result(t7["id"], "xong lần 2")
check("D accept → done", cm.complete_review(t7["id"], True, actor="owner")["status"] == "done")
t8 = new_task("h", approval_required=False)
assert cm.claim_next()["id"] == t8["id"]
cm.report_failure(t8["id"], "ngã")
check("D failed → retry → queued, retry_count +1",
      cm.retry(t8["id"], actor="owner")["status"] == "queued"
      and cm.get_task(t8["id"])["retry_count"] == 1, cm.get_task(t8["id"])["retry_count"])
for target in (CMod.QUEUED, CMod.RUNNING, CMod.REVIEW):
    try:
        cm._transition(t7["id"], target, "test")
        check("D done → %s vẫn bị cấm" % target, False, "không ném")
    except ValueError:
        check("D done → %s vẫn bị cấm" % target, True)
try:
    cm.complete_review("khong-co-task-nao", True)
    check("D task không tồn tại vẫn ném", False, "không ném")
except ValueError:
    check("D task không tồn tại vẫn ném", True)
print("D đường đi   : pending→queued→running→review→done, rework, retry — không đổi; nước cấm vẫn ném")

# ── E. Hai người bấm Accept cùng lúc ───────────────────────────────────────
# _settle kiểm-tra-rồi-đổi trong CÙNG một lượt giữ khoá, nên kẻ thua không thấy
# review nữa mà thấy done ⇒ trả về no-op thay vì nổ hook lần hai.
FIRED[:] = []
t9 = task_in_review()
start = threading.Barrier(2)
errors = []


def accept():
    try:
        start.wait(timeout=5)
        cm.complete_review(t9, True, actor="owner")
    except Exception as e:  # noqa: BLE001
        errors.append(repr(e))


threads = [threading.Thread(target=accept) for _ in range(2)]
for th in threads:
    th.start()
for th in threads:
    th.join(timeout=10)
check("E hai luồng cùng accept: hook vẫn chỉ nổ một lần", len(FIRED) == 1, FIRED)
check("E không luồng nào ăn ngoại lệ", not errors, errors)
check("E task vẫn done", cm.get_task(t9)["status"] == "done")
print("E đua nhau   : check-then-move nằm trong một lượt giữ khoá — đúng một kẻ thắng")

print("=" * 70)
if failures:
    print("%d FAIL / %d" % (len(failures), checks))
    for x in failures:
        print("  FAIL", x)
    sys.exit(1)
print("%d/%d PASS" % (checks, checks))
