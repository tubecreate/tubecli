"""Đồng bộ mật khẩu dashboard với TubeCLI Cloud từ chính bảng điều khiển (core/cloud_link.py + auth_routes).

Chạy:  python tests/cloud_link_test.py      (mã thoát 0 = đạt)

Vì sao (user 29/10/2026): «bên tubecli setting … không có chỗ để đồng bộ pass với cloud». Trước chỉ app
TubeCLI Connect báo cloud được. Khoá: tìm tunnel token đúng nguồn (biến môi trường > connect.json > tệp
/etc/cloudflared/token của VPS), KHÔNG BAO GIỜ trả token ra ngoài, gọi đúng route cloud và dịch mã lỗi;
route lõi đòi mật khẩu hiện tại + dùng chung bộ đếm sai; đổi mật khẩu kèm sync_cloud.

Cách ly: DATA_DIR tạm (auth.json giả), thư mục Connect + tệp token tạm, và một «cloud giả» http.server
chạy 127.0.0.1 — không gọi mạng thật, không đụng mật khẩu thật của máy.
"""
import asyncio
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = tempfile.mkdtemp(prefix="tubecli_cloudlink_")
CONNECT = os.path.join(TMP, "connect")
TOKFILE = os.path.join(TMP, "cf_token")
for k in ("TUNNEL_TOKEN", "TUBECLI_TUNNEL_TOKEN"):
    os.environ.pop(k, None)
os.environ["TUBECLI_CONNECT_HOME"] = CONNECT
os.environ["TUBECLI_TUNNEL_TOKEN_FILE"] = TOKFILE

failures, checks = [], 0


def check(label, ok, detail=""):
    global checks
    checks += 1
    print(("[PASS] " if ok else "[FAIL] ") + label + ("" if ok else f"  {detail}"))
    if not ok:
        failures.append(label)


# ── cloud giả ────────────────────────────────────────────────────────────────
SEEN = []
REPLY = {"status": 200, "body": {"ok": True, "server_id": 13}}


class Fake(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        SEEN.append({"path": self.path, "body": json.loads(self.rfile.read(n) or b"{}"),
                     "ua": self.headers.get("User-Agent", "")})
        data = json.dumps(REPLY["body"]).encode()
        self.send_response(REPLY["status"])
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


srv = HTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=srv.serve_forever, daemon=True).start()
os.environ["TUBECLI_CLOUD_URL"] = f"http://127.0.0.1:{srv.server_address[1]}/"

from tubecli.core import cloud_link as cl  # noqa: E402

check("cloud_url bỏ «/» cuối", cl.cloud_url() == f"http://127.0.0.1:{srv.server_address[1]}")

# ── 1. tìm token ─────────────────────────────────────────────────────────────
check("không có gì → ('', 'none'), link_status linked=False", cl.find_tunnel_token() == ("", "none")
      and cl.link_status()["linked"] is False)
io.open(TOKFILE, "w", encoding="utf-8").write("  VPS-TOKEN-123  \n")
check("VPS: /etc/cloudflared/token → nguồn vps, đã bỏ khoảng trắng", cl.find_tunnel_token() == ("VPS-TOKEN-123", "vps"))
os.makedirs(CONNECT, exist_ok=True)
io.open(os.path.join(CONNECT, "connect.json"), "w", encoding="utf-8").write(json.dumps({"tunnel_token": "CONNECT-TOKEN-9", "lang": "vi"}))
check("Connect: connect.json đứng TRƯỚC tệp VPS", cl.find_tunnel_token() == ("CONNECT-TOKEN-9", "connect"))
os.environ["TUNNEL_TOKEN"] = "ENV-TOKEN"
check("biến môi trường đứng trước hết", cl.find_tunnel_token() == ("ENV-TOKEN", "env"))
os.environ.pop("TUNNEL_TOKEN")
io.open(os.path.join(CONNECT, "connect.json"), "w", encoding="utf-8").write("{not json")
check("connect.json hỏng → bỏ qua, rơi về tệp VPS", cl.find_tunnel_token() == ("VPS-TOKEN-123", "vps"))
st = cl.link_status()
check("link_status KHÔNG chứa token (chỉ linked/source/cloud_url)",
      set(st) == {"linked", "source", "cloud_url"} and "VPS-TOKEN-123" not in json.dumps(st), st)

import builtins  # noqa: E402
_real_open = builtins.open


def _deny(path, *a, **k):
    if str(path) == TOKFILE:
        raise PermissionError(13, "denied")
    return _real_open(path, *a, **k)


