"""
Capability registry — what a video job needs, and what is actually installed.

The video pipeline is assembled from EXTERNAL extensions that live under
data/extensions_external/ (gitignored). A fresh install therefore has the Video
Agent but none of the machinery, and the agent could only answer "I can't do
that" without saying why or what to do about it.

This module answers three questions for any job:
  * which extensions does it need?
  * which of those are installed and enabled right now?
  * if something is missing, what exactly should the user install?

The answer is rendered as a short, actionable message pointing at the Market,
so both the chat agent and the Telegram bot can hand it straight to the user.
"""
import logging
from typing import Dict, List, Optional

logger = logging.getLogger("VideoStudio")

MARKET_URL = "/market"

# Extension id → how to describe it to a human.
EXTENSIONS: Dict[str, Dict[str, str]] = {
    "video_downloader": {
        "label": "Video Downloader",
        "does": "downloads video from Douyin / TikTok / YouTube without watermark",
    },
    "subtitle_extractor": {
        "label": "Subtitle Extractor",
        "does": "extracts subtitles (Gemini or Whisper), translates them, exports SRT/VTT/ASS and burns them in",
    },
    "tts_vibevoice": {
        "label": "TTS VibeVoice",
        "does": "text-to-speech and dubbing, including timing a voice track to an SRT",
    },
    "video_editor": {
        "label": "Video Editor",
        "does": "cuts, effects and re-encoding",
    },
    "video_studio": {
        "label": "Video Studio",
        "does": "detects and removes burned-in subtitles, analyses channels, runs the reup pipeline",
    },
}

# Job id → what it needs and which endpoint does the work.
JOBS: Dict[str, Dict] = {
    "download": {
        "label": "Download a video",
        "requires": ["video_downloader"],
        "endpoint": "POST /api/v1/ytdl/download_async",
    },
    "channel_analysis": {
        "label": "Analyse a channel and suggest content ideas",
        "requires": ["video_studio"],
        "optional": ["video_downloader"],
        "endpoint": "POST /api/v1/video-studio/channel/analyze",
    },
    "extract_subtitle": {
        "label": "Extract subtitles from a video",
        "requires": ["subtitle_extractor"],
        "endpoint": "POST /api/v1/subtitle/extract",
    },
    "translate_subtitle": {
        "label": "Translate subtitles",
        "requires": ["subtitle_extractor"],
        "endpoint": "POST /api/v1/subtitle/translate",
    },
    "remove_hardsub": {
        "label": "Detect and cover the original burned-in subtitles",
        "requires": ["video_studio"],
        "endpoint": "POST /api/v1/video-studio/hardsub/remove",
    },
    "tts": {
        "label": "Dub the video with text-to-speech",
        "requires": ["tts_vibevoice"],
        "endpoint": "POST /api/v1/tts/synthesize-srt",
    },
    "burn_subtitle": {
        "label": "Burn subtitles into the video",
        "requires": ["subtitle_extractor"],
        "endpoint": "POST /api/v1/subtitle/burn",
    },
    "reup_pipeline": {
        "label": "Full reup pipeline (download → subtitles → translate → cover original subs → dub → burn)",
        "requires": ["video_studio", "video_downloader", "subtitle_extractor", "tts_vibevoice"],
        "endpoint": "POST /api/v1/video-studio/pipeline/reup",
    },
}


def installed_extensions() -> Dict[str, bool]:
    """{extension_id: enabled} for everything the manager knows about."""
    try:
        from tubecli.core.extension_manager import extension_manager

        return {e.name: bool(e.enabled) for e in extension_manager.get_all()}
    except Exception as e:
        logger.warning(f"[VideoStudio] could not list extensions: {e}")
        return {}


def check_job(job_id: str) -> Dict:
    """Can this job run? Returns {job, label, ready, missing, disabled, ...}."""
    job = JOBS.get(job_id)
    if not job:
        return {"job": job_id, "ready": False, "error": f"Unknown job: {job_id}"}

    state = installed_extensions()
    missing, disabled, present = [], [], []
    for ext in job["requires"]:
        if ext not in state:
            missing.append(ext)
        elif not state[ext]:
            disabled.append(ext)
        else:
            present.append(ext)

    return {
        "job": job_id,
        "label": job["label"],
        "endpoint": job.get("endpoint", ""),
        "requires": job["requires"],
        "optional": job.get("optional", []),
        "present": present,
        "missing": missing,
        "disabled": disabled,
        "ready": not missing and not disabled,
    }


def check_all() -> Dict:
    results = {jid: check_job(jid) for jid in JOBS}
    return {
        "jobs": results,
        "ready": [j for j, r in results.items() if r["ready"]],
        "blocked": [j for j, r in results.items() if not r["ready"]],
        "extensions": installed_extensions(),
    }


def _describe(ext_id: str) -> str:
    meta = EXTENSIONS.get(ext_id, {})
    label = meta.get("label", ext_id)
    does = meta.get("does", "")
    return f"**{label}** (`{ext_id}`)" + (f" — {does}" if does else "")


def guidance_for(job_ids: List[str]) -> Optional[str]:
    """Markdown telling the user exactly what to install, or None if all set.

    This is what the agent shows instead of a bare "I can't do that".
    """
    if isinstance(job_ids, str):
        job_ids = [job_ids]

    missing, disabled, wanted = [], [], []
    for jid in job_ids:
        r = check_job(jid)
        if r.get("error"):
            continue
        wanted.append(r["label"])
        for e in r["missing"]:
            if e not in missing:
                missing.append(e)
        for e in r["disabled"]:
            if e not in disabled:
                disabled.append(e)

    if not missing and not disabled:
        return None

    lines = ["⚠️ **Missing tools for this job.**", ""]
    if wanted:
        lines.append("You asked for: " + "; ".join(wanted))
        lines.append("")
    if missing:
        lines.append(f"Install these from the Market ({MARKET_URL}):")
        lines += [f"  {i}. {_describe(e)}" for i, e in enumerate(missing, 1)]
        lines.append("")
    if disabled:
        lines.append("These are installed but switched off — enable them in Extensions:")
        lines += [f"  - {_describe(e)}" for e in disabled]
        lines.append("")
    lines.append(
        "After installing or enabling, **restart the server** — extension routes are "
        "bound once at startup."
    )
    return "\n".join(lines)


def capability_report() -> str:
    """Human-readable "what can I do right now" summary."""
    data = check_all()
    lines = ["## Video capabilities", ""]
    for jid, r in data["jobs"].items():
        mark = "✅" if r["ready"] else "❌"
        line = f"{mark} **{r['label']}**"
        if not r["ready"]:
            gaps = r["missing"] + r["disabled"]
            line += f" — needs: {', '.join(EXTENSIONS.get(g, {}).get('label', g) for g in gaps)}"
        lines.append(line)
    if data["blocked"]:
        lines += ["", f"Install what is missing from the Market ({MARKET_URL}), then restart the server."]
    return "\n".join(lines)
