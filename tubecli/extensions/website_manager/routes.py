"""
Website Manager Extension — FastAPI routes.
"""
import asyncio
import json
import os
import re
import queue
import threading
import logging
from typing import Optional, AsyncGenerator

from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel

logger = logging.getLogger("WebsiteManagerRoutes")

# ── Static UI Router ─────────────────────────────────────────────────
_EXT_DIR = os.path.dirname(os.path.abspath(__file__))
_STATIC_ROOT = os.path.realpath(os.path.join(_EXT_DIR, "static"))

# Tên site hợp lệ (dùng chung cho deploy + SSE + tên file log/build).
_SITE_NAME_RE = re.compile(r'^[a-z0-9\-]{1,64}\Z')
# URL template chỉ cho phép GitHub/GitLab https (chặn argument-injection + ext::).
_GITHUB_URL_RE = re.compile(r'^https://(github\.com|gitlab\.com)/[\w.\-]+/[\w.\-]+?(?:\.git)?$')

# Origin-guard dùng chung (same-origin aware) — xem core/origin_guard.py.
from tubecli.core.origin_guard import guard_origin as _guard_origin

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
    """Serve Website Manager static assets (chỉ trong thư mục static/)."""
    # Chống path traversal: chuẩn hoá rồi bắt buộc nằm trong _STATIC_ROOT.
    # `%2F..%2F` sống sót qua tầng ASGI nên phải kiểm bằng realpath, không tin
    # vào việc trình duyệt tự chuẩn hoá. realpath NẰM TRONG try vì null-byte
    # (%00) khiến chính realpath ném ValueError.
    try:
        filepath = os.path.realpath(os.path.join(_STATIC_ROOT, filename))
        if os.path.commonpath([_STATIC_ROOT, filepath]) != _STATIC_ROOT:
            raise HTTPException(404, "File not found")
    except (ValueError, OSError):
        # ValueError: khác ổ đĩa (Windows) hoặc null-byte; OSError: path lỗi
        raise HTTPException(404, "File not found")
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
# Origin-guard áp cho MỌI endpoint API (đọc secret + kích deploy).
router = APIRouter(
    prefix="/api/v1/website-manager",
    tags=["website-manager"],
    dependencies=[Depends(_guard_origin)],
)


# ── Validation dùng chung ────────────────────────────────────────────
_ALLOWED_STATUS = {"active", "deploying", "failed"}


def _valid_url_or_empty(v: str) -> bool:
    """URL cho phép: rỗng hoặc http(s). Chặn javascript:/data: (XSS qua href)."""
    if not v:
        return True
    return bool(re.match(r'^https?://', v.strip(), re.I))


# ── Mask secrets ─────────────────────────────────────────────────────
_SECRET_FIELDS = ("cf_api_token", "admin_password", "wp_token", "user_token")


def _mask_secret(val: str, strong: bool = False) -> str:
    """Che secret. strong=True (cho mật khẩu ngắn) chỉ trả '•••' — không hé lộ
    ký tự nào (secret dài 11-16 ký tự mà lộ 8 đầu+cuối là quá yếu cho password)."""
    if not val:
        return val
    if strong or len(val) <= 16:
        return "•••"
    return val[:4] + "•••" + val[-4:]


def _mask_site(site: dict) -> dict:
    """Trả bản sao site đã che mọi secret — dùng cho MỌI response trả site."""
    item = dict(site)
    for f in _SECRET_FIELDS:
        if item.get(f):
            item[f] = _mask_secret(item[f], strong=(f == "admin_password"))
    return item


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
    cf_email: str = ""                  # có email → Global API Key
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
    """List all managed websites (secret đã được che)."""
    mgr = _get_manager()
    sites = mgr.list_websites()
    return {"sites": [_mask_site(s) for s in sites]}


