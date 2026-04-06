"""
Calendar Manager Extension — Core logic for Google Calendar events.
Uses Auth Manager OAuth tokens to interact with Google Calendar API.
Supports recurring events (RRULE) and Telegram reminders.
"""
import os
import json
import logging
import threading
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any

from tubecli.core.extension_manager import Extension
from tubecli.config import DATA_DIR

logger = logging.getLogger("CalendarManagerExtension")

CALENDAR_DATA_FILE = os.path.join(DATA_DIR, "calendar_manager.json")

# Default reminder minutes before event
DEFAULT_REMINDER_MINUTES = 15


class CalendarManager:
    """Manages Google Calendar events via Auth Manager credentials."""

    def __init__(self, data_file: str = CALENDAR_DATA_FILE):
        self.data_file = data_file
        self._data: Dict[str, Any] = {"reminder_settings": {}, "notified_events": []}
        self._reminder_thread: Optional[threading.Thread] = None
        self._reminder_stop = threading.Event()
        self._load()

    # ── Load / Save ──────────────────────────────────────────

    def _load(self):
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            except Exception:
                pass

    def _save(self):
        os.makedirs(os.path.dirname(self.data_file), exist_ok=True)
        with open(self.data_file, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)

    # ── Credential Resolution ────────────────────────────────

    def _get_credentials(self, cred_id: str = "", email: str = ""):
        """Get Google OAuth credentials from Auth Manager.
        Returns a tuple of (OAuthCredentials, resolved_token_id).
        Note: We return resolved_token_id so caller knows the exact token.
        """
        try:
            from tubecli.extensions.auth_manager.extension import auth_manager

            if not email:
                email = self._get_default_calendar_email()

            # If an explicit identifier is provided, try to use it directly
            if cred_id:
                # cred_id might actually be a token_id here if we pass it around
                access_token = auth_manager.get_active_token(cred_id)
                if access_token:
                    from google.oauth2.credentials import Credentials as OAuthCredentials
                    return OAuthCredentials(token=access_token), cred_id
                return None, cred_id

            tokens = auth_manager.list_tokens(provider="google")
            best_token_id = None

            # 1. Find a token matching email AND having calendar scope
            if email:
                for t in tokens:
                    if t.get("authorized_email", "").lower() == email.lower():
                        # Check scopes
                        scopes = t.get("scopes", [])
                        # "calendar" scope is required for creation, or "calendar.readonly" for listing
                        if any("calendar" in s for s in scopes):
                            best_token_id = t.get("token_id")
                            break

            # 2. Fallback: Any token that has calendar scope (regardless of email)
            if not best_token_id:
                for t in tokens:
                    scopes = t.get("scopes", [])
                    if any("calendar" in s for s in scopes):
                        best_token_id = t.get("token_id")
                        break
            
            # 3. Last resort fallback: matching email (if user manually crafted scopes or we failed scope check)
            if not best_token_id and email:
                for t in tokens:
                    if t.get("authorized_email", "").lower() == email.lower():
                        best_token_id = t.get("token_id")
                        break

            if best_token_id:
                access_token = auth_manager.get_active_token(best_token_id)
                if access_token:
                    from google.oauth2.credentials import Credentials as OAuthCredentials
                    return OAuthCredentials(token=access_token), best_token_id

        except ImportError:
            logger.warning("Auth Manager or google-auth not available")
        except Exception as e:
            logger.error(f"Error getting calendar credentials: {e}")

        return None, ""

    def _build_service(self, credentials):
        """Build Google Calendar API service."""
        from googleapiclient.discovery import build
        return build("calendar", "v3", credentials=credentials)

    # ── Calendar Operations ──────────────────────────────────

    def list_calendars(self, cred_id: str = "", email: str = "") -> dict:
        """List all calendars for the authenticated user."""
        credentials, resolved_id = self._get_credentials(cred_id, email)
        if not credentials:
            return {"status": "error", "message": "No valid Google credentials found. Authorize via Auth Manager first.", "calendars": []}

        try:
            service = self._build_service(credentials)
            result = service.calendarList().list().execute()
            calendars = []
            for cal in result.get("items", []):
                calendars.append({
                    "id": cal.get("id"),
                    "summary": cal.get("summary", ""),
                    "description": cal.get("description", ""),
                    "primary": cal.get("primary", False),
                    "access_role": cal.get("accessRole", ""),
                    "background_color": cal.get("backgroundColor", ""),
                    "time_zone": cal.get("timeZone", ""),
                })
            return {"status": "success", "calendars": calendars, "count": len(calendars), "credential_id": resolved_id}
        except Exception as e:
            return {"status": "error", "message": str(e), "calendars": []}

    def list_events(
        self,
        cred_id: str = "",
        email: str = "",
        calendar_id: str = "primary",
        time_min: str = "",
        time_max: str = "",
        max_results: int = 50,
        query: str = "",
    ) -> dict:
        """List events from a calendar."""
        credentials, resolved_id = self._get_credentials(cred_id, email)
        if not credentials:
            return {"status": "error", "message": "No valid Google credentials found.", "events": []}

        try:
            service = self._build_service(credentials)

            # Default: from now to 7 days ahead
            if not time_min:
                time_min = datetime.now(timezone.utc).isoformat()
            if not time_max:
                time_max = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()

            params = {
                "calendarId": calendar_id,
                "timeMin": time_min,
                "timeMax": time_max,
                "maxResults": max_results,
                "singleEvents": True,
                "orderBy": "startTime",
            }
            if query:
                params["q"] = query

            result = service.events().list(**params).execute()
            events = []
            for ev in result.get("items", []):
                start = ev.get("start", {})
                end = ev.get("end", {})
                events.append({
                    "id": ev.get("id"),
                    "summary": ev.get("summary", "(No title)"),
                    "description": ev.get("description", ""),
                    "start": start.get("dateTime") or start.get("date", ""),
                    "end": end.get("dateTime") or end.get("date", ""),
                    "location": ev.get("location", ""),
                    "status": ev.get("status", ""),
                    "html_link": ev.get("htmlLink", ""),
                    "recurrence": ev.get("recurrence", []),
                    "attendees": [a.get("email", "") for a in ev.get("attendees", [])],
                    "creator": ev.get("creator", {}).get("email", ""),
                })

            return {"status": "success", "events": events, "count": len(events), "credential_id": resolved_id}
        except Exception as e:
            return {"status": "error", "message": str(e), "events": []}

    def create_event(
        self,
        cred_id: str = "",
        email: str = "",
        calendar_id: str = "primary",
        summary: str = "",
        start: str = "",
        end: str = "",
        description: str = "",
        location: str = "",
        attendees: List[str] = None,
        recurrence: List[str] = None,
        reminders_minutes: List[int] = None,
        time_zone: str = "Asia/Ho_Chi_Minh",
    ) -> dict:
        """Create a calendar event with optional recurrence."""
        credentials, resolved_id = self._get_credentials(cred_id, email)
        if not credentials:
            return {"status": "error", "message": "No valid Google credentials found."}

        if not summary:
            return {"status": "error", "message": "Event summary (title) is required."}
        if not start:
            return {"status": "error", "message": "Start time is required."}

        # Default end = start + 1 hour
        if not end:
            try:
                start_dt = datetime.fromisoformat(start)
                end = (start_dt + timedelta(hours=1)).isoformat()
            except Exception:
                end = start

        try:
            service = self._build_service(credentials)

            event_body: Dict[str, Any] = {
                "summary": summary,
                "start": {"dateTime": start, "timeZone": time_zone},
                "end": {"dateTime": end, "timeZone": time_zone},
            }

            if description:
                event_body["description"] = description
            if location:
                event_body["location"] = location
            if attendees:
                event_body["attendees"] = [{"email": e} for e in attendees]
            if recurrence:
                event_body["recurrence"] = recurrence

            # Reminders
            if reminders_minutes:
                event_body["reminders"] = {
                    "useDefault": False,
                    "overrides": [{"method": "popup", "minutes": m} for m in reminders_minutes],
                }

            result = service.events().insert(calendarId=calendar_id, body=event_body).execute()

            return {
                "status": "success",
                "event_id": result.get("id"),
                "html_link": result.get("htmlLink", ""),
                "summary": result.get("summary"),
                "start": result.get("start", {}).get("dateTime", ""),
                "end": result.get("end", {}).get("dateTime", ""),
                "recurrence": result.get("recurrence", []),
                "message": f"✅ Event '{summary}' created successfully.",
            }
        except Exception as e:
            return {"status": "error", "message": f"Failed to create event: {e}"}

    def update_event(
        self,
        cred_id: str = "",
        email: str = "",
        calendar_id: str = "primary",
        event_id: str = "",
        summary: str = None,
        start: str = None,
        end: str = None,
        description: str = None,
        location: str = None,
        recurrence: List[str] = None,
        time_zone: str = "Asia/Ho_Chi_Minh",
    ) -> dict:
        """Update an existing calendar event."""
        credentials, resolved_id = self._get_credentials(cred_id, email)
        if not credentials:
            return {"status": "error", "message": "No valid Google credentials found."}
        if not event_id:
            return {"status": "error", "message": "Event ID is required."}

        try:
            service = self._build_service(credentials)

            # Get existing event first
            existing = service.events().get(calendarId=calendar_id, eventId=event_id).execute()

            if summary is not None:
                existing["summary"] = summary
            if description is not None:
                existing["description"] = description
            if location is not None:
                existing["location"] = location
            if start is not None:
                existing["start"] = {"dateTime": start, "timeZone": time_zone}
            if end is not None:
                existing["end"] = {"dateTime": end, "timeZone": time_zone}
            if recurrence is not None:
                existing["recurrence"] = recurrence

            result = service.events().update(
                calendarId=calendar_id, eventId=event_id, body=existing
            ).execute()

            return {
                "status": "success",
                "event_id": result.get("id"),
                "summary": result.get("summary"),
                "message": f"✅ Event '{result.get('summary')}' updated.",
            }
        except Exception as e:
            return {"status": "error", "message": f"Failed to update event: {e}"}

    def delete_event(
        self,
        cred_id: str = "",
        email: str = "",
        calendar_id: str = "primary",
        event_id: str = "",
    ) -> dict:
        """Delete a calendar event."""
        credentials, resolved_id = self._get_credentials(cred_id, email)
        if not credentials:
            return {"status": "error", "message": "No valid Google credentials found."}
        if not event_id:
            return {"status": "error", "message": "Event ID is required."}

        try:
            service = self._build_service(credentials)
            service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
            return {"status": "success", "event_id": event_id, "message": f"✅ Event '{event_id}' deleted."}
        except Exception as e:
            return {"status": "error", "message": f"Failed to delete event: {e}"}

    def quick_add(
        self,
        cred_id: str = "",
        email: str = "",
        calendar_id: str = "primary",
        text: str = "",
    ) -> dict:
        """Quick add an event from natural language text."""
        credentials, resolved_id = self._get_credentials(cred_id, email)
        if not credentials:
            return {"status": "error", "message": "No valid Google credentials found."}
        if not text:
            return {"status": "error", "message": "Text description is required."}

        try:
            service = self._build_service(credentials)
            result = service.events().quickAdd(calendarId=calendar_id, text=text).execute()
            return {
                "status": "success",
                "event_id": result.get("id"),
                "summary": result.get("summary", text),
                "start": result.get("start", {}).get("dateTime", ""),
                "html_link": result.get("htmlLink", ""),
                "message": f"✅ Quick-added: '{result.get('summary', text)}'",
            }
        except Exception as e:
            return {"status": "error", "message": f"Failed to quick-add event: {e}"}

    # ── Telegram Reminder System ─────────────────────────────

    def get_upcoming_events_for_reminder(
        self, email: str = "", minutes_ahead: int = DEFAULT_REMINDER_MINUTES
    ) -> List[dict]:
        """Get events starting within the next N minutes (for Telegram reminders)."""
        now = datetime.now(timezone.utc)
        time_min = now.isoformat()
        time_max = (now + timedelta(minutes=minutes_ahead + 1)).isoformat()

        result = self.list_events(email=email, time_min=time_min, time_max=time_max, max_results=10)
        if result["status"] != "success":
            return []

        upcoming = []
        for ev in result.get("events", []):
            start_str = ev.get("start", "")
            if not start_str:
                continue
            try:
                start_dt = datetime.fromisoformat(start_str)
                # Make timezone-aware if naive
                if start_dt.tzinfo is None:
                    start_dt = start_dt.replace(tzinfo=timezone.utc)
                diff_minutes = (start_dt - now).total_seconds() / 60
                if 0 <= diff_minutes <= minutes_ahead:
                    ev["_minutes_until"] = round(diff_minutes)
                    upcoming.append(ev)
            except Exception:
                continue

        return upcoming

    def is_event_notified(self, event_id: str, date_str: str = "") -> bool:
        """Check if we already sent a reminder for this event today."""
        self._load()
        today = date_str or datetime.now().strftime("%Y-%m-%d")
        key = f"{event_id}_{today}"
        notified = self._data.get("notified_events", [])
        return key in notified

    def mark_event_notified(self, event_id: str, date_str: str = ""):
        """Mark event as notified for today."""
        self._load()
        today = date_str or datetime.now().strftime("%Y-%m-%d")
        key = f"{event_id}_{today}"
        notified = self._data.setdefault("notified_events", [])
        if key not in notified:
            notified.append(key)
        # Keep only last 500 entries
        if len(notified) > 500:
            self._data["notified_events"] = notified[-500:]
        self._save()

    def start_reminder_daemon(self, check_interval_sec: int = 60):
        """Start background thread that checks for upcoming events and sends Telegram reminders."""
        if self._reminder_thread and self._reminder_thread.is_alive():
            return

        self._reminder_stop.clear()
        self._reminder_thread = threading.Thread(
            target=self._reminder_loop,
            args=(check_interval_sec,),
            daemon=True,
        )
        self._reminder_thread.start()
        logger.info("Calendar reminder daemon started")

    def stop_reminder_daemon(self):
        """Stop the reminder daemon."""
        self._reminder_stop.set()
        if self._reminder_thread:
            self._reminder_thread.join(timeout=3)

    def _reminder_loop(self, interval_sec: int):
        """Background loop: check upcoming events and send Telegram reminders."""
        while not self._reminder_stop.is_set():
            try:
                self._check_and_notify()
            except Exception as e:
                logger.error(f"Reminder check error: {e}")

            for _ in range(interval_sec):
                if self._reminder_stop.is_set():
                    break
                import time
                time.sleep(1)

    def _check_and_notify(self):
        """Check for events starting soon and send Telegram notifications."""
        # Read default calendar email from global settings
        email = self._get_default_calendar_email()
        if not email:
            return

        # Read reminder minutes setting
        reminder_minutes = self._data.get("reminder_settings", {}).get(
            "minutes_before", DEFAULT_REMINDER_MINUTES
        )

        upcoming = self.get_upcoming_events_for_reminder(email=email, minutes_ahead=reminder_minutes)

        for ev in upcoming:
            event_id = ev.get("id", "")
            if not event_id or self.is_event_notified(event_id):
                continue

            # Build notification message
            summary = ev.get("summary", "No title")
            start = ev.get("start", "")
            minutes_until = ev.get("_minutes_until", 0)
            location = ev.get("location", "")

            msg = f"📅 **Nhắc nhở lịch**\n\n"
            msg += f"🔔 **{summary}**\n"
            msg += f"⏰ Bắt đầu sau {minutes_until} phút\n"
            msg += f"🕐 {start}\n"
            if location:
                msg += f"📍 {location}\n"

            # Send via Telegram
            self._send_telegram_reminder(msg)
            self.mark_event_notified(event_id)
            print(f"[Calendar] 🔔 Reminder sent: {summary} (in {minutes_until}m)")

    def _get_default_calendar_email(self) -> str:
        """Read default_calendar_email from global_settings.json."""
        try:
            settings_file = os.path.join(str(DATA_DIR), "global_settings.json")
            if os.path.exists(settings_file):
                with open(settings_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("default_calendar_email", "")
        except Exception:
            pass
        return ""

    def _send_telegram_reminder(self, message: str):
        """Send a reminder message via Telegram using global bot token."""
        try:
            settings_file = os.path.join(str(DATA_DIR), "global_settings.json")
            if not os.path.exists(settings_file):
                return

            with open(settings_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            token = data.get("telegram_bot_token", "")
            chat_id = data.get("telegram_chat_id", "")

            if not token or not chat_id:
                return

            import requests as req_lib
            send_url = f"https://api.telegram.org/bot{token}/sendMessage"
            req_lib.post(send_url, json={
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "Markdown",
            }, timeout=10)

        except Exception as e:
            logger.warning(f"Failed to send Telegram reminder: {e}")


# Global singleton
calendar_manager = CalendarManager()


class CalendarManagerExtension(Extension):
    name = "calendar_manager"
    version = "0.1.0"
    description = "Manage Google Calendar — events, recurring schedules & Telegram reminders (core extension)"
    author = "TubeCreate"
    extension_type = "system"

    def on_enable(self):
        os.makedirs(os.path.dirname(CALENDAR_DATA_FILE), exist_ok=True)
        # Start reminder daemon when extension is enabled
        calendar_manager.start_reminder_daemon()

    def on_disable(self):
        calendar_manager.stop_reminder_daemon()

    def get_commands(self):
        from tubecli.extensions.calendar_manager.commands import calendar_group
        return calendar_group

    def get_routes(self):
        from tubecli.extensions.calendar_manager.routes import router
        return router

    def get_nodes(self) -> Dict[str, Any]:
        try:
            from tubecli.nodes.google_calendar_node import GoogleCalendarNode
            return {"google_calendar": GoogleCalendarNode}
        except ImportError:
            return {}

    def get_skills(self) -> list:
        return [
            {
                "name": "📅 Calendar Scheduler",
                "description": "Lập lịch sự kiện Google Calendar — hỗ trợ recurring events cho livestream hằng ngày, meeting, etc.",
                "skill_type": "Skill",
                "commands": [
                    "lập lịch", "tạo lịch", "schedule", "create event",
                    "thêm sự kiện", "đặt lịch", "lịch hẹn", "lên lịch livestream",
                ],
                "workflow_data": {
                    "name": "Calendar Scheduler",
                    "nodes": [
                        {
                            "id": "event_input",
                            "type": "text_input",
                            "label": "📝 Event Description",
                            "config": {"text": ""},
                        },
                        {
                            "id": "calendar_action",
                            "type": "google_calendar",
                            "label": "📅 Create Event",
                            "config": {"action": "quick_add"},
                        },
                        {
                            "id": "result_output",
                            "type": "output",
                            "label": "📤 Result",
                            "config": {"print": True},
                        },
                    ],
                    "connections": [
                        {
                            "from_node_id": "event_input",
                            "from_port_id": "content",
                            "to_node_id": "calendar_action",
                            "to_port_id": "event_data",
                        },
                        {
                            "from_node_id": "calendar_action",
                            "from_port_id": "status",
                            "to_node_id": "result_output",
                            "to_port_id": "data",
                        },
                    ],
                },
            },
        ]
