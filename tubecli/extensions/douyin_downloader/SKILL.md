# SKILL.md — Video Downloader Extension

## Mô tả
Extension **Downloader** cho phép tải video từ TikTok và Douyin (DouYin).

## Khi nào dùng
- User gửi link TikTok hoặc Douyin kèm yêu cầu tải
- User yêu cầu "tải video", "download video", "lấy video" VÀ CÓ KÈM URL

> ⛔ **KHÔNG DÙNG** khi: tin nhắn không chứa URL video, tin nhắn chỉ là chào hỏi/chat thường.

## Cách kích hoạt (AI OUTPUT JSON)

### Tải video từ URL:
```json
{"action": "download_video", "url": "https://www.douyin.com/video/XXXXXXX"}
```

### Formats URL được hỗ trợ:
- `https://www.douyin.com/video/<VIDEO_ID>` — Douyin video trực tiếp
- `https://www.tiktok.com/@<user>/video/<ID>` — TikTok video
- `https://vm.tiktok.com/<SHORT_CODE>` — TikTok short URL
- `https://v.douyin.com/<SHORT_CODE>` — Douyin short URL
- `https://www.iesdouyin.com/share/video/<ID>` — Douyin share link

## API Endpoints

| Method | Path | Mô tả |
|--------|------|-------|
| POST | `/api/v1/douyin_downloader/parse` | Parse video info: `{"url": "..."}` |
| POST | `/api/v1/douyin_downloader/download` | Tải video: `{"url": "..."}` |
| GET | `/api/v1/douyin_downloader/status/{task_id}` | Check tiến trình |
| GET | `/api/v1/douyin_downloader/history` | Lịch sử tải |
| GET | `/api/v1/douyin_downloader/file/{filename}` | Serve file |

## Workflow tự động (AI tự hành)
1. AI nhận URL từ user
2. AI output JSON `{"action": "download_video", "url": "..."}`
3. Hệ thống gọi `/parse` → lấy download URL
4. Hệ thống gọi `/download` → tải file
5. Bot Telegram gửi file trực tiếp cho user (sendDocument)

## QUAN TRỌNG
- **KHÔNG bao giờ** hướng dẫn user vào Dashboard để tải
- **LUÔN LUÔN** output JSON action để hệ thống tự tải
- Sau khi tải xong, file được gửi trực tiếp về Telegram
