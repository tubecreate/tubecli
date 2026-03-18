"""
Browser Plugin — API routes.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List

router = APIRouter(prefix="/api/v1/browser", tags=["browser"])


class ProfileCreateRequest(BaseModel):
    name: str
    proxy: str = ""
    tags: List[str] = ["Windows", "Chrome"]

class ProfileUpdateRequest(BaseModel):
    proxy: Optional[str] = None
    tags: Optional[List[str]] = None
    notes: Optional[str] = None

class LaunchRequest(BaseModel):
    profile: str
    prompt: str = ""
    url: str = ""
    headless: bool = False
    manual: bool = True

class StopRequest(BaseModel):
    profile: str


@router.get("/profiles")
async def api_list_profiles():
    from tubecli.plugins.browser.profile_manager import list_profiles
    return {"profiles": list_profiles()}

@router.post("/profiles")
async def api_create_profile(req: ProfileCreateRequest):
    from tubecli.plugins.browser.profile_manager import create_profile
    try:
        profile = create_profile(req.name, proxy=req.proxy, tags=req.tags)
        return {"status": "created", "profile": profile}
    except ValueError as e:
        raise HTTPException(409, str(e))

@router.get("/profiles/{name}")
async def api_get_profile(name: str):
    from tubecli.plugins.browser.profile_manager import get_profile
    profile = get_profile(name)
    if not profile:
        raise HTTPException(404, f"Profile '{name}' not found")
    return profile

@router.put("/profiles/{name}")
async def api_update_profile(name: str, req: ProfileUpdateRequest):
    from tubecli.plugins.browser.profile_manager import update_profile
    profile = update_profile(name, **req.model_dump(exclude_none=True))
    if not profile:
        raise HTTPException(404, f"Profile '{name}' not found")
    return {"status": "updated", "profile": profile}

@router.delete("/profiles/{name}")
async def api_delete_profile(name: str):
    from tubecli.plugins.browser.profile_manager import delete_profile
    if not delete_profile(name):
        raise HTTPException(404, f"Profile '{name}' not found")
    return {"status": "deleted"}

@router.get("/profiles/{name}/fingerprint")
async def api_get_fingerprint(name: str):
    from tubecli.plugins.browser.profile_manager import get_fingerprint
    fp = get_fingerprint(name)
    if not fp:
        raise HTTPException(404, f"Fingerprint not found or failed to fetch for profile '{name}'")
    return fp

@router.post("/profiles/{name}/fingerprint/reset")
async def api_reset_fingerprint(name: str):
    from tubecli.plugins.browser.profile_manager import reset_fingerprint
    if reset_fingerprint(name):
        return {"status": "reset", "profile": name}
    raise HTTPException(404, f"Fingerprint not found for profile '{name}'")


@router.post("/launch")
async def api_launch_browser(req: LaunchRequest):
    from tubecli.plugins.browser.process_manager import browser_process_manager
    result = browser_process_manager.spawn(
        profile=req.profile, prompt=req.prompt, url=req.url, headless=req.headless, manual=req.manual
    )
    return result

@router.post("/stop")
async def api_stop_browser(req: StopRequest):
    from tubecli.plugins.browser.process_manager import browser_process_manager
    if browser_process_manager.stop_by_profile(req.profile):
        return {"status": "stopped", "profile": req.profile}
    raise HTTPException(404, "No running browser for this profile")

@router.get("/status")
async def api_browser_status():
    from tubecli.plugins.browser.process_manager import browser_process_manager
    return {"instances": browser_process_manager.list_running()}
