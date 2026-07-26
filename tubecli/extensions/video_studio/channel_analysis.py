"""
Channel analysis — read a channel's back catalogue, tell the user what it is
about and what to make next.

Ported from ReupDouyin's core/channel_ideas.py. Two differences: the video list
comes from whatever downloader extension is installed (yt-dlp via
video_downloader), and the LLM call goes through AgentBrain so it inherits key
rotation and provider failover.
"""
import json
import logging
import re
from typing import Dict, List, Optional

logger = logging.getLogger("VideoStudio")

MAX_VIDEOS_FOR_PROMPT = 40

PROMPT = """You are a YouTube/TikTok/Douyin content strategist.

Here are videos from the channel "{channel}" (title · views):
{listing}

ANALYSE this channel, then PROPOSE new video ideas.

Return ONLY one valid JSON object, no markdown and no commentary:
{{
  "topics": ["main topic 1", "main topic 2"],
  "audience": "who watches this channel",
  "tone": "the channel's voice and style",
  "title_formula": "the pattern its best-performing titles follow",
  "what_works": ["observation about the top performers"],
  "ideas": [
    {{"title": "suggested video title",
      "why": "why this fits the channel and should perform",
      "hook": "the first 3 seconds"}}
  ]
}}
Give 5 to 8 ideas. Write every value in {language}."""


def _fmt_views(n) -> str:
    try:
        n = int(n)
    except Exception:
        return "?"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def build_listing(videos: List[Dict], limit: int = MAX_VIDEOS_FOR_PROMPT) -> str:
    """Titles + views, most-viewed first, so the model sees what works."""
    rows = []
    for v in videos:
        title = (v.get("title") or v.get("desc") or "").strip().replace("\n", " ")
        if not title:
            continue
        views = v.get("view_count") or v.get("views") or v.get("play_count") or 0
        rows.append((int(views or 0), title[:120]))
    rows.sort(key=lambda r: -r[0])
    return "\n".join(f"- {t} · {_fmt_views(v)} views" for v, t in rows[:limit])


def _extract_json(text: str) -> Optional[Dict]:
    if not text:
        return None
    # Strip the auto-failover banner the brain may prepend (core/brain.py).
    text = re.sub(r"^⚠️\s*\*?\[Auto-Failover[^\]]*\]\*?\s*", "", text.strip())
    for candidate in (re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
                      + [text]):
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
        except Exception:
            continue
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group())
            return data if isinstance(data, dict) else None
        except Exception:
            return None
    return None


def fetch_channel_videos(url: str, limit: int = 40) -> Dict:
    """List a channel's videos.

    Uses yt-dlp with --flat-playlist, which returns one line of JSON per video
    without resolving each one. The downloader extension's /info endpoint is NOT
    used here: it always runs a full --dump-json for a single video, so on a
    channel URL it walks every entry and times out after 60s.
    """
    import json as _json
    import os
    import shutil
    import subprocess

    exe = shutil.which("yt-dlp")
    if not exe:
        return {"ok": False, "no_ytdlp": True,
                "message": "yt-dlp not found. Install the Video Downloader extension "
                           "from the Market (it ships yt-dlp), or `pip install yt-dlp`."}

    cmd = [exe, "--flat-playlist", "--dump-json", "--ignore-errors",
           "--playlist-end", str(max(1, min(int(limit or 40), 200))), url]
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=300, creationflags=(0x08000000 if os.name == "nt" else 0),
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": "Listing the channel timed out after 5 minutes."}
    except Exception as e:
        return {"ok": False, "message": f"yt-dlp failed: {e}"}

    videos, name = [], ""
    for line in (r.stdout or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            entry = _json.loads(line)
        except Exception:
            continue
        if entry.get("_type") == "playlist" and not entry.get("title"):
            continue
        videos.append(entry)
        name = name or entry.get("channel") or entry.get("uploader") or ""

    if not videos:
        err = (r.stderr or "").strip()[-300:]
        return {"ok": False,
                "message": "No videos found for that channel. Check the URL"
                           + (f" — yt-dlp said: {err}" if err else ".")}

    # --flat-playlist entries often omit the channel name; fall back to the
    # handle in the URL so the report is not headed by a blank.
    if not name:
        m = re.search(r"(?:@|/(?:c|channel|user)/)([^/?#]+)", url)
        if m:
            name = m.group(1)
    return {"ok": True, "videos": videos, "channel": name}


def analyze_channel(videos: List[Dict], channel_name: str = "",
                    language: str = "the same language as the channel's titles") -> Dict:
    """Turn a video list into a strategy report. Synchronous (LLM call)."""
    listing = build_listing(videos)
    if not listing:
        return {"ok": False, "message": "The video list has no usable titles."}

    from tubecli.core.agent import agent_manager
    from tubecli.core.brain import AgentBrain

    agents = agent_manager.get_all()
    if not agents:
        return {"ok": False, "message": "No agent is configured to run the analysis."}
    agent = next((a for a in agents if (a.role or "") == "orchestrator"), agents[0])

    prompt = PROMPT.format(channel=channel_name or "unknown",
                           listing=listing, language=language)
    raw = AgentBrain._call_llm(
        agent.to_dict(),
        [{"role": "system", "content": "You reply with valid JSON only."},
         {"role": "user", "content": prompt}],
        temperature=0.4,
    )
    data = _extract_json(raw)
    if not data:
        return {"ok": False, "message": "The model did not return usable JSON.",
                "raw": (raw or "")[:600]}
    return {"ok": True, "data": data, "video_count": len(videos),
            "channel": channel_name}


def ideas_to_text(data: Dict, channel_name: str = "") -> str:
    """Render the report as readable markdown for chat/Telegram."""
    if not data:
        return "No analysis available."
    out = [f"## 📊 Channel analysis{f' — {channel_name}' if channel_name else ''}", ""]
    if data.get("topics"):
        out.append("**Topics:** " + ", ".join(str(t) for t in data["topics"]))
    if data.get("audience"):
        out.append(f"**Audience:** {data['audience']}")
    if data.get("tone"):
        out.append(f"**Tone:** {data['tone']}")
    if data.get("title_formula"):
        out.append(f"**Title formula:** {data['title_formula']}")
    if data.get("what_works"):
        out += ["", "**What works:**"] + [f"- {w}" for w in data["what_works"]]
    ideas = data.get("ideas") or []
    if ideas:
        out += ["", "### 💡 Video ideas", ""]
        for i, idea in enumerate(ideas, 1):
            if not isinstance(idea, dict):
                continue
            out.append(f"**{i}. {idea.get('title', '')}**")
            if idea.get("why"):
                out.append(f"   - Why: {idea['why']}")
            if idea.get("hook"):
                out.append(f"   - Hook: {idea['hook']}")
    return "\n".join(out)
