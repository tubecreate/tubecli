"""Khoá cloud (core/auth.py + auth_routes + `tubecli cloud-key`) — 13/11/2026.

Chạy:  python tests/cloud_key_test.py      (mã thoát 0 = đạt)

Vì sao (user 13/11/2026, ảnh TubeCLI Connect «Mật khẩu dashboard TubeCLI không đúng» lặp 6 dòng): «cái phần ghép
nối và mật khẩu này nó phức tạp quá cứ lỗi hoài». Connect tự xin một KHOÁ CLOUD trên máy thay cho việc hỏi mật khẩu
dashboard. Khoá: vào bằng đúng cửa đăng nhập cũ; chỉ lưu hash; độc lập với mật khẩu; xoay / thu hồi là phiên của
khoá cũ chết ngay (kể cả khi làm bằng CLI ở tiến trình khác); không mở thêm gì cho máy còn mật khẩu mặc định.

Cách ly: DATA_DIR tạm — không đụng auth.json / cloud_key.json thật của máy; không mạng.
"""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="tubecli_cloudkey_")

import tubecli.config as cfg  # noqa: E402
cfg.DATA_DIR = Path(TMP) / "data"
cfg.DATA_DIR.mkdir(parents=True, exist_ok=True)
from tubecli.core import auth  # noqa: E402
from tubecli.api import auth_routes as ar  # noqa: E402

failures, checks = [], 0


def check(label, ok, detail=""):
    global checks
    checks += 1
    print(("[PASS] " if ok else "[FAIL] ") + label + ("" if ok else f"  {detail}"))
    if not ok:
        failures.append(label)


class Req:
    def __init__(self, host="127.0.0.1", headers=None, cookies=None):
        self.headers = headers or {}
        self.client = type("C", (), {"host": host})()
        self.cookies = cookies or {}


def body_of(resp):
    if isinstance(resp, dict):
        return 200, resp
    return resp.status_code, json.loads(resp.body)


def cookie_of(resp):
    raw = resp.headers.get("set-cookie", "")
    return raw.split("tubecli_session=", 1)[1].split(";", 1)[0] if "tubecli_session=" in raw else ""


def login(pw, host="203.0.113.9"):
    resp = asyncio.run(ar.login(ar.LoginRequest(password=pw), Req(host=host), None))
    code, body = body_of(resp)
    return code, body, (cookie_of(resp) if code == 200 else "")


check("A0 file khoá nằm trong thư mục tạm", str(auth._cloud_key_file()).startswith(TMP), auth._cloud_key_file())
auth.ensure_initialised()
auth.set_password("Mat-Khau-Chu-May-1")

# ── A. khoá ───────────────────────────────────────────────────────────────────
check("A1 chưa có khoá: không khoá nào đúng, kể cả chuỗi rỗng / đúng dạng",
      not auth.verify_cloud_key("") and not auth.verify_cloud_key("tck_" + "a" * 43)
      and auth.cloud_key_info() == {"set": False, "created_at": 0})
k1 = auth.mint_cloud_key()
check("A2 khoá có tiền tố tck_, dài, ngẫu nhiên", k1.startswith("tck_") and len(k1) >= 44 and auth.mint_cloud_key() != k1)
k1 = auth.mint_cloud_key()
raw = open(auth._cloud_key_file(), encoding="utf-8").read()
check("A3 trên đĩa chỉ có hash — không có khoá", k1 not in raw and k1[4:] not in raw and '"hash"' in raw, raw)
check("A4 đúng khoá thì qua, sai một ký tự thì không", auth.verify_cloud_key(k1)
      and not auth.verify_cloud_key(k1[:-1] + ("A" if k1[-1] != "A" else "B")))
check("A5 khoá KHÔNG phải mật khẩu và ngược lại", not auth.verify_password(k1)
      and not auth.verify_cloud_key("Mat-Khau-Chu-May-1"))
try:
    auth.set_password("tck_matkhaucuatoi")
    bad = False
except ValueError:
    bad = True
