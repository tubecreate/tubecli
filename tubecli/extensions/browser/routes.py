"""
Browser Extension — API routes.
"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional, List
import os
import json
import subprocess
import threading
import asyncio
import psutil
import requests

from .profile_manager import list_profiles, create_profile, get_profile, update_profile, delete_profile, get_fingerprint, reset_fingerprint

router = APIRouter(prefix="/api/v1/browser", tags=["browser"])

# Track download processes
download_processes = {}


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
            
            # 1. Discover versions from PRIVATE SERVER
            private_api_url = "https://api.tubecreate.com/api/fingerprints/check_versions.php"
            try:
                import requests
                resp = requests.get(private_api_url, timeout=5)
                if resp.status_code == 200:
                    private_data = resp.json()
                    if private_data.get("success"):
                        for pv in private_data.get("versions", []):
                            pv_name = pv.get("browser_version", "Unknown")
                            versions.append({
                                "name": pv_name,
                                "browser_version": pv_name,
                                "bas_version": pv.get("bas_version", ""),
                                "downloaded": False, # Will check local folder below
                                "download_url": pv.get("download_url"),
                                "is_private": True,
                                "path": "-"
                            })
            except Exception as e:
                print(f"[PrivateAPI] Error: {e}")

            # 2. Discover local BAS versions from AppData (fallback/local scan)
            bas_apps_path = os.path.join(os.environ.get("APPDATA", ""), "BrowserAutomationStudio", "apps")
            if os.path.isdir(bas_apps_path):
                for dir_name in os.listdir(bas_apps_path):
                    bas_ver_path = os.path.join(bas_apps_path, dir_name)
                    json_path = os.path.join(bas_ver_path, "browser_versions.json")
                    if os.path.isdir(bas_ver_path) and os.path.exists(json_path):
                        try:
                            with open(json_path, "r") as f:
                                bas_data = json.load(f)
                                for bv in bas_data:
                                    bv_name = bv.get("browser_version", "Unknown")
                                    # Update if already exists from API (mark as downloaded)
                                    existing = next((x for x in versions if x["name"] == bv_name), None)
                                    if existing:
                                        existing["downloaded"] = True
                                        existing["path"] = bas_ver_path
                                    else:
                                        versions.append({
                                            "name": bv_name,
                                            "browser_version": bv_name,
                                            "bas_version": bv.get("bas_version", ""),
                                            "downloaded": True,
                                            "path": bas_ver_path,
                                            "is_bas_app": True
                                        })
                        except: pass

            # 3. Add remote versions and check internal data/engine
            for v in raw_versions:
                ver_name = v.get("browser_version", "Unknown")
                bas_ver = v.get("bas_version", "")
                
                # Check if we already have this version
                existing = next((x for x in versions if x["name"] == ver_name), None)
                
                # Check local internal engine folder
                engine_dir = os.path.join(ext_dir, "data", "engine", bas_ver)
                is_installed = False
                if bas_ver and os.path.isdir(engine_dir):
                    if os.listdir(engine_dir):
                        is_installed = True
                
                if existing:
                    if is_installed:
                        existing["downloaded"] = True
                        existing["path"] = engine_dir
                else:
                    versions.append({
                        "name": ver_name,
                        "browser_version": ver_name,
                        "bas_version": bas_ver,
                        "downloaded": is_installed,
                        "path": engine_dir if is_installed else "-",
                        "is_bas_app": False
                    })
            
            # Sort: newest first
            versions.sort(key=lambda x: x.get("bas_version", ""), reverse=True)
            return {"success": True, "versions": versions}
        else:
            return {"success": False, "status": "error", "message": "No versions data found in output", "error": "No versions data found in output"}
            
    except Exception as e:
        return {"success": False, "status": "error", "message": str(e), "error": str(e)}

@router.post("/engine/download/{version}")
async def api_download_engine(version: str, request: Request):
    ext_dir = os.path.dirname(__file__)
    open_script = os.path.join(ext_dir, "open.js")
    
    # We run the download in a non-blocking way
    async def run_download_task():
        try:
            body = await request.json()
        except:
            body = {}
        
        download_url = body.get("download_url")
        
        args = ["node", open_script, "--download-version", version]
        if download_url:
            args.extend(["--download-url", download_url])
            
        proc = subprocess.Popen(args, cwd=ext_dir)
        download_processes[version] = proc
        proc.wait()
        if version in download_processes:
            download_processes.pop(version, None)

    threading.Thread(target=lambda: asyncio.run(run_download_task()), daemon=True).start()
    return {"status": "started", "version": version}

@router.post("/engine/cancel/{version}")
async def api_cancel_engine(version: str):
    if version in download_processes:
        proc = download_processes[version]
        try:
            parent = psutil.Process(proc.pid)
            for child in parent.children(recursive=True):
                child.terminate()
            parent.terminate()
        except:
            proc.terminate()
            
        download_processes.pop(version, None)
        return {"status": "cancelled"}
    return {"status": "not_running"}

@router.get("/engine/status/{version}")
async def api_engine_status(version: str):
    import os
    import json
    
    ext_dir = os.path.dirname(__file__)
    # Find bas_version from the name if needed, but UI sends the same name
    # We check if a .progress.json exists in data/engine/BAS_VERSION or just data/engine/
    # But bas_version is unknown here unless we fetch from engine/versions again.
    # For now, let's assume open.js writes to data/engine/{version}.progress.json
    
    progress_file = os.path.join(ext_dir, "data", "engine", f"{version}.progress.json")
    
    if os.path.exists(progress_file):
        try:
            with open(progress_file, "r") as f:
                data = json.load(f)
                return data
        except:
            return {"status": "downloading", "percent": 0}
            
    # Check if a folder already exists with that version (installed)
    # We might need to iterate through folders to find which one matches 'version'
    # For now, if no progress file, return downloading 0 or check if it's already in versions list
    return {"status": "downloading", "percent": 0}
