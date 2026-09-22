# Agent công khai — cửa DUY NHẤT người lạ chạm được vào máy (core/public_agents.py).
#
# Chạy:  .venv/Scripts/python tests/public_agents_test.py     (exit 0 = pass)
#
# KHÔNG gọi mạng thật ở bất kỳ đâu: đẩy hồ sơ, telemetry Town và Douyin đều bị thay
# bằng bản giả TRƯỚC khi gọi hàm. Một bài test quên giả lập từng ghi đè dữ liệu thật
# (xem memory feedback-tests-mock-all-http), nên ở đây kiểm cả việc «không có request
# nào lọt ra ngoài».
import asyncio
import hashlib
import hmac
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"[PASS] {name}")
    else:
        failed += 1
        print(f"[FAIL] {name}  {detail}")


# ── Chặn mạng: mọi urlopen trong bài test là lỗi ─────────────────────────────
import urllib.request

_net_calls = []


def _no_network(*a, **k):
    _net_calls.append(a[0] if a else k)
    raise RuntimeError("network is disabled in tests")


urllib.request.urlopen = _no_network

from tubecli.core import public_agents as pa  # noqa: E402
from tubecli.core import town_telemetry  # noqa: E402

tmp = tempfile.mkdtemp(prefix="pa-test-")
pa._path = lambda: os.path.join(tmp, "public_agents.json")
KEY = "a" * 48
IDENT = {"server_code": "abc234", "town_key": KEY}
pa._identity = lambda: {"code": IDENT["server_code"], "key": IDENT["town_key"]}

kicks = []
pa._pusher.kick = lambda: kicks.append(1)
reports = []
town_telemetry.report = lambda *a, **k: reports.append(a)


class _A:
    def __init__(self, id, name):
        self.id, self.name = id, name


AGENTS = {"ag-1": _A("ag-1", "Nhà làm phim"), "ag-2": _A("ag-2", "Second")}
pa._agents_by_id = lambda: dict(AGENTS)
# Tải máy giả: không đo CPU thật (máy chạy test đang bận là bài test chập chờn).
LOAD = {"cpu": 10.0, "ram": 20.0}
pa.machine_load = lambda: dict(LOAD)

# ── 1. Chuẩn hoá cài đặt ─────────────────────────────────────────────────────
try:
    pa.normalise({"enabled": True, "name": "x", "skills": ["douyin.resolve"]})
    check("tên 1 ký tự bị từ chối", False)
except ValueError as e:
    check("tên 1 ký tự bị từ chối (bad_name)", str(e) == "bad_name", str(e))
try:
    pa.normalise({"enabled": True, "name": "Ok name", "skills": []})
    check("bật mà không có skill bị từ chối", False)
except ValueError as e:
    check("bật mà không có skill bị từ chối (no_skills)", str(e) == "no_skills", str(e))
n = pa.normalise({"enabled": True, "name": "  Đạo diễn  ", "bio": "a\x00b\nc" * 100,
                  "skills": ["douyin.resolve", "shell.run", "douyin.resolve"], "daily_cap": 999999})
check("skill lạ bị bỏ, không lặp", n["skills"] == ["douyin.resolve"], n["skills"])
check("tên tiếng Việt được nhận, bỏ khoảng trắng hai đầu", n["name"] == "Đạo diễn", n["name"])
check("tiểu sử cắt 160 ký tự, không còn ký tự điều khiển",
      len(n["bio"]) <= 160 and "\x00" not in n["bio"] and "\n" not in n["bio"], repr(n["bio"][:20]))
check("trần/ngày bị kẹp về MAX_DAILY_CAP", n["daily_cap"] == pa.MAX_DAILY_CAP, n["daily_cap"])
check("tên trống → lấy tên agent", pa.normalise({"name": ""}, "Agent Tên")["name"] == "Agent Tên")
d0 = pa.normalise({"name": "Ok name"})
check("ngưỡng mặc định: cảnh báo 80%, song song 2, CPU 85, RAM 90",
      (d0["warn_pct"], d0["max_parallel"], d0["cpu_tired"], d0["ram_tired"]) == (80, 2, 85, 90), d0)
dk = pa.normalise({"name": "Ok name", "warn_pct": 5, "max_parallel": 99, "cpu_tired": "abc", "ram_tired": 100})
check("ngưỡng bị kẹp vào khoảng cho phép (50–95, 1–4), rác → mặc định, RAM 100 giữ nguyên",
      (dk["warn_pct"], dk["max_parallel"], dk["cpu_tired"], dk["ram_tired"]) == (50, 4, 85, 100), dk)
