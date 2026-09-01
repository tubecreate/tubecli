"""HTTP cho Keychain — CRUD + import + gán vào profile.

Bí mật (mật khẩu/khôi phục/2FA) CHỈ rời két qua GET .../{id}?reveal=1, và route
đó dành cho CHỦ sửa. Không route nào trả bí mật trong danh sách. Cả prefix này
KHÔNG có trong allowlist của _guest_allowed (deny-default), nên người được chia
sẻ bàn làm việc không chạm được — đúng ý: két là tài khoản riêng của chủ.
"""
import io
import logging
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger("KeychainRoutes")

router = APIRouter(prefix="/api/v1/keychain", tags=["keychain"])

# store gán khi extension bật (on_enable) — tránh khởi tạo lúc import.
_store = None


def _svc():
    if _store is None:
        raise HTTPException(503, "Keychain chưa sẵn sàng")
    return _store


def set_store(store):
    global _store
    _store = store


class AccountIn(BaseModel):
    platform: str = "generic"
    label: Optional[str] = ""
    username: Optional[str] = ""
    secret: Optional[str] = None
    recovery: Optional[str] = None
    totp: Optional[str] = None
    notes: Optional[str] = ""
    status: Optional[str] = None
    profiles: Optional[List[str]] = None


class StatusIn(BaseModel):
    status: str


@router.get("/accounts")
async def list_accounts(platform: str = "", status: str = ""):
    return {"accounts": _svc().list(platform or "", status or ""),
            "counts": _svc().counts()}


@router.get("/accounts/{acc_id}")
async def get_account(acc_id: str, reveal: int = 0):
    # reveal=1: giải mã bí mật cho chủ sửa. Guest không tới được đây (gate
    # deny-default), nhưng vẫn giữ reveal là tham số tường minh để không bao
    # giờ lộ bí mật ngoài ý muốn ở đường list.
    acc = _svc().get(acc_id, reveal=bool(reveal))
    if not acc:
        raise HTTPException(404, "Không có tài khoản này")
    return acc


@router.post("/accounts")
async def create_account(req: AccountIn):
    try:
        return _svc().create(req.model_dump(exclude_none=True))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.put("/accounts/{acc_id}")
async def update_account(acc_id: str, req: AccountIn):
    acc = _svc().update(acc_id, req.model_dump(exclude_none=True))
    if not acc:
        raise HTTPException(404, "Không có tài khoản này")
    return acc


@router.delete("/accounts/{acc_id}")
async def delete_account(acc_id: str):
    if not _svc().delete(acc_id):
        raise HTTPException(404, "Không có tài khoản này")
    return {"status": "deleted"}


@router.post("/accounts/{acc_id}/status")
async def set_status(acc_id: str, req: StatusIn):
    try:
        acc = _svc().set_status(acc_id, req.status)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not acc:
        raise HTTPException(404, "Không có tài khoản này")
    return acc


# ── Gán tài khoản vào một profile trình duyệt ───────────────────────────
# Đây là chỗ "agent có đủ tài khoản để giúp": két đổ credential vào config của
# profile (google_account/facebook_account/…) — đúng field auto-login đã có —
# rồi agent chạy profile đó là dùng được, mà KHÔNG bao giờ đọc mật khẩu.
_PLATFORM_FIELD = {
    "google": "google_account", "facebook": "facebook_account",
    "tiktok": "tiktok_account", "x": "x_account",
    "discord": "discord_account", "telegram": "telegram_account",
}


class AssignIn(BaseModel):
    profile: str


@router.post("/accounts/{acc_id}/assign")
async def assign_to_profile(acc_id: str, req: AssignIn):
    acc = _svc().get(acc_id, reveal=True)      # cần bí mật để ghi vào profile
    if not acc:
        raise HTTPException(404, "Không có tài khoản này")
    field = _PLATFORM_FIELD.get(acc.get("platform"))
    if not field:
        raise HTTPException(400, "Nền tảng '%s' chưa gán vào profile được "
                                 "(chỉ mạng có auto-login)" % acc.get("platform"))
    from tubecli.extensions.browser.profile_manager import update_profile, get_profile
    if not await run_in_threadpool(get_profile, req.profile):
        raise HTTPException(404, "Không có profile '%s'" % req.profile)
    payload = {field: {
        "email": acc.get("username") or "",
        "password": acc.get("secret") or "",
        "recoveryEmail": acc.get("recovery") or "",
        "twoFactorCodes": acc.get("totp") or "",
    }}
    await run_in_threadpool(lambda: update_profile(req.profile, **payload))
    # Ghi ngược: tài khoản này đang gắn ở profile nào (để UI hiện, để gỡ sau).
    profiles = list(dict.fromkeys((acc.get("profiles") or []) + [req.profile]))
    _svc().update(acc_id, {"profiles": profiles})
    return {"status": "assigned", "profile": req.profile, "field": field}


# ── Import hàng loạt từ Excel/CSV (tiện ích phụ) ────────────────────────
# Không phải trọng tâm (két là để quản lý cá nhân), nhưng ai có sẵn file như
# nuoi_tai_khoan_template thì nạp một phát. Ánh xạ cột → field là XÁC ĐỊNH,
# không đụng AI: cột nào rõ nghĩa cột nấy.
_COL_ALIASES = {
    "platform": "platform", "nền tảng": "platform",
    "label": "label", "tên": "label", "nhãn": "label",
    "username": "username", "email": "username", "google_email": "username",
    "user": "username", "handle": "username", "tài khoản": "username",
    "secret": "secret", "password": "secret", "google_password": "secret",
    "mật khẩu": "secret", "pass": "secret",
    "recovery": "recovery", "google_recovery": "recovery", "khôi phục": "recovery",
    "totp": "totp", "2fa": "totp", "google_2fa": "totp", "twofa": "totp",
    "notes": "notes", "ghi chú": "notes", "note": "notes",
}


class ImportIn(BaseModel):
    rows: List[Dict[str, Any]] = []            # [{cột: giá trị}] client đã parse
    default_platform: Optional[str] = "generic"


@router.post("/import")
async def import_rows(req: ImportIn):
    """Nhận các dòng đã tách sẵn (client đọc file, gửi lên JSON). Mỗi dòng có
    ít nhất username thì tạo một mục; dòng trống bỏ qua."""
    made = skipped = 0
    for raw in (req.rows or []):
        norm = {}
        for k, v in (raw or {}).items():
            key = _COL_ALIASES.get(str(k).strip().lower())
            if key and v not in (None, ""):
                norm[key] = str(v).strip()
        if not norm.get("username") and not norm.get("secret"):
            skipped += 1
            continue
        norm.setdefault("platform", req.default_platform or "generic")
        if norm["platform"] not in __import__(
                "tubecli.extensions.keychain.store", fromlist=["PLATFORMS"]).PLATFORMS:
            norm["platform"] = "generic"
        if not norm.get("label"):
            norm["label"] = norm.get("username") or norm["platform"]
        try:
            _svc().create(norm)
            made += 1
        except Exception:
            skipped += 1
    return {"status": "ok", "created": made, "skipped": skipped,
            "counts": _svc().counts()}