@router.post("/sites")
async def add_website(req: AddWebsiteRequest):
    """Add a website manually (name, user_token, wp_token, thumbnail)."""
    mgr = _get_manager()
    if not _SITE_NAME_RE.match(req.name):
        raise HTTPException(400, "Tên website chỉ được dùng chữ thường, số và dấu gạch ngang (tối đa 64 ký tự).")
    if req.status not in _ALLOWED_STATUS:
        raise HTTPException(400, "status không hợp lệ.")
    if not _valid_url_or_empty(req.deploy_url):
        raise HTTPException(400, "deploy_url phải là http(s) URL.")
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
        return {"status": "ok", "site": _mask_site(site)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.put("/sites/{site_id}")
async def update_website(site_id: str, req: UpdateWebsiteRequest):
    """Update website fields."""
    mgr = _get_manager()
    # Phân biệt "không gửi field" với "gửi rỗng": chỉ bỏ field client không đụng
    # tới (unset), giữ lại chuỗi rỗng để cho phép xoá trắng một token.
    data = req.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(400, "Không có thay đổi nào để lưu.")
    if "name" in data and data["name"] is not None and not _SITE_NAME_RE.match(data["name"]):
        raise HTTPException(400, "Tên website không hợp lệ.")
    if data.get("status") is not None and data["status"] not in _ALLOWED_STATUS:
        raise HTTPException(400, "status không hợp lệ.")
    if "deploy_url" in data and data["deploy_url"] is not None and not _valid_url_or_empty(data["deploy_url"]):
        raise HTTPException(400, "deploy_url phải là http(s) URL.")
    site = mgr.update_website(site_id, **data)
    if not site:
        raise HTTPException(404, f"Website '{site_id}' không tồn tại.")
    return {"status": "ok", "site": _mask_site(site)}


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
        try_acquire_deploy,
        release_deploy,
    )

    # Validate name
    if not _SITE_NAME_RE.match(req.name):
        raise HTTPException(400, "Tên website chỉ được dùng chữ thường, số và dấu gạch ngang (tối đa 64 ký tự).")

    # Validate github_url: chỉ https github/gitlab, chặn argument-injection (-…) + ext::
    if not _GITHUB_URL_RE.match((req.github_url or "").strip()):
        raise HTTPException(400, "GitHub URL không hợp lệ (chỉ chấp nhận https://github.com/... hoặc gitlab.com/...).")

    # Resolve CF credentials: form fields take priority, then cloud_api store
    cf_api_token = req.cf_api_token.strip()
    cf_account_id = req.cf_account_id.strip()
    cf_email = (req.cf_email or "").strip()

    if not cf_api_token or not cf_account_id or not cf_email:
        try:
            from tubecli.extensions.cloud_api.extension import key_manager
            creds = key_manager.get_cloudflare_creds(req.cf_profile_label or "default")
            if not cf_api_token:
                cf_api_token = creds.get("api_token", "")
            if not cf_account_id:
                cf_account_id = creds.get("account_id", "")
            if not cf_email:
                cf_email = creds.get("email", "")  # Global API Key cần email
        except Exception:
            pass

    if not cf_api_token:
        raise HTTPException(400, "CF API Token là bắt buộc (nhập tực tiếp hoặc lưu trong Cloud Keys → Cloudflare).")
    if not cf_account_id:
        raise HTTPException(400, "CF Account ID là bắt buộc.")

    # Deploy-lock: chặn 2 lần deploy song song cùng một site (nếu không, 2 runner
    # cùng xóa/ghi build/{name} + config_{name}.json phá build của nhau).
    if not try_acquire_deploy(req.name):
        raise HTTPException(409, f"Website '{req.name}' đang được deploy. Vui lòng đợi hoàn tất.")

    # Từ đây tới khi thread nhận trách nhiệm, mọi lỗi PHẢI nhả lock (nếu không
    # site kẹt 409 vĩnh viễn). Thread có finally luôn release_deploy sau khi start.
    try:
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
                cf_email,
            ),
            daemon=True,
        )
        t.start()
    except Exception:
        release_deploy(req.name)
        raise

    return {"status": "ok", "message": f"Deploy '{req.name}' đã bắt đầu.", "site_name": req.name}


