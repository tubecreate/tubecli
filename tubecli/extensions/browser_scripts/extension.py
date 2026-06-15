"""
Script Studio Extension — Visual browser automation script editor & manager.
"""
import os
import sys
import logging
import importlib.util

try:
    from tubecli.core.extension_manager import Extension
except ImportError:
    from TubeCLI.core.extension_manager import Extension

logger = logging.getLogger("ScriptStudio")


class BrowserScriptsExtension(Extension):
    name = "browser_scripts"
    version = "1.0.0"
    description = "Script Studio — Visual browser automation script editor"
    author = "TubeCreate"
    extension_type = "built-in"

    def on_enable(self):
        logger.info("Script Studio extension enabled")
        self._init_database()
        self._register_skill()

    def _init_database(self):
        """Initialize SQLite database."""
        try:
            from tubecli.config import DATA_DIR
            db_dir = os.path.join(str(DATA_DIR), "extensions_data", "browser_scripts")
            os.makedirs(db_dir, exist_ok=True)
            db_path = os.path.join(db_dir, "scripts.db")
            
            # Also init the JSON Store here
            try:
                from .db.script_store import ScriptStore
                ScriptStore.get_instance(db_dir)
            except Exception as e:
                logger.error(f"Failed to init JSON store: {e}")

            ext_dir = self.extension_dir or os.path.dirname(os.path.abspath(__file__))
            db_module_path = os.path.join(ext_dir, "db", "database.py")
            spec = importlib.util.spec_from_file_location("script_studio_db", db_module_path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.ScriptDatabase.get_instance(db_path)
            logger.info(f"Script Studio DB initialized: {db_path}")
        except Exception as e:
            logger.error(f"Failed to init Script Studio database: {e}")

    def _register_skill(self):
        """Register Script Studio skill for chatbot routing."""
        try:
            from tubecli.core.skill import skill_manager
            existing = skill_manager.find_by_name("Script Studio")
            if existing:
                return

            skill_manager.create(
                name="Script Studio",
                description=(
                    "Script Studio — Quản lý & chỉnh sửa trực quan các script điều khiển browser. "
                    "Tạo/chỉnh sửa kịch bản tự động hóa browser bằng giao diện kéo-thả. "
                    "Hỗ trợ Playwright, element picker, biến động, retry logic."
                ),
                skill_type="Extension Skill",
                commands=[
                    "script studio", "browser script", "automation script",
                    "tạo script", "quản lý script", "chỉnh sửa script",
                    "browser automation", "playwright script",
                ],
                workflow_data={
                    "extension": "browser_scripts",
                    "action": "open_studio",
                    "sop": (
                        "1. Mở Script Studio tại /script-studio\n"
                        "2. Tạo script mới hoặc import từ file .js\n"
                        "3. Thêm/chỉnh sửa steps bằng visual editor\n"
                        "4. Dùng Element Picker để chọn element trên browser\n"
                        "5. Test từng step hoặc chạy toàn bộ script"
                    ),
                },
            )
            logger.info("✅ Script Studio skill registered.")
        except Exception as e:
            logger.warning(f"Could not register Script Studio skill: {e}")

    def get_routes(self):
        """Load and return FastAPI routers (API + static UI)."""
        try:
            ext_dir = self.extension_dir or os.path.dirname(os.path.abspath(__file__))
            if ext_dir not in sys.path:
                sys.path.insert(0, ext_dir)

            routes_file = os.path.join(ext_dir, "script_routes.py")
            spec = importlib.util.spec_from_file_location("script_studio_routes", routes_file)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            # Merge API + UI routers
            from fastapi import APIRouter
            combined = APIRouter()
            api_router = getattr(mod, "router", None)
            ui_router = getattr(mod, "ui_router", None)
            if api_router:
                combined.include_router(api_router)
            if ui_router:
                combined.include_router(ui_router)

            total = len(combined.routes)
            logger.info(f"Script Studio: loaded {total} routes (API + UI)")
            return combined
        except Exception as e:
            logger.error(f"Failed to load Script Studio routes: {e}")
            import traceback
            traceback.print_exc()
            return None
