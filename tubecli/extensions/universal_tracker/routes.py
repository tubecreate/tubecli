"""
Universal Tracker — REST API routes for managing tracker jobs.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

from tubecli.extensions.universal_tracker.tracker import universal_tracker_engine

router = APIRouter(prefix="/api/v1/universal_tracker", tags=["Universal Tracker"])

@router.on_event("startup")
async def start_tracker_engine():
    import logging
    logger = logging.getLogger("UniversalTracker")
    try:
        from tubecli.extensions.universal_tracker.tracker import universal_tracker_engine
        universal_tracker_engine.start()
        logger.info("Universal Tracker engine background loop started.")
    except Exception as e:
        logger.error(f"Failed to start Universal Tracker: {e}")

class AddTrackerRequest(BaseModel):
    platform: str = ""
    url: str
    interval_minutes: int = 180
    target_team_id: str = ""
    instruction: str = ""
    pipeline_config: Optional[Dict[str, Any]] = None
    notify_chat_id: int = 0
    notify_token: str = ""


class UpdateTrackerRequest(BaseModel):
    interval_minutes: Optional[int] = None
    instruction: Optional[str] = None
    status: Optional[str] = None
    target_team_id: Optional[str] = None
    pipeline_config: Optional[Dict[str, Any]] = None
    notify_chat_id: Optional[int] = None
    notify_token: Optional[str] = None


@router.get("/trackers")
async def list_trackers():
    jobs = universal_tracker_engine.list_trackers()
    return {"success": True, "trackers": jobs, "count": len(jobs)}


@router.post("/trackers")
async def add_tracker(req: AddTrackerRequest):
    platform = req.platform
    if not platform:
        url = req.url.lower()
        if "douyin" in url or "iesdouyin" in url:
            platform = "douyin"
        elif "tiktok" in url:
            platform = "tiktok"
        elif "youtube" in url or "youtu.be" in url:
            platform = "youtube"
        else:
            platform = "website"

    job = universal_tracker_engine.add_tracker(
        platform=platform,
        url=req.url,
        interval_minutes=req.interval_minutes,
        target_team_id=req.target_team_id,
        instruction=req.instruction,
        pipeline_config=req.pipeline_config or {},
        notify_chat_id=req.notify_chat_id,
        notify_token=req.notify_token,
    )
    return {"success": True, "tracker": job.to_dict()}


@router.delete("/trackers/{tracker_id}")
async def remove_tracker(tracker_id: str):
    if universal_tracker_engine.remove_tracker(tracker_id):
        return {"success": True, "message": f"Tracker {tracker_id} removed"}
    raise HTTPException(status_code=404, detail=f"Tracker '{tracker_id}' not found")


@router.put("/trackers/{tracker_id}")
async def update_tracker(tracker_id: str, req: UpdateTrackerRequest):
    engine = universal_tracker_engine
    if tracker_id not in engine._jobs:
        raise HTTPException(status_code=404, detail=f"Tracker '{tracker_id}' not found")

    job = engine._jobs[tracker_id]
    if req.interval_minutes is not None:
        job.interval_minutes = req.interval_minutes
    if req.instruction is not None:
        job.instruction = req.instruction
    if req.status is not None and req.status in ("active", "paused"):
        job.status = req.status
    if req.target_team_id is not None:
        job.target_team_id = req.target_team_id
    if req.pipeline_config is not None:
        job.pipeline_config = req.pipeline_config
    if req.notify_chat_id is not None:
        job.notify_chat_id = req.notify_chat_id
    if req.notify_token is not None:
        job.notify_token = req.notify_token

    engine._save()
    return {"success": True, "tracker": job.to_dict()}


@router.post("/trackers/{tracker_id}/check")
async def force_check(tracker_id: str):
    engine = universal_tracker_engine
    if tracker_id not in engine._jobs:
        raise HTTPException(status_code=404, detail=f"Tracker '{tracker_id}' not found")

    job = engine._jobs[tracker_id]
    result = await engine.force_check_job(tracker_id)
    return {"success": result["success"], "message": result["message"], "tracker": job.to_dict()}
