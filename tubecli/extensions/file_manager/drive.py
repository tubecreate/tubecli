"""Google Drive integration for the File Manager.

Every operation authenticates through Auth Manager tokens (the same store the
Sheets extension uses), so the acting Google account is always one the user
authorized — and every response names that account, because "which Drive did
this land in" is exactly the question that burned the Sheets integration.

googleapiclient is imported lazily inside the handlers: a machine without the
Google client libraries keeps a fully working File Manager and only the Drive
endpoints answer 503.
"""
import io
import os
import logging
import tempfile
import urllib.parse
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger("FileManagerDrive")

router_drive = APIRouter(prefix="/api/v1/file-manager/drive", tags=["File Manager Drive"])

# Google-native documents have no bytes to download; they must be exported.
_EXPORT_FORMATS = {
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"),
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"),
    "application/vnd.google-apps.presentation": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation", ".pptx"),
    "application/vnd.google-apps.drawing": ("image/png", ".png"),
}

_FOLDER_MIME = "application/vnd.google-apps.folder"

MAX_TRANSFER_MB = 512  # hard cap for upload/download payloads through this API


def _am():
    try:
        from tubecli.extensions.auth_manager.extension import auth_manager as am
        return am
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="Auth Manager không khả dụng — không thể xác thực Google Drive.",
        )


def _gapi():
    """Import the Google client lazily so a missing library is a per-endpoint
    503 with instructions, not an extension that fails to load."""
    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload, MediaIoBaseDownload
        from google.oauth2.credentials import Credentials
        return build, MediaFileUpload, MediaIoBaseUpload, MediaIoBaseDownload, Credentials
    except ImportError as e:
        raise HTTPException(
            status_code=503,
            detail=(
                f"Thiếu thư viện Google API ({e}). Cài bằng: "
                f"pip install google-api-python-client google-auth"
            ),
        )


def _drive_tokens(am) -> List[Dict[str, Any]]:
    """Google tokens whose scopes mention drive at all (full, file or readonly)."""
    return [t for t in am.list_tokens("google") if "drive" in " ".join(t.get("scopes", []))]


def _pick_token(cred_id: Optional[str] = None, email: Optional[str] = None):
    """(token_id, email). Priority: explicit cred_id/token_id → email → newest
    still-alive token. Same contract as sheets_api._pick_token — never
    tokens[0], which is the OLDEST token on the machine."""
    from datetime import datetime
    am = _am()
    tokens = _drive_tokens(am)
    if not tokens:
        raise HTTPException(
            status_code=400,
            detail=(
                "Chưa có tài khoản Google nào cấp quyền Drive. "
                "Vào Auth Manager → Authorize với scope 'drive'."
            ),
        )
    if cred_id:
        hit = next((t for t in tokens
                    if t["token_id"] == cred_id or t.get("credential_id") == cred_id), None)
        if hit:
            return hit["token_id"], hit.get("authorized_email", "")
        raise HTTPException(
            status_code=400,
            detail=f"cred_id '{cred_id}' không phải token Google có scope Drive. Kiểm tra Auth Manager.",
        )
    if email:
        hit = next((t for t in tokens
                    if (t.get("authorized_email") or "").lower() == email.lower()), None)
        if hit:
            return hit["token_id"], hit.get("authorized_email", "")

    def _exp(t):
        try:
            return datetime.fromisoformat(t.get("expires_at") or "")
        except Exception:
            return datetime.min

    alive = [t for t in tokens if _exp(t) > datetime.now()]
    best = max(alive or tokens, key=_exp)
    return best["token_id"], best.get("authorized_email", "")


def _get_creds(cred_id: Optional[str] = None, email: Optional[str] = None):
    """Credentials with refresh material when available, so googleapiclient can
    renew mid-operation. Returns (credentials, acting_email)."""
    build, _, _, _, Credentials = _gapi()
    am = _am()
    token_id, acting_email = _pick_token(cred_id, email)
    access_token = am.get_active_token(token_id)
    if not access_token:
        raise HTTPException(
            status_code=401,
            detail="Google token hết hạn và không refresh được. Authorize lại trong Auth Manager.",
        )
    td = am.get_token_data(token_id) or {}
    cd = am.get_credential(td.get("credential_id")) if hasattr(am, "get_credential") else None
    cd = cd or {}
    if td.get("refresh_token") and cd.get("client_id"):
        creds = Credentials(
            token=access_token,
            refresh_token=td.get("refresh_token"),
            client_id=cd.get("client_id"),
            client_secret=cd.get("client_secret"),
            token_uri="https://oauth2.googleapis.com/token",
        )
    else:
        creds = Credentials(token=access_token)
    return creds, acting_email


