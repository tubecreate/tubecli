# "làm video từ những gì đã đọc, thiết kế thumbnail, đăng luôn lên kênh X" → một task auto không
# duyệt: chat hiểu lệnh, tra kênh theo tên, chọn hồ sơ trình duyệt (nhóm → đã đăng nhập → Keychain),
# bước thumbnail qua Thumbnail Studio, gắn thumbnail khi đăng.
import asyncio
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

from tubecli.core import intent_router as R  # noqa: E402
from tubecli.core import intent_handlers as H  # noqa: E402
from tubecli.extensions.content_video import pipeline as P  # noqa: E402

router = R.IntentRouter() if hasattr(R, "IntentRouter") else R.intent_router
cls = lambda msg: router.classify(msg) if hasattr(router, "classify") else router.route(msg)

# 1. Chat hiểu: đăng / khỏi duyệt / thumbnail / tên kênh (Việt + Anh, có dấu và không dấu)
r = cls("làm video từ những gì đã đọc hôm nay, thiết kế thumbnail phù hợp và đăng luôn lên kênh Cinematic Bible")
d = r.extracted_data
assert r.intent_type == "content_video" and d.get("publish") and d.get("no_review") and d.get("thumbnail"), d
assert d.get("publish_channel_name") == "Cinematic Bible", d
d = cls("tạo video từ tin tức hôm nay rồi đăng lên kênh youtube luôn, bỏ qua phần duyệt, có ảnh đại diện").extracted_data
assert d.get("publish") and d.get("no_review") and d.get("thumbnail") and not d.get("publish_channel_name"), d
d = cls("make a video from what I read today and publish it to channel News Daily without review").extracted_data
assert d.get("publish") and d.get("no_review") and d.get("publish_channel_name") == "News Daily", d
d = cls("lam video tu nhung gi da doc hom nay, dang len kenh Tin Nong khoi duyet").extracted_data
assert d.get("publish") and d.get("no_review") and d.get("publish_channel_name") == "Tin Nong", d
d = cls("làm video từ những gì đã đọc hôm nay").extracted_data
assert not d.get("publish") and not d.get("no_review") and not d.get("thumbnail"), d
d = cls("làm video 5 phút từ những gì đã đọc hôm nay và đăng lên kênh \"Góc Nhìn\" nhé").extracted_data
assert d.get("publish_channel_name") == "Góc Nhìn" and d.get("target_words") == 750, d
print("1 chat      : đăng/khỏi duyệt/thumbnail/tên kênh nhận đúng, lệnh thường không dính")

# 2. Handler: có publish/no_review → create_auto_task (không duyệt) với đủ tuỳ chọn; thường → digest
calls = {"auto": [], "digest": []}
P.create_auto_task = lambda agent_id, options=None, created_by="", origin=None, job_label="", hp=None, hw=None, sources=None: (
    calls["auto"].append((agent_id, options, created_by, job_label, sources)) or {"id": "0190a1b2-0000-7000-8000-00000000abcd", "seq": 9, "status": "queued"})
P.create_digest_task = lambda agent_id, options=None, created_by="", origin=None, sources=None, **k: (
    calls["digest"].append((agent_id, options)) or {"id": "0190a1b2-0000-7000-8000-00000000abcd", "seq": 9, "status": "queued"})
reply = asyncio.run(H.dispatch(cls("làm video từ những gì đã đọc hôm nay, có thumbnail, đăng luôn lên kênh Cinematic Bible"), {"id": "a1", "name": "CB"}, "vi"))
assert reply and "codex:" in reply and len(calls["auto"]) == 1 and not calls["digest"], (reply, calls)
aid, opts, by, label, srcs = calls["auto"][0]
assert aid == "a1" and by == "user" and opts["publish"] is True and opts["thumbnail"] is True and opts["publish_channel_name"] == "Cinematic Bible", opts
asyncio.run(H.dispatch(cls("làm video từ những gì đã đọc hôm nay"), {"id": "a1"}, "vi"))
assert len(calls["digest"]) == 1 and len(calls["auto"]) == 1
print("2 handler   : đăng/khỏi duyệt → task auto (user); lệnh thường → task duyệt")

# 3. Tra kênh theo tên qua các token Google; ưu tiên khớp đúng tên; không thấy → cảnh báo
P._google_tokens = lambda: [{"token_id": "tokA", "scopes": ["youtube"]}, {"token_id": "tokB", "scopes": ["youtube"]}]
P._vm_token = lambda tid: f"live-{tid}"
P._channels = lambda token: {"live-tokA": [{"id": "UC1", "title": "Cinematic Bible Stories", "description": "d1"}],
                             "live-tokB": [{"id": "UC2", "title": "Cinematic Bible", "description": "d2"}, {"id": "UC3", "title": "Kids"}]}[token]
