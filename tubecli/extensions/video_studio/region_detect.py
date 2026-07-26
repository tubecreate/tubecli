"""
Detect and cover burned-in (hardcoded) subtitles.

Ported from ReupDouyin's core/subtitles/region_detect.py and adapted to
tubecli: vision calls go through the cloud_api key manager instead of a
local settings file, and the 9router proxy is used when it is running.

Two halves:
  detect_subtitle_region()  — sample frames, ask a vision model where the
                              burned-in caption sits, aggregate into one box
  cover_region()            — remove/obscure that box with ffmpeg

Cover modes, from least to most visible:
  delogo — INTERPOLATES the box from its surrounding edges. On flat backgrounds
           (anime, plain colour) the text vanishes with no smear or ghosting.
           This is the "nội suy" mode and the best default.
  blur   — Gaussian blur; better on busy/live-action backgrounds.
  pixel  — mosaic; guarantees the text is unreadable.
  fill   — darken the box outright.

Every mode except delogo is feathered by default: the patch is composited
through a blurred mask so the edge melts into the frame instead of leaving a
hard rectangle.
"""
import base64
import json
import logging
import os
import re
import uuid
from statistics import median
from typing import Dict, List, Optional

from tubecli.extensions.video_studio.ffmpeg_utils import (
    find_ffprobe, media_duration, probe_size, require_ffmpeg, run,
)

logger = logging.getLogger("VideoStudio")

DETECT_PROMPT = (
    "You are a video subtitle-region detector. The attached image is ONE frame from "
    "a short video.\n\n"
    "TASK: Find ONLY hardcoded/burned-in SUBTITLE text — the caption text overlaid on "
    "the video (usually a line or two near the bottom). This is the spoken-dialogue "
    "caption a viewer reads.\n\n"
    "IGNORE: channel logos, watermarks, usernames, hashtags, on-screen UI, big title "
    "graphics, timestamps, and any text that is part of the filmed scene.\n\n"
    "For each subtitle text block, give a TIGHT bounding box that fully encloses the "
    "text (all lines together).\n\n"
    "OUTPUT: a JSON array only, no other text. Coordinates are NORMALIZED floats in "
    "[0,1] relative to image width/height, box = [x1,y1,x2,y2] = "
    "[left, top, right, bottom].\n"
    'Example: [{"text": "字幕内容", "box": [0.12, 0.86, 0.88, 0.95]}]\n'
    "If there is NO burned-in subtitle in this frame, return exactly: []"
)

COVER_MODES = ("delogo", "blur", "pixel", "fill")


# ── Frame sampling ───────────────────────────────────────────────────

def _temp_dir() -> str:
    from tubecli.config import EXTENSIONS_DATA_DIR

    d = os.path.join(str(EXTENSIONS_DATA_DIR), "video_studio", "temp",
                     f"region_{uuid.uuid4().hex[:8]}")
    os.makedirs(d, exist_ok=True)
    return d


