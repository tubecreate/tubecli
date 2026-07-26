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
    from tubecli.core.bot_i18n import t

    return {"status": "queued", "task": task,
            "message": t("vs.queued_approve_hint", seq=task.get("seq"))}


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


# ── One-string job wrappers (chat/skill entry points) ────────────────
#
# extension_action skills can only send ONE string. The raw endpoints behind
# these jobs need structured bodies (file_path, srt_content, srt_path…), which
# is why every direct mapping used to 422. Each wrapper takes {"input": …} —
# a URL or a local file path — builds the right subset of the reup pipeline,
# and queues it as a codex task so it runs in the background with progress.
# The reply carries the codex marker, so chat renders a live card.

class JobRequest(BaseModel):
    input: str
    options: Dict[str, Any] = {}
    created_by: str = "brain"
    origin: Optional[Dict[str, Any]] = None


# job → which pipeline steps stay on (everything else is turned off), and
# whether the job needs the VIDEO FILE itself. Subtitle-only jobs do not:
# the pipeline pulls the platform's caption track first and downloads solely
# as a fallback when a video has none, so "tách sub <youtube link>" costs one
# request instead of a full download plus a Whisper pass.
_JOB_STEPS = {
    "extract": {"subtitle"},
    "translate": {"subtitle", "translate"},
    "dub": {"subtitle", "translate", "dub"},
    "burn": {"subtitle", "burn"},
}
_JOB_NEEDS_VIDEO = {"dub", "burn"}
# The step that IS the job. If it fails, the task fails — the others are
# prerequisites and may legitimately be skipped.
_JOB_REQUIRED = {"extract": "subtitle", "translate": "translate",
                 "dub": "dub", "burn": "burn"}
_JOB_LABELS = {
    "extract": "Extract subtitles",
    "translate": "Translate subtitles",
    "dub": "Dub with TTS",
    "burn": "Burn subtitles",
}


# "translate to English" — the target language a user names in passing. Without
# this the translate job always used its default (vi), so asking for English
# quietly produced Vietnamese.
_TARGET_LANGS = [
    (r"(tiếng\s*anh|english|英语|英文|英語|영어|английск|i̇ngilizce|ingles|inglés)", "en"),
    (r"(tiếng\s*việt|vietnamese|越南语|越南文|ベトナム語|베트남어|вьетнамск|vietnamca|vietnamita)", "vi"),
    (r"(tiếng\s*trung|chinese|中文|简体|中国語|중국어|китайск|çince|chino)", "zh"),
    (r"(tiếng\s*nhật|japanese|日语|日文|日本語|일본어|японск|japonca|japonés)", "ja"),
    (r"(tiếng\s*hàn|korean|韩语|韓文|韓国語|한국어|корейск|korece|coreano)", "ko"),
    (r"(tiếng\s*nga|russian|俄语|ロシア語|러시아어|русск|rusça|ruso)", "ru"),
    (r"(tiếng\s*tây\s*ban\s*nha|spanish|西班牙语|スペイン語|스페인어|испанск|i̇spanyolca|español)", "es"),
    (r"(tiếng\s*thổ|turkish|土耳其语|トルコ語|튀르키예어|турецк|türkçe|turco)", "tr"),
]


def _target_language(text: str) -> Optional[str]:
    import re as _re

    for pattern, code in _TARGET_LANGS:
        if _re.search(pattern, text or "", _re.IGNORECASE):
            return code
    return None


def _extract_source(text: str) -> str:
    """Pull the URL or file path out of a free-text skill input."""
    import re as _re

    m = _re.search(r"(https?://\S+)", text)
    if m:
        return m.group(0).rstrip(".,;?!)")
    # A quoted or bare Windows/Unix path somewhere in the sentence
    m = _re.search(r"([A-Za-z]:\\[^\s\"']+|/[^\s\"']+)", text)
    if m and os.path.isfile(m.group(0)):
        return m.group(0)
    candidate = text.strip().strip('"\'')
    return candidate


@router.post("/job/{job_id}")
async def queue_single_job(job_id: str, req: JobRequest):
    """Queue one video job (extract/translate/dub/burn) from a single string."""
    from tubecli.core.bot_i18n import t as _bt

    if job_id not in _JOB_STEPS:
        raise HTTPException(404, f"Unknown job: {job_id}. Use one of {sorted(_JOB_STEPS)}.")
    source = _extract_source(req.input or "")
    is_url = source.startswith(("http://", "https://"))
    if not source or (not is_url and not os.path.isfile(source)):
        # No link and no existing file — ask instead of failing with a trace.
        return {"status": "need_input", "report": _bt("vs.ask_url")}

    try:
        from tubecli.extensions.video_studio.pipeline import STEPS, create_codex_task
    except ImportError:
        raise HTTPException(400, "The codex extension is required to run jobs.")

    keep = _JOB_STEPS[job_id]
    needs_video = job_id in _JOB_NEEDS_VIDEO
    options = {sid: (sid in keep or (sid == "download" and needs_video))
               for sid, _, _, _ in STEPS}
    options["job_label"] = _JOB_LABELS[job_id]   # so the result is not headed "Reup pipeline"
    options["required_steps"] = [_JOB_REQUIRED[job_id]]
    target = _target_language(req.input or "")
    if target:
        options["target_language"] = target
    options.update(req.options or {})
    # An SRT source needs no download/extract; run_reup detects that itself.
    try:
        task = await asyncio.to_thread(
            create_codex_task, source, options, req.created_by, req.origin,
            _JOB_LABELS[job_id],
        )
    except Exception as e:
        logger.error(f"[VideoStudio] queueing {job_id} failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))

    queued = task.get("status") == "queued"
    head = (_bt("vs.queued_job", job=_JOB_LABELS[job_id], seq=task["seq"])
            + _bt("vs.starting_now" if queued else "vs.awaiting_approval"))
    return {
        "status": "queued",
        "task": task,
        "report": f"{head}\n\n<!--codex:{task['id']}:{task['seq']}:{task.get('status','')}-->",
    }
