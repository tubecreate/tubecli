# -*- coding: utf-8 -*-
"""Muse (muse.ai) làm nhà cung cấp AI như 9Router — chữ + ảnh qua phiên trình duyệt đã đăng nhập (2/10/2026).

Kiểm (KHÔNG chạm trình duyệt / Muse thật: ensure_browser, run_tool, chat_completion… đều giả):
  A. nhận model theo tên; build_prompt (system + yêu cầu, lượt trước thành ngữ cảnh, content dạng list); ảnh data: URI
  B. chọn chat phụ: dùng lại tới turns_per_chat rồi mở mới; đổi hồ sơ → mở mới; next_state đếm lượt
  C. parse_tool_output; settings/set_settings (hồ sơ phải có thật, kẹp số lượt)
  D. ask(): chưa chọn hồ sơ → config; chat phụ hỏng → thử lại với chat mới MỘT lần; lỗi → MuseError đúng kind
  E. generate_image_bytes → JPEG; trả chữ thay ảnh: từ chối thật → refused, tán chuyện → error
  F. image_gen: nhà "muse" (có/không hồ sơ), hỏng thì lùi Cloudflare, list_models, không tự chọn muse
  G. brain: provider rõ ràng, nhận theo tên, openai_compat_params, lỗi thành "[Muse Error] …"
  H. routes /api/v1/muse: models, chat/completions (thường + stream), mã lỗi theo kind, images/generations, settings
  I. cloud_api: PROVIDERS/khả năng/has_key theo hồ sơ/base_url; server.py include router; muse_tool.cjs đúng cú pháp

Run:  python tests/muse_test.py
"""
import asyncio
import base64
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

import tubecli.config as CFG  # noqa: E402
TMP = Path(tempfile.mkdtemp(prefix="muse_test_"))
CFG.GLOBAL_SETTINGS_FILE = TMP / "global_settings.json"
from tubecli.core import muse as M  # noqa: E402
_REAL_RUN_TOOL = M.run_tool        # các phần sau thay bằng bản giả; phần K cần bản thật

PROFILES = TMP / "profiles"
(PROFILES / "chayagent").mkdir(parents=True)
(PROFILES / "other").mkdir()
(PROFILES / "other_bas").mkdir()
M._profiles_dir = lambda: str(PROFILES)
STATE = TMP / "muse_state.json"
M._state_file = lambda: str(STATE)

PASS = FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", label)
    else:
        FAIL += 1
        print("  FAIL", label, "—", str(detail)[:300])


_PNG_N = [0]


def png_bytes(size=(64, 36), mode="RGB"):
    """Mỗi lần một ảnh KHÁC (Muse vẽ mới thật) — ảnh trùng trong cùng chat nay bị coi là Muse gửi lại ảnh cũ."""
    from PIL import Image
    buf = io.BytesIO()
    _PNG_N[0] += 1
    g = _PNG_N[0] % 250
    Image.new(mode, size, (200, g, 50) if mode == "RGB" else (200, g, 50, 128)).save(buf, "WEBP")
    return buf.getvalue()


# ── A ─────────────────────────────────────────────────────────────────────────
print("A. model + prompt")
ok(M.is_muse_model("muse-spark") and M.is_muse_model(" Muse-Image ") and not M.is_muse_model("ag/gemini"),
   "is_muse_model nhận theo tên")
p = M.build_prompt([{"role": "system", "content": "Be brief."}, {"role": "user", "content": "Write a title."}])
ok(p.startswith("[New independent request") and "Instructions:\nBe brief." in p and p.endswith("Request:\nWrite a title."),
   "system + yêu cầu", p)
p = M.build_prompt([{"role": "user", "content": "hi"}])
ok(p.endswith("\n\nhi") and "Request:" not in p, "chỉ một câu hỏi → không nhãn Request", p)
p = M.build_prompt([{"role": "user", "content": "first"}, {"role": "assistant", "content": "answer one"},
                    {"role": "user", "content": [{"type": "text", "text": "second"}, {"type": "image_url",
                                                  "image_url": {"url": "data:image/png;base64,AAAA"}}]}])
ok("Earlier messages, for context only:\nUser said: first\n\nAssistant said: answer one" in p
   and p.endswith("Request:\nsecond") and "### USER" not in p, "lượt trước là NGỮ CẢNH, content dạng list", p)
d = Path(tempfile.mkdtemp(dir=TMP))
refs = M.images_of([{"role": "user", "content": [{"type": "image_url", "image_url": {
    "url": "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xffxx").decode()}}]}], str(d))
