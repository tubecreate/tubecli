"""Test Media Library: bộ sưu tập, tệp, ba kiểu bốc, API, và bộ từ điển i18n.

Chạy: python tests/media_library_test.py
"""
import io
import json
import os
import re
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tubecli.extensions.media_library import library  # noqa: E402

_TMP = tempfile.mkdtemp(prefix="media_lib_test_")
library.data_dir = lambda: _TMP  # type: ignore

FAILS, COUNT = [], [0]


def check(cond, msg):
    COUNT[0] += 1
    if not cond:
        FAILS.append(msg)
        print(f"  FAIL {msg}")


def group(n):
    print(f"\n== {n}")


def png(w=40, h=30):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (180, 30, 30)).save(buf, "PNG")
    return buf.getvalue()


# ── A. định danh ───────────────────────────────────────────────────────
group("A. safe_id")
check(library.safe_id("Kho ảnh nền đỏ") == "kho_anh_nen_do", "bo dau tieng Viet")
check(library.safe_id("Đồ hoạ 2!") == "do_hoa_2", "xu ly d gach ngang")
check(library.safe_id("") == "collection", "rong co duong lui")
# Tên phi Latinh rụng hết khi lọc ASCII: đường lui phải là từ tiếng Anh, không
# phải "kho" — sản phẩm tên tiếng Anh mà mã kho ra tiếng Việt là lọt ngôn ngữ.
check(library.safe_id("キャラクター画像") == "collection", "ten Nhat -> duong lui tieng Anh")
check(library.safe_id("Медиа") == "collection", "ten Nga -> duong lui tieng Anh")
_jp = library.create("キャラクター画像")
check(_jp["id"].startswith("collection"), f"tao kho ten Nhat: id tieng Anh, khong phai kho_N: {_jp['id']}")
library.delete(_jp["id"])
check(library.kind_of("a.PNG") == "image", "nhan dang anh")
check(library.kind_of("b.gif") == "gif", "nhan dang gif")
check(library.kind_of("c.mp4") == "video", "nhan dang video")

# ── B. bộ sưu tập ──────────────────────────────────────────────────────
group("B. bo suu tap")
c = library.create("Kho avatar", description="chân dung cắt sẵn")
check(c["id"] == "kho_avatar", f"id sinh tu ten: {c['id']}")
check(os.path.isdir(library.collection_dir(c["id"])), "tao thu muc")

c2 = library.create("Kho avatar")
check(c2["id"] == "kho_avatar_2", f"trung ten thi them so: {c2['id']}")

r = library.rename(c["id"], name="Kho chân dung")
check(r["name"] == "Kho chân dung", "doi ten hien thi")
check(os.path.isdir(os.path.join(_TMP, "kho_avatar")),
      "doi ten KHONG dung toi thu muc")
check(library.rename("khong_co", name="x") is None, "doi ten kho la tra None")

check(len(library.list_all()) == 2, "liet ke duoc")
check(library.get("khong_co") is None, "kho khong co tra None")

# ── C. tệp ─────────────────────────────────────────────────────────────
group("C. tep")
for n in ("b.png", "a.png", "clip.mp4", "anim.gif"):
    blob = png() if n.endswith(".png") else b"\x00" * 100
    library.add_file(c["id"], n, blob)
names = [f["name"] for f in library.list_files(c["id"])]
check(names == ["a.png", "anim.gif", "b.png", "clip.mp4"],
      f"thu tu on dinh theo ten: {names}")

info = library.get(c["id"])
check(info["count"] == 4, f"dem dung: {info['count']}")
check(info["kinds"] == {"image": 2, "gif": 1, "video": 1}, f"dem theo loai: {info['kinds']}")
check(info["cover"] == "a.png", "anh bia la tep dau")

dup = library.add_file(c["id"], "a.png", png())
check(dup != "a.png", f"trung ten thi doi ten chu khong ghi de: {dup}")

check(library.file_path(c["id"], "a.png"), "lay duoc duong dan")
check(library.file_path(c["id"], "../../etc/passwd") is None, "chan duong dan la")
check(library.delete_file(c["id"], dup), "xoa duoc tep")
check(not library.delete_file(c["id"], "khong_co.png"), "xoa tep la tra False")

# nhập từ đĩa
src = os.path.join(_TMP, "ngoai.png")
with open(src, "wb") as f:
    f.write(png())
got = library.import_path(c["id"], src)
check(got == "ngoai.png", f"chep tu dia: {got}")
check(library.import_path(c["id"], os.path.join(_TMP, "khong_co.png")) is None,
      "chep tep khong co tra None")

# ── D. bốc ─────────────────────────────────────────────────────────────
group("D. boc")
imgs = [f["name"] for f in library.list_files(c["id"]) if f["kind"] == "image"]
picks = [os.path.basename(library.pick(c["id"], "cycle", kind="image")[0])
         for _ in range(len(imgs))]
