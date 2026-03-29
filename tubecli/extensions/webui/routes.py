"""
WebUI API routes — serve dashboard and workflow static files via FastAPI.
"""
from fastapi import APIRouter
from fastapi.responses import FileResponse
import os

router = APIRouter(tags=["webui"])
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

# ── Include Story API ───────────────────────────────────────────────
from .story_api import story_router
router.include_router(story_router)


@router.get("/dashboard")
async def dashboard():
    index = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index):
        return FileResponse(index)
    return {"error": "Dashboard not found"}


@router.get("/workflow")
async def workflow_page():
    """Serve the workflow builder page."""
    wf_page = os.path.join(STATIC_DIR, "workflow.html")
    if os.path.exists(wf_page):
        return FileResponse(wf_page)
    return {"error": "Workflow builder not found"}


@router.get("/teams")
async def teams_page():
    """Serve the Teams AI dashboard page."""
    teams_file = os.path.join(STATIC_DIR, "teams.html")
    if os.path.exists(teams_file):
        return FileResponse(teams_file)
    return {"error": "Teams dashboard not found"}


@router.get("/studio")
async def studio_page():
    """Serve the 3D Studio editor page."""
    studio_file = os.path.join(STATIC_DIR, "studio.html")
    if os.path.exists(studio_file):
        return FileResponse(studio_file)
    return {"error": "Studio page not found"}


@router.get("/market")
async def market_page():
    """Serve the Extension Market page."""
    market_file = os.path.join(STATIC_DIR, "market.html")
    if os.path.exists(market_file):
        return FileResponse(market_file)
    return {"error": "Market page not found"}


@router.get("/downloader")
async def downloader_page():
    """Serve the Video Downloader page."""
    dl_file = os.path.join(STATIC_DIR, "downloader.html")
    if os.path.exists(dl_file):
        return FileResponse(dl_file)
    return {"error": "Downloader page not found"}


@router.get("/story")
async def story_page():
    """Serve the 3D Story Engine page."""
    story_file = os.path.join(STATIC_DIR, "story.html")
    if os.path.exists(story_file):
        return FileResponse(story_file)
    return {"error": "Story page not found"}


@router.get("/auth-manager")
async def auth_manager_page():
    """Serve the Auth Manager page."""
    am_file = os.path.join(STATIC_DIR, "auth_manager.html")
    if os.path.exists(am_file):
        return FileResponse(am_file)
    return {"error": "Auth Manager page not found"}


@router.get("/video-editor")
async def video_editor_page():
    """Serve the Video Editor page."""
    from tubecli.config import DATA_DIR
    editor_file = os.path.join(DATA_DIR, "extensions_external", "video_editor", "static", "editor.html")
    if os.path.exists(editor_file):
        return FileResponse(editor_file)
    return {"error": "Video Editor page not found"}


@router.get("/video-editor-static/{filename:path}")
async def serve_video_editor_static(filename: str):
    """Serve Video Editor static files (JS, CSS)."""
    from tubecli.config import DATA_DIR
    filepath = os.path.join(DATA_DIR, "extensions_external", "video_editor", "static", filename)
    if os.path.exists(filepath):
        return FileResponse(filepath)
    return {"error": f"File {filename} not found"}


@router.get("/static/{filename:path}")
async def serve_static(filename: str):
    """Serve static files (JS, CSS, etc.)."""
    filepath = os.path.join(STATIC_DIR, filename)
    if os.path.exists(filepath):
        return FileResponse(filepath)
    return {"error": f"File {filename} not found"}