check("A6 mật khẩu dashboard không được mang tiền tố tck_", bad)
open(auth._cloud_key_file(), "w", encoding="utf-8").write("{ hỏng")
auth._cloud_key_cache.update(mtime=None, hash="")
check("A7 file khoá hỏng = KHÔNG có khoá (cửa đóng)", not auth.verify_cloud_key(k1) and not auth.cloud_key_info()["set"])
k1 = auth.mint_cloud_key()

# ── B. đăng nhập bằng khoá ────────────────────────────────────────────────────
code, body, ck = login(k1)
check("B1 khoá cloud đăng nhập được ở /auth/login (từ xa)", code == 200 and body.get("ok") and ck, (code, body))
check("B2 phiên của khoá hợp lệ", auth.session_valid(ck))
code, body, _ = login("tck_" + "x" * 43)
check("B3 khoá sai → 401, cùng câu với mật khẩu sai", code == 401 and body.get("detail") == "Mật khẩu không đúng.", (code, body))
code, body, ck_pw = login("Mat-Khau-Chu-May-1")
check("B4 mật khẩu dashboard vẫn đăng nhập như cũ", code == 200 and ck_pw)

# đổi mật khẩu dashboard KHÔNG cắt khoá cloud (đây là lỗi «cứ lỗi hoài»)
auth.set_password("Mat-Khau-Moi-2")
check("B5 đổi mật khẩu: phiên cũ chết (cả hai loại)", not auth.session_valid(ck) and not auth.session_valid(ck_pw))
code, body, ck = login(k1)
check("B6 …nhưng khoá cloud VẪN đăng nhập lại được", code == 200 and auth.session_valid(ck), (code, body))

# ── C. xoay / thu hồi ─────────────────────────────────────────────────────────
code, body = body_of(asyncio.run(ar.cloud_key_rotate(ar.CloudKeyRotateRequest(current_key="tck_" + "z" * 43), Req(host="203.0.113.9"))))
check("C1 xoay bằng khoá sai → 401, khoá cũ còn nguyên", code == 401 and auth.verify_cloud_key(k1), (code, body))
code, body = body_of(asyncio.run(ar.cloud_key_rotate(ar.CloudKeyRotateRequest(current_key=k1), Req(host="203.0.113.9"))))
k2 = body.get("key", "")
check("C2 xoay bằng khoá đúng → khoá mới", code == 200 and k2.startswith("tck_") and k2 != k1, (code, body))
check("C3 khoá cũ chết, phiên của khoá cũ chết ngay", not auth.verify_cloud_key(k1) and not auth.session_valid(ck))
code, body, ck2 = login(k2)
code_pw, _b, ck_pw = login("Mat-Khau-Moi-2")
check("C4 khoá mới + mật khẩu đăng nhập được", code == 200 and code_pw == 200)

# thu hồi bằng CLI ở TIẾN TRÌNH KHÁC: máy chủ đang chạy phải thấy ngay (đọc lại theo mtime)
env = dict(os.environ, PYTHONIOENCODING="utf-8")
boot = ("import sys, pathlib; sys.path.insert(0, r'%s'); import tubecli.config as c; c.DATA_DIR = pathlib.Path(r'%s'); "
        "from tubecli.cli.cloud_key_cmd import cloud_key_cmd; cloud_key_cmd(sys.argv[1:], standalone_mode=True)"
        % (ROOT, cfg.DATA_DIR))
r = subprocess.run([sys.executable, "-c", boot, "--status"], capture_output=True, text=True, env=env, timeout=120)
check("C5 CLI --status: có khoá, không in khoá", r.returncode == 0 and "cloud key: set" in r.stdout and "tck_" not in r.stdout, r.stdout + r.stderr)
r = subprocess.run([sys.executable, "-c", boot, "--revoke"], capture_output=True, text=True, env=env, timeout=120)
check("C6 CLI --revoke chạy được", r.returncode == 0 and "revoked" in r.stdout, r.stdout + r.stderr)
check("C7 thu hồi ở tiến trình khác: khoá + phiên của khoá chết NGAY, phiên mật khẩu còn",
      not auth.verify_cloud_key(k2) and not auth.session_valid(ck2) and auth.session_valid(ck_pw))
