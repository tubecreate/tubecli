# -*- coding: utf-8 -*-
"""Giải phóng RAM: dọn đúng trình duyệt bỏ hoang, không đụng phiên có người dùng.

Run:  python tests/free_memory_test.py     (exit 0 = pass)

Bối cảnh: máy cấu hình thấp, khung live view báo "quá lâu không nhận được hình"
trong khi đồng hồ RAM đầy. Ai giữ? Chromium của lượt agent đã xong mà launcher
chết trước khi dọn; node preview + Chromium từ trước lần restart; live view mà tab
canvas đã đóng. Nút "Giải phóng RAM" phải dọn đúng những thứ đó và CHỈ những thứ đó.

Kiểm, đối chiếu code thật trong extensions/browser:
  A. _profile_of_cmdline    — hai hình dạng dòng lệnh, biên thư mục tuan5/tuan50
  B. plan_memory_reclaim    — cột DỌN / cột GIỮ cho từng cảnh
  C. reclaim_browser_memory — dry_run không giết; chạy thật giết đúng cột DỌN, đo RAM
  D. route /free-memory     — khách bị 403
  E. preview_server.cjs     — /status có viewers + idle_since, cập nhật đúng lúc
"""
import asyncio
import os
import sys
import unittest.mock as mock
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

from tubecli.extensions.browser import routes as R  # noqa: E402
import tubecli.extensions.browser.process_manager as PM  # noqa: E402

failures = []
checks = 0


def check(label, ok, detail=""):
    global checks
    checks += 1
    if not ok:
        failures.append(f"{label}: {detail}")


class LiveProc:
    def poll(self):
        return None


class DeadProc:
    def poll(self):
        return 0


PD = r"C:\srv\tubecli\browser_profiles" if os.name == "nt" else "/srv/tubecli/browser_profiles"


def J(*p):
    return os.path.join(PD, *p)


print("=" * 70)
print("GIẢI PHÓNG RAM — DỌN ĐÚNG, GIỮ ĐÚNG")
print("=" * 70)

# ── A. dòng lệnh → tên hồ sơ ────────────────────────────────────────────────
f = R._profile_of_cmdline
check("A user-data-dir= → tên hồ sơ", f(["chrome", f"--user-data-dir={J('tuan3')}"], PD) == "tuan3")
check("A đường dẫn sâu hơn vẫn ra đúng tên", f(["chrome", f"--user-data-dir={J('tuan3', 'Default')}"], PD) == "tuan3")
check("A biên thư mục: tuan50 KHÔNG phải tuan5", f(["chrome", f"--user-data-dir={J('tuan50')}"], PD) == "tuan50")
check("A preview_server --profile <tên>",
      f(["node", "/x/preview_server.cjs", "--profile", "tuan7", "--profiles-dir", PD], PD) == "tuan7")
check("A --profiles-dir một mình → None", f(["node", "/x/other.js", "--profiles-dir", PD], PD) is None)
check("A không liên quan → None", f(["python", "server.py"], PD) is None)
check("A rỗng → None", f(None, PD) is None and f([], PD) is None)
check("A --profile theo sau là cờ khác → None", f(["node", "/x/preview_server.cjs", "--profile", "--url"], PD) is None)
print("A cmdline    : 2 hình dạng | biên thư mục | không đoán bừa")

