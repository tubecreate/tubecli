---
name: Browser Automation
description: Quản lý browser profiles anti-detect, mở/đóng trình duyệt, tự động hóa web
---

# Browser Automation Extension

Quản lý trình duyệt anti-detect với fingerprint spoofing, hỗ trợ proxy và cookies.

## Keyword Triggers (Tier 1 — 0 token)

Các lệnh sau được xử lý trực tiếp, KHÔNG cần gọi AI:

| Lệnh | Ví dụ |
|-------|-------|
| List profiles | "list browser", "danh sách browser", "danh sách profile" |
| Mở browser | "mở browser testlive", "open browser testlive", "launch profile chan" |
| Tạo profile | "tạo browser profile myname", "create profile abc" |
| Đóng browser | "đóng browser testlive", "stop browser testlive", "tắt browser" |
| Xóa profile | "xóa browser profile old1", "delete profile abc" |

## API Endpoints

| Method | Endpoint | Mô tả |
|--------|----------|-------|
| GET | `/api/v1/browser/profiles` | List tất cả profiles |
| POST | `/api/v1/browser/profiles` | Tạo profile: `{"name": "xxx"}` |
| POST | `/api/v1/browser/launch` | Mở browser: `{"profile": "xxx"}` |
| POST | `/api/v1/browser/stop` | Đóng browser: `{"profile": "xxx"}` |
| DELETE | `/api/v1/browser/profiles/{name}` | Xóa profile |
| GET | `/api/v1/browser/status` | Trạng thái instances đang chạy |

## Browser Actions (Node.js)

15 action modules có sẵn: browse, click, comment, extract_content, login, navigate, read_gmail, save_image, search, search_extract, type, visual_scan, watch, captcha_helper, mouse_helper.
