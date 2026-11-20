"""Lưu tài khoản vào Keychain qua trình kết nối MCP — quyền «keychain», bí mật CHỈ ĐI VÀO két.

Chạy:  python tests/keychain_connector_test.py      (mã thoát 0 = đạt)

Vì sao (user 20/11/2026): «người dùng có thể gửi thông tin của google account hay tài khoản khác qua mcp khi được cho
phép». Chủ bật ô «Allow saving accounts to the Keychain» cho một kết nối trên TubeCLI Cloud › Connectors; agent dùng
keychain_save (ghi) và keychain_accounts (danh sách đã che). Không có đường nào đọc mật khẩu / mã 2FA / email khôi phục ra.

Cách ly: két thật của extension Keychain nhưng file dữ liệu + khoá ở thư mục tạm; không mạng, không đụng data thật.
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

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"[PASS] {name}")
    else:
        failed += 1
        print(f"[FAIL] {name}  {str(detail)[:400]}")


from tubecli.core import claude_connector as CC  # noqa: E402
from tubecli.extensions.codex_gpt import tools as T  # noqa: E402
from tubecli.extensions.keychain import crypto, routes as KR, store as KS  # noqa: E402

TMP = os.path.realpath(tempfile.mkdtemp(prefix="kc_conn_"))
crypto.init(os.path.join(TMP, "key"))
STORE = KS.KeychainStore(os.path.join(TMP, "keychain.json"))
KR.set_store(STORE)

PW = "S3cr3t pass "            # dấu cách cuối: mật khẩu KHÔNG bị strip
TOTP = "JBSWY3DPEHPK3PXP"
REC = "backup@example.com"


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


def text(res):
    return "".join(c.get("text", "") for c in (res.get("result") or res).get("content", []))


def call(name, args, perms=("keychain",), level="write"):
    return run(CC.call(name, dict(args), level, False, app=None, perms=perms, grant=7))


# ── A. quyền ────────────────────────────────────────────────────────────────
check("A1 «keychain» là quyền thêm hợp lệ", "keychain" in CC.PERMS)
r = call("keychain_save", {"platform": "google", "username": "a@gmail.com", "password": PW}, perms=("share",))
check("A2 không có quyền ⇒ từ chối, chỉ đường bật ô", r["result"]["isError"] and "Allow saving accounts" in text(r), text(r))
check("A3 không có quyền ⇒ két không đổi", STORE.list() == [])
r = call("keychain_save", {"platform": "google", "username": "a@gmail.com", "password": PW}, level="read")
check("A4 kết nối chỉ-đọc ⇒ không ghi", r["result"]["isError"] and "read-only" in text(r), text(r))
r = call("keychain_accounts", {}, perms=())
check("A5 danh sách cũng cần quyền", r["result"]["isError"], text(r))
names = [t["name"] for t in T.list_tools()]
check("A6 Codex GPT trên máy (không quyền thêm) không thấy công cụ keychain_*",
      not any(n.startswith("keychain_") for n in names), names)
tw = [t["name"] for t in CC.list_tools("write")]
check("A7 trình kết nối mức ghi thấy cả hai công cụ", {"keychain_save", "keychain_accounts"} <= set(tw))
tr = [t["name"] for t in CC.list_tools("read")]
check("A8 mức đọc chỉ thấy keychain_accounts", "keychain_accounts" in tr and "keychain_save" not in tr, tr)
check("A9 /api/v1/keychain vẫn chặn hẳn cho tubecli_api", "/api/v1/keychain" in T.BLOCK_ALL)

# ── B. lưu mới ──────────────────────────────────────────────────────────────
r = call("keychain_save", {"platform": "google", "username": "A@Gmail.com", "password": PW, "totp": TOTP,
                           "recovery_email": REC, "label": "Work", "notes": "mail 300"})
out = text(r)
check("B1 lưu mới không cần link duyệt", "needs_approval" not in r and not r["result"]["isError"], r)
check("B2 kết quả KHÔNG chứa mật khẩu / khoá 2FA / email khôi phục",
      PW.strip() not in out and TOTP not in out and REC not in out, out)
check("B3 kết quả nói đã ghi bí mật nào (chỉ tên)", "Secrets written: password, totp, recovery_email" in out, out)
acc = STORE.list("google")[0]
full = STORE.get(acc["id"], reveal=True)
check("B4 két giữ đúng mật khẩu (kể cả dấu cách cuối)", full["secret"] == PW, repr(full["secret"]))
check("B5 két giữ khoá 2FA + email khôi phục", full["totp"] == TOTP and full["recovery"] == REC)
raw = open(os.path.join(TMP, "keychain.json"), encoding="utf-8").read()
check("B6 file két trên đĩa đã mã hoá (không có bí mật trần)", PW.strip() not in raw and TOTP not in raw and REC not in raw)
check("B7 nhãn + ghi chú lưu được", full["label"] == "Work" and full["notes"] == "mail 300")

# ── C. cập nhật / an toàn ───────────────────────────────────────────────────
r = call("keychain_save", {"platform": "google", "username": "a@gmail.com", "notes": "mail 301", "password": ""})
check("C1 cùng platform + username (không phân biệt hoa thường) ⇒ cập nhật, không tạo trùng",
      len(STORE.list("google")) == 1 and "Updated" in text(r), text(r))
full = STORE.get(acc["id"], reveal=True)
check("C2 mật khẩu rỗng KHÔNG xoá mật khẩu đã lưu", full["secret"] == PW)
check("C3 ghi chú đổi", full["notes"] == "mail 301")
r = call("keychain_save", {"id": acc["id"], "password": "new-pass"})
check("C4 cập nhật theo id", STORE.get(acc["id"], reveal=True)["secret"] == "new-pass", text(r))
r = call("keychain_save", {"platform": "google", "username": "b@gmail.com"})
check("C5 tài khoản mới thiếu mật khẩu ⇒ lỗi", r["result"]["isError"] and "password" in text(r), text(r))
r = call("keychain_save", {"platform": "myspace", "username": "x", "password": "y"})
check("C6 nền tảng lạ ⇒ lỗi", r["result"]["isError"] and "platform" in text(r), text(r))
r = call("keychain_save", {"id": "nope", "password": "y"})
check("C7 id không có ⇒ lỗi", r["result"]["isError"], text(r))
r = call("keychain_save", {"platform": "google", "username": "c@gmail.com", "password": "x" * 1001})
check("C8 mật khẩu quá dài ⇒ lỗi, không lưu", r["result"]["isError"] and len(STORE.list("google")) == 1, text(r))

# ── D. không lộ bí mật ở đâu cả ─────────────────────────────────────────────
tool = T.TOOLS["keychain_save"]
summ = tool.summary({"platform": "google", "username": "a@gmail.com", "password": PW, "totp": TOTP,
                     "recovery_email": REC})
check("D1 tóm tắt (thẻ duyệt / nhật ký) không có bí mật", PW.strip() not in summ and TOTP not in summ and REC not in summ, summ)
check("D2 keychain_save không bao giờ cần link duyệt (tham số không vào bảng duyệt của cloud)",
      not CC.is_dangerous(tool, {"platform": "google", "username": "a", "password": "p"}))
r = call("keychain_accounts", {})
lst = text(r)
check("D3 danh sách không có bí mật", "new-pass" not in lst and TOTP not in lst and REC not in lst, lst)
rows = json.loads(lst.split("\n", 1)[1])
check("D4 danh sách có cờ đã lưu", rows[0]["has_password"] and rows[0]["has_2fa"] and rows[0]["has_recovery_email"], rows)
r = call("keychain_accounts", {"filter": "301"})
check("D5 lọc theo ghi chú", "a@gmail.com" in text(r), text(r))
r = call("keychain_accounts", {"filter": "zzz"})
check("D6 lọc không khớp ⇒ 0", text(r).startswith("0 Keychain"), text(r))

# ── E. két tắt ──────────────────────────────────────────────────────────────
KR.set_store(None)
r = call("keychain_accounts", {})
check("E1 Keychain tắt ⇒ báo rõ", r["result"]["isError"] and "turned off" in text(r), text(r))
KR.set_store(STORE)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
