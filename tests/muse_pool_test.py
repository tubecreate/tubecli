# -*- coding: utf-8 -*-
"""Muse nhiều TÀI KHOẢN (5/10/2026, user: «có 3 tài khoản có thể tạo cùng lúc 3 ảnh cho nhanh hơn không?»).

Kiểm (KHÔNG chạm trình duyệt / Muse thật: ensure_browser, run_tool, _cdp_port đều giả):
  A. settings: hồ sơ chính + phụ (không trùng, phải có thật), chưa có chính thì không có bể; lanes kẹp 1..MAX_LANES
  B. 3 tài khoản → 3 lượt chạy CÙNG LÚC; 1 tài khoản → xếp hàng như cũ
  C. lượt tuần tự xoay vòng qua các tài khoản; mỗi tài khoản giữ chat phụ RIÊNG; file trạng thái cũ (phẳng) vẫn đọc
  D. chat phụ của tài khoản nào thì lượt sau (chuỗi clip) chạy đúng tài khoản đó
  E. tài khoản chưa đăng nhập → thử lại ở tài khoản khác, tài khoản hỏng bị bỏ qua một lúc
  F. lanes=2: một tài khoản chạy 2 lượt cùng lúc, mỗi lượt một chat phụ
  G. status() có một dòng cho mỗi tài khoản; route PUT /settings nhận extra_profiles + lanes
  H. Muse gửi lại ảnh cũ của chat → vẽ lại trong chat mới
  I. lượt treo hết hạn → ĐÓNG phiên, hỏi lại trong chat mới (tối đa 3 lượt; ảnh / chuỗi clip cũng vậy)
  J. trình duyệt treo → đóng phiên (giải phóng RAM), mở lại, thử lại; 3 lần hỏng / chưa đăng nhập → một dòng Telegram
  K. nút Muse TỪ XA («giống 9Router»): mỗi nút = thêm chỗ ngồi; lượt rơi vào đó gọi HTTP (giả); lỗi theo mã của nút

Run:  python tests/muse_pool_test.py
"""
import asyncio
import json
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

import tubecli.config as CFG  # noqa: E402
TMP = Path(tempfile.mkdtemp(prefix="muse_pool_test_"))
CFG.GLOBAL_SETTINGS_FILE = TMP / "global_settings.json"
from tubecli.core import muse as M  # noqa: E402

PROFILES = TMP / "profiles"
for n in ("chayagent", "muse2", "muse3"):
    (PROFILES / n).mkdir(parents=True)
M._profiles_dir = lambda: str(PROFILES)
STATE = TMP / "muse_state.json"
M._state_file = lambda: str(STATE)
PORTS = {"chayagent": 9201, "muse2": 9202, "muse3": 9203}
BY_PORT = {v: k for k, v in PORTS.items()}
M.ensure_browser = lambda profile, launch=True: PORTS[profile]

PASS = FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", label)
    else:
        FAIL += 1
        print("  FAIL", label, "—", str(detail)[:300])


def reset():
    M._BUSY.clear()
    M._LAST_USED.clear()
    M._DOWN.clear()
    M._THREAD_OWNER.clear()
    M._BUSY_SINCE.clear()
    M._LAST_OK.clear()
    M._HUNG_RESET.clear()
    STATE.write_text("{}", encoding="utf-8")


def slots():
    return json.loads(STATE.read_text()).get("slots", {})


# ── A ─────────────────────────────────────────────────────────────────────────
print("A. cài đặt")
ok(M.set_settings(extra_profiles=["muse2"])["pool"] == [], "chưa có hồ sơ chính → chưa có bể (chưa cấu hình)")
st = M.set_settings(profile="chayagent", extra_profiles=["muse2", "muse3", "muse2", "chayagent", ""])
ok(st["pool"] == ["chayagent", "muse2", "muse3"] and st["extra_profiles"] == ["muse2", "muse3"],
   "bể = chính + phụ, bỏ trùng và bỏ trống", st)
try:
    M.set_settings(extra_profiles=["muse2", "khong-co"])
    ok(False, "hồ sơ phụ không có → ValueError")
except ValueError:
    ok(M.settings()["extra_profiles"] == ["muse2", "muse3"], "hồ sơ phụ không có → ValueError, giữ nguyên bể cũ")
ok(M.set_settings(lanes=9)["lanes"] == M.MAX_LANES and M.set_settings(lanes=0)["lanes"] == 1, "lanes kẹp 1..MAX_LANES")
M.set_settings(lanes=1)

# ── B ─────────────────────────────────────────────────────────────────────────
print("B. chạy cùng lúc")
live = {"now": 0, "max": 0}
used = []
mu = threading.Lock()


def slow_tool(port, action, req=None, timeout=60):
    with mu:
        live["now"] += 1
        live["max"] = max(live["max"], live["now"])
        used.append((BY_PORT[port], req["thread"]))
        tid = req["thread"] if req["thread"] != "new" else f"T-{BY_PORT[port]}-{len(used)}"
    time.sleep(0.4)
    with mu:
        live["now"] -= 1
    return {"ok": True, "text": "x", "images": [], "thread_id": tid}


