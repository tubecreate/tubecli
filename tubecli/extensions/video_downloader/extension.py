"""
Video Downloader Extension — Download videos from 50+ platforms using yt-dlp.
Provides: API routes, workflow node, AI skill.
"""
import os
import logging
from tubecli.core.extension_manager import Extension

logger = logging.getLogger("VideoDownloaderExtension")


class VideoDownloaderExtension(Extension):
    name = "video_downloader"
    version = "1.0.0"
    description = "Download videos from YouTube, TikTok, and 50+ platforms using yt-dlp"
    author = "TubeCreate Community"

    def on_install(self):
        """Ensure download directory exists on install."""
        logger.info("Video Downloader Extension installed")
        data_dir = os.environ.get("TUBECLI_DATA_DIR", "data")
        dl_dir = os.path.join(data_dir, "ytdl_downloads")
        os.makedirs(dl_dir, exist_ok=True)

    def on_enable(self):
        logger.info("Video Downloader Extension enabled")

    def get_routes(self):
        try:
            import os
            import importlib.util
            
            # Load exact specific routes.py without sys.path namespace collision
            routes_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "routes.py")
            spec = importlib.util.spec_from_file_location("video_dl_ext_routes", routes_file)
            routes_mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(routes_mod)
            
            router = getattr(routes_mod, "router", None)
            page_router = getattr(routes_mod, "_page_router", None)
            print("Importlib loaded Router instance:", router, "Routes total:", len(router.routes) if router else 0)
            # Return list of routers: API + UI page
            if page_router:
                return [router, page_router]
            return router
        except Exception as e:
            print(f"FAILED to import video_downloader router via importlib: {e}")
            import traceback
            traceback.print_exc()
            return None

    def get_nodes(self):
        try:
            import importlib.util
            import os
            
            nodes_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nodes.py")
            spec = importlib.util.spec_from_file_location("video_dl_nodes", nodes_file)
            nodes_mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(nodes_mod)
            
            VideoDownloadNode = getattr(nodes_mod, "VideoDownloadNode", None)
            if VideoDownloadNode:
                return {"video_download": VideoDownloadNode}
            return {}
        except Exception as e:
            print(f"FAILED to import video_downloader nodes: {e}")
            import traceback
            traceback.print_exc()
            return {}
