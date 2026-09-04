# -*- coding: utf-8 -*-
"""Tự động đăng video sau mỗi lượt thu thập — nửa "cò súng".

Run:  PYTHONIOENCODING=utf-8 python -X utf8 tests/content_video_autopublish_test.py

Ý người dùng: "mỗi lần thu thập thành công thì … viết nội dung mới, đăng lên kênh
youtube đã được cấp api", và "đăng luôn khỏi duyệt". Cò súng nằm ở cuối
process_manager._record_run_end — tức là trong LUỒNG THEO DÕI TIẾN TRÌNH, nơi
không có ai bắt lỗi hộ. Nên nửa số kiểm tra dưới đây là về chuyện KHÔNG ĐƯỢC NỔ,
chứ không phải về chuyện bắn trúng.

Vì sao mốc high-water chứ không phải "lượt này có cào được gì không":
`work` rỗng trên mọi lượt hẹn giờ (scripted_only ⇒ open.js không in "Step:" lẫn
"Actions: N"), còn đếm dòng log thì sai vì extract_content.js in banner COMPLETE
cả khi bỏ qua URL trùng. Chỉ có chính cái kho mới trả lời được.

Kiểm, đối chiếu code thật:
  A. Sổ JSON     — thiếu file / hỏng / lạ kiểu → mặc định; ghi-đọc khứ hồi; ghi
                   nguyên tử; đọc là tự quy 0 bộ đếm khi sang ngày mới
  B. scan_new    — chỉ đếm bài CÓ NỘI DUNG, chỉ tính bài mới hơn mốc; chưa có mốc
                   thì CHỈ hôm nay (không quét cả kho cũ); kho hỏng → (0, "")
  C. Các cửa ải  — mỗi lý do bỏ qua một câu riêng: outcome / không có agent / tắt
                   / bật mà chưa chọn kênh / trần ngày / chống dội / chưa đủ bài
  D. Sang ngày   — bộ đếm hôm qua không khoá được hôm nay
  E. Bắn         — create_plan_task nhận approval_required=False, publish=True,
                   đúng kênh + quyền riêng tư + mốc cũ; xong mới dời mốc, tăng đếm
  F. Bắn hụt     — create_plan_task ném ⇒ KHÔNG dời mốc (lượt sau thử lại), không
                   ném ngược ra ngoài
  G. Không cổng  — chế độ tự động chạy trọn MỘT task (KIND_AUTO); không còn
                   đỗ ở REVIEW ⇒ phải tự bấm Accept thì on_accept mới queue render
  H. Móc         — _record_run_end nuốt mọi lỗi của autopublish
  I. Trường agent— auto_publish/publish_* có trong Agent + to_dict + from_dict +
                   AgentUpdateRequest/AgentCreateRequest
  J. Kho > 500   — scraped_store.query sắp cả kho rồi mới cắt, limit kẹp ở 500,
                   nên order="asc" nghĩa là "500 dòng CŨ NHẤT": quá 500 dòng là
                   mốc mù hẳn. Quét phải lật trang theo chiều GIẢM
  K. Hai cái mốc — lúc xếp việc chỉ ghi high_water_pending (cho cửa chống dội);
                   high_water + bộ đếm ngày chỉ nhúc nhích khi commit_published
                   báo video đã lên kênh; commit hai lần chỉ tính một
  L. Cửa ải mới  — extension content_video bị tắt/gỡ; lượt chạy tay (trigger)
  M. Mốc rác     — dòng không đọc được scraped_at thì không được tính
  N. Nguyên khối — hai lượt chạy cùng lúc không xếp được hai task
"""
import ast
import io
import json
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

from tubecli.core.agent import Agent as RealAgent  # noqa: E402
from tubecli.core import scraped_store as SS  # noqa: E402
from tubecli.core import agent as AG  # noqa: E402
from tubecli.extensions.content_video import autopublish as A  # noqa: E402
from tubecli.extensions.content_video import pipeline as P  # noqa: E402

failures = []
checks = 0


def check(label, ok, detail=""):
    global checks
    checks += 1
    if not ok:
        failures.append("%s: %s" % (label, detail))


print("=" * 70)
print("TỰ ĐỘNG ĐĂNG VIDEO SAU LƯỢT THU THẬP — CÒ SÚNG")
print("=" * 70)

TMP = Path(tempfile.mkdtemp(prefix="autopub-"))
STORE = TMP / "store" / "autopublish.json"
A._store_path = lambda: STORE


def reset_store():
    try:
        if STORE.exists():
            STORE.unlink()
    except OSError:
        pass


def agent(**kw):
    """Agent THẬT, không phải giả — test này cũng là bằng chứng các trường tồn tại."""
    base = dict(name="MC", id="a1", auto_publish=True, publish_token_id="tok-1",
                publish_channel_id="UC123", publish_channel_name="Kênh Tin Nhanh",
                publish_privacy="public", publish_min_pages=3, publish_max_per_day=2,
                allowed_profiles=["p1"])
    base.update(kw)
    return RealAgent(**base)


class FakeCodex:
    """Đủ nhiều của codex_manager để chạy cầu duyệt."""

    def __init__(self):
        self.tasks = {}
        self.accepted = []

    def get_task(self, tid):
        return self.tasks.get(str(tid))

    def complete_review(self, task_id, accepted=True, actor="user", feedback=""):
        t = self.tasks.get(str(task_id))
        if not t or t.get("status") != "review":
            raise ValueError("Transition not allowed")
        t["status"] = "done"
        self.accepted.append((str(task_id), actor, accepted))
        return t


CODEX = FakeCodex()
A._codex = lambda: CODEX

# _scope() hỏi pipeline để đếm ĐÚNG những hồ sơ pipeline sẽ gom; chốt lại ở đây
# để test không phụ thuộc group_context của máy đang chạy.
P._agent_scope = lambda a: list(getattr(a, "allowed_profiles", []) or [])

QUERY_CALLS = []
ROWS = []


