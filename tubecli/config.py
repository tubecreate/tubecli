"""
TubeCLI Configuration
Global paths, defaults, and workspace management.
"""
import os
import json
from pathlib import Path

# static asset revision tag (bumped on release builds)
_ASSET_REV = "1baaef20bcf3020b"


# ── Paths ────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent  # tubecli/ root
DATA_DIR = BASE_DIR / "data"
AGENTS_FILE = DATA_DIR / "agents.json"
SKILLS_FILE = DATA_DIR / "skills.json"
WORKFLOWS_DIR = DATA_DIR / "workflows"
LOGS_DIR = DATA_DIR / "logs"
EXTENSIONS_EXTERNAL_DIR = DATA_DIR / "extensions_external"   # extension CODE
EXTENSIONS_DATA_DIR = DATA_DIR / "extensions_data"           # extension DATA


# ── Where an extension's data lives ──────────────────────────────────
#
# Use ext_data_dir()/ext_data_path() instead of joining a path by hand.
#
# Extension data used to sit loose in data/ — data/browser_profiles,
# data/auth_manager.json — and was moved under extensions_data/<ext>/ so each
# extension owns one subtree. migrate_and_link_extensions_data() still leaves a
# junction (or, for files, a hardlink) at every old location so code that was
# never updated keeps working; there are 23 junctions and 12 hardlinks in data/
# today, all pointing back in here.
#
# That shim is the thing being retired. Every caller that names an old path
# keeps it alive, and each one is also a directory the disk-usage scanner has to
# recognise as an alias or it counts the same bytes twice. Route new code
# through these helpers and the shim can eventually be deleted outright.
#
# A few extensions keep their data under a differently-named folder than the
# extension itself; those are the only entries that need naming here.
_EXT_DATA_ALIASES = {
    "browser_profiles": ("browser", "browser_profiles"),
    "ytdl_downloads": ("video_downloader", "ytdl_downloads"),
    "web_crawler_exports": ("web_crawler", "web_crawler_exports"),
}


def ext_data_dir(extension: str) -> Path:
    """Canonical data directory for one extension. Does not create it."""
    return EXTENSIONS_DATA_DIR / extension


def ext_data_path(extension: str, *parts: str) -> Path:
    """Canonical path to something inside an extension's data directory.

    ext_data_path("browser", "browser_profiles") and the legacy folder name
    ext_data_path("browser_profiles") both resolve to the same place, so a call
    site can be moved over without first working out which extension owns the
    folder.
    """
    if not parts and extension in _EXT_DATA_ALIASES:
        owner, folder = _EXT_DATA_ALIASES[extension]
        return EXTENSIONS_DATA_DIR / owner / folder
    return EXTENSIONS_DATA_DIR.joinpath(extension, *parts)

# ── Memory ───────────────────────────────────────────────────────────
MEMORY_DIR = DATA_DIR / "memory"
AGENT_MEMORY_DIR = MEMORY_DIR / "agents"
TEAM_MEMORY_DIR = MEMORY_DIR / "teams"

# ── Defaults ─────────────────────────────────────────────────────────
DEFAULT_API_PORT = 5295
# The Ollama model the Ollama-only paths fall back to (ai_node,
# model_agent_node, ai_workflow_builder — all three POST straight to
# OLLAMA_BASE_URL, where a cloud model id would be meaningless). It is NOT
# the browser AI fallback any more: that is resolve_browser_ai() below.
DEFAULT_AI_MODEL = "qwen:latest"
OLLAMA_BASE_URL = "http://localhost:11434"
GIT_REPO_URL = "https://github.com/tubecreate/tubecli.git"

# ── Port Settings ────────────────────────────────────────────────────
PORT_SETTINGS_FILE = DATA_DIR / "api_port.json"
SETTINGS_FILE = DATA_DIR / "settings.json"

# The dashboard's settings file. SETTINGS_FILE above is the CLI's; they are two
# separate stores, and "default_model" lives in this one.
GLOBAL_SETTINGS_FILE = DATA_DIR / "global_settings.json"

