"""
TubeCLI Extension System
Enhanced extension architecture with git-based install, external discovery,
SKILL.md for AI guidance, and extension-provided workflow nodes.
"""
import os
import sys
import json
import logging
import importlib
import importlib.util
import subprocess
import shutil
from typing import Dict, List, Optional, Any, Type
from pathlib import Path
from tubecli.config import DATA_DIR, EXTENSIONS_EXTERNAL_DIR

logger = logging.getLogger('ExtensionManager')


def _run_node_tool(tool: str, tool_args: List[str], *, cwd: str,
                   timeout: int, label: str) -> bool:
    """Run an npm/npx command portably, and say so when it fails.

    shell=False with an executable we resolve ourselves. Passing an arg LIST
    together with shell=True means two different things per platform: Windows
    joins it into one command string, but POSIX rewrites it to
    ['/bin/sh', '-c'] + args, so only the first element is the command and the
    rest are bound to $0, $1... and dropped. `npm install` was therefore a bare
    `npm` on Linux and macOS — it printed usage, exited, and installed nothing,
    which is why an extension could report a successful install and then fail at
    first use. shutil.which is what makes dropping shell=True safe on Windows:
    it resolves npm/npx to the npm.cmd/npx.cmd shims that shell=True used to find.

    The result used to be discarded entirely, so a real npm failure was silent
    too. Returns True only when the command actually ran and exited 0.
    """
    exe = shutil.which(tool)
    if not exe:
        logger.warning("%s: `%s` not found on PATH — skipped.", label, tool)
        return False
    try:
        result = subprocess.run([exe] + tool_args, cwd=cwd, capture_output=True,
                                text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        logger.warning("%s: `%s %s` timed out after %ss.",
                       label, tool, " ".join(tool_args), timeout)
        return False
    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "").strip().splitlines()[-3:]
        logger.warning("%s: `%s %s` exited %s. %s", label, tool,
                       " ".join(tool_args), result.returncode, " / ".join(tail))
        return False
    return True


# ── Version comparison & Git Helpers ─────────────────────────────────

def compare_versions(v1: str, v2: str) -> int:
    """Compare two version strings. Support both standard YYYY.MM.DD.HHMMSS and semver.
    Returns:
        1 if v1 > v2
        -1 if v1 < v2
        0 if v1 == v2
    """
    def parse(v):
        parts = []
        for part in str(v).strip().split('.'):
            if part.isdigit():
                parts.append(int(part))
            else:
                parts.append(part)
        return parts

    p1 = parse(v1)
    p2 = parse(v2)
    
    for i in range(max(len(p1), len(p2))):
        el1 = p1[i] if i < len(p1) else 0
        el2 = p2[i] if i < len(p2) else 0
        
        if type(el1) != type(el2):
            el1 = str(el1)
            el2 = str(el2)
            
        if el1 > el2:
            return 1
        elif el1 < el2:
            return -1
    return 0


def get_git_tracking_branch(dir_path: str) -> str:
    """Get remote upstream branch name (e.g. main, master)."""
    import subprocess
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "@{u}"],
            cwd=dir_path, capture_output=True, text=True, timeout=5
        )
        if res.returncode == 0 and res.stdout.strip():
            parts = res.stdout.strip().split('/', 1)
            if len(parts) == 2:
                return parts[1]
    except Exception:
        pass
    
    try:
        res = subprocess.run(
            ["git", "branch", "-r"],
            cwd=dir_path, capture_output=True, text=True, timeout=5
        )
        if res.returncode == 0:
            branches = res.stdout.strip()
            if "origin/main" in branches:
                return "main"
            elif "origin/master" in branches:
                return "master"
    except Exception:
        pass
    return "main"


def get_git_commit_version(dir_path: str, remote: bool = False, branch: str = "main") -> Optional[str]:
    """Get the git commit datetime formatted as standard YYYY.MM.DD.HHMMSS."""
    import subprocess
    try:
        if remote:
            cmd = ["git", "log", "-n", "1", "--format=%cd", "--date=format:%Y.%m.%d.%H%M%S", f"origin/{branch}"]
        else:
            cmd = ["git", "log", "-n", "1", "--format=%cd", "--date=format:%Y.%m.%d.%H%M%S"]
            
        res = subprocess.run(cmd, cwd=dir_path, capture_output=True, text=True, timeout=10)
        if res.returncode == 0:
            return res.stdout.strip()
    except Exception:
        pass
    return None