def fake_query(**kw):
    """Bản sao NGUYÊN VĂN đoạn đuôi của scraped_store.query.

    Chính cái đuôi này là chỗ có bug: sắp TOÀN BỘ kho rồi mới cắt
    items[offset:offset+limit], với limit bị kẹp cứng ở 500. Một fake trả về cả
    danh sách bất kể limit sẽ giấu mất bug — nên nó phải cắt y như bản thật.
    """
    QUERY_CALLS.append(kw)
    rows = ROWS
    if kw.get("only_with_content"):
        rows = [r for r in rows if r.get("has_content")]
    if kw.get("day") == "today":
        rows = [r for r in rows if r.get("_today")]
    rows = sorted(rows, key=lambda r: r.get("scraped_at") or "",
                  reverse=(kw.get("order") != "asc"))
    total = len(rows)
    offset = max(0, int(kw.get("offset") or 0))
    limit = max(1, min(int(kw.get("limit") or 50), 500))
    page = rows[offset:offset + limit]
    return {"items": page, "total": total, "count": len(page),
            "offset": offset, "limit": limit}


SS.query = fake_query

PLAN_CALLS = []
PLAN_RAISES = [None]
SEQ = [100]


def fake_create_auto_task(agent_id, options=None, created_by="user", origin=None,
                          job_label="Auto publish", high_water_prev=None, high_water=None):
    PLAN_CALLS.append(dict(agent_id=agent_id, options=dict(options or {}),
                           created_by=created_by, origin=dict(origin or {}),
                           job_label=job_label, high_water_prev=high_water_prev,
                           high_water=high_water))
    if PLAN_RAISES[0]:
        raise PLAN_RAISES[0]
    tid = "task-auto-%d" % len(PLAN_CALLS)
    # Vào sổ codex giả: cửa chống dội của lượt sau tra chính bảng này.
    CODEX.tasks[tid] = {"id": tid, "seq": 7, "status": "running"}
    return {"id": tid, "seq": 7}


P.create_auto_task = fake_create_auto_task


AGENTS = {}
AG.agent_manager.get = lambda aid: AGENTS.get(str(aid))


def fire(a, outcome="completed", run_id="run-1", trigger=""):
    AGENTS.clear()
    AGENTS[a.id] = a
    return A.maybe_publish_after_run(a.id, run_id, outcome, trigger)


# ── A. Sổ JSON ──────────────────────────────────────────────────────────────
reset_store()
m = A.get_mark("a1")
check("A thiếu file → mặc định đủ khoá",
      m == {"high_water": "", "high_water_pending": "", "published_today": 0,
            "day": A._today(), "last_task_id": "", "last_fired_at": 0.0,
            "last_commit_key": "", "last_video_url": ""}, m)
check("A ghi được khi thư mục chưa tồn tại",
      A.save_mark("a1", high_water="2026-09-04T01:00:00+00:00", published_today=1,
                  day=A._today(), last_task_id="t9", last_fired_at=123.5) is True)
m = A.get_mark("a1")
check("A khứ hồi", m["high_water"] == "2026-09-04T01:00:00+00:00"
      and m["published_today"] == 1 and m["last_task_id"] == "t9"
      and m["last_fired_at"] == 123.5, m)
check("A agent khác không dính", A.get_mark("a2")["high_water"] == "")
A.save_mark("a2", high_water="x")
check("A hai agent cùng sổ", A.get_mark("a1")["high_water"].startswith("2026-09-04")
      and A.get_mark("a2")["high_water"] == "x")
check("A ghi nguyên tử: không để lại .tmp", not (STORE.parent / (STORE.name + ".tmp")).exists())
# File rách / lạ kiểu → coi như chưa có, KHÔNG ném
STORE.write_text("{ this is not json", encoding="utf-8")
check("A file hỏng → mặc định, không ném", A.get_mark("a1")["high_water"] == "")
check("A file hỏng vẫn ghi đè được", A.save_mark("a1", high_water="z") is True
      and A.get_mark("a1")["high_water"] == "z")
STORE.write_text("[1, 2, 3]", encoding="utf-8")
check("A JSON không phải dict → {}", A._read_all() == {} and A.get_mark("a1")["high_water"] == "")
STORE.write_text(json.dumps({"a1": "một chuỗi", "a2": {"high_water": "ok"}}), encoding="utf-8")
check("A entry lạ kiểu bị bỏ, entry lành vẫn đọc được",
      A._read_all() == {"a2": {"high_water": "ok"}} and A.get_mark("a2")["high_water"] == "ok")
STORE.write_text(json.dumps({"a1": {"published_today": "ba", "last_fired_at": "sớm",
                                    "day": A._today()}}), encoding="utf-8")
m = A.get_mark("a1")
check("A số rác → 0, không ném", m["published_today"] == 0 and m["last_fired_at"] == 0.0, m)
# Ổ đĩa hỏng: _store_path ném → đọc trả {}, ghi trả False, không ai ném
A._store_path = lambda: (_ for _ in ()).throw(OSError("disk gone"))
check("A đĩa hỏng: đọc → {}", A._read_all() == {})
check("A đĩa hỏng: ghi → False, không ném", A.save_mark("a1", high_water="q") is False)
check("A đĩa hỏng: get_mark vẫn trả mặc định", A.get_mark("a1")["published_today"] == 0)
A._store_path = lambda: STORE
check("A save_mark không có agent_id → False", A.save_mark("") is False)
print("A sổ JSON    : thiếu/hỏng/lạ kiểu → mặc định | khứ hồi | tmp+replace | đĩa hỏng không ném")

# ── B. Đếm bài mới ──────────────────────────────────────────────────────────
reset_store()
ROWS[:] = [
    {"scraped_at": "2026-09-03T10:00:00+00:00", "has_content": True, "_today": False},
    {"scraped_at": "2026-09-04T08:00:00+00:00", "has_content": True, "_today": True},
    {"scraped_at": "2026-09-04T09:00:00+00:00", "has_content": True, "_today": True},
    {"scraped_at": "2026-09-04T09:30:00+00:00", "has_content": False, "_today": True},
]
QUERY_CALLS[:] = []
a = agent()
count, newest = A.scan_new(a, "2026-09-04T08:30:00+00:00")
check("B chỉ đếm bài mới hơn mốc", count == 1, count)
check("B newest = mốc mới nhất đã đếm", newest == "2026-09-04T09:00:00+00:00", newest)
kw = QUERY_CALLS[-1]
check("B hỏi kho với only_with_content=True", kw.get("only_with_content") is True, kw)
check("B có mốc → không lọc theo ngày", kw.get("day") is None, kw)
check("B quét theo chiều GIẢM (asc + limit 500 = 500 dòng CŨ NHẤT)",
      kw.get("order") == "desc" and kw.get("limit") == P.PAGE_LIMIT == 500, kw)
