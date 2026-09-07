"""
File Manager API Routes — REST API for file/folder operations.

TWO PREFIXES, ONE IMPLEMENTATION
--------------------------------
`static/file_manager.js` line 18 hardcodes ``/api/v1/files`` while the disk /
cleanup / permissions contract specifies ``/api/v1/file-manager``. Renaming the
old prefix would 404 the shipped page against a server that reports itself
healthy, so both are served: the shared CRUD endpoints are declared once on
``_shared`` and mounted under each prefix, and the two routers are exported as a
list (``tubecli/core/extension_manager.py`` line 641 accepts a list of routers).

``/info`` is the one endpoint that genuinely differs between the prefixes and is
therefore declared twice — see the two handlers at the bottom for why.

BACKEND MODULES
---------------
The disk / cleanup / permissions features live in sibling modules and are
imported lazily, never at module scope. A module-scope import of a file that is
missing or that raises on an unsupported platform would take down every
file-manager endpoint, not just the new ones — this extension has shipped that
class of bug before (``import pwd`` on Windows). Lazy import turns it into a 503
on the affected endpoint alone, naming the module that failed.

Expected public surface (first name found wins; the aliases exist only so a
rename does not silently 404 a feature):

  disk_usage.list_volumes()                     -> {"volumes": [...]} | [...]
  disk_usage.start_scan(path)                   -> "<scan_id>" | {"scan_id": ...}
  disk_usage.get_scan(scan_id)                  -> {"status": ..., ...} | None
  disk_usage.cancel_scan(scan_id)               -> {"status": "cancelled"} | None

  cleanup.scan_categories(path, service)        -> {"categories": [...]} | [...]
  cleanup.apply_cleanup(path, category_ids, dry_run, scan_id=None)
                                                -> {"dry_run", "deleted", "freed", "failed"}

  permissions.get_permissions(path)             -> contract payload
  permissions.set_permissions(path, recursive, posix_mode, windows)
                                                -> {"status", "applied", "message", "failed"}

Platform policy (POSIX mode vs Windows ACL, and the refusal to add a Windows
DENY ace that can lock a user out of their own directory unrecoverably) belongs
to ``permissions.py``. It is deliberately NOT duplicated here: two copies of one
safety rule drift, and the copy that drifts is the one that stops refusing.
"""
import importlib
import inspect
import logging
import os
import re
import stat
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request, UploadFile, File, Form, Body
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from starlette.responses import FileResponse

logger = logging.getLogger("FileManagerRoutes")

# Shared CRUD endpoints, declared once and mounted under both prefixes. The two
# include_router() calls are at the BOTTOM of this file, not here: include_router
# copies the routes that exist at the moment it runs, so calling it before the
# @_shared decorators have executed mounts an empty router and every CRUD
# endpoint 404s against a server that starts up reporting no errors.
_shared = APIRouter()

# The prefix the shipped UI calls.
router_legacy = APIRouter(prefix="/api/v1/files", tags=["File Manager"])

# The prefix the disk / cleanup / permissions contract specifies.
router_fm = APIRouter(prefix="/api/v1/file-manager", tags=["File Manager"])

# extension.py does `from ...routes import router`; the manager unwraps a list.
router = [router_legacy, router_fm]

# Google Drive integration lives in its own module; googleapiclient is imported
# lazily inside its handlers, so this import only fails on a genuinely broken
# drive.py — in which case the rest of the File Manager must keep working.
try:
    from tubecli.extensions.file_manager.drive import router_drive
    router.append(router_drive)
except Exception as _drive_err:  # pragma: no cover
    logger.warning("Google Drive routes unavailable: %s", _drive_err)

# Backend kwargs that may be omitted when the callee does not declare them.
# Everything else is mandatory: silently dropping `dry_run` would turn a preview
# into a real deletion, which is exactly the failure this file must not allow.
_OPTIONAL_BACKEND_KWARGS = frozenset({"scan_id"})

_OCTAL_MODE_RE = re.compile(r"^(0o|0)?[0-7]{3,4}$")


def _get_service():
    """The service behind every UI endpoint in this file.

    user_file_service skips the allowed-roots fence (a logged-in human browsing
    their own machine) but keeps BLOCKED_PATHS. The AI keeps using the strict
    `file_service` singleton — that import lives in brain.py and the nodes, not
    here. Falls back to the sandboxed one if the split is not present (older
    file_service.py), so the UI degrades to the previous behaviour rather than
    crashing.
    """
    try:
        from tubecli.extensions.file_manager.file_service import user_file_service
        return user_file_service
    except ImportError:
        from tubecli.extensions.file_manager.file_service import file_service
        return file_service


# ── Backend module plumbing ──────────────────────────────────────

def _resolve(module_name: str, *names: str):
    """Import a sibling backend module and return its first matching callable.

    Every failure is reported with the module path and the names that were
    tried, because "feature unavailable" with no reason is indistinguishable
    from "feature broken" for whoever has to fix it.
    """
    full = f"tubecli.extensions.file_manager.{module_name}"
    try:
        module = importlib.import_module(full)
    except ImportError as e:
        logger.error("Backend module %s could not be imported: %s", full, e)
        raise HTTPException(
            status_code=503,
            detail=(
                f"Chức năng này cần module {module_name}.py nhưng không nạp được: {e}\n"
                f"Kiểm tra file {full.replace('.', '/')}.py và các thư viện nó cần."
            ),
        )
    except Exception as e:  # a module that raises at import time, e.g. a bad platform guard
        logger.exception("Backend module %s raised while importing", full)
        raise HTTPException(
            status_code=503,
            detail=(
                f"Module {module_name}.py lỗi khi nạp ({type(e).__name__}: {e}).\n"
                f"Các chức năng file khác vẫn hoạt động bình thường."
            ),
        )

    for name in names:
        fn = getattr(module, name, None)
        if callable(fn):
            return fn

    logger.error("Backend module %s exposes none of %s", full, names)
    raise HTTPException(
        status_code=503,
        detail=(
            f"Module {module_name}.py không cung cấp hàm nào trong: {', '.join(names)}.\n"
            f"Đây là lỗi lập trình, không phải lỗi dữ liệu của bạn."
        ),
    )


def _accepts(fn, name: str) -> bool:
    """Does `fn` declare a parameter called `name` (or **kwargs)?"""
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        # C callables and some wrappers refuse introspection. Treat that as "no"
        # so an optional extra is never forced onto a callee that may reject it.
        return False
    for p in sig.parameters.values():
        if p.kind is p.VAR_KEYWORD:
            return True
        if p.name == name and p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY):
            return True
    return False


async def _call(fn, module_name: str, fn_name: str, **kwargs) -> Any:
    """Invoke a backend callable off the event loop, with a signature pre-check.

    Two things this buys. (1) Binding the arguments BEFORE the call means a
    signature mismatch is reported as a 503 naming the real signature, while a
    TypeError raised inside the function still propagates as a genuine bug
    instead of being mislabelled. (2) Cleanup and usage scans are minutes-long
    blocking walks (measured: 227 files/s cold); running them inline in an
    `async def` handler would freeze every other request on the server, so
    synchronous backends are pushed to the threadpool.
    """
    dropped = []
    for key in list(kwargs):
        if key in _OPTIONAL_BACKEND_KWARGS and not _accepts(fn, key):
            dropped.append(key)
            kwargs.pop(key)
    if dropped:
        logger.info("%s.%s does not accept %s — omitted", module_name, fn_name, dropped)

    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        sig = None
    if sig is not None:
        try:
            sig.bind(**kwargs)
        except TypeError as e:
            logger.error("Signature mismatch calling %s.%s%s", module_name, fn_name, sig)
            raise HTTPException(
                status_code=503,
                detail=(
                    f"{module_name}.{fn_name}{sig} không nhận đúng tham số mà API gửi "
                    f"({', '.join(sorted(kwargs))}): {e}\n"
                    f"Đây là lỗi lập trình giữa routes.py và {module_name}.py."
                ),
            )

    if inspect.iscoroutinefunction(fn) or inspect.iscoroutinefunction(
        getattr(fn, "__call__", None)
    ):
        return await fn(**kwargs)
    return await run_in_threadpool(lambda: fn(**kwargs))


