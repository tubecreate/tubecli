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

## Allowed Area
Operations are only allowed within:
- `~/Desktop` — Main screen
- `~/Documents` — Documents
- `~/Downloads` — Downloads
- `data/` — TubeCLI data folder

## Security Notes
- MUST NOT access system directories (Windows, Program Files, etc.)
- MUST NOT delete important files without asking for confirmation
- Always notify the user before deleting

## Workflow Node
Use the `file_manager` node in the workflow builder:
- Input: `command` (text command), `path`, `content`, `destination`
- Output: `result` (operation result), `status`
