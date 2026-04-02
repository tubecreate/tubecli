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


# ── Global Settings API ─────────────────────────────────────────────
import json
from fastapi import Request
from fastapi.responses import JSONResponse

def _settings_path():
    """Return path to global_settings.json in the project data dir."""
    try:
        from tubecli.config import DATA_DIR
        d = DATA_DIR
    except Exception:
        d = os.path.join(os.path.expanduser("~"), ".tubecli", "data")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "global_settings.json")

_DEFAULT_SETTINGS = {
    "default_model": "qwen:latest",
    "api_port": "5295",
    "api_base_url": "http://localhost:5295",
    "language": "vi",
    "telegram_bot_token": "",
    "telegram_chat_id": "",
}

@router.get("/api/v1/settings")
async def get_global_settings():
    p = _settings_path()
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                saved = json.load(f)
            merged = {**_DEFAULT_SETTINGS, **saved}
            return JSONResponse(merged)
        except Exception:
            pass
    return JSONResponse(_DEFAULT_SETTINGS.copy())

@router.put("/api/v1/settings")
async def save_global_settings(request: Request):
    body = await request.json()
    p = _settings_path()
    existing = _DEFAULT_SETTINGS.copy()
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                existing.update(json.load(f))
        except Exception:
            pass
    existing.update(body)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)
    return JSONResponse({"status": "success", "settings": existing})


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


def _find_file_manager_dir():
    """Find the File Manager extension static directory."""
    fm_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "file_manager", "static")
    if os.path.isdir(fm_dir):
        return fm_dir
    return None


@router.get("/file-manager")
async def file_manager_page():
    """Serve the File Manager page."""
    fm_dir = _find_file_manager_dir()
    if fm_dir:
        html_file = os.path.join(fm_dir, "file_manager.html")
        if os.path.exists(html_file):
            return FileResponse(html_file)
    return {"error": "File Manager page not found"}


@router.get("/file-manager-static/{filename:path}")
async def serve_file_manager_static(filename: str):
    """Serve File Manager static files (JS, CSS)."""
    fm_dir = _find_file_manager_dir()
    if fm_dir:
        filepath = os.path.join(fm_dir, filename)
        if os.path.exists(filepath):
            return FileResponse(filepath)
    return {"error": f"File {filename} not found"}



def _find_video_editor_dir():
    """Find the Video Editor extension directory (handles both 'video_editor' and 'video_editor__xxx' folders)."""
    from tubecli.config import DATA_DIR
    ext_base = os.path.join(DATA_DIR, "extensions_external")
    if not os.path.isdir(ext_base):
        return None
    # Check exact name first, then prefix match
    exact = os.path.join(ext_base, "video_editor")
    if os.path.isdir(exact):
        return exact
    for entry in os.listdir(ext_base):
        if entry.startswith("video_editor__") and os.path.isdir(os.path.join(ext_base, entry)):
            return os.path.join(ext_base, entry)
    return None


def _find_sheets_manager_dir():
    """Find the Sheets Manager extension directory (handles 'sheets_manager' and 'sheets_manager__xxx')."""
    from tubecli.config import DATA_DIR
    ext_base = os.path.join(DATA_DIR, "extensions_external")
    if not os.path.isdir(ext_base):
        return None
    exact = os.path.join(ext_base, "sheets_manager")
    if os.path.isdir(exact):
        return exact
    for entry in os.listdir(ext_base):
        if entry.startswith("sheets_manager__") and os.path.isdir(os.path.join(ext_base, entry)):
            return os.path.join(ext_base, entry)
    return None


@router.get("/video-editor")
async def video_editor_page():
    """Serve the Video Editor page."""
    ve_dir = _find_video_editor_dir()
    if ve_dir:
        editor_file = os.path.join(ve_dir, "static", "editor.html")
        if os.path.exists(editor_file):
            return FileResponse(editor_file)
    # Return a friendly install guide instead of raw JSON error
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content="""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Video Editor — Not Installed</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { 
                font-family: 'Segoe UI', system-ui, sans-serif;
                background: #0a0a12; color: #e0e0e0;
                display: flex; justify-content: center; align-items: center;
                min-height: 100vh;
            }
            .card {
                background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                border: 1px solid #2a2a4a; border-radius: 16px;
                padding: 48px; max-width: 520px; text-align: center;
                box-shadow: 0 8px 32px rgba(0,0,0,0.4);
            }
            .icon { font-size: 64px; margin-bottom: 16px; }
            h1 { font-size: 24px; margin-bottom: 12px; color: #fff; }
            p { color: #aaa; line-height: 1.6; margin-bottom: 24px; }
            .steps { text-align: left; background: #0d1117; border-radius: 10px; padding: 20px; margin-bottom: 24px; }
            .steps li { margin-bottom: 10px; color: #c9d1d9; list-style: none; }
            .steps li::before { content: "→ "; color: #58a6ff; font-weight: bold; }
            .btn {
                display: inline-block; padding: 12px 32px;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: #fff; border-radius: 8px; text-decoration: none;
                font-weight: 600; transition: transform 0.2s;
            }
            .btn:hover { transform: translateY(-2px); }
            code { background: #161b22; padding: 2px 6px; border-radius: 4px; color: #58a6ff; font-size: 14px; }
        </style>
    </head>
    <body>
        <div class="card">
            <div class="icon">🎬</div>
            <h1>Video Editor Extension</h1>
            <p>This extension is not installed yet. Install it from the Marketplace to get started.</p>
            <ul class="steps">
                <li>Open <strong>Dashboard</strong></li>
                <li>Go to <strong>Extensions → Marketplace</strong></li>
                <li>Search for <code>Video Editor</code></li>
                <li>Click <strong>Install</strong></li>
                <li>Restart TubeCLI and refresh this page</li>
            </ul>
            <a href="/dashboard" class="btn">← Back to Dashboard</a>
        </div>
    </body>
    </html>
    """, status_code=200)


