"""
Content Video — FastAPI routes.

Three entry points, all of which end in the same codex task:
  GET  /capabilities      what can run right now (extensions + Content Studio's own answer)
  POST /plan              which steps would run for these options
  POST /run               queue a content video for an agent

These are owner routes. /api/v1/content-video is not in the guest middleware's
sensitive list, so the gate is applied here: a shared-workspace guest never
gets to spend an agent's corpus and keys.
"""
import asyncio
import logging
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger("ContentVideo")

router = APIRouter(prefix="/api/v1/content-video", tags=["content-video"])


def _deny_guests(request: Request) -> None:
    if getattr(request.state, "guest_scope", None):
        raise HTTPException(403, "Not available in a shared workspace.")


class PlanRequest(BaseModel):
    options: Dict[str, Any] = {}


class RunRequest(BaseModel):
    # Rỗng khi lời gọi tới từ SKILL: brain gắn agent_id vào payload nhờ cờ
    # `with_agent` trong workflow_data, nên ở đây chỉ cần cho phép rỗng rồi báo
    # lỗi tử tế, thay vì để Pydantic ném 422 với mảng validation.
    agent_id: str = ""
    # Kỹ năng extension_action chỉ gửi được MỘT chuỗi. Nhận nó ở đây và tự rút
    # link ra làm nguồn — cùng cách video_studio làm cho các job một-chuỗi.
    input: str = ""
    agent_name: str = ""
    sources: List[str] = []
    options: Dict[str, Any] = {}
    created_by: str = ""
    origin: Optional[Dict[str, Any]] = None
    # Nội dung DÁN TAY từ cửa sổ "Nhiệm vụ mới" của Codex — thay cho kho đã
    # đọc/đã xem của agent. Có nó thì agent chỉ còn là "ai viết": model của nó.
    content: str = ""
    # True: dừng ở kịch bản cho người duyệt (hai chặng). False: chạy thẳng tới mp4.
    review: bool = True


@router.get("/capabilities")
async def capabilities(request: Request):
    _deny_guests(request)
    from tubecli.extensions.content_video.capabilities import capability_report

    return {"text": await asyncio.to_thread(capability_report, True)}


@router.post("/plan")
async def plan_route(req: PlanRequest, request: Request):
    _deny_guests(request)
    from tubecli.extensions.content_video.pipeline import describe_plan, plan

    return {"steps": plan(req.options), "text": describe_plan(req.options)}


_URL_RE = re.compile(r"https?://\S+")


@router.post("/run")
async def run_route(req: RunRequest, request: Request):
    """Queue the pipeline as a codex task for one agent.

    Two callers, one endpoint: the canvas (structured body) and the agent's
    "🎬 Content Video" skill (one string + the agent the brain attached).
    """
    _deny_guests(request)
    agent_id = (req.agent_id or "").strip()
    content = (req.content or "").strip()
    if content and not agent_id:
        # Nội dung dán tay KHÔNG cần kho của agent, nhưng vẫn cần một agent để
        # VIẾT — câu "chạy từ khung chat của agent" bên dưới sẽ chỉ sai đường.
        raise HTTPException(400, "Choose the agent whose AI model writes the script.")
    if not agent_id:
        # Câu trả lời phải là câu NGƯỜI đọc được: brain chuyển nguyên trường
        # `report` vào chat, còn 400 thì chỉ thành một dòng lỗi kỹ thuật.
        return {"status": "need_agent",
                "report": ("Kỹ năng này làm video từ kho đã đọc/đã xem của CHÍNH agent, nên "
                           "phải chạy từ khung chat của một agent. Mở agent rồi nhắc lại giúp tôi.")}
    try:
        from tubecli.extensions.content_video.pipeline import (
            SOURCE_TEXT_MAX, create_auto_task, create_digest_task, create_plan_task, queued_reply)
    except ImportError:
        raise HTTPException(400, "The codex extension is required to run pipelines.")
    if len(content) > SOURCE_TEXT_MAX:
        raise HTTPException(400, f"The content is {len(content):,} characters; the limit is "
                                 f"{SOURCE_TEXT_MAX:,}. Split it into several videos.")

    # Link nằm lẫn trong câu người dùng gõ → thành nguồn cào thêm.
    sources = list(req.sources or [])
    for u in _URL_RE.findall(req.input or ""):
        u = u.rstrip(".,;?!)")
        if u not in sources:
            sources.append(u)

    origin = dict(req.origin or {})
    origin.setdefault("agent_id", agent_id)
    # Lời gọi đi qua skill là MODEL tự quyết → created_by="brain", tức chịu đúng
    # luật duyệt của codex ("AI đề xuất, người duyệt"). Canvas gửi created_by
    # tường minh thì giữ nguyên.
    created_by = (req.created_by or "").strip() or ("brain" if req.input else "user")
    options = dict(req.options or {})
    if content:
        options["source_text"] = content
    # Người bấm "Tạo video" trong cửa sổ Codex CHÍNH LÀ lời duyệt để bắt đầu:
    # cổng duyệt-trước-khi-chạy chỉ bắt họ bấm thêm lần nữa cho cùng một ý. Cổng
    # có nghĩa là cổng SAU kịch bản (review=True). Lời gọi từ skill/brain thì
    # vẫn theo luật duyệt của codex như cũ.
    label = "Video from content"
    approval = False if created_by == "user" else None
    try:
        if not content:
            # Đường cũ, GIỮ NGUYÊN tên hàm và từng đối số. Skill, canvas và test
            # vẫn chặn đúng cái tên create_digest_task: gọi sang tên khác là lọt
            # qua mock của họ và tạo task THẬT trên bảng Codex đang chạy.
            task = await asyncio.to_thread(
                create_digest_task, agent_id, req.options, created_by, origin, sources)
        elif not req.review:
            task = await asyncio.to_thread(lambda: create_auto_task(
                agent_id, options, created_by=created_by, origin=origin,
                job_label=label, sources=sources))
        else:
            task = await asyncio.to_thread(lambda: create_plan_task(
                agent_id, options, created_by=created_by, origin=origin, sources=sources,
                job_label=label, approval_required=approval))
    except Exception as e:
        logger.error(f"[ContentVideo] queueing failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))
    return {"status": "queued", "task": task, "report": queued_reply(task)}