def burst(n):
    out = []
    ts = [threading.Thread(target=lambda: out.append(M.ask("q"))) for _ in range(n)]
    t0 = time.time()
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    return time.time() - t0, out


M.run_tool = slow_tool
reset()
took, res = burst(3)
ok(live["max"] == 3 and took < 1.0, "3 tài khoản → 3 lượt cùng lúc (~0,4 s chứ không 1,2 s)", (live, round(took, 2)))
ok(sorted(r["profile"] for r in res) == ["chayagent", "muse2", "muse3"], "mỗi lượt một tài khoản khác nhau",
   [r["profile"] for r in res])
ok(not M._BUSY, "mọi chỗ ngồi đã nhả")
M.set_settings(extra_profiles=[])
reset()
live.update(now=0, max=0)
took, res = burst(3)
ok(live["max"] == 1 and took >= 1.1 and {r["profile"] for r in res} == {"chayagent"},
   "một tài khoản → xếp hàng từng lượt như trước", (live, round(took, 2)))
M.set_settings(extra_profiles=["muse2", "muse3"])

# ── C ─────────────────────────────────────────────────────────────────────────
print("C. xoay vòng + chat phụ riêng")
reset()
used.clear()
seq = [M.ask("q")["profile"] for _ in range(6)]
ok(seq[:3] == ["chayagent", "muse2", "muse3"] and seq[3:] == seq[:3], "lượt tuần tự xoay vòng qua các tài khoản", seq)
sl = slots()
ok(set(sl) == {"chayagent", "muse2", "muse3"} and all(v.get("turns") == 2 for v in sl.values()),
   "mỗi tài khoản một chat phụ riêng, đếm lượt riêng", sl)
ok([t for p, t in used if p == "muse2"][1] == sl["muse2"]["thread"], "lượt thứ hai của muse2 gõ tiếp chat của muse2",
   used)
STATE.write_text(json.dumps({"profile": "chayagent", "thread": "T-old", "turns": 3}), encoding="utf-8")
ok(M._slot_state(M._load_state(), "chayagent").get("thread") == "T-old"
   and M._slot_state(M._load_state(), "muse2") == {}, "file trạng thái cũ (một hồ sơ) = chỗ của hồ sơ chính")
M._save_slot("muse2", {"profile": "muse2", "thread": "T-m2", "turns": 1})
ok(slots().get("chayagent", {}).get("thread") == "T-old" and slots()["muse2"]["thread"] == "T-m2",
   "ghi chỗ mới không làm mất chat cũ của hồ sơ chính")

# ── D ─────────────────────────────────────────────────────────────────────────
print("D. chuỗi clip ở đúng tài khoản")
reset()
seen = []


def chain_tool(port, action, req=None, timeout=60):
    seen.append((BY_PORT[port], req["thread"]))
    tid = req["thread"] if req["thread"] != "new" else f"CH-{BY_PORT[port]}"
    return {"ok": True, "text": "", "videos": [], "thread_id": tid}


M.run_tool = chain_tool
M._LAST_USED.update({"chayagent": 3.0, "muse2": 1.0, "muse3": 2.0})       # muse2 lâu chưa dùng nhất
first = M.ask("clip 1", thread_id="new")
ok(first["profile"] == "muse2" and first["thread_id"] == "CH-muse2", "clip đầu: chat MỚI ở tài khoản rảnh", first)
for _ in range(3):
    M.ask("clip n", thread_id="CH-muse2")
ok([p for p, _ in seen[1:]] == ["muse2"] * 3, "clip nối tiếp luôn ở tài khoản mở chat ấy", seen)
M.ask("legacy", thread_id="T-unknown")
ok(seen[-1][0] == "chayagent", "chat phụ không rõ chủ (trước khi có bể) → hồ sơ chính như cũ", seen[-1])

# ── E ─────────────────────────────────────────────────────────────────────────
print("E. tài khoản hỏng")
reset()
tried = []


def muse2_signed_out(port, action, req=None, timeout=60):
    tried.append(BY_PORT[port])
    if BY_PORT[port] == "muse2":
        return {"ok": False, "kind": "auth", "error": "not signed in"}
    return {"ok": True, "text": "ok", "images": [], "thread_id": "T-" + BY_PORT[port]}


M.run_tool = muse2_signed_out
M._LAST_USED.update({"chayagent": 3.0, "muse2": 1.0, "muse3": 2.0})
r = M.ask("q")
ok(tried == ["muse2", "muse3"] and r["profile"] == "muse3", "muse2 chưa đăng nhập → thử lại ở tài khoản khác", tried)
ok(M._DOWN.get("muse2", 0) > time.time(), "muse2 bị bỏ qua một lúc")
tried.clear()
for _ in range(4):
    M.ask("q")
ok("muse2" not in tried, "các lượt sau không đụng tới muse2", tried)
M.run_tool = lambda port, action, req=None, timeout=60: {"ok": False, "kind": "auth", "error": "not signed in"}
reset()
try:
    M.ask("q")
    ok(False, "mọi tài khoản hỏng → MuseError")
