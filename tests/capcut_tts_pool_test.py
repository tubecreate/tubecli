# CapCut TTS: xoay tài khoản, giữ nhịp, cho nghỉ tài khoản đang bị chặn.
#
# Chạy:  python tests/capcut_tts_pool_test.py     (exit 0 = pass)
#        In "SKIP" và exit 0 khi máy không có extension capcut_tts.
#
# VÌ SAO CÓ FILE NÀY
#   13/9/2026: gửi liên tục là tài khoản CapCut bị khoá. Luồng cũ dồn CẢ MỘT LƯỢT
#   vào đúng một tài khoản và không nghỉ giây nào giữa hai lượt; hỏng thì còn tự
#   chia nhỏ rồi thử lại ngay trên chính tài khoản đang bị chặn.
#
#   Phía Node gói mọi lỗi tổng hợp thành "502 Failed to synthesize audio", nên án
#   nghỉ dựa vào HÀNH VI (hỏng liên tiếp), không đọc được lý do từ câu lỗi. Test giữ
#   cả chuyện ngược lại: lỗi KHÔNG phải của tài khoản (audio rỗng, văn bản 4xx, Node
#   tắt) thì không được phạt — phạt oan là tự cho nghỉ cả bể.
import asyncio
import os
import sys
import tempfile
import time as _time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

EXT = ROOT / "data" / "extensions_external" / "capcut_tts"
if not (EXT / "capcut_pool.py").exists():
    print(f"SKIP: không có capcut_pool tại {EXT}")
    sys.exit(0)
sys.path.insert(0, str(EXT))

TMP = tempfile.mkdtemp(prefix="capcut_pool_")
import tubecli.config as cfg  # noqa: E402
cfg.DATA_DIR = Path(TMP)
cfg.GLOBAL_SETTINGS_FILE = Path(TMP) / "global_settings.json"
cfg.EXTENSIONS_DATA_DIR = Path(TMP) / "extensions_data"

import capcut_pool as CP  # noqa: E402

failures, checks = [], 0


