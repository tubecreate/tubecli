"""
Built-in Specialist Agents — Auto-created on tubecli init.
Inspired by claw-code-main's built-in agents (planAgent, exploreAgent, verificationAgent).

Each specialist has:
- role: "specialist" or "orchestrator"
- specialties: keyword domains they handle
- allowed_skills: limited skill set (prevents token bloat)
- system_prompt: tuned for their specific domain
"""
import re
from typing import List, Dict

# CJK (Trung/Nhật/Hàn) không có ranh giới từ để chốt \b — với chúng dùng
# substring; ký tự Latin/số thì chốt whole-word.
_CJK_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯]")


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

    existing_by_name = {a.name.lower(): a for a in agent_manager.get_all()}
    created = []
    created_ids = []

    # 1. Create Orchestrator first
    if force or ORCHESTRATOR_AGENT["name"].lower() not in existing_by_name:
        agent = agent_manager.create(**ORCHESTRATOR_AGENT)
        created.append(agent.name)
        created_ids.append(agent.id)
        print(f"[Specialists] ✅ Created orchestrator: {agent.name}")

    # 2. Create Specialists — hoặc RESYNC định nghĩa cho agent đã tồn tại.
    # Trước đây agent trùng tên bị bỏ qua hoàn toàn nên specialties trong
    # data đóng băng ở phiên bản cũ (Video Agent lưu 9 từ khóa trong khi
    # code có 17 — thiếu reup/mirror/ffmpeg/cắt...). Resync = UNION để giữ
    # từ khóa người dùng tự thêm.
    for spec_def in BUILTIN_SPECIALISTS:
        existing = existing_by_name.get(spec_def["name"].lower())
        if existing and not force:
            _resync_specialist(agent_manager, existing, spec_def)
            continue
        agent = agent_manager.create(**spec_def)
        created.append(agent.name)
        created_ids.append(agent.id)
        print(f"[Specialists] ✅ Created specialist: {agent.name} (specialties: {spec_def['specialties'][:3]})")

    # 3. Link skills — CHỈ cho agent mới tạo hoặc agent chưa từng được gán
    # (allowed_skills rỗng). Trước đây hàm này ghi đè vô điều kiện mỗi
    # discovery pass, xóa sạch mọi chỉnh tay của người dùng trong UI.
    _auto_assign_skills(agent_manager, agent_ids=created_ids, include_empty=True)

    # 4. Create default team grouping all specialists
    if created:
        _create_default_team(agent_manager)

    return created


def _resync_specialist(agent_manager, existing, spec_def: Dict):
    """Đồng bộ specialties từ code vào agent đã tồn tại (union, không phá
    chỉnh sửa của người dùng). Không đụng model / allowed_skills / prompt."""
    try:
        stored = list(getattr(existing, "specialties", []) or [])
        code_specs = list(spec_def.get("specialties", []) or [])
        stored_lower = {s.lower() for s in stored}
        # Chỉ THÊM từ khóa mới từ code; giữ nguyên thứ tự cũ + phần user thêm.
        merged = stored + [s for s in code_specs if s.lower() not in stored_lower]
        if len(merged) != len(stored):
            agent_manager.update(existing.id, specialties=merged)
            added = len(merged) - len(stored)
            print(f"[Specialists] ↻ {existing.name}: +{added} specialty mới (resync)")
    except Exception as e:
        print(f"[Specialists] Resync warning cho {getattr(existing, 'name', '?')}: {e}")


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


def _auto_assign_skills(agent_manager, agent_ids=None, include_empty=False):
    """Gán skill cho specialist theo specialties.

    Chỉ chạm agent trong `agent_ids` (agent vừa tạo) và — nếu
    `include_empty` — cả agent có allowed_skills rỗng (chưa từng được gán).
    KHÔNG ghi đè agent đã có allowed_skills do người dùng chỉnh tay.
    Trước đây hàm này ghi đè vô điều kiện mỗi discovery pass nên xóa sạch
    mọi tùy chỉnh trong UI.
    """
    try:
        from tubecli.core.skill import skill_manager

        all_skills = skill_manager.get_all()
        if not all_skills:
            return

        target_ids = set(agent_ids or [])

        def _kw_in(haystack: str, kw: str) -> bool:
            """Whole-word match (CJK giữ substring) — 'live' không còn dính
            'livestream' trong mô tả, 'google' không kéo cả Calendar về Search."""
            kw = (kw or "").strip().lower()
            if not kw:
                return False
            # CJK không có ranh giới từ → substring; còn lại chốt \b thủ công
            if _CJK_RE.search(kw):
                return kw in haystack
            return re.search(r"(?<!\w)" + re.escape(kw) + r"(?!\w)", haystack) is not None

        runnable_ids = [s.id for s in all_skills if s.is_runnable]

        for agent in agent_manager.get_all():
            role = getattr(agent, "role", "general") or "general"
            current = getattr(agent, "allowed_skills", []) or []

            if role == "orchestrator":
                # Orchestrator điều phối → LUÔN thấy mọi skill CHẠY ĐƯỢC, refresh
                # mỗi lần (không đặt sau cổng touchable — nếu không, skill thêm
                # sau lần gán đầu sẽ không bao giờ tới được orchestrator). Bỏ
                # skill hỏng để không chọn nhầm skill fail ngay.
                if set(current) != set(runnable_ids):
                    agent_manager.update(agent.id, allowed_skills=runnable_ids)
                continue

            # Với specialist: chỉ chạm agent vừa tạo hoặc (include_empty và rỗng),
            # KHÔNG ghi đè tùy chỉnh tay của người dùng.
            touchable = (agent.id in target_ids) or (include_empty and not current)
            if not touchable:
                continue

            specialties = getattr(agent, "specialties", []) or []
            if role != "specialist" or not specialties:
                continue

            matched_skill_ids = []
            for skill in all_skills:
                if not skill.is_runnable:
                    continue
                haystack = (
                    f"{(skill.name or '').lower()} "
                    f"{(skill.description or '').lower()} "
                    f"{' '.join(skill.commands or []).lower()}"
                )
                if any(_kw_in(haystack, spec) for spec in specialties):
                    matched_skill_ids.append(skill.id)

            if matched_skill_ids:
                agent_manager.update(agent.id, allowed_skills=matched_skill_ids)
                print(f"[Specialists] 🔗 {agent.name}: gán {len(matched_skill_ids)} skill")
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