def _envelope(result: Any, key: str) -> Dict[str, Any]:
    """Accept either the bare payload or the already-wrapped envelope.

    A backend returning a bare list where the contract wants {"key": [...]}
    would otherwise be double-wrapped into {"key": {"key": [...]}}, which the
    UI renders as an empty result — a wrong answer shown as a successful one.
    """
    if isinstance(result, dict) and key in result:
        return result
    return {key: result}


def _model_dump(model: Optional[BaseModel]) -> Optional[Dict[str, Any]]:
    """Pydantic v2 renamed .dict() to .model_dump(); support whichever is present."""
    if model is None:
        return None
    dump = getattr(model, "model_dump", None) or getattr(model, "dict")
    return dump()


# ── Path validation shared by every new endpoint ─────────────────

def _validate(svc, path: str) -> str:
    """Run a caller-supplied path through the sandbox before anything touches it.

    _validate_path is the extension's single chokepoint for "may this path be
    read or written at all"; it is private but there is no public equivalent,
    and bypassing it is how a cleanup endpoint ends up deleting outside the
    allowed roots. Its ValueError carries the allowed roots, so it is surfaced
    verbatim rather than replaced with a generic refusal.
    """
    if not path or not path.strip():
        raise HTTPException(status_code=400, detail="Thiếu tham số 'path'.")
    try:
        return svc._validate_path(path)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except OSError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Không đọc được đường dẫn '{path}': {e.strerror or e}",
        )


def _require_exists(safe_path: str, original: str) -> None:
    """404 with the actual reason. _validate_path never checks existence."""
    if os.path.exists(safe_path):
        return
    if os.path.lexists(safe_path):
        raise HTTPException(
            status_code=404,
            detail=f"Liên kết bị hỏng, đích không còn tồn tại: {original}",
        )
    raise HTTPException(status_code=404, detail=f"Đường dẫn không tồn tại: {original}")


def _require_dir(safe_path: str, original: str) -> None:
    if not os.path.isdir(safe_path):
        raise HTTPException(
            status_code=400,
            detail=f"Đường dẫn phải là một thư mục, đây là file: {original}",
        )


def _fail(where: str, path: str, e: Exception) -> HTTPException:
    """Map a backend exception to a specific status and a message that says why.

    The catch-all is still a 500 — an unexpected bug must not be dressed up as a
    user error — but it names the operation, the path and the exception type so
    the failure is actionable rather than an opaque stack trace string.
    """
    if isinstance(e, HTTPException):
        return e
    if isinstance(e, FileNotFoundError):
        return HTTPException(status_code=404, detail=f"Không tìm thấy: {e}")
    if isinstance(e, PermissionError):
        return HTTPException(
            status_code=403,
            detail=f"Không đủ quyền truy cập '{path}': {e.strerror or e}",
        )
    if isinstance(e, NotImplementedError):
        return HTTPException(
            status_code=501,
            detail=f"{where} không được hỗ trợ trên hệ điều hành này: {e}",
        )
    if isinstance(e, ValueError):
        return HTTPException(status_code=400, detail=str(e))
    if isinstance(e, OSError):
        # winerror is Windows-only; errno exists everywhere. Report whichever is
        # present so "being used by another process" reaches the user as itself.
        code = getattr(e, "winerror", None) or e.errno
        return HTTPException(
            status_code=400,
            detail=f"Lỗi hệ thống tệp khi {where} '{path}' (mã {code}): {e.strerror or e}",
        )
    logger.exception("%s failed for %s", where, path)
    return HTTPException(
        status_code=500,
        detail=f"Lỗi không lường trước khi {where} '{path}': {type(e).__name__}: {e}",
    )


# ── Media preview: the only endpoint here that serves raw bytes ──
#
# A CLOSED ALLOWLIST, not a guess. mimetypes.guess_type is deliberately not
# used: api/server.py:12-19 registers image/svg+xml and application/javascript
# at import time, and ~/Downloads is an allowed root (file_service.py:14-18), so
# guessing would let a file the user downloaded from anywhere be served as an
# executable document FROM THE DASHBOARD'S OWN ORIGIN. Script running there is
# unauthenticated admin: the API has no auth, and POST
# /api/v1/extensions/install runs git clone + pip install.
#
# .svg is absent on purpose. Inside <img> it cannot script — but the moment this
# table holds one scriptable type, the invariant "this endpoint cannot emit a
# document" is gone, and whoever later adds an <object> or a new-tab link
# reopens the hole. An SVG keeps showing its icon, like any other non-media file.
_MEDIA_TYPES = {
    # Raster images -> <img>
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
    ".ico": "image/x-icon", ".avif": "image/avif",
    # Video -> <video>. Only containers a browser can actually demux. .mkv,
    # .avi, .flv, .wmv and .ts are left out because no engine plays them, and a
    # preview that always fails is worse than the icon the user already has.
    ".mp4": "video/mp4", ".m4v": "video/mp4", ".webm": "video/webm",
    ".ogv": "video/ogg", ".mov": "video/quicktime",
    # Audio -> <audio>
    ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".aac": "audio/aac",
    ".wav": "audio/wav", ".flac": "audio/flac", ".ogg": "audio/ogg",
    ".oga": "audio/ogg", ".opus": "audio/ogg",
    # Document -> <iframe>, drawn by the browser's own viewer
    ".pdf": "application/pdf",
}

_RAW_HEADERS = {
    # The response must never be re-interpreted as a type other than the one
    # chosen from _MEDIA_TYPES above.
    "X-Content-Type-Options": "nosniff",
    # A foreign page's <img>/<video>/<script> sends no Origin header, so the
    # global cross-origin guard lets those through; CORP is what actually stops
    # them, and with them the "does this file exist / how big is it" oracle.
    "Cross-Origin-Resource-Policy": "same-origin",
    # Inert even if a future edit ever lets a document type reach this handler.
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'self'; sandbox",
    "Cache-Control": "private, no-store",
}

# PDF drops the `sandbox` token and nothing else. Firefox draws PDFs with
# pdf.js, which is script-driven, so a sandbox without allow-scripts leaves the
# frame blank. No engine's built-in viewer can reach the embedding page's DOM,
# frame-ancestors still pins the frame to this origin, and nosniff still pins
# the type.
_CSP_PDF = "default-src 'none'; frame-ancestors 'self'"

# Audio and video need `media-src 'self'`, and cannot keep `sandbox`.
#
# Opening a media URL in its own tab makes the browser synthesise a document
# holding a <video>/<audio> whose source is that same URL — so the response's
# own CSP governs whether it may load. Measured in Chrome 150: with
# "default-src 'none'; sandbox" the element sits at readyState 0 with duration
# null and never plays; with this policy it reaches readyState 4. `sandbox` has
# to go with it, because a sandboxed document has an opaque origin and 'self'
# then matches nothing. Neither token was buying anything here — audio and video
# cannot execute script in any engine — while their cost was a dead "open in a
# new tab" link, which is the escape hatch offered when in-page playback fails.
_CSP_MEDIA = "default-src 'none'; media-src 'self'; frame-ancestors 'self'"

# A browser sets Sec-Fetch-Site on every request it makes. Absent means a
# non-browser client (curl, the CLI, Telegram) — the same call the global
# origin guard already makes for a missing Origin header.
_SAFE_FETCH_SITES = frozenset({"same-origin", "none"})


