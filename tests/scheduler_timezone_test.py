"""Lịch chạy theo MÚI GIỜ của agent + mốc kế tiếp có offset + xếp lại khi lịch đổi (user 17/10/2026).

Chạy:  python tests/scheduler_timezone_test.py     (exit 0 = pass)

VÌ SAO: hai agent trên VPS (UTC) đặt «08:00–23:00, 1 lượt/ngày» mà chủ ở Việt Nam thấy «hôm nay 0 lượt»: bộ hẹn
giờ so ngày/giờ bằng datetime.now() trần của máy chủ nên «08:00» là 15:00 VN, ngày mới bắt đầu 07:00 VN; đổi số
lượt trên cloud cũng không làm lõi tính lại mốc kế tiếp. Luật canh ở đây:
  1. agent.timezone hợp lệ → mọi mốc (ngày trong tuần, cửa sổ giờ, bộ đếm hôm nay, mốc kế tiếp) theo múi giờ đó;
     thiếu / sai tên → giờ máy chủ như cũ, không ném.
  2. Mốc lưu ra là ISO CÓ offset; mốc cũ không offset vẫn đọc được (coi là giờ máy chủ).
  3. schedule_plan_changed: đổi giờ/ngày/số lượt/bật-tắt/múi giờ → True (route PUT xoá mốc); chỉ đổi tên, hay
     request tự đặt schedule_next_run → False.
  4. GET /runs trả server_now + timezone + server_utc_offset_min; __version__ = .201.
"""
import datetime
import os
import re
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from zoneinfo import ZoneInfo  # noqa: E402
from tubecli.core import scheduler as S  # noqa: E402

ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print("  PASS", name)
    else:
        fail += 1
        print(f"  FAIL {name}  {detail}")


VN = ZoneInfo("Asia/Ho_Chi_Minh")
DAYS6 = ["mon", "tue", "wed", "thu", "fri", "sat"]


def agent(**kw):
    d = dict(id="a1", name="A", timezone="Asia/Ho_Chi_Minh", schedule_enabled=True, schedule_active_days=list(DAYS6),
             schedule_start_time="08:00", schedule_end_time="23:00", schedule_max_runs=10, schedule_runs_today=0,
             schedule_repeat="daily", schedule_interval=60, schedule_next_run=None, schedule_last_run=None)
    d.update(kw)
    return types.SimpleNamespace(**d)


