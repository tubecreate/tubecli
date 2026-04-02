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
                    "liệt kê file", "list files",
                    "quản lý file", "file manager",
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