def _require_same_origin_fetch(request: Request) -> None:
    """Refuse browser-initiated cross-site loads of this endpoint.

    The global guard checks Origin — but a browser sends no Origin on a
    navigation, an <img src>, an <iframe src> or a window.open, which is exactly
    the request shape that matters for a handler that returns file bytes.
    Sec-Fetch-Site closes that gap: another site pointing anything at this
    server yields "cross-site" and is refused, while the dashboard's own tags
    and a user-typed URL yield "same-origin"/"none" and pass.
    """
    site = request.headers.get("sec-fetch-site")
    if site is None:
        return
    if site.strip().lower() not in _SAFE_FETCH_SITES:
        raise HTTPException(
            status_code=403,
            detail="Yêu cầu bị từ chối: nội dung này chỉ được mở từ chính trang File Manager.",
        )


def _inline_disposition(name: str) -> str:
    """Advisory filename for the browser's "Save as". Never fatal.

    Header values are latin-1, and on POSIX a filename can hold lone surrogates
    that quote() cannot encode. A name this function cannot represent must cost
    the user a nice download filename, not the preview itself.
    """
    try:
        encoded = quote(name.encode("utf-8", "replace").decode("utf-8"), safe="")
    except Exception:
        return "inline"
    return f"inline; filename*=UTF-8''{encoded}" if encoded else "inline"


# ── Request Models ───────────────────────────────────────────────

class CreateFolderRequest(BaseModel):
    path: str

class CreateFileRequest(BaseModel):
    path: str
    content: str = ""

class MoveRequest(BaseModel):
    src: str
    dst: str

class CopyRequest(BaseModel):
    src: str
    dst: str

class DeleteRequest(BaseModel):
    path: str

class UsageScanRequest(BaseModel):
    path: str

class CleanupApplyRequest(BaseModel):
    path: str
    category_ids: List[str] = []
    # Optional and defaulting to None rather than False: an explicit `null`, a
    # missing field and a malformed field must all mean "preview", never
    # "delete". Resolved to True below.
    dry_run: Optional[bool] = None
    # Additive. The preview and the real run can only be identical if apply
    # consumes the plan the scan already stored instead of re-walking the tree.
    scan_id: Optional[str] = None

class WindowsAclChange(BaseModel):
    identity: str
    rights: str
    action: str

class PermissionsRequest(BaseModel):
    path: str
    recursive: bool = False
    posix_mode: Optional[str] = None
    windows: Optional[WindowsAclChange] = None


# ── Shared CRUD routes (served under both prefixes) ──────────────

# ── Lối tắt thư mục (người dùng ghim) ─────────────────────────────
# Lưu trên MÁY CHỦ (không phải localStorage) để mở từ máy nào cũng thấy cùng
# một danh sách — File Manager mở qua cloud, qua điện thoại, qua node canvas.

def _shortcuts_file() -> str:
    data_dir = os.environ.get("TUBECLI_DATA_DIR", "data")
    try:
        from tubecli.config import DATA_DIR as _dd
        data_dir = str(_dd)
    except Exception:
        pass
    d = os.path.join(os.path.abspath(data_dir), "file_manager")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "shortcuts.json")


def _load_shortcuts() -> List[Dict[str, Any]]:
    import json
    try:
        with open(_shortcuts_file(), encoding="utf-8") as f:
            data = json.load(f)
        items = data.get("shortcuts") if isinstance(data, dict) else data
        out = []
        for it in items or []:
            if isinstance(it, dict) and it.get("path"):
                out.append({"path": str(it["path"]), "name": str(it.get("name") or os.path.basename(str(it["path"])) or it["path"])})
        return out
    except Exception:
        return []


def _save_shortcuts(items: List[Dict[str, Any]]) -> None:
    import json
    p = _shortcuts_file()
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"shortcuts": items}, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


def _shortcuts_view(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{"path": it["path"], "name": it["name"], "exists": os.path.isdir(it["path"])} for it in items]


MAX_SHORTCUTS = 40


@_shared.get("/shortcuts")
async def list_shortcuts():
    """Thư mục đã ghim, kèm cờ còn tồn tại hay không (ghim rồi xoá thư mục là chuyện thường)."""
    return {"success": True, "shortcuts": _shortcuts_view(_load_shortcuts())}


@_shared.post("/shortcuts")
async def add_shortcut(body: Dict[str, Any] = Body(default={})):
    """Ghim một THƯ MỤC. Đường dẫn đi qua đúng chốt kiểm của mọi endpoint khác
    (blocklist), và phải là thư mục có thật — ghim file thì thành nút chết."""
    svc = _get_service()
    raw = str((body or {}).get("path") or "")
    path = _validate(svc, raw)
    if not os.path.isdir(path):
        raise HTTPException(status_code=400, detail="Chỉ ghim được thư mục.")
    name = str((body or {}).get("name") or "").strip() or (os.path.basename(os.path.normpath(path)) or path)
    items = _load_shortcuts()
    key = os.path.normcase(os.path.normpath(path))
    items = [it for it in items if os.path.normcase(os.path.normpath(it["path"])) != key]
    if len(items) >= MAX_SHORTCUTS:
        raise HTTPException(status_code=400, detail=f"Tối đa {MAX_SHORTCUTS} lối tắt.")
    items.append({"path": os.path.normpath(path), "name": name[:80]})
    _save_shortcuts(items)
    return {"success": True, "shortcuts": _shortcuts_view(items)}


@_shared.delete("/shortcuts")
async def remove_shortcut(path: str = Query(...)):
    key = os.path.normcase(os.path.normpath(str(path or "")))
    items = _load_shortcuts()
    kept = [it for it in items if os.path.normcase(os.path.normpath(it["path"])) != key]
    if len(kept) != len(items):
        _save_shortcuts(kept)
    return {"success": True, "shortcuts": _shortcuts_view(kept), "removed": len(kept) != len(items)}


# ── Chia sẻ công khai (link kiểu Google Drive) ────────────────────
# Link `/s/<token>` mở KHÔNG cần đăng nhập (server.py miễn auth tiền tố /s/):
# trang xem trước + nút tải. Token 24 ký tự ngẫu nhiên là thứ duy nhất bảo vệ
# file, nên: chỉ chia sẻ FILE (không thư mục), mọi lần truy cập đều kiểm lại
# hạn dùng + file còn tồn tại, và không bao giờ lộ đường dẫn máy chủ ra trang
# công khai. Thu hồi = xoá bản ghi, link chết ngay.

def _shares_file() -> str:
    return os.path.join(os.path.dirname(_shortcuts_file()), "shares.json")


def _load_shares() -> List[Dict[str, Any]]:
    import json
    try:
        with open(_shares_file(), encoding="utf-8") as f:
            data = json.load(f)
        items = data.get("shares") if isinstance(data, dict) else data
        return [it for it in (items or []) if isinstance(it, dict) and it.get("token") and it.get("path")]
    except Exception:
        return []


def _save_shares(items: List[Dict[str, Any]]) -> None:
    import json
    p = _shares_file()
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"shares": items}, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


def _share_alive(it: Dict[str, Any]) -> bool:
    import time
    exp = it.get("expires")
    if exp and float(exp) < time.time():
        return False
    return os.path.isfile(str(it.get("path") or ""))


def _share_view(it: Dict[str, Any]) -> Dict[str, Any]:
    path = str(it.get("path") or "")
    try:
        size = os.path.getsize(path) if os.path.isfile(path) else 0
    except OSError:
        size = 0
    return {"token": it["token"], "name": it.get("name") or os.path.basename(path), "path": path,
            "url_path": "/s/" + it["token"], "created": it.get("created"), "expires": it.get("expires"),
            "downloads": int(it.get("downloads") or 0), "exists": os.path.isfile(path), "size": size,
            "alive": _share_alive(it)}


def _find_share(token: str) -> Optional[Dict[str, Any]]:
    tok = str(token or "").strip()
    if not tok:
        return None
    for it in _load_shares():
        if it.get("token") == tok:
            return it
    return None


