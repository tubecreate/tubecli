# -*- coding: utf-8 -*-
"""KÊNH CHƯA XÁC MINH — không đăng video quá 15 phút, hết vòng «dựng → đăng hỏng → dựng lại» (19/10/2026).

User: «quy trình đăng video youtube bằng script đang bị lỗi đăng video >15 phút. gắn cờ chưa xác minh đăng video dài,
livestream cho kênh mới. nếu video dài thì cảnh báo đăng và không đăng vào kênh chưa xác minh tránh tình trạng loop
đăng liên tục». (Task «Auto publish» 17:11 trên VPS: script kẹt ở bước Hiển thị, mốc corpus đứng yên ⇒ lượt thu thập
sau lại dựng nguyên video dài.)

  A. trường agent publish_unverified: mặc định False, ép bool, có trong to_dict + AgentCreate/UpdateRequest
  B. cò súng: truyền publish_unverified + tắt thumbnail; đang tạm dừng ⇒ không xếp task (hay chỉ dựng nếu auto_video);
     tạm dừng tự hết khi bỏ cờ / đổi mẫu / sửa mẫu
  C. bước đăng: cờ bật + video > 15 phút ⇒ KHÔNG gọi đăng, không ném, cảnh báo có link xác minh + dừng cò súng;
     ≤ 15 phút ⇒ đăng bình thường
  D. đăng hỏng video > 15 phút chưa gắn cờ: task tự đăng ⇒ bật cờ agent + dừng; task tay ⇒ chỉ cảnh báo; video ngắn
     hỏng ⇒ không đụng cờ
  E. thumbnail: kênh chưa xác minh ⇒ không gắn (API) + script nhận thumbnail_set=0
  F. form Codex: ô «Channel not verified yet» gửi publish_unverified, nhớ lựa chọn; 9 locale

Run:  python tests/publish_unverified_test.py
"""
import io
import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from tubecli.core import agent as AG  # noqa: E402
from tubecli.core import templates as TPL  # noqa: E402
from tubecli.extensions.content_video import autopublish as A  # noqa: E402
from tubecli.extensions.content_video import pipeline as P  # noqa: E402

PASS = FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", label)
    else:
        FAIL += 1
        print("  FAIL", label, "—", str(detail)[:300])


TMP = Path(tempfile.mkdtemp(prefix="unverified-"))
STORE = TMP / "autopublish.json"
A._store_path = lambda: STORE

TEMPLATES = {"Bible": {"updated_at": "2026-10-17T09:15:25+07:00"}}
TPL.get_template = lambda name: TEMPLATES.get(name)

AGENTS = {}
UPDATES = []


class _AM:
    def get(self, aid):
        return AGENTS.get(aid)

    def update(self, aid, **kw):
        UPDATES.append((aid, kw))
        a = AGENTS.get(aid)
        for k, v in AG.coerce_publish_fields(kw).items():
            setattr(a, k, v)
        return a


AG.agent_manager = _AM()
P_scan = [(5, "2026-10-19T01:00:00Z")]
A.scan_new = lambda agent, hw="": P_scan[0]
A._codex = lambda: type("C", (), {"get_task": staticmethod(lambda t: None)})()
try:
    from tubecli.extensions.content_video import capabilities as CAP
    CAP.installed_extensions = lambda: {}
except Exception:       # noqa: BLE001
    pass
CALLS = []


def fake_create(agent_id, options=None, created_by="", origin=None, job_label="", high_water_prev=None,
                high_water=None):
    CALLS.append({"options": dict(options or {}), "label": job_label})
    return {"id": "t%d" % len(CALLS), "seq": len(CALLS)}


P.create_auto_task = fake_create


def agent(**kw):
    base = dict(name="Bible ES", id="ag1", auto_publish=True, publish_method="script", publish_min_pages=3,
                publish_max_per_day=5, content_video_preset="Bible", allowed_profiles=["p1"])
    base.update(kw)
    a = AG.Agent(**base)
    AGENTS[a.id] = a
    return a


