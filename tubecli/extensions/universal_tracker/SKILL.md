---
name: "Universal Tracker"
description: "Cross-platform background monitor to auto-detect new videos/posts (YouTube, Douyin, Website) and run team workflows."
version: "1.0.0"
author: "TubeCreate"
---

# 🎯 Functionality
This skill lets you Monitor a platform periodically (e.g. Douyin, YouTube, Website). When a new video/post appears, the system automatically packages that post and hands it off to an Agent Team, or sends a message to the user for processing.

> **🛑 IMPORTANT DISTINCTION:**
> - This skill (`add_tracker`) is used to monitor **VIDEO CHANNELS** (YouTube, Douyin, TikTok) or raw data feeds (to download videos / trigger an AI Team to handle cross-platform video uploads).
> - IF the user asks to monitor a **WEBSITE / NEWS SITE** to translate articles and publish them to a **WordPress** site: **NEVER USE THIS SKILL**. You must find and use the Web Crawler skill (with action: `watch_page`).
## 📥 Action: Add a new Tracker (add_tracker)
Use when the user asks "monitor Douyin channel ABC every x hours, then use the AutoReup team to handle it".

**Examples:**
- "Monitor youtube https://youtube.com/channel... every 2 hours, then use team room1"
- "When there is a new video at https://v.douyin.com... automatically call team_abcdef"

```json
{
  "action": "add_tracker",
  "platform": "youtube", // youtube, douyin, tiktok, website
  "url": "https://...",
  "interval_minutes": 60, // Repeat interval (in minutes). Default is 60.
  "target_team_id": "team_abcdef", // (Optional) ID of the team/workflow that handles new posts
  "instruction": "Download and upload to youtube Shorts" // (Optional) Instruction note
}
```

## 📥 Action: List Active Trackers (list_trackers)
Triggered when the user says: "Show the list of trackers", "Which channels are being monitored".

```json
{
  "action": "list_trackers"
}
```

## 📥 Action: Remove a Tracker (remove_tracker)
Triggered when the user wants to stop monitoring. Pass in the Tracker ID.

```json
{
  "action": "remove_tracker",
  "tracker_id": "abc123xyz"
}
```

## 📥 Action: Fetch the video NOW (trigger_tracker)
Use when the user asks to "post the latest video", "get the latest video", "upload the newest post to the channel".

> **⚡ IMPORTANT DISTINCTION RULE:**
> - User says "**monitor**", "**track**", "**every X hours**" → `add_tracker` (create a new config)
> - User says "**latest**", "**post to channel**", "**upload the new post**", "**get the new video**" → `trigger_tracker` (trigger NOW)
> - If a tracker already exists for this URL, ALWAYS use `trigger_tracker`. DO NOT create a duplicate tracker!

```json
{
  "action": "trigger_tracker",
  "tracker_id": "" // (Optional) tracker ID; if left empty, the most recent tracker is used
}
```