except M.MuseError as e:
    ok(e.kind == "auth" and not M._BUSY, "mọi tài khoản hỏng → MuseError(auth), chỗ ngồi đã nhả", e.kind)
M.run_tool = lambda port, action, req=None, timeout=60: {"ok": False, "kind": "refused", "error": "policy"}
reset()
try:
    M.ask("q")
except M.MuseError as e:
    ok(e.kind == "refused" and not M._DOWN, "từ chối nội dung KHÔNG làm tài khoản bị bỏ qua", M._DOWN)

# ── F ─────────────────────────────────────────────────────────────────────────
print("F. nhiều lượt trên một tài khoản")
M.set_settings(extra_profiles=[], lanes=2)
M.run_tool = slow_tool
reset()
live.update(now=0, max=0)
used.clear()
took, res = burst(2)
ok(live["max"] == 2 and took < 0.8, "lanes=2 → một tài khoản chạy 2 lượt cùng lúc", (live, round(took, 2)))
ok(set(slots()) == {"chayagent", "chayagent#2"} and slots()["chayagent"]["thread"] != slots()["chayagent#2"]["thread"],
   "mỗi lượt một chat phụ riêng (không gõ chung một chat)", slots())
M.set_settings(extra_profiles=["muse2", "muse3"], lanes=1)

# ── G ─────────────────────────────────────────────────────────────────────────
print("G. trạng thái + route")
reset()
M._cdp_port = lambda profile: 0 if profile == "muse3" else PORTS[profile]
M.run_tool = lambda port, action, req=None, timeout=60: {"ok": True, "logged_in": BY_PORT[port] != "muse2",
                                                          "verified": True}
s = M.status()
rows = {r["profile"]: r for r in s["pool"]}
ok(list(rows) == ["chayagent", "muse2", "muse3"] and s["logged_in"] is True and s["profile"] == "chayagent",
   "status: dòng cho mỗi tài khoản, trường ngoài là của hồ sơ chính", s)
ok(rows["muse2"]["logged_in"] is False and "not signed in" in rows["muse2"]["message"]
   and rows["muse3"]["running"] is False, "status: muse2 chưa đăng nhập, muse3 đang tắt", rows)

from tubecli.api import muse_routes as R  # noqa: E402
r = asyncio.run(R.api_put_settings(R.MuseSettingsRequest(extra_profiles=["muse3"], lanes=2)))
ok(r["pool"] == ["chayagent", "muse3"] and r["lanes"] == 2, "PUT /settings nhận extra_profiles + lanes", r)
g = asyncio.run(R.api_get_settings())
ok(g["max_lanes"] == M.MAX_LANES and "muse2" in g["profiles"] and g["extra_profiles"] == ["muse3"],
   "GET /settings: max_lanes, danh sách hồ sơ để chọn, hồ sơ phụ đang dùng", g)

# ── H ─────────────────────────────────────────────────────────────────────────
print("H. Muse gửi lại ảnh cũ")
import io  # noqa: E402
import os  # noqa: E402
from PIL import Image  # noqa: E402


def png(color):
    buf = io.BytesIO()
    Image.new("RGB", (64, 36), color).save(buf, "PNG")
    return buf.getvalue()


M.set_settings(extra_profiles=[], lanes=1)
M._cdp_port = lambda profile: PORTS[profile]
reset()
M._THREAD_IMAGES.clear()
plan = []
asked = []


def img_tool(port, action, req=None, timeout=60):
    asked.append(req["thread"])
    color, tid = plan.pop(0)
    p = os.path.join(req["image_dir"], f"x{len(asked)}.png")
    with open(p, "wb") as f:
        f.write(png(color))
    return {"ok": True, "text": "", "images": [{"path": p}], "thread_id": tid}


M.run_tool = img_tool
plan[:] = [("red", "T1"), ("red", "T1"), ("blue", "T2")]
a = M.generate_image_bytes("shot 26")
b = M.generate_image_bytes("shot 27")
ok(asked == ["new", "T1", "new"] and a != b, "ảnh trùng ảnh chat đã gửi → vẽ lại trong chat MỚI", asked)
plan[:] = [("blue", "T1")]
asked.clear()
c = M.generate_image_bytes("shot 28")
ok(asked == ["T1"] and c == b, "ảnh giống ảnh của chat KHÁC → vẫn nhận (chỉ so trong cùng chat)", asked)
plan[:] = [("green", "T3"), ("green", "T3")]
M.generate_image_bytes("shot 29")
plan[:] = [("green", "T3"), ("green", "T3")]
asked.clear()
try:
    M._THREAD_IMAGES.setdefault("T3", []).append(__import__("hashlib").sha1(png("green")).hexdigest())
    M._save_slot("chayagent", {"profile": "chayagent", "thread": "T3", "turns": 1})
    M.generate_image_bytes("shot 30", thread_id="T3")
    ok(False, "trùng cả hai lần → MuseError")
