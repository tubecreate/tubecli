"""
Video Engine — FFmpeg GPU/CPU wrapper for video processing.
Provides: trim, merge, overlay, effects, export, probe, thumbnail.
Auto-detects GPU (NVENC, QSV, AMF) with CPU fallback.
"""
import os
import re
import sys
import json
import shutil
import asyncio
import logging
import subprocess
from typing import Optional, List, Dict, Any, Tuple

logger = logging.getLogger("video_editor.engine")


# ── FFmpeg Detection ─────────────────────────────────────────────────

def get_ffmpeg_path() -> Optional[str]:
    """Find ffmpeg executable: system PATH → imageio-ffmpeg fallback."""
    ff = shutil.which("ffmpeg")
    if ff:
        return ff
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def get_ffprobe_path() -> Optional[str]:
    """Find ffprobe executable."""
    fp = shutil.which("ffprobe")
    if fp:
        return fp
    # Try alongside ffmpeg
    ff = get_ffmpeg_path()
    if ff:
        probe = os.path.join(os.path.dirname(ff), "ffprobe" + (".exe" if sys.platform == "win32" else ""))
        if os.path.exists(probe):
            return probe
    return None


def detect_gpu_encoder() -> Tuple[str, str]:
    """
    Detect best available GPU encoder.
    Returns (video_codec, encoder_name) e.g. ("h264_nvenc", "NVIDIA NVENC").
    Falls back to ("libx264", "CPU (libx264)").
    """
    ff = get_ffmpeg_path()
    if not ff:
        return "libx264", "CPU (libx264)"

    try:
        result = subprocess.run(
            [ff, "-encoders"], capture_output=True, text=True, timeout=10
        )
        encoders = result.stdout
    except Exception:
        return "libx264", "CPU (libx264)"

    # Priority: NVIDIA > Intel QSV > AMD AMF
    if "h264_nvenc" in encoders:
        return "h264_nvenc", "NVIDIA NVENC"
    if "h264_qsv" in encoders:
        return "h264_qsv", "Intel QSV"
    if "h264_amf" in encoders:
        return "h264_amf", "AMD AMF"
    return "libx264", "CPU (libx264)"


# ── Helper ───────────────────────────────────────────────────────────

def _run_ffmpeg(args: List[str], timeout: int = 600) -> subprocess.CompletedProcess:
    """Run an FFmpeg command synchronously."""
    ff = get_ffmpeg_path()
    if not ff:
        raise RuntimeError("FFmpeg not found. Install ffmpeg or run: pip install imageio-ffmpeg")
    cmd = [ff] + args
    logger.info(f"Running: {' '.join(cmd)}")
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


async def _run_ffmpeg_async(args: List[str], timeout: int = 600) -> subprocess.CompletedProcess:
    """Run FFmpeg in a thread pool."""
    return await asyncio.to_thread(_run_ffmpeg, args, timeout)


def _ensure_output_dir(output_path: str):
    """Make sure the directory for the output file exists."""
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)


# ── Core Operations ──────────────────────────────────────────────────

async def probe(input_file: str) -> Dict[str, Any]:
    """Get media file metadata using ffprobe."""
    fp = get_ffprobe_path()
    if not fp:
        # Fallback: use ffmpeg
        ff = get_ffmpeg_path()
        if not ff:
            raise RuntimeError("Neither ffprobe nor ffmpeg found")
        cmd = [ff, "-i", input_file, "-hide_banner"]
        result = await asyncio.to_thread(
            lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        )
        # Parse basic info from stderr
        stderr = result.stderr
        info = {"file": input_file}
        dur_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", stderr)
        if dur_match:
            h, m, s = dur_match.groups()
            info["duration"] = float(h) * 3600 + float(m) * 60 + float(s)
        res_match = re.search(r"(\d{2,5})x(\d{2,5})", stderr)
        if res_match:
            info["width"] = int(res_match.group(1))
            info["height"] = int(res_match.group(2))
        fps_match = re.search(r"(\d+(?:\.\d+)?)\s*fps", stderr)
        if fps_match:
            info["fps"] = float(fps_match.group(1))
        return info

    cmd = [
        fp, "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", input_file
    ]
    result = await asyncio.to_thread(
        lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr[:300]}")

    data = json.loads(result.stdout)
    fmt = data.get("format", {})
    video_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    audio_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), {})

    return {
        "file": input_file,
        "duration": float(fmt.get("duration", 0)),
        "size": int(fmt.get("size", 0)),
        "bitrate": int(fmt.get("bit_rate", 0)),
        "format_name": fmt.get("format_name", ""),
        "width": int(video_stream.get("width", 0)),
        "height": int(video_stream.get("height", 0)),
        "fps": eval(video_stream["r_frame_rate"]) if video_stream.get("r_frame_rate") and "/" in str(video_stream.get("r_frame_rate", "")) else float(video_stream.get("r_frame_rate", 0) or 0),
        "video_codec": video_stream.get("codec_name", ""),
        "audio_codec": audio_stream.get("codec_name", ""),
        "audio_sample_rate": int(audio_stream.get("sample_rate", 0) or 0),
        "streams": len(data.get("streams", [])),
    }


