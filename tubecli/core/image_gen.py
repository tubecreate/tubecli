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
import io
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
# Bản lùi khi 9Router hỏng/hết quota = model Cloudflare mặc định. KHÔNG dùng flux-2-klein-9b: giấy phép
# FLUX Non-Commercial của Black Forest Labs — video đăng YouTube kiếm tiền là dùng thương mại (16/9/2026).
NR_FALLBACK_CF_MODEL = CF_DEFAULT_MODEL
PROVIDERS = ("cloudflare", "gemini", "9router")
ASPECT_RATIOS = ("16:9", "9:16", "1:1", "4:3", "3:4")
DEFAULT_MODELS = {"cloudflare": CF_DEFAULT_MODEL, "gemini": GEMINI_DEFAULT_MODEL, "9router": NR_DEFAULT_MODEL}
# 429 của Cloudflare KHÔNG phải hết hạn mức ngày (giới hạn theo phút / quá tải): đỗ ngắn rồi dùng lại, không 15 phút.
CF_RATE_COOLDOWN_SEC = 60
# Mọi account đều đang đỗ nhưng có account mở lại trong chừng này giây → chờ rồi vẽ tiếp, thay vì bỏ cả lô.
CF_WAIT_MAX_SEC = 75
# Số bước khử nhiễu của flux-1-schnell. Đo thật 18/9/2026: 8 bước bám prompt hơn rõ (3 vật trong khung thì
# vẽ đủ 3, 4 bước thường rụng còn 1–2) nhưng tốn gấp đôi neuron, nên mặc định vẫn 4 — ai cần thì đặt.
CF_STEPS_DEFAULT = 4
CF_STEPS_MIN = 1
CF_STEPS_MAX = 8


