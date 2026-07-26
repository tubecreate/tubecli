"""
ffmpeg/ffprobe helpers for video_studio.

Kept separate so the engines never shell out ad hoc, and so a missing ffmpeg
produces one clear message instead of a raw OSError deep in a filter chain.
"""
import logging
import os
import shutil
import subprocess
from typing import List, Optional, Tuple

logger = logging.getLogger("VideoStudio")

# Windows: never flash a console window for a background ffmpeg call.
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def _which(name: str) -> Optional[str]:
    found = shutil.which(name)
    if found:
        return found
    # Honour an explicit path from global settings, like the rest of the app.
    try:
        import json

        from tubecli.config import DATA_DIR

        settings_file = os.path.join(str(DATA_DIR), "global_settings.json")
        if os.path.exists(settings_file):
            with open(settings_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            configured = data.get("ffmpeg_path") or ""
            if configured:
                base = os.path.dirname(configured) if os.path.isfile(configured) else configured
                candidate = os.path.join(base, name + (".exe" if os.name == "nt" else ""))
                if os.path.isfile(candidate):
                    return candidate
    except Exception:
        pass
    return None


def find_ffmpeg() -> Optional[str]:
    return _which("ffmpeg")


def find_ffprobe() -> Optional[str]:
    return _which("ffprobe")


def require_ffmpeg() -> str:
    exe = find_ffmpeg()
    if not exe:
        raise RuntimeError(
            "ffmpeg not found. Install it from https://ffmpeg.org and make sure it is on "
            "PATH, or set 'ffmpeg_path' in Settings."
        )
    return exe


def run(cmd: List[str], timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, creationflags=_NO_WINDOW,
    )


def probe_size(video_path: str) -> Tuple[int, int]:
    """(width, height), or (0, 0) when it cannot be read."""
    ffprobe = find_ffprobe()
    if not ffprobe:
        return (0, 0)
    try:
        r = run([ffprobe, "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height",
                 "-of", "csv=s=x:p=0", video_path], timeout=30)
        w, h = r.stdout.strip().split("x")[:2]
        return (int(w), int(h))
    except Exception:
        return (0, 0)


def media_duration(path: str) -> float:
    """Duration in seconds, 0.0 when unknown."""
    ffprobe = find_ffprobe()
    if not ffprobe:
        return 0.0
    try:
        r = run([ffprobe, "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", path], timeout=30)
        return float((r.stdout or "0").strip() or 0)
    except Exception:
        return 0.0