def get_git_remote_url(dir_path: str) -> Optional[str]:
    """Get remote origin URL for the git repository."""
    import subprocess
    try:
        res = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=dir_path, capture_output=True, text=True, timeout=5
        )
        if res.returncode == 0:
            return res.stdout.strip()
    except Exception:
        pass
    return None


EXTENSIONS_CONFIG_FILE = os.path.join(DATA_DIR, "extensions.json")

# ── Extension Manifest Schema ────────────────────────────────────────

REQUIRED_MANIFEST_FIELDS = ["name", "version", "description", "entry", "extension_class"]

MANIFEST_TEMPLATE = {
    "name": "",
    "version": "1.0.0",
    "description": "",
    "author": "",
    "entry": "extension.py",
    "extension_class": "",
    "dependencies": [],
    "nodes": [],
    "skill_md": "SKILL.md",
    "ui_static": "",
    "api_prefix": "",
    "min_tubecli_version": "0.1.0",
}


def validate_manifest(manifest: dict) -> List[str]:
    """Validate a tubecli-extension.json manifest. Returns list of errors."""
    errors = []
    for field in REQUIRED_MANIFEST_FIELDS:
        if not manifest.get(field):
            errors.append(f"Missing required field: '{field}'")
    if manifest.get("name") and not manifest["name"].replace("_", "").replace("-", "").isalnum():
        errors.append(f"Invalid extension name: '{manifest['name']}' (use alphanumeric, -, _)")
    return errors


# ── Extension Base Class ─────────────────────────────────────────────

class Extension:
    """Base class for all TubeCLI extensions."""
    name: str = "base_extension"
    version: str = "0.1.0"
    description: str = ""
    author: str = ""
    default_port: Optional[int] = None
    extension_type: str = "system"       # "system" | "external"
    extension_dir: Optional[str] = None  # absolute path to extension directory

    def __init__(self):
        self.enabled = False
        self.current_port: Optional[int] = self.default_port
        self._routes = []
        self._commands = []
        self._manifest: dict = {}

    # ── Lifecycle Hooks ──────────────────────────────────────

    def on_install(self):
        """Called when extension is first installed."""
        pass

    def on_enable(self):
        """Called when extension is enabled."""
        pass

    def on_disable(self):
        """Called when extension is disabled."""
        pass

    def on_uninstall(self):
        """Called before extension is removed."""
        pass

    # ── Extension Points ─────────────────────────────────────

    def get_routes(self):
        """Return FastAPI router for API routes."""
        return None

    def get_commands(self):
        """Return Click command group for CLI commands."""
        return None

    def get_nodes(self) -> Dict[str, Any]:
        """Return dict of {node_type: NodeClass} this extension provides."""
        return {}

    def get_skills(self) -> List[Dict]:
        """Return list of skill definitions this extension provides.
        Each item should match the format used in default_skills.py:
        {
            "name": str,
            "description": str,
            "skill_type": str,
            "commands": List[str],
            "workflow_data": dict,
        }
        """
        return []

    def get_skill_md(self) -> Optional[str]:
        """Return SKILL.md content for AI guidance."""
        if self.extension_dir:
            skill_md_path = os.path.join(self.extension_dir, "SKILL.md")
            if os.path.exists(skill_md_path):
                try:
                    with open(skill_md_path, "r", encoding="utf-8") as f:
                        return f.read()
                except Exception:
                    pass
        return None

    def get_ui_static_dir(self) -> Optional[str]:
        """Return absolute path to extension's static UI directory."""
        if self.extension_dir:
            static_dir = os.path.join(self.extension_dir, "static")
            if os.path.isdir(static_dir):
                return static_dir
        return None

    def get_telegram_actions(self) -> Dict[str, Any]:
        """Return a dict of {action_name: async_handler_function} for Telegram Bot.
        Each handler receives (action_data: dict, context: dict) and returns str or dict.
        Override this in your extension to register Telegram-accessible actions.
        """
        return {}

    def get_manifest(self) -> dict:
        """Return extension manifest data."""
        return self._manifest or {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "extension_type": self.extension_type,
        }

    # ── Serialization ────────────────────────────────────────

    def to_dict(self) -> dict:
        manifest = self._manifest or {}
        git_url = None
        if self.extension_dir:
            git_dir = os.path.join(self.extension_dir, ".git")
            if os.path.exists(git_dir):
                git_url = get_git_remote_url(self.extension_dir)
                git_ver = get_git_commit_version(self.extension_dir)
                manifest_ver = manifest.get("version", "")
                if git_ver:
                    # Re-read manifest version from disk (hot-reload support)
                    try:
                        import json as _json
                        mf = os.path.join(self.extension_dir, "tubecli-extension.json")
                        if os.path.exists(mf):
                            with open(mf, "r", encoding="utf-8-sig") as _f:
                                manifest_ver = _json.load(_f).get("version", manifest_ver)
                    except Exception:
                        pass
                    # Use whichever is newer: manifest version or git commit version
                    if manifest_ver and compare_versions(manifest_ver, git_ver) > 0:
                        self.version = manifest_ver
                    else:
                        self.version = git_ver
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "enabled": self.enabled,
            "default_port": self.default_port,
            "current_port": self.current_port,
            "extension_type": self.extension_type,
            "extension_dir": self.extension_dir,
            "icon": manifest.get("icon", "📦"),
            "has_skill_md": self.get_skill_md() is not None,
            "has_nodes": bool(self.get_nodes()),
            "has_ui": self.get_ui_static_dir() is not None,
            "page_url": manifest.get("page_url", ""),
            "display_name": manifest.get("display_name", ""),
            "category": manifest.get("category", ""),
            "tags": manifest.get("tags", []),
            "license": manifest.get("license", ""),
            "homepage": manifest.get("homepage", ""),
            "donate": manifest.get("donate", ""),
            "git_url": git_url,
        }


