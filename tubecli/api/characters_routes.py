"""/api/v1/characters — KHO NHÂN VẬT chung của mọi studio (tubecli.core.characters, 10/10/2026). MỖI KHO MỘT STYLE.

  GET    /api/v1/characters?style=…                       hồ sơ của kho style ấy (thiếu style = mọi kho) + sheet_url
  GET    /api/v1/characters/stores                        [{key, count}] các kho
  GET    /api/v1/characters/{store}/{slug}                một hồ sơ (theo slug, tên hay biệt danh)
  GET    /api/v1/characters/{store}/{slug}/sheet          ảnh reference sheet
  POST   /api/v1/characters                               {style, name, aliases, series, kind, prompt_name, look,
                                                           personality, notes, status, size, slug?, sheet_path? |
                                                           sheet_data?} — thêm / sửa
  POST   /api/v1/characters/match                         {text, style, cast?: [slug], aliases?}
  POST   /api/v1/characters/bundle                        {style, slugs} → gói [{store, profile, sheet_data}] (Chợ)
  POST   /api/v1/characters/install                       {items, style?, overwrite?}
  DELETE /api/v1/characters/{store}/{slug}

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
    style: str
    cast: List[str] = []
    aliases: Optional[bool] = None


class BundleBody(BaseModel):
    style: str
    slugs: List[str]


class InstallBody(BaseModel):
    items: List[Dict[str, Any]]
    style: str = ""
    overwrite: bool = False


def _deny_guest(request: Request) -> None:
    if getattr(request.state, "guest_scope", None):
        raise HTTPException(403, "Not available in a shared workspace.")


def _style(style: str) -> str:
    try:
        return C.style_key(style)
    except ValueError as e:
        raise HTTPException(400, str(e))


def _public(p: Dict[str, Any]) -> Dict[str, Any]:
    out = {k: v for k, v in p.items() if k != "sheet_path"}
    out["has_sheet"] = bool(p.get("sheet_path"))
    out["sheet_url"] = (f"/api/v1/characters/{quote(p['store'])}/{quote(p['slug'])}/sheet"
                        if p.get("sheet_path") else "")
    return out


@router.get("")
async def list_all(style: str = "", series: str = ""):
    items = C.load_all(_style(style) if style.strip() else None)
    if series.strip():
        s = series.strip().casefold()
        items = [p for p in items if s in str(p.get("series") or "").casefold()]
    return {"success": True, "characters": [_public(p) for p in items]}


@router.get("/stores")
async def list_stores():
    return {"success": True, "stores": C.stores()}


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
        p = C.save(body, str(body.get("style") or body.get("store") or ""),
                   sheet_src=str(body.get("sheet_path") or ""), sheet_data=str(body.get("sheet_data") or ""))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"success": True, "character": _public(p)}


@router.post("/match")
async def match(body: MatchBody):
    aliases = bool(body.cast) if body.aliases is None else body.aliases
    found = C.match(body.text, _style(body.style), only=body.cast or None, aliases=aliases)
    return {"success": True, "characters": [_public(p) for p in found]}


@router.post("/bundle")
async def bundle(body: BundleBody, request: Request):
    _deny_guest(request)
    return {"success": True, "items": C.bundle(body.slugs, _style(body.style))}


@router.post("/install")
async def install(body: InstallBody, request: Request):
    _deny_guest(request)
    try:
        done = C.install_bundle(body.items, style=body.style or None, overwrite=body.overwrite)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"success": True, "installed": done}


@router.get("/{store}/{key}/sheet")
async def sheet(store: str, key: str):
    p = C.get(key, _style(store))
    if not p or not p.get("sheet_path"):
        raise HTTPException(404, f"No sheet for «{key}» in store «{store}»")
    return FileResponse(p["sheet_path"], headers={"Cache-Control": "no-cache"})


@router.get("/{store}/{key}")
async def get_one(store: str, key: str):
    p = C.get(key, _style(store))
    if not p:
        raise HTTPException(404, f"Character «{key}» not found in store «{store}»")
    return {"success": True, "character": _public(p)}


@router.delete("/{store}/{key}")
async def delete(store: str, key: str, request: Request):
    _deny_guest(request)
    if not C.delete(key, _style(store)):
        raise HTTPException(404, f"Character «{key}» not found in store «{store}»")
    return {"success": True}
