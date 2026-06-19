"""
Browser Extension — API routes.
"""
from fastapi import APIRouter, HTTPException, Request, File, UploadFile
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
    facebook_account: Optional[Any] = None
    tiktok_account: Optional[Any] = None
    x_account: Optional[Any] = None
    discord_account: Optional[Any] = None
    telegram_account: Optional[Any] = None
    window_size: Optional[dict] = None   # {"width": int, "height": int}
    chrome_version: Optional[str] = None

class LaunchRequest(BaseModel):
    profile: str
    prompt: str = ""
    url: str = "https://google.com"
    headless: bool = False
    manual: bool = True
    ai_model: str = "qwen:latest"
    context: Optional[dict] = None

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
    
    # Parse account strings -> JSON if needed
    for act_key in ("google_account", "facebook_account", "tiktok_account", "x_account", "discord_account", "telegram_account"):
        if act_key in data and isinstance(data[act_key], str):
            raw = data[act_key].strip()
            if raw:
                # Split by pipe or tab
                parts = raw.split("|") if "|" in raw else raw.split("\t")
                parts = [p.strip() for p in parts if p.strip()]
                data[act_key] = {
                    "email": parts[0] if len(parts) > 0 else "",
                    "password": parts[1] if len(parts) > 1 else "",
                    "recoveryEmail": parts[2] if len(parts) > 2 else "",
                    "twoFactorCodes": parts[3] if len(parts) > 3 else "",
                }
            else:
                data[act_key] = None
    
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


_launching_profiles = set()
_launching_lock = asyncio.Lock()

def is_profile_running(profile_name: str) -> bool:
    from .process_manager import browser_process_manager
    # Check normal running profiles
    for inst in browser_process_manager.list_all():
        if inst.get("profile") == profile_name and inst.get("status") == "running":
            return True
            
    # Check preview running profiles
    dead_sessions = []
    is_running = False
    for session_id, info in list(_preview_processes.items()):
        proc = info.get("proc")
        if proc and proc.poll() is not None:
            dead_sessions.append(session_id)
        elif info.get("profile") == profile_name:
            is_running = True
            
    for session_id in dead_sessions:
        _preview_processes.pop(session_id, None)
        
    return is_running

@router.post("/launch")
async def api_launch_browser(req: LaunchRequest):
    async with _launching_lock:
        if req.profile in _launching_profiles or is_profile_running(req.profile):
            raise HTTPException(400, f"Profile '{req.profile}' is already running or opening.")
        _launching_profiles.add(req.profile)
        
    try:
        from .process_manager import browser_process_manager
        result = browser_process_manager.spawn(
            profile=req.profile, prompt=req.prompt, url=req.url, headless=req.headless, manual=req.manual, ai_model=req.ai_model, context=req.context
        )
        return result
    finally:
        async with _launching_lock:
            _launching_profiles.discard(req.profile)

@router.post("/stop")
async def api_stop_browser(req: StopRequest):
    from .process_manager import browser_process_manager
    stopped = False
    
    # 1. Stop normal browser process
    if browser_process_manager.stop_by_profile(req.profile):
        stopped = True
        
    # 2. Stop preview browser process
    dead_sessions = []
    for session_id, info in list(_preview_processes.items()):
        if info.get("profile") == req.profile:
            proc = info.get("proc")
            if proc:
                try:
                    import platform
                    import subprocess
                    if platform.system() == "Windows":
                        subprocess.run(
                            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                            capture_output=True, timeout=5
                        )
                    else:
                        proc.terminate()
                except Exception:
                    pass
            _preview_processes.pop(session_id, None)
            stopped = True
            
    if stopped:
        return {"status": "stopped", "profile": req.profile}
    raise HTTPException(404, f"No running browser for profile '{req.profile}'")