def _svc(cred_id: Optional[str] = None, email: Optional[str] = None):
    build = _gapi()[0]
    creds, acting_email = _get_creds(cred_id, email)
    # cache_discovery=False: the file-based discovery cache needs oauth2client
    # and only logs a noisy warning without it.
    return build("drive", "v3", credentials=creds, cache_discovery=False), acting_email


def _drive_error(e: Exception, op: str) -> HTTPException:
    msg = str(e)
    if "insufficient" in msg.lower() or "PERMISSION_DENIED" in msg or "403" in msg:
        return HTTPException(
            status_code=403,
            detail=(
                f"Google từ chối thao tác {op}: {msg}\n"
                f"Token này có thể chỉ có quyền đọc (drive.readonly) hoặc thiếu scope 'drive' — "
                f"Authorize lại trong Auth Manager với quyền Google Drive đầy đủ."
            ),
        )
    if "404" in msg or "notFound" in msg:
        return HTTPException(status_code=404, detail=f"Không tìm thấy file/thư mục trên Drive ({op}).")
    return HTTPException(status_code=502, detail=f"Lỗi Google Drive khi {op}: {msg}")


def _file_payload(f: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": f.get("id"),
        "name": f.get("name"),
        "mime_type": f.get("mimeType"),
        "is_folder": f.get("mimeType") == _FOLDER_MIME,
        "size": int(f["size"]) if f.get("size") else None,
        "modified": f.get("modifiedTime"),
        "url": f.get("webViewLink"),
        "icon": f.get("iconLink"),
        "parents": f.get("parents") or [],
    }


_LIST_FIELDS = "nextPageToken, files(id, name, mimeType, size, modifiedTime, webViewLink, iconLink, parents)"


