"""Auth Manager: sửa một credential KHÔNG được làm mất Client ID / Secret đã lưu; nút mắt chỉ mở tại máy.

Chạy:  python tests/auth_manager_edit_keep_secret_test.py      (mã thoát 0 = đạt)

Vì sao (user 15/11/2026): «tôi nhập key rồi nhưng khi edit lại không thấy, và không có mắt để mở xem phần secret».
Form Edit để trống hai ô (máy chủ che khoá) rồi gửi chuỗi RỖNG lên; update_credential ghi "" đè lên — đổi tên một
credential là mất khoá. Nay ô trống = giữ nguyên; danh sách báo has_secret; GET /credentials/{id}/reveal trả nguyên
văn CHỈ khi dashboard mở ngay trên máy (không qua tunnel / cloud).

Cách ly: tệp auth_manager.json trong thư mục tạm — không đụng credential thật của máy; không mạng.
"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass
TMP = tempfile.mkdtemp(prefix="am_edit_")

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
from tubecli.extensions.auth_manager import routes as R  # noqa: E402
from fastapi import HTTPException  # noqa: E402

DATA = os.path.join(TMP, "auth_manager.json")
am = E.AuthManager(data_file=DATA)
check("0 tệp dữ liệu nằm trong thư mục tạm", am.data_file.startswith(TMP), am.data_file)
E.auth_manager = am                     # route đọc `from .extension import auth_manager`

CID = "135642621234-abcdefghijklmnop.apps.googleusercontent.com"
SEC = "GOCSPX-thisIsTheSecret_1234567890"
am._data["credentials"]["cred_x"] = {"provider": "google", "name": "Google", "client_id": CID, "client_secret": SEC,
                                     "credentials_json": "", "scopes": ["youtube"], "created_at": "2026-11-15T08:17:00"}
am._save()

# ── A. sửa mà để trống ô khoá ─────────────────────────────────────────────────
r = am.update_credential("cred_x", name="Kênh chính", client_id="", client_secret="", credentials_json="")


class _Current:
    """Bản ghi HIỆN TẠI của cred_x — mỗi thao tác của AuthManager đọc lại tệp, nên không giữ tham chiếu cũ."""

    def __getitem__(self, key):
        return am._data["credentials"]["cred_x"][key]


c = _Current()
check("A1 đổi tên, hai ô khoá để trống → tên đổi", r["status"] == "success" and c["name"] == "Kênh chính")
check("A2 …Client ID và Secret GIỮ NGUYÊN (trước bị ghi đè thành rỗng)", c["client_id"] == CID and c["client_secret"] == SEC, c)
r = am.update_credential("cred_x", client_id="   ", client_secret="\n")
check("A3 chỉ có khoảng trắng cũng coi là để trống", c["client_id"] == CID and c["client_secret"] == SEC)
am.update_credential("cred_x", client_id="***masked", client_secret="***")
check("A4 giá trị che (***) vẫn bị bỏ qua như cũ", c["client_id"] == CID and c["client_secret"] == SEC)
am.update_credential("cred_x", client_secret="GOCSPX-newSecret_0987654321")
check("A5 gõ Secret MỚI → thay được, Client ID giữ", c["client_secret"] == "GOCSPX-newSecret_0987654321" and c["client_id"] == CID)
am.update_credential("cred_x", client_secret=SEC)
on_disk = json.load(open(DATA, encoding="utf-8"))["credentials"]["cred_x"]
check("A6 trên đĩa cũng còn nguyên khoá", on_disk["client_id"] == CID and on_disk["client_secret"] == SEC)

# ── B. danh sách ──────────────────────────────────────────────────────────────
row = next(x for x in am.list_credentials() if x["id"] == "cred_x")
check("B1 danh sách che Client ID, KHÔNG có Secret, báo has_secret", row["client_id"] != CID and "client_secret" not in row
      and row["has_secret"] is True and SEC not in json.dumps(row), row)
am._data["credentials"]["cred_empty"] = {"provider": "google", "name": "trống", "client_id": "", "client_secret": ""}
am._save()
check("B2 credential chưa có Secret → has_secret False", next(x for x in am.list_credentials() if x["id"] == "cred_empty")["has_secret"] is False)


# ── C. nút mắt: chỉ tại máy ───────────────────────────────────────────────────
class Req:
    def __init__(self, host, headers=None):
        self.client = type("C", (), {"host": host})()
        self.headers = headers or {}


def reveal(req, cid="cred_x"):
    try:
        return 200, asyncio.run(R.api_reveal_credential(cid, req))
    except HTTPException as e:
        return e.status_code, e.detail


code, body = reveal(Req("127.0.0.1"))
check("C1 mở tại máy (loopback, không qua proxy) → trả nguyên văn", code == 200 and body == {"client_id": CID, "client_secret": SEC}, (code, body))
code, body = reveal(Req("203.0.113.9"))
check("C2 từ xa → 403, không lộ gì", code == 403 and SEC not in str(body), (code, body))
code, body = reveal(Req("127.0.0.1", {"cf-connecting-ip": "203.0.113.9", "x-forwarded-for": "203.0.113.9"}))
check("C3 loopback nhưng do TUNNEL chuyển tới (có header proxy) → 403", code == 403 and SEC not in str(body), (code, body))
code, body = reveal(Req("127.0.0.1"), "khong-co")
check("C4 credential không tồn tại → 404", code == 404)

# ── D. giao diện ──────────────────────────────────────────────────────────────
js = (ROOT / "tubecli" / "extensions" / "webui" / "static" / "auth_manager.js").read_text(encoding="utf-8")
html = (ROOT / "tubecli" / "extensions" / "webui" / "static" / "auth_manager.html").read_text(encoding="utf-8")
check("D1 form có nút mắt cạnh ô Secret + dòng «khoá đã lưu»", 'id="cred-secret-eye"' in html and 'onclick="toggleCredSecret()"' in html
      and 'id="cred-saved-hint"' in html)
edit = js[js.index("function editCredential(credId)"):js.index("function editCredential(credId)") + 1200]
check("D2 mở Edit → hiện gợi ý khoá đã lưu", "credSavedHint(cred);" in edit)
check("D3 mở form MỚI → ẩn gợi ý", "credSavedHint(null);" in js)
eye = js[js.index("async function toggleCredSecret()"):js.index("function editCredential(credId)")]
check("D4 nút mắt: ô trống lúc sửa thì gọi /reveal, lỗi thì báo chứ không điền bừa",
      "/credentials/${editId}/reveal" in eye and "showToast(" in eye and "secret.type = 'text'" in eye)

print(f"\n{passed}/{passed + failed} PASS")
sys.exit(1 if failed else 0)
