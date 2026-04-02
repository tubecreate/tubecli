---
name: File Manager
description: Quản lý file và folder trên máy tính
---

# File Manager Extension

## Khả năng
Extension này cho phép AI tạo, xóa, di chuyển, sao chép và liệt kê file/folder trực tiếp trên máy tính của người dùng.

## Hành động có thể thực hiện

### 1. Tạo thư mục
```json
{"action": "file_action", "operation": "create_folder", "path": "~/Desktop/my_folder"}
```

### 2. Tạo file
```json
{"action": "file_action", "operation": "create_file", "path": "~/Desktop/note.txt", "content": "Nội dung file"}
```

### 3. Liệt kê file trong thư mục
```json
{"action": "file_action", "operation": "list", "path": "~/Desktop"}
```

### 4. Xóa file hoặc folder
```json
{"action": "file_action", "operation": "delete", "path": "~/Desktop/my_folder"}
```

### 5. Di chuyển / Đổi tên
```json
{"action": "file_action", "operation": "move", "path": "~/Desktop/old_name.txt", "destination": "~/Desktop/new_name.txt"}
```

### 6. Sao chép
```json
{"action": "file_action", "operation": "copy", "path": "~/Desktop/file.txt", "destination": "~/Documents/file_copy.txt"}
```

### 7. Đọc nội dung file
```json
{"action": "file_action", "operation": "read", "path": "~/Desktop/note.txt"}
```

## Vùng cho phép
Chỉ cho phép thao tác trong:
- `~/Desktop` — Màn hình chính
- `~/Documents` — Tài liệu
- `~/Downloads` — Tải về
- `data/` — Thư mục dữ liệu TubeCLI

## Lưu ý bảo mật
- KHÔNG được truy cập thư mục hệ thống (Windows, Program Files, etc.)
- KHÔNG được xóa file quan trọng mà không hỏi xác nhận
- Luôn thông báo cho người dùng trước khi xóa

## Workflow Node
Sử dụng node `file_manager` trong workflow builder:
- Input: `command` (lệnh dạng text), `path`, `content`, `destination`
- Output: `result` (kết quả thao tác), `status`
