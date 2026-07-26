"""
The Video Agent's skill set.

Every skill is an `extension_action`: a thin, runnable wrapper over an endpoint
that already exists. That matters because AgentBrain.build_system_prompt hides
any skill whose `is_runnable` is False — several of the Video Agent's old skills
were empty shells, so the agent could not see them and kept answering "I can't
do that". Each definition below carries a real endpoint, so it is runnable by
construction.

`requires` names the capability job (see capabilities.py). When the backing
extension is not installed the skill is still registered — but the agent is told
what to install instead of failing silently.
"""
import logging
from typing import Dict, List

logger = logging.getLogger("VideoStudio")

SKILLS: List[Dict] = [
    {
        "name": "🎬 Video Capabilities",
        "requires": None,
        "description": (
            "Check which video tools are installed and what the Video Agent can do "
            "right now. Use this FIRST whenever a video request cannot be fulfilled, "
            "so the user is told exactly which extension to install from the Market."
        ),
        "commands": ["video capabilities", "kiểm tra công cụ video", "video tools"],
        "input_hint": "no input needed",
        "when_to_use": "Before saying a video job is impossible, or when the user asks what you can do with video.",
        "endpoint": "/api/v1/video-studio/capabilities",
        "method": "GET",
        "input_key": "q",
    },
    {
        "name": "📥 Download Video",
        "requires": "download",
        "description": (
            "Download a video from Douyin, TikTok, YouTube and other platforms, "
            "without watermark where possible. Accepts full or shortened links. "
            "Runs in the BACKGROUND as a Codex task with a live progress bar — it "
            "returns a task number immediately, it does not block the chat."
        ),
        # Deliberately distinct from the legacy '🌍 Universal Video Downloader'
        # skill, which owns "download video"/"download youtube".
        # _match_skill_command returns the FIRST skill whose command matches, so
        # sharing a phrase would silently hand the job back to the old workflow —
        # the one that calls the synchronous endpoint and dies at 30s.
        "commands": ["tải video này", "tai video nay", "download this video",
                     "video downloader", "tải link"],
        "input_hint": "the video URL",
        "when_to_use": "The user gives a link to ONE video and wants the file.",
        "endpoint": "/api/v1/video-studio/download",
        "input_key": "url",
    },
    {
        "name": "📊 Analyze Channel",
        "requires": "channel_analysis",
        "description": (
            "Read a channel's videos and report what it is about — topics, audience, "
            "tone, the title formula behind its best performers — then propose 5-8 new "
            "video ideas with hooks. Works on YouTube, TikTok and Douyin channel links."
        ),
        "commands": ["phân tích kênh", "analyze channel", "channel ideas", "ý tưởng kênh"],
        "input_hint": "the channel URL (e.g. https://www.youtube.com/@name)",
        "when_to_use": "The user asks what a channel is about, how it performs, or what to post next.",
        "endpoint": "/api/v1/video-studio/channel/analyze",
        "input_key": "url",
    },
    {
        "name": "📝 Extract Subtitles",
        "requires": "extract_subtitle",
        "description": (
            "Transcribe a video into timed subtitle lines using Gemini (cloud) or "
            "Whisper (offline), and export SRT/VTT/ASS."
        ),
        # 'extract subtitle' and 'transcribe' belong to the legacy (broken)
        # "Subtitle Extractor" skill. _match_skill_command does not check
        # is_runnable, so sharing a phrase would route the job to a skill that
        # cannot execute.
        "commands": ["tách sub", "tách phụ đề", "lấy phụ đề", "sub từ video",
                     "get subtitles"],
        "input_hint": "path to a downloaded video file",
        "when_to_use": "The user wants the spoken content of a video as text or an SRT.",
        "endpoint": "/api/v1/subtitle/extract",
        "input_key": "video_path",
    },
    {
        "name": "🌐 Translate Subtitles",
        "requires": "translate_subtitle",
        "description": "Translate an existing subtitle track into another language, keeping the timings.",
        "commands": ["dịch phụ đề", "dịch sub", "translate subtitle"],
        "input_hint": "subtitle lines or an SRT path, plus the target language",
        "when_to_use": "The user has subtitles and wants them in another language.",
        "endpoint": "/api/v1/subtitle/translate",
        "input_key": "text",
    },
    {
        "name": "🧽 Remove Burned-in Subtitles",
        "requires": "remove_hardsub",
        "description": (
            "Find the original hardcoded subtitle band with a vision model and erase it. "
            "Default mode 'delogo' INTERPOLATES the area from its surroundings, so on flat "
            "backgrounds the text disappears with no blur box. Other modes: blur, pixel, fill."
        ),
        "commands": ["xoá sub gốc", "che sub gốc", "remove hardsub", "xóa phụ đề gốc"],
        "input_hint": "path to the video file",
        "when_to_use": "Before adding new subtitles to a reup, so the old ones do not show through.",
        "endpoint": "/api/v1/video-studio/hardsub/remove",
        "input_key": "video_path",
    },
    {
        "name": "🔊 Dub with TTS",
        "requires": "tts",
        "description": (
            "Generate a voice track from subtitles and mux it into the video, "
            "stretching each line to match its timing. Replaces or mixes with the original audio."
        ),
        "commands": ["lồng tiếng", "dub video", "text to speech video"],
        "input_hint": "video path plus the subtitle lines to speak",
        "when_to_use": "The user wants the video spoken in another voice or language.",
        "endpoint": "/api/v1/tts/synthesize-srt",
        "input_key": "video_path",
    },
    {
        "name": "🔥 Burn Subtitles",
        "requires": "burn_subtitle",
        "description": "Render subtitles permanently into the video frames with a chosen style.",
        "commands": ["ghi sub", "burn subtitle", "ghép phụ đề"],
        "input_hint": "video path plus the subtitle lines",
        "when_to_use": "The user wants subtitles baked into the picture rather than a separate file.",
        "endpoint": "/api/v1/subtitle/burn",
        "input_key": "video_path",
    },
    {
        "name": "🚀 Reup Pipeline",
        "requires": "reup_pipeline",
        "description": (
            "Run the whole reup chain for one link: download → extract subtitles → "
            "translate → cover the original burned-in subtitles → dub → burn the new "
            "subtitles. Queued as a Codex task, so it waits for your approval, shows a "
            "step timeline, survives a restart and can be cancelled or retried."
        ),
        "commands": ["reup", "reup video", "chạy pipeline reup"],
        "input_hint": "the source video URL",
        "when_to_use": "The user wants a finished localized video from a source link in one go.",
        "endpoint": "/api/v1/video-studio/pipeline/reup",
        "input_key": "url",
    },
]

