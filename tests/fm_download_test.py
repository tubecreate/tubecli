# -*- coding: utf-8 -*-
"""File Manager: GET /download — tải mọi loại file, thư mục và nhiều mục thành zip (14/9/2026).

Vì sao: /raw chỉ phục vụ ảnh/video/PDF (415 với .json/.py…) và ghi inline để xem trước; chọn
nhiều cần tải MỌI loại file và cả thư mục. Zip dựng trực tiếp (ZIP_STORED, không file tạm).

Kiểm qua TestClient thật:
  A. một file thường → 200, attachment kèm tên (UTF-8), đúng byte, mọi đuôi (.json)
  B. thư mục → zip đúng cây (bỏ symlink nếu tạo được), tên zip = tên thư mục
  C. nhiều mục (file + thư mục) → một zip, tên trùng thêm (2)
  D. không có → 404; Sec-Fetch-Site cross-site → 403; thiếu path → 422
  E. _zip_stream nhả theo khúc (generator), ZIP hợp lệ với testzip()

Run:  python tests/fm_download_test.py
"""
import io
import json
import os
import shutil
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass
_TMP_ROOT = os.path.join(os.path.dirname(HERE), "_tmp_tests")   # %TEMP% nằm trong vùng bị chặn
os.makedirs(_TMP_ROOT, exist_ok=True)
TMP = tempfile.mkdtemp(prefix="fm_dl_", dir=_TMP_ROOT)
os.environ["TUBECLI_DATA_DIR"] = os.path.join(TMP, "data")
os.makedirs(os.environ["TUBECLI_DATA_DIR"], exist_ok=True)

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
import tubecli.extensions.file_manager.routes as R  # noqa: E402

COUNT = [0]
FAILS = []


def check(cond, msg, detail=""):
    COUNT[0] += 1
    print(("  ok  " if cond else "  FAIL") + " " + msg + ("" if cond else f" — {str(detail)[:200]}"))
    if not cond:
        FAILS.append(msg)


app = FastAPI()
for r in R.router:
    app.include_router(r)
c = TestClient(app)
P = "/api/v1/files"

root = os.path.join(TMP, "kho")
os.makedirs(os.path.join(root, "tập 1", "sub"))
files = {
    os.path.join(root, "ghi chú.json"): b'{"a": 1}',
    os.path.join(root, "video.mp4"): os.urandom(70000),
    os.path.join(root, "tập 1", "a.txt"): b"aaa",
    os.path.join(root, "tập 1", "sub", "b.bin"): os.urandom(3000),
}
for p, body in files.items():
    with open(p, "wb") as f:
        f.write(body)
# thư mục thứ hai có file trùng tên với thư mục 1 để kiểm (2)
os.makedirs(os.path.join(root, "khác"))
with open(os.path.join(root, "khác", "video.mp4"), "wb") as f:
    f.write(b"xx")

print("── A. một file thường ──────────────────────────────────────")
r = c.get(P + "/download", params={"path": os.path.join(root, "ghi chú.json")})
check(r.status_code == 200 and r.content == b'{"a": 1}', "file .json → 200 đúng byte (/raw từng 415)", (r.status_code, r.content[:40]))
cd = r.headers.get("content-disposition", "")
check(cd.startswith("attachment;") and "ghi%20ch%C3%BA.json" in cd, "attachment kèm tên UTF-8", cd)
check(r.headers.get("content-type", "").startswith("application/octet-stream") and r.headers.get("x-content-type-options") == "nosniff", "octet-stream + nosniff", r.headers.get("content-type"))
r = c.get(P + "/download", params={"path": os.path.join(root, "video.mp4")})
check(r.status_code == 200 and r.content == files[os.path.join(root, "video.mp4")], "file video 70 KB → nguyên vẹn")

