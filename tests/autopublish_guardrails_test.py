# -*- coding: utf-8 -*-
"""Hai hàng rào của dây chuyền tự đăng: giá trị bẩn, và lượt chạy thử.

Run:  PYTHONIOENCODING=utf-8 python -X utf8 tests/autopublish_guardrails_test.py

Vì sao phải khoá lại bằng test:

  1. PUT /api/v1/agents/{id} đổ thẳng body vào AgentManager.update, nơi code cũ
     chỉ có `if hasattr(agent, k): setattr(agent, k, v)` — bỏ qua TOÀN BỘ phép
     ép kiểu Agent.__init__ vừa làm. Một lần gọi API là đủ để cài
     publish_min_pages=-1 (ngưỡng "đủ bài mới" luôn đúng ⇒ mỗi lượt một video
     rác), publish_max_per_day=2.5, hay publish_privacy="banana" (YouTube từ
     chối, mất cả video vừa dựng). Hỏng âm thầm tới tận lần khởi động sau, vì
     lúc nạp lại từ đĩa Agent.__init__ mới ép kiểu.

  2. Nút "Chạy thử" gọi run_agent_routine(trigger="manual"), hàm này TỰ mint
     một run_id thật — nên cái chặn duy nhất trong _record_run_end
     ("if not run_id") không thấy gì khác thường và một lần thử nghiệm đẻ ra
     video CÔNG KHAI người dùng không hề yêu cầu.

Kiểm, đối chiếu code thật:
  A. Ép kiểu     — coerce_publish_value: rác → mặc định, 0 sống, chuỗi số hiểu
                   được, quyền lạ quy về public
  B. Cửa PUT     — AgentManager.update ép kiểu như hàm dựng; 0 vẫn là 0; trường
                   khác không bị đụng; xuống đĩa rồi nạp lại vẫn sạch
  C. Tầng API    — AgentCreateRequest/AgentUpdateRequest từ chối -1 / 0 /
                   2.5 / "banana"; nhận "3" và 0; None = "không đụng tới"
  D. Chạy thử    — _record_run_end đọc trigger từ sổ run_log và đưa xuống
                   autopublish: lượt manual không bắn, lượt schedule có bắn
"""
import io
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

import tubecli.config as cfg  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="autopub-guard-"))
# run_log gọi ext_data_path() bên trong _dir() nên vá sau khi import vẫn ăn.
cfg.ext_data_path = lambda *parts: TMP.joinpath(*parts)

from tubecli.core import agent as AG  # noqa: E402
from tubecli.core import run_log as RL  # noqa: E402
from tubecli.core import run_bulletin as RB  # noqa: E402

failures = []
checks = 0


def check(label, ok, detail=""):
    global checks
    checks += 1
    if not ok:
        failures.append("%s: %s" % (label, detail))


print("=" * 70)
print("HÀNG RÀO TỰ ĐĂNG — GIÁ TRỊ BẨN & LƯỢT CHẠY THỬ")
print("=" * 70)

# ── A. Ép kiểu một chỗ ─────────────────────────────────────────────────────
C = AG.coerce_publish_value
TABLE = [
    ("publish_min_pages", -1, 1), ("publish_min_pages", 0, 1),
    ("publish_min_pages", "3", 3), ("publish_min_pages", "ba", 3),
    ("publish_min_pages", None, 3), ("publish_min_pages", 7, 7),
    ("publish_max_per_day", -5, 0), ("publish_max_per_day", 0, 0),
    ("publish_max_per_day", 2.5, 2), ("publish_max_per_day", [], 2),
    ("publish_max_per_day", "4", 4),
    ("publish_privacy", "banana", "public"), ("publish_privacy", "", "public"),
    ("publish_privacy", None, "public"), ("publish_privacy", "UNLISTED", "unlisted"),
    ("publish_privacy", " private ", "private"), ("publish_privacy", 7, "public"),
    ("auto_publish", "yes", True), ("auto_publish", 0, False),
    ("publish_token_id", None, ""), ("publish_channel_id", 12, "12"),
]
for key, raw, want in TABLE:
    got = C(key, raw)
    check("A %s(%r) → %r" % (key, raw, want), got == want and type(got) is type(want), repr(got))
check("A khoá lạ đi qua không suy suyển", C("name", "MC") == "MC")
check("A ba lựa chọn quyền riêng tư, không hơn",
      AG.PUBLISH_PRIVACY_CHOICES == ("public", "unlisted", "private"),
      AG.PUBLISH_PRIVACY_CHOICES)
check("A hàm dựng dùng đúng bộ luật đó",
      AG.Agent(name="x", publish_min_pages=-1, publish_max_per_day=-3,
               publish_privacy="banana").publish_min_pages == 1
      and AG.Agent(name="x", publish_max_per_day=-3).publish_max_per_day == 0
      and AG.Agent(name="x", publish_privacy="banana").publish_privacy == "public")
