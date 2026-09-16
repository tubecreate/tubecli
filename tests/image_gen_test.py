# -*- coding: utf-8 -*-
"""AI tạo ảnh DÙNG CHUNG của lõi: cài đặt, chọn nhà, route /api/v1/images (15/9/2026).

User: "AI tạo ảnh là thứ dùng chung" — bộ vẽ dời từ Content Studio vào tubecli/core/image_gen.py.

Kiểm (TestClient thật, nhà cung cấp giả):
  A. image_settings/set_image_settings ghi global_settings.json; nhà sai → ValueError
  B. resolve_provider: rõ ràng > cài đặt chung > tự chọn (Cloudflare trước Gemini); gõ sai tên → ok False;
     9Router lùi sang Cloudflare flux-1-schnell (không phải klein-9b phi thương mại)
  C. routes: GET/PUT settings (resolved không lộ khoá), 400 nhà sai; GET models; POST test; POST generate
     ghi file + url; GET file; tên file đi ngược thư mục → 400; 404 file không có
  D. server.py include router; generate_image ghi .part rồi đổi tên; refused/error giữ kind

Run:  python tests/image_gen_test.py
"""
import asyncio
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
TMP = Path(tempfile.mkdtemp(prefix="image_gen_"))
CFG.GLOBAL_SETTINGS_FILE = TMP / "global_settings.json"
from tubecli.core import image_gen as G  # noqa: E402
from tubecli.api import image_routes as R  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

PASS = FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", label)
    else:
        FAIL += 1
        print("  FAIL", label, "—", str(detail)[:300])


class FakeKM:
    def __init__(self, cf=True, gemini=True):
        self.cf, self.gemini, self.reports = cf, gemini, []

    def get_cloudflare_creds(self, label="default"):
        return {"api_token": "tok", "account_id": "acc", "email": ""} if self.cf else {}

    def get_active_key(self, provider):
        return "gkey" if (self.gemini and provider == "gemini") else None

    def report_key_error(self, provider, api_key, msg, transient=False):
        self.reports.append((provider, transient))


km = FakeKM()
G._key_manager = lambda: km
G.shared_output_dir = lambda: str(TMP / "images") if (TMP / "images").mkdir(exist_ok=True) or True else ""

print("── A. cài đặt chung ────────────────────────────────────────")
ok(G.image_settings() == {"provider": "", "model": ""}, "chưa đặt gì → trống (tự chọn)", G.image_settings())
ok(G.set_image_settings("Cloudflare", "@cf/x") == {"provider": "cloudflare", "model": "@cf/x"}, "đặt → chuẩn hoá chữ thường, ghi file")
ok(json.load(open(CFG.GLOBAL_SETTINGS_FILE, encoding="utf-8")).get("image_provider") == "cloudflare", "global_settings.json có image_provider")
try:
    G.set_image_settings("dalle", ""); ok(False, "nhà sai phải ném")
except ValueError as e:
    ok("dalle" in str(e), "nhà sai → ValueError kể tên", e)
ok(G.set_image_settings("auto", "") == {"provider": "", "model": ""}, "'auto' = trống")

print("── B. resolve_provider ─────────────────────────────────────")
G.set_image_settings("gemini", "gemini-x")
r = G.resolve_provider()
ok(r["ok"] and r["provider"] == "gemini" and r["model"] == "gemini-x" and "key" in r, "trống → theo cài đặt chung (gemini-x)", r)
r = G.resolve_provider("cloudflare")
ok(r["ok"] and r["provider"] == "cloudflare" and r["model"] == G.CF_DEFAULT_MODEL, "rõ nhà khác cài đặt → model mặc định của nhà đó (không lấy model gemini)", r)
r = G.resolve_provider("gemini")
ok(r["model"] == "gemini-x", "rõ nhà TRÙNG cài đặt → giữ model đã đặt", r)
G.set_image_settings("", "")
r = G.resolve_provider()
ok(r["ok"] and r["provider"] == "cloudflare", "tự chọn: Cloudflare trước", r)
km.cf = False
r = G.resolve_provider()
ok(r["ok"] and r["provider"] == "gemini", "không có Cloudflare → Gemini", r)
km.gemini = False
r = G.resolve_provider()
ok(not r["ok"] and "Chưa có nhà cung cấp" in r["reason"], "không có gì → ok False kèm chỉ đường", r)
km.cf = km.gemini = True
ok(not G.resolve_provider("dalle")["ok"], "gõ sai tên → ok False, không đổi nhà")
ok(set(G.public_resolution(G.resolve_provider("gemini"))) == {"ok", "provider", "model", "reason"}, "public_resolution không lộ khoá")


class FakeNR:
    """9Router giả — không đọc khoá thật, không gọi mạng."""
    def api_key(self): return "nr-key"
    def is_local(self): return False
    def base_url(self): return "https://nr.example/v1"
    def auth_headers(self): return {"Authorization": "Bearer nr-key"}


_real_nr = G._ninerouter_module
G._ninerouter_module = lambda: FakeNR()
r = G.resolve_provider("9router")
fb = r.get("fallback") or {}
# User 16/9/2026: "Bản lùi của 9Router đang là klein 9 sửa lại flux 1" — klein-9b là giấy phép phi thương mại.
ok(r["ok"] and r["model"] == G.NR_DEFAULT_MODEL and fb.get("provider") == "cloudflare"
   and fb.get("model") == "@cf/black-forest-labs/flux-1-schnell", "9Router lùi sang Cloudflare flux-1-schnell", fb)
