# Kéo file từ máy vào canvas → Kho nguyên liệu: nhận audio, có ba kho mặc định,
# và route trả về ĐƯỜNG DẪN để canvas xem trước ngay tại chỗ thả.
#
# Chạy:  python tests/media_library_drop_test.py     (exit 0 = pass)
#
# VÌ SAO CÓ FILE NÀY
#   Ba chỗ, mỗi chỗ hỏng theo cách người dùng không đoán được:
#     1. Kho chỉ nhận ảnh/GIF/video, nên kéo một file mp3 vào là bị từ chối — mà
#        lời đọc là nguyên liệu hay dùng nhất sau ảnh.
#     2. Không có kho nào sẵn: đường kéo-thả từ canvas không có chỗ để rơi vào ở
#        lần đầu, và bắt người dùng tự tạo kho trước là một bước không ai đoán ra.
#     3. Route tải lên chỉ trả về TÊN file. Canvas cần ĐƯỜNG DẪN để xem trước
#        (node đọc qua /media?path=), không có thì client phải tự đoán đường dẫn
#        nội bộ của extension — đoán sai thì node hiện ô trống, không báo gì.
import asyncio
import io
import re as _re2
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

TMP = Path(tempfile.mkdtemp(prefix="medialib_drop_"))
import tubecli.config as cfg  # noqa: E402
cfg.DATA_DIR = TMP
# ext_data_path() đọc EXTENSIONS_DATA_DIR (hằng tính lúc import), nên đổi DATA_DIR
# là CHƯA đủ — thiếu dòng này thì test ghi file giả vào kho THẬT của người dùng.
cfg.EXTENSIONS_DATA_DIR = TMP / "extensions_data"

from tubecli.extensions.media_library import library as L  # noqa: E402
from tubecli.extensions.media_library import routes as MR  # noqa: E402

failures, checks = [], 0


def check(label, ok, detail=""):
    global checks
    checks += 1
    print(("  ok  " if ok else "  FAIL") + " " + label + (f"  ({detail})" if detail else ""))
    if not ok:
        failures.append(label)


# ── A. loại file ──────────────────────────────────────────────────────────
for name, want in (("a.mp3", "audio"), ("b.wav", "audio"), ("c.m4a", "audio"), ("d.flac", "audio"),
                   ("e.mp4", "video"), ("f.mov", "video"), ("g.gif", "gif"), ("h.png", "image"),
                   ("i.jpeg", "image")):
    check(f"A {name} → {want}", L.kind_of(name) == want, L.kind_of(name))
check("A audio nằm trong danh sách nhận", "x.mp3".endswith(L.ALL_EXT) and "x.opus".endswith(L.ALL_EXT))
# GIF về kho ẢNH: người dùng nghĩ nó là ảnh, không ai đi tìm kho "gif".
check("A GIF vào kho ảnh", L.default_collection_for("a.gif") == "image", L.default_collection_for("a.gif"))
check("A mp3 vào kho âm thanh", L.default_collection_for("a.mp3") == "audio")
check("A mp4 vào kho video", L.default_collection_for("a.mp4") == "video")

# ── B. ba kho mặc định, tạo kiểu "thiếu thì thêm" ─────────────────────────
made = L.ensure_defaults()
check("B tạo đủ ba kho", sorted(c["id"] for c in made) == ["audio", "image", "video"],
      [c["id"] for c in made])
check("B kho có tên người đọc được", all(c.get("name") for c in made), [c.get("name") for c in made])
# Tên kho phải theo NGÔN NGỮ máy chủ. Ghi cứng một thứ tiếng là sai với sản phẩm 9
# ngôn ngữ: người để giao diện tiếng Nhật vẫn thấy kho tên "Âm thanh".
import json as _json  # noqa: E402
_locdir = ROOT / "tubecli" / "extensions" / "media_library" / "locales"
for _lang in ("en", "vi", "zh", "zh-TW", "ja", "ko", "es", "tr", "ru"):
    _d = _json.load(io.open(_locdir / f"{_lang}.json", encoding="utf-8-sig"))
    _miss = [c for c in L.DEFAULT_COLLECTION_IDS
             if not _d.get(f"media.default.{c}.name") or not _d.get(f"media.default.{c}.desc")]
    check(f"B locale {_lang} có tên+mô tả ba kho", not _miss, _miss)
cfg.get_language = lambda: "ja"
check("B tên kho theo ngôn ngữ máy chủ", L._default_labels()["audio"][0] == "音声",
      L._default_labels()["audio"][0])
