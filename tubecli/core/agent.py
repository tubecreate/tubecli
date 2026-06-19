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
        browser_ai_model: str = "qwen:latest",
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
        proxy_config: str = "", 
        proxy_provider: Dict = None,
        # Schedule (Tab 7: Schedule)
        timezone: str = None,
        # Auth & Clouds (Misc)
        auth: Dict = None, 
        cloud_api_keys: Dict = None,
        # Scraper History (Tab 8: History)
        enable_scraping: bool = False,
        scraper_text_limit: int = 10000,
        script_output_format: str = "json",
        # Schedule Settings
        schedule_enabled: bool = False,
        schedule_repeat: str = "Daily",
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
        self.proxy_config = proxy_config
        self.proxy_provider = proxy_provider or {"mode": "static"}
        
        self.timezone = timezone
        self.auth = auth or {"google": [], "facebook": [], "tiktok": [], "x": [], "discord": [], "telegram": []}
        self.cloud_api_keys = cloud_api_keys or {
            "gemini": "", "claude": "", "openai": "", "deepseek": ""
        }
        
        # Scraper
        self.enable_scraping = enable_scraping
        self.scraper_text_limit = scraper_text_limit
        self.script_output_format = script_output_format

        # Schedule
        self.schedule_enabled = schedule_enabled
        self.schedule_repeat = schedule_repeat
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
            "browser_ai_model": getattr(self, "browser_ai_model", "qwen:latest"),
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
            "proxy_config": getattr(self, "proxy_config", ""),
            "proxy_provider": getattr(self, "proxy_provider", {"mode": "static"}),
            "timezone": getattr(self, "timezone", None),
            "auth": getattr(self, "auth", {}),
            "cloud_api_keys": getattr(self, "cloud_api_keys", {}),
            "enable_scraping": getattr(self, "enable_scraping", False),
            "scraper_text_limit": getattr(self, "scraper_text_limit", 10000),
            "script_output_format": getattr(self, "script_output_format", "json"),
            "schedule_enabled": getattr(self, "schedule_enabled", False),
            "schedule_repeat": getattr(self, "schedule_repeat", "Daily"),
            "schedule_active_days": getattr(self, "schedule_active_days", []),
            "schedule_start_time": getattr(self, "schedule_start_time", "08:00"),
            "schedule_end_time": getattr(self, "schedule_end_time", "22:00"),
            "schedule_max_runs": getattr(self, "schedule_max_runs", 10),
            "schedule_next_run": getattr(self, "schedule_next_run", None),
            "schedule_last_run": getattr(self, "schedule_last_run", None),
            "schedule_runs_today": getattr(self, "schedule_runs_today", 0),
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
        for k, v in updates.items():
            if hasattr(agent, k):
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
