"""
Video Studio — the pieces of a reup workflow that tubecli did not have yet.

Ports two engines from ReupDouyin (detecting and erasing burned-in subtitles,
and channel analysis), adds the approval-gated reup pipeline on top of codex,
and — because the rest of the video chain lives in optional external extensions
— tells the user exactly what to install from the Market when a job cannot run.
"""
import logging
import os
from typing import Any, Dict, Optional

from tubecli.core.extension_manager import Extension

logger = logging.getLogger("VideoStudio")


class VideoStudioExtension(Extension):
    name = "video_studio"
    version = "1.0.0"
    description = "Xoá sub gốc (nội suy), phân tích kênh và pipeline reup cho Video Agent"
    author = "TubeCreate"
    extension_type = "system"

    def __init__(self):
        super().__init__()
        self.extension_dir = os.path.dirname(os.path.abspath(__file__))

    def on_enable(self):
        """Idempotent — on_enable re-fires on every discovery pass."""
        try:
            from tubecli.extensions.video_studio.skills import register_skills

            stats = register_skills()
            logger.info(f"Video Studio enabled; skills {stats}")
        except Exception as e:
            logger.warning(f"Could not register Video Studio skills: {e}")

    def get_routes(self):
        from tubecli.extensions.video_studio.routes import router

        return router

    def get_skill_md(self) -> Optional[str]:
        path = os.path.join(self.extension_dir, "SKILL.md")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        return None

    def get_telegram_actions(self) -> Dict[str, Any]:
        return {
            "video_capabilities": self._action_capabilities,
            "analyze_channel": self._action_analyze_channel,
            "remove_hardsub": self._action_remove_hardsub,
            "reup_video": self._action_reup,
        }

    # ── Telegram actions (flat payloads only) ────────────────────

    async def _action_capabilities(self, action_data: dict, context: dict) -> str:
        from tubecli.extensions.video_studio.capabilities import capability_report

        return capability_report()

    async def _action_analyze_channel(self, action_data: dict, context: dict) -> str:
        import asyncio

        from tubecli.extensions.video_studio.capabilities import guidance_for

        url = (action_data.get("url") or action_data.get("channel") or "").strip()
        if not url:
            return "❌ Missing `url` — send the channel link."
        gap = guidance_for(["channel_analysis"])
        if gap:
            return gap
        from tubecli.extensions.video_studio.channel_analysis import (
            analyze_channel, fetch_channel_videos, ideas_to_text,
        )

        fetched = await asyncio.to_thread(fetch_channel_videos, url, 40)
        if not fetched.get("ok"):
            return f"❌ {fetched.get('message')}"
        result = await asyncio.to_thread(
            analyze_channel, fetched["videos"], fetched.get("channel", ""))
        if not result.get("ok"):
            return f"❌ {result.get('message')}"
        return ideas_to_text(result.get("data") or {}, fetched.get("channel", ""))

    async def _action_remove_hardsub(self, action_data: dict, context: dict) -> str:
        import asyncio

        from tubecli.extensions.video_studio.capabilities import guidance_for

        path = (action_data.get("video_path") or action_data.get("path") or "").strip()
        if not path:
            return "❌ Missing `video_path`."
        gap = guidance_for(["remove_hardsub"])
        if gap:
            return gap
        from tubecli.extensions.video_studio.region_detect import (
            cover_region, detect_subtitle_region,
        )

        info = await asyncio.to_thread(detect_subtitle_region, path, 6)
        if not info.get("found"):
            return "ℹ️ No burned-in subtitles found — nothing to cover."
        from tubecli.config import EXTENSIONS_DATA_DIR

        outdir = os.path.join(str(EXTENSIONS_DATA_DIR), "video_studio", "outputs")
        os.makedirs(outdir, exist_ok=True)
        out = os.path.join(
            outdir, f"{os.path.splitext(os.path.basename(path))[0]}_clean.mp4")
        mode = action_data.get("mode") or "delogo"
        result = await asyncio.to_thread(cover_region, path, info["box"], out, mode)
        return f"✅ Original subtitles covered ({mode}):\n`{result}`"

    async def _action_reup(self, action_data: dict, context: dict) -> str:
        import asyncio

        url = (action_data.get("url") or "").strip()
        if not url:
            return "❌ Missing `url`."
        from tubecli.extensions.video_studio.pipeline import create_codex_task

        origin = {"chat_id": context.get("chat_id", ""),
                  "token": context.get("token", "")}
        try:
            task = await asyncio.to_thread(create_codex_task, url, {}, "brain", origin)
        except Exception as e:
            return f"❌ Could not queue the reup: {e}"
        return (f"🚀 Reup queued as *Codex #{task['seq']}* — awaiting your approval.\n"
                f"Reply `approve {task['seq']}` to start.")


extension_instance = VideoStudioExtension()
