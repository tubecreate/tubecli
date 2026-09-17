# -*- coding: utf-8 -*-
"""Danh tính cloud của máy → thư mục cha trên Google Drive (17/9/2026).

User: "chỗ upload project lên drive chỉnh lại giúp tôi upload thế này sử dụng đường dẫn tạo folder
username-vps-9/tenproject để biết được user nào đăng lên và ở server nào nếu tất cả đăng chung 1 driver".

Kiểm:
  A. core/cloud_identity: chưa biết → «tubecli-<tên máy>»; lưu → «username-vps-<mã ngẫu nhiên>»; sai dạng →
     ValueError; file hỏng / file lõi .116 chỉ có số thứ tự → coi như chưa biết; không đổi thì không ghi lại
     (user 17/9/2026: "tên server để theo stt này có ổn không? người dùng họ xài họ sẽ biết có bao nhiêu server")
  B. route /api/v1/instance/cloud-identity: PUT chỉ phiên đăng nhập thật của chủ (loopback/run_api không đủ,
     khách bị chặn), sai dạng → 400; GET trả danh tính + tên thư mục
  C. server.py gắn router; pipeline lấy tên thư mục từ đây

Run:  python tests/cloud_identity_test.py     (exit 0 = pass)
"""
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

import tubecli.config as CFG  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="cloud_ident_"))
CFG.DATA_DIR = TMP / "data"
CFG.EXTENSIONS_DATA_DIR = CFG.DATA_DIR / "extensions_data"
CFG.DATA_DIR.mkdir(parents=True)

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from tubecli.core import auth, cloud_identity as CI  # noqa: E402
from tubecli.api import instance_routes as R  # noqa: E402

PASS = FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", label)
    else:
        FAIL += 1
        print("  FAIL", label, "—", str(detail)[:300])


FILE = Path(CI._path())
if os.path.commonpath([os.path.realpath(str(FILE)), os.path.realpath(str(TMP))]) != os.path.realpath(str(TMP)):
    print("ABORT — cloud_identity.json không nằm trong thư mục tạm:", FILE)
    sys.exit(2)

print("── A. core/cloud_identity ──────────────────────────────────")
ok(CI.load() == {}, "chưa có file → chưa biết")
fallback = CI.drive_root_name()
ok(fallback.startswith("tubecli") and "/" not in fallback and " " not in fallback,
   "máy chưa nối cloud → «tubecli-<tên máy>» (không có / hay khoảng trắng)", fallback)
saved = CI.save("tuan89tk", "k7m2qx")
ok(saved["username"] == "tuan89tk" and saved["server_code"] == "k7m2qx" and FILE.is_file(), "lưu → ghi file", saved)
ok(CI.drive_root_name() == "tuan89tk-vps-k7m2qx", "tên thư mục «username-vps-<mã ngẫu nhiên>»", CI.drive_root_name())
mtime = FILE.stat().st_mtime_ns
seen = CI.load()["seen"]
ok(CI.save("tuan89tk", " K7M2QX ")["seen"] == seen and FILE.stat().st_mtime_ns == mtime,
   "không đổi gì (khác hoa/thường, khoảng trắng) → không ghi lại file")
ok(CI.save("vinh_it.2", "p3xw9d")["username"] == "vinh_it.2" and CI.drive_root_name() == "vinh_it.2-vps-p3xw9d",
   "đổi tài khoản / máy → tên mới")
for bad_u, bad_code, label in (("", "k7m2qx", "username rỗng"), ("a/b", "k7m2qx", "username có /"),
                               ("a b", "k7m2qx", "username có khoảng trắng"), ("x" * 65, "k7m2qx", "username quá dài"),
                               ("ok_user", 9, "mã là SỐ THỨ TỰ (kiểu int của lõi .116)"), ("ok_user", "ab", "mã quá ngắn"),
                               ("ok_user", "a/b-cd", "mã có /"), ("ok_user", "k7m 2q", "mã có khoảng trắng"),
                               ("ok_user", "x" * 17, "mã quá dài"), ("ok_user", True, "mã kiểu bool"),
                               ("ok_user", None, "không có mã")):
    try:
        CI.save(bad_u, bad_code)
        ok(False, f"sai dạng phải ném: {label}")
    except ValueError:
        ok(CI.drive_root_name() == "vinh_it.2-vps-p3xw9d", f"sai dạng → ValueError, giữ danh tính cũ: {label}")