check(sorted(picks) == sorted(imgs), f"cycle di het roi moi lap: {picks}")
check(os.path.basename(library.pick(c["id"], "cycle", kind="image")[0]) == picks[0],
      "cycle quay dung cho")

before = library.peek_cycle(c["id"])
library.pick(c["id"], "cycle", commit=False)
check(library.peek_cycle(c["id"]) == before, "xem truoc khong doi con tro")

p, why = library.pick(c["id"], "ai", chosen="b.png")
check(os.path.basename(p) == "b.png", f"AI chon dung ten: {why}")
p, why = library.pick(c["id"], "ai", chosen="khong_co.png")
check(p and "fell back" in why, f"AI chon ten la thi co duong lui: {why}")

vids = [os.path.basename(library.pick(c["id"], "random", kind="video")[0])
        for _ in range(4)]
check(set(vids) == {"clip.mp4"}, f"loc theo loai: {set(vids)}")

check(library.pick("khong_co_that", "random") == ("", "collection is empty"),
      "kho khong co tra rong, khong no")
check(library.pick(c2["id"], "random", kind="video")[1] == "collection has no video",
      "noi ro thieu loai gi")

# ── E. xoá kho ─────────────────────────────────────────────────────────
group("E. xoa kho")
d = library.create("Tam")
library.add_file(d["id"], "x.png", png())
path = library.collection_dir(d["id"])
check(library.delete(d["id"]), "xoa duoc")
check(not os.path.exists(path), "xoa ca thu muc")
check(not library.delete("khong_co"), "xoa kho la tra False")

e = library.create("Giu tep")
library.add_file(e["id"], "y.png", png())
epath = library.collection_dir(e["id"])
library.delete(e["id"], with_files=False)
check(os.path.exists(epath), "keep_files thi giu lai tep tren dia")
shutil.rmtree(epath, ignore_errors=True)

# ── F. API ─────────────────────────────────────────────────────────────
group("F. API")
try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from tubecli.extensions.media_library import routes as R
    R.library.data_dir = lambda: _TMP
    app = FastAPI()
    app.include_router(R.router)
    app.include_router(R.page_router)
    cl = TestClient(app)
    B = "/api/v1/media"

    r = cl.get(f"{B}/collections")
    check(r.status_code == 200 and r.json()["stats"]["collections"] >= 2,
          "GET /collections")

    r = cl.post(f"{B}/collections", json={"name": "Qua API"})
    check(r.status_code == 200, f"POST /collections: {r.status_code}")
    cid = r.json()["collection"]["id"]
    check(cl.post(f"{B}/collections", json={"name": ""}).status_code == 400,
          "ten rong -> 400")

    r = cl.post(f"{B}/collections/{cid}/files",
                files={"file": ("z.png", png(), "image/png")})
    check(r.status_code == 200 and r.json()["kind"] == "image",
          f"tai tep len: {r.text[:80]}")
    r = cl.post(f"{B}/collections/{cid}/files",
                files={"file": ("z.exe", b"MZ", "application/octet-stream")})
    check(r.status_code == 400, "tu choi dinh dang la")
    check(cl.post(f"{B}/collections/khong_co/files",
                  files={"file": ("z.png", png(), "image/png")}).status_code == 404,
          "kho khong co -> 404")

    r = cl.get(f"{B}/collections/{cid}")
    check(r.status_code == 200 and len(r.json()["files"]) == 1, "GET mot kho")
    check(cl.get(f"{B}/collections/{cid}/files/z.png").status_code == 200,
          "phuc vu tep")

    r = cl.post(f"{B}/collections/{cid}/pick", json={"mode": "random"})
    check(r.json()["file"] == "z.png", f"boc qua API: {r.json()}")

    check(cl.put(f"{B}/collections/{cid}", json={"name": "Doi ten"}).status_code == 200,
          "PUT doi ten")
    check(cl.delete(f"{B}/collections/{cid}/files/z.png").status_code == 200, "xoa tep")
    check(cl.delete(f"{B}/collections/{cid}").status_code == 200, "xoa kho")
    check(cl.get(f"{B}/collections/{cid}").status_code == 404, "xoa roi thi 404")

    h = cl.get(f"{B}/health").json()
    check(h["ok"] and "dir" in h, f"health: {h}")

    # Trang: TubeCLI khong tu phuc vu static, extension phai tu khai route
    r = cl.get("/media-library")
    check(r.status_code == 200 and "text/html" in r.headers.get("content-type", ""),
          f"GET /media-library tra HTML: {r.status_code}")
    check("__ASSET_VER__" not in r.text, "da thay version vao HTML")
    check("no-store" in r.headers.get("cache-control", ""), "HTML khong duoc cache")
    for asset in ("app.css", "app.js"):
        rr = cl.get(f"/media-library-static/{asset}")
        check(rr.status_code == 200, f"phuc vu {asset}: {rr.status_code}")
    check(cl.get("/media-library-static/../routes.py").status_code == 404,
          "chan thoat khoi thu muc static")
except ImportError as ex:
    print(f"  (bo qua: {ex})")

