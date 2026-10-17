"""Content DNA — cấu trúc + văn phong một kênh, học từ bài mẫu; content_video chèn vào prompt người viết kịch bản."""
# Bộ dò extension nội bộ tìm `extension_instance` ở ngay package (không phải module con).
from .extension import extension_instance  # noqa: F401

__all__ = ["extension_instance"]
