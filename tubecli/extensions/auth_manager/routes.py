"""
Auth Manager Extension — FastAPI routes.
OAuth callback uses the same API port (no separate server).
"""
import asyncio
import re
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Any, Optional, List

router = APIRouter(prefix="/api/v1/auth-manager", tags=["auth-manager"])


class AddCredentialRequest(BaseModel):
    provider: str
    name: str
    client_id: str = ""
    client_secret: str = ""
    credentials_json: str = ""
    service_account_email: str = ""
    scopes: List[str] = []


class AddManualTokenRequest(BaseModel):
    provider: str
    name: str
    identifier: str
    access_token: str


class UpdateCredentialRequest(BaseModel):
    name: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    credentials_json: Optional[str] = None
    service_account_email: Optional[str] = None
    scopes: Optional[List[str]] = None


class AuthorizeRequest(BaseModel):
    scopes: List[str]
    browser_profile: str = ""


# ── Providers ────────────────────────────────────────────────────

@router.get("/providers")
async def api_list_providers():
    """List all supported OAuth providers."""
    from .extension import auth_manager
    return {"providers": auth_manager.list_providers()}


# ── Credentials CRUD ─────────────────────────────────────────────

@router.get("/credentials")
async def api_list_credentials(provider: Optional[str] = None):
    """List all stored credentials (masked)."""
    from .extension import auth_manager
    return {"credentials": auth_manager.list_credentials(provider)}


@router.post("/credentials")
async def api_add_credential(req: AddCredentialRequest):
    """Add a new OAuth credential."""
    from .extension import auth_manager
    result = auth_manager.add_credential(
        provider=req.provider,
        name=req.name,
        client_id=req.client_id,
        client_secret=req.client_secret,
        credentials_json=req.credentials_json,
        service_account_email=req.service_account_email,
        scopes=req.scopes,
    )
    if result["status"] == "error":
        raise HTTPException(400, result["message"])
    return result


@router.post("/credentials/manual")
async def api_add_manual_token(req: AddManualTokenRequest):
    """Add a manual long-lived token directly (e.g. FB Page Token)."""
    from .extension import auth_manager
    result = auth_manager.add_manual_token(
        provider=req.provider,
        name=req.name,
        identifier=req.identifier,
        access_token=req.access_token,
    )
    if result.get("status") == "error":
        raise HTTPException(400, result.get("message", "Error"))
    return result


@router.put("/credentials/{cred_id}")
async def api_update_credential(cred_id: str, req: UpdateCredentialRequest):
    """Update an existing credential."""
    from .extension import auth_manager
    data = req.model_dump(exclude_none=True)
    result = auth_manager.update_credential(cred_id, **data)
    if result["status"] == "error":
        raise HTTPException(404, result["message"])
    return result


@router.delete("/credentials/{cred_id}")
async def api_delete_credential(cred_id: str):
    """Delete a credential and its token."""
    from .extension import auth_manager
    result = auth_manager.remove_credential(cred_id)
    if result["status"] == "error":
        raise HTTPException(404, result["message"])
    return result


# ── OAuth Flow ───────────────────────────────────────────────────

@router.post("/credentials/{cred_id}/authorize")
async def api_authorize(cred_id: str, req: AuthorizeRequest, request: Request):
    """Start OAuth flow — build URL and optionally launch browser profile."""
    from .extension import auth_manager

    # Determine callback base URL from request
    scheme = request.url.scheme
    host = request.headers.get("host", "localhost:2516")
    callback_base = f"{scheme}://{host}"

    result = auth_manager.build_oauth_url(
        cred_id=cred_id,
        scopes=req.scopes,
        browser_profile=req.browser_profile,
        callback_base=callback_base,
    )

    if result["status"] == "error":
        raise HTTPException(400, result["message"])

    # If browser_profile is specified, launch via browser process manager
    if req.browser_profile:
        try:
            from tubecli.extensions.browser.process_manager import browser_process_manager
            launch_result = browser_process_manager.spawn(
                profile=req.browser_profile,
                url=result["auth_url"],
                manual=True,
            )
            result["browser_launch"] = launch_result
            print(f"🌐 Browser profile '{req.browser_profile}' launch result: {launch_result}")
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"❌ Failed to launch browser profile '{req.browser_profile}': {e}")
            result["browser_launch"] = {"status": "error", "error": str(e)}
    # No else — let the frontend handle opening via window.open() / redirect

    return result