check("B đúng agent + đúng phạm vi hồ sơ",
      kw.get("agent_id") == "a1" and list(kw.get("allowed_profiles") or []) == ["p1"], kw)
count, newest = A.scan_new(a, "")
check("B chưa có mốc → CHỈ hôm nay (không quét cả kho cũ)", count == 2, count)
check("B chưa có mốc → newest vẫn là bài mới nhất hôm nay",
      newest == "2026-09-04T09:00:00+00:00", newest)
check("B chưa có mốc → day='today' gửi xuống kho", QUERY_CALLS[-1].get("day") == "today")
check("B bài chưa cào được nội dung KHÔNG được tính",
      A.scan_new(a, "2026-09-04T09:10:00+00:00")[0] == 0)
check("B new_pages() = con số của scan_new", A.new_pages(a, "") == 2)


def boom(**kw):
    raise OSError("scraped_data unreadable")


SS.query = boom
check("B kho hỏng → (0, ''), không ném", A.scan_new(a, "") == (0, ""))
SS.query = fake_query
print("B đếm bài    : chỉ bài có nội dung | > mốc | chưa có mốc thì chỉ hôm nay | kho hỏng không ném")

# ── C. Các cửa ải ───────────────────────────────────────────────────────────
reset_store()
PLAN_CALLS[:] = []
r = fire(agent(), outcome="error")
check("C outcome hỏng → nói rõ outcome", r == "skip: outcome=error", r)
check("C outcome hỏng → không đụng kho, không queue", not PLAN_CALLS)
check("C timeout_kill_failed cũng không tính", fire(agent(), outcome="timeout_kill_failed")
      == "skip: outcome=timeout_kill_failed")
for ok in A.OK_OUTCOMES:
    check("C %s là kết cục có thu hoạch" % ok, not fire(agent(publish_min_pages=99),
                                                       outcome=ok).startswith("skip: outcome"))
AGENTS.clear()
r = A.maybe_publish_after_run("ma-khong-co", "run-1", "completed")
check("C agent không tồn tại → nói tên", r == "skip: agent ma-khong-co not found", r)
check("C không có agent_id → nói rõ",
      A.maybe_publish_after_run("", "run-1", "completed") == "skip: no agent id")
r = fire(agent(auto_publish=False))
check("C công tắc tắt", r == "skip: auto-publish off", r)
r = fire(agent(publish_token_id=""))
check("C bật mà chưa có token → KHÔNG im lặng",
      r == "skip: auto-publish armed but no YouTube token chosen", r)
r = fire(agent(publish_channel_id=""))
check("C bật mà chưa chọn kênh → KHÔNG im lặng",
      r == "skip: auto-publish armed but no YouTube channel chosen", r)
check("C chưa chọn kênh thì không queue gì", not PLAN_CALLS)
# trần ngày
A.save_mark("a1", published_today=2, day=A._today())
r = fire(agent(publish_max_per_day=2))
check("C chạm trần ngày → nói cả số", r == "skip: daily cap reached (2/2)", r)
A.save_mark("a1", published_today=0, day=A._today())
# chống dội: việc trước còn chạy
CODEX.tasks["t-run"] = {"id": "t-run", "seq": 7, "status": "running"}
A.save_mark("a1", last_task_id="t-run", last_fired_at=time.time())
r = fire(agent())
check("C chống dội khi việc trước còn chạy", r.startswith("skip: debounced"), r)
check("C chống dội → không queue thêm", not PLAN_CALLS)
CODEX.tasks["t-run"]["status"] = "done"
r = fire(agent(publish_min_pages=99))
check("C việc trước xong rồi thì thôi chống dội", not r.startswith("skip: debounced"), r)
A.save_mark("a1", last_fired_at=time.time() - A.DEBOUNCE_SEC - 1, last_task_id="t-run")
CODEX.tasks["t-run"]["status"] = "running"
r = fire(agent(publish_min_pages=99))
check("C quá cửa sổ chống dội thì cũng thôi", not r.startswith("skip: debounced"), r)
# chưa đủ bài
reset_store()
r = fire(agent(publish_min_pages=3))
check("C chưa đủ bài → nói cả có mấy / cần mấy", r == "skip: only 2 new page(s), needs 3", r)
check("C chưa đủ bài → mốc KHÔNG bị dời", A.get_mark("a1")["high_water"] == "")
print("C cửa ải     : outcome | agent | tắt | chưa chọn kênh (kêu to) | trần ngày | chống dội | chưa đủ bài")

# ── D. Sang ngày mới ────────────────────────────────────────────────────────
reset_store()
PLAN_CALLS[:] = []
A.save_mark("a1", published_today=9, day="2000-01-01")
check("D bộ đếm của hôm qua tự quy 0 lúc ĐỌC", A.get_mark("a1")["published_today"] == 0)
check("D và ngày đọc ra là hôm nay", A.get_mark("a1")["day"] == A._today())
r = fire(agent(publish_min_pages=1, publish_max_per_day=2))
check("D sang ngày mới thì bắn được lại", r.startswith("queued:"), r)
mD = A.get_mark("a1")
A.commit_published("a1", mD["high_water_pending"], task_id=mD["last_task_id"])
check("D đếm lại từ 1", A.get_mark("a1")["published_today"] == 1)
print("D sang ngày  : bộ đếm hôm qua không khoá được hôm nay")

# ── E. Bắn thật ─────────────────────────────────────────────────────────────
reset_store()
PLAN_CALLS[:] = []
a = agent(publish_min_pages=2, publish_privacy="unlisted", content_video_preset="Tin nhanh")
r = fire(a, run_id="run-77")
check("E trả về câu queued có số bài + tên kênh",
      r.startswith("queued:") and "2 new page(s)" in r and "Kênh Tin Nhanh" in r, r)
call = PLAN_CALLS[-1] if PLAN_CALLS else {}
check("E ĐÚNG MỘT task được xếp", len(PLAN_CALLS) == 1, PLAN_CALLS)
# Không còn cổng duyệt nào để bỏ qua: chế độ tự động là MỘT task chạy trọn,
# nên bằng chứng đúng là nó gọi create_auto_task chứ không phải create_plan_task.
check("E dùng create_auto_task — một task chạy trọn, không ô duyệt",
      call.get("job_label") == "Auto publish" and "approval_required" not in call, call)
