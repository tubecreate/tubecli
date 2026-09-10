# CapCut TTS: mốc từ theo đoạn ngắn — cắt câu dưới ngưỡng CapCut cắt mốc, ghép mp3 mã hoá lại,
# cộng dồn mốc. In "SKIP" và exit 0 khi máy không có extension capcut_tts.
import os
import shutil
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

EXT = ROOT / "data" / "extensions_external" / "capcut_tts"
if not (EXT / "capcut_routes.py").exists():
    print(f"SKIP: không có extension capcut_tts tại {EXT}")
    sys.exit(0)
sys.path.insert(0, str(EXT))
TMP = tempfile.mkdtemp(prefix="capcut_marks_")
import tubecli.config as cfg  # noqa: E402
cfg.DATA_DIR = Path(TMP)
# ext_data_path() đọc EXTENSIONS_DATA_DIR (hằng của module, tính lúc import), nên
# đổi DATA_DIR là CHƯA đủ — thiếu dòng này thì mp3 giả của test rơi vào Lịch sử
# thật của người dùng.
cfg.EXTENSIONS_DATA_DIR = Path(TMP) / "extensions_data"
import capcut_routes as R  # noqa: E402

failures, checks = [], 0


def check(label, ok, detail=""):
    global checks
    checks += 1
    if not ok:
        failures.append(f"{label}: {detail}")


# A. cắt câu: mọi đoạn ≤ 90 ký tự, cắt ở ranh giới câu trước, không mất chữ
text = ("El vicepresidente Vance sostiene que esto no es una guerra. Pero en el golfo hay barcos ardiendo, "
        "y un golfo entero al borde de algo que nadie quiere nombrar. ¿Qué pasará mañana? Nadie lo sabe.")
ch = R.split_text(text)
check("A ≤90", all(len(c) <= 90 for c in ch), [len(c) for c in ch])
check("A không mất chữ", " ".join(ch).split() == text.split())
check("A cắt ở câu", ch[0].endswith("guerra.") , ch[0])
long_sentence = " ".join(["palabra"] * 40)                    # 319 ký tự, không dấu câu
ch2 = R.split_text(long_sentence)
check("A câu quá dài cắt ở khoảng trắng", all(len(c) <= 90 for c in ch2) and " ".join(ch2).split() == long_sentence.split(), [len(c) for c in ch2])
check("A rỗng", R.split_text("   ") == [])
check("A ngưỡng < 100 (CapCut cắt mốc ở ~100)", R.MARK_CHUNK_CHARS < 100)

# B. cộng dồn mốc theo độ dài THẬT từng đoạn; đoạn không đo được → mốc cuối + 0.15
merged = R.merge_marks([
    (2.0, [{"word": "uno", "start": 0.0, "end": 0.5}, {"word": "dos", "start": 0.5, "end": 1.0}]),
    (0.0, [{"word": "tres", "start": 0.1, "end": 0.6}]),
    (1.5, [{"word": "cuatro", "start": 0.0, "end": 0.4}, {"word": "", "start": 0, "end": 1}, {"word": "x", "start": 1, "end": 0.5}]),
])
check("B dời mốc", [ (w["word"], w["start"]) for w in merged] == [("uno", 0.0), ("dos", 0.5), ("tres", 2.1), ("cuatro", 2.75)], merged)
check("B bỏ mốc hỏng", len(merged) == 4)

# C. ghép mp3 mã hoá lại: 2 đoạn 1s + 2s → ~3s, 44100Hz mono
ff = shutil.which("ffmpeg")
if ff:
    a = os.path.join(TMP, "a.mp3"); b = os.path.join(TMP, "b.mp3"); out = os.path.join(TMP, "out.mp3")
    subprocess.run([ff, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=440:d=1", "-ar", "24000", "-c:a", "libmp3lame", a], check=True)
    subprocess.run([ff, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=440:d=2", "-ar", "44100", "-c:a", "libmp3lame", b], check=True)
    ok = R._concat_mp3([Path(a), Path(b)], Path(out))
    dur = R._media_seconds(out)
    sr = subprocess.run([shutil.which("ffprobe"), "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=sample_rate",
                         "-of", "csv=p=0", out], capture_output=True, text=True).stdout.strip()
    check("C ghép", ok and abs(dur - 3.0) < 0.3 and sr == "44100", (ok, dur, sr))
    check("C đo đoạn", abs(R._media_seconds(a) - 1.0) < 0.2, R._media_seconds(a))
else:
    print("(bỏ C: máy không có ffmpeg)")

# D. route xin mốc đi theo đoạn: mỗi đoạn một lượt gọi worker, file cuối là bản ghép, mốc cộng dồn
import base64
import json
calls = []


class _Resp:
    def __init__(self, body):
        self.status_code = 200
        self.headers = {"content-type": "application/json"}
        self.text = json.dumps(body)
        self._body = body

    def json(self):
        return self._body


def fake_post(url, headers=None, json=None, timeout=180):
    calls.append(json["text"])
    a = os.path.join(TMP, f"chunk{len(calls)}.mp3")
    if ff:
        subprocess.run([ff, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=440:d=1", "-c:a", "libmp3lame", a], check=True)
        audio = open(a, "rb").read()
    else:
        audio = b"ID3" + b"\x00" * 2000
    toks = json["text"].split()
    step = 0.9 / max(1, len(toks))                       # mốc giả phải nằm TRONG 1 giây audio giả
    words = [{"word": w, "start": round(i * step, 3), "end": round(i * step + step * 0.8, 3)} for i, w in enumerate(toks)]
    return _Resp({"audio": base64.b64encode(audio).decode(), "words": words, "duration": 1.0})


R.requests.post = fake_post
R._ensure_node = lambda: "http://x"
R._account_headers = lambda email: {}
R.account_store.record_use = lambda *a, **k: None
req = R.SynthesizeRequest(email="a@x", text=text, speaker="Chispa", timestamps=True)
import asyncio
res = asyncio.run(R.synthesize(req))
check("D nhiều đoạn", isinstance(res, dict) and res["chunks"] == len(R.split_text(text)) and len(calls) == res["chunks"], (type(res), calls))
check("D đủ mốc", len(res["words"]) == len(text.split()), (len(res["words"]), len(text.split())))
starts = [w["start"] for w in res["words"]]
check("D mốc tăng dần và dời sang đoạn sau", starts == sorted(starts) and starts[-1] > 1.0, starts[-3:])
check("D file ghép", (R._output_dir() / res["file"]).is_file() and len(base64.b64decode(res["audio_b64"])) > 1000)

print("=" * 70)
if failures:
    print(f"{len(failures)} FAIL / {checks}")
    for x in failures:
        print("  FAIL", x)
    sys.exit(1)
print(f"{checks}/{checks} PASS")