ok(len(refs) == 1 and refs[0].endswith(".jpg") and open(refs[0], "rb").read() == b"\xff\xd8\xffxx", "ảnh data: URI → file", refs)

# ── B ─────────────────────────────────────────────────────────────────────────
print("B. chọn chat phụ")
ok(M.pick_thread({}, "chayagent", 10) == "new", "chưa có chat → new")
st = {"profile": "chayagent", "thread": "t1", "turns": 3}
ok(M.pick_thread(st, "chayagent", 10) == "t1", "còn lượt → dùng lại")
ok(M.pick_thread({**st, "turns": 10}, "chayagent", 10) == "new", "đủ lượt → new")
ok(M.pick_thread(st, "other", 10) == "new", "đổi hồ sơ → new")
ok(M.pick_thread(st, "chayagent", 10, fresh=True) == "new", "fresh → new")
n = M.next_state(st, "chayagent", "t1", {"thread_id": "t1"})
ok(n["turns"] == 4 and n["thread"] == "t1", "cùng chat → +1", n)
n = M.next_state(st, "chayagent", "new", {"thread_id": "t2"})
ok(n["turns"] == 1 and n["thread"] == "t2", "chat mới → đếm lại 1", n)
ok(M.next_state(st, "chayagent", "t1", {}) == st, "không có thread_id → giữ nguyên")

# ── C ─────────────────────────────────────────────────────────────────────────
print("C. tool output + cài đặt")
r = M.parse_tool_output('noise\n__MUSE_RESULT__{"ok": true, "text": "x"}__MUSE_END__\n')
ok(r == {"ok": True, "text": "x"}, "bóc kết quả giữa hai dấu", r)
r = M.parse_tool_output("", "Error: Cannot find module 'playwright'\n")
ok(not r["ok"] and "Cannot find module" in r["error"], "không có dấu → lỗi kèm dòng stderr cuối", r)
r = M.parse_tool_output("__MUSE_RESULT__{bad__MUSE_END__")
ok(not r["ok"] and "bad JSON" in r["error"], "JSON hỏng", r)
ok(M.settings() == {"profile": "", "extra_profiles": [], "pool": [], "lanes": 1,
                    "turns_per_chat": M.DEFAULT_TURNS_PER_CHAT, "remotes": [], "node_key": ""},
   "mặc định: chưa chọn hồ sơ, một lượt mỗi tài khoản, không nút từ xa")
try:
    M.set_settings(profile="nope")
    ok(False, "hồ sơ không có → ValueError")
except ValueError:
    ok(True, "hồ sơ không có → ValueError")
try:
    M.set_settings(profile="../x")
    ok(False, "tên đi ngược thư mục → ValueError")
except ValueError:
    ok(True, "tên đi ngược thư mục → ValueError")
ok(M.set_settings(profile="chayagent", turns_per_chat=999) == {"profile": "chayagent", "extra_profiles": [],
                                                               "pool": ["chayagent"], "lanes": 1,
                                                               "turns_per_chat": M.MAX_TURNS_PER_CHAT,
                                                               "remotes": [], "node_key": ""},
   "lưu hồ sơ + kẹp số lượt")
ok(M.set_settings(turns_per_chat=0)["turns_per_chat"] == 1 and M.settings()["profile"] == "chayagent",
   "chỉ ghi khoá được truyền; số lượt ≥ 1")
M.set_settings(turns_per_chat=10)
ok(M.local_base_url().startswith("http://127.0.0.1:") and M.local_base_url().endswith("/api/v1/muse/v1"), "base url cục bộ")

# ── D ─────────────────────────────────────────────────────────────────────────
print("D. ask()")
calls = []
_REAL_ENSURE_BROWSER = M.ensure_browser      # giữ bản thật cho nhóm E3
M.ensure_browser = lambda profile, launch=True: 9222


def tool_ok(port, action, req=None, timeout=60):
    calls.append(dict(req or {}))
    tid = req["thread"] if req["thread"] != "new" else "T-new-%d" % len(calls)
    return {"ok": True, "text": "hello", "images": [], "thread_id": tid}


M.run_tool = tool_ok
STATE.write_text("{}", encoding="utf-8")


def SL(key="chayagent"):
    """Trạng thái chat phụ của một chỗ ngồi (file trạng thái nay chia theo chỗ: {"slots": {...}})."""
    return json.loads(STATE.read_text()).get("slots", {}).get(key, {})


