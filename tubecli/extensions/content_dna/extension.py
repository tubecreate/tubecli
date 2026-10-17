"""Content DNA — đúc «ADN nội dung» (cấu trúc + văn phong) từ bài mẫu, để AI viết kịch bản đúng giọng một kênh.

User 16/10/2026: «trong chỗ thời lượng của content studio ngoài những option mặc định tôi muốn làm thêm một dạng mẫu
customize, kiểu như xây dựng mẫu cấu trúc, cách hành văn (ADN) để AI viết content dựa vào đó… tạo 1 extension mới
trong tubecli chức năng giống như t2content (đọc dữ liệu, bài mẫu, đúc kết thành mẫu), xong template list mẫu đó
để chọn». Ý tưởng lấy từ C:\\T2Content (core/giong_van.py + mau.py), viết lại cho TubeCLI:

- học: bài dán / file (.txt .md .srt .vtt .docx) / link YouTube (phụ đề) → phân tích TỪNG bài mẫu rồi GỘP
  (T2Content chỉ đọc 6 bài trong một lượt gọi) → ADN chuẩn hoá (tỷ lệ các nhịp cộng đúng 100);
- lưu: DATA_DIR/content_dna/<id>.json, giữ vài bản trước khi sửa / học lại; sửa tay được (T2Content không có);
- dùng: mẫu Content Studio chọn ADN (ô «Content DNA» cạnh «Video length»), form Codex đè từng task; pipeline
  content_video chèn MỘT khối «CONTENT DNA» vào system prompt của bước viết kịch bản (apply.prompt_block).
"""
import logging
import os

from tubecli.core.extension_manager import Extension

logger = logging.getLogger("ContentDnaExtension")


class ContentDnaExtension(Extension):
    name = "content_dna"
    display_name = "Content DNA"
    version = "1.0.0"
    description = "Learn a channel's script structure and writing style from sample texts, then write in it"
    author = "TubeCreate"
    # system: bật sẵn, kể cả trên máy đã init từ trước (extension_manager._default_on).
    extension_type = "system"

    def on_enable(self):
        from . import store
        os.makedirs(store.data_dir(), exist_ok=True)
        logger.info("Content DNA enabled — %s DNA(s) in %s", len(store.list_all()), store.data_dir())

    def get_routes(self):
        from .routes import page_router, router
        return [router, page_router]


extension_instance = ContentDnaExtension()
