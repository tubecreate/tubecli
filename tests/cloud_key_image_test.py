# -*- coding: utf-8 -*-
"""«🖼 Test ảnh» cho từng khoá ở Cloud API Keys (17/9/2026).

User: "giúp tôi thêm logic test api ảnh ở đây" (ảnh chụp bảng «Keys đã lưu»).

Kiểm (nhà cung cấp giả, không gọi mạng):
  A. resolve_key: đúng MỘT khoá theo nhãn; model: tham số > model đã chọn ở AI tạo ảnh > mặc định;
     Cloudflare thiếu Account ID / nhà không vẽ được / nhãn không có → báo rõ; 9Router dùng key của dòng; không đường lùi
  B. test_key_draw vẽ được: Cloudflare gọi _cf_generate (một account, KHÔNG xoay), ảnh giữ ở data/images, mỗi khoá
     một file (lần sau thay), đo cỡ, ghi kết quả lên khoá
  C. hỏng: 9Router 502 → báo lỗi, KHÔNG lùi sang Cloudflare, ghi kết quả lỗi; nhà không vẽ ảnh → không ghi gì
  D. KeyManager thật: get_key_entry (bản sao, cả khoá đang tắt), set_image_test lưu file, list_keys trả image_test
  E. route POST /api/v1/cloud-api/keys/test-image

Run:  python tests/cloud_key_image_test.py     (exit 0 = pass)
"""
import asyncio
import io
import json
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

TMP = Path(tempfile.mkdtemp(prefix="key_image_"))
CFG.DATA_DIR = TMP / "data"
CFG.EXTENSIONS_DATA_DIR = CFG.DATA_DIR / "extensions_data"
CFG.GLOBAL_SETTINGS_FILE = TMP / "global_settings.json"
CFG.DATA_DIR.mkdir(parents=True)

from PIL import Image  # noqa: E402
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


def img_bytes(fmt="PNG", size=(64, 48)):
    buf = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(buf, fmt)
    return buf.getvalue()


class FakeKM:
    def __init__(self):
        self.entries = {
            "cloudflare": {"cf1": {"key": "cftok", "account_id": "acc1", "email": "a@x.com", "active": False},
                           "cfnoacc": {"key": "cftok2"}},
            "gemini": {"g1": {"key": "gkey"}},
            "9router": {"nr1": {"key": "sk-nr"}},
            "openai": {"o1": {"key": "sk-oa"}},
        }
        self.tests = []

    def get_key_entry(self, provider, label="default"):
        e = (self.entries.get(provider) or {}).get(label)
        return dict(e) if e else None

    def set_image_test(self, provider, label, result):
        self.tests.append((provider, label, dict(result)))


class FakeNR:
    def base_url(self):
        return "https://nr.example/v1"

    def auth_headers(self, key=None):
        return {"User-Agent": "TubeCLI", "Authorization": f"Bearer {key}"}


km = FakeKM()
IMAGES = TMP / "images"
IMAGES.mkdir()
G._key_manager = lambda: km
G._ninerouter_module = lambda: FakeNR()
G.shared_output_dir = lambda: str(IMAGES)
CALLS = []
NEXT = {"cloudflare": img_bytes("PNG"), "gemini": img_bytes("JPEG", (80, 80)), "9router": img_bytes("PNG")}


async def fake_cf(r, prompt, aspect, timeout):
    CALLS.append(("cf", dict(r), aspect))
    v = NEXT["cloudflare"]
    if isinstance(v, Exception):
        raise v
    return v


async def fake_gemini(r, prompt, aspect, refs, timeout):
    CALLS.append(("gemini", dict(r), aspect))
    return NEXT["gemini"]


async def fake_nr(r, prompt, aspect, timeout):
    CALLS.append(("9router", dict(r), aspect))
    v = NEXT["9router"]
    if isinstance(v, Exception):
        raise v
    return v


async def must_not(*a, **k):
    raise AssertionError("test ảnh của MỘT khoá không được xoay tài khoản / lùi nhà khác")


G._cf_generate = fake_cf
G._gemini_generate = fake_gemini
G._nr_generate = fake_nr
G._cf_generate_rotating = must_not
G.generate_bytes = must_not

print("── A. resolve_key ──────────────────────────────────────────")
r = G.resolve_key("cloudflare", "cf1")
ok(r["ok"] and r["creds"] == {"api_token": "cftok", "account_id": "acc1", "email": "a@x.com", "label": "cf1"}
   and r["model"] == G.CF_DEFAULT_MODEL and r["label"] == "cf1",
   "Cloudflare: đúng token + Account ID + email của NHÃN đó (kể cả khoá đang tắt), model mặc định", r)
