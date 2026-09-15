# -*- coding: utf-8 -*-
"""Cloudflare xoay qua MỌI account (lõi .103, 15/9/2026).

User: "lỗi tạo ảnh claudflare không xoay tua" (Codex: "stopped after the first shot failed: HTTP 429 … daily free
allocation of 10,000 neurons") + "phải bấm chọn lại model mới được". KeyManager thật trên file tạm, Cloudflare giả.

Kiểm:
  A. ba account: a, b hết hạn mức ngày → c vẽ được; a, b đỗ tới 00:00 UTC; shot sau đi thẳng c
  B. Global API Key dùng chung (cùng khoá, khác account_id): chỉ đỗ account lỗi, xoay sang account kia
  C. Studio thử lại shot với r vẫn giữ account ĐÃ ĐỖ → đổi account TRƯỚC khi gọi (không đập vào account đỗ)
  D. 429 thường (không phải hết hạn mức ngày) → đỗ ~60 s, không 15 phút
  E. mọi account đang đỗ nhưng có account mở lại trong ≤ 75 s → chờ rồi vẽ tiếp
  F. hết cách → lỗi giữ câu gốc + kể từng account, lý do, lúc mở lại; account tắt tay → bảo bật lại
  G. report_key_error theo nhãn / account_id; KeyManager cũ (không có cloudflare_accounts) → ném lỗi gốc

Run:  python tests/key_rotation_accounts_test.py
"""
import asyncio
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

import tubecli.config as CFG  # noqa: E402
TMP = Path(tempfile.mkdtemp(prefix="key_rot_acc_"))
CFG.GLOBAL_SETTINGS_FILE = TMP / "global_settings.json"
from tubecli.extensions.cloud_api import extension as ext  # noqa: E402
from tubecli.core import image_gen as G  # noqa: E402

PASS = FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", label)
    else:
        FAIL += 1
        print("  FAIL", label, "—", str(detail)[:300])


DAILY = "HTTP 429: {\"errors\":[{\"message\":\"AiError: AiError: you have used up your daily free allocation of 10,000 neurons, please upgrade to Cloudflare's Workers Paid plan\"}],\"code\":400}"
calls = []
BEHAVIOUR = {}          # account_id → "daily" | "rate" | "auth" | "ok"


async def fake_cf(r, prompt, aspect_ratio, timeout):
    acc = r["creds"]["account_id"]
    calls.append(r["creds"]["label"])
    how = BEHAVIOUR.get(acc, "ok")
    if how == "daily":
        raise G.ProviderError("rate_limit", DAILY)
    if how == "rate":
        raise G.ProviderError("rate_limit", "HTTP 429: {\"errors\":[{\"message\":\"Too many requests\"}]}")
    if how == "auth":
        raise G.ProviderError("auth", "HTTP 401: Authentication error")
    return b"\xff\xd8\xff" + acc.encode()


G._cf_generate = fake_cf
slept = []


def fresh(*accounts):
    """accounts: (label, token, account_id). Kho khoá mới."""
    km = ext.KeyManager(data_file=str(TMP / f"keys_{time.time_ns()}.json"))
    for label, tok, acc in accounts:
        km.add_cloudflare_key(tok, acc, label=label)
    G._key_manager = lambda: km
    calls.clear(), slept.clear(), BEHAVIOUR.clear()
    return km


def run(r, prompt="apple"):
    return asyncio.run(G.generate_bytes(r, prompt))


print("── A. ba account ───────────────────────────────────────────")
km = fresh(("a", "tokA", "accA"), ("b", "tokB", "accB"), ("c", "tokC", "accC"))
BEHAVIOUR.update({"accA": "daily", "accB": "daily"})
r = G.resolve_provider("cloudflare", "@cf/x")
data = run(r)
ok(data.endswith(b"accC") and calls == ["a", "b", "c"], "a, b hết hạn mức → vẽ bằng c (bản .95 dừng ở b)", calls)
ea, eb = km._keys["cloudflare"]["a"], km._keys["cloudflare"]["b"]
ok(not ea["active"] and not eb["active"] and 0 < ea["disabled_until"] - time.time() <= 86400
   and km._keys["cloudflare"]["c"]["active"], "a, b đỗ tới 00:00 UTC; c vẫn bật", (ea.get("disabled_until"), eb.get("disabled_until")))
ok(r["label"] == "c" and r["rotated_to"] == "c" and r["creds"]["account_id"] == "accC", "r mang account c", r.get("label"))
calls.clear()
run(r, "shot 2")
ok(calls == ["c"], "shot sau đi thẳng c", calls)

print("── B. Global API Key dùng chung cho hai account ────────────")
km = fresh(("g1", "GLOBALKEY", "acc1"), ("g2", "GLOBALKEY", "acc2"))
BEHAVIOUR.update({"acc1": "daily"})
r = G.resolve_provider("cloudflare", "@cf/x")
data = run(r)
ok(data.endswith(b"acc2") and calls == ["g1", "g2"], "cùng khoá, khác account → vẫn xoay (bản .95 coi là một)", calls)
ok(not km._keys["cloudflare"]["g1"]["active"] and km._keys["cloudflare"]["g2"]["active"], "chỉ đỗ account lỗi, không đỗ cả nhóm")