cfg.get_language = lambda: "vi"
# Thiếu câu dịch thì VẪN tạo được kho, không ném — id làm tên tạm.
check("B thiếu câu dịch vẫn có tên tạm", all(L._default_labels()[c][0] for c in L.DEFAULT_COLLECTION_IDS))
# Gọi lại KHÔNG được ghi đè: Chợ gọi on_enable mỗi lần cài, ghi đè một lần là mất
# tên kho khách đã sửa.
L.rename("image", name="Ảnh của tôi")
again = L.ensure_defaults()
check("B gọi lại không tạo thêm", len(L.list_all()) == 3, len(L.list_all()))
check("B gọi lại KHÔNG ghi đè tên khách đã sửa",
      L.get("image")["name"] == "Ảnh của tôi", L.get("image")["name"])
check("B trả về kho đang có", any(c["id"] == "image" for c in again))

# ── C. tải lên trả về ĐƯỜNG DẪN ───────────────────────────────────────────
class _Up:
    """UploadFile giả, chỉ cần filename + read()."""

    def __init__(self, name, blob):
        self.filename = name
        self._b = blob

    async def read(self):
        return self._b


MP3 = b"ID3\x03\x00" + b"\x00" * 4000
res = asyncio.run(MR.upload_file("audio", _Up("Lời đọc mở đầu.mp3", MP3)))
check("C nhận file mp3", res.get("ok") is True and res.get("kind") == "audio", res)
check("C trả về đường dẫn thật", res.get("path") and os.path.isfile(res["path"]), res.get("path"))
check("C đường dẫn nằm trong thư mục tạm của test", str(TMP) in str(res.get("path")), res.get("path"))
check("C trả về kho + số byte", res.get("collection") == "audio" and res.get("bytes") == len(MP3), res)
check("C tên file bị làm sạch", " " not in res["name"] and res["name"].endswith(".mp3"), res["name"])

# Trùng tên thì thêm số, KHÔNG ghi đè — ghi đè là cách nhanh nhất để người dùng
# mất một tấm mà không biết.
res2 = asyncio.run(MR.upload_file("audio", _Up("Lời đọc mở đầu.mp3", MP3)))
check("C trùng tên → tên mới", res2["name"] != res["name"], (res["name"], res2["name"]))
check("C cả hai file còn trên đĩa", os.path.isfile(res["path"]) and os.path.isfile(res2["path"]))

# Loại không nhận thì từ chối rõ ràng.
try:
    asyncio.run(MR.upload_file("audio", _Up("virus.exe", b"MZ" + b"\x00" * 900)))
    check("C từ chối loại lạ", False, "không ném")
except Exception as e:
    check("C từ chối loại lạ", getattr(e, "status_code", 0) == 400, getattr(e, "detail", e))

# ── D. route /defaults cho canvas ─────────────────────────────────────────
d = MR.defaults()
check("D trả ba kho", len(d["collections"]) == 3, len(d["collections"]))
check("D có bảng loại → kho", d["map"]["audio"] == "audio" and d["map"]["gif"] == "image", d["map"])
check("D có bảng đuôi file", ".mp3" in d["ext"]["audio"] and ".mp4" in d["ext"]["video"], list(d["ext"]))
# Canvas dùng bảng này để biết mp3 rơi vào kho nào: mọi đuôi kho NHẬN đều phải có
# mặt, nếu không file đó lặng lẽ rơi vào kho ảnh.
allext = {e for v in d["ext"].values() for e in v}
check("D bảng đuôi phủ hết loại được nhận", set(L.ALL_EXT) == allext,
      sorted(set(L.ALL_EXT) ^ allext))

# ── D2. chữ nhắc loại file phải nói cả AUDIO ─────────────────────────────
# Kho nhận audio rồi mà câu nhắc vẫn ghi "ảnh, GIF hoặc video" thì người dùng đọc
# xong không dám kéo file mp3 vào — tính năng có mà như không.
for _lang in ("en", "vi", "zh", "zh-TW", "ja", "ko", "es", "tr", "ru"):
    _d = _json.load(io.open(_locdir / f"{_lang}.json", encoding="utf-8-sig"))
    for _k in ("media.count.audio", "media.kind.audio", "media.kindtag.audio"):
        check(f"D2 {_lang} có {_k}", _k in _d)
_app = io.open(ROOT / "tubecli" / "extensions" / "media_library" / "static" / "app.js", encoding="utf-8").read()
check("D2 nhãn loại có audio", "audio: 'media.kindtag.audio'" in _app)
check("D2 kho chưa có bìa hiện biểu tượng theo loại", "function kindGlyph(" in _app
      and "rail-glyph" in _app)
_css = io.open(ROOT / "tubecli" / "extensions" / "media_library" / "static" / "app.css", encoding="utf-8").read()
check("D2 có CSS cho biểu tượng đó", ".rail-glyph" in _css)

# ── E. on_enable tạo kho, và không ném khi kho đã có ─────────────────────
src = io.open(ROOT / "tubecli" / "extensions" / "media_library" / "extension.py", encoding="utf-8").read()
check("E on_enable gọi ensure_defaults", "library.ensure_defaults()" in src)
check("E ensure_defaults nằm SAU khi import library",
      src.index("from . import library") < src.index("library.ensure_defaults()"))
