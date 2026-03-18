"""
Browser Profile Manager
Folder-based profile system with config.json per profile.
Ported from python-video-studio browser-laucher/web_manager.
"""
import os
import json
import shutil
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
                "notes": config.get("notes", ""),
                "has_cookies": os.path.exists(os.path.join(profile_path, "cookies.json")),
            })
    # Sort newest first
    profiles.sort(key=lambda p: p.get("created_at", ""), reverse=True)
    return profiles


def create_profile(name: str, proxy: str = "", tags: List[str] = None) -> Dict[str, Any]:
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
        "notes": "",
        "blacklist": [],
    }
    _save_config(safe_name, config)

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
    for key in ("tags", "proxy", "notes", "blacklist"):
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