r = M.ask("q1")
ok(r["text"] == "hello" and calls[-1]["thread"] == "new", "lượt đầu mở chat mới", calls[-1])
M.ask("q2")
ok(calls[-1]["thread"] == "T-new-1" and SL()["turns"] == 2, "lượt sau gõ tiếp chat ấy",
   STATE.read_text())


def tool_dead_then_ok(port, action, req=None, timeout=60):
    calls.append(dict(req or {}))
    if req["thread"] != "new":
        return {"ok": False, "kind": "error", "error": "Muse chat box did not appear."}
    return {"ok": True, "text": "fresh", "images": [], "thread_id": "T-fresh"}


M.run_tool = tool_dead_then_ok
n0 = len(calls)
r = M.ask("q3")
ok(r["text"] == "fresh" and [c["thread"] for c in calls[n0:]] == ["T-new-1", "new"]
   and SL().get("thread") == "T-fresh", "chat phụ hỏng → thử lại chat mới MỘT lần",
   [c["thread"] for c in calls[n0:]])
M.run_tool = lambda port, action, req=None, timeout=60: {"ok": False, "kind": "auth", "error": "not signed in"}
try:
    M.ask("q4")
    ok(False, "lỗi đăng nhập → MuseError(auth)")
except M.MuseError as e:
    ok(e.kind == "auth" and "not signed in" in str(e), "lỗi đăng nhập → MuseError(auth)", e.kind)
ok(not M._BUSY, "chỗ ngồi được nhả sau lỗi")
M.set_settings(profile="")
try:
    M.ask("q5")
    ok(False, "chưa chọn hồ sơ → config")
except M.MuseError as e:
    ok(e.kind == "config" and "Cloud API Keys" in str(e), "chưa chọn hồ sơ → config", e)
M.set_settings(profile="chayagent")

# ── E ─────────────────────────────────────────────────────────────────────────
print("E. vẽ ảnh")
seen_req = {}


def tool_img(port, action, req=None, timeout=60):
    seen_req.update(req)
    path = os.path.join(req["image_dir"], "muse_x_0.webp")
    with open(path, "wb") as f:
        f.write(png_bytes())
    return {"ok": True, "text": "", "images": [{"path": path, "width": 64, "height": 36}], "thread_id": "T-img"}


M.run_tool = tool_img
data = M.generate_image_bytes("a fox", "9:16")
ok(data[:3] == b"\xff\xd8\xff", "webp → JPEG", data[:4])
ok(seen_req.get("want_images") and "Aspect ratio: 9:16 (vertical portrait)." in seen_req["prompt"]
   and seen_req["prompt"].rstrip().endswith("a fox"), "lời xin ảnh nói khung hình", seen_req.get("prompt"))
ok("Aspect ratio: 16:9" in M.image_request("x", "7:3"), "khung lạ → 16:9")
ok("attached image" in M.image_request("x", "1:1", with_refs=True), "có ảnh tham chiếu → nói dùng ảnh đính kèm")
M.run_tool = lambda port, action, req=None, timeout=60: {"ok": True, "text": "Sorry, I can't create that image.",
                                                         "images": [], "thread_id": "T-img"}
try:
    M.generate_image_bytes("x")
    ok(False, "từ chối → refused")
except M.MuseError as e:
    ok(e.kind == "refused", "từ chối thật → refused", e.kind)
M.run_tool = lambda port, action, req=None, timeout=60: {"ok": True, "text": "Which style would you like?",
                                                         "images": [], "thread_id": "T-img"}
try:
    M.generate_image_bytes("x")
    ok(False, "hỏi lại → error")
except M.MuseError as e:
    ok(e.kind == "error" and "Which style" in str(e), "hỏi lại / tán chuyện → error (còn đường lùi)", e.kind)

# ── E2 ────────────────────────────────────────────────────────────────────────
print("E2. video (2/10/2026: image→video 10 s, 704×1104, ~90 s)")
seen_v = {}


def tool_vid(port, action, req=None, timeout=60):
    seen_v.update(req)
    path = os.path.join(req["video_dir"], "muse_x_0.mp4")
    with open(path, "wb") as f:
        f.write(b"\x00\x00\x00\x18ftypmp42")
    return {"ok": True, "text": "", "images": [], "videos": [{"path": path, "width": 704, "height": 1104, "duration": 10}],
            "thread_id": "T-vid"}