@router.post("/sites/{site_name}/cancel")
async def cancel_deploy_route(site_name: str):
    """Hủy một deploy đang chạy: kill cả cây tiến trình node/git/npm/wrangler."""
    if not _SITE_NAME_RE.match(site_name):
        raise HTTPException(400, "Tên site không hợp lệ.")
    from tubecli.extensions.website_manager.extension import cancel_deploy, is_deploying
    if not is_deploying(site_name):
        raise HTTPException(409, f"'{site_name}' không đang deploy.")
    killed = cancel_deploy(site_name)
    return {"status": "ok", "cancelled": killed,
            "message": f"Đã gửi lệnh hủy deploy '{site_name}'." if killed
                       else "Không tìm thấy tiến trình đang chạy (có thể vừa kết thúc)."}


@router.get("/sites/{site_name}/logs")
async def stream_logs(site_name: str, request: Request):
    """SSE endpoint to stream deploy logs in real-time."""
    from tubecli.extensions.website_manager.extension import (
        get_log_file,
        register_log_listener,
        unregister_log_listener,
    )

    # Chống path traversal: {site_name} khớp [^/]+ nhưng trên Windows '\' vẫn là
    # separator → validate cứng trước khi ghép vào đường dẫn file .log.
    if not _SITE_NAME_RE.match(site_name):
        raise HTTPException(400, "Tên site không hợp lệ.")

    log_q: queue.Queue = queue.Queue(maxsize=2000)
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


# Templates withdrawn from the picker. The catalogue is served by
# autoweb.tubecreate.com, which this code cannot edit, so a retired template is
# filtered here instead — in _fetch_templates, so it disappears from BOTH the
# dashboard picker and the agent deploy skill rather than only the UI.
_HIDDEN_TEMPLATE_IDS = {"ngo-quyen"}   # school/government portal, retired

_FALLBACK_TEMPLATES = [
    {"id": "commandcode", "name": "Tech Landing Page",
     "description": "Landing page tiếng Anh phong cách hiện đại tối màu, dành cho SaaS.",
     "thumbnail": "/themes/commandcode.png", "tags": ["Tiếng Anh", "Tech", "SaaS"],
     "color": "#7c3aed", "githubUrl": "https://github.com/tiensyk09/template-commandcode.git"},
    {"id": "korean-news", "name": "Báo điện tử Hàn Quốc",
     "description": "Portal tin tức tiếng Hàn chuyên nghiệp.",
     "thumbnail": "/themes/korean-news.png", "tags": ["Tiếng Hàn", "Tin tức", "Portal"],
     "color": "#c0392b", "githubUrl": "https://github.com/tiensyk09/template-korean-news.git"},
    {"id": "long-chau", "name": "Nhà thuốc Long Châu",
     "description": "Giao diện thương mại điện tử nhà thuốc chuyên nghiệp.",
     "thumbnail": "/themes/long-chau.png", "tags": ["Tiếng Việt", "Dược phẩm", "Bán lẻ"],
     "color": "#005bcd", "githubUrl": "https://github.com/tiensyk09/template-long-chau.git"},
]


def _visible(templates: list) -> list:
    """Drop retired templates (see _HIDDEN_TEMPLATE_IDS)."""
    return [t for t in templates
            if isinstance(t, dict) and t.get("id") not in _HIDDEN_TEMPLATE_IDS]


