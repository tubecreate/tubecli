"""
Video Trim Node — Cut video by start/end time.
"""
import os
import asyncio
from typing import Dict, Any
from tubecli.nodes.base_node import BaseNode, PortType


class VideoTrimNode(BaseNode):
    node_type = "video_trim"
    display_name = "✂️ Video Trim"
    description = "Trim/cut a video segment by specifying start and end time"
    icon = "✂️"
    category = "Video"

    def _setup_ports(self):
        self.add_input("input_file", PortType.FILE, "Input video file path", required=True)
        self.add_input("start_time", PortType.TEXT, "Start time (e.g. 00:00:05 or 5)", required=True)
        self.add_input("end_time", PortType.TEXT, "End time (e.g. 00:00:15 or 15)", required=True)
        self.add_output("output_file", PortType.FILE, "Trimmed video file path")
        self.add_output("status", PortType.TEXT, "Operation status")

    async def execute(self, inputs: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        input_file = inputs.get("input_file") or self.config.get("input_file", "")
        start = inputs.get("start_time") or self.config.get("start_time", "0")
        end = inputs.get("end_time") or self.config.get("end_time", "10")

        if not input_file or not os.path.exists(input_file):
            return {"output_file": "", "status": "error: input file not found"}

        # Generate output path
        base = os.path.splitext(os.path.basename(input_file))[0]
        ext = os.path.splitext(input_file)[1] or ".mp4"
        data_dir = os.environ.get("TUBECLI_DATA_DIR", "data")
        output_dir = os.path.join(data_dir, "video_editor", "exports")
        os.makedirs(output_dir, exist_ok=True)
        output_file = os.path.join(output_dir, f"{base}_trim{ext}")

        try:
            import importlib.util
            engine_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "video_engine.py")
            spec = importlib.util.spec_from_file_location("ve_engine", engine_path)
            engine = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(engine)

            result = await engine.trim(input_file, start, end, output_file)
            return {
                "output_file": result.get("output", output_file),
                "status": "success",
            }
        except Exception as e:
            return {"output_file": "", "status": f"error: {e}"}