M.run_tool = tool_vid
vd = Path(tempfile.mkdtemp(dir=TMP))
(TMP / "p.jpg").write_bytes(b"\xff\xd8\xffx")
cur_thread = SL().get("thread")      # chat phụ dùng chung đang mở (từ nhóm E)
v = M.generate_video_clip("the boy walks down the hallway", str(vd), [str(TMP / "p.jpg")], "9:16")
ok(v["path"].endswith(".mp4") and v["duration"] == 10 and v["thread_id"] == "T-vid", "generate_video_clip trả clip", v)
ok(seen_v.get("want_videos") and seen_v.get("video_dir") == str(vd) and seen_v.get("thread") == cur_thread
   and "Aspect ratio: 9:16" in seen_v["prompt"] and "reference for the person" in seen_v["prompt"],
   "lượt đầu: xin video, chat phụ dùng chung, lời xin có khung + tham chiếu", {k: seen_v.get(k) for k in ("thread", "want_videos")})
v2 = M.generate_video_clip("continue", str(vd), [], "9:16", continue_from=True, thread_id="T-vid")
ok(seen_v.get("thread") == "T-vid" and "final frame of the previous shot" in seen_v["prompt"],
   "clip nối tiếp: đúng chat phụ đã chỉ + khung đầu phải trùng khung cuối", seen_v.get("thread"))
ok(SL().get("thread") == "T-vid", "lượt đầu KHÔNG chỉ chat → dùng chat chung và ghi thread mới")
v3 = M.generate_video_clip("again", str(vd), [], "9:16", continue_from=True, thread_id="T-own")
ok(seen_v.get("thread") == "T-own" and SL().get("thread") == "T-vid",
   "thread_id riêng KHÔNG ghi đè chat phụ dùng chung")
M.run_tool = lambda port, action, req=None, timeout=60: {"ok": True, "text": "I can't make videos of real people.",
                                                         "images": [], "videos": [], "thread_id": "T"}
try:
    M.generate_video_clip("x", str(vd))
    ok(False, "từ chối → refused")
except M.MuseError as e:
    ok(e.kind == "refused", "trả chữ từ chối thay video → refused", e.kind)
M.run_tool = lambda port, action, req=None, timeout=60: {"ok": True, "text": "Xin lỗi, tôi đã gặp vấn đề khi phản hồi. Vui lòng thử lại.",
                                                         "images": [], "videos": [], "thread_id": "T"}
try:
    M.generate_video_clip("x", str(vd))
    ok(False, "lỗi hệ thống Muse → error")
except M.MuseError as e:
    ok(e.kind == "error", "«Xin lỗi, tôi đã gặp vấn đề… thử lại» = lỗi tạm thời → error (gọi lại được), không phải refused", e.kind)
ok(M._no_output_kind("I couldn't generate the image — the generation service is temporarily unavailable") == "error"
   and M._no_output_kind("Sorry, I can't create images of real people.") == "refused" and M._no_output_kind("Which style do you want?") == "error",
   "_no_output_kind: unavailable → error, từ chối thật → refused, hỏi lại → error")
M.run_tool = lambda port, action, req=None, timeout=60: {"ok": False, "kind": "timeout", "error": "Muse did not finish within 600 s."}
try:
    M.generate_video_clip("x", str(vd))
    ok(False, "hết giờ → timeout")
except M.MuseError as e:
    ok(e.kind == "timeout", "hết giờ → MuseError(timeout)", e.kind)
js_src = (ROOT / "tubecli" / "extensions" / "browser" / "muse_tool.cjs").read_text(encoding="utf-8")
ok("data-hatch-video-wrapper" in js_src and "saveVideos" in js_src and "want_videos" in js_src and "VIDEO_GRACE_MS" in js_src,
   "driver biết tải video (wrapper + poster + chờ video)")
# 3/10/2026: đính ảnh quá sớm → Muse lặng lẽ bỏ ảnh mà vẫn gửi tin (demo 2 người mất chàng trai, clip 3 #165 sai khung)
_att = js_src[js_src.index("if (files.length) {"):js_src.index("await ta.click(")]
ok("blob|data" in _att and "showed in the composer" in _att and "round < 2" in _att and _att.index("previews") < _att.index("return { ok: false"),
   "driver đính ảnh xong phải THẤY đủ ảnh xem trước; thiếu thì đính lại 1 lần, vẫn thiếu thì báo lỗi (không gửi tin thiếu ảnh)")

