---
name: auth_manager
description: Manage OAuth credentials & tokens for Google, Facebook, TikTok
---

# Auth Manager Extension

Kỹ năng này chịu trách nhiệm sinh ra đường dẫn (URL) cấp quyền (Google, Facebook, TikTok) để người dùng có thể nhấp vào và cấp quyền ứng dụng, ví dụ: Quản lý đăng video lên YouTube, Fanpage, TikTok.

## Khi nào dùng
- Người dùng yêu cầu "gửi tôi link cấp quyền"
- Người dùng muốn "cấp quyền quản lý kênh youtube mới"
- Người dùng yêu cầu "cấp quyền facebook/tiktok", "cấp quyền ứng dụng"

## Cách kích hoạt (AI OUTPUT JSON)

Nếu người dùng yêu cầu link cấp quyền, hãy phân tích nền tảng (provider) và trả về JSON sau:

```json
{
  "action": "generate_auth_link",
  "provider": "google",
  "scopes": ["youtube", "youtube_upload"]
}
```

Các giá trị `provider` hỗ trợ: `google`, `facebook`, `tiktok`.
Nếu không biết scopes, có thể để trống rỗng `[]`, hệ thống sẽ tự dùng scope mặc định phổ biến nhất.

> **Lưu ý:** Sau khi bot phản hồi JSON, hệ thống sẽ trả về 1 đường link cho người dùng bấm vào cấp quyền.
