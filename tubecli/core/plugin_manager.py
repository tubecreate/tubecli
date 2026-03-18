"""
TubeCLI Plugin System
Base classes and plugin manager for extensible architecture.
"""
import os
import json
import logging
import importlib
from typing import Dict, List, Optional, Any
from pathlib import Path
from tubecli.config import DATA_DIR

logger = logging.getLogger('PluginManager')

PLUGINS_CONFIG_FILE = os.path.join(DATA_DIR, "plugins.json")


class Plugin:
    """Base class for all TubeCLI plugins."""
    name: str = "base_plugin"
    version: str = "0.1.0"
    description: str = ""
    author: str = ""
    default_port: Optional[int] = None

    def __init__(self):
        self.enabled = False
        self.current_port: Optional[int] = self.default_port
        self._routes = []
        self._commands = []

    def on_install(self):
        """Called when plugin is first installed."""
        pass

    def on_enable(self):
        """Called when plugin is enabled."""
        pass

    def on_disable(self):
        """Called when plugin is disabled."""
        pass

    def get_routes(self):
        """Return FastAPI router for API routes."""
        return None

    def get_commands(self):
        """Return Click command group for CLI commands."""
        return None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "enabled": self.enabled,
            "default_port": self.default_port,
            "current_port": self.current_port,
        }


class PluginManager:
    """Discovers, loads, and manages plugins."""

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

    def discover_plugins(self):
        """Auto-discover built-in plugins from tubecli.plugins package."""
        plugin_modules = [
            "tubecli.plugins.browser",
            "tubecli.plugins.webui",
            "tubecli.plugins.market",
        ]
        for module_path in plugin_modules:
            try:
                mod = importlib.import_module(module_path)
                if hasattr(mod, "plugin_instance"):
                    plugin = mod.plugin_instance
                    self.register(plugin)
            except ImportError as e:
                logger.debug(f"Plugin {module_path} not available: {e}")
            except Exception as e:
                logger.error(f"Error loading plugin {module_path}: {e}")

    def register(self, plugin: Plugin):
        """Register a plugin instance."""
        self._plugins[plugin.name] = plugin
        
        # Restore port from config if custom
        cfg = self._config.get(plugin.name, {})
        if "port" in cfg:
            plugin.current_port = cfg["port"]
            
        # Restore enabled state from config
        if cfg.get("enabled", False):
            plugin.enabled = True
            try:
                plugin.on_enable()
            except Exception as e:
                logger.error(f"Error enabling plugin {plugin.name}: {e}")

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


# Global singleton
plugin_manager = PluginManager()
