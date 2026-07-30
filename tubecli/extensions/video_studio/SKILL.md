---
name: "Video Studio"
description: "Remove the original burned-in subtitles via interpolation, analyze channels, and an approval-gated reup pipeline."
version: "1.0.0"
author: "TubeCreate"
---

# 🎬 Video Studio

Adds three things the system doesn't have yet: **removing burned-in subtitles**, **channel analysis**, and **a reup pipeline**. The remaining stages (downloading video, extracting subtitles, translation, TTS) live in other extensions — see the rules below.

## 🛑 IMPORTANT RULE: when a tool is missing, GUIDE the user, don't say "can't be done"

Most video stages are handled by optional extensions. If the user requests something whose extension isn't installed:

1. Do **NOT** give a generic answer like "I don't have that capability".
2. Emit `{"action": "video_capabilities"}` to get the exact list.
3. Hand the result verbatim to the user — it lists **exactly which extension to install**, describes each one, and reminds them to go to the **Market (`/market`)** then **restart the server**.

Job → extension needed:

| Job | Extension needed |
|---|---|
| Download video | `video_downloader` |
| Extract subtitles / translate / burn subtitles | `subtitle_extractor` |
| Voiceover (TTS) | `tts_vibevoice` |
| Remove original subtitles · analyze channel · pipeline | `video_studio` (already installed) |
| Full reup pipeline | all 4 of the above |

## 📥 video_capabilities — see what can be done

```json
{"action": "video_capabilities"}
```

Use BEFORE refusing any video request.

## 📥 analyze_channel — analyze a channel, suggest content

```json
{"action": "analyze_channel", "url": "https://www.youtube.com/@tenkenh"}
```

Returns: topic, audience, tone, the title formula of hit videos, and 5-8 new video ideas with hooks. Use when the user asks *"what is this channel about"*, *"what video should I make next"*.

## 📥 remove_hardsub — remove burned-in subtitles

```json
{"action": "remove_hardsub", "video_path": "C:/path/video.mp4", "mode": "delogo"}
```

`mode`: `delogo` (default — **interpolates** from the surrounding border; on a flat background the text vanishes without leaving a streak), `blur`, `pixel`, `fill`.

## 📥 reup_video — run the whole chain

```json
{"action": "reup_video", "url": "https://v.douyin.com/xxxx"}
```

Download → extract subtitles → translate → mask the original subtitles → voiceover → burn new subtitles. Creates a **Codex task awaiting approval** — report the task number to the user and remind them of `approve <n>`. **Don't say it has finished running**; it has only just been queued.

## 🌐 HTTP API

| Method | Endpoint | Job |
|---|---|---|
| GET | `/api/v1/video-studio/capabilities` | What can be done / what's missing |
| GET | `/api/v1/video-studio/capabilities/{job}` | Details of one job |
| POST | `/api/v1/video-studio/hardsub/detect` | Only detect the subtitle region, don't modify the video |
| POST | `/api/v1/video-studio/hardsub/remove` | Detect + mask |
| POST | `/api/v1/video-studio/channel/analyze` | Analyze a channel |
| POST | `/api/v1/video-studio/pipeline/plan` | See which steps the pipeline will run |
| POST | `/api/v1/video-studio/pipeline/reup` | Queue the pipeline as a Codex task |

## 💡 Examples

**User:** "https://www.youtube.com/@abc what content is this channel about?"
```json
{"action": "analyze_channel", "url": "https://www.youtube.com/@abc"}
```

**User:** "reup this video into Vietnamese for me https://v.douyin.com/xxx"
```json
{"action": "reup_video", "url": "https://v.douyin.com/xxx"}
```

**User:** "extract the subtitles from this video" — but `subtitle_extractor` isn't installed:
```json
{"action": "video_capabilities"}
```
→ then hand the raw result to the user so they know what to install.
