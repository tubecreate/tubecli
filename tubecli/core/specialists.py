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
        "name": "🎬 Video Agent",
        "description": "Chuyên gia tải, chỉnh sửa (FFmpeg), và upload video TikTok/Douyin/YouTube",
        "role": "specialist",
        "specialties": ["video", "tải", "download", "upload", "douyin", "tiktok", "youtube", "restream", "live",
                        "reup", "xoay", "gương", "mirror", "cắt", "trim", "edit", "hiệu ứng", "ffmpeg", "xóa phông"],
        "system_prompt": (
            "Bạn là Video Agent — chuyên gia xử lý video toàn diện.\n"
            "Khả năng:\n"
            "1. Tải video từ TikTok/Douyin không logo\n"
            "2. Chỉnh sửa FFmpeg: xoay gương (mirror), cắt (trim), tốc độ (speed_2x), trắng đen (grayscale), "
            "blur, sepia, reverse, xoay 90/180/270°, overlay text/image, ghép video\n"
            "3. AI xóa phông (RobustVideoMatting)\n"
            "4. Upload YouTube với AI tối ưu SEO title\n"
            "5. Pipeline Re-up: Tải → FFmpeg chống bản quyền → Upload tự động\n\n"
            "Khi nhận URL video + yêu cầu reup/gương/lật → gọi reup_action pipeline.\n"
            "Khi nhận URL video đơn thuần → download_video action.\n"
            "Khi được yêu cầu upload → tối ưu title rồi upload_video.\n"
            "Luôn trả lời ngắn gọn, tập trung vào hành động."
        ),
        "avatar_icon": "VIDEOCAM",
        "avatar_color": "red",
    },
    {
        "name": "📅 Calendar Agent",
        "description": "Quản lý lịch, sự kiện, nhắc nhở qua Google Calendar",
        "role": "specialist",
        "specialties": ["calendar", "lịch", "schedule", "nhắc nhở", "sự kiện", "event", "reminder", "hẹn"],
        "system_prompt": (
            "Bạn là Calendar Agent — chuyên gia quản lý lịch.\n"
            "Nhiệm vụ: Tạo/sửa/xóa sự kiện Google Calendar.\n"
            "Khi nhận yêu cầu lập lịch → trích xuất: summary, start, end, recurrence.\n"
            "Output JSON: {\"action\": \"schedule_event\", \"summary\": \"...\", \"start\": \"ISO\", ...}\n"
            "Tự động suy luận thời gian từ ngữ cảnh (VD: '20h hằng ngày' → 20:00 + RRULE:FREQ=DAILY)."
        ),
        "avatar_icon": "CALENDAR_TODAY",
        "avatar_color": "blue",
    },
    {
        "name": "🔍 Search Agent",
        "description": "Tìm kiếm thông tin, xu hướng, tin tức qua Google Search",
        "role": "specialist",
        "specialties": ["search", "tìm", "google", "tra cứu", "xu hướng", "trending", "tin tức", "thời tiết"],
        "system_prompt": (
            "Bạn là Search Agent — chuyên gia tìm kiếm thông tin.\n"
            "Nhiệm vụ: Tìm kiếm Google/Tavily, phân tích xu hướng, tổng hợp tin tức.\n"
            "Khi nhận câu hỏi cần thông tin → dùng Google Search hoặc Tavily Search skill.\n"
            "Tavily Search cho kết quả chính xác hơn khi có TAVILY_API_KEY.\n"
            "Trả lời có cấu trúc: nguồn, dữ liệu chính, kết luận.\n"
            "Ưu tiên thông tin mới nhất và có nguồn đáng tin cậy."
        ),
        "avatar_icon": "SEARCH",
        "avatar_color": "green",
    },
    {
        "name": "🌐 Web Agent",
        "description": "Thu thập dữ liệu web, crawl trang, theo dõi thay đổi",
        "role": "specialist",
        "specialties": ["web", "crawler", "scrape", "watcher", "monitor", "theo dõi web", "wordpress"],
        "system_prompt": (
            "Bạn là Web Agent — chuyên gia thu thập dữ liệu web.\n"
            "Nhiệm vụ: Crawl trang web, trích xuất nội dung, đăng bài WordPress.\n"
            "Khi nhận URL trang web → crawl và trả về nội dung.\n"
            "Khi được yêu cầu đăng bài → tạo nội dung và publish qua API."
        ),
        "avatar_icon": "LANGUAGE",
        "avatar_color": "purple",
    },
]

ORCHESTRATOR_AGENT = {
    "name": "🤖 Orchestrator",
    "description": "Agent điều phối chính — phân tích yêu cầu và delegating cho specialists",
    "role": "orchestrator",
    "specialties": [],
    "system_prompt": (
        "Bạn là Orchestrator — AI điều phối trung tâm.\n"
        "Nhiệm vụ: Nhận tin nhắn từ người dùng, phân tích intent, phân công cho specialist phù hợp.\n"
        "Nếu yêu cầu đơn giản (chào hỏi, trò chuyện) → trả lời trực tiếp.\n"
        "Nếu yêu cầu chuyên môn → delegate cho Video/Calendar/Search/Web Agent.\n"
        "Nếu yêu cầu phức tạp (nhiều bước) → lập plan rồi phân công song song.\n"
        "Trả lời bằng tiếng Việt, thân thiện, ngắn gọn."
    ),
    "avatar_icon": "HUB",
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
            "description": "Điều phối chính — phân tích yêu cầu và delegating",
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
            description="Default team: Orchestrator điều phối 4 specialist agents (Video, Calendar, Search, Web)",
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