check("cài đặt cũ không có ngưỡng → đọc ra mặc định", pa.threshold({}, "max_parallel") == 2)
check("mệt khi CPU ≥ ngưỡng", pa.is_tired({"cpu_tired": 70}, {"cpu": 70.0, "ram": 10.0}))
check("mệt khi RAM ≥ ngưỡng", pa.is_tired({"ram_tired": 60}, {"cpu": 1.0, "ram": 61.0}))
check("ngưỡng 100 = không bao giờ mệt", not pa.is_tired({"cpu_tired": 100, "ram_tired": 100}, {"cpu": 100.0, "ram": 100.0}))
check("không đo được tải → không mệt", not pa.is_tired({"cpu_tired": 50}, None))

saved = pa.set_settings("ag-1", {"enabled": True, "name": "Douyin Helper", "skills": ["douyin.resolve"], "daily_cap": 2})
check("lưu cài đặt thì đánh thức việc đẩy hồ sơ", kicks, kicks)
check("file cài đặt nằm ở thư mục tạm của test", os.path.exists(os.path.join(tmp, "public_agents.json")))
pa.set_settings("ag-2", {"enabled": False, "name": "Second", "skills": ["douyin.resolve"]})

# ── 2. Hồ sơ đẩy lên cloud = danh sách TRẮNG ────────────────────────────────
entries = pa.public_entries()
check("chỉ agent ĐANG bật vào hồ sơ", [e["agent_id"] for e in entries] == ["ag-1"], entries)
row = pa._profile_row(entries[0])
check("hồ sơ chỉ gồm a/name/bio/skills/cap/warn/par/tired — không id thật, không tên agent gốc",
      set(row) == {"a", "name", "bio", "skills", "cap", "warn", "par", "tired"} and "ag-1" not in json.dumps(row)
      and "Nhà làm phim" not in json.dumps(row, ensure_ascii=False), row)
check("mã agent trong hồ sơ = băm của telemetry Town", row["a"] == town_telemetry.agent_hash("ag-1"))
hot = pa._profile_row(entries[0], {"cpu": 97.5, "ram": 40.0})
check("hồ sơ chỉ mang CỜ mệt, không mang số CPU/RAM thô của máy",
      hot["tired"] is True and "97" not in json.dumps(hot) and "cpu" not in hot and "ram" not in hot, hot)
AGENTS.pop("ag-2")
data = json.load(open(pa._path(), encoding="utf-8"))
data["ghost"] = {"enabled": True, "name": "Ghost", "skills": ["douyin.resolve"]}
json.dump(data, open(pa._path(), "w", encoding="utf-8"))
check("agent đã xoá không lọt vào hồ sơ", all(e["agent_id"] != "ghost" for e in pa.public_entries()))

# ── 3. Chữ ký cloud → máy ────────────────────────────────────────────────────
body = json.dumps({"agent": row["a"], "skill": "douyin.resolve", "input": "x"}).encode()
now = 1790000000
nonce = "0123456789abcdef0123"
sig = pa.sign(KEY, "invoke", str(now), body, nonce)
want = hmac.new(KEY.encode(), f"invoke.{now}.{nonce}.".encode() + body, hashlib.sha256).hexdigest()
check("chữ ký = HMAC(town_key, 'invoke.<ts>.<nonce>.<body>')", sig == want)
check("chữ ký đúng → hợp lệ", pa.verify_invoke(str(now), nonce, sig, body, now=now) == "")
check("phát lại đúng request đó → replayed", pa.verify_invoke(str(now), nonce, sig, body, now=now) == "replayed")
n2 = "fedcba9876543210fedc"
check("sai chữ ký → bad_signature", pa.verify_invoke(str(now), n2, "0" * 64, body, now=now) == "bad_signature")
check("chữ ký sai KHÔNG đốt nonce (request thật sau đó vẫn qua)",
      pa.verify_invoke(str(now), n2, pa.sign(KEY, "invoke", str(now), body, n2), body, now=now) == "")
n3 = "aaaaaaaaaaaaaaaaaaaa"
check("lệch giờ quá 5 phút → bad_signature",
      pa.verify_invoke(str(now - 301), n3, pa.sign(KEY, "invoke", str(now - 301), body, n3), body, now=now) == "bad_signature")
check("nonce sai dạng → bad_signature",
      pa.verify_invoke(str(now), "xyz", pa.sign(KEY, "invoke", str(now), body, "xyz"), body, now=now) == "bad_signature")
