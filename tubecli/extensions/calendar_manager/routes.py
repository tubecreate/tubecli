"""
Calendar Manager Extension — FastAPI routes.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List

router = APIRouter(prefix="/api/v1/calendar", tags=["calendar-manager"])


class CreateEventRequest(BaseModel):
    calendar_id: str = "primary"
    summary: str
    start: str
    end: str = ""
    description: str = ""
    location: str = ""
    attendees: List[str] = []
    recurrence: List[str] = []
    reminders_minutes: List[int] = []
    time_zone: str = "Asia/Ho_Chi_Minh"
    cred_id: str = ""
    email: str = ""


class UpdateEventRequest(BaseModel):
    calendar_id: str = "primary"
    summary: Optional[str] = None
    start: Optional[str] = None
    end: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    recurrence: Optional[List[str]] = None
    time_zone: str = "Asia/Ho_Chi_Minh"
    cred_id: str = ""
    email: str = ""


class QuickAddRequest(BaseModel):
    calendar_id: str = "primary"
    text: str
    cred_id: str = ""
    email: str = ""


# ── Credentials (matching Sheets Manager pattern) ────────────

@router.get("/credentials")
async def list_calendar_credentials():
    """List Google OAuth credentials that have calendar scope."""
    try:
        from tubecli.extensions.auth_manager.extension import auth_manager as am
        tokens = am.list_tokens("google")
        # Filter tokens that have calendar scope
        cal_tokens = []
        for t in tokens:
            scopes = " ".join(t.get("scopes", []))
            if "calendar" in scopes or "googleapis.com/auth/calendar" in scopes:
                cal_tokens.append({
                    "id": t["token_id"],
                    "name": t.get("credential_name", t["token_id"]),
                    "email": t.get("authorized_email", ""),
                })
        # If no calendar-scoped tokens, also show all Google tokens as fallback
        if not cal_tokens:
            for t in tokens:
                cal_tokens.append({
                    "id": t["token_id"],
                    "name": t.get("credential_name", t["token_id"]),
                    "email": t.get("authorized_email", ""),
                })
        return {"credentials": cal_tokens}
    except Exception as e:
        return {"credentials": [], "error": str(e)}


# ── Calendars ────────────────────────────────────────────────────

@router.get("/calendars")
async def api_list_calendars(cred_id: str = "", email: str = ""):
    """List all calendars for the authenticated user."""
    from .extension import calendar_manager
    result = calendar_manager.list_calendars(cred_id=cred_id, email=email)
    if result["status"] == "error":
        raise HTTPException(400, result["message"])
    return result


# ── Events ───────────────────────────────────────────────────────

@router.get("/events")
async def api_list_events(
    calendar_id: str = "primary",
    time_min: str = "",
    time_max: str = "",
    max_results: int = 50,
    query: str = "",
    cred_id: str = "",
    email: str = "",
):
    """List events from a calendar."""
    from .extension import calendar_manager
    result = calendar_manager.list_events(
        cred_id=cred_id,
        email=email,
        calendar_id=calendar_id,
        time_min=time_min,
        time_max=time_max,
        max_results=max_results,
        query=query,
    )
    if result["status"] == "error":
        raise HTTPException(400, result["message"])
    return result


@router.post("/events")
async def api_create_event(req: CreateEventRequest):
    """Create a new calendar event (supports recurrence)."""
    from .extension import calendar_manager
    result = calendar_manager.create_event(
        cred_id=req.cred_id,
        email=req.email,
        calendar_id=req.calendar_id,
        summary=req.summary,
        start=req.start,
        end=req.end,
        description=req.description,
        location=req.location,
        attendees=req.attendees,
        recurrence=req.recurrence,
        reminders_minutes=req.reminders_minutes,
        time_zone=req.time_zone,
    )
    if result["status"] == "error":
        raise HTTPException(400, result["message"])
    return result


@router.put("/events/{event_id}")
async def api_update_event(event_id: str, req: UpdateEventRequest):
    """Update an existing calendar event."""
    from .extension import calendar_manager
    result = calendar_manager.update_event(
        cred_id=req.cred_id,
        email=req.email,
        calendar_id=req.calendar_id,
        event_id=event_id,
        summary=req.summary,
        start=req.start,
        end=req.end,
        description=req.description,
        location=req.location,
        recurrence=req.recurrence,
        time_zone=req.time_zone,
    )
    if result["status"] == "error":
        raise HTTPException(400, result["message"])
    return result


@router.delete("/events/{event_id}")
async def api_delete_event(event_id: str, calendar_id: str = "primary", cred_id: str = "", email: str = ""):
    """Delete a calendar event."""
    from .extension import calendar_manager
    result = calendar_manager.delete_event(
        cred_id=cred_id,
        email=email,
        calendar_id=calendar_id,
        event_id=event_id,
    )
    if result["status"] == "error":
        raise HTTPException(400, result["message"])
    return result


@router.post("/quick-add")
async def api_quick_add(req: QuickAddRequest):
    """Quick add an event from natural language text."""
    from .extension import calendar_manager
    result = calendar_manager.quick_add(
        cred_id=req.cred_id,
        email=req.email,
        calendar_id=req.calendar_id,
        text=req.text,
    )
    if result["status"] == "error":
        raise HTTPException(400, result["message"])
    return result


# ── Reminder Settings ────────────────────────────────────────────

@router.get("/reminders/settings")
async def api_get_reminder_settings():
    """Get calendar reminder settings."""
    from .extension import calendar_manager
    calendar_manager._load()
    settings = calendar_manager._data.get("reminder_settings", {})
    return {
        "minutes_before": settings.get("minutes_before", 15),
        "enabled": settings.get("enabled", True),
    }


class ReminderSettingsRequest(BaseModel):
    minutes_before: int = 15
    enabled: bool = True


@router.put("/reminders/settings")
async def api_update_reminder_settings(req: ReminderSettingsRequest):
    """Update calendar reminder settings."""
    from .extension import calendar_manager
    calendar_manager._load()
    calendar_manager._data.setdefault("reminder_settings", {})
    calendar_manager._data["reminder_settings"]["minutes_before"] = req.minutes_before
    calendar_manager._data["reminder_settings"]["enabled"] = req.enabled
    calendar_manager._save()
    return {"status": "success", "settings": calendar_manager._data["reminder_settings"]}
