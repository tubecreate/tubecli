---
name: Video Downloader (yt-dlp)
description: Download videos from YouTube, TikTok, and 50+ platforms
---

# Video Downloader Skill

This extension provides video downloading capabilities via yt-dlp.

## Available API Endpoints

### Check Status
```
GET /api/v1/ytdl/status
```
Returns whether yt-dlp is installed and its version.

### Get Video Info
```
POST /api/v1/ytdl/info
{"url": "https://www.youtube.com/watch?v=VIDEO_ID"}
```
Returns video metadata (title, duration, uploader, thumbnails) without downloading.

### Download Video
```
POST /api/v1/ytdl/download
{
  "url": "https://www.youtube.com/watch?v=VIDEO_ID",
  "format": "mp4",
  "quality": "720p",
  "title": "my_video"
}
```
Downloads video to `data/ytdl_downloads/`. Supports:
- **format**: `mp4`, `mp3`, `webm`
- **quality**: `360p`, `480p`, `720p`, `1080p`, `best`

### Search Videos
```
POST /api/v1/ytdl/search
{
  "query": "python tutorial",
  "platform": "youtube",
  "limit": 10
}
```
Search for videos on YouTube or SoundCloud.

### List Downloads
```
GET /api/v1/ytdl/downloads
```

### Delete Download
```
DELETE /api/v1/ytdl/downloads/{filename}
```

## Workflow Node

Use the **📹 Video Download** node in workflows:
- **Inputs**: `url` (required), `format`, `quality`
- **Outputs**: `file_path`, `filename`, `status`

## Supported Platforms
YouTube, TikTok, Instagram, Twitter/X, Facebook, Twitch, Bilibili,
SoundCloud, Vimeo, Dailymotion, and 50+ more platforms supported by yt-dlp.
