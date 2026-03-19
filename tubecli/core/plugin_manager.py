"""
TubeCLI Plugin System
Enhanced plugin architecture with git-based install, external discovery,
SKILL.md for AI guidance, and plugin-provided workflow nodes.
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
from tubecli.config import DATA_DIR, PLUGINS_EXTERNAL_DIR

logger = logging.getLogger('PluginManager')

PLUGINS_CONFIG_FILE = os.path.join(DATA_DIR, "plugins.json")

# ── Plugin Manifest Schema ────────────────────────────────────────

REQUIRED_MANIFEST_FIELDS = ["name", "version", "description", "entry", "plugin_class"]

MANIFEST_TEMPLATE = {
    "name": "",
    "version": "1.0.0",
    "description": "",
    "author": "",
    "entry": "plugin.py",
    "plugin_class": "",
    "dependencies": [],
    "nodes": [],
    "skill_md": "SKILL.md",
    "ui_static": "",
    "api_prefix": "",
    "min_tubecli_version": "0.1.0",
}


def validate_manifest(manifest: dict) -> List[str]:
    """Validate a tubecli-plugin.json manifest. Returns list of errors."""
    errors = []
    for field in REQUIRED_MANIFEST_FIELDS:
        if not manifest.get(field):
            errors.append(f"Missing required field: '{field}'")
    if manifest.get("name") and not manifest["name"].replace("_", "").replace("-", "").isalnum():
        errors.append(f"Invalid plugin name: '{manifest['name']}' (use alphanumeric, -, _)")
    return errors


# ── Plugin Base Class ─────────────────────────────────────────────

class Plugin:
    """Base class for all TubeCLI plugins."""
    name: str = "base_plugin"
    version: str = "0.1.0"
    description: str = ""
    author: str = ""
    default_port: Optional[int] = None
    plugin_type: str = "system"       # "system" | "external"
    plugin_dir: Optional[str] = None  # absolute path to plugin directory

    def __init__(self):
        self.enabled = False
        self.current_port: Optional[int] = self.default_port
        self._routes = []
        self._commands = []
        self._manifest: dict = {}

    # ── Lifecycle Hooks ──────────────────────────────────────

    def on_install(self):
        """Called when plugin is first installed."""
        pass

    def on_enable(self):
        """Called when plugin is enabled."""
        pass

    def on_disable(self):
        """Called when plugin is disabled."""
        pass

    def on_uninstall(self):
        """Called before plugin is removed."""
        pass

    # ── Extension Points ─────────────────────────────────────

    def get_routes(self):
        """Return FastAPI router for API routes."""
        return None

    def get_commands(self):
        """Return Click command group for CLI commands."""
        return None

    def get_nodes(self) -> Dict[str, Any]:
        """Return dict of {node_type: NodeClass} this plugin provides."""
        return {}

    def get_skill_md(self) -> Optional[str]:
        """Return SKILL.md content for AI guidance."""
        if self.plugin_dir:
            skill_md_path = os.path.join(self.plugin_dir, "SKILL.md")
            if os.path.exists(skill_md_path):
                try:
                    with open(skill_md_path, "r", encoding="utf-8") as f:
                        return f.read()
                except Exception:
                    pass
        return None

    def get_ui_static_dir(self) -> Optional[str]:
        """Return absolute path to plugin's static UI directory."""
        if self.plugin_dir:
            static_dir = os.path.join(self.plugin_dir, "static")
            if os.path.isdir(static_dir):
                return static_dir
        return None

    def get_manifest(self) -> dict:
        """Return plugin manifest data."""
        return self._manifest or {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "plugin_type": self.plugin_type,
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
            "plugin_type": self.plugin_type,
            "plugin_dir": self.plugin_dir,
            "has_skill_md": self.get_skill_md() is not None,
            "has_nodes": bool(self.get_nodes()),
            "has_ui": self.get_ui_static_dir() is not None,
        }


# ── Plugin Manager ────────────────────────────────────────────────

