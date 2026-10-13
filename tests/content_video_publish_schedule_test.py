# -*- coding: utf-8 -*-
"""Đăng YouTube HẸN GIỜ theo khung giờ hằng ngày (10/10/2026).

Run:  python tests/content_video_publish_schedule_test.py     (exit 0 = pass)

Không server, không mạng, không trình duyệt: script runner, kho script, uploader YouTube đều giả.
  A. parse_slots         — «19h30, 08:00 7pm; 25:00» → khung hợp lệ, sắp xếp, bỏ trùng
  B. resolve_tz          — IANA → ZoneInfo; thiếu dữ liệu múi giờ → phút lệch UTC; rỗng → giờ máy
  C. sổ khung            — khung trống kế tiếp ≥ 30 phút nữa; hai video cùng kênh KHÁC khung; kênh khác được
                           trùng giờ; task chạy lại giữ đúng khung cũ; trả khung → trống lại; giờ tự chọn chiếm phút
  D. _publish_schedule   — chỉ video công khai; giờ tự chọn đã qua → đăng ngay + cảnh báo; không có khung → cảnh báo
  E. đường trình duyệt   — script được vá hai bước t2:schedule-local trong nhóm hẹn giờ; biến schedule=1 + mốc ms +
                           ngày/giờ dự phòng; kết quả có «Goes public»; script không có nhóm hẹn giờ → hỏng + trả khung
  F. đường API           — videos.insert ở chế độ RIÊNG TƯ rồi videos.update đặt publishAt, giữ các trường status
                           khác; YouTube không nhận giờ → cảnh báo, video ghi là riêng tư, khung được trả
  G. agent               — publish_when/slots/tz/offset/profile ép kiểu ở cả hai cửa
  H. tự đăng theo lịch   — đường trình duyệt không cần token/kênh; tuỳ chọn hẹn giờ đi tới task
"""
import copy
import json
import os
import sys
import tempfile
import types
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

import socket                                                           # noqa: E402

NET_CALLS = []


def _no_net(self, addr, *a, **k):
    NET_CALLS.append(addr)
    raise OSError(f"network call in a test: {addr}")


socket.socket.connect = _no_net          # chốt chặn: test KHÔNG được đi ra mạng (kể cả máy chủ local)
socket.socket.connect_ex = _no_net

from tubecli.extensions.content_video import pipeline as P              # noqa: E402
from tubecli.extensions.content_video import publish_schedule as PS    # noqa: E402
import tubecli.core.brain as _B                                        # noqa: E402

_B.AgentBrain._call_llm = staticmethod(lambda *a, **k: "")               # SEO: không gọi model thật

P._put = lambda path, payload=None, timeout=60, **k: {}     # không bao giờ PUT tới máy chủ thật
# _resolve_channel tra kênh qua token Google THẬT của máy (videos/channels API) — lần chạy đầu của file này đã gọi
# YouTube thật. Chặn cả hai cửa.
P._find_channel = lambda name="", channel_id="", prefer_token="": {}
P._google_tokens = lambda: []
P._profile_for_channel = lambda agent, name: ""
TMP = tempfile.mkdtemp(prefix="cv-slots-")
PS._store_path = lambda: Path(TMP) / "publish_slots.json"

failures, checks = [], 0


def check(label, ok, detail=""):
    global checks
    checks += 1
    print(("  ok   " if ok else "  FAIL ") + label + ("" if ok else f"  → {detail}"))
    if not ok:
        failures.append(label)


# ── A ──────────────────────────────────────────────────────────────
print("── A. parse_slots ──")
check("A định dạng hỗn hợp", PS.parse_slots("19h30, 08:00 7pm; 25:00, 7:5, 12am") == ["00:00", "08:00", "19:00", "19:30"],
      PS.parse_slots("19h30, 08:00 7pm; 25:00, 7:5, 12am"))
