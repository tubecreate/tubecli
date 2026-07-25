"""
Codex — FastAPI routes.

Exposes two routers (Extension.get_routes returns both):
  * ui_router  — no prefix, serves /codex and its static assets
  * router     — /api/v1/codex/... task board API
"""
import asyncio
import logging
import mimetypes
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from tubecli.extensions.codex.manager import ALL_STATES, codex_manager

logger = logging.getLogger("Codex")

_EXT_DIR = os.path.dirname(os.path.abspath(__file__))
_STATIC_DIR = os.path.join(_EXT_DIR, "static")

_MEDIA_TYPES = {
    ".css": "text/css",
    ".js": "application/javascript",
    ".html": "text/html",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
}
_NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate"}


# ── UI router ────────────────────────────────────────────────────────

ui_router = APIRouter(tags=["codex-ui"])


@ui_router.get("/codex")
async def serve_codex_ui():
    """Serve the Codex task board."""
    return FileResponse(
        os.path.join(_STATIC_DIR, "codex.html"), media_type="text/html", headers=_NO_CACHE
    )


@ui_router.get("/codex/{filename:path}")
async def serve_codex_static(filename: str):
    """Serve Codex static assets."""
    filepath = os.path.normpath(os.path.join(_STATIC_DIR, filename))
    if not filepath.startswith(_STATIC_DIR) or not os.path.isfile(filepath):
        raise HTTPException(404, "File not found")
    ext = os.path.splitext(filename)[1].lower()
    media = _MEDIA_TYPES.get(ext) or mimetypes.guess_type(filepath)[0] or "application/octet-stream"
    return FileResponse(filepath, media_type=media, headers=_NO_CACHE)


# ── API router ───────────────────────────────────────────────────────

router = APIRouter(prefix="/api/v1/codex", tags=["codex"])

_worker_started = False


@router.on_event("startup")
async def _boot_codex_worker():
    """Start the queue worker once, on the server's event loop."""
    global _worker_started
    if _worker_started:
        return
    try:
        from tubecli.extensions.codex.worker import codex_worker

        codex_worker.start()
        _worker_started = True
    except Exception as e:
        logger.error(f"[Codex] Failed to start worker: {e}")


@router.on_event("shutdown")
async def _stop_codex_worker():
    global _worker_started
    try:
        from tubecli.extensions.codex.worker import codex_worker

        codex_worker.stop()
    except Exception:
        pass
    _worker_started = False


# ── Request models ───────────────────────────────────────────────────

class CreateTaskRequest(BaseModel):
    goal: str
    title: str = ""
    assignee_type: str = "agent"
    assignee_id: str = ""
    assignee_name: str = ""
    skill_name: str = ""
    approval_required: Optional[bool] = None
    priority: int = 0
    created_by: str = "user"
    origin: Optional[Dict[str, Any]] = None


class UpdateTaskRequest(BaseModel):
    title: Optional[str] = None
    goal: Optional[str] = None
    priority: Optional[int] = None
    assignee_type: Optional[str] = None
    assignee_id: Optional[str] = None
    assignee_name: Optional[str] = None


class DecisionRequest(BaseModel):
    actor: str = "user"
    note: str = ""


class ReviewRequest(BaseModel):
    accepted: bool
    actor: str = "user"
    feedback: str = ""


class CommandRequest(BaseModel):
    text: str = ""
    actor: str = "user"


# ── Helpers ──────────────────────────────────────────────────────────

def _require(task_id: str) -> Dict[str, Any]:
    task = codex_manager.resolve_ref(task_id)
    if not task:
        raise HTTPException(404, f"Task not found: {task_id}")
    return task


def _guard(fn, *args, **kwargs):
    """Translate the manager's ValueError contract into HTTP 400."""
    try:
        return fn(*args, **kwargs)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Codex] API error: {e}", exc_info=True)
        raise HTTPException(500, str(e))


# ── Endpoints ────────────────────────────────────────────────────────

@router.get("/stats")
async def get_stats():
    return codex_manager.get_stats()


@router.get("/tasks")
async def list_tasks(status: str = "", limit: int = 50, created_by: str = ""):
    if status and status != "active" and status not in ALL_STATES:
        raise HTTPException(400, f"Unknown status: {status}")
    tasks = codex_manager.list_tasks(status=status, limit=limit, created_by=created_by)
    return {"tasks": tasks, "count": len(tasks)}


