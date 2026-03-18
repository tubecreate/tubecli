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
        # Smart Agent fields
        persona: Dict = None,
        routine: Dict = None,
        thinking_map: Dict = None,
        history_log: List[Dict] = None,
        timezone: str = None,
        cloud_api_keys: Dict = None,
        **kwargs,
    ):
        self.id = id or str(_uuid7())
        self.name = name
        self.description = description
        self.system_prompt = system_prompt
        self.allowed_skills = allowed_skills or []
        self.created_at = created_at or datetime.datetime.now().isoformat()
        self.model = model

        # Smart Agent
        self.persona = persona or {}
        self.routine = routine or {}
        self.thinking_map = thinking_map or {"concepts": {}, "emotions": {"current": "neutral"}}
        self.history_log = history_log or []
        self.timezone = timezone
        self.cloud_api_keys = cloud_api_keys or {
            "gemini": "", "claude": "", "openai": "", "deepseek": ""
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "system_prompt": self.system_prompt,
            "allowed_skills": self.allowed_skills,
            "created_at": self.created_at,
            "model": self.model,
            "persona": self.persona,
            "routine": self.routine,
            "thinking_map": self.thinking_map,
            "history_log": self.history_log,
            "timezone": getattr(self, "timezone", None),
            "cloud_api_keys": getattr(self, "cloud_api_keys", {}),
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
            except Exception as e:
                print(f"[AgentManager] Error loading agents: {e}")
                self.agents = {}

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
