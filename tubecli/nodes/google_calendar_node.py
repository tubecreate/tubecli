"""Built-in node: Google Calendar — list/create/update/delete events + recurring schedules."""
from typing import Dict, Any
from tubecli.nodes.base_node import BaseNode, PortType
import json
import traceback


class GoogleCalendarNode(BaseNode):
    node_type = "google_calendar"
    display_name = "📅 Google Calendar"
    description = "List, create, update, or delete Google Calendar events. Supports recurring events."
    icon = "📅"
    category = "Integration"
    config_schema = {
        "action": {"type": "string", "required": True, "description": "Calendar operation.", "default": "list", "options": ["list", "create", "update", "delete", "quick_add"]},
        "calendar_id": {"type": "string", "description": "Calendar ID.", "default": "primary"},
        "summary": {"type": "string", "description": "Event title (for create/update)."},
        "start_time": {"type": "string", "description": "Start datetime ISO 8601, e.g. 2026-07-09T09:00:00."},
        "end_time": {"type": "string", "description": "End datetime ISO 8601."},
        "description": {"type": "string", "description": "Event description."},
        "location": {"type": "string", "description": "Event location."},
        "event_id": {"type": "string", "description": "Event ID (for update/delete)."},
        "recurrence": {"type": "string", "description": "RRULE string for recurring events, e.g. RRULE:FREQ=DAILY."},
        "time_zone": {"type": "string", "description": "IANA timezone.", "default": "Asia/Ho_Chi_Minh"},
        "quick_text": {"type": "string", "description": "Natural language event for quick_add, e.g. 'Meeting tomorrow 3pm'."},
    }

    def _setup_ports(self):
        self.add_input("credentials", PortType.JSON, "Google credentials (from Google Auth node)", required=False)
        self.add_input("event_data", PortType.JSON, "Event data (JSON with summary, start, end, etc.)", required=False)
        self.add_output("events", PortType.JSON, "Calendar events as JSON array")
        self.add_output("event_id", PortType.TEXT, "Created/updated event ID")
        self.add_output("status", PortType.TEXT, "Operation status")

    async def execute(self, inputs: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        action = self.config.get("action", "list")
        calendar_id = self.config.get("calendar_id", "primary")
        summary = self.config.get("summary", "")
        start_time = self.config.get("start_time", "")
        end_time = self.config.get("end_time", "")
        description = self.config.get("description", "")
        location = self.config.get("location", "")
        event_id = self.config.get("event_id", "")
        recurrence_str = self.config.get("recurrence", "")
        time_zone = self.config.get("time_zone", "Asia/Ho_Chi_Minh")
        quick_text = self.config.get("quick_text", "")

        # Get credentials
        creds_input = inputs.get("credentials")
        event_data_input = inputs.get("event_data")

        # Override from event_data input if provided
        if event_data_input and isinstance(event_data_input, dict):
            summary = event_data_input.get("summary", summary)
            start_time = event_data_input.get("start", start_time)
            end_time = event_data_input.get("end", end_time)
            description = event_data_input.get("description", description)
            location = event_data_input.get("location", location)
            event_id = event_data_input.get("event_id", event_id)
            recurrence_str = event_data_input.get("recurrence", recurrence_str)
            quick_text = event_data_input.get("text", quick_text) or event_data_input.get("quick_text", quick_text)
        elif event_data_input and isinstance(event_data_input, str):
            # If event_data is a string, try parsing as JSON
            try:
                parsed = json.loads(event_data_input)
                if isinstance(parsed, dict):
                    summary = parsed.get("summary", summary)
                    start_time = parsed.get("start", start_time)
                    end_time = parsed.get("end", end_time)
                    description = parsed.get("description", description)
                    quick_text = parsed.get("text", quick_text)
            except (json.JSONDecodeError, TypeError):
                # Plain text — use as quick_text for quick_add action
                if action == "quick_add":
                    quick_text = event_data_input

        try:
            credentials = None
            scopes = ["https://www.googleapis.com/auth/calendar"]

            if creds_input and isinstance(creds_input, dict):
                cred_type = creds_input.get("_type", "")
                if cred_type == "google_oauth":
                    from google.oauth2.credentials import Credentials as OAuthCredentials
                    access_token = creds_input.get("_access_token", "")
                    if not access_token:
                        return {
                            "events": [], "event_id": "",
                            "status": "Error: OAuth token is empty. Re-authorize in Auth Manager.",
                        }
                    credentials = OAuthCredentials(token=access_token)
                elif cred_type == "google_credentials":
                    creds_data = creds_input["_creds_data"]
                    from google.oauth2.service_account import Credentials
                    credentials = Credentials.from_service_account_info(creds_data, scopes=scopes)

            # Fallback: try CalendarManager auto-detection
            if not credentials:
                try:
                    from tubecli.extensions.calendar_manager.extension import calendar_manager
                    # Use calendar_manager which auto-finds credentials
                    return await self._execute_via_manager(calendar_manager, action, calendar_id,
                                                           summary, start_time, end_time, description,
                                                           location, event_id, recurrence_str, time_zone, quick_text)
                except ImportError:
                    return {
                        "events": [], "event_id": "",
                        "status": "Error: No credentials. Connect Google Auth node or configure Auth Manager.",
                    }

            # Direct API execution with credentials
            from googleapiclient.discovery import build
            service = build("calendar", "v3", credentials=credentials)

            if action == "list":
                return self._action_list(service, calendar_id, start_time, end_time)
            elif action == "create":
                return self._action_create(service, calendar_id, summary, start_time, end_time,
                                           description, location, recurrence_str, time_zone)
            elif action == "update":
                return self._action_update(service, calendar_id, event_id, summary, start_time,
                                           end_time, description, location, recurrence_str, time_zone)
            elif action == "delete":
                return self._action_delete(service, calendar_id, event_id)
            elif action == "quick_add":
                return self._action_quick_add(service, calendar_id, quick_text or summary)
            elif action == "list_calendars":
                return self._action_list_calendars(service)
            else:
                return {
                    "events": [], "event_id": "",
                    "status": f"Error: Unknown action '{action}'. Use: list, create, update, delete, quick_add, list_calendars",
                }

        except ImportError as e:
            return {
                "events": [], "event_id": "",
                "status": f"Error: Missing package — {e}",
                "_error_guidance": "Run: pip install google-auth google-api-python-client",
            }
        except Exception as e:
            tb = traceback.format_exc()
            return {
                "events": [], "event_id": "",
                "status": f"Error: {e}",
                "_traceback": tb,
            }

    async def _execute_via_manager(self, mgr, action, calendar_id, summary, start_time,
                                    end_time, description, location, event_id, recurrence_str,
                                    time_zone, quick_text):
        """Execute via CalendarManager (auto-finds credentials)."""
        recurrence = [recurrence_str] if recurrence_str else []

        if action == "list":
            result = mgr.list_events(calendar_id=calendar_id, time_min=start_time, time_max=end_time)
            return {"events": result.get("events", []), "event_id": "", "status": result.get("message", f"✅ {result.get('count', 0)} events found")}
        elif action == "create":
            result = mgr.create_event(calendar_id=calendar_id, summary=summary, start=start_time,
                                       end=end_time, description=description, location=location,
                                       recurrence=recurrence, time_zone=time_zone)
            return {"events": [], "event_id": result.get("event_id", ""), "status": result.get("message", str(result))}
        elif action == "update":
            result = mgr.update_event(calendar_id=calendar_id, event_id=event_id, summary=summary,
                                       start=start_time, end=end_time, description=description,
                                       location=location, recurrence=recurrence, time_zone=time_zone)
            return {"events": [], "event_id": result.get("event_id", ""), "status": result.get("message", str(result))}
        elif action == "delete":
            result = mgr.delete_event(calendar_id=calendar_id, event_id=event_id)
            return {"events": [], "event_id": event_id, "status": result.get("message", str(result))}
        elif action == "quick_add":
            result = mgr.quick_add(calendar_id=calendar_id, text=quick_text or summary)
            return {"events": [], "event_id": result.get("event_id", ""), "status": result.get("message", str(result))}
        elif action == "list_calendars":
            result = mgr.list_calendars()
            return {"events": result.get("calendars", []), "event_id": "", "status": f"✅ {result.get('count', 0)} calendars found"}
        else:
            return {"events": [], "event_id": "", "status": f"Error: Unknown action '{action}'"}

    # ── Direct API Actions ───────────────────────────────────

    def _action_list(self, service, calendar_id, time_min, time_max):
        from datetime import datetime, timedelta, timezone as tz
        if not time_min:
            time_min = datetime.now(tz.utc).isoformat()
        if not time_max:
            time_max = (datetime.now(tz.utc) + timedelta(days=7)).isoformat()

        result = service.events().list(
            calendarId=calendar_id, timeMin=time_min, timeMax=time_max,
            maxResults=50, singleEvents=True, orderBy="startTime",
        ).execute()

        events = []
        for ev in result.get("items", []):
            start = ev.get("start", {})
            events.append({
                "id": ev.get("id"),
                "summary": ev.get("summary", "(No title)"),
                "start": start.get("dateTime") or start.get("date", ""),
                "description": ev.get("description", ""),
            })
        return {"events": events, "event_id": "", "status": f"✅ Found {len(events)} events"}

    def _action_create(self, service, calendar_id, summary, start, end, desc, location, recurrence_str, tz):
        from datetime import datetime, timedelta
        if not end:
            try:
                end = (datetime.fromisoformat(start) + timedelta(hours=1)).isoformat()
            except Exception:
                end = start

        body = {
            "summary": summary,
            "start": {"dateTime": start, "timeZone": tz},
            "end": {"dateTime": end, "timeZone": tz},
        }
        if desc:
            body["description"] = desc
        if location:
            body["location"] = location
        if recurrence_str:
            body["recurrence"] = [recurrence_str]

        result = service.events().insert(calendarId=calendar_id, body=body).execute()
        return {
            "events": [], "event_id": result.get("id", ""),
            "status": f"✅ Event '{summary}' created",
        }

    def _action_update(self, service, calendar_id, event_id, summary, start, end, desc, location, recurrence_str, tz):
        existing = service.events().get(calendarId=calendar_id, eventId=event_id).execute()
        if summary:
            existing["summary"] = summary
        if desc:
            existing["description"] = desc
        if location:
            existing["location"] = location
        if start:
            existing["start"] = {"dateTime": start, "timeZone": tz}
        if end:
            existing["end"] = {"dateTime": end, "timeZone": tz}
        if recurrence_str:
            existing["recurrence"] = [recurrence_str]

        result = service.events().update(calendarId=calendar_id, eventId=event_id, body=existing).execute()
        return {
            "events": [], "event_id": result.get("id", ""),
            "status": f"✅ Event '{result.get('summary')}' updated",
        }

    def _action_delete(self, service, calendar_id, event_id):
        service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
        return {"events": [], "event_id": event_id, "status": f"✅ Event '{event_id}' deleted"}

    def _action_quick_add(self, service, calendar_id, text):
        result = service.events().quickAdd(calendarId=calendar_id, text=text).execute()
        return {
            "events": [], "event_id": result.get("id", ""),
            "status": f"✅ Quick-added: '{result.get('summary', text)}'",
        }

    def _action_list_calendars(self, service):
        result = service.calendarList().list().execute()
        calendars = [
            {"id": c.get("id"), "summary": c.get("summary", ""), "primary": c.get("primary", False)}
            for c in result.get("items", [])
        ]
        return {"events": calendars, "event_id": "", "status": f"✅ {len(calendars)} calendars found"}