n4 = "bbbbbbbbbbbbbbbbbbbb"
check("chữ ký của đường 'agents' không dùng được cho invoke",
      pa.verify_invoke(str(now), n4, pa.sign(KEY, "agents", str(now), body, n4), body, now=now) == "bad_signature")
check("sửa một byte thân → bad_signature",
      pa.verify_invoke(str(now), "c" * 20, pa.sign(KEY, "invoke", str(now), body, "c" * 20), body + b" ", now=now) == "bad_signature")
_saved_ident = pa._identity
pa._identity = lambda: None
check("máy chưa có khoá → not_configured", pa.verify_invoke(str(now), "d" * 20, "x", body, now=now) == "not_configured")
pa._identity = _saved_ident

# Vector chung với cloud: tests/public_agents_test.mjs phải ra đúng chuỗi này.
VEC = pa.sign("k" * 48, "invoke", "1790000000", b'{"agent":"0123456789abcdef","skill":"douyin.resolve","input":"hi","caller":"abcdef012345"}', "00112233445566778899aabb")
check("vector chữ ký chung JS↔Python (cloud tests/public_agents_test.mjs)",
      VEC == "eed8911d3aee21394c0d04bfa017f291c8012a154b3429e701861cd9232a53ca", VEC)

# ── 4. Gọi skill ─────────────────────────────────────────────────────────────
calls = []


async def fake_handler(text):
    calls.append(text)
    if text == "boom":
        raise RuntimeError("secret internal path C:/Users/owner")
    if text == "slow":
        await asyncio.sleep(5)
    return {"kind": "video", "media": [{"type": "video", "url": "https://v.douyinvod.com/x"}]}


pa.PUBLIC_SKILLS["douyin.resolve"] = pa.PublicSkill("douyin.resolve", "douyin_downloader", fake_handler)


def run(payload):
    try:
        return "ok", asyncio.run(pa.invoke(payload))
    except pa.PublicSkillError as e:
        return e.code, e.status


h = row["a"]
check("agent không công khai → agent_not_public 404",
      run({"agent": "f" * 16, "skill": "douyin.resolve", "input": "x"}) == ("agent_not_public", 404))
check("skill không được chủ chọn → skill_not_allowed 403",
      run({"agent": h, "skill": "shell.run", "input": "x"}) == ("skill_not_allowed", 403))
check("mã agent sai dạng → bad_request", run({"agent": "../etc", "skill": "douyin.resolve", "input": "x"})[0] == "bad_request")
check("input quá dài → bad_input", run({"agent": h, "skill": "douyin.resolve", "input": "x" * 1001})[0] == "bad_input")
reports.clear()
st, res = run({"agent": h, "skill": "douyin.resolve", "input": " https://v.douyin.com/abc/ ", "caller": "abcdef012345"})
check("lượt hợp lệ chạy handler và trả kết quả", st == "ok" and res["kind"] == "video", (st, res))
check("handler nhận input đã bỏ khoảng trắng", calls[-1] == "https://v.douyin.com/abc/", calls[-1:])
check("Town thấy agent đi tới nhà Douyin rồi xong",
      [r[:2] for r in reports] == [("douyin_downloader", "running"), ("douyin_downloader", "success")], reports)
st, status = run({"agent": h, "skill": "douyin.resolve", "input": "boom"})
check("handler ném lỗi → skill_failed 502, không lộ chi tiết nội bộ", (st, status) == ("skill_failed", 502))
check("trần/ngày (2) chặn lượt thứ ba → daily_cap 429",
      run({"agent": h, "skill": "douyin.resolve", "input": "x"}) == ("daily_cap", 429))

pa._gate = pa._Gate()
LOAD.update(cpu=99.0)
check("máy quá ngưỡng CPU → tired 429, không chạy handler, không tính lượt",
      run({"agent": h, "skill": "douyin.resolve", "input": "x"}) == ("tired", 429) and pa.usage("ag-1")["used"] == 0)
LOAD.update(cpu=10.0)
pa.INVOKE_TIMEOUT_SEC = 0.2
check("handler treo → timeout 504", run({"agent": h, "skill": "douyin.resolve", "input": "slow"}) == ("timeout", 504))
g = pa._Gate()
check("cổng song song: 2 lượt cùng agent qua, lượt 3 → busy",
      [g.enter("z", 100), g.enter("z", 100), g.enter("z", 100)] == ["", "", "busy"])
