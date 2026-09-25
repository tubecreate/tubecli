"""
Cloud API Extension — API routes.
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional

# Router này chứa CF token + mọi AI API key. Origin-guard chặn trang web
# cross-origin (evil.com) fetch/CSRF tới đây — cùng cơ chế với website_manager.
from tubecli.core.origin_guard import guard_origin

router = APIRouter(
    prefix="/api/v1/cloud-api",
    tags=["cloud-api"],
    dependencies=[Depends(guard_origin)],
)


class AddKeyRequest(BaseModel):
    provider: str
    api_key: str
    label: str = "default"


class RemoveKeyRequest(BaseModel):
    provider: str
    label: str = "default"


class TestKeyRequest(BaseModel):
    provider: str
    label: str = "default"


class TestImageKeyRequest(BaseModel):
    provider: str
    label: str = "default"
    model: str = ""             # "" = model đã chọn cho nhà này ở AI tạo ảnh, không có thì mặc định


@router.get("/providers")
async def api_list_providers():
    """List all supported cloud AI providers."""
    from tubecli.extensions.cloud_api.extension import key_manager
    return {"providers": key_manager.list_providers()}


@router.get("/keys")
async def api_list_keys(provider: Optional[str] = None):
    """List stored API keys (masked)."""
    from tubecli.extensions.cloud_api.extension import key_manager
    return {"keys": key_manager.list_keys(provider)}


@router.post("/keys")
async def api_add_key(req: AddKeyRequest):
    """Add an API key for a cloud provider."""
    from tubecli.extensions.cloud_api.extension import key_manager
    result = key_manager.add_key(req.provider, req.api_key, req.label)
    if result["status"] == "error":
        raise HTTPException(400, result["message"])
    return result


@router.delete("/keys")
async def api_remove_key(req: RemoveKeyRequest):
    """Remove an API key."""
    from tubecli.extensions.cloud_api.extension import key_manager
    result = key_manager.remove_key(req.provider, req.label)
    if result["status"] == "error":
        raise HTTPException(404, result["message"])
    return result


@router.post("/keys/test")
async def api_test_key(req: TestKeyRequest):
    """Test if an API key is valid."""
    from tubecli.extensions.cloud_api.extension import key_manager
    return key_manager.test_key(req.provider, req.label)


@router.post("/keys/test-image")
async def api_test_image_key(req: TestImageKeyRequest):
    """Vẽ thử MỘT ảnh bằng đúng khoá này (Cloudflare, Gemini, 9Router) — không xoay khoá, không lùi nhà khác."""
    from tubecli.core import image_gen
    return await image_gen.test_key_draw(req.provider, req.label, req.model or None)


@router.post("/keys/enable")
async def api_enable_key(req: TestKeyRequest):
    """Re-enable a key that was auto-disabled on a quota error."""
    from tubecli.extensions.cloud_api.extension import key_manager
    result = key_manager.enable_key(req.provider, req.label)
    if result["status"] == "error":
        raise HTTPException(404, result["message"])
    return result


@router.get("/keys/{provider}/active")
async def api_get_active_key(provider: str):
    """Get the active API key for a provider (for internal use by agents)."""
    from tubecli.extensions.cloud_api.extension import key_manager
    key = key_manager.get_active_key(provider)
    if not key:
        raise HTTPException(404, f"No active key for provider '{provider}'")
    # Return masked for security
    masked = key[:6] + "..." + key[-4:] if len(key) > 10 else "***"
    return {"provider": provider, "has_key": True, "masked_key": masked}

class UpdateProviderSettings(BaseModel):
    models: Optional[list[str]] = None
    # Endpoint của provider tự host (9Router ở máy khác). None = giữ nguyên; "" = về mặc định.
    base_url: Optional[str] = None


class TestEndpointRequest(BaseModel):
    base_url: str = ""          # "" = endpoint đang lưu
    api_key: str = ""           # "" = key đang bật của provider

@router.post("/providers/{provider}/refresh-models")
def api_refresh_models(provider: str):
    """Replace the model list with the provider's own live catalogue.

    `def`, not `async def`: this does a blocking urllib fetch, and Starlette
    runs sync endpoints in the threadpool instead of freezing the event loop.
    """
    from tubecli.extensions.cloud_api.extension import key_manager
    result = key_manager.refresh_models(provider)
    if result["status"] == "error":
        raise HTTPException(400, result["message"])
    return result


@router.put("/providers/{provider}/settings")
async def api_update_provider_settings(provider: str, req: UpdateProviderSettings):
    """Update settings for a provider: the models list and/or the endpoint (base_url)."""
    from tubecli.extensions.cloud_api.extension import key_manager
    if req.models is None and req.base_url is None:
        raise HTTPException(400, "Nothing to update — send models and/or base_url.")
    result = {"status": "success"}
    if req.models is not None:
        result = key_manager.set_models(provider, req.models)
        if result["status"] == "error":
            raise HTTPException(400, result["message"])
    if req.base_url is not None:
        res_url = key_manager.set_base_url(provider, req.base_url)
        if res_url["status"] == "error":
            raise HTTPException(400, res_url["message"])
        result = {**result, **res_url}
    return result


@router.post("/providers/{provider}/test-endpoint")
def api_test_provider_endpoint(provider: str, req: TestEndpointRequest):
    """Thử một endpoint TRƯỚC khi lưu: GET <endpoint>/models với key → số model, hay lỗi nói rõ.

    `def`, không `async def`: gọi mạng đồng bộ, Starlette chạy nó trong threadpool.
    """
    import requests as _req
    from tubecli.extensions.cloud_api.extension import key_manager, normalize_base_url, CUSTOM_BASE_PROVIDERS
    if provider not in CUSTOM_BASE_PROVIDERS:
        raise HTTPException(400, f"{provider} không đổi endpoint được.")
    try:
        base = normalize_base_url(req.base_url) or key_manager.get_base_url(provider)
    except ValueError as e:
        raise HTTPException(400, str(e))
    key = req.api_key.strip() or key_manager.get_active_key(provider) or ""
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        resp = _req.get(base + "/models", headers=headers, timeout=15)
    except Exception as e:      # noqa: BLE001
        return {"ok": False, "base_url": base, "has_key": bool(key), "error": f"Không kết nối được: {e}"}
    if resp.status_code != 200:
        return {"ok": False, "base_url": base, "has_key": bool(key), "status_code": resp.status_code,
                "error": (resp.text or f"HTTP {resp.status_code}")[:300]}
    try:
        data = resp.json()
        models = [m.get("id") for m in (data.get("data") or []) if isinstance(m, dict) and m.get("id")]
    except (ValueError, AttributeError):
        models = []
    return {"ok": True, "base_url": base, "has_key": bool(key), "model_count": len(models), "models": models[:60]}

class TestModelRequest(BaseModel):
    model: str
    prompt: str = "Reply 'Hello from API!'"

def is_image_model(model: str) -> bool:
    """Model VẼ ẢNH theo tên: cx/gpt-image-2, ag/gemini-3.1-flash-image, @cf/black-forest-labs/flux-1-schnell…

    Nút Test từng gửi mọi model vào /chat/completions — model ảnh bị từ chối dù vẫn tốt (máy khách 25/9/2026 test
    cx/gpt-image-2 «không được»)."""
    m = str(model or "").lower()
    return any(k in m for k in ("image", "flux", "stable-diffusion", "sdxl", "dall-e", "imagen", "phoenix", "lucid-origin"))


async def _test_image_model(prov: str, model: str, prompt: str) -> dict:
    """Vẽ thử MỘT ảnh bằng bộ vẽ của lõi (đúng cổng /images/generations của 9Router, Gemini, Cloudflare) — KHÔNG đường
    lùi: hỏng thì trả đúng lỗi của nhà cung cấp (vd «usage limit has been reached»), chứ không vẽ bằng model khác
    rồi báo xanh."""
    import base64
    import io
    from tubecli.core import image_gen as G
    r = G.resolve_provider(prov, model)
    if not r.get("ok"):
        raise HTTPException(400, r.get("reason") or f"{prov}/{model} is not usable on this machine")
    r.pop("fallback", None)
    try:
        data = await G.generate_bytes(r, prompt or "a simple chalk drawing of a house", "1:1", timeout=180)
    except Exception as e:      # noqa: BLE001 — trả nguyên lời nhà cung cấp cho người bấm Test
        raise HTTPException(502, f"{prov}/{model}: {e}")
    size = None
    try:
        from PIL import Image
        size = list(Image.open(io.BytesIO(data)).size)
    except Exception:           # noqa: BLE001
        pass
    mime = "image/png" if data[:4] == b"\x89PNG" else "image/jpeg"
    return {"status": "success", "kind": "image", "size": size, "bytes": len(data),
            "image": f"data:{mime};base64," + base64.b64encode(data).decode("ascii")}


@router.post("/providers/{provider}/test-model")
async def api_test_provider_model(provider: str, req: TestModelRequest):
    """Test a specific model."""
    from tubecli.extensions.cloud_api.extension import key_manager
    from tubecli.core.ai_generator import call_gemini, call_openai_compatible, call_claude
    
    prov = provider.lower()
    if is_image_model(req.model):
        return await _test_image_model(prov, req.model, req.prompt)
    # Cloudflare is compound (account_id + token) and account-scoped, so it does
    # not fit get_active_key. Route it to the dedicated caller, which reads the
    # compound credential itself.
    if prov == "cloudflare":
        from tubecli.core.brain import AgentBrain
        res = AgentBrain._call_cloudflare(req.model, [{"role": "user", "content": req.prompt}], 0.3)
        if isinstance(res, str) and res.startswith("[Cloudflare Error]"):
            raise HTTPException(400, res)
        return {"status": "success", "response": res}

    key = key_manager.get_active_key(provider)
    if not key:
        raise HTTPException(400, f"No active key configured for {provider}")

    try:
        if prov == "gemini":
            res = call_gemini(req.model, key, req.prompt)
        elif prov == "openai" or prov == "chatgpt":
            res = call_openai_compatible(req.model, key, req.prompt)
        elif prov == "grok":
            res = call_openai_compatible(req.model, key, req.prompt, base_url="https://api.x.ai/v1")
        elif prov == "deepseek":
            res = call_openai_compatible(req.model, key, req.prompt, base_url="https://api.deepseek.com")
        elif prov == "claude":
            res = call_claude(req.model, key, req.prompt)
        elif prov == "openrouter":
            res = call_openai_compatible(req.model, key, req.prompt, base_url="https://openrouter.ai/api/v1")
        elif prov == "9router":
            # 9Router: endpoint trong Cloud API Keys (mặc định cổng 20128 trên máy này)
            res = call_openai_compatible(req.model, key or "9router", req.prompt,
                                         base_url=key_manager.get_base_url("9router"))
        else:
            raise HTTPException(400, f"Direct testing for {provider} not supported.")
            
        return {"status": "success", "response": res}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/9router/status")
async def api_9router_status():
    """Check if 9Router is running and get its models."""
    import requests as _req
    from tubecli.extensions.cloud_api.extension import key_manager
    try:
        key = key_manager.get_active_key("9router")
        headers = {}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        from tubecli.extensions.cloud_api.extension import is_local_url
        base = key_manager.get_base_url("9router")
        remote = not is_local_url(base)
        resp = _req.get(base + "/models", headers=headers, timeout=10 if remote else 3)
        if resp.status_code == 200:
            data = resp.json()
            models = []
            if isinstance(data, dict) and "data" in data:
                models = [m.get("id", m.get("name", "")) for m in data["data"] if isinstance(m, dict)]
            return {"running": True, "model_count": len(models), "models": models, "base_url": base, "remote": remote}
        return {"running": False, "model_count": 0, "models": [], "base_url": base, "remote": remote,
                "status_code": resp.status_code}
    except Exception:
        return {"running": False, "model_count": 0, "models": []}


# ── Cloudflare Credential Routes ──────────────────────────────────────


class AddCloudflareKeyRequest(BaseModel):
    api_token: str
    account_id: str
    label: str = "default"
    email: str = ""   # có email → api_token là Global API Key


class TestCloudflareKeyRequest(BaseModel):
    label: str = "default"


@router.get("/cloudflare/profiles")
async def api_list_cloudflare_profiles():
    """List all stored Cloudflare credential profiles."""
    from tubecli.extensions.cloud_api.extension import key_manager
    return {"profiles": key_manager.list_cloudflare_keys()}


@router.post("/cloudflare/profiles")
async def api_add_cloudflare_profile(req: AddCloudflareKeyRequest):
    """Add or update Cloudflare credentials (API Token + Account ID)."""
    from tubecli.extensions.cloud_api.extension import key_manager
    if not req.api_token:
        raise HTTPException(400, "API Token là bắt buộc.")
    if not req.account_id:
        raise HTTPException(400, "Account ID là bắt buộc.")
    result = key_manager.add_cloudflare_key(req.api_token, req.account_id, req.label, req.email)
    if result["status"] == "error":
        raise HTTPException(400, result["message"])
    return result


@router.delete("/cloudflare/profiles/{label}")
async def api_delete_cloudflare_profile(label: str):
    """Delete a Cloudflare credential profile."""
    from tubecli.extensions.cloud_api.extension import key_manager
    result = key_manager.remove_key("cloudflare", label)
    if result["status"] == "error":
        raise HTTPException(404, result["message"])
    return result


class ProbeCloudflareRequest(BaseModel):
    api_token: str
    account_id: str = ""
    email: str = ""


@router.post("/cloudflare/probe")
async def api_probe_cloudflare(req: ProbeCloudflareRequest):
    """Check a Cloudflare credential WITHOUT saving it.

    The dashboard's "Verify" button used to POST the credential into the store
    and only then test it — so sanity-checking a pasted token overwrote the
    working profile under the same label, with no confirmation. Checking is now
    a read-only operation.
    """
    from tubecli.extensions.cloud_api.extension import key_manager
    return key_manager.probe_cloudflare(req.api_token, req.account_id, req.email)


@router.post("/cloudflare/profiles/{label}/test")
async def api_test_cloudflare_profile(label: str):
    """Test a Cloudflare API Token by calling the verify endpoint."""
    from tubecli.extensions.cloud_api.extension import key_manager
    return key_manager.test_cloudflare_key(label)


@router.get("/cloudflare/profiles/{label}/creds")
async def api_get_cloudflare_creds(label: str = "default"):
    """Get Cloudflare credentials for internal use (e.g. website_manager deploy).
    Returns masked token for security."""
    from tubecli.extensions.cloud_api.extension import key_manager
    creds = key_manager.get_cloudflare_creds(label)
    if not creds.get("api_token"):
        raise HTTPException(404, f"Không tìm thấy Cloudflare profile '{label}'.")
    token = creds["api_token"]
    masked = token[:6] + "..." + token[-4:] if len(token) > 10 else "***"
    return {
        "label": creds["label"],
        "masked_token": masked,
        "account_id": creds["account_id"],
        "email": creds.get("email", ""),
        "auth_type": "global_key" if creds.get("email") else "api_token",
        "has_creds": True,
    }


@router.get("/cloudflare/creds")
async def api_get_default_cloudflare_creds():
    """Get default Cloudflare credentials (full, for internal extension use).
    Called by website_manager to auto-fill deploy form."""
    from tubecli.extensions.cloud_api.extension import key_manager
    creds = key_manager.get_cloudflare_creds("default")
    if not creds.get("api_token"):
        return {"has_creds": False, "api_token": "", "account_id": "", "label": None}
    token = creds["api_token"]
    masked = token[:6] + "..." + token[-4:] if len(token) > 10 else "***"
    return {
        "has_creds": True,
        "masked_token": masked,
        "account_id": creds["account_id"],
        "email": creds.get("email", ""),
        "auth_type": "global_key" if creds.get("email") else "api_token",
        "label": creds["label"],
    }