except M.MuseError as e:
    ok("earlier image" in str(e) and asked == ["T3", "new"], "trùng cả hai lần → MuseError, không trả tranh nhịp khác",
       (str(e), asked))

# ── I ─────────────────────────────────────────────────────────────────────────
print("I. lượt chữ treo hết hạn")
M.set_settings(extra_profiles=["muse2", "muse3"], lanes=1)
reset()
hung = []


def first_hangs(port, action, req=None, timeout=60):
    hung.append((BY_PORT[port], req["thread"]))
    if len(hung) == 1:
        return {"ok": False, "kind": "timeout", "error": "Muse did not finish within 300 s.", "thread_id": "T-hang"}
    return {"ok": True, "text": "scenes", "images": [], "thread_id": "T-" + BY_PORT[port]}


M.run_tool = first_hangs
M.RESET_WAIT = 0
resets = []
M.reset_browser = lambda p: (resets.append(p) or True)
M._save_slot("chayagent", {"profile": "chayagent", "thread": "T-hang", "turns": 3})
M._LAST_USED.update({"chayagent": 1.0, "muse2": 2.0, "muse3": 3.0})
r = M.ask("describe scenes 1-12")
ok(r["text"] == "scenes" and len(hung) == 2 and hung[1][1] == "new" and resets == ["chayagent"],
   "treo → ĐÓNG phiên tài khoản ấy, hỏi lại trong chat mới (user 9/10: «15 phút không thành công thì reset phiên»)", (hung, resets))
ok(not M._DOWN and not M._BUSY, "treo không làm tài khoản bị bỏ qua, chỗ ngồi đã nhả", (M._DOWN, M._BUSY))
M.run_tool = lambda port, action, req=None, timeout=60: (hung.append(1) or
                                                        {"ok": False, "kind": "timeout", "error": "slow"})
reset()
hung.clear()
resets.clear()
try:
    M.ask("q")
    ok(False, "treo mãi → MuseError")
except M.MuseError as e:
    ok(e.kind == "timeout" and len(hung) == M.MUSE_ATTEMPTS and len(resets) == M.MUSE_ATTEMPTS - 1,
       "treo mãi → đóng phiên + thử lại đủ 3 lượt rồi MuseError(timeout)", (hung, resets))
reset()
hung.clear()
resets.clear()
try:
    M.ask("draw", want_images=True)
except M.MuseError:
    pass
n_img = len(hung)
try:
    M.ask("clip", thread_id="CH-x")
except M.MuseError:
    pass
ok(n_img == M.MUSE_ATTEMPTS and len(hung) == 2 * M.MUSE_ATTEMPTS and len(resets) == 2 * (M.MUSE_ATTEMPTS - 1),
   "ảnh / chat riêng (chuỗi clip) treo → cũng đóng phiên + thử lại", (hung, resets))
ok(M.VIDEO_TIMEOUT == 900, "một lượt quay chờ tối đa 15 phút")

# ── J ─────────────────────────────────────────────────────────────────────────
print("J. trình duyệt treo → đóng phiên, mở lại, thử lại; 3 lần hỏng → Telegram")
M.set_settings(profile="chayagent", extra_profiles=["muse2", "muse3"], lanes=1)
reset()
M.RESET_WAIT = 0
real_alert = M._alert
killed, alerts, seq = [], [], []
M.reset_browser = lambda p: (killed.append(p) or True)
M._alert = lambda reason, text: (alerts.append((reason, text)) or True)


def flaky_browser(port, action, req=None, timeout=60):
    seq.append(BY_PORT[port])
    if len(seq) <= 2:
        return {"ok": False, "kind": "browser", "error": f"cannot attach to the browser on CDP port {port}"}
    return {"ok": True, "text": "fine", "images": [], "thread_id": "T-" + BY_PORT[port]}


M.run_tool = flaky_browser
M._LAST_USED.update({"chayagent": 1.0, "muse2": 2.0, "muse3": 3.0})
r = M.ask("q")
ok(r["text"] == "fine" and len(seq) == 3 and killed == seq[:2] and not alerts,
   "treo 2 lần → đóng phiên (giải phóng RAM) + mở lại + thử lại, lần 3 được, không báo", (seq, killed, alerts))
ok(len(set(seq)) == 3 and not M._BUSY, "mỗi lượt thử ưu tiên tài khoản khác; chỗ ngồi đã nhả", (seq, M._BUSY))
reset()
seq.clear()
killed.clear()
M.run_tool = lambda port, action, req=None, timeout=60: (seq.append(BY_PORT[port]) or
                                                        {"ok": False, "kind": "browser", "error": "cannot attach"})
try:
    M.ask("q")
    ok(False, "3 lần hỏng → MuseError")
except M.MuseError as e:
    ok(e.kind == "browser" and len(seq) == M.MUSE_ATTEMPTS and len(killed) == M.MUSE_ATTEMPTS - 1 and len(alerts) == 1
       and "3 times" in alerts[0][1] and alerts[0][0].startswith("browser:"),
       "3 lần hỏng → MuseError(browser) + MỘT dòng Telegram", (seq, killed, alerts))
