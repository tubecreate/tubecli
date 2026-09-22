# Canvas Engine

Bộ dựng cảnh động cho dây chuyền «Diễn giải» (Explainer) của Content Studio. Không có giao diện.

- `renderer/` là phần DỰNG (canvas_renderer.js + video_encoder.py + phụ đề + nền). Nó bắt nguồn từ bộ dựng của
  T2Studio, nhưng từ 21/9/2026 **repo này là nguồn gốc duy nhất**: sửa bộ dựng thì sửa Ở ĐÂY, gói trên Chợ đóng từ
  chính thư mục này (`tubecli-cloud/scripts/publish_canvas_engine.py`). T2Studio chỉ còn là thứ để tham khảo —
  dây chuyền không đọc, không chép gì từ thư mục ấy nữa.
- Cần Node.js và ffmpeg trên máy. Package `canvas` được `npm install` tự động khi bật extension
  (hoặc `POST /api/v1/canvas-engine/install-canvas`). Xem `GET /api/v1/canvas-engine/status`.
- Content Studio tự tìm thấy bộ dựng ở đây; không phải cấu hình gì thêm.