found = P._find_channel(name="cinematic bible")
assert found == {"id": "UC2", "name": "Cinematic Bible", "about": "d2", "token_id": "tokB"}, found
assert P._find_channel(name="kids")["id"] == "UC3" and P._find_channel(name="Nope") == {}
assert P._find_channel(channel_id="UC1")["token_id"] == "tokA"


class _Agent:
    id = "a1"; name = "CB"; publish_channel_id = ""; publish_channel_name = ""; publish_token_id = ""
    allowed_profiles = []; login_accounts = []; language = ""

    def to_dict(self):
        return {"model": "gemini-2.0-flash"}


st = {"agent": _Agent()}
opts = {"publish_channel_name": "Cinematic Bible"}
res = P._resolve_channel(st, opts)
assert opts["publish_channel_id"] == "UC2" and opts["publish_token_id"] == "tokB" and res["name"] == "Cinematic Bible", (opts, res)
assert P._resolve_channel(st, {}) is res, "nhớ trong state, không tra lại"
st2 = {"agent": _Agent()}
o2 = {"publish_channel_name": "Nope"}
P._resolve_channel(st2, o2)
assert not o2.get("publish_channel_id") and any("no api token here" in w.lower() for w in st2["warnings"]), st2
# 3b. Không token nhưng có HỒ SƠ TRÌNH DUYỆT mang tên kênh: bí danh nhóm / tên hồ sơ / google_account
from tubecli.core import group_context as G0
from tubecli.extensions.browser import profile_manager as PM0
G0.effective_groups = lambda agent_id, group_id="": [{"profiles": [{"profile": "test2", "alias": "mai le", "access": "use"}, {"profile": "other", "alias": "", "access": "use"}]}]
PM0.get_profile = lambda name: {"test2": {"google_account": {"email": "maile.x2b1m@gmail.com"}}, "other": {"google_account": {"email": "someone@gmail.com"}}}.get(name, {})
assert P._profile_for_channel(_Agent(), "mai le") == "test2"
G0.effective_groups = lambda agent_id, group_id="": [{"profiles": [{"profile": "test2", "alias": "", "access": "use"}]}]
assert P._profile_for_channel(_Agent(), "Mai Le") == "test2", "khớp qua email google_account (maile…)"
assert P._profile_for_channel(_Agent(), "Cinematic Bible") == ""
st3 = {"agent": _Agent(), "_say": lambda *a: None}
o3 = {"publish_channel_name": "mai le"}
P._resolve_channel(st3, o3)
assert o3.get("publish_profile") == "test2" and not st3.get("warnings") and st3["channel_profile"] == "test2", (o3, st3)
G0.effective_groups = lambda agent_id, group_id="": []
print("3 kênh      : tên → id + token_id qua token; không token → hồ sơ trình duyệt mang tên/bí danh/tài khoản đó; không gì → cảnh báo có hướng dẫn")

# 4. Hồ sơ trình duyệt: nhóm đã đăng nhập → riêng đã đăng nhập → Keychain → nhóm → riêng
from tubecli.core import group_context as G
G.effective_groups = lambda agent_id, group_id="": [{"profiles": [{"profile": "g_cold", "access": "use"}, {"profile": "g_yt", "access": "use"}, {"profile": "g_noaccess", "access": "read"}]}]
from tubecli.extensions.browser import profile_manager as PM
PM.detect_logins = lambda name: {"g_yt": ["google", "youtube"], "own_yt": ["youtube"]}.get(name, [])


class _A2(_Agent):
    allowed_profiles = ["own_cold", "own_yt"]; login_accounts = ["acc1"]


assert P._login_profile(_A2(), {}) == "g_yt"
assert P._login_profile(_A2(), {"publish_profile": "forced"}) == "forced"
PM.detect_logins = lambda name: {"own_yt": ["youtube"]}.get(name, [])
assert P._login_profile(_A2(), {}) == "own_yt"
PM.detect_logins = lambda name: []
import types
sys.modules.setdefault("tubecli.extensions.keychain", types.ModuleType("tubecli.extensions.keychain"))
kc = types.ModuleType("tubecli.extensions.keychain.routes"); kc.ensure_profile_for_account = lambda acc: {"profile": f"kc_{acc}", "created": True}
sys.modules["tubecli.extensions.keychain.routes"] = kc
assert P._login_profile(_A2(), {}) == "kc_acc1"


