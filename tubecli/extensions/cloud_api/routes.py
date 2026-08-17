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
    models: list[str]

@router.put("/providers/{provider}/settings")
async def api_update_provider_settings(provider: str, req: UpdateProviderSettings):
    """Update settings (e.g. models list) for a provider."""
    from tubecli.extensions.cloud_api.extension import key_manager
    result = key_manager.set_models(provider, req.models)
    if result["status"] == "error":
        raise HTTPException(400, result["message"])
    return result

class TestModelRequest(BaseModel):
    model: str
    prompt: str = "Reply 'Hello from API!'"

@router.post("/providers/{provider}/test-model")
async def api_test_provider_model(provider: str, req: TestModelRequest):
    """Test a specific model."""
    from tubecli.extensions.cloud_api.extension import key_manager
    from tubecli.core.ai_generator import call_gemini, call_openai_compatible, call_claude
    
    prov = provider.lower()
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
            # 9Router uses OpenAI-compatible API on localhost:20128
            res = call_openai_compatible(req.model, key or "9router", req.prompt, base_url="http://localhost:20128/v1")
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
        resp = _req.get("http://localhost:20128/v1/models", headers=headers, timeout=3)
        if resp.status_code == 200:
            data = resp.json()
            models = []
            if isinstance(data, dict) and "data" in data:
                models = [m.get("id", m.get("name", "")) for m in data["data"] if isinstance(m, dict)]
            return {"running": True, "model_count": len(models), "models": models}
        return {"running": False, "model_count": 0, "models": []}
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

