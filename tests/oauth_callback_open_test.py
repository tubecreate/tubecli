# -*- coding: utf-8 -*-
"""Callback OAuth không còn bắt nhập mật khẩu phiên (16/9/2026).

User: "chỗ cấp quyền auth sau khi cấp quyền trả về thì bắt nhập mật khẩu phiên, chỗ này bỏ qua yêu cầu phiên khi
call back từ google được ko? vì nhập mật khẩu xong phải làm lại lần nữa, người mới họ ko biết tưởng phần mềm lỗi."

Trình duyệt quay về từ Google (hồ sơ mới của node Browser, điện thoại) chưa có phiên → bị đẩy sang
/login?next=<đường dẫn KHÔNG query> → `code` của Google rơi mất, mà code chỉ dùng được một lần.

Kiểm:
  A. đúng MỘT đường của auth-manager được miễn đăng nhập (callback), và đó đúng là redirect_uri gửi cho Google;
     /tokens, /credentials, /oauth/authorize… vẫn phải có phiên
  B. _login_next giữ query và mã hoá (các route khác cũng hưởng)
  C. trang /login chỉ nhận ?next= là đường dẫn nội bộ — không cho //evil.com hay https://evil.com
  D. state: sai/hết hạn thì KHÔNG gọi provider; dùng một lần; state cũ bị dọn khi tạo state mới

Run:  python tests/oauth_callback_open_test.py     (exit 0 = pass)
"""
import ast
import io
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

PASS = FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", label)
    else:
        FAIL += 1
        print("  FAIL", label, "—", str(detail)[:300])


SRV = io.open(ROOT / "tubecli" / "api" / "server.py", encoding="utf-8").read()
TREE = ast.parse(SRV)
CALLBACK = "/api/v1/auth-manager/oauth/callback"


def symbol(name):
    for node in ast.walk(TREE):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    return None


print("── A. đường được miễn đăng nhập ────────────────────────────")
exact = symbol("_AUTH_EXEMPT_EXACT") or set()
prefixes = symbol("_AUTH_EXEMPT_PREFIX") or ()
ok(CALLBACK in exact, "callback OAuth nằm trong _AUTH_EXEMPT_EXACT", sorted(exact))
am_exempt = [p for p in exact if p.startswith("/api/v1/auth-manager")]
ok(am_exempt == [CALLBACK], "CHỈ đường callback của auth-manager được miễn", am_exempt)
for p in ("/api/v1/auth-manager/tokens", "/api/v1/auth-manager/credentials",
          "/api/v1/auth-manager/oauth/callback/x", "/api/v1/auth-manager/gsheets/read"):
    ok(p not in exact and not p.startswith(tuple(prefixes)), f"vẫn phải có phiên: {p}")
ok(not any(CALLBACK.startswith(pre) for pre in prefixes), "không miễn theo tiền tố (khớp ĐÚNG đường)", prefixes)

# redirect_uri gửi cho Google phải chính là đường vừa miễn — lệch một ký tự là lại hỏi mật khẩu.
EXT = io.open(ROOT / "tubecli" / "extensions" / "auth_manager" / "extension.py", encoding="utf-8").read()
ok(f'"{CALLBACK}"' in EXT or f"'{CALLBACK}'" in EXT or CALLBACK.lstrip("/") in EXT,
   "extension.py dựng redirect_uri đúng đường callback đó")

print("── B. /login?next= giữ query ───────────────────────────────")
fn = next((n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == "_login_next"), None)
ok(fn is not None, "server.py có _login_next")
ns = {}
exec(ast.get_source_segment(SRV, fn), ns)  # noqa: S102 — chạy đúng hàm thật, không phải bản chép
_login_next = ns["_login_next"]
ok(_login_next("/dashboard") == "/dashboard", "không có query → nguyên đường dẫn")
got = _login_next("/api/v1/auth-manager/oauth/callback", "code=4/0AX&state=abc")
ok(got == "/api/v1/auth-manager/oauth/callback%3Fcode%3D4/0AX%26state%3Dabc",
   "có query → giữ đủ code + state, mã hoá ? & = để không lẫn vào tham số của /login", got)
ok("%26" in _login_next("/x", "a=1&b=2"), "dấu & được mã hoá")
ok("_login_next(request.url.path, request.url.query)" in SRV, "middleware dùng _login_next (không còn chỉ path)")
ok("next={request.url.path}" not in SRV, "không còn chỗ nào chỉ mang path")

print("── C. /login chỉ nhận đường dẫn nội bộ ─────────────────────")
# Kiểm ở GIÁ TRỊ CHẠY THẬT, không phải mã nguồn: _LOGIN_PAGE là chuỗi Python KHÔNG raw, nên một regex viết
# bằng dấu gạch chéo ngược trong đó bị Python co lại và gửi xuống trình duyệt sai cú pháp (đã mắc 16/9/2026).
from tubecli.api.auth_routes import _LOGIN_PAGE  # noqa: E402

GUARD = ("var next=(nextRaw.charAt(0)==='/' && nextRaw.charAt(1)!=='/' && nextRaw.charCodeAt(1)!==92)")
ok(GUARD in _LOGIN_PAGE, "trang /login lọc ?next=: phải bắt đầu bằng ĐÚNG một dấu / (chặn //evil.com, https://…, /\\evil.com)")
ok("var nextRaw=new URLSearchParams(location.search).get('next')||'';" in _LOGIN_PAGE, "đọc ?next= thô rồi mới lọc")
ok("get('next')||'/dashboard'" not in _LOGIN_PAGE, "không còn nhận thẳng ?next= chưa lọc")
_next_lines = [ln for ln in _LOGIN_PAGE.splitlines() if "nextRaw" in ln]
ok(len(_next_lines) >= 2 and not any("\\" in ln for ln in _next_lines),
   "khối lọc ?next= không chứa dấu gạch chéo ngược nào (chuỗi Python không raw co nó lại → JS hỏng)", _next_lines)
