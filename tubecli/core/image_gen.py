"""Bộ vẽ ảnh DÙNG CHUNG của lõi — gọi Cloudflare Workers AI, Gemini image hay 9Router qua HTTP.

Trước 15/9/2026 bộ vẽ này nằm trong extension Content Studio (engines/api_image_engine.py),
Thumbnail Studio chép một bản riêng, còn tab «AI tạo ảnh» trên Flow chỉ chỉnh được cài đặt của
Studio. User: "AI tạo ảnh là thứ dùng chung" — nên lõi giữ:

  * cài đặt chung  image_provider / image_model trong global_settings.json (image_settings())
  * bộ gọi từng nhà cung cấp theo đúng khuôn từng model (đo thật 14/9/2026, xem phần Cloudflare)
  * generate_image() ghi ảnh ra một đường dẫn bất kỳ, test_draw() vẽ thử một ảnh 1:1 rồi xoá
  * list_models() hỏi thẳng nhà cung cấp

Khoá vẫn ở Cloud API Keys (cloud_api.key_manager). Extension nào muốn vẽ thì gọi vào đây;
Content Studio giữ lại phần riêng của nó (tên file theo shot, lô vẽ, dừng sớm) và uỷ thác
phần gọi nhà cung cấp cho mô-đun này khi lõi có nó.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
from typing import Optional

logger = logging.getLogger("tubecli.image_gen")

STATUS_SUCCESS = "success"
STATUS_ERROR = "error"
STATUS_REFUSED = "refused"

CF_DEFAULT_MODEL = "@cf/black-forest-labs/flux-1-schnell"
GEMINI_DEFAULT_MODEL = "gemini-2.5-flash-image"
NR_DEFAULT_MODEL = "ag/gemini-3.1-flash-image"
NR_FALLBACK_CF_MODEL = "@cf/black-forest-labs/flux-2-klein-9b"
PROVIDERS = ("cloudflare", "gemini", "9router")
ASPECT_RATIOS = ("16:9", "9:16", "1:1", "4:3", "3:4")
DEFAULT_MODELS = {"cloudflare": CF_DEFAULT_MODEL, "gemini": GEMINI_DEFAULT_MODEL, "9router": NR_DEFAULT_MODEL}


class ProviderError(Exception):
    """Lỗi từ nhà cung cấp, kèm `kind`: rate_limit | auth | refused | error."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


# ── cài đặt chung ─────────────────────────────────────────────────────────────

def image_settings() -> dict:
    """{provider, model} — chuỗi rỗng = tự chọn (auto)."""
    try:
        from tubecli.config import read_global_settings
        g = read_global_settings()
    except Exception:
        g = {}
    p = str(g.get("image_provider") or "").strip().lower()
    m = str(g.get("image_model") or "").strip()
    if p in ("auto",):
        p = ""
    return {"provider": p, "model": m}


def set_image_settings(provider: Optional[str], model: Optional[str]) -> dict:
    p = str(provider or "").strip().lower()
    if p in ("auto",):
        p = ""
    if p and p not in PROVIDERS:
        raise ValueError(f"Không biết nhà cung cấp ảnh '{p}'. Chỉ hỗ trợ: {', '.join(PROVIDERS)} (hoặc để trống để tự chọn).")
    from tubecli.config import set_global_setting
    set_global_setting("image_provider", p)
    set_global_setting("image_model", str(model or "").strip())
    return image_settings()


def shared_output_dir() -> str:
    """Nơi ảnh vẽ qua route /api/v1/images/generate được cất (data/images)."""
    try:
        from tubecli.config import DATA_DIR
        d = os.path.join(str(DATA_DIR), "images")
    except Exception:
        d = os.path.join(os.path.expanduser("~"), ".tubecli", "images")
    os.makedirs(d, exist_ok=True)
    return d


# ── khoá + chọn nhà cung cấp ───────────────────────────────────────────────────

def _key_manager():
    from tubecli.extensions.cloud_api.extension import key_manager
    return key_manager


def _ninerouter_module():
    try:
        import importlib
        return importlib.import_module("tubecli.core.ninerouter")
    except Exception:      # noqa: BLE001
        return None


