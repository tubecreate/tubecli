"""
Video Editor API Routes — REST API for video editing operations.
All heavy operations run as background tasks with progress tracking.
"""
import os
import sys
import uuid
import shutil
import asyncio
import logging
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List

logger = logging.getLogger("video_editor.api")

router = APIRouter(prefix="/api/v1/video", tags=["Video Editor"])

@router.on_event("startup")
async def start_video_job_engine():
    import sys
    ve_dir = os.path.dirname(os.path.abspath(__file__))
    if ve_dir not in sys.path: sys.path.append(ve_dir)
    try:
        import job_engine
        job_engine.global_job_engine.start()
        logger.info("Video Job Engine background processing started.")
    except Exception as e:
        logger.error(f"Failed to start Video Job Engine: {e}")

# ── Lazy imports (same dir) ──────────────────────────────────────────

def _engine():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "ve_engine", os.path.join(os.path.dirname(__file__), "video_engine.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _pm():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "ve_pm", os.path.join(os.path.dirname(__file__), "project_manager.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── Task Tracking ────────────────────────────────────────────────────

TASKS = {}


def _create_task(operation: str) -> str:
    task_id = uuid.uuid4().hex[:8]
    TASKS[task_id] = {
        "status": "running",
        "operation": operation,
        "progress": 0,
        "result": None,
        "error": None,
    }
    return task_id


def _complete_task(task_id: str, result: dict):
    if task_id in TASKS:
        TASKS[task_id]["status"] = "done"
        TASKS[task_id]["progress"] = 100
        TASKS[task_id]["result"] = result


def _fail_task(task_id: str, error: str):
    if task_id in TASKS:
        TASKS[task_id]["status"] = "error"
        TASKS[task_id]["error"] = error


# ── Pydantic Models ──────────────────────────────────────────────────

class ProjectCreate(BaseModel):
    name: str
    description: str = ""


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    timeline: Optional[dict] = None
    export_settings: Optional[dict] = None


class TrimRequest(BaseModel):
    input_file: str
    start: str              # "00:00:05" or "5"
    end: str                # "00:00:15" or "15"
    output_file: Optional[str] = None


class MergeRequest(BaseModel):
    input_files: List[str]
    transition: str = "none"    # none, fade, dissolve, wipeleft, etc.
    output_file: Optional[str] = None


class OverlayRequest(BaseModel):
    input_file: str
    overlay_type: str = "text"  # text, image
    text: Optional[str] = None
    overlay_file: Optional[str] = None
    x: str = "10"
    y: str = "10"
    fontsize: int = 36
    fontcolor: str = "white"
    scale: float = 1.0
    opacity: float = 1.0
    output_file: Optional[str] = None


class EffectRequest(BaseModel):
    input_file: str
    effect: str             # e.g. "grayscale", "blur", "speed_2x"
    params: Optional[dict] = None
    output_file: Optional[str] = None


class ExportRequest(BaseModel):
    input_file: str
    format: str = "mp4"
    quality: str = "high"
    resolution: Optional[str] = None
    fps: Optional[int] = None
    output_file: Optional[str] = None
    timeline: Optional[list] = None


class FFmpegRequest(BaseModel):
    command: str            # Raw ffmpeg args (without 'ffmpeg' prefix)
    input_file: Optional[str] = None


# ── Helpers ──────────────────────────────────────────────────────────

def _get_exports_dir():
    try:
        from tubecli.config import DATA_DIR
        data_dir = DATA_DIR
    except:
        data_dir = os.environ.get("TUBECLI_DATA_DIR", "data")
    d = os.path.join(data_dir, "video_editor", "exports")
    os.makedirs(d, exist_ok=True)
    return d


def _get_uploads_dir():
    try:
        from tubecli.config import DATA_DIR
        data_dir = DATA_DIR
    except:
        data_dir = os.environ.get("TUBECLI_DATA_DIR", "data")
    d = os.path.join(data_dir, "video_editor", "uploads")
    os.makedirs(d, exist_ok=True)
    return d


def _auto_output(input_file: str, suffix: str, ext: Optional[str] = None) -> str:
    """Generate an output filename based on input + operation suffix."""
    base = os.path.splitext(os.path.basename(input_file))[0]
    extension = ext or os.path.splitext(input_file)[1] or ".mp4"
    if not extension.startswith("."):
        extension = "." + extension
    return os.path.join(_get_exports_dir(), f"{base}_{suffix}_{uuid.uuid4().hex[:6]}{extension}")


# ── Status Route ─────────────────────────────────────────────────────

@router.get("/status")
async def video_editor_status():
    """Check FFmpeg availability, version, and GPU encoder."""
    engine = _engine()
    ff = engine.get_ffmpeg_path()
    if not ff:
        return {
            "status": "success",
            "ffmpeg_installed": False,
            "version": None,
            "gpu_encoder": None,
        }

    import subprocess
    try:
        result = subprocess.run([ff, "-version"], capture_output=True, text=True, timeout=10)
        version_line = result.stdout.split("\n")[0] if result.stdout else "unknown"
    except Exception:
        version_line = "unknown"

    codec, encoder_name = engine.detect_gpu_encoder()

    return {
        "status": "success",
        "ffmpeg_installed": True,
        "ffmpeg_path": ff,
        "version": version_line,
        "gpu_encoder": encoder_name,
        "gpu_codec": codec,
    }


# ── Project Routes ───────────────────────────────────────────────────

@router.post("/projects")
async def create_project(req: ProjectCreate):
    """Create a new editing project."""
    pm = _pm()
    project = pm.create_project(req.name, req.description)
    return {"status": "success", "project": project}


@router.get("/projects")
async def list_projects():
    """List all projects."""
    pm = _pm()
    projects = pm.list_projects()
    return {"status": "success", "projects": projects, "count": len(projects)}


@router.get("/projects/{project_id}")
async def get_project(project_id: str):
    """Get project details including timeline."""
    pm = _pm()
    project = pm.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"status": "success", "project": project}


