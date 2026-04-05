import os
import logging
from typing import Dict, Any, Optional

from tubecli.core.extension_manager import Extension
from tubecli.extensions.universal_tracker.tracker import universal_tracker_engine

logger = logging.getLogger("UniversalTrackerExtension")


class UniversalTrackerExtension(Extension):
    name = "universal_tracker"
    version = "1.0.0"
    description = "Cross-platform background tracker for contents (YouTube, Douyin) that triggers AI teams."
    author = "TubeCreate"
    extension_type = "system"

    def on_enable(self):
        logger.info("Universal Tracker extension enabled")

    def on_disable(self):
        universal_tracker_engine.stop()

    def get_routes(self):
        from tubecli.extensions.universal_tracker.routes import router
        return router

    def get_skill_md(self) -> Optional[str]:
        skill_path = os.path.join(os.path.dirname(__file__), "SKILL.md")
        if os.path.exists(skill_path):
            with open(skill_path, "r", encoding="utf-8") as f:
                return f.read()
        return None

    def get_telegram_actions(self):
        return {
            "add_tracker": self._action_add_tracker,
            "list_trackers": self._action_list_trackers,
            "remove_tracker": self._action_remove_tracker,
        }

    async def _action_add_tracker(self, action_data: dict, context: dict) -> str:
        platform = action_data.get("platform", "")
        url = action_data.get("url", "") or action_data.get("source_url", "")

        # Support interval in hours or minutes
        interval_minutes = int(action_data.get("interval_minutes", 0))
        if not interval_minutes:
            interval_hours = action_data.get("interval_hours", 0)
            if interval_hours:
                interval_minutes = int(float(interval_hours) * 60)
            else:
                interval_minutes = 60

        target_team_id = action_data.get("target_team_id", "")
        instruction = action_data.get("instruction", "")

        # Auto-detect platform from URL
        if not platform:
            if "douyin" in url or "iesdouyin" in url:
                platform = "douyin"
            elif "tiktok" in url:
                platform = "tiktok"
            elif "youtube" in url or "youtu.be" in url:
                platform = "youtube"
            else:
                platform = "website"

        # Accept target channel info for instruction enrichment
        target_channel_id = action_data.get("target_channel_id", "")
        email = action_data.get("email", "")
        if target_channel_id and not instruction:
            instruction = f"Upload lên kênh YouTube {target_channel_id}"
            if email:
                instruction += f" (tài khoản: {email})"

        if not url:
            return "❌ Thiếu thông số url. Hãy cung cấp URL kênh cần theo dõi."

        job = universal_tracker_engine.add_tracker(
            platform=platform,
            url=url,
            interval_minutes=interval_minutes,
            target_team_id=target_team_id,
            instruction=instruction,
        )

        hours_display = interval_minutes / 60
        msg = f"✅ Đã thêm cấu hình theo dõi mới!\n"
        msg += f"📡 Nguồn: {platform.upper()}\n"
        msg += f"🔗 URL: {url}\n"
        msg += f"⏱️ Chu kỳ: {hours_display:.0f} giờ ({interval_minutes} phút)\n"
        if target_team_id:
            msg += f"🤖 Team xử lý: {target_team_id}\n"
        if instruction:
            msg += f"📝 Ghi chú: {instruction}\n"
        msg += f"🆔 Tracker ID: {job.id}"
        return msg

    async def _action_list_trackers(self, action_data: dict, context: dict) -> str:
        jobs = universal_tracker_engine.list_trackers()
        if not jobs:
            return "📡 Hiện tại không có chương trình theo dõi nào đang chạy ngầm."

        msg = f"📋 Danh sách các Tracker ({len(jobs)}):\n\n"
        for j in jobs:
            msg += f"🔹 ID: {j['id']} ({j['status']})\n"
            msg += f"   - Nguồn: {j['platform'].upper()} | {j['url']}\n"
            msg += f"   - Chu kỳ: {j['interval_minutes']} phút\n"
            if j["target_team_id"]:
                msg += f"   - Kích hoạt Team: {j['target_team_id']}\n"
            msg += "\n"
        return msg

    async def _action_remove_tracker(self, action_data: dict, context: dict) -> str:
        tracker_id = action_data.get("tracker_id", "")
        if not tracker_id:
            return "❌ Thiếu tracker_id."

        if universal_tracker_engine.remove_tracker(tracker_id):
            return f"✅ Đã xoá thành công Tracker {tracker_id}."
        else:
            return f"❌ Không tìm thấy Tracker ID '{tracker_id}'."