print("A ép kiểu    : rác → mặc định | 0 sống | \"3\" hiểu được | quyền lạ → public")

# ── B. Cửa PUT: AgentManager.update ────────────────────────────────────────
agents_file = TMP / "agents.json"
mgr = AG.AgentManager(agents_file=agents_file)
ag = mgr.create(name="MC")

# Đúng hình dạng một PUT: model_dump(exclude_none=True) của AgentUpdateRequest.
mgr.update(ag.id, auto_publish=True, publish_min_pages=-1, publish_max_per_day=2.5,
           publish_privacy="banana", publish_token_id=None, description="mô tả mới")
saved = mgr.get(ag.id)
check("B min_pages=-1 → 1 (không còn ngưỡng luôn đúng)", saved.publish_min_pages == 1,
      saved.publish_min_pages)
check("B max_per_day=2.5 → 2", saved.publish_max_per_day == 2, saved.publish_max_per_day)
check("B privacy='banana' → public", saved.publish_privacy == "public", saved.publish_privacy)
check("B token_id=None → chuỗi rỗng, không phải None", saved.publish_token_id == "",
      repr(saved.publish_token_id))
check("B auto_publish vẫn bật", saved.auto_publish is True)
check("B trường không thuộc nhóm publish_* không bị đụng",
      saved.description == "mô tả mới", saved.description)

mgr.update(ag.id, publish_max_per_day=0)
check("B trần 0 SỐNG SÓT — 0 nghĩa là tạm khoá, không phải rác",
      mgr.get(ag.id).publish_max_per_day == 0, mgr.get(ag.id).publish_max_per_day)
mgr.update(ag.id, publish_min_pages="5", publish_privacy="UNLISTED",
           publish_channel_id=99)
saved = mgr.get(ag.id)
check("B chuỗi số vẫn thành số", saved.publish_min_pages == 5, saved.publish_min_pages)
check("B quyền viết hoa vẫn hiểu", saved.publish_privacy == "unlisted", saved.publish_privacy)
check("B id kênh dạng số → chuỗi", saved.publish_channel_id == "99", repr(saved.publish_channel_id))

# xuống đĩa rồi nạp lại: không được có gì bẩn nằm chờ tới lần khởi động sau
disk = io.open(agents_file, encoding="utf-8").read()
check("B đĩa không giữ 'banana'", "banana" not in disk, "")
reloaded = AG.AgentManager(agents_file=agents_file).get(ag.id)
check("B nạp lại từ đĩa vẫn đúng",
      reloaded.publish_min_pages == 5 and reloaded.publish_max_per_day == 0
      and reloaded.publish_privacy == "unlisted",
      (reloaded.publish_min_pages, reloaded.publish_max_per_day, reloaded.publish_privacy))
check("B update task không tồn tại vẫn trả None", mgr.update("khong-co", auto_publish=True) is None)
print("B cửa PUT    : setattr thô đã bị chặn | 0 vẫn là 0 | trường khác nguyên vẹn | đĩa sạch")

# ── C. Tầng API nói \"sai rồi\" thay vì âm thầm ép ──────────────────────────
from tubecli.api.server import AgentCreateRequest, AgentUpdateRequest  # noqa: E402

BAD = [
    {"publish_min_pages": -1}, {"publish_min_pages": 0},
    {"publish_max_per_day": -1}, {"publish_max_per_day": 2.5},
    {"publish_privacy": "banana"}, {"publish_privacy": "PUBLIC_ISH"},
]
for bad in BAD:
    for model in (AgentUpdateRequest, AgentCreateRequest):
        kw = dict(bad)
        if model is AgentCreateRequest:
            kw["name"] = "MC"
        try:
            model(**kw)
            check("C %s từ chối %r" % (model.__name__, bad), False, "nhận mất rồi")
        except Exception as e:  # pydantic.ValidationError
            check("C %s từ chối %r" % (model.__name__, bad), "ValidationError" in type(e).__name__,
                  repr(e)[:120])

good = AgentUpdateRequest(publish_min_pages="3", publish_max_per_day=0,
                          publish_privacy="UNLISTED")
check("C \"3\" → 3", good.publish_min_pages == 3, good.publish_min_pages)
check("C trần 0 được nhận (tạm khoá)", good.publish_max_per_day == 0, good.publish_max_per_day)
check("C quyền viết hoa được chuẩn hoá", good.publish_privacy == "unlisted", good.publish_privacy)
dumped = AgentUpdateRequest(publish_max_per_day=0).model_dump(exclude_none=True)
check("C PUT một phần: chỉ trường được nói tới đi xuống",
      dumped == {"publish_max_per_day": 0}, dumped)
