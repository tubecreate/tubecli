"""
Browser Extension — API routes.
"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional, List, Any
import os
import json
import subprocess
import threading
import asyncio

# Note: psutil and requests are imported lazily inside handlers to avoid
# preventing route registration when these packages aren't installed.

from .profile_manager import list_profiles, create_profile, get_profile, update_profile, delete_profile, get_fingerprint, reset_fingerprint, refresh_fingerprint

router = APIRouter(prefix="/api/v1/browser", tags=["browser"])

# Track download processes
download_processes = {}


class ProfileCreateRequest(BaseModel):
    name: str
    proxy: str = ""
    browser_version: str = "latest"
    version: Optional[str] = None  # Compatibility with UI sending 'version'
    tags: List[str] = ["Windows", "Chrome"]
    window_size: Optional[dict] = None   # {"width": 1920, "height": 1080}
    chrome_version: Optional[str] = ""

class ProfileUpdateRequest(BaseModel):
    proxy: Optional[str] = None
    browser_version: Optional[str] = None
    version: Optional[str] = None # Compatibility with UI
    tags: Optional[List[str]] = None
    notes: Optional[str] = None
    google_account: Optional[Any] = None  # Can be raw string or dict
    window_size: Optional[dict] = None   # {"width": int, "height": int}
    chrome_version: Optional[str] = None

class LaunchRequest(BaseModel):
    profile: str
    prompt: str = ""
    url: str = ""
    headless: bool = False
    manual: bool = True
    ai_model: str = "qwen:latest"

class StopRequest(BaseModel):
    profile: str


@router.get("/profiles")
async def api_list_profiles():
    from .profile_manager import list_profiles
    profiles = await asyncio.to_thread(list_profiles)
    return {"profiles": profiles}

@router.post("/profiles")
async def api_create_profile(req: ProfileCreateRequest):
    from .profile_manager import create_profile
    try:
        # Map 'version' to 'browser_version' if needed
        version = req.version or req.browser_version
        profile = await asyncio.to_thread(
            create_profile,
            req.name,
            proxy=req.proxy,
            browser_version=version,
            tags=req.tags,
            window_size=req.window_size,
            chrome_version=req.chrome_version or "",
        )
        return {"status": "created", "profile": profile}
    except ValueError as e:
        raise HTTPException(409, str(e))

@router.get("/profiles/{name}")
async def api_get_profile(name: str):
    from .profile_manager import get_profile
    profile = await asyncio.to_thread(get_profile, name)
    if not profile:
        raise HTTPException(404, f"Profile '{name}' not found")
    return profile

@router.put("/profiles/{name}")
async def api_update_profile(name: str, req: ProfileUpdateRequest):
    from .profile_manager import update_profile
    data = req.model_dump(exclude_none=True)
    if "version" in data and "browser_version" not in data:
        data["browser_version"] = data.pop("version")
    
    # Parse google_account string -> JSON if needed
    if "google_account" in data and isinstance(data["google_account"], str):
        raw = data["google_account"].strip()
        if raw:
            # Split by pipe or tab
            parts = raw.split("|") if "|" in raw else raw.split("\t")
            parts = [p.strip() for p in parts if p.strip()]
            data["google_account"] = {
                "email": parts[0] if len(parts) > 0 else "",
                "password": parts[1] if len(parts) > 1 else "",
                "recoveryEmail": parts[2] if len(parts) > 2 else "",
                "twoFactorCodes": parts[3] if len(parts) > 3 else "",
            }
        else:
            data["google_account"] = None
    
    profile = await asyncio.to_thread(update_profile, name, **data)
    if not profile:
        raise HTTPException(404, f"Profile '{name}' not found")
    return {"status": "updated", "profile": profile}

@router.delete("/profiles/{name}")
async def api_delete_profile(name: str):
    from .profile_manager import delete_profile
    success = await asyncio.to_thread(delete_profile, name)
    if not success:
        raise HTTPException(404, f"Profile '{name}' not found")
    return {"status": "deleted"}

@router.get("/profiles/{name}/fingerprint")
async def api_get_fingerprint(name: str):
    import asyncio
    from .profile_manager import get_fingerprint
    fp = await asyncio.to_thread(get_fingerprint, name)
    if not fp:
        raise HTTPException(404, f"Fingerprint not found or failed to fetch for profile '{name}'")
    return fp

@router.post("/profiles/{name}/fingerprint/reset")
async def api_reset_fingerprint(name: str):
    from .profile_manager import reset_fingerprint
    success = await asyncio.to_thread(reset_fingerprint, name)
    if success:
        return {"status": "reset", "profile": name}
    raise HTTPException(404, f"Fingerprint not found for profile '{name}'")


@router.post("/profiles/{name}/fingerprint/refresh")
async def api_refresh_fingerprint(name: str):
    """Force-fetch a brand new fingerprint from the remote API, replacing any existing one."""
    import asyncio
    from .profile_manager import refresh_fingerprint
    try:
        # Run in thread pool — refresh_fingerprint uses blocking requests.get() with 8MB+ responses
        fp = await asyncio.to_thread(refresh_fingerprint, name)
        if fp:
            return {"status": "refreshed", "profile": name, "fingerprint_keys": list(fp.keys())[:5]}
        raise HTTPException(500, f"Failed to refresh fingerprint for profile '{name}'. API may be unavailable.")
    except HTTPException:
        raise
    except Exception as e:
        print(f"[refresh_fingerprint] Error: {e}")
        raise HTTPException(500, f"Failed to refresh fingerprint for profile '{name}': {str(e)}")


@router.get("/profiles/{name}/cookies")
async def api_get_cookies(name: str):
    """Get cookies.json content for a profile."""
    import os, json
    from .profile_manager import PROFILES_DIR
    cookie_path = os.path.join(PROFILES_DIR, name, "cookies.json")
    if not os.path.exists(cookie_path):
        return {"cookies": [], "count": 0}
    try:
        with open(cookie_path, "r", encoding="utf-8") as f:
            cookies = json.load(f)
        return {"cookies": cookies, "count": len(cookies) if isinstance(cookies, list) else 0}
    except Exception as e:
        raise HTTPException(500, f"Failed to read cookies: {e}")

@router.post("/profiles/{name}/cookies")
async def api_import_cookies(name: str, request: Request):
    """Import cookies.json for a profile."""
    import os, json
    from .profile_manager import PROFILES_DIR
    profile_path = os.path.join(PROFILES_DIR, name)
    if not os.path.isdir(profile_path):
        raise HTTPException(404, f"Profile '{name}' not found")
    try:
        body = await request.json()
        cookies = body.get("cookies", body) if isinstance(body, dict) else body
        if not isinstance(cookies, list):
            cookies = [cookies]
        cookie_path = os.path.join(profile_path, "cookies.json")
        with open(cookie_path, "w", encoding="utf-8") as f:
            json.dump(cookies, f, indent=2, ensure_ascii=False)
        return {"status": "imported", "count": len(cookies)}
    except Exception as e:
        raise HTTPException(500, f"Failed to import cookies: {e}")

@router.delete("/profiles/{name}/cookies")
async def api_delete_cookies(name: str):
    """Delete cookies.json for a profile."""
    import os
    from .profile_manager import PROFILES_DIR
    cookie_path = os.path.join(PROFILES_DIR, name, "cookies.json")
    if os.path.exists(cookie_path):
        os.remove(cookie_path)
        return {"status": "deleted"}
    return {"status": "not_found"}


@router.post("/launch")
async def api_launch_browser(req: LaunchRequest):
    from .process_manager import browser_process_manager
    result = browser_process_manager.spawn(
        profile=req.profile, prompt=req.prompt, url=req.url, headless=req.headless, manual=req.manual, ai_model=req.ai_model
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
    def _fetch():
        import json
        import os
        
        try:
            ext_dir = os.path.dirname(__file__)
            versions = []
            api_error = None
            
            # 1. Fetch versions from private API server (fast, no HEAD requests)
            private_api_url = "https://tubecli.zeabur.app/api/fingerprints/check_versions.php"
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

            # 2. Add local fallback versions if they are not in the list
            fallback_versions = [
                {"bas_version": "30.0.0", "browser_version": "147.0.7727.56",
                 "download_url": "http://downloads.bablosoft.com/distr/FastExecuteScript64/30.0.0/FastExecuteScript.x64.zip"},
                {"bas_version": "29.9.2", "browser_version": "146.0.7680.80",
                 "download_url": "http://downloads.bablosoft.com/distr/FastExecuteScript64/29.9.2/FastExecuteScript.x64.zip"},
                {"bas_version": "29.8.1", "browser_version": "145.0.7632.46",
                 "download_url": "http://downloads.bablosoft.com/distr/FastExecuteScript64/29.8.1/FastExecuteScript.x64.zip"},
                {"bas_version": "29.7.0", "browser_version": "144.0.7559.60",
                 "download_url": "http://downloads.bablosoft.com/distr/FastExecuteScript64/29.7.0/FastExecuteScript.x64.zip"},
                {"bas_version": "29.5.0", "browser_version": "142.0.7444.60",
                 "download_url": "http://downloads.bablosoft.com/distr/FastExecuteScript64/29.5.0/FastExecuteScript.x64.zip"},
            ]
            
            existing_bas_versions = set(v.get("bas_version") for v in versions)
            for fv in fallback_versions:
                if fv["bas_version"] not in existing_bas_versions:
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
            # plugin.setWorkingFolder(__dirname) in open.js makes plugin look here
            for v in versions:
                bas_ver = v.get("bas_version", "")
                if not bas_ver:
                    continue
                
                script_dir = os.path.join(ext_dir, "data", "script", bas_ver)
                is_installed = os.path.isdir(script_dir) and os.path.isfile(
                    os.path.join(script_dir, "FastExecuteScript.exe")
                )
                
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

    return await asyncio.to_thread(_fetch)

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
    
    # If no download_url provided, construct Security Browser URL
    if not download_url:
        download_url = f"http://downloads.bablosoft.com/distr/FastExecuteScript64/{bas_version}/FastExecuteScript.x64.zip"
    
    # Extract to data/script/ — plugin.setWorkingFolder(__dirname) in open.js
    # makes the plugin look here for engines
    target_dir = os.path.join(ext_dir, "data", "script", bas_version)
    progress_file = os.path.join(ext_dir, "data", "engine", f"{version}.progress.json")
    
    # Ensure directories exist
    # CRITICAL: We MUST create the data/engine/{bas_version} directory
    # The plugin checks for its existence to skip downloading
    engine_dir = os.path.join(ext_dir, "data", "engine", bas_version)
    os.makedirs(engine_dir, exist_ok=True)
    os.makedirs(target_dir, exist_ok=True)
    
    def write_progress(status, percent=0, error=""):
        import json as _json
        data = {"version": version, "status": status, "percent": percent}
        if error:
            data["error"] = error
        try:
            tmp_progress = progress_file + ".tmp"
            with open(tmp_progress, "w") as f:
                _json.dump(data, f, indent=2)
            os.replace(tmp_progress, progress_file)
        except:
            pass
    
    # Build fallback Security Browser URL
    fallback_url = f"http://downloads.bablosoft.com/distr/FastExecuteScript64/{bas_version}/FastExecuteScript.x64.zip"
    
    def download_and_extract():
        import zipfile
        import requests
        
        # Try local_url first, then fallback to Security Browser CDN
        urls_to_try = []
        if download_url and download_url != fallback_url:
            urls_to_try.append(("local", download_url))
        urls_to_try.append(("security_browser", fallback_url))
        
        for url_label, url in urls_to_try:
            try:
                write_progress("downloading", 3, f"Trying {url_label} server...")
                
                resp = requests.get(url, stream=True, timeout=300, verify=False)
                if resp.status_code != 200:
                    if url_label == "local":
                        write_progress("downloading", 3, f"Local server returned {resp.status_code}, switching to Security Browser CDN...")
                        continue
                    write_progress("error", 0, f"HTTP {resp.status_code} from {url}")
                    return
                
                total_size = int(resp.headers.get("content-length", 0))
                downloaded = 0
                
                write_progress("downloading", 5, f"Downloading from {url_label} server...")
                
                tmp_zip = os.path.join(ext_dir, "data", "engine", f"{bas_version}.zip")
                with open(tmp_zip, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=1024 * 256):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total_size > 0:
                                pct = int((downloaded / total_size) * 80) + 5
                                write_progress("downloading", min(pct, 85))
                
                write_progress("extracting", 90)
                
                try:
                    with zipfile.ZipFile(tmp_zip, "r") as zf:
                        zf.extractall(target_dir)
                except zipfile.BadZipFile:
                    try:
                        os.remove(tmp_zip)
                    except:
                        pass
                    if url_label == "local":
                        write_progress("downloading", 3, "Local file corrupt, switching to Security Browser CDN...")
                        continue
                    write_progress("error", 0, "Downloaded file is not a valid ZIP archive")
                    return
                
                try:
                    os.remove(tmp_zip)
                except:
                    pass
                
                write_progress("completed", 100)
                return
                
            except Exception as e:
                if url_label == "local":
                    write_progress("downloading", 3, f"Local server failed, switching to Security Browser CDN...")
                    continue
                write_progress("error", 0, str(e)[:300])
                return
        
        write_progress("error", 0, "All download servers failed")
    
    # Write initial progress immediately to prevent startup flicker
    write_progress("downloading", 0, "Initializing download...")
    
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


@router.get("/2fa")
async def api_get_2fa(secret: str = ""):
    """Generate a live 6-digit TOTP code from a base32 secret."""
    if not secret:
        raise HTTPException(400, "Missing 'secret' query parameter")
    try:
        import pyotp
        import time
        # Clean up the secret: remove spaces, uppercase
        clean_secret = secret.replace(" ", "").upper()
        totp = pyotp.TOTP(clean_secret)
        code = totp.now()
        remaining = 30 - (int(time.time()) % 30)
        return {"code": code, "time": int(time.time()), "remaining": remaining}
    except Exception as e:
        raise HTTPException(500, f"Failed to generate TOTP: {str(e)}")

# ── Chrome Extension Communication ──

import time

# Store connected extensions: token -> {"last_seen": float, "queue": list, "results": dict}
browser_extensions = {}

class BrowserCommandResult(BaseModel):
    token: str
    commandId: str
    action: str
    success: bool
    result: Optional[Any] = None
    error: Optional[str] = None

class RegisterRequest(BaseModel):
    token: str
    userAgent: str
    timestamp: int

@router.post("/register")
async def api_register_browser(req: RegisterRequest):
    browser_extensions[req.token] = {"last_seen": time.time(), "queue": [], "results": {}}
    return {"success": True}

@router.delete("/extensions/{token}")
async def api_disconnect_browser(token: str):
    if token in browser_extensions:
        del browser_extensions[token]
    return {"success": True}

@router.get("/extensions")
async def api_get_browser_extensions():
    now = time.time()
    active = []
    # Clean up dead extensions (inactive > 60s)
    for token, data in list(browser_extensions.items()):
        if now - data["last_seen"] < 60:
            active.append({"token": token, "last_seen": data["last_seen"]})
        else:
            del browser_extensions[token]
    return {"extensions": active}

@router.get("/commands/{token}")
async def api_get_commands(token: str):
    if token not in browser_extensions:
        browser_extensions[token] = {"last_seen": time.time(), "queue": [], "results": {}}
    else:
        browser_extensions[token]["last_seen"] = time.time()
        
    if browser_extensions[token]["queue"]:
        cmd = browser_extensions[token]["queue"].pop(0)
        return {"command": cmd}
    return {"command": None}

@router.post("/commands/{token}")
async def api_post_command(token: str, command: dict):
    if token not in browser_extensions:
        browser_extensions[token] = {"last_seen": time.time(), "queue": [], "results": {}}
    
    if "id" not in command:
        import uuid
        command["id"] = str(uuid.uuid4())[:8]
        
    browser_extensions[token]["queue"].append(command)
    return {"success": True, "command_id": command["id"]}

@router.post("/result")
async def api_post_result(result: BrowserCommandResult):
    token = result.token
    if token in browser_extensions:
        browser_extensions[token]["last_seen"] = time.time()
        browser_extensions[token]["results"][result.commandId] = result.model_dump()
        return {"success": True}
    return {"success": False, "error": "Token not found"}

@router.get("/result/{token}/{command_id}")
async def api_get_result(token: str, command_id: str):
    if token in browser_extensions:
        if command_id in browser_extensions[token]["results"]:
            res = browser_extensions[token]["results"].pop(command_id) # Consume result
            return {"ready": True, **res}
    return {"ready": False}

