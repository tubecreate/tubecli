"""
Built-in Specialist Agents — Auto-created on tubecli init.
Inspired by claw-code-main's built-in agents (planAgent, exploreAgent, verificationAgent).

Each specialist has:
- role: "specialist" or "orchestrator"
- specialties: keyword domains they handle
- allowed_skills: limited skill set (prevents token bloat)
- system_prompt: tuned for their specific domain
"""
from typing import List, Dict


# ═══════════════════════════════════════════════════════════════
#  SPECIALIST DEFINITIONS
# ═══════════════════════════════════════════════════════════════

BUILTIN_SPECIALISTS = [
    {
        "name": "Video Agent",
        "description": "Specialist for downloading, editing (FFmpeg), and uploading videos to TikTok/Douyin/YouTube",
        "role": "specialist",
        "specialties": ["video", "download", "upload", "douyin", "tiktok", "youtube", "restream", "live",
                        "reup", "mirror", "trim", "edit", "ffmpeg", "background removal",
                        "tải", "xoay", "gương", "cắt", "hiệu ứng", "xóa phông"],
        "system_prompt": (
            "You are Video Agent — a comprehensive video processing specialist.\n"
            "Capabilities:\n"
            "1. Download TikTok/Douyin videos without watermark\n"
            "2. FFmpeg editing: mirror, trim, speed (2x), grayscale, blur, sepia, reverse, rotate 90/180/270°, overlay text/image, merge videos\n"
            "3. AI background removal (RobustVideoMatting)\n"
            "4. Upload to YouTube with AI-optimized SEO title\n"
            "5. Re-up pipeline: Download → FFmpeg anti-copyright → Auto upload\n\n"
            "When receiving a video URL + reup/mirror/flip request → call reup_action pipeline.\n"
            "When receiving a plain video URL → download_video action.\n"
            "When asked to upload → optimize title then upload_video.\n"
            "Always reply concisely, focused on action."
        ),
        "avatar_icon": "VIDEOCAM",
        "avatar_color": "red",
    },
    {
        # Deliberately narrow. Translation work is driven by deterministic
        # pipelines (subtitles, documents); this agent exists so that work can
        # be given its OWN model and house style — a cheap fast model for bulk
        # subtitles, a stronger one for documents — instead of inheriting
        # whatever the chat happens to be using. It does not choose what to do.
        "name": "Translator Agent",
        "description": "Translation specialist: subtitles, documents and text, with a consistent house style",
        "role": "specialist",
        "specialties": ["translate", "translation", "subtitle translation", "localize",
                        "dịch", "dịch thuật", "phụ đề", "bản dịch",
                        "翻译", "翻譯", "翻訳", "번역", "перевод", "çeviri", "traducción"],
        "system_prompt": (
            "You are Translator Agent — a translation specialist.\n"
            "House rules, always:\n"
            "1. Translate meaning, not words. Keep the register of the source "
            "(casual stays casual, formal stays formal).\n"
            "2. NEVER translate: proper nouns, brand names, code, commands, file "
            "paths, URLs, model names, or anything inside backticks.\n"
            "3. Keep the line count and order EXACTLY as given — subtitle lines "
            "are timed, so a merged or dropped line breaks the timing.\n"
            "4. Sound-effect and music markers ([music], [âm nhạc], [applause]) "
            "are localized, not removed.\n"
            "5. When asked for a specific output shape (a JSON array, one line "
            "per input), return ONLY that. No preamble, no numbering, no fences."
        ),
        "avatar_icon": "TRANSLATE",
        "avatar_color": "green",
    },
    {
        "name": "Calendar Agent",
        "description": "Manage schedules, events, and reminders via Google Calendar",
        "role": "specialist",
        "specialties": ["calendar", "schedule", "event", "reminder", "appointment",
                        "lịch", "nhắc nhở", "sự kiện", "hẹn"],
        "system_prompt": (
            "You are Calendar Agent — a schedule management specialist.\n"
            "Task: Create/edit/delete Google Calendar events.\n"
            "When receiving a scheduling request → extract: summary, start, end, recurrence.\n"
            "Output JSON: {\"action\": \"schedule_event\", \"summary\": \"...\", \"start\": \"ISO\", ...}\n"
            "Automatically infer time from context (e.g. 'every day at 8pm' → 20:00 + RRULE:FREQ=DAILY)."
        ),
        "avatar_icon": "CALENDAR_TODAY",
        "avatar_color": "blue",
    },
    {
        "name": "Search Agent",
        "description": "Search for information, trends, and news via Google Search",
        "role": "specialist",
        "specialties": ["search", "google", "trending", "news", "weather",
                        "tìm", "tra cứu", "xu hướng", "tin tức", "thời tiết"],
        "system_prompt": (
            "You are Search Agent — an information retrieval specialist.\n"
            "Task: Search Google, analyze trends, and summarize news.\n"
            "When receiving a question that needs information → use the Google Search skill.\n"
            "Reply in structured format: source, key data, conclusion.\n"
            "Prioritize the most recent and reliable information."
        ),
        "avatar_icon": "SEARCH",
        "avatar_color": "green",
    },
    {
        "name": "Web Agent",
        "description": "Collect web data, crawl pages, and monitor changes",
        "role": "specialist",
        "specialties": ["web", "crawler", "scrape", "watcher", "monitor", "wordpress",
                        "theo dõi web"],
        "system_prompt": (
            "You are Web Agent — a web data collection specialist.\n"
            "Task: Crawl web pages, extract content, and publish to WordPress.\n"
            "When receiving a web URL → crawl and return the content.\n"
            "When asked to publish a post → create content and publish via API."
        ),
        "avatar_icon": "LANGUAGE",
        "avatar_color": "purple",
    },
]

