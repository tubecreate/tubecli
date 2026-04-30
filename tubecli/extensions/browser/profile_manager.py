"""
Browser Profile Manager
Folder-based profile system with config.json per profile.
Ported from python-video-studio browser-laucher/web_manager.
"""
import os
import json
import shutil
import requests
from datetime import datetime
from typing import List, Optional, Dict, Any
from tubecli.config import DATA_DIR

PROFILES_DIR = os.path.join(DATA_DIR, "browser_profiles")


def ensure_profiles_dir():
    os.makedirs(PROFILES_DIR, exist_ok=True)


def list_profiles() -> List[Dict[str, Any]]:
    """List all browser profiles with metadata."""
    ensure_profiles_dir()
    profiles = []
    for name in os.listdir(PROFILES_DIR):
        profile_path = os.path.join(PROFILES_DIR, name)
        if os.path.isdir(profile_path):
            config = _load_config(name)
            profiles.append({
                "name": name,
                "created_at": config.get("created_at", ""),
                "tags": config.get("tags", []),
                "proxy": config.get("proxy", ""),
                "browser_version": config.get("browser_version", "latest"),
                "chrome_version": config.get("chrome_version", ""),
                "window_size": config.get("window_size", {"width": 1920, "height": 1080}),
                "notes": config.get("notes", ""),
                "has_cookies": os.path.exists(os.path.join(profile_path, "cookies.json")),
                "has_fingerprint": os.path.exists(os.path.join(profile_path, "fingerprint.json")),
                "google_account": config.get("google_account", None),
            })
    # Sort newest first
    profiles.sort(key=lambda p: p.get("created_at", ""), reverse=True)
    return profiles


def create_profile(name: str, proxy: str = "", browser_version: str = "latest", tags: List[str] = None,
                   window_size: Dict[str, int] = None, chrome_version: str = "") -> Dict[str, Any]:
    """Create a new browser profile folder with config."""
    ensure_profiles_dir()
    safe_name = "".join(c for c in name if c.isalnum() or c in "_-")
    profile_path = os.path.join(PROFILES_DIR, safe_name)

    if os.path.exists(profile_path):
        raise ValueError(f"Profile '{safe_name}' already exists")

    os.makedirs(profile_path)

    config = {
        "created_at": datetime.now().isoformat(),
        "tags": tags or ["Windows", "Chrome"],
        "proxy": proxy,
        "browser_version": browser_version,
        "chrome_version": chrome_version or "",
        "window_size": window_size or {"width": 1920, "height": 1080},
        "notes": "",
        "blacklist": [],
    }
    _save_config(safe_name, config)
    
    # Try fetching initial fingerprint
    get_fingerprint(safe_name)

    return {"name": safe_name, **config}


def delete_profile(name: str) -> bool:
    """Delete a profile and its data."""
    profile_path = os.path.join(PROFILES_DIR, name)
    if not os.path.exists(profile_path):
        return False
    shutil.rmtree(profile_path)
    return True


def get_profile(name: str) -> Optional[Dict[str, Any]]:
    """Get a single profile's config."""
    profile_path = os.path.join(PROFILES_DIR, name)
    if not os.path.isdir(profile_path):
        return None
    config = _load_config(name)
    return {"name": name, **config}


def update_profile(name: str, **kwargs) -> Optional[Dict[str, Any]]:
    """Update profile config fields."""
    profile_path = os.path.join(PROFILES_DIR, name)
    if not os.path.isdir(profile_path):
        return None
    config = _load_config(name)
    for key in ("tags", "proxy", "browser_version", "chrome_version", "window_size", "notes", "blacklist", "google_account"):
        if key in kwargs and kwargs[key] is not None:
            config[key] = kwargs[key]
    _save_config(name, config)
    return {"name": name, **config}


def bulk_set_proxy(names: List[str], proxy: str) -> List[Dict]:
    """Set proxy for multiple profiles at once."""
    results = []
    for name in names:
        if update_profile(name, proxy=proxy):
            results.append({"name": name, "status": "updated"})
        else:
            results.append({"name": name, "status": "not_found"})
    return results