print("── B. thư mục → zip ────────────────────────────────────────")
r = c.get(P + "/download", params={"path": os.path.join(root, "tập 1")})
check(r.status_code == 200 and r.headers.get("content-type", "").startswith("application/zip"), "thư mục → application/zip", (r.status_code, r.headers.get("content-type")))
check("t%E1%BA%ADp%201.zip" in r.headers.get("content-disposition", ""), "tên zip = tên thư mục", r.headers.get("content-disposition"))
z = zipfile.ZipFile(io.BytesIO(r.content))
names = sorted(z.namelist())
check(names == ["tập 1/a.txt", "tập 1/sub/b.bin"], "đúng cây thư mục trong zip", names)
check(z.read("tập 1/sub/b.bin") == files[os.path.join(root, "tập 1", "sub", "b.bin")] and z.testzip() is None, "nội dung đúng, zip hợp lệ")
check(all(i.compress_type == zipfile.ZIP_STORED for i in z.infolist()), "ZIP_STORED (không nén lại video)")

print("── C. nhiều mục ────────────────────────────────────────────")
r = c.get(P + "/download?" + "&".join("path=" + R.quote(p, safe="") for p in [
    os.path.join(root, "video.mp4"), os.path.join(root, "khác", "video.mp4"), os.path.join(root, "tập 1"), os.path.join(root, "ghi chú.json")]))
check(r.status_code == 200, "4 mục → 200", r.status_code)
z = zipfile.ZipFile(io.BytesIO(r.content))
names = sorted(z.namelist())
check(names == ["ghi chú.json", "tập 1/a.txt", "tập 1/sub/b.bin", "video (2).mp4", "video.mp4"], "file + thư mục trong một zip, tên trùng thêm (2)", names)
check(z.read("video (2).mp4") == b"xx" and z.testzip() is None, "video (2).mp4 là file thứ hai, zip hợp lệ")
check(r.headers.get("content-disposition", "").startswith("attachment; filename*=UTF-8''files-"), "tên zip files-<mốc>.zip", r.headers.get("content-disposition"))
r2 = c.get(P + "/download", params={"path": [os.path.join(root, "video.mp4"), os.path.join(root, "video.mp4")]})
check(r2.status_code == 200 and r2.content == files[os.path.join(root, "video.mp4")], "cùng một file lặp hai lần → một file, gửi thẳng")

print("── D. từ chối ──────────────────────────────────────────────")
r = c.get(P + "/download", params={"path": os.path.join(root, "không có.txt")})
check(r.status_code == 404, "không có → 404", r.status_code)
r = c.get(P + "/download", params={"path": os.path.join(root, "video.mp4")}, headers={"sec-fetch-site": "cross-site"})
check(r.status_code == 403, "trang lạ nhúng link → 403 (cùng cổng với /raw)", r.status_code)
r = c.get(P + "/download")
check(r.status_code == 422, "thiếu path → 422", r.status_code)

print("── E. luồng zip ────────────────────────────────────────────")
chunks = list(R._zip_stream([os.path.join(root, "tập 1"), os.path.join(root, "ghi chú.json")]))
blob = b"".join(chunks)
check(len(chunks) >= 2 and zipfile.ZipFile(io.BytesIO(blob)).testzip() is None, "generator nhả nhiều khúc, ghép lại là zip hợp lệ", len(chunks))
try:
    link = os.path.join(root, "tập 1", "link_ngoai")
    os.symlink(os.path.join(TMP, "data"), link, target_is_directory=True)
    have_link = True
except (OSError, NotImplementedError, AttributeError):
    have_link = False
if have_link:
    names = [a for _, a in R._zip_arcnames([os.path.join(root, "tập 1")])]
    check(all("link_ngoai" not in n for n in names), "symlink trong thư mục bị bỏ, không theo link ra ngoài", names)
else:
    print("  (không tạo được symlink ở đây — bỏ ca đó)")
check(R._zip_name([os.path.join(root, "tập 1")]) == "tập 1.zip" and R._zip_name(["a", "b"]).startswith("files-"), "_zip_name")
check(R._attachment_disposition("ảnh.png") == "attachment; filename*=UTF-8''%E1%BA%A3nh.png", "_attachment_disposition")

shutil.rmtree(TMP, ignore_errors=True)
print()
if FAILS:
    print(f"{COUNT[0] - len(FAILS)}/{COUNT[0]} PASS — {len(FAILS)} HỎNG")
    sys.exit(1)
print(f"{COUNT[0]}/{COUNT[0]} PASS")