# ── A. helpers ─────────────────────────────────────────────────────────────
print("A. agent_tz / parse_when / server_utc_offset_min")
check("agent_tz hợp lệ", getattr(S.agent_tz(agent()), "key", None) == "Asia/Ho_Chi_Minh")
check("agent_tz rỗng → None (giờ máy chủ)", S.agent_tz(agent(timezone="")) is None and S.agent_tz(agent(timezone=None)) is None)
check("agent_tz tên lạ → None, không ném", S.agent_tz(agent(timezone="Mars/Olympus")) is None)
p = S.parse_when("2026-10-17T08:00:00+07:00", agent())
check("parse_when mốc có offset → đúng giờ VN", p is not None and (p.hour, p.minute) == (8, 0) and p.utcoffset() == datetime.timedelta(hours=7))
legacy = S.parse_when("2026-10-17T01:00:00", agent())
want = datetime.datetime(2026, 10, 17, 1, 0).astimezone().astimezone(VN)
check("parse_when mốc cũ không offset = giờ máy chủ, đổi sang múi giờ agent", legacy == want, (legacy, want))
check("parse_when chuỗi hỏng / rỗng → None", S.parse_when("banana", agent()) is None and S.parse_when("", agent()) is None)
now_vn = S.now_for(agent())
check("now_for có múi giờ agent", now_vn.tzinfo is not None and now_vn.utcoffset() == datetime.timedelta(hours=7))
off = S.server_utc_offset_min()
want_off = int(datetime.datetime.now().astimezone().utcoffset().total_seconds() // 60)
check("server_utc_offset_min = offset máy chủ", off == want_off, (off, want_off))

# ── B. mốc kế tiếp theo múi giờ ───────────────────────────────────────────────
print("B. _calculate_next_schedule_time")
sched = S.Scheduler()
r = sched._calculate_next_schedule_time(agent(), datetime.datetime(2026, 10, 17, 2, 0, tzinfo=VN))  # T7 02:00 VN
check("T7 02:00 VN → T7 08:00 VN", r == datetime.datetime(2026, 10, 17, 8, 0, tzinfo=VN), r)
check("mốc giữ múi giờ, isoformat có +07:00", r.isoformat().endswith("+07:00"), r.isoformat())
r = sched._calculate_next_schedule_time(agent(), datetime.datetime(2026, 10, 18, 10, 0, tzinfo=VN))  # CN
check("CN (không chọn) → T2 08:00 VN", r == datetime.datetime(2026, 10, 19, 8, 0, tzinfo=VN), r)
r = sched._calculate_next_schedule_time(agent(schedule_runs_today=10), datetime.datetime(2026, 10, 17, 10, 0, tzinfo=VN))
check("T7 đã đủ lượt → bỏ CN → T2 08:00 VN", r == datetime.datetime(2026, 10, 19, 8, 0, tzinfo=VN), r)
r = sched._calculate_next_schedule_time(agent(), datetime.datetime(2026, 10, 17, 10, 30, tzinfo=VN))
check("trong cửa sổ, chưa đủ lượt → giữ nguyên mốc", r == datetime.datetime(2026, 10, 17, 10, 30, tzinfo=VN), r)

# ── C. schedule_plan_changed ────────────────────────────────────────────────
print("C. schedule_plan_changed")
a = agent()
check("không đổi gì → False", S.schedule_plan_changed(a, {"schedule_max_runs": 10, "schedule_start_time": "08:00"}) is False)
check("đổi số lượt (chuỗi) → True", S.schedule_plan_changed(a, {"schedule_max_runs": "11"}) is True)
check("đổi múi giờ → True", S.schedule_plan_changed(a, {"timezone": "UTC"}) is True)
check("ngày đổi thứ tự / hoa thường → False", S.schedule_plan_changed(a, {"schedule_active_days": ["Sat", "MON", "tue", "wed", "thu", "fri"]}) is False)
check("bớt một ngày → True", S.schedule_plan_changed(a, {"schedule_active_days": DAYS6[:-1]}) is True)
check("tắt lịch → True", S.schedule_plan_changed(a, {"schedule_enabled": False}) is True)
check("request tự đặt schedule_next_run → False (tôn trọng)", S.schedule_plan_changed(a, {"schedule_next_run": "", "schedule_max_runs": 99}) is False)
check("chỉ đổi tên → False", S.schedule_plan_changed(a, {"name": "B", "description": "x"}) is False)
check("updates không phải dict → False", S.schedule_plan_changed(a, None) is False)

# ── D. _tick end-to-end với đồng hồ giả ─────────────────────────────────────
print("D. _tick theo múi giờ agent")
from tubecli.core.skill import skill_manager  # noqa: E402
from tubecli.core.agent import agent_manager  # noqa: E402
from tubecli.core import run_log  # noqa: E402

# Trần trình duyệt: bản có max_concurrent_browsers() (global setting, 13/10) hoặc bản chỉ có hằng — nới cả hai.
saved = dict(get_all_s=skill_manager.get_all, get_all_a=agent_manager.get_all, save=agent_manager._save,
             now_for=S.now_for, maxb=getattr(S, "max_concurrent_browsers", None), maxc=S.MAX_CONCURRENT_AGENT_BROWSERS,
             rl_start=run_log.start, rl_skip=run_log.skip, rl_new=run_log.new_run_id, rl_sweep=run_log.sweep)
fired, skips = [], []
agents = []
try:
    skill_manager.get_all = lambda: []
    agent_manager.get_all = lambda: agents
    agent_manager._save = lambda: None
    S.MAX_CONCURRENT_AGENT_BROWSERS = 10
    if saved["maxb"]:
        S.max_concurrent_browsers = lambda: 10
    run_log.start = lambda *a, **k: None
    run_log.new_run_id = lambda: "r1"
    run_log.sweep = lambda: None
    run_log.skip = lambda aid, name, reason, detail="", **k: skips.append(reason)
    sched = S.Scheduler()
    sched._last_sweep_date = datetime.date.today()
    sched._count_running_agent_browsers = lambda: 0
    sched._log_history = lambda *a, **k: None
    sched.set_agent_runner(lambda aid, run_id=None: fired.append(aid))

    def at(dt):
        S.now_for = lambda a, _dt=dt: _dt

    # 1. Lỗi gốc: máy chủ UTC 01:00:30 = 08:00:30 VN thứ Bảy, mốc 08:00+07 → PHẢI chạy (trước đây 01:00 ngoài cửa sổ).
    agents[:] = [agent(schedule_next_run="2026-10-17T08:00:00+07:00")]
    at(datetime.datetime(2026, 10, 17, 8, 0, 30, tzinfo=VN))
    sched._tick()
    a1 = agents[0]
    check("1 đến hạn trong cửa sổ VN → chạy", fired == ["a1"], fired)
    check("1 runs_today = 1, last_run có +07:00", a1.schedule_runs_today == 1 and str(a1.schedule_last_run).endswith("+07:00"), (a1.schedule_runs_today, a1.schedule_last_run))
    nxt = S.parse_when(a1.schedule_next_run, a1)
    check("1 mốc kế tiếp có offset, sau ≥ 60 phút, trong cửa sổ", str(a1.schedule_next_run).endswith("+07:00") and nxt >= datetime.datetime(2026, 10, 17, 9, 0, tzinfo=VN) and "08:00" <= nxt.strftime("%H:%M") <= "23:00", a1.schedule_next_run)

    # 2. Chủ nhật (không chọn) → bỏ lượt inactive_day, dời sang T2 08:00 VN.
    fired.clear(); skips.clear()
    agents[:] = [agent(schedule_next_run="2026-10-18T09:00:00+07:00")]
    at(datetime.datetime(2026, 10, 18, 9, 0, 10, tzinfo=VN))
    sched._tick()
    check("2 CN → không chạy, ghi inactive_day", fired == [] and skips == ["inactive_day"], (fired, skips))
    check("2 dời sang T2 08:00 VN", agents[0].schedule_next_run == datetime.datetime(2026, 10, 19, 8, 0, tzinfo=VN).isoformat(), agents[0].schedule_next_run)

    # 3. Chưa có mốc (vừa bật / lịch vừa đổi) → xếp lượt đầu 2–20 phút, có offset, không chạy ngay.
    fired.clear(); skips.clear()
    agents[:] = [agent()]
    base = datetime.datetime(2026, 10, 17, 10, 0, tzinfo=VN)
    at(base)
    sched._tick()
    first = S.parse_when(agents[0].schedule_next_run, agents[0])
    check("3 xếp lượt đầu 2–20 phút sau, có +07:00, chưa chạy", fired == [] and str(agents[0].schedule_next_run).endswith("+07:00")
          and base + datetime.timedelta(minutes=2) <= first <= base + datetime.timedelta(minutes=20), agents[0].schedule_next_run)

    # 4. Đã đủ 1/1 lượt → daily_cap, mốc nhảy qua CN tới T2 08:00 VN (đúng cảnh hai agent của user).
    fired.clear(); skips.clear()
    agents[:] = [agent(schedule_max_runs=1, schedule_runs_today=1, schedule_last_run="2026-10-17T08:05:00+07:00",
                       schedule_next_run="2026-10-17T09:10:00+07:00")]
    at(datetime.datetime(2026, 10, 17, 9, 10, 5, tzinfo=VN))
    sched._tick()
    check("4 đủ lượt → daily_cap, không chạy", fired == [] and skips == ["daily_cap"], (fired, skips))
    check("4 mốc = T2 08:00 VN", agents[0].schedule_next_run == datetime.datetime(2026, 10, 19, 8, 0, tzinfo=VN).isoformat(), agents[0].schedule_next_run)

    # 5. Sang ngày mới THEO GIỜ VN (last_run hôm qua VN) → bộ đếm về 0 và chạy lại.
    fired.clear(); skips.clear()
    agents[:] = [agent(schedule_max_runs=1, schedule_runs_today=1, schedule_last_run="2026-10-16T22:30:00+07:00",
                       schedule_next_run="2026-10-17T08:00:00+07:00")]
    at(datetime.datetime(2026, 10, 17, 8, 0, 20, tzinfo=VN))
    sched._tick()
    check("5 ngày mới theo VN → đếm lại từ 0 và chạy", fired == ["a1"] and agents[0].schedule_runs_today == 1, (fired, agents[0].schedule_runs_today))

    # 6. Không có múi giờ → vẫn chạy theo giờ máy chủ (now_for giả trả giờ máy chủ có offset).
    fired.clear(); skips.clear()
    srv_now = datetime.datetime(2026, 10, 17, 12, 0, 5).astimezone()
    agents[:] = [agent(timezone="", schedule_next_run=srv_now.replace(second=0).isoformat())]
    at(srv_now)
    sched._tick()
    check("6 không múi giờ → chạy theo giờ máy chủ", fired == ["a1"], (fired, skips))
finally:
    skill_manager.get_all = saved["get_all_s"]
    agent_manager.get_all = saved["get_all_a"]
    agent_manager._save = saved["save"]
    S.now_for = saved["now_for"]
    S.MAX_CONCURRENT_AGENT_BROWSERS = saved["maxc"]
    if saved["maxb"]:
        S.max_concurrent_browsers = saved["maxb"]
    run_log.start, run_log.skip, run_log.new_run_id, run_log.sweep = saved["rl_start"], saved["rl_skip"], saved["rl_new"], saved["rl_sweep"]

# ── E. route + phiên bản (tĩnh) ───────────────────────────────────────────────
print("E. server.py + __version__")
srv = open(os.path.join(ROOT, "tubecli", "api", "server.py"), encoding="utf-8").read()
check("GET /runs trả server_now", '"server_now": now_for(agent).isoformat()' in srv)
check("GET /runs trả timezone + server_utc_offset_min", '"server_utc_offset_min": server_utc_offset_min()' in srv and '"timezone": str(getattr(agent, "timezone", "") or "") if agent_tz(agent) else ""' in srv)
check("PUT /agents/{id} xoá mốc khi lịch đổi", 'if schedule_plan_changed(current, data):' in srv and 'data["schedule_next_run"] = ""' in srv)
init = open(os.path.join(ROOT, "tubecli", "__init__.py"), encoding="utf-8").read()
check("__version__ = 2026.08.09.201", re.search(r'^__version__ = "2026\.08\.09\.201"', init, re.M) is not None)

print(f"\n{ok}/{ok + fail} PASS")
sys.exit(1 if fail else 0)
