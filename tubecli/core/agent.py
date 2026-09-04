"""
Agent Model and Manager
Manages AI agents with personas, routines, and skill assignments.
"""
import json
import datetime
from typing import Dict, List, Optional, Any
from pathlib import Path

try:
    from uuid_extensions import uuid7 as _uuid7
except ImportError:
    import uuid
    _uuid7 = uuid.uuid4

from tubecli.config import AGENTS_FILE, ensure_data_dirs


# ── Tự đăng video: ép kiểu một chỗ ───────────────────────────
#
# Nhóm publish_* là các số/chuỗi điều khiển một hành động CÔNG KHAI (đăng
# YouTube không ai duyệt), nên không được tin dữ liệu đầu vào từ BẤT
# KỲ đâu: agents.json (bản cũ / người dùng sửa tay), body của PUT
# /api/v1/agents/{id}, hay một lời gọi nội bộ agent_manager.update().
#
# Tách ra đây vì có HAI cửa vào: Agent.__init__ (tạo mới / nạp từ đĩa) và
# AgentManager.update (setattr thẳng, không đi qua __init__). Trước đây chỉ
# cửa thứ nhất ép kiểu, nên một lần PUT là đủ để cài publish_min_pages=-1 hay
# publish_privacy="banana" vào bộ nhớ: chuỗi trôi xuống tận YouTube API,
# còn số âm khiến ngưỡng "đủ bài mới" luôn đúng ⇒ video rác tự đăng.

PUBLISH_PRIVACY_CHOICES = ("public", "unlisted", "private")
# "script" = đăng qua YouTube Studio bằng script trình duyệt của người dùng
# (bật được KIẾM TIỀN, hẹn giờ, không tốn quota API); "api" = videos.insert.
PUBLISH_METHOD_CHOICES = ("script", "api")

# Mặc định khi giá trị không cứu được. Giống hệt chữ ký Agent.__init__.
PUBLISH_DEFAULTS = {
    "auto_publish": False,
    "publish_token_id": "",
    "publish_channel_id": "",
    "publish_channel_name": "",
    "publish_privacy": "public",
    "publish_method": "script",
    "publish_monetize": False,
    "publish_min_pages": 3,
    "publish_max_per_day": 2,
}


def coerce_publish_value(key: str, value: Any) -> Any:
    """Ép MỘT trường publish_* về kiểu/miền hợp lệ. Rác ⇒ mặc định, không ném.

    Không ném là cố ý: hàm này còn chạy lúc NẠP agents.json lúc khởi động,
    một dòng hỏng không được phép làm chết cả server. Tầng API mới là chỗ
    nói "sai rồi" (422) — xem AgentCreateRequest/AgentUpdateRequest.
    """
    if key in ("auto_publish", "publish_monetize"):
        return bool(value)
    if key == "publish_method":
        m = str(value or "").strip().lower()
        return m if m in PUBLISH_METHOD_CHOICES else PUBLISH_DEFAULTS[key]
    if key in ("publish_token_id", "publish_channel_id", "publish_channel_name"):
        return str(value or "")
    if key == "publish_privacy":
        privacy = str(value or "").strip().lower()
        # Một giá trị lạ đi thẳng vào videos.insert sẽ bị YouTube từ chối (mất
        # cả video vừa dựng), nên quy về mặc định thay vì chờ tới lúc đăng.
        return privacy if privacy in PUBLISH_PRIVACY_CHOICES else PUBLISH_DEFAULTS[key]
    if key == "publish_min_pages":
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            return PUBLISH_DEFAULTS[key]
    if key == "publish_max_per_day":
        try:
            # 0 = khoá hẳn (người dùng tự hạ trần về 0) nên 0 là giá trị HỢP LỆ;
            # chỉ chặn số âm và rác.
            return max(0, int(value))
        except (TypeError, ValueError):
            return PUBLISH_DEFAULTS[key]
    return value


def coerce_publish_fields(values: Dict[str, Any]) -> Dict[str, Any]:
    """Bản dùng cho cả một dict: chỉ động đến các khoá publish_* đã biết."""
    return {k: (coerce_publish_value(k, v) if k in PUBLISH_DEFAULTS else v)
            for k, v in values.items()}


