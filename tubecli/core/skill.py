"""
Skill Model and Manager
Skills are reusable workflow templates that agents can execute.
Equivalent to "Bots" in python-video-studio.
"""
import json
import uuid
import datetime
from typing import Dict, List, Optional, Any
from pathlib import Path

from tubecli.config import SKILLS_FILE, ensure_data_dirs


class Skill:
    """A reusable workflow template (skill)."""

    def __init__(
        self,
        name: str,
        workflow_data: Dict = None,
        skill_type: str = "General",
        description: str = "",
        commands: List[str] = None,
        schedule_enabled: bool = False,
        schedule_type: str = "daily",
        schedule_value: str = "08:00",
        schedule_interval_minutes: int = 60,
        last_run: Optional[str] = None,
        next_run: Optional[str] = None,
        created_at: str = None,
        id: Optional[str] = None,
        **kwargs,
    ):
        self.id = id or str(uuid.uuid4())
        self.name = name
        self.workflow_data = workflow_data or {"nodes": [], "connections": []}
        self.skill_type = skill_type
        self.description = description
        self.commands = commands or []
        self.schedule_enabled = schedule_enabled
        self.schedule_type = schedule_type
        self.schedule_value = schedule_value
        self.schedule_interval_minutes = schedule_interval_minutes
        self.last_run = last_run
        self.next_run = next_run
        self.created_at = created_at or datetime.datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "workflow_data": self.workflow_data,
            "skill_type": self.skill_type,
            "description": self.description,
            "commands": self.commands,
            "schedule_enabled": self.schedule_enabled,
            "schedule_type": self.schedule_type,
            "schedule_value": self.schedule_value,
            "schedule_interval_minutes": self.schedule_interval_minutes,
            "last_run": self.last_run,
            "next_run": self.next_run,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "Skill":
        return cls(**data)


class SkillManager:
    """CRUD manager for skills with JSON persistence."""

    def __init__(self, skills_file: Path = None):
        self.skills_file = skills_file or SKILLS_FILE
        self.skills: Dict[str, Skill] = {}
        ensure_data_dirs()
        self._load()

    def _load(self):
        if self.skills_file.exists():
            try:
                with open(self.skills_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.skills = {item["id"]: Skill.from_dict(item) for item in data}
            except Exception as e:
                print(f"[SkillManager] Error loading skills: {e}")
                self.skills = {}

    def _save(self):
        try:
            self.skills_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.skills_file, "w", encoding="utf-8") as f:
                json.dump(
                    [s.to_dict() for s in self.skills.values()],
                    f, indent=2, ensure_ascii=False,
                )
        except Exception as e:
            print(f"[SkillManager] Error saving skills: {e}")

    # ── Public API ────────────────────────────────────────────────

    def create(self, **kwargs) -> Skill:
        skill = Skill(**kwargs)
        self.skills[skill.id] = skill
        self._save()
        return skill

    def update(self, skill_id: str, **updates) -> Optional[Skill]:
        if skill_id not in self.skills:
            return None
        skill = self.skills[skill_id]
        for k, v in updates.items():
            if hasattr(skill, k):
                setattr(skill, k, v)
        self._save()
        return skill

    def delete(self, skill_id: str) -> bool:
        if skill_id in self.skills:
            del self.skills[skill_id]
            self._save()
            return True
        return False

    def get(self, skill_id: str) -> Optional[Skill]:
        return self.skills.get(skill_id)

    def get_all(self) -> List[Skill]:
        return list(self.skills.values())

    def find_by_name(self, name: str) -> Optional[Skill]:
        """Find skill by name (case-insensitive, with normalization)."""
        normalized = name.lower().replace(" ", "").replace("_", "").replace("-", "")
        for skill in self.skills.values():
            if skill.name.lower() == name.lower():
                return skill
            skill_norm = skill.name.lower().replace(" ", "").replace("_", "").replace("-", "")
            if skill_norm == normalized:
                return skill
        # Also check commands
        for skill in self.skills.values():
            if skill.commands and name in skill.commands:
                return skill
        return None


# Global singleton
skill_manager = SkillManager()
