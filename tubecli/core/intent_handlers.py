"""
Intent Handler Registry — MỘT nơi định nghĩa việc cho các intent skip_llm.

Bối cảnh (từ audit): trước đây `IntentResult.skip_llm` được set nhưng KHÔNG
nơi nào đọc; hai đường dispatch (telegram_listener + chat/pipeline) mỗi bên tự
viết lại danh sách `intent_type` bằng tay → thêm intent ở đường này thì đường
kia âm thầm rơi vào LLM. Đây là gốc mọi lệch pha.

Registry này là điểm hội tụ: một intent "thuần văn bản" (chạy xong trả về một
chuỗi, không có side-effect riêng kênh như gửi file) chỉ cần đăng ký MỘT handler
ở đây; cả hai dispatcher gọi `dispatch()` nên hành vi giống hệt nhau, và intent
mới chỉ phải thêm một chỗ.

Handler ký hiệu:  async fn(intent, agent_dict, user_lang) -> Optional[str]
  - trả chuỗi kết quả để hiển thị
  - trả None để dispatcher rơi về xử lý mặc định (LLM)

Các intent có side-effect riêng kênh (gửi file, plan-&-confirm, đổi kênh...) vẫn
để trong dispatcher tương ứng — registry chỉ gom phần THUẦN VĂN BẢN.
"""
import asyncio
import logging
from typing import Optional, Callable, Dict, Awaitable

logger = logging.getLogger(__name__)

# intent_type → handler
INTENT_HANDLERS: Dict[str, Callable[..., Awaitable[Optional[str]]]] = {}
# intent_type → (badge hiển thị, tên skill để lưu history)
INTENT_META: Dict[str, Dict[str, str]] = {}


def register(intent_type: str, badge: str = "", skill_used: str = ""):
    def deco(fn):
        INTENT_HANDLERS[intent_type] = fn
        INTENT_META[intent_type] = {"badge": badge, "skill_used": skill_used}
        return fn
    return deco


def has_handler(intent_type: str) -> bool:
    return intent_type in INTENT_HANDLERS


def meta_for(intent_type: str) -> Dict[str, str]:
    return INTENT_META.get(intent_type, {"badge": "", "skill_used": ""})


async def dispatch(intent, agent_dict: dict, user_lang: str = "vi") -> Optional[str]:
    """Gọi handler đã đăng ký cho intent. Trả None nếu không có handler hoặc
    handler tự bỏ (để dispatcher rơi về LLM)."""
    fn = INTENT_HANDLERS.get(getattr(intent, "intent_type", ""))
    if not fn:
        return None
    try:
        return await fn(intent, agent_dict, user_lang)
    except Exception as e:
        logger.error(f"[IntentHandlers] {getattr(intent,'intent_type','?')} failed: {e}",
                     exc_info=True)
        return None  # rơi về LLM thay vì trả rỗng


# ══════════════════════════════════════════════════════════════════
#  HANDLERS (thuần văn bản, dùng chung 2 kênh)
# ══════════════════════════════════════════════════════════════════

@register("read_page", badge="🌐 Web Reader", skill_used="Web Reader")
async def _read_page(intent, agent_dict, user_lang) -> Optional[str]:
    """"xem trang <url> tóm tắt" → đọc thẳng trang đó rồi tóm tắt."""
    data = getattr(intent, "extracted_data", None) or {}
    url = data.get("url", "")
    task = data.get("task", "")
    if not url:
        return None
    from tubecli.core.web_reader import read_and_summarize
    return await asyncio.to_thread(read_and_summarize, url, task, agent_dict, user_lang)


@register("channel_analyze", badge="📊 Analyze Channel", skill_used="Analyze Channel")
async def _channel_analyze(intent, agent_dict, user_lang) -> Optional[str]:
    """"vào kênh <url> phân tích + đề xuất kênh tương tự" → chạy skill Analyze
    Channel deterministic (extension_action, không cần LLM chọn)."""
    data = getattr(intent, "extracted_data", None) or {}
    url = data.get("url", "")
    matched = getattr(intent, "matched_skills", None) or []
    sid = matched[0] if matched else None
    if not url or not sid:
        return "⚠️ Chưa gán skill Analyze Channel cho agent, hoặc thiếu URL kênh."
    from tubecli.core.skill import skill_manager
    from tubecli.core.brain import AgentBrain
    skill = skill_manager.get(sid)
    if not skill:
        return "⚠️ Không tìm thấy skill Analyze Channel."
    try:
        reply = await asyncio.wait_for(
            AgentBrain.autonomous_run(message=url, agent=agent_dict, skill=skill.to_dict()),
            timeout=240,
        )
        return reply
    except asyncio.TimeoutError:
        return "⏰ Phân tích kênh chạy quá lâu (>4 phút)."


@register("scraped_data", badge="📚 Dữ liệu đã cào", skill_used="Scraped Data")
async def _scraped_data(intent, agent_dict, user_lang) -> Optional[str]:
    """"lấy dữ liệu đã cào hôm nay" → đọc thẳng kho, không gọi LLM.

    Kho nằm trên đĩa và câu hỏi chỉ là lọc + sắp xếp, nên để LLM soạn lại là
    vừa tốn token vừa có nguy cơ nó bịa tiêu đề. Agent nào hỏi thì chỉ thấy
    phần của agent đó — phạm vi lấy từ allowed_profiles như tab Lịch sử.
    """
    from tubecli.core.scraped_query import answer

    data = getattr(intent, "extracted_data", None) or {}
    text = data.get("query", "") or data.get("text", "")
    agent_id = (agent_dict or {}).get("id")
    profiles = (agent_dict or {}).get("allowed_profiles") or []
    return await asyncio.to_thread(
        answer, text, agent_id=agent_id, allowed_profiles=profiles,
        with_content=bool(data.get("with_content")),
    )


@register("content_video", badge="🎬 Content Video", skill_used="Content Video")
async def _content_video(intent, agent_dict, user_lang) -> Optional[str]:
    """"làm video từ những gì đã đọc hôm nay" → xếp MỘT task Codex rồi trả thẻ ngay.

    Việc nặng (kịch bản, Content Studio, ffmpeg) chạy nền trong codex worker;
    lượt chat này không đợi và không tốn token LLM. Agent lấy từ agent_dict —
    tức agent đang nói chuyện — nên chỉ đọc được kho của chính nó. Trả None khi
    extension chưa có để dispatcher rơi về LLM như mọi handler khác.
    """
    agent_id = str((agent_dict or {}).get("id") or "")
    if not agent_id:
        return None
    try:
        from tubecli.extensions.content_video.pipeline import create_digest_task, queued_reply
    except ImportError:
        return None
    data = getattr(intent, "extracted_data", None) or {}
    # target_words là "video 10 phút" đã đổi ra số chữ ở router. Trước đây tuple
    # này thiếu nó nên lời hẹn độ dài rơi ngay tại đây: pipeline lặng lẽ lấy độ
    # dài của mẫu (hoặc mặc định ~2 phút) và thẻ kết quả ghi "from the template".
    options = {k: data[k] for k in ("day", "aspect_ratio", "preset", "target_words", "language")
               if data.get(k)}
    # created_by="user": the human typed the command verbatim, so the task
    # follows the codex auto-approve policy exactly like a skill command.
    task = await asyncio.to_thread(
        create_digest_task, agent_id, options, "user", {"agent_id": agent_id},
        list(data.get("sources") or []),
    )
    return queued_reply(task)
