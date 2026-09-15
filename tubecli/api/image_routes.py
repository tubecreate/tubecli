"""/api/v1/images — AI tạo ảnh DÙNG CHUNG (cài đặt, danh sách model, vẽ thử, vẽ, phát file).

Vì sao có: tab «AI tạo ảnh» trên Flow từng chỉ chỉnh cài đặt của Content Studio, máy chưa cài
Studio thì không có gì để chọn, Thumbnail Studio chép engine riêng. Từ lõi .94 (15/9/2026) bộ
vẽ nằm ở tubecli.core.image_gen; các extension gọi vào đây hoặc import thẳng mô-đun.
"""
from __future__ import annotations

import os
import re
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from starlette.responses import FileResponse

from tubecli.core import image_gen as G

router = APIRouter(prefix="/api/v1/images", tags=["images"])


class ImageSettingsRequest(BaseModel):
    provider: Optional[str] = None     # cloudflare | gemini | 9router | "" = tự chọn
    model: Optional[str] = None


class ImageTestRequest(BaseModel):
    provider: Optional[str] = ""
    model: Optional[str] = ""


class ImageGenerateRequest(BaseModel):
    prompt: str
    aspect_ratio: Optional[str] = "16:9"
    provider: Optional[str] = ""
    model: Optional[str] = ""
    filename: Optional[str] = ""       # tên file muốn (chỉ tên, không thư mục); trống = uuid


def _settings_payload() -> dict:
    cfg = G.image_settings()
    r = G.resolve_provider(cfg["provider"] or None, cfg["model"] or None)
    return {"provider": cfg["provider"], "model": cfg["model"], "providers": list(G.PROVIDERS),
            "defaults": dict(G.DEFAULT_MODELS), "resolved": G.public_resolution(r), "core": True}


@router.get("/settings")
async def get_image_settings():
    """Cài đặt chung + nhà/model sẽ thật sự dùng (resolved) — không kèm khoá."""
    return _settings_payload()


@router.put("/settings")
async def put_image_settings(req: ImageSettingsRequest):
    try:
        G.set_image_settings(req.provider, req.model)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _settings_payload()


@router.get("/models")
async def list_image_models(provider: str = Query("", description="cloudflare | gemini | 9router; trống = tất cả")):
    p = (provider or "").lower()
    if p in G.PROVIDERS:
        return {"models": {p: await G.list_models(p)}}
    out = {}
    for prov in G.PROVIDERS:
        out[prov] = await G.list_models(prov)
    return {"models": out}


@router.post("/test")
async def test_image(req: ImageTestRequest):
    """Vẽ thử một ảnh 1:1 rồi xoá: {ok, stage, provider, model, seconds, message, kind}."""
    return await G.test_draw(req.provider or None, req.model or None)


_SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]{1,120}$")


@router.post("/generate")
async def generate(req: ImageGenerateRequest):
    """Vẽ một ảnh vào data/images/ và trả đường dẫn + URL phát."""
    if not (req.prompt or "").strip():
        raise HTTPException(400, "Thiếu prompt.")
    aspect = req.aspect_ratio or "16:9"
    if aspect not in G.ASPECT_RATIOS:
        raise HTTPException(400, f"aspect_ratio phải là một trong {', '.join(G.ASPECT_RATIOS)}.")
    name = (req.filename or "").strip()
    if name and not _SAFE_NAME.match(name):
        raise HTTPException(400, "filename chỉ gồm chữ, số, dấu chấm, gạch — không có thư mục.")
    if not name:
        name = f"{uuid.uuid4().hex}.jpg"
    elif not name.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
        name += ".jpg"
    path = os.path.join(G.shared_output_dir(), name)
    res = await G.generate_image(req.prompt, path, req.provider or None, req.model or None, aspect_ratio=aspect)
    if res.get("status") != G.STATUS_SUCCESS:
        return {"ok": False, "status": res.get("status"), "message": res.get("message", ""),
                "kind": res.get("kind", ""), "provider": res.get("provider", ""), "model": res.get("model", "")}
    return {"ok": True, "status": "success", "path": path, "filename": name, "url": f"/api/v1/images/file/{name}",
            "provider": res.get("provider"), "model": res.get("model"), "fallback_from": res.get("fallback_from", "")}


@router.get("/file/{name}")
async def serve_image(name: str):
    """Phát một ảnh trong data/images/ theo TÊN (không đi ngược thư mục)."""
    if not _SAFE_NAME.match(name or ""):
        raise HTTPException(400, "Tên file không hợp lệ.")
    path = os.path.join(G.shared_output_dir(), name)
    if not os.path.isfile(path):
        raise HTTPException(404, "Không có ảnh này.")
    return FileResponse(path)
