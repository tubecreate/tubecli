"""
Auth Manager Extension — Manages OAuth credentials and tokens for multiple providers.
Core extension: provides token/credential storage used by other extensions (browser, agents, workflows).
"""
import os
import json
import uuid
import logging
import secrets
import threading
import webbrowser
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from urllib.parse import urlencode
from tubecli.core.extension_manager import Extension
from tubecli.config import DATA_DIR

logger = logging.getLogger("AuthManagerExtension")

AUTH_DATA_FILE = os.path.join(DATA_DIR, "auth_manager.json")

# ── Supported Providers ──────────────────────────────────────────

PROVIDERS = {
    "google": {
        "name": "Google",
        "icon": "🔵",
        "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "revoke_url": "https://oauth2.googleapis.com/revoke",
        "scopes": {
            "youtube": {
                "label": "YouTube (Full)",
                "value": "https://www.googleapis.com/auth/youtube",
            },
            "youtube_readonly": {
                "label": "YouTube (Read Only)",
                "value": "https://www.googleapis.com/auth/youtube.readonly",
            },
            "youtube_upload": {
                "label": "YouTube Upload",
                "value": "https://www.googleapis.com/auth/youtube.upload",
            },
            "youtube_partner": {
                "label": "YouTube Content ID",
                "value": "https://www.googleapis.com/auth/youtubepartner",
            },
            "drive": {
                "label": "Google Drive",
                "value": "https://www.googleapis.com/auth/drive",
            },
            "drive_readonly": {
                "label": "Google Drive (Read Only)",
                "value": "https://www.googleapis.com/auth/drive.readonly",
            },
            "sheets": {
                "label": "Google Sheets",
                "value": "https://www.googleapis.com/auth/spreadsheets",
            },
            "sheets_readonly": {
                "label": "Google Sheets (Read Only)",
                "value": "https://www.googleapis.com/auth/spreadsheets.readonly",
            },
            "gmail_readonly": {
                "label": "Gmail (Read Only)",
                "value": "https://www.googleapis.com/auth/gmail.readonly",
            },
            "gmail_send": {
                "label": "Gmail (Send)",
                "value": "https://www.googleapis.com/auth/gmail.send",
            },
            "gmail_modify": {
                "label": "Gmail (Modify)",
                "value": "https://www.googleapis.com/auth/gmail.modify",
            },
            "calendar": {
                "label": "Google Calendar",
                "value": "https://www.googleapis.com/auth/calendar",
            },
            "calendar_readonly": {
                "label": "Google Calendar (Read Only)",
                "value": "https://www.googleapis.com/auth/calendar.readonly",
            },
            "indexing": {
                "label": "Google Indexing API",
                "value": "https://www.googleapis.com/auth/indexing",
            },
            "business_manage": {
                "label": "Google Business Profile",
                "value": "https://www.googleapis.com/auth/business.manage",
            },
        },
        "services": {
            "youtube_manage": {
                "label": "📺 YouTube — Quản lý kênh",
                "description": "Đọc, upload video, livestream, quản lý kênh YouTube",
                "icon": "📺",
                "scopes": ["youtube", "youtube_upload", "youtube_readonly"],
            },
            "youtube_read": {
                "label": "📖 YouTube — Chỉ đọc",
                "description": "Xem thông tin kênh, video, analytics",
                "icon": "📖",
                "scopes": ["youtube_readonly"],
            },
            "sheets_manage": {
                "label": "📊 Google Sheets — Quản lý",
                "description": "Thêm, sửa, xóa dữ liệu trong Sheets",
                "icon": "📊",
                "scopes": ["sheets", "drive"],
            },
            "sheets_read": {
                "label": "📋 Google Sheets — Chỉ đọc",
                "description": "Đọc dữ liệu từ Sheets",
                "icon": "📋",
                "scopes": ["sheets_readonly", "drive_readonly"],
            },
            "drive_manage": {
                "label": "📁 Google Drive — Quản lý",
                "description": "Upload, tạo, sửa, xóa files trên Drive",
                "icon": "📁",
                "scopes": ["drive"],
            },
            "gmail_manage": {
                "label": "📧 Gmail — Đọc & Gửi",
                "description": "Đọc email, gửi email, quản lý nhãn",
                "icon": "📧",
                "scopes": ["gmail_readonly", "gmail_send"],
            },
            "calendar_manage": {
                "label": "📅 Calendar — Quản lý",
                "description": "Tạo, sửa, xóa sự kiện lịch",
                "icon": "📅",
                "scopes": ["calendar"],
            },
            "indexing_service": {
                "label": "🔍 Google Indexing API",
                "description": "Ping Indexing (Ép Google crawl nhanh)",
                "icon": "🔍",
                "scopes": ["indexing"],
            },
            "maps_business": {
                "label": "🗺️ Google Maps (Business Profile)",
                "description": "Quản lý địa điểm kinh doanh",
                "icon": "🗺️",
                "scopes": ["business_manage"],
            },
        },
        "credentials_type": ["oauth_client", "service_account"],
    },
    "facebook": {
        "name": "Facebook / Meta",
        "icon": "📘",
        "auth_url": "https://www.facebook.com/v19.0/dialog/oauth",
        "token_url": "https://graph.facebook.com/v19.0/oauth/access_token",
        "revoke_url": None,
        "scopes": {
            "pages_manage": {
                "label": "Manage Pages",
                "value": "pages_manage_posts,pages_read_engagement,pages_show_list",
            },
            "pages_messaging": {
                "label": "Pages Messaging",
                "value": "pages_messaging",
            },
            "ads": {
                "label": "Ads Management",
                "value": "ads_management",
            },
            "instagram": {
                "label": "Instagram Basic",
                "value": "instagram_basic,instagram_content_publish",
            },
        },
        "services": {
            "fanpage_manage": {
                "label": "📄 Fanpage — Quản lý",
                "description": "Đăng bài, đọc tương tác, quản lý fanpage",
                "icon": "📄",
                "scopes": ["pages_manage"],
            },
            "fanpage_chat": {
                "label": "💬 Fanpage — Nhắn tin",
                "description": "Gửi/nhận tin nhắn qua Messenger",
                "icon": "💬",
                "scopes": ["pages_manage", "pages_messaging"],
            },
            "ads_manage": {
                "label": "📢 Ads — Quản lý quảng cáo",
                "description": "Tạo, sửa, đọc chiến dịch quảng cáo",
                "icon": "📢",
                "scopes": ["ads"],
            },
            "instagram_manage": {
                "label": "📸 Instagram — Quản lý",
                "description": "Đăng ảnh/video, đọc insights",
                "icon": "📸",
                "scopes": ["instagram", "pages_manage"],
            },
        },
        "credentials_type": ["oauth_client"],
    },
    "tiktok": {
        "name": "TikTok",
        "icon": "🎵",
        "auth_url": "https://www.tiktok.com/v2/auth/authorize/",
        "token_url": "https://open.tiktokapis.com/v2/oauth/token/",
        "revoke_url": "https://open.tiktokapis.com/v2/oauth/revoke/",
        "scopes": {
            "video_list": {
                "label": "Video List",
                "value": "video.list",
            },
            "video_upload": {
                "label": "Video Upload (legacy)",
                "value": "video.upload",
            },
            "video_publish": {
                "label": "Video Publish (Content Posting API v2)",
                "value": "video.publish",
            },
            "user_info": {
                "label": "User Info Basic",
                "value": "user.info.basic",
            },
            "user_info_stats": {
                "label": "User Info Stats",
                "value": "user.info.stats",
            },
        },
        "services": {
            "tiktok_manage": {
                "label": "🎬 TikTok — Quản lý & Xem video",
                "description": "Xem danh sách video (Display API), upload video dạng draft, xem thông tin tài khoản",
                "icon": "🎬",
                "scopes": ["user_info", "user_info_stats", "video_list", "video_upload"],
            },
            "tiktok_upload": {
                "label": "⬆️ TikTok — Upload video",
                "description": "Chỉ upload video lên TikTok (lưu dạng draft)",
                "icon": "⬆️",
                "scopes": ["user_info", "video_upload"],
            },
            "tiktok_read": {
                "label": "👁 TikTok — Chỉ đọc (Display API)",
                "description": "Xem danh sách video và thông tin tài khoản (không upload)",
                "icon": "👁",
                "scopes": ["user_info", "user_info_stats", "video_list"],
            },
        },
        "credentials_type": ["oauth_client"],
    },
}


