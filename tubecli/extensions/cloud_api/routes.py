"""
Cloud API Extension — API routes.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/api/v1/cloud-api", tags=["cloud-api"])


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
    
    key = key_manager.get_active_key(provider)
    if not key:
        raise HTTPException(400, f"No active key configured for {provider}")
        
    try:
        prov = provider.lower()
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
        else:
            raise HTTPException(400, f"Direct testing for {provider} not supported.")
            
        return {"status": "success", "response": res}
    except Exception as e:
        raise HTTPException(500, str(e))