check("E lỗi tạo kho không làm hỏng lượt bật", "except Exception" in src.split("ensure_defaults()")[1][:120])

# ── F. giao diện cloud: nghe sự kiện thả, đặt node đúng chỗ ──────────────
CLOUD = ROOT.parent / "tubecli-cloud"
if not CLOUD.is_dir():
    print(f"(bỏ F: không thấy repo cloud ở {CLOUD})")
else:
    fb = io.open(CLOUD / "components" / "flow" / "FlowBuilder.js", encoding="utf-8").read()
    check("F canvas nghe drop + dragover", "onDrop={onCanvasDropFiles}" in fb
          and "onDragOver={onCanvasDragOver}" in fb)
    # preventDefault ở CẢ HAI: thiếu ở dragover thì trình duyệt vẫn mở file và mất
    # cả trang canvas đang làm.
    check("F chặn hành vi mặc định của trình duyệt",
          fb.count("ev.preventDefault()") >= 2 and "dropEffect = 'copy'" in fb)
    check("F đặt node tại ĐÚNG chỗ thả",
          "rf.screenToFlowPosition({ x: ev.clientX, y: ev.clientY })" in fb)
    check("F đọc toạ độ TRƯỚC khi await", fb.index("const at = rf.screenToFlowPosition")
          < fb.index("await uploadToLibrary"))
    check("F xem được ngay tại chỗ (mode open)", "mode: 'open'" in fb)
    # Tiền tố route THẬT là /api/v1/media (không phải /api/v1/media-library) —
    # đoán sai tiền tố là 404 và node hiện "Not Found" mà không ai biết vì sao.
    _prefix = _re2.search(r'APIRouter\(prefix="([^"]+)"',
                          io.open(ROOT / "tubecli" / "extensions" / "media_library" / "routes.py",
                                  encoding="utf-8").read()).group(1)
    check("F tiền tố route đọc được", _prefix == "/api/v1/media", _prefix)
    check("F cloud gọi ĐÚNG tiền tố", f"'{_prefix}/defaults'" in fb, _prefix)
    check("F cloud tải lên ĐÚNG tiền tố",
          _prefix + "/collections/${encodeURIComponent(cid)}/files" in fb, _prefix)
    check("F không còn tiền tố đoán sai", "/api/v1/media-library/" not in fb,
          [l.strip() for l in fb.split(chr(10)) if "/api/v1/media-library/" in l])
    check("F chưa có tunnel thì nói rõ", "flow.drop.noServer" in fb)
    # Node đặt NGAY lúc thả, TRƯỚC khi tải lên: thấy chỗ mình vừa thả có gì.
    check("F đặt node trước khi tải lên",
          fb.index("const ids = files.map(") < fb.index("await uploadToLibrary"))
    check("F node placeholder mang cờ đang tải", "uploading: true, upload_pct: 0" in fb)
    check("F addNode trả id để bơm tiến độ", "return id;" in fb
          and "updateNode(nodeId, { upload_pct: pct })" in fb)
    check("F xong thì node tự đổi sang file thật",
          "uploading: false, upload_pct: 100" in fb and "path: d.path" in fb)
    # Hỏng thì GIỮ node kèm lý do: xoá đi thì không biết file nào trượt.
    check("F hỏng thì giữ node kèm lý do", "upload_error: String(e.message" in fb)
    # Tiến độ phải nằm TRONG node, không phải dải ở mép trên canvas.
    nd = io.open(CLOUD / "components" / "flow" / "nodes.js", encoding="utf-8").read()
    check("F node vẽ thanh phần trăm", "data.uploading || data.upload_error" in nd
          and "flow.node.uploadingPct" in nd)
    check("F node hỏng hiện lý do ngay trong node", "data.upload_error}</div>" in nd)
    check("F KHÔNG còn dải tiến độ ở mép trên canvas", "dropBusy.pct" not in fb)
    KEYS = ("flow.drop.hint", "flow.drop.uploading", "flow.drop.noPath", "flow.drop.noServer",
            "flow.node.uploadingPct")
    for lang in ("en", "vi", "zh", "zh-TW", "ja", "ko", "es", "tr", "ru"):
        loc = io.open(CLOUD / "lib" / "locales" / f"{lang}.js", encoding="utf-8").read()
        miss = [k for k in KEYS if f"'{k}':" not in loc]
        check(f"F locale {lang} đủ khoá", not miss, miss)

shutil.rmtree(TMP, ignore_errors=True)
print("=" * 70)
if failures:
    print(f"{len(failures)} FAIL / {checks}")
    sys.exit(1)
print(f"{checks}/{checks} PASS")