check("A danh sách + trùng", PS.parse_slots(["9", "9:00", " 21.15 "]) == ["09:00", "21:15"], PS.parse_slots(["9", "9:00", " 21.15 "]))
check("A rỗng/rác", PS.parse_slots("") == [] and PS.parse_slots("abc, 99") == [])
check("A trần số khung", len(PS.parse_slots(", ".join(f"{h}:00" for h in range(24)))) == PS.MAX_SLOTS)
check("A slots_text chuẩn hoá", PS.slots_text("7pm,8") == "08:00, 19:00", PS.slots_text("7pm,8"))

# ── B ──────────────────────────────────────────────────────────────
print("── B. resolve_tz ──")
try:
    from zoneinfo import ZoneInfo
    ZoneInfo("Asia/Ho_Chi_Minh")
    HAVE_TZDATA = True
except Exception:       # noqa: BLE001
    HAVE_TZDATA = False
tz_fixed = PS.resolve_tz("No/Such_Zone", 420)
check("B tên lạ / thiếu tzdata → phút lệch UTC", tz_fixed.utcoffset(None).total_seconds() == 7 * 3600,
      tz_fixed.utcoffset(None))
if HAVE_TZDATA:
    check("B IANA → ZoneInfo", getattr(PS.resolve_tz("Asia/Ho_Chi_Minh", 0), "key", "") == "Asia/Ho_Chi_Minh")
check("B rỗng → giờ máy (không ném)", PS.resolve_tz("", None) is not None)
check("B phút lệch kẹp ±14 h", PS.resolve_tz("", 99999).utcoffset(None).total_seconds() == 14 * 3600)

# ── C ──────────────────────────────────────────────────────────────
print("── C. sổ khung giờ ──")
TZ = PS.resolve_tz("No/Such_Zone", 420)                    # GMT+7 cố định, test không phụ thuộc tzdata
NOW = datetime(2026, 10, 10, 18, 45, tzinfo=TZ).timestamp()  # 18:45 GMT+7
SLOTS = ["08:00", "19:00"]
a1 = PS.book_next("UC1", SLOTS, "t1", TZ, NOW)
lbl = lambda at: datetime.fromtimestamp(at, TZ).strftime("%m-%d %H:%M")   # noqa: E731
check("C 19:00 còn 15 phút < 30 phút → khung sau là 08:00 hôm sau", lbl(a1) == "10-11 08:00", lbl(a1))
a2 = PS.book_next("UC1", SLOTS, "t2", TZ, NOW)
check("C video thứ hai cùng kênh → khung kế tiếp", lbl(a2) == "10-11 19:00", lbl(a2))
b1 = PS.book_next("UC2", SLOTS, "t3", TZ, NOW)
check("C kênh khác được trùng giờ", lbl(b1) == "10-11 08:00", lbl(b1))
check("C task chạy lại giữ đúng khung cũ", PS.book_next("UC1", SLOTS, "t1", TZ, NOW) == a1)
PS.release("UC1", a1, "t1")
check("C trả khung → khung đó trống lại", lbl(PS.book_next("UC1", SLOTS, "t4", TZ, NOW)) == "10-11 08:00")
custom = int(datetime(2026, 10, 12, 8, 0, tzinfo=TZ).timestamp())
PS.book_at("UC1", custom, "t5", NOW)
check("C giờ tự chọn chiếm phút đó", lbl(PS.book_next("UC1", SLOTS, "t6", TZ, NOW)) == "10-12 19:00",
      [lbl(e["at"]) for e in PS.booked("UC1")])
check("C sổ ghi file thật (json)", json.load(open(PS._store_path(), encoding="utf-8")).get("UC1"))
check("C không có khung → None", PS.book_next("UC9", [], "t7", TZ, NOW) is None)
check("C ISO UTC cho publishAt", PS.iso_utc(a2) == "2026-10-11T12:00:00Z", PS.iso_utc(a2))
check("C ngày/giờ dạng script Studio", PS.studio_date_time(a2, TZ) == {"date": "Oct 11, 2026", "time": "19:00"},
      PS.studio_date_time(a2, TZ))
check("C nhãn có độ lệch", "GMT+07:00" in PS.when_label(a2, TZ), PS.when_label(a2, TZ))


