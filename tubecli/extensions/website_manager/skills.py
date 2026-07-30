"""
Website Manager — đăng ký skill cho agent (extension_action).

Trước đây extension này KHÔNG đăng ký skill nào → agent trong chat/Telegram không
gọi được, chỉ dùng qua UI. Ở đây định nghĩa 2 skill mỏng bọc REST endpoint và gắn
vào "Web Agent" (nhóm crawl web) — theo đúng pattern video_studio/skills.py.

Mỗi skill là `extension_action`: runner POST {input_key: message} tới endpoint,
đọc field 'report' trong response làm câu trả lời cho người dùng.
"""
import logging

logger = logging.getLogger("WebsiteManagerSkills")

WEB_AGENT_NAME = "Web Agent"

SKILLS = [
    {
        "name": "🌐 Quản lý Website",
        "description": "Xem danh sách website đang quản lý cùng trạng thái deploy "
                       "(active/deploying/failed) và URL. Dùng khi người dùng hỏi "
                       "'có những web nào', 'trạng thái website', 'danh sách web'.",
        "commands": ["quản lý web", "danh sách web", "danh sách website", "trạng thái web",
                     "trạng thái website", "list website", "list web", "xem web", "websites"],
        "input_hint": "Không cần input (hoặc từ khoá lọc theo tên).",
        "when_to_use": "Khi người dùng muốn xem/kiểm tra các website đã tạo và tình trạng của chúng.",
        "endpoint": "/api/v1/website-manager/skill/websites",
        "input_key": "q",
    },
    {
        "name": "🚀 Tạo Website",
        "description": "Tạo & deploy một website mới lên Cloudflare Workers từ một "
                       "template có sẵn (dùng Cloudflare credentials đã lưu, mật khẩu "
                       "admin sinh tự động). Yêu cầu nêu TÊN site + TEMPLATE. Dùng khi "
                       "người dùng nói 'tạo web', 'dựng website', 'deploy web'.",
        "commands": ["tạo website", "tạo web", "dựng web", "dựng website", "deploy web",
                     "deploy website", "create website", "tạo trang web"],
        "input_hint": "Nêu tên site + template. VD: 'tạo web coffee-shop template coffee-machine'.",
        "when_to_use": "Khi người dùng muốn tạo/deploy một website mới từ template lên Cloudflare.",
        "endpoint": "/api/v1/website-manager/skill/deploy",
        "input_key": "request",
    },
]


def register_skills() -> dict:
    """Tạo/refresh 2 skill rồi gắn vào Web Agent (union, không phá tùy chỉnh tay)."""
    stats = {"created": 0, "updated": 0, "attached": 0}
    try:
        from tubecli.core.skill import skill_manager
    except Exception as e:
        logger.warning(f"[WebsiteManager] skill manager unavailable: {e}")
        return stats

    skill_ids = []
    for spec in SKILLS:
        payload = {
            "description": spec["description"],
            "skill_type": "Extension Skill",
            "skill_format": "extension_action",
            "commands": spec["commands"],
            "input_hint": spec.get("input_hint", ""),
            "when_to_use": spec.get("when_to_use", ""),
            "workflow_data": {
                "extension": "website_manager",
                "endpoint": spec["endpoint"],
                "method": "POST",
                "input_key": spec["input_key"],
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
            logger.warning(f"[WebsiteManager] could not register {spec['name']!r}: {e}")

    # Gắn vào Web Agent — union với allowed_skills hiện có (không ghi đè crawler/wordpress
    # hay tùy chỉnh của người dùng).
    try:
        from tubecli.core.agent import agent_manager
        agent = agent_manager.find_by_name(WEB_AGENT_NAME)
        if agent:
            current = list(agent.allowed_skills or [])
            merged = current + [sid for sid in skill_ids if sid not in current]
            if set(merged) != set(current):
                agent_manager.update(agent.id, allowed_skills=merged)
                stats["attached"] = len(merged) - len(current)
                logger.info(f"[WebsiteManager] attached {stats['attached']} skill vào {WEB_AGENT_NAME}")
    except Exception as e:
        logger.warning(f"[WebsiteManager] could not attach skills to {WEB_AGENT_NAME}: {e}")

    return stats
