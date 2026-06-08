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
EXTENSIONS_DATA_DIR = DATA_DIR / "extensions_data"

# ── Memory ───────────────────────────────────────────────────────────
MEMORY_DIR = DATA_DIR / "memory"
AGENT_MEMORY_DIR = MEMORY_DIR / "agents"
TEAM_MEMORY_DIR = MEMORY_DIR / "teams"

# ── Defaults ─────────────────────────────────────────────────────────
DEFAULT_API_PORT = 5295
DEFAULT_AI_MODEL = "qwen:latest"
OLLAMA_BASE_URL = "http://localhost:11434"
GIT_REPO_URL = "https://github.com/tubecreate/tubecli.git"

# ── Port Settings ────────────────────────────────────────────────────
PORT_SETTINGS_FILE = DATA_DIR / "api_port.json"
SETTINGS_FILE = DATA_DIR / "settings.json"

# ── Supported Languages ─────────────────────────────────────────
SUPPORTED_LANGUAGES = ["zh", "zh-TW", "vi", "en", "ja", "ko", "es", "tr", "ru"]
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


def get_setting(key: str, default_val=None):
    """Get a generic setting from settings file."""
    try:
        if SETTINGS_FILE.exists():
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get(key, default_val)
    except Exception:
        pass
    return default_val


def set_setting(key: str, value) -> bool:
    """Save a generic setting to settings file."""
    try:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        settings = {}
        if SETTINGS_FILE.exists():
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    settings = json.load(f)
            except Exception:
                pass
        settings[key] = value
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


def ensure_data_dirs():
    """Create all required data directories."""
    for d in [DATA_DIR, WORKFLOWS_DIR, LOGS_DIR, EXTENSIONS_EXTERNAL_DIR,
              MEMORY_DIR, AGENT_MEMORY_DIR, TEAM_MEMORY_DIR, EXTENSIONS_DATA_DIR]:
        d.mkdir(parents=True, exist_ok=True)
    
    try:
        migrate_and_link_extensions_data()
    except Exception as e:
        import logging
        logging.getLogger("config").error(f"Error during extensions data migration: {e}")


