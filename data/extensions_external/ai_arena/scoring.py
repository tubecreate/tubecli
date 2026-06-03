"""
ELO Scoring System + Match Persistence for AI Arena.
"""
import json
import os
import logging
from typing import Dict, Optional
from datetime import datetime

logger = logging.getLogger("AIArena.Scoring")

K_FACTOR = 32  # ELO K-factor


class ScoringSystem:
    """ELO rating + match history."""

    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.leaderboard_file = os.path.join(data_dir, "leaderboard.json")
        self.matches_dir = os.path.join(data_dir, "matches")
        os.makedirs(self.matches_dir, exist_ok=True)
        self._leaderboard = self._load_leaderboard()

    def _load_leaderboard(self) -> dict:
        if os.path.exists(self.leaderboard_file):
            try:
                with open(self.leaderboard_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"players": {}}

    def _save_leaderboard(self):
        os.makedirs(os.path.dirname(self.leaderboard_file), exist_ok=True)
        with open(self.leaderboard_file, "w", encoding="utf-8") as f:
            json.dump(self._leaderboard, f, indent=2, ensure_ascii=False)

    def get_player_rating(self, player_key: str) -> int:
        """Get ELO rating for a player (identified by provider|model)."""
        player = self._leaderboard["players"].get(player_key, {})
        return player.get("elo", 1500)

    def update_ratings(self, players: list, result: dict):
        """Update ELO ratings after a match.
        
        Args:
            players: List of dicts with {key, name, provider, model, emoji}
            result: Dict with {winner, scores: {player_key: score}}
        """
        scores = result.get("scores", {})
        player_keys = [p["key"] for p in players]

        # Initialize players in leaderboard if needed
        for p in players:
            if p["key"] not in self._leaderboard["players"]:
                self._leaderboard["players"][p["key"]] = {
                    "name": p["name"],
                    "provider": p["provider"],
                    "model": p["model"],
                    "emoji": p.get("emoji", "🤖"),
                    "elo": 1500,
                    "wins": 0,
                    "losses": 0,
                    "draws": 0,
                    "games": 0,
                    "total_tokens": 0,
                    "agent_id": p.get("agent_id", ""),
                }
            else:
                self._leaderboard["players"][p["key"]]["name"] = p["name"]
                if "emoji" in p:
                    self._leaderboard["players"][p["key"]]["emoji"] = p["emoji"]
                if "agent_id" in p:
                    self._leaderboard["players"][p["key"]]["agent_id"] = p["agent_id"]

        # For 2-player: standard ELO
        if len(player_keys) == 2:
            k1, k2 = player_keys[0], player_keys[1]
            r1 = self._leaderboard["players"][k1]["elo"]
            r2 = self._leaderboard["players"][k2]["elo"]
            s1 = scores.get(k1, 0.5)
            s2 = scores.get(k2, 0.5)

            e1 = 1 / (1 + 10 ** ((r2 - r1) / 400))
            e2 = 1 / (1 + 10 ** ((r1 - r2) / 400))

            self._leaderboard["players"][k1]["elo"] = round(r1 + K_FACTOR * (s1 - e1))
            self._leaderboard["players"][k2]["elo"] = round(r2 + K_FACTOR * (s2 - e2))

            # Update W/L/D
            for key, score in [(k1, s1), (k2, s2)]:
                self._leaderboard["players"][key]["games"] += 1
                if score == 1.0:
                    self._leaderboard["players"][key]["wins"] += 1
                elif score == 0.0:
                    self._leaderboard["players"][key]["losses"] += 1
                else:
                    self._leaderboard["players"][key]["draws"] += 1
        else:
            # Multi-player: simplified — gain/lose based on finish position
            sorted_players = sorted(player_keys, key=lambda k: scores.get(k, 0), reverse=True)
            n = len(sorted_players)
            for i, key in enumerate(sorted_players):
                rank_score = 1.0 - (i / (n - 1)) if n > 1 else 0.5
                current_elo = self._leaderboard["players"][key]["elo"]
                avg_elo = sum(self._leaderboard["players"][k]["elo"] for k in player_keys) / n
                expected = 1 / (1 + 10 ** ((avg_elo - current_elo) / 400))
                new_elo = round(current_elo + K_FACTOR * (rank_score - expected))
                self._leaderboard["players"][key]["elo"] = new_elo
                self._leaderboard["players"][key]["games"] += 1
                if rank_score >= 0.9:
                    self._leaderboard["players"][key]["wins"] += 1
                elif rank_score <= 0.1:
                    self._leaderboard["players"][key]["losses"] += 1
                else:
                    self._leaderboard["players"][key]["draws"] += 1

        self._save_leaderboard()

    def update_tokens(self, player_key: str, tokens: int):
        """Track total tokens used by a player."""
        if player_key in self._leaderboard["players"]:
            self._leaderboard["players"][player_key]["total_tokens"] = \
                self._leaderboard["players"][player_key].get("total_tokens", 0) + tokens
            self._save_leaderboard()

    def save_match(self, match_data: dict):
        """Save a completed match to disk."""
        match_id = match_data.get("id", "unknown")
        filepath = os.path.join(self.matches_dir, f"{match_id}.json")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(match_data, f, indent=2, ensure_ascii=False)

    def get_leaderboard(self, game_filter: str = None) -> list:
        """Get sorted leaderboard."""
        entries = []
        for key, data in self._leaderboard["players"].items():
            entries.append({
                "key": key,
                **data,
            })
        entries.sort(key=lambda x: x["elo"], reverse=True)
        return entries

    def get_match_history(self, limit: int = 20) -> list:
        """Get recent match history."""
        matches = []
        if os.path.isdir(self.matches_dir):
            files = sorted(os.listdir(self.matches_dir), reverse=True)[:limit]
            for fname in files:
                fpath = os.path.join(self.matches_dir, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        matches.append(json.load(f))
                except Exception:
                    pass
        return matches