def _fetch_templates() -> tuple:
    """Trả (list templates, is_fallback). Dùng chung cho GET /templates và skill deploy."""
    import urllib.request
    try:
        req = urllib.request.Request(
            "https://autoweb.tubecreate.com/api/templates",
            headers={"User-Agent": "TubeCLI/1.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            if isinstance(data, list) and data:
                visible = _visible(data)
                # Only treat the remote list as usable if something survived the
                # filter; otherwise fall through to the local list.
                if visible:
                    return visible, False
    except Exception as e:
        logger.error(f"Failed to fetch templates: {e}")
    return _visible(_FALLBACK_TEMPLATES), True


@router.get("/templates")
def list_templates():
    """Fetch and return available themes from autoweb.tubecreate.com API.

    Là `def` (không phải `async def`) để FastAPI chạy trong threadpool — nếu để
    `async def` thì `urllib.urlopen(timeout=10)` blocking sẽ đóng băng toàn bộ
    event loop uvicorn tới 10 giây (mọi SSE + request khác treo theo).
    """
    templates, fallback = _fetch_templates()
    out = {"templates": templates}
    if fallback:
        out["fallback"] = True
    return out


# ── Skill-friendly endpoints (cho agent gọi qua extension_action) ─────
# Trả về {"report": "<text>"} để runner extension_action hiển thị thẳng cho user.

class SkillTextRequest(BaseModel):
    q: str = ""
    request: str = ""
    input: str = ""

    def text(self) -> str:
        return (self.request or self.q or self.input or "").strip()


@router.post("/skill/websites")
async def skill_list_websites(req: SkillTextRequest):
    """Skill 'Quản lý Website': liệt kê site + trạng thái cho agent."""
    mgr = _get_manager()
    sites = mgr.list_websites()
    if not sites:
        return {"report": "📭 Chưa có website nào được quản lý. Dùng skill 'Tạo Website' "
                          "để deploy một site mới từ template."}
    icon = {"active": "✅", "deploying": "⏳", "failed": "❌"}
    lines = [f"📊 Đang quản lý {len(sites)} website:"]
    for s in sites:
        st = s.get("status", "?")
        url = s.get("deploy_url") or "chưa có URL"
        warn = " ⚠️(mật khẩu admin mặc định)" if s.get("deploy_warning") == "admin_default_password" else ""
        lines.append(f"{icon.get(st, '•')} {s.get('name')} — {st} — {url}{warn}")
    return {"report": "\n".join(lines)}


@router.post("/skill/deploy")
async def skill_deploy_website(req: SkillTextRequest):
    """Skill 'Tạo Website': parse yêu cầu (tên + template) → deploy dùng CF profile
    mặc định + mật khẩu admin sinh tự động. Nếu thiếu thông tin → trả hướng dẫn,
    KHÔNG đoán bừa (deploy tốn tài nguyên CF, khó hoàn tác)."""
    import re as _re
    import secrets
    from tubecli.extensions.website_manager.extension import (
        website_manager as mgr, _deploy_site_background, try_acquire_deploy, release_deploy,
    )

    text = req.text()
    templates, _ = _fetch_templates()
    tmpl_by_id = {t.get("id", "").lower(): t for t in templates if t.get("id")}
    tmpl_list_str = ", ".join(sorted(tmpl_by_id.keys())) or "(không tải được danh sách)"

    if not text:
        return {"report": f"Cho tôi biết TÊN site và TEMPLATE để tạo website.\n"
                          f"Ví dụ: \"tạo web coffee-shop template coffee-machine\".\n"
                          f"Template có sẵn: {tmpl_list_str}"}

    low = text.lower()
    # 1) Tìm template id xuất hiện trong yêu cầu
    matched_tmpl = None
    for tid in sorted(tmpl_by_id.keys(), key=len, reverse=True):
        if _re.search(r"(?<!\w)" + _re.escape(tid) + r"(?!\w)", low):
            matched_tmpl = tmpl_by_id[tid]
            break
    if not matched_tmpl:
        return {"report": f"⚠️ Chưa xác định được template. Hãy nêu rõ một trong các "
                          f"template sau trong yêu cầu:\n{tmpl_list_str}\n"
                          f"Ví dụ: \"tạo web coffee-shop template coffee-machine\"."}

    # 2) Tên site: token slug sau 'tên/name' hoặc token slug đầu tiên (bỏ template id + từ khoá)
    stop = {"tạo", "web", "website", "deploy", "dựng", "create", "tên", "name",
            "template", "theme", matched_tmpl.get("id", "").lower()}
    name = ""
    m = _re.search(r"(?:tên|name)\s*[:=]?\s*([a-z0-9][a-z0-9\-]{1,63})", low)
    if m:
        name = m.group(1)
    else:
        for tok in _re.findall(r"[a-z0-9][a-z0-9\-]{1,63}", low):
            if tok not in stop and not tok.isdigit():
                name = tok
                break
    name = _re.sub(r"[^a-z0-9\-]", "", name)[:63].strip("-")
    if not name or not _SITE_NAME_RE.match(name):
        return {"report": f"⚠️ Chưa xác định được TÊN site hợp lệ (chỉ chữ thường/số/gạch ngang).\n"
                          f"Ví dụ: \"tạo web coffee-shop template {matched_tmpl.get('id')}\"."}

    github_url = matched_tmpl.get("githubUrl") or matched_tmpl.get("github_url") or ""
    if not _GITHUB_URL_RE.match(github_url):
        return {"report": f"⚠️ Template '{matched_tmpl.get('id')}' không có GitHub URL hợp lệ."}

    # 3) CF creds mặc định
    try:
        from tubecli.extensions.cloud_api.extension import key_manager
        creds = key_manager.get_cloudflare_creds("default")
    except Exception:
        creds = {}
    cf_api_token = (creds.get("api_token") or "").strip()
    cf_account_id = (creds.get("account_id") or "").strip()
    cf_email = (creds.get("email") or "").strip()
    if not cf_api_token or not cf_account_id:
        return {"report": "⚠️ Chưa cấu hình Cloudflare. Vào giao diện Website Manager → "
                          "'Cloudflare Credentials' để thêm API Token + Account ID trước khi tạo web."}

    if mgr.get_website(name):
        return {"report": f"⚠️ Website '{name}' đã tồn tại. Chọn tên khác hoặc xóa site cũ."}

    # 4) Mật khẩu admin sinh tự động (an toàn)
    admin_password = "wm" + secrets.token_urlsafe(9)

    if not try_acquire_deploy(name):
        return {"report": f"⏳ '{name}' đang được deploy rồi. Xem tiến trình trong giao diện."}
    try:
        mgr.add_website(name=name, template=matched_tmpl.get("id"), status="deploying",
                        cf_api_token=cf_api_token, cf_account_id=cf_account_id,
                        admin_password=admin_password)
        t = threading.Thread(
            target=_deploy_site_background,
            args=(mgr, name, matched_tmpl.get("id"), github_url, cf_api_token,
                  cf_account_id, admin_password, name, cf_email),
            daemon=True,
        )
        t.start()
    except Exception as e:
        release_deploy(name)
        return {"report": f"❌ Không khởi động được deploy: {e}"}

    return {"report": f"🚀 Đã bắt đầu tạo website '{name}' từ template '{matched_tmpl.get('id')}'.\n"
                      f"Theo dõi tiến trình real-time trong giao diện Website Manager (mục Deploy Log).\n"
                      f"🔑 Mật khẩu admin (tự sinh, hãy lưu lại): {admin_password}\n"
                      f"URL dự kiến: https://{name}.workers.dev/admin"}


@router.get("/cloudflare-profiles")
async def get_cloudflare_profiles():
    """Get saved Cloudflare profiles from cloud_api extension (for deploy form auto-fill)."""
    try:
        from tubecli.extensions.cloud_api.extension import key_manager
        profiles = key_manager.list_cloudflare_keys()
        return {"profiles": profiles, "has_profiles": len(profiles) > 0}
    except Exception as e:
        return {"profiles": [], "has_profiles": False, "error": str(e)}
