"""
Agent Memory — 3-Layer Memory System for AI Agents.

Layer 1: Working Memory  — last 10 messages (handled by brain.py, not here)
Layer 2: Session Memory  — auto-summarized past sessions
Layer 3: Long-term Memory — extracted facts & knowledge

Also supports Team Shared Memory (briefings + knowledge).
"""
import json
import os
import datetime
from typing import Dict, List, Optional, Callable
from pathlib import Path

from tubecli.config import AGENT_MEMORY_DIR, TEAM_MEMORY_DIR

# ── Constants ────────────────────────────────────────────────────────
MAX_SESSIONS = 20          # Keep last N session summaries
MAX_FACTS = 100            # Max facts per agent
SUMMARIZE_THRESHOLD = 20   # Summarize after N messages
PAUSE_MINUTES = 30         # Summarize if last msg > N min ago
MEMORY_CONTEXT_LIMIT = 2000  # Max chars injected into system prompt
MAX_TEAM_BRIEFINGS = 10    # Keep last N team briefings


# ── Utility ──────────────────────────────────────────────────────────

def _agent_dir(agent_id: str) -> Path:
    """Return and ensure the memory directory for an agent."""
    d = AGENT_MEMORY_DIR / agent_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _team_dir(team_id: str) -> Path:
    """Return and ensure the memory directory for a team."""
    d = TEAM_MEMORY_DIR / team_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_json(path: Path) -> list:
    """Load a JSON list from file, return [] if missing/corrupt."""
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _save_json(path: Path, data: list):
    """Save a list to JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ════════════════════════════════════════════════════════════════════
#  LAYER 2: Session Memory
# ════════════════════════════════════════════════════════════════════

class SessionMemory:
    """Manages auto-summarized session history for each agent."""

    @staticmethod
    def _sessions_path(agent_id: str) -> Path:
        return _agent_dir(agent_id) / "sessions.json"

    @staticmethod
    def should_summarize(agent_id: str, history: List[Dict]) -> bool:
        """Check if a summarization is needed:
        - 20+ messages since last summary, OR
        - Last message was >30 minutes ago (session gap detected)
        """
        if not history or len(history) < 4:
            return False

        # Count messages since last summarization marker
        unsummarized = 0
        for msg in reversed(history):
            if msg.get("_summarized"):
                break
            unsummarized += 1

        if unsummarized >= SUMMARIZE_THRESHOLD:
            return True

        # Session-gap detection: this runs right AFTER the newest exchange
        # (user + assistant) was appended, so comparing "now" vs the LAST
        # message is always ~0s and never fired. Instead compare the newest
        # exchange's start against the message before it — a >30 min gap
        # means the user came back after a pause → archive the old block.
        if unsummarized >= 6 and len(history) >= 3:
            try:
                cur_ts = history[-2].get("timestamp", "")   # current user msg
                prev_ts = history[-3].get("timestamp", "")  # end of previous exchange
                if cur_ts and prev_ts:
                    cur_time = datetime.datetime.fromisoformat(cur_ts)
                    prev_time = datetime.datetime.fromisoformat(prev_ts)
                    if (cur_time - prev_time).total_seconds() > PAUSE_MINUTES * 60:
                        return True
            except Exception:
                pass

        return False

    @staticmethod
    def summarize_and_archive(
        agent_id: str,
        history: List[Dict],
        llm_caller: Callable,
    ) -> Optional[str]:
        """Use LLM to summarize recent unsummarized messages.
        
        Args:
            agent_id: The agent's ID
            history: The full history_log  
            llm_caller: Function(messages) -> str that calls the agent's LLM
            
        Returns:
            The summary text, or None if failed
        """
        # Gather unsummarized messages
        unsummarized = []
        for msg in reversed(history):
            if msg.get("_summarized"):
                break
            unsummarized.insert(0, msg)

        if len(unsummarized) < 4:
            return None

        # Build conversation text for summarization
        conv_text = ""
        for msg in unsummarized:
            role = msg.get("role", "user")
            content = msg.get("content", "")[:500]
            conv_text += f"{role}: {content}\n"

        # Trim to reasonable size
        conv_text = conv_text[:3000]

        prompt_messages = [
            {"role": "system", "content": "You are a concise summarizer. Respond ONLY with the summary, no extra text."},
            {"role": "user", "content": f"""Summarize this conversation in 3-5 sentences. Focus on:
- What topics were discussed
- What decisions were made
- What tasks or actions were mentioned
- Any important information about the user

Conversation:
{conv_text}

Write the summary in the same language as the conversation."""}
        ]

        try:
            summary = llm_caller(prompt_messages)
            if not summary or len(summary) < 10:
                return None
        except Exception as e:
            print(f"[Memory] Summarization failed: {e}")
            return None

        # Extract topics (simple keyword extraction)
        topics = []
        topic_keywords = {
            "telegram": ["telegram", "bot token", "chat id"],
            "settings": ["settings", "cài đặt", "config", "thiết lập"],
            "memory": ["memory", "bộ nhớ", "nhớ", "lưu trữ"],
            "workflow": ["workflow", "skill", "node", "quy trình"],
            "agent": ["agent", "sub-agent", "team", "nhân viên"],
            "browser": ["browser", "trình duyệt", "profile", "chrome"],
            "development": ["code", "dev", "build", "deploy", "lập trình"],
            "api": ["api", "endpoint", "request", "server"],
        }
        conv_lower = conv_text.lower()
        for topic, keywords in topic_keywords.items():
            if any(kw in conv_lower for kw in keywords):
                topics.append(topic)

        # Save session
        now = datetime.datetime.now()
        session = {
            "id": f"sess_{now.strftime('%Y%m%d_%H%M')}",
            "timestamp": now.isoformat(),
            "summary": summary.strip(),
            "message_count": len(unsummarized),
            "topics": topics[:5],
        }

        sessions = _load_json(SessionMemory._sessions_path(agent_id))
        sessions.append(session)

        # Keep only last MAX_SESSIONS
        if len(sessions) > MAX_SESSIONS:
            sessions = sessions[-MAX_SESSIONS:]

        _save_json(SessionMemory._sessions_path(agent_id), sessions)

        print(f"[Memory] Session archived for agent {agent_id[:8]}... "
              f"({len(unsummarized)} msgs → summary)")

        return summary

    @staticmethod
    def get_recent_sessions(agent_id: str, limit: int = 5) -> List[Dict]:
        """Load the last N session summaries."""
        sessions = _load_json(SessionMemory._sessions_path(agent_id))
        return sessions[-limit:]

    @staticmethod
    def clear(agent_id: str):
        """Clear all session memory for an agent."""
        path = SessionMemory._sessions_path(agent_id)
        if path.exists():
            path.unlink()


# ════════════════════════════════════════════════════════════════════
#  LAYER 3: Long-term Knowledge
# ════════════════════════════════════════════════════════════════════

class KnowledgeMemory:
    """Manages extracted facts and knowledge for persistent memory."""

    VALID_CATEGORIES = [
        "user_info",      # Name, habits, timezone
        "project_info",   # Projects being worked on
        "decisions",      # Important decisions made
        "preferences",    # Style, language, tool preferences
        "sub_agents",     # Info about sub-agents and teams
        "technical",      # Technical details, ports, models
    ]

    @staticmethod
    def _knowledge_path(agent_id: str) -> Path:
        return _agent_dir(agent_id) / "knowledge.json"

    @staticmethod
    def extract_facts(
        agent_id: str,
        history: List[Dict],
        llm_caller: Callable,
    ) -> List[Dict]:
        """Use LLM to extract important facts from recent conversation.
        
        Returns list of extracted facts.
        """
        # Gather unsummarized messages
        unsummarized = []
        for msg in reversed(history):
            if msg.get("_summarized"):
                break
            unsummarized.insert(0, msg)

        if len(unsummarized) < 4:
            return []

        conv_text = ""
        for msg in unsummarized:
            role = msg.get("role", "user")
            content = msg.get("content", "")[:500]
            conv_text += f"{role}: {content}\n"

        conv_text = conv_text[:3000]

        # Load existing facts to avoid duplicates
        existing = KnowledgeMemory.get_knowledge(agent_id)
        existing_text = "\n".join([f"- {f['fact']}" for f in existing[-20:]]) if existing else "None yet"

        categories_str = ", ".join(KnowledgeMemory.VALID_CATEGORIES)

        prompt_messages = [
            {"role": "system", "content": "You are a fact extractor. Output ONLY valid JSON array, nothing else."},
            {"role": "user", "content": f"""Extract important facts from this conversation that should be remembered long-term.