os.remove(os.path.join(CONNECT, "connect.json"))
builtins.open = _deny
try:
    check("tệp token không đọc được (quyền) → ('', 'unreadable')", cl.find_tunnel_token() == ("", "unreadable"))
    r = cl.sync_password("pw")
    check("sync khi không đọc được token → token_unreadable, không gọi cloud", r["code"] == "token_unreadable" and not SEEN, r)
finally:
    builtins.open = _real_open

# ── 2. sync_password với cloud giả ───────────────────────────────────────────
io.open(os.path.join(CONNECT, "connect.json"), "w", encoding="utf-8").write(json.dumps({"tunnel_token": "CONNECT-TOKEN-9"}))
r = cl.sync_password("Mat-Khau-Moi-123")
check("200 → synced + server_id", r == {"ok": True, "code": "synced", "server_id": 13, "source": "connect"}, r)
check("gửi đúng route + token + mật khẩu, UA TubeCLI",
      SEEN and SEEN[-1]["path"] == "/api/servers/pair/password"
      and SEEN[-1]["body"] == {"tunnel_token": "CONNECT-TOKEN-9", "tubecli_password": "Mat-Khau-Moi-123"}
      and SEEN[-1]["ua"].startswith("TubeCLI/"), SEEN[-1:] )
for status, code in ((401, "not_recognised"), (409, "cloud_login_failed"), (500, "cloud_error")):
    REPLY.update(status=status, body={"error": f"lý do {status}"})
    r = cl.sync_password("x")
    check(f"{status} → {code} kèm lý do của cloud", r["ok"] is False and r["code"] == code and r["error"] == f"lý do {status}", r)
REPLY.update(status=200, body={"ok": True, "server_id": 13})
os.environ["TUBECLI_CLOUD_URL"] = "http://127.0.0.1:9"      # cổng discard: không ai nghe
r = cl.sync_password("x", timeout=5)
check("cloud không gọi được → cloud_unreachable", r["code"] == "cloud_unreachable", r)
os.environ["TUBECLI_CLOUD_URL"] = f"http://127.0.0.1:{srv.server_address[1]}"
os.remove(os.path.join(CONNECT, "connect.json"))
os.remove(TOKFILE)
n_before = len(SEEN)
r = cl.sync_password("x")
check("không liên kết → not_linked, KHÔNG gọi cloud", r["code"] == "not_linked" and len(SEEN) == n_before, r)

# ── 3. route lõi (DATA_DIR tạm) ──────────────────────────────────────────────
import tubecli.config as cfg  # noqa: E402
cfg.DATA_DIR = Path(TMP) / "data"
cfg.DATA_DIR.mkdir(parents=True, exist_ok=True)
from tubecli.core import auth  # noqa: E402
from tubecli.api import auth_routes as ar  # noqa: E402

check("auth.json nằm trong thư mục tạm", str(auth._auth_file()).startswith(TMP), auth._auth_file())
auth.ensure_initialised()
auth.set_password("Mat-Khau-Cu-123")
io.open(os.path.join(CONNECT, "connect.json"), "w", encoding="utf-8").write(json.dumps({"tunnel_token": "CONNECT-TOKEN-9"}))


class Req:
    def __init__(self):
        self.headers = {}
        self.client = type("C", (), {"host": "127.0.0.1"})()
        self.cookies = {}


def body_of(resp):
    if isinstance(resp, dict):
        return 200, resp
    return resp.status_code, json.loads(resp.body)


st = asyncio.run(ar.cloud_link_status())
check("GET cloud-link: linked qua connect, không token", st["linked"] and st["source"] == "connect" and "CONNECT-TOKEN-9" not in json.dumps(st), st)

n_before = len(SEEN)
code, b = body_of(asyncio.run(ar.cloud_sync(ar.CloudSyncRequest(password="sai-roi"), Req())))
check("cloud-sync sai mật khẩu hiện tại → 401, KHÔNG gọi cloud", code == 401 and len(SEEN) == n_before, (code, b))
code, b = body_of(asyncio.run(ar.cloud_sync(ar.CloudSyncRequest(password="Mat-Khau-Cu-123"), Req())))
check("cloud-sync đúng mật khẩu → gửi cloud, synced", code == 200 and b.get("code") == "synced"
      and SEEN[-1]["body"]["tubecli_password"] == "Mat-Khau-Cu-123", (code, b))