print("── C. thử lại shot với r giữ account đã đỗ ─────────────────")
km = fresh(("a", "tokA", "accA"), ("b", "tokB", "accB"))
r = G.resolve_provider("cloudflare", "@cf/x")               # r = a
km.report_key_error("cloudflare", "tokA", DAILY, transient=True, until=time.time() + 3600, only_label="a")
data = run(r)
ok(data.endswith(b"accB") and calls == ["b"], "a đang đỗ → đổi sang b TRƯỚC khi gọi, không gọi a", calls)

print("── D. 429 thường → đỗ ngắn ─────────────────────────────────")
km = fresh(("a", "tokA", "accA"), ("b", "tokB", "accB"))
BEHAVIOUR.update({"accA": "rate"})
run(G.resolve_provider("cloudflare", "@cf/x"))
ea = km._keys["cloudflare"]["a"]
ok(calls == ["a", "b"] and 0 < ea["disabled_until"] - time.time() <= G.CF_RATE_COOLDOWN_SEC + 1, "429 theo phút → đỗ ~60 s rồi xoay", ea.get("disabled_until"))

print("── E. mọi account đỗ, có account mở lại sớm → chờ ─────────")
km = fresh(("a", "tokA", "accA"), ("b", "tokB", "accB"))
BEHAVIOUR.update({"accA": "daily"})
km.report_key_error("cloudflare", "tokB", "HTTP 429: Too many requests", transient=True, until=time.time() + 30, only_label="b")


async def fake_sleep(sec):
    slept.append(sec)
    km._keys["cloudflare"]["b"]["disabled_until"] = time.time() - 1      # thời gian trôi: b tới hạn
    km._save()


G._sleep = fake_sleep
data = run(G.resolve_provider("cloudflare", "@cf/x"))
ok(data.endswith(b"accB") and calls == ["a", "b"] and len(slept) == 1 and slept[0] <= G.CF_WAIT_MAX_SEC + 1,
   "a hết hạn mức, b mở lại sau 30 s → chờ một lần rồi vẽ bằng b", (calls, slept))

print("── F. hết cách → kể từng account ───────────────────────────")
km = fresh(("a", "tokA", "accA"), ("b", "tokB", "accB"), ("off", "tokO", "accO"))
BEHAVIOUR.update({"accA": "daily", "accB": "daily"})
km.report_key_error("cloudflare", "tokO", "HTTP 401: Authentication error", transient=False, only_label="off")
try:
    run(G.resolve_provider("cloudflare", "@cf/x")); ok(False, "phải ném")
except G.ProviderError as e:
    msg = str(e)
    ok(e.kind == "rate_limit" and msg.startswith("HTTP 429:") and "Cloudflare accounts tried:" in msg
       and "a — daily free allocation used up, resumes" in msg and "b — daily free allocation used up, resumes" in msg
       and "off — HTTP 401: Authentication error (turned off — re-enable it in Cloud API Keys)" in msg
       and "Add another Cloudflare account" in msg, "giữ câu gốc + từng account, lý do, lúc mở lại", msg)
    ok(calls == ["a", "b"] and not slept, "không gọi account tắt tay, không chờ khi mở lại lúc 00:00", (calls, slept))
res = asyncio.run(G.generate_image("apple", str(TMP / "x.jpg"), provider="cloudflare", model="@cf/x"))
ok(res["status"] == "error" and "All Cloudflare accounts are paused" in res["message"]
   and "a — daily free allocation used up, resumes" in res["message"] and "Chưa có credential" not in res["message"],
   "mọi account đang đỗ ngay lúc chọn nhà → kể từng account (không còn 'Chưa có credential')", res)

print("── G. đỗ theo nhãn / account; KeyManager cũ ────────────────")
km = fresh(("x1", "SAME", "accX1"), ("x2", "SAME", "accX2"))
km.report_key_error("cloudflare", "SAME", "boom", transient=True, until=time.time() + 60, account_id="accX2")
ok(km._keys["cloudflare"]["x1"]["active"] and not km._keys["cloudflare"]["x2"]["active"], "report_key_error(account_id=) đỗ đúng account")
km.report_key_error("cloudflare", "SAME", "boom", transient=True)
ok(not km._keys["cloudflare"]["x1"]["active"], "không nhãn / account → đỗ theo khoá như cũ (tương thích)")
accs = km.cloudflare_accounts()
ok([a["label"] for a in accs] == ["x1", "x2"] and all("api_token" in a and "disabled_until" in a for a in accs), "cloudflare_accounts theo thứ tự đã lưu")


class OldKM:
    """cloud_api cũ: không có cloudflare_accounts, report_key_error chưa nhận only_label/account_id."""

    def get_cloudflare_creds(self, label="default"):
        return {"api_token": "tokOld", "account_id": "accOld", "email": "", "label": "old"}

    def report_key_error(self, provider, api_key, msg, transient=False, until=None):
        self.reported = (provider, api_key, transient, until)


old = OldKM()
G._key_manager = lambda: old
calls.clear()
BEHAVIOUR.update({"accOld": "daily"})
try:
    run(G.resolve_provider("cloudflare", "@cf/x")); ok(False, "phải ném")
except G.ProviderError as e:
    ok(str(e) == DAILY and calls == ["old"] and old.reported[0] == "cloudflare", "KeyManager cũ → vẫn đỗ theo khoá, ném lỗi gốc", (str(e)[:40], calls))

print()
print(f"{PASS}/{PASS + FAIL} PASS" if not FAIL else f"{PASS}/{PASS + FAIL} PASS — {FAIL} HỎNG")
sys.exit(1 if FAIL else 0)
