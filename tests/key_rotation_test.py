# -*- coding: utf-8 -*-
"""Xoay khoá cho bộ vẽ ảnh (15/9/2026): Cloudflare hết hạn mức → đỗ tới 00:00 UTC, xoay ngay sang tài
khoản khác; KeyManager đỗ theo mốc giờ và hồi cả khoá Cloudflare.

User: "hiện tại có logic xoay key chưa?" sau khi Thử vẽ trả 429 "used up your daily free allocation".

Kiểm (KeyManager thật trên file tạm, nhà cung cấp giả):
  A. report_key_error(until=) đỗ tới mốc; get_cloudflare_creds hồi khoá khi tới mốc; cooldown cũ vẫn chạy
  B. generate_bytes: tài khoản 'a' 429 hết hạn mức → 'a' đỗ tới 00:00 UTC, xoay sang 'b' ngay, r mang creds 'b'
     + rotated_to; shot sau đi thẳng 'b' (không gọi 'a' nữa); chỉ một tài khoản → ném 429, test_draw kèm gợi ý
  C. lỗi khoá (401) → đỗ cứng (không tự hồi); từ chối nội dung → không đỗ, không xoay; Gemini vẫn báo như cũ
  D. resolve/public_resolution mang label; Studio engine không copy r

Run:  python tests/key_rotation_test.py
"""
import asyncio
import os
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
TMP = Path(tempfile.mkdtemp(prefix="key_rot_"))
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


km = ext.KeyManager(data_file=str(TMP / "keys.json"))
km.add_cloudflare_key("tokA", "accA", label="a")
km.add_cloudflare_key("tokB", "accB", label="b")
G._key_manager = lambda: km

print("── A. KeyManager đỗ theo mốc + hồi Cloudflare ─────────────")
ok(km.get_cloudflare_creds()["label"] == "a", "mặc định: tài khoản đầu tiên đang bật (a)")
km.report_key_error("cloudflare", "tokA", "daily quota", transient=True, until=time.time() + 3600)
ok(km.get_cloudflare_creds()["label"] == "b", "đỗ 'a' tới mốc → get_cloudflare_creds trả 'b'")
e = km._keys["cloudflare"]["a"]
ok(e["active"] is False and e.get("disable_reason") == "transient" and e.get("disabled_until"), "mục 'a' ghi disabled_until", e)
e["disabled_until"] = time.time() - 1
km._save()
ok(km.get_cloudflare_creds()["label"] == "a", "tới mốc → 'a' được hồi ngay trong get_cloudflare_creds")
km.report_key_error("cloudflare", "tokA", "429", transient=True)
km._keys["cloudflare"]["a"]["disabled_at"] = time.time() - ext.TRANSIENT_COOLDOWN_SECONDS - 1
km._save()
ok(km.get_cloudflare_creds()["label"] == "a", "không có mốc → cooldown cố định như cũ")
ok(any(k.get("disabled_until") is None and "status_msg" in k for k in km.list_cloudflare_keys()), "list_cloudflare_keys có status_msg/disabled_until")

print("── B. xoay ngay trong lượt vẽ ─────────────────────────────")
calls = []


async def fake_cf(r, prompt, aspect_ratio, timeout):
    tok = r["creds"]["api_token"]
    calls.append(tok)
    if tok == "tokA":
        raise G.ProviderError("rate_limit", "HTTP 429: you have used up your daily free allocation of 10,000 neurons")
    return b"\xff\xd8\xff" + b"b" * 20


G._cf_generate = fake_cf
r = G.resolve_provider("cloudflare", "@cf/x")
ok(r["label"] == "a", "resolve → 'a' kèm label", r)
data = asyncio.run(G.generate_bytes(r, "apple"))
ok(data.startswith(b"\xff\xd8") and calls == ["tokA", "tokB"], "'a' 429 → xoay sang 'b' ngay, vẽ được", calls)
ok(r["rotated_to"] == "b" and r["creds"]["api_token"] == "tokB" and r["label"] == "b", "r mang tài khoản mới (creds/label/rotated_to)", {k: r.get(k) for k in ("rotated_to", "label")})
ea = km._keys["cloudflare"]["a"]
ok(ea["active"] is False and ea.get("disabled_until") and ea["disabled_until"] > time.time() and ea["disabled_until"] - time.time() <= 86400,
   "'a' đỗ tới 00:00 UTC (≤ 24 giờ)", ea.get("disabled_until"))
