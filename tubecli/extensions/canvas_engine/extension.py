"""Canvas Engine — bộ dựng cảnh động cho dây chuyền «Diễn giải» của Content Studio.

Không có giao diện, không có node. Việc duy nhất: mang thư mục `renderer/` (bộ dựng — repo này là nguồn gốc của nó) tới máy này và lo cho
package node-canvas có mặt. Content Studio tìm bộ dựng ở `<extension>/renderer` (canvas_video_engine.renderer_candidates).
"""
import logging
import os
import shutil
import subprocess
import threading

try:
    from tubecli.core.extension_manager import Extension
except ImportError:
    from TubeCLI.core.extension_manager import Extension

logger = logging.getLogger("CanvasEngine")
CANVAS_VERSION = "3.2.3"        # bản có prebuild cho Linux x64 + Windows (đo VPS Ubuntu 24.04 18/9/2026: cài 2 giây)


class CanvasEngineExtension(Extension):
    name = "canvas_engine"
    version = "1.0.0"
    description = "Canvas renderer for Content Studio's Explainer pipeline"
    author = "TubeCreate"
    extension_type = "system"       # bộ dò built-in ghi "system"; gói Chợ cho lõi cũ được loader ngoài ghi "external"

    def renderer_dir(self) -> str:
        return os.path.join(self.extension_dir or os.path.dirname(os.path.abspath(__file__)), "renderer")

    def canvas_ready(self) -> bool:
        return os.path.isdir(os.path.join(self.renderer_dir(), "node_modules", "canvas"))

    def on_enable(self):
        logger.info("Canvas Engine enabled: %s", self.renderer_dir())
        if not self.canvas_ready():
            # Cài NỀN, không chặn khởi động: npm install mất 2-60 giây tuỳ mạng.
            threading.Thread(target=self._install_canvas, name="canvas-engine-npm", daemon=True).start()

    def _install_canvas(self):
        root = self.renderer_dir()
        npm = shutil.which("npm") or shutil.which("npm.cmd")
        if not npm:
            logger.warning("Canvas Engine: npm not found — install Node.js LTS, then re-enable this extension.")
            return
        try:
            r = subprocess.run([npm, "install", "--no-audit", "--no-fund", f"canvas@{CANVAS_VERSION}"], cwd=root,
                               capture_output=True, text=True, timeout=600)
            tail = (r.stderr or r.stdout or "").strip()[-400:]
            if r.returncode == 0 and self.canvas_ready():
                logger.info("Canvas Engine: node-canvas %s installed", CANVAS_VERSION)
            else:
                logger.warning("Canvas Engine: npm install failed (%s): %s", r.returncode, tail)
        except Exception as e:      # noqa: BLE001
            logger.warning("Canvas Engine: npm install error: %s", e)

    def get_routes(self):
        from fastapi import APIRouter
        router = APIRouter(prefix="/api/v1/canvas-engine", tags=["canvas-engine"])
        ext = self

        @router.get("/status")
        async def status():
            root = ext.renderer_dir()
            return {"success": True, "renderer": root, "version": ext.version,
                    "renderer_present": os.path.isfile(os.path.join(root, "engines", "canvas_renderer.js")),
                    "node": shutil.which("node") or "", "ffmpeg": shutil.which("ffmpeg") or "",
                    "canvas_installed": ext.canvas_ready()}

        @router.post("/install-canvas")
        async def install_canvas():
            if not ext.canvas_ready():
                threading.Thread(target=ext._install_canvas, daemon=True).start()
            return {"success": True, "started": not ext.canvas_ready(), "canvas_installed": ext.canvas_ready()}

        return router


extension_instance = CanvasEngineExtension()