# ── E3 ────────────────────────────────────────────────────────────────────────
print("E3. cổng CDP từ dòng lệnh Chromium + mở ẩn hỏng sớm (2/10/2026: server restart mất dấu preview_cdp.json)")
import types as _types


class _FakeProc:
    def __init__(self, cmd, ports=()):
        self.info = {"cmdline": cmd}
        self._ports = ports

    def net_connections(self, kind="tcp"):
        return [_types.SimpleNamespace(status="LISTEN", laddr=_types.SimpleNamespace(port=pt)) for pt in self._ports]


def _fake_psutil(procs):
    m = _types.ModuleType("psutil")
    m.process_iter = lambda attrs=None: list(procs)
    return m


_real_psutil = sys.modules.get("psutil")
prof_dir = str(PROFILES / "chayagent")
alive = {64233, 5555}
M._port_alive = lambda port: int(port) in alive
sys.modules["psutil"] = _fake_psutil([
    _FakeProc(["chrome.exe", "--type=renderer", f"--user-data-dir={prof_dir}", "--remote-debugging-port=64233"]),   # tiến trình con: bỏ
    _FakeProc(["chrome.exe", f"--user-data-dir={PROFILES / 'other'}", "--remote-debugging-port=64233"]),           # hồ sơ khác: bỏ
    _FakeProc(["chrome.exe", f"--user-data-dir={prof_dir}", "--remote-debugging-port=64233"]),
])
ok(M._cdp_port_from_processes("chayagent") == 64233, "cổng đọc từ --remote-debugging-port của tiến trình chính đúng hồ sơ")
sys.modules["psutil"] = _fake_psutil([_FakeProc(["chrome.exe", f"--user-data-dir={prof_dir}", "--remote-debugging-port=0"], ports=(4444, 5555))])
ok(M._cdp_port_from_processes("chayagent") == 5555, "cổng 0 (ngẫu nhiên) → lấy cổng đang nghe mà /json/version trả lời")
sys.modules["psutil"] = _fake_psutil([_FakeProc(["chrome.exe", f"--user-data-dir={PROFILES / 'other'}", "--remote-debugging-port=64233"])])
ok(M._cdp_port_from_processes("chayagent") == 0, "không có Chromium của hồ sơ này → 0")
if _real_psutil is not None:
    sys.modules["psutil"] = _real_psutil
else:
    del sys.modules["psutil"]

# ensure_browser (bản thật, các mắt xích giả): tiến trình mở ẩn chết sớm → báo ngay lý do, không đợi hết LAUNCH_WAIT
_eb = _REAL_ENSURE_BROWSER
_seq = iter([0, 0, 0, 0])
M._cdp_port = lambda profile: next(_seq, 0)
M._launch_hidden = lambda profile: "inst-1"
M._instance_status = lambda inst: {"status": "error", "error": "Failed to launch the browser process"}
waited = []
try:
    _eb("chayagent", sleep=lambda s: waited.append(s))
    ok(False, "mở ẩn hỏng → MuseError(browser) ngay")
except M.MuseError as e:
    ok(e.kind == "browser" and "Failed to launch" in str(e) and sum(waited) < M.LAUNCH_WAIT,
       "mở ẩn hỏng → MuseError(browser) kèm lý do, không đợi hết LAUNCH_WAIT", (e.kind, str(e)[:80], sum(waited)))
_seq = iter([0, 0, 7777])
M._instance_status = lambda inst: {"status": "running"}
ok(_eb("chayagent", sleep=lambda s: waited.append(s)) == 7777, "mở ẩn xong → trả cổng")
try:
    _eb("chayagent", launch=False)
    ok(False, "launch=False mà tắt → browser")
except M.MuseError as e:
    ok(e.kind == "browser", "launch=False mà hồ sơ tắt → MuseError(browser)")

# ── F ─────────────────────────────────────────────────────────────────────────
print("F. image_gen")
from tubecli.core import image_gen as G  # noqa: E402


class FakeKM:
    def get_cloudflare_creds(self, label="default"):
        return {"api_token": "tok", "account_id": "acc", "email": "", "label": "cf"}

    def get_active_key(self, provider):
        return None

    def cloudflare_accounts(self):
        return []


G._key_manager = lambda: FakeKM()
r = G.resolve_provider("muse")
ok(r["ok"] and r["provider"] == "muse" and r["model"] == "muse-image" and r.get("fallback", {}).get("provider") == "cloudflare",
   "muse có hồ sơ → ok + lùi Cloudflare", r)
