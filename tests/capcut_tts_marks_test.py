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
# global_settings.json THẬT của máy nằm ở đường dẫn mặc định — trỏ sang thư mục
# tạm trước khi test ghi cài đặt nhịp gửi bên dưới.
cfg.GLOBAL_SETTINGS_FILE = Path(TMP) / "global_settings.json"
import capcut_routes as R  # noqa: E402
cfg.set_global_setting("capcut_min_gap", 0)
cfg.set_global_setting("capcut_hourly_cap", 0)

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
check("D nhiều đoạn", isinstance(res, dict) and res["chunks"] == len(R.split_sentences(text)) and len(calls) == res["chunks"], (type(res), calls))
check("D mỗi lượt là câu TRỌN (không lượt nào bắt đầu giữa câu)",
      all(c[:1].isupper() or c[:1] in "¿¡" for c in calls), calls)
check("D đủ mốc", len(res["words"]) == len(text.split()), (len(res["words"]), len(text.split())))
starts = [w["start"] for w in res["words"]]
check("D mốc tăng dần và dời sang đoạn sau", starts == sorted(starts) and starts[-1] > 1.0, starts[-3:])
check("D file ghép", (R._output_dir() / res["file"]).is_file() and len(base64.b64decode(res["audio_b64"])) > 1000)

# E. chia theo CÂU cho đường xin mốc (dựng video)
#    13/9/2026: dựng video đọc ngắt giữa câu vì cắt cứng ở 90 ký tự.
vi = ("Hôm nay chúng ta sẽ cùng nhau tìm hiểu câu chuyện về một ngôi làng nhỏ nằm sâu trong thung lũng "
      "mà hầu như chưa ai từng đặt chân tới và cũng chẳng có tấm bản đồ nào ghi tên. "
      "Trời mưa. Gió lạnh. "
      "Người dân nơi đây sống bằng nghề dệt vải, họ dậy từ khi trời còn tối, thắp đèn dầu, "
      "ngồi bên khung cửi suốt nhiều giờ liền, rồi mang từng tấm vải ra chợ phiên cách đó ba ngày đường.")
sents = R._sentences(vi)
ch3 = R.split_sentences(vi)
check("E không mất chữ", " ".join(ch3).split() == vi.split(), ch3)
check("E câu ≤280 ký tự KHÔNG bị cắt giữa chừng",
      all(any(s0 in c for c in ch3) for s0 in sents if len(s0) <= R.MARK_SENTENCE_MAX),
      [len(s0) for s0 in sents])
check("E câu ngắn gộp chung một lượt khi tổng ≤90", "Trời mưa. Gió lạnh." in ch3, ch3)
check("E mọi lượt kết thúc ở dấu kết câu", all(c.rstrip()[-1] in ".!?…" for c in ch3), ch3)

longs = ("Người dân nơi đây sống bằng nghề dệt vải từ bao đời nay và họ vẫn giữ nếp làm việc cũ dù cuộc sống "
         "ngoài kia đã thay đổi rất nhiều, họ dậy từ khi trời còn tối để thắp đèn dầu rồi ngồi bên khung cửi "
         "suốt nhiều giờ liền mà không nghỉ ngơi và mang từng tấm vải ra chợ phiên cách đó ba ngày đường.")
check("E (mẫu test là câu thật sự vượt trần)", len(longs) > R.MARK_SENTENCE_MAX, len(longs))
p4 = R.split_sentences(longs)
check("E câu vượt trần: mọi mảnh ≤ trần", all(len(c) <= R.MARK_SENTENCE_MAX for c in p4), [len(c) for c in p4])
check("E câu vượt trần: cắt ở DẤU PHẨY, không ở khoảng trắng giữa cụm", p4[0].endswith(","), p4)
check("E câu vượt trần: không để đuôi cụt", min(len(c) for c in p4) >= len(longs) * 0.25, [len(c) for c in p4])

nocomma = " ".join(["chúng tôi đi qua cánh đồng"] * 8) + " và " + " ".join(["họ ngồi đợi dưới gốc cây"] * 8) + "."
p5 = R.split_sentences(nocomma)
check("E không dấu phẩy: mảnh ≤ trần, không mất chữ",
      all(len(c) <= R.MARK_SENTENCE_MAX for c in p5) and " ".join(p5).split() == nocomma.split(), [len(c) for c in p5])
