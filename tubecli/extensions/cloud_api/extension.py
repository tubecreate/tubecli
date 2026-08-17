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

_SALT = "e2b4414788ac0777"

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
        "anthropic_url": "https://api.deepseek.com/anthropic",
        "models": ["deepseek-v4-flash", "deepseek-v4-pro"],
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
    "everai": {
        "name": "EverAI TTS",
        "base_url": "https://everai.vn/api/v1",
        "models": ["tts"],
        "env_var": "EVERAI_API_KEY",
    },
    "9router": {
        "name": "9Router",
        "base_url": "http://localhost:20128/v1",
        "models": [],
        "env_var": "",
        "local": True,
    },
    "github": {
        "name": "GitHub",
        "base_url": "https://api.github.com",
        "models": [],
        "env_var": "GITHUB_TOKEN",
    },
    "cloudflare": {
        "name": "Cloudflare",
        "base_url": "https://api.cloudflare.com/client/v4",
        # Workers AI text-generation models, reached through the account-scoped
        # OpenAI-compatible endpoint /accounts/{id}/ai/v1. Verified live against
        # the models/search API; a subset of the ~26 available, picked for chat.
        "models": [
            "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
            "@cf/meta/llama-4-scout-17b-16e-instruct",
            "@cf/openai/gpt-oss-120b",
            "@cf/openai/gpt-oss-20b",
            "@cf/qwen/qwen3-30b-a3b-fp8",
            "@cf/mistralai/mistral-small-3.1-24b-instruct",
            "@cf/zai-org/glm-5.2",
            "@cf/deepseek-ai/deepseek-r1-distill-qwen-32b",
        ],
        "env_var": "CLOUDFLARE_API_TOKEN",
        "icon": "☁️",
        "description": "Workers AI (chat) + Workers/D1/R2/Pages deployment credentials",
        # Cloudflare uses compound credentials: api_token + account_id
        "compound": True,
        "fields": [
            {"key": "api_token", "label": "API Token", "env": "CLOUDFLARE_API_TOKEN",
             # The comment in website_manager (extension.py:338) is explicit that a
             # dashboard-created token is 40 chars with NO prefix; the old "cfut_"
             # placeholder made a valid token look wrong.
             "placeholder": "40-character API token (no prefix)", "secret": True},
            {"key": "account_id", "label": "Account ID", "env": "CLOUDFLARE_ACCOUNT_ID",
             "placeholder": "32-character hex string", "secret": False},
        ],
    },
}

# What actually consumes a stored key, kept in one place so the dashboard can
# stop showing an "Add" button on a card whose key nothing reads. Anything not
# listed here has a card but no request path — the "API chưa sử dụng được" case.
#   chat   — reaches an LLM through brain._call_provider (must match the loop in
#            core/brain.py that fills cloud_keys)
#   deploy — used by website_manager for wrangler deploys (compound credential)
# A provider can serve more than one purpose, so this maps to a LIST. Cloudflare
# is the case that forced it: one stored credential backs BOTH Workers AI chat
# (brain._call_cloudflare) and website_manager's wrangler deploys — the same
# profile, written from either screen and read by both. Labelling it "chat"
# alone told a website_manager user their deploy credential was a chat key.
PROVIDER_CAPABILITY = {
    "gemini": ["chat"], "openai": ["chat"], "claude": ["chat"], "deepseek": ["chat"],
    "grok": ["chat"], "openrouter": ["chat"], "9router": ["chat"],
    "cloudflare": ["chat", "deploy"],
    # github, everai: registered but no consumer yet -> [] (nothing reads them)
}

