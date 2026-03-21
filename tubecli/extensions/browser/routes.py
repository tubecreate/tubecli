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

# Note: psutil and requests are imported lazily inside handlers to avoid
# preventing route registration when these packages aren't installed.

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
    return {"instances": browser_process_manager.list_all()}

@router.get("/log/{profile}")
async def api_browser_log(profile: str):
    """Read latest log file for a browser profile instance."""
    from .process_manager import browser_process_manager
    # Find latest instance for this profile
    all_instances = browser_process_manager.list_all()
    instance = None
    for inst in reversed(all_instances):
        if inst.get("profile") == profile:
            instance = inst
            break
    
    if not instance:
        return {"error": "No instance found for this profile", "log": ""}
    
    log_file = instance.get("log_file", "")
    log_content = ""
    if log_file and os.path.exists(log_file):
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                log_content = f.read(5000)  # Last 5KB
        except Exception as e:
            log_content = f"Error reading log: {e}"
    else:
        log_content = f"Log file not found: {log_file}"
    
    return {
        "instance_id": instance.get("instance_id"),
        "status": instance.get("status"),
        "command": instance.get("command"),
        "log_file": log_file,
        "log": log_content,
        "debug": instance.get("debug", {}),
    }

@router.get("/engine/versions")
async def api_get_engine_versions():
    import json
    import os
    
    try:
        ext_dir = os.path.dirname(__file__)
        versions = []
        api_error = None
        
        # 1. Fetch versions from private API server (fast, no HEAD requests)
        private_api_url = "https://api.tubecreate.com/api/fingerprints/check_versions.php"
        try:
            import requests
            from tubecli.config import get_language
            lang = get_language()
            resp = requests.post(private_api_url, json={"lang": lang}, timeout=15)
            if resp.status_code == 200:
                private_data = resp.json()
                if private_data.get("success"):
                    for pv in private_data.get("versions", []):
                        pv_name = pv.get("browser_version")
                        if not pv_name or pv_name == "Unknown":
                            pv_name = pv.get("bas_version")
                        if not pv_name:
                            pv_name = "Unknown"
                            
                        versions.append({
                            "name": pv_name,
                            "browser_version": pv.get("browser_version", pv_name),
                            "bas_version": pv.get("bas_version", ""),
                            "downloaded": False,
                            "download_url": pv.get("download_url"),
                            "local_url": pv.get("local_url"),
                            "bablosoft_url": pv.get("bablosoft_url"),
                            "is_private": True,
                            "path": "-"
                        })
                else:
                    api_error = private_data.get("message", "API returned success=false")
            else:
                api_error = f"API returned status {resp.status_code}"
        except ImportError:
            api_error = "Python 'requests' module not installed. Run: pip install requests"
            print(f"[PrivateAPI] {api_error}")
        except Exception as e:
            api_error = f"API connection error: {str(e)}"
            print(f"[PrivateAPI] Error: {e}")

        # 2. Fallback hardcoded versions if API failed
        if not versions:
            fallback_versions = [
                {"bas_version": "29.8.1", "browser_version": "145.0.7632.46",
                 "download_url": "http://downloads.bablosoft.com/distr/FastExecuteScript64/29.8.1/FastExecuteScript.x64.zip"},
                {"bas_version": "29.7.0", "browser_version": "144.0.7559.60",
                 "download_url": "http://downloads.bablosoft.com/distr/FastExecuteScript64/29.7.0/FastExecuteScript.x64.zip"},
                {"bas_version": "29.5.0", "browser_version": "142.0.7444.60",
                 "download_url": "http://downloads.bablosoft.com/distr/FastExecuteScript64/29.5.0/FastExecuteScript.x64.zip"},
            ]
            for fv in fallback_versions:
                versions.append({
                    "name": fv["browser_version"],
                    "browser_version": fv["browser_version"],
                    "bas_version": fv["bas_version"],
                    "downloaded": False,
                    "download_url": fv["download_url"],
                    "is_private": False,
                    "is_fallback": True,
                    "path": "-"
                })

        # 3. Check local install status — data/script/{bas_version}/
        for v in versions:
            bas_ver = v.get("bas_version", "")
            if not bas_ver:
                continue
            
            script_dir = os.path.join(ext_dir, "data", "script", bas_ver)
            is_installed = False
            
            if os.path.isdir(script_dir):
                if any(os.path.isfile(os.path.join(script_dir, f)) for f in os.listdir(script_dir)):
                    is_installed = True
            
            v["downloaded"] = is_installed
            v["path"] = script_dir if is_installed else "-"
        
        # Sort: newest first
        versions.sort(key=lambda x: x.get("bas_version", ""), reverse=True)
        
        result = {"success": True, "versions": versions}
        if api_error and not any(v.get("is_private") for v in versions):
            result["warning"] = api_error
        return result
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "status": "error", "message": str(e), "error": str(e)}

