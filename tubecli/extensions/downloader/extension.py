"""
Downloader Extension — Download videos from TikTok & Douyin.
"""
import logging
import os
import json
from tubecli.core.extension_manager import Extension

logger = logging.getLogger("DownloaderExtension")

SETTINGS_FILE = "downloader_settings.json"
DEFAULT_SETTINGS = {
    "cookie_douyin": "",
    "cookie_tiktok": "",
    "proxy": "",
    "download_path": "downloads",
    "max_workers": 3,
    "chunk_size": 1048576,
}


class DownloaderExtension(Extension):
    name = "downloader"
    description = "Download video từ TikTok & Douyin"
    version = "0.1.0"
    enabled_by_default = True

    def setup(self):
        logger.info("Downloader Extension loaded")
        data_dir = os.environ.get("TUBECLI_DATA_DIR", "data")
        dl_dir = os.path.join(data_dir, "downloads")
        os.makedirs(dl_dir, exist_ok=True)
        # Load/create settings
        self.settings_path = os.path.join(data_dir, SETTINGS_FILE)
        self.settings = self._load_settings()

    def _load_settings(self):
        if os.path.exists(self.settings_path):
            try:
                with open(self.settings_path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    merged = {**DEFAULT_SETTINGS, **saved}
                    return merged
            except Exception:
                pass
        return DEFAULT_SETTINGS.copy()

    def save_settings(self, new_settings: dict):
        self.settings.update(new_settings)
        with open(self.settings_path, "w", encoding="utf-8") as f:
            json.dump(self.settings, f, indent=2, ensure_ascii=False)

    def get_routes(self):
        from tubecli.extensions.downloader.routes import router
        return router
