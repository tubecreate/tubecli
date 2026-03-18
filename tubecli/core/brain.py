"""
Agent Brain — Decision-making logic for smart agents.
Determines tasks based on routine/time and selects appropriate skills.
"""
import datetime
import random
from typing import Dict, List, Optional


class AgentBrain:
    """The 'brain' of a smart agent: routine analysis and skill selection."""

    @staticmethod
    def determine_current_task(routine: Dict, current_time: datetime.datetime = None) -> Optional[Dict]:
        """Determine the current task based on daily routine and time of day."""
        if not current_time:
            current_time = datetime.datetime.now()

        hour = current_time.hour
        time_of_day = "night"
        if 6 <= hour < 12:
            time_of_day = "morning"
        elif 12 <= hour < 18:
            time_of_day = "afternoon"
        elif 18 <= hour <= 23:
            time_of_day = "evening"

        daily_routine = routine.get("dailyRoutine", {})
        if not daily_routine:
            return None

        return {
            "time_of_day": time_of_day,
            "activities": daily_routine.get(time_of_day, {}),
        }

    @staticmethod
    def select_skill(task_context: Dict, available_skills: List[Dict]) -> Optional[Dict]:
        """Select the most appropriate skill for the current task context."""
        if not available_skills:
            return None

        activities = task_context.get("activities", {})
        time_of_day = task_context.get("time_of_day", "")

        # Simple keyword matching (can be enhanced with AI)
        for skill in available_skills:
            desc = (skill.get("description", "") + skill.get("name", "")).lower()
            for activity_key in activities:
                if activity_key.lower() in desc:
                    return skill

        # Fallback: return first skill
        return available_skills[0] if available_skills else None

    @staticmethod
    def update_thinking_map(thinking_map: Dict, content: str, source: str) -> Dict:
        """Update the thinking map (memory) with new information."""
        import re

        if "concepts" not in thinking_map:
            thinking_map["concepts"] = {}

        words = re.findall(r'\w+', content.lower())
        for w in words:
            if len(w) > 5:
                thinking_map["concepts"][w] = thinking_map["concepts"].get(w, 0) + 1

        return thinking_map