def resolve_provider(provider: Optional[str] = None, model: Optional[str] = None) -> dict:
    """Nhà cung cấp sẽ dùng và có DÙNG ĐƯỢC không: {"ok", "provider", "model", "reason", ...}.

    provider/model để trống → lấy cài đặt chung; cài đặt chung trống → "auto": Cloudflare trước
    (gói miễn phí), rồi Gemini. Gõ sai tên nhà → báo lỗi, KHÔNG lặng lẽ đổi sang nhà khác (tiền
    tiêu ở chỗ người dùng không chọn mà trông như chạy được).
    """
    cfg = image_settings()
    provider = (provider or "").strip().lower() or cfg["provider"]
    model = (model or "").strip() or (cfg["model"] if (not provider or provider == cfg["provider"]) else "")
    km = _key_manager()

    def _cloudflare(m=None):
        creds = km.get_cloudflare_creds()
        if not creds.get("api_token") or not creds.get("account_id"):
            return {"ok": False, "provider": "cloudflare", "model": m or CF_DEFAULT_MODEL,
                    "reason": "Chưa có credential Cloudflare (cần API token + Account ID) trong Cloud API Keys."}
        return {"ok": True, "provider": "cloudflare", "model": m or CF_DEFAULT_MODEL,
                "creds": creds, "label": creds.get("label") or "", "reason": ""}

    def _gemini(m=None):
        key = km.get_active_key("gemini")
        if not key:
            return {"ok": False, "provider": "gemini", "model": m or GEMINI_DEFAULT_MODEL,
                    "reason": "Chưa có API key Gemini đang bật trong Cloud API Keys."}
        return {"ok": True, "provider": "gemini", "model": m or GEMINI_DEFAULT_MODEL,
                "key": key, "reason": ""}

    def _ninerouter(m=None):
        m = m or NR_DEFAULT_MODEL
        nr = _ninerouter_module()
        if nr is None:
            return {"ok": False, "provider": "9router", "model": m,
                    "reason": "Lõi TubeCLI này chưa có mô-đun 9Router — cập nhật TubeCLI."}
        if not nr.api_key() and not nr.is_local():
            return {"ok": False, "provider": "9router", "model": m,
                    "reason": "9Router ở máy khác cần key đang bật trong Cloud API Keys."}
        out = {"ok": True, "provider": "9router", "model": m, "base": nr.base_url(),
               "headers": nr.auth_headers(), "reason": ""}
        # 9Router vẽ bằng quota tài khoản Antigravity — hết giữa lô là chuyện thường → đường lùi.
        fb = _cloudflare(NR_FALLBACK_CF_MODEL)
        if fb["ok"]:
            out["fallback"] = fb
        return out

    p = provider
    if p == "cloudflare":
        return _cloudflare(model)
    if p == "gemini":
        return _gemini(model)
    if p == "9router":
        return _ninerouter(model)
    if p not in ("", "auto"):
        return {"ok": False, "provider": p, "model": model or "",
                "reason": f"Không biết nhà cung cấp ảnh '{p}'. Chỉ hỗ trợ: cloudflare, gemini, 9router "
                          f"(hoặc để trống để tự chọn)."}
    cf = _cloudflare(model)
    if cf["ok"]:
        return cf
    gm = _gemini(model)
    if gm["ok"]:
        return gm
    return {"ok": False, "provider": "auto", "model": model or "",
            "reason": "Chưa có nhà cung cấp ảnh nào dùng được. Thêm credential Cloudflare "
                      "hoặc API key Gemini ở Cloud API Keys, rồi chọn model ở AI tạo ảnh."}


def public_resolution(r: dict) -> dict:
    """Bản không chứa khoá để trả ra ngoài."""
    return {k: v for k, v in r.items() if k in ("ok", "provider", "model", "reason", "label")}


def _cred_id(r: dict) -> str:
    """Định danh tài khoản đang dùng (để biết resolve lại có ra tài khoản KHÁC không)."""
    return str((r.get("creds") or {}).get("api_token") or r.get("key") or r.get("base") or "")


def _is_daily_quota(msg: str) -> bool:
    low = (msg or "").lower()
    return "daily free allocation" in low or "neurons" in low


