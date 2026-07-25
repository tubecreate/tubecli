"""
Chat — a single place to talk to the whole system.

Multi-session conversations (like ChatGPT) on top of the same routing the
Telegram bot uses, so anything the bot can do the browser can do too:
intent routing, skill selection, extension actions (codex, tracker, calendar…).
"""
import logging
import os
from typing import Optional

from tubecli.core.extension_manager import Extension

logger = logging.getLogger("Chat")


class ChatExtension(Extension):
    name = "chat"
    version = "1.0.0"
    description = "Giao diện chat tổng — trò chuyện với mọi agent, có lịch sử hội thoại"
    author = "TubeCreate"
    extension_type = "system"

    def __init__(self):
        super().__init__()
        self.extension_dir = os.path.dirname(os.path.abspath(__file__))

    def on_enable(self):
        logger.info("Chat extension enabled")

    def get_routes(self):
        from tubecli.extensions.chat.routes import router, ui_router

        return [ui_router, router]

    def get_ui_static_dir(self) -> Optional[str]:
        return os.path.join(self.extension_dir, "static")


extension_instance = ChatExtension()
