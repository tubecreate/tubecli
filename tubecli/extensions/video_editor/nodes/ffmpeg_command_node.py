"""
FFmpeg Command Node — Run arbitrary FFmpeg commands.
Power-user node for custom video processing pipelines.
"""
import os
from typing import Dict, Any
from tubecli.nodes.base_node import BaseNode, PortType


class FFmpegCommandNode(BaseNode):
    node_type = "ffmpeg_command"
    display_name = "🎬 FFmpeg Command"
    description = "Run a custom FFmpeg command for advanced video processing"
    icon = "🎬"
    category = "Video"

    def _setup_ports(self):
        self.add_input("command", PortType.TEXT, "FFmpeg arguments (without 'ffmpeg' prefix)", required=True)
        self.add_input("input_file", PortType.FILE, "Optional input file (replaces {input} in command)", required=False)
        self.add_output("output_file", PortType.FILE, "Output file path (if produced)")
        self.add_output("stdout", PortType.TEXT, "FFmpeg stdout output")
        self.add_output("status", PortType.TEXT, "Operation status")

    async def execute(self, inputs: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        command = inputs.get("command") or self.config.get("command", "")
        input_file = inputs.get("input_file") or self.config.get("input_file", "")

        if not command:
            return {"output_file": "", "stdout": "", "status": "error: command is required"}

        # Replace {input} placeholder with actual file path
        if input_file and "{input}" in command:
            command = command.replace("{input}", input_file)

        # Auto-detect output file from -o or last argument
        output_file = ""
        parts = command.split()
        for i, p in enumerate(parts):
            if p in ("-o", "-output") and i + 1 < len(parts):
                output_file = parts[i + 1]
                break

        try:
            import importlib.util
            engine_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "video_engine.py")
            spec = importlib.util.spec_from_file_location("ve_engine", engine_path)
            engine = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(engine)

            result = await engine.run_custom_ffmpeg(command, input_file)
            return {
                "output_file": output_file,
                "stdout": result.get("stdout", "") + result.get("stderr", ""),
                "status": result.get("status", "unknown"),
            }
        except Exception as e:
            return {"output_file": "", "stdout": "", "status": f"error: {e}"}