reset()
alerts.clear()
killed.clear()
try:
    M.ask("q", launch=False)
except M.MuseError:
    pass
ok(not killed and not alerts, "launch=False (chỉ dò trạng thái) → không đóng phiên, không báo", (killed, alerts))
reset()
alerts.clear()
M.run_tool = lambda port, action, req=None, timeout=60: {"ok": False, "kind": "auth", "error": "not signed in"}
try:
    M.ask("q")
except M.MuseError:
    pass
ok(len(alerts) == 1 and alerts[0][0].startswith("auth:") and "not signed in" in alerts[0][1],
   "mọi tài khoản chưa đăng nhập → một dòng Telegram", alerts)
reset()
alerts.clear()
M.run_tool = lambda port, action, req=None, timeout=60: {"ok": False, "kind": "refused", "error": "policy"}
try:
    M.ask("q")
except M.MuseError:
    pass
ok(not alerts, "từ chối nội dung → không báo Telegram", alerts)
# _alert thật: rate-limit theo lý do; chưa cấu hình bot/chat → không gửi, không ném
import tubecli.extensions.codex.telegram as TG
sent = []
TG.notify_fire_and_forget = lambda token, chat, text: sent.append((chat, text))
M._telegram_target = lambda: ("tok", "123")
M._ALERTED.clear()
ok(real_alert("browser:x", "hello") is True and real_alert("browser:x", "again") is False and sent == [("123", "hello")],
   "Telegram thật: cùng lý do chỉ báo một lần mỗi ALERT_EVERY giây", sent)
M._telegram_target = lambda: ("", "")
ok(real_alert("other", "x") is False and len(sent) == 1, "chưa cấu hình bot/chat → không gửi, không ném", sent)

# ── K ─────────────────────────────────────────────────────────────────────────
print("K. nút Muse từ xa (giống 9Router)")
M.set_settings(profile="chayagent", extra_profiles=[], lanes=1, remotes=[{"base_url": "https://vps1.example.com/api/v1/muse/", "key": "k1", "seats": 2},
                                                                        {"url": "ftp://bad", "key": "x"}, {"base_url": "http://vps2:5295/api/v1/muse", "seats": 99}])
st = M.settings()
ok(st["remotes"] == [{"base_url": "https://vps1.example.com/api/v1/muse", "key": "k1", "seats": 2},
                     {"base_url": "http://vps2:5295/api/v1/muse", "key": "", "seats": M.MAX_REMOTE_SEATS}],
   "remotes: bỏ dấu / cuối, bỏ URL không http(s), kẹp số chỗ", st["remotes"])
# 9/10/2026 user dán tên miền trần «https://tungho2-23.tubecreate.com» → phải tự nối /api/v1/muse; thiếu scheme → https (IP → http)
ok([M._node_url(u) for u in ("https://tungho2-23.tubecreate.com", "tungho2-23.tubecreate.com/", "192.168.1.5:5295", "localhost:5295",
                             "http://vps:5295/api/v1/muse", "https://proxy.example.com/muse", "", "ftp://x", "   ")]
   == ["https://tungho2-23.tubecreate.com/api/v1/muse", "https://tungho2-23.tubecreate.com/api/v1/muse", "http://192.168.1.5:5295/api/v1/muse",
       "http://localhost:5295/api/v1/muse", "http://vps:5295/api/v1/muse", "https://proxy.example.com/muse", "", "", ""],
   "_node_url: tên miền trần → https + /api/v1/muse; IP/localhost → http; đường dẫn riêng giữ nguyên; rỗng/ftp → bỏ",
   [M._node_url(u) for u in ("https://tungho2-23.tubecreate.com", "192.168.1.5:5295", "ftp://x")])
try:
    M.set_settings(node_key="short")
    ok(False, "khoá node ngắn → ValueError")
except ValueError:
    ok(True, "khoá node < 16 ký tự → ValueError")
M.set_settings(node_key="abcdefghijklmnop-QRSTUV")
ok(M.node_key_ok("Bearer abcdefghijklmnop-QRSTUV") and M.node_key_ok("abcdefghijklmnop-QRSTUV") and not M.node_key_ok("Bearer nope")
   and not M.node_key_ok(None), "node_key_ok: Bearer / trần, sai → False")
M.set_settings(node_key="")
ok(not M.node_key_ok("Bearer abcdefghijklmnop-QRSTUV"), "không có khoá node → mọi bearer bị từ chối")
reset()
remote_calls = []


def fake_remote(node, prof, prompt, **kw):
    remote_calls.append((node["base_url"], prof, kw.get("want_videos"), kw.get("thread_id")))
    if kw.get("want_videos"):
        p = str(TMP / f"rv_{len(remote_calls)}.mp4")
        open(p, "wb").write(b"0" * 20000)
        return {"ok": True, "text": "", "images": [], "videos": [{"path": p, "duration": 10, "width": 1248, "height": 704}],
                "thread_id": f"{prof}:T-node", "profile": prof}
    return {"ok": True, "text": "remote hi", "images": [], "videos": [], "profile": prof}


