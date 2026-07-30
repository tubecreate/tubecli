---
name: auth_manager
description: Manage OAuth credentials & tokens for Google, Facebook, TikTok
---

# Auth Manager Extension

This skill is responsible for generating the authorization URL (Google, Facebook, TikTok) that the user can click to grant app permissions, e.g. managing video uploads to YouTube, Fanpage, TikTok.

## When to use
- The user asks to "send me the authorization link"
- The user wants to "grant permission to manage a new youtube channel"
- The user asks to "grant facebook/tiktok permission", "grant app permission"

## How to trigger (AI OUTPUT JSON)

If the user asks for an authorization link, analyze the platform (provider) and return the following JSON:

```json
{
  "action": "generate_auth_link",
  "provider": "google",
  "scopes": ["youtube", "youtube_upload"]
}
```

Supported `provider` values: `google`, `facebook`, `tiktok`.
If you don't know the scopes, you can leave it empty `[]`, and the system will automatically use the most common default scope.

> **Note:** After the bot responds with JSON, the system will return a link for the user to click and grant permission.
