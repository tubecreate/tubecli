"""/api/v1/templates — kho MẪU chung của mọi studio (tubecli.core.templates).

  GET    /api/v1/templates?section=wizard|ref_video   danh sách (kèm `view` = dữ liệu phần riêng ấy khi hỏi)
  GET    /api/v1/templates/{id_or_name}?section=…     một mẫu
  POST   /api/v1/templates                             {name, section, data, origin?} — lưu phần riêng (gộp khoá)
  POST   /api/v1/templates/{id_or_name}/rename         {name}
  POST   /api/v1/templates/{id_or_name}/cast           {cast: [slug kho nhân vật]} — dàn nhân vật của mẫu
  DELETE /api/v1/templates/{id_or_name}

Content Studio vẫn có /api/v1/studio/presets (đọc/ghi qua kho này); Pod Studio có /api/v1/pod_studio/presets và
/ref-video/templates. Route này cho giao diện/agent cần thấy mọi mẫu ở một chỗ. Khách workspace chia sẻ không tới
được namespace này (gate chỉ mở namespace của extension được chia sẻ).
"""
from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from tubecli.core import templates as T

router = APIRouter(prefix="/api/v1/templates", tags=["templates"])


class SaveBody(BaseModel):
    name: str
    section: str
    data: Dict[str, Any] = {}
    origin: str = ""


class RenameBody(BaseModel):
    name: str


class CastBody(BaseModel):
    cast: List[str] = []


def _section(section: str) -> str:
    s = str(section or "").strip()
    if s and s not in T.SECTIONS:
        raise HTTPException(400, f"Unknown section «{s}» (known: {', '.join(T.SECTIONS)})")
    return s


def _deny_guest(request: Request) -> None:
    if getattr(request.state, "guest_scope", None):
        raise HTTPException(403, "Not available in a shared workspace.")


@router.get("")
async def list_all(section: str = ""):
    s = _section(section)
    return {"success": True, "sections": list(T.SECTIONS),
            "templates": [T.summary(t, s) for t in T.list_templates()]}


@router.get("/{key:path}")
async def get_one(key: str, section: str = ""):
    t = T.get_template(key)
    if not t:
        raise HTTPException(404, f"Template «{key}» not found")
    return {"success": True, "template": T.summary(t, _section(section))}


@router.post("")
async def save(body: SaveBody, request: Request):
    _deny_guest(request)
    try:
        t = T.save_section(body.name, _section(body.section) or "wizard", body.data, origin=body.origin)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"success": True, "template": T.summary(t, body.section)}


@router.post("/{key:path}/rename")
async def rename(key: str, body: RenameBody, request: Request):
    _deny_guest(request)
    try:
        t = T.rename_template(key, body.name)
    except ValueError as e:
        raise HTTPException(409, str(e))
    if not t:
        raise HTTPException(404, f"Template «{key}» not found")
    return {"success": True, "template": T.summary(t)}


@router.post("/{key:path}/cast")
async def set_cast(key: str, body: CastBody, request: Request):
    _deny_guest(request)
    t = T.set_cast(key, body.cast)
    if not t:
        raise HTTPException(404, f"Template «{key}» not found")
    return {"success": True, "template": T.summary(t)}


@router.delete("/{key:path}")
async def delete(key: str, request: Request):
    _deny_guest(request)
    if not T.delete_template(key):
        raise HTTPException(404, f"Template «{key}» not found")
    return {"success": True}
