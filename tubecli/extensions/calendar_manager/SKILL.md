---
name: calendar_manager
description: Manage Google Calendar — create, list, update, delete events with recurring & reminders
---

# Calendar Manager Extension

This core extension manages Google Calendar events. It uses OAuth credentials
from Auth Manager to interact with Google Calendar API. AI agents and Telegram
chat can use it to schedule daily tasks, livestreams, meetings, etc.

## Usage from Other Extensions

```python
from tubecli.extensions.calendar_manager.extension import calendar_manager

# List upcoming events
events = calendar_manager.list_events(cred_id="cred_xxx", time_min="2026-04-01T00:00:00Z")

# Create a new event
result = calendar_manager.create_event(
    cred_id="cred_xxx",
    summary="Livestream Daily",
    start="2026-04-03T20:00:00+07:00",
    end="2026-04-03T22:00:00+07:00",
    description="Daily livestream session",
    recurrence=["RRULE:FREQ=DAILY;COUNT=30"],
)

# Quick add from natural language
result = calendar_manager.quick_add(cred_id="cred_xxx", text="Meeting tomorrow 10am-11am")

# Delete an event
calendar_manager.delete_event(cred_id="cred_xxx", event_id="abc123")
```

## Recurring Events (RRULE)

Use Google Calendar RRULE format:
- Daily: `RRULE:FREQ=DAILY`
- Weekly: `RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR`
- Monthly: `RRULE:FREQ=MONTHLY;BYMONTHDAY=1`
- Daily for 30 days: `RRULE:FREQ=DAILY;COUNT=30`

## API Endpoints

- `GET /api/v1/calendar/calendars` — List calendars
- `GET /api/v1/calendar/events` — List events (query: calendar_id, time_min, time_max, max_results)
- `POST /api/v1/calendar/events` — Create event (supports recurrence)
- `PUT /api/v1/calendar/events/{event_id}` — Update event
- `DELETE /api/v1/calendar/events/{event_id}` — Delete event
- `POST /api/v1/calendar/quick-add` — Quick add from text

## Telegram Integration

When user chats in Telegram, AI can schedule events by outputting:
```json
{"action": "schedule_event", "summary": "Livestream", "start": "2026-04-03T20:00:00+07:00", "end": "2026-04-03T22:00:00+07:00", "recurrence": "RRULE:FREQ=DAILY"}
```

The system will automatically use the default_calendar_email from global settings.

## CLI Commands

- `tubecli calendar calendars` — List calendars
- `tubecli calendar list` — List today's events
- `tubecli calendar add "Title" --start "..." --end "..."` — Create event
- `tubecli calendar delete <event_id>` — Delete event
