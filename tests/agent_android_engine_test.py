# -*- coding: utf-8 -*-
"""Lịch agent chạy trên ANDROID (18/11/2026): agent.android_devices + run_routine_on_android.

Kiểm (KHÔNG máy Android thật — extension giả):
  1. trường android_devices đi qua hàm dựng, to_dict, model Create/Update (pydantic bỏ lặng trường lạ)
  2. không chọn máy ⇒ False (đi đường trình duyệt như cũ)
  3. chọn máy mà KHÔNG có extension Android ⇒ True + nhật ký «skipped» (KHÔNG lùi sang trình duyệt)
  4. extension chạy được ⇒ gọi đúng tham số, nhật ký completed; lỗi / ném ngoại lệ ⇒ failed
  5. email chạy trên app Gmail: compose (AI agent) chỉ khi cần viết, người nhận, extension cũ không vỡ
  6. kho dữ liệu: agent thấy thư đọc trên Android (android-*), không thấy của agent khác

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
ok(not events, "không chọn máy ⇒ không ghi nhật ký", events)

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

print("── 5. email trên app Gmail (18/11) ─────────────────────────────")
events.clear()
fx = FakeExt({"ok": True, "summary": "Gmail app on a1: read 2"})
use(fx)
r = SV.run_routine_on_android(droid, "checkEmails", "gmail", 60, run_id="r5", topics=["lịch sử"])
ok(r is True and fx.calls and fx.calls[0]["behavior"] == "checkEmails", "checkEmails ⇒ chạy trên Android", fx.calls)
ok("compose" not in fx.calls[0], "checkEmails KHÔNG cần AI soạn chữ", list(fx.calls[0]))
ok(fx.calls[0].get("agent_id") == droid.id and fx.calls[0].get("topics") == ["lịch sử"],
   "đưa agent_id (gắn dữ liệu đã đọc) + chủ đề", fx.calls[0])

fx = FakeExt({"ok": True, "summary": "report sent"})
use(fx)
SV.run_routine_on_android(droid, "sendReport", "gmail", 60, run_id="r6", recipients=["a@b.co", ""], topics=["x"])
c = fx.calls[0]
ok(callable(c.get("compose")) and c.get("recipients") == ["a@b.co"], "sendReport ⇒ compose + người nhận (bỏ rỗng)", c)

fx = FakeExt({"ok": True, "summary": "replied"})
use(fx)
SV.run_routine_on_android(droid, "replyEmail", "gmail", 60, run_id="r7")
ok(callable(fx.calls[0].get("compose")), "replyEmail ⇒ compose", fx.calls[0])


class OldExt:                                     # extension bản cũ: chữ ký cố định, không **kwargs
    agent_engine = "android"

    def __init__(self):
        self.got = None

    def run_agent_behavior(self, device, behavior, query="", seconds=90, timeout=900):
        self.got = dict(device=device, behavior=behavior, query=query, seconds=seconds)
        return {"ok": True, "summary": "old"}


old_ext = OldExt()
use(old_ext)
events.clear()
SV.run_routine_on_android(droid, "watchVideos", "q", 60, run_id="r8", topics=["t"])
ok(old_ext.got and old_ext.got["behavior"] == "watchVideos" and events[-1][1] == "completed",
   "extension bản cũ không vỡ vì khoá lạ (compose/topics…)", (old_ext.got, events[-1:]))

from tubecli.core import brain as BR              # noqa: E402
_orig = BR.AgentBrain._call_llm
BR.AgentBrain._call_llm = staticmethod(lambda ag, msgs, temperature=0.7: "Xin chào, cảm ơn bạn.")
ok(SV.android_compose_fn(droid)("viết thư") == "Xin chào, cảm ơn bạn.", "compose trả chữ AI")
BR.AgentBrain._call_llm = staticmethod(lambda ag, msgs, temperature=0.7: "[Gemini Error] 429 rate limit exceeded")
try:
    SV.android_compose_fn(droid)("viết thư")
    ok(False, "lỗi AI dạng chữ phải NÉM (không gửi chữ lỗi đi)")
except RuntimeError:
    ok(True, "lỗi AI dạng chữ ⇒ ném, không gửi thư")
BR.AgentBrain._call_llm = _orig

print("── 6. kho dữ liệu: agent thấy thư đọc trên Android ──────────────")
import json as _json                              # noqa: E402
import tempfile                                   # noqa: E402
from pathlib import Path                          # noqa: E402
from tubecli.core import scraped_store as SS      # noqa: E402

tmp = Path(tempfile.mkdtemp(prefix="sstore_"))
for prof, rows in {"Chrome 1": [{"url": "https://a.vn/1", "title": "web", "agentId": "D1"}],
                   "android-a1": [{"url": "https://mail.google.com/mail/u/0/#android/x1", "title": "mail D1",
                                   "agentId": "D1", "isScraped": True},
                                  {"url": "https://mail.google.com/mail/u/0/#android/x2", "title": "mail other",
                                   "agentId": "OTHER", "isScraped": True}]}.items():
    (tmp / prof).mkdir()
    (tmp / prof / "history.json").write_text(_json.dumps({"scrapedArticles": rows}), encoding="utf-8")
    (tmp / prof / "articles.json").write_text(_json.dumps(
        [dict(r, content="body " + r["title"]) for r in rows]), encoding="utf-8")
SS.data_root = lambda: tmp
ok(SS.agent_profiles(["Chrome 1"], "D1") == ["Chrome 1", "android-a1"], "agent_profiles thêm android-*",
   SS.agent_profiles(["Chrome 1"], "D1"))
ok(SS.agent_profiles(["Chrome 1"]) == ["Chrome 1"], "không agent_id ⇒ không thêm")
titles = {i.get("title") for i in SS.query(agent_id="D1", allowed_profiles=["Chrome 1"])["items"]}
ok("mail D1" in titles and "web" in titles, "query của agent có thư đọc trên Android", titles)
ok("mail other" not in titles, "KHÔNG thấy thư của agent khác trên cùng máy", titles)

print(f"\n{PASS} pass, {FAIL} fail")
sys.exit(1 if FAIL else 0)
