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
  I. lượt chữ treo hết hạn → hỏi lại MỘT lần trong chat mới (ảnh / chuỗi clip thì không)
  J. trình duyệt treo → đóng phiên (giải phóng RAM), mở lại, thử lại; 3 lần hỏng / chưa đăng nhập → một dòng Telegram

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
M._save_slot("chayagent", {"profile": "chayagent", "thread": "T-hang", "turns": 3})
M._LAST_USED.update({"chayagent": 1.0, "muse2": 2.0, "muse3": 3.0})
r = M.ask("describe scenes 1-12")
ok(r["text"] == "scenes" and len(hung) == 2 and hung[1][1] == "new" and hung[1][0] != "chayagent",
   "chữ treo → hỏi lại MỘT lần trong chat mới ở tài khoản khác", hung)
ok(not M._DOWN and not M._BUSY, "treo không làm tài khoản bị bỏ qua, chỗ ngồi đã nhả", (M._DOWN, M._BUSY))
M.run_tool = lambda port, action, req=None, timeout=60: (hung.append(1) or
                                                        {"ok": False, "kind": "timeout", "error": "slow"})
reset()
hung.clear()
try:
    M.ask("q")
    ok(False, "treo cả hai lần → MuseError")
except M.MuseError as e:
    ok(e.kind == "timeout" and len(hung) == 2, "treo cả hai lần → MuseError(timeout), chỉ thử lại một lần", hung)
reset()
hung.clear()
try:
    M.ask("draw", want_images=True)
except M.MuseError:
    pass
try:
    M.ask("clip", thread_id="CH-x")
except M.MuseError:
    pass
ok(len(hung) == 2, "ảnh / chat riêng (chuỗi clip) treo → KHÔNG tự hỏi lại", hung)

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

print()
print(f"{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