def _next_utc_midnight() -> float:
    """Hạn mức ngày của Workers AI reset 00:00 UTC — đỗ tài khoản tới đúng mốc đó."""
    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone.utc)
    nxt = (now + _dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return nxt.timestamp()


def _local_clock(ts: float) -> str:
    import datetime as _dt
    return _dt.datetime.fromtimestamp(ts).strftime("%H:%M %d/%m")


def _classify(status_code: int, body: str) -> str:
    """Lời từ chối nội dung không được thử lại mãi; 429 không được giết cả lô."""
    low = (body or "").lower()
    if status_code == 429 or "rate limit" in low or "quota" in low or "resource_exhausted" in low:
        return "rate_limit"
    if status_code in (401, 403):
        return "auth"
    if "safety" in low or "blocked" in low or "policy" in low or "prohibited" in low:
        return "refused"
    return "error"


def _report_key(r: dict, msg: str, transient: bool) -> None:
    """Báo cloud_api khoá hỏng để failover/cooldown làm việc.

    Cloudflare cũng được báo (trước đây chỉ Gemini): hết hạn mức NGÀY → đỗ tới 00:00 UTC, 429
    thường → cooldown; khoá sai (401/403) → đỗ cứng. Có tài khoản thứ hai thì lượt sau tự sang.
    """
    try:
        km = _key_manager()
        if r.get("provider") == "gemini" and r.get("key"):
            km.report_key_error("gemini", r["key"], msg[:160], transient=transient)
        elif r.get("provider") == "cloudflare" and (r.get("creds") or {}).get("api_token"):
            until = _next_utc_midnight() if (transient and _is_daily_quota(msg)) else None
            r["parked_until"] = until
            km.report_key_error("cloudflare", r["creds"]["api_token"], msg[:160], transient=transient, until=until)
    except Exception:
        pass


# ── HTTP ──────────────────────────────────────────────────────────────────────

async def _post_json(url: str, payload: dict, headers: dict, timeout: int) -> dict:
    def _sync():
        import urllib.request
        import urllib.error
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                     headers={"Content-Type": "application/json", **headers})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")[:600]
            except Exception:
                pass
            raise ProviderError(_classify(e.code, body), f"HTTP {e.code}: {body[:240]}")
        except Exception as e:
            raise ProviderError("error", f"{type(e).__name__}: {e}")

    return await asyncio.to_thread(_sync)