G.set_image_settings("cloudflare", "@cf/black-forest-labs/flux-2-klein-4b")
ok(G.resolve_key("cloudflare", "cf1")["model"] == "@cf/black-forest-labs/flux-2-klein-4b",
   "model đã chọn cho Cloudflare ở AI tạo ảnh")
ok(G.resolve_key("cloudflare", "cf1", "@cf/x")["model"] == "@cf/x", "tham số model thắng")
ok(G.resolve_key("gemini", "g1")["model"] == G.GEMINI_DEFAULT_MODEL, "nhà khác cài đặt chung → model mặc định của nhà đó")
G.set_image_settings("", "")
r = G.resolve_key("cloudflare", "cfnoacc")
ok(not r["ok"] and "Account ID" in r["reason"], "Cloudflare thiếu Account ID → nói rõ", r)
r = G.resolve_key("openai", "o1")
ok(not r["ok"] and "not an image provider" in r["reason"], "nhà không vẽ ảnh → nói rõ", r)
r = G.resolve_key("gemini", "khong-co")
ok(not r["ok"] and "No saved key 'khong-co'" in r["reason"], "nhãn không có → nói rõ", r)
r = G.resolve_key("9router", "nr1")
ok(r["ok"] and r["base"] == "https://nr.example/v1" and r["headers"]["Authorization"] == "Bearer sk-nr"
   and r["model"] == G.NR_DEFAULT_MODEL and "fallback" not in r,
   "9Router: key CỦA DÒNG, không đường lùi Cloudflare", r)
ok(G.resolve_key("gemini", "g1")["key"] == "gkey", "Gemini: key của dòng")

print("── B. vẽ được ──────────────────────────────────────────────")
out = asyncio.run(G.test_key_draw("cloudflare", "cf1"))
files = sorted(os.listdir(IMAGES))
ok(out["ok"] and out["stage"] == "generate" and out["width"] == 64 and out["height"] == 48
   and out["url"].startswith("/api/v1/images/file/keytest_cloudflare_") and out["url"].endswith(".png")
   and files == [out["url"].rsplit("/", 1)[1]], "Cloudflare vẽ được: ảnh giữ ở data/images, đo cỡ, có URL xem", (out, files))
ok(CALLS[-1][0] == "cf" and CALLS[-1][2] == "1:1" and CALLS[-1][1]["creds"]["account_id"] == "acc1",
   "gọi _cf_generate của ĐÚNG account (không _cf_generate_rotating)", CALLS[-1][:1])
ok(km.tests[-1][:2] == ("cloudflare", "cf1") and km.tests[-1][2]["ok"] is True and km.tests[-1][2]["model"] == G.CF_DEFAULT_MODEL
   and km.tests[-1][2]["at"], "ghi kết quả lên khoá", km.tests[-1])
NEXT["cloudflare"] = img_bytes("JPEG")
out2 = asyncio.run(G.test_key_draw("cloudflare", "cf1"))
ok(sorted(os.listdir(IMAGES)) == [out2["url"].rsplit("/", 1)[1]] and out2["url"].endswith(".jpg"),
   "vẽ lại: thay ảnh cũ của khoá (kể cả khác đuôi), không để rác", os.listdir(IMAGES))
out3 = asyncio.run(G.test_key_draw("gemini", "g1"))
ok(out3["ok"] and out3["width"] == 80 and len(os.listdir(IMAGES)) == 2, "khoá khác có file riêng", os.listdir(IMAGES))
import re as _re  # noqa: E402
ok(all(_re.match(r"^[A-Za-z0-9._-]{1,120}$", n) for n in os.listdir(IMAGES)),
   "tên file qua được bộ lọc tên an toàn của /api/v1/images/file")

print("── C. hỏng ─────────────────────────────────────────────────")
CALLS.clear()
NEXT["9router"] = G.ProviderError("error", "9Router HTTP 502: error code: 502")
n_files = len(os.listdir(IMAGES))
out = asyncio.run(G.test_key_draw("9router", "nr1"))
ok(not out["ok"] and out["stage"] == "generate" and out["kind"] == "error" and "502" in out["message"] and out["url"] == ""
   and len(os.listdir(IMAGES)) == n_files, "9Router 502 → báo lỗi thật, không có ảnh", out)
