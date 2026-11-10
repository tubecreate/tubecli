# -*- coding: utf-8 -*-
"""Dọn phiên trình duyệt quá giờ + đếm chỗ cho bộ lập lịch + lý do tự đăng vào run_log + history bỏ log (10/11/2026).

Run:  PYTHONIOENCODING=utf-8 python tests/browser_session_reaper_test.py     (exit 0 = pass)

Không tiến trình thật, không trình duyệt, không đụng DATA_DIR thật: phiên là dict giả, terminate là hàm giả,
SQLite là file tạm.
"""
import asyncio
import importlib.util
import os
import sys
import tempfile
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from tubecli.extensions.browser import session_reaper as R  # noqa: E402

ok = fail = 0


def check(name, cond, info=""):
    global ok, fail
    if cond:
        ok += 1
        print("  PASS", name)
    else:
        fail += 1
        print(f"  FAIL {name} {info}")


NOW = time.time()


def inst(iid, profile, age_min, url="", run_id=None, agent_id=None, maxd=None, status="running"):
    return {"instance_id": iid, "profile": profile, "status": status, "_url": url, "_run_id": run_id,
            "_agent_id": agent_id, "_max_duration": maxd,
            "started_at": datetime.fromtimestamp(NOW - age_min * 60 - 1).isoformat(),
            "command": f"node open.js --profile {profile} --manual" + (f" --url {url}" if url else "")}


MUSE = "https://muse.ai/"

print("=== 1. loại phiên ===")
check("Muse ẩn", R.session_kind(inst("a", "muse-vinh-20", 5, MUSE, maxd=6 * 3600)) == R.KIND_MUSE)
check("lượt theo lịch", R.session_kind(inst("b", "gmail_x", 5, "", run_id="run-1", agent_id="ag", maxd=500))
      == R.KIND_SCHEDULED)
check("làm mới cookie", R.session_kind(inst("c", "p", 5, "https://www.youtube.com/", maxd=300)) == R.KIND_COOKIES)
check("mở tay", R.session_kind(inst("d", "test", 5)) == R.KIND_MANUAL)

print("=== 2. ai giữ chỗ (dòng busy) ===")
hs = R.holders([inst("m1", "muse-vinh-20", 107, MUSE, maxd=21600), inst("m2", "muse-vinh-22", 33, MUSE, maxd=21600),
                inst("s", "gmail_pk", 2, run_id="r", agent_id="a", maxd=500),
                inst("x", "old", 9, status="completed")], NOW)
check("bỏ phiên đã xong", len(hs) == 3, hs)
check("cũ nhất trước", hs[0]["profile"] == "muse-vinh-20", hs)
txt = R.describe_holders(hs)
check("nói hồ sơ + loại + tuổi", "muse-vinh-20 (Muse, hidden, 1h47m)" in txt and "gmail_pk (scheduled run, 2m)" in txt,
      txt)
many = R.holders([inst(f"m{i}", f"muse-{i}", i, MUSE) for i in range(12)], NOW)
check("cắt danh sách dài", "+4 more" in R.describe_holders(many), R.describe_holders(many))

print("=== 3. Muse ẩn chiếm tối đa trần − 1 ===")
seven = R.holders([inst(f"m{i}", f"muse-vinh-{20 + i}", 30, MUSE) for i in range(7)], NOW)
check("7 Muse, trần 5 → đếm 4 (còn 1 chỗ cho lượt lịch)", R.counted_for_cap(seven, 5) == 4,
      R.counted_for_cap(seven, 5))
plus_one = seven + R.holders([inst("s", "gmail_x", 1, run_id="r", agent_id="a")], NOW)
check("thêm 1 lượt lịch → đủ trần (không mở thêm cái thứ 9)", R.counted_for_cap(plus_one, 5) == 5)
two_muse = R.holders([inst("m1", "a", 1, MUSE), inst("m2", "b", 1, MUSE), inst("t", "test", 1)], NOW)
check("ít Muse: đếm đủ như cũ", R.counted_for_cap(two_muse, 5) == 3)
check("trần 1: Muse không chiếm chỗ nào", R.counted_for_cap(R.holders([inst("m", "a", 1, MUSE)], NOW), 1) == 0)
five_other = R.holders([inst(f"o{i}", f"p{i}", 1) for i in range(5)], NOW)
check("phiên thường vẫn đếm đủ", R.counted_for_cap(five_other, 5) == 5)

