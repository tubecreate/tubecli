---
name: Browser Automation
description: Manage anti-detect browser profiles, open/close browsers, automate the web
---

# Browser Automation Extension

Manage anti-detect browsers with fingerprint spoofing, with proxy and cookie support.

## Keyword Triggers (Tier 1 — 0 token)

The following commands are handled directly, WITHOUT calling the AI:

| Command | Example |
|-------|-------|
| List profiles | "list browser", "danh sách browser", "danh sách profile" |
| Open browser | "mở browser testlive", "open browser testlive", "launch profile chan" |
| Create profile | "tạo browser profile myname", "create profile abc" |
| Close browser | "đóng browser testlive", "stop browser testlive", "tắt browser" |
| Delete profile | "xóa browser profile old1", "delete profile abc" |

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------|
| GET | `/api/v1/browser/profiles` | List all profiles |
| POST | `/api/v1/browser/profiles` | Create profile: `{"name": "xxx"}` |
| POST | `/api/v1/browser/launch` | Open browser: `{"profile": "xxx"}` |
| POST | `/api/v1/browser/stop` | Close browser: `{"profile": "xxx"}` |
| DELETE | `/api/v1/browser/profiles/{name}` | Delete profile |
| GET | `/api/v1/browser/status` | Status of running instances |

## Browser Actions (Node.js)

16 action modules available: browse, click, comment, follow, extract_content, login, navigate, read_gmail, save_image, search, search_extract, type, visual_scan, watch, captcha_helper, mouse_helper.

## Agent routine tasks (schedule keys)
An agent's daily routine runs in one of its browser profiles (`allowed_profiles`), or on an Android phone when
`android_devices` is set (read `tubecli_doc('android_window')` for phones). Tasks live in
`persona.dailyRoutine` = `{period: {key: true}}` for `morning`, `afternoon`, `evening`, `night`; each run picks one
enabled key at random.

| Key | In the browser profile | Needs a profile signed in to |
|---|---|---|
| `browse_topic`, `study` | Google search on the agent's topics, read a result | — |
| `news` | A news site in the agent's language, read an article | — |
| `watch_video` | youtube.com: search a topic, watch a video | YouTube (Google) |
| `check_email` · `reply_email` · `send_report` | Gmail (reply / report written by AI; reports need recipients) | Google |
| `comment` | YouTube or TikTok: watch a video, the session AI writes one short comment from the title in the agent's language | YouTube or TikTok |
| `watch_live` | YouTube (Live filter) or TikTok live search: watch a live stream, never chats | — |
| `follow` | YouTube Subscribe / TikTok Follow on the video it watched (skips channels already followed) | YouTube or TikTok |

- "Signed in" = the profile's login chips: `GET /api/v1/browser/profiles` → `logins` (`google`, `youtube`,
  `tiktok`, `facebook`, `x`…). Tasks no candidate profile can do are skipped; the run uses a profile that can.
  `comment` / `follow` pick YouTube or TikTok from that profile's chips (random when both).
- `comment`, `watch_live` and `follow` are public actions on the owner's accounts: enable them ONLY when the owner
  asks. The AI routine generator never enables them. Daily cap per agent: 4 comments, 3 follows, 6 lives — then the
  run watches a normal video instead. A comment the AI cannot write cleanly (link, @mention, error text) is not posted.
- Set it (read first — `dailyRoutine` is replaced as a whole, keep the keys already there):
  `tubecli_api("GET", "/api/v1/agents/<agent_id>")`, then
  `tubecli_api("PUT", "/api/v1/agents/<agent_id>", body={"persona": {"dailyRoutine": {"evening": {"watch_video": true, "comment": true}}}})`.
- Run the routine once now: `POST /api/v1/agents/<agent_id>/test_routine` (it picks a task like a scheduled run —
  this is a REAL run: a picked `comment` / `follow` is really posted). Results: `GET /api/v1/agents/<agent_id>/runs`
  (behavior `commentVideo` / `watchLive` / `followChannel`, outcome, log tail).
- Needs TubeCLI ≥ 2026.08.09.246 — older versions do not know these keys.
