"""
Video Processing Node — Single unified node for ALL video operations.
Uses a dropdown preset to select operation: trim, merge, overlay, effect, export, custom ffmpeg.
AI only needs to wire 1 node and pick the right preset.

Inspired by python-video-studio's FFmpegCommandNode pattern.
"""
import os
import asyncio
from typing import Dict, Any, Optional
from tubecli.nodes.base_node import BaseNode, PortType


class VideoProcessingNode(BaseNode):
    node_type = "video_processing"
    display_name = "🎬 Video Processing"
    description = "All-in-one video node: trim, merge, effect, overlay, export, or custom FFmpeg command"
    icon = "🎬"
    category = "Video"

    # Declared so the config panel and the LLM catalog can both see them. This
    # was empty, so /api/v1/nodes advertised no config at all for the node the
    # AI prompt calls the answer to "ANY video processing task": the panel showed
    # only a Node Label field, and the model had to guess key names. `options`
    # for `operation` is filled in below from OPERATIONS, the single source of
    # truth, so the list cannot drift from what execute() actually accepts.
    config_schema = {
        "operation": {
            "type": "select", "default": "trim", "required": True,
            "description": "What to do with the video. Every other field is optional.",
        },
        "output_dir": {
            "type": "string", "default": "",
            "description": "Where to write the result. Empty = the default exports folder.",
        },
        "output_suffix": {
            "type": "string", "default": "_processed",
            "description": "Appended to the output filename.",
        },
        "start_time": {
            "type": "string", "default": "0",
            "description": "Trim only. Start position, e.g. 0 or 00:00:05.",
        },
        "end_time": {
            "type": "string", "default": "10",
            "description": "Trim only. End position, e.g. 10 or 00:00:15.",
        },
        "text": {
            "type": "string", "default": "",
            "description": "overlay_text only. The caption to burn in.",
        },
        "command": {
            "type": "textarea", "default": "",
            "description": "custom only. Raw FFmpeg arguments; {input} and {output} are substituted.",
        },
    }

    # ── Operation Presets ────────────────────────────────────────────
    OPERATIONS = {
        # --- Trim & Cut ---
        "trim":              {"cmd": "-i {input} -ss {start_time} -to {end_time} -c copy -avoid_negative_ts make_zero {output}",       "label": "✂️ Trim (Cut)"},
        "trim_reencode":     {"cmd": "-i {input} -ss {start_time} -to {end_time} -c:v {codec} -c:a aac {output}",                      "label": "✂️ Trim (Re-encode)"},

        # --- Effects ---
        "grayscale":         {"cmd": "-i {input} -vf colorchannelmixer=.3:.4:.3:0:.3:.4:.3:0:.3:.4:.3 -c:v {codec} -c:a copy {output}", "label": "🔲 Grayscale"},
        "sepia":             {"cmd": "-i {input} -vf colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131 -c:v {codec} -c:a copy {output}", "label": "🟤 Sepia"},
        "blur":              {"cmd": "-i {input} -vf boxblur=5:1 -c:v {codec} -c:a copy {output}",                                     "label": "🌫️ Blur"},
        "sharpen":           {"cmd": "-i {input} -vf unsharp=5:5:1.5:5:5:0.0 -c:v {codec} -c:a copy {output}",                         "label": "🔍 Sharpen"},
        "negative":          {"cmd": "-i {input} -vf negate -c:v {codec} -c:a copy {output}",                                           "label": "🎞️ Negative"},
        "vintage":           {"cmd": "-i {input} -vf curves=vintage -c:v {codec} -c:a copy {output}",                                   "label": "📷 Vintage"},
        "vignette":          {"cmd": "-i {input} -vf vignette=PI/4 -c:v {codec} -c:a copy {output}",                                    "label": "🔘 Vignette"},

        # --- Transform ---
        "speed_2x":          {"cmd": "-i {input} -filter:v setpts=0.5*PTS -filter:a atempo=2.0 -c:v {codec} {output}",                  "label": "⏩ Speed 2x"},
        "speed_05x":         {"cmd": "-i {input} -filter:v setpts=2.0*PTS -filter:a atempo=0.5 -c:v {codec} {output}",                  "label": "🐌 Speed 0.5x"},
        "rotate_90":         {"cmd": "-i {input} -vf transpose=1 -c:v {codec} -c:a copy {output}",                                      "label": "↻ Rotate 90°"},
        "rotate_180":        {"cmd": "-i {input} -vf transpose=1,transpose=1 -c:v {codec} -c:a copy {output}",                           "label": "🔄 Rotate 180°"},
        "flip_h":            {"cmd": "-i {input} -vf hflip -c:v {codec} -c:a copy {output}",                                            "label": "↔️ Flip Horizontal"},
        "flip_v":            {"cmd": "-i {input} -vf vflip -c:v {codec} -c:a copy {output}",                                            "label": "↕️ Flip Vertical"},

        # --- Resize ---
        "resize_720p":       {"cmd": "-i {input} -vf scale=-1:720 -c:v {codec} -c:a copy {output}",                                     "label": "📐 Resize 720p"},
        "resize_1080p":      {"cmd": "-i {input} -vf scale=-1:1080 -c:v {codec} -c:a copy {output}",                                    "label": "📐 Resize 1080p"},
        "resize_480p":       {"cmd": "-i {input} -vf scale=-1:480 -c:v {codec} -c:a copy {output}",                                     "label": "📐 Resize 480p"},

        # --- Audio ---
        "extract_audio":     {"cmd": "-i {input} -vn -acodec mp3 -ab 192k {output}", "ext": ".mp3",                                     "label": "🎵 Extract Audio"},
        "remove_audio":      {"cmd": "-i {input} -an -c:v copy {output}",                                                               "label": "🔇 Remove Audio"},
        "add_audio":         {"cmd": "-i {input} -i {audio} -c:v copy -c:a aac -shortest {output}",                                     "label": "🔊 Add Audio Track"},

        # --- Merge ---
        "merge_concat":      {"cmd": "MERGE_CONCAT",                                                                                    "label": "🔗 Merge / Concat Videos"},

        # --- Overlay ---
        "overlay_text":      {"cmd": "OVERLAY_TEXT",                                                                                     "label": "📝 Text Overlay"},
        "overlay_image":     {"cmd": "OVERLAY_IMAGE",                                                                                    "label": "🖼️ Image/Watermark Overlay"},

        # --- Convert ---
        "convert_mp4":       {"cmd": "-i {input} -c:v {codec} -c:a aac {output}",                                                       "label": "📦 Convert to MP4"},
        "convert_webm":      {"cmd": "-i {input} -c:v libvpx-vp9 -c:a libopus {output}", "ext": ".webm",                                "label": "📦 Convert to WebM"},
        "convert_gif":       {"cmd": "-i {input} -vf fps=10,scale=480:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse -loop 0 {output}", "ext": ".gif", "label": "📦 Convert to GIF"},

        # --- Export ---
        "export_high":       {"cmd": "-i {input} -c:v {codec} -crf 18 -preset slow -c:a aac -b:a 192k {output}",                        "label": "📤 Export (High Quality)"},
        "export_medium":     {"cmd": "-i {input} -c:v {codec} -crf 23 -preset medium -c:a aac -b:a 128k {output}",                      "label": "📤 Export (Medium)"},
        "export_fast":       {"cmd": "-i {input} -c:v {codec} -crf 28 -preset fast -c:a aac -b:a 96k {output}",                         "label": "📤 Export (Fast/Small)"},

        # --- Misc ---
        "fade_in_out":       {"cmd": "-i {input} -vf fade=t=in:st=0:d=1,fade=t=out:st=9:d=1 -c:v {codec} -c:a copy {output}",           "label": "🌅 Fade In + Out"},
        "stabilize":         {"cmd": "-i {input} -vf deshake -c:v {codec} -c:a copy {output}",                                           "label": "📹 Stabilize"},
        "reverse":           {"cmd": "-i {input} -vf reverse -af areverse -c:v {codec} {output}",                                        "label": "⏪ Reverse"},
        "thumbnail":         {"cmd": "-i {input} -ss {start_time} -vframes 1 -vf scale=320:-1 {output}", "ext": ".jpg",                  "label": "🖼️ Extract Thumbnail"},

        # --- Custom ---
        "custom":            {"cmd": "",                                                                                                  "label": "⚙️ Custom FFmpeg Command"},
    }

    # Filled from OPERATIONS so the advertised choices and the ones execute()
    # accepts are the same list by construction, not by anyone remembering.
    config_schema["operation"]["options"] = list(OPERATIONS.keys())

    def _setup_ports(self):
        self.add_input("input_file", PortType.FILE, "Input video/audio file path", required=True)
        self.add_input("input_files", PortType.TEXT, "Multiple input paths (comma-separated, for merge)", required=False)
        self.add_input("audio_file", PortType.TEXT, "Audio file path (for add_audio / overlay)", required=False)
        self.add_input("start_time", PortType.TEXT, "Start time for trim (e.g. 00:00:05 or 5)", required=False)
        self.add_input("end_time", PortType.TEXT, "End time for trim (e.g. 00:00:15 or 15)", required=False)
        self.add_input("text", PortType.TEXT, "Text content (for overlay_text)", required=False)
        self.add_input("output_dir", PortType.TEXT, "Output folder (leave empty for default)", required=False)
        self.add_output("output_file", PortType.FILE, "Output file path")
        self.add_output("status", PortType.TEXT, "Operation status")

    def get_config_fields(self):
        options = [(k, v["label"]) for k, v in self.OPERATIONS.items()]
        return [
            {
                "name": "operation",
                "type": "dropdown",
                "label": "Operation",
                "default": "trim",
                "options": options,
            },
            {
                "name": "command",
                "type": "textarea",
                "label": "FFmpeg Command (editable, auto-filled by preset)",
                "default": self.OPERATIONS["trim"]["cmd"],
                "placeholder": "Variables: {input}, {output}, {audio}, {codec}, {start_time}, {end_time}",
            },
            {
                "name": "output_suffix",
                "type": "text",
                "label": "Output Suffix",
                "default": "_processed",
            },
            {
                "name": "output_dir",
                "type": "text",
                "label": "Output Directory (empty = default exports)",
                "default": "",
            },
        ]

    def validate_config(self, field_name: str, value: Any) -> Dict[str, Any]:
        """When user changes operation dropdown, auto-fill the command textarea."""
        if field_name == "operation" and value in self.OPERATIONS:
            op = self.OPERATIONS[value]
            return {"command": op["cmd"]}
        return {}

    async def execute(self, inputs: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        import logging
        logger = logging.getLogger("video_processing_node")
        logger.info(f"[VideoProcessing] Raw inputs received: {inputs}")
        logger.info(f"[VideoProcessing] Config values: {self.config.values if hasattr(self.config, 'values') else self.config}")

        # Try multiple sources for the input file path
        input_file = (
            inputs.get("input_file")
            or inputs.get("input")
            or inputs.get("current_item")
            or inputs.get("result")
            or inputs.get("output_file")
            or inputs.get("content")
            or self.config.get("input_file", "")
        )

        # Sanitize: strip surrounding quotes and whitespace
        if isinstance(input_file, str):
            input_file = input_file.strip().strip('"').strip("'").strip()
        
        # If it's a list, take the first element
        if isinstance(input_file, list) and len(input_file) > 0:
            input_file = str(input_file[0]).strip().strip('"').strip("'")

        logger.info(f"[VideoProcessing] Resolved input_file: '{input_file}' | exists: {os.path.exists(input_file) if input_file else False}")
        
        if not input_file or not os.path.exists(input_file):
            return {"output_file": "", "status": f"error: input file not found (got: '{input_file}')"}

        operation = self.config.get("operation", "trim")
        command_template = self.config.get("command", "")
        output_suffix = self.config.get("output_suffix", "_processed")

        # Load engine
        import importlib.util
        engine_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "video_engine.py",
        )
        spec = importlib.util.spec_from_file_location("ve_engine", engine_path)
        engine = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(engine)

        # Detect GPU
        codec, encoder_name = engine.detect_gpu_encoder()

        # Output path
        op_meta = self.OPERATIONS.get(operation, {})
        ext = op_meta.get("ext", os.path.splitext(input_file)[1] or ".mp4")
        base = os.path.splitext(os.path.basename(input_file))[0]
        
        # Determine output directory: input port > config > default
        output_dir = (
            inputs.get("output_dir")
            or self.config.get("output_dir", "")
        )
        if output_dir:
            output_dir = output_dir.strip().strip('"').strip("'")
        if not output_dir:
            data_dir = os.environ.get("TUBECLI_DATA_DIR", "data")
            output_dir = os.path.join(data_dir, "video_editor", "exports")
        os.makedirs(output_dir, exist_ok=True)
        output_file = os.path.join(output_dir, f"{base}{output_suffix}{ext}")

        # ── Special Operations (need custom logic) ──
        try:
            if operation == "merge_concat":
                raw = inputs.get("input_files") or self.config.get("input_files", "")
                files = [f.strip() for f in raw.split(",") if f.strip()]
                if not files:
                    files = [input_file]
                result = await engine.merge(files, output_file)
                return {"output_file": result.get("output", output_file), "status": "success"}

            if operation == "overlay_text":
                text = inputs.get("text") or self.config.get("text", "Hello")
                result = await engine.overlay_text(input_file, text, output_file)
                return {"output_file": result.get("output", output_file), "status": "success"}

            if operation == "overlay_image":
                overlay_img = inputs.get("audio_file") or self.config.get("overlay_image", "")
                result = await engine.overlay_image(input_file, overlay_img, output_file)
                return {"output_file": result.get("output", output_file), "status": "success"}

            # ── Generic FFmpeg Command Execution ──
            if not command_template:
                command_template = op_meta.get("cmd", "")

            if not command_template:
                return {"output_file": "", "status": "error: no command template"}

            # Replace variables
            variables = {
                "{input}": f'"{input_file}"',
                "{output}": f'"{output_file}"',
                "{audio}": f'"{inputs.get("audio_file", "")}"',
                "{codec}": codec,
                "{start_time}": inputs.get("start_time") or self.config.get("start_time", "0"),
                "{end_time}": inputs.get("end_time") or self.config.get("end_time", "10"),
                "{text}": inputs.get("text") or self.config.get("text", ""),
            }

            command = command_template
            for var, val in variables.items():
                command = command.replace(var, val)

            ffmpeg_path = engine.get_ffmpeg_path()
            if not ffmpeg_path:
                return {"output_file": "", "status": "error: ffmpeg not found"}

            full_cmd = f'"{ffmpeg_path}" -y {command}'

            process = await asyncio.create_subprocess_shell(
                full_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()

            if process.returncode == 0 and os.path.exists(output_file):
                return {
                    "output_file": output_file,
                    "status": f"success ({encoder_name})",
                }
            else:
                err = stderr.decode(errors="ignore")[-300:] if stderr else "Unknown error"
                return {"output_file": "", "status": f"error: {err}"}

        except Exception as e:
            return {"output_file": "", "status": f"error: {e}"}