@router.post("/engine/download/{version}")
async def api_download_engine(version: str, request: Request):
    ext_dir = os.path.dirname(__file__)
    
    try:
        body = await request.json()
    except:
        body = {}
    
    download_url = body.get("download_url", "")
    bas_version = body.get("bas_version") or version
    
    # Check if already downloading this version
    if version in download_processes:
        return {"status": "already_downloading", "version": version}
    
    # If no download_url provided, construct bablosoft URL
    if not download_url:
        download_url = f"http://downloads.bablosoft.com/distr/FastExecuteScript64/{bas_version}/FastExecuteScript.x64.zip"
    
    # ZIP saved to data/engine/, extract to data/script/
    target_dir = os.path.join(ext_dir, "data", "script", bas_version)
    progress_file = os.path.join(ext_dir, "data", "engine", f"{version}.progress.json")
    
    # Ensure directories exist
    os.makedirs(os.path.join(ext_dir, "data", "engine"), exist_ok=True)
    os.makedirs(target_dir, exist_ok=True)
    
    def write_progress(status, percent=0, error=""):
        import json as _json
        data = {"version": version, "status": status, "percent": percent}
        if error:
            data["error"] = error
        try:
            with open(progress_file, "w") as f:
                _json.dump(data, f, indent=2)
        except:
            pass
    
    # Build fallback bablosoft URL
    bablosoft_url = f"http://downloads.bablosoft.com/distr/FastExecuteScript64/{bas_version}/FastExecuteScript.x64.zip"
    
    def download_and_extract():
        import zipfile
        import tempfile
        import requests
        
        # Try local_url first, then fallback to bablosoft
        urls_to_try = []
        if download_url and download_url != bablosoft_url:
            urls_to_try.append(("local", download_url))
        urls_to_try.append(("bablosoft", bablosoft_url))
        
        for url_label, url in urls_to_try:
            try:
                write_progress("downloading", 3, f"Trying {url_label} server...")
                
                resp = requests.get(url, stream=True, timeout=300, verify=False)
                if resp.status_code != 200:
                    if url_label == "local":
                        write_progress("downloading", 3, f"Local server returned {resp.status_code}, switching to bablosoft...")
                        continue  # Try next URL
                    write_progress("error", 0, f"HTTP {resp.status_code} from {url}")
                    return
                
                total_size = int(resp.headers.get("content-length", 0))
                downloaded = 0
                
                write_progress("downloading", 5, f"Downloading from {url_label} server...")
                
                # Save to temp file
                tmp_zip = os.path.join(ext_dir, "data", "engine", f"{bas_version}.zip")
                with open(tmp_zip, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=1024 * 256):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total_size > 0:
                                pct = int((downloaded / total_size) * 80) + 5  # 5-85%
                                write_progress("downloading", min(pct, 85))
                
                write_progress("extracting", 90)
                
                # Extract ZIP
                try:
                    with zipfile.ZipFile(tmp_zip, "r") as zf:
                        zf.extractall(target_dir)
                except zipfile.BadZipFile:
                    try:
                        os.remove(tmp_zip)
                    except:
                        pass
                    if url_label == "local":
                        write_progress("downloading", 3, "Local file corrupt, switching to bablosoft...")
                        continue  # Try next URL
                    write_progress("error", 0, "Downloaded file is not a valid ZIP archive")
                    return
                
                # Clean up zip
                try:
                    os.remove(tmp_zip)
                except:
                    pass
                
                write_progress("completed", 100)
                return  # Success!
                
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                if url_label == "local":
                    write_progress("downloading", 3, f"Local server failed ({type(e).__name__}), switching to bablosoft...")
                    continue  # Try next URL
                write_progress("error", 0, f"Connection failed: {str(e)[:200]}")
                return
            except Exception as e:
                if url_label == "local":
                    write_progress("downloading", 3, f"Local error: {str(e)[:100]}, switching to bablosoft...")
                    continue  # Try next URL
                write_progress("error", 0, str(e)[:300])
                return
        
        write_progress("error", 0, "All download servers failed")
    
    # Run download in background thread
    def run_bg():
        download_processes[version] = True
        try:
            download_and_extract()
        finally:
            download_processes.pop(version, None)
    
    threading.Thread(target=run_bg, daemon=True).start()
    return {"status": "started", "version": version}

@router.post("/engine/cancel/{version}")
async def api_cancel_engine(version: str):
    if version in download_processes:
        proc = download_processes[version]
        try:
            import psutil
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
    is_running = version in download_processes
    
    if os.path.exists(progress_file):
        try:
            with open(progress_file, "r") as f:
                data = json.load(f)
                data["is_running"] = is_running
                return data
        except:
            return {"status": "downloading", "percent": 0, "is_running": is_running}
    
    return {"status": "unknown", "percent": 0, "is_running": is_running}
