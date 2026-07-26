---
name: "Video Studio"
description: "Xoá sub gốc bằng nội suy, phân tích kênh, và pipeline reup có duyệt."
version: "1.0.0"
author: "TubeCreate"
---

# 🎬 Video Studio

Bổ sung ba thứ mà hệ thống chưa có: **xoá phụ đề cháy sẵn**, **phân tích kênh**, và **pipeline reup**. Các khâu còn lại (tải video, tách sub, dịch, TTS) nằm ở extension khác — xem luật bên dưới.

## 🛑 LUẬT QUAN TRỌNG: thiếu công cụ thì HƯỚNG DẪN, đừng nói "không làm được"

Phần lớn khâu video do extension tuỳ chọn đảm nhiệm. Nếu người dùng yêu cầu một việc mà extension chưa cài:

1. **KHÔNG** trả lời chung chung kiểu "tôi không có khả năng đó".
2. Phát `{"action": "video_capabilities"}` để lấy danh sách chính xác.
3. Đưa nguyên văn kết quả cho người dùng — nó liệt kê **đúng extension cần cài**, mô tả từng cái, và nhắc vào **Market (`/market`)** rồi **khởi động lại server**.

Việc → extension cần:

| Việc | Cần extension |
|---|---|
| Tải video | `video_downloader` |
| Tách sub / dịch / ghi sub | `subtitle_extractor` |
| Lồng tiếng (TTS) | `tts_vibevoice` |
| Xoá sub gốc · phân tích kênh · pipeline | `video_studio` (đã có) |
| Pipeline reup đầy đủ | cả 4 cái trên |

## 📥 video_capabilities — xem làm được gì

```json
{"action": "video_capabilities"}
```

Dùng TRƯỚC khi từ chối bất kỳ yêu cầu video nào.

## 📥 analyze_channel — phân tích kênh, gợi ý nội dung

```json
{"action": "analyze_channel", "url": "https://www.youtube.com/@tenkenh"}
```

Trả về: chủ đề, đối tượng, giọng điệu, công thức tiêu đề của video ăn khách, và 5-8 ý tưởng video mới kèm hook. Dùng khi người dùng hỏi *"kênh này nói về gì"*, *"nên làm video gì tiếp"*.

## 📥 remove_hardsub — xoá phụ đề cháy sẵn

```json
{"action": "remove_hardsub", "video_path": "C:/path/video.mp4", "mode": "delogo"}
```

`mode`: `delogo` (mặc định — **nội suy** từ viền xung quanh, nền phẳng thì chữ biến mất không để lại vệt), `blur`, `pixel`, `fill`.

## 📥 reup_video — chạy cả chuỗi

```json
{"action": "reup_video", "url": "https://v.douyin.com/xxxx"}
```

Tải → tách sub → dịch → che sub gốc → lồng tiếng → ghi sub mới. Tạo thành **task Codex chờ duyệt** — báo số task cho người dùng và nhắc `approve <n>`. **Đừng nói là đã chạy xong**; nó chỉ mới được xếp hàng.

## 🌐 HTTP API

| Method | Endpoint | Việc |
|---|---|---|
| GET | `/api/v1/video-studio/capabilities` | Làm được gì / thiếu gì |
| GET | `/api/v1/video-studio/capabilities/{job}` | Chi tiết một việc |
| POST | `/api/v1/video-studio/hardsub/detect` | Chỉ dò vùng sub, không sửa video |
| POST | `/api/v1/video-studio/hardsub/remove` | Dò + che |
| POST | `/api/v1/video-studio/channel/analyze` | Phân tích kênh |
| POST | `/api/v1/video-studio/pipeline/plan` | Xem pipeline sẽ chạy bước nào |
| POST | `/api/v1/video-studio/pipeline/reup` | Xếp hàng pipeline thành task Codex |

## 💡 Ví dụ

**User:** "https://www.youtube.com/@abc kênh này nói về nội dung gì?"
```json
{"action": "analyze_channel", "url": "https://www.youtube.com/@abc"}
```

**User:** "reup video này sang tiếng Việt giúp tôi https://v.douyin.com/xxx"
```json
{"action": "reup_video", "url": "https://v.douyin.com/xxx"}
```

**User:** "tách sub video này" — nhưng `subtitle_extractor` chưa cài:
```json
{"action": "video_capabilities"}
```
→ rồi đưa nguyên kết quả cho người dùng để họ biết cài gì.
