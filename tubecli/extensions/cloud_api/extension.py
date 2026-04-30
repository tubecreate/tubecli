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
        "models": ["gemini-2.5-flash", "gemini-2.5-pro"],
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
    "openrouter": {
        "name": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "models": [
            "anthropic/claude-haiku-4.5",
            "anthropic/claude-opus-4.6",
            "anthropic/claude-sonnet-4.5",
            "anthropic/claude-sonnet-4.6",
            "deepseek/deepseek-r1",
            "google/gemini-2.5-flash-lite",
            "google/gemini-3-flash-preview",
            "google/gemini-3-pro-preview",
            "google/gemini-3.1-pro-preview",
            "meta-llama/llama-3.3-70b-instruct",
            "minimax/minimax-m2.5",
            "mistralai/codestral-2508",
            "mistralai/mistral-7b-instruct-v0.1",
            "mistralai/mistral-large",
            "mistralai/mistral-medium-3.1",
            "mistralai/mistral-small-3.2-24b-instruct-2506",
            "moonshotai/kimi-k2-thinking",
            "openai/gpt-5",
            "openai/gpt-5-mini",
            "openai/gpt-5-nano",
            "openai/gpt-5.1",
            "openai/gpt-5.2",
            "openai/gpt-5.2-pro",
            "openai/gpt-5.3-chat",
            "openai/gpt-oss-120b",
            "perplexity/sonar",
            "qwen/qwen3-235b-a22b",
            "x-ai/grok-3",
            "x-ai/grok-3-mini",
            "x-ai/grok-4",
            "x-ai/grok-4.1-fast",
            "z-ai/glm-5"
        ],
        "env_var": "OPENROUTER_API_KEY",
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
                # Migrate legacy plain-string keys to proper {label: {key, active}} format
                migrated = False
                for provider in list(self._keys.keys()):
                    if provider.startswith("_"):
                        continue
                    value = self._keys[provider]
                    if isinstance(value, str) and value:
                        import datetime as _dt
                        self._keys[provider] = {
                            "default": {
                                "key": value,
                                "active": True,
                                "added_at": _dt.datetime.now().isoformat(),
                            }
                        }
                        migrated = True
                        logger.info(f"Migrated legacy string key for '{provider}' to proper format.")
                if migrated:
                    self._save()
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
        self._load()
        entry = self._keys.get(provider, {}).get(label)
        if entry and entry.get("active"):
            return entry["key"]
        # Fallback: environment variable
        env_var = PROVIDERS.get(provider, {}).get("env_var", "")
        if env_var:
            return os.environ.get(env_var)
        return None

    def get_models(self, provider: str) -> List[str]:
        """Get models for a provider, merging defaults with custom settings."""
        self._load()
        default_models = PROVIDERS.get(provider, {}).get("models", [])
        custom_models = self._keys.get("_settings", {}).get(provider, {}).get("models")
        return custom_models if custom_models is not None else default_models

    def set_models(self, provider: str, models: List[str]) -> dict:
        """Save a custom list of models for a provider."""
        if provider not in PROVIDERS:
            return {"status": "error", "message": f"Unknown provider: {provider}"}
        settings = self._keys.setdefault("_settings", {})
        prov_settings = settings.setdefault(provider, {})
        prov_settings["models"] = models
        self._save()
        return {"status": "success", "message": f"Models updated for {provider}"}

    def report_key_error(self, provider: str, api_key: str, error_msg: str = "Quota Exceeded") -> None:
        """Mark a key as inactive due to an error (e.g., 429 Too Many Requests)."""
        self._load()
        entries = self._keys.get(provider, {})
        for label, entry in entries.items():
            if entry.get("key") == api_key:
                entry["active"] = False
                entry["status_msg"] = error_msg
                self._save()
                logger.warning(f"Key '{label}' for {provider} disabled automatically. Reason: {error_msg}")
                return

    def get_active_key(self, provider: str) -> Optional[str]:
        """Get any active key for a provider (round-robin ready)."""
        self._load()
        entries = self._keys.get(provider, {})
        # Guard: legacy plain-string key
        if isinstance(entries, str) and entries:
            return entries
        if isinstance(entries, dict):
            for label, entry in entries.items():
                if isinstance(entry, dict) and entry.get("active"):
                    return entry["key"]
        # Fallback: env var
        env_var = PROVIDERS.get(provider, {}).get("env_var", "")
        return os.environ.get(env_var) if env_var else None

    def list_keys(self, provider: str = None) -> dict:
        """List all stored keys (masked) with their extended status."""
        self._load()
        result = {}
        # Ignore _settings key
        sources = {p: self._keys[p] for p in self._keys if p != "_settings"}
        if provider:
            sources = {provider: sources.get(provider, {})}
            
        for prov, keys in sources.items():
            result[prov] = {}
            # Guard: legacy plain-string key
            if isinstance(keys, str):
                masked = keys[:6] + "..." + keys[-4:] if len(keys) > 10 else "***"
                result[prov]["default"] = {
                    "masked_key": masked,
                    "active": True,
                    "status_msg": "(legacy format)",
                    "added_at": "",
                }
                continue
            if not isinstance(keys, dict):
                continue
            for label, entry in keys.items():
                if not isinstance(entry, dict): continue
                key_val = entry.get("key", "")
                masked = key_val[:6] + "..." + key_val[-4:] if len(key_val) > 10 else "***"
                result[prov][label] = {
                    "masked_key": masked,
                    "active": entry.get("active", False),
                    "status_msg": entry.get("status_msg", ""),
                    "added_at": entry.get("added_at", ""),
                }
        return result

    def list_providers(self) -> List[dict]:
        """List all supported providers with their status and custom models."""
        self._load()
        result = []
        for prov_id, prov_info in PROVIDERS.items():
            has_key = self.get_active_key(prov_id) is not None
            result.append({
                "id": prov_id,
                "name": prov_info["name"],
                "models": self.get_models(prov_id),
                "has_key": has_key,
                "key_count": len(self._keys.get(prov_id, {})) if prov_id in self._keys else 0,
            })
        return result

    def test_key(self, provider: str, label: str = "default") -> dict:
        """Test if an API key is valid by making a lightweight API call."""
        self._load()
        entry = self._keys.get(provider, {}).get(label)
        if not entry or not entry.get("key"):
            return {"status": "error", "message": f"No key found for {provider}/{label}."}
        
        key = entry["key"]

        try:
            import requests
            prov_info = PROVIDERS.get(provider, {})

            if provider == "gemini":
                url = f"https://generativelanguage.googleapis.com/v1beta/models?key={key}"
                resp = requests.get(url, timeout=10)
                if resp.status_code == 200:
                    entry["active"] = True
                    entry["status_msg"] = ""
                    self._save()
                    return {"status": "success", "message": f"Gemini key is valid. Models: {len(resp.json().get('models', []))}"}
                return {"status": "error", "message": f"Gemini key invalid: {resp.status_code}"}

            elif provider == "openai":
                resp = requests.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {key}"},
                    timeout=10,
                )
                if resp.status_code == 200:
                    entry["active"] = True
                    entry["status_msg"] = ""
                    self._save()
                    return {"status": "success", "message": f"OpenAI key is valid."}
                return {"status": "error", "message": f"OpenAI key error: {resp.status_code}"}

            elif provider == "openrouter":
                payload = {
                    "model": "openai/gpt-4o-mini",
                    "messages": [{"role": "user", "content": "Hello"}]
                }
                resp = requests.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json=payload,
                    timeout=15,
                )
                if resp.status_code == 200:
                    entry["active"] = True
                    entry["status_msg"] = ""
                    self._save()
                    return {"status": "success", "message": f"OpenRouter key is valid. API Test OK."}
                
                try:
                    err_json = resp.json()
                    err_msg = err_json.get("error", {}).get("message", "Unknown Error")
                except Exception:
                    err_msg = resp.text[:100]
                    
                return {"status": "error", "message": f"OpenRouter key error {resp.status_code}: {err_msg}"}

            elif provider == "claude":
                # Claude doesn't have a simple list endpoint, use a minimal message
                entry["active"] = True
                entry["status_msg"] = ""
                self._save()
                return {"status": "info", "message": "Claude key stored and activated (Validation requires a message call)."}

            elif provider == "deepseek":
                resp = requests.get(
                    "https://api.deepseek.com/v1/models",
                    headers={"Authorization": f"Bearer {key}"},
                    timeout=10,
                )
                if resp.status_code == 200:
                    entry["active"] = True
                    entry["status_msg"] = ""
                    self._save()
                    return {"status": "success", "message": f"DeepSeek key is valid."}
                return {"status": "error", "message": f"DeepSeek key error: {resp.status_code}"}

            else:
                entry["active"] = True
                entry["status_msg"] = ""
                self._save()
                return {"status": "info", "message": f"Key stored & activated for {provider}. No auto-validation available."}

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
