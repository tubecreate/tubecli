"""
AI Arena Extension â€” Entry point.
"""
import logging
import os

try:
    from tubecli.core.extension_manager import Extension
    from tubecli.config import DATA_DIR
except ImportError:
    from TubeCLI.core.extension_manager import Extension
    DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data")

logger = logging.getLogger("AIArenaExtension")


class AIArenaExtension(Extension):
    name = "ai_arena"
    description = "ðŸŽ® AI Arena â€” Äáº¥u trÆ°á»ng AI: Cá» vua, Snake Arena & more"
    version = "1.1.0"
    enabled_by_default = True

    def __init__(self):
        super().__init__()
        self._game_manager = None

    def setup(self):
        logger.info("AI Arena Extension loaded")

    def on_enable(self):
        """Initialize GameManager when extension is enabled."""
        try:
            from game_manager import GameManager
            self._game_manager = GameManager(str(DATA_DIR))
            logger.info("✅ AI Arena GameManager initialized")
        except Exception as e:
            logger.error(f"Failed to initialize GameManager: {e}")

    def on_disable(self):
        self._game_manager = None

    def get_routes(self):
        try:
            import arena_routes
            if self._game_manager:
                arena_routes.set_game_manager(self._game_manager)
            return arena_routes.main_router
        except Exception as e:
            logger.error(f"Failed to load AI Arena routes: {e}")
            import traceback
            traceback.print_exc()
            return None

    def get_skill_md(self):
        if self.extension_dir:
            path = os.path.join(self.extension_dir, "SKILL.md")
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        return f.read()
                except Exception:
                    pass
        return None