o = call.get("options") or {}
check("E options publish=True (cũng là công tắc bước upload)", o.get("publish") is True, o)
check("E mang đúng token/kênh/tên kênh của agent",
      o.get("publish_token_id") == "tok-1" and o.get("publish_channel_id") == "UC123"
      and o.get("publish_channel_name") == "Kênh Tin Nhanh", o)
check("E quyền riêng tư của agent, không phải mặc định", o.get("publish_privacy") == "unlisted", o)
check("E mẫu (vibe) của agent đi kèm", o.get("preset") == "Tin nhanh", o)
check("E mốc cũ đi cả trong options lẫn tham số",
      o.get("high_water_prev") == "" and call.get("high_water_prev") == "", call)
check("E CHẶN TRÊN cũng đi kèm — bài cào được trong lúc task chạy là của lượt sau",
      o.get("high_water") == "2026-09-04T09:00:00+00:00"
      and call.get("high_water") == "2026-09-04T09:00:00+00:00", call)
check("E cờ autopublish để pipeline biết ghi sổ ngược lại", o.get("autopublish") is True, o)
check("E created_by / job_label",
      call.get("created_by") == "autopublish" and call.get("job_label") == "Auto publish", call)
check("E origin nói rõ lượt chạy nào châm ngòi",
      (call.get("origin") or {}).get("run_id") == "run-77"
      and (call.get("origin") or {}).get("trigger") == "scraped_run", call)
m = A.get_mark("a1")
check("E mốc TẠM ghi tới bài mới nhất (chỉ để chống dội)",
      m["high_water_pending"] == "2026-09-04T09:00:00+00:00", m)
check("E mốc THẬT chưa nhúc nhích — video còn chưa lên kênh", m["high_water"] == "", m)
check("E bộ đếm ngày cũng chưa tăng", m["published_today"] == 0, m)
check("E nhớ task vừa xếp + thời điểm", m["last_task_id"].startswith("task-")
      and m["last_fired_at"] > 0, m)
# Video lên kênh: giờ mới dời mốc thật và tính một suất.
A.commit_published("a1", m["high_water_pending"], video_url="https://youtu.be/VID1",
                   task_id=m["last_task_id"])
m = A.get_mark("a1")
check("E đăng xong → mốc thật dời tới bài mới nhất",
      m["high_water"] == "2026-09-04T09:00:00+00:00", m)
check("E đăng xong → bộ đếm ngày tăng 1", m["published_today"] == 1, m)
# lượt kế tiếp: mốc đã dời nên không còn bài nào mới (đóng task trước lại để
# cửa chống dội không che mất câu trả lời thật)
CODEX.tasks[m["last_task_id"]]["status"] = "done"
r2 = fire(agent(publish_min_pages=1))
check("E lượt sau không có bài mới → không làm lại video",
      r2 == "skip: only 0 new page(s), needs 1", r2)
check("E vẫn chỉ một task tổng cộng", len(PLAN_CALLS) == 1, PLAN_CALLS)
# agent không đặt mẫu → không nhét khoá preset rỗng vào options
reset_store()
PLAN_CALLS[:] = []
fire(agent(publish_min_pages=1, content_video_preset=""))
check("E không có mẫu → không có khoá 'preset'", "preset" not in (PLAN_CALLS[-1]["options"]),
      PLAN_CALLS[-1]["options"])
print("E bắn thật   : create_auto_task (một task, không ô duyệt) | publish=True + kênh + quyền | mốc & bộ đếm dời SAU khi xếp")

# ── F. Bắn hụt ──────────────────────────────────────────────────────────────
reset_store()
A.save_mark("a1", high_water="2026-09-04T08:30:00+00:00", published_today=0, day=A._today())
PLAN_CALLS[:] = []
PLAN_RAISES[0] = RuntimeError("codex is not installed")
r = fire(agent(publish_min_pages=1))
check("F create_auto_task ném → trả câu error, KHÔNG ném ra ngoài",
      r.startswith("error: could not queue") and "codex is not installed" in r, r)
m = A.get_mark("a1")
check("F mốc KHÔNG bị dời (lượt sau thử lại đúng chỗ)",
      m["high_water"] == "2026-09-04T08:30:00+00:00", m)
check("F bộ đếm ngày KHÔNG tăng", m["published_today"] == 0, m)
check("F mốc tạm cũng không bị ghi", m["high_water_pending"] == "", m)
PLAN_RAISES[0] = None
r = fire(agent(publish_min_pages=1))
check("F lượt sau vẫn còn bài để làm lại", r.startswith("queued:"), r)
# lỗi ở giữa chừng cũng không được thoát ra ngoài
_get = AG.agent_manager.get
AG.agent_manager.get = lambda aid: (_ for _ in ()).throw(RuntimeError("agents.json locked"))
r = A.maybe_publish_after_run("a1", "run-x", "completed")
check("F lỗi bất kỳ → 'error: …', không ném", r.startswith("error:") and "locked" in r, r)
AG.agent_manager.get = _get
print("F bắn hụt    : không dời mốc, không tăng đếm, không ném")

# ── G. Không có cổng duyệt nào để lách ────────────────────────────────────
# Bản đầu dựng một luồng nền ngồi chờ task vào REVIEW rồi tự bấm Accept — chạy
# được, nhưng là giả làm người duyệt. Nay cổng bị bỏ hẳn: chế độ tự động chạy
# trọn trong một task, lúc vào REVIEW thì video đã lên. Test này khoá lại điều
# đó để không ai dựng lại cây cầu.
import inspect as _inspect

_src = _inspect.getsource(A)
for gone in ("_arm_auto_accept", "accept_if_waiting", "complete_review", "_settle_pending"):
    check("G không còn %s" % gone, gone not in _src, gone)
check("G không dựng luồng nền nào", "Thread(" not in _src)
check("G chỉ dùng create_auto_task", "create_auto_task" in _src and "create_plan_task" not in _src)
_pl = _inspect.getsource(P)
check("G pipeline có KIND_AUTO chạy trọn dãy bước",
      'KIND_AUTO = "content_video.auto"' in _pl and "AUTO_STEPS = PLAN_STEPS + RENDER_STEPS[1:]" in _pl
      and "_run_steps(AUTO_STEPS" in _pl, "")