# How long a key auto-disabled by a TRANSIENT error (a plain 429) stays out
# before get_active_key is allowed to try it again. Hard quota/billing errors
# ignore this and stay off until re-enabled by hand.
TRANSIENT_COOLDOWN_SECONDS = 15 * 60


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

        # Reload first so a key added here does not clobber a disable written by
        # another path (brain failover, another process) between our load and save.
        self._load()
        self._keys.setdefault(provider, {})[label] = {
            "key": api_key,
            "active": True,
            "verified": False,   # stored, but not checked until Test runs
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

    def report_key_error(self, provider: str, api_key: str, error_msg: str = "Quota Exceeded",
                         transient: bool = False) -> None:
        """Mark a key inactive after an error.

        `transient=True` is for a plain rate-limit (a 429 that will clear on its
        own): the key is parked with a timestamp and get_active_key brings it
        back after TRANSIENT_COOLDOWN_SECONDS. `transient=False` is for a hard
        stop (insufficient_quota / billing) and stays off until re-enabled by
        hand. The old code treated every error as permanent, so one transient
        429 retired a key forever — and with two labels holding the SAME key,
        it disabled only the first and failover retried the identical twin.
        """
        import time as _t
        self._load()
        entries = self._keys.get(provider, {})
        if not isinstance(entries, dict):
            return
        hit = False
        for label, entry in entries.items():
            if isinstance(entry, dict) and entry.get("key") == api_key:
                entry["active"] = False
                entry["status_msg"] = error_msg
                if transient:
                    entry["disabled_at"] = _t.time()
                    entry["disable_reason"] = "transient"
                else:
                    entry.pop("disabled_at", None)
                    entry["disable_reason"] = "hard"
                hit = True
                logger.warning(f"Key '{label}' for {provider} disabled ({'transient' if transient else 'hard'}). Reason: {error_msg}")
        if hit:
            self._save()

    def get_active_key(self, provider: str) -> Optional[str]:
        """Get an active key for a provider, reviving cooled-down transient ones."""
        import time as _t
        self._load()
        entries = self._keys.get(provider, {})
        # Guard: legacy plain-string key
        if isinstance(entries, str) and entries:
            return entries
        if isinstance(entries, dict):
            now = _t.time()
            revived = False
            for label, entry in entries.items():
                if not isinstance(entry, dict) or entry.get("active"):
                    continue
                if entry.get("disable_reason") == "transient" and \
                   now - float(entry.get("disabled_at") or 0) >= TRANSIENT_COOLDOWN_SECONDS:
                    entry["active"] = True
                    entry.pop("status_msg", None)
                    entry.pop("disabled_at", None)
                    entry.pop("disable_reason", None)
                    revived = True
                    logger.info(f"Key '{label}' for {provider} auto-re-enabled after cooldown.")
            if revived:
                self._save()
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
                    # None when the key has never been tested — the dashboard
                    # shows that as "chưa kiểm chứng", distinct from a green
                    # verified state and from a disabled one.
                    "verified": entry.get("verified"),
                    "status_msg": entry.get("status_msg", ""),
                    "disable_reason": entry.get("disable_reason", ""),
                    "added_at": entry.get("added_at", ""),
                }
        return result

    def list_providers(self) -> List[dict]:
        """List all supported providers with their status and custom models.

        Now carries the fields the dashboard needs to stop lying: `capability`
        (so a card with no consumer says so instead of offering a broken Add
        button), `compound`/`fields` (so Cloudflare renders a real two-field
        form instead of a one-key box the backend rejects), plus icon/description.
        """
        self._load()
        result = []
        for prov_id, prov_info in PROVIDERS.items():
            has_key = self.get_active_key(prov_id) is not None or prov_info.get("local", False)
            result.append({
                "id": prov_id,
                "name": prov_info["name"],
                "models": self.get_models(prov_id),
                "has_key": has_key,
                "key_count": len(self._keys.get(prov_id, {})) if isinstance(self._keys.get(prov_id), dict) else 0,
                # `capabilities` is the truth (a provider can do several things);
                # `capability` stays as the first one so anything reading the
                # older single-value field keeps working.
                "capabilities": list(PROVIDER_CAPABILITY.get(prov_id, [])),
                "capability": (PROVIDER_CAPABILITY.get(prov_id) or ["none"])[0],
                "compound": bool(prov_info.get("compound")),
                "fields": prov_info.get("fields", []),
                "local": bool(prov_info.get("local")),
                "icon": prov_info.get("icon", ""),
                "description": prov_info.get("description", ""),
            })
        return result

    def test_key(self, provider: str, label: str = "default") -> dict:
        """Test if an API key is valid by making a lightweight API call.

        The result now carries `verified`: True only when a network call
        actually confirmed the key. Providers with no validation path (claude,
        github, everai…) are stored and marked active but verified=False, so the
        dashboard can show "chưa kiểm chứng" instead of a green "hoạt động" that
        a typo'd key would also earn. The old behaviour marked everything active
        and called it success, which is why a wrong key looked fine until an
        agent died on it.
        """
        # Cloudflare is compound — its credential lives under a different shape
        # and has a real verifier. Route it there and mirror the result.
        if provider == "cloudflare":
            cf = self.test_cloudflare_key(label)
            verified = cf.get("status") == "success"
            entries = self._keys.get("cloudflare", {})
            if isinstance(entries, dict) and label in entries and isinstance(entries[label], dict):
                entries[label]["active"] = True
                entries[label]["verified"] = verified
                entries[label]["status_msg"] = "" if verified else cf.get("message", "")
                self._save()
            return {**cf, "verified": verified}

        self._load()
        entry = self._keys.get(provider, {}).get(label)
        if not entry or not entry.get("key"):
            return {"status": "error", "message": f"No key found for {provider}/{label}."}

        key = entry["key"]

        def ok(msg):
            entry["active"] = True
            entry["verified"] = True
            entry["status_msg"] = ""
            self._save()
            return {"status": "success", "verified": True, "message": msg}

        def stored(msg):
            # Kept, usable, but the truth is we could not check it.
            entry["active"] = True
            entry["verified"] = False
            entry["status_msg"] = ""
            self._save()
            return {"status": "info", "verified": False, "message": msg}

        try:
            import requests

            if provider == "gemini":
                resp = requests.get(f"https://generativelanguage.googleapis.com/v1beta/models?key={key}", timeout=10)
                if resp.status_code == 200:
                    return ok(f"Gemini key is valid. Models: {len(resp.json().get('models', []))}")
                return {"status": "error", "verified": False, "message": f"Gemini key invalid: {resp.status_code}"}

            elif provider == "openai":
                resp = requests.get("https://api.openai.com/v1/models",
                                    headers={"Authorization": f"Bearer {key}"}, timeout=10)
                if resp.status_code == 200:
                    return ok("OpenAI key is valid.")
                return {"status": "error", "verified": False, "message": f"OpenAI key error: {resp.status_code}"}

            elif provider == "openrouter":
                resp = requests.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json={"model": "openai/gpt-4o-mini", "messages": [{"role": "user", "content": "Hello"}]},
                    timeout=15,
                )
                if resp.status_code == 200:
                    return ok("OpenRouter key is valid. API Test OK.")
                try:
                    err_msg = resp.json().get("error", {}).get("message", "Unknown Error")
                except Exception:
                    err_msg = resp.text[:100]
                return {"status": "error", "verified": False, "message": f"OpenRouter key error {resp.status_code}: {err_msg}"}

            elif provider == "deepseek":
                resp = requests.get("https://api.deepseek.com/v1/models",
                                    headers={"Authorization": f"Bearer {key}"}, timeout=10)
                if resp.status_code == 200:
                    return ok("DeepSeek key is valid.")
                return {"status": "error", "verified": False, "message": f"DeepSeek key error: {resp.status_code}"}

            elif provider == "grok":
                resp = requests.get("https://api.x.ai/v1/models",
                                    headers={"Authorization": f"Bearer {key}"}, timeout=10)
                if resp.status_code == 200:
                    return ok("Grok key is valid.")
                return {"status": "error", "verified": False, "message": f"Grok key error: {resp.status_code}"}

            elif provider == "claude":
                # No cheap list endpoint; a real check needs a paid message call.
                return stored("Đã lưu key Claude — chưa kiểm chứng (cần một message call để xác minh).")

            else:
                return stored(f"Đã lưu key cho {provider} — chưa có cách tự kiểm chứng.")

        except Exception as e:
            return {"status": "error", "verified": False, "message": f"Test failed: {e}"}

    def enable_key(self, provider: str, label: str = "default") -> dict:
        """Re-enable a key that was auto-disabled. The path that did not exist,
        so a quota-hit key could only be revived by hand-editing the JSON."""
        self._load()
        entry = self._keys.get(provider, {}).get(label)
        if not isinstance(entry, dict):
            return {"status": "error", "message": f"Key '{label}' not found for {provider}."}
        entry["active"] = True
        entry.pop("status_msg", None)
        entry.pop("disabled_at", None)
        entry.pop("disable_reason", None)
        self._save()
        return {"status": "success", "message": f"Key '{label}' for {provider} re-enabled."}

    # ── Cloudflare Compound Credentials ──────────────────────────

    def add_cloudflare_key(
        self,
        api_token: str,
        account_id: str,
        label: str = "default",
        email: str = "",
    ) -> dict:
        """Store Cloudflare credential.

        - Nếu có `email` → coi api_token là GLOBAL API KEY (xác thực bằng cặp
          X-Auth-Email + X-Auth-Key).
        - Nếu không có email → API Token (Authorization: Bearer).
        """
        import datetime as _dt
        self._keys.setdefault("cloudflare", {})[label] = {
            "key": api_token,
            "account_id": account_id,
            "email": (email or "").strip(),
            "active": True,
            "added_at": _dt.datetime.now().isoformat(),
        }
        self._save()
        return {
            "status": "success",
            "message": f"Cloudflare credentials '{label}' saved.",
        }

    def get_cloudflare_creds(self, label: str = "default") -> dict:
        """Return {api_token, account_id, email} for a Cloudflare credential label."""
        self._load()
        entries = self._keys.get("cloudflare", {})
        entry = entries.get(label) if isinstance(entries, dict) else None
        if entry and entry.get("active"):
            return {
                "api_token": entry.get("key", ""),
                "account_id": entry.get("account_id", ""),
                "email": entry.get("email", ""),
                "label": label,
            }
        # Fallback to environment variables
        api_token = os.environ.get("CLOUDFLARE_API_TOKEN", "") or os.environ.get("CLOUDFLARE_API_KEY", "")
        account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
        email = os.environ.get("CLOUDFLARE_EMAIL", "")
        if api_token or account_id:
            return {"api_token": api_token, "account_id": account_id, "email": email, "label": "env"}
        return {"api_token": "", "account_id": "", "email": "", "label": None}

    def list_cloudflare_keys(self) -> list:
        """List all stored Cloudflare credential profiles (masked)."""
        self._load()
        entries = self._keys.get("cloudflare", {})
        result = []
        if not isinstance(entries, dict):
            return result
        for label, entry in entries.items():
            if not isinstance(entry, dict):
                continue
            token = entry.get("key", "")
            masked = token[:6] + "..." + token[-4:] if len(token) > 10 else "***"
            result.append({
                "label": label,
                "masked_token": masked,
                "account_id": entry.get("account_id", ""),
                "email": entry.get("email", ""),
                "auth_type": "global_key" if entry.get("email") else "api_token",
                "active": entry.get("active", False),
                "added_at": entry.get("added_at", ""),
            })
        return result

    def test_cloudflare_key(self, label: str = "default") -> dict:
        """Verify Cloudflare credentials.

        - Có email → Global API Key: GET /user với X-Auth-Email + X-Auth-Key.
        - Không email → API Token: GET /user/tokens/verify với Bearer.
        """
        creds = self.get_cloudflare_creds(label)
        if not creds.get("api_token"):
            return {"status": "error", "message": "Không tìm thấy Cloudflare API Token/Key."}
        email = (creds.get("email") or "").strip()
        try:
            import urllib.request
            import urllib.error
            if email:
                # Global API Key
                req = urllib.request.Request(
                    "https://api.cloudflare.com/client/v4/user",
                    headers={
                        "X-Auth-Email": email,
                        "X-Auth-Key": creds["api_token"],
                        "Content-Type": "application/json",
                    },
                )
                ok_msg = "✅ Cloudflare Global API Key hợp lệ!"
            else:
                # API Token
                req = urllib.request.Request(
                    "https://api.cloudflare.com/client/v4/user/tokens/verify",
                    headers={"Authorization": f"Bearer {creds['api_token']}", "Content-Type": "application/json"},
                )
                ok_msg = "✅ Cloudflare API Token hợp lệ!"
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                if data.get("success"):
                    return {"status": "success", "message": ok_msg, "result": data.get("result", {})}
                errors = ", ".join([e.get("message", "") for e in data.get("errors", [])])
                return {"status": "error", "message": f"Không hợp lệ: {errors}"}
        except urllib.error.HTTPError as e:
            hint = " (Global API Key cần đúng email; hoặc dùng API Token thì bỏ trống email)" if e.code == 401 else ""
            return {"status": "error", "message": f"Lỗi kiểm tra: HTTP {e.code}{hint}"}
        except Exception as e:
            return {"status": "error", "message": f"Lỗi kiểm tra: {e}"}


# Global singleton
key_manager = KeyManager()


class CloudApiExtension(Extension):
    name = "cloud_api"
    version = "0.1.0"
    description = "Manage cloud AI providers (Gemini, OpenAI, Claude, DeepSeek, Grok, Cloudflare) and API keys"
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