class _A3(_Agent):
    allowed_profiles = ["own_cold"]


assert P._login_profile(_A3(), {}) == "g_cold", "không ai đăng nhập, không Keychain → hồ sơ nhóm trước hồ sơ riêng"
G.effective_groups = lambda agent_id, group_id="": []
assert P._login_profile(_A3(), {}) == "own_cold"
print("4 hồ sơ     : nhóm+đăng nhập > riêng+đăng nhập > Keychain > nhóm > riêng; publish_profile ép thắng")

# 5. Bước thumbnail: gọi /auto, chờ job, lấy phương án A, checkpoint; tắt mặc định; mẫu từ preset
TMP = tempfile.mkdtemp(prefix="cv_thumb_")
png = os.path.join(TMP, "job1_A.png"); open(png, "wb").write(b"\x89PNG" + b"\x00" * 100)
posts, gets = [], []
P._post = lambda path, payload, timeout=300: posts.append((path, payload)) or {"job_id": "job1"}
polls = iter([{"status": "running", "steps": [{"name": "background", "state": "running"}]},
              {"status": "done", "variants": [{"file": png, "template": "news"}], "warnings": ["font fallback"]}])
P._get = lambda path, timeout=60: gets.append(path) or next(polls)
P._checkpoint_merge = lambda state, extra: state.setdefault("_ck", {}).update(extra)
P.POLL_SEC = 0
said = []
st = {"agent": _A3(), "title": "El Dios Invisible", "script": "w " * 3000, "video_path": "/v.mp4", "language": "es",
      "episode_id": 7, "channel_resolved": {"id": "UC2", "name": "Cinematic Bible", "token_id": "tokB", "about": ""},
      "preset": {"name": "p", "fields": {"metadata": {"thumbnail_template": "bible_epic"}}},
      "_say": lambda *a: said.append(a), "_cancelled": lambda: False}
P._step_thumbnail(st, {"thumbnail": True})
assert posts[0][0] == "/api/v1/thumbnail/auto" and posts[0][1]["template_id"] == "bible_epic" and posts[0][1]["n"] == 1
assert posts[0][1]["channel"] == "Cinematic Bible" and posts[0][1]["lang"] == "es" and posts[0][1]["platform"] == "youtube" and len(posts[0][1]["script"]) <= 2500
assert st["thumbnail_path"] == png and st["thumbnail_template_used"] == "news" and st["_ck"] == {"thumbnail_path": png}
assert any("Thumbnail: font fallback" in w for w in st["warnings"]) and gets == ["/api/v1/thumbnail/jobs/job1"] * 2
posts.clear()
st3 = {"agent": _A3(), "_say": lambda *a: said.append(a), "_cancelled": lambda: False}
P._step_thumbnail(st3, {})
assert posts == [] and said[-1][1] == "skipped", "mặc định tắt"
assert P.DEFAULTS["thumbnail"] is False and any(s[0] == "thumbnail" for s in P.RENDER_STEPS) and "thumbnail" in P.SOFT_FAIL_STEPS
assert [s[0] for s in P.RENDER_STEPS][-3:] == ["render", "thumbnail", "publish"]
print("5 thumbnail : /auto với mẫu từ preset, chờ job, lấy A, checkpoint, cảnh báo; tắt mặc định; đứng giữa render và publish")

# 6. Đăng qua script: tra kênh, tìm video theo tiêu đề bằng API rồi gắn thumbnail và điền id/link
import types as _t
runs = []
fake_sr = _t.ModuleType("tubecli.extensions.browser_scripts.script_routes")


class _Res(dict):
    success = True
    log = ""


fake_sr.run_script_sync = lambda slug, variables=None, profile="", headless=True, timeout=None: runs.append(variables) or _Res()
sys.modules["tubecli.extensions.browser_scripts.script_routes"] = fake_sr
_real_live_publish = P._live_publish
P._live_publish = lambda *a, **k: None          # nhóm 6: không có live view → đường ẩn
P._login_profile = lambda agent, options, state=None: "g_yt"
P._seo_for = lambda state, options, channel: {"title": "El Dios Invisible", "description": "d", "tags": ["a"]}
setmb, listed = [], []


class _VM:
    @staticmethod
    def list_videos(channel_id, access_token, max_results=50):
        listed.append(channel_id)
        return [] if len(listed) < 2 else [{"id": "VID9", "title": "El Dios Invisible"}]

    @staticmethod
    def set_thumbnail(video_id, path, token):
        setmb.append((video_id, path, token)); return {"status": "success"}