async def _post_any(url: str, data: bytes, headers: dict, timeout: int) -> tuple:
    """POST bytes → (content_type, body bytes); lỗi HTTP thành ProviderError."""
    def _sync():
        import urllib.request
        import urllib.error
        req = urllib.request.Request(url, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.headers.get("content-type", ""), resp.read()
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")[:600]
            except Exception:
                pass
            raise ProviderError(_classify(e.code, body), f"HTTP {e.code}: {body[:240]}")
        except Exception as e:
            raise ProviderError("error", f"{type(e).__name__}: {e}")

    return await asyncio.to_thread(_sync)


# ── Cloudflare: mỗi model một KHUÔN gọi ───────────────────────────────────────
# Đo thật 14/9/2026 trên tài khoản Workers Paid:
#   flux-1-schnell   JSON {prompt, steps} (thêm width/height là 400)   → JSON result.image (b64)
#   flux-2-dev/klein multipart/form-data prompt, width, height          → JSON result.image
#   lucid-origin     JSON {prompt, width, height}                        → JSON result.image
#   phoenix-1.0, SDXL, sdxl-lightning, dreamshaper  JSON {prompt, width, height} → ẢNH THÔ
#   stable-diffusion-v1-5-inpainting cần ảnh vào (không vẽ từ chữ) — 400 "missing required input image"
# Khuôn đọc từ schema của model (/ai/models/schema), nhớ theo tiến trình; không hỏi được thì đoán theo tên.
_CF_DIMS = {"16:9": (1024, 576), "9:16": (576, 1024), "1:1": (1024, 1024),
            "4:3": (1024, 768), "3:4": (768, 1024)}
_CF_KIND_CACHE: dict = {}


def cf_kind_from_schema(schema, model: str) -> str:
    """'multipart' | 'dims' (JSON có width/height) | 'prompt' (JSON chỉ prompt + steps)."""
    inp = (schema or {}).get("input") if isinstance(schema, dict) else None
    inp = inp if isinstance(inp, dict) else {}
    props = inp.get("properties") or {}
    if "multipart" in props or list(inp.get("required") or []) == ["multipart"]:
        return "multipart"
    if "width" in props and "height" in props:
        return "dims"
    if props:
        return "prompt"
    low = (model or "").lower()
    if "flux-2" in low:
        return "multipart"
    if "flux-1-schnell" in low:
        return "prompt"
    return "dims"


def cf_request(kind: str, prompt: str, aspect_ratio: str) -> tuple:
    """(content_type, body bytes) của một lượt /ai/run theo khuôn của model."""
    w, h = _CF_DIMS.get(aspect_ratio or "16:9", _CF_DIMS["16:9"])
    if kind == "multipart":
        import uuid
        boundary = "----tubecli" + uuid.uuid4().hex
        fields = {"prompt": prompt, "width": str(w), "height": str(h)}
        body = b"".join(
            (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n").encode("utf-8")
            for k, v in fields.items()) + f"--{boundary}--\r\n".encode("utf-8")
        return f"multipart/form-data; boundary={boundary}", body
    if kind == "dims":
        return "application/json", json.dumps({"prompt": prompt, "width": w, "height": h}).encode("utf-8")
    return "application/json", json.dumps({"prompt": f"{prompt} (aspect ratio {aspect_ratio})", "steps": 4}).encode("utf-8")


def cf_image_bytes(content_type: str, raw: bytes) -> bytes:
    """Ảnh từ trả lời: JSON result.image (base64) hay chính bytes ảnh (jpeg/png/webp)."""
    ct = (content_type or "").lower()
    if "json" in ct or raw[:1] in (b"{", b"["):
        body = json.loads(raw.decode("utf-8"))
        if not body.get("success", True):
            errs = "; ".join(e.get("message", "") for e in body.get("errors", []))
            raise ProviderError(_classify(200, errs), errs or "Cloudflare trả về lỗi không rõ.")
        img = (body.get("result") or {}).get("image")
        if not img:
            raise ProviderError("error", "Cloudflare không trả về trường result.image.")
        return base64.b64decode(img)
    if raw[:3] == b"\xff\xd8\xff" or raw[:4] == b"\x89PNG" or raw[:4] == b"RIFF":
        return raw
    raise ProviderError("error", f"Cloudflare trả về {ct or 'dữ liệu'} không phải ảnh.")


def _cf_headers(creds: dict) -> dict:
    return ({"X-Auth-Email": creds["email"], "X-Auth-Key": creds["api_token"]}
            if creds.get("email") else {"Authorization": f"Bearer {creds['api_token']}"})


async def _cf_kind(base: str, headers: dict, model: str, timeout: int) -> str:
    if model in _CF_KIND_CACHE:
        return _CF_KIND_CACHE[model]

    def _sync():
        import urllib.request
        from urllib.parse import quote
        req = urllib.request.Request(f"{base}/ai/models/schema?model={quote(model, safe='')}", headers=headers)
        with urllib.request.urlopen(req, timeout=min(timeout, 20)) as resp:
            return json.loads(resp.read().decode("utf-8")).get("result")
    try:
        schema = await asyncio.to_thread(_sync)
    except Exception as e:      # noqa: BLE001
        logger.info("cloudflare schema %s: %s", model, e)
        schema = None
    kind = cf_kind_from_schema(schema, model)
    _CF_KIND_CACHE[model] = kind
    return kind


async def _cf_generate(r: dict, prompt: str, aspect_ratio: str, timeout: int) -> bytes:
    creds = r["creds"]
    headers = _cf_headers(creds)
    base = f"https://api.cloudflare.com/client/v4/accounts/{creds['account_id']}"
    kind = await _cf_kind(base, headers, r["model"], timeout)
    ctype, body = cf_request(kind, prompt, aspect_ratio)
    ct, raw = await _post_any(f"{base}/ai/run/{r['model']}", body, {**headers, "Content-Type": ctype}, timeout)
    return cf_image_bytes(ct, raw)


# ── Gemini ────────────────────────────────────────────────────────────────────

async def _gemini_generate(r: dict, prompt: str, aspect_ratio: str, reference_images, timeout: int) -> bytes:
    parts = [{"text": f"{prompt}\n\n(Aspect ratio: {aspect_ratio})"}]
    for p in (reference_images or [])[:3]:
        try:
            with open(p, "rb") as f:
                raw = f.read()
            mime = "image/png" if raw[:4] == b"\x89PNG" else "image/jpeg"
            parts.append({"inline_data": {"mime_type": mime, "data": base64.b64encode(raw).decode()}})
        except Exception as e:
            logger.warning("bỏ qua ảnh tham chiếu %s: %s", p, e)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{r['model']}:generateContent?key={r['key']}"
    body = await _post_json(url, {"contents": [{"parts": parts}],
                                  "generationConfig": {"responseModalities": ["IMAGE"]}}, {}, timeout)
    cands = body.get("candidates") or []
    if not cands:
        fb = (body.get("promptFeedback") or {}).get("blockReason")
        raise ProviderError("refused" if fb else "error",
                            f"Gemini từ chối prompt ({fb})." if fb else "Gemini không trả về ứng viên nào.")
    reason = cands[0].get("finishReason") or ""
    for part in cands[0].get("content", {}).get("parts", []):
        blob = (part.get("inlineData") or part.get("inline_data") or {}).get("data")
        if blob:
            return base64.b64decode(blob)
    raise ProviderError("refused" if "SAFETY" in reason.upper() else "error",
                        f"Gemini không trả về ảnh (finishReason={reason or 'không rõ'}).")


# ── 9Router (Antigravity) ─────────────────────────────────────────────────────
# Đo thật 14/9/2026 (9Router 0.5.75): POST {base}/images/generations {model, prompt, n, size}
# → {"data": [{"b64_json": …}]}; chỉ `size` đổi được khung; 4:3 xin 16:9 rồi khâu dựng cắt.
_NR_SIZES = {"16:9": "1792x1024", "9:16": "1024x1792", "1:1": "1024x1024",
             "4:3": "1792x1024", "3:4": "1024x1792"}


def nr_request(model: str, prompt: str, aspect_ratio: str) -> bytes:
    return json.dumps({"model": model, "prompt": prompt, "n": 1,
                       "size": _NR_SIZES.get(aspect_ratio or "16:9", _NR_SIZES["16:9"])}).encode("utf-8")


def nr_image_bytes(content_type: str, raw: bytes) -> bytes:
    if raw[:3] == b"\xff\xd8\xff" or raw[:4] == b"\x89PNG" or raw[:4] == b"RIFF":
        return raw
    try:
        body = json.loads(raw.decode("utf-8"))
    except Exception:
        raise ProviderError("error", f"9Router trả về {content_type or 'dữ liệu'} không phải ảnh.")
    if isinstance(body, dict) and body.get("error"):
        err = body["error"]
        msg = err.get("message") if isinstance(err, dict) else str(err)
        raise ProviderError(_classify(200, msg or ""), f"9Router: {msg}")
    items = body.get("data") if isinstance(body, dict) else None
    b64 = items[0].get("b64_json") if items and isinstance(items[0], dict) else None
    if not b64:
        raise ProviderError("error", "9Router không trả về ảnh (thiếu data[0].b64_json).")
    return base64.b64decode(b64)


async def _nr_generate(r: dict, prompt: str, aspect_ratio: str, timeout: int) -> bytes:
    headers = {**(r.get("headers") or {}), "Content-Type": "application/json"}
    ct, raw = await _post_any(f"{r['base']}/images/generations", nr_request(r["model"], prompt, aspect_ratio), headers, timeout)
    return nr_image_bytes(ct, raw)


# ── vẽ ────────────────────────────────────────────────────────────────────────

async def generate_bytes(r: dict, prompt: str, aspect_ratio: str = "16:9",
                         reference_images: Optional[list] = None, timeout: int = 180) -> bytes:
    """Bytes ảnh từ nhà cung cấp đã resolve; ném ProviderError. Có đường lùi (9Router → Cloudflare).

    Xoay khoá: rate_limit/auth → resolve lại; ra tài khoản KHÁC thì vẽ ngay bằng nó và ghi tài
    khoản mới vào `r` (caller giữ `r` cho cả lô nên các shot sau đi thẳng, không tốn thêm 429).
    """
    r.pop("fallback_from", None)
    try:
        if r["provider"] == "cloudflare":
            return await _cf_generate(r, prompt, aspect_ratio, timeout)
        if r["provider"] == "9router":
            return await _nr_generate(r, prompt, aspect_ratio, timeout)
        return await _gemini_generate(r, prompt, aspect_ratio, reference_images, timeout)
    except ProviderError as e:
        if e.kind == "rate_limit":
            _report_key(r, str(e), transient=True)
        elif e.kind == "auth":
            _report_key(r, str(e), transient=False)
        if e.kind in ("rate_limit", "auth") and not r.get("_rotated"):
            nr = resolve_provider(r["provider"], r.get("model"))
            if nr.get("ok") and _cred_id(nr) and _cred_id(nr) != _cred_id(r):
                logger.warning("%s/%s: %s → xoay sang tài khoản '%s'", r["provider"], r["model"], str(e)[:100], nr.get("label") or "?")
                nr["_rotated"] = True
                data = await generate_bytes(nr, prompt, aspect_ratio, reference_images, timeout)
                r["rotated_to"] = nr.get("label") or ""
                for k in ("creds", "key", "base", "headers", "label", "fallback"):
                    if k in nr:
                        r[k] = nr[k]
                r["_rotated"] = True
                return data
        fb = r.get("fallback")
        # Nhà chính hỏng (quota, 502, khoá sai) mà có đường lùi → vẽ tiếp; lời TỪ CHỐI nội dung thì không.
        if fb and e.kind != "refused":
            logger.warning("%s/%s hỏng (%s) → vẽ bằng %s/%s", r["provider"], r["model"], str(e)[:120], fb["provider"], fb["model"])
            data = await generate_bytes(fb, prompt, aspect_ratio, reference_images, timeout)
            r["fallback_from"] = f"{r['provider']}/{r['model']}: {str(e)[:160]}"
            return data
        raise


async def generate_image(prompt: str, out_path: str, provider: Optional[str] = None, model: Optional[str] = None,
                         aspect_ratio: str = "16:9", reference_images: Optional[list] = None,
                         timeout: int = 180, resolved: Optional[dict] = None) -> dict:
    """Vẽ MỘT ảnh ra out_path (ghi tạm .part rồi đổi tên — không ai đọc phải file dở).

    Trả {"status": success|error|refused, "path"|"message", "provider", "model", "kind"?, "fallback_from"?}.
    """
    if not prompt or not prompt.strip():
        return {"status": STATUS_ERROR, "message": "Prompt rỗng."}
    r = dict(resolved) if resolved else resolve_provider(provider, model)
    if not r.get("ok"):
        return {"status": STATUS_ERROR, "message": r.get("reason", "Chưa cấu hình nhà cung cấp ảnh."),
                "provider": r.get("provider", ""), "model": r.get("model", "")}
    try:
        data = await generate_bytes(r, prompt, aspect_ratio, reference_images, timeout)
    except ProviderError as e:
        return {"status": STATUS_REFUSED if e.kind == "refused" else STATUS_ERROR, "message": str(e),
                "kind": e.kind, "provider": r["provider"], "model": r["model"]}
    except Exception as e:      # noqa: BLE001
        logger.exception("generate_image failed")
        return {"status": STATUS_ERROR, "message": f"{type(e).__name__}: {e}", "provider": r["provider"], "model": r["model"]}
    if not data:
        return {"status": STATUS_ERROR, "message": "Nhà cung cấp không trả về ảnh nào.", "provider": r["provider"], "model": r["model"]}
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    tmp = out_path + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, out_path)
    out = {"status": STATUS_SUCCESS, "path": out_path, "provider": r["provider"], "model": r["model"],
           "label": r.get("label", "")}
    if r.get("fallback_from"):
        out["fallback_from"] = r["fallback_from"]
    if r.get("rotated_to"):
        out["rotated_to"] = r["rotated_to"]
    return out


async def test_draw(provider: Optional[str] = None, model: Optional[str] = None, timeout: int = 90) -> dict:
    """Vẽ THỬ một ảnh 1:1 rồi xoá — câu trả lời thật thay cho dấu tick suy từ khoá."""
    r = resolve_provider(provider, model)
    if not r.get("ok"):
        return {"ok": False, "stage": "credentials", "provider": r.get("provider", ""),
                "model": r.get("model", ""), "seconds": 0, "message": r.get("reason", "")}
    path = os.path.join(shared_output_dir(), f"_probe_{int(time.time() * 1000)}.jpg")
    t0 = time.time()
    res = await generate_image("A single red apple on a plain white table, soft daylight, simple and clean",
                               path, aspect_ratio="1:1", resolved=r, timeout=timeout)
    secs = round(time.time() - t0, 1)
    try:
        os.remove(path)
    except OSError:
        pass
    ok = res.get("status") == STATUS_SUCCESS
    message = "" if ok else str(res.get("message") or "")
    if not ok and res.get("kind") == "rate_limit" and r["provider"] == "cloudflare":
        # Hết hạn mức mà không có tài khoản khác để xoay → nói rõ đã đỗ tới lúc nào và cách thêm.
        until = r.get("parked_until")
        when = f" tới {_local_clock(until)}" if until else ""
        message += (f" — tài khoản '{r.get('label') or '?'}' đã tạm ngưng{when}; thêm một tài khoản "
                    f"Cloudflare khác ở Cloud API Keys thì lần sau tự xoay.")
    return {"ok": ok, "stage": "generate", "provider": r["provider"], "model": r["model"], "seconds": secs,
            "label": r.get("label", ""), "rotated_to": r.get("rotated_to", ""),
            "message": message, "kind": res.get("kind", ""), "fallback_from": res.get("fallback_from", "")}


# ── danh sách model ───────────────────────────────────────────────────────────

async def list_models(provider: str) -> list:
    """Model ảnh nhà cung cấp đang có, hỏi thẳng nhà (danh mục chat của cloud_api cố ý lọc bỏ model ảnh)."""
    p = (provider or "").lower()
    if p == "cloudflare":
        creds = _key_manager().get_cloudflare_creds()
        if not creds.get("api_token") or not creds.get("account_id"):
            return []
        headers = _cf_headers(creds)

        def _sync():
            import urllib.request
            url = (f"https://api.cloudflare.com/client/v4/accounts/{creds['account_id']}"
                   f"/ai/models/search?task=Text-to-Image&per_page=50")
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=20) as resp:
                return json.loads(resp.read().decode())
        try:
            d = await asyncio.to_thread(_sync)
            return [m.get("name") for m in d.get("result", []) if m.get("name")]
        except Exception as e:
            logger.warning("list_models cloudflare: %s", e)
            return []
    if p == "9router":
        nr = _ninerouter_module()
        if nr is None:
            return []

        def _sync():
            import urllib.request
            req = urllib.request.Request(nr.models_url(), headers=nr.auth_headers())
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode())
        found = []
        try:
            d = await asyncio.to_thread(_sync)
            found = [m.get("id") for m in d.get("data", []) if "image" in str(m.get("id", "")).lower()]
        except Exception as e:
            logger.warning("list_models 9router: %s", e)
        return [NR_DEFAULT_MODEL] + [m for m in found if m != NR_DEFAULT_MODEL]
    if p == "gemini":
        key = _key_manager().get_active_key("gemini")
        if not key:
            return []

        def _sync():
            import urllib.request
            url = f"https://generativelanguage.googleapis.com/v1beta/models?key={key}&pageSize=200"
            with urllib.request.urlopen(url, timeout=20) as resp:
                return json.loads(resp.read().decode())
        try:
            d = await asyncio.to_thread(_sync)
            return [m["name"].replace("models/", "") for m in d.get("models", [])
                    if "image" in m.get("name", "").lower() and "generateContent" in m.get("supportedGenerationMethods", [])]
        except Exception as e:
            logger.warning("list_models gemini: %s", e)
            return []
    return []