M.set_settings(profile="")
r = G.resolve_provider("muse")
ok(not r["ok"] and "browser profile" in r["reason"], "chưa chọn hồ sơ → không dùng được", r)
M.set_settings(profile="chayagent")
ok(G.resolve_provider("")["provider"] == "cloudflare", "tự chọn KHÔNG bốc muse")
ok("muse" in G.PROVIDERS and G.set_image_settings("muse", "")["provider"] == "muse", "cài đặt chung nhận muse")
G.set_image_settings("", "")
ok(asyncio.run(G.list_models("muse")) == ["muse-image"], "list_models muse")


async def fake_cf(r, prompt, ar, timeout):
    return b"\xff\xd8\xffCF"

G._cf_generate_rotating = fake_cf
M.run_tool = lambda port, action, req=None, timeout=60: {"ok": False, "kind": "browser", "error": "browser closed"}
r = G.resolve_provider("muse")
data = asyncio.run(G._generate_bytes(r, "x", "16:9"))
ok(data == b"\xff\xd8\xffCF" and r.get("drew_provider") == "cloudflare" and "Muse" in r.get("fallback_from", ""),
   "Muse hỏng → vẽ bằng Cloudflare, ghi fallback_from", r.get("fallback_from"))
M.run_tool = lambda port, action, req=None, timeout=60: {"ok": True, "text": "I cannot draw that, it violates policy.",
                                                         "images": [], "thread_id": "T"}
r = G.resolve_provider("muse")
try:
    asyncio.run(G._generate_bytes(r, "x", "16:9"))
    ok(False, "từ chối → không lùi")
except G.ProviderError as e:
    ok(e.kind == "refused", "lời từ chối KHÔNG lùi sang nhà khác", e.kind)
M.run_tool = tool_img
r = G.resolve_provider("muse")
data = asyncio.run(G._generate_bytes(r, "x", "16:9"))
ok(data[:3] == b"\xff\xd8\xff" and not r.get("fallback_from"), "Muse vẽ được → không lùi")
rk = G.resolve_key("muse")
ok(rk["ok"] and "fallback" not in rk and rk["provider"] == "muse", "resolve_key muse: không khoá, không lùi", rk)
from tubecli.core import agent_media  # noqa: E402
ok("muse" in agent_media.IMAGE_PROVIDERS, "agent_media nhận muse")

# ── G ─────────────────────────────────────────────────────────────────────────
print("G. brain")
from tubecli.core.brain import AgentBrain  # noqa: E402
got = []


def fake_chat(messages, model="muse-spark", timeout=300):
    got.append((model, messages))
    return "muse says hi"

M.chat_completion = fake_chat
msgs = [{"role": "user", "content": "hello"}]
ok(AgentBrain._call_provider("muse", "muse-spark", {}, msgs) == "muse says hi", "provider rõ ràng → Muse")
ok(AgentBrain._call_llm({"model": "muse-spark", "cloud_api_keys": {}}, msgs) == "muse says hi" and got[-1][0] == "muse-spark",
   "model muse-* không provider → Muse")
params = AgentBrain.openai_compat_params({"model": "muse-spark"})
ok(params and params[0] == M.local_base_url() and params[1] == "muse", "openai_compat_params → cổng cục bộ", params)
ok(AgentBrain.openai_compat_params({"model": "x", "provider": "muse"})[0] == M.local_base_url(), "provider muse rõ ràng")


def bad_chat(messages, model="muse-spark", timeout=300):
    raise M.MuseError("auth", "not signed in")

M.chat_completion = bad_chat
res = AgentBrain._call_provider("muse", "muse-spark", {}, msgs)
ok(res.startswith("[Muse Error]") and "not signed in" in res, "lỗi → chuỗi [Muse Error]", res)
from tubecli.api.ai_routes import is_llm_error  # noqa: E402
ok(is_llm_error(res), "nút Thử gọi nhận ra là lỗi")
M.chat_completion = fake_chat

# ── H ─────────────────────────────────────────────────────────────────────────
print("H. routes")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from tubecli.api import muse_routes as R  # noqa: E402
app = FastAPI()
app.include_router(R.router)
c = TestClient(app)
r = c.get("/api/v1/muse/v1/models").json()
ok({m["id"] for m in r["data"]} == {"muse-spark", "muse-image"}, "models", r)
r = c.post("/api/v1/muse/v1/chat/completions", json={"model": "muse-spark", "messages": msgs})
ok(r.status_code == 200 and r.json()["choices"][0]["message"]["content"] == "muse says hi", "chat thường", r.text[:200])
r = c.post("/api/v1/muse/v1/chat/completions", json={"model": "muse-spark", "messages": msgs, "stream": True})
deltas = []
for line in r.text.splitlines():
    if line.startswith("data: ") and line[6:] != "[DONE]":
        deltas.append(json.loads(line[6:])["choices"][0]["delta"].get("content", ""))
