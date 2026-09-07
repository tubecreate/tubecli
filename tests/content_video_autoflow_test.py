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
    allowed_profiles = []; login_accounts = []


st = {"agent": _Agent()}
opts = {"publish_channel_name": "Cinematic Bible"}
res = P._resolve_channel(st, opts)
assert opts["publish_channel_id"] == "UC2" and opts["publish_token_id"] == "tokB" and res["name"] == "Cinematic Bible", (opts, res)
assert P._resolve_channel(st, {}) is res, "nhớ trong state, không tra lại"
st2 = {"agent": _Agent()}
o2 = {"publish_channel_name": "Nope"}
P._resolve_channel(st2, o2)
assert not o2.get("publish_channel_id") and any("no youtube account" in w.lower() for w in st2["warnings"]), st2
print("3 kênh      : tên → id + token_id qua mọi token; khớp đúng tên thắng; không thấy → cảnh báo")

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
assert runs and "studio.youtube.com/channel/UC2/videos/upload" in runs[0]["upload_url"], runs[0]["upload_url"]
assert st["published"]["video_id"] == "VID9" and st["published"]["thumbnail"] == "set" and setmb == [("VID9", png, "live-tokB")], (st["published"], setmb)
assert listed == ["UC2", "UC2"], "thử lại vì YouTube liệt kê chậm"
# không có token cho kênh → thumbnail để lại cảnh báo, video vẫn lên
P._google_tokens = lambda: []
setmb.clear()
st = {"agent": _A3(), "video_path": "/v.mp4", "thumbnail_path": png, "_say": lambda *a: None, "_cancelled": lambda: False}
P._publish_via_script(st, {"publish_channel_name": "Nope"}, "public")
assert st["published"]["via"] == "script" and not setmb and any("set it on youtube studio by hand" in w.lower() for w in st["warnings"]), st["warnings"]
print("6 đăng      : script → tìm video theo tiêu đề, gắn thumbnail, điền id/link; không token → cảnh báo rõ")

# 7. Thẻ kết quả có dòng Thumbnail (xem trước Codex bắt được đường dẫn)
out = P._render_result({"shot_count": 3, "thumbnail_path": png, "thumbnail_template_used": "news",
                        "published": {"thumbnail": "set", "url": "https://youtu.be/x", "video_id": "x"}}, {}, [], [], 1.0)
assert f"- **Thumbnail**: `{png}` · template news · set on YouTube" in out, out
print("7 thẻ       : dòng Thumbnail với đường dẫn, mẫu, trạng thái gắn")
print()
print("ALL 7 GROUPS PASSED")