def _escape_q(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


# ── Request models ───────────────────────────────────────────────

class MkdirRequest(BaseModel):
    name: str
    parent_id: Optional[str] = "root"
    cred_id: Optional[str] = None


class UploadPathRequest(BaseModel):
    local_path: str
    folder_id: Optional[str] = "root"
    cred_id: Optional[str] = None
    name: Optional[str] = None


class DownloadRequest(BaseModel):
    file_id: str
    dest_dir: str
    cred_id: Optional[str] = None


class RenameRequest(BaseModel):
    file_id: str
    new_name: str
    cred_id: Optional[str] = None


class ShareRequest(BaseModel):
    file_id: str
    cred_id: Optional[str] = None
    type: Optional[str] = "anyone"        # anyone | user
    role: Optional[str] = "reader"        # reader | writer | commenter
    email: Optional[str] = ""


class TrashRequest(BaseModel):
    file_id: str
    cred_id: Optional[str] = None


# ── Endpoints ────────────────────────────────────────────────────

def _is_readonly(scopes: List[str]) -> bool:
    """True when the token can list but not write.

    Auth Manager stores SHORT scope keys the user picked at authorize time
    ('drive', 'drive_file', 'drive_readonly'), not full OAuth URLs —
    list_tokens returns token['scopes'] as those keys. The raw-URL form is only
    seen for tokens authorized with a literal scope string, so accept both:
    a write capability is the full 'drive' key/URL or 'drive.file'/'drive_file';
    'drive_readonly' alone is read-only.
    """
    joined = " " + " ".join(scopes) + " "
    can_write = (
        " drive " in joined            # short key: full Drive
        or " drive_file " in joined    # short key: per-file write
        or "auth/drive " in joined     # raw URL: full Drive
        or "auth/drive.file" in joined # raw URL: per-file write
    )
    return not can_write


@router_drive.get("/accounts")
async def drive_accounts():
    """Google accounts that authorized a Drive scope, for the account picker."""
    am = _am()
    tokens = _drive_tokens(am)
    return {
        "accounts": [
            {
                "id": t["token_id"],
                "credential_id": t.get("credential_id"),
                "name": t.get("credential_name") or "",
                "email": t.get("authorized_email") or "",
                "scopes": t.get("scopes", []),
                "status": t.get("status") or "",
                "readonly": _is_readonly(t.get("scopes", [])),
            }
            for t in tokens
        ]
    }


@router_drive.get("/list")
async def drive_list(
    folder_id: str = Query("root"),
    cred_id: Optional[str] = Query(None),
    q: Optional[str] = Query(None, description="Search by name, current folder ignored when set"),
    page_token: Optional[str] = Query(None),
    page_size: int = Query(100, ge=1, le=1000),
):
    def work():
        service, acting_email = _svc(cred_id)
        if q:
            query = f"name contains '{_escape_q(q)}' and trashed=false"
        else:
            query = f"'{_escape_q(folder_id or 'root')}' in parents and trashed=false"
        resp = service.files().list(
            q=query,
            fields=_LIST_FIELDS,
            orderBy="folder,name",
            pageSize=page_size,
            pageToken=page_token,
        ).execute()
        # Resolve the folder's own name so the UI breadcrumb can label it.
        folder_name = None
        if not q and folder_id and folder_id != "root":
            try:
                meta = service.files().get(fileId=folder_id, fields="id, name").execute()
                folder_name = meta.get("name")
            except Exception:
                folder_name = None
        return {
            "status": "ok",
            "owner_email": acting_email,
            "folder_id": folder_id or "root",
            "folder_name": folder_name,
            "next_page_token": resp.get("nextPageToken"),
            "files": [_file_payload(f) for f in resp.get("files", [])],
        }

    try:
        return await run_in_threadpool(work)
    except HTTPException:
        raise
    except Exception as e:
        raise _drive_error(e, "liệt kê file")


@router_drive.post("/mkdir")
async def drive_mkdir(req: MkdirRequest):
    name = (req.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Thiếu tên thư mục.")

    def work():
        service, acting_email = _svc(req.cred_id)
        body = {"name": name, "mimeType": _FOLDER_MIME,
                "parents": [req.parent_id or "root"]}
        f = service.files().create(
            body=body, fields="id, name, mimeType, webViewLink, parents"
        ).execute()
        return {"status": "ok", "owner_email": acting_email, "file": _file_payload(f)}

    try:
        return await run_in_threadpool(work)
    except HTTPException:
        raise
    except Exception as e:
        raise _drive_error(e, "tạo thư mục")


@router_drive.post("/upload")
async def drive_upload_path(req: UploadPathRequest):
    """Upload a file that already exists on THIS server's disk.

    Reads stay behind the STRICT sandbox on purpose: the ONLY caller of this
    endpoint is the AI's drive_upload action (extension.py) — the human UI
    uploads browser bytes through /upload-content, which touches no server
    path. If this used the un-fenced user_file_service, a prompt-injected or
    Telegram-driven drive_upload could read any readable file on the box
    (~/.env, tokens, other users' documents) and push it to a Drive account it
    names, then make it public with drive_share. So local_path is validated
    against the same strict file_service the AI's writes use.
    """
    from tubecli.extensions.file_manager.file_service import file_service as strict_svc
    try:
        safe = strict_svc._validate_path(req.local_path)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    if not os.path.isfile(safe):
        raise HTTPException(status_code=404, detail=f"File không tồn tại trên máy chủ: {req.local_path}")
    size = os.path.getsize(safe)
    if size > MAX_TRANSFER_MB * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=f"File {size // (1024 * 1024)}MB vượt giới hạn {MAX_TRANSFER_MB}MB của API này.",
        )

    def work():
        _, MediaFileUpload, _, _, _ = _gapi()
        service, acting_email = _svc(req.cred_id)
        body = {"name": (req.name or os.path.basename(safe)),
                "parents": [req.folder_id or "root"]}
        media = MediaFileUpload(safe, resumable=size > 5 * 1024 * 1024)
        f = service.files().create(
            body=body, media_body=media,
            fields="id, name, mimeType, size, webViewLink, parents",
        ).execute()
        return {"status": "ok", "owner_email": acting_email,
                "local_path": safe, "file": _file_payload(f)}

    try:
        return await run_in_threadpool(work)
    except HTTPException:
        raise
    except Exception as e:
        raise _drive_error(e, "tải file lên")


@router_drive.post("/upload-content")
async def drive_upload_content(
    request: Request,
    name: str = Query(...),
    folder_id: str = Query("root"),
    cred_id: Optional[str] = Query(None),
):
    """Upload from the browser: the raw request body is the file content.

    Deliberately not multipart — python-multipart is not a dependency of this
    server, and a raw body with the filename in the query string needs nothing.
    """
    fname = os.path.basename((name or "").strip())
    if not fname:
        raise HTTPException(status_code=400, detail="Thiếu tên file (query 'name').")
    length = request.headers.get("content-length")
    if length and int(length) > MAX_TRANSFER_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File vượt giới hạn {MAX_TRANSFER_MB}MB.")
    data = await request.body()
    if not data:
        raise HTTPException(status_code=400, detail="Nội dung file rỗng.")
    if len(data) > MAX_TRANSFER_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File vượt giới hạn {MAX_TRANSFER_MB}MB.")
    content_type = request.headers.get("x-file-type") or "application/octet-stream"

    def work():
        _, _, MediaIoBaseUpload, _, _ = _gapi()
        service, acting_email = _svc(cred_id)
        media = MediaIoBaseUpload(io.BytesIO(data), mimetype=content_type,
                                  resumable=len(data) > 5 * 1024 * 1024)
        f = service.files().create(
            body={"name": fname, "parents": [folder_id or "root"]},
            media_body=media,
            fields="id, name, mimeType, size, webViewLink, parents",
        ).execute()
        return {"status": "ok", "owner_email": acting_email, "file": _file_payload(f)}

    try:
        return await run_in_threadpool(work)
    except HTTPException:
        raise
    except Exception as e:
        raise _drive_error(e, "tải file lên")


def _download_to_spool(service, file_id: str):
    """Fetch Drive content into a spooled temp file. Returns (spool, name, mime)."""
    _, _, _, MediaIoBaseDownload, _ = _gapi()
    meta = service.files().get(fileId=file_id, fields="id, name, mimeType, size").execute()
    name = meta.get("name") or file_id
    mime = meta.get("mimeType") or "application/octet-stream"
    if meta.get("size") and int(meta["size"]) > MAX_TRANSFER_MB * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=f"File {int(meta['size']) // (1024 * 1024)}MB vượt giới hạn {MAX_TRANSFER_MB}MB của API này.",
        )
    if mime in _EXPORT_FORMATS:
        export_mime, ext = _EXPORT_FORMATS[mime]
        request = service.files().export_media(fileId=file_id, mimeType=export_mime)
        if not name.lower().endswith(ext):
            name += ext
        mime = export_mime
    elif mime.startswith("application/vnd.google-apps"):
        raise HTTPException(
            status_code=400,
            detail=f"Loại file Google '{mime}' không tải về được dưới dạng dữ liệu.",
        )
    else:
        request = service.files().get_media(fileId=file_id)

    spool = tempfile.SpooledTemporaryFile(max_size=50 * 1024 * 1024)
    downloader = MediaIoBaseDownload(spool, request, chunksize=8 * 1024 * 1024)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    spool.seek(0)
    return spool, name, mime


