# CapCut TTS: đọc theo ĐỢT — nhiều đoạn, MỘT lượt gọi CapCut, audio riêng từng đoạn.
#
# Chạy:  python tests/capcut_tts_batch_test.py     (exit 0 = pass)
#        In "SKIP" và exit 0 khi máy không có extension capcut_tts.
#
# VÌ SAO CÓ FILE NÀY
#   13/9/2026 người dùng: bước giọng đọc của dây chuyền dựng video quá chậm — 127 shot
#   là 127 lượt riêng (mượn tài khoản, ký + gọi CapCut, tải file). API multi_platform
#   vốn nhận MẢNG văn bản và trả audio RIÊNG từng đoạn. Đo thật giọng 11labs: 16 đoạn
#   một lượt 23 giây, gọi từng đoạn ~93 giây.
#   Phải giữ: đợt vẫn đi qua bể tài khoản (MỘT lượt mượn cho cả đợt), chỉ số phần tử
#   khớp đúng văn bản gửi lên, phần tử hỏng không làm mất cả đợt, server Node cũ (chưa
#   có route) thì báo 501 để bên gọi đọc từng đoạn thay vì coi là tài khoản hỏng.
import asyncio
import base64
import json as _json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

EXT = ROOT / "data" / "extensions_external" / "capcut_tts"
if not (EXT / "capcut_routes.py").exists():
    print(f"SKIP: không có extension capcut_tts tại {EXT}")
    sys.exit(0)
sys.path.insert(0, str(EXT))

TMP = tempfile.mkdtemp(prefix="capcut_batch_")
import tubecli.config as cfg  # noqa: E402
cfg.DATA_DIR = Path(TMP)
# Trỏ cài đặt chung + dữ liệu extension sang thư mục tạm TRƯỚC khi import routes, kẻo
# test ghi đè cài đặt / Lịch sử thật của người dùng.
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
        return _json.loads(self.text or "{}")


def setup(emails):
    st = Store(emails)
    R.account_store = st
    R.pool = CP.AccountPool(st, settings=lambda: R.pool_settings(),
                            region_of=lambda e: st.accs.get(e, {}).get("region", ""))
    R._ensure_node = lambda: "http://x"
    R._account_headers = lambda email: {"x-capcut-email": email}
    return st


def node_ok(texts, broken=()):
    """Phản hồi /v2/synthesize/batch giả. Audio mang chữ của đoạn để kiểm vào đúng chỗ."""
    items = []
    for i, t in enumerate(texts):
        audio = b"" if i in broken else (b"ID3" + t.encode("utf-8") + b"\x00" * 1200)
        items.append({"index": i, "contentType": "audio/mpeg", "byteLength": len(audio),
                      "audio": base64.b64encode(audio).decode(),
                      "meta": {"material.duration": 5929000,
                               "material.audio_meta_data": {"utterance_list": [
                                   {"text": t, "start_time": 0, "end_time": 5929000,
                                    "Caption": "", "Subtitle": ""}]}}})
    return Resp(200, b"", "application/json",
                _json.dumps({"materials": len(texts), "items": items, "timings": {"ttsMs": 9631, "downloadMs": 2612}}))


def run(req):
    return asyncio.run(R.synthesize_batch(req))


print("== A. timeout theo độ dài đợt")
check("A1 sàn 180 giây", R.batch_timeout(0) == 180, R.batch_timeout(0))
check("A2 đợt dài hơn thì chờ lâu hơn", R.batch_timeout(8000) > R.batch_timeout(1600) >= 180)
check("A3 trần 900 giây", R.batch_timeout(10 ** 7) == 900)

print("== B. đọc phản hồi của Node")
obj = _json.loads(node_ok(["uno dos", "tres cuatro"], broken={1}).text)
obj["items"].append({"index": 5, "audio": "", "byteLength": 0})      # chỉ số ngoài danh sách: bỏ qua
got = R.batch_items(obj, 3)
check("B1 đúng số phần tử theo số đoạn gửi lên", [g["index"] for g in got] == [0, 1, 2], got)
check("B2 đoạn có audio: ok + base64 nguyên vẹn",
      got[0]["ok"] and base64.b64decode(got[0]["audio_b64"]).startswith(b"ID3uno dos"), got[0])