def check(label, ok, detail=""):
    global checks
    checks += 1
    print(("  ok   " if ok else "  FAIL ") + label + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(label)


class Clock:
    """Đồng hồ giả: sleep() chỉ đẩy giờ, test chạy tức thì mà vẫn đo được nhịp."""
    def __init__(self):
        self.t = 1_000_000.0
        self.slept = 0.0

    def now(self):
        return self.t

    def sleep(self, dt):
        self.t += dt
        self.slept += dt


class Store:
    def __init__(self, accs):
        self.accs = {a["email"]: {"enabled": True, "region": "VN", "rest_until": 0, "strikes": 0, **a}
                     for a in accs}
        self.writes = 0

    def list_masked(self):
        return [dict(v) for v in self.accs.values()]

    def set_rest(self, email, until, strikes):
        self.writes += 1
        if email in self.accs:
            self.accs[email]["rest_until"] = until
            self.accs[email]["strikes"] = strikes


class ZeroRng:
    def uniform(self, a, b):
        return 0.0


def make(accs, **settings):
    st = Store(accs)
    ck = Clock()
    base = {"min_gap": 4, "hourly_cap": 0, "rotate": True}
    base.update(settings)
    p = CP.AccountPool(st, settings=lambda: base,
                       region_of=lambda e: st.accs.get(e, {}).get("region", ""),
                       clock=ck.now, sleep=ck.sleep, rng=ZeroRng())
    return p, st, ck, base


A, B, C, U = "a@x.com", "b@x.com", "c@x.com", "us@x.com"

print("== A. xoay vòng trong cùng vùng")
p, st, ck, _ = make([{"email": A}, {"email": B}, {"email": C}, {"email": U, "region": "US"}])
seq = []
for _ in range(6):
    e = p.acquire(A)
    seq.append(e)
    p.release(e, ok=True)
check("A1 ba tài khoản VN chia đều lượt", sorted(set(seq)) == [A, B, C], seq)
check("A2 không bao giờ sang tài khoản khác vùng", U not in seq,
      "giọng Việt không có trên tài khoản US ⇒ đọc hỏng")
check("A3 không dồn liên tiếp vào một tài khoản", all(seq[i] != seq[i + 1] for i in range(len(seq) - 1)), seq)

print("== B. giữ nhịp trên MỘT tài khoản")
p, st, ck, _ = make([{"email": A}], min_gap=4)
e1 = p.acquire(A)
p.release(e1, ok=True)
t0 = ck.t
e2 = p.acquire(A)
check("B1 lượt thứ hai phải chờ đủ khoảng nghỉ", ck.t - t0 >= 4 - 1e-9, f"chờ {ck.t - t0:.2f}s")
p.release(e2, ok=True)
p2, st2, ck2, _ = make([{"email": A}, {"email": B}], min_gap=4)
x = p2.acquire(A); p2.release(x, ok=True)
t0 = ck2.t
y = p2.acquire(A)
check("B2 có tài khoản rảnh thì KHÔNG phải chờ", ck2.t - t0 < 1e-9 and y != x, f"{x}->{y} chờ {ck2.t - t0}")

print("== C. mỗi tài khoản một lượt đang chạy")
p, st, ck, _ = make([{"email": A}, {"email": B}], min_gap=0)
x = p.acquire(A)
y = p.acquire(A)
check("C1 lượt thứ hai (song song) sang tài khoản khác", x != y, f"{x} {y}")

print("== D. án nghỉ theo lỗi liên tiếp")
p, st, ck, _ = make([{"email": A}, {"email": B}], min_gap=0)
r1 = p.release(p.acquire(A), ok=False, error="Failed to synthesize audio")
check("D1 hỏng lần 1: không phạt, chỉ xoay", r1 == 0 and st.accs[A]["strikes"] + st.accs[B]["strikes"] == 1)
# dồn cho A hỏng lần 2
st.accs[B]["enabled"] = False
p.release(p.acquire(A), ok=False, error="Failed to synthesize audio")
check("D2 hỏng lần 2 liền: nghỉ 10 phút", 0 < st.accs[A]["rest_until"] - ck.t <= 600 + 1e-6,
      st.accs[A])
ck.t = st.accs[A]["rest_until"] + 1
p.release(p.acquire(A), ok=False, error="Failed to synthesize audio")
check("D3 hỏng lần 3 liền: nghỉ 30 phút", abs(st.accs[A]["rest_until"] - ck.t - 1800) < 1, st.accs[A])
ck.t = st.accs[A]["rest_until"] + 1
p.release(p.acquire(A), ok=True)
check("D4 đọc được là xoá án", st.accs[A]["strikes"] == 0 and st.accs[A]["rest_until"] == 0, st.accs[A])
p.release(p.acquire(A), ok=False, error="CapCut login is backing off after a recent failure. Retry in 300s")
check("D5 dấu hiệu bị chặn rõ ràng: nghỉ 1 giờ ngay", abs(st.accs[A]["rest_until"] - ck.t - 3600) < 1, st.accs[A])

print("== E. lỗi KHÔNG phải của tài khoản thì không phạt")
p, st, ck, _ = make([{"email": A}], min_gap=0)
for _ in range(5):
    p.release(p.acquire(A), ok=False, error="CapCut trả audio rỗng (12 byte)", strike=False)
check("E1 audio rỗng 5 lần: không án", st.accs[A]["strikes"] == 0 and st.accs[A]["rest_until"] == 0, st.accs[A])

print("== F. hết tài khoản rảnh thì nói giờ, không treo")
p, st, ck, _ = make([{"email": A}, {"email": B}], min_gap=0)
st.accs[A]["rest_until"] = ck.t + 3600
st.accs[B]["rest_until"] = ck.t + 1800
t0 = ck.t
try:
    p.acquire(A, max_wait=90)
    check("F1 ném PoolExhausted", False, "không ném")
except CP.PoolExhausted as ex:
    check("F1 ném PoolExhausted", True)
    check("F2 câu lỗi nói giờ sớm nhất", _time.strftime("%H:%M", _time.localtime(t0 + 1800)) in str(ex), str(ex))
    check("F3 không ngồi chờ khi biết chắc quá hạn", ck.t - t0 < 1e-9, f"chờ {ck.t - t0}")
st.accs[B]["rest_until"] = ck.t + 30
e = p.acquire(A, max_wait=90)
check("F4 án ngắn hơn giới hạn chờ thì chờ rồi đi", e == B and ck.t - t0 >= 30 - 1e-6, f"{e} {ck.t - t0}")

print("== G. trần lượt mỗi giờ")
p, st, ck, _ = make([{"email": A}], min_gap=0, hourly_cap=3)
for _ in range(3):
    p.release(p.acquire(A), ok=True)
try:
    p.acquire(A, max_wait=60)
    check("G1 lượt thứ 4 trong giờ bị chặn", False)
except CP.PoolExhausted:
    check("G1 lượt thứ 4 trong giờ bị chặn", True)
ck.t += 3601
check("G2 qua một giờ là đi tiếp", p.acquire(A, max_wait=1) == A)

print("== H. tắt xoay / email lạ / tài khoản đã tắt")
p, st, ck, base = make([{"email": A}, {"email": B}], min_gap=0, rotate=False)
seq = []
for _ in range(3):
    e = p.acquire(A); seq.append(e); p.release(e, ok=True)
check("H1 tắt xoay: chỉ dùng tài khoản được chọn", set(seq) == {A}, seq)
check("H2 nút Thử/Nghe thử ép rotate=False dù cài đặt bật",
      (base.update(rotate=True), p.acquire(B, rotate=False))[1] == B)
p, st, ck, _ = make([{"email": A}], min_gap=0)
check("H3 email không có trong kho: dùng đúng nó, không đoán", p.acquire("la@x.com") == "la@x.com")
p, st, ck, _ = make([{"email": A, "enabled": False}, {"email": B}], min_gap=0)
check("H4 tài khoản được chọn đang TẮT: xoay sang cái còn bật cùng vùng", p.acquire(A) == B)

print("== I. xoá án bằng tay + trạng thái cho giao diện")
p, st, ck, _ = make([{"email": A}], min_gap=4)
st.accs[A].update(rest_until=ck.t + 999, strikes=3)
s0 = p.status()[A]
check("I1 status nói đang nghỉ tới lúc nào", s0["rest_until"] > ck.t and s0["strikes"] == 3, s0)
p.clear_rest(A)
check("I2 «Dùng lại ngay» xoá án", st.accs[A]["rest_until"] == 0 and st.accs[A]["strikes"] == 0)
check("I3 và đi được ngay", p.acquire(A, max_wait=0) == A)

# ── J. nối vào routes: lượt dài rải qua các tài khoản, và cạn bể thì dừng gọn ──
print("== J. routes đi qua bể")
import capcut_routes as R  # noqa: E402
cfg.set_global_setting("capcut_min_gap", 0)
cfg.set_global_setting("capcut_hourly_cap", 0)


class Resp:
    def __init__(self, code=200, content=b"\xff\xfb" + b"\x00" * 2000, ctype="audio/mpeg", text=""):
        self.status_code, self.content, self.text = code, content, text
        self.headers = {"content-type": ctype}


class RStore(Store):
    def get_credentials(self, email):
        return {"email": email, "password": "x"} if email in self.accs else None

    def record_use(self, email, error=""):
        self.accs.get(email, {})["last_error"] = error


rs = RStore([{"email": A}, {"email": B}])
R.account_store = rs
R.pool = CP.AccountPool(rs, settings=lambda: R.pool_settings(),
                        region_of=lambda e: rs.accs.get(e, {}).get("region", ""))
R._ensure_node = lambda: "http://x"
seen = []


def post_ok(url, headers=None, json=None, timeout=180):
    seen.append(headers.get("x-capcut-email"))
    return Resp()


R.requests.post = post_ok
R._account_headers = lambda email: {"x-capcut-email": email}
R._concat_mp3 = lambda parts, out: False
text = " ".join(f"Câu thứ {n} kể một đoạn chuyện dài vừa đủ để cắt." for n in range(1, 400))
req = R.SynthesizeRequest(email=A, text=text)
st0 = asyncio.run(R.synthesize_chunks(req))
end = _time.time() + 20
while _time.time() < end:
    stt = asyncio.run(R.synthesize_chunks_status(st0["task_id"]))
    if stt["status"] != "running":
        break
    _time.sleep(0.05)
check("J1 bài nhiều đoạn đọc xong", stt["status"] == "completed" and stt["failed"] == 0, stt.get("error"))
check("J2 các đoạn rải qua CẢ HAI tài khoản", set(seen) == {A, B}, seen)
check("J3 mỗi đoạn ghi tài khoản đã đọc nó", all(r.get("account") in (A, B) for r in stt["chunks"]))

# Cả hai tài khoản đang nghỉ lâu: lượt dừng NGAY, không chia nhỏ, không đốt request.
rs.accs[A]["rest_until"] = _time.time() + 7200
rs.accs[B]["rest_until"] = _time.time() + 7200
seen.clear()
st1 = asyncio.run(R.synthesize_chunks(R.SynthesizeRequest(email=A, text=text)))
end = _time.time() + 20
while _time.time() < end:
    stt = asyncio.run(R.synthesize_chunks_status(st1["task_id"]))
    if stt["status"] != "running":
        break
    _time.sleep(0.05)
check("J4 bể cạn: không gửi request nào", seen == [], seen)
check("J5 mọi đoạn mang lý do có giờ", all("nghỉ" in (r.get("error") or "") for r in stt["chunks"]),
      [r.get("error") for r in stt["chunks"]][:2])
check("J6 lượt kết thúc, không treo", stt["status"] == "completed")


def _code(coro):
    try:
        asyncio.run(coro)
    except R.HTTPException as e:
        return e.status_code
    return 0


check("J7 /synthesize trả 503 kèm lý do khi bể cạn",
      _code(R.synthesize(R.SynthesizeRequest(email=A, text="Xin chào các bạn."))) == 503)
check("J8 /synthesize có mốc từ cũng 503, không treo event loop",
      _code(R.synthesize(R.SynthesizeRequest(email=A, text="Xin chào các bạn.", timestamps=True))) == 503)

# Hỏng 5xx liên tiếp trên A → A nghỉ, B gánh tiếp.
rs.accs[A].update(rest_until=0, strikes=0)
rs.accs[B].update(rest_until=0, strikes=0)
R.pool = CP.AccountPool(rs, settings=lambda: R.pool_settings(),
                        region_of=lambda e: rs.accs.get(e, {}).get("region", ""))
seen.clear()


def a_locked(url, headers=None, json=None, timeout=180):
    who = headers.get("x-capcut-email")
    seen.append(who)
    if who == A:
        return Resp(code=502, content=b"", ctype="application/json",
                    text='{"code":"BAD_GATEWAY","message":"Failed to synthesize audio"}')
    return Resp()


R.requests.post = a_locked
st2 = asyncio.run(R.synthesize_chunks(R.SynthesizeRequest(email=A, text=text)))
end = _time.time() + 20
while _time.time() < end:
    stt = asyncio.run(R.synthesize_chunks_status(st2["task_id"]))
    if stt["status"] != "running":
        break
    _time.sleep(0.05)
check("J9 tài khoản bị chặn được cho nghỉ", rs.accs[A]["rest_until"] > _time.time(), rs.accs[A])
check("J10 tài khoản kia gánh hết, bài vẫn đủ", stt["failed"] == 0, stt.get("chunks", [{}])[0])
check("J11 A bị gọi ÍT lần rồi thôi (không đấm tiếp)", seen.count(A) <= 3, f"A bị gọi {seen.count(A)} lần")

print("=" * 70)
if failures:
    print(f"{len(failures)} FAIL / {checks}")
    sys.exit(1)
print(f"{checks}/{checks} PASS")
