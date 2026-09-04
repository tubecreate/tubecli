"""
The Content Video skill — one chip in the agent's Skills tab.

Why a skill and not only a chat verb: the verb is invisible. It fires when the
model decides to emit it, so nobody can look at an agent and see that it can
turn what it read into a video, and nobody can take that ability away. A skill
is a row in the store: it shows up as a chip in the agent editor, the owner
ticks it on or off per agent, and its `commands` are phrases the owner can edit.

It is an `extension_action` skill, so the brain POSTs one string to a real
endpoint (AgentBrain.autonomous_run). That path used to carry no identity,
which is exactly why this pipeline could not be a skill: reading an agent's
corpus and spending its keys on behalf of "whoever" is not a thing. The
`with_agent` flag added alongside this file makes the brain send agent_id, so
the route serves the agent that actually asked.
"""
import logging
from typing import Dict, List

logger = logging.getLogger("ContentVideo")

SKILL_NAME = "🎬 Content Video"

SKILLS: List[Dict] = [
    {
        "name": SKILL_NAME,
        "description": (
            "Turn what this agent has READ and WATCHED into a narrated video. It gathers the "
            "agent's own browsing corpus for the day, pulls transcripts for videos it watched, "
            "crawls any extra links given, writes a script with this agent's model, and puts "
            "that script on the Codex board FOR REVIEW. Nothing is rendered until a human "
            "accepts the script; accepting queues the render (shot images, voice, ffmpeg) and "
            "the finished mp4 lands on the same board. Runs in the BACKGROUND as a Codex task: "
            "it returns a task number immediately and never blocks the chat."
        ),
        # Phrases the owner can edit in the Skills tab. Deliberately distinct from
        # the video_studio skills, whose commands own "tải video"/"sub từ video":
        # _match_skill_command takes the FIRST runnable skill whose command is a
        # prefix, so a shared phrase would silently hand the job to the downloader.
        "commands": [
            "làm video từ những gì đã đọc", "lam video tu nhung gi da doc",
            "làm video hôm nay", "lam video hom nay",
            "tổng hợp thành video", "tong hop thanh video",
            "content video", "video from what i read", "make today's video",
        ],
        "input_hint": "nothing, or extra links to include",
        "when_to_use": (
            "The user asks for a video built from what the agent has been reading or watching "
            "(a daily round-up, a digest, 'make a video about today'). NOT for downloading or "
            "re-uploading someone else's video — those are the Video Studio skills."
        ),
        "endpoint": "/api/v1/content-video/run",
        "method": "POST",
        "input_key": "input",
        "with_agent": True,
    },
]


def register_skills() -> Dict[str, int]:
    """Create or refresh the skill. Idempotent: matched by name, updated in place.

    Deliberately does NOT attach itself to any agent. Which agent may spend its
    corpus and its keys on a video is the owner's call, made with the chip in
    the Skills tab — video_studio auto-attaches to one fixed "Video Agent", and
    that is the reason people find skills on agents they never chose.
    """
    stats = {"created": 0, "updated": 0}
    try:
        from tubecli.core.skill import skill_manager
    except Exception as e:
        logger.warning(f"[ContentVideo] skill manager unavailable: {e}")
        return stats

    for spec in SKILLS:
        payload = {
            "description": spec["description"],
            "skill_type": "Extension Skill",
            "skill_format": "extension_action",
            "commands": spec["commands"],
            "input_hint": spec["input_hint"],
            "when_to_use": spec["when_to_use"],
            "workflow_data": {
                "extension": "content_video",
                "endpoint": spec["endpoint"],
                "method": spec.get("method", "POST"),
                "input_key": spec["input_key"],
                "with_agent": bool(spec.get("with_agent")),
            },
        }
        try:
            existing = skill_manager.find_by_name(spec["name"])
            if existing:
                skill_manager.update(existing.id, **payload)
                stats["updated"] += 1
            else:
                skill_manager.create(name=spec["name"], **payload)
                stats["created"] += 1
        except Exception as e:
            logger.warning(f"[ContentVideo] could not register {spec['name']!r}: {e}")
    return stats
