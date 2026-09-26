"""/api/v1/ai — gọi THỬ một model chat (Flow → nút «Thử gọi» trong bảng chọn AI mặc định).

Vì sao (26/9/2026): bảng chọn model chấm xanh theo KHOÁ và DANH MỤC (khoá còn hiệu lực, 9Router liệt kê model) — nhưng
ag/gemini-3.8-flash vẫn trả 403 khi gọi thật, task hỏng ở bước viết kịch bản mới biết. Gọi thử phải đi đúng đường agent
đi (AgentBrain._call_llm: cùng cách chọn provider, cùng kho khoá), hỏi một câu 1 từ, trả về sống/chết + lý do.
Brain trả LỖI bằng CHUỖI «[… Error] …» chứ không ném — ở đây nhận diện chuỗi ấy là hỏng.
"""
from __future__ import annotations

import asyncio
import re
import time

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/ai", tags=["ai"])

_LLM_ERROR_RE = re.compile(r"^\[[\w .-]*Error\]", re.I)
_PROBE = [{"role": "user", "content": "Reply with the single word OK."}]
_MAX_MSG = 400


class TestRequest(BaseModel):
    model: str = ""         # rỗng = model mặc định của máy (resolve_browser_ai_model)
    provider: str = ""      # rỗng = đoán theo tên như agent


def is_llm_error(text: str) -> bool:
    return bool(_LLM_ERROR_RE.match((text or "").lstrip()))


def probe_result(model: str, reply, seconds: float) -> dict:
    """Kết luận từ câu trả lời của brain: chuỗi lỗi / rỗng → hỏng, còn lại → sống (kèm câu trả lời cắt ngắn)."""
    text = str(reply or "").strip()
    if not text:
        return {"ok": False, "model": model, "seconds": seconds, "message": "The model returned an empty reply."}
    if is_llm_error(text):
        return {"ok": False, "model": model, "seconds": seconds, "message": text[:_MAX_MSG]}
    return {"ok": True, "model": model, "seconds": seconds, "reply": text[:80]}


def run_probe(model: str, provider: str = "") -> dict:
    """Gọi thử đồng bộ (chạy trong thread). Không bao giờ ném: lỗi thành {"ok": False, "message"}."""
    from tubecli.core.brain import AgentBrain

    agent = {"model": model}
    if provider:
        agent["provider"] = provider
    t0 = time.time()
    try:
        reply = AgentBrain._call_llm(agent, list(_PROBE), temperature=0.0, max_tokens=8)
    except Exception as e:    # noqa: BLE001 — lý do hỏng là thứ người dùng cần đọc
        return {"ok": False, "model": model, "seconds": round(time.time() - t0, 1), "message": str(e)[:_MAX_MSG] or type(e).__name__}
    return probe_result(model, reply, round(time.time() - t0, 1))


@router.post("/test")
async def test_model(req: TestRequest):
    model = str(req.model or "").strip()
    if not model:
        from tubecli.config import resolve_browser_ai_model
        model = str(resolve_browser_ai_model({}) or "").strip()
    if not model:
        return {"ok": False, "model": "", "seconds": 0, "message": "No model to test — pick a model first."}
    return await asyncio.to_thread(run_probe, model, str(req.provider or "").strip().lower())