g.leave("z")
check("xong một lượt thì lượt mới lại qua", g.enter("z", 100) == "")
g1 = pa._Gate()
check("chủ đặt song song = 1 → lượt thứ hai busy", [g1.enter("y", 100, 1), g1.enter("y", 100, 1)] == ["", "busy"])
check("đếm lượt hôm nay + đang chạy cho tab của chủ", g1.usage("y") == {"used": 1, "running": 1}, g1.usage("y"))

# Tắt công khai → dừng ngay ở lượt kế
pa._gate = pa._Gate()
pa.set_settings("ag-1", {"enabled": False, "name": "Douyin Helper", "skills": ["douyin.resolve"]})
check("tắt công khai → lượt kế bị từ chối ngay",
      run({"agent": h, "skill": "douyin.resolve", "input": "x"}) == ("agent_not_public", 404))

# ── 5. Skill Douyin cho người lạ ─────────────────────────────────────────────
from tubecli.extensions.douyin_downloader import public_skill as dps  # noqa: E402

share = "7.94 复制打开抖音，看看【作者的作品】ipad 立体手绘 https://v.douyin.com/2YGO60t-ZPM/ bAT:/ 07/25"
check("lấy link Douyin ra khỏi đoạn chữ chia sẻ của app", dps.pick_link(share) == "https://v.douyin.com/2YGO60t-ZPM/", dps.pick_link(share))
check("id video trần được nhận", dps.pick_link("7628804136596187301") == "7628804136596187301")
for bad in ["http://127.0.0.1:5295/api/v1/files", "https://douyin.com.evil.com/video/1",
            "https://evil.com/douyin.com/video/1", "file:///etc/passwd", "https://www.douyin.com@evil.com/x", "hello"]:
    check(f"không nhận link lạ: {bad}", dps.pick_link(bad) == "", dps.pick_link(bad))

seen = {}


class FakeParser:
    @staticmethod
    async def parse(url, proxy=None, cookie=None):
        seen["parse"] = (url, cookie)
        if "user" in url:
            return "douyin_user", "MS4w"
        return "douyin", "7628804136596187301"


class FakeInfo:
    def __init__(self, kind):
        self.kind = kind

    def to_dict(self):
        if self.kind == "image":
            return {"type": "image", "title": "t", "author": "a", "cover_url": "https://p3.douyinpic.com/c",
                    "download_url": "https://p3.douyinpic.com/1", "download_urls": [
                        "https://p3.douyinpic.com/1", "https://p3.douyinpic.com/2", "https://v3.douyinvod.com/live.mp4"]}
        return {"type": "video", "title": "T" * 500, "author": "A", "duration": "00:00:42",
                "cover_url": "https://p3-sign.douyinpic.com/c", "music_url": "",
                "download_url": "https://aweme.snssdk.com/aweme/v1/play/?video_id=v1",
                "download_urls": ["https://aweme.snssdk.com/aweme/v1/play/?video_id=v1"] + [f"https://x{i}.douyinvod.com/v" for i in range(6)]}


class FakeClient:
    kind = "video"

    @staticmethod
    async def get_video_info(platform, detail_id, cookie="", proxy=None, reasons=None):
        seen["info"] = (platform, detail_id, cookie)
        return FakeInfo(FakeClient.kind)


import types  # noqa: E402

fake_routes = types.ModuleType("tubecli.extensions.douyin_downloader.routes")
fake_routes._get_settings = lambda: {"cookie_douyin": "sessionid=OWNER_SECRET; ttwid=1%7Cabc; passport=x", "proxy": ""}
fake_api = types.ModuleType("tubecli.extensions.douyin_downloader.api_client")
fake_api.APIClient = FakeClient
fake_lp = types.ModuleType("tubecli.extensions.douyin_downloader.link_parser")
fake_lp.LinkParser = FakeParser
sys.modules["tubecli.extensions.douyin_downloader.routes"] = fake_routes
sys.modules["tubecli.extensions.douyin_downloader.api_client"] = fake_api
sys.modules["tubecli.extensions.douyin_downloader.link_parser"] = fake_lp


async def _fake_direct(url, proxy):
    return "https://v26.douyinvod.com/sig/exp/video/" + url.rsplit("=", 1)[-1] if "/aweme/v1/play" in url else ""


_real_direct = dps._direct_video
dps._direct_video = _fake_direct


def resolve(text):
    try:
        return "ok", asyncio.run(dps.resolve(text))
    except pa.PublicSkillError as e:
        return e.code, None