check("B3 thời lượng lấy từ material.duration (µs → giây)", got[0]["duration"] == 5.929, got[0]["duration"])
check("B4 utterance_list đổi ra giây", got[0]["utterances"] == [{"text": "uno dos", "start": 0.0, "end": 5.929}],
      got[0]["utterances"])
check("B5 audio rỗng → ok=False kèm lý do, không kèm audio",
      not got[1]["ok"] and got[1]["audio_b64"] == "" and "rỗng" in got[1]["error"], got[1])
check("B6 CapCut trả THIẾU phần tử → ok=False", not got[2]["ok"] and got[2]["error"], got[2])
obj2 = _json.loads(node_ok(["a" * 20]).text)
obj2["items"][0]["meta"]["downloadError"] = "CapCut audio download failed: 403 Forbidden"
obj2["items"][0]["meta"]["material.audio_meta_data"] = _json.dumps(
    {"utterance_list": [{"text": "x", "start_time": 0, "end_time": 1500000}]})
g2 = R.batch_items(obj2, 1)
check("B7 tải file hỏng → ok=False nêu lỗi tải", not g2[0]["ok"] and "403" in g2[0]["error"], g2[0])
check("B8 audio_meta_data dạng chuỗi JSON vẫn đọc được", g2[0]["utterances"] == [{"text": "x", "start": 0.0, "end": 1.5}],
      g2[0]["utterances"])

print("== C. route /synthesize/batch")
st = setup([A, B])
sent, acq = [], []
orig_acquire = R.pool.acquire
R.pool.acquire = lambda *a, **k: (acq.append(1), orig_acquire(*a, **k))[1]


def node(url, headers=None, json=None, timeout=180):
    sent.append({"url": url, "json": json, "who": headers.get("x-capcut-email"), "timeout": timeout})
    return node_ok(json["texts"])


R.requests.post = node
texts = ["El pueblo despertó.", "   ", "Don Aurelio abrió la panadería.", "Nadie lo sabía."]
res = run(R.SynthesizeBatchRequest(email=A, texts=texts, speaker="sKgg4MPUDBy69X7iv3fA"))
check("C1 gọi đúng route đợt của Node, MỘT lượt", len(sent) == 1 and sent[0]["url"] == "http://x/v2/synthesize/batch",
      sent)
check("C2 MỘT lượt mượn tài khoản cho cả đợt", acq == [1], acq)
check("C3 đoạn rỗng không gửi lên CapCut",
      sent[0]["json"]["texts"] == ["El pueblo despertó.", "Don Aurelio abrió la panadería.", "Nadie lo sabía."],
      sent[0]["json"])
body = sent[0]["json"]
check("C4 kèm giọng + tốc độ/âm lượng mặc định đã lưu, không xin mốc",
      body.get("speaker") == "sKgg4MPUDBy69X7iv3fA" and body.get("speed") == 10 and body.get("volume") == 10
      and "timestamps" not in body, body)
items = res["items"]
check("C5 chỉ số khớp danh sách GỬI LÊN (đoạn rỗng giữ chỗ)",
      [it["index"] for it in items] == [0, 1, 2, 3] and not items[1]["ok"] and items[1]["error"], items[1])
check("C6 audio vào ĐÚNG đoạn",
      base64.b64decode(items[2]["audio_b64"]).startswith("ID3Don Aurelio".encode("utf-8"))
      and base64.b64decode(items[3]["audio_b64"]).startswith(b"ID3Nadie"))
check("C7 nói tài khoản đã đọc", res["account"] == A, res.get("account"))
check("C8 timeout theo độ dài đợt", sent[0]["timeout"] == R.batch_timeout(sum(len(t) for t in body["texts"])),
      sent[0]["timeout"])
check("C9 trả số đo thời gian của Node", res.get("timings", {}).get("ttsMs") == 9631, res.get("timings"))

print("== D. lỗi")
st = setup([A, B])
R.requests.post = lambda url, headers=None, json=None, timeout=180: Resp(404, b"", "text/html",
                                                                       "Cannot POST /v2/synthesize/batch")
try:
    run(R.SynthesizeBatchRequest(email=A, texts=["hola", "adiós"]))
    check("D1 server Node cũ không có route → 501", False, "không ném lỗi")
except R.HTTPException as e:
    check("D1 server Node cũ không có route → 501 (bên gọi đọc từng đoạn)", e.status_code == 501, e.status_code)