@_shared.post("/share")
async def create_share(body: Dict[str, Any] = Body(default={})):
    """Tạo (hoặc trả lại) link công khai cho một FILE. `expires_days` 0 = không hạn.
    Đã có link cho file này thì trả lại link cũ, trừ khi `renew` = true (link mới,
    link cũ chết)."""
    import secrets
    import time
    svc = _get_service()
    raw = str((body or {}).get("path") or "")
    path = _validate(svc, raw)
    if not os.path.isfile(path):
        raise HTTPException(status_code=400, detail="Chỉ chia sẻ được file (chưa hỗ trợ thư mục).")
    try:
        days = int((body or {}).get("expires_days") or 0)
    except (TypeError, ValueError):
        days = 0
    days = max(0, min(days, 365))
    key = os.path.normcase(os.path.normpath(path))
    items = _load_shares()
    existing = [it for it in items if os.path.normcase(os.path.normpath(it["path"])) == key]
    if existing and not (body or {}).get("renew"):
        return {"success": True, "share": _share_view(existing[0]), "created": False}
    items = [it for it in items if os.path.normcase(os.path.normpath(it["path"])) != key]
    now = time.time()
    it = {"token": secrets.token_urlsafe(18), "path": os.path.normpath(path),
          "name": str((body or {}).get("name") or "").strip()[:120] or os.path.basename(path),
          "created": now, "expires": (now + days * 86400) if days > 0 else None, "downloads": 0}
    items.append(it)
    _save_shares(items)
    return {"success": True, "share": _share_view(it), "created": True}


@_shared.get("/share")
async def get_share(path: str = Query(...)):
    """Link công khai của một file (null nếu chưa chia sẻ)."""
    key = os.path.normcase(os.path.normpath(str(path or "")))
    for it in _load_shares():
        if os.path.normcase(os.path.normpath(it["path"])) == key:
            return {"success": True, "share": _share_view(it)}
    return {"success": True, "share": None}


@_shared.get("/shares")
async def list_shares():
    return {"success": True, "shares": [_share_view(it) for it in _load_shares()]}


@_shared.delete("/share/{token}")
async def revoke_share(token: str):
    items = _load_shares()
    kept = [it for it in items if it.get("token") != token]
    if len(kept) != len(items):
        _save_shares(kept)
    return {"success": True, "removed": len(kept) != len(items)}


# Router KHÔNG tiền tố cho trang công khai — server.py miễn đăng nhập cho /s/.
router_public = APIRouter(tags=["File Manager · public share"])

_SHARE_PAGE_TEXT = {
    "vi": {"title": "Tệp được chia sẻ", "download": "Tải xuống", "open": "Mở tệp", "size": "Kích thước",
           "expires": "Hết hạn", "never": "Không hết hạn", "gone": "Link không tồn tại hoặc đã hết hạn.",
           "by": "Chia sẻ từ TubeCLI"},
    "en": {"title": "Shared file", "download": "Download", "open": "Open file", "size": "Size",
           "expires": "Expires", "never": "Never expires", "gone": "This link does not exist or has expired.",
           "by": "Shared from TubeCLI"},
}


def _share_lang(request: Request) -> str:
    al = (request.headers.get("accept-language") or "").lower()
    return "vi" if al.startswith("vi") else "en"


def _human(n: int) -> str:
    x = float(n or 0)
    for u in ("B", "KB", "MB", "GB"):
        if x < 1024:
            return f"{x:.1f} {u}" if u != "B" else f"{int(x)} {u}"
        x /= 1024
    return f"{x:.1f} TB"


def _share_page(it: Optional[Dict[str, Any]], request: Request) -> str:
    import html as _h
    import time
    L = _SHARE_PAGE_TEXT[_share_lang(request)]
    css = ("body{margin:0;background:#0f1115;color:#e6e8ee;font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}"
           ".wrap{max-width:900px;margin:0 auto;padding:32px 20px}.card{background:#171a21;border:1px solid #262a35;"
           "border-radius:16px;padding:24px}.name{font-size:20px;font-weight:700;word-break:break-all;margin:0 0 6px}"
           ".meta{color:#9aa3b2;font-size:13px;margin-bottom:18px}.prev{background:#0b0d12;border-radius:12px;overflow:hidden;"
           "margin:0 0 18px;text-align:center}.prev img,.prev video{max-width:100%;max-height:70vh;display:block;margin:0 auto}"
           ".prev iframe{width:100%;height:70vh;border:0;background:#fff}.prev audio{width:100%;padding:24px 0}"
           ".btn{display:inline-block;background:#5276eb;color:#fff;text-decoration:none;font-weight:600;padding:12px 22px;"
           "border-radius:10px;margin-right:10px}.btn.q{background:#262a35}.foot{color:#5f6878;font-size:12px;margin-top:22px}"
           ".ico{font-size:56px;padding:40px 0}")
    if it is None or not _share_alive(it):
        return (f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
                f"<meta name='robots' content='noindex'><title>{_h.escape(L['title'])}</title><style>{css}</style></head>"
                f"<body><div class='wrap'><div class='card'><p class='name'>{_h.escape(L['gone'])}</p>"
                f"<p class='foot'>{_h.escape(L['by'])}</p></div></div></body></html>")
    name = _h.escape(it.get("name") or os.path.basename(it["path"]))
    tok = _h.escape(it["token"])
    ext = os.path.splitext(it["path"])[1].lower()
    mt = _MEDIA_TYPES.get(ext) or ""
    raw = f"/s/{tok}/raw"
    if mt.startswith("image/"):
        prev = f"<div class='prev'><img src='{raw}' alt='{name}'></div>"
    elif mt.startswith("video/"):
        prev = f"<div class='prev'><video controls preload='metadata' src='{raw}'></video></div>"
    elif mt.startswith("audio/"):
        prev = f"<div class='prev'><audio controls preload='metadata' src='{raw}'></audio></div>"
    elif mt == "application/pdf":
        prev = f"<div class='prev'><iframe src='{raw}' title='{name}'></iframe></div>"
    else:
        prev = "<div class='prev'><div class='ico'>📄</div></div>"
    exp = it.get("expires")
    exp_s = time.strftime("%Y-%m-%d %H:%M", time.localtime(float(exp))) if exp else L["never"]
    size = _human(os.path.getsize(it["path"]) if os.path.isfile(it["path"]) else 0)
    open_btn = f"<a class='btn q' href='{raw}' target='_blank' rel='noopener'>{_h.escape(L['open'])}</a>" if mt else ""
    return (f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<meta name='robots' content='noindex'><title>{name} — {_h.escape(L['title'])}</title><style>{css}</style></head>"
            f"<body><div class='wrap'><div class='card'><p class='name'>{name}</p>"
            f"<p class='meta'>{_h.escape(L['size'])}: {size} · {_h.escape(L['expires'])}: {_h.escape(exp_s)}</p>{prev}"
            f"<a class='btn' href='/s/{tok}/download'>⬇ {_h.escape(L['download'])}</a>{open_btn}"
            f"<p class='foot'>{_h.escape(L['by'])}</p></div></div></body></html>")


_SHARE_HEADERS = {"Cache-Control": "private, no-store", "X-Robots-Tag": "noindex",
                  "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"}


@router_public.get("/s/{token}")
async def public_share_page(token: str, request: Request):
    from starlette.responses import HTMLResponse
    it = _find_share(token)
    alive = it is not None and _share_alive(it)
    return HTMLResponse(_share_page(it, request), status_code=200 if alive else 404, headers=dict(_SHARE_HEADERS))


