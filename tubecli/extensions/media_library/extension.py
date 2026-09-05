"""Media Library — bộ sưu tập ảnh, GIF và video dùng chung cho mọi extension.

Cài sẵn cùng TubeCLI. Mỗi extension trước đây tự đẻ một kho riêng, nên cùng một
tấm ảnh phải tải lên nhiều lần và sửa một chỗ thì các chỗ khác vẫn cũ. Ở đây
người dùng gom nguyên liệu một lần; extension nào cần thì chỉ trỏ vào tên kho,
và máy bốc file theo luật của nó.
"""
import logging
import os

from tubecli.core.extension_manager import Extension

logger = logging.getLogger("MediaLibraryExtension")


class MediaLibraryExtension(Extension):
    name = "media_library"
    # Tên máy giữ nguyên `media_library`; tên người đọc là tiếng Anh, và bảng
    # điều khiển dịch nó qua khoá i18n cùng tên (xem locales/*.json).
    display_name = "Media Library"
    version = "1.1.0"
    description = "Shared store of images, GIFs and videos for every extension"
    author = "TubeCreate"
    extension_type = "system"

    def on_enable(self):
        from . import library
        os.makedirs(library.data_dir(), exist_ok=True)
        s = library.stats()
        logger.info("Media Library enabled — %s kho, %s tệp, tại %s",
                    s["collections"], s["files"], s["dir"])

    def get_routes(self):
        # Hai router: API có tiền tố, và trang người dùng thì không. TubeCLI
        # không tự phục vụ thư mục static của extension.
        from .routes import page_router, router
        return [router, page_router]


extension_instance = MediaLibraryExtension()
