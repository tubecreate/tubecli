# CapCut TTS: văn bản dài đọc LẦN LƯỢT theo đoạn rồi ghép; tốc độ/âm lượng có mặc định lưu được.
#
# Chạy:  python tests/capcut_tts_chunk_test.py     (exit 0 = pass)
#        In "SKIP" và exit 0 khi máy không có extension capcut_tts.
#
# VÌ SAO CÓ FILE NÀY
#   Sidecar Node CÓ tự cắt văn bản ở 100 ký tự, nhưng nó bắn tất cả đoạn SONG SONG
#   (Promise.all trong CapCutService.synthesizeChunkedBuffers) rồi nối byte thô
#   (Buffer.concat). Một kịch bản 3000 ký tự thành 30 request cùng lúc, và đoạn nào
#   CapCut trả 24000Hz thì méo giọng khi nằm cạnh đoạn 44100Hz — đúng lý do
#   _concat_mp3 ở phía Python phải MÃ HOÁ LẠI. Cả hai chuyện đều KHÔNG báo lỗi:
#   file vẫn ra, vẫn phát được, chỉ là thiếu đoạn hoặc sai giọng.
#
#   Tốc độ/âm lượng: trước đây model đặt cứng 10, nên lượt do agent gọi không có
#   cách nào theo ý người dùng đã chỉnh trên giao diện.
import io
import json
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

EXT = ROOT / "data" / "extensions_external" / "capcut_tts"
if not (EXT / "capcut_routes.py").exists():
    print(f"SKIP: không có extension capcut_tts tại {EXT}")
    sys.exit(0)
sys.path.insert(0, str(EXT))
TMP = tempfile.mkdtemp(prefix="capcut_chunk_")
import tubecli.config as cfg  # noqa: E402
cfg.DATA_DIR = Path(TMP)
# Mặc định đọc/ghi vào global_settings.json THẬT của máy — trỏ sang thư mục tạm
# trước khi gọi bất cứ thứ gì, kẻo test ghi đè cài đặt của người dùng.
cfg.GLOBAL_SETTINGS_FILE = Path(TMP) / "global_settings.json"
# _output_dir() đi qua ext_data_path → EXTENSIONS_DATA_DIR, một hằng của module
# tính lúc import. Không trỏ lại thì test ghi mp3 giả vào LỊCH SỬ THẬT của người
# dùng (đã xảy ra một lần khi viết test này).
cfg.EXTENSIONS_DATA_DIR = Path(TMP) / "extensions_data"
import capcut_routes as R  # noqa: E402
import asyncio  # noqa: E402

failures, checks = [], 0


def _mark_of(chunk_text: str) -> str:
    """Số khổ ĐẦU TIÊN nằm trong một đoạn — dùng làm mốc nhận diện đoạn đó.

    Mốc phải là chuỗi có thật trong đoạn, để khi máy chủ giả nhận một PHẦN CON của
    đoạn ấy nó vẫn nhận ra và vẫn làm hỏng.
    """
    import re as _re
    m = _re.search(r"Khổ thứ (\d+)\.", chunk_text)
    return m.group(1) if m else "0"


def _wait_task(task_id: str, secs: float = 30.0) -> dict:
    """Chờ lượt đọc nền xong. POST chỉ khởi động rồi trả về ngay (tránh HTTP 524),
    nên mọi phép kiểm về KẾT QUẢ phải đi qua route tiến độ."""
    import time as _tt
    import asyncio as _aio
    end = _tt.time() + secs
    st = {}
    while _tt.time() < end:
        st = _aio.run(R.synthesize_chunks_status(task_id))
        if st.get("status") != "running":
            return st
        _tt.sleep(0.2)
    return st


def _raises(fn) -> int:
    """Mã lỗi HTTP mà fn() ném ra, 0 nếu nó không ném."""
    try:
        fn()
    except Exception as e:      # noqa: BLE001
        return int(getattr(e, "status_code", 0) or 0)
    return 0


def check(label, ok, detail=""):
    global checks
    checks += 1
    if not ok:
        failures.append(f"{label}: {detail}")