class Agent:
    """An AI agent with identity, skills, and behavioral configuration."""

    def __init__(
        self,
        name: str,
        description: str = "",
        system_prompt: str = "You are a helpful AI assistant.",
        allowed_skills: List[str] = None,
        id: Optional[str] = None,
        created_at: Optional[str] = None,
        model: str = None,
        # Tab 1: Identity & Options
        avatar_icon: str = "SMART_TOY", 
        avatar_type: str = "bot",
        avatar_color: str = "blue",
        # Empty means "not chosen". The AI that drives this agent's browser
        # is then resolve_browser_ai()'s answer — the user's default browser
        # AI, or their default AI — instead of a model literal the agent was
        # born holding and nobody ever picked.
        browser_ai_model: str = "",
        # Tab 3: Telegram
        telegram_token: str = "",
        telegram_chat_id: str = "",
        # Tab 4: Messenger
        messenger_token: str = "",
        messenger_page_id: str = "",
        messenger_php_url: str = "",
        direct_trigger_skill_id: str = "",
        # Team Delegation (Phase 2)
        role: str = "general",  # "orchestrator" | "specialist" | "general"
        specialties: List[str] = None,  # ["video", "calendar", "search", ...]
        # Smart Agent fields (Tab 5: Behavior)
        persona: Dict = None,
        routine: Dict = None,
        thinking_map: Dict = None,
        history_log: List[Dict] = None,
        # Browser & Network (Tab 6: Browser)
        allowed_profiles: List[str] = None,
        login_accounts: List[str] = None,
        proxy_config: str = "", 
        proxy_provider: Dict = None,
        # Schedule (Tab 7: Schedule)
        timezone: str = None,
        # Language for keywords / prompts / responses
        language: str = "auto",
        # The Content Studio wizard preset (template) this agent's videos
        # follow; "" = the Studio's defaults. Saved from the wizard's
        # Preset → Save, so there is one template system, not two.
        content_video_preset: str = "",
        # Auth & Clouds (Misc)
        auth: Dict = None, 
        cloud_api_keys: Dict = None,
        # Scraper History (Tab 8: History)
        enable_scraping: bool = False,
        scraper_text_limit: int = 10000,
        script_output_format: str = "json",
        # Đưa lịch/hành vi + nhật ký lượt chạy vào ngữ cảnh CHAT (mặc định bật)
        routine_in_chat: bool = True,
        # Hành vi GIỐNG NGƯỜI bằng AI: BẬT → agent lướt/xem/đọc do AI quyết từng
        # bước (tự nhiên hơn nhưng TỐN TOKEN). TẮT (mặc định) → chạy bằng kịch bản
        # cố định (search→click→browse/watch), tiết kiệm. Email soạn-mới (trả lời/
        # báo cáo) LUÔN dùng AI; check-mail LUÔN dùng script — cờ này chỉ đổi các
        # hành vi lướt/xem.
        humanlike_behavior: bool = False,
        # ── Tự động đăng video sau mỗi lượt thu thập ───────────────────
        # BẬT → lượt hẹn giờ nào thu thập được đủ bài mới thì tự viết kịch bản,
        # dựng mp4 và ĐĂNG THẲNG lên kênh YouTube đã chọn, không chờ ai duyệt.
        # Mặc định TẮT: đây là hành động công khai ra ngoài, phải do người dùng
        # bấm bật, không được là mặc định của mọi agent cũ.
        auto_publish: bool = False,
        # Token YouTube CỤ THỂ, không phải cred_id. Một credential Google có thể
        # đang giữ nhiều token (máy này: 9 token YouTube chung 1 credential), nên
        # tra theo cred_id chỉ trả về "token nào đứng trước trong dict" — tức là
        # đăng nhầm kênh. Chỉ token_id mới trỏ đúng một tài khoản.
        publish_token_id: str = "",
        # Kênh đích. channel_name lưu kèm để pipeline sinh tiêu đề/mô tả/hashtag
        # "theo tên kênh" mà không phải gọi YouTube API chỉ để hỏi tên (và giao
        # diện vẫn hiện đúng tên khi token tạm hỏng).
        publish_channel_id: str = "",
        publish_channel_name: str = "",
        # "đăng luôn khỏi duyệt" ⇒ mặc định public. Lưu ý: OAuth client CHƯA được
        # Google xác minh sẽ bị ép về private bất kể giá trị này.
        publish_privacy: str = "public",
        # Đường đăng. Mặc định "script" vì đó là đường người dùng đã chạy thật
        # và là đường DUY NHẤT bật được kiếm tiền; "api" nhanh hơn nhưng không.
        publish_method: str = "script",
        publish_monetize: bool = False,
        # Số bài MỚI (đã cào được nội dung) tối thiểu để bõ công làm một video.
        publish_min_pages: int = 3,
        # Trần video/ngày. YouTube videos.insert tốn 1600 trên hạn mức 10.000/ngày
        # của MỘT OAuth client — tức khoảng 6 lượt đăng/ngày cho TẤT CẢ tài khoản
        # dùng chung client đó. Mặc định 2 để vài agent cùng chạy vẫn không cháy
        # hạn mức, kéo theo khoá cả nút Upload tay của người dùng.
        publish_max_per_day: int = 2,
        # Schedule Settings
        schedule_enabled: bool = False,
        schedule_repeat: str = "Daily",
        schedule_interval: int = 60,
        schedule_active_days: List[str] = None,
        schedule_start_time: str = "08:00",
        schedule_end_time: str = "22:00",
        schedule_max_runs: int = 10,
        schedule_next_run: str = None,
        schedule_last_run: str = None,
        schedule_runs_today: int = 0,
        **kwargs,
    ):
        self.id = id or str(_uuid7())
        self.name = name
        self.description = description
        self.system_prompt = system_prompt
        self.allowed_skills = allowed_skills or []
        self.created_at = created_at or datetime.datetime.now().isoformat()
        self.model = model
        
        # New comprehensive fields
        self.avatar_icon = avatar_icon
        self.avatar_type = avatar_type
        self.avatar_color = avatar_color
        self.browser_ai_model = browser_ai_model
        
        self.telegram_token = telegram_token
        self.telegram_chat_id = telegram_chat_id
        
        self.messenger_token = messenger_token
        self.messenger_page_id = messenger_page_id
        self.messenger_php_url = messenger_php_url
        self.direct_trigger_skill_id = direct_trigger_skill_id
        self.role = role
        self.specialties = specialties or []

        # Smart Agent
        self.persona = persona or {}
        self.routine = routine or {}
        self.thinking_map = thinking_map or {"concepts": {}, "emotions": {"current": "neutral"}}
        self.history_log = history_log or []
        
        # Browser
        self.allowed_profiles = allowed_profiles or []
        # Tài khoản Keychain agent dùng để đăng nhập. Mỗi cái sẽ
        # được đảm bảo có profile (tạo nếu thiếu) trước khi routine chạy.
        self.login_accounts = login_accounts or []
        self.proxy_config = proxy_config
        self.proxy_provider = proxy_provider or {"mode": "static"}
        
        self.timezone = timezone
        self.language = language or "auto"
        self.content_video_preset = str(content_video_preset or "")
        self.auth = auth or {"google": [], "facebook": [], "tiktok": [], "x": [], "discord": [], "telegram": []}
        self.cloud_api_keys = cloud_api_keys or {
            "gemini": "", "claude": "", "openai": "", "deepseek": ""
        }
        
        # Scraper
        self.enable_scraping = enable_scraping
        self.scraper_text_limit = scraper_text_limit
        self.script_output_format = script_output_format
        self.routine_in_chat = True if routine_in_chat is None else bool(routine_in_chat)
        self.humanlike_behavior = bool(humanlike_behavior)

        # Tự động đăng video. Ép kiểu ngay tại đây chứ không tin dữ liệu trong
        # agents.json: file đó do người dùng / bản cũ ghi, một chuỗi "3" lọt vào
        # publish_min_pages sẽ làm phép so sánh ngưỡng sai âm thầm. Cùng một
        # bộ luật với AgentManager.update — xem coerce_publish_value ở trên.
        for _k, _v in coerce_publish_fields({
            "auto_publish": auto_publish,
            "publish_token_id": publish_token_id,
            "publish_channel_id": publish_channel_id,
            "publish_channel_name": publish_channel_name,
            "publish_privacy": publish_privacy,
            "publish_method": publish_method,
            "publish_monetize": publish_monetize,
            "publish_min_pages": publish_min_pages,
            "publish_max_per_day": publish_max_per_day,
        }).items():
            setattr(self, _k, _v)

        # Schedule
        self.schedule_enabled = schedule_enabled
        self.schedule_repeat = schedule_repeat
        self.schedule_interval = schedule_interval
        self.schedule_active_days = schedule_active_days or ["Mon", "Tue", "Wed", "Thu", "Fri"]
        self.schedule_start_time = schedule_start_time
        self.schedule_end_time = schedule_end_time
        self.schedule_max_runs = schedule_max_runs
        self.schedule_next_run = schedule_next_run
        self.schedule_last_run = schedule_last_run
        self.schedule_runs_today = schedule_runs_today

        # AI Arena chess stats (ELO, W/L/D, learned principles) — optional.
        self.chess_stats = kwargs.get("chess_stats", {}) or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "system_prompt": self.system_prompt,
            "allowed_skills": self.allowed_skills,
            "created_at": self.created_at,
            "model": self.model,
            "avatar_icon": self.avatar_icon,
            "avatar_type": self.avatar_type,
            "avatar_color": self.avatar_color,
            # Reported raw, empty when unset. /api/v1/agents/{id} carries the
            # resolved answer alongside it as "browser_ai_resolved".
            "browser_ai_model": getattr(self, "browser_ai_model", "") or "",
            "telegram_token": self.telegram_token,
            "telegram_chat_id": self.telegram_chat_id,
            "messenger_token": self.messenger_token,
            "messenger_page_id": self.messenger_page_id,
            "messenger_php_url": self.messenger_php_url,
            "direct_trigger_skill_id": self.direct_trigger_skill_id,
            "role": getattr(self, "role", "general"),
            "specialties": getattr(self, "specialties", []),
            "persona": self.persona,
            "routine": self.routine,
            "thinking_map": self.thinking_map,
            "history_log": self.history_log,
            "allowed_profiles": getattr(self, "allowed_profiles", []),
            "login_accounts": getattr(self, "login_accounts", []),
            "proxy_config": getattr(self, "proxy_config", ""),
            "proxy_provider": getattr(self, "proxy_provider", {"mode": "static"}),
            "timezone": getattr(self, "timezone", None),
            "language": getattr(self, "language", "auto"),
            "content_video_preset": getattr(self, "content_video_preset", "") or "",
            "auth": getattr(self, "auth", {}),
            "cloud_api_keys": getattr(self, "cloud_api_keys", {}),
            "enable_scraping": getattr(self, "enable_scraping", False),
            "scraper_text_limit": getattr(self, "scraper_text_limit", 10000),
            "script_output_format": getattr(self, "script_output_format", "json"),
            "routine_in_chat": getattr(self, "routine_in_chat", True),
            "humanlike_behavior": getattr(self, "humanlike_behavior", False),
            "auto_publish": getattr(self, "auto_publish", False),
            "publish_token_id": getattr(self, "publish_token_id", "") or "",
            "publish_channel_id": getattr(self, "publish_channel_id", "") or "",
            "publish_channel_name": getattr(self, "publish_channel_name", "") or "",
            "publish_privacy": getattr(self, "publish_privacy", "public") or "public",
            "publish_method": getattr(self, "publish_method", "script") or "script",
            "publish_monetize": bool(getattr(self, "publish_monetize", False)),
            "publish_min_pages": getattr(self, "publish_min_pages", 3),
            "publish_max_per_day": getattr(self, "publish_max_per_day", 2),
            "schedule_enabled": getattr(self, "schedule_enabled", False),
            "schedule_repeat": getattr(self, "schedule_repeat", "Daily"),
            "schedule_interval": getattr(self, "schedule_interval", 60),
            "schedule_active_days": getattr(self, "schedule_active_days", []),
            "schedule_start_time": getattr(self, "schedule_start_time", "08:00"),
            "schedule_end_time": getattr(self, "schedule_end_time", "22:00"),
            "schedule_max_runs": getattr(self, "schedule_max_runs", 10),
            "schedule_next_run": getattr(self, "schedule_next_run", None),
            "schedule_last_run": getattr(self, "schedule_last_run", None),
            "schedule_runs_today": getattr(self, "schedule_runs_today", 0),
            "schedule": {
                "enabled": getattr(self, "schedule_enabled", False),
                "repeat": getattr(self, "schedule_repeat", "Daily"),
                "interval": getattr(self, "schedule_interval", 60),
                "active_days": getattr(self, "schedule_active_days", []),
                "start_time": getattr(self, "schedule_start_time", "08:00"),
                "end_time": getattr(self, "schedule_end_time", "22:00"),
                "max_runs": getattr(self, "schedule_max_runs", 10),
            },
            "chess_stats": getattr(self, "chess_stats", {}),
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "Agent":
        return cls(**data)


