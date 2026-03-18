"""Built-in node: Google Auth — provides Google API credentials."""
from typing import Dict, Any
from tubecli.nodes.base_node import BaseNode, PortType
import json


class GoogleAuthNode(BaseNode):
    node_type = "google_auth"
    display_name = "🔐 Google Auth"
    description = "Authenticate with Google APIs using a service account JSON key."
    icon = "🔐"
    category = "Auth"

    def _setup_ports(self):
        self.add_output("credentials", PortType.JSON, "Google credentials object")
        self.add_output("status", PortType.TEXT, "Auth status message")

    async def execute(self, inputs: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        creds_json = self.config.get("credentials_json", "")
        scopes_str = self.config.get("scopes", "https://www.googleapis.com/auth/spreadsheets,https://www.googleapis.com/auth/drive")

        if not creds_json:
            return {"credentials": None, "status": "Error: No credentials_json provided"}

        try:
            creds_data = json.loads(creds_json) if isinstance(creds_json, str) else creds_json
            scopes = [s.strip() for s in scopes_str.split(",")]

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
                "status": f"✅ Authenticated as {creds_data.get('client_email', 'unknown')}",
            }

        except ImportError:
            return {"credentials": None, "status": "Error: google-auth not installed. Run: pip install google-auth"}
        except json.JSONDecodeError:
            return {"credentials": None, "status": "Error: Invalid JSON in credentials_json"}
        except Exception as e:
            return {"credentials": None, "status": f"Error: {e}"}
