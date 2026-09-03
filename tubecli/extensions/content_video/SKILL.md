---
name: "Content Video"
description: "Turn what the agent read and watched today into a narrated video: script → Content Studio storyboard → images → voice → mp4, as a Codex task."
version: "1.0.0"
author: "TubeCreate"
---

# 🎬 Content Video

Makes a **video from the agent's own collected material**: the articles it scraped, the videos it watched (via transcripts), plus any extra links the user gives. It writes the script with this agent's model, then hands it to Content Studio for the storyboard, images, voice and the final mp4. The whole thing runs in the background as a **Codex task** with a live progress card.

Use it when the user says things like: *"make a video from what you read today"*, *"turn today's news into a video"*, *"làm video từ những gì đã đọc/xem hôm nay"*, *"tổng hợp hôm nay thành video"*, *"make a video about these links"*.

## 📥 content_video_run — queue the video

```json
{"action": "content_video_run"}
```

Optional fields (all flat):

```json
{"action": "content_video_run",
 "day": "today",
 "sources": ["https://example.com/article", "https://youtube.com/watch?v=..."],
 "aspect_ratio": "9:16",
 "style": "news",
 "title": "",
 "tts_voice": "vi-VN-HoaiMyNeural",
 "language": "vi"}
```

- `day`: `today` (default), `yesterday`, or `all`.
- `sources`: extra links to crawl and fold in. YouTube links become transcripts.
- `aspect_ratio`: `16:9` (default) or `9:16` for Reels/Shorts/TikTok.
- `style`: `news`, `story`, `review`, `explainer`… — a hint to the writer.

The agent that is speaking is always the owner of the video; you cannot make one for another agent.

**After emitting the action**: tell the user the task number and that it is **queued** (and awaiting approval if the reply says so). Do **not** say the video is done — the card in the chat updates on its own, and the mp4 path appears there when it finishes.

## 📥 content_video_capabilities — what is missing

```json
{"action": "content_video_capabilities"}
```

Use this **before saying "I can't"**: it lists which Market extensions are missing (Content Studio, Web Crawler, TTS VibeVoice), whether ffmpeg is found, and what Content Studio itself reports about its text/image providers. Hand the answer to the user verbatim.

## What happens inside (so you can explain it)

1. Checks Content Studio is installed and has a text and an image provider — fails here, before spending anything, if not.
2. Reads the agent's corpus for the day (only this agent's own profiles and the ones its groups share).
3. Fetches transcripts for watched YouTube videos and crawls the extra sources (needs Web Crawler; skipped if absent).
4. Writes the script with this agent's model.
5. Content Studio: project → episode → storyboard → shot images → voice (edge-tts, free) → ffmpeg export.
6. The task ends in **review**: the user watches the video and accepts it on the Codex board.

If the corpus is empty the task fails with a clear message: the agent needs a browsing routine with data collection on, or some `sources`.