# ── Extension Manager ────────────────────────────────────────────────

class ExtensionManager:
    """Discovers, loads, and manages extensions (built-in + external)."""

    # Built-in system extensions to discover
    BUILTIN_EXTENSIONS = [
        "tubecli.extensions.webui",
        "tubecli.extensions.market",
        "tubecli.extensions.cloud_api",
        "tubecli.extensions.ollama_manager",
        "tubecli.extensions.multi_agents",
        "tubecli.extensions.browser",
        "tubecli.extensions.browser_scripts",
        "tubecli.extensions.website_manager",
        "tubecli.extensions.studio3d",
        "tubecli.extensions.douyin_downloader",
        "tubecli.extensions.auth_manager",
        "tubecli.extensions.calendar_manager",
        "tubecli.extensions.file_manager",
        "tubecli.extensions.universal_tracker",
        "tubecli.extensions.codex",
        "tubecli.extensions.chat",
        "tubecli.extensions.video_studio",
    ]

    # Essential external extensions to auto-install if missing
    ESSENTIAL_EXTENSIONS = [
        # browser is now a built-in extension
    ]

    def __init__(self):
        self._extensions: Dict[str, Extension] = {}
        self._config: Dict[str, Any] = {}
        self._load_config()

    def _load_config(self):
        try:
            if os.path.exists(EXTENSIONS_CONFIG_FILE):
                with open(EXTENSIONS_CONFIG_FILE, "r", encoding="utf-8") as f:
                    self._config = json.load(f)
        except Exception:
            self._config = {}

    def _save_config(self):
        os.makedirs(os.path.dirname(EXTENSIONS_CONFIG_FILE), exist_ok=True)
        with open(EXTENSIONS_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(self._config, f, indent=2, ensure_ascii=False)

    # ── Discovery ────────────────────────────────────────────

    def discover_extensions(self):
        """Auto-discover all extensions: built-in system + external."""
        # 0. Ensure essential extensions are installed
        self.ensure_essential_extensions()

        # 1. Built-in system extensions
        for module_path in self.BUILTIN_EXTENSIONS:
            try:
                mod = importlib.import_module(module_path)
                if hasattr(mod, "extension_instance"):
                    extension = mod.extension_instance
                    extension.extension_type = "system"
                    if not extension.extension_dir:
                        extension.extension_dir = os.path.dirname(
                            getattr(mod, "__file__", "")
                        )
                    self.register(extension)
                    # Auto-enable newly discovered built-in extensions
                    if extension.name not in self._config:
                        logger.info(f"Auto-enabling new built-in extension: {extension.name}")
                        self.enable(extension.name)
            except ImportError as e:
                logger.debug(f"Extension {module_path} not available: {e}")
            except Exception as e:
                logger.error(f"Error loading extension {module_path}: {e}")

        # 2. External extensions (git-installed)
        self.discover_external_extensions()

    def ensure_essential_extensions(self):
        """Auto-install essential extensions from git if missing."""
        ext_dir = str(EXTENSIONS_EXTERNAL_DIR)
        for essential in self.ESSENTIAL_EXTENSIONS:
            # Check if directory exists (by repo name or manifest name)
            # Standard repo name for browser-control is browser-control or browser-laucher
            # We check the manifest name matches to be sure.
            
            is_installed = False
            if os.path.exists(ext_dir):
                for entry in os.listdir(ext_dir):
                    target_dir = os.path.join(ext_dir, entry)
                    manifest_file = os.path.join(target_dir, "tubecli-extension.json")
                    if os.path.exists(manifest_file):
                        try:
                            with open(manifest_file, "r", encoding="utf-8-sig") as f:
                                manifest = json.load(f)
                                if manifest.get("name") == essential["name"]:
                                    is_installed = True
                                    break
                        except Exception:
                            continue
            
            if not is_installed:
                logger.info(f"Auto-installing essential extension: {essential['name']}...")
                print(f"📦 First run: Auto-installing {essential['name']} extension...")
                res = self.install_from_git(essential["git_url"])
                if res["status"] == "success":
                    logger.info(f"Successfully auto-installed {essential['name']}")
                else:
                    logger.error(f"Failed to auto-install {essential['name']}: {res['message']}")

    def discover_external_extensions(self):
        """Scan data/extensions_external/ for installed external extensions."""
        ext_dir = str(EXTENSIONS_EXTERNAL_DIR)
        if not os.path.isdir(ext_dir):
            return

        for entry in os.listdir(ext_dir):
            extension_path = os.path.join(ext_dir, entry)
            if not os.path.isdir(extension_path):
                continue

            manifest_file = os.path.join(extension_path, "tubecli-extension.json")
            if not os.path.exists(manifest_file):
                logger.debug(f"Skipping {entry}: no tubecli-extension.json")
                continue

            try:
                with open(manifest_file, "r", encoding="utf-8-sig") as f:
                    manifest = json.load(f)

                errors = validate_manifest(manifest)
                if errors:
                    logger.error(f"Invalid manifest in {entry}: {errors}")
                    continue

                # Already loaded?
                if manifest["name"] in self._extensions:
                    continue

                # Load extension module dynamically
                extension = self._load_external_extension(extension_path, manifest)
                if extension:
                    self.register(extension)
                    # Auto-enable newly discovered external extensions
                    # (only if not already in config — respects user's manual disable)
                    if extension.name not in self._config:
                        logger.info(f"Auto-enabling new external extension: {extension.name}")
                        self.enable(extension.name)

            except Exception as e:
                logger.error(f"Error loading external extension {entry}: {e}")

    def _load_external_extension(self, extension_path: str, manifest: dict) -> Optional[Extension]:
        """Dynamically load an external extension from its directory."""
        entry_file = os.path.join(extension_path, manifest["entry"])
        if not os.path.exists(entry_file):
            logger.error(f"Entry file not found: {entry_file}")
            return None

        extension_name = manifest["name"]
        module_name = f"tubecli_ext_{extension_name}"

        try:
            # Add extension path to sys.path temporarily
            if extension_path not in sys.path:
                sys.path.insert(0, extension_path)

            spec = importlib.util.spec_from_file_location(module_name, entry_file)
            if not spec or not spec.loader:
                logger.error(f"Cannot create module spec for {entry_file}")
                return None

            mod = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = mod
            spec.loader.exec_module(mod)

            # Get the extension class
            cls_name = manifest["extension_class"]
            if not hasattr(mod, cls_name):
                logger.error(f"Extension class '{cls_name}' not found in {entry_file}")
                return None

            extension_cls = getattr(mod, cls_name)
            extension = extension_cls()
            extension.extension_type = "external"
            extension.extension_dir = extension_path
            extension._manifest = manifest
            extension.name = manifest["name"]
            
            # Determine version: prefer manifest version if newer than git commit date
            ext_ver = manifest.get("version", "0.1.0")
            git_dir = os.path.join(extension_path, ".git")
            if os.path.exists(git_dir):
                git_ver = get_git_commit_version(extension_path)
                if git_ver:
                    # Manifest version wins if explicitly set newer than git commit date
                    if ext_ver and compare_versions(ext_ver, git_ver) > 0:
                        pass  # keep ext_ver (manifest wins)
                    else:
                        ext_ver = git_ver
            
            extension.version = ext_ver
            extension.description = manifest.get("description", "")
            extension.author = manifest.get("author", "")

            return extension

        except Exception as e:
            logger.error(f"Error loading external extension {extension_name}: {e}")
            return None

    # ── Registration ─────────────────────────────────────────

    def register(self, extension: Extension):
        """Register a extension instance."""
        self._extensions[extension.name] = extension

        # Restore config (port, enabled)
        cfg = self._config.get(extension.name, {})
        if "port" in cfg:
            extension.current_port = cfg["port"]

        if cfg.get("enabled", False):
            extension.enabled = True
            try:
                extension.on_enable()
            except Exception as e:
                logger.error(f"Error enabling extension {extension.name}: {e}")

    # ── Enable / Disable ─────────────────────────────────────

    def enable(self, name: str) -> bool:
        extension = self._extensions.get(name)
        if not extension:
            return False
        # register() already calls on_enable() for anything the saved config marks
        # enabled, and `tubecli init` then calls enable() for every system
        # extension — so every on_enable() ran twice on a normal startup, doing its
        # setup twice and printing its errors twice.
        already_enabled = extension.enabled
        extension.enabled = True
        if not already_enabled:
            extension.on_enable()
        self._config.setdefault(name, {})["enabled"] = True
        self._save_config()
        return True

    def disable(self, name: str) -> bool:
        extension = self._extensions.get(name)
        if not extension:
            return False
        extension.enabled = False
        extension.on_disable()
        self._config.setdefault(name, {})["enabled"] = False
        self._save_config()
        return True

    # ── Getters ──────────────────────────────────────────────

    def get(self, name: str) -> Optional[Extension]:
        return self._extensions.get(name)

    def get_all(self) -> List[Extension]:
        return list(self._extensions.values())

    def get_enabled(self) -> List[Extension]:
        return [p for p in self._extensions.values() if p.enabled]

    def set_port(self, name: str, port: int) -> bool:
        extension = self._extensions.get(name)
        if not extension:
            return False
        extension.current_port = port
        self._config.setdefault(name, {})["port"] = port
        self._save_config()
        return True

    # ── CLI / API Registration ───────────────────────────────

    def register_cli_commands(self, cli_group):
        """Register all enabled extension CLI commands to the main CLI group."""
        for extension in self.get_enabled():
            try:
                cmds = extension.get_commands()
                if cmds:
                    cli_group.add_command(cmds)
            except Exception as e:
                logger.error(f"Error registering CLI for {extension.name}: {e}")

    def _ensure_extension_deps(self, extension):
        """Auto-install missing Python dependencies declared in tubecli-extension.json."""
        manifest = getattr(extension, '_manifest', None)
        if not manifest:
            return
        deps = manifest.get("dependencies", [])
        if not deps:
            return

        missing = []
        for pkg in deps:
            # Normalize package name for import check: lunar-python → lunar_python
            import_name = pkg.replace("-", "_").split(">=")[0].split("<=")[0].split("==")[0].strip()
            try:
                importlib.import_module(import_name)
            except ImportError:
                missing.append(pkg)

        if missing:
            print(f"[ExtensionManager] Installing dependencies for '{extension.name}': {', '.join(missing)}")
            try:
                subprocess.run(
                    [sys.executable, "-m", "pip", "install", *missing, "--quiet"],
                    capture_output=True, timeout=120,
                )
                print(f"[ExtensionManager] Dependencies installed successfully for '{extension.name}'")
            except Exception as e:
                print(f"[ExtensionManager] WARNING: Failed to install deps for '{extension.name}': {e}")

    def register_api_routes(self, app):
        """Register all enabled extension API routes to the FastAPI app."""
        for extension in self.get_enabled():
            try:
                # Ensure extension dir is in sys.path so local imports work
                # (e.g. `from routes import router` inside extension.py)
                ext_dir = getattr(extension, 'extension_dir', None)
                if ext_dir and ext_dir not in sys.path:
                    sys.path.insert(0, ext_dir)

                # Auto-install missing dependencies from manifest before loading
                self._ensure_extension_deps(extension)

                router = extension.get_routes()
                if router:
                    # Support extensions returning a list of routers
                    routers = router if isinstance(router, list) else [router]
                    for r in routers:
                        app.include_router(r)
                    logger.info(f"Registered API routes for extension '{extension.name}'")
                    # Duplicated the logger line above, and no flag reached it — so
                    # `api start --quiet` still printed 17 lines of routine startup
                    # chatter. Backgrounded with `&`, that reads as the server having
                    # hung rather than having started.
                    if not os.environ.get("TUBECLI_QUIET"):
                        print(f"SUCCESS registering {extension.name} routes ({len(routers)} router(s))")
            except Exception as e:
                import traceback
                # Failures are always shown: quiet is about routine noise, not about
                # hiding something that went wrong.
                logger.error(f"Failed to register API routes for extension '{extension.name}': {e}")
                print(f"FAILED to register API routes for extension '{extension.name}': {e}",
                      file=sys.stderr)
                traceback.print_exc()

    # ── Extension Nodes Registration ────────────────────────────

    def register_extension_nodes(self, node_registry: dict):
        """Merge all enabled extensions' nodes into the global NODE_REGISTRY.

        Values are validated before they go in. One extension returns a dict
        (a manifest-style description) instead of a class, and an unvalidated
        merge put that dict straight into the registry — where the very next
        `cls not in seen` in list_available_nodes() raised
        "TypeError: unhashable type: 'dict'" and took the whole node palette
        down with it. One malformed extension must not be able to do that.
        """
        for extension in self.get_enabled():
            try:
                nodes = extension.get_nodes()
                if not nodes:
                    continue
                for node_type, node_cls in nodes.items():
                    if node_type in node_registry:
                        continue
                    if not isinstance(node_cls, type):
                        logger.warning(
                            "Extension '%s' offered node '%s' as %s, not a class - skipped.",
                            extension.name, node_type, type(node_cls).__name__)
                        continue
                    node_registry[node_type] = node_cls
                    logger.info(f"Registered node '{node_type}' from extension '{extension.name}'")
            except Exception as e:
                logger.error(f"Error registering nodes for {extension.name}: {e}")

    # ── SKILL.md Collection ──────────────────────────────────

    def get_all_skill_mds(self) -> List[dict]:
        """Collect all SKILL.md content from enabled extensions for AI agents.
        Also collects extra skill MDs from extensions that provide them."""
        results = []
        for extension in self.get_enabled():
            try:
                content = extension.get_skill_md()
                if content:
                    results.append({
                        "extension": extension.name,
                        "version": extension.version,
                        "skill_md": content,
                    })
            except Exception:
                pass

            # Collect extra skill MDs (e.g., SKILL_WATCHER.md)
            try:
                if hasattr(extension, "get_extra_skill_mds"):
                    extras = extension.get_extra_skill_mds()
                    if extras:
                        results.extend(extras)
            except Exception:
                pass

        return results

    def get_all_telegram_actions(self) -> Dict[str, Any]:
        """Collect all Telegram action handlers from enabled extensions.
        Returns a dict of {action_name: handler_fn} merged from all extensions."""
        actions = {}
        for extension in self.get_enabled():
            try:
                ext_actions = extension.get_telegram_actions()
                if ext_actions:
                    for action_name, handler in ext_actions.items():
                        actions[action_name] = {
                            "handler": handler,
                            "extension": extension.name,
                        }
            except Exception:
                pass
        return actions

    # ── Git Install / Uninstall ──────────────────────────────

    def install_from_git(self, git_url: str) -> dict:
        """Clone a extension from git URL, validate, and register.

        Returns: {"status": "success"|"error", "extension": ..., "message": ...}
        """
        ext_dir = str(EXTENSIONS_EXTERNAL_DIR)
        os.makedirs(ext_dir, exist_ok=True)

        # Replace backslashes for cross-platform split
        normalized_url = git_url.replace("\\", "/")
        # Extract repo name from URL
        repo_name = normalized_url.rstrip("/").split("/")[-1]
        if repo_name.endswith(".git"):
            repo_name = repo_name[:-4]

        # Ensure repo_name is just the folder name, not an absolute path (e.g. C:)
        if ":" in repo_name:
            repo_name = repo_name.split(":")[-1]

        # Derive likely manifest name: repo slug → underscore format
        # e.g. "edu-video-studio" → "edu_video_studio"
        likely_manifest_name = repo_name.replace("-", "_").lower()

        target_dir = os.path.join(ext_dir, repo_name)

        # Check if already installed — by BOTH repo name AND manifest name
        if os.path.isdir(target_dir):
            return {"status": "error", "message": f"Extension directory '{repo_name}' already exists. Uninstall first."}

        # Also check by manifest name (e.g. edu_video_studio vs edu-video-studio)
        if likely_manifest_name != repo_name:
            manifest_dir = os.path.join(ext_dir, likely_manifest_name)
            if os.path.isdir(manifest_dir):
                return {"status": "error", "message": f"Extension '{likely_manifest_name}' already exists. Uninstall first."}

        # Scan all existing extensions by manifest name to prevent duplicates
        if os.path.isdir(ext_dir):
            for entry in os.listdir(ext_dir):
                entry_path = os.path.join(ext_dir, entry)
                if not os.path.isdir(entry_path):
                    continue
                manifest_file = os.path.join(entry_path, "tubecli-extension.json")
                if os.path.exists(manifest_file):
                    try:
                        with open(manifest_file, "r", encoding="utf-8-sig") as f:
                            existing_manifest = json.load(f)
                        existing_name = existing_manifest.get("name", "").replace("-", "_").lower()
                        if existing_name and existing_name == likely_manifest_name:
                            return {"status": "error", "message": f"Extension '{existing_name}' is already installed (in folder '{entry}'). Uninstall first."}
                    except Exception:
                        continue

        # Git clone
        try:
            result = subprocess.run(
                ["git", "clone", "--depth", "1", git_url, target_dir],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode != 0:
                return {"status": "error", "message": f"Git clone failed: {result.stderr}"}
        except FileNotFoundError:
            return {"status": "error", "message": "Git is not installed or not in PATH."}
        except subprocess.TimeoutExpired:
            return {"status": "error", "message": "Git clone timed out (120s)."}

        # Validate manifest
        manifest_file = os.path.join(target_dir, "tubecli-extension.json")
        if not os.path.exists(manifest_file):
            shutil.rmtree(target_dir, ignore_errors=True)
            return {"status": "error", "message": "No tubecli-extension.json found in repository."}

        try:
            with open(manifest_file, "r", encoding="utf-8-sig") as f:
                manifest = json.load(f)
        except Exception as e:
            shutil.rmtree(target_dir, ignore_errors=True)
            return {"status": "error", "message": f"Invalid tubecli-extension.json: {e}"}

        errors = validate_manifest(manifest)
        if errors:
            shutil.rmtree(target_dir, ignore_errors=True)
            return {"status": "error", "message": f"Manifest validation failed: {'; '.join(errors)}"}

        # Rename folder from git repo slug to manifest name if different
        manifest_name = manifest.get("name", repo_name)
        if manifest_name and manifest_name != repo_name:
            new_target_dir = os.path.join(ext_dir, manifest_name)
            if os.path.isdir(new_target_dir):
                shutil.rmtree(target_dir, ignore_errors=True)
                return {"status": "error", "message": f"Extension '{manifest_name}' already exists. Uninstall first."}
            try:
                os.rename(target_dir, new_target_dir)
                target_dir = new_target_dir
                manifest_file = os.path.join(target_dir, "tubecli-extension.json")
            except OSError as e:
                logger.warning(f"Could not rename extension dir: {e}")

        # Install Python dependencies if requirements.txt exists
        req_file = os.path.join(target_dir, "requirements.txt")
        if os.path.exists(req_file):
            try:
                subprocess.run(
                    [sys.executable, "-m", "pip", "install", "-r", req_file, "--quiet"],
                    capture_output=True, timeout=120,
                )
            except Exception as e:
                logger.warning(f"Failed to install extension python dependencies: {e}")

        # Install Node.js dependencies if package.json exists
        pkg_file = os.path.join(target_dir, "package.json")
        if os.path.exists(pkg_file):
            try:
                print(f"📦 Installing Node.js dependencies for {manifest['name']}...")
                _run_node_tool("npm", ["install", "--no-audit", "--no-fund"],
                               cwd=target_dir, timeout=180,
                               label=f"{manifest['name']} node deps")

                # Check if playwright is a dependency and install its browsers
                with open(pkg_file, "r", encoding="utf-8") as f:
                    pkg_data = json.load(f)
                    deps = {**pkg_data.get("dependencies", {}), **pkg_data.get("devDependencies", {})}
                    
                    if "playwright" in deps or "playwright-with-fingerprints" in deps:
                        print(f"🎭 Installing Playwright browsers for {manifest['name']}...")
                        _run_node_tool("npx", ["playwright", "install", "chromium"],
                                       cwd=target_dir, timeout=300,
                                       label=f"{manifest['name']} playwright browsers")
                    
            except Exception as e:
                logger.warning(f"Failed to install extension node dependencies: {e}")

        # Load the extension
        extension = self._load_external_extension(target_dir, manifest)
        if not extension:
            shutil.rmtree(target_dir, ignore_errors=True)
            return {"status": "error", "message": "Failed to load extension module."}

        # Register and enable
        self.register(extension)
        extension.on_install()
        self.enable(extension.name)

        return {
            "status": "success",
            "extension": extension.to_dict(),
            "message": f"Extension '{extension.name}' v{extension.version} installed and enabled.",
        }

    def update_extension(self, name: str) -> dict:
        """Update an external extension from Git and reinstall dependencies."""
        extension = self._extensions.get(name)
        if not extension:
            # Try slugified version
            normalized = name.replace(" ", "_").lower()
            extension = self._extensions.get(normalized)
            
        if not extension:
            # Try case-insensitive name or display name comparison
            for e in self.get_all():
                if e.name.lower() == name.lower():
                    extension = e
                    break
                manifest = e.get_manifest()
                if manifest.get("display_name", "").lower() == name.lower():
                    extension = e
                    break
                if manifest.get("name", "").lower() == name.lower():
                    extension = e
                    break

        if not extension:
            return {"status": "error", "message": f"Extension '{name}' not found."}

        # Normalize name for subsequent operations
        name = extension.name

        if extension.extension_type != "external":
            return {"status": "error", "message": f"Cannot update system extension '{name}'."}

        target_dir = extension.extension_dir
        if not target_dir or not os.path.exists(target_dir):
            return {"status": "error", "message": "Extension directory not found."}

        # Update via Git if .git is present
        git_dir = os.path.join(target_dir, ".git")
        if os.path.exists(git_dir):
            try:
                logger.info(f"Updating extension '{name}' via git stash & pull...")
                # Safe Git update sequence
                subprocess.run(["git", "stash"], cwd=target_dir, capture_output=True, timeout=30)
                
                branch = get_git_tracking_branch(target_dir)
                result = subprocess.run(
                    ["git", "pull", "origin", branch],
                    cwd=target_dir, capture_output=True, text=True, timeout=120
                )
                
                subprocess.run(["git", "stash", "pop"], cwd=target_dir, capture_output=True, timeout=30)
                
                if result.returncode != 0:
                    return {"status": "error", "message": f"Git pull failed: {result.stderr}"}
            except Exception as e:
                return {"status": "error", "message": f"Git pull error: {e}"}
        else:
            return {"status": "error", "message": "Currently only extensions installed via Git can be updated."}

        # Install Python dependencies if requirements.txt exists
        req_file = os.path.join(target_dir, "requirements.txt")
        if os.path.exists(req_file):
            try:
                subprocess.run(
                    [sys.executable, "-m", "pip", "install", "-r", req_file, "--quiet"],
                    capture_output=True, timeout=120,
                )
            except Exception as e:
                logger.warning(f"Failed to install extension python dependencies during update: {e}")

        # Install Node.js dependencies if package.json exists
        pkg_file = os.path.join(target_dir, "package.json")
        if os.path.exists(pkg_file):
            try:
                print(f"📦 Updating Node.js dependencies for {name}...")
                _run_node_tool("npm", ["install", "--no-audit", "--no-fund"],
                               cwd=target_dir, timeout=180,
                               label=f"{name} node deps update")
            except Exception as e:
                logger.warning(f"Failed to update node dependencies: {e}")

        # Reload extension
        manifest_file = os.path.join(target_dir, "tubecli-extension.json")
        if not os.path.exists(manifest_file):
            return {"status": "error", "message": "manifest not found after update"}

        try:
            with open(manifest_file, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            
            was_enabled = extension.enabled
            self.disable(name)
            
            reloaded_ext = self._load_external_extension(target_dir, manifest)
            if not reloaded_ext:
                return {"status": "error", "message": "Failed to reload extension module."}
                
            self.register(reloaded_ext)
            if was_enabled:
                self.enable(name)
                
            return {
                "status": "success",
                "extension": reloaded_ext.to_dict(),
                "message": f"Extension '{name}' updated successfully to v{reloaded_ext.version}.",
            }
        except Exception as e:
            return {"status": "error", "message": f"Error reloading extension: {e}"}

    def uninstall(self, name: str) -> dict:
        """Remove an external extension.

        Returns: {"status": "success"|"error", "message": ...}
        """
        extension = self._extensions.get(name)
        if not extension:
            return {"status": "error", "message": f"Extension '{name}' not found."}

        if extension.extension_type != "external":
            return {"status": "error", "message": f"Cannot uninstall system extension '{name}'. Use disable instead."}

        # Call lifecycle hook
        try:
            extension.on_uninstall()
        except Exception:
            pass

        # Disable first
        self.disable(name)

        # Remove from registry
        del self._extensions[name]

        # Remove config
        if name in self._config:
            del self._config[name]
            self._save_config()

        # Remove directory
        if extension.extension_dir and os.path.isdir(extension.extension_dir):
            try:
                shutil.rmtree(extension.extension_dir)
            except Exception as e:
                return {"status": "error", "message": f"Extension disabled but failed to remove directory: {e}"}

        return {"status": "success", "message": f"Extension '{name}' uninstalled."}


# Global singleton
extension_manager = ExtensionManager()
