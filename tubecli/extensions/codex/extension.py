"""
Codex — mission control for agentic work.

A durable, approval-gated task board that the user AND the AI brain can both
write to: create a task, delegate it to an agent or team, watch it run, approve
or reject it, and review the result — from the web board, from Telegram, or
over HTTP.
"""
import logging
import os
from typing import Any, Dict, Optional

from tubecli.core.extension_manager import Extension

logger = logging.getLogger("Codex")

SKILL_NAME = "Codex"
SKILL_COMMANDS = [
    "codex",
    "tasks",
    "nhiệm vụ",
    "approve",
    "reject",
    "retry",
    "accept",
    "duyệt",
    "từ chối",
]


class CodexExtension(Extension):
    name = "codex"
    version = "1.0.0"
    description = "Mission control — giao việc cho agent, duyệt, theo dõi và nghiệm thu kết quả"
    author = "TubeCreate"
    extension_type = "system"

    def __init__(self):
        super().__init__()
        self.extension_dir = os.path.dirname(os.path.abspath(__file__))

    # ── Lifecycle ────────────────────────────────────────────────

    def on_enable(self):
        """Idempotent: on_enable re-fires on every discovery pass, so this must
        never spawn threads. The queue worker is started from the router's
        startup event instead (routes.py)."""
        self._register_skill()
        logger.info("Codex extension enabled")

    def on_disable(self):
        try:
            from tubecli.extensions.codex.worker import codex_worker

            codex_worker.stop()
        except Exception:
            pass

    def _register_skill(self):
        """Register the Codex skill so IntentRouter._match_skill_command
        (core/intent_router.py:446) can route 'approve 3' with zero LLM tokens.

        Extension.get_skills() is never called by ExtensionManager, so
        registration goes straight through skill_manager — the same approach
        browser_scripts uses (extensions/browser_scripts/extension.py:60-127).
        """
        try:
            from tubecli.core.skill import skill_manager

            payload = {
                "description": (
                    "Codex mission control: xem, duyệt, từ chối, huỷ và chạy lại các task "
                    "được giao cho AI agent. Dùng cho 'codex', 'approve 3', 'reject 3'."
                ),
                "skill_type": "Extension Skill",
                "skill_format": "extension_action",
                "commands": SKILL_COMMANDS,
                "input_hint": "codex | codex <số> | approve <số> | reject <số> | retry <số>",
                "when_to_use": "Khi người dùng muốn xem hoặc quyết định về task trong Codex.",
                "workflow_data": {
                    "extension": "codex",
                    "endpoint": "/api/v1/codex/command",
                    "method": "POST",
                    "input_key": "text",
                    "payload": {"actor": "user:telegram"},
                },
            }
            existing = skill_manager.find_by_name(SKILL_NAME)
            if existing:
                skill_manager.update(existing.id, **payload)
            else:
                skill_manager.create(name=SKILL_NAME, **payload)
        except Exception as e:
            logger.warning(f"Could not register the Codex skill: {e}")

    # ── Extension points ─────────────────────────────────────────

    def get_routes(self):
        from tubecli.extensions.codex.routes import router, ui_router

        return [ui_router, router]

    def get_commands(self):
        try:
            from tubecli.extensions.codex.commands import codex_group

            return codex_group
        except Exception as e:
            logger.warning(f"Could not load Codex CLI commands: {e}")
            return None

    def get_telegram_actions(self) -> Dict[str, Any]:
        from tubecli.extensions.codex.telegram import get_telegram_actions

        return get_telegram_actions()

    def get_ui_static_dir(self) -> Optional[str]:
        return os.path.join(self.extension_dir, "static")

    def get_skill_md(self) -> Optional[str]:
        skill_path = os.path.join(self.extension_dir, "SKILL.md")
        if os.path.exists(skill_path):
            with open(skill_path, "r", encoding="utf-8") as f:
                return f.read()
        return None


extension_instance = CodexExtension()