r = subprocess.run([sys.executable, "-c", boot, "--new"], capture_output=True, text=True, env=env, timeout=120)
k3 = (r.stdout or "").strip().splitlines()[-1] if r.stdout.strip() else ""
check("C8 CLI --new in đúng MỘT dòng là khoá, máy chủ nhận ngay", r.returncode == 0 and k3.startswith("tck_")
      and len(r.stdout.strip().splitlines()) == 1 and auth.verify_cloud_key(k3), r.stdout + r.stderr)
r = subprocess.run([sys.executable, "-c", boot], capture_output=True, text=True, env=env, timeout=120)
check("C9 CLI không cờ → báo cách dùng, không tạo khoá", r.returncode != 0 and auth.verify_cloud_key(k3))
code, body = body_of(asyncio.run(ar.cloud_key_revoke()))
check("C10 route thu hồi", code == 200 and body.get("revoked") is True and not auth.verify_cloud_key(k3))
code, body = body_of(asyncio.run(ar.cloud_key_revoke()))
check("C11 thu hồi lần hai: không lỗi, revoked=False", code == 200 and body.get("revoked") is False)

# ── D. đổi mật khẩu bằng khoá (hộp «bắt buộc đổi mật khẩu mặc định» trên cloud) ──
k4 = auth.mint_cloud_key()
auth.set_password(auth.DEFAULT_PASSWORD, _is_default=True)
check("D1 máy còn 123456: phiên TỪ XA của khoá cloud vẫn bị khoá ở mọi route khác",
      auth.default_password_refusal("203.0.113.9", {}, "/api/v1/agents") is not None
      and auth.default_password_refusal("203.0.113.9", {}, "/api/v1/auth/password") is None)
code, body = body_of(asyncio.run(ar.change_password(ar.PasswordChangeRequest(
    current_password="tck_" + "q" * 43, new_password="Mat-Khau-Tu-Cloud-3"), Req(host="203.0.113.9"))))
check("D2 khoá sai ở ô mật khẩu hiện tại → 401", code == 401, (code, body))
code, body = body_of(asyncio.run(ar.change_password(ar.PasswordChangeRequest(
    current_password=k4, new_password="Mat-Khau-Tu-Cloud-3"), Req(host="203.0.113.9"))))
check("D3 khoá đúng làm «mật khẩu hiện tại» → đặt được mật khẩu mới", code == 200 and auth.verify_password("Mat-Khau-Tu-Cloud-3")
      and not auth.is_default_password(), (code, body))
check("D4 …và khoá cloud vẫn nguyên", auth.verify_cloud_key(k4))
st = asyncio.run(ar.cloud_link_status())
check("D5 /auth/cloud-link báo có khoá, không lộ khoá / hash", st.get("cloud_key", {}).get("set") is True
      and "tck_" not in json.dumps(st) and auth._cloud_key_hash() not in json.dumps(st), st)

# bộ đếm sai dùng chung: 5 khoá sai liên tiếp → khoá đăng nhập của IP đó
for _ in range(6):
    code, body, _c = login("tck_" + "w" * 43, host="198.51.100.7")
check("D6 dò khoá cũng dính bộ đếm sai (429)", code == 429, (code, body))

# ── E. có khoá thì KHÔNG gửi mật khẩu dashboard lên cloud ─────────────────────
from tubecli.core import cloud_link  # noqa: E402
SENT = []
cloud_link.sync_password = lambda pw: SENT.append(pw) or {"ok": True, "code": "synced"}
r = asyncio.run(ar._sync_cloud("Mat-Khau-Tu-Cloud-3"))
check("E1 máy có khoá cloud: đồng bộ mật khẩu là việc KHÔNG làm (code cloud_key), không gọi cloud",
      r == {"ok": True, "code": "cloud_key"} and not SENT, (r, SENT))
auth.revoke_cloud_key()
r = asyncio.run(ar._sync_cloud("Mat-Khau-Tu-Cloud-3"))
check("E2 không có khoá: đồng bộ như cũ", r.get("code") == "synced" and SENT == ["Mat-Khau-Tu-Cloud-3"], (r, SENT))

print(f"\n{checks - len(failures)}/{checks} PASS")
sys.exit(1 if failures else 0)