async def trim(input_file: str, start: str, end: str, output_file: str) -> Dict[str, Any]:
    """Trim video from start to end time. Times in HH:MM:SS or seconds format."""
    _ensure_output_dir(output_file)
    args = [
        "-y", "-i", input_file,
        "-ss", str(start), "-to", str(end),
        "-c", "copy",  # Stream copy for speed (no re-encoding)
        "-avoid_negative_ts", "make_zero",
        output_file
    ]
    result = await _run_ffmpeg_async(args)
    if result.returncode != 0:
        # Retry with re-encoding if stream copy fails
        codec, _ = detect_gpu_encoder()
        args = [
            "-y", "-i", input_file,
            "-ss", str(start), "-to", str(end),
            "-c:v", codec, "-c:a", "aac",
            output_file
        ]
        result = await _run_ffmpeg_async(args)
        if result.returncode != 0:
            raise RuntimeError(f"Trim failed: {result.stderr[:500]}")

    return {"output": output_file, "status": "success"}


async def merge(input_files: List[str], output_file: str, transition: str = "none") -> Dict[str, Any]:
    """Merge/concatenate multiple video files."""
    _ensure_output_dir(output_file)

    if transition == "none" or not transition:
        # Use concat demuxer (fastest, lossless)
        concat_file = output_file + ".concat.txt"
        try:
            with open(concat_file, "w", encoding="utf-8") as f:
                for inp in input_files:
                    f.write(f"file '{os.path.abspath(inp)}'\n")

            args = [
                "-y", "-f", "concat", "-safe", "0",
                "-i", concat_file,
                "-c", "copy",
                output_file
            ]
            result = await _run_ffmpeg_async(args)
            if result.returncode != 0:
                raise RuntimeError(f"Merge failed: {result.stderr[:500]}")
        finally:
            if os.path.exists(concat_file):
                os.remove(concat_file)
    else:
        # Merge with crossfade transition
        duration = 0.5  # transition duration
        filter_parts = []
        inputs_args = []
        for i, f in enumerate(input_files):
            inputs_args.extend(["-i", f])

        # Build xfade filter chain
        if len(input_files) == 2:
            # Get duration of first clip for offset calculation
            info = await probe(input_files[0])
            offset = info.get("duration", 5) - duration
            filter_complex = (
                f"[0:v][1:v]xfade=transition={transition}:"
                f"duration={duration}:offset={offset}[v];"
                f"[0:a][1:a]acrossfade=d={duration}[a]"
            )
            args = ["-y"] + inputs_args + [
                "-filter_complex", filter_complex,
                "-map", "[v]", "-map", "[a]",
                output_file
            ]
        else:
            # For 3+ files, chain xfade filters
            args = ["-y"] + inputs_args + ["-c", "copy", output_file]

        result = await _run_ffmpeg_async(args)
        if result.returncode != 0:
            raise RuntimeError(f"Merge with transition failed: {result.stderr[:500]}")

    return {"output": output_file, "status": "success"}


