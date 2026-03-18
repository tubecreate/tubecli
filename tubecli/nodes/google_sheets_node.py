"""Built-in node: Google Sheets — read/write/append Google Spreadsheets + auto-create."""
from typing import Dict, Any
from tubecli.nodes.base_node import BaseNode, PortType
import json
import traceback


class GoogleSheetsNode(BaseNode):
    node_type = "google_sheets"
    display_name = "📊 Google Sheets"
    description = "Read, write, or append data to Google Sheets. Auto-creates sheet if not found."
    icon = "📊"
    category = "Integration"

    def _setup_ports(self):
        self.add_input("credentials", PortType.JSON, "Google credentials (from Google Auth node)", required=False)
        self.add_input("data", PortType.JSON, "Data to write (JSON array of arrays)", required=False)
        self.add_input("range", PortType.TEXT, "Cell range override", required=False)
        self.add_output("rows", PortType.JSON, "Sheet data as JSON array")
        self.add_output("spreadsheet_id", PortType.TEXT, "Spreadsheet ID (useful when auto-created)")
        self.add_output("status", PortType.TEXT, "Operation status")

    async def execute(self, inputs: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        action = self.config.get("action", "read")
        spreadsheet_id = self.config.get("spreadsheet_id", "")
        sheet_name = self.config.get("sheet_name", "Sheet1")
        cell_range = inputs.get("range") or self.config.get("range", "A1:Z1000")
        full_range = f"{sheet_name}!{cell_range}"
        title = self.config.get("title", sheet_name)

        # Get credentials
        creds_input = inputs.get("credentials")
        creds_json_str = self.config.get("credentials_json", "")

        try:
            creds_data = None
            scopes = [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
            ]

            if creds_input and isinstance(creds_input, dict) and creds_input.get("_type") == "google_credentials":
                creds_data = creds_input["_creds_data"]
                scopes = creds_input.get("_scopes", scopes)
                # Ensure drive scope is included for auto-create
                if "https://www.googleapis.com/auth/drive" not in scopes:
                    scopes.append("https://www.googleapis.com/auth/drive")
            elif creds_json_str:
                creds_data = json.loads(creds_json_str) if isinstance(creds_json_str, str) else creds_json_str

            if not creds_data:
                return {
                    "rows": [], "spreadsheet_id": "", 
                    "status": "Error: No credentials. Connect Google Auth node or set credentials_json.",
                    "_error_guidance": "Kết nối node 🔐 Google Auth trước node 📊 Google Sheets, hoặc dán Service Account JSON vào config.",
                }

            from google.oauth2.service_account import Credentials
            from googleapiclient.discovery import build

            credentials = Credentials.from_service_account_info(creds_data, scopes=scopes)
            sheets_service = build("sheets", "v4", credentials=credentials)
            sheets = sheets_service.spreadsheets()

            # Auto-create spreadsheet if ID is empty or "auto"
            if not spreadsheet_id or spreadsheet_id.lower() in ("auto", "new", "create"):
                spreadsheet_id, sheet_name = self._create_spreadsheet(
                    sheets_service, title or "TubeCLI Data"
                )
                self.config["spreadsheet_id"] = spreadsheet_id
                self.config["sheet_name"] = sheet_name

            # Fetch actual sheet names to prevent "Unable to parse range" error
            try:
                sheet_metadata = sheets_service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
                actual_sheets = [s.get("properties", {}).get("title") for s in sheet_metadata.get("sheets", [])]
                if sheet_name not in actual_sheets and actual_sheets:
                    # Fallback to the first available sheet if configured one is not found
                    sheet_name = actual_sheets[0]
            except Exception:
                pass # Ignore metadata fetch errors, let the actual action fail

            full_range = f"'{sheet_name}'!{cell_range}" if cell_range else f"'{sheet_name}'"

            # Execute action
            if action == "read":
                result = sheets.values().get(
                    spreadsheetId=spreadsheet_id, range=full_range
                ).execute()
                rows = result.get("values", [])
                return {
                    "rows": rows, "spreadsheet_id": spreadsheet_id,
                    "status": f"✅ Read {len(rows)} rows from {sheet_name}",
                }

            elif action in ("write", "update"):
                data = self._get_data(inputs)
                body = {"values": data}
                sheets.values().update(
                    spreadsheetId=spreadsheet_id, range=full_range,
                    valueInputOption="USER_ENTERED", body=body,
                ).execute()
                return {
                    "rows": data, "spreadsheet_id": spreadsheet_id,
                    "status": f"✅ Updated {len(data)} rows in {sheet_name}",
                }

            elif action == "append":
                data = self._get_data(inputs)
                body = {"values": data}
                # Use A1 notation for append — API auto-detects next empty row
                append_range = f"{sheet_name}!A1"
                sheets.values().append(
                    spreadsheetId=spreadsheet_id, range=append_range,
                    valueInputOption="USER_ENTERED",
                    insertDataOption="INSERT_ROWS",
                    body=body,
                ).execute()
                return {
                    "rows": data, "spreadsheet_id": spreadsheet_id,
                    "status": f"✅ Appended {len(data)} rows to {sheet_name}",
                }

            elif action == "clear":
                sheets.values().clear(
                    spreadsheetId=spreadsheet_id, range=full_range, body={}
                ).execute()
                return {
                    "rows": [], "spreadsheet_id": spreadsheet_id,
                    "status": f"✅ Cleared {full_range}",
                }

            else:
                return {
                    "rows": [], "spreadsheet_id": spreadsheet_id,
                    "status": f"Error: Unknown action '{action}'. Use: read, write, append, update, clear",
                }

        except ImportError as e:
            return {
                "rows": [], "spreadsheet_id": "",
                "status": f"Error: Missing package — {e}",
                "_error_guidance": "Chạy: pip install google-auth google-api-python-client",
            }
        except Exception as e:
            tb = traceback.format_exc()
            # Extract error details for Google API HttpError
            error_msg = ""
            try:
                from googleapiclient.errors import HttpError
                if isinstance(e, HttpError):
                    status_code = e.resp.status if hasattr(e, 'resp') else '?'
                    content = e.content.decode('utf-8') if hasattr(e, 'content') and e.content else ''
                    reason = e.reason if hasattr(e, 'reason') else ''
                    error_msg = f"HTTP {status_code}: {reason or content[:300]}"
            except Exception:
                pass
            if not error_msg:
                error_msg = str(e) or repr(e)
            if not error_msg or error_msg in ("", "''", '""'):
                lines = [l for l in tb.strip().split("\n") if l.strip()]
                error_msg = lines[-1] if lines else "Unknown error"
            guidance = self._get_error_guidance(error_msg + " " + tb)
            return {
                "rows": [], "spreadsheet_id": spreadsheet_id or "",
                "status": f"Error: {error_msg}",
                "_error_guidance": guidance,
                "_traceback": tb,
            }

    def _get_data(self, inputs: Dict[str, Any]) -> list:
        """Extract data from inputs or config, ensuring it's a 2D array."""
        data = inputs.get("data") or self.config.get("data", [])
        if isinstance(data, str):
            data = json.loads(data)
        # Ensure 2D array
        if data and not isinstance(data[0], list):
            data = [data]
        return data

    def _create_spreadsheet(self, sheets_service, title: str):
        """Create a new Google Spreadsheet and return (id, first_sheet_name)."""
        body = {
            "properties": {"title": title},
            "sheets": [{"properties": {"title": "Sheet1"}}],
        }
        result = sheets_service.spreadsheets().create(body=body).execute()
        spreadsheet_id = result["spreadsheetId"]
        # Get actual sheet tab name from response
        first_sheet = result.get("sheets", [{}])[0]
        tab_name = first_sheet.get("properties", {}).get("title", "Sheet1")
        return spreadsheet_id, tab_name

    def _get_error_guidance(self, error_msg: str) -> str:
        """Return AI-friendly guidance based on common error patterns."""
        e = error_msg.lower()

        if "404" in e or "not found" in e:
            return (
                "Spreadsheet không tìm thấy. Kiểm tra spreadsheet_id hoặc đặt thành 'auto' để tự tạo mới. "
                "Đảm bảo đã share sheet cho service account email."
            )
        if "403" in e or "permission" in e or "forbidden" in e:
            return (
                "Không có quyền truy cập. Mở Google Sheet → Share → thêm email service account "
                "(client_email trong JSON key) với quyền Editor."
            )
        if "401" in e or "unauthorized" in e or "invalid_grant" in e:
            return "Credentials không hợp lệ hoặc hết hạn. Tạo lại JSON key từ Google Cloud Console."
        if "quota" in e or "rate" in e:
            return "Đã vượt quota API. Đợi vài phút hoặc tăng quota trong Google Cloud Console."
        if "invalid" in e and "range" in e:
            return f"Range không hợp lệ. Dùng định dạng 'A1:Z1000' hoặc 'Sheet1!A1:D10'."
        if "api" in e and ("not enabled" in e or "disabled" in e):
            return (
                "Google Sheets API chưa được bật. Vào Google Cloud Console → APIs & Services → "
                "Library → tìm 'Google Sheets API' → Enable."
            )

        return f"Lỗi không xác định: {error_msg}. Kiểm tra credentials, spreadsheet_id, và quyền truy cập."
