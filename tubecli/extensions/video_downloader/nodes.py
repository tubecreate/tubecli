"""
Video Download Node — Workflow node for downloading video via yt-dlp.
Can be used in TubeCLI workflow builder with input/output ports.
"""
import os
import re
import sys
import glob
import shutil
import subprocess
import asyncio
from typing import Dict, Any

from tubecli.nodes.base_node import BaseNode, PortType


class VideoDownloadNode(BaseNode):
    node_type = "video_download"
    display_name = "📹 Video Download"
    description = "Download video from YouTube, TikTok, and 50+ platforms using yt-dlp"
    icon = "📹"
    category = "Media"

    # Declared so /api/v1/nodes advertises them: the properties panel builds
    # itself from this, and the LLM catalog teaches the model these exact key
    # names. Empty, as it was, the panel showed only a Node Label field and the
    # model had to guess. Keys and defaults match what execute() reads.
    config_schema = {
        "url": {
            "type": "string", "default": "",
            "description": "Video link. Optional when the `url` input port is connected.",
        },
        "format": {
            "type": "select", "default": "mp4", "options": ["mp4", "mp3"],
            "description": "mp4 keeps the video; mp3 extracts audio only.",
        },
        "quality": {
            "type": "select", "default": "720p",
            "options": ["360p", "480p", "720p", "1080p", "best"],
            "description": "Higher quality means a bigger file and a slower download.",
        },
        "title": {
            "type": "string", "default": "video",
            "description": "Base name for the saved file.",
        },
        "proxy": {
            "type": "string", "default": "",
            "description": "Optional proxy, e.g. socks5://host:port.",
        },
    }

    def _setup_ports(self):
        self.add_input("url", PortType.TEXT, "Video URL (YouTube, TikTok, etc.)", required=True)
        self.add_input("format", PortType.TEXT, "Output format: mp4, mp3", required=False)
        self.add_input("quality", PortType.TEXT, "Quality: 360p, 480p, 720p, 1080p, best", required=False)
        self.add_output("file_path", PortType.TEXT, "Downloaded file path")
        self.add_output("filename", PortType.TEXT, "Downloaded filename")
        self.add_output("status", PortType.TEXT, "Download status")

    async def execute(self, inputs: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        url = inputs.get("url") or self.config.get("url", "")
        fmt = inputs.get("format") or self.config.get("format", "mp4")
        quality = inputs.get("quality") or self.config.get("quality", "720p")
        proxy = self.config.get("proxy")
        title = self.config.get("title", "video")

        if not url:
            return {"file_path": "", "filename": "", "status": "error: no URL provided"}

        # Ensure yt-dlp is available
        if shutil.which("yt-dlp") is None:
            try:
                subprocess.run(
                    [sys.executable, "-m", "pip", "install", "yt-dlp"],
                    capture_output=True, timeout=120,
                )
            except Exception as e:
                return {"file_path": "", "filename": "", "status": f"error: cannot install yt-dlp: {e}"}

        # Prepare output
        data_dir = os.environ.get("TUBECLI_DATA_DIR", "data")
        dl_dir = os.path.join(data_dir, "ytdl_downloads")
        os.makedirs(dl_dir, exist_ok=True)

        clean_title = re.sub(r'[\\/*?:"<>|]', "", title).strip()[:120] or "video"
        output_template = os.path.join(dl_dir, f"{clean_title}.%(ext)s")

        # Build yt-dlp command
        cmd = ["yt-dlp", "-o", output_template]

        if fmt == "mp3":
            cmd.extend(["-x", "--audio-format", "mp3"])
        else:
            height = quality.replace("p", "")
            if height == "best":
                cmd.extend(["-f", "bestvideo+bestaudio/best", "--merge-output-format", "mp4"])
            else:
                cmd.extend([
                    "-f", f"bestvideo[height<={height}]+bestaudio/best[height<={height}]/best",
                    "--merge-output-format", "mp4",
                ])

        if proxy:
            cmd.extend(["--proxy", proxy])

        cmd.append(url)

        try:
            result = await asyncio.to_thread(
                lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            )

            if result.returncode != 0:
                return {"file_path": "", "filename": "", "status": f"error: {result.stderr[:300]}"}

            # Find output file
            ext = "mp3" if fmt == "mp3" else "mp4"
            pattern = os.path.join(dl_dir, f"{clean_title}.*")
            files = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
            output_file = files[0] if files else output_template.replace("%(ext)s", ext)

            return {
                "file_path": output_file,
                "filename": os.path.basename(output_file),
                "status": "success",
            }

        except subprocess.TimeoutExpired:
            return {"file_path": "", "filename": "", "status": "error: download timeout"}
        except Exception as e:
            return {"file_path": "", "filename": "", "status": f"error: {e}"}
