"""
Browser Extension — API routes.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List

router = APIRouter(prefix="/api/v1/browser", tags=["browser"])


class ProfileCreateRequest(BaseModel):
    name: str
    proxy: str = ""
    browser_version: str = "latest"
    version: Optional[str] = None  # Compatibility with UI sending 'version'
    tags: List[str] = ["Windows", "Chrome"]

class ProfileUpdateRequest(BaseModel):
    proxy: Optional[str] = None
    browser_version: Optional[str] = None
    version: Optional[str] = None # Compatibility with UI
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
    from .profile_manager import list_profiles
    return {"profiles": list_profiles()}

@router.post("/profiles")
async def api_create_profile(req: ProfileCreateRequest):
    from .profile_manager import create_profile
    try:
        # Map 'version' to 'browser_version' if needed
        version = req.version or req.browser_version
        profile = create_profile(req.name, proxy=req.proxy, browser_version=version, tags=req.tags)
        return {"status": "created", "profile": profile}
    except ValueError as e:
        raise HTTPException(409, str(e))

@router.get("/profiles/{name}")
async def api_get_profile(name: str):
    from .profile_manager import get_profile
    profile = get_profile(name)
    if not profile:
        raise HTTPException(404, f"Profile '{name}' not found")
    return profile

@router.put("/profiles/{name}")
async def api_update_profile(name: str, req: ProfileUpdateRequest):
    from .profile_manager import update_profile
    data = req.model_dump(exclude_none=True)
    if "version" in data and "browser_version" not in data:
        data["browser_version"] = data.pop("version")
        
    profile = update_profile(name, **data)
    if not profile:
        raise HTTPException(404, f"Profile '{name}' not found")
    return {"status": "updated", "profile": profile}

@router.delete("/profiles/{name}")
async def api_delete_profile(name: str):
    from .profile_manager import delete_profile
    if not delete_profile(name):
        raise HTTPException(404, f"Profile '{name}' not found")
    return {"status": "deleted"}

@router.get("/profiles/{name}/fingerprint")
async def api_get_fingerprint(name: str):
    from .profile_manager import get_fingerprint
    fp = get_fingerprint(name)
    if not fp:
        raise HTTPException(404, f"Fingerprint not found or failed to fetch for profile '{name}'")
    return fp

@router.post("/profiles/{name}/fingerprint/reset")
async def api_reset_fingerprint(name: str):
    from .profile_manager import reset_fingerprint
    if reset_fingerprint(name):
        return {"status": "reset", "profile": name}
    raise HTTPException(404, f"Fingerprint not found for profile '{name}'")


@router.post("/launch")
async def api_launch_browser(req: LaunchRequest):
    from .process_manager import browser_process_manager
    result = browser_process_manager.spawn(
        profile=req.profile, prompt=req.prompt, url=req.url, headless=req.headless, manual=req.manual
    )
    return result

@router.post("/stop")
async def api_stop_browser(req: StopRequest):
    from .process_manager import browser_process_manager
    if browser_process_manager.stop_by_profile(req.profile):
        return {"status": "stopped", "profile": req.profile}
    raise HTTPException(404, "No running browser for this profile")

@router.get("/status")
async def api_browser_status():
    from .process_manager import browser_process_manager
    return {"instances": browser_process_manager.list_running()}

@router.get("/engine/versions")
async def api_get_engine_versions():
    import subprocess
    import json
    import os
    
    try:
        ext_dir = os.path.dirname(__file__)
        open_script = os.path.join(ext_dir, "open.js")
        
        # Run node open.js --list-versions
        result = subprocess.run(
            ["node", open_script, "--list-versions"],
            capture_output=True,
            text=True,
            cwd=ext_dir,
            timeout=30
        )
        
        if result.returncode != 0:
            return {"success": False, "status": "error", "message": f"CLI error: {result.stderr}", "error": f"CLI error: {result.stderr}"}
            
        # Parse custom markers
        output = result.stdout
        start_marker = "__VERSIONS_START__"
        end_marker = "__VERSIONS_END__"
        
        if start_marker in output and end_marker in output:
            json_str = output.split(start_marker)[1].split(end_marker)[0].strip()
            raw_versions = json.loads(json_str)
            
            # Enrich with local status
            versions = []
            for v in raw_versions:
                ver_name = v.get("browser_version", "Unknown")
                bas_ver = v.get("bas_version", "")
                
                # Check local engine folder
                engine_dir = os.path.join(ext_dir, "data", "engine", bas_ver)
                is_installed = os.path.exists(engine_dir) and bas_ver != ""
                
                versions.append({
                    "name": ver_name,
                    "browser_version": ver_name,
                    "bas_version": bas_ver,
                    "downloaded": is_installed,
                    "path": engine_dir if is_installed else "-"
                })
            return {"success": True, "versions": versions}
        else:
            return {"success": False, "status": "error", "message": "No versions data found in output", "error": "No versions data found in output"}
            
    except Exception as e:
        return {"success": False, "status": "error", "message": str(e), "error": str(e)}