# ── B. kế hoạch: cột DỌN / cột GIỮ ──────────────────────────────────────────
NOW = 1_700_000_000.0
instances = [
    {"profile": "agentA", "status": "running", "_process": LiveProc(), "_agent_id": "ag1", "started_at": None},
    {"profile": "doneB", "status": "completed", "_process": DeadProc(), "_agent_id": "ag2"},
    {"profile": "deadLauncherC", "status": "running", "_process": DeadProc(), "_agent_id": "ag3"},
]
sessions = {
    "s1": {"profile": "viewD", "proc": LiveProc(), "port": 41001, "started_at": NOW - 600, "opened_by": "canvas"},
    "s2": {"profile": "abandonE", "proc": LiveProc(), "port": 41002, "started_at": NOW - 3600},
    "s3": {"profile": "oldSrvF", "proc": LiveProc(), "port": 41003, "started_at": NOW - 100},
    "s4": {"profile": "mine", "proc": LiveProc(), "port": 41004, "started_at": NOW - 60},
    "s5": {"profile": "deadPrevG", "proc": DeadProc(), "port": 41005},
    "s6": {"profile": "freshH", "proc": LiveProc(), "port": 41006, "started_at": NOW - 30},
}
probes = {
    41001: {"viewers": 1, "idle_since": None},
    41002: {"viewers": 0, "idle_since": (NOW - 20 * 60) * 1000},   # 20 phút không ai xem
    41003: None,                                                    # server cũ: không biết
    41006: {"viewers": 0, "idle_since": (NOW - 2 * 60) * 1000},     # mới rời 2 phút
}
groups = {
    "agentA": {"pids": [11], "rss_mb": 500, "names": ["chrome"]},
    "doneB": {"pids": [21, 22], "rss_mb": 700, "names": ["chrome"]},
    "deadLauncherC": {"pids": [31], "rss_mb": 300, "names": ["chrome"]},
    "viewD": {"pids": [41], "rss_mb": 400, "names": ["node", "chrome"]},
    "abandonE": {"pids": [51], "rss_mb": 900, "names": ["node", "chrome"]},
    "oldSrvF": {"pids": [61], "rss_mb": 200, "names": ["node"]},
    "mine": {"pids": [71], "rss_mb": 350, "names": ["node", "chrome"]},
    "deadPrevG": {"pids": [81], "rss_mb": 150, "names": ["chrome"]},
    "ghostI": {"pids": [91, 92], "rss_mb": 800, "names": ["chrome"]},
    "launchingJ": {"pids": [101], "rss_mb": 100, "names": ["chrome"]},
    "freshH": {"pids": [111], "rss_mb": 120, "names": ["node"]},
}
plan = R.plan_memory_reclaim("mine", sessions, instances, groups,
                             viewers_probe=lambda port: probes.get(port),
                             launching=["launchingJ"], now=NOW)
rec = {x["profile"]: x for x in plan["reclaim"]}
pro = {x["profile"]: x for x in plan["protected"]}
check("B agent đang chạy → GIỮ", pro.get("agentA", {}).get("why") == "agent_running", pro.get("agentA"))
check("B   kèm ai + pid + MB",
      pro.get("agentA", {}).get("who") == "ag1" and pro.get("agentA", {}).get("pids") == [11]
      and pro.get("agentA", {}).get("rss_mb") == 500, pro.get("agentA"))
check("B lượt đã xong, Chromium còn → finished_run", rec.get("doneB", {}).get("reason") == "finished_run", rec.get("doneB"))
check("B launcher chết dù sổ ghi running → finished_run",
      rec.get("deadLauncherC", {}).get("reason") == "finished_run", rec.get("deadLauncherC"))
check("B live view có người xem → GIỮ",
      pro.get("viewD", {}).get("why") == "live_view" and pro.get("viewD", {}).get("viewers") == 1, pro.get("viewD"))
check("B live view 20 phút không ai xem → abandoned_view",
      rec.get("abandonE", {}).get("reason") == "abandoned_view" and rec.get("abandonE", {}).get("idle_mins") == 20,
      rec.get("abandonE"))
check("B live view mới rời 2 phút → GIỮ (chưa quá ngưỡng)", pro.get("freshH", {}).get("why") == "live_view", pro.get("freshH"))
check("B server cũ không báo viewers → GIỮ (không biết thì giữ)",
      pro.get("oldSrvF", {}).get("why") == "live_view" and pro.get("oldSrvF", {}).get("viewers") is None, pro.get("oldSrvF"))
