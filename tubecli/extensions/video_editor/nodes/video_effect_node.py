"""
Video Effect Node — Apply visual effects and filters to video.
"""
import os
from typing import Dict, Any
from tubecli.nodes.base_node import BaseNode, PortType


class VideoEffectNode(BaseNode):
    node_type = "video_effect"
    display_name = "✨ Video Effect"
    description = "Apply visual effects and filters (blur, speed, grayscale, etc.)"
    icon = "✨"
    category = "Video"

    def _setup_ports(self):
        self.add_input("input_file", PortType.FILE, "Input video file path", required=True)
        self.add_input("effect", PortType.TEXT, "Effect name (e.g. blur, grayscale, speed_2x, rotate_90)", required=True)
        self.add_output("output_file", PortType.FILE, "Processed video file path")
        self.add_output("status", PortType.TEXT, "Operation status")

    async def execute(self, inputs: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        input_file = inputs.get("input_file") or self.config.get("input_file", "")
        effect = inputs.get("effect") or self.config.get("effect", "")

        if not input_file or not os.path.exists(input_file):
            return {"output_file": "", "status": "error: input file not found"}
        if not effect:
            return {"output_file": "", "status": "error: effect name is required"}

        base = os.path.splitext(os.path.basename(input_file))[0]
        ext = os.path.splitext(input_file)[1] or ".mp4"
        data_dir = os.environ.get("TUBECLI_DATA_DIR", "data")
        output_dir = os.path.join(data_dir, "video_editor", "exports")
        os.makedirs(output_dir, exist_ok=True)
        output_file = os.path.join(output_dir, f"{base}_{effect}{ext}")

        try:
            import importlib.util
            engine_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "video_engine.py")
            spec = importlib.util.spec_from_file_location("ve_engine", engine_path)
            engine = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(engine)

            params = {}
            if effect == "custom":
                params["filter"] = self.config.get("custom_filter", "")

            result = await engine.apply_effect(input_file, effect, output_file, params)
            return {
                "output_file": result.get("output", output_file),
                "status": "success",
            }
        except Exception as e:
            return {"output_file": "", "status": f"error: {e}"}
