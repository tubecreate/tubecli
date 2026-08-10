"""
Video Export Node — Export video with format, quality, and resolution settings.
"""
import os
import uuid
from typing import Dict, Any
from tubecli.nodes.base_node import BaseNode, PortType


class VideoExportNode(BaseNode):
    node_type = "video_export"
    display_name = "📤 Video Export"
    description = "Export video with specified format, quality, resolution, and FPS"
    icon = "📤"
    category = "Video"

    def _setup_ports(self):
        self.add_input("input_file", PortType.FILE, "Input video file path", required=True)
        self.add_input("format", PortType.TEXT, "Output format: mp4, webm, avi, mov, gif", required=False)
        self.add_input("quality", PortType.TEXT, "Quality: low, medium, high, ultra", required=False)
        self.add_input("resolution", PortType.TEXT, "Resolution: 360p, 480p, 720p, 1080p, 1440p, 4k", required=False)
        self.add_output("output_file", PortType.FILE, "Exported video file path")
        self.add_output("file_size", PortType.TEXT, "Output file size in bytes")
        self.add_output("status", PortType.TEXT, "Operation status")

    async def execute(self, inputs: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        input_file = inputs.get("input_file") or self.config.get("input_file", "")
        fmt = inputs.get("format") or self.config.get("format", "mp4")
        quality = inputs.get("quality") or self.config.get("quality", "high")
        resolution = inputs.get("resolution") or self.config.get("resolution")
        fps = self.config.get("fps")

        if not input_file or not os.path.exists(input_file):
            return {"output_file": "", "file_size": "0", "status": "error: input file not found"}

        base = os.path.splitext(os.path.basename(input_file))[0]
        ext = f".{fmt}" if fmt else ".mp4"
        data_dir = os.environ.get("TUBECLI_DATA_DIR", "data")
        output_dir = os.path.join(data_dir, "video_editor", "exports")
        os.makedirs(output_dir, exist_ok=True)
        output_file = os.path.join(output_dir, f"{base}_export_{uuid.uuid4().hex[:6]}{ext}")

        try:
            import importlib.util
            engine_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "video_engine.py")
            spec = importlib.util.spec_from_file_location("ve_engine", engine_path)
            engine = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(engine)

            result = await engine.export_video(
                input_file, output_file,
                format=fmt,
                quality=quality,
                resolution=resolution,
                fps=int(fps) if fps else None,
            )
            return {
                "output_file": result.get("output", output_file),
                "file_size": str(result.get("file_size", 0)),
                "status": "success",
            }
        except Exception as e:
            return {"output_file": "", "file_size": "0", "status": f"error: {e}"}