def sample_frames(video_path: str, n: int = 6, width: int = 720) -> List[Dict]:
    """n frames spread evenly over the middle 90% of the video."""
    ffmpeg = require_ffmpeg()
    dur = media_duration(video_path) or 1.0
    tmp = _temp_dir()

    lo, hi = dur * 0.05, dur * 0.95
    n = max(1, n)
    step = (hi - lo) / n if n > 1 else 0
    frames = []
    for i in range(n):
        t = lo + step * (i + 0.5)
        out = os.path.join(tmp, f"f{i:02d}.jpg")
        try:
            r = run([ffmpeg, "-y", "-ss", f"{max(t, 0):.3f}", "-i", video_path,
                     "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "3", out],
                    timeout=30)
            if r.returncode == 0 and os.path.exists(out):
                frames.append({"t": round(t, 2), "path": out})
        except Exception as e:
            logger.warning(f"[VideoStudio] frame {i} failed: {e}")
    return frames


# ── Box maths ────────────────────────────────────────────────────────

def _norm_box(box) -> Optional[List[float]]:
    """Normalise to [x1,y1,x2,y2] in 0..1. Tolerates the 0..1000 scale Gemini
    sometimes returns."""
    try:
        vals = [float(v) for v in box[:4]]
    except Exception:
        return None
    if len(vals) < 4:
        return None
    if any(v > 1.5 for v in vals):
        vals = [v / 1000.0 for v in vals]
    x1, y1, x2, y2 = vals
    x1, x2 = sorted((x1, x2))
    y1, y2 = sorted((y1, y2))
    x1, y1 = max(0.0, x1), max(0.0, y1)
    x2, y2 = min(1.0, x2), min(1.0, y2)
    if x2 - x1 < 0.02 or y2 - y1 < 0.01:
        return None
    return [round(x1, 4), round(y1, 4), round(x2, 4), round(y2, 4)]


def _parse_detection(text: str) -> List[Dict]:
    m = re.search(r"\[.*\]", text or "", re.DOTALL)
    if not m:
        return []
    try:
        arr = json.loads(m.group())
    except Exception:
        return []
    out = []
    for it in arr if isinstance(arr, list) else []:
        if not isinstance(it, dict):
            continue
        box = _norm_box(it.get("box") or it.get("bbox") or [])
        if box:
            out.append({"text": str(it.get("text", "")).strip(), "box": box})
    return out


def aggregate_boxes(all_boxes: List[List[float]], pad_x: float = 0.03,
                    pad_y: float = 0.015) -> Optional[List[float]]:
    """Merge per-frame boxes into one cover region.

    Horizontally UNION — lines differ in length, the box must cover the longest.
    Vertically MEDIAN — the caption band sits still, so one noisy frame must not
    stretch it. Then pad to swallow outlines and drop shadows.
    """
    if not all_boxes:
        return None
    x1 = min(b[0] for b in all_boxes)
    x2 = max(b[2] for b in all_boxes)
    y1 = median(b[1] for b in all_boxes)
    y2 = median(b[3] for b in all_boxes)
    return [round(max(0.0, x1 - pad_x), 4), round(max(0.0, y1 - pad_y), 4),
            round(min(1.0, x2 + pad_x), 4), round(min(1.0, y2 + pad_y), 4)]


def to_pixels(box: List[float], w: int, h: int) -> Dict[str, int]:
    """0..1 box → even pixel rect (ffmpeg filters want even numbers)."""
    x = int(box[0] * w) & ~1
    y = int(box[1] * h) & ~1
    bw = (int((box[2] - box[0]) * w) + 1) & ~1
    bh = (int((box[3] - box[1]) * h) + 1) & ~1
    return {"x": x, "y": y, "w": max(2, min(bw, w - x)), "h": max(2, min(bh, h - y))}


# ── Vision backends ──────────────────────────────────────────────────

def _vision_source() -> Dict:
    """Pick a vision backend. 9router first (local, no key), then Gemini."""
    try:
        import requests

        r = requests.get("http://localhost:20128/v1/models", timeout=1.5)
        if r.status_code == 200:
            ids = [m.get("id") for m in r.json().get("data", []) if m.get("id")]
            preferred = next(
                (i for i in ids if "gemini" in i.lower() or "flash" in i.lower()),
                ids[0] if ids else None,
            )
            if preferred:
                key = ""
                try:
                    from tubecli.extensions.cloud_api.extension import key_manager

                    key = key_manager.get_active_key("9router") or ""
                except Exception:
                    pass
                return {"kind": "openai", "base_url": "http://localhost:20128/v1",
                        "model": preferred, "api_key": key or "9router"}
    except Exception:
        pass

    try:
        from tubecli.extensions.cloud_api.extension import key_manager

        gkey = key_manager.get_active_key("gemini")
        if gkey:
            return {"kind": "gemini", "api_key": gkey, "model": "gemini-2.5-flash"}
        for pid, base in (("openai", None),
                          ("openrouter", "https://openrouter.ai/api/v1")):
            k = key_manager.get_active_key(pid)
            if k:
                from tubecli.extensions.cloud_api.extension import PROVIDERS

                models = PROVIDERS.get(pid, {}).get("models") or []
                if models:
                    return {"kind": "openai", "api_key": k, "model": models[0],
                            "base_url": base}
    except Exception as e:
        logger.warning(f"[VideoStudio] could not resolve a vision backend: {e}")
    return {}


def _detect_openai(img_b64: str, cfg: Dict) -> List[Dict]:
    import requests

    url = f"{cfg.get('base_url') or 'https://api.openai.com/v1'}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if cfg.get("api_key"):
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    payload = {
        "model": cfg["model"], "temperature": 0.0, "max_tokens": 2048,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": DETECT_PROMPT},
            {"type": "image_url",
             "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
        ]}],
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=120)
    if resp.status_code != 200:
        raise RuntimeError(f"vision HTTP {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    content = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
    return _parse_detection(content)


def _detect_gemini(img_b64: str, cfg: Dict) -> List[Dict]:
    import requests

    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{cfg['model']}:generateContent?key={cfg['api_key']}")
    payload = {"contents": [{"parts": [
        {"text": DETECT_PROMPT},
        {"inline_data": {"mime_type": "image/jpeg", "data": img_b64}},
    ]}], "generationConfig": {"temperature": 0.0}}
    resp = requests.post(url, json=payload, timeout=120)
    if resp.status_code != 200:
        raise RuntimeError(f"Gemini HTTP {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    parts = (data.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
    return _parse_detection("".join(p.get("text", "") for p in parts))


# ── Public API ───────────────────────────────────────────────────────

def detect_subtitle_region(video_path: str, sample: int = 6, on_progress=None) -> Dict:
    """Find the burned-in caption band.

    Returns {found, box, box_px, frames_with_text, total_frames, samples, size}.
    found=False simply means the video has no hardcoded subtitles.
    """
    if not os.path.isfile(video_path):
        raise RuntimeError(f"File not found: {video_path}")

    cfg = _vision_source()
    if not cfg:
        raise RuntimeError(
            "Detecting the subtitle region needs a vision model. Add a Gemini "
            "(or OpenAI/OpenRouter) key in Cloud API Keys, or start 9router."
        )

    w, h = probe_size(video_path)
    frames = sample_frames(video_path, n=sample)
    total = len(frames)
    if total == 0:
        raise RuntimeError("Could not extract any frame to analyse.")

    samples, sub_boxes = [], []
    for done, fr in enumerate(frames, start=1):
        try:
            with open(fr["path"], "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode()
            dets = (_detect_gemini(img_b64, cfg) if cfg["kind"] == "gemini"
                    else _detect_openai(img_b64, cfg))
        except Exception as e:
            logger.warning(f"[VideoStudio] detect t={fr['t']} failed: {e}")
            dets = []
        # The real caption is the largest box in the frame.
        best = max(dets, key=lambda d: (d["box"][2] - d["box"][0]) *
                   (d["box"][3] - d["box"][1]), default=None)
        if best:
            sub_boxes.append(best["box"])
            samples.append({"t": fr["t"], "text": best["text"], "box": best["box"]})
        else:
            samples.append({"t": fr["t"], "text": "", "box": None})
        if on_progress:
            try:
                on_progress(done, total)
            except Exception:
                pass

    for fr in frames:
        try:
            os.remove(fr["path"])
        except Exception:
            pass
    try:
        os.rmdir(os.path.dirname(frames[0]["path"]))
    except Exception:
        pass

    box = aggregate_boxes(sub_boxes)
    # Require the caption on at least a third of sampled frames — one stray
    # detection is not a subtitle track.
    found = box is not None and len(sub_boxes) >= max(1, total // 3)
    return {
        "found": bool(found),
        "box": box,
        "box_px": to_pixels(box, w, h) if (box and w and h) else None,
        "frames_with_text": len(sub_boxes),
        "total_frames": total,
        "samples": samples,
        "size": [w, h],
    }


def cover_region(video_path: str, box: List[float], output_path: str,
                 mode: str = "delogo", strength: int = 24,
                 feather: bool = True) -> str:
    """Cover `box` (0..1) so the original subtitle is gone. Audio is copied."""
    if mode not in COVER_MODES:
        raise ValueError(f"Unknown mode {mode!r}; expected one of {COVER_MODES}")
    ffmpeg = require_ffmpeg()
    w, h = probe_size(video_path)
    if not w or not h:
        raise RuntimeError("Could not read the video dimensions.")
    px = to_pixels(box, w, h)
    x, y, bw, bh = px["x"], px["y"], px["w"], px["h"]
    os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)

    if mode == "delogo":
        # Interpolate the box from its surrounding edges — no smear, no ghost.
        # delogo needs the box strictly inside the frame, >=1px on every side.
        dx = max(1, min(x, w - 3))
        dy = max(1, min(y, h - 3))
        dw = max(1, min(bw, w - dx - 1))
        dh = max(1, min(bh, h - dy - 1))
        cmd = [ffmpeg, "-y", "-i", video_path,
               "-vf", f"delogo=x={dx}:y={dy}:w={dw}:h={dh}",
               "-c:a", "copy", "-c:v", "libx264", "-preset", "veryfast",
               "-crf", "20", output_path]
        r = run(cmd, timeout=1800)
        if r.returncode != 0 or not os.path.exists(output_path):
            raise RuntimeError(f"ffmpeg delogo failed: {(r.stderr or '')[-400:]}")
        return output_path

    def _effect(cw: int, ch: int) -> str:
        if mode == "blur":
            return f"gblur=sigma={max(6, strength)}"
        if mode == "fill":
            return f"gblur=sigma=26,drawbox=0:0:{cw}:{ch}:color=black@0.72:t=fill"
        div = max(2, strength // 2)
        return (f"scale={max(2, cw // div)}:{max(2, ch // div)}:flags=neighbor,"
                f"scale={cw}:{ch}:flags=neighbor")

    if not feather:
        fc = (f"[0:v]crop={bw}:{bh}:{x}:{y},{_effect(bw, bh)}[fg];"
              f"[0:v][fg]overlay={x}:{y}[v]")
    else:
        # Crop wider than the box so the edge has room to fade, then composite
        # through a blurred white mask sized to the box itself.
        F = max(12, min(int(round(bh * 0.5)), 64)) & ~1
        cx = max(0, x - F) & ~1
        cy = max(0, y - F) & ~1
        cw = max(2, min(w - cx, bw + 2 * F) & ~1)
        ch = max(2, min(h - cy, bh + 2 * F) & ~1)
        ox, oy = x - cx, y - cy
        sigma = max(4, F // 2)
        fc = (
            f"[0:v]crop={cw}:{ch}:{cx}:{cy},split[reg][regm];"
            f"[reg]{_effect(cw, ch)}[fg0];"
            f"[regm]drawbox=0:0:{cw}:{ch}:color=black:t=fill,"
            f"drawbox={ox}:{oy}:{bw}:{bh}:color=white:t=fill,"
            f"format=gray,gblur=sigma={sigma}[mask];"
            f"[fg0][mask]alphamerge[fg];"
            f"[0:v][fg]overlay={cx}:{cy}[v]"
        )

    cmd = [ffmpeg, "-y", "-i", video_path,
           "-filter_complex", fc, "-map", "[v]", "-map", "0:a?",
           "-c:a", "copy", "-c:v", "libx264", "-preset", "veryfast",
           "-crf", "20", output_path]
    r = run(cmd, timeout=1800)
    if r.returncode != 0 or not os.path.exists(output_path):
        raise RuntimeError(f"ffmpeg cover failed: {(r.stderr or '')[-400:]}")
    return output_path