VIDEO_AGENT_NAME = "Video Agent"


def register_skills() -> Dict[str, int]:
    """Create or refresh every skill, then attach them to the Video Agent.

    Idempotent: matches by name, updates in place. Also drops skills from the
    Video Agent that are not runnable, since the prompt builder hides those and
    they only make the agent look more capable than it is.
    """
    stats = {"created": 0, "updated": 0, "attached": 0, "pruned": 0}
    try:
        from tubecli.core.skill import skill_manager
    except Exception as e:
        logger.warning(f"[VideoStudio] skill manager unavailable: {e}")
        return stats

    skill_ids = []
    for spec in SKILLS:
        payload = {
            "description": spec["description"],
            "skill_type": "Extension Skill",
            "skill_format": "extension_action",
            "commands": spec["commands"],
            "input_hint": spec["input_hint"],
            "when_to_use": spec["when_to_use"],
            "workflow_data": {
                "extension": "video_studio",
                "endpoint": spec["endpoint"],
                "method": spec.get("method", "POST"),
                "input_key": spec["input_key"],
                "requires_job": spec.get("requires"),
            },
        }
        try:
            existing = skill_manager.find_by_name(spec["name"])
            if existing:
                skill_manager.update(existing.id, **payload)
                skill_ids.append(existing.id)
                stats["updated"] += 1
            else:
                created = skill_manager.create(name=spec["name"], **payload)
                skill_ids.append(created.id)
                stats["created"] += 1
        except Exception as e:
            logger.warning(f"[VideoStudio] could not register {spec['name']!r}: {e}")

    try:
        from tubecli.core.agent import agent_manager

        agent = agent_manager.find_by_name(VIDEO_AGENT_NAME)
        if not agent:
            return stats

        current = list(agent.allowed_skills or [])
        # Drop skills the prompt builder would hide anyway — an agent listing
        # skills it cannot run is worse than one with a short, honest list.
        kept = []
        for sid in current:
            s = skill_manager.get(sid)
            if s is None:
                stats["pruned"] += 1
                continue
            if not s.is_runnable:
                logger.info(f"[VideoStudio] dropping non-runnable skill {s.name!r} from {VIDEO_AGENT_NAME}")
                stats["pruned"] += 1
                continue
            kept.append(sid)

        merged = kept + [sid for sid in skill_ids if sid not in kept]
        if merged != current:
            agent_manager.update(agent.id, allowed_skills=merged)
            stats["attached"] = len(skill_ids)
    except Exception as e:
        logger.warning(f"[VideoStudio] could not attach skills to the agent: {e}")

    return stats