M._ask_remote = fake_remote
M.run_tool = lambda port, action, req=None, timeout=60: {"ok": True, "text": "local", "images": [], "thread_id": "T-" + BY_PORT[port]}
M._LAST_USED.update({"chayagent": 9.0, "remote0": 1.0, "remote1": 2.0})
r = M.ask("q")
ok(r["text"] == "remote hi" and r["profile"] == "remote0" and remote_calls[0][0] == "https://vps1.example.com/api/v1/muse",
   "nút từ xa là tài khoản trong bể: lượt rơi vào remote0 → gọi HTTP (giả), không mở trình duyệt", (r, remote_calls))
reset()
remote_calls.clear()
M._LAST_USED.update({"chayagent": 1.0, "remote0": 9.0, "remote1": 9.0})
ok(M.ask("q")["text"] == "local", "lâu chưa dùng nhất → chayagent (cục bộ) vẫn được chọn", M._LAST_USED)
# chỗ ngồi: chayagent 1 + remote0 2 + remote1 6 = 9 lượt cùng lúc
reset()
busy_now = {"n": 0, "max": 0}


def slow_remote(node, prof, prompt, **kw):
    busy_now["n"] += 1
    busy_now["max"] = max(busy_now["max"], busy_now["n"])
    time.sleep(0.25)
    busy_now["n"] -= 1
    return {"ok": True, "text": "r", "images": [], "videos": [], "profile": prof}


def slow_local(port, action, req=None, timeout=60):
    busy_now["n"] += 1
    busy_now["max"] = max(busy_now["max"], busy_now["n"])
    time.sleep(0.25)
    busy_now["n"] -= 1
    return {"ok": True, "text": "l", "images": [], "thread_id": "T-" + BY_PORT[port]}


M._ask_remote = slow_remote
M.run_tool = slow_local
ths = [threading.Thread(target=lambda: M.ask("q")) for _ in range(9)]
t0 = time.time()
for t in ths:
    t.start()
for t in ths:
    t.join()
ok(busy_now["max"] == 9 and time.time() - t0 < 0.9 and not M._BUSY, "9 chỗ ngồi (1 cục bộ + 2 + 6 từ xa) chạy cùng lúc, chỗ ngồi đã nhả", (busy_now, round(time.time() - t0, 2)))
# clip từ xa: file về video_dir, chat phụ ghim vào nút
reset()
remote_calls.clear()
M._ask_remote = fake_remote
M.run_tool = lambda port, action, req=None, timeout=60: {"ok": False, "kind": "browser", "error": "local dead"}
M.reset_browser = lambda p: True
M._LAST_USED.update({"chayagent": 1.0, "remote0": 5.0, "remote1": 6.0})
v = M.generate_video_clip("clip", str(TMP / "vd_remote"), [], "16:9")
ok(v["path"].endswith(".mp4") and v["thread_id"] == "remote0:T-node" and any(c[1] == "remote0" for c in remote_calls),
   "cục bộ hỏng → clip làm ở nút từ xa, thread_id mang tên nút", (v, remote_calls))
remote_calls.clear()
v2 = M.generate_video_clip("next", str(TMP / "vd_remote"), [], "16:9", continue_from=True, thread_id="remote0:T-node")
ok(remote_calls and remote_calls[0][1] == "remote0" and remote_calls[0][3] == "remote0:T-node",
   "chuỗi clip ghim chat phụ → đúng nút remote0", remote_calls)
# nút không nối được → bỏ qua nút 10 phút, thử nút/tài khoản khác
reset()
M.run_tool = lambda port, action, req=None, timeout=60: {"ok": True, "text": "local ok", "images": [], "thread_id": "T-x"}


def dead_remote(node, prof, prompt, **kw):
    raise M.MuseError("browser", f"remote Muse node {node['base_url']} unreachable")


M._ask_remote = dead_remote
M._LAST_USED.update({"chayagent": 9.0, "remote0": 1.0, "remote1": 2.0})
r = M.ask("q")
ok(r["text"] == "local ok" and M._DOWN.get("remote0", 0) > time.time(), "nút chết → bỏ qua 10 phút, lượt sang tài khoản khác", (r.get("profile"), list(M._DOWN)))
# CHỈ nút từ xa, không hồ sơ ở máy này (9/10/2026 user: «người dùng chỉ remote mà không dùng browser local»)
reset()
remote_calls.clear()
M._ask_remote = fake_remote
M.run_tool = lambda port, action, req=None, timeout=60: (_ for _ in ()).throw(AssertionError("local browser must not be used"))
M.set_settings(profile="", extra_profiles=[], remotes=[{"base_url": "https://vps1.example.com", "key": "k1", "seats": 2}])
stt = M.status()
ok(stt["configured"] and stt["remote_only"] and stt["remote_nodes"] == 1 and stt["remote_seats"] == 2 and "remote" in stt["message"].lower(),
   "chỉ-remote: status() configured=True, remote_only, nêu số nút/chỗ", {k: stt[k] for k in ("configured", "remote_only", "remote_nodes", "remote_seats", "message")})