check("B phiên của CHÍNH khung gọi → own_stalled", rec.get("mine", {}).get("reason") == "own_stalled", rec.get("mine"))
check("B preview chết, Chromium còn → dead_preview", rec.get("deadPrevG", {}).get("reason") == "dead_preview", rec.get("deadPrevG"))
check("B không có trong sổ nào → orphan",
      rec.get("ghostI", {}).get("reason") == "orphan" and rec.get("ghostI", {}).get("pids") == [91, 92], rec.get("ghostI"))
check("B đang mở dở → GIỮ", pro.get("launchingJ", {}).get("why") == "launching", pro.get("launchingJ"))
check("B mỗi mục dọn có why_vi", all(x.get("why_vi") for x in plan["reclaim"]), plan["reclaim"])
check("B xếp theo MB giảm dần", [x["profile"] for x in plan["reclaim"]][:2] == ["abandonE", "ghostI"],
      [x["profile"] for x in plan["reclaim"]])
check("B không hồ sơ nào ở cả hai cột", not (set(rec) & set(pro)), set(rec) & set(pro))
check("B đủ 11 hồ sơ", len(rec) + len(pro) == 11, (len(rec), len(pro)))
plan2 = R.plan_memory_reclaim("mine", {"s": {"profile": "mine", "proc": LiveProc(), "port": 1}}, [], {}, now=NOW)
check("B sổ còn, tiến trình hết → dọn sổ 0 MB",
      plan2["reclaim"] and plan2["reclaim"][0]["profile"] == "mine" and plan2["reclaim"][0]["rss_mb"] == 0, plan2)
print(f"B ke hoach   : {len(rec)} dọn / {len(pro)} giữ — agent chạy, người đang xem, server cũ, đang mở dở đều được GIỮ")

# ── C. chạy thật với mọi thứ bên ngoài giả ──────────────────────────────────


class FakeBPM:
    def __init__(self, insts):
        import threading
        self._instances_lock = threading.Lock()
        self._instances = insts
        self.stopped = []

    def stop_by_profile(self, p):
        self.stopped.append(p)
        return False


fk_calls, killed_pids, stopped_previews = [], [], []


def fake_force_kill(prof, wait=3.0):
    fk_calls.append(prof)
    return {"killed": [{"pid": 999, "name": "chrome"}], "locks_removed": ["/x/SingletonLock"], "errors": []}


def fake_kill_pids(pids, wait=3.0):
    killed_pids.extend(pids)
    return {"killed": list(pids), "errors": []}


ram_seq = iter([700, 1900])
groups_c = {"doneB": {"pids": [21, 22], "rss_mb": 700, "names": ["chrome"]},
            "agentA": {"pids": [11], "rss_mb": 500, "names": ["chrome"]}}
fake_bpm = FakeBPM({"a": instances[0], "b": instances[1]})
with mock.patch.object(R, "_browser_groups", lambda pd: dict(groups_c)), \
     mock.patch.object(R, "_preview_viewers", lambda port, timeout=1.0: None), \
     mock.patch.object(R, "_kill_pids", fake_kill_pids), \
     mock.patch.object(R, "stop_preview_for_profile", lambda p: stopped_previews.append(p) or False), \
     mock.patch.object(R, "_available_ram_mb", lambda: next(ram_seq)), \
     mock.patch.object(R.time, "sleep", lambda s: None), \
     mock.patch.dict(R._preview_processes, {}, clear=True), \
     mock.patch.object(PM, "browser_process_manager", fake_bpm), \
     mock.patch.object(PM, "force_kill_profile", fake_force_kill):
    dry = R.reclaim_browser_memory("mine", dry_run=True)
    check("C dry_run không giết gì", not killed_pids and not fk_calls and not stopped_previews, (killed_pids, fk_calls))
    check("C dry_run trả kế hoạch + tổng MB",
          dry["dry_run"] is True and dry["reclaimable_mb"] == 700 and [x["profile"] for x in dry["reclaim"]] == ["doneB"], dry)
    check("C dry_run cột giữ có agentA", [x["profile"] for x in dry["protected"]] == ["agentA"], dry["protected"])
    ram_seq = iter([700, 1900])
    real = R.reclaim_browser_memory("mine", dry_run=False)
