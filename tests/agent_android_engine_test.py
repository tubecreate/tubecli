# -*- coding: utf-8 -*-
"""Lịch agent chạy trên ANDROID (18/11/2026): agent.android_devices + run_routine_on_android.

Kiểm (KHÔNG máy Android thật — extension giả):
  1. trường android_devices đi qua hàm dựng, to_dict, model Create/Update (pydantic bỏ lặng trường lạ)
  2. không chọn máy / behavior email ⇒ False (đi đường trình duyệt như cũ)
  3. chọn máy mà KHÔNG có extension Android ⇒ True + nhật ký «skipped» (KHÔNG lùi sang trình duyệt)
  4. extension chạy được ⇒ gọi đúng tham số, nhật ký completed; lỗi / ném ngoại lệ ⇒ failed

Run:  python tests/agent_android_engine_test.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")

from tubecli.core import agent as AG          # noqa: E402

PASS = FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", label)
    else:
        FAIL += 1
        print("  FAIL", label, "—", str(detail)[:300])


print("── 1. trường agent ────────────────────────────────────────────")
a = AG.Agent(name="A", android_devices=["a1", "", None, "a2"])
ok(a.android_devices == ["a1", "a2"], "hàm dựng bỏ giá trị rỗng", a.android_devices)
ok(a.to_dict().get("android_devices") == ["a1", "a2"], "to_dict có android_devices")
ok(AG.Agent(name="B").android_devices == [], "mặc định rỗng")
ok(AG.Agent.from_dict(a.to_dict()).android_devices == ["a1", "a2"], "from_dict giữ nguyên")

from tubecli.api import server as SV            # noqa: E402

ok("android_devices" in SV.AgentCreateRequest.model_fields, "AgentCreateRequest khai android_devices")
ok("android_devices" in SV.AgentUpdateRequest.model_fields, "AgentUpdateRequest khai android_devices")
dumped = SV.AgentUpdateRequest(android_devices=["a1"]).model_dump(exclude_none=True)
ok(dumped.get("android_devices") == ["a1"], "PUT mang android_devices tới agent_manager.update", dumped)

print("── 2–4. run_routine_on_android ─────────────────────────────────")
from tubecli.core import run_log as RL          # noqa: E402
from tubecli.core import extension_manager as EM  # noqa: E402

events = []
RL.launch = lambda run_id, agent_id, **f: events.append(("launch", f))
RL.end = lambda run_id, agent_id, outcome, **f: events.append(("end", outcome, f))


class FakeExt:
    agent_engine = "android"

    def __init__(self, result=None, boom=False):
        self.calls, self.result, self.boom = [], result, boom

    def run_agent_behavior(self, **kw):
        self.calls.append(kw)
        if self.boom:
            raise RuntimeError("bridge down")
        return self.result


class NotAndroid:
    agent_engine = ""


def use(*exts):
    EM.extension_manager.get_enabled = lambda: list(exts)


logged = []
log = lambda msg, ok=True: logged.append((msg, ok))   # noqa: E731
plain = AG.Agent(name="P")
droid = AG.Agent(name="D", android_devices=["a1"])

use(FakeExt({"ok": True, "summary": "x"}))
ok(SV.run_routine_on_android(plain, "watchVideos", "q", 60, run_id="r0") is False, "không chọn máy ⇒ False")
ok(SV.run_routine_on_android(droid, "checkEmails", "q", 60, run_id="r0") is False, "email ⇒ False (vẫn trình duyệt)")
ok(not events, "hai ca trên không ghi nhật ký", events)

events.clear()
use(NotAndroid())
r = SV.run_routine_on_android(droid, "watchVideos", "lofi", 60, run_id="r1", log=log)
ok(r is True, "thiếu extension ⇒ True (không lùi sang trình duyệt)")
ok(events and events[0][1].get("spawn_status") == "skipped" and events[-1][1] == "skipped",
   "nhật ký skipped", events)

events.clear()
fx = FakeExt({"ok": True, "summary": "YouTube app on a1: watched X"})
use(NotAndroid(), fx)
r = SV.run_routine_on_android(droid, "watchVideos", "lofi", 75, run_id="r2", time_period="evening", log=log)
ok(r is True and fx.calls and fx.calls[0]["device"] == "a1" and fx.calls[0]["behavior"] == "watchVideos"
   and fx.calls[0]["query"] == "lofi" and fx.calls[0]["seconds"] == 75, "gọi extension đúng tham số", fx.calls)
ok(events[0][1].get("profile") == "android:a1" and events[0][1].get("spawn_status") == "running",
   "launch ghi profile android:a1", events[0])
ok(events[-1][1] == "completed" and "watched X" in events[-1][2].get("log_tail", ""), "end completed + tóm tắt", events[-1])

events.clear()
use(FakeExt({"ok": False, "error": "Could not find a video"}))
SV.run_routine_on_android(droid, "watchVideos", "", 60, run_id="r3")
ok(events[-1][1] == "failed" and "Could not find" in events[-1][2].get("log_tail", ""), "kết quả lỗi ⇒ failed", events[-1])

events.clear()
use(FakeExt(boom=True))
r = SV.run_routine_on_android(droid, "morningCheck", "tin", 60, run_id="r4")
ok(r is True and events[-1][1] == "failed" and "bridge down" in events[-1][2].get("log_tail", ""),
   "extension ném lỗi ⇒ failed, không sập lịch", events[-1])

events.clear()
use(FakeExt({"ok": True, "summary": "s"}))
SV.run_routine_on_android(droid, "watchVideos", "q", 60, run_id=None)
ok(not events, "không run_id ⇒ không ghi nhật ký (chạy tay cũ)", events)

print(f"\n{PASS} pass, {FAIL} fail")
sys.exit(1 if FAIL else 0)