def _public_file(it: Dict[str, Any], inline: bool) -> FileResponse:
    resolved = os.path.realpath(it["path"])
    try:
        st = os.stat(resolved)
    except OSError:
        raise HTTPException(status_code=404, detail="File không còn trên máy chủ.")
    if not stat.S_ISREG(st.st_mode):
        raise HTTPException(status_code=404, detail="File không còn trên máy chủ.")
    ext = os.path.splitext(resolved)[1].lower()
    mt = _MEDIA_TYPES.get(ext)
    name = it.get("name") or os.path.basename(resolved)
    headers = {"Cache-Control": "private, max-age=0, must-revalidate", "X-Content-Type-Options": "nosniff",
               "X-Robots-Tag": "noindex", "Cross-Origin-Resource-Policy": "cross-origin"}
    if inline and mt:
        headers["Content-Disposition"] = _inline_disposition(name)
        if mt == "application/pdf":
            headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors *"
        elif mt.startswith(("audio/", "video/")):
            headers["Content-Security-Policy"] = _CSP_MEDIA
        media_type = mt
    else:
        headers["Content-Disposition"] = _inline_disposition(name).replace("inline", "attachment", 1)
        media_type = "application/octet-stream"
    return FileResponse(resolved, media_type=media_type, stat_result=st, headers=headers)


@router_public.api_route("/s/{token}/raw", methods=["GET", "HEAD"])
async def public_share_raw(token: str, request: Request):
    """Xem tại chỗ (ảnh/video/âm thanh/PDF, có Range); định dạng khác thì tải về."""
    it = _find_share(token)
    if it is None or not _share_alive(it):
        raise HTTPException(status_code=404, detail="Link không tồn tại hoặc đã hết hạn.")
    return _public_file(it, inline=True)


@router_public.get("/s/{token}/download")
async def public_share_download(token: str):
    it = _find_share(token)
    if it is None or not _share_alive(it):
        raise HTTPException(status_code=404, detail="Link không tồn tại hoặc đã hết hạn.")
    items = _load_shares()
    for x in items:
        if x.get("token") == it["token"]:
            x["downloads"] = int(x.get("downloads") or 0) + 1
    try:
        _save_shares(items)
    except Exception:
        pass
    return _public_file(it, inline=False)


@_shared.get("/roots")
async def get_roots():
    r"""Get list of allowed root directories, and the server's path separator.

    `sep` exists because the page used to infer the separator by asking whether
    the path it was displaying contained a backslash. That is a legal character
    in a POSIX filename: for a real directory `/home/bob/Downloads/my\folder`
    the UI built `…/my\folder\new`, POSIX os.path.normpath leaves backslashes
    untouched, and create-folder therefore made one directory literally named
    `my\folder\new` inside Downloads instead of `new` inside `my\folder`. The
    server is the only party that knows os.sep for certain, so it says it once
    here — this is the first call the page makes.
    """
    svc = _get_service()
    return {"success": True, "sep": os.sep, "roots": svc.get_allowed_roots()}


def _guest_confine_listing(request, result) -> None:
    """Guest (workspace scoped): BỎ entry symlink trỏ RA NGOÀI folder được chia sẻ.

    _file_info dùng os.stat (follow symlink) nên một symlink trong F trỏ ra ngoài sẽ lộ
    metadata (size/mtime/is_dir/existence) của target — dù nội dung đã bị gate chặn ở
    read/raw. Lọc theo realpath (auth.path_in_folders) để chỉ giữ entry THỰC nằm trong
    phạm vi. Chỉ tác động request GUEST (owner không có guest_scope → no-op). FAIL-CLOSED:
    lỗi lọc → trả listing RỖNG chứ không để rò.
    """
    gscope = getattr(getattr(request, "state", None), "guest_scope", None)
    if not isinstance(gscope, dict):
        return
    try:
        folders = gscope.get("folders") or []
        items = result.get("items") if isinstance(result, dict) else None
        if not (folders and isinstance(items, list)):
            if folders and isinstance(result, dict):
                result["items"] = []; result["count"] = 0; result["dirs"] = 0; result["files"] = 0
            return
        from tubecli.core import auth
        kept = [it for it in items
                if isinstance(it, dict) and auth.path_in_folders(it.get("path"), folders)]
        result["items"] = kept
        result["count"] = len(kept)
        result["dirs"] = sum(1 for i in kept if i.get("is_dir"))
        result["files"] = sum(1 for i in kept if not i.get("is_dir") and "error" not in i)
    except Exception:
        if isinstance(result, dict):
            result["items"] = []; result["count"] = 0; result["dirs"] = 0; result["files"] = 0


@_shared.get("/list")
async def list_files(
    request: Request,
    path: str = Query(..., description="Directory path"),
    show_hidden: bool = Query(False, description="Show hidden files"),
):
    """List files and folders in a directory."""
    svc = _get_service()
    try:
        result = svc.list_dir(path, show_hidden=show_hidden)
        _guest_confine_listing(request, result)
        return {"success": True, **result}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@_shared.post("/create-folder")
async def create_folder(req: CreateFolderRequest):
    """Create a new folder."""
    svc = _get_service()
    try:
        result = svc.create_folder(req.path)
        return {"success": True, **result}
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@_shared.post("/create-file")
async def create_file(req: CreateFileRequest):
    """Create a new file with optional content."""
    svc = _get_service()
    try:
        result = svc.create_file(req.path, req.content)
        return {"success": True, **result}
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class WriteTextRequest(BaseModel):
    path: str
    content: str


@_shared.post("/write")
async def write_text(req: WriteTextRequest):
    """Ghi ĐÈ nội dung text vào một file đã có (nút Lưu của trình sửa trên canvas).

    Khác /create-file (tạo mới): đây là lưu nội dung đang sửa. create_file() đã biết .docx/.xlsx
    nên lưu đúng định dạng cho các loại đó. CHỈ CHỦ — _guest_allowed deny-default mọi thao tác ghi.
    """
    svc = _get_service()
    try:
        result = svc.create_file(req.path, req.content)
        return {"success": True, **result}
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class WriteSheetRequest(BaseModel):
    path: str
    sheets: List[Dict[str, Any]]


class WriteDocRequest(BaseModel):
    path: str
    paragraphs: List[Dict[str, Any]]


@_shared.get("/read-sheet")
async def read_sheet(path: str = Query(..., description="Đường dẫn .xlsx")):
    """Đọc .xlsx thành lưới ô cho trình sửa bảng tính trên canvas."""
    svc = _get_service()
    try:
        return {"success": True, **svc.read_sheet(path)}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@_shared.get("/xlsx/grid")
async def api_xlsx_grid(path: str, sheet: str = "", max_rows: int = 200, max_cols: int = 40):
    """Lưới xlsx kèm định dạng + ô gộp — để node bảng tính trên canvas dùng
    CÙNG giao diện với node Google Sheet."""
    svc = _get_service()
    try:
        return {"success": True, **svc.sheet_grid(path, sheet or None, max_rows, max_cols)}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class XlsxCellsRequest(BaseModel):
    path: str
    sheet: Optional[str] = ""
    cells: Dict[str, Any] = {}


@_shared.post("/xlsx/cells")
async def api_xlsx_cells(req: XlsxCellsRequest):
    """Ghi TỪNG Ô tại chỗ. Khác write-sheet (dựng lại cả workbook, làm mất định
    dạng/công thức/tab không gửi lên) — đây là đường mà trình sửa ô phải đi."""
    svc = _get_service()
    try:
        return {"success": True, **svc.update_sheet_cells(req.path, req.sheet or None, req.cells)}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class XlsxAddSheetRequest(BaseModel):
    path: str
    title: Optional[str] = ""


@_shared.post("/xlsx/sheet")
async def api_xlsx_add_sheet(req: XlsxAddSheetRequest):
    """Thêm trang tính mới vào workbook (không đụng các tab đã có)."""
    svc = _get_service()
    try:
        return {"success": True, **svc.add_sheet(req.path, req.title or "")}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class XlsxFormatRequest(BaseModel):
    path: str
    sheet: Optional[str] = ""
    range: str = ""
    bold: Optional[bool] = None
    italic: Optional[bool] = None
    fontSize: Optional[int] = None
    align: Optional[str] = None
    bg: Optional[str] = None
    clear: Optional[bool] = None     # True = xoá sạch định dạng vùng


