"""
TubeCLI Configuration
Global paths, defaults, and workspace management.
"""
import os
import json
from pathlib import Path


# ── Paths ────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent  # tubecli/ root
DATA_DIR = BASE_DIR / "data"
AGENTS_FILE = DATA_DIR / "agents.json"
SKILLS_FILE = DATA_DIR / "skills.json"
WORKFLOWS_DIR = DATA_DIR / "workflows"
LOGS_DIR = DATA_DIR / "logs"
EXTENSIONS_EXTERNAL_DIR = DATA_DIR / "extensions_external"

# ── Defaults ─────────────────────────────────────────────────────────
DEFAULT_API_PORT = 5295
DEFAULT_AI_MODEL = "qwen:latest"
OLLAMA_BASE_URL = "http://localhost:11434"
GIT_REPO_URL = "https://github.com/tubecreate/tubecli.git"

# ── Port Settings ────────────────────────────────────────────────────
PORT_SETTINGS_FILE = DATA_DIR / "api_port.json"
SETTINGS_FILE = DATA_DIR / "settings.json"

# ── Supported Languages ─────────────────────────────────────────
SUPPORTED_LANGUAGES = ["vi", "en"]
DEFAULT_LANGUAGE = "en"


def get_api_port() -> int:
    """Get configured API port from settings, or default."""
    try:
        if PORT_SETTINGS_FILE.exists():
            with open(PORT_SETTINGS_FILE, "r") as f:
                data = json.load(f)
                return int(data.get("port", DEFAULT_API_PORT))
    except Exception:
        pass
    return DEFAULT_API_PORT


def set_api_port(port: int) -> bool:
    """Save API port to settings file."""
    try:
        PORT_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(PORT_SETTINGS_FILE, "w") as f:
            json.dump({"port": port}, f)
        return True
    except Exception:
        return False


def get_language() -> str:
    """Get configured language from settings file, or default."""
    try:
        if SETTINGS_FILE.exists():
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                lang = data.get("language", DEFAULT_LANGUAGE)
                if lang in SUPPORTED_LANGUAGES:
                    return lang
    except Exception:
        pass
    return DEFAULT_LANGUAGE


def set_language(lang: str) -> bool:
    """Save language preference to settings file."""
    try:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        # Read existing settings if any
        settings = {}
        if SETTINGS_FILE.exists():
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    settings = json.load(f)
            except Exception:
                pass
        settings["language"] = lang
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


def ensure_data_dirs():
    """Create all required data directories."""
    for d in [DATA_DIR, WORKFLOWS_DIR, LOGS_DIR, EXTENSIONS_EXTERNAL_DIR]:
        d.mkdir(parents=True, exist_ok=True)