check("G run_kind điều phối KIND_AUTO", "if kind == KIND_AUTO:" in _pl and "return run_auto(" in _pl)
check("G create_auto_task xếp task kind auto, approval_required=False",
      '"kind": KIND_AUTO' in _pl and "approval_required=False" in _pl.split("def create_auto_task")[1], "")
print("G không cổng : bỏ hẳn ô duyệt thay vì lách — không luồng nền, không tự-Accept")

# ── H. Móc trong process_manager ────────────────────────────────────────────
from tubecli.extensions.browser.process_manager import BrowserProcessManager  # noqa: E402
from tubecli.core import run_log as RL  # noqa: E402
from tubecli.core import run_bulletin as RB  # noqa: E402

pm_src = io.open(ROOT / "tubecli" / "extensions" / "browser" / "process_manager.py",
                 encoding="utf-8").read()
body = pm_src.split("def _record_run_end")[1].split("\n    def _log_group_failure")[0]
check("H móc nằm trong _record_run_end", "autopublish.maybe_publish_after_run" in body, "")
check("H gọi sau bản tin run_bulletin",
      body.index("run_bulletin.post_end") < body.index("autopublish.maybe_publish_after_run"), "")
check("H import trong hàm (kiểu của file), không phải đầu file",
      "from tubecli.extensions.content_video import autopublish" in body
      and "from tubecli.extensions.content_video import autopublish" not in pm_src.split("class ")[0], "")
check("H có try/except riêng bọc lời gọi",
      "auto-publish check failed" in body, "")

MGR = BrowserProcessManager.__new__(BrowserProcessManager)
ended = []
RL.end = lambda *a, **kw: ended.append((a, kw))
RB.post_end = lambda *a, **kw: None
calls = []


def exploding(agent_id, run_id="", outcome="", trigger=""):
    calls.append((agent_id, run_id, outcome))
    raise RuntimeError("autopublish exploded")


_real_trigger = A.maybe_publish_after_run
A.maybe_publish_after_run = exploding
try:
    MGR._record_run_end("run-9", "a1", "inst-1", "completed", 0,
                        "2026-09-04T10:00:00", None, profile="p1")
    ok = True
except Exception as e:  # noqa: BLE001
    ok, err = False, e
check("H autopublish ném → _record_run_end vẫn về bình thường", ok,
      "" if ok else repr(err))
check("H và nó thật sự đã được gọi", calls == [("a1", "run-9", "completed")], calls)
check("H run_log.end vẫn được ghi trước đó", len(ended) == 1, ended)
calls[:] = []
MGR._record_run_end("", "a1", "i", "completed", 0, "2026-09-04T10:00:00", None)
check("H lượt thủ công (không run_id) → không hỏi autopublish", not calls, calls)
# run_log ném cũng không được nuốt mất móc
RL.end = lambda *a, **kw: (_ for _ in ()).throw(OSError("logs full"))
calls[:] = []
MGR._record_run_end("run-10", "a1", "i", "completed", 0, "2026-09-04T10:00:00", None)
check("H run_log hỏng vẫn không nuốt mất móc autopublish",
      calls == [("a1", "run-10", "completed")], calls)
A.maybe_publish_after_run = _real_trigger       # các mục sau còn cần cò súng thật
print("H móc        : gọi sau bản tin | import trong hàm | nổ cũng không ném vào luồng theo dõi")

# ── I. Trường agent + request model ─────────────────────────────────────────
d = RealAgent(name="x").to_dict()
DEFAULTS = {"auto_publish": False, "publish_token_id": "", "publish_channel_id": "",
            "publish_channel_name": "", "publish_privacy": "public",
            "publish_min_pages": 3, "publish_max_per_day": 2}
for k, v in DEFAULTS.items():
    check("I mặc định %s = %r" % (k, v), d.get(k) == v, d.get(k))
check("I agent cũ (agents.json thiếu khoá) vẫn nạp được",
      RealAgent.from_dict({"name": "x"}).publish_max_per_day == 2)
check("I from_dict nhận giá trị",
      RealAgent.from_dict({"name": "x", "auto_publish": True,
                           "publish_channel_id": "UC9"}).publish_channel_id == "UC9")
check("I None → mặc định lành", RealAgent(name="x", publish_privacy=None,
                                          publish_token_id=None).publish_privacy == "public")
check("I số rác trong file → mặc định, không nổ lúc nạp",
      RealAgent(name="x", publish_min_pages="ba").publish_min_pages == 3
      and RealAgent(name="x", publish_max_per_day=[]).publish_max_per_day == 2)
check("I chuỗi số vẫn hiểu được", RealAgent(name="x", publish_min_pages="7").publish_min_pages == 7)
check("I trần 0 là hợp lệ (khoá hẳn)", RealAgent(name="x", publish_max_per_day=0).publish_max_per_day == 0)
mgr_file = Path(tempfile.mkdtemp(prefix="autopub-agents-")) / "agents.json"
mgr = AG.AgentManager(agents_file=mgr_file)
ag = mgr.create(name="x")
mgr.update(ag.id, auto_publish=True, publish_channel_id="UC7", publish_max_per_day=1)
saved = mgr.get(ag.id)
check("I AgentManager.update ghi được (PUT /agents/{id})",
      saved.auto_publish is True and saved.publish_channel_id == "UC7"
      and saved.publish_max_per_day == 1)
check("I và xuống đĩa rồi nạp lại vẫn còn",
      json.loads(mgr_file.read_text(encoding="utf-8"))[0]["publish_channel_id"] == "UC7")
tree = ast.parse((ROOT / "tubecli" / "api" / "server.py").read_text(encoding="utf-8"))


def _fields(cls_name):
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls_name)
    return {s.target.id: ast.unparse(s.annotation) for s in node.body if isinstance(s, ast.AnnAssign)}


TYPES = {"auto_publish": "Optional[bool]", "publish_token_id": "Optional[str]",
         "publish_channel_id": "Optional[str]", "publish_channel_name": "Optional[str]",
         "publish_privacy": "Optional[str]", "publish_min_pages": "Optional[int]",
         "publish_max_per_day": "Optional[int]"}
for cls in ("AgentUpdateRequest", "AgentCreateRequest"):
    got = _fields(cls)
    for k, want in TYPES.items():
        check("I %s.%s: %s" % (cls, k, want), got.get(k) == want, got.get(k))