def fire():
    return A.maybe_publish_after_run("ag1", "run1", "completed", "schedule")


print("A. trường agent")
a = agent()
ok(a.publish_unverified is False and a.to_dict()["publish_unverified"] is False, "mặc định False, có trong to_dict")
ok(AG.coerce_publish_value("publish_unverified", "yes") is True and AG.coerce_publish_value("publish_unverified", 0) is False,
   "ép bool")
src = (ROOT / "tubecli" / "api" / "server.py").read_text(encoding="utf-8")
ok("publish_unverified: Optional[bool] = False" in src and "publish_unverified: Optional[bool] = None" in src,
   "AgentCreateRequest + AgentUpdateRequest có trường")

print("B. cò súng")
STORE.unlink(missing_ok=True)
agent(publish_unverified=True)
r = fire()
o = CALLS[-1]["options"]
ok(r.startswith("queued") and o.get("publish_unverified") is True and o.get("thumbnail") is False and o.get("publish"),
   "kênh chưa xác minh ⇒ options publish_unverified=True, thumbnail=False", (r, o))
agent(publish_unverified=False)
fire()
ok(CALLS[-1]["options"].get("publish_unverified") is False and CALLS[-1]["options"].get("thumbnail") is True,
   "đã xác minh ⇒ False, thumbnail theo publish_thumbnail")

STORE.unlink(missing_ok=True)
agent(publish_unverified=True)
ok(A.pause_for_length("ag1", 1031, "Bible"), "pause_for_length ghi sổ")
n = len(CALLS)
r = fire()
ok(len(CALLS) == n and r.startswith("skip: auto-publish paused") and "17:11" in r, "đang dừng ⇒ không xếp task", r)
agent(publish_unverified=True, auto_video=True)
r = fire()
ok(len(CALLS) == n + 1 and CALLS[-1]["options"].get("publish") is False and "render only" in r,
   "đang dừng + auto_video ⇒ chỉ dựng, không đăng", r)
agent(publish_unverified=False)
r = fire()
ok(r.startswith("queued") and CALLS[-1]["options"].get("publish") is True and not A.get_mark("ag1")["paused"],
   "bỏ cờ (đã xác minh) ⇒ hết dừng, đăng lại", r)
agent(publish_unverified=True)
A.pause_for_length("ag1", 1031, "Bible")
TEMPLATES["Bible"] = {"updated_at": "2026-10-19T10:00:00+07:00"}
r = fire()
ok(r.startswith("queued") and not A.get_mark("ag1")["paused"], "sửa mẫu (updated_at đổi) ⇒ hết dừng", r)
A.pause_for_length("ag1", 1031, "Bible")
agent(publish_unverified=True, content_video_preset="Short ES")
r = fire()
ok(r.startswith("queued"), "đổi mẫu ⇒ hết dừng", r)

print("C. bước đăng")
SECS = [1031.0]
P.media_seconds = lambda path: SECS[0]
PUB = []
P._publish_now = lambda state, options: PUB.append(dict(options))
P._remember_published = lambda state: None
P._commit_autopublish = lambda state, options: None


def st(**kw):
    s = {"video_path": str(TMP / "ep.mp4"), "agent": AGENTS["ag1"], "_say": lambda *a: None, "warnings": []}
    s.update(kw)
    return s


agent(publish_unverified=True)
STORE.unlink(missing_ok=True)
s = st()
P._step_publish(s, {"publish": True, "publish_unverified": True, "autopublish": True, "preset": "Bible"})
ok(not PUB and s.get("publish_blocked") == "long_unverified", "17:11 + chưa xác minh ⇒ không gọi đăng, không ném")
w = " ".join(s["warnings"])
ok("17:11" in w and "15 minutes" in w and P.VERIFY_URL in w and "paused" in w, "cảnh báo: độ dài, mức 15 phút, link xác minh, đã dừng", w)
ok(A.get_mark("ag1")["paused"].get("seconds") == 1031, "cò súng bị dừng", A.get_mark("ag1")["paused"])
SECS[0] = 899.0
s = st()
P._step_publish(s, {"publish": True, "publish_unverified": True, "autopublish": True})
ok(len(PUB) == 1 and not s.get("publish_blocked"), "14:59 ⇒ đăng bình thường")
SECS[0] = 1031.0
s = st()
P._step_publish(s, {"publish": True, "publish_unverified": False})
ok(len(PUB) == 2, "đã xác minh ⇒ video dài vẫn đăng")

