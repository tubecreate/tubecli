"""
WebUI API routes — serve dashboard and workflow static files via FastAPI.
"""
from fastapi import APIRouter
from fastapi.responses import FileResponse
import os

router = APIRouter(tags=["webui"])
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


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


@router.get("/downloader")
async def downloader_page():
    """Serve the Video Downloader page."""
    dl_file = os.path.join(STATIC_DIR, "downloader.html")
    if os.path.exists(dl_file):
        return FileResponse(dl_file)
    return {"error": "Downloader page not found"}


@router.get("/static/{filename:path}")
async def serve_static(filename: str):
    """Serve static files (JS, CSS, etc.)."""
    filepath = os.path.join(STATIC_DIR, filename)
    if os.path.exists(filepath):
        return FileResponse(filepath)
    return {"error": f"File {filename} not found"}
