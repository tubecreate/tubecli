"""
Video Overlay Node — Add text or image overlay to video.
"""
import os
from typing import Dict, Any
from tubecli.nodes.base_node import BaseNode, PortType


class VideoOverlayNode(BaseNode):
    node_type = "video_overlay"
    display_name = "📝 Video Overlay"
    description = "Add text or image/watermark overlay on a video"
    icon = "📝"
    category = "Video"

    def _setup_ports(self):
        self.add_input("input_file", PortType.FILE, "Input video file path", required=True)
        self.add_input("overlay_type", PortType.TEXT, "Overlay type: text or image", required=False)
        self.add_input("text", PortType.TEXT, "Text content (for text overlay)", required=False)
        self.add_input("overlay_file", PortType.FILE, "Image file path (for image overlay)", required=False)
        self.add_input("position", PortType.TEXT, "Position: top-left, center, bottom-center, custom x:y", required=False)
        self.add_output("output_file", PortType.FILE, "Output video file path")
        self.add_output("status", PortType.TEXT, "Operation status")

    async def execute(self, inputs: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        input_file = inputs.get("input_file") or self.config.get("input_file", "")
        overlay_type = inputs.get("overlay_type") or self.config.get("overlay_type", "text")
        text = inputs.get("text") or self.config.get("text", "")
        overlay_file = inputs.get("overlay_file") or self.config.get("overlay_file", "")
        position = inputs.get("position") or self.config.get("position", "bottom-center")

        if not input_file or not os.path.exists(input_file):
            return {"output_file": "", "status": "error: input file not found"}

        # Parse position
        position_map = {
            "top-left": ("10", "10"),
            "top-center": ("(w-text_w)/2", "10"),
            "top-right": ("w-text_w-10", "10"),
            "center": ("(w-text_w)/2", "(h-text_h)/2"),
            "bottom-left": ("10", "h-th-20"),
            "bottom-center": ("(w-text_w)/2", "h-th-20"),
            "bottom-right": ("w-text_w-10", "h-th-20"),
        }
        if position in position_map:
            x, y = position_map[position]
        elif ":" in position:
            x, y = position.split(":", 1)
        else:
            x, y = "(w-text_w)/2", "h-th-20"

        base = os.path.splitext(os.path.basename(input_file))[0]
        ext = os.path.splitext(input_file)[1] or ".mp4"
        data_dir = os.environ.get("TUBECLI_DATA_DIR", "data")
        output_dir = os.path.join(data_dir, "video_editor", "exports")
        os.makedirs(output_dir, exist_ok=True)
        output_file = os.path.join(output_dir, f"{base}_overlay{ext}")

        try:
            import importlib.util
            engine_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "video_engine.py")
            spec = importlib.util.spec_from_file_location("ve_engine", engine_path)
            engine = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(engine)

            if overlay_type == "text":
                if not text:
                    return {"output_file": "", "status": "error: text content is required"}
                result = await engine.overlay_text(
                    input_file, text, output_file,
                    x=x, y=y,
                    fontsize=int(self.config.get("fontsize", 36)),
                    fontcolor=self.config.get("fontcolor", "white"),
                )
            else:
                if not overlay_file or not os.path.exists(overlay_file):
                    return {"output_file": "", "status": "error: overlay image file not found"}
                result = await engine.overlay_image(
                    input_file, overlay_file, output_file,
                    x=x, y=y,
                    scale=float(self.config.get("scale", 1.0)),
                    opacity=float(self.config.get("opacity", 1.0)),
                )

            return {
                "output_file": result.get("output", output_file),
                "status": "success",
            }
        except Exception as e:
            return {"output_file": "", "status": f"error: {e}"}