ok([c[0] for c in CALLS] == ["9router"], "KHÔNG lùi sang Cloudflare (Test chung từng báo OK khi Cloudflare vẽ thay)", CALLS)
ok(km.tests[-1][:2] == ("9router", "nr1") and km.tests[-1][2]["ok"] is False and "502" in km.tests[-1][2]["message"],
   "ghi kết quả lỗi lên khoá", km.tests[-1])
n_tests = len(km.tests)
out = asyncio.run(G.test_key_draw("openai", "o1"))
ok(not out["ok"] and out["stage"] == "credentials" and len(km.tests) == n_tests, "khoá OpenAI → không vẽ, không ghi gì", out)
out = asyncio.run(G.test_key_draw("cloudflare", "cfnoacc"))
ok(not out["ok"] and out["stage"] == "credentials" and km.tests[-1][2]["ok"] is False,
   "Cloudflare thiếu Account ID → lỗi ở bước khoá, ghi lại", out)

CF401 = 'HTTP 401: {"result":null,"success":false,"errors":[{"code":10000,"message":"Authentication error"}],"messages":[]}'
GM429 = 'HTTP 429: {\n  "error": {\n    "code": 429,\n    "message": "You exceeded your current quota, please check your plan"\n  }\n}'
ok(G._short_error(CF401) == "HTTP 401: Authentication error" and G._short_error(GM429) == "HTTP 429: You exceeded your current quota, please check your plan"
   and G._short_error("HTTP 502: error code: 502\n") == "HTTP 502: error code: 502" and G._short_error("boom") == "boom",
   "câu lỗi đọc được: rút message khỏi JSON của Cloudflare / Gemini (đo thật 17/9/2026), giữ nguyên câu thường")
NEXT["9router"] = G.ProviderError("auth", CF401)
ok(asyncio.run(G.test_key_draw("9router", "nr1"))["message"] == "HTTP 401: Authentication error" and
   km.tests[-1][2]["message"] == "HTTP 401: Authentication error", "kết quả + bản ghi dùng câu đã rút gọn")

print("── D. KeyManager thật ──────────────────────────────────────")
import tubecli.extensions.cloud_api.extension as EXT  # noqa: E402
if os.path.commonpath([os.path.realpath(EXT.CLOUD_API_DATA_FILE), os.path.realpath(str(TMP))]) != os.path.realpath(str(TMP)):
    print("ABORT — cloud_api_keys.json không nằm trong thư mục tạm:", EXT.CLOUD_API_DATA_FILE)
    sys.exit(2)
KM = EXT.KeyManager()
KM.add_key("gemini", "gm-fake-key-1234567890", "mine")
e = KM.get_key_entry("gemini", "mine")
e["key"] = "changed"
ok(KM.get_key_entry("gemini", "mine")["key"] == "gm-fake-key-1234567890" and KM.get_key_entry("gemini", "nope") is None,
   "get_key_entry trả BẢN SAO; nhãn không có → None")
KM.set_image_test("gemini", "mine", {"ok": True, "model": "gemini-x", "seconds": 3.2, "message": "", "kind": "", "at": "t"})
KM2 = EXT.KeyManager()
listed = KM2.list_keys("gemini")["gemini"]["mine"]
ok(listed["image_test"]["ok"] is True and listed["image_test"]["model"] == "gemini-x" and "key" not in listed["image_test"],
   "set_image_test lưu xuống file; list_keys trả image_test (không lộ key)", listed)
KM.set_image_test("gemini", "nope", {"ok": True})
ok("nope" not in KM2.list_keys("gemini")["gemini"], "nhãn không có → không tạo khoá rỗng")

print("── E. route ────────────────────────────────────────────────")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from tubecli.extensions.cloud_api import routes as R  # noqa: E402

app = FastAPI()
app.include_router(R.router)
c = TestClient(app)
NEXT["cloudflare"] = img_bytes("PNG")
res = c.post("/api/v1/cloud-api/keys/test-image", json={"provider": "cloudflare", "label": "cf1"})
ok(res.status_code == 200 and res.json()["ok"] is True and res.json()["url"].startswith("/api/v1/images/file/keytest_"),
   "POST /keys/test-image → vẽ thử đúng khoá", res.text[:200])
res = c.post("/api/v1/cloud-api/keys/test-image", json={"provider": "cloudflare", "label": "cf1"},
             headers={"Origin": "https://evil.example"})
ok(res.status_code == 403, "trang web khác origin → 403 (origin guard)", res.status_code)

print()
print(f"{PASS}/{PASS + FAIL} PASS" if not FAIL else f"{PASS}/{PASS + FAIL} PASS — {FAIL} HỎNG")
sys.exit(1 if FAIL else 0)
