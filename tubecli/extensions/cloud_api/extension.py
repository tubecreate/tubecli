"""
Cloud API Extension — Manages cloud AI providers and API keys.
Provides key storage, rotation, validation, usage tracking, and provider health checks.
"""
import os
import json
import logging
from typing import Dict, List, Optional
from tubecli.core.extension_manager import Extension
from tubecli.config import DATA_DIR

logger = logging.getLogger("CloudApiExtension")

CLOUD_API_DATA_FILE = os.path.join(DATA_DIR, "cloud_api_keys.json")

# ── Supported Providers ──────────────────────────────────────────

PROVIDERS = {
    "gemini": {
        "name": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com",
        "models": ["gemini-2.0-flash", "gemini-2.0-pro", "gemini-1.5-flash", "gemini-1.5-pro"],
        "env_var": "GEMINI_API_KEY",
    },
    "openai": {
        "name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "o1", "o3-mini"],
        "env_var": "OPENAI_API_KEY",
    },
    "claude": {
        "name": "Anthropic Claude",
        "base_url": "https://api.anthropic.com/v1",
        "models": ["claude-sonnet-4-20250514", "claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022"],
        "env_var": "ANTHROPIC_API_KEY",
    },
    "deepseek": {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "models": ["deepseek-chat", "deepseek-coder", "deepseek-reasoner"],
        "env_var": "DEEPSEEK_API_KEY",
    },
    "grok": {
        "name": "xAI Grok",
        "base_url": "https://api.x.ai/v1",
        "models": ["grok-2", "grok-2-mini"],
        "env_var": "XAI_API_KEY",
    },
}


class KeyManager:
    """Manages API keys for cloud providers."""

    def __init__(self, data_file: str = CLOUD_API_DATA_FILE):
        self.data_file = data_file
        self._keys: Dict[str, dict] = {}
        self._load()

    def _load(self):
        try:
            if os.path.exists(self.data_file):
                with open(self.data_file, "r", encoding="utf-8") as f:
                    self._keys = json.load(f)
        except Exception:
            self._keys = {}

    def _save(self):
        os.makedirs(os.path.dirname(self.data_file), exist_ok=True)
        with open(self.data_file, "w", encoding="utf-8") as f:
            json.dump(self._keys, f, indent=2, ensure_ascii=False)

    def add_key(self, provider: str, api_key: str, label: str = "default") -> dict:
        """Add or update an API key for a provider."""
        if provider not in PROVIDERS:
            return {"status": "error", "message": f"Unknown provider: {provider}. Available: {list(PROVIDERS.keys())}"}

        self._keys.setdefault(provider, {})[label] = {
            "key": api_key,
            "active": True,
            "added_at": __import__("datetime").datetime.now().isoformat(),
        }
        self._save()
        return {"status": "success", "message": f"Key '{label}' added for {provider}."}

    def remove_key(self, provider: str, label: str = "default") -> dict:
        if provider in self._keys and label in self._keys[provider]:
            del self._keys[provider][label]
            if not self._keys[provider]:
                del self._keys[provider]
            self._save()
            return {"status": "success", "message": f"Key '{label}' removed from {provider}."}
        return {"status": "error", "message": f"Key '{label}' not found for {provider}."}

    def get_key(self, provider: str, label: str = "default") -> Optional[str]:
        """Get an API key. Falls back to env var if no stored key."""
        entry = self._keys.get(provider, {}).get(label)
        if entry and entry.get("active"):
            return entry["key"]
        # Fallback: environment variable
        env_var = PROVIDERS.get(provider, {}).get("env_var", "")
        if env_var:
            return os.environ.get(env_var)
        return None

    def get_active_key(self, provider: str) -> Optional[str]:
        """Get any active key for a provider (round-robin ready)."""
        entries = self._keys.get(provider, {})
        for label, entry in entries.items():
            if entry.get("active"):
                return entry["key"]
        # Fallback: env var
        env_var = PROVIDERS.get(provider, {}).get("env_var", "")
        return os.environ.get(env_var) if env_var else None

    def list_keys(self, provider: str = None) -> dict:
        """List all stored keys (masked)."""
        result = {}
        sources = {provider: self._keys.get(provider, {})} if provider else self._keys
        for prov, keys in sources.items():
            result[prov] = {}
            for label, entry in keys.items():
                key_val = entry.get("key", "")
                masked = key_val[:6] + "..." + key_val[-4:] if len(key_val) > 10 else "***"
                result[prov][label] = {
                    "masked_key": masked,
                    "active": entry.get("active", False),
                    "added_at": entry.get("added_at", ""),
                }
        return result

    def list_providers(self) -> List[dict]:
        """List all supported providers with their status."""
        result = []
        for prov_id, prov_info in PROVIDERS.items():
            has_key = self.get_active_key(prov_id) is not None
            result.append({
                "id": prov_id,
                "name": prov_info["name"],
                "models": prov_info["models"],
                "has_key": has_key,
                "key_count": len(self._keys.get(prov_id, {})),
            })
        return result

    def test_key(self, provider: str, label: str = "default") -> dict:
        """Test if an API key is valid by making a lightweight API call."""
        key = self.get_key(provider, label)
        if not key:
            return {"status": "error", "message": f"No key found for {provider}/{label}."}

        try:
            import requests
            prov_info = PROVIDERS.get(provider, {})

            if provider == "gemini":
                url = f"https://generativelanguage.googleapis.com/v1beta/models?key={key}"
                resp = requests.get(url, timeout=10)
                if resp.status_code == 200:
                    return {"status": "success", "message": f"Gemini key is valid. Models: {len(resp.json().get('models', []))}"}
                return {"status": "error", "message": f"Gemini key invalid: {resp.status_code}"}

            elif provider == "openai":
                resp = requests.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {key}"},
                    timeout=10,
                )
                if resp.status_code == 200:
                    return {"status": "success", "message": f"OpenAI key is valid."}
                return {"status": "error", "message": f"OpenAI key error: {resp.status_code}"}

            elif provider == "claude":
                # Claude doesn't have a simple list endpoint, use a minimal message
                return {"status": "info", "message": "Claude key stored. Validation requires a message call."}

            elif provider == "deepseek":
                resp = requests.get(
                    "https://api.deepseek.com/v1/models",
                    headers={"Authorization": f"Bearer {key}"},
                    timeout=10,
                )
                if resp.status_code == 200:
                    return {"status": "success", "message": f"DeepSeek key is valid."}
                return {"status": "error", "message": f"DeepSeek key error: {resp.status_code}"}

            else:
                return {"status": "info", "message": f"Key stored for {provider}. No auto-validation available."}

        except Exception as e:
            return {"status": "error", "message": f"Test failed: {e}"}


# Global singleton
key_manager = KeyManager()


class CloudApiExtension(Extension):
    name = "cloud_api"
    version = "0.1.0"
    description = "Manage cloud AI providers (Gemini, OpenAI, Claude, DeepSeek, Grok) and API keys"
    author = "TubeCreate"
    extension_type = "system"

    def on_enable(self):
        # Ensure data file directory exists
        os.makedirs(os.path.dirname(CLOUD_API_DATA_FILE), exist_ok=True)

    def get_commands(self):
        from tubecli.extensions.cloud_api.commands import cloud_api_group
        return cloud_api_group

    def get_routes(self):
        from tubecli.extensions.cloud_api.routes import router
        return router