P._vm_module = lambda rel, name: _VM
P._vm_uploader = lambda: _VM
P.THUMB_LOOKUP_DELAY = 0
st = {"agent": _A3(), "video_path": "/v.mp4", "thumbnail_path": png, "_say": lambda *a: None, "_cancelled": lambda: False}
opts = {"publish_channel_name": "Cinematic Bible", "publish_method": "script"}
P._publish_via_script(st, opts, "public")
assert runs and runs[0]["upload_url"] == "https://studio.youtube.com/channel/UC2/videos/upload?d=ud", runs[0]["upload_url"]
assert runs[0]["thumbnail_path"] == png and runs[0]["thumbnail_set"] == "1", runs[0]
assert st["published"]["video_id"] == "VID9" and st["published"]["thumbnail"] == "set" and setmb == [("VID9", png, "live-tokB")], (st["published"], setmb)
assert listed == ["UC2", "UC2"], "thử lại vì YouTube liệt kê chậm"
# không có token cho kênh → thumbnail để lại cảnh báo, video vẫn lên
P._google_tokens = lambda: []
setmb.clear()
st = {"agent": _A3(), "video_path": "/v.mp4", "thumbnail_path": png, "_say": lambda *a: None, "_cancelled": lambda: False}
P._publish_via_script(st, {"publish_channel_name": "Nope"}, "public")
assert st["published"]["via"] == "script" and not setmb and any("handed to the youtube studio upload script" in w.lower() for w in st["warnings"]), st["warnings"]
st = {"agent": _A3(), "video_path": "/v.mp4", "_say": lambda *a: None, "_cancelled": lambda: False}
P._publish_via_script(st, {"publish_channel_name": "Nope"}, "public")
assert runs[-1]["thumbnail_set"] == "0" and runs[-1]["thumbnail_path"] == "", "không có thumbnail → nhánh script tắt"
print("6 đăng      : script → tìm video theo tiêu đề, gắn thumbnail, điền id/link; không token → cảnh báo rõ")

# 6b. Nhánh thumbnail tự chèn vào script (một lần, sau bước mô tả), là bước condition theo thumbnail_set
class _Store:
    def __init__(self):
        self.script = {"slug": "youtube_upload", "steps": [
            {"type": "navigate", "params": {"url": "{{upload_url}}"}},
            {"type": "type", "selector": "#title-textarea #textbox", "params": {"text": "{{title}}"}},
            {"type": "type", "selector": "#description-textarea #textbox", "params": {"text": "{{description}}"}},
            {"type": "sleep", "params": {"ms": 8000}}]}
        self.saved = []

    def get_script(self, slug):
        return self.script if slug == "youtube_upload" else None

    def update_script(self, slug, **kw):
        self.script["steps"] = kw["steps"]; self.saved.append(slug); return self.script


store = _Store()
SR = sys.modules["tubecli.extensions.browser_scripts.script_routes"]   # module giả từ nhóm 6
SR._store = lambda: store
assert P.ensure_thumbnail_branch("youtube_upload") is True and store.saved == ["youtube_upload"]
steps = store.script["steps"]
assert steps[1]["label"].startswith("t2:open-upload") and steps[1]["params"]["check"].startswith("!document.querySelector"), steps[1]
assert [t["type"] for t in steps[1]["params"]["then_steps"]] == ["click_if_exists", "sleep", "click_if_exists", "sleep"]
assert "#create-icon" in steps[1]["params"]["then_steps"][0]["selector"] and "#text-item-0" in steps[1]["params"]["then_steps"][2]["selector"]
steps[3], steps[4] = steps[4], steps[3]      # thumbnail đứng sau mô tả (giờ ở 4 vì có opener) — sắp lại để các check dưới giữ nguyên
assert steps[3]["type"] == "condition" and steps[3]["label"].startswith("t2:thumbnail"), steps[3]
assert steps[3]["params"]["check"].startswith("'{{thumbnail_set}}' === '1' && !!document.querySelector(")
assert [t["type"] for t in steps[3]["params"]["then_steps"]] == ["upload", "sleep"], "không có bước wait (input ẩn)"
assert steps[3]["params"]["then_steps"][0]["selector"] == "ytcp-thumbnail-uploader input#file-loader"
assert steps[3]["params"]["then_steps"][0]["params"]["file"] == "{{thumbnail_path}}"
assert P.ensure_thumbnail_branch("youtube_upload") is False and len(store.saved) == 1, "idempotent"
steps[3]["params"]["then_steps"].insert(0, {"type": "wait"})              # bản cũ trên máy khác
assert P.ensure_thumbnail_branch("youtube_upload") is True and len(store.saved) == 2 and     [t["type"] for t in store.script["steps"][3]["params"]["then_steps"]] == ["upload", "sleep"], "bản cũ được thay"
assert P.ensure_thumbnail_branch("no_such") is False
print("6b script   : nhánh condition thumbnail chèn sau bước mô tả, một lần, không có ảnh thì bỏ qua")

