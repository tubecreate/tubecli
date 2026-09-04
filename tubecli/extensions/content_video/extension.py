"""
Content Video — an agent turns what it read and watched into a video.

The pipeline itself (pipeline.py) is hosted on codex like video_studio's reup:
durable, approval-gated, stepped, cancellable, visible on /codex, the chat
card and Telegram. This module is the thin shell around it: registration,
the routes, and the verbs an agent can emit from chat or Telegram.
"""
import logging
import os
import re
from typing import Any, Dict, List, Optional

from tubecli.core.extension_manager import Extension

logger = logging.getLogger("ContentVideo")

# Options a verb may pass straight through to the pipeline.
_PASSTHROUGH = ("day", "aspect_ratio", "style", "title", "tts_voice", "max_items",
                "max_videos", "language", "target_words", "preset")


def _urls(value: Any) -> List[str]:
    if isinstance(value, str):
        value = re.split(r"[\s,]+", value)
    return [str(v).strip() for v in (value or []) if str(v).strip().startswith("http")]


class ContentVideoExtension(Extension):
    name = "content_video"
    version = "1.0.0"
    description = "Agent gom những gì đã đọc/xem → kịch bản → Content Studio → video, chạy trên Codex"
    author = "TubeCreate"
    extension_type = "system"

    def __init__(self):
        super().__init__()
        self.extension_dir = os.path.dirname(os.path.abspath(__file__))

    def on_enable(self):
        """Idempotent — on_enable re-fires on every discovery pass. No threads here."""
        # Content Studio's engine shells out to a bare "ffmpeg"; a server started
        # from a launcher inherits a PATH that often has none. Same fix as video_studio.
        try:
            from tubecli.extensions.video_studio.ffmpeg_utils import ensure_on_path

            ensure_on_path()
        except Exception as e:
            logger.warning(f"[ContentVideo] could not make ffmpeg discoverable: {e}")

        # Stage 2 starts when the reviewer ACCEPTS the script: codex calls this
        # hook. Registering is idempotent, so on_enable re-firing is harmless.
        try:
            from tubecli.extensions.codex.manager import codex_manager
            from tubecli.extensions.content_video.pipeline import KIND_PLAN, create_render_task

            codex_manager.on_accept(KIND_PLAN, create_render_task)
        except Exception as e:
            logger.warning(f"[ContentVideo] could not register the accept hook: {e}")

        # Một chip trong tab Kỹ năng của agent. Verb thì vô hình — nó nổ khi model
        # quyết định, nên chủ máy không nhìn thấy agent có khả năng này và cũng
        # không tắt được. Skill là một dòng trong kho: hiện thành chip, chủ tự tick
        # cho từng agent, và `commands` sửa được ngay trên giao diện.
        try:
            from tubecli.extensions.content_video.skills import register_skills

            stats = register_skills()
            logger.info(f"[ContentVideo] skills {stats}")
        except Exception as e:
            logger.warning(f"[ContentVideo] could not register skills: {e}")

    def get_routes(self):
        from tubecli.extensions.content_video.routes import router

        return router

    def get_skill_md(self) -> Optional[str]:
        path = os.path.join(self.extension_dir, "SKILL.md")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        return None

    def get_telegram_actions(self) -> Dict[str, Any]:
        return {
            "content_video_run": self._action_run,
            "content_video_capabilities": self._action_capabilities,
        }

    # ── Verbs (flat payloads only) ───────────────────────────────

    async def _action_capabilities(self, action_data: dict, context: dict) -> str:
        import asyncio

        from tubecli.extensions.content_video.capabilities import capability_report

        return await asyncio.to_thread(capability_report, True)

    async def _action_run(self, action_data: dict, context: dict) -> str:
        """Queue a content video for the agent that is speaking.

        The agent comes from the dispatcher's context, never from the model's
        JSON: a verb may only spend an agent's corpus and keys on that agent's
        own behalf.
        """
        import asyncio

        from tubecli.extensions.content_video.pipeline import create_digest_task, queued_reply

        agent = context.get("agent") or {}
        agent_id = str(agent.get("id") or "")
        if not agent_id:
            return "❌ No agent in this conversation — run this from an agent's chat."

        sources = _urls(action_data.get("sources") or action_data.get("urls") or action_data.get("url"))
        options = {k: action_data[k] for k in _PASSTHROUGH if action_data.get(k) not in (None, "")}
        origin = {
            "chat_id": context.get("chat_id", ""),
            "token": context.get("token", ""),
            "agent_id": agent_id,
            "group_ids": [str(g) for g in (context.get("group_ids") or [])],
        }
        try:
            # codex_manager takes an RLock and writes a file: keep it off the loop.
            task = await asyncio.to_thread(
                create_digest_task, agent_id, options, "brain", origin, sources)
        except Exception as e:
            logger.error(f"[ContentVideo] queueing failed: {e}", exc_info=True)
            return f"❌ Could not queue the content video: {e}"
        return queued_reply(task)


extension_instance = ContentVideoExtension()