@_shared.post("/xlsx/format")
async def api_xlsx_format(req: XlsxFormatRequest):
    fmt = {k: v for k, v in (("bold", req.bold), ("italic", req.italic),
                             ("fontSize", req.fontSize), ("align", req.align),
                             ("bg", req.bg), ("clear", req.clear)) if v is not None}
    svc = _get_service()
    try:
        return {"success": True, **svc.format_sheet_cells(req.path, req.sheet or None, req.range, fmt)}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class XlsxMergeRequest(BaseModel):
    path: str
    sheet: Optional[str] = ""
    range: str = ""
    merge: bool = True


@_shared.post("/xlsx/merge")
async def api_xlsx_merge(req: XlsxMergeRequest):
    svc = _get_service()
    try:
        return {"success": True, **svc.merge_sheet_cells(req.path, req.sheet or None, req.range, req.merge)}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@_shared.post("/write-sheet")
async def write_sheet(req: WriteSheetRequest):
    """Lưu lưới ô trở lại .xlsx (openpyxl). CHỈ CHỦ — guest deny-default mọi thao tác ghi."""
    svc = _get_service()
    try:
        return {"success": True, **svc.write_sheet(req.path, req.sheets)}
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@_shared.get("/read-doc")
async def read_doc(path: str = Query(..., description="Đường dẫn .docx")):
    """Đọc .docx thành danh sách đoạn có style cho trình soạn thảo trên canvas."""
    svc = _get_service()
    try:
        return {"success": True, **svc.read_doc(path)}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@_shared.post("/write-doc")
async def write_doc(req: WriteDocRequest):
    """Lưu các đoạn trở lại .docx (python-docx). CHỈ CHỦ — guest deny-default."""
    svc = _get_service()
    try:
        return {"success": True, **svc.write_doc(req.path, req.paragraphs)}
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@_shared.post("/upload")
async def upload_files(dir: str = Form(...), files: List[UploadFile] = File(...)):
    """Tải MỘT/NHIỀU file từ máy người dùng vào thư mục `dir` trên server.

    CHỈ CHỦ (write): _guest_allowed deny-default mọi endpoint trừ list/read/raw → sharee KHÔNG
    bao giờ tới được đây. Path do write_bytes()->_validate_path jail (BLOCKED_PATHS); tên file rút
    về basename để chặn traversal.
    """
    svc = _get_service()
    saved, errors = [], []
    for f in files:
        name = os.path.basename(f.filename or "").strip()
        if not name:
            continue
        try:
            data = await f.read()
            result = svc.write_bytes(os.path.join(dir, name), data)
            saved.append({"name": name, **result})
        except ValueError as e:
            errors.append({"name": name, "error": str(e)})
        except Exception as e:
            errors.append({"name": name, "error": str(e)})
    if not saved and errors:
        raise HTTPException(status_code=403, detail=errors[0]["error"])
    return {"success": True, "saved": saved, "count": len(saved), "errors": errors}


@_shared.get("/read")
async def read_file(
    path: str = Query(..., description="File path"),
    max_lines: int = Query(1000, description="Max lines to read"),
):
    """Read text file content."""
    svc = _get_service()
    try:
        result = svc.read_file(path, max_lines=max_lines)
        return {"success": True, **result}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# HEAD is declared explicitly. FastAPI's @get registers GET alone — only bare
# Starlette routes mirror GET onto HEAD — so a HEAD probe answered 405. Some
# players and download managers open a media URL that way before streaming it,
# and FileResponse already serves HEAD correctly (headers only, no body).
@_shared.api_route("/raw", methods=["GET", "HEAD"])
async def raw_media(
    request: Request,
    path: str = Query(..., description="File path inside the sandbox"),
):
    """Stream one media file for in-page preview. Nothing else.

    Why not /read: read_file decodes as UTF-8 and refuses anything over
    MAX_FILE_SIZE_MB with a 200 whose body is {"error": ...}, which the page
    turns into an error toast. Both behaviours are right for text and wrong for
    a 2 GB video. FileResponse streams at 64 KiB and already implements
    Accept-Ranges, 206 + Content-Range, 416, If-Range, ETag, Last-Modified and
    HEAD. Range is not optional for <video>: Safari opens with a probe range and
    treats a plain 200 as an unusable source, and with no Accept-Ranges the
    scrub bar is dead in every engine. None of it is worth hand-rolling.
    """
    # Guest (workspace scoped) đã qua cổng scope + auth bằng cookie guest ở middleware →
    # trang workspace cloud là nơi NHÚNG HỢP LỆ (<img>/<video> cross-site). Bỏ guard
    # chống-hotlink CHỈ cho guest hợp lệ (owner vẫn bị guard như cũ).
    if not getattr(getattr(request, "state", None), "guest_scope", None):
        _require_same_origin_fetch(request)

    svc = _get_service()
    safe = _validate(svc, path)

    ext = os.path.splitext(safe)[1].lower()
    media_type = _MEDIA_TYPES.get(ext)
    if media_type is None:
        raise HTTPException(
            status_code=415,
            detail=(
                f"Không xem trước được định dạng '{ext or '(không có phần mở rộng)'}'. "
                f"Chỉ ảnh, video, âm thanh và PDF mới được phục vụ ở đây."
            ),
        )

    # _validate_path checks the resolved path but returns the unresolved one, so
    # a caller that just opens the return value walks the link a second time and
    # a link swapped in between the two walks escapes the sandbox. Resolve here,
    # re-validate the target that will actually be opened, and hand that to
    # FileResponse. The data root holds real symlinks, so this is not theoretical.
    try:
        resolved = os.path.realpath(safe)
    except OSError as e:
        raise _fail("mở file", path, e)
    if resolved != safe:
        _validate(svc, resolved)

    _require_exists(resolved, path)
    try:
        st = os.stat(resolved)
    except OSError as e:
        raise _fail("mở file", path, e)
    if not stat.S_ISREG(st.st_mode):
        # FileResponse raises RuntimeError for this after the headers may already
        # be on the wire, which reaches the user as an opaque 500. Refuse first,
        # with the status this module's convention calls for.
        raise HTTPException(
            status_code=400,
            detail=f"Đường dẫn phải là một file thường: {path}",
        )

    headers = dict(_RAW_HEADERS)
    if media_type == "application/pdf":
        headers["Content-Security-Policy"] = _CSP_PDF
    elif media_type.startswith(("audio/", "video/")):
        headers["Content-Security-Policy"] = _CSP_MEDIA
    headers["Content-Disposition"] = _inline_disposition(os.path.basename(resolved))

    # GUEST (workspace scoped) xem từ trang cloud — KHÁC origin (same-site) với tunnel. CORP
    # 'same-origin' chặn <img>/<video> cross-origin (ERR_BLOCKED_BY_RESPONSE.NotSameOrigin) và
    # frame-ancestors 'self' chặn iframe PDF. Quyền ĐỌC đã enforce qua scope (cookie guest +
    # _guest_allowed path∈folder/file), CORP/frame-ancestors chỉ là lớp chống-hotlink cho khách
    # vô danh → nới cho guest hợp lệ. Owner (không guest_scope) giữ nguyên khoá chặt.
    if getattr(getattr(request, "state", None), "guest_scope", None):
        headers["Cross-Origin-Resource-Policy"] = "cross-origin"
        if media_type == "application/pdf":
            headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors *"

    # stat_result is handed over so Content-Length, ETag and Last-Modified come
    # from the stat this handler already validated rather than a second one.
    # filename= is deliberately not passed: FileResponse only writes
    # Content-Disposition when it is, and defaults that to "attachment", which
    # would turn every <img> and <video> into a download prompt.
    return FileResponse(
        resolved,
        media_type=media_type,
        stat_result=st,
        headers=headers,
    )


