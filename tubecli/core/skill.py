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
        skill_format: str = "workflow",
        description: str = "",
        commands: List[str] = None,
        input_hint: str = "",
        when_to_use: str = "",
        examples: List[str] = None,
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

        # Backward compatibility for old skills that might not have skill_format
        if "skill_format" in kwargs:
            self.skill_format = kwargs["skill_format"]
        else:
            self.skill_format = skill_format

        self.description = description
        self.commands = commands or []
        # ── Tool contract for LLM agents ──
        # input_hint:  what the "input" string should contain (a URL, a query…)
        # when_to_use: when the agent should (and should NOT) pick this skill
        # examples:    sample user messages → expected input
        self.input_hint = input_hint or ""
        self.when_to_use = when_to_use or ""
        self.examples = examples or []
        self.schedule_enabled = schedule_enabled
        self.schedule_type = schedule_type
        self.schedule_value = schedule_value
        self.schedule_interval_minutes = schedule_interval_minutes
        self.last_run = last_run
        self.next_run = next_run
        self.created_at = created_at or datetime.datetime.now().isoformat()

    @property
    def is_runnable(self) -> bool:
        """Whether run_skill can actually execute this skill.
        Non-runnable skills are hidden from the LLM so agents never pick
        a skill that would immediately fail with 'no workflow nodes'."""
        wf = self.workflow_data or {}
        fmt = (self.skill_format or "workflow").lower()
        # Legacy UI-created markdown skills: skill_type="Markdown", format "workflow"
        if fmt == "workflow" and self.skill_type == "Markdown":
            fmt = "markdown"
        # A skill carrying a SOP / how-to markdown can ALWAYS run: it returns
        # that text. The "Extension Skill" studio cards (Content/Graphic/POD/
        # EduVideo/Script Studio, Subtitle Extractor, TTS) are format="workflow"
        # with only a sop → they used to count as dead and show "chưa có
        # workflow". Treating the sop as runnable turns them into useful how-to
        # responders instead. (Empty cards with no sop stay non-runnable.)
        if wf.get("sop") or wf.get("markdown_content") or wf.get("markdown"):
            return True
        if fmt == "browser_script":
            return bool(wf.get("script_id"))
        if fmt == "extension_action":
            return bool(wf.get("endpoint"))
        # Default: workflow — needs at least one node
        return bool(wf.get("nodes"))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "workflow_data": self.workflow_data,
            "skill_type": self.skill_type,
            "skill_format": self.skill_format,
            "description": self.description,
            "commands": self.commands,
            "input_hint": self.input_hint,
            "when_to_use": self.when_to_use,
            "examples": self.examples,
            "is_runnable": self.is_runnable,
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
            # Skip read-only/computed fields (e.g. is_runnable is a property)
            if k in ("is_runnable", "id"):
                continue
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

    @staticmethod
    def _normalize_name(name: str) -> str:
        """Normalize a skill name for fuzzy comparison: casefold and keep only
        alphanumeric characters (drops emoji, spaces, punctuation)."""
        return "".join(ch for ch in str(name).casefold() if ch.isalnum())

    def find_by_name(self, name: str) -> Optional[Skill]:
        """Find skill by name (case-insensitive, emoji/punctuation tolerant)."""
        if not name:
            return None
        normalized = self._normalize_name(name)
        for skill in self.skills.values():
            if skill.name.lower() == name.lower():
                return skill
            if normalized and self._normalize_name(skill.name) == normalized:
                return skill
        # Substring match (e.g. "Google Sheets" vs "📊 Google Sheets Manager")
        if normalized and len(normalized) >= 4:
            for skill in self.skills.values():
                if normalized in self._normalize_name(skill.name):
                    return skill
        # Also check commands
        for skill in self.skills.values():
            if skill.commands and name in skill.commands:
                return skill
        return None


# Global singleton
skill_manager = SkillManager()