ok("klein" not in G.NR_FALLBACK_CF_MODEL, "bản lùi không phải FLUX.2 klein (9B phi thương mại)", G.NR_FALLBACK_CF_MODEL)
km.cf = False
ok("fallback" not in G.resolve_provider("9router"), "không có Cloudflare → không có đường lùi")
km.cf = True
G._ninerouter_module = _real_nr

print("── C. routes ───────────────────────────────────────────────")
app = FastAPI(); app.include_router(R.router); c = TestClient(app)
calls = []


async def fake_bytes(r, prompt, aspect_ratio="16:9", reference_images=None, timeout=180):
    calls.append((r["provider"], r["model"], aspect_ratio, prompt[:20]))
    if "refuse" in prompt:
        raise G.ProviderError("refused", "content policy")
    if "fail" in prompt:
        raise G.ProviderError("auth", "HTTP 401: bad key")
    return b"\xff\xd8\xff" + b"x" * 100


G.generate_bytes = fake_bytes
G.list_models = lambda p: asyncio.sleep(0, result={"cloudflare": ["@cf/a", "@cf/b"], "gemini": ["g-img"], "9router": []}.get(p, []))

r = c.get("/api/v1/images/settings").json()
ok(r["core"] is True and r["provider"] == "" and r["resolved"]["provider"] == "cloudflare" and "creds" not in r["resolved"], "GET settings: core, tự chọn, resolved không khoá", r)
r = c.put("/api/v1/images/settings", json={"provider": "gemini", "model": "g-img"}).json()
ok(r["provider"] == "gemini" and r["model"] == "g-img" and r["resolved"]["model"] == "g-img", "PUT settings → phản hồi mới", r)
ok(c.put("/api/v1/images/settings", json={"provider": "dalle"}).status_code == 400, "PUT nhà sai → 400")
r = c.get("/api/v1/images/models?provider=cloudflare").json()
ok(r == {"models": {"cloudflare": ["@cf/a", "@cf/b"]}}, "GET models theo nhà", r)
r = c.get("/api/v1/images/models").json()
ok(set(r["models"]) == {"cloudflare", "gemini", "9router"}, "GET models không nhà → cả ba")
r = c.post("/api/v1/images/test", json={"provider": "cloudflare", "model": "@cf/a"}).json()
ok(r["ok"] is True and r["provider"] == "cloudflare" and r["model"] == "@cf/a" and calls[-1][2] == "1:1", "POST test: vẽ 1:1 thật, ok True", r)
ok(not [f for f in os.listdir(G.shared_output_dir()) if f.startswith("_probe_")], "file thử đã xoá")
km.cf = False
r = c.post("/api/v1/images/test", json={"provider": "cloudflare"}).json()
ok(r["ok"] is False and r["stage"] == "credentials", "POST test thiếu khoá → stage credentials", r)
km.cf = True
r = c.post("/api/v1/images/generate", json={"prompt": "an apple", "aspect_ratio": "9:16", "filename": "apple"}).json()
ok(r["ok"] is True and r["url"] == "/api/v1/images/file/apple.jpg" and os.path.isfile(r["path"]) and calls[-1][2] == "9:16", "POST generate → file + url, đúng tỉ lệ", r)
ok(c.get("/api/v1/images/file/apple.jpg").status_code == 200 and c.get("/api/v1/images/file/apple.jpg").content.startswith(b"\xff\xd8"), "GET file → bytes ảnh")
ok(c.post("/api/v1/images/generate", json={"prompt": "x", "filename": "../evil"}).status_code == 400, "filename có thư mục → 400")
ok(c.post("/api/v1/images/generate", json={"prompt": "x", "aspect_ratio": "2:1"}).status_code == 400, "tỉ lệ lạ → 400")
ok(c.get("/api/v1/images/file/nope.jpg").status_code == 404 and c.get("/api/v1/images/file/..%2Fx.jpg").status_code in (400, 404), "file không có → 404; đi ngược → chặn")
r = c.post("/api/v1/images/generate", json={"prompt": "please refuse this"}).json()
ok(r["ok"] is False and r["status"] == "refused" and r["kind"] == "refused", "từ chối nội dung → status refused", r)
r = c.post("/api/v1/images/generate", json={"prompt": "fail now"}).json()
ok(r["ok"] is False and r["kind"] == "auth" and "401" in r["message"], "lỗi khoá → kind auth kèm message", r)

print("── D. lõi ──────────────────────────────────────────────────")
src = (ROOT / "tubecli" / "api" / "server.py").read_text(encoding="utf-8")
ok("from tubecli.api.image_routes import router as _image_router" in src and "app.include_router(_image_router)" in src, "server.py include router")
out = TMP / "one.jpg"
res = asyncio.run(G.generate_image("an apple", str(out), resolved={"ok": True, "provider": "cloudflare", "model": "@cf/a", "creds": {}}))
ok(res["status"] == "success" and out.is_file() and not (TMP / "one.jpg.part").exists(), "generate_image: ghi .part rồi đổi tên", res)
ok(asyncio.run(G.generate_image("", str(out)))["status"] == "error", "prompt rỗng → error")

print()
print(f"{PASS}/{PASS + FAIL} PASS" if not FAIL else f"{PASS}/{PASS + FAIL} PASS — {FAIL} HỎNG")
sys.exit(1 if FAIL else 0)