# 6c. VPS không có script youtube_upload → tạo từ bản mẫu đóng kèm (44 bước, có 2 bước của pipeline)
class _EmptyStore:
    def __init__(self):
        self.created = []

    def get_script(self, slug):
        return self.created[-1] if self.created else None

    def create_script(self, name, slug=None, description="", category="general", target_url="", tags=None, steps=None, variables=None):
        d = {"name": name, "slug": slug, "steps": steps or [], "target_url": target_url}
        self.created.append(d); return d


es = _EmptyStore()
SR._store = lambda: es
assert P.ensure_upload_script("youtube_upload") is True and es.created[0]["slug"] == "youtube_upload"
seeded = es.created[0]["steps"]
assert len(seeded) >= 30 and seeded[0]["type"] == "navigate" and es.created[0]["target_url"] == "{{upload_url}}", (len(seeded), len(es.created))
assert any(str(x.get("label", "")).startswith("t2:thumbnail") for x in seeded) and any(str(x.get("label", "")).startswith("t2:open-upload") for x in seeded)
lab = [str(x.get("label", "")).split(" ")[0] for x in seeded]
wu = lab.index("t2:wait-upload")
assert seeded[wu]["type"] == "loop" and seeded[wu]["params"]["break_on"].startswith("(() =>"), seeded[wu]
assert seeded[wu]["params"]["steps"][0]["type"] == "evaluate", "vòng chờ in tiến độ ra log"
i_done = next(i for i, x in enumerate(seeded) if "#done-button" in str(x.get("selector") or ""))
i_close = max(i for i, x in enumerate(seeded) if "#close-button" in str(x.get("selector") or ""))
assert wu < lab.index("t2:clear-overlays") < i_done < lab.index("t2:publish-click") < lab.index("t2:verify-publish") < i_close, lab
assert "t2:schedule-guard" in lab and not any(str(x.get("selector") or "").startswith("[data-t2") for x in seeded), \
    "bước gõ ngày/giờ nằm trong nhánh hẹn giờ, không chạy thẳng"
assert P.ensure_upload_script("youtube_upload") is False and len(es.created) == 1, "đã có thì không tạo lại"
assert P.ensure_upload_script("no_such_script") is False
assert P.ensure_thumbnail_branch("youtube_upload") is False, "bản mẫu đã mang đúng ba bước"
# script cũ của người dùng (không có wait-upload) → chèn ngay trước nút Xuất bản, một lần
es.created[0]["steps"] = [x for x in seeded if not str(x.get("label", "")).startswith(("t2:wait-upload", "t2:clear-overlays"))]
es.update_script = lambda slug, **kw: es.created[0].update(steps=kw["steps"])
assert P.ensure_thumbnail_branch("youtube_upload") is True
s2 = es.created[0]["steps"]
l2 = [str(x.get("label", "")).split(" ")[0] for x in s2]
assert l2.count("t2:wait-upload") == 1 and l2.count("t2:clear-overlays") == 1
assert l2.index("t2:wait-upload") < l2.index("t2:clear-overlays") < next(i for i, x in enumerate(s2) if "#done-button" in str(x.get("selector") or "")), l2
assert P.ensure_thumbnail_branch("youtube_upload") is False
print("6c seed      : thiếu script trên VPS → tạo từ assets/youtube_upload.json, có sẵn ba bước pipeline; script cũ được chèn bước chờ tải lên")

# 6e. Đăng TRONG live view: mở khung Browser nếu chưa có, gắn script qua CDP (không bơm mật khẩu),
# đổ log runner vào Activity, đóng khung khi xong, giữ khung khi hỏng, không mở được thì trả None (đường ẩn)
P._live_publish = _real_live_publish      # dùng bản thật
calls, said = [], []
P.SCRIPT_LOG_POLL = 0.0; P.SCRIPT_APPEAR_WAIT = 0.5; P.LIVE_CDP_WAIT = 2
P._preview_port = lambda profile: None
P._cdp_port = lambda profile: 9222
LOGS = [{"lines": [], "offset": 0, "running": True},
        {"lines": ['{"status":"step","exec_id":7,"step_index":3,"step_type":"upload","message":"Đã nạp file lên input"}'], "offset": 1, "running": True},
        {"lines": ['{"status":"log","exec_id":7,"message":"x"}', '{"status":"done","exec_id":7,"success":true}'], "offset": 3, "running": False}]
