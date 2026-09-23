"""Danh tính của máy trong TubeCLI Cloud: tài khoản chủ + mã công khai NGẪU NHIÊN của server (17/9/2026).

Cloud PUT sau mỗi lần đăng nhập hộ (lib/tubecli.js → pushCloudIdentity); task video lưu lên Google Drive
đặt thư mục cha theo đó — «<username>-vps-<mã server>/<tên project>» (core/cloud_identity.py). Không nhận số thứ
tự servers.id: nó lộ quy mô hệ thống cho người nhận link.

PUT đòi phiên đăng nhập THẬT của chủ, như các đường …/server/{kind} của group_routes: gate trong server.py
cho loopback đi thẳng, nên "đến từ 127.0.0.1" (run_api của model) không đủ để đổi tên thư mục mọi máy đăng
lên. Khách của không gian chia sẻ đã bị _guest_allowed chặn mặc định; ở đây chặn thêm lần nữa.
"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from tubecli.core import cloud_identity

router = APIRouter(tags=["Instance"])


class CloudIdentityRequest(BaseModel):
    username: str
    server_code: str
    # Bản cloud cũ không gửi trường này; None = giữ khoá máy đang có.
    town_key: str | None = None
    # Mã người gọi của CHỦ tài khoản cloud — máy dùng để tự khoá agent «riêng tư».
    owner: str | None = None


def _require_owner_session(request: Request) -> None:
    from tubecli.core import auth

    if getattr(request.state, "guest_scope", None) or not auth.session_valid(request.cookies.get(auth.SESSION_COOKIE)):
        raise HTTPException(403, "only the owner's signed-in session can set the cloud identity")


@router.get("/api/v1/instance/cloud-identity")
async def get_cloud_identity():
    """CHỈ phần hiển thị được. `town_key` là khoá KÝ của máy (ai có nó thì gọi được
    /api/v1/public/invoke), `owner` là mã chủ tài khoản — hai thứ đó không bao giờ đi ra
    khỏi máy. Trước 23/9/2026 route này trả cả hai, mà mọi phiên đăng nhập đều đọc được,
    kể cả khách được chia sẻ máy."""
    ident = cloud_identity.load()
    shown = {k: ident.get(k) for k in ("username", "server_code", "seen")} if ident else None
    return {"identity": shown, "drive_root": cloud_identity.drive_root_name()}


@router.put("/api/v1/instance/cloud-identity")
async def put_cloud_identity(req: CloudIdentityRequest, request: Request):
    _require_owner_session(request)
    try:
        ident = cloud_identity.save(req.username, req.server_code, req.town_key, req.owner)
    except ValueError as e:
        raise HTTPException(400, str(e))
    shown = {k: ident.get(k) for k in ("username", "server_code", "seen")}
    # CỜ, không phải khoá: cloud cần biết «máy đã cất chưa» để cron thôi quét lại, mà
    # đọc lại khoá qua HTTP thì ai có phiên cũng lấy được nó.
    return {"ok": True, "identity": shown,
            "town_key_set": bool(ident.get("town_key")),
            "owner_set": bool(ident.get("owner")),
            "drive_root": cloud_identity.drive_root_name()}