@router.get("/oauth/callback")
async def api_oauth_callback(code: str = "", state: str = "", error: str = ""):
    """OAuth callback — exchange code for token. Returns HTML success/error page."""
    if error:
        return HTMLResponse(content=_callback_html("error", f"Authorization denied: {error}"), status_code=400)

    if not code or not state:
        return HTMLResponse(content=_callback_html("error", "Missing code or state parameter."), status_code=400)

    from .extension import auth_manager
    result = auth_manager.handle_oauth_callback(code, state)

    if result["status"] == "error":
        return HTMLResponse(content=_callback_html("error", result["message"]), status_code=400)

    return HTMLResponse(content=_callback_html(
        "success",
        result.get("message", "Authorization successful!"),
        email=result.get("authorized_email", ""),
        profile=result.get("browser_profile", ""),
    ))


# ── Tokens ───────────────────────────────────────────────────────

@router.get("/tokens")
async def api_list_tokens(provider: Optional[str] = None):
    """List all authorized tokens."""
    from .extension import auth_manager
    return {"tokens": auth_manager.list_tokens(provider)}


@router.post("/tokens/{token_id}/refresh")
async def api_refresh_token(token_id: str):
    """Refresh an expired token."""
    from .extension import auth_manager
    result = auth_manager.refresh_token(token_id)
    if result["status"] == "error":
        raise HTTPException(400, result["message"])
    return result


@router.delete("/tokens/{token_id}")
async def api_revoke_token(token_id: str):
    """Revoke a token."""
    from .extension import auth_manager
    result = auth_manager.revoke_token(token_id)
    if result["status"] == "error":
        raise HTTPException(404, result["message"])
    return result


@router.get("/tokens/{cred_id}/active")
async def api_get_active_token(cred_id: str):
    """Get active access token (for internal use by other extensions)."""
    from .extension import auth_manager
    token = auth_manager.get_active_token(cred_id)
    if not token:
        raise HTTPException(404, f"No active token for credential '{cred_id}'")
    masked = token[:10] + "..." + token[-4:] if len(token) > 14 else "***"
    return {"credential_id": cred_id, "has_token": True, "masked_token": masked}


@router.get("/tokens/{cred_id}/access-token")
async def api_get_access_token_full(cred_id: str):
    """Return the REAL active access token (auto-refresh nếu hết hạn).

    Cùng cổng xác thực session như mọi endpoint khác — ai có mật khẩu TubeCLI
    vốn đã có terminal và đọc được token in-process. Endpoint này phục vụ
    "AI Guide phương án B" (người dùng chủ động chọn, đã được cảnh báo rủi ro):
    cho AI bên ngoài (ChatGPT/Claude...) tự lấy token mới từ xa sau khi login.
    """
    from .extension import auth_manager
    token = auth_manager.get_active_token(cred_id)
    if not token:
        raise HTTPException(404, f"No active token for credential '{cred_id}'")
    data = auth_manager.get_token_data(cred_id) or {}
    return {
        "credential_id": cred_id,
        "access_token": token,
        "expires_at": data.get("expires_at", ""),
        "scopes": data.get("scopes", []),
    }


# ── Google Sheets (group-context Sheet node) ─────────────────────
# Thin HTTP face over gsheets.py so the cloud Sheet node can inspect / preview a
# spreadsheet with the owner's token while the browser never holds that token.
# Owner-only like the rest of this router (the guest gate denies by default).

_SHEET_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


class GSheetsAppendRequest(BaseModel):
    cred_id: str
    tab: str = ""
    rows: List[Any] = []


def _gsheets_http_status(err) -> int:
    # Collapse Google's vocabulary into what the node distinguishes: bad request,
    # no access, not found, or "Google is unhappy" (429 / 5xx / unreachable).
    if err.status == 400:
        return 400
    if err.status in (401, 403):
        return 403
    if err.status == 404:
        return 404
    return 502