upd = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "AgentUpdateRequest")
defaults = {s.target.id: ast.unparse(s.value) for s in upd.body
            if isinstance(s, ast.AnnAssign) and s.value is not None}
# "None" trần hay "Field(None, ge=1)" đều là cùng một điều: khoá nào không gửi
# thì không đổi. Đọc chữ chứ đừng đọc nguyên văn dòng code.
def _default_is_none(expr):
    e = str(expr or "")
    return e == "None" or e.startswith("Field(None")


check("I AgentUpdateRequest mặc định None (PUT một phần không tắt nhầm auto_publish)",
      all(_default_is_none(defaults.get(k)) for k in TYPES), {k: defaults.get(k) for k in TYPES})
print("I trường     : mặc định | agent cũ nạp được | update ghi được | request model đủ trường")


# ── J. Kho quá 500 dòng: mốc phải nhìn từ đầu MỚI ───────────────────────────
# Bằng chứng trên máy thật: một lượt quét asc nhìn thấy bài mới nhất là
# 2026-07-26 trong khi quét desc thấy 2026-08-29 — nguyên một tháng vô hình.
# Nguyên nhân nằm ở đuôi scraped_store.query: sắp TOÀN BỘ kho rồi cắt
# items[offset:offset+limit], limit kẹp cứng 500. Nên "asc + limit 500" =
# 500 dòng CŨ NHẤT, và một hồ sơ quá 500 dòng là cái mốc mù hẳn: chuỗi tự đăng
# hoặc không bao giờ nổ, hoặc nổ xong chết ở bước gom — sau khi đã tiêu mất mốc
# lẫn một suất trong trần ngày.
import datetime as _dt  # noqa: E402

BIG_N = 900
_t0 = _dt.datetime(2026, 6, 1, tzinfo=_dt.timezone.utc)


def _stamp(i):
    return (_t0 + _dt.timedelta(hours=2 * i)).isoformat()


BIG = [{"scraped_at": _stamp(i), "has_content": True, "_today": False,
        "title": "Bài %d" % i, "url": "https://vd.vn/%d" % i,
        "content": "Nội dung bài %d" % i, "domain": "vd.vn"} for i in range(BIG_N)]
reset_store()
ROWS[:] = BIG
QUERY_CALLS[:] = []
HW = _stamp(BIG_N - 50)                      # còn đúng 49 bài mới hơn mốc

# Cách CŨ, gọi thẳng vào kho y như code cũ vẫn gọi: một trang asc.
old_page = fake_query(agent_id="a1", allowed_profiles=["p1"], day=None,
                      only_with_content=True, limit=500, order="asc")
old_new = [i for i in old_page["items"] if i["scraped_at"] > HW]
check("J cách cũ (asc, limit 500) MÙ HẲN với bài mới", old_new == [], len(old_new))
check("J   vì nó bốc đúng 500 dòng CŨ NHẤT",
      old_page["items"][-1]["scraped_at"] == _stamp(499), old_page["items"][-1]["scraped_at"])

QUERY_CALLS[:] = []
count, newest = A.scan_new(agent(), HW)
check("J quét giảm thấy đủ 49 bài mới", count == 49, count)
check("J   và mốc mới là bài MỚI NHẤT của kho", newest == _stamp(BIG_N - 1), newest)
check("J   hỏi kho theo chiều giảm", all(k.get("order") == "desc" for k in QUERY_CALLS),
      [k.get("order") for k in QUERY_CALLS])
check("J   dừng ngay khi chạm mốc — không lật hết cả kho", len(QUERY_CALLS) == 1, len(QUERY_CALLS))

# Mốc nằm SÂU dưới đáy: phải biết lật trang chứ không chỉ đọc trang đầu.
QUERY_CALLS[:] = []
deep = _stamp(100)
count_deep, newest_deep = A.scan_new(agent(), deep)
check("J mốc nằm sâu → lật trang cho tới khi chạm", count_deep == BIG_N - 101, count_deep)
check("J   có lật sang trang thứ hai", len(QUERY_CALLS) >= 2, len(QUERY_CALLS))
check("J   trang sau xin đúng offset kế tiếp",
      len(QUERY_CALLS) >= 2 and QUERY_CALLS[1].get("offset") == 500, QUERY_CALLS[:2])
check("J   mốc mới vẫn là bài mới nhất", newest_deep == _stamp(BIG_N - 1), newest_deep)

# Chưa có mốc lần nào: vẫn chỉ tính hôm nay, và vẫn không được mù.
BIG[-3]["_today"] = BIG[-2]["_today"] = BIG[-1]["_today"] = True
check("J chưa có mốc → chỉ hôm nay, và thấy đúng ba bài", A.scan_new(agent(), "")[0] == 3)
BIG[-3]["_today"] = BIG[-2]["_today"] = BIG[-1]["_today"] = False

# Vòng lật trang phải có đáy: kho lỗi trả mãi một trang đầy cũng không treo.
_saved_query = SS.query
SS.query = lambda **kw: {"items": [dict(BIG[-1]) for _ in range(500)], "total": 10 ** 9}
rows = P.scan_window(agent_id="a1", allowed_profiles=["p1"], hw_prev="", only_with_content=True)
check("J kho trả mãi không hết → dừng ở trần MAX_SCAN_PAGES",
      len(rows) == 500 * P.MAX_SCAN_PAGES, len(rows))
SS.query = _saved_query

# Cùng cái bug ấy ở bước GOM của pipeline: nó cũng quét asc + limit 500.
gather_state = {"agent": agent(), "profiles": ["p1"], "corpus": [], "videos": [],
                "warnings": [], "_say": lambda *a, **k: None, "_cancelled": lambda: False}
try:
    P._step_gather(gather_state, {"high_water_prev": HW, "max_items": 30})
    gather_err = ""
except Exception as e:  # noqa: BLE001
    gather_err = str(e)          # đúng cái chết im lặng ngoài đời: "nothing new"
got = gather_state["corpus"]
check("J bước gom cũng thấy bài mới (không còn 'corpus không có gì mới')",
      not gather_err and len(got) == 30 and got[-1]["scraped_at"] == _stamp(BIG_N - 1),
      gather_err or len(got))
