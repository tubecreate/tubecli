"""/api/v1/series — HỒ SƠ TRUYỆN (tubecli.core.series, 11/10/2026): quan hệ / nơi chốn / giai đoạn của truyện dài kỳ.

  GET    /api/v1/series                 danh sách (slug, tên, số thành viên)
  GET    /api/v1/series/{key}           một hồ sơ (theo slug, tên hay biệt danh)
  GET    /api/v1/series/{key}/brief     đoạn STORY BIBLE đưa model (?present=slug1,slug2)
  POST   /api/v1/series                 {name, aliases, names, summary, world, members, relations, phases, slug?}
  DELETE /api/v1/series/{key}

Chỉ có tác dụng với mẫu dạng kể chuyện (Film / Drama, Xianxia) chọn hồ sơ này (wizSeries). Khách workspace không ghi được.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from tubecli.core import series as S

router = APIRouter(prefix="/api/v1/series", tags=["series"])


def _deny_guest(request: Request) -> None:
    if getattr(request.state, "guest_scope", None):
        raise HTTPException(403, "Not available in a shared workspace.")


@router.get("")
async def list_all():
    return {"success": True, "formats": list(S.NARRATIVE_FORMATS),
            "series": [{"slug": s["slug"], "name": s["name"], "names": s.get("names") or {},
                        "members": len(s.get("members") or []), "updated_at": s.get("updated_at") or ""}
                       for s in S.list_all()]}


@router.get("/{key}/brief")
async def brief(key: str, present: str = ""):
    s = S.get(key)
    if not s:
        raise HTTPException(404, f"Series «{key}» not found")
    keep = [x.strip() for x in present.split(",") if x.strip()] or None
    return {"success": True, "brief": S.brief(s, keep)}


@router.get("/{key}")
async def get_one(key: str):
    s = S.get(key)
    if not s:
        raise HTTPException(404, f"Series «{key}» not found")
    return {"success": True, "series": s}


@router.post("")
async def save(request: Request):
    _deny_guest(request)
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(400, "Body must be JSON")
    if not isinstance(body, dict):
        raise HTTPException(400, "Body must be an object")
    try:
        return {"success": True, "series": S.save(body)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/{key}")
async def delete(key: str, request: Request):
    _deny_guest(request)
    if not S.delete(key):
        raise HTTPException(404, f"Series «{key}» not found")
    return {"success": True}