class ProviderError(Exception):
    """Lỗi từ nhà cung cấp, kèm `kind`: rate_limit | auth | refused | error."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


# ── cài đặt chung ─────────────────────────────────────────────────────────────

def _clamp_steps(v) -> int:
    """0 = để model tự dùng mặc định của nó; số ngoài khoảng thì kẹp về khoảng Cloudflare cho phép."""
    try:
        n = int(str(v if v is not None else "0").strip() or 0)
    except (TypeError, ValueError):
        return 0
    return 0 if n <= 0 else max(CF_STEPS_MIN, min(CF_STEPS_MAX, n))


def _ink_mode(v) -> str:
    """auto (mặc định: chỉ ảnh nét vẽ mới làm dày) | off | on."""
    m = str(v or "").strip().lower()
    return m if m in INK_MODES else "auto"


def _clamp_radius(v) -> int:
    """0 = tự tính theo cỡ ảnh và độ mảnh của nét."""
    try:
        n = int(str(v if v is not None else "0").strip() or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, min(9, n))


def image_settings() -> dict:
    """{provider, model, steps, ink, ink_radius} — chuỗi rỗng / 0 = tự chọn (auto)."""
    try:
        from tubecli.config import read_global_settings
        g = read_global_settings()
    except Exception:
        g = {}
    p = str(g.get("image_provider") or "").strip().lower()
    m = str(g.get("image_model") or "").strip()
    if p in ("auto",):
        p = ""
    return {"provider": p, "model": m, "steps": _clamp_steps(g.get("image_steps")),
            "ink": _ink_mode(g.get("image_ink")), "ink_radius": _clamp_radius(g.get("image_ink_radius"))}


def set_image_settings(provider: Optional[str], model: Optional[str], steps: Optional[int] = None,
                       ink: Optional[str] = None, ink_radius: Optional[int] = None) -> dict:
    """Ba cài đặt sau chỉ ghi khi được truyền: lượt PUT chỉ đổi nhà cung cấp không được xoá chúng."""
    p = str(provider or "").strip().lower()
    if p in ("auto",):
        p = ""
    if p and p not in PROVIDERS:
        raise ValueError(f"Không biết nhà cung cấp ảnh '{p}'. Chỉ hỗ trợ: {', '.join(PROVIDERS)} (hoặc để trống để tự chọn).")
    if ink is not None and str(ink).strip().lower() not in INK_MODES:
        raise ValueError(f"Không biết chế độ làm dày nét '{ink}'. Chỉ hỗ trợ: {', '.join(INK_MODES)}.")
    from tubecli.config import set_global_setting
    set_global_setting("image_provider", p)
    set_global_setting("image_model", str(model or "").strip())
    if steps is not None:
        set_global_setting("image_steps", _clamp_steps(steps))
    if ink is not None:
        set_global_setting("image_ink", str(ink).strip().lower())
    if ink_radius is not None:
        set_global_setting("image_ink_radius", _clamp_radius(ink_radius))
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
            accs = _cf_accounts()
            if accs:
                # Có account mà account nào cũng đang đỗ / tắt: "chưa có credential" là nói sai — Studio chọn nhà
                # ở đầu mỗi lô nên người dùng từng thấy đúng câu sai này (15/9/2026).
                states = "; ".join(f"{a['label']} — {_cf_state_text(a)}" for a in accs)
                return {"ok": False, "provider": "cloudflare", "model": m or CF_DEFAULT_MODEL,
                        "reason": f"All Cloudflare accounts are paused: {states}. Add another Cloudflare account "
                                  "in Cloud API Keys, or wait for one to resume."}
            return {"ok": False, "provider": "cloudflare", "model": m or CF_DEFAULT_MODEL,
                    "reason": "Chưa có credential Cloudflare (cần API token + Account ID) trong Cloud API Keys."}
        return {"ok": True, "provider": "cloudflare", "model": m or CF_DEFAULT_MODEL,
                "creds": creds, "label": creds.get("label") or "", "reason": "",
                "steps": cfg.get("steps") or 0}

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
    """Định danh tài khoản đang dùng. Cloudflare = token + account_id: Global API Key dùng CHUNG cho mọi account
    cùng email, còn hạn mức Workers AI tính theo account (15/9/2026)."""
    creds = r.get("creds") or {}
    if creds.get("api_token"):
        return f"{creds['api_token']}|{creds.get('account_id') or ''}"
    return str(r.get("key") or r.get("base") or "")


def _acc_id(acc: dict) -> str:
    return f"{acc.get('api_token') or ''}|{acc.get('account_id') or ''}"


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
            if transient and _is_daily_quota(msg):
                until = _next_utc_midnight()
            elif transient:
                until = time.time() + CF_RATE_COOLDOWN_SEC      # 429 theo phút / quá tải: đỗ ngắn
            else:
                until = None
            r["parked_until"] = until
            creds = r["creds"]
            try:
                km.report_key_error("cloudflare", creds["api_token"], msg[:160], transient=transient, until=until,
                                    only_label=creds.get("label") or None, account_id=creds.get("account_id") or None)
            except TypeError:       # cloud_api cũ: chưa đỗ theo nhãn — đỗ theo khoá như trước
                km.report_key_error("cloudflare", creds["api_token"], msg[:160], transient=transient, until=until)
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


def cf_request(kind: str, prompt: str, aspect_ratio: str, steps: int = 0) -> tuple:
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
    # steps chỉ gửi ở khuôn "prompt" (flux-1-schnell): khuôn dims/multipart của model khác chưa chắc
    # nhận trường này, mà Cloudflare từ chối thẳng trường lạ (Bad input: … not allowed).
    return "application/json", json.dumps({"prompt": f"{prompt} (aspect ratio {aspect_ratio})",
                                           "steps": _clamp_steps(steps) or CF_STEPS_DEFAULT}).encode("utf-8")


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
    ctype, body = cf_request(kind, prompt, aspect_ratio, r.get("steps") or 0)
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

_sleep = asyncio.sleep


def _cf_accounts() -> list:
    try:
        return list(_key_manager().cloudflare_accounts())
    except Exception:      # noqa: BLE001 — cloud_api cũ không có cloudflare_accounts()
        return []


def _cf_switch(r: dict, acc: dict, why: str) -> None:
    """Đưa r sang account `acc` — GHI THẲNG vào r: batch của Studio giữ r cho cả lô, shot sau đi thẳng account mới."""
    old = r.get("label") or "?"
    r["creds"] = {"api_token": acc["api_token"], "account_id": acc["account_id"], "email": acc.get("email", ""),
                  "label": acc["label"]}
    r["label"] = acc["label"]
    r["rotated_to"] = acc["label"]
    r["_rotated"] = True
    logger.warning("cloudflare/%s: account '%s' %s → '%s'", r.get("model"), old, why, acc["label"])


def _cf_state_text(acc: dict) -> str:
    if acc.get("active"):
        return "available"
    msg = str(acc.get("status_msg") or "").strip()
    reason = "daily free allocation used up" if _is_daily_quota(msg) else (msg[:80] or "turned off")
    if acc.get("disable_reason") != "transient":
        return f"{reason} (turned off — re-enable it in Cloud API Keys)"
    until = acc.get("disabled_until")
    return f"{reason}, resumes {_local_clock(float(until))}" if until else reason


async def _cf_generate_rotating(r: dict, prompt: str, aspect_ratio: str, timeout: int) -> bytes:
    """Vẽ bằng Cloudflare, thử LẦN LƯỢT mọi account còn dùng được (user 15/9/2026: "lỗi tạo ảnh claudflare không
    xoay tua").

    * account của r đang bị đỗ → đổi sang account đang bật TRƯỚC khi gọi (Studio thử lại shot không đập vào account đỗ)
    * 429 / 401 → đỗ ĐÚNG account (hết hạn mức ngày: tới 00:00 UTC; 429 thường: CF_RATE_COOLDOWN_SEC) → account kế
    * hết account mà có account mở lại trong CF_WAIT_MAX_SEC → chờ rồi vẽ tiếp (một lần)
    * hết cách → lỗi kể TỪNG account kèm lý do và lúc mở lại
    """
    tried: list = []
    waited = False
    first_err = None
    while True:
        accounts = _cf_accounts()
        cur = next((a for a in accounts if _acc_id(a) == _cred_id(r)), None)
        if cur is not None and not cur["active"]:
            nxt = next((a for a in accounts if a["active"] and _acc_id(a) not in tried), None)
            if nxt is not None:
                _cf_switch(r, nxt, "is parked")
        try:
            return await _cf_generate(r, prompt, aspect_ratio, timeout)
        except ProviderError as e:
            if e.kind not in ("rate_limit", "auth"):
                raise
            first_err = first_err or e
            _report_key(r, str(e), transient=(e.kind == "rate_limit"))
            tried.append(_cred_id(r))
            accounts = _cf_accounts()
            nxt = next((a for a in accounts if a["active"] and _acc_id(a) not in tried), None)
            if nxt is not None:
                _cf_switch(r, nxt, f"refused ({str(e)[:80]})")
                continue
            soonest = min((float(a["disabled_until"]) for a in accounts
                           if not a["active"] and a.get("disable_reason") == "transient" and a.get("disabled_until")),
                          default=None)
            if not waited and soonest is not None and soonest - time.time() <= CF_WAIT_MAX_SEC:
                waited = True
                tried.clear()
                logger.warning("cloudflare: every account is parked — waiting %.0f s for one to resume",
                               max(0.0, soonest - time.time()))
                await _sleep(max(1.0, soonest - time.time() + 1))
                continue
            if not accounts:
                raise
            states = "; ".join(f"{a['label']} — {_cf_state_text(a)}" for a in accounts)
            raise ProviderError(e.kind, f"{first_err} — Cloudflare accounts tried: {states}. Add another Cloudflare "
                                        "account in Cloud API Keys, or wait for one to resume.") from e


async def _generate_bytes(r: dict, prompt: str, aspect_ratio: str = "16:9",
                          reference_images: Optional[list] = None, timeout: int = 180) -> bytes:
    """Bytes ảnh từ nhà cung cấp đã resolve; ném ProviderError. Có đường lùi (9Router → Cloudflare).

    Xoay khoá: rate_limit/auth → resolve lại; ra tài khoản KHÁC thì vẽ ngay bằng nó và ghi tài
    khoản mới vào `r` (caller giữ `r` cho cả lô nên các shot sau đi thẳng, không tốn thêm 429).
    """
    r.pop("fallback_from", None)
    r.pop("drew_provider", None)
    r.pop("drew_model", None)
    try:
        if r["provider"] == "cloudflare":
            return await _cf_generate_rotating(r, prompt, aspect_ratio, timeout)
        if r["provider"] == "9router":
            return await _nr_generate(r, prompt, aspect_ratio, timeout)
        return await _gemini_generate(r, prompt, aspect_ratio, reference_images, timeout)
    except ProviderError as e:
        # Cloudflare: đỗ + xoay qua MỌI account đã làm trong _cf_generate_rotating. Gemini: như cũ.
        if r["provider"] != "cloudflare":
            if e.kind == "rate_limit":
                _report_key(r, str(e), transient=True)
            elif e.kind == "auth":
                _report_key(r, str(e), transient=False)
        if e.kind in ("rate_limit", "auth") and not r.get("_rotated") and r["provider"] != "cloudflare":
            nr = resolve_provider(r["provider"], r.get("model"))
            if nr.get("ok") and _cred_id(nr) and _cred_id(nr) != _cred_id(r):
                logger.warning("%s/%s: %s → xoay sang tài khoản '%s'", r["provider"], r["model"], str(e)[:100], nr.get("label") or "?")
                nr["_rotated"] = True
                data = await _generate_bytes(nr, prompt, aspect_ratio, reference_images, timeout)
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
            data = await _generate_bytes(fb, prompt, aspect_ratio, reference_images, timeout)
            r["fallback_from"] = f"{r['provider']}/{r['model']}: {str(e)[:160]}"
            # Bên VẼ THẬT là đường lùi (có thể lùi tiếp một tầng nữa) — báo cáo phải ghi tên nó, không
            # phải nhà đã hỏng: Sheet và thẻ bước từng ghi "9router" cho ảnh Cloudflare vẽ.
            r["drew_provider"] = fb.get("drew_provider") or fb["provider"]
            r["drew_model"] = fb.get("drew_model") or fb["model"]
            return data
        raise


# ── làm dày nét cho ảnh NÉT VẼ (doodle, người que, whiteboard) ────────────────
# Vì sao: đo thật 18/9/2026 trên FLUX-1 schnell — nó vẽ ĐÚNG thể loại người que mực đen trên giấy trắng
# nhưng nét MẢNH hơn hẳn video whiteboard thật, và viết "very thick bold 8px stroke" vào prompt cũng
# không dày thêm. Một bước hình thái học (MinFilter = lấy điểm tối nhất quanh pixel) kéo nét đen dày ra
# đúng cỡ bút lông. Chỉ ảnh nét vẽ mới bị đụng: ảnh chụp, tranh màu nước… trả về nguyên xi.
# Đo trên chính video whiteboard mẫu (18/9/2026): phóng khung lên cạnh ngắn 1024 thì nét dày 9,75 px
# ⇒ bút lông ≈ cạnh ngắn / 105. FLUX-1 schnell vẽ ra 6,2 px, MinFilter(5) đưa lên 11,0 px là khớp mắt.
INK_TARGET_DIV = 105
INK_MIN_TARGET = 3.0
# Phép ước độ dày chỉ là phép ĐO GẦN: trên hình nhiều mực nó đo thiếu, nên bán kính tính ra lại quá tay —
# bản thử 18/9/2026 ra 14,9 px so với đích 9,75 và mắt người que bết thành một cục đen. Nên sau khi làm dày
# phải đo lại; quá trần thì lùi bán kính. Trần 1,35 lần: trên ngưỡng đó nét bắt đầu ăn vào chi tiết nhỏ.
INK_OVER_LIMIT = 1.35
INK_MODES = ("auto", "off", "on")


def _pil():
    try:
        from PIL import Image, ImageFilter, ImageOps, ImageStat
        return Image, ImageFilter, ImageOps, ImageStat
    except Exception:       # noqa: BLE001 — thiếu Pillow thì bỏ qua bước trang trí, không ai mất ảnh
        return None


def ink_stats(im) -> dict:
    """Số đo quyết định: ảnh này CÓ PHẢI nét đen trên trắng, và nét đang dày bao nhiêu pixel."""
    _, ImageFilter, _, ImageStat = _pil()
    g = im.convert("L")
    w, h = g.size
    total = max(1, w * h)
    hist = g.histogram()
    ink = max(1, sum(hist[:128]))
    # Nét rộng d pixel, mòn 1 pixel mỗi bên thì còn d-2 → phần còn lại cho ra chính d.
    kept = sum(g.filter(ImageFilter.MaxFilter(3)).histogram()[:128]) / ink
    return {"white": sum(hist[240:]) / total, "mid": sum(hist[60:200]) / total,
            "dark": sum(hist[:128]) / total,
            "sat": (ImageStat.Stat(im.convert("HSV").split()[1]).mean[0] / 255.0
                    if im.mode not in ("L", "1") else 0.0),
            "width": (2.0 / (1.0 - kept)) if kept < 0.97 else 99.0,
            "target": max(INK_MIN_TARGET, min(w, h) / INK_TARGET_DIV)}


def is_line_art(st: dict) -> bool:
    """Gần hết là giấy trắng, gần như không có nửa tối (bóng/khối), gần như không màu, mà vẫn có mực.

    Sàn mực thấp (0,2 %) vì một hình người que nhỏ giữa khung 1024 chỉ chiếm chừng đó; nó chỉ để loại
    ảnh TRẮNG TRƠN (lượt vẽ hỏng) chứ không phải để đo độ dày.
    """
    return (st["white"] >= 0.80 and st["mid"] <= 0.12 and st["sat"] <= 0.06
            and 0.002 <= st["dark"] <= 0.30)


def thicken_ink(data: bytes, mode: str = "", radius: int = 0) -> bytes:
    """Ảnh nét vẽ mà nét mảnh hơn cỡ bút lông → làm dày; còn lại trả về nguyên bytes.

    Mọi lỗi ở đây đều bị nuốt: ảnh đã vẽ xong và đã tính tiền rồi, không được để bước trang trí
    làm đổ cả lô.
    """
    if not data:
        return data
    cfg = image_settings()
    mode = (mode or cfg["ink"] or "auto").strip().lower()
    mods = _pil()
    if mode == "off" or not mods:
        return data
    Image, ImageFilter, ImageOps, _ = mods
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
        fmt = (im.format or "PNG").upper()
        st = ink_stats(im)
        if mode == "auto" and not is_line_art(st):
            return data
        want = int(radius or cfg["ink_radius"] or 0)
        fixed = bool(want)      # người dùng chỉ định tay thì tôn trọng, không tự lùi
        if not want:
            grow = st["target"] - st["width"]
            if mode == "auto" and grow < 1.0:
                return data                     # nét đã đủ dày, đụng vào chỉ làm bết
            want = int(max(3, min(9, round(grow) + 1)))
        want = want if want % 2 else want + 1
        gray = im.convert("L")
        out = None
        # want luôn là số LẺ ≥ 3 nên vòng này chạy want, want-2, … 3 rồi dừng hẳn ở 3.
        for k in range(want, 1, -2):
            out = ImageOps.autocontrast(gray.filter(ImageFilter.MinFilter(k)), cutoff=1)
            if fixed or k <= 3 or ink_stats(out)["width"] <= st["target"] * INK_OVER_LIMIT:
                break
        buf = io.BytesIO()
        if fmt in ("JPEG", "JPG"):
            out.save(buf, "JPEG", quality=92)
        elif fmt == "WEBP":
            out.save(buf, "WEBP", quality=95)
        else:
            out.save(buf, "PNG", optimize=True)
        return buf.getvalue()
    except Exception as e:      # noqa: BLE001
        logger.info("bỏ qua bước làm dày nét: %s", e)
        return data


async def generate_bytes(r: dict, prompt: str, aspect_ratio: str = "16:9",
                         reference_images: Optional[list] = None, timeout: int = 180) -> bytes:
    """Bytes ảnh của nhà đã resolve, ĐÃ qua bước làm dày nét nếu là ảnh nét vẽ (xem thicken_ink).

    Bọc ngoài `_generate_bytes` để bước làm dày chạy ĐÚNG MỘT LẦN: bên trong nó còn tự xoay tài khoản
    và lùi sang nhà khác bằng cách gọi đệ quy chính nó.
    """
    return thicken_ink(await _generate_bytes(r, prompt, aspect_ratio, reference_images, timeout))


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
    out = {"status": STATUS_SUCCESS, "path": out_path,
           "provider": r.get("drew_provider") or r["provider"],
           "model": r.get("drew_model") or r["model"], "label": r.get("label", "")}
    if r.get("fallback_from"):
        out["fallback_from"] = r["fallback_from"]
    if r.get("rotated_to"):
        out["rotated_to"] = r["rotated_to"]
    return out


# ── vẽ thử bằng ĐÚNG MỘT khoá đã lưu (nút «🖼 Test ảnh» ở Cloud API Keys, 17/9/2026) ───────────────────────────
KEY_TEST_PROMPT = "A single red apple on a plain white table, soft daylight, simple and clean"


def resolve_key(provider: str, label: str = "default", model: Optional[str] = None) -> dict:
    """Như resolve_provider nhưng CHỈ khoá (provider, nhãn) người dùng bấm: không xoay tài khoản, không đường lùi
    Cloudflare — kết quả phải nói về chính khoá đó (Test chung từng báo 9Router «OK» trong khi Cloudflare vẽ thay).
    Model: tham số → model đã chọn cho nhà này ở AI tạo ảnh → mặc định của nhà."""
    p = str(provider or "").strip().lower()
    label = str(label or "default")
    if p not in PROVIDERS:
        return {"ok": False, "provider": p, "model": "", "label": label,
                "reason": f"'{p}' is not an image provider — image tests work for: {', '.join(PROVIDERS)}."}
    cfg = image_settings()
    m = (model or "").strip() or (cfg["model"] if cfg["provider"] == p else "") or DEFAULT_MODELS[p]
    entry = _key_manager().get_key_entry(p, label)
    if not entry or not entry.get("key"):
        return {"ok": False, "provider": p, "model": m, "label": label,
                "reason": f"No saved key '{label}' for {p}."}
    base = {"ok": True, "provider": p, "model": m, "label": label, "reason": "", "_rotated": True}
    if p == "cloudflare":
        if not entry.get("account_id"):
            return {**base, "ok": False, "reason": "This Cloudflare key has no Account ID — add it to draw images."}
        return {**base, "creds": {"api_token": entry["key"], "account_id": entry["account_id"],
                                  "email": entry.get("email") or "", "label": label}}
    if p == "gemini":
        return {**base, "key": entry["key"]}
    nr = _ninerouter_module()
    if nr is None:
        return {**base, "ok": False, "reason": "This TubeCLI has no 9Router module — update TubeCLI."}
    return {**base, "base": nr.base_url(), "headers": nr.auth_headers(entry["key"])}


def _short_error(message: str) -> str:
    """«HTTP 429: {…JSON dài…}» → «HTTP 429: You exceeded your current quota…» — câu hiện trong bảng khoá phải đọc
    được. Lấy error.message (Gemini/OpenAI), errors[0].message (Cloudflare) hay detail; không phải JSON thì giữ nguyên."""
    import re as _re

    msg = str(message or "").strip()
    m = _re.match(r"^(HTTP \d+):\s*(.*)$", msg, _re.S)
    if not m:
        return msg[:300]
    head, body = m.group(1), m.group(2).strip()
    try:
        data = json.loads(body)
    except ValueError:
        return f"{head}: {' '.join(body.split())}"[:300]
    text = ""
    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, dict):
            text = str(err.get("message") or "")
        elif isinstance(err, str):
            text = err
        errs = data.get("errors")
        if not text and isinstance(errs, list) and errs and isinstance(errs[0], dict):
            text = str(errs[0].get("message") or "")
        text = text or str(data.get("detail") or data.get("message") or "")
    return f"{head}: {' '.join(text.split())}"[:300] if text else f"{head}: {' '.join(body.split())}"[:300]


def _image_ext(data: bytes) -> str:
    if data[:4] == b"\x89PNG":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return "jpg"


async def test_key_draw(provider: str, label: str = "default", model: Optional[str] = None,
                        timeout: int = 150) -> dict:
    """Vẽ thử MỘT ảnh 1:1 bằng đúng một khoá; ảnh giữ lại ở data/images để xem (mỗi khoá một file, lần sau ghi
    đè). Ghi kết quả lên khoá. Trả {ok, stage, provider, label, model, seconds, message, kind, url, width, height}."""
    import hashlib

    r = resolve_key(provider, label, model)
    out = {"ok": False, "stage": "credentials", "provider": r.get("provider", ""), "label": r.get("label", ""),
           "model": r.get("model", ""), "seconds": 0, "message": r.get("reason", ""), "kind": "", "url": "",
           "width": 0, "height": 0}
    if r.get("ok"):
        out["stage"] = "generate"
        t0 = time.time()
        try:
            if r["provider"] == "cloudflare":
                data = await _cf_generate(r, KEY_TEST_PROMPT, "1:1", timeout)       # một account, không xoay
            elif r["provider"] == "gemini":
                data = await _gemini_generate(r, KEY_TEST_PROMPT, "1:1", None, timeout)
            else:
                data = await _nr_generate(r, KEY_TEST_PROMPT, "1:1", timeout)       # không lùi sang Cloudflare
            if not data:
                raise ProviderError("error", "The provider returned no image.")
            stem = f"keytest_{r['provider']}_{hashlib.sha1(r['label'].encode('utf-8')).hexdigest()[:10]}"
            folder = shared_output_dir()
            for old in os.listdir(folder):
                if old.startswith(stem + "."):
                    try:
                        os.remove(os.path.join(folder, old))
                    except OSError:
                        pass
            name = f"{stem}.{_image_ext(data)}"
            with open(os.path.join(folder, name), "wb") as f:
                f.write(data)
            out.update({"ok": True, "message": "", "url": f"/api/v1/images/file/{name}"})
            try:
                from PIL import Image
                import io as _io
                with Image.open(_io.BytesIO(data)) as im:
                    out["width"], out["height"] = im.size
            except Exception:      # noqa: BLE001 — không đo được cỡ thì vẫn là vẽ được
                pass
        except ProviderError as e:
            out.update({"message": _short_error(str(e)), "kind": e.kind})
        except Exception as e:      # noqa: BLE001
            out.update({"message": f"{type(e).__name__}: {e}", "kind": "error"})
        out["seconds"] = round(time.time() - t0, 1)
    try:
        import datetime as _dt
        if out["provider"] not in PROVIDERS:
            return out                  # khoá không phải nhà vẽ ảnh: không ghi gì lên nó
        _key_manager().set_image_test(out["provider"], out["label"], {
            "ok": out["ok"], "model": out["model"], "seconds": out["seconds"], "message": out["message"][:300],
            "kind": out["kind"], "at": _dt.datetime.now().isoformat(timespec="seconds")})
    except Exception as e:      # noqa: BLE001
        logger.info("image key test not recorded: %s", e)
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