@router.post("/tasks")
async def create_task(req: CreateTaskRequest):
    task = _guard(
        codex_manager.create_task,
        goal=req.goal,
        title=req.title,
        created_by=req.created_by,
        origin=req.origin,
        assignee_type=req.assignee_type,
        assignee_id=req.assignee_id,
        assignee_name=req.assignee_name,
        skill_name=req.skill_name,
        approval_required=req.approval_required,
        priority=req.priority,
    )
    return {"status": "created", "task": task}


@router.get("/tasks/{task_id}")
async def get_task(task_id: str, events: int = 50):
    task = _require(task_id)
    return {
        "task": task,
        "events": codex_manager.get_events(task["id"], limit=events),
    }


@router.put("/tasks/{task_id}")
async def update_task(task_id: str, req: UpdateTaskRequest):
    task = _require(task_id)
    updated = _guard(
        codex_manager.update_task, task["id"], **req.dict(exclude_none=True)
    )
    return {"status": "updated", "task": updated}


@router.get("/tasks/{task_id}/events")
async def get_events(task_id: str, after: str = "", limit: int = 200):
    task = _require(task_id)
    return {"events": codex_manager.get_events(task["id"], after=after, limit=limit)}


@router.post("/tasks/{task_id}/approve")
async def approve_task(task_id: str, req: DecisionRequest = DecisionRequest()):
    task = _require(task_id)
    return {"status": "approved", "task": _guard(
        codex_manager.approve, task["id"], actor=req.actor, note=req.note
    )}


@router.post("/tasks/{task_id}/reject")
async def reject_task(task_id: str, req: DecisionRequest = DecisionRequest()):
    task = _require(task_id)
    return {"status": "rejected", "task": _guard(
        codex_manager.reject, task["id"], actor=req.actor, note=req.note
    )}


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str, req: DecisionRequest = DecisionRequest()):
    task = _require(task_id)
    return {"status": "cancelled", "task": _guard(
        codex_manager.cancel, task["id"], actor=req.actor
    )}


@router.post("/tasks/{task_id}/retry")
async def retry_task(task_id: str, req: DecisionRequest = DecisionRequest()):
    task = _require(task_id)
    return {"status": "queued", "task": _guard(
        codex_manager.retry, task["id"], actor=req.actor
    )}


@router.post("/tasks/{task_id}/review")
async def review_task(task_id: str, req: ReviewRequest):
    task = _require(task_id)
    return {"status": "reviewed", "task": _guard(
        codex_manager.complete_review,
        task["id"], req.accepted, actor=req.actor, feedback=req.feedback,
    )}


@router.post("/tasks/{task_id}/plan")
async def plan_task(task_id: str):
    """Ask the brain to decompose the goal into steps (blocking LLM call)."""
    task = _require(task_id)
    try:
        updated = await asyncio.to_thread(codex_manager.plan_task, task["id"])
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error(f"[Codex] plan_task failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))
    return {"status": "planned", "task": updated}


@router.get("/assignees")
async def list_assignees():
    """Agents and teams available as delegation targets (for the UI picker)."""
    agents: List[Dict[str, str]] = []
    teams: List[Dict[str, str]] = []
    try:
        from tubecli.core.agent import agent_manager

        agents = [
            {"id": a.id, "name": a.name, "role": a.role or "general"}
            for a in agent_manager.get_all()
        ]
    except Exception as e:
        logger.warning(f"[Codex] Could not list agents: {e}")
    try:
        from tubecli.extensions.multi_agents.extension import orchestrator

        teams = [
            {"id": t.id, "name": t.name, "strategy": getattr(t, "strategy", "")}
            for t in orchestrator.get_all_teams()
        ]
    except Exception as e:
        logger.debug(f"[Codex] Could not list teams: {e}")
    return {"agents": agents, "teams": teams}


@router.post("/command", response_class=PlainTextResponse)
async def run_command(req: CommandRequest):
    """Deterministic text command ('codex', 'approve 3', ...) — no LLM involved.

    This is the endpoint the registered Codex skill points at, giving Telegram a
    zero-token path into the board.

    Returns PLAIN TEXT on purpose: AgentBrain.autonomous_run's extension_action
    branch (core/brain.py:598-631) passes a JSON body through
    format_skill_result, which truncates every value at 300 chars and may spend
    an extra LLM call. A non-JSON body takes the `return resp.text[:2000]`
    path instead, so the board reaches the user verbatim.
    """
    from tubecli.extensions.codex.telegram import handle_command

    return handle_command(req.text, actor=req.actor)


@router.get("/worker")
async def worker_status():
    try:
        from tubecli.extensions.codex.worker import codex_worker

        return codex_worker.status()
    except Exception as e:
        raise HTTPException(500, str(e))