# ── A. bộ cắt dùng chung ───────────────────────────────────────────────────
_PARA = ("Việt Nam có bờ biển dài hơn ba nghìn kilômét. Miền Bắc có mùa đông lạnh, miền Nam thì nắng quanh năm, "
         "còn miền Trung hứng bão gần như mỗi tháng chín. Người ta trồng lúa hai vụ, có nơi ba vụ. "
         "Cà phê ở Tây Nguyên, vải thiều ở Bắc Giang, thanh long ở Bình Thuận. Đó là chuyện của đất.")
# Ngưỡng đoạn nay tính theo ĐỘ DÀI TIẾNG (~2,5 phút ≈ 2050 ký tự) chứ không còn 100,
# nên văn bản mẫu phải dài thật mới ra nhiều đoạn — dùng đoạn ngắn là test chỉ còn
# một đoạn và mọi phép kiểm về nhiều đoạn thành vô nghĩa mà vẫn xanh.
# Mỗi khổ mang một số thứ tự nên nội dung các đoạn KHÁC NHAU. Lặp y nguyên một
# khổ là bẫy: `plain.index(text)` trong máy chủ giả trả về đoạn ĐẦU TIÊN khớp, nên
# phép làm-hỏng-đoạn-N rơi vào đoạn khác và test xanh sai.
LONG = " ".join(f"Khổ thứ {i}. {_PARA}" for i in range(1, 31))   # ~9200 ký tự
plain = R.split_text(LONG, R.PLAIN_CHUNK_CHARS)
check("A mọi đoạn ≤ ngưỡng", all(len(c) <= R.PLAIN_CHUNK_CHARS for c in plain), [len(c) for c in plain])
check("A không mất chữ", " ".join(plain).split() == LONG.split())
# Gói nhiều câu/vế vào một đoạn cho tới sát ngưỡng, nhưng KHÔNG BAO GIỜ cắt giữa
# vế: đoạn nào cũng kết ở dấu câu (giọng ngắt hơi sai chỗ là nghe ra ngay).
check("A đoạn nào cũng kết ở dấu câu", all(c[-1] in ".,;:!?…" for c in plain), [c[-12:] for c in plain])
check("A nhiều đoạn thật", len(plain) >= 3, len(plain))
# Sidecar chỉ cắt khi text DÀI HƠN ngưỡng của nó. Ta cắt trước theo độ dài tiếng,
# và NÂNG ngưỡng của sidecar lên cao hơn để nó không cắt lần hai rồi nối byte thô
# sau lưng mình. Hai số này phải đi cùng nhau, nên khoá cả hai ở đây.
_pm = io.open(EXT / "capcut_process_manager.py", encoding="utf-8").read()
import re as _re
_m = _re.search(r'"CAPCUT_TTS_TEXT_CHUNK_MAX_LENGTH":\s*"(\d+)"', _pm)
check("A có nâng ngưỡng cắt của sidecar", _m is not None)
check("A ngưỡng của ta NHỎ HƠN ngưỡng sidecar",
      _m and R.PLAIN_CHUNK_CHARS < int(_m.group(1)), (R.PLAIN_CHUNK_CHARS, _m and _m.group(1)))
