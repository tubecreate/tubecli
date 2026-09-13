# CapCut TTS: bể tài khoản KHÔNG được cho nghỉ oan.
#
# Chạy:  python tests/capcut_tts_false_rest_test.py     (exit 0 = pass)
#        In "SKIP" và exit 0 khi máy không có extension capcut_tts.
#
# VÌ SAO CÓ FILE NÀY
#   13/9/2026: dây chuyền dựng video 127 shot, giọng 11labs (Alejandro Durán), nhận
#   HTTP 503 "Tất cả tài khoản CapCut đang nghỉ…" cho MỌI shot — trong khi tài khoản
#   không hề bị CapCut giới hạn. Đo trên máy thật: giọng 11labs xin mốc từ thì Node
#   trả HTTP 502 "Word timestamps are only available for sami voices". Bể coi mọi
#   5xx là lỗi tài khoản nên tính án; chỗ nhớ giọng không-mốc lại chỉ bắt mã 400.
#   Mỗi shot: thử mốc (án) → đọc thường (xoá án MỘT tài khoản) → án dồn nhanh hơn
#   xoá → cả hai tài khoản "nghỉ".
#   Đường xin mốc dùng WebSocket SAMI bằng token không cần đăng nhập: nó chưa bao
#   giờ tiêu lượt của tài khoản nào.
import asyncio
import io
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

TMP = tempfile.mkdtemp(prefix="capcut_false_rest_")
import tubecli.config as cfg  # noqa: E402
cfg.DATA_DIR = Path(TMP)
cfg.GLOBAL_SETTINGS_FILE = Path(TMP) / "global_settings.json"
cfg.EXTENSIONS_DATA_DIR = Path(TMP) / "extensions_data"
cfg.set_global_setting("capcut_min_gap", 0)
cfg.set_global_setting("capcut_hourly_cap", 0)

import capcut_pool as CP     # noqa: E402
import capcut_routes as R    # noqa: E402

failures, checks = [], 0


