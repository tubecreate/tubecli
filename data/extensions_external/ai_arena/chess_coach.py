"""
Chess Coach — Skill-learning system for AI Arena agents.

After every chess game, an agent reflects on the match (win OR loss, good
AND bad moves) and distills concise, reusable principles. Those principles are
persisted per-agent and injected back into future game prompts, so an agent
genuinely improves over time.

Storage: data/ai_arena/chess_skills.json
"""
import json
import logging
import os
import re
from datetime import datetime
from typing import List, Optional

logger = logging.getLogger("AIArena.ChessCoach")

MAX_PRINCIPLES = 12      # cap distilled principles to keep prompts small
MAX_LESSONS = 30         # cap stored per-game reflections


class ChessCoach:
    """Generates and stores chess skill insights per agent."""

    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.skills_file = os.path.join(data_dir, "chess_skills.json")
        self._data = self._load()

    def _load(self) -> dict:
        if os.path.exists(self.skills_file):
            try:
                with open(self.skills_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"agents": {}}

    def _save(self):
        os.makedirs(os.path.dirname(self.skills_file), exist_ok=True)
        with open(self.skills_file, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)

    # ── Read API ──────────────────────────────────────────────

    def _agent(self, key: str) -> dict:
        return self._data["agents"].setdefault(key, {
            "principles": [],     # distilled, reusable rules
            "lessons": [],        # per-game reflections (history)
            "games_analyzed": 0,
            "updated_at": None,
        })

    def get_principles(self, key: str) -> List[str]:
        """Return the distilled principles for an agent key (provider|model)."""
        return self._data.get("agents", {}).get(key, {}).get("principles", [])

    def get_skill_block(self, key: str) -> str:
        """Build a prompt snippet with the agent's learned chess principles."""
        principles = self.get_principles(key)
        if not principles:
            return ""
        lines = "\n".join(f"- {p}" for p in principles[:MAX_PRINCIPLES])
        return (
            "\nYOUR LEARNED CHESS PRINCIPLES (from your own past games — "
            "apply them this game):\n" + lines + "\n"
        )

    def get_agent_summary(self, key: str) -> dict:
        a = self._data.get("agents", {}).get(key)
        if not a:
            return {"principles": [], "lessons": [], "games_analyzed": 0}
        return {
            "principles": a.get("principles", []),
            "lessons": a.get("lessons", [])[-10:],
            "games_analyzed": a.get("games_analyzed", 0),
            "updated_at": a.get("updated_at"),
        }

    # ── Learning API ──────────────────────────────────────────

    def learn_from_game(self, player, outcome: str, move_history: list,
                        opponent_name: str, final_reason: str) -> Optional[dict]:
        """Reflect on a finished chess game and update the agent's principles.

        Args:
            player: AIPlayer instance (has provider/model/_call_ai).
            outcome: "win" | "loss" | "draw".
            move_history: list of {san, uci, player, move_number}.
            opponent_name: opponent display name.
            final_reason: e.g. "checkmate", "max_turns".
        Returns the new reflection dict, or None on failure.
        """
        key = f"{player.provider}|{player.model}"
        agent = self._agent(key)

        prompt = self._build_reflection_prompt(
            outcome, move_history, opponent_name, final_reason,
            agent.get("principles", []),
        )

        try:
            raw = player._call_ai(prompt)
        except Exception as e:
            logger.warning(f"[ChessCoach] reflection call failed for {key}: {e}")
            return None

        if not raw or raw.startswith("[ERROR]") or raw.startswith("[QUOTA_ERROR]"):
            logger.info(f"[ChessCoach] no reflection for {key}: {str(raw)[:120]}")
            return None

        parsed = self._parse_reflection(raw)
        if not parsed:
            return None

        # Merge new principles, dedupe (case-insensitive), keep most recent.
        existing = agent.get("principles", [])
        merged = self._merge_principles(existing, parsed["principles"])
        agent["principles"] = merged[:MAX_PRINCIPLES]

        lesson = {
            "outcome": outcome,
            "opponent": opponent_name,
            "reason": final_reason,
            "summary": parsed.get("summary", ""),
            "good_moves": parsed.get("good_moves", []),
            "mistakes": parsed.get("mistakes", []),
            "learned_at": datetime.now().isoformat(),
        }
        agent.setdefault("lessons", []).append(lesson)
        agent["lessons"] = agent["lessons"][-MAX_LESSONS:]
        agent["games_analyzed"] = agent.get("games_analyzed", 0) + 1
        agent["updated_at"] = datetime.now().isoformat()

        self._save()
        logger.info(f"[ChessCoach] {key} learned {len(parsed['principles'])} "
                    f"insights ({outcome} vs {opponent_name})")
        return {"key": key, "lesson": lesson, "principles": agent["principles"]}

    # ── Internals ─────────────────────────────────────────────

    def _build_reflection_prompt(self, outcome, move_history, opponent_name,
                                 final_reason, current_principles) -> str:
        moves_san = []
        for m in move_history:
            san = m.get("san") or m.get("move") or m.get("uci") or ""
            if san:
                moves_san.append(san)
        pgn_like = " ".join(
            (f"{i//2+1}." if i % 2 == 0 else "") + s
            for i, s in enumerate(moves_san)
        )
        pgn_like = pgn_like[:2000]  # token guard

        prior = ""
        if current_principles:
            prior = "Your current principles:\n" + \
                    "\n".join(f"- {p}" for p in current_principles) + "\n"

        return f"""You just finished a chess game. Reflect and learn from it.

RESULT: You {outcome.upper()} (reason: {final_reason}) against {opponent_name}.

MOVES PLAYED (SAN):
{pgn_like or "(no moves recorded)"}

{prior}
Analyze BOTH your good moves and your mistakes — learn from wins and losses alike.
Then output STRICT JSON only (no markdown, no extra text) in this exact shape:
{{
  "summary": "one sentence on how the game went",
  "good_moves": ["short note on a strong idea you played"],
  "mistakes": ["short note on an error to avoid next time"],
  "principles": ["concise reusable rule, max 12 words", "another rule"]
}}
Keep each principle short, general, and actionable. 2-4 principles max."""

    def _parse_reflection(self, raw: str) -> Optional[dict]:
        text = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        # Pull the first {...} JSON object.
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except Exception:
            return None

        principles = data.get("principles") or []
        if isinstance(principles, str):
            principles = [principles]
        principles = [str(p).strip() for p in principles if str(p).strip()]

        def _aslist(v):
            if isinstance(v, str):
                return [v] if v.strip() else []
            if isinstance(v, list):
                return [str(x).strip() for x in v if str(x).strip()]
            return []

        return {
            "summary": str(data.get("summary", "")).strip()[:300],
            "good_moves": _aslist(data.get("good_moves"))[:5],
            "mistakes": _aslist(data.get("mistakes"))[:5],
            "principles": principles[:4],
        }

    def _merge_principles(self, existing: list, new: list) -> list:
        seen = {p.lower(): p for p in existing}
        # New principles take priority (appended last → kept after slicing? keep order)
        ordered = list(existing)
        for p in new:
            if p.lower() not in seen:
                seen[p.lower()] = p
                ordered.append(p)
        return ordered