@router_drive.get("/fetch")
async def drive_fetch(file_id: str = Query(...), cred_id: Optional[str] = Query(None)):
    """Stream a Drive file to the BROWSER as a download."""
    def work():
        service, _ = _svc(cred_id)
        return _download_to_spool(service, file_id)

    try:
        spool, name, mime = await run_in_threadpool(work)
    except HTTPException:
        raise
    except Exception as e:
        raise _drive_error(e, "tải file về")

    quoted = urllib.parse.quote(name)
    fallback = name.encode("ascii", "replace").decode("ascii").replace('"', "_")

    def iterfile():
        try:
            while True:
                chunk = spool.read(1024 * 256)
                if not chunk:
                    break
                yield chunk
        finally:
            spool.close()

    return StreamingResponse(
        iterfile(),
        media_type=mime,
        headers={
            "Content-Disposition": f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quoted}",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router_drive.post("/download")
async def drive_download_to_server(req: DownloadRequest):
    """Save a Drive file onto THIS server's disk.

    Writes stay behind the STRICT sandbox on purpose: this route is the one the
    AI's drive_download action calls, and a server-side write is the same risk
    whoever clicks the button. Humans who want the file on their own machine
    use /fetch, which touches no server path at all.
    """
    from tubecli.extensions.file_manager.file_service import file_service as strict_svc
    try:
        safe_dir = strict_svc._validate_path(req.dest_dir)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))

    def work():
        service, acting_email = _svc(req.cred_id)
        spool, name, mime = _download_to_spool(service, req.file_id)
        try:
            os.makedirs(safe_dir, exist_ok=True)
            dest = os.path.join(safe_dir, os.path.basename(name))
            with open(dest, "wb") as f:
                while True:
                    chunk = spool.read(1024 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
        finally:
            spool.close()
        return {
            "status": "ok", "owner_email": acting_email, "path": dest,
            "name": os.path.basename(dest), "mime_type": mime,
            "size": os.path.getsize(dest),
        }

    try:
        return await run_in_threadpool(work)
    except HTTPException:
        raise
    except Exception as e:
        raise _drive_error(e, "tải file về máy chủ")


@router_drive.post("/rename")
async def drive_rename(req: RenameRequest):
    new_name = (req.new_name or "").strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="Thiếu tên mới.")

    def work():
        service, acting_email = _svc(req.cred_id)
        f = service.files().update(
            fileId=req.file_id, body={"name": new_name},
            fields="id, name, mimeType, webViewLink, parents",
        ).execute()
        return {"status": "ok", "owner_email": acting_email, "file": _file_payload(f)}

    try:
        return await run_in_threadpool(work)
    except HTTPException:
        raise
    except Exception as e:
        raise _drive_error(e, "đổi tên")


