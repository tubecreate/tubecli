---
name: "Universal Tracker"
description: "Cross-platform background monitor to auto-detect new videos/posts (YouTube, Douyin, Website) and run team workflows."
version: "1.0.0"
author: "TubeCreate"
---

# 🎯 Chức năng
Kỹ năng này giúp Theo Dõi (Monitor) một nền tảng theo định kỳ (ví dụ: Douyin, YouTube, Website). Khi có video mới/bài đăng mới xuất hiện, hệ thống sẽ tự động đóng gói bài đăng đó và giao cho một Biệt đội Agent (Team) hoặc gửi tin nhắn cho người dùng để xử lý.

> **🛑 LƯU Ý PHÂN BIỆT QUAN TRỌNG:**
> - Kỹ năng này (`add_tracker`) dùng để theo dõi **KÊNH VIDEO** (YouTube, Douyin, TikTok) hoặc Nguồn cấp dữ liệu thô (để tải video / kích hoạt Team AI xử lý upload video chéo nền tảng).
> - NẾU người dùng yêu cầu theo dõi **TRANG WEB / BÁO CHÍ** để dịch bài và đăng lên trang **WordPress**: **TUYỆT ĐỐI KHÔNG DÙNG KỸ NĂNG NÀY**. Bạn phải tìm và dùng kỹ năng của Web Crawler (với action: `watch_page`).
## 📥 Hành động: Thêm Theo Dõi mới (add_tracker)
Dùng khi người dùng yêu cầu "theo dõi kênh Douyin ABC mỗi x giờ, rồi dùng team AutoReup để xử lý".

**Ví dụ:**
- "Theo dõi youtube https://youtube.com/channel... mỗi 2 giờ, sau đó dùng team room1"
- "Khi có video mới ở https://v.douyin.com... thì tự gọi team_abcdef"

```json
{
  "action": "add_tracker",
  "platform": "youtube", // youtube, douyin, tiktok, website
  "url": "https://...",
  "interval_minutes": 60, // Thời gian lặp lại (theo phút). Mặc định là 60.
  "target_team_id": "team_abcdef", // (Tùy chọn) ID của team/workflow xử lý khi có bài mới
  "instruction": "Tải về và up lên youtube Shorts" // (Tùy chọn) Ghi chú dặn dò
}
```

## 📥 Hành động: Danh sách Đang Theo dõi (list_trackers)
Được kích hoạt khi người dùng nói: "Xem danh sách đang theo dõi", "Các kênh dang monitor".

```json
{
  "action": "list_trackers"
}
```

## 📥 Hành động: Xoá Theo Dõi (remove_tracker)
Được kích hoạt khi người dùng muốn dừng theo dõi. Truyền vào ID của Tracker.

```json
{
  "action": "remove_tracker",
  "tracker_id": "abc123xyz"
}
```
