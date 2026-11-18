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
 "language": "vi",
 "target_words": 1500}
```

- `day`: `today` (default), `yesterday`, or `all`.
- `sources`: extra links to crawl and fold in. YouTube links become transcripts.
- `aspect_ratio`: `16:9` (default) or `9:16` for Reels/Shorts/TikTok.
- `style`: `news`, `story`, `review`, `explainer`… — a hint to the writer.
- `publish`: `true` to upload to YouTube when the video is done (runs straight through, no review). `publish_channel_name`: the channel by name, e.g. `"Cinematic Bible"` (resolved to the right Google account); `publish_privacy`: `public` (default) | `unlisted` | `private`.
- `thumbnail`: `true` to design a thumbnail with Thumbnail Studio (AI title + Flux image on a template) and attach it when publishing; `thumbnail_template`: the template to force — its id or the NAME shown in Thumbnail Studio ("Noah flood"), looked up there. Leave it empty and the AI picks, preferring templates this channel drew itself. The user can name one in chat: "thumbnail mẫu noal", "thumbnail template big_number".
- The user saying *"đăng luôn lên kênh X, khỏi duyệt, có thumbnail"* / *"publish it to channel X without review with a thumbnail"* is `publish` + `publish_channel_name` + `thumbnail`.
- `target_words`: script length in words, ~150 words per minute read aloud (10 minutes → 1500, 20 minutes → 3000). Omit to follow the agent's Content Studio template. The user saying *"video 10 phút"* / *"a 20 minute video"* is this field.

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

## Publishing a finished video and running auto-publish over the API

Use these when a rendered video sits in **review** and never reached YouTube, or to steer an agent's automatic videos.
Uploads go through YouTube Studio in a browser profile, one at a time. Nothing here needs the owner's approval.

### Publish the video of a review task
`POST /api/v1/codex/tasks/{task id or number}/publish`
body (all optional): `{title, description, tags, privacy, channel, profile, when, force, ignore_daily_limit}`

- It uploads the file the task already rendered. It never renders again and never rewrites the script.
- `title` / `description` / `tags` replace the generated ones. Leave them out to have them written from the script.
- `privacy`: `public` (default from the agent), `unlisted` or `private`. `when`: `now` or `slots` (the agent's daily publish times).
- Channel: `profile` (browser profile name) wins, then `channel` (a name or alias looked up in the profiles), then the agent's own setting. If `channel` matches several profiles the call is refused and lists them: pass `profile`.
- The answer is `202 {status: "queued", job}`. Follow it with `GET /api/v1/codex/tasks/{id}/publish` → `{task, published: {video_id, url} | null, job}`. Job status: `queued`, `waiting` (see `wait_reason`), `running`, `done`, `failed`, `unverified`, `interrupted`.
- On success the task moves to **done** and its result carries `Published: https://youtu.be/<id>`.
- `unverified` means Studio finished but returned no video link. Check the channel by hand before publishing again; a second try needs `force: true`.
- Refusals you should expect: `422 too_long_for_unverified_channel` (over 15 minutes on a channel marked not verified: the owner must verify the channel), `409 daily_limit_reached` (the agent's videos-per-day limit, counting queued jobs; use `when: "slots"`, raise the limit, or `ignore_daily_limit: true` only when the owner says so), `409 already_published`, `409 not_in_review`.

### The browser queue
`GET /api/v1/content-video/publish-jobs?active=true` → `{jobs, gate, settings}`. One browser profile is open at a time. A job waits while free RAM is under 1.5 GB or while a video is rendering, and the profile is closed after every job. Do not open the same profile yourself while a job runs.

### Edit the title, description or tags of a published video
`PUT /api/v1/youtube/videos/{video_id}` body `{title?, description?, tags?, channel? | profile?}` → `202 {job}`; then `GET /api/v1/youtube/videos/{video_id}`. It uses the same queue. `category_id` and `default_audio_language` are accepted but not applied yet (`job.not_applied`). This path is new: read the job result and confirm on YouTube.

### Auto-publish per agent
- `POST /api/v1/codex/tasks/{id}/published` body `{url | video_id, channel?, scheduled?}` records a video that was published BY HAND outside TubeCLI (for example with the youtube_upload script): it writes the link on the task, moves it from review to done and counts it toward the agent's daily limit. It uploads nothing. A real video link is required (`https://youtu.be/<id>`, a `watch?v=` link or `https://studio.youtube.com/video/<id>`).
- `GET /api/v1/codex/autopublish/{agent_id}` → `{publish, auto_video, daily_limit, published_today, profile, channel, channel_unverified, agent_paused, paused_for_length, paused_detail, paused_at, resumed, when, when_choices, slots, will_publish, why_not}`. `will_publish` says whether the agent's NEXT automatic video is uploaded; `why_not` gives the reason when it is not. `resumed` (`{at, by, reason, seconds, paused_at}`, last 14 days) tells when a pause for a long video was lifted, for example because the owner unticked «Channel not verified».
- `PATCH /api/v1/codex/autopublish/{agent_id}` body `{publish?: true|false, daily_limit?: 1-20, channel_unverified?: true|false, when?: "now"|"slots", slots?: "12:00, 19:00"}` turns the Publish step of automatic videos on or off and sets the videos-per-day limit. `publish: true` also clears a self-pause. `channel_unverified: false` says the channel is phone-verified (videos over 15 minutes are allowed again). `when: "slots"` uploads right after rendering and schedules the video on YouTube at the next free time in `slots`; there is no separate timed publisher. Videos already waiting in review are never published by this switch: use `POST /api/v1/codex/tasks/{id}/publish` for each, which obeys the daily limit.
- `POST /api/v1/agents/{agent_id}/pause` stops the agent's schedule and its automatic videos; `POST /api/v1/agents/{agent_id}/resume` turns them back on.
- An automatic video is not created when the agent already has a video on the same topic from the last 21 days. The agent's run then shows `skip: duplicate topic` under `GET /api/v1/agents/{agent_id}/runs` (`notes`).
- Topics are grouped into clusters: the same Bible passage or the same main words count as one topic, however the query is worded ("seek first the kingdom Matthew 6" and "Matthew 6:33 explained" are one cluster). A cluster with an open task, a rendered video or a published video rests for the niche's `cooldown_days` (default 21): it is left out of the agent's daily keywords, the run shows `skip: topic in cooldown`, and a script whose title falls in it stops in review with `⚠ TOPIC IN COOLDOWN` before rendering. Unticking «Channel not verified» (`PUT /api/v1/agents/{agent_id}` with `publish_unverified: false`) resumes a pause for a long video at once.
