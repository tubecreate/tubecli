---
name: File Manager
description: Manage files and folders on the computer
---

# File Manager Extension

## Capabilities
This extension lets the AI create, delete, move, copy and list files/folders directly on the user's computer.

## Available Actions

### 1. Create folder
```json
{"action": "file_action", "operation": "create_folder", "path": "~/Desktop/my_folder"}
```

### 2. Create file
```json
{"action": "file_action", "operation": "create_file", "path": "~/Desktop/note.txt", "content": "File content"}
```

### 3. List files in a folder
```json
{"action": "file_action", "operation": "list", "path": "~/Desktop"}
```

### 4. Delete a file or folder
```json
{"action": "file_action", "operation": "delete", "path": "~/Desktop/my_folder"}
```

### 5. Move / Rename
```json
{"action": "file_action", "operation": "move", "path": "~/Desktop/old_name.txt", "destination": "~/Desktop/new_name.txt"}
```

### 6. Copy
```json
{"action": "file_action", "operation": "copy", "path": "~/Desktop/file.txt", "destination": "~/Documents/file_copy.txt"}
```

### 7. Read file content
```json
{"action": "file_action", "operation": "read", "path": "~/Desktop/note.txt"}
```

## Google Drive Actions

The extension can also manage the user's **Google Drive** through Auth Manager
tokens. Pass `cred_id` when the agent's system prompt names one — that pins the
operation to the Google account the user selected. Without `cred_id` the newest
authorized Drive token is used.

IMPORTANT: Google Drive files are CLOUD resources — NEVER use `file_action`
for them. Use the `drive_*` actions below. `file_id` values come from a
previous `drive_list` result.

### 8. List Drive files / search
```json
{"action": "drive_list", "folder_id": "root", "cred_id": "<from agent auth guide>"}
```
Search by name: `{"action": "drive_list", "query": "report", "cred_id": "..."}`

### 9. Upload a server file to Drive
```json
{"action": "drive_upload", "local_path": "~/Downloads/video.mp4", "folder_id": "root", "cred_id": "..."}
```

### 10. Download a Drive file to the server
```json
{"action": "drive_download", "file_id": "<drive file id>", "dest_dir": "~/Downloads", "cred_id": "..."}
```

### 11. Rename a Drive file
```json
{"action": "drive_rename", "file_id": "<drive file id>", "new_name": "new-name.mp4", "cred_id": "..."}
```

### 12. Share a Drive file
Anyone with the link: `{"action": "drive_share", "file_id": "...", "role": "reader", "cred_id": "..."}`
A specific person: `{"action": "drive_share", "file_id": "...", "type": "user", "email": "person@gmail.com", "role": "writer", "cred_id": "..."}`

### 13. Create a Drive folder
```json
{"action": "drive_mkdir", "name": "Backups", "parent_id": "root", "cred_id": "..."}
```

### 14. Delete a Drive file (moves to trash, recoverable)
```json
{"action": "drive_delete", "file_id": "<drive file id>", "cred_id": "..."}
```

## Spreadsheet Actions (xlsx_read / xlsx_append / xlsx_write)

These edit `.xlsx` / `.xlsm` workbooks IN PLACE (other sheets, formatting and
formulas are kept) and read/append `.csv`. Use them for spreadsheets instead of
`file_action` read/create_file, which flattens the file to text.

### 15. Read a sheet as a table
```json
{"action": "xlsx_read", "path": "~/Downloads/plan.xlsx", "sheet": "Sheet1", "max_rows": 100}
```
`sheet` is optional (active sheet). The reply shows `| a | b |` rows, the total
row count and the other sheet names. Formula cells show their last computed
result; the server does not calculate formulas, and after `xlsx_append` /
`xlsx_write` the cached results are gone, so those cells show the formula text
(e.g. `=SUM(B2:B9)`) and the reply says how many. Compute such totals yourself
from the rows when you need the number.

### 16. Append rows after the last filled row
```json
{"action": "xlsx_append", "path": "~/Downloads/plan.xlsx", "sheet": "Sheet1", "rows": [["a", "b"], ["c", "d"]]}
```

### 17. Write specific cells
```json
{"action": "xlsx_write", "path": "~/Downloads/plan.xlsx", "sheet": "Sheet1", "cells": {"A1": "v", "B2": 3}}
```
A block works too: `{"action": "xlsx_write", "path": "...", "rows": [[1, 2], [3, 4]], "start": "B2"}`.
CSV files support `xlsx_read` and `xlsx_append` only.

Boundary: when the agent belongs to a group (a `GROUP WORKSPACE` block in the
prompt), ONLY the spreadsheet files and folders listed there can be used, with
the access of their node (`read` < `append` < `write`) — nothing else exists,
even inside the sandbox below. Without a group, the sandbox below applies.

## Allowed Area (applies to AI file_action only)
AI-triggered LOCAL file operations are sandboxed to:
- `~/Desktop` — Main screen
- `~/Documents` — Documents
- `~/Downloads` — Downloads
- `data/` — TubeCLI data folder

The human user browsing the File Manager UI is NOT limited to these folders —
only AI actions are. If the user asks about a file outside the sandbox, tell
them to use the File Manager UI, or to move it into one of the folders above.
Google Drive actions are not path-sandboxed (they act on the user's own Drive),
except `drive_download`'s `dest_dir`, which must be inside the sandbox.

## Security Notes
- MUST NOT access system directories (Windows, Program Files, etc.)
- MUST NOT delete important files without asking for confirmation
- Always notify the user before deleting
- After any Drive action, repeat the returned link and account email verbatim

## Workflow Node
Use the `file_manager` node in the workflow builder:
- Input: `command` (text command), `path`, `content`, `destination`
- Output: `result` (operation result), `status`