ok(r.status_code == 200 and "".join(deltas) == "muse says hi" and r.text.rstrip().endswith("data: [DONE]"),
   "chat stream ráp lại đúng chữ", r.text[:300])
M.chat_completion = bad_chat
r = c.post("/api/v1/muse/v1/chat/completions", json={"model": "muse-spark", "messages": msgs, "stream": True})
ok(r.status_code == 401 and "not signed in" in r.json()["error"]["message"], "lỗi đăng nhập → 401 TRƯỚC khi mở luồng", r.text)
M.chat_completion = fake_chat
ok(c.post("/api/v1/muse/v1/chat/completions", json={"messages": []}).status_code == 400, "thiếu messages → 400")
ok(R.aspect_from("1792x1024", None) == "16:9" and R.aspect_from("1024x1792", None) == "9:16"
   and R.aspect_from("1024x1024", None) == "1:1" and R.aspect_from("x", "3:4") == "3:4"
   and R.aspect_from(None, None) == "16:9", "size/aspect → khung hình")
ar_seen = []
M.generate_image_bytes = lambda prompt, ar="16:9", refs=None, timeout=300: ar_seen.append(ar) or b"\xff\xd8\xffIMG"
r = c.post("/api/v1/muse/v1/images/generations", json={"prompt": "fox", "size": "1024x1792", "n": 2}).json()
# nút từ xa: /v1/videos/generations trả clip base64 + thread_id; ảnh tham chiếu base64 → file tạm → xoá
vid_seen = []


def fake_video(prompt, out_dir, refs=None, ar="16:9", continue_from=False, thread_id="", timeout=600):
    vid_seen.append((prompt, [os.path.basename(x) for x in (refs or [])], ar, thread_id))
    p = os.path.join(out_dir, "clip.mp4")
    open(p, "wb").write(b"MP4DATA")
    return {"path": p, "poster": "", "width": 1248, "height": 704, "duration": 10, "thread_id": "T-r"}


M.generate_video_clip = fake_video
rv = c.post("/api/v1/muse/v1/videos/generations", json={"prompt": "walk", "aspect_ratio": "16:9", "thread_id": "T-r",
                                                          "reference_images": ["data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff" + b"x" * 200).decode()]}).json()
ok(base64.b64decode(rv["data"][0]["b64_json"]) == b"MP4DATA" and rv["data"][0]["thread_id"] == "T-r" and vid_seen[0][2] == "16:9"
   and vid_seen[0][3] == "T-r" and len(vid_seen[0][1]) == 1 and vid_seen[0][1][0].endswith(".jpg"),
   "/v1/videos/generations: clip base64 + thread_id, ảnh tham chiếu base64 thành file tạm", (rv.get("data", [{}])[0].get("thread_id"), vid_seen))
M.generate_video_clip = lambda *a, **k: (_ for _ in ()).throw(M.MuseError("refused", "no"))
rv2 = c.post("/api/v1/muse/v1/videos/generations", json={"prompt": "x"})
ok(rv2.status_code == 400 and rv2.json()["error"]["code"] == "refused", "lỗi Muse → {error: {code}} để bên gọi dựng lại MuseError")
ok(len(r["data"]) == 2 and base64.b64decode(r["data"][0]["b64_json"]) == b"\xff\xd8\xffIMG" and ar_seen == ["9:16", "9:16"],
   "images/generations n=2, khung 9:16", r)
r = c.get("/api/v1/muse/settings").json()
ok(r["profile"] == "chayagent" and r["profiles"] == ["chayagent", "other"], "settings liệt kê hồ sơ (bỏ _bas)", r)
ok(c.put("/api/v1/muse/settings", json={"profile": "ghost"}).status_code == 400, "PUT hồ sơ không có → 400")
ok(c.put("/api/v1/muse/settings", json={"turns_per_chat": 5}).json()["turns_per_chat"] == 5, "PUT số lượt")
M._cdp_port = lambda profile: 0
r = c.get("/api/v1/muse/status").json()
ok(r["configured"] and not r["running"] and "background" in r["message"], "status: hồ sơ tắt không phải hỏng", r)