class AgentManager:
    """CRUD manager for agents with JSON persistence."""

    def __init__(self, agents_file: Path = None):
        self.agents_file = agents_file or AGENTS_FILE
        self.agents: Dict[str, Agent] = {}
        ensure_data_dirs()
        self._load()

    def _load(self):
        if self.agents_file.exists():
            try:
                with open(self.agents_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.agents = {item["id"]: Agent.from_dict(item) for item in data}
                # Run migration to clean default agent names & Orchestrator icon
                if self._migrate_default_agents():
                    self._save()
            except Exception as e:
                print(f"[AgentManager] Error loading agents: {e}")
                self.agents = {}

    def _migrate_default_agents(self) -> bool:
        renamed = False
        name_mapping = {
            "🎬 Video Agent": "Video Agent",
            "📅 Calendar Agent": "Calendar Agent",
            "🔍 Search Agent": "Search Agent",
            "🌐 Web Agent": "Web Agent",
            "🤖 Orchestrator": "Orchestrator",
        }
        for agent in self.agents.values():
            old_name = agent.name
            if old_name in name_mapping:
                agent.name = name_mapping[old_name]
                renamed = True
            else:
                for emoji in ["🎬", "📅", "🔍", "🌐", "🤖", "🛡️", "🔵"]:
                    if old_name.startswith(emoji):
                        trimmed = old_name[len(emoji):].strip()
                        if trimmed in ["Video Agent", "Calendar Agent", "Search Agent", "Web Agent", "Orchestrator"]:
                            agent.name = trimmed
                            renamed = True
                            break
            # Adjust Orchestrator icon to "hub"
            if agent.name == "Orchestrator" and agent.avatar_icon != "hub":
                agent.avatar_icon = "hub"
                renamed = True
        return renamed

    def _save(self):
        try:
            self.agents_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.agents_file, "w", encoding="utf-8") as f:
                json.dump(
                    [a.to_dict() for a in self.agents.values()],
                    f, indent=2, ensure_ascii=False,
                )
        except Exception as e:
            print(f"[AgentManager] Error saving agents: {e}")

    # ── Public API ────────────────────────────────────────────────

    def create(self, **kwargs) -> Agent:
        agent = Agent(**kwargs)
        self.agents[agent.id] = agent
        self._save()
        return agent

    def update(self, agent_id: str, **updates) -> Optional[Agent]:
        if agent_id not in self.agents:
            return None
        agent = self.agents[agent_id]
        # PUT /api/v1/agents/{id} đổ thẳng body vào đây, không đi qua Agent.__init__,
        # nên mọi phép ép kiểu của hàm dựng bị bỏ qua. Chặn lại ở đây (tầng cuối
        # trước bộ nhớ) để một client cũ hay một lời gọi API trực tiếp không cài
        # được publish_max_per_day=2.5 / publish_privacy="banana" vào dây chuyền
        # tự đăng — hỏng âm thầm tới tận lần khởi động sau.
        updates = coerce_publish_fields(updates)
        for k, v in updates.items():
            if hasattr(agent, k):
                if k in ("routine", "persona") and isinstance(v, dict):
                    existing = getattr(agent, k)
                    if isinstance(existing, dict):
                        merged = dict(existing)
                        merged.update(v)
                        setattr(agent, k, merged)
                    else:
                        setattr(agent, k, v)
                else:
                    setattr(agent, k, v)
        self._save()
        return agent

    def delete(self, agent_id: str) -> bool:
        if agent_id in self.agents:
            del self.agents[agent_id]
            self._save()
            return True
        return False

    def get(self, agent_id: str) -> Optional[Agent]:
        return self.agents.get(agent_id)

    def get_all(self) -> List[Agent]:
        return list(self.agents.values())

    def find_by_name(self, name: str) -> Optional[Agent]:
        """Find agent by name (case-insensitive)."""
        for agent in self.agents.values():
            if agent.name.lower() == name.lower():
                return agent
        return None


# Global singleton
agent_manager = AgentManager()
