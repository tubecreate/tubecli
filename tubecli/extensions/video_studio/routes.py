"""
Video Studio — FastAPI routes.
"""
import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("VideoStudio")

router = APIRouter(prefix="/api/v1/video-studio", tags=["video-studio"])


# ── Requests ─────────────────────────────────────────────────────────

class DetectRequest(BaseModel):
    video_path: str
    sample: int = 6


class RemoveRequest(BaseModel):
    video_path: str
    mode: str = "delogo"
    sample: int = 6
    strength: int = 24
    feather: bool = True
    box: Optional[List[float]] = None      # skip detection when supplied
    output_path: str = ""


class ChannelRequest(BaseModel):
    url: str = ""
    videos: Optional[List[Dict[str, Any]]] = None
    channel_name: str = ""
    limit: int = 40
    language: str = "the same language as the channel's titles"


class ReupRequest(BaseModel):
    url: str
    options: Dict[str, Any] = {}
    created_by: str = "user"
    origin: Optional[Dict[str, Any]] = None


class DownloadRequest(BaseModel):
    url: str
    created_by: str = "user"
    origin: Optional[Dict[str, Any]] = None


# ── Capabilities ─────────────────────────────────────────────────────

@router.get("/capabilities")
async def capabilities():
    """What can run right now, and what is missing."""
    from tubecli.extensions.video_studio.capabilities import capability_report, check_all

    data = check_all()
    data["report"] = capability_report()
    return data


@router.get("/capabilities/{job_id}")
async def capability(job_id: str):
    from tubecli.extensions.video_studio.capabilities import check_job, guidance_for

    result = check_job(job_id)
    if result.get("error"):
        raise HTTPException(404, result["error"])
    result["guidance"] = guidance_for([job_id])
    return result


# ── Hardcoded-subtitle removal ───────────────────────────────────────

@router.post("/hardsub/detect")
async def detect_hardsub(req: DetectRequest):
    """Locate the burned-in subtitle band without touching the video."""
    from tubecli.extensions.video_studio.region_detect import detect_subtitle_region

    if not os.path.isfile(req.video_path):
        raise HTTPException(400, f"File not found: {req.video_path}")
    try:
        return await asyncio.to_thread(
            detect_subtitle_region, req.video_path, req.sample
        )
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/hardsub/remove")
async def remove_hardsub(req: RemoveRequest):
    """Detect (unless a box is given) and cover the original subtitles."""
    from tubecli.extensions.video_studio.region_detect import (
        COVER_MODES, cover_region, detect_subtitle_region,
    )

    if not os.path.isfile(req.video_path):
        raise HTTPException(400, f"File not found: {req.video_path}")
    if req.mode not in COVER_MODES:
        raise HTTPException(400, f"mode must be one of {list(COVER_MODES)}")

    info: Dict[str, Any] = {}
    box = req.box
    if not box:
        try:
            info = await asyncio.to_thread(
                detect_subtitle_region, req.video_path, req.sample
            )
        except Exception as e:
            raise HTTPException(500, str(e))
        if not info.get("found") or not info.get("box"):
            return {"found": False, "output_path": "", "info": info,
                    "message": "No burned-in subtitles were found — nothing to cover."}
        box = info["box"]

    out = req.output_path
    if not out:
        from tubecli.config import EXTENSIONS_DATA_DIR

        outdir = os.path.join(str(EXTENSIONS_DATA_DIR), "video_studio", "outputs")
        os.makedirs(outdir, exist_ok=True)
        stem = os.path.splitext(os.path.basename(req.video_path))[0]
        out = os.path.join(outdir, f"{stem}_clean.mp4")

    try:
        result = await asyncio.to_thread(
            cover_region, req.video_path, box, out, req.mode, req.strength, req.feather
        )
    except Exception as e:
        raise HTTPException(500, str(e))
    return {"found": True, "output_path": result, "box": box, "mode": req.mode,
            "info": info}


# ── Channel analysis ─────────────────────────────────────────────────

@router.post("/channel/analyze")
async def analyze_channel_route(req: ChannelRequest):
    """Analyse a channel and propose new video ideas."""
    from tubecli.extensions.video_studio.channel_analysis import (
        analyze_channel, fetch_channel_videos, ideas_to_text,
    )

    videos = req.videos or []
    channel = req.channel_name
    if not videos:
        if not req.url:
            raise HTTPException(400, "Provide either 'url' or 'videos'.")
        fetched = await asyncio.to_thread(fetch_channel_videos, req.url, req.limit)
        if not fetched.get("ok"):
            from tubecli.extensions.video_studio.capabilities import guidance_for

            raise HTTPException(400, (guidance_for(["channel_analysis"])
                                      or fetched.get("message", "Could not fetch videos.")))
        videos = fetched["videos"]
        channel = channel or fetched.get("channel", "")

    result = await asyncio.to_thread(analyze_channel, videos, channel, req.language)
    if not result.get("ok"):
        raise HTTPException(500, result.get("message", "Analysis failed."))
    result["text"] = ideas_to_text(result.get("data") or {}, channel)
    return result


# ── Reup pipeline ────────────────────────────────────────────────────

@router.post("/download")
async def download_route(req: DownloadRequest):
    """Queue a background download with a progress bar.

    Deliberately NOT a synchronous call: yt-dlp takes minutes, and any caller
    (workflow node, chat turn, Telegram handler) times out long before it
    finishes. As a codex task it reports live percentage and survives a restart.
    """
    if not (req.url or "").strip():
        raise HTTPException(400, "url is required")
    from tubecli.extensions.video_studio.capabilities import guidance_for

    gap = guidance_for(["download"])
    if gap:
        raise HTTPException(400, gap)
    try:
        from tubecli.extensions.video_studio.jobs import create_download_task

        task = await asyncio.to_thread(
            create_download_task, req.url, req.created_by, req.origin
        )
    except Exception as e:
        logger.error(f"[VideoStudio] queueing the download failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))
    return {"status": "queued", "task": task,
            "message": (f"📥 Download queued as Codex #{task.get('seq')} — approve it "
                        f"to start; progress shows on the board.")}


@router.post("/pipeline/plan")
async def pipeline_plan(req: ReupRequest):
    from tubecli.extensions.video_studio.pipeline import describe_plan, plan

    return {"steps": plan(req.options), "text": describe_plan(req.options)}


@router.post("/pipeline/reup")
async def pipeline_reup(req: ReupRequest):
    """Queue the pipeline as an approval-gated codex task."""
    if not (req.url or "").strip():
        raise HTTPException(400, "url is required")
    try:
        from tubecli.extensions.video_studio.pipeline import create_codex_task
    except ImportError:
        raise HTTPException(400, "The codex extension is required to run pipelines.")
    try:
        task = await asyncio.to_thread(
            create_codex_task, req.url, req.options, req.created_by, req.origin
        )
    except Exception as e:
        logger.error(f"[VideoStudio] queueing the reup failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))
    return {"status": "queued", "task": task,
            "message": f"Reup queued as Codex #{task.get('seq')} — approve it to start."}
