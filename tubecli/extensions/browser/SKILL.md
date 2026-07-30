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

15 action modules available: browse, click, comment, extract_content, login, navigate, read_gmail, save_image, search, search_extract, type, visual_scan, watch, captcha_helper, mouse_helper.
