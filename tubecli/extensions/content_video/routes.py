"""
Content Video — FastAPI routes.

Three entry points, all of which end in the same codex task:
  GET  /capabilities      what can run right now (extensions + Content Studio's own answer)
  POST /plan              which steps would run for these options
  POST /run               queue a content video for an agent

These are owner routes. /api/v1/content-video is not in the guest middleware's
sensitive list, so the gate is applied here: a shared-workspace guest never
gets to spend an agent's corpus and keys.
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger("ContentVideo")

router = APIRouter(prefix="/api/v1/content-video", tags=["content-video"])


def _deny_guests(request: Request) -> None:
    if getattr(request.state, "guest_scope", None):
        raise HTTPException(403, "Not available in a shared workspace.")


class PlanRequest(BaseModel):
    options: Dict[str, Any] = {}


class RunRequest(BaseModel):
    agent_id: str
    sources: List[str] = []
    options: Dict[str, Any] = {}
    created_by: str = "user"
    origin: Optional[Dict[str, Any]] = None


@router.get("/capabilities")
async def capabilities(request: Request):
    _deny_guests(request)
    from tubecli.extensions.content_video.capabilities import capability_report

    return {"text": await asyncio.to_thread(capability_report, True)}


@router.post("/plan")
async def plan_route(req: PlanRequest, request: Request):
    _deny_guests(request)
    from tubecli.extensions.content_video.pipeline import describe_plan, plan

    return {"steps": plan(req.options), "text": describe_plan(req.options)}


@router.post("/run")
async def run_route(req: RunRequest, request: Request):
    """Queue the pipeline as a codex task for one agent."""
    _deny_guests(request)
    if not (req.agent_id or "").strip():
        raise HTTPException(400, "agent_id is required")
    try:
        from tubecli.extensions.content_video.pipeline import create_digest_task, queued_reply
    except ImportError:
        raise HTTPException(400, "The codex extension is required to run pipelines.")
    origin = dict(req.origin or {})
    origin.setdefault("agent_id", req.agent_id)
    try:
        task = await asyncio.to_thread(
            create_digest_task, req.agent_id, req.options, req.created_by, origin, req.sources)
    except Exception as e:
        logger.error(f"[ContentVideo] queueing failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))
    return {"status": "queued", "task": task, "report": queued_reply(task)}
