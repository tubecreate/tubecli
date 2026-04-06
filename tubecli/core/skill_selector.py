"""
Skill Selector — Smart skill filtering for LLM context.
Only injects the most relevant skills instead of ALL skills.
Inspired by claw-code-main's ToolPool and filter_tools_by_permission_context().
"""
from typing import Dict, List


class SkillSelector:
    """Select only relevant skills for a given intent, reducing token waste."""

    # Category → keyword mapping for fast lookup
    CATEGORY_MAP = {
        "video": ["video", "tải", "download", "douyin", "tiktok", "upload", "youtube"],
        "calendar": ["calendar", "lịch", "schedule", "sự kiện", "event", "nhắc"],
        "search": ["search", "tìm", "google", "tra cứu", "trending", "xu hướng"],
        "browser": ["browser", "trình duyệt", "web", "scrape", "crawl"],
        "sheets": ["sheets", "google sheets", "bảng tính", "spreadsheet"],
        "gmail": ["gmail", "email", "mail", "thư"],
        "team": ["team", "nhóm", "đội", "agent", "multi-agent"],
        "file": ["file", "folder", "thư mục", "tạo file", "xóa file"],
        "livestream": ["live", "livestream", "restream", "phát sóng", "直播"],
        "crawler": ["crawler", "watcher", "theo dõi web", "scraper"],
    }

    def select(
        self,
        message: str,
        intent_type: str,
        all_skills: List[Dict],
        matched_skill_ids: List[str] = None,
        limit: int = 3,
    ) -> List[Dict]:
        """
        Select the most relevant skills for this message + intent.
        
        Priority:
        1. Pre-matched skills from IntentRouter (highest priority)
        2. Category-based filtering by intent type
        3. Keyword scoring against message text
        
        Returns at most `limit` skills to minimize token usage.
        """
        if not all_skills:
            return []

        # 1. If IntentRouter already matched specific skills, use those
        if matched_skill_ids:
            matched = [s for s in all_skills if s.get("id") in matched_skill_ids]
            if matched:
                return matched[:limit]

        # 2. Intent-based category filter
        intent_categories = self._get_intent_categories(intent_type)
        if intent_categories:
            category_matched = self._filter_by_categories(all_skills, intent_categories)
            if category_matched:
                return category_matched[:limit]

        # 3. Keyword scoring (fallback for complex_action)
        msg_lower = message.lower()
        return self._score_and_select(msg_lower, all_skills, limit)

    def select_for_team(
        self,
        message: str,
        agent_skills: List[str],
        all_skills: List[Dict],
        limit: int = 3,
    ) -> List[Dict]:
        """Select skills for a specific team agent (only from their allowed_skills)."""
        if agent_skills:
            filtered = [s for s in all_skills if s.get("id") in agent_skills]
        else:
            filtered = all_skills
        
        msg_lower = message.lower()
        return self._score_and_select(msg_lower, filtered, limit)

    def _get_intent_categories(self, intent_type: str) -> List[str]:
        """Map intent type to relevant skill categories."""
        mapping = {
            "video_download": ["video"],
            "video_upload": ["video"],
            "calendar": ["calendar"],
            "search": ["search"],
            "file_ops": ["file"],
            "team_create": ["team"],
            "live_action": ["livestream"],
            "tracker_action": ["video", "crawler"],
        }
        return mapping.get(intent_type, [])

    def _filter_by_categories(self, skills: List[Dict], categories: List[str]) -> List[Dict]:
        """Filter skills that match any of the given categories."""
        results = []
        for skill in skills:
            name = (skill.get("name", "") or "").lower()
            desc = (skill.get("description", "") or "").lower()
            cmds = " ".join(skill.get("commands", []) or []).lower()
            haystack = f"{name} {desc} {cmds}"

            for cat in categories:
                keywords = self.CATEGORY_MAP.get(cat, [cat])
                if any(kw in haystack for kw in keywords):
                    results.append(skill)
                    break

        return results

    def _score_and_select(self, msg_lower: str, skills: List[Dict], limit: int) -> List[Dict]:
        """Score skills by relevance to message and return top N."""
        tokens = set(w for w in msg_lower.split() if len(w) > 2)
        scored = []

        for skill in skills:
            score = 0
            name = (skill.get("name", "") or "").lower()
            desc = (skill.get("description", "") or "").lower()
            cmds = skill.get("commands", []) or []

            # Command keyword match (highest weight)
            for cmd in cmds:
                if cmd and cmd.lower() in msg_lower:
                    score += 5
                    break

            # Name word match
            for w in name.split():
                if len(w) > 2 and w in tokens:
                    score += 3

            # Description word match
            desc_matches = sum(1 for w in desc.split() if len(w) > 3 and w in tokens)
            score += min(desc_matches, 3)

            if score > 0:
                scored.append((score, skill))

        scored.sort(key=lambda x: -x[0])
        return [s for _, s in scored[:limit]]


# Global singleton
skill_selector = SkillSelector()