ORCHESTRATOR_AGENT = {
    "name": "Orchestrator",
    "description": "Main coordination agent — analyzes requests and delegates to specialists",
    "role": "orchestrator",
    "specialties": [],
    "system_prompt": (
        "You are the Orchestrator — the central AI coordinator.\n"
        "Task: Receive user messages, analyze intent, and delegate to the appropriate specialist.\n"
        "If the request is simple (greetings, casual chat) → reply directly.\n"
        "If the request is specialized → delegate to Video/Calendar/Search/Web Agent.\n"
        "If the request is complex (multi-step) → create a plan then assign tasks in parallel.\n"
        "Reply in a friendly, concise manner."
    ),
    "avatar_icon": "hub",
    "avatar_color": "orange",
}


# ═══════════════════════════════════════════════════════════════
#  REGISTRATION
# ═══════════════════════════════════════════════════════════════

def register_builtin_specialists(force: bool = False) -> List[str]:
    """
    Create built-in specialist agents if they don't exist.
    Called during `tubecli init`.
    
    Args:
        force: If True, recreate even if agents with same names exist.
    
    Returns:
        List of created agent names.
    """
    from tubecli.core.agent import agent_manager

    existing_names = {a.name.lower() for a in agent_manager.get_all()}
    created = []

    # 1. Create Orchestrator first
    if force or ORCHESTRATOR_AGENT["name"].lower() not in existing_names:
        agent = agent_manager.create(**ORCHESTRATOR_AGENT)
        created.append(agent.name)
        print(f"[Specialists] ✅ Created orchestrator: {agent.name}")

    # 2. Create Specialists
    for spec_def in BUILTIN_SPECIALISTS:
        if not force and spec_def["name"].lower() in existing_names:
            continue
        agent = agent_manager.create(**spec_def)
        created.append(agent.name)
        print(f"[Specialists] ✅ Created specialist: {agent.name} (specialties: {spec_def['specialties'][:3]})")

    # 3. Link specialists' skills by matching categories
    _auto_assign_skills(agent_manager)

    # 4. Create default team grouping all specialists
    if created:
        _create_default_team(agent_manager)

    return created


