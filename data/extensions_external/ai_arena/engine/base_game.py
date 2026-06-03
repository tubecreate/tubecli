"""
BaseGame — Abstract class cho tất cả game trong AI Arena.
Mỗi game cụ thể (Chess, Snake, ...) kế thừa class này.
"""
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any


class BaseGame(ABC):
    """Abstract base for all AI Arena games."""

    name: str = "base_game"
    display_name: str = "Base Game"
    icon: str = "🎮"
    min_players: int = 2
    max_players: int = 2
    description: str = ""

    @abstractmethod
    def get_initial_state(self, player_ids: List[str]) -> dict:
        """Create and return the initial game state."""
        pass

    @abstractmethod
    def get_valid_moves(self, state: dict, player_id: str) -> list:
        """Return list of valid moves for the given player."""
        pass

    @abstractmethod
    def apply_move(self, state: dict, player_id: str, move: Any) -> dict:
        """Apply a move and return the new state."""
        pass

    @abstractmethod
    def check_game_over(self, state: dict) -> Optional[dict]:
        """Check if game is over.
        Returns None if not over, or dict with:
        {
            "winner": player_id or None (draw),
            "reason": "checkmate" | "timeout" | "collision" | etc,
            "scores": {player_id: score, ...}
        }
        """
        pass

    @abstractmethod
    def get_current_player(self, state: dict) -> str:
        """Return the player_id whose turn it is."""
        pass

    @abstractmethod
    def render_state_for_ai(self, state: dict, player_id: str) -> str:
        """Render the game state as a text prompt for the AI to understand."""
        pass

    @abstractmethod
    def parse_ai_move(self, ai_response: str, state: dict, player_id: str) -> Any:
        """Parse the AI's text response into a valid move object.
        Raises ValueError if the response cannot be parsed.
        """
        pass

    @abstractmethod
    def render_state_for_ui(self, state: dict) -> dict:
        """Render the game state as a JSON-serializable dict for the frontend."""
        pass

    def get_game_rules_prompt(self) -> str:
        """Return a string describing the game rules for the AI."""
        return f"You are playing {self.display_name}."

    def get_max_turns(self) -> int:
        """Maximum turns before the game is declared a draw."""
        return 200
