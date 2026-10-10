"""/api/v1/characters — KHO NHÂN VẬT chung của mọi studio (tubecli.core.characters, 10/10/2026).

  GET    /api/v1/characters?series=…                 danh sách hồ sơ (+ sheet_url)
  GET    /api/v1/characters/{slug}                   một hồ sơ (theo slug, tên hay biệt danh)
  GET    /api/v1/characters/{slug}/sheet             ảnh reference sheet
  POST   /api/v1/characters                          {name, aliases, series, kind, prompt_name, look, personality, notes,
                                                     style, status, size, slug?, sheet_path? | sheet_data?} — thêm / sửa
  POST   /api/v1/characters/match                    {text, cast?: [slug], aliases?} → nhân vật kho mà text nhắc tên
  POST   /api/v1/characters/bundle                   {slugs} → gói [{profile, sheet_data}] (mẫu bán lên Chợ mang theo)
  POST   /api/v1/characters/install                  {items, overwrite?} → cài gói nhân vật
  DELETE /api/v1/characters/{slug}

Content Studio đọc kho qua mô-đun lõi (cùng tiến trình); route này cho giao diện, Thumbnail Studio / bố cục và agent.
Khách workspace chia sẻ không ghi được (đọc thì gate namespace đã chặn sẵn như kho mẫu).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from tubecli.core import characters as C

router = APIRouter(prefix="/api/v1/characters", tags=["characters"])


class MatchBody(BaseModel):
    text: str
    cast: List[str] = []
    aliases: Optional[bool] = None


class BundleBody(BaseModel):
    slugs: List[str]


class InstallBody(BaseModel):
    items: List[Dict[str, Any]]
    overwrite: bool = False


def _deny_guest(request: Request) -> None:
    if getattr(request.state, "guest_scope", None):
        raise HTTPException(403, "Not available in a shared workspace.")


def _public(p: Dict[str, Any]) -> Dict[str, Any]:
    out = {k: v for k, v in p.items() if k != "sheet_path"}
    out["has_sheet"] = bool(p.get("sheet_path"))
    out["sheet_url"] = f"/api/v1/characters/{quote(p['slug'])}/sheet" if p.get("sheet_path") else ""
    return out


@router.get("")
async def list_all(series: str = ""):
    items = C.load_all()
    if series.strip():
        s = series.strip().casefold()
        items = [p for p in items if s in str(p.get("series") or "").casefold()]
    return {"success": True, "characters": [_public(p) for p in items]}


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
        p = C.save(body, sheet_src=str(body.get("sheet_path") or ""), sheet_data=str(body.get("sheet_data") or ""))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"success": True, "character": _public(p)}


@router.post("/match")
async def match(body: MatchBody):
    aliases = bool(body.cast) if body.aliases is None else body.aliases
    return {"success": True, "characters": [_public(p) for p in C.match(body.text, only=body.cast or None,
                                                                         aliases=aliases)]}


@router.post("/bundle")
async def bundle(body: BundleBody, request: Request):
    _deny_guest(request)
    return {"success": True, "items": C.bundle(body.slugs)}


@router.post("/install")
async def install(body: InstallBody, request: Request):
    _deny_guest(request)
    try:
        done = C.install_bundle(body.items, overwrite=body.overwrite)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"success": True, "installed": done}


@router.get("/{key}/sheet")
async def sheet(key: str):
    p = C.get(key)
    if not p or not p.get("sheet_path"):
        raise HTTPException(404, f"No sheet for «{key}»")
    return FileResponse(p["sheet_path"], headers={"Cache-Control": "no-cache"})


@router.get("/{key}")
async def get_one(key: str):
    p = C.get(key)
    if not p:
        raise HTTPException(404, f"Character «{key}» not found")
    return {"success": True, "character": _public(p)}


@router.delete("/{key}")
async def delete(key: str, request: Request):
    _deny_guest(request)
    if not C.delete(key):
        raise HTTPException(404, f"Character «{key}» not found")
    return {"success": True}