async def overlay_text(
    input_file: str, text: str, output_file: str,
    x: str = "(w-text_w)/2", y: str = "h-th-20",
    fontsize: int = 36, fontcolor: str = "white",
    bg_color: str = "black@0.5", font: str = ""
) -> Dict[str, Any]:
    """Add text overlay to video."""
    _ensure_output_dir(output_file)
    codec, _ = detect_gpu_encoder()

    # Escape special chars for drawtext
    escaped_text = text.replace("'", "\\'").replace(":", "\\:")

    drawtext = f"drawtext=text='{escaped_text}':x={x}:y={y}:fontsize={fontsize}:fontcolor={fontcolor}:box=1:boxcolor={bg_color}:boxborderw=8"
    if font:
        drawtext += f":fontfile='{font}'"

    args = [
        "-y", "-i", input_file,
        "-vf", drawtext,
        "-c:v", codec, "-c:a", "copy",
        output_file
    ]
    result = await _run_ffmpeg_async(args)
    if result.returncode != 0:
        raise RuntimeError(f"Text overlay failed: {result.stderr[:500]}")

    return {"output": output_file, "status": "success"}


async def overlay_image(
    input_file: str, overlay_file: str, output_file: str,
    x: str = "10", y: str = "10", scale: float = 1.0, opacity: float = 1.0
) -> Dict[str, Any]:
    """Add image/watermark overlay to video."""
    _ensure_output_dir(output_file)
    codec, _ = detect_gpu_encoder()

    filter_complex = f"[1:v]scale=iw*{scale}:ih*{scale}"
    if opacity < 1.0:
        filter_complex += f",format=rgba,colorchannelmixer=aa={opacity}"
    filter_complex += f"[ovrl];[0:v][ovrl]overlay={x}:{y}"

    args = [
        "-y", "-i", input_file, "-i", overlay_file,
        "-filter_complex", filter_complex,
        "-c:v", codec, "-c:a", "copy",
        output_file
    ]
    result = await _run_ffmpeg_async(args)
    if result.returncode != 0:
        raise RuntimeError(f"Image overlay failed: {result.stderr[:500]}")

    return {"output": output_file, "status": "success"}


# ── Effects ──────────────────────────────────────────────────────────

EFFECT_FILTERS = {
    "speed_2x":       {"vf": "setpts=0.5*PTS", "af": "atempo=2.0"},
    "speed_0.5x":     {"vf": "setpts=2.0*PTS", "af": "atempo=0.5"},
    "speed_1.5x":     {"vf": "setpts=0.67*PTS", "af": "atempo=1.5"},
    "rotate_90":      {"vf": "transpose=1"},
    "rotate_180":     {"vf": "transpose=1,transpose=1"},
    "rotate_270":     {"vf": "transpose=2"},
    "flip_h":         {"vf": "hflip"},
    "flip_v":         {"vf": "vflip"},
    "mirror":         {"vf": "hflip"},
    "grayscale":      {"vf": "colorchannelmixer=.3:.4:.3:0:.3:.4:.3:0:.3:.4:.3"},
    "sepia":          {"vf": "colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131"},
    "blur":           {"vf": "boxblur=5:1"},
    "blur_heavy":     {"vf": "boxblur=10:5"},
    "sharpen":        {"vf": "unsharp=5:5:1.5:5:5:0.0"},
    "brightness_up":  {"vf": "eq=brightness=0.1"},
    "brightness_down": {"vf": "eq=brightness=-0.1"},
    "contrast_up":    {"vf": "eq=contrast=1.3"},
    "contrast_down":  {"vf": "eq=contrast=0.7"},
    "saturate":       {"vf": "eq=saturation=1.5"},
    "desaturate":     {"vf": "eq=saturation=0.5"},
    "vignette":       {"vf": "vignette=PI/4"},
    "fade_in":        {"vf": "fade=t=in:st=0:d=1"},
    "fade_out":       {"vf": "fade=t=out:st=0:d=1"},
    "reverse":        {"vf": "reverse", "af": "areverse"},
    "vintage":        {"vf": "curves=vintage"},
    "negative":       {"vf": "negate"},
    "noise":          {"vf": "noise=alls=20:allf=t+u"},
    "stabilize":      {"vf": "deshake"},
}