@router_drive.post("/share")
async def drive_share(req: ShareRequest):
    perm_type = (req.type or "anyone").strip().lower()
    role = (req.role or "reader").strip().lower()
    if perm_type not in ("anyone", "user"):
        raise HTTPException(status_code=400, detail="'type' phải là 'anyone' hoặc 'user'.")
    if role not in ("reader", "writer", "commenter"):
        raise HTTPException(status_code=400, detail="'role' phải là reader/writer/commenter.")
    if perm_type == "user" and not (req.email or "").strip():
        raise HTTPException(status_code=400, detail="Chia sẻ theo 'user' cần 'email'.")

    def work():
        service, acting_email = _svc(req.cred_id)
        body = {"type": perm_type, "role": role}
        if perm_type == "user":
            body["emailAddress"] = req.email.strip()
        service.permissions().create(
            fileId=req.file_id, body=body,
            sendNotificationEmail=(perm_type == "user"),
        ).execute()
        meta = service.files().get(fileId=req.file_id, fields="id, name, webViewLink").execute()
        return {
            "status": "ok", "owner_email": acting_email,
            "file": {"id": meta.get("id"), "name": meta.get("name"), "url": meta.get("webViewLink")},
            "shared_with": req.email.strip() if perm_type == "user" else "anyone-with-link",
            "role": role,
        }

    try:
        return await run_in_threadpool(work)
    except HTTPException:
        raise
    except Exception as e:
        raise _drive_error(e, "chia sẻ")


@router_drive.post("/trash")
async def drive_trash(req: TrashRequest):
    """Move to Drive trash — recoverable, and therefore the default 'delete'."""
    def work():
        service, acting_email = _svc(req.cred_id)
        f = service.files().update(
            fileId=req.file_id, body={"trashed": True}, fields="id, name",
        ).execute()
        return {"status": "ok", "owner_email": acting_email,
                "file": {"id": f.get("id"), "name": f.get("name")}, "trashed": True}

    try:
        return await run_in_threadpool(work)
    except HTTPException:
        raise
    except Exception as e:
        raise _drive_error(e, "chuyển vào thùng rác")


@router_drive.delete("/delete")
async def drive_delete(file_id: str = Query(...), cred_id: Optional[str] = Query(None)):
    """Permanent delete. The UI's delete button uses /trash; this exists for
    callers that explicitly want no recovery window."""
    def work():
        service, acting_email = _svc(cred_id)
        service.files().delete(fileId=file_id).execute()
        return {"status": "ok", "owner_email": acting_email, "deleted": file_id}

    try:
        return await run_in_threadpool(work)
    except HTTPException:
        raise
    except Exception as e:
        raise _drive_error(e, "xóa vĩnh viễn")
