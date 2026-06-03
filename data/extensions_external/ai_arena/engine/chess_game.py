"""
Chess Game Engine — Cờ Vua cho AI Arena.
Sử dụng thư viện python-chess để validate nước đi.
"""
import re
from typing import Optional, List, Any

try:
    import chess
except ImportError:
    chess = None

from engine.base_game import BaseGame


class ChessGame(BaseGame):
    name = "chess"
    display_name = "♟️ Chess"
    icon = "♟️"
    min_players = 2
    max_players = 2
    description = "Classic chess — two AI models play against each other"

    # Piece unicode for UI rendering
    PIECE_SYMBOLS = {
        'P': '♙', 'N': '♘', 'B': '♗', 'R': '♖', 'Q': '♕', 'K': '♔',
        'p': '♟', 'n': '♞', 'b': '♝', 'r': '♜', 'q': '♛', 'k': '♚',
    }

    # Standard FIDE-style time controls (base seconds, increment seconds).
    TIME_CONTROLS = {
        "bullet":      {"base": 60,   "increment": 0,  "label": "Bullet 1+0"},
        "blitz":       {"base": 180,  "increment": 2,  "label": "Blitz 3+2"},
        "rapid":       {"base": 600,  "increment": 5,  "label": "Rapid 10+5"},
        "classical":   {"base": 1800, "increment": 30, "label": "Classical 30+30"},
        "unlimited":   {"base": 0,    "increment": 0,  "label": "No clock"},
    }
    DEFAULT_TIME_CONTROL = "rapid"

    def __init__(self, time_control: str = None):
      self.time_control = time_control or self.DEFAULT_TIME_CONTROL
      if self.time_control not in self.TIME_CONTROLS:
          self.time_control = self.DEFAULT_TIME_CONTROL

    def get_initial_state(self, player_ids: List[str]) -> dict:
      if chess is None:
          raise ValueError(
              "Thư viện python-chess chưa được cài đặt trên máy. "
              "Vui lòng chạy lệnh 'pip install chess' hoặc kiểm tra kết nối mạng để Extension tự động cài đặt."
          )
      if len(player_ids) != 2:
          raise ValueError("Chess requires exactly 2 players")
      tc = self.TIME_CONTROLS[self.time_control]
        return {
            "fen": chess.STARTING_FEN,
            "players": {
                "white": player_ids[0],
                "black": player_ids[1],
            },
            "move_history": [],
            "move_count": 0,
            "captured": {"white": [], "black": []},
            # ── Time control (chess clocks) ──
            "time_control": self.time_control,
            "tc_base": tc["base"],
            "tc_increment": tc["increment"],
            "clocks": {
                "white": float(tc["base"]),
                "black": float(tc["base"]),
            },
            "flagged": None,   # player_id who ran out of time
        }

    def get_valid_moves(self, state: dict, player_id: str) -> list:
        board = chess.Board(state["fen"])
        return [move.uci() for move in board.legal_moves]

    def apply_move(self, state: dict, player_id: str, move: Any) -> dict:
        board = chess.Board(state["fen"])
        uci_move = chess.Move.from_uci(str(move))

        if uci_move not in board.legal_moves:
            raise ValueError(f"Illegal move: {move}")

        # Track captured piece
        captured_piece = board.piece_at(uci_move.to_square)
        if captured_piece:
            color = "white" if captured_piece.color == chess.BLACK else "black"
            state["captured"][color].append(captured_piece.symbol().upper())

        # Record move in algebraic notation before pushing
        san_move = board.san(uci_move)
        board.push(uci_move)

        state["fen"] = board.fen()
        state["move_history"].append({
            "player": player_id,
            "uci": str(move),
            "san": san_move,
            "move_number": state["move_count"] + 1,
        })
        state["move_count"] += 1
        return state

    def consume_time(self, state: dict, player_id: str, seconds: float) -> bool:
        """Deduct thinking time from a player's clock and add the increment.

        Returns True if the player FLAGGED (ran out of time). No-op for the
        'unlimited' time control.
        """
        if state.get("tc_base", 0) <= 0:   # unlimited
            return False
        color = "white" if state["players"]["white"] == player_id else "black"
        clocks = state.setdefault("clocks", {})
        remaining = float(clocks.get(color, 0))
        remaining -= float(seconds)
        if remaining <= 0:
            clocks[color] = 0.0
            state["flagged"] = player_id
            return True
        # Survived → apply Fischer increment.
        remaining += float(state.get("tc_increment", 0))
        clocks[color] = remaining
        return False

    def check_game_over(self, state: dict) -> Optional[dict]:
        board = chess.Board(state["fen"])

        # ── Time forfeit (flag fall) ──
        flagged = state.get("flagged")
        if flagged:
            loser_id = flagged
            winner_id = next(
                (pid for pid in state["players"].values() if pid != loser_id),
                None,
            )
            return {
                "winner": winner_id,
                "reason": "timeout",
                "scores": {winner_id: 1.0, loser_id: 0.0} if winner_id else {},
            }

        if board.is_checkmate():
            # The player who is checkmated loses
            loser_color = "white" if board.turn == chess.WHITE else "black"
            winner_color = "black" if loser_color == "white" else "white"
            winner_id = state["players"][winner_color]
            loser_id = state["players"][loser_color]
            return {
                "winner": winner_id,
                "reason": "checkmate",
                "scores": {winner_id: 1.0, loser_id: 0.0},
            }

        if board.is_stalemate():
            w_id = state["players"]["white"]
            b_id = state["players"]["black"]
            return {
                "winner": None,
                "reason": "stalemate",
                "scores": {w_id: 0.5, b_id: 0.5},
            }

        if board.is_insufficient_material():
            w_id = state["players"]["white"]
            b_id = state["players"]["black"]
            return {
                "winner": None,
                "reason": "insufficient_material",
                "scores": {w_id: 0.5, b_id: 0.5},
            }

        if board.can_claim_fifty_moves():
            w_id = state["players"]["white"]
            b_id = state["players"]["black"]
            return {
                "winner": None,
                "reason": "fifty_move_rule",
                "scores": {w_id: 0.5, b_id: 0.5},
            }

        if board.is_repetition(3):
            w_id = state["players"]["white"]
            b_id = state["players"]["black"]
            return {
                "winner": None,
                "reason": "threefold_repetition",
                "scores": {w_id: 0.5, b_id: 0.5},
            }

        # Max turns check
        if state["move_count"] >= self.get_max_turns():
            w_id = state["players"]["white"]
            b_id = state["players"]["black"]
            return {
                "winner": None,
                "reason": "max_turns",
                "scores": {w_id: 0.5, b_id: 0.5},
            }

        return None

    def get_current_player(self, state: dict) -> str:
        board = chess.Board(state["fen"])
        color = "white" if board.turn == chess.WHITE else "black"
        return state["players"][color]

    def render_state_for_ai(self, state: dict, player_id: str) -> str:
        board = chess.Board(state["fen"])
        color = "white" if state["players"]["white"] == player_id else "black"

        # Build ASCII board
        board_str = str(board)

        # Valid moves
        valid_moves = [move.uci() for move in board.legal_moves]
        moves_str = ", ".join(valid_moves[:50])  # Limit to 50 for token saving
        if len(valid_moves) > 50:
            moves_str += f"... ({len(valid_moves)} total)"

        # Recent moves
        recent = state["move_history"][-6:] if state["move_history"] else []
        history_str = " → ".join([f"{m['san']}" for m in recent]) if recent else "Game just started"

        # Check status
        status = ""
        if board.is_check():
            status = "⚠️ YOU ARE IN CHECK!"

        prompt = f"""{self.get_game_rules_prompt()}

You are playing as {color.upper()}.
{status}

CURRENT BOARD (a1 is bottom-left):
{board_str}

FEN: {state['fen']}
Move #{state['move_count'] + 1}
Recent moves: {history_str}

YOUR VALID MOVES: {moves_str}

RESPOND WITH ONLY YOUR MOVE IN UCI FORMAT (e.g., e2e4, g1f3, e7e8q for promotion).
Do not include any explanation, just the move."""

        return prompt

    def parse_ai_move(self, ai_response: str, state: dict, player_id: str) -> Any:
        """Parse UCI move from AI response."""
        # Clean response — keep original case for SAN
        original_text = ai_response.strip()
        original_text = re.sub(r'<think>.*?</think>', '', original_text, flags=re.DOTALL).strip()
        text = original_text.lower()

        board = chess.Board(state["fen"])

        # Try to find a UCI move pattern (e.g., e2e4, a7a8q)
        uci_pattern = re.findall(r'\b([a-h][1-8][a-h][1-8][qrbn]?)\b', text)
        for move_str in uci_pattern:
            try:
                move = chess.Move.from_uci(move_str)
                if move in board.legal_moves:
                    return move_str
            except (ValueError, chess.InvalidMoveError):
                continue

        # Try SAN notation case-sensitive (e.g., Nf3, e4, O-O, Qxd5)
        san_pattern = re.findall(
            r'\b([KQRBN]?[a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?[+#]?|O-O(?:-O)?)\b',
            original_text
        )
        for san in san_pattern:
            try:
                move = board.parse_san(san)
                return move.uci()
            except (ValueError, chess.InvalidMoveError, chess.AmbiguousMoveError, chess.IllegalMoveError):
                continue

        # Fallback: try matching any word against all legal moves' SAN
        words = re.findall(r'[A-Za-z0-9\-\+\#\=]+', original_text)
        for word in words:
            for legal_move in board.legal_moves:
                try:
                    san = board.san(legal_move)
                    if word == san or word.lower() == san.lower():
                        return legal_move.uci()
                except Exception:
                    continue

        raise ValueError(f"Could not parse move from AI response: {ai_response[:200]}")

    def render_state_for_ui(self, state: dict) -> dict:
        board = chess.Board(state["fen"])

        # Build 8x8 grid for UI
        grid = []
        for rank in range(7, -1, -1):
            row = []
            for file in range(8):
                square = chess.square(file, rank)
                piece = board.piece_at(square)
                cell = {
                    "square": chess.square_name(square),
                    "piece": piece.symbol() if piece else None,
                    "unicode": self.PIECE_SYMBOLS.get(piece.symbol(), '') if piece else '',
                    "color": "white" if piece and piece.color == chess.WHITE else ("black" if piece else None),
                    "is_light": (rank + file) % 2 == 1,
                }
                row.append(cell)
            grid.append(row)

        # Last move highlight
        last_move = None
        if state["move_history"]:
            lm = state["move_history"][-1]["uci"]
            last_move = {"from": lm[:2], "to": lm[2:4]}

        return {
            "game": "chess",
            "grid": grid,
            "fen": state["fen"],
            "turn": "white" if board.turn == chess.WHITE else "black",
            "is_check": board.is_check(),
            "move_count": state["move_count"],
            "move_history": state["move_history"],
            "captured": state["captured"],
            "last_move": last_move,
            "players": state["players"],
            # Time control / clocks
            "time_control": state.get("time_control", "unlimited"),
            "tc_increment": state.get("tc_increment", 0),
            "clocks": state.get("clocks", {}),
            "flagged": state.get("flagged"),
        }

    def get_game_rules_prompt(self) -> str:
        return """You are playing CHESS. Standard international chess rules apply.
You must respond with EXACTLY ONE valid move in UCI format (e.g., e2e4, g1f3).
For pawn promotion, append the piece letter (e.g., e7e8q for queen promotion).
For castling: e1g1 (kingside white), e1c1 (queenside white), e8g8 (kingside black), e8c8 (queenside black).
Think strategically. Try to control the center, develop pieces, and protect your king."""

    def get_max_turns(self) -> int:
        return 150  # 150 half-moves = 75 full moves