print("=== 4. kế hoạch dọn ===")
rows = [
    inst("muse_busy", "muse-vinh-20", 400, MUSE, maxd=21600),           # đang bận → giữ
    inst("muse_idle", "muse-vinh-21", 120, MUSE, maxd=21600),           # rảnh 40' → dọn
    inst("muse_fresh", "muse-vinh-22", 10, MUSE, maxd=21600),           # mới mở, chưa nhận lượt → giữ
    inst("muse_recent", "muse-vinh-23", 200, MUSE, maxd=21600),         # vừa xong lượt 5' trước → giữ
    inst("overrun", "gmail_a", 20, run_id="r1", agent_id="ag1", maxd=500),   # 1200 s > 500+180 → dọn
    inst("in_time", "gmail_b", 5, run_id="r2", agent_id="ag2", maxd=500),    # còn hạn → giữ
    inst("manual_old", "hand", 5 * 60),                                 # mở tay 5 giờ → dọn
    inst("manual_live", "watched", 9 * 60),                             # có người xem → giữ
    inst("manual_young", "hand2", 60),                                  # 1 giờ → giữ
    inst("muse_over_live", "muse-vinh-24", 7 * 60, MUSE, maxd=21600),   # quá 6h nhưng đang xem live → giữ
    inst("done", "gone", 999, status="completed"),
]
plan = R.plan_sweep(rows, NOW, live_profiles=["watched", "muse-vinh-24"],
                    muse_busy={"muse-vinh-20": 1},
                    muse_last_active={"muse-vinh-21": NOW - 40 * 60, "muse-vinh-23": NOW - 5 * 60})
ids = {p["instance_id"]: p for p in plan}
check("dọn đúng 3 phiên", set(ids) == {"muse_idle", "overrun", "manual_old"}, sorted(ids))
check("  Muse rảnh: lý do có thời gian rảnh", "idle for 40m" in ids.get("muse_idle", {}).get("reason", ""), ids)
check("  quá hạn: nêu hạn", "past its 8m limit" in ids.get("overrun", {}).get("reason", ""), ids)
check("  mở tay: nêu hạn 4h", "limit 4h00m" in ids.get("manual_old", {}).get("reason", ""), ids)
check("manual_max=0 tắt dọn mở tay",
      "manual_old" not in {p["instance_id"] for p in R.plan_sweep(rows, NOW, ["watched", "muse-vinh-24"],
                                                                 {"muse-vinh-20": 1}, {}, manual_max=0)})
over_muse = [inst("mo", "muse-x", 6 * 60 + 10, MUSE, maxd=21600)]
check("Muse quá 6h + 3' mà rảnh → dọn vì quá hạn",
      "past its" in (R.plan_sweep(over_muse, NOW, [], {}, {}) or [{}])[0].get("reason", ""))
check("Muse quá 6h mà ĐANG BẬN → giữ", R.plan_sweep(over_muse, NOW, [], {"muse-x": 1}, {}) == [])

print("=== 5. sweep thật: gọi terminate + ghi log, nhịp 60 s ===")
from tubecli.extensions.browser import process_manager as PM  # noqa: E402

pm = PM.browser_process_manager


class FakeProc:
    def poll(self):
        return None


notes = []
from tubecli.core import run_log  # noqa: E402

real_note = getattr(run_log, "note", None)
run_log.note = lambda run_id, agent_id, text, kind="info": notes.append((run_id, agent_id, kind, text))
saved = dict(pm._instances)
pm._instances.clear()
for r in rows:
    r = dict(r)
    r["_process"] = FakeProc()
    pm._instances[r["instance_id"]] = r
real_live, real_muse = R._live_profiles, R._muse_state
R._live_profiles = lambda: ["watched", "muse-vinh-24"]
R._muse_state = lambda: ({"muse-vinh-20": 1}, {"muse-vinh-21": NOW - 40 * 60, "muse-vinh-23": NOW - 5 * 60})
killed = []
try:
    done = R.sweep(now=NOW, force=True, terminate=lambda iid: killed.append(iid) or True)
    check("terminate đúng 3 phiên", sorted(killed) == ["manual_old", "muse_idle", "overrun"], killed)
    check("lượt agent quá giờ ghi note vào run_log",
          any(n[0] == "r1" and n[2] == "reaper" and "gmail_a" in n[3] for n in notes), notes)
    check("phiên không thuộc agent không ghi run_log", len(notes) == 1, notes)
    check("kết quả nói stopped", all(d["stopped"] for d in done))
    again = R.sweep(now=NOW + 10, terminate=lambda iid: killed.append(iid) or True)
    check("trong 60 s không quét lại", again == [] and len(killed) == 3)
    R._muse_state = lambda: (None, None)
    killed.clear()
    R.sweep(now=NOW + 120, terminate=lambda iid: killed.append(iid) or True)
    check("không đọc được sổ Muse → không đụng phiên Muse nào", "muse_idle" not in killed and "overrun" in killed,
          killed)
    print("=== 6. scheduler dùng phép đếm mới + nói ai giữ chỗ ===")
    from tubecli.core import scheduler as S  # noqa: E402
    pm._instances.clear()
    for i in range(7):
        r = inst(f"mz{i}", f"muse-vinh-{20 + i}", 30 + i, MUSE, maxd=21600)
        r["_process"] = FakeProc()
        pm._instances[r["instance_id"]] = r
    sch = S.Scheduler() if hasattr(S, "Scheduler") else None
    if sch is None:
        sch = next(v for v in vars(S).values() if hasattr(v, "_count_running_agent_browsers"))
    real_cap = S.max_concurrent_browsers
    S.max_concurrent_browsers = lambda: 5
    check("7 Muse → đếm 4 < 5", sch._count_running_agent_browsers() == 4, sch._count_running_agent_browsers())
    check("dòng busy nêu Muse", "muse-vinh-20 (Muse, hidden" in sch._busy_holders_text(), sch._busy_holders_text())
    S.max_concurrent_browsers = real_cap