ALREADY KNOWN FACTS (avoid duplicates):
{existing_text}

CONVERSATION:
{conv_text}

Extract NEW facts only. Output a JSON array. Each item:
{{"fact": "concise fact statement", "category": "one of: {categories_str}", "importance": "high/medium/low"}}

Rules:
- Only extract facts worth remembering (names, preferences, decisions, project info)
- Skip trivial chitchat
- If no important new facts, return empty array: []
- Write facts in the same language as the conversation"""}
        ]

        try:
            raw = llm_caller(prompt_messages)
            # Parse JSON from response
            import re
            match = re.search(r'\[.*\]', raw, re.DOTALL)
            if not match:
                return []
            facts_data = json.loads(match.group())
        except Exception as e:
            print(f"[Memory] Fact extraction failed: {e}")
            return []

        if not isinstance(facts_data, list):
            return []

        # Save new facts
        now = datetime.datetime.now()
        new_facts = []
        for i, fd in enumerate(facts_data[:10]):  # Max 10 facts per extraction
            if not isinstance(fd, dict) or not fd.get("fact"):
                continue
            
            category = fd.get("category", "technical")
            if category not in KnowledgeMemory.VALID_CATEGORIES:
                category = "technical"

            fact = {
                "id": f"fact_{now.strftime('%Y%m%d%H%M')}_{i}",
                "fact": fd["fact"][:300],
                "category": category,
                "importance": fd.get("importance", "medium"),
                "source": f"sess_{now.strftime('%Y%m%d_%H%M')}",
                "created_at": now.isoformat(),
            }
            new_facts.append(fact)

        if new_facts:
            all_facts = existing + new_facts
            # Prune if over limit
            if len(all_facts) > MAX_FACTS:
                all_facts = KnowledgeMemory._prune(all_facts, MAX_FACTS)
            _save_json(KnowledgeMemory._knowledge_path(agent_id), all_facts)
            print(f"[Memory] {len(new_facts)} new facts extracted for agent {agent_id[:8]}...")

        return new_facts

    @staticmethod
    def get_knowledge(agent_id: str) -> List[Dict]:
        """Load all facts for an agent."""
        return _load_json(KnowledgeMemory._knowledge_path(agent_id))

    @staticmethod
    def add_fact(agent_id: str, fact: str, category: str = "technical", importance: str = "medium"):
        """Manually add a fact."""
        if category not in KnowledgeMemory.VALID_CATEGORIES:
            category = "technical"

        facts = KnowledgeMemory.get_knowledge(agent_id)
        now = datetime.datetime.now()
        facts.append({
            "id": f"fact_manual_{now.strftime('%Y%m%d%H%M%S')}",
            "fact": fact[:300],
            "category": category,
            "importance": importance,
            "source": "manual",
            "created_at": now.isoformat(),
        })

        if len(facts) > MAX_FACTS:
            facts = KnowledgeMemory._prune(facts, MAX_FACTS)

        _save_json(KnowledgeMemory._knowledge_path(agent_id), facts)

    @staticmethod
    def _prune(facts: List[Dict], max_count: int) -> List[Dict]:
        """Remove low-importance facts when over limit.
        Priority: high > medium > low, then by recency.
        """
        importance_order = {"high": 0, "medium": 1, "low": 2}
        facts.sort(key=lambda f: (
            importance_order.get(f.get("importance", "medium"), 1),
            f.get("created_at", ""),
        ))
        # Keep all high, then medium, trim low
        return facts[:max_count]

    @staticmethod
    def clear(agent_id: str):
        """Clear all knowledge for an agent."""
        path = KnowledgeMemory._knowledge_path(agent_id)
        if path.exists():
            path.unlink()


# ════════════════════════════════════════════════════════════════════
#  TEAM SHARED MEMORY
# ════════════════════════════════════════════════════════════════════

class TeamMemory:
    """Shared memory for agent teams — briefings and team knowledge."""

    @staticmethod
    def _briefings_path(team_id: str) -> Path:
        return _team_dir(team_id) / "briefings.json"

    @staticmethod
    def _knowledge_path(team_id: str) -> Path:
        return _team_dir(team_id) / "knowledge.json"

    @staticmethod
    def save_briefing(team_id: str, briefing: str, task_context: Dict = None):
        """Save a task briefing from the orchestrator for the team."""
        now = datetime.datetime.now()
        entry = {
            "id": f"brief_{now.strftime('%Y%m%d_%H%M%S')}",
            "timestamp": now.isoformat(),
            "briefing": briefing[:1000],
            "context": task_context or {},
        }

        briefings = _load_json(TeamMemory._briefings_path(team_id))
        briefings.append(entry)

        if len(briefings) > MAX_TEAM_BRIEFINGS:
            briefings = briefings[-MAX_TEAM_BRIEFINGS:]

        _save_json(TeamMemory._briefings_path(team_id), briefings)

    @staticmethod
    def get_briefings(team_id: str, limit: int = 5) -> List[Dict]:
        """Get recent team briefings."""
        briefings = _load_json(TeamMemory._briefings_path(team_id))
        return briefings[-limit:]

    @staticmethod
    def add_team_fact(team_id: str, fact: str, category: str = "technical"):
        """Add a fact to team-level knowledge."""
        facts = _load_json(TeamMemory._knowledge_path(team_id))
        now = datetime.datetime.now()
        facts.append({
            "id": f"tfact_{now.strftime('%Y%m%d%H%M%S')}",
            "fact": fact[:300],
            "category": category,
            "created_at": now.isoformat(),
        })
        if len(facts) > MAX_FACTS:
            facts = facts[-MAX_FACTS:]
        _save_json(TeamMemory._knowledge_path(team_id), facts)

    @staticmethod
    def get_team_knowledge(team_id: str) -> List[Dict]:
        """Get team-level knowledge facts."""
        return _load_json(TeamMemory._knowledge_path(team_id))

    @staticmethod
    def get_team_context(team_id: str) -> str:
        """Build a context string from team memory for sub-agents."""
        parts = []

        # Recent briefings
        briefings = TeamMemory.get_briefings(team_id, limit=3)
        if briefings:
            parts.append("📋 Team Briefings:")
            for b in briefings:
                ts = b.get("timestamp", "")[:10]
                parts.append(f"  [{ts}] {b.get('briefing', '')[:200]}")

        # Team knowledge
        facts = TeamMemory.get_team_knowledge(team_id)
        if facts:
            parts.append("\n🧠 Team Knowledge:")
            for f in facts[-10:]:
                parts.append(f"  - {f.get('fact', '')[:150]}")

        return "\n".join(parts)[:1000]

    @staticmethod
    def clear(team_id: str):
        """Clear all team memory."""
        for path in [TeamMemory._briefings_path(team_id),
                     TeamMemory._knowledge_path(team_id)]:
            if path.exists():
                path.unlink()


# ════════════════════════════════════════════════════════════════════
#  MAIN API: Build Memory Context for Brain
# ════════════════════════════════════════════════════════════════════

class AgentMemory:
    """Unified interface for the 3-layer memory system."""

    @staticmethod
    def build_memory_context(agent_id: str, team_id: str = None) -> str:
        """Build memory context string to inject into the system prompt.
        
        Combines:
        - Layer 2: Recent session summaries
        - Layer 3: Knowledge facts
        - Team: Shared briefings (if team_id provided)
        
        Returns a formatted string ≤ MEMORY_CONTEXT_LIMIT chars.
        """
        parts = []

        # Layer 2: Session Summaries
        sessions = SessionMemory.get_recent_sessions(agent_id, limit=5)
        if sessions:
            parts.append("### 📋 Previous Conversation Summaries:")
            for s in sessions:
                ts = s.get("timestamp", "")[:16]
                summary = s.get("summary", "")[:200]
                parts.append(f"  [{ts}] {summary}")

        # Layer 3: Knowledge Facts
        facts = KnowledgeMemory.get_knowledge(agent_id)
        if facts:
            parts.append("\n### 🧠 Known Facts (Long-term Memory):")
            # Group by category
            by_cat = {}
            for f in facts:
                cat = f.get("category", "other")
                by_cat.setdefault(cat, []).append(f.get("fact", ""))

            cat_labels = {
                "user_info": "👤 User",
                "project_info": "📁 Projects",
                "decisions": "✅ Decisions",
                "preferences": "⚙️ Preferences",
                "sub_agents": "🤖 Agents & Teams",
                "technical": "🔧 Technical",
            }
            for cat, cat_facts in by_cat.items():
                label = cat_labels.get(cat, cat)
                facts_str = " | ".join(cat_facts[-5:])  # Last 5 per category
                parts.append(f"  {label}: {facts_str[:300]}")

        # Team context
        if team_id:
            team_ctx = TeamMemory.get_team_context(team_id)
            if team_ctx:
                parts.append(f"\n### 👥 Team Context:\n{team_ctx}")

        result = "\n".join(parts)

        # Enforce size limit
        if len(result) > MEMORY_CONTEXT_LIMIT:
            result = result[:MEMORY_CONTEXT_LIMIT - 3] + "..."

        return result

    @staticmethod
    def should_summarize(agent_id: str, history: List[Dict]) -> bool:
        """Delegate to SessionMemory."""
        return SessionMemory.should_summarize(agent_id, history)

    @staticmethod
    def summarize_and_archive(agent_id: str, history: List[Dict], llm_caller: Callable) -> Optional[str]:
        """Delegate to SessionMemory."""
        return SessionMemory.summarize_and_archive(agent_id, history, llm_caller)

    @staticmethod
    def extract_facts(agent_id: str, history: List[Dict], llm_caller: Callable) -> List[Dict]:
        """Delegate to KnowledgeMemory."""
        return KnowledgeMemory.extract_facts(agent_id, history, llm_caller)

    @staticmethod
    def get_full_memory(agent_id: str) -> Dict:
        """Get complete memory overview for an agent."""
        return {
            "agent_id": agent_id,
            "sessions": SessionMemory.get_recent_sessions(agent_id, limit=MAX_SESSIONS),
            "knowledge": KnowledgeMemory.get_knowledge(agent_id),
            "session_count": len(SessionMemory.get_recent_sessions(agent_id, limit=MAX_SESSIONS)),
            "fact_count": len(KnowledgeMemory.get_knowledge(agent_id)),
        }

    @staticmethod
    def clear_all(agent_id: str):
        """Clear all memory for an agent."""
        SessionMemory.clear(agent_id)
        KnowledgeMemory.clear(agent_id)

    @staticmethod
    def mark_history_summarized(history: List[Dict]) -> List[Dict]:
        """Mark all current messages as summarized so they won't be re-summarized."""
        for msg in history:
            msg["_summarized"] = True
        return history