print("D. đăng hỏng video dài")


def boom(state, options):
    raise RuntimeError("The upload script did not finish — step 16 sleep")


P._publish_now = boom
agent(publish_unverified=False)
STORE.unlink(missing_ok=True)
UPDATES.clear()
s = st()
try:
    P._step_publish(s, {"publish": True, "autopublish": True, "preset": "Bible"})
    ok(False, "đăng hỏng vẫn phải ném (bước optional ghi chú)")
except RuntimeError:
    ok(True, "đăng hỏng vẫn ném như cũ")
ok(UPDATES == [("ag1", {"publish_unverified": True})] and AGENTS["ag1"].publish_unverified is True,
   "task tự đăng ⇒ tự bật cờ agent", UPDATES)
ok(A.get_mark("ag1")["paused"].get("reason") == A.PAUSE_LONG_UNVERIFIED, "và dừng cò súng")
ok("now marked “not verified”" in " ".join(s["warnings"]), "cảnh báo nói đã đánh dấu + cách gỡ", s["warnings"])
UPDATES.clear()
s = st()
try:
    P._step_publish(s, {"publish": True})
except RuntimeError:
    pass
ok(not UPDATES and "tick “Channel not verified”" in " ".join(s["warnings"]), "task tay ⇒ chỉ gợi ý, không đụng agent")
SECS[0] = 600.0
agent(publish_unverified=False)
UPDATES.clear()
s = st()
try:
    P._step_publish(s, {"publish": True, "autopublish": True})
except RuntimeError:
    pass
ok(not UPDATES and "not verified" not in " ".join(s["warnings"]), "video ngắn hỏng ⇒ không đoán là chưa xác minh")

print("E. thumbnail")
th = TMP / "thumb.jpg"
th.write_bytes(b"x")
s = st(thumbnail_path=str(th), publish_unverified=True)
P._attach_thumbnail(s, "tok", "vid")
ok("not attached" in " ".join(s["warnings"]) and "verified" in " ".join(s["warnings"]), "API: không gắn, nói lý do")
psrc = (ROOT / "tubecli" / "extensions" / "content_video" / "pipeline.py").read_text(encoding="utf-8")
body = psrc[psrc.index("def _publish_via_script("):psrc.index("def _publish_now(")]
ok('and not options.get("publish_unverified")) else "0"' in body, "script: thumbnail_set=0 khi chưa xác minh")

print("F. form Codex")
cx = ROOT / "tubecli" / "extensions" / "codex"
html = (cx / "static" / "codex.html").read_text(encoding="utf-8")
js = (cx / "static" / "codex.js").read_text(encoding="utf-8")
ok('id="cx-v-yt-unverified"' in html and 'data-i18n="codex.field_video_yt_unverified"' in html, "ô trong form")
ok("o.publish_unverified = true" in js and "CV_YT_UNVERIFIED_KEY" in js
   and "lsSet(CV_YT_UNVERIFIED_KEY" in js and "lsGet(CV_YT_UNVERIFIED_KEY) === '1'" in js, "gửi option + nhớ lựa chọn")
for lang in ("en", "vi", "es", "ja", "ko", "ru", "tr", "zh-TW", "zh"):
    d = json.loads((cx / "locales" / f"{lang}.json").read_text(encoding="utf-8"))
    ok(d.get("codex.field_video_yt_unverified") and "15" in d.get("codex.field_video_yt_unverified_hint", ""),
       f"locale {lang}")

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