finally:
    pm._instances.clear()
    pm._instances.update(saved)
    R._live_profiles, R._muse_state = real_live, real_muse
    if real_note is None:
        del run_log.note
    else:
        run_log.note = real_note

print("=== 7. lý do tự đăng vào run_log ===")
notes.clear()
run_log.note = lambda run_id, agent_id, text, kind="info": notes.append((run_id, agent_id, kind, text))
PM.BrowserProcessManager._note_autopublish("run-9", "ag-9", "skip: auto video and auto-publish off")
check("ghi note autopublish", notes == [("run-9", "ag-9", "autopublish", "skip: auto video and auto-publish off")],
      notes)
PM.BrowserProcessManager._note_autopublish("", "ag-9", "x")
check("không run_id → không ghi", len(notes) == 1)
del run_log.note
try:
    PM.BrowserProcessManager._note_autopublish("run-9", "ag-9", "x")
    check("run_log chưa có note() → im lặng bỏ qua", True)
except Exception as e:      # noqa: BLE001
    check("run_log chưa có note() → im lặng bỏ qua", False, e)
if real_note is not None:
    run_log.note = real_note

print("=== 8. Muse: thời điểm rảnh ===")
from tubecli.core import muse as M  # noqa: E402
with M._POOL:
    M._BUSY["prof-t"] = "prof-t"
M._release("prof-t")
la = M.last_active_by_profile()
check("trả lượt ghi mốc rảnh", abs(la.get("prof-t", 0) - time.time()) < 5, la)
M._LAST_RELEASED.pop("prof-t", None)

print("=== 9. /executions/history bỏ / cắt log ===")
DB_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "tubecli", "extensions", "browser_scripts", "db", "database.py")
spec = importlib.util.spec_from_file_location("bs_db_reaper_test", DB_FILE)
dbm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dbm)
tmp = tempfile.mkdtemp(prefix="reaper_test_")
db = dbm.ScriptDatabase(os.path.join(tmp, "scripts.db"))
eid = db.create_execution("s1", "p1", {"caption": "x"})
big = "A" * 50000 + "TAIL-END"
db.update_execution(eid, status="success", log=big)
full = db.list_executions()
check("mặc định: log nguyên văn (tương thích)", full[0]["log"] == big and "log_length" not in full[0])
none = db.list_executions(log_chars=0)
check("log_chars=0: bỏ log", none[0]["log"] == "" and none[0]["log_length"] == len(big) and none[0]["log_truncated"])
tail = db.list_executions(log_chars=8)
check("log_chars=8: 8 ký tự cuối", tail[0]["log"] == "TAIL-END" and tail[0]["log_truncated"], tail[0]["log"])
check("  biến vẫn đọc được", tail[0]["variables"].get("caption") == "x", tail[0]["variables"])
short = db.list_executions(log_chars=10 ** 6)
check("đuôi dài hơn log: không bị coi là cắt", short[0]["log"] == big and not short[0]["log_truncated"])
check("script_id + log_chars", db.list_executions("s1", limit=1, log_chars=0)[0]["log"] == "")

from tubecli.extensions.browser_scripts import script_routes as SR  # noqa: E402
real_db = SR._db
SR._db = lambda: db
try:
    r = asyncio.run(SR.execution_history(limit=5, include_log=False))
    check("route include_log=false", r["executions"][0]["log"] == "")
    r = asyncio.run(SR.execution_history(limit=5, log_tail=4))
    check("route log_tail=4", r["executions"][0]["log"] == "-END")
    r = asyncio.run(SR.execution_history(limit=5))
    check("route mặc định nguyên văn", r["executions"][0]["log"] == big)
finally:
    SR._db = real_db

print(f"\n{ok} passed, {fail} failed")
sys.exit(1 if fail else 0)
