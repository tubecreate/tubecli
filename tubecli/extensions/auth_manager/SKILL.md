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

## Google Sheets shared through a group (gsheet_*)

When the agent sits inside a Flow Builder group that contains a **Sheet** node, the
group prompt block lists that sheet by alias and the exact JSON syntax. Five actions
are handled here (auth_manager owns the Google token):

| action | needs access | purpose |
|---|---|---|
| `gsheet_read` | read | rows of a tab / range (`max_rows`, `tail`) |
| `gsheet_tabs` | read | list tabs |
| `gsheet_append` | append | add rows after the last filled row |
| `gsheet_update` | write | overwrite an explicit `range` |
| `gsheet_create_tab` | manage | add a tab |

Rules: refer to the sheet by its **alias** (`"sheet": "<alias>"`) — never by id or
credential; a sheet that is not in the agent's group(s) does not exist and the action
is refused. Without any group sheet the answer is "No Google Sheet is shared with this
agent". The HTTP side used by the cloud Sheet node: `GET /gsheets/inspect`,
`GET /gsheets/{id}/values`, `POST /gsheets/{id}/append` under `/api/v1/auth-manager`.