@router.put("/projects/{project_id}")
async def update_project(project_id: str, req: ProjectUpdate):
    """Update project (name, timeline, export settings)."""
    pm = _pm()
    updates = req.model_dump(exclude_none=True)
    project = pm.update_project(project_id, updates)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"status": "success", "project": project}


@router.delete("/projects/{project_id}")
async def delete_project(project_id: str):
    """Delete a project and all its files."""
    pm = _pm()
    if pm.delete_project(project_id):
        return {"status": "success", "message": f"Project {project_id} deleted"}
    raise HTTPException(status_code=404, detail="Project not found")


# ── Upload Route ─────────────────────────────────────────────────────

@router.post("/upload")
async def upload_media(
    file: UploadFile = File(...),
    project_id: Optional[str] = Form(None),
):
    """Upload a media file. Optionally attach to a project."""
    uploads_dir = _get_uploads_dir()
    filename = file.filename or f"upload_{uuid.uuid4().hex[:8]}"
    save_path = os.path.join(uploads_dir, filename)

    # Save uploaded file
    with open(save_path, "wb") as f:
        content = await file.read()
        f.write(content)

    # Probe media info
    engine = _engine()
    try:
        info = await engine.probe(save_path)
    except Exception:
        info = {"file": save_path}

    result = {
        "status": "success",
        "filename": filename,
        "path": save_path,
        "size": os.path.getsize(save_path),
        "info": info,
    }

    # Add to project if specified
    if project_id:
        pm = _pm()
        media_type = "video"
        if filename.lower().endswith((".mp3", ".wav", ".ogg", ".flac", ".aac")):
            media_type = "audio"
        elif filename.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")):
            media_type = "image"

        media_entry = pm.add_media_to_project(
            project_id, filename, save_path,
            media_type=media_type,
            duration=info.get("duration", 0),
            width=info.get("width", 0),
            height=info.get("height", 0),
        )
        if media_entry:
            result["media"] = media_entry

    return result


# ── Video Operations (Async with task tracking) ──────────────────────

@router.post("/trim")
async def trim_video(req: TrimRequest, bg_tasks: BackgroundTasks):
    """Trim a video segment."""
    if not os.path.exists(req.input_file):
        raise HTTPException(status_code=400, detail=f"Input file not found: {req.input_file}")

    output = req.output_file or _auto_output(req.input_file, "trim")
    task_id = _create_task("trim")

    async def do_trim():
        try:
            engine = _engine()
            result = await engine.trim(req.input_file, req.start, req.end, output)
            _complete_task(task_id, result)
        except Exception as e:
            _fail_task(task_id, str(e))

    bg_tasks.add_task(asyncio.run, do_trim())
    return {"status": "success", "task_id": task_id, "output_file": output}


