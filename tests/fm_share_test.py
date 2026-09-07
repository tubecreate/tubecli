# -*- coding: utf-8 -*-
"""File Manager — chia sẻ công khai (/share, /s/<token>) + menu nền thư mục + dán vào Drive.

Chạy: python tests/fm_share_test.py
"""
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
_TMP_ROOT = os.path.join(os.path.dirname(HERE), "_tmp_tests")   # %TEMP% nằm trong vùng bị chặn
os.makedirs(_TMP_ROOT, exist_ok=True)
TMP = tempfile.mkdtemp(prefix="fm_share_", dir=_TMP_ROOT)
os.environ["TUBECLI_DATA_DIR"] = os.path.join(TMP, "data")
os.makedirs(os.environ["TUBECLI_DATA_DIR"], exist_ok=True)

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
import tubecli.extensions.file_manager.routes as R  # noqa: E402

COUNT = [0]
FAILS = []


def check(cond, msg):
    COUNT[0] += 1
    print(("  ok  " if cond else "  FAIL") + " " + msg)
    if not cond:
        FAILS.append(msg)


R._shortcuts_file = lambda: os.path.join(TMP, "shortcuts.json")     # shares.json nằm cạnh
app = FastAPI()
for r in R.router:
    app.include_router(r)
c = TestClient(app)
P = R.router_fm.prefix

folder = os.path.join(TMP, "media"); os.makedirs(folder)
png = os.path.join(folder, "ảnh bìa.png")
from PIL import Image  # noqa: E402
Image.new("RGB", (64, 32), (255, 0, 0)).save(png)
txt = os.path.join(folder, "notes.txt"); open(txt, "w", encoding="utf-8").write("hello share")
big = os.path.join(folder, "clip.mp4"); open(big, "wb").write(b"\x00" * 200000)

# ── tạo link ──
r = c.post(P + "/share", json={"path": png, "expires_days": 0})
check(r.status_code == 200 and r.json().get("created") is True, f"tạo link cho file: {r.status_code} {r.text[:120]}")
sh = r.json()["share"]
tok = sh["token"]
check(len(tok) >= 20 and sh["url_path"] == "/s/" + tok and sh["expires"] is None and sh["alive"], f"token dài, url_path, không hạn: {sh}")
r2 = c.post(P + "/share", json={"path": png})
check(r2.json()["created"] is False and r2.json()["share"]["token"] == tok, "chia sẻ lại cùng file → trả link cũ")
r3 = c.post(P + "/share", json={"path": png, "renew": True, "expires_days": 7})
tok2 = r3.json()["share"]["token"]
check(r3.json()["created"] is True and tok2 != tok and abs(r3.json()["share"]["expires"] - (time.time() + 7 * 86400)) < 120, "renew → token mới, hạn 7 ngày")
check(c.get("/s/" + tok).status_code == 404, "token cũ chết sau renew")
tok = tok2

r = c.post(P + "/share", json={"path": folder})
check(r.status_code == 400, f"thư mục → 400 ({r.status_code})")
r = c.post(P + "/share", json={"path": os.path.join(folder, "khong_co.png")})
check(r.status_code in (400, 403, 404), f"file không có → lỗi ({r.status_code})")
blocked = [p for p in ("/etc/hosts", "C:\\Windows\\System32\\drivers\\etc\\hosts") if os.path.isfile(p)]
if blocked:
    r = c.post(P + "/share", json={"path": blocked[0]})
    check(r.status_code == 403, f"đường dẫn bị chặn → 403 ({r.status_code})")

r = c.get(P + "/share", params={"path": png})
check(r.json()["share"]["token"] == tok, "GET /share?path → link của file")
r = c.get(P + "/share", params={"path": txt})
check(r.json()["share"] is None, "file chưa chia sẻ → null")

# ── trang công khai ──
r = c.get("/s/" + tok, headers={"Accept-Language": "vi-VN,vi;q=0.9"})
check(r.status_code == 200 and "text/html" in r.headers.get("content-type", "") and "ảnh bìa.png" in r.text and "Tải xuống" in r.text
      and "/s/" + tok + "/raw" in r.text and TMP not in r.text, "trang chia sẻ (vi): tên file, nút tải, xem trước, KHÔNG lộ đường dẫn")
r = c.get("/s/" + tok, headers={"Accept-Language": "en-US"})
check("Download" in r.text and "noindex" in r.text, "trang chia sẻ (en) + noindex")
r = c.get("/s/" + tok + "/raw")
check(r.status_code == 200 and r.headers["content-type"].startswith("image/png") and r.content[:8] == b"\x89PNG\r\n\x1a\n"
      and "inline" in r.headers.get("content-disposition", ""), f"raw ảnh: inline image/png ({r.headers.get('content-type')})")