polls = {"i": 0}


def _fake_post(path, payload, timeout=0):
    calls.append(("POST", path, payload))
    if path.endswith("/preview/launch"):
        return {"status": "launched", "session_id": "pv1", "port": 5001}
    if path.endswith("/run"):
        return {"status": "started", "exec_id": 7}
    return {"status": "stopped"}


def _fake_get(path, timeout=0):
    calls.append(("GET", path, None))
    i = min(polls["i"], len(LOGS) - 1); polls["i"] += 1
    return LOGS[i]


P._post, P._get = _fake_post, _fake_get
stl = {"_say": lambda step, status, msg: said.append(msg), "_cancelled": lambda: False}
res = P._live_publish(stl, "youtube_upload", {"upload_url": "https://studio.youtube.com/x", "title": "t"}, "test2")
assert res is not None and res.success is True and res.exec_id == 7, (res, getattr(res, "log", ""))
launch = next(c for c in calls if c[1].endswith("/preview/launch"))[2]
assert launch["profile"] == "test2" and launch["url"] == "https://studio.youtube.com/x" and launch["opened_by"] == "content_video"
run = next(c for c in calls if c[1].endswith("/youtube_upload/run"))[2]
assert run["attach"] is True and run["inject_credentials"] is False and run["headless"] is False and run["variables"]["title"] == "t", run
assert any("step 3 upload: Đã nạp file lên input" in m for m in said) and any("script finished" in m for m in said), said
assert calls[-1][1].endswith("/preview/stop") and calls[-1][2] == {"session_id": "pv1"}, "xong thì đóng khung mình mở"
assert any("watch it in the Browser node" in m for m in said), said
# live view có sẵn → không mở, không đóng
calls.clear(); said.clear(); polls["i"] = 0
P._preview_port = lambda profile: 5001
res = P._live_publish(stl, "youtube_upload", {"upload_url": "u"}, "test2")
assert res.success and not any(c[1].endswith("/preview/launch") or c[1].endswith("/preview/stop") for c in calls), calls
# hỏng → giữ khung mình mở để soi
P._preview_port = lambda profile: None
calls.clear(); said.clear(); polls["i"] = 0
LOGS[2] = {"lines": ['{"status":"done","exec_id":7,"success":false,"message":"login"}'], "offset": 2, "running": False}
res = P._live_publish(stl, "youtube_upload", {"upload_url": "u"}, "test2")
assert res.success is False and not any(c[1].endswith("/preview/stop") for c in calls) and any("stays open" in m for m in said), (calls, said)
# preflight từ chối (hết RAM…) → None, không chạy gì
calls.clear(); said.clear()
P._post = lambda path, payload, timeout=0: {"ok": False, "reason": "low_memory", "message_vi": "Máy chủ sắp hết RAM"}
assert P._live_publish(stl, "youtube_upload", {"upload_url": "u"}, "test2") is None and any("Máy chủ sắp hết RAM" in m for m in said), said
# hồ sơ đang có script khác chạy (409) → lỗi rõ, không âm thầm chạy ẩn đè lên
def _busy(path, payload, timeout=0):
    if path.endswith("/run"):
        raise RuntimeError(f"{path} → HTTP 409: busy")
    return {"status": "launched", "session_id": "pv2"}
P._post = _busy
try:
    P._live_publish(stl, "youtube_upload", {"upload_url": "u"}, "test2"); assert False, "phải ném"
except RuntimeError as e:
    assert "already running" in str(e), e
# huỷ task giữa chừng → dừng lượt chạy
P._post = _fake_post; calls.clear(); polls["i"] = 0
LOGS[2] = {"lines": [], "offset": 1, "running": True}
flags = {"n": 0}
stc = {"_say": lambda *a: None, "_cancelled": lambda: flags.__setitem__("n", flags["n"] + 1) or flags["n"] > 3}
try:
    P._follow_script_run(stc, 7); assert False, "phải ném huỷ"
except Exception as e:
    assert "Cancelled" in str(e), e
assert any(c[1].endswith("/execution/7/stop") for c in calls), calls
# _run_upload_script: live None → run_script_sync (ẩn); publish_headless ép ẩn
P._live_publish = lambda *a, **k: None
runs.clear()
r = P._run_upload_script(stl, {}, "youtube_upload", {"a": "1"}, "test2")
assert runs and runs[-1] == {"a": "1"} and isinstance(r, _Res)
P._live_publish = lambda *a, **k: (_ for _ in ()).throw(AssertionError("không được gọi khi publish_headless"))
P._run_upload_script(stl, {"publish_headless": True}, "youtube_upload", {"a": "2"}, "test2")
assert runs[-1] == {"a": "2"}
P._live_publish = lambda *a, **k: None
print("6e live view : mở khung Browser → gắn script (không bơm mật khẩu) → log vào Activity → đóng khi xong/giữ khi hỏng; từ chối/409/huỷ xử lý đúng")