code, b = body_of(asyncio.run(ar.change_password(ar.PasswordChangeRequest(
    current_password="Mat-Khau-Cu-123", new_password="Mat-Khau-Moi-456", sync_cloud=True), Req())))
check("đổi mật khẩu + sync_cloud → ok + cloud.synced với mật khẩu MỚI",
      code == 200 and b.get("ok") and (b.get("cloud") or {}).get("code") == "synced"
      and SEEN[-1]["body"]["tubecli_password"] == "Mat-Khau-Moi-456" and auth.verify_password("Mat-Khau-Moi-456"), (code, b))
n_before = len(SEEN)
code, b = body_of(asyncio.run(ar.change_password(ar.PasswordChangeRequest(
    current_password="Mat-Khau-Moi-456", new_password="Mat-Khau-Ba-789"), Req())))
check("đổi mật khẩu KHÔNG sync_cloud (trang /login, client cũ) → không gọi cloud, không có khoá cloud",
      code == 200 and "cloud" not in b and len(SEEN) == n_before, (code, b))

# cổng đăng nhập: hai route mới KHÔNG được miễn
SRV = io.open(ROOT / "tubecli/api/server.py", encoding="utf-8").read()
exempt = SRV[SRV.index("_AUTH_EXEMPT_EXACT"):][:900]
check("cloud-link / cloud-sync nằm SAU cổng đăng nhập (không trong danh sách miễn)",
      "cloud-link" not in exempt and "cloud-sync" not in exempt)

# ── 4. bảng điều khiển ──────────────────────────────────────────────────────
APP = io.open(ROOT / "tubecli/extensions/webui/static/app.js", encoding="utf-8").read().replace("\r\n", "\n")
try:
    subprocess.run(["node", "--check", str(ROOT / "tubecli/extensions/webui/static/app.js")], check=True, capture_output=True, timeout=60)
    check("app.js cú pháp hợp lệ", True)
except Exception as e:  # noqa: BLE001
    check("app.js cú pháp hợp lệ", False, getattr(e, "stderr", e))
check("mở tab Settings là gắn thẻ Mật khẩu & TubeCLI Cloud", "if (tab === 'settings') mountCloudPasswordCard();" in APP)
for fn in ("mountCloudPasswordCard", "cloudPwChange", "cloudPwSync", "cloudPwSyncText"):
    check(f"app.js có {fn}()", f"function {fn}(" in APP)
ch = APP[APP.index("async function cloudPwChange("):][:1600]
check("đổi mật khẩu gửi sync_cloud theo ô tick (tắt khi máy chưa liên kết)",
      "sync_cloud: !!(syncBox && syncBox.checked && !syncBox.disabled)" in ch and "'/api/v1/auth/password'" in ch)
check("đồng bộ riêng gọi /api/v1/auth/cloud-sync", "apiPost('/api/v1/auth/cloud-sync', { password: pw })" in APP)
KEYS = ["title", "desc", "status_unknown", "linked_connect", "linked_vps", "linked_env", "not_linked", "unreadable",
        "change_title", "current", "new", "confirm", "sync_too", "change_btn", "sync_title", "sync_hint", "sync_btn",
        "fill", "mismatch", "changed", "working", "r_synced", "r_not_linked", "r_unreadable", "r_not_recognised",
        "r_login_failed", "r_unreachable", "r_error"]
used = set(__import__("re").findall(r"T\('cloudpw\.([a-z_]+)'", APP))
check("mọi khoá cloudpw.* app.js dùng đều có trong danh sách", used <= set(KEYS), used - set(KEYS))
en = json.load(io.open(ROOT / "tubecli/extensions/webui/locales/en.json", encoding="utf-8"))
for lang in ["en", "vi", "zh", "zh-TW", "ja", "ko", "es", "tr", "ru"]:
    d = json.load(io.open(ROOT / f"tubecli/extensions/webui/locales/{lang}.json", encoding="utf-8"))
    miss = [k for k in KEYS if f"cloudpw.{k}" not in d]
    check(f"locale {lang}: đủ {len(KEYS)} khoá cloudpw", not miss, miss)
    if lang != "en":
        same = [k for k in KEYS if d.get(f"cloudpw.{k}") == en.get(f"cloudpw.{k}") and k not in ("title",)]
        check(f"locale {lang}: đã dịch (không chép nguyên tiếng Anh)", len(same) <= 1, same)

srv.shutdown()
print(f"\n{checks - len(failures)}/{checks} PASS")
sys.exit(1 if failures else 0)
