"""/api/v1/clone/* — nhân bản extension + template sang máy khác (core/clone_kit.py, 30/10/2026).

  GET  /api/v1/clone/manifest                  máy này có gì để chép (mục bật/tắt, extension, template)
  POST /api/v1/clone/export  {sections}        đóng gói → {token, path, bytes, expires_at, manifest}
  GET  /api/v1/clone/bundle/<token>            tải gói — KHÔNG cần đăng nhập (máy đích tải qua tunnel); mã 256 bit,
                                               hạn 2 giờ, tối đa 5 lượt (_AUTH_EXEMPT_PREFIX trong server.py)
  GET  /api/v1/clone/bundle/<token>/manifest   manifest của gói (không tính lượt) — thẻ duyệt ở máy đích đọc trước
  POST /api/v1/clone/plan    {url, sections, mode}  kế hoạch nhập, không ghi gì
  POST /api/v1/clone/import  {url, sections, mode}  tải + nhập ở luồng nền → {job_id}
  GET  /api/v1/clone/jobs/<id>                 tiến độ / báo cáo
Công cụ MCP: codex_gpt/tools.py (clone_manifest, clone_export, clone_import [luôn hỏi chủ], clone_status).
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from tubecli.core import clone_kit as CK

router = APIRouter(tags=["Clone"])


async def _body(request: Request) -> dict:
    try:
        b = await request.json()
        return b if isinstance(b, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


@router.get("/api/v1/clone/manifest")
async def clone_manifest():
    return await asyncio.to_thread(CK.local_manifest)


@router.post("/api/v1/clone/export")
async def clone_export(request: Request):
    b = await _body(request)
    loop = asyncio.get_running_loop()
    try:
        return await asyncio.to_thread(CK.export_bundle, b.get("sections"), request.app, loop, bool(b.get("fresh")))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(500, str(e))


@router.get("/api/v1/clone/bundle/{token}/manifest")
async def clone_bundle_manifest(token: str):
    v = await asyncio.to_thread(CK.bundle_for, token, False)
    if v is None:
        raise HTTPException(404, "No bundle with that token (expired, used up, or wrong).")
    return v.get("manifest") or {}


@router.get("/api/v1/clone/bundle/{token}")
async def clone_bundle(token: str):
    v = await asyncio.to_thread(CK.bundle_for, token, True)
    if v is None:
        raise HTTPException(404, "No bundle with that token (expired, used up, or wrong).")
    return FileResponse(v["file_path"], media_type="application/zip", filename="tubecli-clone.zip")


@router.post("/api/v1/clone/plan")
async def clone_plan(request: Request):
    b = await _body(request)
    try:
        man = await asyncio.to_thread(CK.fetch_remote_manifest, b.get("url"))
        plan = CK.plan_import(man, b.get("sections"), str(b.get("mode") or "newer"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # noqa: BLE001 — mạng / nguồn trả lỗi
        raise HTTPException(502, f"Could not read the source bundle: {e}")
    return {**plan, "summary": CK.plan_summary(plan)}


@router.post("/api/v1/clone/import")
async def clone_import(request: Request):
    b = await _body(request)
    try:
        return CK.start_import(b.get("url"), b.get("sections"), str(b.get("mode") or "newer"), request.app,
                               asyncio.get_running_loop())
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/api/v1/clone/jobs/{jid}")
async def clone_job(jid: str):
    j = CK.job_status(jid)
    if j is None:
        raise HTTPException(404, "No clone job with that id.")
    return j


@router.on_event("startup")
async def _apply_pending_templates() -> None:
    """Gói template xếp chờ (Content Studio vừa được chép, chưa nạp lúc nhập) → nhập sau khi server lên ~20 s."""
    loop = asyncio.get_running_loop()

    async def later():
        await asyncio.sleep(20)
        try:
            from tubecli.api.server import app
            res = await asyncio.to_thread(CK.apply_pending, app, loop)
            if res:
                print(f"[clone] pending template imports: {res}")
        except Exception as e:  # noqa: BLE001
            print(f"[clone] pending template import failed: {e}")
    loop.create_task(later())