@router.post("/merge")
async def merge_videos(req: MergeRequest, bg_tasks: BackgroundTasks):
    """Merge/concatenate multiple videos."""
    for f in req.input_files:
        if not os.path.exists(f):
            raise HTTPException(status_code=400, detail=f"Input file not found: {f}")

    output = req.output_file or _auto_output(req.input_files[0], "merged")
    task_id = _create_task("merge")

    async def do_merge():
        try:
            engine = _engine()
            result = await engine.merge(req.input_files, output, req.transition)
            _complete_task(task_id, result)
        except Exception as e:
            _fail_task(task_id, str(e))

    bg_tasks.add_task(asyncio.run, do_merge())
    return {"status": "success", "task_id": task_id, "output_file": output}


@router.post("/overlay")
async def overlay_video(req: OverlayRequest, bg_tasks: BackgroundTasks):
    """Add text or image overlay to video."""
    if not os.path.exists(req.input_file):
        raise HTTPException(status_code=400, detail=f"Input file not found: {req.input_file}")

    output = req.output_file or _auto_output(req.input_file, "overlay")
    task_id = _create_task("overlay")

    async def do_overlay():
        try:
            engine = _engine()
            if req.overlay_type == "text":
                if not req.text:
                    _fail_task(task_id, "Text is required for text overlay")
                    return
                result = await engine.overlay_text(
                    req.input_file, req.text, output,
                    x=req.x, y=req.y,
                    fontsize=req.fontsize, fontcolor=req.fontcolor,
                )
            else:
                if not req.overlay_file or not os.path.exists(req.overlay_file):
                    _fail_task(task_id, "Overlay image file not found")
                    return
                result = await engine.overlay_image(
                    req.input_file, req.overlay_file, output,
                    x=req.x, y=req.y,
                    scale=req.scale, opacity=req.opacity,
                )
            _complete_task(task_id, result)
        except Exception as e:
            _fail_task(task_id, str(e))

    bg_tasks.add_task(asyncio.run, do_overlay())
    return {"status": "success", "task_id": task_id, "output_file": output}


@router.post("/effect")
async def apply_effect(req: EffectRequest, bg_tasks: BackgroundTasks):
    """Apply a video effect/filter."""
    if not os.path.exists(req.input_file):
        raise HTTPException(status_code=400, detail=f"Input file not found: {req.input_file}")

    output = req.output_file or _auto_output(req.input_file, req.effect)
    task_id = _create_task("effect")

    async def do_effect():
        try:
            engine = _engine()
            result = await engine.apply_effect(req.input_file, req.effect, output, req.params)
            _complete_task(task_id, result)
        except Exception as e:
            _fail_task(task_id, str(e))

    bg_tasks.add_task(asyncio.run, do_effect())
    return {"status": "success", "task_id": task_id, "output_file": output}


@router.post("/export")
async def export_video(req: ExportRequest, bg_tasks: BackgroundTasks):
    """Export video with specified format, quality, and resolution."""
    if not os.path.exists(req.input_file):
        raise HTTPException(status_code=400, detail=f"Input file not found: {req.input_file}")

    ext = f".{req.format}" if req.format else ".mp4"
    output = req.output_file or _auto_output(req.input_file, "export", ext)
    task_id = _create_task("export")

    async def do_export():
        try:
            engine = _engine()
            result = await engine.export_video(
                req.input_file, output,
                format=req.format,
                quality=req.quality,
                resolution=req.resolution,
                fps=req.fps,
                timeline=req.timeline,
            )
            _complete_task(task_id, result)
        except Exception as e:
            _fail_task(task_id, str(e))

    bg_tasks.add_task(asyncio.run, do_export())
    return {"status": "success", "task_id": task_id, "output_file": output}


@router.post("/ffmpeg")
async def run_ffmpeg_command(req: FFmpegRequest, bg_tasks: BackgroundTasks):
    """Run a custom FFmpeg command."""
    task_id = _create_task("ffmpeg_custom")

    async def do_ffmpeg():
        try:
            engine = _engine()
            result = await engine.run_custom_ffmpeg(req.command, req.input_file)
            _complete_task(task_id, result)
        except Exception as e:
            _fail_task(task_id, str(e))

    bg_tasks.add_task(asyncio.run, do_ffmpeg())
    return {"status": "success", "task_id": task_id}


# ── Task Status ──────────────────────────────────────────────────────

@router.get("/task/{task_id}")
async def get_task_status(task_id: str):
    """Get status of an async video processing task."""
    if task_id not in TASKS:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": "success", "task": TASKS[task_id]}


# ── Probe / Info ─────────────────────────────────────────────────────

