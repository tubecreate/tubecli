"""Routes của agent công khai — xem tubecli/core/public_agents.py cho lý do từng rào.

  GET  /api/v1/public-agents               chủ xem: skill công khai có gì, agent nào đang bật
  PUT  /api/v1/public-agents/{agent_id}    chủ bật/tắt, đặt tên công khai, chọn skill, trần/ngày
  POST /api/v1/public/invoke               CHỈ cloud gọi (chữ ký HMAC) — miễn phiên đăng nhập
                                           trong _AUTH_EXEMPT_EXACT của api/server.py
  POST /api/v1/public/mcp                  trình kết nối claude.ai — CHỈ cloud gọi, chữ ký miền «mcp»
                                           (core/claude_connector.py)
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
    # "public" | "private" — xem VISIBILITIES trong core/public_agents.py.
    # None = KHÔNG gửi = giữ nguyên thứ đang lưu. Mặc định "public" ở đây thì một client
    # chưa biết tới trường này sẽ âm thầm mở agent riêng tư ra cho người lạ.
    visibility: Optional[str] = None
    name: str = ""
    bio: str = ""
    skills: List[str] = []
    daily_cap: Optional[int] = None
    warn_pct: Optional[int] = None
    max_parallel: Optional[int] = None
    cpu_tired: Optional[int] = None
    ram_tired: Optional[int] = None
    # browser.remote: hồ sơ trình duyệt cho người lạ dùng, phút/phiên, chính sách tải file.
    # None = không gửi = giữ bản đang lưu.
    browser_profile: Optional[str] = None
    browser_minutes: Optional[int] = None
    browser_upload: Optional[str] = None
    # Giá thuê trình duyệt, xu/phút (0 = miễn phí). browser_minutes là TRẦN mỗi phiên.
    browser_price: Optional[int] = None
    # Bản 4/10/2026: NHIỀU hồ sơ cho thuê (lưới cho khách chọn trên Town), bán theo PHIÊN cố
    # định, số phiên song song, cho khách tạo hồ sơ sạch. PHẢI khai ở đây: pydantic BỎ LẶNG
    # trường lạ, nên thiếu một dòng là Flow lưu mà không có tác dụng gì (test canh bên dưới).
    browser_profiles: Optional[List[str]] = None
    browser_mode: Optional[str] = None
    browser_session_minutes: Optional[int] = None
    browser_slots: Optional[int] = None
    browser_fresh: Optional[bool] = None
    # Giữ hồ sơ lâu dài: phí giữ MỘT LẦN (0 = không cho giữ) + số ngày mỗi lần giữ.
    browser_keep_price: Optional[int] = None
    browser_keep_days: Optional[int] = None
    # Nhận việc THUÊ từ Chợ mẫu (làm video từ mẫu của máy): bật/tắt, giá (xu), kiểu tính
    # (job = trọn gói | minute = theo phút), trần phút, danh sách TÊN mẫu phục vụ.
    hire_on: Optional[bool] = None
    hire_price: Optional[int] = None
    hire_unit: Optional[str] = None
    hire_minutes_max: Optional[int] = None
    hire_presets: Optional[List[str]] = None
    # Nhận việc VIDEO QUẢNG CÁO TỪ ẢNH (Pod Studio, 3/10/2026): giá xu MỖI CLIP 10 s, trần số clip/việc, cho khách
    # gửi ảnh người mẫu của họ hay không, TÊN mẫu (kho mẫu chung) phục vụ. None = không gửi = giữ bản đang lưu.
    hire_pod_on: Optional[bool] = None
    hire_pod_price: Optional[int] = None
    hire_pod_clips_max: Optional[int] = None
    hire_pod_models: Optional[bool] = None
    hire_pod_templates: Optional[List[str]] = None
    # Chuẩn hoá Word theo NĐ 30 (office.docx, 4/10/2026): credits MỖI TRANG, trần trang/việc, model AI (rỗng = chỉ luật).
    hire_office_on: Optional[bool] = None
    hire_office_price: Optional[int] = None
    hire_office_pages_max: Optional[int] = None
    hire_office_model: Optional[str] = None


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
        # Máy đã biết mã chủ tài khoản cloud chưa. Chưa biết thì agent «riêng tư» sẽ từ
        # chối mọi lượt gọi (đóng khi hỏng), nên tab Công khai phải nói ra điều đó.
        "owner_known": bool(public_agents.owner_caller()),
        "skills": public_agents.available_skills(),
        "agents": agents,
        # Số CPU/RAM thô chỉ ở đây (chủ xem); lên cloud chỉ có cờ «mệt».
        "load": public_agents.machine_load(),
        "defaults": {"daily_cap": public_agents.DEFAULT_DAILY_CAP, "max_daily_cap": public_agents.MAX_DAILY_CAP},
        "thresholds": {k: {"default": d, "min": lo, "max": hi} for k, (d, lo, hi) in public_agents.THRESHOLDS.items()},
        # Mẫu Pod Studio dùng được cho «nhận làm video quảng cáo» (kho mẫu chung, phần ref_video) — Flow bày ô chọn.
        # Chỉ mẫu đã có phần Pod (ref_video) — 54 mẫu Content Studio thuần không chen vào ô chọn.
        "pod_templates": public_agents.pod_template_cards(
            [t.get("name") for t in _shared_templates() if "ref_video" in (t.get("sections") or {})]),
        "pod_clips_max": public_agents.HIRE_POD_CLIPS_MAX,
        # Skill chuẩn hoá Word (office.docx): máy có extension Office Editor không, đếm trang thật hay ước tính,
        # + model chat gọi được (ô chọn «AI nhận diện khối»).
        "office": {**public_agents.office_status(), "models": _office_models()},
    }


def _office_models() -> list:
    try:
        from tubecli.core import public_office
        return public_office.ai_models()
    except Exception:      # noqa: BLE001
        return []


def _shared_templates() -> list:
    try:
        from tubecli.core import templates as T
        return T.list_templates()
    except Exception:      # noqa: BLE001
        return []


@router.put("/api/v1/public-agents/{agent_id}")
async def put_public_agent(agent_id: str, req: PublicAgentSettings, request: Request):
    _require_owner(request)
    from tubecli.core.agent import agent_manager

    agent = agent_manager.get(agent_id)
    if not agent:
        raise HTTPException(404, "agent not found")
    try:
        # exclude_none: trường không gửi thì không có mặt trong dict, để normalise()
        # biết đường giữ nguyên giá trị cũ.
        saved = public_agents.set_settings(agent_id, req.dict(exclude_none=True), agent.name)
    except ValueError as e:
        # mã ổn định để trang tự dịch (pa.err.<code>)
        return JSONResponse(status_code=400, content={"error": str(e), "code": str(e)})
    return {"ok": True, "public": saved, "cloud_ready": public_agents.cloud_ready()}


@router.post("/api/v1/public/catalog")
async def public_catalog(request: Request):
    """Danh mục giọng của skill (capcut.tts) — CHỈ cloud gọi, chữ ký miền «catalog» (chữ ký
    của invoke không dùng được ở đây và ngược lại). Chỉ đọc, không tính lượt."""
    body = await request.body()
    if len(body) > MAX_INVOKE_BODY:
        return JSONResponse(status_code=413, content={"ok": False, "code": "too_large"})
    why = public_agents.verify_invoke(
        request.headers.get("x-town-ts"),
        request.headers.get("x-town-nonce"),
        request.headers.get("x-town-sig"),
        body,
        domain="catalog",
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
        data = await public_agents.catalog(payload)
    except public_agents.PublicSkillError as e:
        return JSONResponse(status_code=e.status, content={"ok": False, "code": e.code})
    return {"ok": True, **data}


@router.post("/api/v1/public/mcp")
async def public_mcp(request: Request):
    """Trình kết nối claude.ai: cloud chuyển tools/list, tools/call của Claude xuống đây (chữ ký miền «mcp» — chữ ký
    của invoke/catalog/hire không dùng được ở đây và ngược lại). Chủ phải bật công tắc «claude_connector» trên máy."""
    from tubecli.core import claude_connector

    body = await request.body()
    if len(body) > claude_connector.MAX_BODY:
        return JSONResponse(status_code=413, content={"ok": False, "code": "too_large"})
    why = public_agents.verify_invoke(
        request.headers.get("x-town-ts"),
        request.headers.get("x-town-nonce"),
        request.headers.get("x-town-sig"),
        body,
        domain="mcp",
    )
    if why:
        status = 503 if why == "not_configured" else 401
        return JSONResponse(status_code=status, content={"ok": False, "code": why})
    try:
        import json

        payload = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return JSONResponse(status_code=400, content={"ok": False, "code": "bad_request"})
    status, out = await claude_connector.handle(payload, request.app)
    return JSONResponse(status_code=status, content=out)


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


@router.post("/api/v1/public/hire")
async def public_hire_accept(request: Request):
    """CHỈ cloud gọi (chữ ký miền «hire») — nhận một việc thuê từ Chợ mẫu rồi trả lời NGAY;
    video chạy nền bằng dây chuyền content_video, tiến độ máy tự báo về cloud."""
    body = await request.body()
    # 16 MB: việc «video quảng cáo từ ảnh» (pod.video) mang ảnh khách gửi (base64, ≤ 5 tấm × 3 MB) — chữ ký HMAC
    # vẫn kiểm trên TOÀN BỘ thân trước khi đọc nội dung; việc chỉ có chữ thì vẫn nhỏ như cũ.
    if len(body) > 16 * 1024 * 1024:
        return JSONResponse(status_code=413, content={"ok": False, "code": "too_large"})
    why = public_agents.verify_invoke(
        request.headers.get("x-town-ts"), request.headers.get("x-town-nonce"),
        request.headers.get("x-town-sig"), body, domain="hire")
    if why:
        status = 503 if why == "not_configured" else 401
        return JSONResponse(status_code=status, content={"ok": False, "code": why})
    try:
        import json

        payload = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return JSONResponse(status_code=400, content={"ok": False, "code": "bad_request"})
    from tubecli.core import public_hire
    try:
        return await public_hire.receive(payload)
    except public_agents.PublicSkillError as e:
        return JSONResponse(status_code=e.status, content={"ok": False, "code": e.code})


@router.api_route("/api/v1/public/hire/file/{code}/{n}", methods=["GET", "HEAD"])
async def public_hire_file(code: str, n: int, request: Request):
    """Cloud lấy file đã giao của một việc thuê. Chữ ký HMAC miền «hire-file» ký trên CHÍNH
    đường dẫn (cloud: `hire-file.<ts>.<nonce>.<path>`) — cùng nonce/cửa sổ với invoke, nên
    một request bắt được không phát lại được."""
    from fastapi.responses import FileResponse

    path = f"/api/v1/public/hire/file/{code}/{n}"
    why = public_agents.verify_invoke(
        request.headers.get("x-town-ts"), request.headers.get("x-town-nonce"),
        request.headers.get("x-town-sig"), path.encode("utf-8"), domain="hire-file")
    if why:
        status = 503 if why == "not_configured" else 401
        return JSONResponse(status_code=status, content={"ok": False, "code": why})
    from tubecli.core import public_hire

    f = public_hire.file_for(code, n)
    if not f:
        return JSONResponse(status_code=404, content={"ok": False, "code": "file_not_found"})
    return FileResponse(f["path"], media_type=f["type"], filename=f["name"])