def get_fingerprint(name: str) -> Optional[dict]:
    """Get the fingerprint for a profile, fetching from API if missing/invalid."""
    profile_path = os.path.join(PROFILES_DIR, name)
    if not os.path.isdir(profile_path):
        return None

    fp_path = os.path.join(profile_path, "fingerprint.json")
    
    # Try reading existing
    if os.path.exists(fp_path):
        try:
            with open(fp_path, "r", encoding="utf-8") as f:
                fp = json.load(f)
                if fp and isinstance(fp, dict) and len(fp) > 5:
                    return fp
        except Exception:
            pass  # Fallback to fetch new
            
    # Fetch new from API
    try:
        # Read config to pass params
        config = get_profile(name)
        tags_param = "Microsoft Windows,Chrome"
        min_browser_version = None
        window_size = None
        
        if config:
            browser_version = config.get("browser_version")
            if browser_version and browser_version not in ("default", "latest"):
                try: min_browser_version = browser_version.split('.')[0]
                except: pass
            
            tags = config.get("tags")
            if tags:
                tag_map = {"Windows": "Microsoft Windows", "macOS": "Mac OS X"}
                mapped_tags = [tag_map.get(t, t) for t in tags]
                tags_param = ",".join(mapped_tags)
                
            window_size = config.get("window_size")

        def _do_fetch(params):
            resp = requests.get("https://api.tubecreate.com/api/fingerprints/getfinger.php", params=params, timeout=180.0)
            resp.raise_for_status()
            data = resp.json()
            
            if data and data.get("status") == "success":
                fp_data = None
                # New format: fingerprint inline
                if data.get("fingerprint"):
                    fp_data = data["fingerprint"]
                # Old format: download via file_path
                elif data.get("file_path"):
                    fp_url = f"https://api.tubecreate.com/{data['file_path']}"
                    fp_resp = requests.get(fp_url, timeout=120.0)
                    fp_resp.raise_for_status()
                    fp_data = fp_resp.json()
                
                # Validate: check for {valid: false}
                if fp_data and isinstance(fp_data, dict) and fp_data.get("valid") is False:
                    print(f"[Fingerprint] Bablosoft returned valid=false: {fp_data.get('message', '?')}")
                    return None
                    
                return fp_data
            return None

        # Attempt 1: with size ranges
        params = {"tags": tags_param}
        if min_browser_version:
            params["min_browser_version"] = min_browser_version
        if window_size:
            w, h = window_size.get("width", 1920), window_size.get("height", 1080)
            params["min_width"] = max(w - 200, 1024)
            params["max_width"] = w + 200
            params["min_height"] = max(h - 200, 600)
            params["max_height"] = h + 200

        fp_data = _do_fetch(params)
        
        # Attempt 2: without size
        if not fp_data and window_size:
            print("[Fingerprint] Retrying without size constraints...")
            params2 = {"tags": tags_param}
            if min_browser_version:
                params2["min_browser_version"] = min_browser_version
            fp_data = _do_fetch(params2)
        
        # Attempt 3: without version
        if not fp_data and min_browser_version:
            print("[Fingerprint] Retrying without version constraint...")
            fp_data = _do_fetch({"tags": tags_param})

        if fp_data:
            with open(fp_path, "w", encoding="utf-8") as f:
                json.dump(fp_data, f)
            return fp_data
            
    except Exception as e:
        print(f"[Fingerprint API Error] {e}")
        
    return None


def reset_fingerprint(name: str) -> bool:
    """Delete the existing fingerprint so it gets re-fetched next time."""
    profile_path = os.path.join(PROFILES_DIR, name)
    fp_path = os.path.join(profile_path, "fingerprint.json")
    if os.path.exists(fp_path):
        try:
            os.remove(fp_path)
            return True
        except OSError:
            pass
    return False


def refresh_fingerprint(name: str) -> Optional[dict]:
    """Force-fetch a fresh fingerprint from API, overwriting any existing one."""
    profile_path = os.path.join(PROFILES_DIR, name)
    if not os.path.isdir(profile_path):
        return None
    fp_path = os.path.join(profile_path, "fingerprint.json")
    # Remove existing fingerprint to force fresh fetch
    try:
        if os.path.exists(fp_path):
            os.remove(fp_path)
    except OSError:
        pass
    return get_fingerprint(name)


def _load_config(name: str) -> dict:
    config_path = os.path.join(PROFILES_DIR, name, "config.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"tags": ["Windows", "Chrome"], "notes": "", "blacklist": []}


def _save_config(name: str, config: dict):
    config_path = os.path.join(PROFILES_DIR, name, "config.json")
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
