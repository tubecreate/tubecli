"""Built-in node: Google Auth — provides Google API credentials."""
from typing import Dict, Any
from tubecli.nodes.base_node import BaseNode, PortType
import json


class GoogleAuthNode(BaseNode):
    node_type = "google_auth"
    display_name = "🔐 Google Auth"
    description = "Authenticate with Google APIs using Auth Manager OAuth or service account JSON."
    icon = "🔐"
    category = "Auth"
    config_schema = {
        "scopes": {"type": "string", "description": "Comma-separated OAuth scopes. Usually leave default; node auto-uses saved credentials.", "default": "https://www.googleapis.com/auth/spreadsheets,https://www.googleapis.com/auth/drive"},
        "credentials_json": {"type": "string", "description": "Optional inline service-account JSON. Leave empty to use saved OAuth from Auth Manager."},
    }

    def _setup_ports(self):
        self.add_output("credentials", PortType.JSON, "Google credentials object")
        self.add_output("status", PortType.TEXT, "Auth status message")

    async def execute(self, inputs: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        scopes_str = self.config.get("scopes", "https://www.googleapis.com/auth/spreadsheets,https://www.googleapis.com/auth/drive")
        scopes = [s.strip() for s in scopes_str.split(",")]

        # ── Strategy 1: Use Auth Manager extension (OAuth tokens) ──
        auth_result = self._try_auth_manager(scopes, **kwargs)
        if auth_result:
            return auth_result

        # ── Strategy 2: Use service account JSON (manual config) ──
        creds_json = self.config.get("credentials_json", "")
        if creds_json:
            return self._try_service_account(creds_json, scopes)

        return {
            "credentials": None,
            "status": "Error: Không tìm thấy credentials. Vui lòng cấp quyền Google trong Auth Manager hoặc nhập Service Account JSON."
        }

    def _try_auth_manager(self, scopes: list, **kwargs) -> Dict[str, Any] | None:
        """Try to get credentials from auth_manager extension."""
        try:
            from tubecli.extensions.auth_manager.extension import auth_manager

            # Find Google credentials with active tokens
            google_creds = auth_manager.list_credentials(provider="google")
            if not google_creds:
                return None

            # Find one that has an active token and matching scopes
            best_cred = None
            for cred in google_creds:
                if cred.get("has_token") and cred.get("token_status") == "active":
                    best_cred = cred
                    break
                elif cred.get("has_token") and cred.get("token_status") == "expired":
                    # Still viable — get_active_token will auto-refresh
                    if not best_cred:
                        best_cred = cred

            if not best_cred:
                return None

            cred_id = best_cred["id"]
            
            # Determine profile name from execution context
            profile_name = "default"
            agent_context = kwargs.get("agent_context", {})
            if agent_context:
                profile_name = agent_context.get("browser_profile", "") or agent_context.get("profile_name", "default")
            
            # Use profile-specific token to support Multi-Token
            access_token = auth_manager.get_active_token_for_profile(cred_id, profile_name)
            if not access_token:
                # Fallback to general lookup just in case
                access_token = auth_manager.get_active_token(cred_id)
                
            if not access_token:
                return None

            # Get full credential data for service account fallback info
            # Re-resolve the correct token ID matching the profile
            token_id = auth_manager._resolve_token_id(cred_id)
            for t_id, t_data in auth_manager._data.get("tokens", {}).items():
                if t_data.get("credential_id") == cred_id and t_data.get("browser_profile") == profile_name:
                    token_id = t_id
                    break

            token_data = auth_manager.get_token_data(token_id)

            return {
                "credentials": {
                    "_type": "google_oauth",
                    "_access_token": access_token,
                    "_credential_id": cred_id,
                    "_scopes": scopes,
                    "client_email": token_data.get("authorized_email", "") if token_data else "",
                    "credential_name": best_cred.get("name", ""),
                    "project_id": "",
                },
                "status": f"✅ OAuth: {token_data.get('authorized_email', 'authorized')} (via Auth Manager: {best_cred.get('name', cred_id)})",
            }

        except ImportError:
            return None
        except Exception as e:
            import logging
            logging.getLogger("GoogleAuthNode").warning(f"Auth Manager lookup failed: {e}")
            return None

    def _try_service_account(self, creds_json: str, scopes: list) -> Dict[str, Any]:
        """Authenticate using service account JSON key."""
        try:
            creds_data = json.loads(creds_json) if isinstance(creds_json, str) else creds_json

            from google.oauth2.service_account import Credentials
            credentials = Credentials.from_service_account_info(creds_data, scopes=scopes)

            return {
                "credentials": {
                    "_type": "google_credentials",
                    "_creds_data": creds_data,
                    "_scopes": scopes,
                    "project_id": creds_data.get("project_id", ""),
                    "client_email": creds_data.get("client_email", ""),
                },
                "status": f"✅ Service Account: {creds_data.get('client_email', 'unknown')}",
            }

        except ImportError:
            return {"credentials": None, "status": "Error: google-auth not installed. Run: pip install google-auth"}
        except json.JSONDecodeError:
            return {"credentials": None, "status": "Error: Invalid JSON in credentials_json"}
        except Exception as e:
            return {"credentials": None, "status": f"Error: {e}"}