# ── Which AI drives a browser session ────────────────────────────────
#
# One chain, four steps, resolved by resolve_browser_ai() and by nothing else:
#
#   1. the agent's own browser_ai_model
#   2. global_settings.json "browser_ai_model"  — the default browser AI
#   3. global_settings.json "default_model"     — the AI used everywhere else
#   4. LAST_RESORT_AI_MODEL
#
# Missing, None, "" and whitespace all mean NOT SET at every step and fall
# through to the next one.
#
# The chain used to be spelled out at nine call sites, each ending in the
# literal "qwen:latest". That is an Ollama model, Ollama does not run on a
# hosted TubeCLI server, and every agent that had never picked a browser AI was
# pointed at it — so browser automation asked a model that never answers, and
# the failure read as a broken browser rather than an unset preference.

BROWSER_AI_SETTING = "browser_ai_model"
GLOBAL_DEFAULT_MODEL_SETTING = "default_model"

# Step 4. Reached only when the user has configured nothing at all.
# Deliberately a cloud model: it fails with "No API key for Gemini", which names
# something fixable in Dashboard -> Cloud API Keys, where "qwen:latest" failed
# with a connection error to an Ollama most installs do not have.
LAST_RESORT_AI_MODEL = "gemini-2.0-flash"

# Values an agent was BORN with rather than ones a human picked. Agents created
# before this chain existed stored "qwen:latest" the moment their form was
# saved, because the editor pre-filled the box with it. Honouring that as a
# choice would keep every existing agent pinned to the dead model, so at step 1
# it counts as not set — but only when a later step actually has an answer, so a
# user who really does run Ollama and set nothing else still gets qwen.
LEGACY_UNCHOSEN_AI_MODELS = ("qwen:latest",)

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