# 6f. Chuỗi chống NHÁP: bọc bước hẹn giờ, dọn thứ che nút, bấm dự phòng, xác minh trạng thái thật
sched = [
    {"type": "navigate", "params": {"url": "{{upload_url}}"}},
    {"type": "type", "selector": "#description-textarea #textbox", "params": {"text": "{{description}}"}},
    {"type": "evaluate", "label": "Chế độ hiển thị", "params": {"code": "'{{schedule}}'==='1'?'skip':'vis'"}},
    {"type": "loop", "label": "Mở phần Lên lịch", "params": {"break_on": "!!document.querySelector('#datepicker-trigger')", "steps": []}},
    {"type": "click_if_exists", "selector": "#datepicker-trigger", "params": {}},
    {"type": "type", "selector": "[data-t2date='1']", "params": {"text": "{{t2_date_str}}"}},
    {"type": "type", "selector": "[data-t2time='1']", "params": {"text": "{{t2_time_str}}"}},
    {"type": "keyboard", "params": {"key": "Enter"}},
    {"type": "sleep", "params": {"ms": 800}},
    {"type": "click_if_exists", "selector": "#dismiss-button, tp-yt-paper-dialog #close-button", "params": {}},
    {"type": "wait", "selector": "#done-button", "params": {"timeout": 60000}},
    {"type": "click", "selector": "#done-button", "params": {}},
    {"type": "click_if_exists", "selector": "#close-button, ytcp-button#close-button", "params": {}},
]
steps6f = list(sched)
assert P.ensure_schedule_guard(steps6f) is True
guard = next(x for x in steps6f if str(x.get("label", "")).startswith("t2:schedule-guard"))
assert guard["type"] == "condition" and guard["params"]["check"] == "'{{schedule}}' === '1'"
inner = [x["type"] for x in guard["params"]["then_steps"]]
assert inner == ["loop", "click_if_exists", "type", "type", "keyboard", "sleep"], inner
assert not any(str(x.get("selector") or "").startswith("[data-t2") for x in steps6f), "bước gõ ngày/giờ không còn chạy thẳng"
assert [x["type"] for x in steps6f[:3]] == ["navigate", "type", "evaluate"], "bước trước đó giữ nguyên"
assert P.ensure_schedule_guard(steps6f) is False, "idempotent"
assert P.ensure_schedule_guard([{"type": "click", "selector": "#done-button"}]) is False, "script không hẹn giờ → không đụng"

# mỏ neo: xác minh đặt TRƯỚC nút đóng CUỐI (không phải nút đóng popup ở đầu), bấm dự phòng trước xác minh
st6 = list(sched)
for _pre, _mk, _pos in (("t2:wait-upload", P.wait_upload_step, P._before_done),
                        ("t2:clear-overlays", P.clear_overlays_step, P._before_done),
                        ("t2:publish-click", P.publish_click_step, P._before_verify),
                        ("t2:verify-publish", P.verify_publish_step, P._before_close)):
    assert P._place_step(st6, _pre, _mk(), _pos) is True, _pre
order = [str(x.get("label", "")).split(" ")[0] for x in st6]
i_wait, i_clear = order.index("t2:wait-upload"), order.index("t2:clear-overlays")
i_click, i_ver = order.index("t2:publish-click"), order.index("t2:verify-publish")
i_done = next(i for i, x in enumerate(st6) if x.get("selector") == "#done-button" and x["type"] == "wait")
i_close = len(st6) - 1
assert i_wait < i_clear < i_done < i_click < i_ver < i_close, order
assert st6[i_close]["type"] == "click_if_exists", "bước đóng hộp thoại vẫn là bước cuối"
assert st6[i_clear]["params"]["code"].startswith("(() =>") and "elementFromPoint" in st6[i_clear]["params"]["code"]
assert st6[i_click]["params"]["save_as"] == "t2_publish_click" and st6[i_ver]["params"]["save_as"] == P.VERIFY_PUBLISH_VAR
assert st6[i_ver].get("on_error") == "skip" and st6[i_click].get("on_error") == "skip", "ném lỗi trong trình duyệt là rơi vào smart-fix"