@router.get("/status")
async def api_browser_status():
    from .process_manager import browser_process_manager
    instances = browser_process_manager.list_all()
    
    # Add preview processes to the instances list so the frontend knows they are running
    dead_sessions = []
    for session_id, info in list(_preview_processes.items()):
        proc = info.get("proc")
        if proc and proc.poll() is not None:
            dead_sessions.append(session_id)
        else:
            exists = False
            for inst in instances:
                if inst.get("profile") == info.get("profile") and inst.get("status") == "running":
                    exists = True
                    break
            if not exists:
                instances.append({
                    "instance_id": session_id,
                    "profile": info.get("profile"),
                    "status": "running",
                    "manual": True,
                    "is_preview": True
                })
                
    for session_id in dead_sessions:
        _preview_processes.pop(session_id, None)
        
    return {"instances": instances}

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
                                
                            display_name = pv_name
                            if not display_name.startswith("ShardX") and not display_name.startswith("BAS"):
                                display_name = f"BAS {display_name}"
                            versions.append({
                                "name": display_name,
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
                {"bas_version": "30.1.0", "browser_version": "148.0.7778.97",
                 "download_url": "http://downloads.bablosoft.com/distr/FastExecuteScript64/30.1.0/FastExecuteScript.x64.zip"},
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
                    display_name = fv["browser_version"]
                    if not display_name.startswith("ShardX") and not display_name.startswith("BAS"):
                        display_name = f"BAS {display_name}"
                    versions.append({
                        "name": display_name,
                        "browser_version": fv["browser_version"],
                        "bas_version": fv["bas_version"],
                        "downloaded": False,
                        "download_url": fv["download_url"],
                        "is_private": False,
                        "is_fallback": True,
                        "path": "-"
                    })

            # 2b. Add ShardX versions (for ShardBrowser compatibility)
            shardx_versions = [
                {"bas_version": "ShardX-148.0.7778.97", "browser_version": "ShardX 148.0.7778.97", "download_url": ""},
                {"bas_version": "ShardX-148.0.7778.216", "browser_version": "ShardX 148.0.7778.216", "download_url": ""},
            ]
            for sv in shardx_versions:
                versions.append({
                    "name": sv["browser_version"],
                    "browser_version": sv["browser_version"],
                    "bas_version": sv["bas_version"],
                    "downloaded": False,
                    "download_url": sv["download_url"],
                    "is_private": False,
                    "is_fallback": True,
                    "is_shardx": True,
                    "path": "-"
                })

            # 3. Check local install status — data/script/{bas_version}/
            # plugin.setWorkingFolder(__dirname) in open.js makes plugin look here
            for v in versions:
                bas_ver = v.get("bas_version", "")
                if not bas_ver:
                    continue
                
                if v.get("is_shardx"):
                    # Check ShardX local installation in AppData
                    version_num = bas_ver.replace("ShardX-", "")
                    appdata = os.environ.get("APPDATA")
                    is_installed = False
                    chrome_path = ""
                    if appdata:
                        # Path: %APPDATA%/shardx-launcher/runtime/engines/<version>/ShardX-Windows-<version>/chrome.exe
                        chrome_path = os.path.join(appdata, "shardx-launcher", "runtime", "engines", version_num, f"ShardX-Windows-{version_num}", "chrome.exe")
                        is_installed = os.path.isfile(chrome_path)
                        
                        # Fallback check for flat layout
                        if not is_installed:
                            chrome_path_alt = os.path.join(appdata, "shardx-launcher", "runtime", "engines", version_num, "chrome.exe")
                            is_installed = os.path.isfile(chrome_path_alt)
                            if is_installed:
                                chrome_path = chrome_path_alt
                        
                        # Fallback check for Windows folder without version
                        if not is_installed:
                            chrome_path_alt2 = os.path.join(appdata, "shardx-launcher", "runtime", "engines", version_num, "ShardX-Windows", "chrome.exe")
                            is_installed = os.path.isfile(chrome_path_alt2)
                            if is_installed:
                                chrome_path = chrome_path_alt2
                                
                    v["downloaded"] = is_installed
                    v["path"] = os.path.dirname(chrome_path) if is_installed else "-"
                else:
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
    version = version.replace("BAS ", "").replace("BAS-", "").strip()
    
    try:
        body = await request.json()
    except:
        body = {}
    
    # Check if already downloading this version
    if version in download_processes:
        return {"status": "already_downloading", "version": version}
    
    progress_file = os.path.join(ext_dir, "data", "engine", f"{version}.progress.json")
    os.makedirs(os.path.dirname(progress_file), exist_ok=True)
    
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
    
    # Write initial progress immediately to prevent startup flicker
    write_progress("downloading", 0, "Initializing download...")
    
    if version.startswith("ShardX-"):
        version_num = version.replace("ShardX-", "").replace("ShardX ", "").strip()
        appdata = os.environ.get("APPDATA")
        if not appdata:
            appdata = os.path.expanduser("~\\AppData\\Roaming")
        target_dir = os.path.join(appdata, "shardx-launcher", "runtime", "engines", version_num)
        os.makedirs(target_dir, exist_ok=True)
        
        def download_and_extract_shardx():
            import zipfile
            import requests
            
            url = f"https://cf-r2-worker.tubecli.workers.dev/ShardX-Windows-{version_num}.zip"
            try:
                write_progress("downloading", 3, f"Connecting to Cloudflare R2 worker...")
                
                resp = requests.get(url, stream=True, timeout=300, verify=False)
                if resp.status_code != 200:
                    write_progress("error", 0, f"HTTP {resp.status_code} from {url}")
                    return
                
                total_size = int(resp.headers.get("content-length", 0))
                downloaded = 0
                
                write_progress("downloading", 5, "Downloading ShardX engine...")
                
                tmp_zip = os.path.join(ext_dir, "data", "engine", f"{version}.zip")
                with open(tmp_zip, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=1024 * 256):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total_size > 0:
                                pct = int((downloaded / total_size) * 80) + 5
                                write_progress("downloading", min(pct, 85))
                
                write_progress("extracting", 90, "Extracting ShardX engine...")
                
                try:
                    with zipfile.ZipFile(tmp_zip, "r") as zf:
                        zf.extractall(target_dir)
                except zipfile.BadZipFile:
                    try:
                        os.remove(tmp_zip)
                    except:
                        pass
                    write_progress("error", 0, "Downloaded ShardX zip file is corrupt")
                    return
                
                try:
                    os.remove(tmp_zip)
                except:
                    pass
                
                write_progress("completed", 100)
                return
                
            except Exception as e:
                write_progress("error", 0, f"Download failed: {str(e)[:300]}")
                return
        
        def run_bg_shardx():
            download_processes[version] = True
            try:
                download_and_extract_shardx()
            finally:
                download_processes.pop(version, None)
        
        threading.Thread(target=run_bg_shardx, daemon=True).start()
        return {"status": "started", "version": version}

    download_url = body.get("download_url", "")
    bas_version = body.get("bas_version") or version
    
    # If no download_url provided, construct Security Browser URL
    if not download_url:
        download_url = f"http://downloads.bablosoft.com/distr/FastExecuteScript64/{bas_version}/FastExecuteScript.x64.zip"
    
    # Extract to data/script/ — plugin.setWorkingFolder(__dirname) in open.js
    # makes the plugin look here for engines
    target_dir = os.path.join(ext_dir, "data", "script", bas_version)
    
    # Ensure directories exist
    # CRITICAL: We MUST create the data/engine/{bas_version} directory
    # The plugin checks for its existence to skip downloading
    engine_dir = os.path.join(ext_dir, "data", "engine", bas_version)
    os.makedirs(engine_dir, exist_ok=True)
    os.makedirs(target_dir, exist_ok=True)
    
    # Build fallback Security Browser URL
    fallback_url = f"http://downloads.bablosoft.com/distr/FastExecuteScript64/{bas_version}/FastExecuteScript.x64.zip"
    
    def download_and_extract():
        import zipfile
        import requests
        
        # Try local_url first, then Cloudflare R2 proxy, then fallback to Bablosoft
        urls_to_try = []
        if download_url and download_url != fallback_url:
            urls_to_try.append(("local", download_url))
            
        # Cloudflare R2 proxy worker domain (uses user's workers.dev subdomain)
        cf_subdomain = "tubecli"
        cf_proxy_url = f"https://cf-r2-worker.{cf_subdomain}.workers.dev/distr/FastExecuteScript64/{bas_version}/FastExecuteScript.x64.zip"
        urls_to_try.append(("cloudflare_r2", cf_proxy_url))
        
        urls_to_try.append(("security_browser", fallback_url))
        
        for url_label, url in urls_to_try:
            try:
                write_progress("downloading", 3, f"Trying {url_label} server...")
                
                resp = requests.get(url, stream=True, timeout=300, verify=False)
                if resp.status_code != 200:
                    if url_label == "local":
                        write_progress("downloading", 3, f"Local server returned {resp.status_code}, switching to Cloudflare R2 proxy...")
                        continue
                    elif url_label == "cloudflare_r2":
                        write_progress("downloading", 3, f"Cloudflare R2 proxy returned {resp.status_code}, switching to Security Browser CDN...")
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
                        write_progress("downloading", 3, "Local file corrupt, switching to Cloudflare R2 proxy...")
                        continue
                    elif url_label == "cloudflare_r2":
                        write_progress("downloading", 3, "Cloudflare R2 file corrupt, switching to Security Browser CDN...")
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
                    write_progress("downloading", 3, f"Local server failed, switching to Cloudflare R2 proxy...")
                    continue
                elif url_label == "cloudflare_r2":
                    write_progress("downloading", 3, f"Cloudflare R2 proxy failed, switching to Security Browser CDN...")
                    continue
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
    version = version.replace("BAS ", "").replace("BAS-", "").strip()
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
    version = version.replace("BAS ", "").replace("BAS-", "").strip()
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


# ── Browser Preview (WebSocket & Canvas proxy) ──

import logging
_preview_processes = {}
preview_logger = logging.getLogger("Browser.Preview")

@router.post("/preview/launch")
async def launch_preview(request: Request):
    """Launch a browser for preview/element picking."""
    body = await request.json()
    profile = body.get("profile", "")
    url = body.get("url", "https://google.com")
    if not url or url == "about:blank":
        url = "https://google.com"

    async with _launching_lock:
        if profile in _launching_profiles or is_profile_running(profile):
            raise HTTPException(400, f"Profile '{profile}' is already running or opening.")
        _launching_profiles.add(profile)

    try:
        ext_dir = os.path.dirname(os.path.abspath(__file__))
        preview_path = os.path.join(ext_dir, "preview_server.cjs")

        # Find available port
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("", 0))
        port = sock.getsockname()[1]
        sock.close()

        # Build environment and NODE_PATH
        env = os.environ.copy()
        browser_ext_nm = os.path.join(ext_dir, "node_modules")
        if os.path.isdir(browser_ext_nm):
            existing = env.get("NODE_PATH", "")
            env["NODE_PATH"] = browser_ext_nm + (";" + existing if existing else "")

        from .profile_manager import PROFILES_DIR
        proc = subprocess.Popen(
            ["node", preview_path, "--profile", profile or "default",
             "--url", url, "--port", str(port),
             "--profiles-dir", PROFILES_DIR],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            cwd=ext_dir, encoding="utf-8", errors="replace",
            env=env,
        )
        
        import threading
        def log_proc_output(p, name):
            try:
                for line in p.stdout:
                    print(f"[PreviewServer][{name}] {line.rstrip()}", flush=True)
            except Exception as e:
                print(f"[PreviewServer][{name}] Error reading stdout: {e}", flush=True)
            finally:
                try: p.stdout.close()
                except: pass
                
        t = threading.Thread(target=log_proc_output, args=(proc, profile), daemon=True)
        t.start()

        session_id = f"preview_{int(time.time())}"
        _preview_processes[session_id] = {"proc": proc, "port": port, "profile": profile}
        return {"status": "launched", "session_id": session_id, "port": port}
    finally:
        async with _launching_lock:
            _launching_profiles.discard(profile)

@router.post("/preview/stop")
async def stop_preview(request: Request):
    body = await request.json()
    session_id = body.get("session_id", "")
    info = _preview_processes.pop(session_id, None)
    if info:
        try:
            # Kill process tree on Windows/Linux
            import platform
            proc = info["proc"]
            if platform.system() == "Windows":
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    capture_output=True, timeout=5
                )
            else:
                proc.terminate()
        except Exception:
            pass
        return {"status": "stopped"}
    return {"status": "not_found"}