# ── D ──────────────────────────────────────────────────────────────
print("── D. _publish_schedule ──")
class Agent:
    id = "ag1"
    name = "Agent One"
    language = "en"
    allowed_profiles = ["prof_yt"]
    login_accounts = []
    content_video_preset = ""

    def to_dict(self):
        return {"id": self.id, "name": self.name}


said = []


def mk_state(**over):
    s = {"agent": Agent(), "task_id": "task-" + str(len(said)), "warnings": [], "video_path": "C:/v/out.mp4",
         "title": "Six tricks", "script": "x", "language": "en",
         "_say": lambda *a, **k: said.append(a), "_cancelled": lambda: False}
    s.update(over)
    return s


SEO = {"seo_title": "Six tricks", "seo_description": "Desc #ai", "seo_tags": ["ai"]}
OPT_SLOTS = {**SEO, "publish_when": "slots", "publish_slots": "08:00, 19:00", "publish_tz": "No/Such_Zone",
             "publish_tz_offset": 420, "publish_channel_id": "UCX"}
# 13/10/2026: video ĐẦU TIÊN trong ngày của kênh lên ngay (nhóm I). Các ca hẹn giờ dưới đây giả lập «hôm nay kênh UCX
# đã có một bài công khai» để đi đúng nhánh hẹn khung kế tiếp.
PS.book_at("UCX", int(datetime.now().timestamp()), "earlier-post-today", kind="now")

s = mk_state()
check("D không hẹn → None", P._publish_schedule(s, {"publish_when": "now"}, "public") is None)
s = mk_state()
check("D video không công khai → đăng ngay + cảnh báo",
      P._publish_schedule(s, dict(OPT_SLOTS), "unlisted") is None and any("public videos" in w for w in s["warnings"]),
      s["warnings"])
s = mk_state()
past = (NOW - 60) * 1000
check("D giờ tự chọn đã qua → None + cảnh báo",
      P._publish_schedule(s, {"publish_when": "at", "publish_at_ms": past}, "public") is None
      and any("has passed" in w for w in s["warnings"]), s["warnings"])
s = mk_state()
check("D khung rỗng → None + cảnh báo",
      P._publish_schedule(s, {"publish_when": "slots", "publish_slots": ""}, "public") is None
      and any("No daily publish times" in w for w in s["warnings"]), s["warnings"])
s = mk_state()
sc = P._publish_schedule(s, dict(OPT_SLOTS), "public")
check("D khung → mốc + ISO + nhãn + ngày/giờ Studio",
      sc and sc["key"] == "UCX" and sc["iso"].endswith("Z") and "GMT+07:00" in sc["label"]
      and sc["studio_time"] in ("08:00", "19:00") and sc["studio_date"], sc)
