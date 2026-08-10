"""
Video Merge Node — Concatenate multiple video files.
"""
import os
import json
from typing import Dict, Any
from tubecli.nodes.base_node import BaseNode, PortType


class VideoMergeNode(BaseNode):
    node_type = "video_merge"
    display_name = "🔗 Video Merge"
    description = "Merge/concatenate multiple video files into one"
    icon = "🔗"
    category = "Video"

    def _setup_ports(self):
        self.add_input("input_files", PortType.TEXT, "Input files (JSON array or comma-separated paths)", required=True)
        self.add_input("transition", PortType.TEXT, "Transition type: none, fade, dissolve", required=False)
        self.add_output("output_file", PortType.FILE, "Merged video file path")
        self.add_output("status", PortType.TEXT, "Operation status")

    async def execute(self, inputs: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        raw_files = inputs.get("input_files") or self.config.get("input_files", "")
        transition = inputs.get("transition") or self.config.get("transition", "none")

        # Parse input files
        if isinstance(raw_files, list):
            file_list = raw_files
        elif raw_files.strip().startswith("["):
            try:
                file_list = json.loads(raw_files)
            except Exception:
                file_list = [f.strip() for f in raw_files.split(",")]
        else:
            file_list = [f.strip() for f in raw_files.split(",")]

        file_list = [f for f in file_list if f and os.path.exists(f)]
        if len(file_list) < 2:
            return {"output_file": "", "status": "error: need at least 2 valid input files"}

        data_dir = os.environ.get("TUBECLI_DATA_DIR", "data")
        output_dir = os.path.join(data_dir, "video_editor", "exports")
        os.makedirs(output_dir, exist_ok=True)
        output_file = os.path.join(output_dir, "merged_output.mp4")

        try:
            import importlib.util
            engine_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "video_engine.py")
            spec = importlib.util.spec_from_file_location("ve_engine", engine_path)
            engine = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(engine)

            result = await engine.merge(file_list, output_file, transition)
            return {
                "output_file": result.get("output", output_file),
                "status": "success",
            }
        except Exception as e:
            return {"output_file": "", "status": f"error: {e}"}
