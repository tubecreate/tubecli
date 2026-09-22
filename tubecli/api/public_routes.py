"""Routes của agent công khai — xem tubecli/core/public_agents.py cho lý do từng rào.

  GET  /api/v1/public-agents               chủ xem: skill công khai có gì, agent nào đang bật
  PUT  /api/v1/public-agents/{agent_id}    chủ bật/tắt, đặt tên công khai, chọn skill, trần/ngày
  POST /api/v1/public/invoke               CHỈ cloud gọi (chữ ký HMAC) — miễn phiên đăng nhập
                                           trong _AUTH_EXEMPT_EXACT của api/server.py
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from tubecli.core import public_agents

router = APIRouter(tags=["Public agents"])

MAX_INVOKE_BODY = 4096


def _require_owner(request: Request) -> None:
    """Chỉ PHIÊN ĐĂNG NHẬP của chủ. Chặn khách được chia sẻ (guest_scope) và chặn cả AI
    agent của chính máy (x-tubecli-agent): agent tự bật công khai cho mình là agent tự
    mở cửa máy cho người lạ."""
    from tubecli.core import auth

    if request.headers.get("x-tubecli-agent") or getattr(request.state, "guest_scope", None):
        raise HTTPException(403, "only the owner's signed-in session can change public agents")
    if not auth.session_valid(request.cookies.get(auth.SESSION_COOKIE)):
        raise HTTPException(403, "only the owner's signed-in session can change public agents")


class PublicAgentSettings(BaseModel):
    enabled: bool = False
    name: str = ""
    bio: str = ""
    skills: List[str] = []
    daily_cap: Optional[int] = None
    warn_pct: Optional[int] = None
    max_parallel: Optional[int] = None
    cpu_tired: Optional[int] = None
    ram_tired: Optional[int] = None


@router.get("/api/v1/public-agents")
async def list_public_agents(request: Request):
    _require_owner(request)
    from tubecli.core.agent import agent_manager

    agents = []
    for a in agent_manager.get_all():
        agents.append({
            "id": a.id,
            "name": a.name,
            "avatar_icon": getattr(a, "avatar_icon", ""),
            "avatar_color": getattr(a, "avatar_color", ""),
            "public": public_agents.get_settings(a.id) or None,
            "usage": public_agents.usage(a.id),
        })
    return {
        "cloud_ready": public_agents.cloud_ready(),
        "skills": public_agents.available_skills(),
        "agents": agents,
        # Số CPU/RAM thô chỉ ở đây (chủ xem); lên cloud chỉ có cờ «mệt».
        "load": public_agents.machine_load(),
        "defaults": {"daily_cap": public_agents.DEFAULT_DAILY_CAP, "max_daily_cap": public_agents.MAX_DAILY_CAP},
        "thresholds": {k: {"default": d, "min": lo, "max": hi} for k, (d, lo, hi) in public_agents.THRESHOLDS.items()},
    }


@router.put("/api/v1/public-agents/{agent_id}")
async def put_public_agent(agent_id: str, req: PublicAgentSettings, request: Request):
    _require_owner(request)
    from tubecli.core.agent import agent_manager

    agent = agent_manager.get(agent_id)
    if not agent:
        raise HTTPException(404, "agent not found")
    try:
        saved = public_agents.set_settings(agent_id, req.dict(), agent.name)
    except ValueError as e:
        # mã ổn định để trang tự dịch (pa.err.<code>)
        return JSONResponse(status_code=400, content={"error": str(e), "code": str(e)})
    return {"ok": True, "public": saved, "cloud_ready": public_agents.cloud_ready()}


@router.post("/api/v1/public/invoke")
async def public_invoke(request: Request):
    body = await request.body()
    if len(body) > MAX_INVOKE_BODY:
        return JSONResponse(status_code=413, content={"ok": False, "code": "too_large"})
    why = public_agents.verify_invoke(
        request.headers.get("x-town-ts"),
        request.headers.get("x-town-nonce"),
        request.headers.get("x-town-sig"),
        body,
    )
    if why:
        status = 503 if why == "not_configured" else 401
        return JSONResponse(status_code=status, content={"ok": False, "code": why})
    try:
        import json

        payload = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return JSONResponse(status_code=400, content={"ok": False, "code": "bad_request"})
    try:
        result = await public_agents.invoke(payload)
    except public_agents.PublicSkillError as e:
        return JSONResponse(status_code=e.status, content={"ok": False, "code": e.code})
    return {"ok": True, "result": result}