check("D2 và không ai bị án", all(a["strikes"] == 0 and a["rest_until"] == 0 for a in st.accs.values()), st.accs)

st = setup([A, B])
who_called = []


def a_broken(url, headers=None, json=None, timeout=180):
    who = headers.get("x-capcut-email")
    who_called.append(who)
    if who == A:
        return Resp(502, b"", "application/json", '{"message":"Failed to synthesize batch: boom"}')
    return node_ok(json["texts"])


R.requests.post = a_broken
res = run(R.SynthesizeBatchRequest(email=A, texts=["hola", "adiós"]))
check("D3 5xx chung ở tài khoản A → đối chứng bằng B, đợt vẫn ra audio",
      who_called == [A, B] and all(it["ok"] for it in res["items"]) and res["account"] == B,
      (who_called, res.get("account")))
check("D4 A bị tính án vì B đọc được đúng đợt đó", st.accs[A]["strikes"] == 1, st.accs[A])

st = setup([A, B])
R.requests.post = lambda url, headers=None, json=None, timeout=180: node_ok(json["texts"])


def exhausted(*a, **k):
    raise CP.PoolExhausted("Tất cả tài khoản CapCut đang nghỉ")


R.pool.acquire = exhausted
try:
    run(R.SynthesizeBatchRequest(email=A, texts=["hola"]))
    check("D5 mọi tài khoản đang nghỉ → 503", False, "không ném lỗi")
except R.HTTPException as e:
    check("D5 mọi tài khoản đang nghỉ → 503 (dây chuyền dừng hẳn)", e.status_code == 503, e.status_code)

st = setup([A])
for bad, label in ((["", "  "], "D6 toàn đoạn rỗng → 400"),
                   (["x"] * (R.BATCH_MAX_TEXTS + 1), f"D7 quá {R.BATCH_MAX_TEXTS} đoạn → 400")):
    try:
        run(R.SynthesizeBatchRequest(email=A, texts=bad))
        check(label, False, "không ném lỗi")
    except R.HTTPException as e:
        check(label, e.status_code == 400, e.status_code)

st = setup([A])
R.requests.post = lambda url, headers=None, json=None, timeout=180: node_ok(json["texts"], broken={0})
res = run(R.SynthesizeBatchRequest(email=A, texts=["uno", "dos"]))
check("D8 một đoạn CapCut trả rỗng → chỉ đoạn đó ok=False, đoạn kia vẫn dùng được",
      (not res["items"][0]["ok"]) and res["items"][1]["ok"], res["items"])
check("D9 và không tính án tài khoản", st.accs[A]["strikes"] == 0, st.accs[A])

print("== E. không phá đường cũ")
st = setup([A])
urls = []
R.requests.post = lambda url, headers=None, json=None, timeout=180: (urls.append(url), Resp())[1]
R._pooled_call("http://x", A)({"text": "hola"})
check("E1 _pooled_call mặc định vẫn gọi /v2/synthesize", urls == ["http://x/v2/synthesize"], urls)

print("== F. server Node: mã nguồn + dist đã dựng lại")
svc = (EXT / "server" / "src" / "services" / "CapCutService.ts").read_text(encoding="utf-8")
check("F1 synthesizeBatch gửi CẢ mảng texts", "async synthesizeBatch(" in svc and "texts: options.texts," in svc)
check("F2 tải audio song song, một file hỏng không làm hỏng cả đợt",
      "Math.min(8, materials.length)" in svc and "meta.downloadError" in svc)
idx = (EXT / "server" / "dist" / "routes" / "v2" / "synthesize" / "index.js").read_text(encoding="utf-8")
dsvc = (EXT / "server" / "dist" / "services" / "CapCutService.js").read_text(encoding="utf-8")
check("F3 dist có route /batch (server chạy dist, không chạy src)", "'/batch'" in idx or '"/batch"' in idx, idx[:300])
check("F4 dist có synthesizeBatch + tải song song 8", "synthesizeBatch" in dsvc and "Math.min(8" in dsvc)
check("F5 SKILL.md hướng dẫn đọc theo đợt", "/synthesize/batch" in (EXT / "SKILL.md").read_text(encoding="utf-8"))

print("=" * 70)
if failures:
    print(f"{len(failures)} FAIL / {checks}")
    sys.exit(1)
print(f"{checks}/{checks} PASS")
