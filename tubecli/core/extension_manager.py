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
            "has_skill_md": self.get_skill_md() is not None,
            "has_nodes": bool(self.get_nodes()),
            "has_ui": self.get_ui_static_dir() is not None,
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
    ]

    # Essential external extensions to auto-install if missing
    ESSENTIAL_EXTENSIONS = [
        {
            "name": "browser",
            "git_url": "https://github.com/tubecreate/browser-control.git"
        }
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
                            with open(manifest_file, "r", encoding="utf-8") as f:
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
                with open(manifest_file, "r", encoding="utf-8") as f:
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
            extension.version = manifest.get("version", "0.1.0")
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
        extension.enabled = True
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

    def register_api_routes(self, app):
        """Register all enabled extension API routes to the FastAPI app."""
        for extension in self.get_enabled():
            try:
                router = extension.get_routes()
                if router:
                    app.include_router(router)
            except Exception as e:
                logger.error(f"Error registering API for {extension.name}: {e}")

    # ── Extension Nodes Registration ────────────────────────────

    def register_extension_nodes(self, node_registry: dict):
        """Merge all enabled extensions' nodes into the global NODE_REGISTRY."""
        for extension in self.get_enabled():
            try:
                nodes = extension.get_nodes()
                if nodes:
                    for node_type, node_cls in nodes.items():
                        if node_type not in node_registry:
                            node_registry[node_type] = node_cls
                            logger.info(f"Registered node '{node_type}' from extension '{extension.name}'")
            except Exception as e:
                logger.error(f"Error registering nodes for {extension.name}: {e}")

    # ── SKILL.md Collection ──────────────────────────────────

    def get_all_skill_mds(self) -> List[dict]:
        """Collect all SKILL.md content from enabled extensions for AI agents."""
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
        return results

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

        target_dir = os.path.join(ext_dir, repo_name)

        # Check if already installed
        if os.path.isdir(target_dir):
            return {"status": "error", "message": f"Extension directory '{repo_name}' already exists. Uninstall first."}

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
            with open(manifest_file, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception as e:
            shutil.rmtree(target_dir, ignore_errors=True)
            return {"status": "error", "message": f"Invalid tubecli-extension.json: {e}"}

        errors = validate_manifest(manifest)
        if errors:
            shutil.rmtree(target_dir, ignore_errors=True)
            return {"status": "error", "message": f"Manifest validation failed: {'; '.join(errors)}"}

        # Install Python dependencies if requirements.txt exists
        req_file = os.path.join(target_dir, "requirements.txt")
        if os.path.exists(req_file):
            try:
                subprocess.run(
                    [sys.executable, "-m", "pip", "install", "-r", req_file, "--quiet"],
                    capture_output=True, timeout=120,
                )
            except Exception as e:
                logger.warning(f"Failed to install extension dependencies: {e}")

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