# ── G. i18n ────────────────────────────────────────────────────────────
# Trang tự dịch bằng /api/v1/i18n/{lang}, mà endpoint đó chỉ TRỘN khoá TOP-LEVEL
# của mọi extension lại một chỗ. Nên ba thứ phải đúng, không thì hỏng im lặng:
# từ điển phải phẳng, khoá phải mang tiền tố riêng, và bản dịch nào cũng phải
# đủ khoá như en.json.
group("G. i18n")

EXT_DIR = os.path.join(ROOT, "tubecli", "extensions", "media_library")
LOC_DIR = os.path.join(EXT_DIR, "locales")
LANGS = ["en", "vi", "zh", "zh-TW", "ja", "ko", "es", "tr", "ru"]

locales = {}
for lang in LANGS:
    path = os.path.join(LOC_DIR, f"{lang}.json")
    data = None
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as ex:
        print(f"  doc {lang}.json hong: {ex}")
    locales[lang] = data
    check(isinstance(data, dict) and bool(data), f"{lang}.json co that va la JSON dict")

en = locales.get("en") or {}
check(len(en) > 100, f"en.json day du: {len(en)} khoa")

# Thêm một ngôn ngữ mà quên khai vào LANGS thì lộ ra ở đây.
extra_files = sorted(x for x in os.listdir(LOC_DIR)
                     if x.endswith(".json") and x[:-5] not in LANGS)
check(not extra_files, f"khong co tep locale la: {extra_files}")

for lang in LANGS:
    d = locales.get(lang)
    if not isinstance(d, dict):
        continue

    # Lồng object vào là T('media.x.y') tra không ra: endpoint gộp chỉ lấy khoá
    # ngoài cùng, phần bên trong không bao giờ tới được trang.
    nested = [k for k, v in d.items() if not isinstance(v, str)]
    check(not nested, f"{lang}.json phang, moi gia tri la chuoi: {nested[:5]}")

    # Bảng điều khiển vẽ thẻ extension bằng T(ext.name) — khoá này PHẢI là chuỗi.
    check(isinstance(d.get("media_library"), str),
          f"{lang}.json co khoa 'media_library' kieu chuoi")

    missing = [k for k in en if k not in d]
    surplus = [k for k in d if k not in en]
    check(not missing, f"{lang}.json khong thieu khoa ({len(missing)}): {missing[:5]}")
    check(not surplus, f"{lang}.json khong thua khoa ({len(surplus)}): {surplus[:5]}")

    # Dịch mà đánh rơi {name} là câu mất luôn tên tệp, mà không ai thấy lỗi.
    bad_ph = []
    for k, v in d.items():
        if k in en and isinstance(v, str):
            if (sorted(set(re.findall(r"\{(\w+)\}", v)))
                    != sorted(set(re.findall(r"\{(\w+)\}", en[k])))):
                bad_ph.append(k)
    check(not bad_ph, f"{lang}.json giu du cho trong: {bad_ph[:5]}")

# Tiền tố riêng: từ điển gộp chung một rổ với mọi extension khác.
odd = sorted(k for k in en if k != "media_library" and not k.startswith("media."))
check(not odd, f"moi khoa giao dien mang tien to 'media.': {odd[:5]}")

# Khoá trang dùng mà en.json không có = màn hình hiện thẳng tên khoá ra.
with open(os.path.join(EXT_DIR, "static", "index.html"), encoding="utf-8") as fh:
    _html = fh.read()
html_keys = set(re.findall(r'data-i18n(?:-placeholder|-title|-aria-label)?="([^"]+)"', _html))
check(len(html_keys) >= 30, f"index.html gan du data-i18n: {len(html_keys)}")
check(all(k in en for k in html_keys),
      f"khoa data-i18n deu co trong en.json: {sorted(k for k in html_keys if k not in en)[:5]}")

with open(os.path.join(EXT_DIR, "static", "app.js"), encoding="utf-8") as fh:
    _appjs = fh.read()
js_keys = set(re.findall(r"\bT\(\s*'([^']+)'", _appjs))
check(len(js_keys) >= 100, f"app.js goi T() du cho: {len(js_keys)}")
check(all(k in en for k in js_keys),
      f"khoa T() deu co trong en.json: {sorted(k for k in js_keys if k not in en)[:5]}")

# Tên hiển thị đã sang tiếng Anh, tên máy vẫn là media_library.
check(en.get("media_library") == "Media Library", "en.json goi ten 'Media Library'")
from tubecli.extensions.media_library.extension import extension_instance as _ext  # noqa: E402
check(_ext.name == "media_library", "ten may khong doi")
check(getattr(_ext, "display_name", "") == "Media Library",
      f"display_name la tieng Anh: {getattr(_ext, 'display_name', '')!r}")

shutil.rmtree(_TMP, ignore_errors=True)
print(f"\n{COUNT[0] - len(FAILS)}/{COUNT[0]} passed")
if FAILS:
    print("FAILED:")
    for m in FAILS:
        print(" -", m)
    sys.exit(1)
print("OK")
