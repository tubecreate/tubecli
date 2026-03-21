"""
3D Studio Extension — Room/scene designer for AI Teams.
"""
import logging
from tubecli.core.extension_manager import Extension

logger = logging.getLogger("Studio3DExtension")


class Studio3DExtension(Extension):
    name = "studio3d"
    description = "3D Studio — Thiết kế văn phòng 3D, tạo mô hình cho teams"
    version = "0.1.0"
    enabled_by_default = True

    def setup(self):
        logger.info("Studio3D Extension loaded")

    def get_routes(self):
        from tubecli.extensions.studio3d.routes import router
        return router
