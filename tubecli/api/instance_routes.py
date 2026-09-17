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


def _require_owner_session(request: Request) -> None:
    from tubecli.core import auth

    if getattr(request.state, "guest_scope", None) or not auth.session_valid(request.cookies.get(auth.SESSION_COOKIE)):
        raise HTTPException(403, "only the owner's signed-in session can set the cloud identity")


@router.get("/api/v1/instance/cloud-identity")
async def get_cloud_identity():
    ident = cloud_identity.load()
    return {"identity": ident or None, "drive_root": cloud_identity.drive_root_name()}


@router.put("/api/v1/instance/cloud-identity")
async def put_cloud_identity(req: CloudIdentityRequest, request: Request):
    _require_owner_session(request)
    try:
        ident = cloud_identity.save(req.username, req.server_code)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "identity": ident, "drive_root": cloud_identity.drive_root_name()}