r = c.get("/s/" + tok + "/download")
check(r.status_code == 200 and "attachment" in r.headers.get("content-disposition", "") and len(r.content) > 50, "download: attachment")
r = c.get(P + "/share", params={"path": png})
check(r.json()["share"]["downloads"] == 1, "đếm lượt tải")

# video: Range
r = c.post(P + "/share", json={"path": big}); vtok = r.json()["share"]["token"]
r = c.get("/s/" + vtok + "/raw", headers={"Range": "bytes=0-99"})
check(r.status_code == 206 and len(r.content) == 100 and r.headers.get("content-range", "").startswith("bytes 0-99/"), f"video raw có Range 206 ({r.status_code})")
r = c.head("/s/" + vtok + "/raw")
check(r.status_code == 200 and r.headers.get("accept-ranges") == "bytes", "HEAD raw: accept-ranges")

# file không phải media: raw → tải về
r = c.post(P + "/share", json={"path": txt}); ttok = r.json()["share"]["token"]
r = c.get("/s/" + ttok + "/raw")
check(r.status_code == 200 and "attachment" in r.headers.get("content-disposition", "") and r.content == b"hello share", "raw của .txt → attachment octet-stream")

# ── hết hạn / thu hồi / mất file ──
items = R._load_shares()
for it in items:
    if it["token"] == ttok:
        it["expires"] = time.time() - 10
R._save_shares(items)
check(c.get("/s/" + ttok).status_code == 404 and c.get("/s/" + ttok + "/download").status_code == 404, "hết hạn → 404 cả trang lẫn tải")
r = c.delete(P + "/share/" + vtok)
check(r.status_code == 200 and r.json()["removed"] is True and c.get("/s/" + vtok + "/raw").status_code == 404, "thu hồi → link chết ngay")
os.remove(png)
check(c.get("/s/" + tok).status_code == 404, "file bị xoá → 404")
check(c.get("/s/khong-co-token").status_code == 404 and c.get("/s/../etc").status_code in (404, 400), "token lạ / lách đường dẫn → 404")
r = c.get(P + "/shares")
check(r.status_code == 200 and isinstance(r.json()["shares"], list), "GET /shares liệt kê")

# ── server.py miễn đăng nhập /s/ ──
srv = open(os.path.join(os.path.dirname(HERE), "tubecli", "api", "server.py"), encoding="utf-8").read()
check('"/s/"' in srv.split("_AUTH_EXEMPT_PREFIX")[1].split("\n")[0], "server.py: /s/ trong _AUTH_EXEMPT_PREFIX")
check(any(getattr(x, "prefix", "") == "" for x in R.router) and len(R.router) >= 3, "router_public không tiền tố nằm trong danh sách router")

# ── giao diện: menu nền + hộp chia sẻ + dán Drive ──
ST = os.path.join(os.path.dirname(HERE), "tubecli", "extensions", "file_manager", "static")
html = open(os.path.join(ST, "file_manager.html"), encoding="utf-8").read()
js = open(os.path.join(ST, "file_manager.js"), encoding="utf-8").read()
acts = open(os.path.join(ST, "fm_actions.js"), encoding="utf-8").read()
drv = open(os.path.join(ST, "fm_drive.js"), encoding="utf-8").read()
check('id="bgContextMenu"' in html and 'id="bgPaste"' in html and 'data-fm-action="bg-upload"' in html, "HTML: menu nền thư mục có Dán/Tải lên")
check('id="fm-share"' in html and 'data-fm-action="share"' in html and 'data-fm-file-only' in html and 'id="fm-drive-bgmenu"' in html, "HTML: hộp chia sẻ + mục Chia sẻ (chỉ file) + menu nền Drive")
check("showBgMenu(" in js and "openShare(" in js and "createShare(" in js and "revokeShare(" in js and "data-fm-file-only" in js, "JS: menu nền + chia sẻ")
check("'share': actShare" in acts and "'bg-upload': actBgUpload" in acts, "fm_actions: đăng ký share/bg-upload")
check("'dmenu-paste-server'" in drv and "pasteFromServer" in drv and "'/upload'" in drv, "fm_drive: dán từ máy chủ = /drive/upload")
for lang in ("en", "vi", "es", "ja", "ko", "ru", "tr", "zh", "zh-TW"):
    with open(os.path.join(os.path.dirname(ST), "locales", lang + ".json"), encoding="utf-8") as f:
        d = json.load(f)
    check(all(k in d for k in ("fm.browse.share", "fm.share.create", "fm.share.revoke", "fm.drive.paste_server")), f"locale {lang} có khoá chia sẻ")

shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{COUNT[0] - len(FAILS)}/{COUNT[0]} passed")
if FAILS:
    print("FAILED:")
    for m in FAILS:
        print(" -", m)
    sys.exit(1)
print("OK")