# ── I ─────────────────────────────────────────────────────────────────────────
print("I. cloud_api + server + driver")
from tubecli.extensions.cloud_api import extension as X  # noqa: E402
km = X.KeyManager(data_file=str(TMP / "keys.json"))
prov = {p["id"]: p for p in km.list_providers()}
mp = prov.get("muse") or {}
ok(mp.get("has_key") and mp.get("browser_session") and mp.get("profile") == "chayagent" and mp.get("models") == ["muse-spark"]
   and mp.get("capabilities") == ["chat", "image"], "thẻ Muse: có sẵn khi đã chọn hồ sơ", mp)
ok(km.get_base_url("muse") == M.local_base_url() and X.PROVIDERS["muse"]["base_url"] == M.local_base_url(),
   "base_url = cổng cục bộ (Content Studio đọc PROVIDERS)")
M.set_settings(profile="")
ok(not {p["id"]: p for p in km.list_providers()}["muse"]["has_key"], "bỏ chọn hồ sơ → chưa sẵn")
src = (ROOT / "tubecli" / "api" / "server.py").read_text(encoding="utf-8")
ok("muse_routes import router" in src and "include_router(_muse_router)" in src, "server.py include router Muse")
tool = ROOT / "tubecli" / "extensions" / "browser" / "muse_tool.cjs"
try:
    chk = subprocess.run(["node", "--check", str(tool)], capture_output=True, text=True, timeout=30)
    ok(chk.returncode == 0, "muse_tool.cjs đúng cú pháp", chk.stderr)
except FileNotFoundError:
    ok(True, "muse_tool.cjs: không có node để kiểm (bỏ qua)")
js = tool.read_text(encoding="utf-8")
ok("browser.close()" not in js.replace("TUYỆT ĐỐI không browser.close()", ""), "driver không bao giờ đóng trình duyệt của người dùng")

print("K. run_tool không bao giờ chờ vô hạn (Pod Studio #160: treo 7,5 giờ dù hạn 645 s)")
import time as _time  # noqa: E402
_real_tool = M._tool_path
_kd = Path(tempfile.mkdtemp(prefix="muse_rt_"))
(_kd / "ok.cjs").write_text('console.log("noise"); console.log(\'__MUSE_RESULT__{"ok":true,"text":"xin chào"}__MUSE_END__\');', encoding="utf-8")
# tiến trình CHÁU kế thừa stdout rồi ngủ 60 s, cha cũng ngủ — đúng hình «có ai giữ đầu ống»
(_kd / "hang.cjs").write_text(
    "const {spawn}=require('child_process');"
    "const c=spawn(process.execPath,['-e','setTimeout(()=>{},60000)'],{stdio:'inherit'});"
    "require('fs').writeFileSync(" + json.dumps(str(_kd / "child.pid")) + ",String(c.pid));"
    "setTimeout(()=>{},60000);", encoding="utf-8")
M.run_tool = _REAL_RUN_TOOL
try:
    M._tool_path = lambda: str(_kd / "ok.cjs")
    r = M.run_tool(1, "status", timeout=5)
    ok(r.get("ok") and r.get("text") == "xin chào", "đầu ra qua file tạm vẫn đọc đúng (UTF-8)", r)
    M._tool_path = lambda: str(_kd / "hang.cjs")
    t0 = _time.time()
    r = M.run_tool(1, "ask", {"prompt": "x"}, timeout=-42)          # chờ = timeout + 45 = 3 s
    took = _time.time() - t0
    ok(r.get("kind") == "timeout" and took < 20, f"driver treo + cháu giữ stdout → timeout sau {took:.1f} s", r)
    import psutil  # noqa: E402
    _cpid = int((_kd / "child.pid").read_text() or 0)
    _time.sleep(0.5)
    ok(not psutil.pid_exists(_cpid) or psutil.Process(_cpid).status() == psutil.STATUS_ZOMBIE, "tiến trình cháu bị giết theo cây", _cpid)
    left = [n for n in os.listdir(tempfile.gettempdir()) if n.startswith(("muse_out_", "muse_err_"))
            and os.path.getmtime(os.path.join(tempfile.gettempdir(), n)) > t0 - 1]
    ok(not left, "file tạm đầu ra được dọn", left)
except FileNotFoundError:
    ok(True, "run_tool: không có node để kiểm (bỏ qua)")
finally:
    M._tool_path = _real_tool

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