check("A đoạn dài khoảng 2-3 phút", 2.0 <= R.CHUNK_MINUTES <= 3.0, R.CHUNK_MINUTES)
check("A mức sàn chia nhỏ nhỏ hơn nhiều lần ngưỡng",
      R.SUBSPLIT_FLOOR < R.PLAIN_CHUNK_CHARS // 4, (R.SUBSPLIT_FLOOR, R.PLAIN_CHUNK_CHARS))
check("A ngưỡng mốc từ vẫn nhỏ hơn", R.MARK_CHUNK_CHARS < 100, R.MARK_CHUNK_CHARS)
check("A rỗng", R.split_text("   ") == [])

# ── B. mặc định tốc độ/âm lượng ────────────────────────────────────────────
check("B chưa lưu gì → 10/10", (R.default_speed(), R.default_volume()) == (10, 10),
      (R.default_speed(), R.default_volume()))
asyncio.run(R.set_settings(R.SettingsRequest(speed=14, volume=7)))
check("B lưu rồi đọc lại", (R.default_speed(), R.default_volume()) == (14, 7),
      (R.default_speed(), R.default_volume()))
# Đổi một thanh không được xoá thanh kia.
asyncio.run(R.set_settings(R.SettingsRequest(speed=None, volume=3)))
check("B None = giữ nguyên", (R.default_speed(), R.default_volume()) == (14, 3),
      (R.default_speed(), R.default_volume()))
# Giá trị vô lý thì KẸP, không ném: một lượt đọc không nên chết vì speed=99.
asyncio.run(R.set_settings(R.SettingsRequest(speed=99, volume=-5)))
check("B kẹp về khoảng hợp lệ", (R.default_speed(), R.default_volume()) == (R.SPEED_MAX, R.VOLUME_MIN),
      (R.default_speed(), R.default_volume()))
got = asyncio.run(R.get_settings())
check("B GET /settings trả cả khoảng", got["speed"] == R.SPEED_MAX and got["speed_min"] == R.SPEED_MIN
      and got["volume_max"] == R.VOLUME_MAX, got)
check("B file cài đặt nằm trong thư mục tạm", (Path(TMP) / "global_settings.json").is_file())
saved = json.loads(io.open(Path(TMP) / "global_settings.json", encoding="utf-8").read())
check("B khoá riêng của CapCut", saved.get("capcut_speed") == R.SPEED_MAX and "capcut_volume" in saved, saved)

# ── C. route đọc thường: lần lượt, đúng thứ tự, một file ghép ──────────────
asyncio.run(R.set_settings(R.SettingsRequest(speed=12, volume=6)))
calls = []


class _Audio:
    def __init__(self, text):
        self.status_code = 200
        self.headers = {"content-type": "audio/mpeg"}
        self.text = ""
        # Nội dung khác nhau theo đoạn để kiểm THỨ TỰ khi ghép byte thô.
        self.content = b"ID3" + text.encode("utf-8")[:40].ljust(2000, b"\x00")


def fake_post(url, headers=None, json=None, timeout=180):
    calls.append(dict(json))
    return _Audio(json["text"])


R.requests.post = fake_post
R._ensure_node = lambda: "http://x"
R._account_headers = lambda email: {}
R.account_store.record_use = lambda *a, **k: None
# Không có ffmpeg trên máy chạy test thì _concat_mp3 trả False và route nối byte
# thô — nhánh đó cũng phải ra đúng số đoạn, nên ép False để kiểm luôn đường lui.
R._concat_mp3 = lambda parts, out: False

# Đường API: người gọi (Content Studio) đã gửi đúng lời của MỘT shot, nên ở đây
# "gọi đoạn nào xử lý đoạn đó" — KHÔNG tự cắt. Cắt thêm chỉ làm ngữ điệu vụn và
# sinh mối ghép giữa câu. Việc cắt 2-3 phút là của đường tạo audio trực tiếp.
res = asyncio.run(R.synthesize(R.SynthesizeRequest(email="a@x", text=LONG)))
check("C API gửi NGUYÊN đoạn được gọi, một lượt", len(calls) == 1 and calls[0]["text"] == LONG,
      (len(calls), calls[0]["text"][:30] if calls else None))
check("C API không cắt dù bài dài", res.headers.get("x-capcut-chunks") == "1", dict(res.headers))
check("C một file trong Lịch sử", len(list(R._output_dir().glob("*.mp3"))) == 1,
      [p.name for p in R._output_dir().glob("*.mp3")])
check("C lượt gọi mang speed/volume mặc định đã lưu",
      calls[0]["speed"] == 12 and calls[0]["volume"] == 6, calls[0])

# Văn bản ngắn: vẫn đúng MỘT lượt.
calls.clear()
res2 = asyncio.run(R.synthesize(R.SynthesizeRequest(email="a@x", text="xin chào")))
check("C ngắn = 1 lượt", len(calls) == 1 and calls[0]["text"] == "xin chào", calls)
check("C ngắn header = 1", res2.headers.get("x-capcut-chunks") == "1", dict(res2.headers))

# Lưới an toàn: CapCut từ chối đoạn DÀI thì tự chia nhỏ rồi ghép, vẫn ra tiếng.
# Trần thật của CapCut chưa đo được, nên đây là chỗ giữ cho một lời shot dài bất
# thường không mất trắng.
calls.clear()


def refuse_long(url, headers=None, json=None, timeout=180):
    calls.append(dict(json))
    if len(json["text"]) > 600:
        return _Fail()
    return _Audio(json["text"])


R.requests.post = refuse_long
res3 = asyncio.run(R.synthesize(R.SynthesizeRequest(email="a@x", text=LONG)))
check("C đoạn bị từ chối → chia nhỏ, vẫn ra audio",
      getattr(res3, "media_type", "") == "audio/mpeg", type(res3))
check("C có thử cả đoạn trước khi chia", calls[0]["text"] == LONG, calls[0]["text"][:30])
# Chia nhỏ chạy ĐỆ QUY: mức giữa vẫn có thể bị từ chối, nên chỉ những lượt CUỐI
# mới dưới mức. Điều phải giữ là: có xuống tới mức qua được, và có DỪNG.
check("C chia tới khi qua được mức bị từ chối",
      any(len(c["text"]) <= 600 for c in calls[1:]), sorted({len(c["text"]) for c in calls[1:]})[:3])
check("C đệ quy có DỪNG, không nổ số lượt", len(calls) < 80, len(calls))
check("C không để lại file .part", not list(R._output_dir().glob("*.part")),
      [p.name for p in R._output_dir().glob("*.part")])
# Chia tới mức sàn mà vẫn bị từ chối thì phải HỎNG, đừng chia vô hạn.
R.requests.post = lambda url, headers=None, json=None, timeout=180: _Fail()
check("C từ chối mọi mức → 502", _raises(lambda: asyncio.run(
    R.synthesize(R.SynthesizeRequest(email="a@x", text=LONG)))) == 502)
R.requests.post = fake_post

# Lời gọi TRUYỀN tham số thì thắng mặc định, và vẫn bị kẹp.
calls.clear()
asyncio.run(R.synthesize(R.SynthesizeRequest(email="a@x", text="xin chào", speed=20, volume=0)))
check("C truyền thì dùng số truyền", calls[0]["speed"] == 20 and calls[0]["volume"] == 0, calls[0])
calls.clear()
asyncio.run(R.synthesize(R.SynthesizeRequest(email="a@x", text="xin chào", speed=999, volume=-9)))
check("C truyền số vô lý → kẹp", calls[0]["speed"] == R.SPEED_MAX and calls[0]["volume"] == R.VOLUME_MIN, calls[0])

# ── D. đoạn hỏng TẠM được cứu ở vòng thử lại; hỏng MÃI thì báo rõ đoạn nào ──
class _Fail:
    status_code = 502
    headers = {"content-type": "application/json"}
    text = "quota"
    content = b""


state = {"n": 0}


def fail_once(url, headers=None, json=None, timeout=180):
    """Đoạn thứ hai hỏng ĐÚNG một lượt — vòng thử lại phải cứu được."""
    state["n"] += 1
    return _Audio(json["text"]) if state["n"] != 2 else _Fail()


R.requests.post = fail_once
# Đếm theo TÊN, không theo số lượng: nhóm C phía trên đã tạo vài file nên phép
# so "before + 1" vỡ mỗi lần thêm một phép kiểm ở trên.
before = {p.name for p in R._output_dir().glob("*.mp3")}
res_d = asyncio.run(R.synthesize(R.SynthesizeRequest(email="a@x", text=LONG)))
check("D hỏng tạm một đoạn KHÔNG còn giết cả lượt",
      getattr(res_d, "media_type", "") == "audio/mpeg", type(res_d))
after = {p.name for p in R._output_dir().glob("*.mp3")}
check("D ra ĐÚNG một file mới", len(after - before) == 1, sorted(after - before))
check("D không để lại thư mục đoạn khi đã xong",
      not list((R._output_dir() / "parts").glob("*")) if (R._output_dir() / "parts").is_dir() else True,
      [p.name for p in (R._output_dir() / "parts").glob("*")] if (R._output_dir() / "parts").is_dir() else [])

# ── E. giao diện: thanh kéo, lưu mặc định, báo số đoạn ─────────────────────
html = io.open(EXT / "static" / "capcut.html", encoding="utf-8").read()
check("E speed là thanh kéo", '<input type="range" id="syn-speed"' in html)
check("E volume là thanh kéo", '<input type="range" id="syn-volume"' in html)
check("E không còn ô nhập số", 'type="number" id="syn-speed"' not in html and 'type="number" id="syn-volume"' not in html)
check("E nhả tay là lưu mặc định", "addEventListener('change', saveSynSettings)" in html)
check("E nạp mặc định lúc mở trang", "loadSynSettings" in html and ".then(loadSynSettings)" in html)
# Giao diện KHÔNG còn đọc header số đoạn: nó gọi /synthesize/chunks và vẽ danh
# sách từng đoạn, nghe được ngay từng cái, đoạn lỗi có nút Thử lại.
check("E gọi đường chịu lỗi, không phải /synthesize", "'/synthesize/chunks'" in html
      and "await fetch(API + '/synthesize'," not in html)
check("E có khung danh sách đoạn", 'id="chunk-box"' in html and "function renderChunks()" in html)
check("E mỗi đoạn xong có player riêng", "API + '/parts/' + encodeURIComponent" in html)
check("E đoạn lỗi có nút thử lại", "onclick = () => retryChunk(c.index)" in html
      and "'/synthesize/retry'" in html)
check("E thử lại tất cả chạy LẦN LƯỢT", "for (const c of CHUNK_RUN.chunks.filter" in html
      and "await retryChunk(c);" in html)
check("E có CSS cho range", "input[type=range]::-webkit-slider-thumb" in html)
# Lý do giọng bị ẩn: sidecar Node ghi cứng TIẾNG ANH và giao diện trước đây in
# nguyên văn ra, nên người dùng tiếng Việt đọc một câu tiếng Anh giữa trang Việt.
check("E lý do giọng ẩn tra qua khoá dịch", "'syn.broken_' + String(h.language" in html)
check("E thiếu câu dịch thì vẫn dùng nguyên văn sidecar", "msg === key ? (h.reason || '')" in html)
for key in ("syn.slider_hint", "syn.default_saved", "syn.done_chunks", "syn.broken_vi_11labs"):
    # Đếm CÓ dấu hai chấm: bản thân mã JS cũng gọi t('syn.…') nên đếm trơ trọi ra 10.
    check(f"E khoá {key} đủ 9 ngôn ngữ", html.count(f"'{key}':") == 9, html.count(f"'{key}':"))

# ── F. đoạn lỗi thì BỎ QUA, đọc tiếp, rồi tự thử lại 2 vòng ───────────────
# Người dùng dán 3000 chữ, đoạn 7 hỏng vì CapCut chặn nhịp: mất trắng 29 đoạn kia
# thì lần nào cũng phải làm lại từ đầu. Đường giao diện phải giữ được phần đã xong.
R._concat_mp3 = lambda parts, out: False
state = {"fail_until": {}}          # index 1-based -> số lượt còn phải hỏng


# Làm hỏng theo NỘI DUNG, không theo chỉ số đoạn. Lý do: khi một đoạn hỏng hết
# lượt, vòng cuối bật lưới CHIA NHỎ và các phần con có nội dung khác — nếu chỉ
# nhận diện theo chỉ số thì phần con nào cũng qua, và test "hỏng mãi" xanh sai.
# Mốc nằm trong văn bản nên phần con nào chứa nó cũng hỏng, đúng như một đoạn mà
# CapCut thật sự không đọc được.
def flaky_post(url, headers=None, json=None, timeout=180):
    calls.append(dict(json))
    txt = json["text"]
    for mark, left in list(state["fail_until"].items()):
        if mark in txt:
            if left > 0:
                state["fail_until"][mark] = left - 1
                return _Fail()
    return _Audio(txt)


R.requests.post = flaky_post

# Đoạn 2 hỏng 1 lượt (vòng thử lại đầu phải cứu được), đoạn 3 hỏng mãi.
calls.clear()
# Mốc lấy từ chính nội dung các đoạn, nên tự đúng khi ngưỡng đoạn đổi.
assert len(plain) >= 4, f"mẫu phải ra >= 4 đoạn, đang {len(plain)}"
FLAKY, BAD = 2, len(plain) - 1     # đoạn hỏng tạm, đoạn hỏng mãi
M_FLAKY = f"Khổ thứ {_mark_of(plain[FLAKY - 1])}."
M_BAD = f"Khổ thứ {_mark_of(plain[BAD - 1])}."
state["fail_until"] = {M_FLAKY: 1, M_BAD: 99}
_start = asyncio.run(R.synthesize_chunks(R.SynthesizeRequest(email="a@x", text=LONG)))
res = _wait_task(_start["task_id"])
check("F lượt nền chạy xong", res.get("status") == "completed", res.get("status"))
rows = {c["index"]: c for c in res["chunks"]}
check("F không chết cả lượt vì một đoạn hỏng", res["success"] is True and res["total"] == len(plain), res.get("total"))
check("F đoạn hỏng tạm được cứu ở vòng thử lại", rows[FLAKY]["ok"] is True and rows[FLAKY]["attempts"] == 2, rows[FLAKY])
check("F đoạn hỏng mãi thì để lại, có lý do", rows[BAD]["ok"] is False and rows[BAD]["error"], rows[BAD])
check("F thử đúng 1 + 2 vòng rồi DỪNG", rows[BAD]["attempts"] == 1 + R.CHUNK_RETRY_ROUNDS, rows[BAD]["attempts"])
check("F các đoạn khác vẫn xong", all(rows[i]["ok"] for i in rows if i != BAD), [i for i in rows if not rows[i]["ok"]])
check("F đếm đúng done/failed", res["done"] == len(plain) - 1 and res["failed"] == 1, (res["done"], res["failed"]))
check("F vẫn ghép được file từ phần đã xong", res["joined"] and (R._output_dir() / res["joined"]).is_file(), res["joined"])
# Mỗi đoạn xong là một file nghe được ngay.
pdir = R._output_dir() / "parts" / res["session"]
files = sorted(p.name for p in pdir.glob("*.mp3"))
check("F mỗi đoạn một file riêng", len(files) == len(plain) - 1 and files[0] == "p001.mp3", files)
check("F file đoạn KHÔNG lẫn vào Lịch sử",
      all("p0" not in p.name for p in R._output_dir().glob("*.mp3")),
      [p.name for p in R._output_dir().glob("*.mp3")])

# Route nghe một đoạn: chặn lách đường dẫn.
ok_row = next(c for c in res["chunks"] if c["ok"])
fr = asyncio.run(R.part_file(res["session"], ok_row["file"]))
check("G nghe được một đoạn", getattr(fr, "media_type", "") == "audio/mpeg", fr)
for bad_s, bad_n in ((res["session"], "../../x.mp3"), ("..", "p001.mp3"), (res["session"], "p1.mp3")):
    try:
        asyncio.run(R.part_file(bad_s, bad_n))
        check(f"G chặn {bad_s}/{bad_n}", False, "KHÔNG chặn")
    except Exception as e:
        check(f"G chặn {bad_s}/{bad_n}", getattr(e, "status_code", 0) in (400, 404), e)

# Thử lại TAY đúng đoạn còn hỏng → xong, và file ghép được dựng lại.
state["fail_until"] = {}
calls.clear()
rr = asyncio.run(R.synthesize_retry(R.RetryChunkRequest(
    email="a@x", text=LONG, session=res["session"], index=BAD)))
check("G thử tay đọc lại ĐÚNG đoạn đó", len(calls) == 1 and calls[0]["text"] == plain[BAD - 1], calls)
check("G thử tay xong thì ghép lại đủ", rr["done"] == len(plain) and rr["joined"], rr)
check("G đoạn ngoài phạm vi → lỗi rõ",
      _raises(lambda: asyncio.run(R.synthesize_retry(R.RetryChunkRequest(
          email="a@x", text=LONG, session=res["session"], index=99)))) in (400,), "phải 400")

# ── I. chạy NỀN: POST trả ngay, tiến độ tăng dần ──────────────────────────
# HTTP 524: tunnel Cloudflare cắt request quá ~100 giây, mà 30 đoạn đọc lần lượt
# thì luôn vượt (người dùng báo 10/9/2026). Kèm bệnh nặng hơn: hàm async gọi
# requests.post ĐỒNG BỘ sẽ chặn event loop, mọi route khác của máy chủ đứng theo
# — đó là loạt 502 từ codex/stats/browser-status trong console lúc đang đọc.
import threading as _th
import time as _t

state["fail_until"] = {}
R.requests.post = flaky_post
gate = _th.Event()
orig_post = R.requests.post


def slow_post(url, headers=None, json=None, timeout=180):
    gate.wait(5)                      # giữ đoạn đầu lại để đo "trả về ngay"
    return orig_post(url, headers=headers, json=json, timeout=timeout)


R.requests.post = slow_post
t0 = _t.time()
start = asyncio.run(R.synthesize_chunks(R.SynthesizeRequest(email="a@x", text=LONG)))
elapsed = _t.time() - t0
check("I POST trả về NGAY, không chờ đọc xong", elapsed < 1.0, f"{elapsed:.2f}s")
check("I trả mã lượt + trạng thái running",
      start.get("task_id") and start.get("status") == "running" and start["total"] == len(plain), start.get("status"))
check("I lúc mới bắt đầu chưa đoạn nào xong", start["done"] == 0, start["done"])

st = asyncio.run(R.synthesize_chunks_status(start["task_id"]))
check("I hỏi được tiến độ", st["status"] == "running" and st["total"] == len(plain), st["status"])
gate.set()                            # thả cho luồng nền chạy
deadline = _t.time() + 30
while _t.time() < deadline:
    st = asyncio.run(R.synthesize_chunks_status(start["task_id"]))
    if st["status"] != "running":
        break
    _t.sleep(0.2)
check("I chạy xong trong luồng nền", st["status"] == "completed", st["status"])
check("I đếm đủ đoạn", st["done"] == len(plain) and st["failed"] == 0, (st["done"], st["failed"]))
check("I ghép được file cuối", st["joined"] and (R._output_dir() / st["joined"]).is_file(), st["joined"])
check("I mã lượt lạ → 404", _raises(lambda: asyncio.run(R.synthesize_chunks_status("khong-co"))) == 404)
R.requests.post = orig_post

# Bảng lượt không được phình mãi: máy chủ chạy nhiều ngày.
check("I có chặn trần bảng lượt", R._CHUNK_TASKS_MAX <= 50 and len(R._CHUNK_TASKS) <= R._CHUNK_TASKS_MAX,
      (R._CHUNK_TASKS_MAX, len(R._CHUNK_TASKS)))

# Giao diện phải HỎI TIẾN ĐỘ, không chờ một request.
check("I giao diện hỏi tiến độ", "async function pollChunks(" in html
      and "'/synthesize/chunks/' + encodeURIComponent(taskId)" in html)
check("I mất bảng lượt giữa đường thì nói thật, không hỏi vô hạn",
      "if (last) return last;" in html and "throw e;" in html)
_routes = io.open(EXT / "capcut_routes.py", encoding="utf-8").read()
check("I đường API không chặn event loop", "await asyncio.to_thread(_read_into" in _routes)
# Soi ĐÚNG thân hàm synthesize: /synthesize/chunks và /synthesize/retry vẫn phải
# cắt (đường tạo audio trực tiếp), chỉ đường API thì không.
import ast as _ast
_fn = next(n for n in _ast.walk(_ast.parse(_routes))
           if isinstance(n, _ast.AsyncFunctionDef) and n.name == "synthesize")
_body = _ast.get_source_segment(_routes, _fn) or ""
check("I đường API KHÔNG tự cắt đoạn", "split_text(req.text, PLAIN_CHUNK_CHARS)" not in _body,
      [l.strip() for l in _body.split("\n") if "PLAIN_CHUNK_CHARS" in l])
check("I đường API vẫn cắt cho ĐƯỜNG MỐC TỪ", "split_text(req.text, MARK_CHUNK_CHARS)" in _body)

print("=" * 70)
if failures:
    print(f"{len(failures)} FAIL / {checks}")
    for x in failures:
        print("  FAIL", x)
    sys.exit(1)
print(f"{checks}/{checks} PASS")
