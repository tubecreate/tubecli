"""Auth Manager: credential chỉ có file JSON không còn mở trang lỗi «Missing required parameter: client_id» của Google.

Chạy:  python tests/auth_manager_json_credential_test.py      (mã thoát 0 = đạt)

Vì sao (user 15/11/2026): «chỗ sử dụng OAuth client ok rồi nhưng nếu sử dụng json và email service thì lỗi» — bấm
Authorize trên credential service account dựng link với client_id rỗng. Nay: khoá service account → báo rõ không cần
cấp quyền (và Drive cần OAuth client); file JSON của OAuth client → tự lấy Client ID / Secret trong đó.

Cách ly: auth_manager.json trong thư mục tạm; không mạng.
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"[PASS] {name}")
    else:
        failed += 1
        print(f"[FAIL] {name}  {str(detail)[:300]}")


from tubecli.extensions.auth_manager import extension as E  # noqa: E402

TMP = tempfile.mkdtemp(prefix="am_json_")
am = E.AuthManager(data_file=os.path.join(TMP, "auth_manager.json"))
check("0 tệp dữ liệu nằm trong thư mục tạm", am.data_file.startswith(TMP))

SA = json.dumps({"type": "service_account", "client_email": "bot@proj.iam.gserviceaccount.com",
                 "private_key": "-----BEGIN PRIVATE KEY-----\nxx\n-----END PRIVATE KEY-----\n", "client_id": "1234567890"})
WEB = json.dumps({"web": {"client_id": "111-abc.apps.googleusercontent.com", "client_secret": "GOCSPX-fromJson"}})
INST = json.dumps({"installed": {"client_id": "222-def.apps.googleusercontent.com", "client_secret": "GOCSPX-inst"}})

# ── A. nhận dạng file JSON ────────────────────────────────────────────────────
check("A1 khoá service account", E.json_credential_kind(SA) == ("service_account", "bot@proj.iam.gserviceaccount.com", ""))
check("A2 OAuth client kiểu web", E.json_credential_kind(WEB) == ("oauth_client", "111-abc.apps.googleusercontent.com", "GOCSPX-fromJson"))
check("A3 OAuth client kiểu installed", E.json_credential_kind(INST)[:2] == ("oauth_client", "222-def.apps.googleusercontent.com"))
check("A4 rỗng / hỏng / không phải object → không nhận", all(E.json_credential_kind(x) == ("", "", "")
                                                           for x in (None, "", "{oops", "[1,2]", "{}")))


def add(**kw):
    return am.add_credential("google", kw.pop("name", "x"), scopes=["drive"], **kw)["credential_id"]


def url_of(cred_id):
    return am.build_oauth_url(cred_id, ["drive"], callback_base="http://127.0.0.1:5295")


# ── B. Authorize ──────────────────────────────────────────────────────────────
r = url_of(add(credentials_json=SA, service_account_email="bot@proj.iam.gserviceaccount.com"))
check("B1 service account → KHÔNG dựng link, báo rõ không cần cấp quyền + Drive cần OAuth client",
      r["status"] == "error" and "auth_url" not in r and "service account" in r["message"]
      and "Drive" in r["message"] and "OAuth Client ID" in r["message"], r)

cid = add(credentials_json=WEB)
r = url_of(cid)
q = parse_qs(urlparse(r.get("auth_url", "")).query)
check("B2 file JSON của OAuth client → link có client_id lấy từ file", r["status"] == "success"
      and q.get("client_id") == ["111-abc.apps.googleusercontent.com"], r)
saved = am._data["credentials"][cid]
check("B3 …và Client ID / Secret được lưu để bước đổi mã dùng", saved["client_id"].startswith("111-abc")
      and saved["client_secret"] == "GOCSPX-fromJson")

r = url_of(add())
check("B4 không Client ID, không JSON → báo thiếu Client ID (không mở Google)", r["status"] == "error"
      and "no Client ID" in r["message"], r)

cid = add(client_id="999-own.apps.googleusercontent.com", client_secret="GOCSPX-own", credentials_json=WEB)
r = url_of(cid)
q = parse_qs(urlparse(r.get("auth_url", "")).query)
check("B5 đã gõ Client ID thì dùng cái đã gõ, không lấy của file", q.get("client_id") == ["999-own.apps.googleusercontent.com"]
      and am._data["credentials"][cid]["client_secret"] == "GOCSPX-own")
check("B6 link dùng đúng địa chỉ callback của máy", q.get("redirect_uri") == ["http://127.0.0.1:5295/api/v1/auth-manager/oauth/callback"])

print(f"\n{passed}/{passed + failed} PASS")
sys.exit(1 if failed else 0)
