"""
Website Manager Extension — FastAPI routes.
"""
import asyncio
import json
import os
import queue
import threading
import logging
from typing import Optional, List, AsyncGenerator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from pydantic import BaseModel

logger = logging.getLogger("WebsiteManagerRoutes")

# ── Static UI Router ─────────────────────────────────────────────────
_EXT_DIR = os.path.dirname(os.path.abspath(__file__))

ui_router = APIRouter(tags=["website-manager-ui"])

@ui_router.get("/website_manager")
async def serve_website_manager_ui():
    """Serve Website Manager UI."""
    return FileResponse(
        os.path.join(_EXT_DIR, "static", "index.html"),
        media_type="text/html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )

@ui_router.get("/website_manager/{filename:path}")
async def serve_website_manager_static(filename: str):
    """Serve Website Manager static assets."""
    filepath = os.path.join(_EXT_DIR, "static", filename)
    if os.path.isfile(filepath):
        if filename.endswith(".css"):
            media = "text/css"
        elif filename.endswith(".js"):
            media = "application/javascript"
        elif filename.endswith(".svg"):
            media = "image/svg+xml"
        elif filename.endswith(".png"):
            media = "image/png"
        elif filename.endswith(".webp"):
            media = "image/webp"
        else:
            media = "application/octet-stream"
        return FileResponse(filepath, media_type=media, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
    raise HTTPException(404, "File not found")

# ── API Router ───────────────────────────────────────────────────────
router = APIRouter(prefix="/api/v1/website-manager", tags=["website-manager"])


# ── Pydantic models ──────────────────────────────────────────────────

class AddWebsiteRequest(BaseModel):
    name: str
    user_token: str = ""
    wp_token: str = ""
    thumbnail: str = ""
    deploy_url: str = ""
    template: str = ""
    status: str = "active"


class UpdateWebsiteRequest(BaseModel):
    name: Optional[str] = None
    user_token: Optional[str] = None
    wp_token: Optional[str] = None
    thumbnail: Optional[str] = None
    deploy_url: Optional[str] = None
    template: Optional[str] = None
    status: Optional[str] = None
    admin_password: Optional[str] = None


class DeployWebsiteRequest(BaseModel):
    name: str
    template_id: str
    github_url: str
    cf_api_token: str = ""
    cf_account_id: str = ""
    cf_profile_label: str = "default"   # load from cloud_api if tokens empty
    admin_password: str = ""
    site_title: str = ""


# ── Helper ───────────────────────────────────────────────────────────

def _get_manager():
    from tubecli.extensions.website_manager.extension import website_manager
    return website_manager


# ── Routes ───────────────────────────────────────────────────────────

@router.get("/sites")
async def list_websites():
    """List all managed websites."""
    mgr = _get_manager()
    sites = mgr.list_websites()
    # Mask sensitive fields
    result = []
    for s in sites:
        item = dict(s)
        if item.get("cf_api_token"):
            t = item["cf_api_token"]
            item["cf_api_token"] = t[:6] + "..." + t[-4:] if len(t) > 10 else "***"
        result.append(item)
    return {"sites": result}


@router.post("/sites")
async def add_website(req: AddWebsiteRequest):
    """Add a website manually (name, user_token, wp_token, thumbnail)."""
    mgr = _get_manager()
    try:
        site = mgr.add_website(
            name=req.name,
            user_token=req.user_token,
            wp_token=req.wp_token,
            thumbnail=req.thumbnail,
            deploy_url=req.deploy_url,
            template=req.template,
            status=req.status,
        )
        return {"status": "ok", "site": site}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.put("/sites/{site_id}")
async def update_website(site_id: str, req: UpdateWebsiteRequest):
    """Update website fields."""
    mgr = _get_manager()
    data = req.model_dump(exclude_none=True)
    site = mgr.update_website(site_id, **data)
    if not site:
        raise HTTPException(404, f"Website '{site_id}' không tồn tại.")
    return {"status": "ok", "site": site}


@router.delete("/sites/{site_id}")
async def delete_website(site_id: str):
    """Delete a website record (does NOT delete Cloudflare resources)."""
    mgr = _get_manager()
    ok = mgr.delete_website(site_id)
    if not ok:
        raise HTTPException(404, f"Website '{site_id}' không tồn tại.")
    return {"status": "ok", "message": f"Đã xóa website '{site_id}'."}


@router.post("/sites/deploy")
async def deploy_website(req: DeployWebsiteRequest):
    """Start background deploy: clone → build → deploy to Cloudflare Workers."""
    from tubecli.extensions.website_manager.extension import (
        website_manager as mgr,
        _deploy_site_background,
    )

    # Validate name
    import re
    if not re.match(r'^[a-z0-9\-]+$', req.name):
        raise HTTPException(400, "Tên website chỉ được dùng chữ thường, số và dấu gạch ngang.")

    # Resolve CF credentials: form fields take priority, then cloud_api store
    cf_api_token = req.cf_api_token.strip()
    cf_account_id = req.cf_account_id.strip()

    if not cf_api_token or not cf_account_id:
        try:
            from tubecli.extensions.cloud_api.extension import key_manager
            creds = key_manager.get_cloudflare_creds(req.cf_profile_label or "default")
            if not cf_api_token:
                cf_api_token = creds.get("api_token", "")
            if not cf_account_id:
                cf_account_id = creds.get("account_id", "")
        except Exception:
            pass

    if not cf_api_token:
        raise HTTPException(400, "CF API Token là bắt buộc (nhập tực tiếp hoặc lưu trong Cloud Keys → Cloudflare).")
    if not cf_account_id:
        raise HTTPException(400, "CF Account ID là bắt buộc.")

    if not req.github_url:
        raise HTTPException(400, "GitHub URL của template là bắt buộc.")

    # Create or reset site record
    existing = mgr.get_website(req.name)
    if existing:
        mgr.update_website(req.name, status="deploying", cf_api_token=cf_api_token, cf_account_id=cf_account_id)
    else:
        mgr.add_website(
            name=req.name,
            template=req.template_id,
            status="deploying",
            cf_api_token=cf_api_token,
            cf_account_id=cf_account_id,
            admin_password=req.admin_password,
        )

    # Start background thread
    t = threading.Thread(
        target=_deploy_site_background,
        args=(
            mgr,
            req.name,
            req.template_id,
            req.github_url,
            cf_api_token,
            cf_account_id,
            req.admin_password,
            req.site_title,
        ),
        daemon=True,
    )
    t.start()

    return {"status": "ok", "message": f"Deploy '{req.name}' đã bắt đầu.", "site_name": req.name}


@router.get("/sites/{site_name}/logs")
async def stream_logs(site_name: str, request: Request):
    """SSE endpoint to stream deploy logs in real-time."""
    from tubecli.extensions.website_manager.extension import (
        get_log_file,
        register_log_listener,
        unregister_log_listener,
    )

    log_q: queue.Queue = queue.Queue(maxsize=500)
    register_log_listener(site_name, log_q)

    async def event_generator() -> AsyncGenerator[str, None]:
        # Send existing log content first
        log_file = get_log_file(site_name)
        if os.path.exists(log_file):
            try:
                with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                    history = f.read()
                if history:
                    payload = json.dumps({"message": history, "is_history": True})
                    yield f"data: {payload}\n\n"
            except Exception:
                pass

        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = log_q.get_nowait()
                    payload = json.dumps(msg)
                    yield f"data: {payload}\n\n"
                except queue.Empty:
                    await asyncio.sleep(0.2)
        finally:
            unregister_log_listener(site_name, log_q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/templates")
async def list_templates():
    """Fetch and return available themes from autoweb.tubecreate.com API."""
    import urllib.request
    import urllib.error

    TEMPLATES_API_URL = "https://autoweb.tubecreate.com/api/templates"
    try:
        req = urllib.request.Request(
            TEMPLATES_API_URL,
            headers={"User-Agent": "TubeCLI/1.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return {"templates": data}
    except Exception as e:
        logger.error(f"Failed to fetch templates: {e}")
        # Return default fallback templates
        return {
            "templates": [
                {
                    "id": "ngo-quyen",
                    "name": "Cổng thông tin trường học",
                    "description": "Trang tin tức tiếng Việt, phù hợp cho trường học, cơ quan hành chính.",
                    "thumbnail": "/themes/ngo-quyen.png",
                    "tags": ["Tiếng Việt", "Tin tức", "Giáo dục"],
                    "color": "#1a56a0",
                    "githubUrl": "https://github.com/tiensyk09/template-ngo-quyen.git",
                },
                {
                    "id": "commandcode",
                    "name": "Tech Landing Page",
                    "description": "Landing page tiếng Anh phong cách hiện đại tối màu, dành cho SaaS.",
                    "thumbnail": "/themes/commandcode.png",
                    "tags": ["Tiếng Anh", "Tech", "SaaS"],
                    "color": "#7c3aed",
                    "githubUrl": "https://github.com/tiensyk09/template-commandcode.git",
                },
                {
                    "id": "korean-news",
                    "name": "Báo điện tử Hàn Quốc",
                    "description": "Portal tin tức tiếng Hàn chuyên nghiệp.",
                    "thumbnail": "/themes/korean-news.png",
                    "tags": ["Tiếng Hàn", "Tin tức", "Portal"],
                    "color": "#c0392b",
                    "githubUrl": "https://github.com/tiensyk09/template-korean-news.git",
                },
                {
                    "id": "long-chau",
                    "name": "Nhà thuốc Long Châu",
                    "description": "Giao diện thương mại điện tử nhà thuốc chuyên nghiệp.",
                    "thumbnail": "/themes/long-chau.png",
                    "tags": ["Tiếng Việt", "Dược phẩm", "Bán lẻ"],
                    "color": "#005bcd",
                    "githubUrl": "https://github.com/tiensyk09/template-long-chau.git",
                },
            ],
            "error": str(e),
            "fallback": True,
        }


@router.get("/cloudflare-profiles")
async def get_cloudflare_profiles():
    """Get saved Cloudflare profiles from cloud_api extension (for deploy form auto-fill)."""
    try:
        from tubecli.extensions.cloud_api.extension import key_manager
        profiles = key_manager.list_cloudflare_keys()
        return {"profiles": profiles, "has_profiles": len(profiles) > 0}
    except Exception as e:
        return {"profiles": [], "has_profiles": False, "error": str(e)}