create_defaults = AgentCreateRequest(name="MC")
check("C mặc định của POST không đổi (3 / 2 / public)",
      create_defaults.publish_min_pages == 3 and create_defaults.publish_max_per_day == 2
      and create_defaults.publish_privacy == "public", create_defaults)
print("C tầng API   : -1 / 0 / 2.5 / quyền lạ → 422 | \"3\" và 0 vẫn qua | None = không đụng tới")

# ── D. Lượt \"Chạy thử\" không được đăng video ──────────────────────────────
from tubecli.extensions.browser.process_manager import BrowserProcessManager  # noqa: E402
from tubecli.extensions.content_video import autopublish as A  # noqa: E402

REAL_TRIGGER_FN = A.maybe_publish_after_run
RB.post_end = lambda *a, **kw: None          # không đẩy bản tin vào chat thật
MGR = BrowserProcessManager.__new__(BrowserProcessManager)

RL.start("run-manual", "a1", "MC", trigger="manual")
RL.start("run-sched", "a1", "MC", trigger="schedule")

CALLS = []


def spy(agent_id, run_id="", outcome="", trigger=""):
    CALLS.append({"agent_id": agent_id, "run_id": run_id, "outcome": outcome,
                  "trigger": trigger})
    return "stub"


A.maybe_publish_after_run = spy
MGR._record_run_end("run-manual", "a1", "i1", "completed", 0, "2026-09-04T10:00:00", None,
                    profile="p1")
check("D lượt manual: trigger đi kèm xuống autopublish",
      CALLS and CALLS[-1]["trigger"] == "manual", CALLS)
MGR._record_run_end("run-sched", "a1", "i2", "completed", 0, "2026-09-04T10:00:00", None,
                    profile="p1")
check("D lượt hẹn giờ: trigger='schedule'", CALLS[-1]["trigger"] == "schedule", CALLS[-1])
CALLS[:] = []
MGR._record_run_end("run-khong-co-trong-so", "a1", "i3", "completed", 0,
                    "2026-09-04T10:00:00", None, profile="p1")
check("D không tra được trigger → vẫn gọi, để autopublish tự quyết (không tắt câm cả chuỗi)",
      len(CALLS) == 1 and CALLS[-1]["trigger"] == "", CALLS)
check("D _run_trigger đọc thẳng sổ run_log",
      MGR._run_trigger("run-manual", "a1") == "manual"
      and MGR._run_trigger("run-sched", "a1") == "schedule"
      and MGR._run_trigger("run-sched", "agent-khac") == ""
      and MGR._run_trigger("", "a1") == "", "")

# Bản content_video CŨ (chưa có tham số trigger): thà không đăng còn hơn đăng nhầm.
OLD_CALLS = []


def old_signature(agent_id, run_id="", outcome=""):
    OLD_CALLS.append((agent_id, run_id, outcome))
    return "old"


A.maybe_publish_after_run = old_signature
MGR._record_run_end("run-manual", "a1", "i4", "completed", 0, "2026-09-04T10:00:00", None,
                    profile="p1")
check("D autopublish cũ + lượt manual → KHÔNG gọi (bên thua thiệt là 'không đăng')",
      OLD_CALLS == [], OLD_CALLS)
MGR._record_run_end("run-sched", "a1", "i5", "completed", 0, "2026-09-04T10:00:00", None,
                    profile="p1")
check("D autopublish cũ + lượt hẹn giờ → vẫn gọi kiểu 3 tham số",
      OLD_CALLS == [("a1", "run-sched", "completed")], OLD_CALLS)

# Giao kèo với nửa bên kia (autopublish thật): lượt manual bị chặn ở đó.
A.maybe_publish_after_run = REAL_TRIGGER_FN
r = A.maybe_publish_after_run("a1", "run-manual", "completed", "manual")
check("D autopublish thật chặn lượt manual", r.startswith("skip:") and "manual" in r.lower(), r)
r2 = A.maybe_publish_after_run("khong-co-agent", "run-sched", "completed", "schedule")
check("D lượt hẹn giờ đi tiếp qua cửa trigger", not r2.startswith("skip: manual"), r2)
pm_src = io.open(ROOT / "tubecli" / "extensions" / "browser" / "process_manager.py",
                 encoding="utf-8").read()
body = pm_src.split("def _record_run_end")[1].split("\n    def _log_group_failure")[0]
check("D móc autopublish nhận trigger", "trigger=trigger" in body, "")
print("D chạy thử   : trigger đọc ngược từ run_log | manual không bắn | bản cũ thì thà không đăng")

print("=" * 70)
if failures:
    print("%d FAIL / %d" % (len(failures), checks))
    for x in failures:
        print("  FAIL", x)
    sys.exit(1)
print("%d/%d PASS" % (checks, checks))