_js_blocks = re.findall(r"<script>(.*?)</script>", _LOGIN_PAGE, re.S)
_node = shutil.which("node")
if _node:
    _p = Path(tempfile.mkdtemp(prefix="login_js_")) / "login.js"
    _p.write_text("\n".join(_js_blocks), encoding="utf-8")
    _r = subprocess.run([_node, "--check", str(_p)], capture_output=True, text=True)
    ok(_r.returncode == 0, "node --check: JS của trang /login đúng cú pháp", (_r.stderr or "").strip()[:200])
else:
    print("  --   bỏ qua node --check (không có node)")

# Lọc ?next= chạy thật trong node, đúng đoạn mã của trang /login.
if _node:
    _drv = Path(tempfile.mkdtemp(prefix="login_next_")) / "drv.js"
    _drv.write_text("const nextRaw=process.argv[2] || '';\n" + GUARD + "\n    ? nextRaw : '/dashboard';\nconsole.log(next);\n",
                    encoding="utf-8")
    for _raw, _want in (("/api/v1/auth-manager/oauth/callback?code=4/0AX&state=abc", "same"),
                        ("/dashboard", "same"), ("/", "same"),
                        ("//evil.com", "/dashboard"), ("https://evil.com", "/dashboard"),
                        ("/\\evil.com", "/dashboard"), ("", "/dashboard")):
        _out = subprocess.run([_node, str(_drv), _raw], capture_output=True, text=True).stdout.strip()
        ok(_out == (_raw if _want == "same" else _want), f"?next={_raw or '(rỗng)'} → {_want}", _out)

print("── D. state dùng một lần, có hạn ───────────────────────────")
import tubecli.extensions.auth_manager.extension as AM  # noqa: E402
import requests as REQ  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="oauth_cb_"))
am = AM.AuthManager(data_file=str(TMP / "auth_manager.json"))
am.add_credential("google", "test", client_id="cid.apps.googleusercontent.com", client_secret="sec")
CRED = list(am._data["credentials"])[0]
CALLS = []


def blocked_post(*a, **k):
    CALLS.append((a, k))
    raise RuntimeError("test chặn mọi lời gọi mạng")


REQ.post = blocked_post
AM._pending_oauth.clear()

ok(AM.PENDING_TTL_SEC == 900, "state sống 15 phút", AM.PENDING_TTL_SEC)
built = am.build_oauth_url(CRED, ["drive"], callback_base="https://tungho2-23.tubecreate.com")
ok(built["status"] == "success" and urlparse(built["redirect_uri"]).path == CALLBACK,
   "redirect_uri = đúng đường callback được miễn", built.get("redirect_uri"))
state = built["state"]
ok(len(state) >= 32 and state in AM._pending_oauth, "state ngẫu nhiên ≥32 ký tự, đã ghi vào sổ chờ", len(state))

res = am.handle_oauth_callback("code_1", "state-khong-ton-tai")
ok(res["status"] == "error" and "expired" in res["message"] and not CALLS,
   "state sai → dừng ngay, KHÔNG gọi provider", (res["message"][:80], CALLS))
ok("Authorize again" in res["message"] and "15 minutes" in res["message"], "câu lỗi chỉ cách làm lại", res["message"])

AM._pending_oauth[state]["created_at"] = (datetime.now() - timedelta(seconds=AM.PENDING_TTL_SEC + 5)).isoformat()
res = am.handle_oauth_callback("code_1", state)
ok(res["status"] == "error" and not CALLS and state not in AM._pending_oauth,
   "state quá 15 phút → hết hạn, không gọi provider, bị dọn khỏi sổ", res["message"][:80])

fresh = am.build_oauth_url(CRED, ["drive"], callback_base="https://tungho2-23.tubecreate.com")["state"]
res = am.handle_oauth_callback("code_2", fresh)
ok(res["status"] == "error" and len(CALLS) == 1, "state hợp lệ → mới gọi provider (ở đây bị test chặn)", len(CALLS))
res2 = am.handle_oauth_callback("code_2", fresh)
ok(res2["status"] == "error" and "expired" in res2["message"] and len(CALLS) == 1,
   "state dùng MỘT lần: gọi lại cùng state không đổi được code lần hai", (res2["message"][:60], len(CALLS)))

old = am.build_oauth_url(CRED, ["drive"], callback_base="https://x.tubecreate.com")["state"]
AM._pending_oauth[old]["created_at"] = (datetime.now() - timedelta(hours=2)).isoformat()
am.build_oauth_url(CRED, ["drive"], callback_base="https://x.tubecreate.com")
ok(old not in AM._pending_oauth, "tạo lượt cấp quyền mới thì dọn luôn state cũ (sổ chờ không phình mãi)")
AM._pending_oauth["rác"] = {"created_at": "không phải mốc thời gian"}
am.build_oauth_url(CRED, ["drive"], callback_base="https://x.tubecreate.com")
ok("rác" not in AM._pending_oauth, "mốc thời gian đọc không ra → coi như hết hạn")

print()
print(f"{PASS}/{PASS + FAIL} PASS" if not FAIL else f"{PASS}/{PASS + FAIL} PASS — {FAIL} HỎNG")
sys.exit(1 if FAIL else 0)