@router.get("/info")
async def get_media_info(file: str):
    """Get video/audio file metadata."""
    if not os.path.exists(file):
        raise HTTPException(status_code=400, detail=f"File not found: {file}")
    engine = _engine()
    try:
        info = await engine.probe(file)
        return {"status": "success", "info": info}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/thumbnail")
async def generate_thumbnail(file: str, time: str = "00:00:01"):
    """Generate a thumbnail from a video file."""
    if not os.path.exists(file):
        raise HTTPException(status_code=400, detail=f"File not found: {file}")

    data_dir = os.environ.get("TUBECLI_DATA_DIR", "data")
    thumbs_dir = os.path.join(data_dir, "video_editor", "thumbnails")
    os.makedirs(thumbs_dir, exist_ok=True)

    base = os.path.splitext(os.path.basename(file))[0]
    thumb_file = os.path.join(thumbs_dir, f"{base}_thumb.jpg")

    engine = _engine()
    try:
        await engine.generate_thumbnail(file, thumb_file, time)
        return FileResponse(thumb_file, media_type="image/jpeg")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Presets & Effects List ───────────────────────────────────────────

@router.get("/presets")
async def get_presets():
    """List available export presets and effects."""
    engine = _engine()
    return {
        "status": "success",
        "effects": list(engine.EFFECT_FILTERS.keys()),
        "export_presets": engine.EXPORT_PRESETS,
        "resolutions": list(engine.RESOLUTION_MAP.keys()),
    }


# ── Background Process Jobs ────────────────────────────────────────

class SetupJobRequest(BaseModel):
    source_url: str
    bg_path: str
    trim_no_person: bool = True

@router.post("/jobs")
async def create_processing_job(req: SetupJobRequest):
    import sys
    ve_dir = os.path.dirname(os.path.abspath(__file__))
    if ve_dir not in sys.path: sys.path.append(ve_dir)
    import job_engine
    
    # Determine background type
    is_color = req.bg_path.startswith("#")
    if not is_color and not os.path.exists(req.bg_path):
        raise HTTPException(status_code=400, detail=f"Background image not found: {req.bg_path}")
    
    bg_type = "color" if is_color else "image"
    bg_value = req.bg_path
    job = job_engine.global_job_engine.create_job(
        source_url=req.source_url,
        background={"type": bg_type, "path": bg_value},
        settings={"trim_no_person": req.trim_no_person}
    )
    
    # Ensure background worker is running
    job_engine.global_job_engine.start()
    
    return {"status": "success", "job": job.to_dict()}

@router.get("/jobs")
async def list_processing_jobs():
    try:
        import sys
        ve_dir = os.path.dirname(os.path.abspath(__file__))
        if ve_dir not in sys.path: sys.path.append(ve_dir)
        import job_engine
        jobs = job_engine.global_job_engine.list_jobs()
        return {"status": "success", "jobs": jobs}
    except Exception as e:
        import traceback
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}

@router.get("/jobs/{job_id}")
async def get_processing_job(job_id: str):
    import sys
    ve_dir = os.path.dirname(os.path.abspath(__file__))
    if ve_dir not in sys.path: sys.path.append(ve_dir)
    import job_engine
    job = job_engine.global_job_engine.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"status": "success", "job": job.to_dict()}

@router.delete("/jobs/{job_id}")
async def delete_processing_job(job_id: str):
    import sys
    ve_dir = os.path.dirname(os.path.abspath(__file__))
    if ve_dir not in sys.path: sys.path.append(ve_dir)
    import job_engine
    if job_engine.global_job_engine.delete_job(job_id):
        return {"status": "success"}
    raise HTTPException(status_code=404, detail="Job not found")

@router.get("/processing")
async def processing_page():
    """Serve the Video Processing Queue page."""
    # Assuming UI is in static folder of video_editor
    static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
    processing_file = os.path.join(static_dir, "processing.html")
    if os.path.exists(processing_file):
        from fastapi.responses import FileResponse
        return FileResponse(processing_file)
    return {"error": "Processing page not found. File path tried: " + processing_file}

# ── File Serving ─────────────────────────────────────────────────────

@router.get("/files/{filename}")
async def serve_file(filename: str):
    """Serve an exported/processed file."""
    exports_dir = _get_exports_dir()
    fpath = os.path.join(exports_dir, filename)
    if not os.path.exists(fpath):
        # Also check uploads
        uploads_dir = _get_uploads_dir()
        fpath = os.path.join(uploads_dir, filename)
    if not os.path.exists(fpath):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(fpath, filename=filename)