@_shared.get("/search")
async def search_files(
    path: str = Query(..., description="Directory to search in"),
    pattern: str = Query("*", description="Glob pattern"),
    recursive: bool = Query(True, description="Search recursively"),
):
    """Search files matching a pattern."""
    svc = _get_service()
    try:
        result = svc.search(path, pattern=pattern, recursive=recursive)
        return {"success": True, **result}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@_shared.post("/move")
async def move_file(req: MoveRequest):
    """Move or rename a file/folder."""
    svc = _get_service()
    try:
        result = svc.move(req.src, req.dst)
        return {"success": True, **result}
    except (FileNotFoundError, ValueError) as e:
        status = 404 if isinstance(e, FileNotFoundError) else 403
        raise HTTPException(status_code=status, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@_shared.post("/copy")
async def copy_file(req: CopyRequest):
    """Copy a file/folder."""
    svc = _get_service()
    try:
        result = svc.copy(req.src, req.dst)
        return {"success": True, **result}
    except (FileNotFoundError, ValueError) as e:
        status = 404 if isinstance(e, FileNotFoundError) else 403
        raise HTTPException(status_code=status, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@_shared.delete("/delete")
async def delete_file(path: str = Query(..., description="Path to delete")):
    """Delete a file or folder."""
    svc = _get_service()
    try:
        result = svc.delete(path)
        return {"success": True, **result}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── /info — the one endpoint that differs per prefix ─────────────

@router_legacy.get("/info")
async def file_info(path: str = Query(..., description="File or folder path")):
    """Get detailed file/folder information.

    Unchanged, including the full os.walk for directories: file_manager.js line
    405 renders `data.total_size_human` in the properties dialog, so removing it
    here would blank a field in the shipped page.
    """
    svc = _get_service()
    try:
        result = svc.info(path)
        return {"success": True, **result}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router_fm.get("/info")
async def file_info_cheap(path: str = Query(..., description="File or folder path")):
    """Same fields as /api/v1/files/info, minus the directory tree walk.

    Directory size is null here BECAUSE it is not computed, not because it is
    zero — measured cost on this machine is 227 files/s, so sizing a directory
    inline turns a properties popup into a multi-minute request. Clients that
    want the number ask POST /usage/scan and poll it. `size_pending` exists so
    the UI can tell "not measured" apart from "empty".
    """
    svc = _get_service()
    safe = _validate(svc, path)
    _require_exists(safe, path)
    try:
        info = svc._file_info(safe)
    except Exception as e:
        raise _fail("đọc thông tin", path, e)

    if info.get("is_dir"):
        info["size"] = None
        info["size_human"] = None
        info["total_files"] = None
        info["total_size"] = None
        info["total_size_human"] = None
        info["size_pending"] = True
        info["size_hint"] = "Dung lượng thư mục chưa được tính. Chạy quét dung lượng để biết con số."
        info["size_endpoint"] = "/api/v1/file-manager/usage/scan"
    else:
        info["size_pending"] = False
    return {"success": True, **info}


# ── Disk volumes ─────────────────────────────────────────────────

@router_fm.get("/disk")
async def disk_volumes():
    """List mounted volumes with capacity figures."""
    fn = _resolve("disk_usage", "list_volumes", "get_volumes", "list_disks")
    try:
        result = await _call(fn, "disk_usage", "list_volumes")
    except Exception as e:
        raise _fail("liệt kê ổ đĩa", "-", e)
    return _envelope(result, "volumes")


# ── Directory usage scan (background job) ────────────────────────

@router_fm.post("/usage/scan")
async def usage_scan_start(req: UsageScanRequest):
    """Start a background walk of `path` and return its scan id immediately."""
    svc = _get_service()
    safe = _validate(svc, req.path)
    _require_exists(safe, req.path)
    _require_dir(safe, req.path)

    fn = _resolve("disk_usage", "start_scan", "start_usage_scan", "scan_start")
    try:
        # service=svc so the walk validates against THIS service; without it
        # disk_usage falls back to the sandboxed singleton and a scan of a
        # perfectly browsable folder outside the old roots would 403.
        if _accepts(fn, "service"):
            result = await _call(fn, "disk_usage", "start_scan", path=safe, service=svc)
        else:
            result = await _call(fn, "disk_usage", "start_scan", path=safe)
    except Exception as e:
        raise _fail("bắt đầu quét dung lượng", req.path, e)

    payload = _envelope(result, "scan_id")
    scan_id = payload.get("scan_id")
    if not scan_id:
        # Without an id the client can never poll, so the scan would run to
        # completion invisibly and look like an instant success.
        raise HTTPException(
            status_code=500,
            detail="disk_usage.start_scan không trả về scan_id, không thể theo dõi tiến trình quét.",
        )
    return payload


@router_fm.get("/usage/scan/{scan_id}")
async def usage_scan_status(scan_id: str):
    """Poll a running scan. Unknown ids are a 404, never a fake 'running'."""
    fn = _resolve("disk_usage", "get_scan", "get_scan_status", "scan_status")
    try:
        result = await _call(fn, "disk_usage", "get_scan", scan_id=scan_id)
    except KeyError:
        result = None
    except Exception as e:
        raise _fail("đọc trạng thái quét", scan_id, e)

    if result is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Không tìm thấy phiên quét '{scan_id}'. "
                f"Phiên có thể đã hết hạn hoặc máy chủ đã khởi động lại — hãy quét lại."
            ),
        )
    if not isinstance(result, dict) or "status" not in result:
        # A status-less body makes the client poll forever with nothing to show.
        raise HTTPException(
            status_code=500,
            detail=f"disk_usage.get_scan trả về dữ liệu thiếu trường 'status' cho phiên '{scan_id}'.",
        )
    return result


@router_fm.post("/usage/scan/{scan_id}/cancel")
async def usage_scan_cancel(scan_id: str):
    """Ask a running scan to stop."""
    fn = _resolve("disk_usage", "cancel_scan", "cancel", "scan_cancel")
    try:
        result = await _call(fn, "disk_usage", "cancel_scan", scan_id=scan_id)
    except KeyError:
        result = None
    except Exception as e:
        raise _fail("hủy phiên quét", scan_id, e)

    if result is None or result is False:
        raise HTTPException(
            status_code=404,
            detail=f"Không tìm thấy phiên quét '{scan_id}' để hủy.",
        )
    if isinstance(result, dict):
        return result
    return {"status": "cancelled"}


# ── Cleanup ──────────────────────────────────────────────────────

def _refuse_dangerous_cleanup_root(safe: str):
    """Cleanup deletes for real. With the UI service no longer fenced by the
    allowed roots, the old backstop "never delete an allowed root itself" lost
    its meaning — so refuse the two targets where a category sweep is
    indistinguishable from wiping the machine: a filesystem root (C:\\, /) and
    the home directory itself. Any folder BELOW them is still fine."""
    normalized = os.path.normpath(safe)
    if os.path.dirname(normalized) == normalized:
        raise HTTPException(
            status_code=403,
            detail="Không dọn dẹp trực tiếp trên thư mục gốc của ổ đĩa. Hãy chọn một thư mục con cụ thể.",
        )
    home = os.path.normpath(os.path.expanduser("~"))
    if os.path.normcase(normalized) == os.path.normcase(home):
        raise HTTPException(
            status_code=403,
            detail="Không dọn dẹp trực tiếp trên toàn bộ thư mục home. Hãy chọn một thư mục con cụ thể.",
        )


