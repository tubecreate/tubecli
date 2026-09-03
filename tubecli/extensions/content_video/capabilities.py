"""
Capability registry for the content-video pipeline.

Same three questions as video_studio/capabilities.py — what does a step need,
which of that is installed, what should the user install — with one addition
video_studio never had to deal with: Content Studio keeps its OWN key ring
(text provider, image provider), separate from the agent's cloud keys. So
besides "is the extension there", `studio_capabilities()` asks the Studio
itself what it can do right now, and the pipeline refuses at step 1 — before a
single LLM token is spent — instead of dying at the image step.
"""
import logging
from typing import Dict, List, Optional

from tubecli.extensions.video_studio.capabilities import (
    MARKET_URL, ffmpeg_ready, installed_extensions,
)

logger = logging.getLogger("ContentVideo")

# Extension id (manifest "name") → how to describe it to a human.
EXTENSIONS: Dict[str, Dict[str, str]] = {
    "content_studio": {
        "label": "Content Studio",
        "does": "breaks a script into shots, generates the shot images, voices them and assembles the video",
    },
    "web_crawler": {
        "label": "Web Crawler",
        "does": "fetches page text and YouTube transcripts for the sources a video is based on",
    },
    "tts_vibevoice": {
        "label": "TTS VibeVoice",
        "does": "text-to-speech (edge-tts, no key needed) used for the narration",
    },
}

NEEDS_FFMPEG = {"render"}

# Job id → what it needs and which endpoint does the work.
JOBS: Dict[str, Dict] = {
    "capabilities": {"label": "Check what this server can do", "requires": ["content_studio"],
                     "endpoint": "GET /api/v1/studio/settings/capabilities"},
    "gather": {"label": "Read the agent's corpus", "requires": [],
               "endpoint": "scraped_store.query"},
    "transcripts": {"label": "Transcripts of watched videos", "requires": ["web_crawler"],
                    "endpoint": "POST /api/v1/web_crawler/scrape"},
    "crawl": {"label": "Crawl extra sources", "requires": ["web_crawler"],
              "endpoint": "POST /api/v1/web_crawler/scrape"},
    "script": {"label": "Write the script", "requires": [],
               "endpoint": "AgentBrain._call_llm"},
    "studio": {"label": "Storyboard in Content Studio", "requires": ["content_studio"],
               "endpoint": "POST /api/v1/studio/episodes/{id}/storyboard"},
    "images": {"label": "Generate shot images", "requires": ["content_studio"],
               "endpoint": "POST /api/v1/studio/episodes/{id}/gen-images"},
    "tts": {"label": "Voice the narration", "requires": ["content_studio", "tts_vibevoice"],
            "endpoint": "POST /api/v1/studio/episodes/{id}/batch-tts"},
    "render": {"label": "Assemble the video", "requires": ["content_studio"],
               "endpoint": "POST /api/v1/studio/episodes/{id}/export-ffmpeg"},
}


def check_job(job_id: str) -> Dict:
    """Can this job run? Returns {job, label, ready, missing, disabled, missing_tools, ...}."""
    job = JOBS.get(job_id)
    if not job:
        return {"job": job_id, "ready": False, "missing": [], "disabled": [],
                "missing_tools": [], "error": f"Unknown job: {job_id}"}

    state = installed_extensions()
    missing, disabled, present = [], [], []
    for ext in job["requires"]:
        if ext not in state:
            missing.append(ext)
        elif not state[ext]:
            disabled.append(ext)
        else:
            present.append(ext)

    tools = []
    if job_id in NEEDS_FFMPEG and not ffmpeg_ready():
        tools.append("ffmpeg")

    return {
        "job": job_id,
        "label": job["label"],
        "endpoint": job.get("endpoint", ""),
        "requires": job["requires"],
        "present": present,
        "missing": missing,
        "disabled": disabled,
        "missing_tools": tools,
        "ready": not missing and not disabled and not tools,
    }


def studio_capabilities(timeout: float = 20) -> Dict[str, Dict]:
    """What Content Studio can do right now: {text, image, voice, assembly, ai_video}.

    Each entry is {ok, label, detail, fix} — the Studio's own words, so the
    pipeline can hand them to the user unchanged. Loopback HTTP on purpose:
    the Studio is an external extension loaded under a private module name,
    and importing it twice would give it a second set of task tables.
    """
    import requests
    from tubecli.config import get_api_port

    r = requests.get(f"http://127.0.0.1:{get_api_port()}/api/v1/studio/settings/capabilities",
                     timeout=timeout)
    if r.status_code >= 400:
        raise RuntimeError(f"Content Studio capabilities → HTTP {r.status_code}: {r.text[:200]}")
    return (r.json() or {}).get("capabilities") or {}


def _describe(ext_id: str) -> str:
    meta = EXTENSIONS.get(ext_id, {})
    label = meta.get("label", ext_id)
    does = meta.get("does", "")
    return f"**{label}** (`{ext_id}`)" + (f" — {does}" if does else "")


def guidance_for(job_ids: List[str]) -> Optional[str]:
    """Markdown telling the user exactly what to install, or None if all set."""
    if isinstance(job_ids, str):
        job_ids = [job_ids]

    missing, disabled, wanted, tools = [], [], [], []
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
        for e in r.get("missing_tools") or []:
            if e not in tools:
                tools.append(e)

    if not missing and not disabled and not tools:
        return None

    lines = ["⚠️ **Missing tools for this job.**", ""]
    if wanted:
        lines += ["You asked for: " + "; ".join(wanted), ""]
    if missing:
        lines.append(f"Install these from the Market ({MARKET_URL}):")
        lines += [f"  {i}. {_describe(e)}" for i, e in enumerate(missing, 1)]
        lines.append("")
    if disabled:
        lines.append("These are installed but switched off — enable them in Extensions:")
        lines += [f"  - {_describe(e)}" for e in disabled]
        lines.append("")
    if "ffmpeg" in tools:
        lines += [
            "**ffmpeg** is not installed, or this server cannot find it. Install it "
            "from https://ffmpeg.org, put its `bin` folder on PATH and restart TubeCLI "
            "— or add `\"ffmpeg_path\"` to `data/global_settings.json`.",
            "",
        ]
    lines.append("After installing or enabling, **restart the server** — extension routes are "
                 "bound once at startup.")
    return "\n".join(lines)


def capability_report(include_studio: bool = True) -> str:
    """Human-readable "what can this pipeline do right now" summary."""
    lines = ["## Content video capabilities", ""]
    blocked = False
    for jid in JOBS:
        r = check_job(jid)
        mark = "✅" if r["ready"] else "❌"
        line = f"{mark} **{r['label']}**"
        if not r["ready"]:
            blocked = True
            gaps = r["missing"] + r["disabled"] + (r.get("missing_tools") or [])
            line += f" — needs: {', '.join(EXTENSIONS.get(g, {}).get('label', g) for g in gaps)}"
        lines.append(line)
    if include_studio:
        try:
            caps = studio_capabilities()
            lines += ["", "**Content Studio says:**"]
            for key in ("text", "image", "voice", "assembly"):
                c = caps.get(key) or {}
                mark = "✅" if c.get("ok") else "❌"
                fix = f" → {c['fix']}" if (not c.get("ok") and c.get("fix")) else ""
                lines.append(f"{mark} {c.get('label', key)}: {c.get('detail', '')}{fix}")
        except Exception as e:
            lines += ["", f"⚠️ Could not ask Content Studio: {str(e)[:160]}"]
    if blocked:
        lines += ["", f"Install what is missing from the Market ({MARKET_URL}), then restart the server."]
    return "\n".join(lines)