check("E không dấu phẩy: cắt ngay trước liên từ gần giữa", any(c.startswith("và ") for c in p5[1:]), p5)

zh = "今天我们去了一个很远的村庄。那里的人们以织布为生！他们每天很早就起床。"
check("E chữ Hán: tách câu không cần khoảng trắng", len(R._sentences(zh)) == 3, R._sentences(zh))
check("E nháy đóng đi theo câu", R._sentences('Anh ấy nói: "Đi thôi." Rồi quay đi.')[0].endswith('"'),
      R._sentences('Anh ấy nói: "Đi thôi." Rồi quay đi.'))

# F. lấp mốc: CapCut chỉ trả mốc cho ~100 ký tự đầu của câu đọc trọn
sent = ("Người dân nơi đây sống bằng nghề dệt vải từ bao đời nay và họ vẫn giữ nếp làm việc "
        "cũ dù cuộc sống ngoài kia đã thay đổi rất nhiều.")
toks = sent.split()
head = [{"word": w, "start": round(i * 0.3, 3), "end": round(i * 0.3 + 0.25, 3)} for i, w in enumerate(toks[:18])]
full = R.fill_marks(sent, head, 10.0)
st5 = [w["start"] for w in full]
check("F đủ mốc cho mọi từ", len(full) == len(toks), (len(full), len(toks)))
check("F giữ nguyên mốc thật ở đầu", full[:18] == [{"word": w["word"], "start": w["start"], "end": w["end"]} for w in head])
check("F mốc tăng dần và không vượt thời lượng", st5 == sorted(st5) and full[-1]["end"] <= 10.0 + 1e-6, st5[-3:])
check("F mốc đã phủ đủ thì không thêm gì", R.fill_marks("một hai", [
    {"word": "một", "start": 0, "end": 0.4}, {"word": "hai", "start": 0.5, "end": 0.9}], 1.0) ==
      [{"word": "một", "start": 0.0, "end": 0.4}, {"word": "hai", "start": 0.5, "end": 0.9}])
wrong = [{"word": "xyz", "start": 0, "end": 0.2}, {"word": "abc", "start": 0.3, "end": 0.5}]
ws = R.fill_marks("một hai ba bốn năm sáu bảy tám", wrong, 4.0)
check("F mốc không khớp chữ: ước lượng CẢ đoạn thay vì gắn mốc lệch",
      [w["word"] for w in ws] == "một hai ba bốn năm sáu bảy tám".split(), ws)
check("F bỏ token chỉ có dấu", len(R.fill_marks("Mưa — gió", [], 2.0)) == 2)

# G. route: CapCut giả chỉ trả mốc 100 ký tự đầu; kết quả vẫn đủ mốc, lượt gọi = số câu
calls.clear()


def partial_post(url, headers=None, json=None, timeout=180):
    calls.append(json["text"])
    audio = b"ID3" + b"\x00" * 4000
    covered, n = [], 0
    for w in json["text"].split():
        if n + len(w) > 100:
            break
        covered.append(w)
        n += len(w) + 1
    step = 0.3
    words = [{"word": w, "start": round(i * step, 3), "end": round(i * step + 0.25, 3)} for i, w in enumerate(covered)]
    return _Resp({"audio": base64.b64encode(audio).decode(), "words": words,
                  "duration": round(len(json["text"].split()) * step + 0.3, 3)})


R.requests.post = partial_post
R._media_seconds = lambda path: 0.0          # không có ffprobe trong test: dùng duration CapCut trả
res2 = asyncio.run(R.synthesize(R.SynthesizeRequest(email="a@x", text=vi, timestamps=True)))
check("G lượt gọi = số lượt theo câu", len(calls) == len(R.split_sentences(vi)), (len(calls), calls))
check("G đủ mốc cho mọi từ của cả shot", len(res2["words"]) == len([t for t in vi.split() if any(ch.isalnum() for ch in t)]),
      (len(res2["words"]), len(vi.split())))
g_st = [w["start"] for w in res2["words"]]
check("G mốc tăng dần qua các câu", g_st == sorted(g_st), g_st[:5])

print("=" * 70)
if failures:
    print(f"{len(failures)} FAIL / {checks}")
    for x in failures:
        print("  FAIL", x)
    sys.exit(1)
print(f"{checks}/{checks} PASS")