@router.get("/video-editor-static/{filename:path}")
async def serve_video_editor_static(filename: str):
    """Serve Video Editor static files (JS, CSS)."""
    ve_dir = _find_video_editor_dir()
    if ve_dir:
        filepath = os.path.join(ve_dir, "static", filename)
        if os.path.exists(filepath):
            return FileResponse(filepath)
    return {"error": f"File {filename} not found"}


@router.get("/sheets-manager")
@router.get("/sheets_manager")
async def sheets_manager_page():
    """Serve the Sheets Manager page."""
    sm_dir = _find_sheets_manager_dir()
    if sm_dir:
        html_file = os.path.join(sm_dir, "static", "sheets_manager.html")
        if os.path.exists(html_file):
            return FileResponse(html_file)
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content="""
    <!DOCTYPE html>
    <html lang="en">
    <head><meta charset="UTF-8"><title>Sheets Manager — Not Installed</title>
    <style>*{margin:0;padding:0;box-sizing:border-box}body{font-family:'Segoe UI',system-ui,sans-serif;background:#0a0a12;color:#e0e0e0;display:flex;justify-content:center;align-items:center;min-height:100vh}.card{background:linear-gradient(135deg,#1a1a2e,#16213e);border:1px solid #2a2a4a;border-radius:16px;padding:48px;max-width:480px;text-align:center;box-shadow:0 8px 32px rgba(0,0,0,.4)}.icon{font-size:64px;margin-bottom:16px}h1{font-size:24px;margin-bottom:12px;color:#fff}p{color:#aaa;line-height:1.6;margin-bottom:24px}.btn{display:inline-block;padding:12px 32px;background:linear-gradient(135deg,#00d4ff,#a855f7);color:#000;border-radius:8px;text-decoration:none;font-weight:700}</style>
    </head>
    <body><div class="card"><div class="icon">📊</div><h1>Sheets Manager</h1><p>Extension not installed. Install it from the Marketplace to get started.</p><a href="/dashboard" class="btn">← Back to Dashboard</a></div></body>
    </html>
    """, status_code=200)


@router.get("/sheets-manager-static/{filename:path}")
@router.get("/sheets_manager-static/{filename:path}")
async def serve_sheets_manager_static(filename: str):
    """Serve Sheets Manager static files (JS, CSS)."""
    sm_dir = _find_sheets_manager_dir()
    if sm_dir:
        filepath = os.path.join(sm_dir, "static", filename)
        if os.path.exists(filepath):
            return FileResponse(filepath)
    return {"error": f"File {filename} not found"}


def _find_livestream_dir():
    """Find the Livestream extension directory (handles 'livestream' and 'livestream__xxx')."""
    from tubecli.config import DATA_DIR
    ext_base = os.path.join(DATA_DIR, "extensions_external")
    if not os.path.isdir(ext_base):
        return None
    exact = os.path.join(ext_base, "livestream")
    if os.path.isdir(exact):
        return exact
    for entry in os.listdir(ext_base):
        if entry.startswith("livestream__") and os.path.isdir(os.path.join(ext_base, entry)):
            return os.path.join(ext_base, entry)
    return None


@router.get("/livestream")
async def livestream_page():
    """Serve the Livestream Manager page."""
    ls_dir = _find_livestream_dir()
    if ls_dir:
        html_file = os.path.join(ls_dir, "static", "livestream.html")
        if os.path.exists(html_file):
            return FileResponse(html_file)
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content="""
    <!DOCTYPE html>
    <html lang="en">
    <head><meta charset="UTF-8"><title>Livestream Manager — Not Installed</title>
    <style>*{margin:0;padding:0;box-sizing:border-box}body{font-family:'Segoe UI',system-ui,sans-serif;background:#0a0a12;color:#e0e0e0;display:flex;justify-content:center;align-items:center;min-height:100vh}.card{background:linear-gradient(135deg,#1a1a2e,#16213e);border:1px solid #2a2a4a;border-radius:16px;padding:48px;max-width:480px;text-align:center;box-shadow:0 8px 32px rgba(0,0,0,.4)}.icon{font-size:64px;margin-bottom:16px}h1{font-size:24px;margin-bottom:12px;color:#fff}p{color:#aaa;line-height:1.6;margin-bottom:24px}.btn{display:inline-block;padding:12px 32px;background:linear-gradient(135deg,#ef4444,#f97316);color:#fff;border-radius:8px;text-decoration:none;font-weight:700}</style>
    </head>
    <body><div class="card"><div class="icon">📡</div><h1>Livestream Manager</h1><p>Extension not installed. Install it from the Marketplace to get started.</p><a href="/dashboard" class="btn">← Back to Dashboard</a></div></body>
    </html>
    """, status_code=200)


@router.get("/livestream-static/{filename:path}")
async def serve_livestream_static(filename: str):
    """Serve Livestream Manager static files (JS, CSS)."""
    ls_dir = _find_livestream_dir()
    if ls_dir:
        filepath = os.path.join(ls_dir, "static", filename)
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