def migrate_and_link_extensions_data():
    """
    Migrate extension data directories/files to `extensions_data/` and create
    transparent filesystem links (junctions on Windows, symlinks on Unix)
    or file hardlinks to keep the codebase backward-compatible and data clean.
    """
    import shutil
    import subprocess

    # 1. Ensure extensions_data directory exists
    EXTENSIONS_DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Helper to hide files/folders on Windows
    def hide_path(path: Path):
        if os.name == 'nt' and path.exists():
            import ctypes
            try:
                # FILE_ATTRIBUTE_HIDDEN = 0x02
                ctypes.windll.kernel32.SetFileAttributesW(str(path), 0x02)
            except Exception:
                pass

    # Helper to check if a directory path is a junction on Windows
    def is_junction(path: Path) -> bool:
        try:
            return path.is_dir() and os.path.abspath(path) != os.path.realpath(path)
        except Exception:
            return False

    # Helper to create directory junction (Windows) or symlink (Unix)
    def create_dir_link(target: Path, link: Path):
        if link.exists():
            # If it's already a junction or symlink, skip
            if os.path.islink(str(link)) or (os.name == 'nt' and is_junction(link)):
                return
            # If it's a real directory, don't overwrite it to avoid data loss
            if link.is_dir():
                return

        try:
            if os.name == 'nt':
                subprocess.run(
                    ["cmd.exe", "/c", "mklink", "/j", str(link), str(target)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            else:
                os.symlink(str(target), str(link), target_is_directory=True)
            hide_path(link)
        except Exception as e:
            pass

    # Helper to create file hardlink
    def create_file_link(target: Path, link: Path):
        if link.exists():
            try:
                if os.path.samefile(target, link):
                    # Already linked — ensure NOT hidden (hidden files block Python writes on Windows)
                    if os.name == 'nt':
                        try:
                            import ctypes
                            attrs = ctypes.windll.kernel32.GetFileAttributesW(str(link))
                            if attrs != -1 and (attrs & 0x02):  # FILE_ATTRIBUTE_HIDDEN
                                ctypes.windll.kernel32.SetFileAttributesW(str(link), attrs & ~0x02)
                        except Exception:
                            pass
                    return
            except Exception:
                pass
            try:
                os.remove(link)
            except Exception:
                pass

        try:
            os.link(str(target), str(link))
            # NOTE: Do NOT hide data files — Hidden attribute causes Python open(path,'w') to
            # fail with PermissionError on Windows when the process tries to replace the file.
        except Exception as e:
            pass

    # --- A. Migrate and Link Extension Directories ---
    ext_names = set([
        "ai_arena", "content_studio", "edu_video_studio", "graphic_studio",
        "livestream", "news_intel", "pod_studio", "remix_studio",
        "subtitle_extractor", "template_designer", "tts_vibevoice", "video_editor",
        "web_crawler", "video_downloader", "browser"
    ])

    # Auto-discover other external extensions
    if EXTENSIONS_EXTERNAL_DIR.exists():
        try:
            for entry in os.listdir(EXTENSIONS_EXTERNAL_DIR):
                if (EXTENSIONS_EXTERNAL_DIR / entry).is_dir() and not entry.startswith('.'):
                    ext_names.add(entry)
        except Exception:
            pass

    # Mapping of folders that have a different name in DATA_DIR than the extension name
    folder_mapping = {
        "web_crawler": ["web_crawler_exports"],
        "video_downloader": ["ytdl_downloads"],
        "browser": ["browser_profiles"]
    }

    for ext_name in ext_names:
        folders_to_link = folder_mapping.get(ext_name, [ext_name])
        for folder_name in folders_to_link:
            old_folder_path = DATA_DIR / folder_name
            new_folder_path = EXTENSIONS_DATA_DIR / ext_name / folder_name

            # If old folder exists and is a real directory (not link/junction), move it to new
            if old_folder_path.exists() and old_folder_path.is_dir() and not os.path.islink(str(old_folder_path)) and not is_junction(old_folder_path):
                try:
                    new_folder_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(old_folder_path), str(new_folder_path))
                    print(f"[Migration] Moved folder: {old_folder_path} -> {new_folder_path}")
                except Exception as e:
                    print(f"[Migration] Error moving folder {folder_name}: {e}")

            # Ensure the destination folder exists
            new_folder_path.parent.mkdir(parents=True, exist_ok=True)
            new_folder_path.mkdir(parents=True, exist_ok=True)

            # Create junction/symlink
            create_dir_link(new_folder_path, old_folder_path)

    # --- B. Migrate and Link Specific Extension Files ---
    file_mapping = {
        "web_crawler": ["watches.json", "watch_logs.json", "yt_watches.json", "yt_watch_logs.json", "wp_sites.json"],
        "video_downloader": ["downloader_settings.json", "ytdl_cookies.txt"],
        "studio3d": ["studio3d_scenes.json"],
        "universal_tracker": ["universal_tracker_jobs.json"],
        "auth_manager": ["auth_manager.json"],
        "calendar_manager": ["calendar_manager.json"],
        "content_studio": ["content_studio.db"],
    }

    for ext_name, filenames in file_mapping.items():
        for filename in filenames:
            old_file_path = DATA_DIR / filename
            new_file_path = EXTENSIONS_DATA_DIR / ext_name / filename

            already_linked = False
            if old_file_path.exists() and new_file_path.exists():
                try:
                    already_linked = os.path.samefile(old_file_path, new_file_path)
                except Exception:
                    pass

            if old_file_path.exists() and old_file_path.is_file() and not already_linked:
                try:
                    new_file_path.parent.mkdir(parents=True, exist_ok=True)
                    if new_file_path.exists():
                        os.remove(new_file_path)
                    shutil.move(str(old_file_path), str(new_file_path))
                    print(f"[Migration] Moved file: {old_file_path} -> {new_file_path}")
                except Exception as e:
                    print(f"[Migration] Error moving file {filename}: {e}")

            # Ensure destination parent exists and file is created
            if not new_file_path.exists():
                new_file_path.parent.mkdir(parents=True, exist_ok=True)
                if filename.endswith(".json"):
                    with open(new_file_path, "w", encoding="utf-8") as f:
                        f.write("{}")
                else:
                    new_file_path.touch()

            # Link the files
            create_file_link(new_file_path, old_file_path)