@router_fm.get("/cleanup/scan")
async def cleanup_scan(path: str = Query(..., description="Directory to analyse")):
    """Detect reclaimable categories under `path`.

    A GET per the contract, but it is a full tree walk plus hashing, so it runs
    in the threadpool rather than on the event loop. Long trees will make this
    request slow; they must not make the whole server slow.
    """
    svc = _get_service()
    safe = _validate(svc, path)
    _require_exists(safe, path)
    _require_dir(safe, path)
    _refuse_dangerous_cleanup_root(safe)

    # The real export is scan_categories; the three older names are fallbacks
    # that cleanup.py has never defined, so resolving them first made this
    # endpoint answer 503 to every request and killed the whole cleanup UI.
    # `service` is passed because scan_categories re-validates the path through
    # FileService and raises when it is missing (cleanup.py `_validate_root`) —
    # correcting only the name would trade the 503 for a 400 on every request.
    fn = _resolve("cleanup", "scan_categories", "scan_cleanup", "scan", "cleanup_scan")
    try:
        result = await _call(fn, "cleanup", "scan_categories", path=safe, service=svc)
    except Exception as e:
        raise _fail("quét dọn dẹp", path, e)
    return _envelope(result, "categories")


@router_fm.post("/cleanup/apply")
async def cleanup_apply(req: CleanupApplyRequest):
    """Delete the selected categories. Previews unless dry_run is explicitly false."""
    svc = _get_service()
    safe = _validate(svc, req.path)
    _require_exists(safe, req.path)
    _require_dir(safe, req.path)
    _refuse_dangerous_cleanup_root(safe)

    dry_run = True if req.dry_run is None else bool(req.dry_run)

    if not req.category_ids:
        raise HTTPException(
            status_code=400,
            detail="Chưa chọn nhóm nào để dọn. Gửi 'category_ids' với ít nhất một mục.",
        )
    if not all(isinstance(c, str) and c.strip() for c in req.category_ids):
        raise HTTPException(
            status_code=400,
            detail="'category_ids' phải là danh sách chuỗi không rỗng.",
        )

    fn = _resolve("cleanup", "apply_cleanup", "apply", "cleanup_apply")

    # If the caller names a stored plan, the plan must actually be used. Letting
    # the request through to a backend that ignores scan_id would re-enumerate
    # the tree at apply time and delete files the user never saw in the preview.
    if req.scan_id and not _accepts(fn, "scan_id"):
        raise HTTPException(
            status_code=501,
            detail=(
                "Bản dọn dẹp này chưa hỗ trợ áp dụng theo 'scan_id' đã lưu. "
                "Hãy quét lại rồi áp dụng ngay, hoặc bỏ trường 'scan_id'."
            ),
        )

    try:
        result = await _call(
            fn,
            "cleanup",
            "apply_cleanup",
            path=safe,
            category_ids=list(req.category_ids),
            dry_run=dry_run,
            # cleanup.apply_cleanup refuses to delete anything without a
            # FileService — every path it touches has to be re-checked against
            # the allowed roots inside the backend, not just here. Omitting it
            # made the backend raise ValueError, which _fail maps to a 400, so a
            # perfectly valid request came back blaming the user's own input.
            service=svc,
            scan_id=req.scan_id,
        )
    except Exception as e:
        raise _fail("dọn dẹp" if not dry_run else "xem trước dọn dẹp", req.path, e)

    if not isinstance(result, dict):
        raise HTTPException(
            status_code=500,
            detail=f"cleanup.apply_cleanup trả về {type(result).__name__}, cần một đối tượng kết quả.",
        )
    # Echo the mode this request actually ran in. A client that mis-sent the
    # flag must be able to see from the response whether files were really
    # deleted, rather than inferring it.
    result["dry_run"] = dry_run
    return result


# ── Permissions ──────────────────────────────────────────────────

@router_fm.get("/permissions")
async def permissions_read(path: str = Query(..., description="File or folder path")):
    """Read ownership and permissions for `path`."""
    svc = _get_service()
    safe = _validate(svc, path)
    _require_exists(safe, path)

    fn = _resolve("permissions", "get_permissions", "read_permissions", "get_perms")
    try:
        if _accepts(fn, "service"):
            return await _call(fn, "permissions", "get_permissions", path=safe, service=svc)
        return await _call(fn, "permissions", "get_permissions", path=safe)
    except Exception as e:
        raise _fail("đọc quyền", path, e)


@router_fm.post("/permissions")
async def permissions_write(req: PermissionsRequest):
    """Apply a permission change.

    Only the request shape is checked here. Which changes are legal on which
    platform — POSIX mode vs Windows ACE, and the refusal to add a DENY ace that
    can lock the user out of their own folder with no way back — is decided in
    permissions.py, so there is exactly one copy of that rule.
    """
    svc = _get_service()
    safe = _validate(svc, req.path)
    _require_exists(safe, req.path)

    if req.posix_mode is None and req.windows is None:
        raise HTTPException(
            status_code=400,
            detail="Không có thay đổi nào được yêu cầu: cần 'posix_mode' hoặc 'windows'.",
        )
    if req.posix_mode is not None and req.windows is not None:
        # Applying both would leave the caller unable to say which half landed
        # when one of them fails.
        raise HTTPException(
            status_code=400,
            detail="Chỉ gửi một trong hai: 'posix_mode' (Linux/macOS) hoặc 'windows' (Windows).",
        )

    posix_mode = None
    if req.posix_mode is not None:
        raw = req.posix_mode.strip()
        if not _OCTAL_MODE_RE.match(raw):
            raise HTTPException(
                status_code=400,
                detail=f"'posix_mode' không hợp lệ: '{req.posix_mode}'. Dùng dạng bát phân, ví dụ 0755 hoặc 644.",
            )
        value = int(raw, 8)
        if value > 0o7777:
            raise HTTPException(
                status_code=400,
                detail=f"'posix_mode' vượt quá giới hạn: '{req.posix_mode}'. Giá trị lớn nhất là 7777.",
            )
        # Normalised to 4 digits so the backend always receives one shape, and
        # so setuid/setgid/sticky survive the round trip instead of being
        # truncated away by a 3-digit format.
        posix_mode = f"{value:04o}"

    windows = _model_dump(req.windows)
    if windows is not None:
        action = (windows.get("action") or "").strip().lower()
        if action not in ("grant", "revoke"):
            raise HTTPException(
                status_code=400,
                detail=f"'windows.action' phải là 'grant' hoặc 'revoke', nhận được: '{windows.get('action')}'.",
            )
        if not (windows.get("identity") or "").strip():
            raise HTTPException(
                status_code=400,
                detail="'windows.identity' không được để trống (ví dụ: DESKTOP-ABC\\\\ADMIN).",
            )
        if not (windows.get("rights") or "").strip():
            raise HTTPException(
                status_code=400,
                detail="'windows.rights' không được để trống (ví dụ: Read, Modify).",
            )
        windows["action"] = action

    fn = _resolve("permissions", "set_permissions", "apply_permissions", "set_perms")
    try:
        extra = {"service": svc} if _accepts(fn, "service") else {}
        result = await _call(
            fn,
            "permissions",
            "set_permissions",
            path=safe,
            recursive=bool(req.recursive),
            posix_mode=posix_mode,
            windows=windows,
            **extra,
        )
    except Exception as e:
        raise _fail("đổi quyền", req.path, e)

    if not isinstance(result, dict) or "status" not in result:
        raise HTTPException(
            status_code=500,
            detail="permissions.set_permissions không trả về trường 'status', không xác định được thay đổi có được áp dụng hay không.",
        )
    return result


# ── Mount the shared CRUD routes under both prefixes ─────────────
# Deliberately the last statements in the module: include_router() snapshots the
# routes present on _shared when it is called, so this must run after every
# @_shared decorator above has been evaluated.
router_legacy.include_router(_shared)
router_fm.include_router(_shared)
router.append(router_public)          # trang công khai /s/<token>, không tiền tố