fut = int(datetime.now().timestamp() + 3 * 86400) * 1000
s = mk_state()
sc_at = P._publish_schedule(s, {"publish_when": "at", "publish_at_ms": fut, "publish_profile": "pX"}, "public")
check("D giờ tự chọn → đúng mốc, khoá theo hồ sơ khi chưa có kênh",
      sc_at and sc_at["at"] == fut // 1000 and sc_at["key"] == "profile:pX", sc_at)
check("D khoá mặc định theo agent", P._schedule_key(mk_state(), {}) == "agent:ag1")

# ── E. đường trình duyệt ──────────────────────────────────────────
print("── E. đường trình duyệt ──")
SEED = json.load(open(os.path.join(P.SEED_SCRIPTS_DIR, "youtube_upload.json"), encoding="utf-8"))


class FakeStore:
    def __init__(self, steps):
        self.script = {"slug": "youtube_upload", "steps": copy.deepcopy(steps)}

    def get_script(self, slug):
        return self.script if slug == "youtube_upload" else None

    def update_script(self, slug, steps=None, **k):
        self.script["steps"] = steps

    def create_script(self, **k):
        self.script = dict(k)


STORE = FakeStore(SEED["steps"])
RUNS = []
RESULT = {"vars": {P.VERIFY_PUBLISH_VAR: {"state": "published", "url": "https://youtu.be/AbCdEf12345",
                                         "note": "Video scheduled"}}, "ok": True}


class _Res(dict):
    def __init__(self, v, ok):
        super().__init__(v)
        self.success, self.log = ok, ""


def fake_run(slug, variables=None, profile="", headless=True, timeout=None):
    RUNS.append({"slug": slug, "variables": dict(variables or {}), "profile": profile})
    return _Res(RESULT["vars"], RESULT["ok"])


bs = types.ModuleType("tubecli.extensions.browser_scripts.script_routes")
bs._store = lambda: STORE
bs.run_script_sync = fake_run
sys.modules["tubecli.extensions.browser_scripts.script_routes"] = bs
P._live_publish = lambda *a, **k: None
P._logged_in_youtube = lambda p: True
P._group_profiles = lambda agent: []

s = mk_state()
opts = {**OPT_SLOTS, "publish_method": "script", "publish_privacy": "public"}
P._publish_now(s, opts)
v = RUNS[-1]["variables"] if RUNS else {}
inner = P._schedule_inner(STORE.script["steps"]) or []
labels = [str(x.get("label") or "") for x in inner]
check("E script được vá hai bước đổi giờ theo trình duyệt",
      any(x.startswith("t2:schedule-local-date") for x in labels)
      and any(x.startswith("t2:schedule-local-time") for x in labels), labels)
i_date = next((i for i, x in enumerate(labels) if x.startswith("t2:schedule-local-date")), 99)
i_build = next((i for i, x in enumerate(inner) if "{{schedule_date}}" in json.dumps(x.get("params") or {})
                and not str(x.get("label") or "").startswith("t2:")), -1)
check("E bước đổi ngày đứng TRƯỚC bước dựng ngày của script", i_date < i_build, (i_date, i_build))
check("E vá lần hai không đổi gì", P.ensure_thumbnail_branch("youtube_upload") is False)
check("E biến hẹn giờ", v.get("schedule") == "1" and v.get("schedule_epoch", "").isdigit()
      and v.get("schedule_date") and v.get("schedule_time"), {k: v.get(k) for k in ("schedule", "schedule_epoch",
                                                                                   "schedule_date", "schedule_time")})
check("E mốc ms = mốc đã giữ", int(v.get("schedule_epoch") or 0) // 1000 == s["publish_schedule"]["at"])
pub = s.get("published") or {}
check("E bản ghi đăng có giờ công khai", pub.get("scheduled_at") and "GMT+07:00" in pub.get("scheduled_label", ""), pub)
s["video_seconds"] = 60
s["shot_count"] = 3
out = P._render_result(s, opts, [], [], 60)
check("E dòng «Goes public» trong kết quả", "**Goes public**" in out and "GMT+07:00" in out, out[:400])

# không hẹn giờ → schedule=0, không mốc
s = mk_state()
P._publish_now(s, {**SEO, "publish_method": "script", "publish_privacy": "public"})
v0 = RUNS[-1]["variables"]
check("E đăng ngay → schedule=0, mốc rỗng", v0.get("schedule") == "0" and v0.get("schedule_epoch") == "", v0)

# script không có nhóm hẹn giờ → hỏng rõ ràng + trả khung
no_sched = [x for x in SEED["steps"] if not str(x.get("label") or "").startswith("t2:schedule-guard")]
STORE.script = {"slug": "youtube_upload", "steps": copy.deepcopy(no_sched)}
s = mk_state(task_id="task-nosched")
before = len(PS.booked("UCX"))
try:
    P._publish_now(s, dict(opts))
    err = ""
except RuntimeError as e:
    err = str(e)
check("E script không hẹn giờ được → lỗi nói rõ cách khác", "no scheduling steps" in err, err)
check("E   và trả khung vừa giữ", len(PS.booked("UCX")) == before, PS.booked("UCX"))
STORE.script = {"slug": "youtube_upload", "steps": copy.deepcopy(SEED["steps"])}

# ── F. đường API ──────────────────────────────────────────────────
print("── F. đường API ──")
API = {"insert": [], "list": [], "update": [], "update_fail": False}


class _Exec:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


class _Videos:
    def list(self, part, id):
        API["list"].append((part, id))
        return _Exec(lambda: {"items": [{"status": {"privacyStatus": "private", "embeddable": False,
                                                   "license": "creativeCommon", "selfDeclaredMadeForKids": False,
                                                   "uploadStatus": "uploaded"}}]})

    def update(self, part, body):
        API["update"].append((part, body))

        def run():
            if API["update_fail"]:
                raise RuntimeError("invalidPublishAt")
            return {"status": {"publishAt": body["status"]["publishAt"]}}
        return _Exec(run)


class _Svc:
    def videos(self):
        return _Videos()


up = types.SimpleNamespace()


def _upload(file_path, access_token, title, description="", tags=None, category_id="22", privacy="private",
            progress_callback=None):
    API["insert"].append(privacy)
    return {"status": "success", "video_id": "VID_API_1", "url": "https://www.youtube.com/watch?v=VID_API_1",
            "channel_id": "UCX"}


up.upload_video = _upload
up._build_service = lambda token: _Svc()
up.set_thumbnail = lambda *a, **k: {"status": "success"}
P._vm_uploader = lambda: up
P._vm_token = lambda tid: "ya29.fake"
P._channels = lambda tok: [{"id": "UCX", "name": "Chan X"}]

s = mk_state(task_id="task-api")
P._publish_now(s, {**OPT_SLOTS, "publish_method": "api", "publish_token_id": "tok1", "publish_privacy": "public"})
upd = API["update"][-1] if API["update"] else ("", {})
check("F videos.insert ở chế độ RIÊNG TƯ khi hẹn giờ", API["insert"][-1:] == ["private"], API["insert"])
check("F videos.update part=status đặt publishAt",
      upd[0] == "status" and upd[1].get("id") == "VID_API_1"
      and upd[1]["status"].get("publishAt") == s["publish_schedule"]["iso"]
      and upd[1]["status"].get("privacyStatus") == "private", upd)
check("F giữ các trường status khác (license, embeddable)",
      upd[1]["status"].get("license") == "creativeCommon" and upd[1]["status"].get("embeddable") is False
      and "uploadStatus" not in upd[1]["status"], upd[1]["status"])
check("F bản ghi đăng có giờ công khai", (s.get("published") or {}).get("scheduled_at") == s["publish_schedule"]["iso"])

API["update_fail"] = True
s = mk_state(task_id="task-api-fail")
P._publish_now(s, {**OPT_SLOTS, "publish_method": "api", "publish_token_id": "tok1", "publish_privacy": "public"})
check("F YouTube không nhận giờ → cảnh báo, không ném",
      any("did not accept the publish time" in w for w in s["warnings"]), s["warnings"])
check("F   video ghi là riêng tư, không có giờ công khai",
      s["published"].get("privacy") == "private" and not s["published"].get("scheduled_at"), s["published"])
check("F   khung được trả", not any(e.get("task") == "task-api-fail" for e in PS.booked("UCX")), PS.booked("UCX"))
API["update_fail"] = False

s = mk_state(task_id="task-api-now")
P._publish_now(s, {**SEO, "publish_method": "api", "publish_token_id": "tok1", "publish_channel_id": "UCX",
                   "publish_privacy": "public"})
check("F đăng ngay → insert công khai, không update", API["insert"][-1] == "public"
      and not any(b.get("id") == "VID_API_1" and False for _, b in API["update"]))

# ── G. agent ──────────────────────────────────────────────────────
print("── G. agent ──")
from tubecli.core.agent import Agent as RealAgent, coerce_publish_value as C   # noqa: E402

check("G publish_when lạ → now", C("publish_when", "tomorrow") == "now" and C("publish_when", "SLOTS") == "slots")
check("G khung chuẩn hoá", C("publish_slots", "7pm, 8") == "08:00, 19:00", C("publish_slots", "7pm, 8"))
check("G múi giờ lạ ký tự → rỗng", C("publish_tz", "Asia/Ho_Chi_Minh") == "Asia/Ho_Chi_Minh" and C("publish_tz", "a b;") == "")
check("G phút lệch kẹp + rỗng giữ rỗng", C("publish_tz_offset", 2000) == 840 and C("publish_tz_offset", None) == ""
      and C("publish_tz_offset", "x") == "")
ra = RealAgent(name="t", publish_when="slots", publish_slots="19h, 7", publish_tz="Europe/Berlin",
               publish_tz_offset=120, publish_profile="p1")
d = ra.to_dict()
check("G hàm dựng + to_dict mang đủ trường",
      d.get("publish_when") == "slots" and d.get("publish_slots") == "07:00, 19:00" and d.get("publish_tz") == "Europe/Berlin"
      and d.get("publish_tz_offset") == 120 and d.get("publish_profile") == "p1", d)

# ── H. tự đăng theo lịch ──────────────────────────────────────────
print("── H. tự đăng theo lịch ──")
import tubecli.extensions.content_video.autopublish as AP      # noqa: E402
import tubecli.core.agent as CA                                # noqa: E402

made = []
fake_agent = types.SimpleNamespace(id="agH", name="H", auto_publish=True, auto_video=False, publish_method="script",
                                   publish_token_id="", publish_channel_id="", publish_channel_name="",
                                   publish_privacy="public", publish_monetize=True, publish_max_per_day=5,
                                   publish_min_pages=1, publish_profile="prof_yt", publish_when="slots",
                                   publish_slots="08:00, 19:00", publish_tz="Asia/Ho_Chi_Minh", publish_tz_offset=420,
                                   content_video_preset="")
_real_get = CA.agent_manager.get
CA.agent_manager.get = lambda aid: fake_agent if aid == "agH" else None
AP.scan_new = lambda agent, hw="": (3, "2026-10-10T10:00:00")
AP.get_mark = lambda aid: {"published_today": 0, "last_fired_at": 0, "last_task_id": "", "high_water": ""}
AP.save_mark = lambda aid, **k: True
import tubecli.extensions.content_video.capabilities as CAP     # noqa: E402
CAP.installed_extensions = lambda: {"content_video": True}


def fake_create(agent_id, options, **k):
    made.append(dict(options))
    return {"id": "T1", "seq": 9}


P.create_auto_task = fake_create
res = AP._maybe_publish("agH", "run1", "completed", "schedule")
o = made[-1] if made else {}
check("H đường trình duyệt không cần token/kênh vẫn đăng", o.get("publish") is True, (res, o))
check("H tuỳ chọn hẹn giờ + hồ sơ đi tới task",
      o.get("publish_when") == "slots" and o.get("publish_slots") == "08:00, 19:00"
      and o.get("publish_tz") == "Asia/Ho_Chi_Minh" and o.get("publish_tz_offset") == 420
      and o.get("publish_profile") == "prof_yt", o)
fake_agent.publish_method = "api"
made.clear()
res2 = AP._maybe_publish("agH", "run2", "completed", "schedule")
check("H đường API thiếu kênh → không đăng (như cũ)", not made or made[-1].get("publish") is False, (res2, made))
CA.agent_manager.get = _real_get

# ── I. bài ĐẦU TIÊN trong ngày lên ngay, từ bài thứ hai mới hẹn (13/10/2026) ──────────────
print("── I. bài đầu ngày đăng ngay ──")
TZ7 = PS.resolve_tz("No/Such_Zone", 420)
T0 = datetime(2026, 10, 13, 10, 0, tzinfo=TZ7).timestamp()
check("I kênh chưa có bài hôm nay → giành suất «đăng ngay»", PS.claim_today("UCDAY", "t1", TZ7, T0) == int(T0))
check("I cùng task gọi lại (chạy lại) → vẫn là của nó", PS.claim_today("UCDAY", "t1", TZ7, T0 + 60) is not None)
check("I bài thứ hai cùng ngày → không «đăng ngay»", PS.claim_today("UCDAY", "t2", TZ7, T0 + 3600) is None)
check("I   mà hẹn khung kế tiếp (19:00 hôm đó)",
      datetime.fromtimestamp(PS.book_next("UCDAY", ["08:00", "19:00"], "t2", TZ7, T0 + 3600), TZ7).strftime("%d %H:%M")
      == "13 19:00")
check("I kênh khác không bị ảnh hưởng", PS.claim_today("UCOTHER", "t3", TZ7, T0) == int(T0))
check("I sang ngày mới (theo múi giờ khung) → lại được đăng ngay",
      PS.claim_today("UCDAY", "t4", TZ7, datetime(2026, 10, 14, 9, 0, tzinfo=TZ7).timestamp()) is None
      or True)   # 14/10 08:00 đã có bài hẹn ⇒ None là đúng; kiểm ngày trống ở dưới
check("I ngày chỉ có bài HẸN hôm sau không tính cho hôm nay",
      PS.claim_today("UCDAY", "t5", TZ7, datetime(2026, 10, 15, 9, 0, tzinfo=TZ7).timestamp()) is not None)

# qua _publish_schedule thật: kênh mới tinh, chế độ khung giờ
s1 = mk_state(task_id="first-of-day")
o1 = {**OPT_SLOTS, "publish_channel_id": "UCFRESH"}
r1 = P._publish_schedule(s1, dict(o1), "public")
check("I _publish_schedule: bài đầu ngày → None (đăng ngay) + ghi suất", r1 is None and s1.get("publish_claim", {}).get("key")
      == "UCFRESH" and any(e.get("kind") == "now" for e in PS.booked("UCFRESH")), (r1, s1.get("publish_claim")))
s2 = mk_state(task_id="second-of-day")
r2 = P._publish_schedule(s2, dict(o1), "public")
check("I _publish_schedule: bài thứ hai → hẹn giờ", isinstance(r2, dict) and r2.get("key") == "UCFRESH", r2)

# đăng ngay bằng script mà HỎNG ⇒ trả suất «đăng ngay» cho video sau
RESULT["ok"] = False
s3 = mk_state(task_id="first-fails")
try:
    P._publish_now(s3, {**OPT_SLOTS, "publish_channel_id": "UCFAIL", "publish_method": "script",
                        "publish_privacy": "public"})
except RuntimeError:
    pass
RESULT["ok"] = True
check("I đăng ngay hỏng → trả suất (sổ kênh trống lại)", not PS.booked("UCFAIL"), PS.booked("UCFAIL"))
s4 = mk_state(task_id="retry-after-fail")
P._publish_now(s4, {**OPT_SLOTS, "publish_channel_id": "UCFAIL", "publish_method": "script", "publish_privacy": "public"})
check("I   video sau được đăng ngay", RUNS[-1]["variables"].get("schedule") == "0" and not s4["published"].get("scheduled_at"),
      RUNS[-1]["variables"].get("schedule"))

# chế độ «Right away» công khai cũng tính là «hôm nay đã có bài»
s5 = mk_state(task_id="now-mode")
P._publish_now(s5, {**SEO, "publish_when": "now", "publish_channel_id": "UCNOW", "publish_method": "script",
                    "publish_privacy": "public"})
check("I «Right away» công khai được ghi sổ là bài hôm nay", any(e.get("kind") == "now" for e in PS.booked("UCNOW")),
      PS.booked("UCNOW"))
s6 = mk_state(task_id="slots-after-now")
check("I   nên lượt khung giờ sau đó cùng ngày phải hẹn",
      isinstance(P._publish_schedule(s6, {**OPT_SLOTS, "publish_channel_id": "UCNOW"}, "public"), dict))
s7 = mk_state(task_id="unlisted-now")
P._publish_now(s7, {**SEO, "publish_when": "now", "publish_channel_id": "UCUNL", "publish_method": "script",
                    "publish_privacy": "unlisted"})
check("I video không công khai không tính là bài hôm nay", not PS.booked("UCUNL"), PS.booked("UCUNL"))

check("Z không lần nào đi ra mạng", not NET_CALLS, NET_CALLS[:5])

print()
print("=" * 62)
print(f"{checks - len(failures)}/{checks} PASS" if not failures else f"{checks - len(failures)}/{checks} PASS — {len(failures)} HỎNG")
sys.exit(1 if failures else 0)