# ── Pending OAuth state storage ──────────────────────────────────
# Maps state_token -> {credential_id, scopes, browser_profile, created_at}
_pending_oauth: Dict[str, dict] = {}
_pending_lock = threading.Lock()


class AuthManager:
    """Manages OAuth credentials and tokens for multiple providers."""

    def __init__(self, data_file: str = AUTH_DATA_FILE):
        self.data_file = data_file
        self._data: Dict[str, Any] = {"credentials": {}, "tokens": {}}
        self._load()

    # ── Load / Save ──────────────────────────────────────────

    def _load(self):
        """Load credentials from disk and auto-migrate legacy tokens."""
        if not os.path.exists(self.data_file):
            self._save()
        with open(self.data_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            self._data["credentials"] = data.get("credentials", {})
            self._data["tokens"] = data.get("tokens", {})

        # AUTO-MIGRATE: If existing tokens use exactly cred_id as the key, migrate them!
        migrated = False
        new_tokens = {}
        for token_key, token_val in list(self._data["tokens"].items()):
            # If the token_key is exactly equal to a credential ID, it's legacy!
            if token_key in self._data["credentials"]:
                # Generate a unique key for it
                new_token_id = f"{token_key}_{uuid.uuid4().hex[:8]}"
                # Ensure it has credential_id inside the data
                if "credential_id" not in token_val:
                    token_val["credential_id"] = token_key
                new_tokens[new_token_id] = token_val
                migrated = True
            else:
                new_tokens[token_key] = token_val

        if migrated:
            self._data["tokens"] = new_tokens
            self._save()
            logger.info("Auto-migrated auth manager tokens to multi-token format.")

    def _save(self):
        os.makedirs(os.path.dirname(self.data_file), exist_ok=True)
        with open(self.data_file, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)

    # ── Credentials CRUD ─────────────────────────────────────

    def add_credential(
        self,
        provider: str,
        name: str,
        client_id: str = "",
        client_secret: str = "",
        credentials_json: str = "",
        service_account_email: str = "",
        scopes: List[str] = None,
        extra: dict = None,
    ) -> dict:
        """Add a new OAuth credential."""
        if provider not in PROVIDERS:
            return {"status": "error", "message": f"Unknown provider: {provider}. Available: {list(PROVIDERS.keys())}"}

        cred_id = f"cred_{uuid.uuid4().hex[:8]}"
        self._data["credentials"][cred_id] = {
            "provider": provider,
            "name": name,
            "client_id": client_id,
            "client_secret": client_secret,
            "credentials_json": credentials_json or None,
            "service_account_email": service_account_email or None,
            "scopes": scopes or [],
            "extra": extra or {},
            "created_at": datetime.now().isoformat(),
        }
        self._save()
        return {"status": "success", "credential_id": cred_id, "message": f"Credential '{name}' added for {provider}."}

    def add_manual_token(self, provider: str, name: str, identifier: str, access_token: str) -> dict:
        """Add a manual token. For Facebook, auto-exchanges to long-lived/page token if possible."""
        if provider not in PROVIDERS:
            return {"status": "error", "message": f"Unknown provider: {provider}."}

        # 1. Create a credential container
        cred_id = f"cred_{uuid.uuid4().hex[:8]}"
        scopes = PROVIDERS[provider].get("services", {}).get("fanpage_manage", {}).get("scopes", ["pages_manage"])
        self._data["credentials"][cred_id] = {
            "provider": provider,
            "name": name,
            "client_id": identifier,  # Store Page ID or generic identifier here
            "client_secret": "***",
            "credentials_json": None,
            "service_account_email": None,
            "scopes": scopes,
            "extra": {},
            "created_at": datetime.now().isoformat(),
        }

        # 2. For Facebook: try to exchange token to long-lived version
        final_token = access_token
        token_note = ""
        expires_days = 60  # default assumption

        if provider == "facebook":
            exchanged = self._fb_exchange_token(access_token, cred_id)
            if exchanged:
                final_token = exchanged["token"]
                token_note = exchanged.get("note", "")
                expires_days = exchanged.get("expires_days", 60)

        # 3. Inject the authorized token
        token_id = f"{cred_id}_{uuid.uuid4().hex[:8]}"
        self._data["tokens"][token_id] = {
            "credential_id": cred_id,
            "access_token": final_token,
            "refresh_token": "",
            "token_type": "Bearer",
            "expires_at": (datetime.now() + timedelta(days=expires_days)).isoformat(),
            "expires_in": expires_days * 86400,
            "scopes": scopes,
            "scope_values": scopes,
            "authorized_email": f"ID: {identifier}",
            "browser_profile": "Manual",
            "authorized_at": datetime.now().isoformat(),
            "raw_response": {"manual": True, "note": token_note}
        }

        self._save()
        msg = f"Manual token added successfully for {provider}."
        if token_note:
            msg += f" ({token_note})"
        return {
            "status": "success",
            "credential_id": cred_id,
            "token_id": token_id,
            "message": msg
        }

    def _fb_exchange_token(self, short_token: str, cred_id: str) -> Optional[dict]:
        """Exchange a Facebook short-lived token to long-lived, then get never-expiring page token."""
        import requests as req

        # Look for an existing Facebook credential with real app_id + app_secret
        app_id, app_secret = None, None
        for cid, cred in self._data["credentials"].items():
            if cred.get("provider") == "facebook" and cred.get("client_id") and cred.get("client_secret", "***") != "***":
                app_id = cred["client_id"]
                app_secret = cred["client_secret"]
                break

        if not app_id or not app_secret:
            logger.info("[FB Exchange] No App ID/Secret found — using token as-is (short-lived).")
            return None

        # Step 1: Exchange short-lived → long-lived user token
        try:
            resp = req.get(
                "https://graph.facebook.com/v19.0/oauth/access_token",
                params={
                    "grant_type": "fb_exchange_token",
                    "client_id": app_id,
                    "client_secret": app_secret,
                    "fb_exchange_token": short_token,
                },
                timeout=15,
            )
            if resp.status_code != 200:
                logger.warning(f"[FB Exchange] Failed to exchange token: {resp.text[:200]}")
                return None

            data = resp.json()
            long_lived_token = data.get("access_token", short_token)
            expires_in = data.get("expires_in", 5184000)  # ~60 days
            logger.info(f"[FB Exchange] Got long-lived token (expires in {expires_in}s)")
        except Exception as e:
            logger.warning(f"[FB Exchange] Exchange request failed: {e}")
            return None

        # Step 2: Use long-lived token to get never-expiring Page Access Token
        try:
            pages_resp = req.get(
                "https://graph.facebook.com/v19.0/me/accounts",
                params={
                    "access_token": long_lived_token,
                    "fields": "id,name,access_token",
                },
                timeout=15,
            )
            if pages_resp.status_code == 200:
                pages = pages_resp.json().get("data", [])
                if pages:
                    # Use the first page token (never expires!)
                    page_token = pages[0].get("access_token", long_lived_token)
                    page_name = pages[0].get("name", "Unknown")
                    logger.info(f"[FB Exchange] Got permanent page token for '{page_name}'")
                    return {
                        "token": page_token,
                        "note": f"Token vĩnh viễn cho page '{page_name}'",
                        "expires_days": 36500,  # ~100 years = never expires
                    }
        except Exception as e:
            logger.warning(f"[FB Exchange] /me/accounts failed: {e}")

        # Step 3: Fallback — return long-lived user token (~60 days)
        return {
            "token": long_lived_token,
            "note": "Long-lived token (~60 ngày)",
            "expires_days": int(expires_in / 86400),
        }


    def update_credential(self, cred_id: str, **kwargs) -> dict:
        """Update an existing credential."""
        self._load()
        cred = self._data["credentials"].get(cred_id)
        if not cred:
            return {"status": "error", "message": f"Credential '{cred_id}' not found."}

        for key in ["name", "client_id", "client_secret", "credentials_json",
                     "service_account_email", "scopes", "extra"]:
            if key in kwargs and kwargs[key] is not None:
                if key in ["client_id", "client_secret"] and isinstance(kwargs[key], str) and kwargs[key].startswith("***"):
                    continue
                cred[key] = kwargs[key]

        cred["updated_at"] = datetime.now().isoformat()
        self._save()
        return {"status": "success", "message": f"Credential '{cred_id}' updated."}

    def remove_credential(self, cred_id: str) -> dict:
        """Remove a credential and its associated token."""
        self._load()
        if cred_id not in self._data["credentials"]:
            return {"status": "error", "message": f"Credential '{cred_id}' not found."}

        del self._data["credentials"][cred_id]
        # Also remove associated token
        self._data["tokens"].pop(cred_id, None)
        self._save()
        return {"status": "success", "message": f"Credential '{cred_id}' removed."}

    def list_credentials(self, provider: str = None) -> List[dict]:
        """List all credentials (masked secrets)."""
        self._load()
        result = []
        for cred_id, cred in self._data["credentials"].items():
            if provider and cred.get("provider") != provider:
                continue
            token_info = self._data["tokens"].get(cred_id)
            masked = {
                "id": cred_id,
                "provider": cred.get("provider"),
                "name": cred.get("name"),
                "client_id": self._mask(cred.get("client_id", "")),
                "has_json": bool(cred.get("credentials_json")),
                "service_account_email": cred.get("service_account_email"),
                "scopes": cred.get("scopes", []),
                "created_at": cred.get("created_at"),
                "has_token": token_info is not None,
                "token_status": self._get_token_status(cred_id),
            }
            result.append(masked)
        return result

    def get_credential(self, cred_id: str) -> Optional[dict]:
        """Get full credential data (internal use)."""
        self._load()
        return self._data["credentials"].get(cred_id)

    # ── OAuth Flow ───────────────────────────────────────────

    def build_oauth_url(self, cred_id: str, scopes: List[str], browser_profile: str = "",
                        callback_base: str = "http://localhost:2516") -> dict:
        """Build OAuth authorization URL and store pending state."""
        self._load()
        cred = self._data["credentials"].get(cred_id)
        if not cred:
            return {"status": "error", "message": f"Credential '{cred_id}' not found."}

        provider = cred["provider"]
        prov_config = PROVIDERS.get(provider)
        if not prov_config:
            return {"status": "error", "message": f"Unknown provider: {provider}"}

        # Generate state token for CSRF protection
        state_token = secrets.token_urlsafe(32)

        # Build redirect URI
        redirect_uri = f"{callback_base}/api/v1/auth-manager/oauth/callback"

        # Resolve scope values
        scope_values = []
        for s in scopes:
            scope_def = prov_config["scopes"].get(s)
            if scope_def:
                scope_values.append(scope_def["value"])
            else:
                scope_values.append(s)  # Raw scope string

        # Build auth URL based on provider
        if provider == "google":
            # Auto-inject OpenID scopes so we can fetch user email
            openid_scopes = [
                "openid",
                "https://www.googleapis.com/auth/userinfo.email",
                "https://www.googleapis.com/auth/userinfo.profile",
            ]
            for oid in openid_scopes:
                if oid not in scope_values:
                    scope_values.append(oid)

            params = {
                "client_id": cred["client_id"],
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": " ".join(scope_values),
                "state": state_token,
                "access_type": "offline",
                "prompt": "consent",
            }
        elif provider == "facebook":
            params = {
                "client_id": cred["client_id"],
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": ",".join(scope_values),
                "state": state_token,
            }
        elif provider == "tiktok":
            # TikTok v2 OAuth requires PKCE (S256 method)
            import hashlib
            # TikTok has a non-standard PKCE implementation: it expects the challenge as a HEX string, not base64url.
            code_verifier = secrets.token_urlsafe(32)
            code_challenge = hashlib.sha256(code_verifier.encode('utf-8')).hexdigest()
            logger.info(f"[TikTok PKCE] verifier={code_verifier[:8]}... challenge={code_challenge[:8]}...")
            params = {
                "client_key": cred["client_id"],
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": ",".join(scope_values),
                "state": state_token,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        else:
            params = {
                "client_id": cred["client_id"],
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": " ".join(scope_values),
                "state": state_token,
            }

        auth_url = f"{prov_config['auth_url']}?{urlencode(params)}"

        # Store pending OAuth state
        with _pending_lock:
            _pending_oauth[state_token] = {
                "credential_id": cred_id,
                "scopes": scopes,
                "scope_values": scope_values,
                "browser_profile": browser_profile,
                "redirect_uri": redirect_uri,
                "created_at": datetime.now().isoformat(),
                # PKCE — only set for TikTok
                **({"code_verifier": code_verifier} if provider == "tiktok" else {}),
            }

        return {
            "status": "success",
            "auth_url": auth_url,
            "state": state_token,
            "redirect_uri": redirect_uri,
        }

    def handle_oauth_callback(self, code: str, state: str) -> dict:
        """Handle OAuth callback — exchange code for token."""
        # Validate state
        with _pending_lock:
            pending = _pending_oauth.pop(state, None)

        if not pending:
            return {"status": "error", "message": "Invalid or expired OAuth state."}

        cred_id = pending["credential_id"]
        cred = self._data["credentials"].get(cred_id)
        if not cred:
            return {"status": "error", "message": f"Credential '{cred_id}' not found."}

        provider = cred["provider"]
        prov_config = PROVIDERS.get(provider)

        # Exchange code for token
        try:
            import requests as req_lib
            if provider == "google":
                resp = req_lib.post(prov_config["token_url"], data={
                    "code": code,
                    "client_id": cred["client_id"],
                    "client_secret": cred["client_secret"],
                    "redirect_uri": pending["redirect_uri"],
                    "grant_type": "authorization_code",
                }, timeout=30)
            elif provider == "facebook":
                resp = req_lib.get(prov_config["token_url"], params={
                    "client_id": cred["client_id"],
                    "client_secret": cred["client_secret"],
                    "redirect_uri": pending["redirect_uri"],
                    "code": code,
                }, timeout=30)
            elif provider == "tiktok":
                code_verifier = pending.get("code_verifier", "")
                logger.info(f"[TikTok Token] exchanging code with PKCE verifier...")
                resp = req_lib.post(
                    prov_config["token_url"],
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    data={
                        "client_key": cred["client_id"],
                        "client_secret": cred["client_secret"],
                        "code": code,
                        "grant_type": "authorization_code",
                        "redirect_uri": pending["redirect_uri"],
                        "code_verifier": code_verifier,
                    },
                    timeout=30,
                )
                logger.info(f"[TikTok Token] HTTP {resp.status_code} → {resp.text[:300]}")
            else:
                resp = req_lib.post(prov_config["token_url"], data={
                    "code": code,
                    "client_id": cred["client_id"],
                    "client_secret": cred["client_secret"],
                    "redirect_uri": pending["redirect_uri"],
                    "grant_type": "authorization_code",
                }, timeout=30)

            token_raw = resp.json()
            logger.info(f"[OAuth Token] provider={provider} status={resp.status_code} keys={list(token_raw.keys())}")

            # TikTok v2 wraps token data inside "data" key and always includes
            # "error": {"code": "ok"} for success — unwrap before generic checks.
            if provider == "tiktok":
                tiktok_error = token_raw.get("error", {})
                if isinstance(tiktok_error, dict) and tiktok_error.get("code") not in ("ok", None, ""):
                    return {"status": "error", "message": f"Token exchange failed: {tiktok_error.get('message', tiktok_error.get('code', str(tiktok_error)))}"}
                if resp.status_code != 200:
                    return {"status": "error", "message": f"Token exchange failed: HTTP {resp.status_code}"}
                # Unwrap the nested "data" key → flat token dict
                token_data = token_raw.get("data", token_raw)
            else:
                token_data = token_raw
                if resp.status_code != 200 or "error" in token_data:
                    error_msg = token_data.get("error_description") or token_data.get("error", str(token_data))
                    return {"status": "error", "message": f"Token exchange failed: {error_msg}"}

            # Facebook: auto-exchange short-lived → long-lived token
            fb_exchange_note = ""
            if provider == "facebook":
                short_token = token_data.get("access_token", "")
                if short_token and cred.get("client_id") and cred.get("client_secret"):
                    try:
                        ll_resp = req_lib.get(
                            "https://graph.facebook.com/v19.0/oauth/access_token",
                            params={
                                "grant_type": "fb_exchange_token",
                                "client_id": cred["client_id"],
                                "client_secret": cred["client_secret"],
                                "fb_exchange_token": short_token,
                            },
                            timeout=15,
                        )
                        if ll_resp.status_code == 200:
                            ll_data = ll_resp.json()
                            long_lived_token = ll_data.get("access_token", short_token)
                            ll_expires = ll_data.get("expires_in", 5184000)
                            token_data["access_token"] = long_lived_token
                            token_data["expires_in"] = ll_expires
                            fb_exchange_note = f"Long-lived token (~{ll_expires // 86400} ngày)"
                            logger.info(f"[FB OAuth] Exchanged to long-lived token (expires in {ll_expires}s)")
                        else:
                            logger.warning(f"[FB OAuth] Long-lived exchange failed: {ll_resp.text[:200]}")
                    except Exception as e:
                        logger.warning(f"[FB OAuth] Long-lived exchange error: {e}")

            # Get user email if possible
            authorized_email = self._fetch_user_email(provider, token_data)

            # Calculate expiry
            expires_in = token_data.get("expires_in", 3600)
            expires_at = (datetime.now() + timedelta(seconds=int(expires_in))).isoformat()

            # Save token
            token_id = f"{cred_id}_{uuid.uuid4().hex[:8]}"
            self._data["tokens"][token_id] = {
                "credential_id": cred_id,
                "access_token": token_data.get("access_token", ""),
                "refresh_token": token_data.get("refresh_token", ""),
                "token_type": token_data.get("token_type", "Bearer"),
                "expires_at": expires_at,
                "expires_in": expires_in,
                "scopes": pending["scopes"],
                "scope_values": pending["scope_values"],
                "authorized_email": authorized_email,
                "browser_profile": pending.get("browser_profile", ""),
                "authorized_at": datetime.now().isoformat(),
                "raw_response": {**token_data, "fb_exchange_note": fb_exchange_note} if fb_exchange_note else token_data,
            }
            self._save()

            return {
                "status": "success",
                "message": f"Authorization successful! Email: {authorized_email or 'N/A'}",
                "credential_id": cred_id,
                "token_id": token_id,
                "authorized_email": authorized_email,
                "browser_profile": pending.get("browser_profile", ""),
            }

        except Exception as e:
            logger.error(f"OAuth token exchange error: {e}")
            return {"status": "error", "message": f"Token exchange error: {str(e)}"}

    def _fetch_user_email(self, provider: str, token_data: dict) -> str:
        """Try to fetch user email/name after OAuth."""
        try:
            import requests as req_lib
            access_token = token_data.get("access_token", "")
            if not access_token:
                return ""

            if provider == "google":
                resp = req_lib.get(
                    "https://www.googleapis.com/oauth2/v2/userinfo",
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=10,
                )
                if resp.status_code == 200:
                    return resp.json().get("email", "")

            elif provider == "facebook":
                resp = req_lib.get(
                    f"https://graph.facebook.com/me?fields=email,name&access_token={access_token}",
                    timeout=10,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("email") or data.get("name", "")

            elif provider == "tiktok":
                open_id = token_data.get("open_id", "")
                return f"tiktok:{open_id}" if open_id else ""

        except Exception as e:
            logger.warning(f"Failed to fetch user email: {e}")
        return ""

    # ── Token Management ─────────────────────────────────────

    def list_tokens(self, provider: str = None) -> List[dict]:
        """List all authorized tokens."""
        self._load()
        result = []
        for token_id, token in self._data["tokens"].items():
            cred_id = token.get("credential_id")
            if not cred_id:
                continue
            cred = self._data["credentials"].get(cred_id, {})
            if provider and cred.get("provider") != provider:
                continue
            result.append({
                "token_id": token_id,
                "credential_id": cred_id,
                "credential_name": cred.get("name", "Unknown"),
                "provider": cred.get("provider", "unknown"),
                "authorized_email": token.get("authorized_email", ""),
                "browser_profile": token.get("browser_profile", ""),
                "scopes": token.get("scopes", []),
                "expires_at": token.get("expires_at", ""),
                "authorized_at": token.get("authorized_at", ""),
                "status": self._get_token_status(token_id),
                "has_refresh": bool(token.get("refresh_token")),
            })
        return result

    def _resolve_token_id(self, identifier: str) -> Optional[str]:
        """Resolve token_id. If a cred_id is passed, returns the first active token_id for it."""
        if identifier in self._data["tokens"]:
            return identifier
        # Fallback: find first token belonging to this cred_id
        for tid, t in self._data["tokens"].items():
            if t.get("credential_id") == identifier:
                return tid
        return None

    def get_active_token(self, identifier: str) -> Optional[str]:
        """Get a valid access token, auto-refreshing if needed."""
        self._load()
        
        # Check if identifier is actually a credential ID of type service_account
        cred = self._data["credentials"].get(identifier)
        if cred and (cred.get("credentials_type") == "service_account" or cred.get("credentials_json")):
            return self._generate_service_account_token(cred)

            
        token_id = self._resolve_token_id(identifier)
        if not token_id:
            return None
            
        token = self._data["tokens"].get(token_id)

        # Check if expired
        expires_at = token.get("expires_at", "")
        if expires_at:
            try:
                exp_dt = datetime.fromisoformat(expires_at)
                if datetime.now() > exp_dt:
                    # Try refresh
                    refresh_result = self.refresh_token(token_id)
                    if refresh_result.get("status") == "success":
                        self._load()
                        token = self._data["tokens"].get(token_id)
                        return token.get("access_token") if token else None
                    return None
            except Exception:
                pass

        return token.get("access_token")

    def _generate_service_account_token(self, cred: dict) -> Optional[str]:
        import json
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request
        
        try:
            cred_json_str = cred.get("credentials_json")
            if not cred_json_str:
                return None
            info = json.loads(cred_json_str)
            scopes = cred.get("scopes", [])
            
            real_scopes = []
            for s in scopes:
                if s.startswith("http"):
                    real_scopes.append(s)
                else:
                    provider_info = PROVIDERS.get("google", {})
                    scope_def = provider_info.get("scopes", {}).get(s)
                    if scope_def:
                        real_scopes.append(scope_def["value"])
                    else:
                        real_scopes.append(s)
            
            if not real_scopes:
                # Fallback scopes if empty (Indexing + Drive + Sheets)
                real_scopes = [
                    "https://www.googleapis.com/auth/indexing",
                    "https://www.googleapis.com/auth/drive",
                    "https://www.googleapis.com/auth/spreadsheets"
                ]

            credentials = service_account.Credentials.from_service_account_info(
                info, scopes=real_scopes
            )
            request = Request()
            credentials.refresh(request)
            return credentials.token
        except Exception as e:
            logger.error(f"Failed to generate service account token: {e}")
            return None

    def get_active_token_for_profile(self, cred_id: str, profile_name: str) -> Optional[str]:
        """Get a valid access token for a specific browser profile."""
        self._load()
        target_token_id = None
        for tid, t in self._data["tokens"].items():
            if t.get("credential_id") == cred_id and t.get("browser_profile") == profile_name:
                target_token_id = tid
                break
                
        if target_token_id:
            return self.get_active_token(target_token_id)
        # Fallback to the first available if none match the profile exactly
        return self.get_active_token(cred_id)

    def get_token_data(self, identifier: str) -> Optional[dict]:
        """Get full token data (internal use by other extensions)."""
        self._load()
        token_id = self._resolve_token_id(identifier)
        if not token_id:
            return None
        return self._data["tokens"].get(token_id)

    def refresh_token(self, identifier: str) -> dict:
        """Refresh an expired token."""
        self._load()
        token_id = self._resolve_token_id(identifier)
        if not token_id:
            return {"status": "error", "message": f"No token found for '{identifier}'."}

        token = self._data["tokens"].get(token_id)
        refresh = token.get("refresh_token")
        if not refresh:
            return {"status": "error", "message": "No refresh token available. Re-authorize required."}

        cred_id = token.get("credential_id")
        cred = self._data["credentials"].get(cred_id, {})
        provider = cred.get("provider")
        prov_config = PROVIDERS.get(provider, {})

        try:
            import requests as req_lib
            if provider == "google":
                resp = req_lib.post(prov_config["token_url"], data={
                    "client_id": cred["client_id"],
                    "client_secret": cred["client_secret"],
                    "refresh_token": refresh,
                    "grant_type": "refresh_token",
                }, timeout=30)
            elif provider == "tiktok":
                resp = req_lib.post(prov_config["token_url"], json={
                    "client_key": cred["client_id"],
                    "client_secret": cred["client_secret"],
                    "refresh_token": refresh,
                    "grant_type": "refresh_token",
                }, timeout=30)
            else:
                resp = req_lib.post(prov_config.get("token_url", ""), data={
                    "client_id": cred["client_id"],
                    "client_secret": cred["client_secret"],
                    "refresh_token": refresh,
                    "grant_type": "refresh_token",
                }, timeout=30)

            new_token = resp.json()
            if resp.status_code != 200 or "error" in new_token:
                error_msg = new_token.get("error_description") or new_token.get("error", str(new_token))
                return {"status": "error", "message": f"Refresh failed: {error_msg}"}

            # Update token data
            token["access_token"] = new_token.get("access_token", token["access_token"])
            if new_token.get("refresh_token"):
                token["refresh_token"] = new_token["refresh_token"]
            expires_in = new_token.get("expires_in", 3600)
            token["expires_at"] = (datetime.now() + timedelta(seconds=int(expires_in))).isoformat()
            token["refreshed_at"] = datetime.now().isoformat()
            self._save()

            return {"status": "success", "message": "Token refreshed successfully."}

        except Exception as e:
            return {"status": "error", "message": f"Refresh error: {str(e)}"}

    def revoke_token(self, identifier: str) -> dict:
        """Revoke a token and remove from storage."""
        self._load()
        token_id = self._resolve_token_id(identifier)
        if not token_id:
            return {"status": "error", "message": f"No token found for '{identifier}'."}

        token = self._data["tokens"].get(token_id)
        cred_id = token.get("credential_id")
        cred = self._data["credentials"].get(cred_id, {})
        provider = cred.get("provider")
        prov_config = PROVIDERS.get(provider, {})

        # Try to revoke on provider side
        if prov_config.get("revoke_url") and token.get("access_token"):
            try:
                import requests as req_lib
                if provider == "google":
                    req_lib.post(prov_config["revoke_url"],
                                 params={"token": token["access_token"]}, timeout=10)
                elif provider == "tiktok":
                    # TikTok revoke requires client_key, client_secret, and token
                    req_lib.post(
                        prov_config["revoke_url"],
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                        data={
                            "client_key": cred.get("client_id", ""),
                            "client_secret": cred.get("client_secret", ""),
                            "token": token["access_token"],
                        },
                        timeout=10,
                    )
            except Exception as e:
                logger.warning(f"Provider revoke failed (non-critical): {e}")

        # Remove from local storage
        del self._data["tokens"][token_id]
        self._save()
        return {"status": "success", "message": f"Token revoked successfully."}

    # ── Helpers ──────────────────────────────────────────────

    def _get_token_status(self, token_id: str) -> str:
        """Get token status: active, expired, none."""
        token = self._data["tokens"].get(token_id)
        if not token:
            return "none"
        expires_at = token.get("expires_at", "")
        if expires_at:
            try:
                exp_dt = datetime.fromisoformat(expires_at)
                if datetime.now() > exp_dt:
                    return "expired" if token.get("refresh_token") else "revoked"
            except Exception:
                pass
        return "active"

    @staticmethod
    def _mask(value: str) -> str:
        if not value or len(value) < 10:
            return "***"
        return value[:8] + "..." + value[-4:]

    def list_providers(self) -> List[dict]:
        """List all supported providers with credential counts."""
        self._load()
        result = []
        for prov_id, prov_info in PROVIDERS.items():
            cred_count = sum(1 for c in self._data["credentials"].values() if c.get("provider") == prov_id)
            token_count = sum(
                1 for tid, t in self._data["tokens"].items()
                if self._data["credentials"].get(t.get("credential_id", ""), {}).get("provider") == prov_id
            )
            result.append({
                "id": prov_id,
                "name": prov_info["name"],
                "icon": prov_info["icon"],
                "scopes": {k: v["label"] for k, v in prov_info["scopes"].items()},
                "services": prov_info.get("services", {}),
                "credentials_type": prov_info.get("credentials_type", ["oauth_client"]),
                "credential_count": cred_count,
                "token_count": token_count,
            })
        return result


# Global singleton — used by other extensions
auth_manager = AuthManager()


class AuthManagerExtension(Extension):
    name = "auth_manager"
    version = "0.1.0"
    description = "Manage OAuth credentials & tokens for Google, Facebook, TikTok (core extension)"
    author = "TubeCreate"
    extension_type = "system"

    def on_enable(self):
        os.makedirs(os.path.dirname(AUTH_DATA_FILE), exist_ok=True)

    def get_commands(self):
        from tubecli.extensions.auth_manager.commands import auth_group
        return auth_group

    def get_routes(self):
        from tubecli.extensions.auth_manager.routes import router
        return router

    def get_telegram_actions(self):
        return {
            "generate_auth_link": self._action_generate_auth_link
        }

    async def _action_generate_auth_link(self, action_data: dict, context: dict) -> str:
        provider = action_data.get("provider", "google").lower()
        scopes = action_data.get("scopes", [])
        
        credentials = auth_manager.list_credentials(provider)
        if not credentials:
            return f"❌ Chưa có credential ứng dụng nào cho '{provider}'. Vui lòng tạo credential trên giao diện Dashboard (Cài Đặt) trước."
            
        cred_id = action_data.get("credential_id")
        if not cred_id:
            cred_id = credentials[0]["id"]
            
        if not scopes:
            if provider == "google":
                scopes = ["youtube", "youtube_upload", "youtube_readonly"]
            elif provider == "facebook":
                scopes = ["pages_manage", "instagram"]
            elif provider == "tiktok":
                scopes = ["video_list", "video_upload"]
                
        base_url = os.environ.get("TUBECLI_BASE_URL")
        if not base_url:
            try:
                from tubecli.config import get_api_port
                base_url = f"http://localhost:{get_api_port()}"
            except Exception:
                base_url = "http://localhost:5295"
        
        result = auth_manager.build_oauth_url(
            cred_id=cred_id,
            scopes=scopes,
            browser_profile="",
            callback_base=base_url
        )
        
        if result["status"] == "error":
            return f"❌ Lỗi tạo link cấp quyền: {result['message']}"
            
        link = result["auth_url"]
        msg = f"🔗 **Link Cấp Quyền {provider.capitalize()}:**\n\n"
        msg += f"👉 [Bấm Vào Đây Để Cấp Quyền]({link})\n\n"
        msg += f"Sau khi ấn vào link và chọn Tài khoản, hệ thống sẽ tự động lưu lại phiên đăng nhập."
        return msg
