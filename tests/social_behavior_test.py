# -*- coding: utf-8 -*-
"""Việc tương tác trong lịch agent (18/11/2026): comment / watch_live / follow trên YouTube hoặc TikTok.

Kiểm (KHÔNG mạng, KHÔNG trình duyệt / máy thật):
  1. khoá lịch mới → behavior; bộ sinh lịch theo vai trò KHÔNG bao giờ tự bật việc tương tác
  2. chip đăng nhập: hồ sơ trình duyệt (YouTube HOẶC TikTok) và máy Android (email cần Google…)
  3. chọn nền tảng + câu lệnh open.js (URL giữ hoa/thường, bước cuối là comment / subscribe / follow)
  4. trần lượt / ngày: chạm trần ⇒ xem video thường; sang ngày mới đếm lại
  5. Android: bình luận được đưa compose (AI agent) + ngôn ngữ; extension báo chip ⇒ lõi đọc được

Run:  python tests/social_behavior_test.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")

from tubecli.api import server as SV            # noqa: E402
from tubecli.core import agent as AG            # noqa: E402

PASS = FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", label)
    else:
        FAIL += 1
        print("  FAIL", label, "—", str(detail)[:300])


print("── 1. khoá lịch ─────────────────────────────────────────────────")
ok(SV.resolve_task_behavior("comment") == "commentVideo", "comment → commentVideo")
ok(SV.resolve_task_behavior("watch_live") == "watchLive", "watch_live → watchLive")
ok(SV.resolve_task_behavior("follow") == "followChannel", "follow → followChannel")
ok(not set(SV.ENGAGEMENT_KEYS) & set(SV.BEHAVIOR_MEANINGS), "bộ sinh lịch không biết (nên không tự bật) việc tương tác")
ok(set(SV.ENGAGEMENT_DAILY_CAP) == set(SV.SOCIAL_BEHAVIORS), "mọi việc tương tác đều có trần / ngày")

print("── 2. chip đăng nhập ────────────────────────────────────────────")
ok(SV.behavior_login_ok("commentVideo", {"tiktok"}), "bình luận: chỉ TikTok là đủ")
ok(SV.behavior_login_ok("followChannel", {"google", "youtube"}), "theo dõi: YouTube là đủ")
ok(not SV.behavior_login_ok("commentVideo", {"google"}), "bình luận: chỉ Google (không YouTube/TikTok) ⇒ không")
ok(not SV.behavior_login_ok("commentVideo", set()), "bình luận: hồ sơ trắng ⇒ không")
ok(SV.behavior_login_ok("watchLive", set()), "xem live: không cần đăng nhập")
ok(SV.behavior_login_ok("checkEmails", {"google"}) and not SV.behavior_login_ok("checkEmails", {"tiktok"}),
   "luật cũ (email cần Google) giữ nguyên")
ok(SV.android_behavior_ok("commentVideo", None), "máy chưa kiểm ⇒ không phán")
ok(not SV.android_behavior_ok("checkEmails", []), "máy không có Google ⇒ không đọc mail")
ok(SV.android_behavior_ok("replyEmail", ["google", "gmail"]), "máy có Google ⇒ trả lời mail được")
ok(not SV.android_behavior_ok("followChannel", ["google"]), "máy có Google nhưng chưa có YouTube app ⇒ không theo dõi")
ok(SV.android_behavior_ok("followChannel", ["tiktok"]), "máy có TikTok ⇒ theo dõi được")
ok(SV.android_behavior_ok("watchVideos", []) and SV.android_behavior_ok("watchLive", []),
   "xem video / live trên máy chưa đăng nhập vẫn được")

print("── 3. nền tảng + câu lệnh ───────────────────────────────────────")
import random  # noqa: E402
r = random.Random(1)
ok(SV.social_platform("commentVideo", {"tiktok"}, r) == "tiktok", "chỉ có TikTok ⇒ TikTok")
ok(SV.social_platform("watchLive", None, r) == "youtube", "chưa rõ chip ⇒ YouTube")
both = {SV.social_platform("commentVideo", {"youtube", "tiktok"}, random.Random(i)) for i in range(20)}
ok(both == {"youtube", "tiktok"}, "có cả hai ⇒ xoay vòng hai nền tảng", both)

p = SV.build_social_prompt("watchLive", "youtube", "lofi music", 200)
ok("sp=EgJAAQ%3D%3D" in p and "search_query=lofi+music" in p, "live YouTube: bộ lọc LIVE nguyên hoa/thường", p)
steps = SV.build_social_prompt("commentVideo", "youtube", "lofi", 90).split(", then ")
ok(steps[0] == "Navigate to youtube.com" and steps[-1].startswith("comment on the video"), "bình luận YouTube", steps)
steps = SV.build_social_prompt("followChannel", "youtube", "lofi", 90).split(", then ")
ok(steps[-1].startswith("subscribe to the channel") and "watch for 90 seconds" in steps, "đăng ký YouTube", steps)
steps = SV.build_social_prompt("followChannel", "tiktok", "nấu ăn", 60).split(", then ")
ok(steps[0].startswith("Navigate to https://www.tiktok.com/search/video?q=n%E1%BA%A5u%20%C4%83n")
   and steps[-1].startswith("follow the creator"), "theo dõi TikTok (chủ đề tiếng Việt mã hoá URL)", steps)
p = SV.build_social_prompt("watchLive", "tiktok", "lofi", 9999)
ok("tiktok.com/search/live?q=lofi" in p and "watch for 300 seconds" in p, "live TikTok, thời gian kẹp ≤ 300 s", p)

print("── 4. trần lượt / ngày ──────────────────────────────────────────")
from tubecli.core import agent as _agent_mod  # noqa: E402
saved = []
_agent_mod.agent_manager.update = lambda aid, **kw: saved.append(kw)
ag = AG.Agent(name="Cap")
ag.routine = {}
got = [SV.apply_engagement_cap(ag, "commentVideo", "2026-11-18") for _ in range(6)]
ok(got == ["commentVideo"] * 4 + ["watchVideos"] * 2, "bình luận tối đa 4 lượt / ngày", got)
ok(ag.routine["engagement_today"] == {"date": "2026-11-18", "commentVideo": 4}, "đếm lưu vào routine",
   ag.routine.get("engagement_today"))
ok(saved and "routine" in saved[-1], "đếm được ghi qua agent_manager.update")
ok(SV.apply_engagement_cap(ag, "commentVideo", "2026-11-19") == "commentVideo", "sang ngày mới ⇒ đếm lại")
ok(SV.apply_engagement_cap(ag, "watchVideos", "2026-11-19") == "watchVideos"
   and "watchVideos" not in ag.routine["engagement_today"], "việc thường không bị đếm")

print("── 5. Android ───────────────────────────────────────────────────")
from tubecli.core import run_log as RL          # noqa: E402
from tubecli.core import extension_manager as EM  # noqa: E402
RL.launch = lambda *a, **k: None
RL.end = lambda *a, **k: None


class FakeExt:
    agent_engine = "android"

    def __init__(self, chips=None):
        self.calls, self.chips = [], chips

    def run_agent_behavior(self, device, behavior, query="", seconds=90, **extra):
        self.calls.append(dict(extra, device=device, behavior=behavior))
        return {"ok": True, "summary": "done"}

    def device_logins(self, device):
        return self.chips


fx = FakeExt(chips=["google", "youtube"])
EM.extension_manager.get_enabled = lambda: [fx]
droid = AG.Agent(name="D", android_devices=["Android 3"], language="vi")
SV.run_routine_on_android(droid, "commentVideo", "lofi", 90)
c = fx.calls[-1]
ok(callable(c.get("compose")) and c.get("language") == "vi", "bình luận: có compose + ngôn ngữ agent", c)
SV.run_routine_on_android(droid, "followChannel", "lofi", 90)
ok("compose" not in fx.calls[-1], "theo dõi: không cần AI viết chữ", fx.calls[-1])
ok(SV.android_device_chips(droid) == ["google", "youtube"], "lõi đọc chip máy qua extension.device_logins")


class OldExt(FakeExt):
    device_logins = None


EM.extension_manager.get_enabled = lambda: [OldExt()]
ok(SV.android_device_chips(droid) is None, "extension cũ (không có device_logins) ⇒ None, lịch chạy như cũ")
ok(SV.android_device_chips(AG.Agent(name="B")) is None, "agent không chọn máy ⇒ None")

print(f"\n{PASS}/{PASS + FAIL} PASS")
sys.exit(1 if FAIL else 0)