r = M.ask("q")
ok(r["text"] == "remote hi" and r["profile"] == "remote0" and remote_calls and remote_calls[0][1] == "remote0",
   "chỉ-remote: ask() chạy ở nút từ xa, không mở trình duyệt cục bộ", (r.get("profile"), remote_calls))
v = M.generate_video_clip("clip", str(TMP / "vd_remote_only"), [], "16:9")
ok(v["path"].endswith(".mp4") and v["thread_id"].startswith("remote0:"), "chỉ-remote: clip video qua nút", v.get("thread_id"))
M.set_settings(remotes=[])
try:
    M.ask("q")
    ok(False, "không hồ sơ, không nút → MuseError(config)")
except M.MuseError as e:
    ok(e.kind == "config" and "remote" in str(e).lower(), "không hồ sơ, không nút → MuseError(config) nhắc cả nút từ xa", str(e))
# test_remote(): thử một nút chưa lưu; status() pool có last_used cho hộp cài đặt
M._ask_remote = fake_remote
tr = M.test_remote("vps1.example.com", "k1")
ok(tr["ok"] and tr["base_url"] == "https://vps1.example.com/api/v1/muse" and tr["reply"] == "remote hi" and tr["seconds"] >= 0,
   "test_remote: tên miền trần → gọi nút, trả ok/reply/base_url chuẩn", tr)
M._ask_remote = dead_remote
tr2 = M.test_remote("https://vps1.example.com/api/v1/muse", "k1")
ok(not tr2["ok"] and tr2["kind"] == "browser" and "unreachable" in tr2["message"], "test_remote: nút chết → ok=False, kind=browser", tr2)
ok(not M.test_remote("", "k")["ok"] and M.test_remote("ftp://x", "k")["kind"] == "config", "test_remote: địa chỉ rỗng/ftp → config")
M.set_settings(profile="chayagent", remotes=[])
M.run_tool = lambda port, action, req=None, timeout=60: {"ok": True, "logged_in": True, "verified": True}
M._LAST_USED["chayagent"] = 1234.5
stp = M.status()
ok(stp["pool"] and stp["pool"][0]["profile"] == "chayagent" and stp["pool"][0].get("last_used") == 1234.5, "status(): mỗi hồ sơ trong bể có last_used", stp["pool"][:1])
ok(M.settings()["remotes"] == [], "xoá nút từ xa")

# ── L ─────────────────────────────────────────────────────────────────────────
print("L. người gác treo: bận > 15 phút không có lần thành công → đóng phiên (10/10/2026)")
reset()
resets, alerts = [], []
M.reset_browser = lambda p: (resets.append(p) or True)
_real_alert = M._alert
M._alert = lambda reason, text: (alerts.append(reason) or True)
now = time.time()
with M._POOL:
    M._BUSY.update({"muse2": "muse2", "muse3": "muse3", "chayagent": "chayagent", "remote0": "remote0"})
    M._BUSY_SINCE.update({"muse2": now - 1000, "muse3": now - 1000, "chayagent": now - 300, "remote0": now - 5000})
M._LAST_OK.update({"muse3": now - 120})          # muse3 vừa thành công 2 phút trước → không phải treo
hung = M._watch_once(now)
ok(hung == ["muse2"] and resets == ["muse2"] and alerts == ["hang:muse2"],
   "chỉ muse2 bị đóng phiên: bận 16 phút, không thành công; muse3 vừa OK; chayagent mới 5 phút; nút từ xa bỏ qua", (hung, resets, alerts))
ok(M._watch_once(now + 60) == [] and resets == ["muse2"], "một lượt chỉ bị đóng phiên MỘT lần (không giết lặp mỗi phút)", resets)
M._release("muse2")
ok("muse2" not in M._HUNG_RESET and "muse2" not in M._BUSY_SINCE, "nhả chỗ → xoá dấu treo, lượt sau được theo dõi lại")
with M._POOL:
    M._BUSY["muse2"] = "muse2"; M._BUSY_SINCE["muse2"] = now - 2000
M._LAST_OK["muse2"] = now - 1990
ok(M._watch_once(now) == ["muse2"], "thành công gần nhất cũng đã quá 15 phút → vẫn coi là treo", resets)
# status() có last_ok + busy_for
M.run_tool = lambda port, action, req=None, timeout=60: {"ok": True, "logged_in": True, "verified": True}
M.set_settings(profile="chayagent", extra_profiles=["muse2"], remotes=[])
stw = M.status()
row = {r["profile"]: r for r in stw["pool"]}
ok(row["muse2"].get("busy_for", 0) >= 1990 and row["muse2"].get("last_ok") and row["chayagent"].get("busy_for", 0) >= 290,
   "status(): mỗi hồ sơ có last_ok + busy_for", {k: (v.get("last_ok"), v.get("busy_for")) for k, v in row.items()})