# _publish_verdict: nháp → hỏng thật; đăng rồi → lấy link; đóng lặng → cảnh báo; script cũ → cảnh báo
stv = {"warnings": []}
try:
    P._publish_verdict(stv, {P.VERIFY_PUBLISH_VAR: {"state": "draft", "note": "Publish | Saved as private"}})
    assert False, "phải ném"
except RuntimeError as e:
    assert "DRAFT" in str(e) and "Saved as private" in str(e), e
v = P._publish_verdict(stv, {P.VERIFY_PUBLISH_VAR: {"state": "published", "url": "https://youtu.be/AbC123_x"}})
assert v["state"] == "published" and v["url"].endswith("AbC123_x") and not stv["warnings"]
P._publish_verdict(stv, {P.VERIFY_PUBLISH_VAR: '{"state": "closed"}'})
assert any("without YouTube" in w for w in stv["warnings"]), stv
stv["warnings"] = []
P._publish_verdict(stv, {})
assert any("did not report whether" in w for w in stv["warnings"]), stv

# đăng qua script: link từ bước xác minh → id video (trước đây chỉ có cảnh báo "no video id")
P._google_tokens = lambda: []
runs.clear()


class _ResV(dict):
    success = True
    log = ""


P._run_upload_script = lambda state, options, slug, variables, profile: (
    runs.append(variables) or _ResV({P.VERIFY_PUBLISH_VAR: {"state": "published", "url": "https://youtu.be/Zz9_kk123"}}))
stp = {"agent": _A3(), "video_path": "/v.mp4", "_say": lambda *a: None, "_cancelled": lambda: False}
P._publish_via_script(stp, {"publish_channel_name": "Nope"}, "public")
assert stp["published"]["video_id"] == "Zz9_kk123" and stp["published"]["url"].endswith("Zz9_kk123"), stp["published"]
assert not any("no video id" in w.lower() for w in stp.get("warnings", [])), stp.get("warnings")
# nháp → bước đăng HỎNG (thẻ task có Retry), không báo đã đăng
P._run_upload_script = lambda state, options, slug, variables, profile: _ResV({P.VERIFY_PUBLISH_VAR: {"state": "draft"}})
stp2 = {"agent": _A3(), "video_path": "/v.mp4", "_say": lambda *a: None, "_cancelled": lambda: False}
try:
    P._publish_via_script(stp2, {"publish_channel_name": "Nope"}, "public")
    assert False, "phải ném"
except RuntimeError as e:
    assert "DRAFT" in str(e), e
assert "published" not in stp2, stp2
print("6f nháp      : bọc bước hẹn giờ; dọn thứ che nút Xuất bản; bấm dự phòng rồi xác minh; nháp → hỏng thật, có link → id video")

# 6d. Retry của lượt auto: kịch bản đã có trong checkpoint → dùng lại, không gọi model
from tubecli.core import brain as B
called = []
B.AgentBrain._call_llm = staticmethod(lambda *a, **k: called.append(1) or "TITLE: x\n\n[SHOW: a]\nb")
P._publish_plan = lambda task_id, agent_name, title, script: len(P.scenes_of(script))
P.resolve_language = lambda *a, **k: ("es", "preset")
stx = {"task_id": "t", "agent": _A3(), "corpus": [{"title": "x", "url": "u", "content": "c" * 50}],
       "checkpoint": {"script": "[SHOW: one]\nHola.\n\n[SHOW: two]\nAdiós.", "title": "El oro"},
       "_say": lambda *a: None, "_cancelled": lambda: False}
P._step_script(stx, {})
assert not called and stx["title"] == "El oro" and stx["scene_count"] == 2 and "Adiós" in stx["script"], stx.get("title")
stx["feedback"] = ["shorter"]; stx["corpus"] = [{"title": "x", "url": "u", "content": "c" * 50}]
P._write_checkpoint = lambda *a, **k: None
P._step_script(stx, {})
assert called, "có góp ý thì mới viết lại"
print("6d retry     : kịch bản trong checkpoint được dùng lại; chỉ viết lại khi có góp ý")

# 7. Thẻ kết quả có dòng Thumbnail (xem trước Codex bắt được đường dẫn)
out = P._render_result({"shot_count": 3, "thumbnail_path": png, "thumbnail_template_used": "news",
                        "published": {"thumbnail": "set", "url": "https://youtu.be/x", "video_id": "x"}}, {}, [], [], 1.0)
assert f"- **Thumbnail**: `{png}` · template news · set on YouTube" in out, out
print("7 thẻ       : dòng Thumbnail với đường dẫn, mẫu, trạng thái gắn")
print()
print("ALL 7 GROUPS PASSED")