check("J   corpus vẫn xếp CŨ TRƯỚC MỚI SAU cho người viết",
      bool(got) and [c["scraped_at"] for c in got] == sorted(c["scraped_at"] for c in got),
      got[:1])
check("J   mốc của lượt gom là bài mới nhất đã dùng",
      gather_state.get("high_water") == _stamp(BIG_N - 1), gather_state.get("high_water"))

# Chặn TRÊN: bài cào được sau lúc cò súng đếm là phần của lượt sau.
g2 = dict(gather_state, corpus=[], videos=[], warnings=[])
try:
    P._step_gather(g2, {"high_water_prev": _stamp(BIG_N - 10), "high_water": _stamp(BIG_N - 4),
                        "max_items": 30})
except Exception as e:  # noqa: BLE001
    print("   (gather clamp:", e, ")")
stamps = [c["scraped_at"] for c in g2["corpus"]]
check("J chặn trên: không ăn sang bài của lượt sau",
      stamps == [_stamp(i) for i in range(BIG_N - 9, BIG_N - 3)], stamps)
check("J   nên cùng một corpus không đẻ ra hai video",
      bool(stamps) and max(stamps) == _stamp(BIG_N - 4), stamps[-1:])
print("J kho lon    : asc+500 = 500 dòng CŨ NHẤT (mù) | quét giảm + lật trang | chặn trên cả hai đầu")

# ── K. Hai cái mốc: ghi tạm lúc xếp, ghi thật lúc video lên kênh ────────────
# Dời mốc ngay lúc xếp việc thì MỌI hỏng hóc phía sau (task lỗi, dựng chết,
# upload trượt, server khởi động lại) đều âm thầm nuốt mất đúng cửa sổ corpus
# đó — những bài ấy không bao giờ được đăng mà cũng không bao giờ được đếm lại.
ROWS[:] = [
    {"scraped_at": "2026-09-04T08:00:00+00:00", "has_content": True, "_today": True},
    {"scraped_at": "2026-09-04T09:00:00+00:00", "has_content": True, "_today": True},
]
reset_store()
PLAN_CALLS[:] = []
r = fire(agent(publish_min_pages=1))
check("K xếp việc xong: mốc THẬT vẫn đứng yên", A.get_mark("a1")["high_water"] == "", r)
check("K   bộ đếm ngày vẫn 0", A.get_mark("a1")["published_today"] == 0)
check("K   chỉ có mốc TẠM được ghi (cho cửa chống dội)",
      A.get_mark("a1")["high_water_pending"] == "2026-09-04T09:00:00+00:00")
# Task chết. Lượt sau phải nhìn thấy y nguyên những bài ấy.
mk = A.get_mark("a1")
# setdefault: nếu bản sửa bị gỡ ra thì lượt trên có thể chẳng xếp được task nào,
# và mục này phải báo hỏng sạch chứ không nổ vì KeyError.
CODEX.tasks.setdefault(mk["last_task_id"], {})["status"] = "failed"
A.save_mark("a1", last_fired_at=0)
r = fire(agent(publish_min_pages=1))
check("K task chết → lượt sau vẫn thấy đủ 2 bài và thử lại",
      r.startswith("queued:") and "2 new page(s)" in r, r)
check("K   vẫn chưa tiêu suất nào của trần ngày", A.get_mark("a1")["published_today"] == 0)

# Video lên kênh thật.
mk = A.get_mark("a1")
res = A.commit_published("a1", "2026-09-04T09:00:00+00:00",
                         video_url="https://youtu.be/AAA", task_id="task-x")
check("K đăng xong → mốc thật dời", A.get_mark("a1")["high_water"] == "2026-09-04T09:00:00+00:00", res)
check("K   bộ đếm ngày tăng đúng 1", A.get_mark("a1")["published_today"] == 1, res)
check("K   nhớ link video vừa đăng", A.get_mark("a1")["last_video_url"] == "https://youtu.be/AAA")
# Chạy lại sau khi khởi động: cùng task commit lần hai KHÔNG được tính thêm.
A.commit_published("a1", "2026-09-04T09:00:00+00:00",
                   video_url="https://youtu.be/AAA", task_id="task-x")
check("K commit lại cùng một task → chỉ tính một lần",
      A.get_mark("a1")["published_today"] == 1, A.get_mark("a1"))
A.commit_published("a1", "2026-09-04T10:00:00+00:00", video_url="https://youtu.be/BBB",
                   task_id="task-y")
check("K task khác → tính tiếp", A.get_mark("a1")["published_today"] == 2)
check("K   mốc đi tới", A.get_mark("a1")["high_water"] == "2026-09-04T10:00:00+00:00")
A.commit_published("a1", "2020-01-01T00:00:00+00:00", task_id="task-z")
check("K mốc KHÔNG bao giờ đi lui (task về đích lệch thứ tự)",
      A.get_mark("a1")["high_water"] == "2026-09-04T10:00:00+00:00", A.get_mark("a1"))
check("K không có mốc gửi kèm → lấy mốc tạm đang treo",
      A.commit_published("a2", "", task_id="t") and A.get_mark("a2")["published_today"] == 1)
check("K không có agent id → nói ra, không ném", A.commit_published("") == "no agent id")
_bad_write = A._write_all
A._write_all = lambda d: (_ for _ in ()).throw(OSError("disk gone"))
check("K sổ hỏng → trả câu lỗi, KHÔNG ném vào luồng thợ codex",
      A.commit_published("a1", "2026-09-05T00:00:00+00:00", task_id="t2") is not None)
A._write_all = _bad_write
print("K hai moc    : xếp việc chỉ ghi mốc TẠM | mốc thật + suất ngày chỉ dời khi video đã lên | commit hai lần = một")

# ── L. Extension bị tắt + lượt chạy tay ────────────────────────────────────
import tubecli.extensions.content_video.capabilities as CAP  # noqa: E402

_real_installed = CAP.installed_extensions
reset_store()
PLAN_CALLS[:] = []
CAP.installed_extensions = lambda: {"content_video": False, "browser": True}
r = fire(agent(publish_min_pages=1))
check("L extension bị TẮT → nói rõ, không xếp việc",
      r == "skip: the Content Video extension is disabled" and not PLAN_CALLS, r)
CAP.installed_extensions = lambda: {"browser": True}
r = fire(agent(publish_min_pages=1))
check("L extension bị GỠ → câu khác hẳn",
      r == "skip: the Content Video extension is not installed", r)