class PluginManager:
    """Discovers, loads, and manages plugins (built-in + external)."""

    # Built-in system plugins to discover
    BUILTIN_PLUGINS = [
        "tubecli.plugins.browser",
        "tubecli.plugins.webui",
        "tubecli.plugins.market",
        "tubecli.plugins.cloud_api",
        "tubecli.plugins.ollama_manager",
        "tubecli.plugins.multi_agents",
    ]

    def __init__(self):
        self._plugins: Dict[str, Plugin] = {}
        self._config: Dict[str, Any] = {}
        self._load_config()

    def _load_config(self):
        try:
            if os.path.exists(PLUGINS_CONFIG_FILE):
                with open(PLUGINS_CONFIG_FILE, "r", encoding="utf-8") as f:
                    self._config = json.load(f)
        except Exception:
            self._config = {}

    def _save_config(self):
        os.makedirs(os.path.dirname(PLUGINS_CONFIG_FILE), exist_ok=True)
        with open(PLUGINS_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(self._config, f, indent=2, ensure_ascii=False)

    # ── Discovery ────────────────────────────────────────────

    def discover_plugins(self):
        """Auto-discover all plugins: built-in system + external."""
        # 1. Built-in system plugins
        for module_path in self.BUILTIN_PLUGINS:
            try:
                mod = importlib.import_module(module_path)
                if hasattr(mod, "plugin_instance"):
                    plugin = mod.plugin_instance
                    plugin.plugin_type = "system"
                    if not plugin.plugin_dir:
                        plugin.plugin_dir = os.path.dirname(
                            getattr(mod, "__file__", "")
                        )
                    self.register(plugin)
            except ImportError as e:
                logger.debug(f"Plugin {module_path} not available: {e}")
            except Exception as e:
                logger.error(f"Error loading plugin {module_path}: {e}")

        # 2. External plugins (git-installed)
        self.discover_external_plugins()

    def discover_external_plugins(self):
        """Scan data/plugins_external/ for installed external plugins."""
        ext_dir = str(PLUGINS_EXTERNAL_DIR)
        if not os.path.isdir(ext_dir):
            return

        for entry in os.listdir(ext_dir):
            plugin_path = os.path.join(ext_dir, entry)
            if not os.path.isdir(plugin_path):
                continue

            manifest_file = os.path.join(plugin_path, "tubecli-plugin.json")
            if not os.path.exists(manifest_file):
                logger.debug(f"Skipping {entry}: no tubecli-plugin.json")
                continue

            try:
                with open(manifest_file, "r", encoding="utf-8") as f:
                    manifest = json.load(f)

                errors = validate_manifest(manifest)
                if errors:
                    logger.error(f"Invalid manifest in {entry}: {errors}")
                    continue

                # Already loaded?
                if manifest["name"] in self._plugins:
                    continue

                # Load plugin module dynamically
                plugin = self._load_external_plugin(plugin_path, manifest)
                if plugin:
                    self.register(plugin)

            except Exception as e:
                logger.error(f"Error loading external plugin {entry}: {e}")

    def _load_external_plugin(self, plugin_path: str, manifest: dict) -> Optional[Plugin]:
        """Dynamically load an external plugin from its directory."""
        entry_file = os.path.join(plugin_path, manifest["entry"])
        if not os.path.exists(entry_file):
            logger.error(f"Entry file not found: {entry_file}")
            return None

        plugin_name = manifest["name"]
        module_name = f"tubecli_ext_{plugin_name}"

        try:
            # Add plugin path to sys.path temporarily
            if plugin_path not in sys.path:
                sys.path.insert(0, plugin_path)

            spec = importlib.util.spec_from_file_location(module_name, entry_file)
            if not spec or not spec.loader:
                logger.error(f"Cannot create module spec for {entry_file}")
                return None

            mod = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = mod
            spec.loader.exec_module(mod)

            # Get the plugin class
            cls_name = manifest["plugin_class"]
            if not hasattr(mod, cls_name):
                logger.error(f"Plugin class '{cls_name}' not found in {entry_file}")
                return None

            plugin_cls = getattr(mod, cls_name)
            plugin = plugin_cls()
            plugin.plugin_type = "external"
            plugin.plugin_dir = plugin_path
            plugin._manifest = manifest
            plugin.name = manifest["name"]
            plugin.version = manifest.get("version", "0.1.0")
            plugin.description = manifest.get("description", "")
            plugin.author = manifest.get("author", "")

            return plugin

        except Exception as e:
            logger.error(f"Error loading external plugin {plugin_name}: {e}")
            return None

    # ── Registration ─────────────────────────────────────────

    def register(self, plugin: Plugin):
        """Register a plugin instance."""
        self._plugins[plugin.name] = plugin

        # Restore config (port, enabled)
        cfg = self._config.get(plugin.name, {})
        if "port" in cfg:
            plugin.current_port = cfg["port"]

        if cfg.get("enabled", False):
            plugin.enabled = True
            try:
                plugin.on_enable()
            except Exception as e:
                logger.error(f"Error enabling plugin {plugin.name}: {e}")

    # ── Enable / Disable ─────────────────────────────────────

    def enable(self, name: str) -> bool:
        plugin = self._plugins.get(name)
        if not plugin:
            return False
        plugin.enabled = True
        plugin.on_enable()
        self._config.setdefault(name, {})["enabled"] = True
        self._save_config()
        return True

    def disable(self, name: str) -> bool:
        plugin = self._plugins.get(name)
        if not plugin:
            return False
        plugin.enabled = False
        plugin.on_disable()
        self._config.setdefault(name, {})["enabled"] = False
        self._save_config()
        return True

    # ── Getters ──────────────────────────────────────────────

    def get(self, name: str) -> Optional[Plugin]:
        return self._plugins.get(name)

    def get_all(self) -> List[Plugin]:
        return list(self._plugins.values())

    def get_enabled(self) -> List[Plugin]:
        return [p for p in self._plugins.values() if p.enabled]

    def set_port(self, name: str, port: int) -> bool:
        plugin = self._plugins.get(name)
        if not plugin:
            return False
        plugin.current_port = port
        self._config.setdefault(name, {})["port"] = port
        self._save_config()
        return True

    # ── CLI / API Registration ───────────────────────────────

    def register_cli_commands(self, cli_group):
        """Register all enabled plugin CLI commands to the main CLI group."""
        for plugin in self.get_enabled():
            try:
                cmds = plugin.get_commands()
                if cmds:
                    cli_group.add_command(cmds)
            except Exception as e:
                logger.error(f"Error registering CLI for {plugin.name}: {e}")

    def register_api_routes(self, app):
        """Register all enabled plugin API routes to the FastAPI app."""
        for plugin in self.get_enabled():
            try:
                router = plugin.get_routes()
                if router:
                    app.include_router(router)
            except Exception as e:
                logger.error(f"Error registering API for {plugin.name}: {e}")

    # ── Plugin Nodes Registration ────────────────────────────

    def register_plugin_nodes(self, node_registry: dict):
        """Merge all enabled plugins' nodes into the global NODE_REGISTRY."""
        for plugin in self.get_enabled():
            try:
                nodes = plugin.get_nodes()
                if nodes:
                    for node_type, node_cls in nodes.items():
                        if node_type not in node_registry:
                            node_registry[node_type] = node_cls
                            logger.info(f"Registered node '{node_type}' from plugin '{plugin.name}'")
            except Exception as e:
                logger.error(f"Error registering nodes for {plugin.name}: {e}")

    # ── SKILL.md Collection ──────────────────────────────────

    def get_all_skill_mds(self) -> List[dict]:
        """Collect all SKILL.md content from enabled plugins for AI agents."""
        results = []
        for plugin in self.get_enabled():
            try:
                content = plugin.get_skill_md()
                if content:
                    results.append({
                        "plugin": plugin.name,
                        "version": plugin.version,
                        "skill_md": content,
                    })
            except Exception:
                pass
        return results

    # ── Git Install / Uninstall ──────────────────────────────

    def install_from_git(self, git_url: str) -> dict:
        """Clone a plugin from git URL, validate, and register.

        Returns: {"status": "success"|"error", "plugin": ..., "message": ...}
        """
        ext_dir = str(PLUGINS_EXTERNAL_DIR)
        os.makedirs(ext_dir, exist_ok=True)

        # Extract repo name from URL
        repo_name = git_url.rstrip("/").split("/")[-1]
        if repo_name.endswith(".git"):
            repo_name = repo_name[:-4]

        target_dir = os.path.join(ext_dir, repo_name)

        # Check if already installed
        if os.path.isdir(target_dir):
            return {"status": "error", "message": f"Plugin directory '{repo_name}' already exists. Uninstall first."}

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
        manifest_file = os.path.join(target_dir, "tubecli-plugin.json")
        if not os.path.exists(manifest_file):
            shutil.rmtree(target_dir, ignore_errors=True)
            return {"status": "error", "message": "No tubecli-plugin.json found in repository."}

        try:
            with open(manifest_file, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception as e:
            shutil.rmtree(target_dir, ignore_errors=True)
            return {"status": "error", "message": f"Invalid tubecli-plugin.json: {e}"}

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
                logger.warning(f"Failed to install plugin dependencies: {e}")

        # Load the plugin
        plugin = self._load_external_plugin(target_dir, manifest)
        if not plugin:
            shutil.rmtree(target_dir, ignore_errors=True)
            return {"status": "error", "message": "Failed to load plugin module."}

        # Register and enable
        self.register(plugin)
        plugin.on_install()
        self.enable(plugin.name)

        return {
            "status": "success",
            "plugin": plugin.to_dict(),
            "message": f"Plugin '{plugin.name}' v{plugin.version} installed and enabled.",
        }

    def uninstall(self, name: str) -> dict:
        """Remove an external plugin.

        Returns: {"status": "success"|"error", "message": ...}
        """
        plugin = self._plugins.get(name)
        if not plugin:
            return {"status": "error", "message": f"Plugin '{name}' not found."}

        if plugin.plugin_type != "external":
            return {"status": "error", "message": f"Cannot uninstall system plugin '{name}'. Use disable instead."}

        # Call lifecycle hook
        try:
            plugin.on_uninstall()
        except Exception:
            pass

        # Disable first
        self.disable(name)

        # Remove from registry
        del self._plugins[name]

        # Remove config
        if name in self._config:
            del self._config[name]
            self._save_config()

        # Remove directory
        if plugin.plugin_dir and os.path.isdir(plugin.plugin_dir):
            try:
                shutil.rmtree(plugin.plugin_dir)
            except Exception as e:
                return {"status": "error", "message": f"Plugin disabled but failed to remove directory: {e}"}

        return {"status": "success", "message": f"Plugin '{name}' uninstalled."}


# Global singleton
plugin_manager = PluginManager()
