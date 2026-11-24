# -*- coding: utf-8 -*-
"""Keychain: nhóm, proxy từng tài khoản, dán hàng loạt từ bảng tính (user 24/11/2026: «tạo nhóm "mail 1" và paste dữ liệu
từ sheet — email password recovermail 2fa proxy», «nhóm có dấu + để thêm, trong list chọn có xoá»).

  A. proxy_host: mọi dạng nhà cung cấp; không bao giờ kèm user / mật khẩu
  B. nhóm: tạo bằng «+» (nhóm rỗng vẫn sống, lưu xuống đĩa), trùng hoa thường = một nhóm, xoá nhóm GIỮ tài khoản
  C. dán hàng loạt: một lần ghi đĩa, vào nhóm, trùng email thì cập nhật / bỏ qua, ô trống không xoá bí mật đã lưu,
     dòng lỗi báo số dòng + lý do và KHÔNG có bí mật, proxy lạ bị từ chối
  D. bí mật (kể cả proxy) không nằm dạng chữ trên đĩa, không có trong danh sách / kết quả nhập
  E. route HTTP: /accounts có groups + features, lọc nhóm, /groups, /groups/delete, /import cũ vẫn chạy như cũ
  F. hồ sơ trình duyệt tạo cho tài khoản mang proxy của tài khoản
  G. MCP keychain_save / keychain_accounts: nhóm + proxy chỉ ghi vào

Chạy:  python tests/keychain_groups_test.py   (exit 0 = pass). Dữ liệu giả, két + khoá trong thư mục tạm, không mạng.
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
os.environ["TUBECLI_CODEX_GPT_DIR"] = tempfile.mkdtemp(prefix="kc_groups_codex_")

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"[PASS] {name}")
    else:
        FAIL += 1
        print(f"[FAIL] {name} -> {str(detail)[:400]}")


from tubecli.extensions.keychain import crypto, routes as KR, store as KS  # noqa: E402

TMP = os.path.realpath(tempfile.mkdtemp(prefix="kc_groups_"))
crypto.init(os.path.join(TMP, "key"))
FILE = os.path.join(TMP, "keychain.json")
ST = KS.KeychainStore(FILE)
KR.set_store(ST)
saves = [0]
_orig_save = ST._save


def counted_save():
    saves[0] += 1
    _orig_save()


ST._save = counted_save
PW1, PW2 = "Fake-Pass 1", "fake-pass-2"
TOTP = "abcd efgh ijkl mnop qrst uvwx yz23 4567"
PROXY_PW = "zz9proxypw"
PROXY = f"10.20.30.40:9100:proxyuser:{PROXY_PW}"


def disk():
    return open(FILE, encoding="utf-8").read()


# ── A ──
for raw, want in [(PROXY, "10.20.30.40:9100"), ("u:p@1.2.3.4:80", "1.2.3.4:80"), ("http://u:p@h.com:8080", "h.com:8080"),
                  ("socks5://1.2.3.4:1080", "1.2.3.4:1080"), ("1.2.3.4:80", "1.2.3.4:80"), ("http://h.com:80:u:p", "h.com:80"),
                  ("user:p@ss@1.2.3.4:80", "1.2.3.4:80"), ("[2001:db8::1]:8080", "[2001:db8::1]:8080"),
                  ("", ""), ("abc", ""), ("1.2.3.4:99999", ""), ("1.2.3.4:80:onlyuser", ""), ("a b:80", "")]:
    check(f"A proxy_host({raw[:22]!r}) = {want!r}", KS.proxy_host(raw) == want, KS.proxy_host(raw))

# ── B ──
g = ST.add_group("  mail   1 ")
check("B1 «+» tạo nhóm rỗng, tên gọn khoảng trắng", g == "mail 1" and ST.groups() == {"mail 1": 0}, ST.groups())
check("B2 nhóm rỗng lưu xuống đĩa (mở lại vẫn còn)", KS.KeychainStore(FILE).groups() == {"mail 1": 0})
check("B3 thêm «MAIL 1» = cùng nhóm, không tạo trùng", ST.add_group("MAIL 1") == "mail 1" and list(ST.groups()) == ["mail 1"])
try:
    ST.add_group("   ")
    check("B4 tên rỗng bị từ chối", False)
except ValueError:
    check("B4 tên rỗng bị từ chối", True)

# ── C ──
rows = [{"username": "a1@example.com", "secret": PW1, "recovery": "r1@example.org", "totp": TOTP, "proxy": PROXY, "group": "Mail 1", "platform": "google", "_line": 1},
        {"username": "a2@example.com", "secret": PW2, "platform": "google", "group": "mail 1", "_line": 2},
        {"username": "", "secret": "x", "platform": "google", "_line": 3},
        {"username": "a4@example.com", "secret": "pw4", "proxy": "not a proxy", "platform": "google", "_line": 4}]
saves[0] = 0
r = ST.bulk_upsert(rows)
check("C1 hai dòng tốt được tạo, MỘT lần ghi đĩa", r["created"] == 2 and saves[0] == 1, (r, saves))
check("C2 dòng lỗi: số dòng + lý do, không bí mật", r["errors"] == [{"line": 3, "reason": "missing username / email"},
                                                           {"line": 4, "user": "a4@example.com", "reason": "proxy not understood"}]
      and "pw4" not in json.dumps(r) and PW1 not in json.dumps(r), r)
check("C3 vào nhóm có sẵn, giữ cách viết cũ", {x["group"] for x in ST.list(group="mail 1")} == {"mail 1"} and ST.groups()["mail 1"] == 2, ST.groups())
a1 = ST.find("google", "A1@EXAMPLE.COM")
full = ST.get(a1["id"], reveal=True)
check("C4 đủ 5 trường; mật khẩu giữ nguyên dấu cách", full["secret"] == PW1 and full["recovery"] == "r1@example.org"
      and full["totp"] == TOTP and full["proxy"] == PROXY and a1["proxy_host"] == "10.20.30.40:9100" and a1["has_proxy"], {k: v for k, v in a1.items()})
r = ST.bulk_upsert([{"username": "a1@example.com", "secret": "", "proxy": "", "notes": "renewed", "platform": "google", "group": "mail 1"}])
full = ST.get(a1["id"], reveal=True)
check("C5 dán lại cùng email: cập nhật, ô trống KHÔNG xoá mật khẩu / proxy", r["updated"] == 1 and r["created"] == 0
      and full["secret"] == PW1 and full["proxy"] == PROXY and full["notes"] == "renewed", r)
r = ST.bulk_upsert([{"username": "a2@example.com", "secret": "new", "platform": "google"}], on_exists="skip")
check("C6 on_exists=skip: không đụng tài khoản đã có", r["skipped"] == 1 and ST.get(ST.find("google", "a2@example.com")["id"], reveal=True)["secret"] == PW2)
r = ST.bulk_upsert([{"username": "a1@example.com", "secret": "x", "platform": "facebook"}])
check("C7 cùng email khác nền tảng = tài khoản khác", r["created"] == 1)
r = ST.bulk_upsert([{"username": f"m{i}@example.com", "secret": "p", "platform": "google"} for i in range(KS.MAX_BULK + 3)])
check("C8 quá trần dòng: nhận tới trần, báo phần thừa", r["created"] == KS.MAX_BULK and r["errors"][-1]["line"] == KS.MAX_BULK + 1, r["errors"][-1:])
for x in ST.list(platform="google"):
    if x["username"].startswith("m"):
        ST.delete(x["id"])

# ── D ──
d = disk()
check("D1 trên đĩa không có mật khẩu / 2FA / user:pass của proxy dạng chữ", PW1 not in d and TOTP not in d and PROXY_PW not in d
      and "proxyuser" not in d and "10.20.30.40:9100" in d)
lst = json.dumps(ST.list())
check("D2 danh sách không có bí mật nào (chỉ host:port của proxy)", PW1 not in lst and PROXY_PW not in lst and "proxyuser" not in lst
      and "10.20.30.40:9100" in lst)

# ── B (xoá) ──
before = len(ST.list())
r = ST.delete_group("MAIL 1")
check("B5 xoá nhóm: GIỮ tài khoản, chuyển về «chưa có nhóm»", r == {"deleted": True, "moved": 2} and len(ST.list()) == before
      and "mail 1" not in ST.groups() and len(ST.list(group="")) == before, (r, ST.groups()))
check("B6 xoá nhóm không có → deleted False", ST.delete_group("nope") == {"deleted": False, "moved": 0})
check("B7 mở lại két: nhóm đã xoá không quay lại", "mail 1" not in KS.KeychainStore(FILE).groups())

# ── E ──
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

app = FastAPI()
app.include_router(KR.router)
c = TestClient(app)
j = c.get("/api/v1/keychain/accounts").json()
check("E1 /accounts có groups + features (cloud biết máy hiểu nhóm / proxy / dán)", set(j["features"]) >= {"groups", "proxy", "bulk"}
      and "groups" in j, j.keys())
j = c.post("/api/v1/keychain/groups", json={"name": "mail 2"}).json()
check("E2 POST /groups", j["group"] == "mail 2" and j["groups"]["mail 2"] == 0, j)
body = {"group": "mail 2", "on_exists": "update", "default_platform": "google", "rows": [
    {"_line": 1, "username": "b1@example.com", "secret": "pb1", "recovery": "rb1@example.org", "totp": "AAAA BBBB", "proxy": "1.1.1.1:80:u:pp1"},
    {"_line": 2, "username": "b2@example.com", "secret": "pb2", "proxy": "bad"}]}
j = c.post("/api/v1/keychain/import", json=body).json()
check("E3 /import dán vào nhóm: 1 tạo, 1 lỗi proxy, không bí mật trong trả lời", j["created"] == 1 and j["errors"][0]["line"] == 2
      and j["groups"]["mail 2"] == 1 and "pb1" not in json.dumps(j) and "pp1" not in json.dumps(j), j)
b1 = ST.get(ST.find("google", "b1@example.com")["id"], reveal=True)
check("E4 2FA dạng nhóm 4 ký tự được ghép liền; nền tảng mặc định google", b1["totp"] == "AAAABBBB" and b1["platform"] == "google", b1["totp"])
j = c.get("/api/v1/keychain/accounts", params={"group": "mail 2"}).json()
check("E5 lọc theo nhóm", [x["username"] for x in j["accounts"]] == ["b1@example.com"], j["accounts"])
j = c.get("/api/v1/keychain/accounts", params={"group": ""}).json()
check("E6 group= (rỗng) = chưa có nhóm", all(not x["group"] for x in j["accounts"]) and len(j["accounts"]) >= 2)
j = c.post("/api/v1/keychain/groups/delete", json={"name": "mail 2"}).json()
check("E7 POST /groups/delete giữ tài khoản", j["moved"] == 1 and ST.find("google", "b1@example.com") is not None and "mail 2" not in j["groups"], j)
n0 = len(ST.list())
j = c.post("/api/v1/keychain/import", json={"rows": [{"email": "old@example.com", "password": "x"}, {"email": "old@example.com", "password": "y"}]}).json()
check("E8 /import kiểu cũ (không on_exists) vẫn như trước: luôn tạo mới", j["created"] == 2 and len(ST.list()) == n0 + 2, j)
r = c.post("/api/v1/keychain/accounts", json={"platform": "google", "username": "c@example.com", "proxy": "garbage"})
check("E9 tạo tay với proxy lạ → 400", r.status_code == 400 and "Proxy" in r.text, r.text)
r = c.post("/api/v1/keychain/accounts", json={"platform": "google", "username": "c@example.com", "proxy": PROXY, "group": "Mail 3"})
acc = r.json()
check("E10 tạo tay có nhóm + proxy", r.status_code == 200 and acc["group"] == "Mail 3" and acc["proxy_host"] == "10.20.30.40:9100"
      and PROXY_PW not in r.text, r.text)
r = c.put(f"/api/v1/keychain/accounts/{acc['id']}", json={"platform": "google", "group": ""})
check("E11 sửa: bỏ nhóm, proxy giữ nguyên", r.json()["group"] == "" and r.json()["has_proxy"], r.json())
r = c.get(f"/api/v1/keychain/accounts/{acc['id']}", params={"reveal": 1}).json()
check("E12 reveal (chỉ chủ) trả proxy đầy đủ để sửa", r["proxy"] == PROXY)

# ── F ──
import types  # noqa: E402

made = {}
pm = types.ModuleType("tubecli.extensions.browser.profile_manager")
pm.get_profile = lambda n: made.get(n)
pm.create_profile = lambda n, proxy="", **k: made.__setitem__(n, {"proxy": proxy})
pm.update_profile = lambda n, **k: made[n].update(k)
real_pm = sys.modules.get("tubecli.extensions.browser.profile_manager")
sys.modules["tubecli.extensions.browser.profile_manager"] = pm
try:
    out = KR.ensure_profile_for_account(acc["id"])
    check("F1 hồ sơ tạo cho tài khoản mang proxy của nó", out["created"] and made[out["profile"]]["proxy"] == PROXY, made)
    plain = ST.create({"platform": "google", "username": "noproxy@example.com", "secret": "x"})
    out = KR.ensure_profile_for_account(plain["id"])
    check("F2 tài khoản không proxy → hồ sơ không proxy", made[out["profile"]]["proxy"] == "")
finally:
    if real_pm is not None:
        sys.modules["tubecli.extensions.browser.profile_manager"] = real_pm
    else:
        sys.modules.pop("tubecli.extensions.browser.profile_manager", None)

# ── G ──
from tubecli.extensions.codex_gpt import tools as T  # noqa: E402


async def _yes(*a, **k):
    return True, "", ""


def mcp(name, args):
    r = asyncio.run(T.call_tool(name, args, None, _yes, perms=("keychain",)))
    return r["isError"], r["content"][0]["text"]


err, txt = mcp("keychain_save", {"platform": "google", "username": "g@example.com", "password": "gpw", "group": "mail 9", "proxy": PROXY})
check("G1 keychain_save nhận nhóm + proxy, không nhắc lại proxy", not err and PROXY_PW not in txt and '"group": "mail 9"' in txt
      and "10.20.30.40:9100" in txt, txt)
err, txt = mcp("keychain_save", {"platform": "google", "username": "g2@example.com", "password": "x", "proxy": "nonsense"})
check("G2 proxy lạ → lỗi, không lưu", err and "proxy" in txt and ST.find("google", "g2@example.com") is None, txt)
err, txt = mcp("keychain_accounts", {"group": "mail 9"})
check("G3 keychain_accounts lọc nhóm, có has_proxy + host, không mật khẩu proxy", not err and "g@example.com" in txt
      and '"has_proxy": true' in txt and PROXY_PW not in txt and "b1@example.com" not in txt, txt)
check("G4 schema công cụ có group + proxy", "proxy" in T.TOOLS["keychain_save"].schema["properties"]
      and "group" in T.TOOLS["keychain_accounts"].schema["properties"])

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