FILE.write_text("{broken", encoding="utf-8")
ok(CI.load() == {} and CI.drive_root_name().startswith("tubecli"), "file hỏng → coi như chưa biết")
FILE.write_text('{"username": "../x", "server_code": "k7m2qx"}', encoding="utf-8")
ok(CI.load() == {}, "file bị sửa tay thành tên lạ → không dùng")
FILE.write_text('{"username": "tuan89tk", "server_id": 9, "seen": 1}', encoding="utf-8")
ok(CI.load() == {} and CI.drive_root_name().startswith("tubecli"),
   "file của lõi .116 (chỉ có số thứ tự) → KHÔNG dùng «vps-9» nữa, chờ cloud báo mã", CI.drive_root_name())

print("── B. route ────────────────────────────────────────────────")
app = FastAPI()


@app.middleware("http")
async def fake_guest(request: Request, call_next):
    if request.headers.get("x-test-guest"):
        request.state.guest_scope = {"group": "g1"}
    return await call_next(request)


app.include_router(R.router)
c = TestClient(app)
auth.session_valid = lambda tok: tok == "good"
FILE.unlink()
body = {"username": "tuan89tk", "server_code": "k7m2qx"}
r = c.put("/api/v1/instance/cloud-identity", json=body)
ok(r.status_code == 403 and CI.load() == {}, "không có phiên (loopback / run_api của model) → 403, không ghi", r.status_code)
c.cookies.set(auth.SESSION_COOKIE, "stale")
r = c.put("/api/v1/instance/cloud-identity", json=body)
ok(r.status_code == 403, "phiên hết hạn → 403", r.status_code)
c.cookies.set(auth.SESSION_COOKIE, "good")
r = c.put("/api/v1/instance/cloud-identity", json=body, headers={"x-test-guest": "1"})
ok(r.status_code == 403 and CI.load() == {}, "khách của không gian chia sẻ → 403", r.status_code)
r = c.put("/api/v1/instance/cloud-identity", json=body)
ok(r.status_code == 200 and r.json()["drive_root"] == "tuan89tk-vps-k7m2qx" and CI.load()["server_code"] == "k7m2qx",
   "phiên chủ (cloud đăng nhập hộ) → lưu, trả tên thư mục", r.text)
r = c.put("/api/v1/instance/cloud-identity", json={"username": "a/b", "server_code": "k7m2qx"})
ok(r.status_code == 400 and CI.drive_root_name() == "tuan89tk-vps-k7m2qx", "tên sai dạng → 400, giữ cũ", r.status_code)
r = c.put("/api/v1/instance/cloud-identity", json={"username": "tuan89tk", "server_id": 9})
ok(r.status_code == 422 and CI.drive_root_name() == "tuan89tk-vps-k7m2qx",
   "cloud cũ gửi số thứ tự (không có mã) → từ chối, giữ cũ", r.status_code)
r = c.get("/api/v1/instance/cloud-identity")
ok(r.status_code == 200 and r.json()["identity"]["username"] == "tuan89tk"
   and r.json()["drive_root"] == "tuan89tk-vps-k7m2qx", "GET: danh tính + tên thư mục", r.text)

print("── C. nối vào máy chủ + pipeline ───────────────────────────")
server_src = (ROOT / "tubecli" / "api" / "server.py").read_text(encoding="utf-8")
ok("from tubecli.api.instance_routes import router as _instance_router" in server_src
   and "app.include_router(_instance_router)" in server_src, "server.py gắn router")
pipe_src = (ROOT / "tubecli" / "extensions" / "content_video" / "pipeline.py").read_text(encoding="utf-8")
ok("cloud_identity.drive_root_name()" in pipe_src and 'DX.find_or_create_folder(drive, "root", root_name)' in pipe_src,
   "bước Drive đặt project trong thư mục của máy")

print()
print(f"{PASS}/{PASS + FAIL} PASS" if not FAIL else f"{PASS}/{PASS + FAIL} PASS — {FAIL} HỎNG")
sys.exit(1 if FAIL else 0)