from fastapi import WebSocket, WebSocketDisconnect

@router.websocket("/preview/ws/{port}")
async def ws_preview_proxy(websocket: WebSocket, port: int):
    """Proxy WebSocket connection to the local preview server."""
    await websocket.accept()
    preview_logger.info(f"[WS Proxy] Client connected, proxying to localhost:{port}")
    
    local_ws = None
    try:
        import aiohttp
        session = aiohttp.ClientSession()
        
        # Retry connection to local preview server up to 20 times (10 seconds)
        retries = 20
        for attempt in range(retries):
            try:
                local_ws = await session.ws_connect(f"http://localhost:{port}", timeout=5)
                break
            except (aiohttp.ClientConnectorError, aiohttp.WSServerHandshakeError) as e:
                if attempt == retries - 1:
                    preview_logger.error(f"[WS Proxy] Failed to connect to localhost:{port} after {retries} attempts: {e}")
                    raise e
                await asyncio.sleep(0.5)
                
        preview_logger.info(f"[WS Proxy] Connected to local preview server on port {port}")
        
        async def forward_to_local():
            """Client → Local preview server"""
            try:
                while True:
                    data = await websocket.receive_text()
                    await local_ws.send_str(data)
            except (WebSocketDisconnect, Exception):
                pass
        
        async def forward_to_client():
            """Local preview server → Client"""
            try:
                async for msg in local_ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        await websocket.send_text(msg.data)
                    elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                        break
            except Exception:
                pass
        
        async def heartbeat():
            """Keep connection alive through reverse proxies"""
            try:
                while True:
                    await asyncio.sleep(15)
                    try:
                        await local_ws.ping()
                    except Exception:
                        break
            except asyncio.CancelledError:
                pass
        
        done, pending = await asyncio.wait(
            [asyncio.create_task(forward_to_local()),
             asyncio.create_task(forward_to_client()),
             asyncio.create_task(heartbeat())],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
    except ImportError:
        preview_logger.error("[WS Proxy] aiohttp not installed.")
        try:
            await websocket.close(code=1011, reason="aiohttp not installed on server")
        except Exception:
            pass
    except Exception as e:
        preview_logger.error(f"[WS Proxy] Error: {e}")
        try:
            await websocket.close(code=1011, reason=str(e)[:120])
        except Exception:
            pass
    finally:
        if local_ws:
            await local_ws.close()
            await session.close()

@router.get("/preview/screenshot/{port}")
async def proxy_screenshot(port: int):
    """Proxy screenshot from local preview server for remote access."""
    import asyncio
    try:
        import requests as _requests
        resp = await asyncio.to_thread(
            _requests.get, f"http://localhost:{port}/screenshot", timeout=10
        )
        if resp.status_code == 200:
            from fastapi.responses import Response
            return Response(content=resp.content, media_type="image/jpeg")
    except Exception as e:
        preview_logger.error(f"[Screenshot Proxy] Error: {e}")
    raise HTTPException(502, "Preview server unavailable")


@router.post("/preview/upload/{port}")
async def api_preview_upload_files(port: int, files: List[UploadFile] = File(...)):
    """Upload files for the file chooser dialog of browser at port."""
    import uuid
    import shutil
    import requests
    
    ext_dir = os.path.dirname(os.path.abspath(__file__))
    temp_dir = os.path.join(ext_dir, "data", "temp_uploads")
    os.makedirs(temp_dir, exist_ok=True)
    
    # Create unique directory for this upload batch
    upload_id = str(uuid.uuid4())
    batch_dir = os.path.join(temp_dir, upload_id)
    os.makedirs(batch_dir, exist_ok=True)
    
    file_paths = []
    try:
        for file in files:
            safe_filename = os.path.basename(file.filename)
            dest_path = os.path.join(batch_dir, safe_filename)
            
            with open(dest_path, "wb") as buffer:
                while chunk := await file.read(1024 * 1024):
                    buffer.write(chunk)
            file_paths.append(dest_path)
            
        node_url = f"http://localhost:{port}/upload-files"
        response = await asyncio.to_thread(
            requests.post,
            node_url,
            json={"filePaths": file_paths},
            timeout=300
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            raise HTTPException(502, f"Node preview server returned {response.status_code}: {response.text}")
    except Exception as e:
        if os.path.exists(batch_dir):
            try:
                shutil.rmtree(batch_dir)
            except Exception:
                pass
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(500, f"File upload failed: {str(e)}")