def _check_sheet_id(sheet_id: str) -> str:
    if not _SHEET_ID_RE.match(sheet_id or ""):
        raise HTTPException(400, "Invalid spreadsheet id")
    return sheet_id


@router.get("/gsheets/inspect")
async def api_gsheets_inspect(cred_id: str = "", url: str = ""):
    """Title + tabs of a spreadsheet given its URL (or bare id) and a credential."""
    from . import gsheets
    sheet_id = gsheets.parse_sheet_id(url)
    if not sheet_id:
        raise HTTPException(400, "Invalid Google Sheets URL or id")
    if not cred_id:
        raise HTTPException(400, "cred_id is required")
    try:
        return await asyncio.to_thread(gsheets.inspect, cred_id, sheet_id)
    except gsheets.GSheetsError as e:
        raise HTTPException(_gsheets_http_status(e), e.message)


@router.get("/gsheets/{sheet_id}/values")
async def api_gsheets_values(sheet_id: str, cred_id: str = "", tab: str = "",
                             range_: str = Query("", alias="range"),
                             max_rows: int = 200, tail: int = 0):
    """Rows of a tab (first `max_rows`, or the last `tail` rows when tail > 0)."""
    from . import gsheets
    _check_sheet_id(sheet_id)
    if not cred_id:
        raise HTTPException(400, "cred_id is required")
    max_rows = max(1, min(int(max_rows or 200), 1000))
    tail = max(0, min(int(tail or 0), 1000))
    try:
        return await asyncio.to_thread(gsheets.read, cred_id, sheet_id, tab, range_ or None, max_rows, tail)
    except gsheets.GSheetsError as e:
        raise HTTPException(_gsheets_http_status(e), e.message)


@router.post("/gsheets/{sheet_id}/append")
async def api_gsheets_append(sheet_id: str, req: GSheetsAppendRequest):
    """Append rows after the last filled row of a tab."""
    from . import gsheets
    _check_sheet_id(sheet_id)
    if not req.cred_id:
        raise HTTPException(400, "cred_id is required")
    try:
        res = await asyncio.to_thread(gsheets.append, req.cred_id, sheet_id, req.tab, req.rows)
    except gsheets.GSheetsError as e:
        raise HTTPException(_gsheets_http_status(e), e.message)
    return {"updated_range": res["updated_range"], "updated_rows": res["updated_rows"], "tab": res["tab"]}


# ── Callback HTML Template ───────────────────────────────────────

def _callback_html(status: str, message: str, email: str = "", profile: str = "") -> str:
    """Generate HTML for OAuth callback result page."""
    is_success = status == "success"
    icon = "✅" if is_success else "❌"
    color = "#10b981" if is_success else "#ef4444"
    bg_color = "#0f1419"
    extra = ""
    if email:
        extra += f'<div style="margin-top:12px;padding:10px;background:#1e293b;border-radius:8px;font-size:0.9rem">📧 {email}</div>'
    if profile:
        extra += f'<div style="margin-top:8px;padding:10px;background:#1e293b;border-radius:8px;font-size:0.9rem">🌐 Profile: {profile}</div>'

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>OAuth {status.title()}</title></head>
<body style="margin:0;display:flex;align-items:center;justify-content:center;min-height:100vh;
background:{bg_color};font-family:Inter,system-ui,sans-serif;color:#e2e8f0">
<div style="text-align:center;padding:40px;background:#1a2332;border-radius:16px;
border:1px solid {color}40;max-width:420px;box-shadow:0 20px 60px rgba(0,0,0,.4)">
<div style="font-size:3rem;margin-bottom:16px">{icon}</div>
<h2 style="color:{color};margin:0 0 12px">{status.title()}</h2>
<p style="color:#94a3b8;line-height:1.6;margin:0">{message}</p>
{extra}
<p style="margin-top:20px;font-size:0.8rem;color:#475569">You can close this tab now.</p>
</div>
</body>
</html>"""
