"""
WebUI API routes — serve dashboard and workflow static files via FastAPI.
"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
import os
import mimetypes

# Register proper MIME types to prevent Windows-specific text/plain CSS bugs
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("image/png", ".png")
mimetypes.add_type("image/jpeg", ".jpg")
mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("application/json", ".json")


router = APIRouter(tags=["webui"])
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

@router.get("/favicon.ico")
async def get_favicon():
    return FileResponse(os.path.join(STATIC_DIR, "favicon.ico"), media_type="image/x-icon")


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

def _default_settings():
    """Build default settings with dynamic port resolution."""
    try:
        from tubecli.config import get_api_port
        port = str(get_api_port())
    except Exception:
        port = "5295"
    return {
        "default_model": "qwen:latest",
        "api_port": port,
        "api_base_url": f"http://localhost:{port}",
        "language": "en",
        "telegram_bot_token": "",
        "telegram_chat_id": "",
        "default_calendar_email": "",
        "default_storage_email": "",
        "ext_update_notifications": False,
        "ext_open_mode": "full_page",
        # "system" | "light" | "dark". The browser's localStorage is what the
        # pre-paint script reads (it must decide before any network call); this
        # copy only carries the choice between machines.
        "theme": "system",
    }

# Keep backward compat for any code referencing _DEFAULT_SETTINGS
_DEFAULT_SETTINGS = _default_settings()

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

    # Auto-update all agents when global default model changes
    if "default_model" in body:
        new_model = body["default_model"]
        try:
            from tubecli.core.agent import agent_manager
            for agent in agent_manager.get_all():
                agent_manager.update(agent.id, model=new_model)
        except Exception:
            pass

    return JSONResponse({"status": "success", "settings": existing})


# ── Pipeline Monitor API ─────────────────────────────────────────
from tubecli.core.pipeline_tracker import pipeline_tracker

@router.get("/api/v1/pipelines")
async def list_pipelines(limit: int = 20, status: str = None):
    """List recent pipeline tasks."""
    tasks = pipeline_tracker.list_tasks(limit=limit, status=status)
    stats = pipeline_tracker.get_stats()
    return JSONResponse({"tasks": tasks, "stats": stats})

@router.get("/api/v1/pipelines/stats")
async def pipeline_stats():
    """Get pipeline task statistics."""
    return JSONResponse(pipeline_tracker.get_stats())

@router.get("/api/v1/pipelines/{task_id}")
async def get_pipeline(task_id: str):
    """Get a single pipeline task detail."""
    task = pipeline_tracker.get_task(task_id)
    if not task:
        return JSONResponse({"error": "Task not found"}, status_code=404)
    return JSONResponse(task)


# Cache-busting tokens, derived rather than typed.
#
# index.html referenced /static/app.js?v=36 — a number a human had to remember to
# increment. Forget it once and every existing user's browser keeps serving the
# old JavaScript against the new API, which presents as a feature that silently
# does nothing and looks like a backend bug. That is exactly what happened when
# the agent run-log panel shipped.
#
# The token is now the first 8 hex of the file's own content hash, substituted at
# serve time, so it changes when and only when the file does.
_ASSET_TOKENS: dict = {}


def _asset_token(name: str) -> str:
    path = os.path.join(STATIC_DIR, name)
    try:
        stamp = os.stat(path).st_mtime_ns
    except OSError:
        return "0"
    cached = _ASSET_TOKENS.get(name)
    if cached and cached[0] == stamp:
        return cached[1]
    try:
        import hashlib
        with open(path, "rb") as f:
            token = hashlib.md5(f.read()).hexdigest()[:8]
    except OSError:
        return "0"
    _ASSET_TOKENS[name] = (stamp, token)
    return token


def _bust(html: str) -> str:
    import re
    # Only /static/<file>.(js|css) — the ?v= on the extension iframes further up
    # index.html are unrelated route parameters and must be left alone.
    #
    # The existing token is OPTIONAL in this pattern, so pages that never had one
    # get one too. workflow.html was such a page: it referenced /static/workflow.js
    # bare, which is a browser cache with no expiry and no way to invalidate it —
    # and because a cache is per-origin, the same code could be current on
    # localhost and months stale on the server's IP.
    return re.sub(
        r'(/static/([A-Za-z0-9_.-]+\.(?:js|css)))(?:\?v=[^"\']*)?',
        lambda m: f"{m.group(1)}?v={_asset_token(m.group(2))}",
        html)


def _html_page(filename: str, missing: str):
    """Serve a static HTML page with fresh asset tokens.

    Every page here loads /static JavaScript, so every page needs the tokens
    rewritten — not just the dashboard. Falls back to the raw file if anything
    goes wrong: a cache-busting bug must never be the reason a page 500s.
    """
    path = os.path.join(STATIC_DIR, filename)
    if not os.path.exists(path):
        return {"error": missing}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return HTMLResponse(_bust(f.read()), headers={"Cache-Control": "no-store"})
    except Exception:
        return FileResponse(path)


@router.get("/dashboard")
async def dashboard():
    # no-store on the HTML itself: it is the thing that carries the asset
    # tokens, so a cached copy would pin the old asset URLs in place and defeat
    # the whole mechanism.
    return _html_page("index.html", "Dashboard not found")


@router.get("/pipeline-monitor")
async def pipeline_monitor_page():
    """Serve the Pipeline Monitor page."""
    return _html_page("pipeline_monitor.html", "Pipeline Monitor page not found")


@router.get("/workflow")
async def workflow_page():
    """Serve the workflow builder page."""
    return _html_page("workflow.html", "Workflow builder not found")


@router.get("/teams")
async def teams_page():
    """Serve the Teams AI dashboard page."""
    return _html_page("teams.html", "Teams dashboard not found")


@router.get("/studio")
async def studio_page():
    """Serve the 3D Studio editor page."""
    return _html_page("studio.html", "Studio page not found")


@router.get("/market")
async def market_page():
    """Serve the Extension Market page."""
    return _html_page("market.html", "Market page not found")


@router.get("/downloader")
async def downloader_page():
    """Serve the Video Downloader page."""
    return _html_page("downloader.html", "Downloader page not found")


@router.get("/story")
async def story_page():
    """Serve the 3D Story Engine page."""
    return _html_page("story.html", "Story page not found")


@router.get("/auth-manager")
async def auth_manager_page():
    """Serve the Auth Manager page."""
    return _html_page("auth_manager.html", "Auth Manager page not found")


@router.get("/browser/view")
async def browser_view_page():
    """Serve the Browser WebSocket View page.

    Through _html_page like the others: this page carries its whole client in an
    inline script, so a cached copy means cached CODE with no asset token to
    invalidate. Every fix to the remote view was landing behind a stale page.
    """
    return _html_page("browser_view.html", "Browser View page not found")



@router.get("/tracker")
async def tracker_page():
    """Serve the Content Tracker management page."""
    return _html_page("tracker.html", "Tracker page not found")


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
            return _ext_html(html_file)
    return {"error": "File Manager page not found"}


# NOTE: the CapCut TTS page is served by the extension's OWN router at
# /api/v1/capcut-tts/page — no page route is added here. A new extension should
# ship its own page route so it does not need an edit to this core file (and a
# server restart perfectly timed with it) just to appear.


def _ext_html(path: str):
    """Serve an extension's HTML page so it can never be served stale.

    These pages carry no asset token of their own, and FileResponse sets only
    ETag/Last-Modified — which browsers are free to treat as a heuristic
    freshness hint and skip the revalidation entirely. After an extension update
    that leaves the old page rendering in an already-open tab, with no way for
    the user to tell. no-store costs one conditional request per page open.
    """
    return FileResponse(path, headers={"Cache-Control": "no-store"})


def _serve_from(base_dir: str, filename: str, label: str):
    """Serve `filename` from `base_dir`, and from nowhere else.

    This used to be os.path.join(base_dir, filename) followed by os.path.exists.
    Starlette normalises a literal "../" out of the URL path before routing, so
    that looked safe — but percent-encoded traversal is decoded AFTER routing and
    arrives at the handler intact. Confirmed: five encoded variants
    (%2e%2e%2f, ..%2f, ..%5c, %252e%252e%252f and %2e%2e/) each returned 200, and
    the reach was not limited to the extension — data/cloud_api_keys.json and
    C:\\Windows\\win.ini both came back. That is arbitrary file read, and the API
    keys are the worst possible thing to hand out.

    realpath on both sides is what actually closes it: it resolves the traversal
    and any symlink before the comparison, so containment is decided on the real
    location rather than on the string the caller supplied.
    """
    if not base_dir:
        raise HTTPException(404, f"{label} not found")
    root = os.path.realpath(base_dir)
    target = os.path.realpath(os.path.join(root, filename))
    if target != root and not target.startswith(root + os.sep):
        raise HTTPException(403, "Path is outside the extension directory")
    if not os.path.isfile(target):
        raise HTTPException(404, f"File {filename} not found")
    return FileResponse(target)


@router.get("/file-manager-static/{filename:path}")
async def serve_file_manager_static(filename: str):
    """Serve File Manager static files (JS, CSS)."""
    return _serve_from(_find_file_manager_dir(), filename, "File Manager")



def _find_video_editor_dir():
    """Find the Video Editor extension directory."""
    from tubecli.core.extension_manager import extension_manager
    ext = extension_manager.get("video_editor")
    if ext and ext.extension_dir:
        return ext.extension_dir
    from tubecli.config import DATA_DIR
    ext_base = os.path.join(DATA_DIR, "extensions_external")
    if not os.path.isdir(ext_base):
        return None
    exact = os.path.join(ext_base, "video_editor")
    if os.path.isdir(exact):
        return exact
    for entry in os.listdir(ext_base):
        if entry.startswith("video_editor__") and os.path.isdir(os.path.join(ext_base, entry)):
            return os.path.join(ext_base, entry)
    return None


def _find_sheets_manager_dir():
    """Find the Sheets Manager extension directory."""
    from tubecli.core.extension_manager import extension_manager
    ext = extension_manager.get("sheets_manager")
    if ext and ext.extension_dir:
        return ext.extension_dir
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
    return _serve_from(os.path.join(ve_dir, "static") if ve_dir else "",
                       filename, "Video Editor")


@router.get("/video/processing")
async def video_processing_page():
    """Serve the Video Processing Queue page."""
    ve_dir = _find_video_editor_dir()
    if ve_dir:
        processing_file = os.path.join(ve_dir, "static", "processing.html")
        if os.path.exists(processing_file):
            return FileResponse(processing_file)
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content="""
    <!DOCTYPE html>
    <html lang="en">
    <head><title>Video Processing — Not Found</title></head>
    <body style="background:#0a0a12;color:white;font-family:sans-serif;display:flex;justify-content:center;align-items:center;height:100vh;">
        <h1>Video Processing UI Not Found</h1>
    </body>
    </html>
    """, status_code=200)

@router.get("/sheets-manager")
@router.get("/sheets_manager")
async def sheets_manager_page():
    """Serve the Sheets Manager page."""
    sm_dir = _find_sheets_manager_dir()
    if sm_dir:
        html_file = os.path.join(sm_dir, "static", "sheets_manager.html")
        if os.path.exists(html_file):
            return _ext_html(html_file)
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
    return _serve_from(os.path.join(sm_dir, "static") if sm_dir else "",
                       filename, "Sheets Manager")


def _find_livestream_dir():
    """Find the Livestream extension directory."""
    from tubecli.core.extension_manager import extension_manager
    ext = extension_manager.get("livestream")
    if ext and ext.extension_dir:
        return ext.extension_dir
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
            return _ext_html(html_file)
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
    return _serve_from(os.path.join(ls_dir, "static") if ls_dir else "",
                       filename, "Livestream Manager")


@router.get("/static/{filename:path}")
async def serve_static(filename: str):
    """Serve static files (JS, CSS, etc.)."""
    return _serve_from(STATIC_DIR, filename, "Dashboard asset")


def _find_web_crawler_dir():
    """Find the Web Crawler extension directory."""
    from tubecli.core.extension_manager import extension_manager
    ext = extension_manager.get("web_crawler")
    if ext and ext.extension_dir:
        return ext.extension_dir
    from tubecli.config import DATA_DIR
    ext_base = os.path.join(DATA_DIR, "extensions_external")
    if not os.path.isdir(ext_base):
        return None
    exact = os.path.join(ext_base, "web_crawler")
    if os.path.isdir(exact):
        return exact
    for entry in os.listdir(ext_base):
        if entry.startswith("web_crawler__") and os.path.isdir(os.path.join(ext_base, entry)):
            return os.path.join(ext_base, entry)
    return None


@router.get("/web-crawler")
@router.get("/web_crawler")
async def web_crawler_page():
    """Serve the Web Crawler page."""
    wc_dir = _find_web_crawler_dir()
    if wc_dir:
        html_file = os.path.join(wc_dir, "static", "web_crawler.html")
        if os.path.exists(html_file):
            return _ext_html(html_file)
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content="""
    <!DOCTYPE html>
    <html lang="en">
    <head><meta charset="UTF-8"><title>Web Crawler — Not Installed</title>
    <style>*{margin:0;padding:0;box-sizing:border-box}body{font-family:'Segoe UI',system-ui,sans-serif;background:#0a0a12;color:#e0e0e0;display:flex;justify-content:center;align-items:center;min-height:100vh}.card{background:linear-gradient(135deg,#1a1a2e,#16213e);border:1px solid #2a2a4a;border-radius:16px;padding:48px;max-width:480px;text-align:center;box-shadow:0 8px 32px rgba(0,0,0,.4)}.icon{font-size:64px;margin-bottom:16px}h1{font-size:24px;margin-bottom:12px;color:#fff}p{color:#aaa;line-height:1.6;margin-bottom:24px}.btn{display:inline-block;padding:12px 32px;background:linear-gradient(135deg,#00d4ff,#10b981);color:#000;border-radius:8px;text-decoration:none;font-weight:700}</style>
    </head>
    <body><div class="card"><div class="icon">🕸️</div><h1>Web Crawler</h1><p>Extension not installed. Install it from the Marketplace to get started.</p><a href="/dashboard" class="btn">← Back to Dashboard</a></div></body>
    </html>
    """, status_code=200)


@router.get("/web-crawler-static/{filename:path}")
@router.get("/web_crawler-static/{filename:path}")
async def serve_web_crawler_static(filename: str):
    """Serve Web Crawler static files (JS, CSS)."""
    wc_dir = _find_web_crawler_dir()
    return _serve_from(os.path.join(wc_dir, "static") if wc_dir else "",
                       filename, "Web Crawler")


def _find_video_manager_dir():
    """Find the Video Manager extension directory."""
    from tubecli.core.extension_manager import extension_manager
    ext = extension_manager.get("video_manager")
    if ext and ext.extension_dir:
        return ext.extension_dir
    from tubecli.config import DATA_DIR
    ext_base = os.path.join(DATA_DIR, "extensions_external")
    if not os.path.isdir(ext_base):
        return None
    exact = os.path.join(ext_base, "video_manager")
    if os.path.isdir(exact):
        return exact
    for entry in os.listdir(ext_base):
        if entry.startswith("video_manager__") and os.path.isdir(os.path.join(ext_base, entry)):
            return os.path.join(ext_base, entry)
    return None


@router.get("/video-manager")
@router.get("/video_manager")
async def video_manager_page():
    """Serve the Video Manager page."""
    vm_dir = _find_video_manager_dir()
    if vm_dir:
        html_file = os.path.join(vm_dir, "static", "index.html")
        if os.path.exists(html_file):
            return _ext_html(html_file)
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content="""
    <!DOCTYPE html>
    <html lang="en">
    <head><meta charset="UTF-8"><title>Video Manager — Not Installed</title>
    <style>*{margin:0;padding:0;box-sizing:border-box}body{font-family:'Segoe UI',system-ui,sans-serif;background:#0a0a12;color:#e0e0e0;display:flex;justify-content:center;align-items:center;min-height:100vh}.card{background:linear-gradient(135deg,#1a1a2e,#16213e);border:1px solid #2a2a4a;border-radius:16px;padding:48px;max-width:480px;text-align:center;box-shadow:0 8px 32px rgba(0,0,0,.4)}.icon{font-size:64px;margin-bottom:16px}h1{font-size:24px;margin-bottom:12px;color:#fff}p{color:#aaa;line-height:1.6;margin-bottom:24px}.btn{display:inline-block;padding:12px 32px;background:linear-gradient(135deg,#3b82f6,#8b5cf6);color:#fff;border-radius:8px;text-decoration:none;font-weight:700}</style>
    </head>
    <body><div class="card"><div class="icon">📹</div><h1>Video Manager</h1><p>Extension not installed. Install it from the Marketplace to get started.</p><a href="/dashboard" class="btn">← Back to Dashboard</a></div></body>
    </html>
    """, status_code=200)


@router.get("/video-manager-static/{filename:path}")
@router.get("/video_manager-static/{filename:path}")
async def serve_video_manager_static(filename: str):
    """Serve Video Manager static files."""
    vm_dir = _find_video_manager_dir()
    return _serve_from(os.path.join(vm_dir, "static") if vm_dir else "",
                       filename, "Video Manager")


def _find_subtitle_extractor_dir():
    """Find the Subtitle Extractor extension directory."""
    from tubecli.core.extension_manager import extension_manager
    ext = extension_manager.get("subtitle_extractor")
    if ext and ext.extension_dir:
        return ext.extension_dir
    from tubecli.config import DATA_DIR
    ext_base = os.path.join(DATA_DIR, "extensions_external")
    if not os.path.isdir(ext_base):
        return None
    exact = os.path.join(ext_base, "subtitle_extractor")
    if os.path.isdir(exact):
        return exact
    for entry in os.listdir(ext_base):
        if entry.startswith("subtitle_extractor__") and os.path.isdir(os.path.join(ext_base, entry)):
            return os.path.join(ext_base, entry)
    return None


@router.get("/subtitle-extractor")
@router.get("/subtitle_extractor")
async def subtitle_extractor_page():
    """Serve the Subtitle Extractor page."""
    se_dir = _find_subtitle_extractor_dir()
    if se_dir:
        html_file = os.path.join(se_dir, "static", "subtitle.html")
        if os.path.exists(html_file):
            return _ext_html(html_file)
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content="""
    <!DOCTYPE html>
    <html lang="en">
    <head><meta charset="UTF-8"><title>Subtitle Extractor — Not Installed</title>
    <style>*{margin:0;padding:0;box-sizing:border-box}body{font-family:'Segoe UI',system-ui,sans-serif;background:#0a0a12;color:#e0e0e0;display:flex;justify-content:center;align-items:center;min-height:100vh}.card{background:linear-gradient(135deg,#1a1a2e,#16213e);border:1px solid #2a2a4a;border-radius:16px;padding:48px;max-width:480px;text-align:center;box-shadow:0 8px 32px rgba(0,0,0,.4)}.icon{font-size:64px;margin-bottom:16px}h1{font-size:24px;margin-bottom:12px;color:#fff}p{color:#aaa;line-height:1.6;margin-bottom:24px}.btn{display:inline-block;padding:12px 32px;background:linear-gradient(135deg,#3b82f6,#8b5cf6);color:#fff;border-radius:8px;text-decoration:none;font-weight:700}</style>
    </head>
    <body><div class="card"><div class="icon">📝</div><h1>Subtitle Extractor</h1><p>Extension not installed. Install it from the Marketplace to get started.</p><a href="/dashboard" class="btn">← Back to Dashboard</a></div></body>
    </html>
    """, status_code=200)


@router.get("/subtitle-extractor-static/{filename:path}")
@router.get("/subtitle_extractor-static/{filename:path}")
async def serve_subtitle_extractor_static(filename: str):
    """Serve Subtitle Extractor static files."""
    se_dir = _find_subtitle_extractor_dir()
    return _serve_from(os.path.join(se_dir, "static") if se_dir else "",
                       filename, "Subtitle Extractor")


def _find_tts_vibevoice_dir():
    """Find the TTS VibeVoice extension directory."""
    from tubecli.core.extension_manager import extension_manager
    ext = extension_manager.get("tts_vibevoice")
    if ext and ext.extension_dir:
        return ext.extension_dir
    from tubecli.config import DATA_DIR
    ext_base = os.path.join(DATA_DIR, "extensions_external")
    if not os.path.isdir(ext_base):
        return None
    exact = os.path.join(ext_base, "tts_vibevoice")
    if os.path.isdir(exact):
        return exact
    for entry in os.listdir(ext_base):
        if entry.startswith("tts_vibevoice__") and os.path.isdir(os.path.join(ext_base, entry)):
            return os.path.join(ext_base, entry)
    return None


@router.get("/tts-vibevoice")
@router.get("/tts_vibevoice")
async def tts_vibevoice_page():
    """Serve the TTS VibeVoice page."""
    tts_dir = _find_tts_vibevoice_dir()
    if tts_dir:
        html_file = os.path.join(tts_dir, "static", "tts.html")
        if os.path.exists(html_file):
            return _ext_html(html_file)
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content="""
    <!DOCTYPE html>
    <html lang="en">
    <head><meta charset="UTF-8"><title>TTS VibeVoice — Not Installed</title>
    <style>*{margin:0;padding:0;box-sizing:border-box}body{font-family:'Segoe UI',system-ui,sans-serif;background:#0a0a12;color:#e0e0e0;display:flex;justify-content:center;align-items:center;min-height:100vh}.card{background:linear-gradient(135deg,#1a1a2e,#16213e);border:1px solid #2a2a4a;border-radius:16px;padding:48px;max-width:480px;text-align:center;box-shadow:0 8px 32px rgba(0,0,0,.4)}.icon{font-size:64px;margin-bottom:16px}h1{font-size:24px;margin-bottom:12px;color:#fff}p{color:#aaa;line-height:1.6;margin-bottom:24px}.btn{display:inline-block;padding:12px 32px;background:linear-gradient(135deg,#6366f1,#a855f7);color:#fff;border-radius:8px;text-decoration:none;font-weight:700}</style>
    </head>
    <body><div class="card"><div class="icon">🔊</div><h1>TTS VibeVoice</h1><p>Extension not installed. Install it from the Marketplace to get started.</p><a href="/dashboard" class="btn">← Back to Dashboard</a></div></body>
    </html>
    """, status_code=200)


@router.get("/tts-vibevoice-static/{filename:path}")
@router.get("/tts_vibevoice-static/{filename:path}")
async def serve_tts_vibevoice_static(filename: str):
    """Serve TTS VibeVoice static files (JS, CSS, i18n)."""
    tts_dir = _find_tts_vibevoice_dir()
    return _serve_from(os.path.join(tts_dir, "static") if tts_dir else "",
                       filename, "TTS VibeVoice")


def _find_ai_arena_dir():
    """Find the AI Arena extension directory."""
    from tubecli.core.extension_manager import extension_manager
    ext = extension_manager.get("ai_arena")
    if ext and ext.extension_dir:
        return ext.extension_dir
    from tubecli.config import DATA_DIR
    ext_base = os.path.join(DATA_DIR, "extensions_external")
    if not os.path.isdir(ext_base):
        return None
    exact = os.path.join(ext_base, "ai_arena")
    if os.path.isdir(exact):
        return exact
    for entry in os.listdir(ext_base):
        if entry.startswith("ai_arena__") and os.path.isdir(os.path.join(ext_base, entry)):
            return os.path.join(ext_base, entry)
    return None


@router.get("/ai-arena")
@router.get("/ai_arena")
async def ai_arena_page():
    """Serve the AI Arena page."""
    arena_dir = _find_ai_arena_dir()
    if arena_dir:
        html_file = os.path.join(arena_dir, "static", "arena.html")
        if os.path.exists(html_file):
            return _ext_html(html_file)
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content="""
    <!DOCTYPE html>
    <html lang="en">
    <head><meta charset="UTF-8"><title>AI Arena — Not Installed</title>
    <style>*{margin:0;padding:0;box-sizing:border-box}body{font-family:'Segoe UI',system-ui,sans-serif;background:#0a0a12;color:#e0e0e0;display:flex;justify-content:center;align-items:center;min-height:100vh}.card{background:linear-gradient(135deg,#1a1a2e,#16213e);border:1px solid #2a2a4a;border-radius:16px;padding:48px;max-width:480px;text-align:center;box-shadow:0 8px 32px rgba(0,0,0,.4)}.icon{font-size:64px;margin-bottom:16px}h1{font-size:24px;margin-bottom:12px;color:#fff}p{color:#aaa;line-height:1.6;margin-bottom:24px}.btn{display:inline-block;padding:12px 32px;background:linear-gradient(135deg,#6366f1,#ec4899);color:#fff;border-radius:8px;text-decoration:none;font-weight:700}</style>
    </head>
    <body><div class="card"><div class="icon">🎮</div><h1>AI Arena</h1><p>Extension not installed. Install it from the Marketplace to get started.</p><a href="/dashboard" class="btn">← Back to Dashboard</a></div></body>
    </html>
    """, status_code=200)


@router.get("/ai-arena-static/{filename:path}")
@router.get("/ai_arena-static/{filename:path}")
async def serve_ai_arena_static(filename: str):
    """Serve AI Arena static files (JS, CSS)."""
    arena_dir = _find_ai_arena_dir()
    return _serve_from(os.path.join(arena_dir, "static") if arena_dir else "",
                       filename, "AI Arena")


def _find_template_designer_dir():
    """Find the Template Designer extension directory."""
    from tubecli.core.extension_manager import extension_manager
    ext = extension_manager.get("template_designer")
    if ext and ext.extension_dir:
        return ext.extension_dir
    from tubecli.config import DATA_DIR
    ext_base = os.path.join(DATA_DIR, "extensions_external")
    if not os.path.isdir(ext_base):
        return None
    exact = os.path.join(ext_base, "template_designer")
    if os.path.isdir(exact):
        return exact
    for entry in os.listdir(ext_base):
        if entry.startswith("template_designer__") and os.path.isdir(os.path.join(ext_base, entry)):
            return os.path.join(ext_base, entry)
    return None


@router.get("/template-designer")
@router.get("/template_designer")
async def template_designer_page():
    """Serve the Template Designer page."""
    td_dir = _find_template_designer_dir()
    if td_dir:
        html_file = os.path.join(td_dir, "static", "designer.html")
        if os.path.exists(html_file):
            return _ext_html(html_file)
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content="""
    <!DOCTYPE html>
    <html lang="en">
    <head><meta charset="UTF-8"><title>Template Designer — Not Installed</title>
    <style>*{margin:0;padding:0;box-sizing:border-box}body{font-family:'Segoe UI',system-ui,sans-serif;background:#0a0a12;color:#e0e0e0;display:flex;justify-content:center;align-items:center;min-height:100vh}.card{background:linear-gradient(135deg,#1a1a2e,#16213e);border:1px solid #2a2a4a;border-radius:16px;padding:48px;max-width:480px;text-align:center;box-shadow:0 8px 32px rgba(0,0,0,.4)}.icon{font-size:64px;margin-bottom:16px}h1{font-size:24px;margin-bottom:12px;color:#fff}p{color:#aaa;line-height:1.6;margin-bottom:24px}.btn{display:inline-block;padding:12px 32px;background:linear-gradient(135deg,#f59e0b,#ef4444);color:#fff;border-radius:8px;text-decoration:none;font-weight:700}</style>
    </head>
    <body><div class="card"><div class="icon">🎨</div><h1>Template Designer</h1><p>Extension not installed. Install it from the Marketplace to get started.</p><a href="/dashboard" class="btn">← Back to Dashboard</a></div></body>
    </html>
    """, status_code=200)


@router.get("/template-designer-static/{filename:path}")
@router.get("/template_designer-static/{filename:path}")
async def serve_template_designer_static(filename: str):
    """Serve Template Designer static files (JS, CSS)."""
    td_dir = _find_template_designer_dir()
    return _serve_from(os.path.join(td_dir, "static") if td_dir else "",
                       filename, "Template Designer")


def _find_edu_video_studio_dir():
    """Find the EduVideo Studio extension directory."""
    from tubecli.core.extension_manager import extension_manager
    ext = extension_manager.get("edu_video_studio")
    if ext and ext.extension_dir:
        return ext.extension_dir
    from tubecli.config import DATA_DIR
    ext_base = os.path.join(DATA_DIR, "extensions_external")
    if not os.path.isdir(ext_base):
        return None
    exact = os.path.join(ext_base, "edu_video_studio")
    if os.path.isdir(exact):
        return exact
    for entry in os.listdir(ext_base):
        if entry.startswith("edu_video_studio__") and os.path.isdir(os.path.join(ext_base, entry)):
            return os.path.join(ext_base, entry)
    return None


@router.get("/edu-video-studio")
@router.get("/edu_video_studio")
async def edu_video_studio_page():
    """Serve the EduVideo Studio page."""
    ev_dir = _find_edu_video_studio_dir()
    if ev_dir:
        html_file = os.path.join(ev_dir, "static", "edu_studio.html")
        if os.path.exists(html_file):
            return _ext_html(html_file)
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content="""
    <!DOCTYPE html>
    <html lang="en">
    <head><meta charset="UTF-8"><title>EduVideo Studio — Not Installed</title>
    <style>*{margin:0;padding:0;box-sizing:border-box}body{font-family:'Segoe UI',system-ui,sans-serif;background:#0a0a12;color:#e0e0e0;display:flex;justify-content:center;align-items:center;min-height:100vh}.card{background:linear-gradient(135deg,#1a1a2e,#16213e);border:1px solid #2a2a4a;border-radius:16px;padding:48px;max-width:480px;text-align:center;box-shadow:0 8px 32px rgba(0,0,0,.4)}.icon{font-size:64px;margin-bottom:16px}h1{font-size:24px;margin-bottom:12px;color:#fff}p{color:#aaa;line-height:1.6;margin-bottom:24px}.btn{display:inline-block;padding:12px 32px;background:linear-gradient(135deg,#FFD700,#f59e0b);color:#000;border-radius:8px;text-decoration:none;font-weight:700}</style>
    </head>
    <body><div class="card"><div class="icon">🎓</div><h1>EduVideo Studio</h1><p>Extension not installed. Install it from the Marketplace to get started.</p><a href="/dashboard" class="btn">← Back to Dashboard</a></div></body>
    </html>
    """, status_code=200)


@router.get("/edu-video-studio-static/{filename:path}")
@router.get("/edu_video_studio-static/{filename:path}")
async def serve_edu_video_studio_static(filename: str):
    """Serve EduVideo Studio static files (JS, CSS)."""
    ev_dir = _find_edu_video_studio_dir()
    return _serve_from(os.path.join(ev_dir, "static") if ev_dir else "",
                       filename, "EduVideo Studio")