# lượt thành công thật ghi _LAST_OK
reset()
M.run_tool = lambda port, action, req=None, timeout=60: {"ok": True, "text": "hi", "images": [], "thread_id": "T-x"}
t_before = time.time()
r = M.ask("q")
ok(M._LAST_OK.get(r["profile"], 0) >= t_before and not M._BUSY_SINCE, "ask() thành công → ghi lần thành công gần nhất, nhả chỗ", (r.get("profile"), M._LAST_OK))
M._alert = _real_alert

# ── M ─────────────────────────────────────────────────────────────────────────
print("M. chặn khu vực cho video → tránh tài khoản ấy, quay lại clip ở chỗ khác (10/10/2026)")
REGION_TXT = "Couldn't create the video — video generation isn't available in your region. I've added it to the retry queue."
reset()
M._NO_VIDEO.clear()
M.set_settings(profile="chayagent", extra_profiles=["muse2"], remotes=[])
calls_m = []


def region_tool(port, action, req=None, timeout=60, blocked=("chayagent",)):
    prof = BY_PORT[port]
    calls_m.append(prof)
    if (req or {}).get("want_videos") and prof in blocked:
        return {"ok": True, "text": REGION_TXT, "images": [], "videos": [], "thread_id": "T-" + prof}
    if (req or {}).get("want_videos"):
        p = str(TMP / f"mv_{len(calls_m)}.mp4")
        open(p, "wb").write(b"0" * 20000)
        return {"ok": True, "text": "", "images": [], "videos": [{"path": p}], "thread_id": "T-" + prof}
    return {"ok": True, "text": "hi", "images": [], "thread_id": "T-" + prof}


M.run_tool = region_tool
M._LAST_USED.update({"chayagent": 1.0, "muse2": 9.0})
v = M.generate_video_clip("clip", str(TMP / "vd_region"), [], "16:9")
ok(v["path"].endswith(".mp4") and calls_m == ["chayagent", "muse2"] and M._NO_VIDEO.get("chayagent", 0) > time.time(),
   "chayagent báo chặn khu vực → clip quay lại ở muse2, chayagent bị tránh cho video", (calls_m, M._NO_VIDEO))
calls_m.clear()
M._LAST_USED.update({"chayagent": 1.0, "muse2": 9.0})
M.generate_video_clip("clip 2", str(TMP / "vd_region"), [], "16:9")
ok(calls_m == ["muse2"], "clip sau đi thẳng muse2 dù chayagent lâu chưa dùng hơn", calls_m)
calls_m.clear()
M._LAST_USED.update({"chayagent": 1.0, "muse2": 9.0})
ok(M.ask("q")["text"] == "hi" and calls_m == ["chayagent"], "chữ / ảnh vẫn dùng tài khoản bị chặn video", calls_m)
M.run_tool = lambda port, action, req=None, timeout=60: {"ok": True, "logged_in": True, "verified": True}
row = {r["profile"]: r for r in M.status()["pool"]}
ok(row["chayagent"].get("video_blocked") is True and row["muse2"].get("video_blocked") is False,
   "status(): dòng hồ sơ có video_blocked", {k: v.get("video_blocked") for k, v in row.items()})
# mọi chỗ đều bị chặn → báo lỗi ngay sau lượt thứ hai, không quay vòng
reset()
M._NO_VIDEO.clear()
calls_m.clear()
M.run_tool = lambda port, action, req=None, timeout=60: region_tool(port, action, req, timeout, blocked=("chayagent", "muse2"))
try:
    M.generate_video_clip("clip 3", str(TMP / "vd_region"), [], "16:9")
    ok(False, "mọi tài khoản bị chặn → MuseError")
except M.MuseError as e:
    ok("region" in str(e) and sorted(calls_m) == ["chayagent", "muse2"], "mọi tài khoản bị chặn → MuseError sau 2 lượt", (calls_m, e))
# nút từ xa báo chặn (lỗi của nút, không phải chữ) → quay lại ở hồ sơ cục bộ
reset()
M._NO_VIDEO.clear()
calls_m.clear()
M.set_settings(profile="chayagent", extra_profiles=[], remotes=[{"base_url": "https://vps1.example.com", "key": "k1", "seats": 1}])


def region_remote(node, prof, prompt, **kw):
    calls_m.append(prof)
    raise M.MuseError("error", "Muse did not make a video: " + REGION_TXT)


M._ask_remote = region_remote
M.run_tool = lambda port, action, req=None, timeout=60: region_tool(port, action, req, timeout, blocked=())
M._LAST_USED.update({"chayagent": 9.0, "remote0": 1.0})
v = M.generate_video_clip("clip 4", str(TMP / "vd_region"), [], "16:9")
ok(v["path"].endswith(".mp4") and calls_m == ["remote0", "chayagent"] and M._NO_VIDEO.get("remote0", 0) > time.time(),
   "nút từ xa bị chặn khu vực → clip quay ở chayagent", (calls_m, M._NO_VIDEO))
M._NO_VIDEO.clear()
M.set_settings(remotes=[])

print()
print(f"{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
