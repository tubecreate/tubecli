# SKILL.md — Video Downloader Extension

## Description
The **Downloader** extension allows downloading videos from TikTok and Douyin (DouYin).

## When to use
- User sends a TikTok or Douyin link along with a download request
- User requests "tải video", "download video", "lấy video" AND INCLUDES A URL

> ⛔ **DO NOT USE** when: the message contains no video URL, the message is just a greeting/casual chat.

## How to trigger (AI OUTPUT JSON)

### Download video from URL:
```json
{"action": "download_video", "url": "https://www.douyin.com/video/XXXXXXX"}
```

### Supported URL formats:
- `https://www.douyin.com/video/<VIDEO_ID>` — Douyin direct video
- `https://www.tiktok.com/@<user>/video/<ID>` — TikTok video
- `https://vm.tiktok.com/<SHORT_CODE>` — TikTok short URL
- `https://v.douyin.com/<SHORT_CODE>` — Douyin short URL
- `https://www.iesdouyin.com/share/video/<ID>` — Douyin share link

## API Endpoints

| Method | Path | Description |
|--------|------|-------|
| POST | `/api/v1/douyin_downloader/parse` | Parse video info: `{"url": "..."}` |
| POST | `/api/v1/douyin_downloader/download` | Download video: `{"url": "..."}` |
| GET | `/api/v1/douyin_downloader/status/{task_id}` | Check progress |
| GET | `/api/v1/douyin_downloader/history` | Download history |
| GET | `/api/v1/douyin_downloader/file/{filename}` | Serve file |

## Automated workflow (AI autonomous)
1. AI receives the URL from the user
2. AI outputs JSON `{"action": "download_video", "url": "..."}`
3. The system calls `/parse` → gets the download URL
4. The system calls `/download` → downloads the file
5. The Telegram bot sends the file directly to the user (sendDocument)

## IMPORTANT
- **NEVER** instruct the user to go to the Dashboard to download
- **ALWAYS** output the JSON action so the system downloads automatically
- After downloading, the file is sent directly to Telegram