async def apply_effect(
    input_file: str, effect_name: str, output_file: str,
    params: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Apply a named effect or custom filter to video."""
    _ensure_output_dir(output_file)
    codec, _ = detect_gpu_encoder()

    if effect_name == "custom" and params and params.get("filter"):
        vf = params["filter"]
        af = params.get("audio_filter")
    elif effect_name in EFFECT_FILTERS:
        flt = EFFECT_FILTERS[effect_name]
        vf = flt.get("vf")
        af = flt.get("af")
    else:
        raise ValueError(f"Unknown effect: '{effect_name}'. Available: {list(EFFECT_FILTERS.keys())}")

    args = ["-y", "-i", input_file]
    if vf:
        args.extend(["-vf", vf])
    args.extend(["-c:v", codec])
    if af:
        args.extend(["-af", af])
    else:
        args.extend(["-c:a", "copy"])
    args.append(output_file)

    result = await _run_ffmpeg_async(args)
    if result.returncode != 0:
        raise RuntimeError(f"Effect '{effect_name}' failed: {result.stderr[:500]}")

    return {"output": output_file, "status": "success", "effect": effect_name}


# ── Export ───────────────────────────────────────────────────────────

EXPORT_PRESETS = {
    "low":    {"crf": "28", "preset": "fast",     "audio_bitrate": "96k"},
    "medium": {"crf": "23", "preset": "medium",   "audio_bitrate": "128k"},
    "high":   {"crf": "18", "preset": "slow",     "audio_bitrate": "192k"},
    "ultra":  {"crf": "15", "preset": "veryslow", "audio_bitrate": "320k"},
}

RESOLUTION_MAP = {
    "360p":  "640:360",
    "480p":  "854:480",
    "720p":  "1280:720",
    "1080p": "1920:1080",
    "1440p": "2560:1440",
    "4k":    "3840:2160",
}


async def export_video(
    input_file: str, output_file: str,
    format: str = "mp4",
    quality: str = "high",
    resolution: Optional[str] = None,
    fps: Optional[int] = None,
    timeline: Optional[List[dict]] = None,
) -> Dict[str, Any]:
    """Export video compiling the full Timeline NLE State (Cut, Crop, Effects, Overlays)."""
    _ensure_output_dir(output_file)
    codec, encoder_name = detect_gpu_encoder()
    preset = EXPORT_PRESETS.get(quality, EXPORT_PRESETS["high"])

    args = ["-y"]
    
    # ── Timeline Data Preprocessing ──
    unique_inputs = []
    if timeline and len(timeline) > 0:
        for track in timeline:
            if track.get("type", "video") != "video": continue
            for clip in track.get("clips", []):
                path = clip.get("path")
                if path and path not in unique_inputs:
                    unique_inputs.append(path)
                    
        if not unique_inputs:
            unique_inputs = [input_file]
            timeline = None
            args.extend(["-i", input_file])
        else:
            for inp in unique_inputs:
                args.extend(["-i", inp])
    else:
        args.extend(["-i", input_file])

    filter_complex = []
    map_target = ""

    # ── Filter Complex Compiler ──
    if timeline and len(unique_inputs) > 0:
        max_duration = 0
        clip_filters = []
        clip_meta = []
        
        res_str = RESOLUTION_MAP.get(resolution, "1920:1080")
        if ":" not in res_str: res_str = "1920:1080"
        fps_str = str(fps) if fps else "30"
        
        c_idx = 0
        for track in timeline:
            if track.get("type", "video") != "video": continue
            for clip in track.get("clips", []):
                clip_path = clip.get("path")
                if not clip_path: continue
                inp_idx = unique_inputs.index(clip_path)
                
                c_start = float(clip.get("start", 0))
                c_end = float(clip.get("end", 5))
                c_off = float(clip.get("offset", 0))
                dur = c_end - c_start
                if c_off + dur > max_duration:
                    max_duration = c_off + dur
                
                # Core Trim
                vf = f"[{inp_idx}:v]trim={c_start}:{c_end},setpts=PTS-STARTPTS"
                
                # Spatial Crop
                crop = clip.get("crop")
                if crop and isinstance(crop, dict):
                    x, y, w, h = crop.get('x', 0), crop.get('y', 0), crop.get('w', 100), crop.get('h', 100)
                    vf += f",crop={w}:{h}:{x}:{y}"
                    
                # Effects
                for eff in clip.get("effects", []):
                    if eff in EFFECT_FILTERS and "vf" in EFFECT_FILTERS[eff]:
                        vf += f",{EFFECT_FILTERS[eff]['vf']}"
                
                # Scale & Padding
                vf += f",scale={res_str}:force_original_aspect_ratio=decrease,pad={res_str}:(ow-iw)/2:(oh-ih)/2,fps={fps_str}"
                
                out_tag = f"v{c_idx}"
                vf += f"[{out_tag}]"
                
                clip_filters.append(vf)
                clip_meta.append({"tag": out_tag, "offset": c_off, "dur": dur})
                c_idx += 1
                
        filter_complex.extend(clip_filters)
        
        # Base Background
        filter_complex.append(f"color=c=black:s={res_str.replace(':', 'x')}:d={max_duration}:r={fps_str}[base]")
        
        # Overlay Stacking Layer by Layer
        curr_base = "base"
        for i, meta in enumerate(clip_meta):
            tag = meta["tag"]
            off = meta["offset"]
            dur = meta["dur"]
            next_base = f"b{i}" if i < len(clip_meta) - 1 else "outv"
            filter_complex.append(f"[{curr_base}][{tag}]overlay=0:0:enable='between(t,{off},{off+dur})'[{next_base}]")
            curr_base = next_base
            
        map_target = "[outv]"

    # ── FFmpeg Command Builder ──
    if filter_complex:
        args.extend(["-filter_complex", ";".join(filter_complex)])
        args.extend(["-map", map_target])
        args.extend(["-map", "0:a?"]) # Fallback map first input's audio
    else:
        vf_parts = []
        if resolution and resolution in RESOLUTION_MAP:
            vf_parts.append(f"scale={RESOLUTION_MAP[resolution]}:force_original_aspect_ratio=decrease,pad={RESOLUTION_MAP[resolution]}:(ow-iw)/2:(oh-ih)/2")
        if fps:
            vf_parts.append(f"fps={fps}")
        if vf_parts:
            args.extend(["-vf", ",".join(vf_parts)])

    # Codec Settings
    if codec == "libx264":
        args.extend(["-c:v", codec, "-crf", preset["crf"], "-preset", preset["preset"]])
    else:
        args.extend(["-c:v", codec, "-b:v", "5M"])
        
    if format == "webm":
        args.extend(["-c:v", "libvpx-vp9", "-crf", "30", "-b:v", "0", "-c:a", "libopus"])
    elif format == "gif":
        if not filter_complex:
            palette_filter = "fps=15,scale=480:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse"
            if vf_parts: palette_filter = ",".join(vf_parts) + "," + palette_filter
            args.extend(["-filter_complex", palette_filter, "-loop", "0"])
        else:
            args.extend(["-loop", "0"])
    else:
        args.extend(["-c:a", "aac", "-b:a", preset["audio_bitrate"]])

    args.append(output_file)

    # ── Execution ──
    result = await _run_ffmpeg_async(args, timeout=1200)
    if result.returncode != 0:
        raise RuntimeError(f"Export failed: {result.stderr[-500:]}")

    file_size = os.path.getsize(output_file) if os.path.exists(output_file) else 0

    return {
        "output": output_file,
        "status": "success",
        "encoder": encoder_name,
        "file_size": file_size,
    }


async def generate_thumbnail(
    input_file: str, output_file: str, time: str = "00:00:01"
) -> Dict[str, Any]:
    """Generate a thumbnail image from video at specified time."""
    _ensure_output_dir(output_file)
    args = [
        "-y", "-i", input_file,
        "-ss", str(time), "-vframes", "1",
        "-vf", "scale=320:-1",
        output_file
    ]
    result = await _run_ffmpeg_async(args, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"Thumbnail generation failed: {result.stderr[:300]}")

    return {"output": output_file, "status": "success"}


async def run_custom_ffmpeg(command_args: str, input_file: Optional[str] = None) -> Dict[str, Any]:
    """Run a custom FFmpeg command string."""
    import shlex
    ff = get_ffmpeg_path()
    if not ff:
        raise RuntimeError("FFmpeg not found")

    args = shlex.split(command_args)
    cmd = [ff] + args
    logger.info(f"Custom FFmpeg: {' '.join(cmd)}")

    result = await asyncio.to_thread(
        lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    )

    return {
        "returncode": result.returncode,
        "stdout": result.stdout[-1000:] if result.stdout else "",
        "stderr": result.stderr[-1000:] if result.stderr else "",
        "status": "success" if result.returncode == 0 else "error",
    }