calls.clear()
asyncio.run(G.generate_bytes(r, "second shot"))
ok(calls == ["tokB"], "shot sau đi thẳng 'b', không gọi 'a' nữa", calls)
res = asyncio.run(G.generate_image("apple", str(TMP / "x.jpg"), resolved=G.resolve_provider("cloudflare", "@cf/x")))
ok(res["status"] == "success" and res["label"] == "b", "generate_image: resolve lại cũng ra 'b' (a đang đỗ), kết quả có label", res)
km.report_key_error("cloudflare", "tokB", "x", transient=True, until=time.time() + 3600)   # cả hai đều đỗ
km._keys["cloudflare"]["a"]["disabled_until"] = time.time() - 1                            # chỉ 'a' sống, và 'a' luôn 429
km._save()
calls.clear()
try:
    asyncio.run(G.generate_bytes(G.resolve_provider("cloudflare", "@cf/x"), "apple")); ok(False, "phải ném 429")
except G.ProviderError as e2:
    ok(e2.kind == "rate_limit" and calls == ["tokA"], "chỉ còn một tài khoản → 429 ném ra, không lặp vô hạn", calls)
G.shared_output_dir = lambda: str(TMP)
km._keys["cloudflare"]["a"]["active"] = True; km._keys["cloudflare"]["a"].pop("disabled_until", None); km._keys["cloudflare"]["a"].pop("disable_reason", None); km._save()
t = asyncio.run(G.test_draw("cloudflare", "@cf/x"))
ok(t["ok"] is False and "tạm ngưng" in t["message"] and "Cloud API Keys" in t["message"] and t["label"] == "a", "test_draw hết hạn mức → gợi ý thêm tài khoản, ghi tài khoản", t)

print("── C. đỗ cứng / từ chối / Gemini ──────────────────────────")
km.add_cloudflare_key("tokA", "accA", label="a"); km.add_cloudflare_key("tokB", "accB", label="b")


async def fake_cf_auth(r, prompt, aspect_ratio, timeout):
    calls.append(r["creds"]["api_token"])
    if r["creds"]["api_token"] == "tokA":
        raise G.ProviderError("auth", "HTTP 401: bad token")
    return b"\xff\xd8\xff"


G._cf_generate = fake_cf_auth
calls.clear()
r = G.resolve_provider("cloudflare", "@cf/x")
asyncio.run(G.generate_bytes(r, "apple"))
ea = km._keys["cloudflare"]["a"]
ok(calls == ["tokA", "tokB"] and ea["active"] is False and ea.get("disable_reason") == "hard", "401 → đỗ CỨNG 'a', xoay sang 'b'", ea)


async def fake_cf_refuse(r, prompt, aspect_ratio, timeout):
    calls.append(r["creds"]["api_token"])
    raise G.ProviderError("refused", "policy")


G._cf_generate = fake_cf_refuse
km.add_cloudflare_key("tokA", "accA", label="a")
calls.clear()
try:
    asyncio.run(G.generate_bytes(G.resolve_provider("cloudflare", "@cf/x"), "apple")); ok(False, "phải ném refused")
except G.ProviderError as e3:
    ok(e3.kind == "refused" and calls == ["tokA"] and km._keys["cloudflare"]["a"]["active"] is True, "từ chối nội dung → không đỗ, không xoay", calls)
km.add_key("gemini", "gk1", label="g1"); km.add_key("gemini", "gk2", label="g2")


async def fake_gem(r, prompt, aspect_ratio, reference_images, timeout):
    calls.append(r["key"])
    if r["key"] == "gk1":
        raise G.ProviderError("rate_limit", "HTTP 429: quota")
    return b"\xff\xd8\xff"


G._gemini_generate = fake_gem
calls.clear()
r = G.resolve_provider("gemini", "gemini-x")
asyncio.run(G.generate_bytes(r, "apple"))
ok(calls == ["gk1", "gk2"] and km._keys["gemini"]["g1"]["active"] is False and r["key"] == "gk2", "Gemini: 429 → đỗ g1 (cooldown), xoay sang g2", calls)

print("── D. label + Studio ───────────────────────────────────────")
ok("label" in G.public_resolution(G.resolve_provider("cloudflare")), "public_resolution có label")
studio = ROOT / "data" / "extensions_external" / "content_studio" / "engines" / "api_image_engine.py"
if studio.is_file():
    s = studio.read_text(encoding="utf-8")
    ok("r = dict(r)\n            data = await _core.generate_bytes" not in s and "data = await _core.generate_bytes(r, prompt, aspect_ratio, reference_images, timeout)" in s,
       "Studio không copy r → lõi cập nhật tài khoản cho cả lô")

print()
print(f"{PASS}/{PASS + FAIL} PASS" if not FAIL else f"{PASS}/{PASS + FAIL} PASS — {FAIL} HỎNG")
sys.exit(1 if FAIL else 0)