st, out = resolve("xem cái này https://www.douyin.com/video/7628804136596187301 nhé")
check("video: trả kết quả", st == "ok" and out["kind"] == "video", (st, out))
check("CHỈ gửi cookie ttwid — cookie đăng nhập của chủ không bao giờ đi theo",
      seen["parse"][1] == "ttwid=1%7Cabc" and seen["info"][2] == "ttwid=1%7Cabc", seen)
check("video: tối đa 3 đường CDN, không trùng", len(out["media"]) == 3 and len({m["url"] for m in out["media"]}) == 3, out["media"])
check("video: link play/ kèm link douyinvod trực tiếp để trình duyệt tự tải",
      out["media"][0].get("direct") == "https://v26.douyinvod.com/sig/exp/video/v1", out["media"][0])
check("tiêu đề bị cắt 300 ký tự", len(out["title"]) == 300)
check("có link nguồn chuẩn để người xem đối chiếu", out["source"] == "https://www.douyin.com/video/7628804136596187301")
FakeClient.kind = "image"
st, out = resolve("https://v.douyin.com/abc/")
check("bài ảnh: ảnh là image, ảnh động mp4 là video",
      st == "ok" and out["kind"] == "images" and [m["type"] for m in out["media"]] == ["image", "image", "video"], out)
# _direct_video thật: chỉ chấp nhận Location trỏ về douyinvod.com (không theo 302 tới chỗ lạ)
import types as _t
class _R:
    def __init__(self, code, loc): self.status_code, self.headers = code, {"location": loc}
class _C:
    def __init__(self, loc): self.loc = loc
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def head(self, url): return _R(302, self.loc)
    async def get(self, url, headers=None): return _R(302, self.loc)
import httpx as _httpx
_orig_client = _httpx.AsyncClient
for loc, want in [("https://v11-o.douyinvod.com/a/b/video.mp4", "https://v11-o.douyinvod.com/a/b/video.mp4"),
                  ("https://evil.com/x.mp4", ""), ("http://v11-o.douyinvod.com/x", ""), ("https://douyinvod.com.evil.com/x", "")]:
    _httpx.AsyncClient = lambda *a, _l=loc, **k: _C(_l)
    got = asyncio.run(_real_direct("https://aweme.snssdk.com/aweme/v1/play/?video_id=v1", None))
    check(f"_direct_video: Location {loc} → {'nhận' if want else 'bỏ'}", got == want, got)
_httpx.AsyncClient = _orig_client
check("_direct_video: link không phải play/ và không phải douyinvod → bỏ, không gọi mạng",
      asyncio.run(_real_direct("https://p3.douyinpic.com/x.jpg", None)) == "")

st, _ = resolve("https://www.douyin.com/user/abc")
check("trang cá nhân → unsupported_link (không kéo cả trăm video)", st == "unsupported_link", st)
st, _ = resolve("không có link nào")
check("không có link → need_douyin_link, không gọi Douyin", st == "need_douyin_link")

# ── 6. Route: chỉ phiên của chủ đổi cài đặt; invoke chỉ nhận chữ ký ───────────
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from tubecli.api import public_routes  # noqa: E402
from tubecli.core import auth  # noqa: E402

app = FastAPI()
app.include_router(public_routes.router)
client = TestClient(app)
auth.session_valid = lambda c: c == "good"
r = client.put("/api/v1/public-agents/ag-1", json={"enabled": True, "name": "Hi there", "skills": ["douyin.resolve"]})
check("PUT không có phiên → 403", r.status_code == 403, r.status_code)
client.cookies.set(auth.SESSION_COOKIE, "good")
r = client.put("/api/v1/public-agents/ag-1", headers={"x-tubecli-agent": "1"},
               json={"enabled": True, "name": "Hi there", "skills": ["douyin.resolve"]})
check("AI agent của máy (x-tubecli-agent) không tự bật công khai được → 403", r.status_code == 403, r.status_code)
r = client.post("/api/v1/public/invoke", content=body, headers={"x-town-ts": str(int(time.time())), "x-town-nonce": "e" * 20, "x-town-sig": "0" * 64})
check("invoke chữ ký sai → 401 bad_signature", r.status_code == 401 and r.json().get("code") == "bad_signature", r.text)
r = client.post("/api/v1/public/invoke", content=b"x" * 5000)
check("invoke thân quá lớn → 413 trước khi kiểm gì khác", r.status_code == 413, r.status_code)

# ── 7. Không một request nào ra mạng ─────────────────────────────────────────
check("không có request mạng nào lọt ra trong cả bài test", not _net_calls, _net_calls)

print(f"\n{passed} pass, {failed} fail")
sys.exit(1 if failed else 0)