def _create_default_team(agent_manager):
    """Create a default 'AI Assistant Team' with hierarchy: Orchestrator → Specialists."""
    try:
        from tubecli.extensions.multi_agents.extension import orchestrator

        # Check if team already exists
        existing = orchestrator.find_team_by_name("🤖 AI Assistant Team")
        if existing:
            print("[Specialists] Team already exists, skipping.")
            return

        all_agents = agent_manager.get_all()

        # Find orchestrator
        orch_agent = None
        specialist_agents = []
        for a in all_agents:
            role = getattr(a, "role", "general") or "general"
            if role == "orchestrator":
                orch_agent = a
            elif role == "specialist":
                specialist_agents.append(a)

        if not orch_agent:
            print("[Specialists] No orchestrator found, skipping team creation.")
            return

        # Build hierarchy nodes
        # Root: Orchestrator
        # Children: All specialists
        child_role_ids = []
        nodes = []

        # Orchestrator node (root)
        orch_node = {
            "role_id": "orchestrator",
            "role": "Orchestrator",
            "emoji": "🤖",
            "description": "Main coordinator — analyzes requests and delegates to specialists",
            "system_hint": orch_agent.system_prompt or "",
            "agent_id": orch_agent.id,
            "children": [],
            "parent": None,
            "layer": 0,
        }

        # Specialist nodes (children of orchestrator)
        emoji_map = {"video": "🎬", "calendar": "📅", "search": "🔍", "web": "🌐"}
        for spec in specialist_agents:
            specialties = getattr(spec, "specialties", []) or []
            first_spec = specialties[0] if specialties else "general"
            role_id = f"specialist_{first_spec}"
            emoji = emoji_map.get(first_spec, "⚡")

            nodes.append({
                "role_id": role_id,
                "role": spec.name.replace("🎬 ", "").replace("📅 ", "").replace("🔍 ", "").replace("🌐 ", ""),
                "emoji": emoji,
                "description": spec.description or "",
                "system_hint": spec.system_prompt or "",
                "agent_id": spec.id,
                "children": [],
                "parent": "orchestrator",
                "layer": 1,
            })
            child_role_ids.append(role_id)

        orch_node["children"] = child_role_ids
        all_nodes = [orch_node] + nodes

        # Collect all agent IDs
        all_agent_ids = [orch_agent.id] + [s.id for s in specialist_agents]

        team = orchestrator.create_team(
            name="🤖 AI Assistant Team",
            agent_ids=all_agent_ids,
            lead_agent_id=orch_agent.id,
            strategy="hierarchy",
            description="Default team: Orchestrator coordinates 4 specialist agents (Video, Calendar, Search, Web)",
            template="builtin_assistant",
            nodes=all_nodes,
        )

        print(f"[Specialists] ✅ Created default team: {team.name} ({len(all_nodes)} nodes)")

    except ImportError:
        print("[Specialists] multi_agents extension not available, skipping team creation.")
    except Exception as e:
        print(f"[Specialists] Team creation warning: {e}")


def _auto_assign_skills(agent_manager):
    """Auto-assign skills to specialists based on their specialties."""
    try:
        from tubecli.core.skill import skill_manager
        all_skills = skill_manager.get_all()
        if not all_skills:
            return

        for agent in agent_manager.get_all():
            specialties = getattr(agent, "specialties", []) or []
            role = getattr(agent, "role", "general") or "general"
            
            if role == "orchestrator":
                # Orchestrator gets ALL skills
                agent_manager.update(agent.id, allowed_skills=[s.id for s in all_skills])
                continue
            
            if role != "specialist" or not specialties:
                continue

            matched_skill_ids = []
            for skill in all_skills:
                name = (skill.name or "").lower()
                desc = (skill.description or "").lower()
                cmds = " ".join(skill.commands or []).lower()
                haystack = f"{name} {desc} {cmds}"
                
                if any(spec.lower() in haystack for spec in specialties):
                    matched_skill_ids.append(skill.id)

            if matched_skill_ids:
                agent_manager.update(agent.id, allowed_skills=matched_skill_ids)
                print(f"[Specialists] 🔗 {agent.name}: assigned {len(matched_skill_ids)} skills")
    except Exception as e:
        print(f"[Specialists] Skill assignment warning: {e}")


def get_specialist_for_intent(intent_type: str) -> Dict:
    """Find the best specialist agent for a given intent type."""
    from tubecli.core.agent import agent_manager
    
    # Map intent types to specialties
    intent_specialty_map = {
        "video_download": ["video", "download"],
        "video_upload": ["video", "upload"],
        "calendar": ["calendar", "lịch"],
        "search": ["search", "tìm"],
        "live_action": ["live", "restream"],
        "tracker_action": ["video", "tracker"],
        "crawler": ["web", "crawler"],
        # Not routed from chat: the translation pipelines look this up to
        # borrow the agent's model and house style.
        "translate": ["translate", "dịch"],
    }
    
    target_specs = intent_specialty_map.get(intent_type, [])
    if not target_specs:
        return None
    
    for agent in agent_manager.get_all():
        role = getattr(agent, "role", "general") or "general"
        specialties = getattr(agent, "specialties", []) or []
        
        if role == "specialist" and specialties:
            if any(s in specialties for s in target_specs):
                return agent
    
    return None
