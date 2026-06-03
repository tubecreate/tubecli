"""
Snake Arena Game Engine — Rắn Săn Mồi Arena cho AI Arena.
Nhiều rắn cùng chơi trên một bàn, turn-based.
"""
import random
import re
from typing import Optional, List, Any

from engine.base_game import BaseGame

DIRECTIONS = {
    "UP": (0, -1),
    "DOWN": (0, 1),
    "LEFT": (-1, 0),
    "RIGHT": (1, 0),
}

OPPOSITE = {
    "UP": "DOWN", "DOWN": "UP",
    "LEFT": "RIGHT", "RIGHT": "LEFT",
}


class SnakeArenaGame(BaseGame):
    name = "snake_arena"
    display_name = "🐍 Snake Arena"
    icon = "🐍"
    min_players = 2
    max_players = 6
    description = "Multi-snake battle arena — last snake standing wins!"

    BOARD_WIDTH = 20
    BOARD_HEIGHT = 15

    # Starting positions for up to 6 players
    START_POSITIONS = [
        (3, 3), (16, 11), (3, 11), (16, 3), (10, 3), (10, 11),
    ]

    SNAKE_EMOJIS = ["🟢", "🔴", "🔵", "🟡", "🟣", "🟠"]
    SNAKE_NAMES = ["Green", "Red", "Blue", "Yellow", "Purple", "Orange"]

    def get_initial_state(self, player_ids: List[str]) -> dict:
        if len(player_ids) < 2:
            raise ValueError("Snake Arena requires at least 2 players")
        if len(player_ids) > 6:
            raise ValueError("Snake Arena supports at most 6 players")

        snakes = {}
        for i, pid in enumerate(player_ids):
            sx, sy = self.START_POSITIONS[i]
            snakes[pid] = {
                "body": [(sx, sy), (sx, sy + 1), (sx, sy + 2)],  # Head first
                "direction": "UP",
                "alive": True,
                "score": 0,
                "color_index": i,
                "emoji": self.SNAKE_EMOJIS[i],
                "name": self.SNAKE_NAMES[i],
            }

        # Generate initial food
        food = self._generate_food(snakes, [], 5)

        return {
            "snakes": snakes,
            "food": food,
            "player_order": player_ids,
            "current_turn_index": 0,
            "turn_count": 0,
            "board_width": self.BOARD_WIDTH,
            "board_height": self.BOARD_HEIGHT,
            "eliminated": [],
            "simultaneous": True,  # All snakes move at once
            "pending_moves": {},
        }

    def _generate_food(self, snakes: dict, existing_food: list, count: int) -> list:
        occupied = set()
        for s in snakes.values():
            if s["alive"]:
                for pos in s["body"]:
                    occupied.add(tuple(pos))
        for f in existing_food:
            occupied.add(tuple(f))

        food = list(existing_food)
        attempts = 0
        while len(food) < count and attempts < 200:
            x = random.randint(0, self.BOARD_WIDTH - 1)
            y = random.randint(0, self.BOARD_HEIGHT - 1)
            if (x, y) not in occupied:
                food.append([x, y])
                occupied.add((x, y))
            attempts += 1
        return food

    def get_valid_moves(self, state: dict, player_id: str) -> list:
        snake = state["snakes"].get(player_id)
        if not snake or not snake["alive"]:
            return []

        current_dir = snake["direction"]
        # Can't go in the opposite direction
        return [d for d in DIRECTIONS.keys() if d != OPPOSITE.get(current_dir, "")]

    def apply_move(self, state: dict, player_id: str, move: Any) -> dict:
        """In simultaneous mode, collect moves first, then resolve."""
        move_str = str(move).upper().strip()
        if move_str not in DIRECTIONS:
            raise ValueError(f"Invalid direction: {move}. Must be UP/DOWN/LEFT/RIGHT.")

        snake = state["snakes"].get(player_id)
        if not snake or not snake["alive"]:
            return state

        # Can't reverse direction
        if move_str == OPPOSITE.get(snake["direction"], ""):
            move_str = snake["direction"]  # Keep going forward

        state["pending_moves"][player_id] = move_str

        # Check if all alive players have submitted moves
        alive_players = [pid for pid, s in state["snakes"].items() if s["alive"]]
        all_submitted = all(pid in state["pending_moves"] for pid in alive_players)

        if all_submitted:
            state = self._resolve_turn(state)

        return state

    def _resolve_turn(self, state: dict) -> dict:
        """Resolve all moves simultaneously."""
        new_heads = {}
        ate_food = {}

        for pid, move_dir in state["pending_moves"].items():
            snake = state["snakes"][pid]
            if not snake["alive"]:
                continue

            snake["direction"] = move_dir
            dx, dy = DIRECTIONS[move_dir]
            head_x, head_y = snake["body"][0]
            new_head = (head_x + dx, head_y + dy)
            new_heads[pid] = new_head

            # Check if eating food
            for f in state["food"]:
                if tuple(f) == new_head:
                    ate_food[pid] = f
                    break

        # Check collisions
        deaths = set()

        for pid, new_head in new_heads.items():
            nx, ny = new_head

            # Wall collision
            if nx < 0 or nx >= state["board_width"] or ny < 0 or ny >= state["board_height"]:
                deaths.add(pid)
                continue

            # Self collision (check against body, excluding tail if not eating)
            snake = state["snakes"][pid]
            body_check = snake["body"] if pid in ate_food else snake["body"][:-1]
            if list(new_head) in body_check or new_head in [tuple(b) for b in body_check]:
                deaths.add(pid)
                continue

            # Collision with other snakes' bodies
            for other_pid, other_snake in state["snakes"].items():
                if other_pid == pid or not other_snake["alive"]:
                    continue
                other_body = other_snake["body"] if other_pid in ate_food else other_snake["body"][:-1]
                if new_head in [tuple(b) for b in other_body]:
                    deaths.add(pid)
                    break

        # Head-to-head collision
        head_positions = {}
        for pid, new_head in new_heads.items():
            if pid in deaths:
                continue
            if new_head in head_positions:
                deaths.add(pid)
                deaths.add(head_positions[new_head])
            else:
                head_positions[new_head] = pid

        # Apply moves for surviving snakes
        for pid, new_head in new_heads.items():
            snake = state["snakes"][pid]
            if pid in deaths:
                snake["alive"] = False
                state["eliminated"].append(pid)
                continue

            snake["body"].insert(0, list(new_head))

            if pid in ate_food:
                state["food"].remove(ate_food[pid])
                snake["score"] += 10
            else:
                snake["body"].pop()

        # Replenish food
        alive_count = sum(1 for s in state["snakes"].values() if s["alive"])
        target_food = max(3, alive_count + 1)
        state["food"] = self._generate_food(state["snakes"], state["food"], target_food)

        state["pending_moves"] = {}
        state["turn_count"] += 1
        return state

    def check_game_over(self, state: dict) -> Optional[dict]:
        alive = [(pid, s) for pid, s in state["snakes"].items() if s["alive"]]

        if len(alive) <= 1:
            scores = {}
            if len(alive) == 1:
                winner_id = alive[0][0]
                for pid, s in state["snakes"].items():
                    scores[pid] = 1.0 if pid == winner_id else 0.0
                return {
                    "winner": winner_id,
                    "reason": "last_standing",
                    "scores": scores,
                }
            else:
                # All dead simultaneously
                for pid in state["snakes"]:
                    scores[pid] = 0.5
                return {
                    "winner": None,
                    "reason": "mutual_elimination",
                    "scores": scores,
                }

        if state["turn_count"] >= self.get_max_turns():
            # Highest score wins
            scores = {}
            max_score = max(s["score"] for s in state["snakes"].values())
            winners = [pid for pid, s in state["snakes"].items() if s["score"] == max_score]
            for pid, s in state["snakes"].items():
                scores[pid] = 1.0 if pid in winners else 0.0
            return {
                "winner": winners[0] if len(winners) == 1 else None,
                "reason": "max_turns" if len(winners) > 1 else "highest_score",
                "scores": scores,
            }

        return None

    def get_current_player(self, state: dict) -> str:
        """For simultaneous mode, return the next player who hasn't submitted a move."""
        alive = [pid for pid in state["player_order"]
                 if state["snakes"][pid]["alive"] and pid not in state["pending_moves"]]
        if alive:
            return alive[0]
        return state["player_order"][0]

    def render_state_for_ai(self, state: dict, player_id: str) -> str:
        snake = state["snakes"][player_id]
        head_x, head_y = snake["body"][0]

        # Build a view of the surroundings (simplified grid)
        view_lines = []
        for y in range(state["board_height"]):
            row = ""
            for x in range(state["board_width"]):
                pos = (x, y)
                cell = "."

                # Check food
                if list(pos) in state["food"]:
                    cell = "F"

                # Check snakes
                for pid, s in state["snakes"].items():
                    if not s["alive"]:
                        continue
                    for i, part in enumerate(s["body"]):
                        if tuple(part) == pos:
                            if i == 0:
                                cell = "H" if pid == player_id else "E"
                            else:
                                cell = "s" if pid == player_id else "e"

                row += cell
            view_lines.append(row)

        board_str = "\n".join(view_lines)

        # Nearby threats
        threats = []
        for dx, dy in [(0, -1), (0, 1), (-1, 0), (1, 0)]:
            nx, ny = head_x + dx, head_y + dy
            if nx < 0 or nx >= state["board_width"] or ny < 0 or ny >= state["board_height"]:
                threats.append(f"WALL at ({nx},{ny})")
            else:
                for pid, s in state["snakes"].items():
                    if not s["alive"]:
                        continue
                    if [nx, ny] in s["body"]:
                        name = "YOUR BODY" if pid == player_id else f"ENEMY ({s['name']})"
                        threats.append(f"{name} at ({nx},{ny})")

        # Food positions
        nearest_food = sorted(state["food"], key=lambda f: abs(f[0] - head_x) + abs(f[1] - head_y))[:3]
        food_str = ", ".join([f"({f[0]},{f[1]})" for f in nearest_food])

        valid_moves = self.get_valid_moves(state, player_id)

        prompt = f"""{self.get_game_rules_prompt()}

You are the {snake['emoji']} {snake['name']} Snake.
Your head is at ({head_x}, {head_y}), direction: {snake['direction']}
Your length: {len(snake['body'])}, Score: {snake['score']}
Board: {state['board_width']}x{state['board_height']}

BOARD (H=your head, s=your body, E=enemy head, e=enemy body, F=food, .=empty):
{board_str}

NEARBY THREATS: {', '.join(threats) if threats else 'None'}
NEAREST FOOD: {food_str}
VALID MOVES: {', '.join(valid_moves)}

RESPOND WITH ONLY ONE DIRECTION: UP, DOWN, LEFT, or RIGHT.
Strategy: Eat food to grow, avoid walls and other snakes. Survive!"""

        return prompt

    def parse_ai_move(self, ai_response: str, state: dict, player_id: str) -> Any:
        text = ai_response.strip().upper()
        text = re.sub(r'<THINK>.*?</THINK>', '', text, flags=re.DOTALL).strip()

        for direction in ["UP", "DOWN", "LEFT", "RIGHT"]:
            if direction in text:
                valid = self.get_valid_moves(state, player_id)
                if direction in valid:
                    return direction

        # Fallback: pick any valid move
        valid = self.get_valid_moves(state, player_id)
        if valid:
            return valid[0]

        raise ValueError(f"No valid move can be parsed from: {ai_response[:200]}")

    def render_state_for_ui(self, state: dict) -> dict:
        snakes_ui = []
        for pid, s in state["snakes"].items():
            snakes_ui.append({
                "player_id": pid,
                "name": s["name"],
                "emoji": s["emoji"],
                "color_index": s["color_index"],
                "body": s["body"],
                "direction": s["direction"],
                "alive": s["alive"],
                "score": s["score"],
                "length": len(s["body"]),
            })

        return {
            "game": "snake_arena",
            "board_width": state["board_width"],
            "board_height": state["board_height"],
            "snakes": snakes_ui,
            "food": state["food"],
            "turn_count": state["turn_count"],
            "eliminated": state["eliminated"],
        }

    def get_game_rules_prompt(self) -> str:
        return """You are playing SNAKE ARENA — a multiplayer snake game.
Rules:
- Move your snake: UP, DOWN, LEFT, or RIGHT
- You CANNOT reverse direction (e.g., can't go DOWN if currently going UP)
- Eat food (F) to grow longer and score points
- If you hit a wall, your own body, or another snake — you DIE
- Last snake alive wins!
Think about survival first, food second. Avoid traps!"""

    def get_max_turns(self) -> int:
        return 300
