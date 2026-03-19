"""
Cloud API Plugin — API routes.
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
    from tubecli.plugins.cloud_api.plugin import key_manager
    return {"providers": key_manager.list_providers()}


@router.get("/keys")
async def api_list_keys(provider: Optional[str] = None):
    """List stored API keys (masked)."""
    from tubecli.plugins.cloud_api.plugin import key_manager
    return {"keys": key_manager.list_keys(provider)}


@router.post("/keys")
async def api_add_key(req: AddKeyRequest):
    """Add an API key for a cloud provider."""
    from tubecli.plugins.cloud_api.plugin import key_manager
    result = key_manager.add_key(req.provider, req.api_key, req.label)
    if result["status"] == "error":
        raise HTTPException(400, result["message"])
    return result


@router.delete("/keys")
async def api_remove_key(req: RemoveKeyRequest):
    """Remove an API key."""
    from tubecli.plugins.cloud_api.plugin import key_manager
    result = key_manager.remove_key(req.provider, req.label)
    if result["status"] == "error":
        raise HTTPException(404, result["message"])
    return result


@router.post("/keys/test")
async def api_test_key(req: TestKeyRequest):
    """Test if an API key is valid."""
    from tubecli.plugins.cloud_api.plugin import key_manager
    return key_manager.test_key(req.provider, req.label)


@router.get("/keys/{provider}/active")
async def api_get_active_key(provider: str):
    """Get the active API key for a provider (for internal use by agents)."""
    from tubecli.plugins.cloud_api.plugin import key_manager
    key = key_manager.get_active_key(provider)
    if not key:
        raise HTTPException(404, f"No active key for provider '{provider}'")
    # Return masked for security
    masked = key[:6] + "..." + key[-4:] if len(key) > 10 else "***"
    return {"provider": provider, "has_key": True, "masked_key": masked}