check("C chạy thật: giết đúng pid của doneB", killed_pids == [21, 22], killed_pids)
check("C   KHÔNG đụng agentA", 11 not in killed_pids and "agentA" not in fk_calls, (killed_pids, fk_calls))
check("C   dọn sổ preview + sổ agent + gỡ khoá",
      stopped_previews == ["doneB"] and fake_bpm.stopped == ["doneB"] and fk_calls == ["doneB"],
      (stopped_previews, fake_bpm.stopped, fk_calls))
check("C   gộp pid force_kill vào báo cáo, không trùng",
      real["done"][0]["killed"] == [21, 22, 999] and real["done"][0]["locks_removed"] == 1, real["done"])
check("C   đo RAM trước/sau, freed = hiệu",
      real["ram_before"] == 700 and real["ram_after"] == 1900 and real["freed_mb"] == 1200, real)
check("C   message_vi kể số trình duyệt + MB",
      "1 trình duyệt" in real["message_vi"] and "1200 MB" in real["message_vi"], real["message_vi"])
ram_seq = iter([700, 700])
with mock.patch.object(R, "_browser_groups", lambda pd: {"agentA": groups_c["agentA"]}), \
     mock.patch.object(R, "_preview_viewers", lambda port, timeout=1.0: None), \
     mock.patch.object(R, "_available_ram_mb", lambda: next(ram_seq)), \
     mock.patch.object(R.time, "sleep", lambda s: None), \
     mock.patch.dict(R._preview_processes, {}, clear=True), \
     mock.patch.object(PM, "browser_process_manager", fake_bpm):
    none = R.reclaim_browser_memory(None, dry_run=False)
check("C không gì để dọn → nói rõ có phiên đang dùng",
      none["done"] == [] and "1 phiên đang có người dùng" in none["message_vi"], none["message_vi"])
print("C chay that  : dry_run im | giết đúng cột dọn, chừa agent | dọn sổ + khoá | RAM trước/sau")

# ── D. route: khách bị chặn ─────────────────────────────────────────────────


class _St:
    guest_scope = {"profiles": ["x"]}


class _Req:
    state = _St()


try:
    asyncio.run(R.api_free_memory(R.FreeMemoryRequest(profile="x", dry_run=True), _Req()))
    check("D khách → 403", False, "không ném")
except Exception as e:  # noqa: BLE001
    check("D khách → 403", getattr(e, "status_code", None) == 403, repr(e))
print("D route      : khách bị 403")

# ── E. preview_server.cjs báo có ai đang xem ────────────────────────────────
src = (ROOT / "tubecli" / "extensions" / "browser" / "preview_server.cjs").read_text(encoding="utf-8")
check("E /status phát viewers", "viewers: clients.size" in src)
check("E /status phát idle_since khi không ai xem", "idle_since: clients.size === 0 ? lastViewerLeftAt : null" in src)
check("E nối vào → xoá mốc", "clients.add(ws);\n        lastViewerLeftAt = null;" in src)
check("E người cuối rời → đặt mốc (cả close lẫn error)",
      src.count("if (clients.size === 0) { lastViewerLeftAt = Date.now(); stopStreaming(); }") == 2)
check("E lúc mới chạy tính từ lúc chạy", "let lastViewerLeftAt = Date.now();" in src)
print("E preview_srv: /status nói có ai đang xem, và từ lúc nào không còn ai")

print("=" * 70)
if failures:
    print(f"{len(failures)} FAIL / {checks}")
    for x in failures:
        print("  FAIL", x)
    sys.exit(1)
print(f"{checks}/{checks} PASS")
