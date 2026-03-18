"""
WebUI API routes — serve dashboard static files via FastAPI.
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
