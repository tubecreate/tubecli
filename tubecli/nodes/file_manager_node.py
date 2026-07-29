"""Built-in node: File Manager — create, delete, move files/folders in workflows."""
import re
from typing import Dict, Any
from tubecli.nodes.base_node import BaseNode, PortType


class FileManagerNode(BaseNode):
    node_type = "file_manager"
    display_name = "📁 File Manager"
    description = "Create, delete, move, copy, list files and folders."
    icon = "📁"
    category = "System"
    config_schema = {
        "action": {"type": "string", "required": True, "description": "File operation. 'auto' parses the natural-language `command` input.", "default": "auto", "options": ["auto", "create_folder", "create_file", "delete", "move", "copy", "list", "read"]},
        "path": {"type": "string", "description": "Target file/folder path, e.g. ~/Desktop/report.txt."},
        "content": {"type": "string", "description": "File content (for create_file)."},
        "destination": {"type": "string", "description": "Destination path (for move/copy)."},
    }

    def _setup_ports(self):
        self.add_input("command", PortType.TEXT, "Natural language command or action", required=False)
        self.add_input("path", PortType.TEXT, "File/folder path", required=False)
        self.add_input("content", PortType.TEXT, "File content (for create)", required=False)
        self.add_input("destination", PortType.TEXT, "Destination path (for move/copy)", required=False)
        self.add_output("result", PortType.TEXT, "Operation result")
        self.add_output("status", PortType.TEXT, "Status message")

    async def execute(self, inputs: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        from tubecli.extensions.file_manager.file_service import file_service

        action = self.config.get("action", "auto")
        path = inputs.get("path") or self.config.get("path", "")
        content = inputs.get("content") or self.config.get("content", "")
        destination = inputs.get("destination") or self.config.get("destination", "")
        command = inputs.get("command", "")

        # Auto-detect action from natural language command
        if action == "auto" and command:
            action, path, content, destination = self._parse_command(command, path, content, destination)

        try:
            if action == "create_folder":
                result = file_service.create_folder(path)
            elif action == "create_file":
                result = file_service.create_file(path, content)
            elif action == "list":
                result = file_service.list_dir(path or "~/Desktop")
                # Format for readability
                items = result.get("items", [])
                lines = [f"📂 {result['path']} ({result['count']} mục):"]
                for item in items[:30]:
                    icon = "📁" if item.get("is_dir") else "📄"
                    size = f" ({item.get('size_human', '')})" if not item.get("is_dir") else ""
                    lines.append(f"  {icon} {item['name']}{size}")
                return {"result": "\n".join(lines), "status": "✅ Listed"}
            elif action == "delete":
                result = file_service.delete(path)
            elif action == "move":
                result = file_service.move(path, destination)
            elif action == "copy":
                result = file_service.copy(path, destination)
            elif action == "read":
                result = file_service.read_file(path)
                return {
                    "result": result.get("content", result.get("message", "")),
                    "status": f"✅ Read {result.get('lines', 0)} lines",
                }
            elif action == "info":
                result = file_service.info(path)
                return {"result": str(result), "status": "✅ Info"}
            elif action == "search":
                pattern = content or "*"
                result = file_service.search(path or "~/Desktop", pattern=pattern)
                matches = result.get("matches", [])
                lines = [f"🔍 Found {len(matches)} files matching '{pattern}':"]
                for m in matches[:20]:
                    lines.append(f"  📄 {m['name']} — {m.get('path', '')}")
                return {"result": "\n".join(lines), "status": f"✅ Found {len(matches)}"}
            else:
                return {"result": f"Unknown action: {action}", "status": "❌ Error"}

            return {
                "result": result.get("message", str(result)),
                "status": result.get("status", "✅ Done"),
            }

        except (FileNotFoundError, ValueError, PermissionError) as e:
            return {"result": str(e), "status": "❌ Error"}
        except Exception as e:
            return {"result": f"Lỗi: {str(e)}", "status": "❌ Error"}

    def _parse_command(self, command: str, path: str, content: str, destination: str):
        """Parse natural language command to determine action and path."""
        import os
        cmd_lower = command.lower().strip()

        # Detect action
        action = "list"  # default

        if any(k in cmd_lower for k in ["tạo folder", "tạo thư mục", "create folder", "mkdir", "make dir"]):
            action = "create_folder"
        elif any(k in cmd_lower for k in ["tạo file", "create file", "touch", "new file", "viết file"]):
            action = "create_file"
        elif any(k in cmd_lower for k in ["xóa", "delete", "remove", "rm "]):
            action = "delete"
        elif any(k in cmd_lower for k in ["di chuyển", "move", "mv "]):
            action = "move"
        elif any(k in cmd_lower for k in ["sao chép", "copy", "cp "]):
            action = "copy"
        elif any(k in cmd_lower for k in ["đọc", "read", "cat ", "xem nội dung", "open file"]):
            action = "read"
        elif any(k in cmd_lower for k in ["tìm", "search", "find", "lọc", "filter"]):
            action = "search"
        elif any(k in cmd_lower for k in ["liệt kê", "list", "ls ", "xem folder", "xem thư mục", "duyệt file", "mở thư mục", "browse"]):
            action = "list"

        # Extract search/filter pattern into `content` parameter
        if action in ("list", "search"):
            import re
            m_ext = re.search(r'(?:đuôi|ext|extension|định dạng)\s*\.?([a-zA-Z0-9_]+)', cmd_lower)
            if m_ext:
                content = f"*.{m_ext.group(1)}"
                action = "search"
            else:
                m_wild = re.search(r'([*a-zA-Z0-9_-]*\.[a-zA-Z0-9]{2,5})', cmd_lower)
                if m_wild:
                    ext = m_wild.group(1)
                    if not ext.startswith("*"):
                        content = f"*{ext}" if ext.startswith(".") else f"*{ext}*"
                    else:
                        content = ext
                    action = "search"
                else:
                    m_type = re.search(r'(?:file|danh sách)\s+(video|ảnh|hình|nhạc|âm thanh|tài liệu|word|excel|pdf)', cmd_lower)
                    if m_type:
                        t = m_type.group(1)
                        if t == "video": content = "*.mp4|*.mkv|*.mov|*.avi|*.webm"
                        elif t in ("ảnh", "hình"): content = "*.jpg|*.png|*.jpeg|*.webp|*.gif"
                        elif t in ("nhạc", "âm thanh"): content = "*.mp3|*.wav|*.flac|*.aac"
                        elif t in ("tài liệu", "pdf"): content = "*.pdf"
                        elif t == "word": content = "*.docx|*.doc"
                        elif t == "excel": content = "*.xlsx|*.csv|*.xls"
                        action = "search"
                    else:
                        m_name = re.search(r'(?:tìm|search|find|lọc|filter|liệt kê|list|danh sách)(?:\s+file|\s+thư mục|\s+folder)?\s*(?:có\s+)?(?:tên\s+|chữ\s+|là\s+)?([^ởtạitrên]+)', cmd_lower)
                        if m_name:
                            name = m_name.group(1).strip()
                            # Avoid matching generic paths as names
                            if name and name not in ("file", "các", "những", "danh sách", "thư mục") and "\\" not in name and "/" not in name and "desktop" not in name and "download" not in name:
                                content = f"*{name}*"
                                action = "search"

        # Extract path from command if not explicitly provided
        if not path:
            path = self._extract_path_from_command(command)

        # Extract folder/file name from command
        if action in ("create_folder", "create_file") and path:
            name = self._extract_name_from_command(command)
            if name and not os.path.basename(path):
                path = os.path.join(path, name)
            elif name and os.path.basename(path) != name:
                # The extracted path might be the parent, append name
                if os.path.isdir(os.path.expanduser(path)):
                    path = os.path.join(path, name)

        return action, path, content, destination

    def _extract_path_from_command(self, command: str) -> str:
        """Extract file path from natural language."""
        import os

        # Map common location keywords to paths
        location_map = {
            "desktop": os.path.expanduser("~/Desktop"),
            "màn hình": os.path.expanduser("~/Desktop"),
            "bàn làm việc": os.path.expanduser("~/Desktop"),
            "documents": os.path.expanduser("~/Documents"),
            "tài liệu": os.path.expanduser("~/Documents"),
            "downloads": os.path.expanduser("~/Downloads"),
            "tải về": os.path.expanduser("~/Downloads"),
        }

        cmd_lower = command.lower()
        base_path = os.path.expanduser("~/Desktop")  # default

        for keyword, mapped_path in location_map.items():
            if keyword in cmd_lower:
                base_path = mapped_path
                break

        # Extract quoted name: 'name' or "name"
        name_match = re.search(r"['\"]([^'\"]+)['\"]", command)
        if name_match:
            return os.path.join(base_path, name_match.group(1))

        # Extract name after "tên" or "named" keyword
        name_match2 = re.search(r"(?:tên|named?|gọi là)\s+(\S+)", command, re.IGNORECASE)
        if name_match2:
            return os.path.join(base_path, name_match2.group(1))

        return base_path

    def _extract_name_from_command(self, command: str) -> str:
        """Extract target name from command."""
        # Try quoted name first
        m = re.search(r"['\"]([^'\"]+)['\"]", command)
        if m:
            return m.group(1)

        # Try "tên X" pattern
        m2 = re.search(r"(?:tên|named?|gọi là)\s+(\S+)", command, re.IGNORECASE)
        if m2:
            return m2.group(1)

        return ""