CAP.installed_extensions = lambda: {}
r = fire(agent(publish_min_pages=1))
check("L không hỏi được danh sách extension → ĐỪNG chặn vì một câu không có đáp án",
      r.startswith("queued:"), r)
reset_store()
CAP.installed_extensions = lambda: (_ for _ in ()).throw(RuntimeError("manager down"))
r = fire(agent(publish_min_pages=1))
check("L hỏi mà nổ → cũng không chặn, và không ném ra ngoài", r.startswith("queued:"), r)
CAP.installed_extensions = lambda: {"content_video": True}
reset_store()

# Chuỗi này là "mỗi lần thu thập THEO LỊCH", không phải "mỗi lần bấm Chạy thử".
PLAN_CALLS[:] = []
r = fire(agent(publish_min_pages=1), trigger="manual")
check("L nút Chạy thử → không đăng gì cả",
      r == "skip: manual run (trigger=manual)" and not PLAN_CALLS, r)
check("L   và không đụng vào sổ", A.get_mark("a1")["high_water_pending"] == "")
r = fire(agent(publish_min_pages=1), trigger="schedule")
check("L lượt hẹn giờ → chạy bình thường", r.startswith("queued:"), r)
reset_store()
A.save_mark("a1", last_fired_at=0)
r = fire(agent(publish_min_pages=1), trigger="")
check("L chưa ai nói trigger → dễ dãi có chủ ý (mặc định chặn sẽ TẮT âm thầm cả chuỗi)",
      r.startswith("queued:"), r)
for good in A.SCHEDULED_TRIGGERS:
    reset_store()
    check("L %s là lịch" % good, fire(agent(publish_min_pages=1), trigger=good).startswith("queued:"))
print("L cua ai moi : extension tắt/gỡ → câu riêng | không hỏi được thì đừng chặn | chỉ chạy cho lượt hẹn giờ")

# ── M. Mốc không đọc được thì không được tính ───────────────────────────────
# Đếm một dòng mà `newest` vẫn rỗng nghĩa là mốc đứng yên — đúng corpus ấy châm
# ngòi lại ở MỌI lượt sau cho tới khi cạn trần ngày.
reset_store()
ROWS[:] = [
    {"scraped_at": "", "has_content": True, "_today": True},
    {"scraped_at": "hôm qua", "has_content": True, "_today": True},
    {"scraped_at": "2026-09-04T09:00:00+00:00", "has_content": True, "_today": True},
]
count, newest = A.scan_new(agent(), "")
check("M dòng không có mốc đọc được thì không tính", count == 1, count)
check("M   mốc mới là dòng duy nhất đọc được", newest == "2026-09-04T09:00:00+00:00", newest)
ROWS[:] = [{"scraped_at": "", "has_content": True, "_today": True},
           {"scraped_at": "không phải ngày", "has_content": True, "_today": True}]
check("M cả kho toàn mốc rác → 0 bài, mốc rỗng", A.scan_new(agent(), "") == (0, ""))
PLAN_CALLS[:] = []
r = fire(agent(publish_min_pages=1))
check("M   nên không bắn", not PLAN_CALLS and r.startswith("skip:"), r)
# Và nếu vì lý do nào đó vẫn có bài mà không có mốc: từ chối, nói rõ vì sao.
_real_scan = A.scan_new
A.scan_new = lambda ag, hw="": (5, "")
reset_store()
r = fire(agent(publish_min_pages=1))
A.scan_new = _real_scan
check("M có bài mà không mốc nào dùng được → từ chối kèm lý do",
      r == "skip: 5 new page(s) but none has a usable timestamp", r)
check("M   và không xếp việc", not PLAN_CALLS, PLAN_CALLS)
print("M moc rac    : dòng không parse được scraped_at không được tính | không có mốc thì không bắn")

# ── N. Quyết định phải nguyên khối ──────────────────────────────────────────
# Trước đây khoá chỉ giữ bên trong save_mark, nên hai lượt chạy của cùng một
# agent (agent nhiều hồ sơ — đúng tình huống cửa chống dội sinh ra để chặn)
# cùng đọc một cái sổ cũ, cùng qua trần ngày, cùng qua chống dội, và xếp HAI
# task. Ở đây lượt thứ hai gõ cửa ngay giữa lúc lượt thứ nhất đang xếp việc.
import threading  # noqa: E402

reset_store()
ROWS[:] = [
    {"scraped_at": "2026-09-04T08:00:00+00:00", "has_content": True, "_today": True},
    {"scraped_at": "2026-09-04T09:00:00+00:00", "has_content": True, "_today": True},
]
PLAN_CALLS[:] = []
second = {}
_plain_create = P.create_auto_task


def racing_create(*a, **kw):
    """Xếp việc xong nhưng CHƯA ghi sổ — đúng khe hở mà lượt kia lọt qua."""
    t = threading.Thread(target=lambda: second.update(
        r=A.maybe_publish_after_run("a1", "run-2", "completed")))
    t.start()
    t.join(timeout=1.5)
    second["blocked"] = t.is_alive()
    second["t"] = t
    return _plain_create(*a, **kw)


AGENTS.clear()
AGENTS["a1"] = agent(publish_min_pages=1)
P.create_auto_task = racing_create
r1 = A.maybe_publish_after_run("a1", "run-1", "completed")
P.create_auto_task = _plain_create
second["t"].join(timeout=5)
check("N lượt thứ nhất xếp được việc", r1.startswith("queued:"), r1)
check("N lượt thứ hai bị chặn ở cửa khoá cho tới khi lượt một ghi sổ xong",
      second.get("blocked") is True, second)
check("N   nên nó thấy sổ MỚI và bị chống dội, không xếp thêm task",
      str(second.get("r", "")).startswith("skip: debounced"), second.get("r"))
check("N ĐÚNG MỘT task cho hai lượt kết thúc cùng lúc", len(PLAN_CALLS) == 1, PLAN_CALLS)
print("N nguyen khoi: giữ khoá trọn cả quyết định → hai lượt kết thúc cùng lúc vẫn một video")

print("=" * 70)
if failures:
    print("%d FAIL / %d" % (len(failures), checks))
    for x in failures:
        print("  FAIL", x)
    sys.exit(1)
print("%d/%d PASS" % (checks, checks))