def check(label, ok, detail=""):
    global checks
    checks += 1
    print(("  ok   " if ok else "  FAIL ") + label + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(label)


A, B = "a@x.com", "b@x.com"


class Store:
    def __init__(self, emails):
        self.accs = {e: {"email": e, "enabled": True, "region": "VN", "rest_until": 0, "strikes": 0,
                         "last_error": ""} for e in emails}

    def list_masked(self):
        return [dict(v) for v in self.accs.values()]

    def set_rest(self, email, until, strikes):
        if email in self.accs:
            self.accs[email]["rest_until"] = until
            self.accs[email]["strikes"] = strikes

    def get_credentials(self, email):
        return {"email": email, "password": "x"} if email in self.accs else None

    def record_use(self, email, error=""):
        if email in self.accs:
            self.accs[email]["last_error"] = error


class Resp:
    def __init__(self, code=200, content=b"\xff\xf3" + b"\x00" * 3000, ctype="audio/mpeg", text=""):
        self.status_code, self.content, self.text = code, content, text
        self.headers = {"content-type": ctype}

    def json(self):
        import json
        return json.loads(self.text or "{}")


SAMI_502 = Resp(502, b"", "application/json",
                '{"code":"BAD_GATEWAY","message":"Word timestamps are only available for sami voices. '
                'Speaker \\"sKgg4MPUDBy69X7iv3fA\\" runs on 11labs"}')
GENERIC_502 = Resp(502, b"", "application/json", '{"code":"BAD_GATEWAY","message":"Failed to synthesize audio"}')


def setup(emails):
    st = Store(emails)
    R.account_store = st
    R.pool = CP.AccountPool(st, settings=lambda: R.pool_settings(),
                            region_of=lambda e: st.accs.get(e, {}).get("region", ""))
    R._ensure_node = lambda: "http://x"
    R._account_headers = lambda email: {"x-capcut-email": email}
    R._concat_mp3 = lambda parts, out: False
    R._media_seconds = lambda path: 0.0
    R._NO_MARKS_SPEAKERS.clear()
    return st


def now():
    return _time.time()


SHOT = ("En lo alto de la montaña vivía un anciano. Los vecinos decían que el muchacho se había marchado. "
        "Pero él nunca perdió la esperanza.")

print("== A. ĐÚNG ca 13/9: 30 shot giọng 11labs qua đường dựng video (timestamps)")
st = setup([A, B])
calls = []


def eleven(url, headers=None, json=None, timeout=180):
    calls.append(("marks" if json.get("timestamps") else "plain", headers.get("x-capcut-email")))
    return SAMI_502 if json.get("timestamps") else Resp()


R.requests.post = eleven
codes = []
for _ in range(30):
    try:
        res = asyncio.run(R.synthesize(R.SynthesizeRequest(email=A, text=SHOT, speaker="sKgg4MPUDBy69X7iv3fA",
                                                           timestamps=True)))
        codes.append(200)
    except R.HTTPException as e:
        codes.append(e.status_code)
check("A1 cả 30 shot đều ra audio — không một 503 nào", codes == [200] * 30, codes[:10])
check("A2 không tài khoản nào bị cho nghỉ", all(a["rest_until"] == 0 and a["strikes"] == 0 for a in st.accs.values()),
      st.accs)
marks = [c for c in calls if c[0] == "marks"]
check("A3 chỉ thử xin mốc ĐÚNG MỘT lần rồi nhớ giọng", len(marks) == 1, len(marks))
check("A4 nhớ giọng 11labs", "sKgg4MPUDBy69X7iv3fA" in R._NO_MARKS_SPEAKERS)
check("A5 đọc thường vẫn rải qua cả hai tài khoản", {c[1] for c in calls if c[0] == "plain"} == {A, B},
      {c[1] for c in calls if c[0] == "plain"})

print("== B. xin mốc KHÔNG đi qua bể tài khoản")
st = setup([A, B])
acq = []
orig_acquire = R.pool.acquire
R.pool.acquire = lambda *a, **k: (acq.append(1), orig_acquire(*a, **k))[1]
R.requests.post = lambda url, headers=None, json=None, timeout=180: SAMI_502
call = R._pooled_call("http://x", A)
for _ in range(10):
    call({"text": "hola", "timestamps": True})
check("B1 10 lượt xin mốc không mượn tài khoản nào", acq == [], len(acq))
check("B2 và không tính án", all(a["strikes"] == 0 for a in st.accs.values()), st.accs)

print("== C. 5xx chung chung: đối chứng bằng tài khoản khác")
st = setup([A, B])
seen = []


def a_broken(url, headers=None, json=None, timeout=180):
    who = headers.get("x-capcut-email")
    seen.append(who)
    return GENERIC_502 if who == A else Resp()


R.requests.post = a_broken
call = R._pooled_call("http://x", A)
r = call({"text": "hola"})
check("C1 lượt đó vẫn ra audio nhờ tài khoản khác", r.status_code == 200 and seen == [A, B], seen)
check("C2 tài khoản hỏng (B đọc được) bị tính án", st.accs[A]["strikes"] == 1, st.accs[A])
check("C3 tài khoản đọc được sạch án", st.accs[B]["strikes"] == 0)

st = setup([A, B])
R.requests.post = lambda url, headers=None, json=None, timeout=180: GENERIC_502
call = R._pooled_call("http://x", A)
for _ in range(6):
    call({"text": "đoạn này giọng không đọc được"})
check("C4 cả hai cùng hỏng đúng yêu cầu đó → lỗi của yêu cầu, KHÔNG ai bị án",
      all(a["strikes"] == 0 and a["rest_until"] == 0 for a in st.accs.values()), st.accs)

st = setup([A])
R.requests.post = lambda url, headers=None, json=None, timeout=180: GENERIC_502
call = R._pooled_call("http://x", A)
for _ in range(6):
    call({"text": "hola"})
check("C5 chỉ MỘT tài khoản: 5xx chung không đủ bằng chứng → không án",
      st.accs[A]["strikes"] == 0 and st.accs[A]["rest_until"] == 0, st.accs[A])

print("== D. dấu hiệu bị chặn rõ ràng vẫn phạt ngay")
st = setup([A, B])
LOCKED = Resp(502, b"", "application/json",
              '{"message":"CapCut login is backing off after a recent failure. Retry in 300s"}')


def a_locked(url, headers=None, json=None, timeout=180):
    return LOCKED if headers.get("x-capcut-email") == A else Resp()


R.requests.post = a_locked
r = R._pooled_call("http://x", A)({"text": "hola"})
check("D1 tài khoản bị chặn nghỉ 1 giờ", st.accs[A]["rest_until"] - now() > 3000, st.accs[A])
check("D2 lượt đó vẫn ra audio nhờ tài khoản khác", r.status_code == 200)

print("== E. xoá MỘT LẦN án oan đã lưu từ bản cũ")
st = setup([A, B])
st.accs[A].update(rest_until=now() + 1800, strikes=3)
st.accs[B].update(rest_until=now() + 600, strikes=2)
flag = R._output_dir().parent / "pool_false_rests_cleared.flag"
if flag.exists():
    flag.unlink()
n = R.reset_false_rests_once()
check("E1 xoá án của cả hai tài khoản", n == 2 and all(a["rest_until"] == 0 and a["strikes"] == 0
                                                       for a in st.accs.values()), (n, st.accs))
st.accs[A].update(rest_until=now() + 1800, strikes=3)
check("E2 chỉ một lần: án MỚI sau đó không bị xoá nữa", R.reset_false_rests_once() == 0
      and st.accs[A]["strikes"] == 3)
ext_src = io.open(EXT / "extension.py", encoding="utf-8").read()
check("E3 extension gọi nó khi bật", "reset_false_rests_once()" in ext_src)

print("== F. dây chuyền dựng video dừng NGAY khi CapCut trả 503 cho cả máy")
from tubecli.extensions.content_video import pipeline as PL  # noqa: E402
check("F1 nhận ra 503 của CapCut TTS",
      PL._capcut_machine_wide(RuntimeError('/api/v1/capcut-tts/synthesize → HTTP 503: {"detail":"Tất cả tài khoản..."}')))
check("F2 không nhầm lỗi của MỘT shot", not PL._capcut_machine_wide(RuntimeError("/api/v1/capcut-tts/synthesize → HTTP 502: x")))
src = io.open(ROOT / "tubecli" / "extensions" / "content_video" / "pipeline.py", encoding="utf-8").read()
check("F3 vòng đọc + vòng thử lại đều dừng khi gặp nó", src.count("if _capcut_machine_wide(e):") == 2)

print("=" * 70)
if failures:
    print(f"{len(failures)} FAIL / {checks}")
    sys.exit(1)
print(f"{checks}/{checks} PASS")