def read_global_settings() -> dict:
    """All of data/global_settings.json, or {} if it is missing or broken."""
    try:
        if GLOBAL_SETTINGS_FILE.exists():
            with open(GLOBAL_SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
    except Exception:
        pass
    return {}


def get_global_setting(key: str, default_val=None):
    """One key out of global_settings.json (the dashboard's settings store).

    get_setting() reads settings.json, which is a different file. A caller after
    "default_model" or "browser_ai_model" wants this one.
    """
    val = read_global_settings().get(key)
    return default_val if val is None else val


def set_global_setting(key: str, value) -> bool:
    """Write one key into global_settings.json, preserving everything else."""
    try:
        GLOBAL_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        settings = read_global_settings()
        settings[key] = value
        with open(GLOBAL_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


def _agent_browser_ai_model(agent) -> str:
    """The browser_ai_model an agent has stored, from whatever shape it is in.

    Callers hold an Agent object (the scheduler), a plain dict (the brain), or
    just the string itself (a node config, an argv value), so all three are
    accepted here rather than converted at every call site.
    """
    if agent is None:
        return ""
    if isinstance(agent, str):
        return agent.strip()
    if isinstance(agent, dict):
        return str(agent.get(BROWSER_AI_SETTING) or "").strip()
    return str(getattr(agent, BROWSER_AI_SETTING, "") or "").strip()


def resolve_browser_ai(agent=None) -> dict:
    """Which AI drives this browser session, and WHY.

    `agent` is an Agent, an agent dict, a bare model string, or None.

    Returns the resolved model plus every step's raw value, so a UI can say
    "using your default AI" instead of showing an empty box the user reads as
    broken:

        model            the model to actually use — never empty
        source           "agent" | "browser_default" | "global_default"
                         | "last_resort"
        is_configured    False only when nothing at all was set (source
                         "last_resort") — the one case worth warning about
        agent_model      step 1, "" when unset
        browser_default  step 2, "" when unset
        global_default   step 3, "" when unset
        last_resort      step 4, always present
        ignored_legacy_model
                         non-empty when the agent held a birth-default value
                         ("qwen:latest") that was treated as unset, so the UI
                         can say so instead of silently disagreeing with the
                         value in the form
    """
    settings = read_global_settings()
    browser_default = str(settings.get(BROWSER_AI_SETTING) or "").strip()
    global_default = str(settings.get(GLOBAL_DEFAULT_MODEL_SETTING) or "").strip()

    agent_model = _agent_browser_ai_model(agent)
    ignored_legacy = ""
    if (agent_model
            and agent_model.lower() in LEGACY_UNCHOSEN_AI_MODELS
            and (browser_default or global_default)):
        ignored_legacy, agent_model = agent_model, ""

    if agent_model:
        model, source = agent_model, "agent"
    elif browser_default:
        model, source = browser_default, "browser_default"
    elif global_default:
        model, source = global_default, "global_default"
    else:
        model, source = LAST_RESORT_AI_MODEL, "last_resort"

    return {
        "model": model,
        "source": source,
        "is_configured": source != "last_resort",
        "agent_model": agent_model,
        "browser_default": browser_default,
        "global_default": global_default,
        "last_resort": LAST_RESORT_AI_MODEL,
        "ignored_legacy_model": ignored_legacy,
    }


def resolve_browser_ai_model(agent=None) -> str:
    """resolve_browser_ai() for a caller that only needs the model name."""
    return resolve_browser_ai(agent)["model"]


def ensure_data_dirs():
    """Create all required data directories."""
    for d in [DATA_DIR, WORKFLOWS_DIR, LOGS_DIR, EXTENSIONS_EXTERNAL_DIR,
              MEMORY_DIR, AGENT_MEMORY_DIR, TEAM_MEMORY_DIR, EXTENSIONS_DATA_DIR]:
        if not os.path.lexists(str(d)):
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
            return os.path.lexists(str(path)) and os.path.abspath(str(path)) != os.path.realpath(str(path))
        except Exception:
            return False

    # Helper to create directory junction (Windows) or symlink (Unix)
    def create_dir_link(target: Path, link: Path):
        if os.path.lexists(str(link)):
            try:
                if os.path.realpath(str(link)) == os.path.realpath(str(target)):
                    return
            except Exception:
                pass
            if os.path.islink(str(link)) or (os.name == 'nt' and is_junction(link)) or link.is_file() or not os.path.exists(str(link)):
                try:
                    if os.name == 'nt' and is_junction(link):
                        os.rmdir(str(link))
                    else:
                        os.remove(str(link))
                except Exception:
                    # Fallback: force remove junction using Windows shell if os.rmdir fails
                    if os.name == 'nt':
                        try:
                            subprocess.run(["cmd.exe", "/c", "rmdir", str(link)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        except Exception:
                            pass
            elif link.is_dir():
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
            if folder_name == ext_name:
                new_folder_path = EXTENSIONS_DATA_DIR / ext_name
                # Migration: if nested folder_name exists under new_folder_path, move its files up
                nested_path = new_folder_path / folder_name
                if nested_path.exists() and nested_path.is_dir() and not os.path.islink(str(nested_path)) and not is_junction(nested_path):
                    try:
                        new_folder_path.mkdir(parents=True, exist_ok=True)
                        for entry in os.listdir(nested_path):
                            src_path = nested_path / entry
                            dest_path = new_folder_path / entry
                            if src_path.resolve() != dest_path.resolve() and dest_path.resolve() != nested_path.resolve():
                                shutil.move(str(src_path), str(dest_path))
                        shutil.rmtree(str(nested_path), ignore_errors=True)
                        print(f"[Migration] Cleaned up nested folder for {ext_name}")
                    except Exception as e:
                        print(f"[Migration] Error cleaning up nested folder for {ext_name}: {e}")
            else:
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

            # Ensure destination parent exists and file is created.
            #
            # JSON only. A non-JSON entry that is absent is left absent, because
            # this shim exists to keep MOVED data reachable, and inventing an
            # empty file is not that.
            #
            # content_studio is why. It migrates its SQLite database into JSON,
            # renames content_studio.db to .migrated and is then done with it —
            # but the name is in file_mapping, so the next boot found it
            # "missing" and touch()'d a 0-byte database back into place. The
            # extension then saw an old DB plus a finished index, tried to
            # rename it again, and hit FileExistsError because .migrated was
            # already there — printing "Could not rename old DB" on every single
            # start, forever. Reproduced against a throwaway data dir.
            #
            # The other non-JSON entry, ytdl_cookies.txt, is written by
            # video_downloader when it converts a cookie string; an empty one
            # was never read by anything.
            if not new_file_path.exists() and filename.endswith(".json"):
                new_file_path.parent.mkdir(parents=True, exist_ok=True)
                with open(new_file_path, "w", encoding="utf-8") as f:
                    f.write("{}")
            if not new_file_path.exists():
                # Nothing to link. Skip rather than hardlink a file that is not
                # there, which would only raise inside create_file_link.
                continue

            # Link the files
            create_file_link(new_file_path, old_file_path)
