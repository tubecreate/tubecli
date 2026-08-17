"""
File Manager Extension — Quản lý file/folder cho AI agents và WebUI.
Cung cấp API tạo, xóa, di chuyển, sao chép file/folder.
"""
import logging
import os
from tubecli.core.extension_manager import Extension

logger = logging.getLogger("FileManagerExtension")


class FileManagerExtension(Extension):
    name = "file_manager"
    version = "1.0.0"
    description = "Quản lý file & folder — API + WebUI file browser"
    author = "TubeCreate"
    enabled_by_default = True

    def setup(self):
        logger.info("File Manager Extension loaded")

    def get_routes(self):
        from tubecli.extensions.file_manager.routes import router
        return router

    def get_nodes(self):
        from tubecli.nodes.file_manager_node import FileManagerNode
        return {"file_manager": FileManagerNode}

    # ── Google Drive actions (chat / Telegram AI) ────────────────
    # The AI emits JSON action blocks; handle_extension_action routes them here.
    # Handlers call this server's own Drive API over HTTP (same pattern as
    # sheets_manager) so validation, threadpooling and error text live in ONE
    # place — drive.py — no matter who triggered the operation.

    def get_telegram_actions(self):
        return {
            "drive_list": self._action_drive_list,
            "drive_upload": self._action_drive_upload,
            "drive_download": self._action_drive_download,
            "drive_rename": self._action_drive_rename,
            "drive_share": self._action_drive_share,
            "drive_mkdir": self._action_drive_mkdir,
            "drive_delete": self._action_drive_delete,
        }

    async def _drive_call(self, method: str, path: str, payload: dict = None, params: dict = None):
        import httpx
        from tubecli.config import get_api_port
        base = f"http://localhost:{get_api_port()}/api/v1/file-manager/drive"
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.request(method, base + path, json=payload, params=params)
            try:
                data = resp.json()
            except Exception:
                data = {"detail": resp.text}
            if resp.status_code != 200:
                raise RuntimeError(str(data.get("detail") or data))
            return data

    @staticmethod
    def _drive_err(e: Exception) -> str:
        return f"❌ Lỗi Google Drive: {e}"

    async def _action_drive_list(self, action_data: dict, context: dict) -> str:
        try:
            params = {
                "folder_id": action_data.get("folder_id") or "root",
                "page_size": 30,
            }
            if action_data.get("cred_id"):
                params["cred_id"] = action_data["cred_id"]
            if action_data.get("query"):
                params["q"] = action_data["query"]
            data = await self._drive_call("GET", "/list", params=params)
            files = data.get("files", [])
            if not files:
                return f"📂 Drive ({data.get('owner_email', '')}): thư mục trống hoặc không có kết quả."
            lines = [f"📂 **Google Drive** — 👤 {data.get('owner_email', '')}"]
            for f in files[:30]:
                icon = "📁" if f.get("is_folder") else "📄"
                link = f" — [mở]({f['url']})" if f.get("url") else ""
                fid = f" `{f.get('id')}`"
                lines.append(f"{icon} {f.get('name')}{fid}{link}")
            if data.get("next_page_token"):
                lines.append("… còn nữa (danh sách đã cắt ở 30 mục).")
            return "\n".join(lines)
        except Exception as e:
            return self._drive_err(e)

    async def _action_drive_upload(self, action_data: dict, context: dict) -> str:
        local_path = action_data.get("local_path") or action_data.get("path") or ""
        if not local_path:
            return "❌ Thiếu 'local_path' — đường dẫn file trên máy chủ cần upload."
        try:
            data = await self._drive_call("POST", "/upload", payload={
                "local_path": local_path,
                "folder_id": action_data.get("folder_id") or "root",
                "cred_id": action_data.get("cred_id"),
                "name": action_data.get("name"),
            })
            f = data.get("file", {})
            msg = "✅ **Đã upload lên Google Drive!**\n\n"
            msg += f"📄 {f.get('name')}\n👤 Tài khoản: {data.get('owner_email', '')}\n"
            if f.get("url"):
                msg += f"🔗 {f['url']}"
            return msg
        except Exception as e:
            return self._drive_err(e)

    async def _action_drive_download(self, action_data: dict, context: dict) -> str:
        file_id = action_data.get("file_id") or ""
        if not file_id:
            return "❌ Thiếu 'file_id' của file trên Drive."
        try:
            data = await self._drive_call("POST", "/download", payload={
                "file_id": file_id,
                "dest_dir": action_data.get("dest_dir") or "~/Downloads",
                "cred_id": action_data.get("cred_id"),
            })
            return (
                "✅ **Đã tải file từ Drive về máy chủ!**\n\n"
                f"📄 {data.get('name')}\n📍 {data.get('path')}\n"
                f"👤 Tài khoản: {data.get('owner_email', '')}"
            )
        except Exception as e:
            return self._drive_err(e)

    async def _action_drive_rename(self, action_data: dict, context: dict) -> str:
        file_id = action_data.get("file_id") or ""
        new_name = action_data.get("new_name") or action_data.get("name") or ""
        if not file_id or not new_name:
            return "❌ Cần cả 'file_id' và 'new_name' để đổi tên."
        try:
            data = await self._drive_call("POST", "/rename", payload={
                "file_id": file_id, "new_name": new_name,
                "cred_id": action_data.get("cred_id"),
            })
            f = data.get("file", {})
            msg = f"✅ **Đã đổi tên thành:** {f.get('name')}\n👤 Tài khoản: {data.get('owner_email', '')}"
            if f.get("url"):
                msg += f"\n🔗 {f['url']}"
            return msg
        except Exception as e:
            return self._drive_err(e)

    async def _action_drive_share(self, action_data: dict, context: dict) -> str:
        file_id = action_data.get("file_id") or ""
        if not file_id:
            return "❌ Thiếu 'file_id' của file cần chia sẻ."
        try:
            data = await self._drive_call("POST", "/share", payload={
                "file_id": file_id,
                "cred_id": action_data.get("cred_id"),
                "type": action_data.get("type") or ("user" if action_data.get("email") else "anyone"),
                "role": action_data.get("role") or "reader",
                "email": action_data.get("email") or "",
            })
            f = data.get("file", {})
            msg = "✅ **Đã chia sẻ!**\n\n"
            msg += f"📄 {f.get('name')}\n🛡️ {data.get('shared_with')} — quyền {data.get('role')}\n"
            msg += f"👤 Tài khoản: {data.get('owner_email', '')}\n"
            if f.get("url"):
                msg += f"🔗 {f['url']}"
            return msg
        except Exception as e:
            return self._drive_err(e)

    async def _action_drive_mkdir(self, action_data: dict, context: dict) -> str:
        name = action_data.get("name") or ""
        if not name:
            return "❌ Thiếu 'name' — tên thư mục cần tạo trên Drive."
        try:
            data = await self._drive_call("POST", "/mkdir", payload={
                "name": name,
                "parent_id": action_data.get("parent_id") or "root",
                "cred_id": action_data.get("cred_id"),
            })
            f = data.get("file", {})
            msg = f"✅ **Đã tạo thư mục Drive:** {f.get('name')}\n👤 Tài khoản: {data.get('owner_email', '')}"
            if f.get("url"):
                msg += f"\n🔗 {f['url']}"
            return msg
        except Exception as e:
            return self._drive_err(e)

    async def _action_drive_delete(self, action_data: dict, context: dict) -> str:
        file_id = action_data.get("file_id") or ""
        if not file_id:
            return "❌ Thiếu 'file_id' của file cần xóa."
        try:
            data = await self._drive_call("POST", "/trash", payload={
                "file_id": file_id, "cred_id": action_data.get("cred_id"),
            })
            f = data.get("file", {})
            return (
                f"✅ **Đã chuyển vào thùng rác Drive:** {f.get('name')}\n"
                f"👤 Tài khoản: {data.get('owner_email', '')}\n"
                f"(Khôi phục được trong 30 ngày tại drive.google.com/drive/trash)"
            )
        except Exception as e:
            return self._drive_err(e)

    def get_skills(self):
        return [
            {
                "name": "📁 File Manager",
                "description": "Tạo, xóa, di chuyển, liệt kê file và folder trên máy tính. AI có thể quản lý file trực tiếp.",
                "skill_type": "Skill",
                "commands": [
                    "tạo folder", "tạo thư mục", "create folder",
                    "tạo file", "create file",
                    "xóa file", "delete file",
                    "liệt kê file", "list files", "duyệt file", "xem thư mục", "browse files",
                    "tìm file", "search file", "lọc", "filter file", "tìm kiếm",
                    "quản lý file", "file manager",
                    "google drive", "drive", "upload drive", "tải lên drive",
                    "upload lên drive", "đưa lên drive", "tải từ drive",
                    "chia sẻ file", "share file", "đổi tên file drive",
                    "liệt kê drive", "xem drive", "list drive",
                ],
                "workflow_data": {
                    "name": "File Manager",
                    "nodes": [
                        {
                            "id": "user_input",
                            "type": "text_input",
                            "label": "📝 Input",
                            "config": {"text": ""},
                        },
                        {
                            "id": "file_op",
                            "type": "file_manager",
                            "label": "📁 File Manager",
                            "config": {"action": "auto"},
                        },
                        {
                            "id": "result_output",
                            "type": "output",
                            "label": "📤 Output",
                            "config": {"print": True},
                        },
                    ],
                    "connections": [
                        {
                            "from_node_id": "user_input",
                            "from_port_id": "content",
                            "to_node_id": "file_op",
                            "to_port_id": "command",
                        },
                        {
                            "from_node_id": "file_op",
                            "from_port_id": "result",
                            "to_node_id": "result_output",
                            "to_port_id": "data",
                        },
                    ],
                },
            }
        ]
