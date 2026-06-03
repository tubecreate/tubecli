"""
Game Manager — Match orchestrator cho AI Arena.
Quản lý trận đấu, gọi AI players, broadcast state qua callback.
"""
import asyncio
import json
import logging
import os
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable

from ai_player import AIPlayer
from scoring import ScoringSystem

logger = logging.getLogger("AIArena.GameManager")

# Game registry
GAME_REGISTRY = {}


def register_game(game_cls):
    """Register a game class."""
    instance = game_cls()
    GAME_REGISTRY[instance.name] = instance
    return game_cls


def _load_games():
    """Load all available games."""
    try:
        from engine.chess_game import ChessGame
        register_game(ChessGame)
    except Exception as e:
        logger.warning(f"Failed to load Chess: {e}")

    try:
        from engine.snake_game import SnakeArenaGame
        register_game(SnakeArenaGame)
    except Exception as e:
        logger.warning(f"Failed to load Snake Arena: {e}")


_load_games()


class Match:
    """Represents a single game match."""

    def __init__(self, match_id: str, game_name: str, players: List[AIPlayer],
                 game_instance=None):
        self.id = match_id
        self.game_name = game_name
        # Allow a per-match game instance (e.g. chess with a chosen time control).
        self.game = game_instance or GAME_REGISTRY[game_name]
        self.players = {p.player_id: p for p in players}
        self.player_order = [p.player_id for p in players]
        self.state: Optional[dict] = None
        self.status = "created"  # created | running | completed | error
        self.result: Optional[dict] = None
        self.move_log: List[dict] = []
        self.chat_log: List[dict] = []
        self.created_at = datetime.now().isoformat()
        self.started_at: Optional[str] = None
        self.finished_at: Optional[str] = None
        self.total_tokens: Dict[str, int] = {}
        self.total_think_time: Dict[str, float] = {}   # cumulative seconds per player
        self._listeners: List[Callable] = []
        self.aborted = False   # set when a user cancels the match mid-game

    def add_listener(self, callback: Callable):
        self._listeners.append(callback)

    def remove_listener(self, callback: Callable):
        if callback in self._listeners:
            self._listeners.remove(callback)

    async def _broadcast(self, event_type: str, data: dict):
        for listener in self._listeners:
            try:
                await listener(event_type, data)
            except Exception as e:
                logger.error(f"Broadcast error: {e}")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "game_name": self.game_name,
            "game_display": self.game.display_name,
            "game_icon": self.game.icon,
            "status": self.status,
            "players": {pid: p.to_dict() for pid, p in self.players.items()},
            "player_order": self.player_order,
            "state_ui": self.game.render_state_for_ui(self.state) if self.state else None,
            "result": self.result,
            "move_count": len(self.move_log),
            "chat_log": self.chat_log[-20:],
            "total_tokens": self.total_tokens,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }

    def to_summary(self) -> dict:
        return {
            "id": self.id,
            "game_name": self.game_name,
            "game_display": self.game.display_name,
            "game_icon": self.game.icon,
            "status": self.status,
            "players": [
                {"id": pid, "name": p.name, "emoji": p.emoji, "model": p.model, "provider": p.provider}
                for pid, p in self.players.items()
            ],
            "result": self.result,
            "move_count": len(self.move_log),
            "total_tokens": self.total_tokens,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }


class GameManager:
    """Central match orchestrator."""

    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        arena_dir = os.path.join(data_dir, "ai_arena")
        os.makedirs(arena_dir, exist_ok=True)
        self.scoring = ScoringSystem(arena_dir)
        # Chess skill-learning coach (per-agent principles persisted to disk).
        try:
            from chess_coach import ChessCoach
            self.coach = ChessCoach(arena_dir)
        except Exception as e:
            logger.warning(f"ChessCoach unavailable: {e}")
            self.coach = None
        self._matches: Dict[str, Match] = {}
        self._running_tasks: Dict[str, asyncio.Task] = {}

    def get_available_games(self) -> list:
        return [
            {
                "name": g.name,
                "display_name": g.display_name,
                "icon": g.icon,
                "min_players": g.min_players,
                "max_players": g.max_players,
                "description": g.description,
            }
            for g in GAME_REGISTRY.values()
        ]

    def get_time_controls(self) -> list:
        """List the standard chess time controls."""
        try:
            from engine.chess_game import ChessGame
            return [
                {"id": tid, **tinfo}
                for tid, tinfo in ChessGame.TIME_CONTROLS.items()
            ]
        except Exception:
            return []

    def create_match(self, game_name: str, players_config: List[dict],
                     time_control: str = None) -> Match:
        """Create a new match.

        players_config: [{name, provider, model, emoji?, agent_id?}, ...]
        time_control: chess time control id (bullet/blitz/rapid/classical/unlimited)
        """
        if game_name not in GAME_REGISTRY:
            raise ValueError(f"Unknown game: {game_name}. Available: {list(GAME_REGISTRY.keys())}")

        game = GAME_REGISTRY[game_name]
        if len(players_config) < game.min_players:
            raise ValueError(f"{game.display_name} requires at least {game.min_players} players")
        if len(players_config) > game.max_players:
            raise ValueError(f"{game.display_name} supports at most {game.max_players} players")

        # For chess, build a fresh instance with the chosen time control.
        game_instance = game
        if game_name == "chess":
            try:
                from engine.chess_game import ChessGame
                game_instance = ChessGame(time_control=time_control)
            except Exception as e:
                logger.warning(f"Falling back to default chess game: {e}")
                game_instance = game

        match_id = uuid.uuid4().hex[:8]

        players = []
        for i, pc in enumerate(players_config):
            player_id = f"p{i}_{pc['provider']}_{pc['model'].replace('/', '_').replace(':', '_')}"
            # Pull learned chess principles for this provider|model if any.
            skill_block = ""
            if game_name == "chess" and self.coach:
                try:
                    skill_block = self.coach.get_skill_block(f"{pc['provider']}|{pc['model']}")
                except Exception:
                    skill_block = ""
            player = AIPlayer(
                player_id=player_id,
                name=pc.get("name", f"Player {i + 1}"),
                provider=pc["provider"],
                model=pc["model"],
                api_key=pc.get("api_key", ""),
                emoji=pc.get("emoji", ["🤖", "🧠", "🦾", "🎯", "💫", "⚡"][i % 6]),
                agent_id=pc.get("agent_id", ""),
                skill_block=skill_block,
            )
            players.append(player)

        match = Match(match_id, game_name, players, game_instance=game_instance)
        self._matches[match_id] = match
        return match

    async def start_match(self, match_id: str) -> Match:
        """Start a match asynchronously."""
        match = self._matches.get(match_id)
        if not match:
            raise ValueError(f"Match {match_id} not found")
        if match.status != "created":
            raise ValueError(f"Match is already {match.status}")

        # Initialize game state
        match.state = match.game.get_initial_state(match.player_order)
        match.status = "running"
        match.started_at = datetime.now().isoformat()

        # Start game loop in background
        task = asyncio.create_task(self._run_match(match))
        self._running_tasks[match_id] = task
        return match

    async def stop_match(self, match_id: str) -> Match:
        """Cancel a running match mid-game (no ELO/skill changes applied)."""
        match = self._matches.get(match_id)
        if not match:
            raise ValueError(f"Match {match_id} not found")
        if match.status not in ("running", "created"):
            return match  # already finished

        # Signal the loop to stop at the next turn boundary.
        match.aborted = True

        # If the loop is blocked inside a slow AI call, cancel the task so the
        # match terminates promptly instead of waiting for the API to return.
        task = self._running_tasks.get(match_id)
        if task and not task.done():
            # Give the cooperative flag a brief chance first.
            await asyncio.sleep(0.05)
            if not task.done():
                task.cancel()

        if match.status == "running" or match.status == "created":
            match.status = "completed"
            if not match.result:
                match.result = {
                    "winner": None,
                    "reason": "aborted",
                    "scores": {pid: 0.0 for pid in match.player_order},
                    "no_rating": True,
                }
            match.finished_at = datetime.now().isoformat()
            await match._broadcast("match_aborted", {
                "reason": "Trận đấu đã bị hủy.",
                "move_count": len(match.move_log),
                "total_tokens": match.total_tokens,
            })
        return match

    async def _run_match(self, match: Match):
        """Main game loop."""
        game = match.game
        state = match.state

        try:
            await match._broadcast("match_start", {
                "match_id": match.id,
                "game": game.display_name,
                "players": {pid: p.to_dict() for pid, p in match.players.items()},
            })

            turn = 0
            while True:
                # User cancelled the match mid-game.
                if match.aborted:
                    match.status = "completed"
                    match.result = {
                        "winner": None,
                        "reason": "aborted",
                        "scores": {pid: 0.0 for pid in match.player_order},
                        "no_rating": True,
                    }
                    match.finished_at = datetime.now().isoformat()
                    await match._broadcast("match_aborted", {
                        "reason": "Trận đấu đã bị hủy.",
                        "move_count": len(match.move_log),
                        "total_tokens": match.total_tokens,
                    })
                    return

                # Check game over
                result = game.check_game_over(state)
                if result:
                    match.result = result
                    match.status = "completed"
                    match.finished_at = datetime.now().isoformat()
                    break

                # For simultaneous games (Snake), get all players' moves
                if getattr(state, 'get', lambda k, d=None: d)('simultaneous', False) or \
                   (isinstance(state, dict) and state.get('simultaneous', False)):
                    alive_players = [
                        pid for pid in match.player_order
                        if state.get("snakes", {}).get(pid, {}).get("alive", False)
                    ]
                    for pid in alive_players:
                        player = match.players[pid]
                        move_result = player.decide_move(game, state)

                        # Track tokens
                        tokens = move_result.get("tokens_used", 0)
                        match.total_tokens[pid] = match.total_tokens.get(pid, 0) + tokens

                        if move_result.get("move") is None:
                            # Forfeit
                            state["snakes"][pid]["alive"] = False
                            state["eliminated"].append(pid)
                            await match._broadcast("player_forfeit", {
                                "player_id": pid,
                                "player_name": player.name,
                                "error": move_result.get("error", ""),
                            })
                            continue

                        state = game.apply_move(state, pid, move_result["move"])

                        # Log
                        match.move_log.append({
                            "turn": turn,
                            "player_id": pid,
                            "player_name": player.name,
                            "move": str(move_result["move"]),
                            "tokens": tokens,
                            "thinking_time": move_result.get("thinking_time", 0),
                        })

                        # Chat
                        chat_msg = move_result.get("chat_message", "")
                        if chat_msg:
                            chat_entry = {
                                "player_id": pid,
                                "player_name": player.name,
                                "emoji": player.emoji,
                                "message": chat_msg,
                                "turn": turn,
                            }
                            match.chat_log.append(chat_entry)

                        # Broadcast each move
                        await match._broadcast("move", {
                            "turn": turn,
                            "player_id": pid,
                            "player_name": player.name,
                            "player_emoji": player.emoji,
                            "move": str(move_result["move"]),
                            "tokens_this_turn": tokens,
                            "total_tokens": match.total_tokens[pid],
                            "thinking_time": move_result.get("thinking_time", 0),
                            "chat_message": chat_msg,
                            "state_ui": game.render_state_for_ui(state),
                        })

                    turn += 1
                    # Small delay for UI
                    await asyncio.sleep(0.3)

                else:
                    # Turn-based games (Chess)
                    current_pid = game.get_current_player(state)
                    player = match.players[current_pid]

                    await match._broadcast("turn_start", {
                        "turn": turn,
                        "player_id": current_pid,
                        "player_name": player.name,
                        "player_emoji": player.emoji,
                    })

                    move_result = player.decide_move(game, state)
                    print(f"  ♟️ {player.name} → {move_result.get('move', 'FAIL')} "
                          f"({move_result.get('thinking_time', 0)}s, "
                          f"tokens: {move_result.get('tokens_used', 0)})")

                    tokens = move_result.get("tokens_used", 0)
                    match.total_tokens[current_pid] = match.total_tokens.get(current_pid, 0) + tokens

                    # ── Chess clock: deduct thinking time; detect flag fall ──
                    thinking_time = move_result.get("thinking_time", 0) or 0
                    if hasattr(game, "consume_time"):
                        flagged = game.consume_time(state, current_pid, thinking_time)
                        if flagged:
                            print(f"\n⏰ [AI Arena] {player.name} FLAGGED (out of time)!")
                            match.result = game.check_game_over(state) or {
                                "winner": next((pid for pid in match.player_order
                                                if pid != current_pid), None),
                                "reason": "timeout",
                                "scores": {pid: (1.0 if pid != current_pid else 0.0)
                                           for pid in match.player_order},
                            }
                            match.status = "completed"
                            match.finished_at = datetime.now().isoformat()
                            await match._broadcast("move", {
                                "turn": turn,
                                "player_id": current_pid,
                                "player_name": player.name,
                                "player_emoji": player.emoji,
                                "move": "⏰ timeout",
                                "tokens_this_turn": tokens,
                                "total_tokens": match.total_tokens[current_pid],
                                "thinking_time": thinking_time,
                                "chat_message": "⏰ Hết giờ!",
                                "state_ui": game.render_state_for_ui(state),
                            })
                            break

                    if move_result.get("move") is None:
                        # Forfeit — only happens if random fallback also failed
                        print(f"\n❌ [AI Arena] {player.name} ({player.provider}/{player.model}) FORFEITED!")
                        print(f"   Error: {move_result.get('error', 'unknown')}")
                        other_players = [pid for pid in match.player_order if pid != current_pid]
                        match.result = {
                            "winner": other_players[0] if other_players else None,
                            "reason": "forfeit",
                            "scores": {pid: (1.0 if pid != current_pid else 0.0) for pid in match.player_order},
                        }
                        match.status = "completed"
                        match.finished_at = datetime.now().isoformat()
                        await match._broadcast("player_forfeit", {
                            "player_id": current_pid,
                            "player_name": player.name,
                            "error": move_result.get("error", ""),
                        })
                        break

                    # Log random fallback info
                    if move_result.get("is_random"):
                        print(f"\n🎲 [AI Arena] {player.name} used RANDOM move: {move_result['move']}")
                        chat_entry = {
                            "player_id": current_pid,
                            "player_name": player.name,
                            "emoji": player.emoji,
                            "message": "🎲 AI bối rối, đi bừa!",
                            "turn": turn,
                        }
                        match.chat_log.append(chat_entry)

                    # Apply move
                    state = game.apply_move(state, current_pid, move_result["move"])
                    match.state = state

                    match.move_log.append({
                        "turn": turn,
                        "player_id": current_pid,
                        "player_name": player.name,
                        "move": str(move_result["move"]),
                        "tokens": tokens,
                        "thinking_time": move_result.get("thinking_time", 0),
                    })

                    # Chat
                    chat_msg = move_result.get("chat_message", "")
                    if chat_msg:
                        match.chat_log.append({
                            "player_id": current_pid,
                            "player_name": player.name,
                            "emoji": player.emoji,
                            "message": chat_msg,
                            "turn": turn,
                        })

                    # Accumulate total thinking time per player.
                    _tt = move_result.get("thinking_time", 0) or 0
                    match.total_think_time[current_pid] = round(
                        match.total_think_time.get(current_pid, 0) + _tt, 2)

                    await match._broadcast("move", {
                        "turn": turn,
                        "player_id": current_pid,
                        "player_name": player.name,
                        "player_emoji": player.emoji,
                        "move": str(move_result["move"]),
                        "tokens_this_turn": tokens,
                        "total_tokens": match.total_tokens[current_pid],
                        "thinking_time": move_result.get("thinking_time", 0),
                        "total_thinking_time": match.total_think_time[current_pid],
                        "chat_message": chat_msg,
                        "state_ui": game.render_state_for_ui(state),
                    })

                    turn += 1
                    await asyncio.sleep(0.2)

            # Match finished — update scores
            # Skip ELO / skill updates for aborted (unrated) matches.
            if match.result and not match.result.get("no_rating") \
               and match.result.get("reason") != "aborted":
                player_infos = []
                for pid, player in match.players.items():
                    key = player.agent_id if getattr(player, "agent_id", "") else f"{player.provider}|{player.model}"
                    player_infos.append({
                        "key": key,
                        "name": player.name,
                        "provider": player.provider,
                        "model": player.model,
                        "emoji": player.emoji,
                        "agent_id": getattr(player, "agent_id", ""),
                    })

                # Remap result scores to use keys
                remapped_scores = {}
                for pid, score in match.result.get("scores", {}).items():
                    player = match.players.get(pid)
                    if player:
                        key = player.agent_id if getattr(player, "agent_id", "") else f"{player.provider}|{player.model}"
                        remapped_scores[key] = score

                remapped_result = {**match.result, "scores": remapped_scores}
                if match.result.get("winner"):
                    winner_player = match.players.get(match.result["winner"])
                    if winner_player:
                        winner_key = winner_player.agent_id if getattr(winner_player, "agent_id", "") else f"{winner_player.provider}|{winner_player.model}"
                        remapped_result["winner_key"] = winner_key

                self.scoring.update_ratings(player_infos, remapped_result)

                # Track tokens
                for pid, player in match.players.items():
                    key = player.agent_id if getattr(player, "agent_id", "") else f"{player.provider}|{player.model}"
                    self.scoring.update_tokens(key, player.total_tokens_used)

                # Save match history
                self.scoring.save_match({
                    "id": match.id,
                    "game": match.game_name,
                    "players": {pid: p.to_dict() for pid, p in match.players.items()},
                    "result": match.result,
                    "move_count": len(match.move_log),
                    "total_tokens": match.total_tokens,
                    "created_at": match.created_at,
                    "finished_at": match.finished_at,
                })

                # ── Chess skill learning + agent sync (non-fatal) ──
                if match.game_name == "chess":
                    try:
                        await self._post_chess_learning(match)
                    except Exception as learn_err:
                        logger.warning(f"Chess learning skipped: {learn_err}")

                # Sync ELO/stats back to linked agents in the agent manager.
                try:
                    self._sync_agent_ratings(match)
                except Exception as sync_err:
                    logger.warning(f"Agent rating sync skipped: {sync_err}")

                await match._broadcast("match_end", {
                    "result": match.result,
                    "total_tokens": match.total_tokens,
                    "move_count": len(match.move_log),
                })

        except asyncio.CancelledError:
            # Match was cancelled via stop_match — treat as a clean abort.
            logger.info(f"Match {match.id} cancelled by user.")
            match.status = "completed"
            if not match.result:
                match.result = {
                    "winner": None,
                    "reason": "aborted",
                    "scores": {pid: 0.0 for pid in match.player_order},
                    "no_rating": True,
                }
                match.finished_at = datetime.now().isoformat()
            try:
                await match._broadcast("match_aborted", {
                    "reason": "Trận đấu đã bị hủy.",
                    "move_count": len(match.move_log),
                    "total_tokens": match.total_tokens,
                })
            except Exception:
                pass
            raise
        except Exception as e:
            logger.error(f"Match {match.id} error: {e}", exc_info=True)
            match.status = "error"
            match.result = {"error": str(e)}
            await match._broadcast("match_error", {"error": str(e)})
        finally:
            self._running_tasks.pop(match.id, None)

    def get_match(self, match_id: str) -> Optional[Match]:
        return self._matches.get(match_id)

    def get_all_matches(self) -> List[dict]:
        return [m.to_summary() for m in self._matches.values()]

    def get_leaderboard(self) -> list:
        return self.scoring.get_leaderboard()

    def get_match_history(self, limit: int = 20) -> list:
        return self.scoring.get_match_history(limit)

    # ── Skill learning & agent integration ───────────────────────

    async def _post_chess_learning(self, match: "Match"):
        """After a chess game, each player reflects and updates its principles."""
        if not self.coach:
            return

        result = match.result or {}
        winner = result.get("winner")
        reason = result.get("reason", "")
        move_history = match.state.get("move_history", []) if match.state else []

        # Build opponent name lookup.
        names = {pid: p.name for pid, p in match.players.items()}

        learned_events = []
        for pid, player in match.players.items():
            if winner is None:
                outcome = "draw"
            elif pid == winner:
                outcome = "win"
            else:
                outcome = "loss"
            opponent = next((names[o] for o in match.players if o != pid), "opponent")

            # Run the (blocking) reflection call off the event loop.
            res = await asyncio.to_thread(
                self.coach.learn_from_game,
                player, outcome, move_history, opponent, reason,
            )
            if res:
                learned_events.append({
                    "player_id": pid,
                    "player_name": player.name,
                    "emoji": player.emoji,
                    "outcome": outcome,
                    "principles": res["lesson"].get("summary", ""),
                    "new_principles": res["principles"][-2:],
                })

        if learned_events:
            await match._broadcast("skill_learned", {"events": learned_events})

    def _sync_agent_ratings(self, match: "Match"):
        """Mirror Arena ELO/W-L-D into linked agents' chess_stats field."""
        linked = [(pid, p) for pid, p in match.players.items() if getattr(p, "agent_id", "")]
        if not linked:
            return
        try:
            from tubecli.core.agent import agent_manager
        except Exception:
            return

        for pid, player in linked:
            leaderboard_key = player.agent_id
            entry = self.scoring._leaderboard["players"].get(leaderboard_key, {})
            model_key = f"{player.provider}|{player.model}"
            chess_stats = {
                "elo": entry.get("elo", 1500),
                "wins": entry.get("wins", 0),
                "losses": entry.get("losses", 0),
                "draws": entry.get("draws", 0),
                "games": entry.get("games", 0),
                "principles": self.coach.get_principles(model_key) if self.coach else [],
                "last_match": match.id,
                "updated_at": datetime.now().isoformat(),
            }
            try:
                agent = agent_manager.get(player.agent_id)
                if agent:
                    agent_manager.update(player.agent_id, chess_stats=chess_stats)
            except Exception as e:
                logger.warning(f"Could not update agent {player.agent_id}: {e}")
