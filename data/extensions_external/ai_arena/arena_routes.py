"""
AI Arena API Routes — FastAPI endpoints for the Arena extension.
"""
import asyncio
import json
import logging
from typing import List, Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, Request
from pydantic import BaseModel

from game_manager import GameManager, GAME_REGISTRY

logger = logging.getLogger("AIArena.Routes")

main_router = APIRouter()
router = APIRouter(prefix="/api/v1/ai_arena", tags=["AI Arena"])
compat_router = APIRouter(prefix="/api/v1/arena", tags=["AI Arena Compatibility"])

# Will be set by extension.py
_game_manager: Optional[GameManager] = None


def set_game_manager(gm: GameManager):
    global _game_manager
    _game_manager = gm


def _gm() -> GameManager:
    if _game_manager is None:
        raise HTTPException(500, "GameManager not initialized")
    return _game_manager


# --- Realtime / Hybrid AI Pathfinder for Snake Arena ---
import time

SNAKE_AGENTS_CACHE = {}  # agent_id -> {target: [x,y], last_llm_call_time: float, pending_llm_call: bool}


def _find_bfs_path(start, target, obstacles, width, height):
    start = tuple(start)
    target = tuple(target)
    if start == target:
        return []
        
    queue = [(start, [])]
    visited = {start}
    
    while queue:
        (cx, cy), path = queue.pop(0)
        
        for move, (dx, dy) in [("UP", (0, -1)), ("DOWN", (0, 1)), ("LEFT", (-1, 0)), ("RIGHT", (1, 0))]:
            nx, ny = cx + dx, cy + dy
            if 0 <= nx < width and 0 <= ny < height and (nx, ny) not in obstacles:
                if (nx, ny) == target:
                    return path + [move]
                if (nx, ny) not in visited:
                    visited.add((nx, ny))
                    queue.append(((nx, ny), path + [move]))
    return []


def _get_safest_move(head, current_dir, obstacles, width, height):
    head = tuple(head)
    opposite = {"UP": "DOWN", "DOWN": "UP", "LEFT": "RIGHT", "RIGHT": "LEFT"}
    valid_moves = []
    
    for move, (dx, dy) in [("UP", (0, -1)), ("DOWN", (0, 1)), ("LEFT", (-1, 0)), ("RIGHT", (1, 0))]:
        if move == opposite.get(current_dir):
            continue
        nx, ny = head[0] + dx, head[1] + dy
        if 0 <= nx < width and 0 <= ny < height and (nx, ny) not in obstacles:
            valid_moves.append((move, (nx, ny)))
            
    if not valid_moves:
        for move in ["UP", "DOWN", "LEFT", "RIGHT"]:
            if move != opposite.get(current_dir):
                return move
                
    best_move = valid_moves[0][0]
    max_free_cells = -1
    
    for move, start_pos in valid_moves:
        q = [start_pos]
        vis = {start_pos}
        cells_count = 0
        while q and cells_count < 30:
            curr = q.pop(0)
            cells_count += 1
            for _, (dx, dy) in [("UP", (0, -1)), ("DOWN", (0, 1)), ("LEFT", (-1, 0)), ("RIGHT", (1, 0))]:
                nx, ny = curr[0] + dx, curr[1] + dy
                if 0 <= nx < width and 0 <= ny < height and (nx, ny) not in obstacles and (nx, ny) not in vis:
                    vis.add((nx, ny))
                    q.append((nx, ny))
        if cells_count > max_free_cells:
            max_free_cells = cells_count
            best_move = move
            
    return best_move


async def _query_snake_llm_async(agent_id: str, prompt: str, game_state: dict, provider: str, model: str, api_key: str):
    try:
        from ai_player import AIPlayer
        player = AIPlayer(
            player_id=agent_id,
            name="LLM-Assistant",
            provider=provider,
            model=model,
            api_key=api_key,
            agent_id=agent_id
        )
        
        raw_response = await asyncio.to_thread(player._call_ai, prompt)
        
        cleaned = raw_response.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()
            
        try:
            res_dict = json.loads(cleaned)
        except Exception:
            import re
            match = re.search(r'(\{[\s\S]*\})', cleaned)
            if match:
                res_dict = json.loads(match.group(1))
            else:
                res_dict = {}
                
        target = res_dict.get("target")
        if target and isinstance(target, list) and len(target) == 2:
            if agent_id in SNAKE_AGENTS_CACHE:
                SNAKE_AGENTS_CACHE[agent_id]["target"] = [int(target[0]), int(target[1])]
                logger.info(f"Background LLM updated target for agent {agent_id} to: {target}")
            
    except Exception as e:
        logger.error(f"Error in background LLM query for agent {agent_id}: {e}")
    finally:
        if agent_id in SNAKE_AGENTS_CACHE:
            SNAKE_AGENTS_CACHE[agent_id]["pending_llm_call"] = False
            SNAKE_AGENTS_CACHE[agent_id]["last_llm_call_time"] = time.time()



# ── Request Models ───────────────────────────────────────────

class PlayerConfig(BaseModel):
    name: str
    provider: str  # ollama | deepseek | gemini | openai | claude | grok | github | 9router | openrouter
    model: str
    emoji: Optional[str] = "🤖"
    api_key: Optional[str] = ""
    agent_id: Optional[str] = ""   # link to an Agent in the agent manager


class CreateMatchRequest(BaseModel):
    game: str
    players: List[PlayerConfig]
    time_control: Optional[str] = None   # bullet | blitz | rapid | classical | unlimited


class CheckModelRequest(BaseModel):
    provider: str
    model: str
    api_key: Optional[str] = ""


# ── Endpoints ────────────────────────────────────────────────

@router.get("/games")
async def list_games():
    """List available games."""
    return {"games": _gm().get_available_games()}


@router.post("/check-model")
async def check_model(req: CheckModelRequest):
    """Verify a specific provider/model can actually answer a prompt.

    Sends a tiny prompt and reports success/failure so the UI can flag
    models that would otherwise silently fall back to random moves.
    """
    import time
    from ai_player import AIPlayer

    player = AIPlayer(
        player_id="probe",
        name="probe",
        provider=req.provider,
        model=req.model,
        api_key=req.api_key or "",
    )

    start = time.time()
    try:
        # Run the blocking HTTP call in a thread so we don't stall the loop.
        raw = await asyncio.to_thread(player._call_ai, "Reply with the single word: OK")
    except Exception as e:
        return {"ok": False, "available": False, "error": str(e)[:300],
                "provider": req.provider, "model": req.model}

    elapsed = round(time.time() - start, 2)
    raw = (raw or "").strip()

    if raw.startswith("[ERROR]") or raw.startswith("[QUOTA_ERROR]"):
        return {
            "ok": False, "available": False,
            "error": raw[:300], "elapsed": elapsed,
            "provider": req.provider, "model": req.model,
        }
    if not raw:
        return {
            "ok": False, "available": False,
            "error": "Empty response from model", "elapsed": elapsed,
            "provider": req.provider, "model": req.model,
        }

    return {
        "ok": True, "available": True,
        "sample": raw[:120], "elapsed": elapsed,
        "provider": req.provider, "model": req.model,
    }


# ── Provider availability ────────────────────────────────────

# Display metadata for every provider the AI player can drive.
_PROVIDER_META = {
    "ollama":   {"label": "Ollama (Local)",  "emoji": "🦙", "kind": "local"},
    "9router":  {"label": "9Router (Local)", "emoji": "🔀", "kind": "local"},
    "deepseek": {"label": "DeepSeek",        "emoji": "🔮", "kind": "cloud"},
    "gemini":   {"label": "Gemini",          "emoji": "✨", "kind": "cloud"},
    "openai":   {"label": "OpenAI",          "emoji": "🧪", "kind": "cloud"},
    "claude":   {"label": "Claude",          "emoji": "🎭", "kind": "cloud"},
    "grok":     {"label": "Grok",            "emoji": "⚡", "kind": "cloud"},
    "openrouter": {"label": "OpenRouter",    "emoji": "🌐", "kind": "cloud"},
    "github":   {"label": "GitHub Models",   "emoji": "🐙", "kind": "cloud"},
}

_DEFAULT_MODELS = {
    "ollama": "",
    "9router": "deepseek-chat",
    "deepseek": "deepseek-chat",
    "gemini": "gemini-2.0-flash",
    "openai": "gpt-4o-mini",
    "claude": "claude-3-5-sonnet-20241022",
    "grok": "grok-3",
    "openrouter": "openai/gpt-4o-mini",
    "github": "gpt-4o-mini",
}


def _probe_local_models(url: str, key: str = None, timeout: float = 2.5):
    """Hit an OpenAI-compatible /models endpoint. Returns (is_up, [model_ids])."""
    import requests
    try:
        headers = {}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code != 200:
            return False, []
        data = resp.json()
        models = []
        if isinstance(data, dict) and isinstance(data.get("data"), list):
            models = [m.get("id") or m.get("name") for m in data["data"] if isinstance(m, dict)]
        models = [m for m in models if m]
        return True, models
    except Exception:
        return False, []


def _get_active_cloud_key(provider: str):
    """Return an active cloud API key for a provider, or None."""
    try:
        from tubecli.extensions.cloud_api.extension import key_manager
        return key_manager.get_active_key(provider)
    except Exception:
        pass
    # Fallback: read cloud_api_keys.json directly
    try:
        import os, json
        from tubecli.config import DATA_DIR
        keys_file = os.path.join(str(DATA_DIR), "cloud_api_keys.json")
        if os.path.exists(keys_file):
            with open(keys_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            for label, info in (data.get(provider) or {}).items():
                if isinstance(info, dict) and info.get("active", True):
                    k = info.get("key") or info.get("api_key")
                    if k:
                        return k
    except Exception:
        pass
    return None


def _ollama_status():
    """Return (is_up, [model_names]) for the local Ollama server."""
    import requests
    try:
        from tubecli.config import OLLAMA_BASE_URL as base
    except Exception:
        base = "http://localhost:11434"
    try:
        resp = requests.get(f"{base}/api/tags", timeout=2.5)
        if resp.status_code != 200:
            return False, []
        models = [m.get("name") for m in resp.json().get("models", []) if m.get("name")]
        return True, models
    except Exception:
        return False, []


@router.get("/providers")
async def list_providers():
    """List ONLY providers that are actually usable right now.

    A provider is included when:
      • local (ollama / 9router): its port is open / server responds, OR
      • cloud: an active API key is configured.
    """
    available = []

    # ── Local: Ollama ──
    ollama_up, ollama_models = _ollama_status()
    if ollama_up:
        meta = _PROVIDER_META["ollama"]
        available.append({
            "value": "ollama",
            "label": f"{meta['emoji']} {meta['label']}",
            "kind": meta["kind"],
            "models": ollama_models,
            "default_model": ollama_models[0] if ollama_models else "",
        })

    # ── Local: 9Router ──
    nine_key = _get_active_cloud_key("9router")
    nine_up, nine_models = _probe_local_models("http://localhost:20128/v1/models", nine_key)
    if nine_up:
        meta = _PROVIDER_META["9router"]
        available.append({
            "value": "9router",
            "label": f"{meta['emoji']} {meta['label']}",
            "kind": meta["kind"],
            "models": nine_models,
            "default_model": nine_models[0] if nine_models else _DEFAULT_MODELS["9router"],
        })

    # ── Cloud providers (need an active key) ──
    try:
        from tubecli.extensions.cloud_api.extension import key_manager
    except Exception:
        key_manager = None

    for prov in ("deepseek", "gemini", "openai", "claude", "grok", "openrouter", "github"):
        key = _get_active_cloud_key(prov)
        if not key:
            continue
        meta = _PROVIDER_META[prov]
        models = []
        if key_manager is not None:
            try:
                models = key_manager.get_models(prov) or []
            except Exception:
                models = []
        available.append({
            "value": prov,
            "label": f"{meta['emoji']} {meta['label']}",
            "kind": meta["kind"],
            "models": models,
            "default_model": (models[0] if models else _DEFAULT_MODELS.get(prov, "")),
        })

    return {"providers": available}


@router.post("/match/create")
async def create_match(req: CreateMatchRequest):
    """Create a new match."""
    try:
        players_config = [p.dict() for p in req.players]
        match = _gm().create_match(req.game, players_config,
                                   time_control=req.time_control)
        return {"status": "created", "match": match.to_dict()}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/time-controls")
async def list_time_controls():
    """List standard chess time controls."""
    return {"time_controls": _gm().get_time_controls()}


@router.get("/agents")
async def list_arena_agents():
    """List agents from the agent manager that can join the Arena.

    Each agent carries its model and any AI Arena chess stats (ELO, W/L/D,
    learned principles).
    """
    try:
        from tubecli.core.agent import agent_manager
    except Exception as e:
        return {"agents": [], "error": str(e)}

    agents = []
    for a in agent_manager.get_all():
        raw_model = a.model or getattr(a, "browser_ai_model", "") or ""
        provider = _infer_provider(raw_model)

        # Clean model name for the UI by stripping any provider prefix
        model = raw_model
        for prov in ("ollama", "9router", "deepseek", "gemini", "openai", "claude", "grok", "openrouter", "github"):
            if raw_model.lower().startswith(f"{prov}/"):
                model = raw_model[len(prov)+1:]
                break
            elif raw_model.lower().startswith(f"{prov}:"):
                model = raw_model[len(prov)+1:]
                break

        agents.append({
            "id": a.id,
            "name": a.name,
            "model": model,
            "provider": provider,
            "avatar_icon": getattr(a, "avatar_icon", "SMART_TOY"),
            "chess_stats": getattr(a, "chess_stats", {}) or {},
        })
    return {"agents": agents}


@router.get("/skills/{provider}/{model}")
async def get_chess_skills(provider: str, model: str):
    """Get the learned chess principles/lessons for a provider|model."""
    gm = _gm()
    if not getattr(gm, "coach", None):
        return {"key": f"{provider}|{model}", "principles": [], "lessons": []}
    key = f"{provider}|{model}"
    return {"key": key, **gm.coach.get_agent_summary(key)}


def _infer_provider(model: str) -> str:
    """Best-effort provider guess from a model id."""
    m = (model or "").lower()
    if not m:
        return "ollama"
    # Check if prefixed with a known provider, e.g. "9router/deepseek-chat" or "gemini/gemini-2.0-flash"
    for prov in ("ollama", "9router", "deepseek", "gemini", "openai", "claude", "grok", "openrouter", "github"):
        if m.startswith(f"{prov}/") or m.startswith(f"{prov}:"):
            return prov
    if m.startswith("9router") or "/" in m and m.split("/")[0] in ("cx", "ag"):
        return "9router"
    if "claude" in m:
        return "claude"
    if "gemini" in m:
        return "gemini"
    if m.startswith("gpt") or m.startswith("o1") or m.startswith("o3"):
        return "openai"
    if "deepseek" in m:
        return "deepseek"
    if "grok" in m:
        return "grok"
    if "/" in m:
        return "openrouter"
    return "ollama"


@router.post("/match/{match_id}/start")
async def start_match(match_id: str):
    """Start a created match."""
    try:
        match = await _gm().start_match(match_id)
        return {"status": "started", "match_id": match.id}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/match/{match_id}/stop")
async def stop_match(match_id: str):
    """Cancel a running match mid-game (no ELO/skill changes are applied)."""
    try:
        match = await _gm().stop_match(match_id)
        return {"status": "aborted", "match_id": match.id}
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/match/{match_id}")
async def get_match(match_id: str):
    """Get match state."""
    match = _gm().get_match(match_id)
    if not match:
        raise HTTPException(404, "Match not found")
    return {"match": match.to_dict()}


@router.get("/matches")
async def list_matches():
    """List all matches."""
    return {"matches": _gm().get_all_matches()}


@router.get("/leaderboard")
async def get_leaderboard():
    """Get ELO leaderboard."""
    return {"leaderboard": _gm().get_leaderboard()}


@router.get("/history")
async def get_history(limit: int = 20):
    """Get match history."""
    return {"matches": _gm().get_match_history(limit)}


class PlayTurnRequest(BaseModel):
    agent_id: str
    game_id: str
    game_state: dict
    prompt: str


@router.post("/play-turn")
@compat_router.post("/play-turn")
async def play_turn(req: PlayTurnRequest):
    """Webhook called by the Central Tournament Hub to get the agent's next move."""
    try:
        from tubecli.core.agent import agent_manager
    except ImportError:
        raise HTTPException(500, "Agent manager not available")

    # 1. Retrieve the agent locally by ID
    agent = agent_manager.get(req.agent_id)
    if not agent:
        raise HTTPException(404, f"Agent {req.agent_id} not found on this server")

    # 2. Get the model and provider of this agent
    model = agent.model or getattr(agent, "browser_ai_model", "") or ""
    if not model:
        raise HTTPException(400, f"Agent {agent.name} has no configured AI model.")

    provider = _infer_provider(model)

    # Strip prefix if it exists to pass clean model to AIPlayer
    for prov in ("ollama", "9router", "deepseek", "gemini", "openai", "claude", "grok", "openrouter", "github"):
        if model.lower().startswith(f"{prov}/"):
            model = model[len(prov)+1:]
            break
        elif model.lower().startswith(f"{prov}:"):
            model = model[len(prov)+1:]
            break

    api_key = ""  # Will be resolved dynamically by AIPlayer

    # ── Check if this is the Snake Game ──
    # If yes, use the Hybrid AI approach to run in realtime (< 5ms response time)
    if req.game_id in ("snake", "snake_arena"):
        if req.agent_id not in SNAKE_AGENTS_CACHE:
            SNAKE_AGENTS_CACHE[req.agent_id] = {
                "target": None,
                "last_llm_call_time": 0,
                "pending_llm_call": False
            }
            
        cache = SNAKE_AGENTS_CACHE[req.agent_id]
        
        # Get board state parameters
        width = req.game_state.get("board_width", 20)
        height = req.game_state.get("board_height", 15)
        food_list = req.game_state.get("food", [])
        
        # Determine player role
        my_role = req.game_state.get("current_turn", "player_1")
        opponent_role = "player_2" if my_role == "player_1" else "player_1"
        
        my_snake = req.game_state.get("snakes", {}).get(my_role)
        opp_snake = req.game_state.get("snakes", {}).get(opponent_role)
        
        if not my_snake or not my_snake.get("alive"):
            raise HTTPException(400, "Snake is dead or not found in state.")
            
        head = my_snake["body"][0]
        current_dir = my_snake["direction"]
        
        # Build obstacle set (body segments)
        obstacles = set()
        for role, s in req.game_state.get("snakes", {}).items():
            if s and s.get("alive"):
                body = s["body"]
                # Keep own tail out of obstacles if snake is longer than 1 to prevent self-collision errors
                if role == my_role and len(body) > 1:
                    body = body[:-1]
                for part in body:
                    obstacles.add(tuple(part))
                    
        # Check target validity
        target = cache["target"]
        if target:
            # Check if target is still in the active food list
            target_tuple = tuple(target)
            if target_tuple not in [tuple(f) for f in food_list]:
                target = None
                cache["target"] = None
                
        # If no target or 5 seconds passed, launch LLM in the background
        if not target or (time.time() - cache["last_llm_call_time"] > 5.0):
            if not cache["pending_llm_call"]:
                cache["pending_llm_call"] = True
                asyncio.create_task(_query_snake_llm_async(
                    req.agent_id, req.prompt, req.game_state, provider, model, api_key
                ))
                
        # Micro pathfinding
        move = None
        if target:
            path = _find_bfs_path(head, target, obstacles, width, height)
            if path:
                move = path[0]
                
        # If target path blocked, head to closest reachable food
        if not move and food_list:
            paths_to_food = []
            for f in food_list:
                p = _find_bfs_path(head, f, obstacles, width, height)
                if p:
                    paths_to_food.append((len(p), p[0]))
            if paths_to_food:
                paths_to_food.sort()
                move = paths_to_food[0][1]
                
        # Ultimate fallback: safest path with maximum space
        if not move:
            move = _get_safest_move(head, current_dir, obstacles, width, height)
            
        return {"move": {"move": move}}

    # 3. Instantiate AIPlayer to communicate with the model
    from ai_player import AIPlayer
    player = AIPlayer(
        player_id=req.agent_id,
        name=agent.name,
        provider=provider,
        model=model,
        api_key=api_key,
        agent_id=req.agent_id
    )

    # 4. Call LLM to get the response
    try:
        # Run blocking HTTP call in a separate thread to keep FastAPI loop non-blocking
        raw_response = await asyncio.to_thread(player._call_ai, req.prompt)
    except Exception as e:
        raise HTTPException(500, f"Error calling AI: {e}")

    if raw_response.startswith("[ERROR]") or raw_response.startswith("[QUOTA_ERROR]"):
        raise HTTPException(502, f"AI Provider Error: {raw_response}")

    # 5. Parse the action (move) based on the game format
    import re
    cleaned = raw_response.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()
    if cleaned.startswith("json"):
        cleaned = cleaned[4:].strip()

    try:
        move_dict = json.loads(cleaned)
    except Exception:
        match = re.search(r'(\{[\s\S]*\})', cleaned)
        if match:
            try:
                move_dict = json.loads(match.group(1))
            except Exception:
                move_dict = {"move": raw_response}
        else:
            move_dict = {"move": raw_response}

    return {"move": move_dict}


# ── WebSocket Live Viewer ────────────────────────────────────

@router.websocket("/match/{match_id}/live")
async def match_live(websocket: WebSocket, match_id: str):
    """WebSocket endpoint for live match updates."""
    await websocket.accept()

    match = _gm().get_match(match_id)
    if not match:
        await websocket.send_json({"type": "error", "message": "Match not found"})
        await websocket.close()
        return

    # Send current state
    await websocket.send_json({
        "type": "init",
        "match": match.to_dict(),
    })

    # Register listener
    queue = asyncio.Queue()

    async def on_event(event_type: str, data: dict):
        await queue.put({"type": event_type, **data})

    match.add_listener(on_event)

    try:
        while True:
            try:
                # Wait for events with timeout
                event = await asyncio.wait_for(queue.get(), timeout=60)
                await websocket.send_json(event)

                if event["type"] in ("match_end", "match_error"):
                    break
            except asyncio.TimeoutError:
                # Send heartbeat
                await websocket.send_json({"type": "heartbeat"})
            except WebSocketDisconnect:
                break
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        match.remove_listener(on_event)
        try:
            await websocket.close()
        except Exception:
            pass


# ── Server-Sent Events (SSE) Proxy for Central Hub ──
from fastapi.responses import StreamingResponse
import httpx

@router.get("/hub/matches/{match_id}/stream")
async def proxy_hub_stream(match_id: str, hub_url: str = "https://tour.zeabur.app"):
    """Server-side proxy for Central Hub SSE streams to avoid cross-origin (CORS) security blocks in browser."""
    async def event_generator():
        headers = {"Accept": "text/event-stream"}
        async with httpx.AsyncClient(timeout=None) as client:
            try:
                async with client.stream(
                    "GET", 
                    f"{hub_url.rstrip('/')}/api/v1/hub/matches/{match_id}/stream", 
                    headers=headers
                ) as response:
                    async for line in response.aiter_lines():
                        if line:
                            yield f"{line}\n"
                        else:
                            yield "\n"
            except Exception as e:
                logger.error(f"Error in SSE proxy stream for match {match_id}: {e}")
                # Yield error event so the client knows it failed
                err_payload = json.dumps({"event": "error", "message": f"Proxy error: {str(e)}"})
                yield f"data: {err_payload}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/hub/matches/{match_id}")
async def proxy_hub_match_details(match_id: str, hub_url: str = "https://tour.zeabur.app"):
    """Proxy match details from Central Hub to local browser to avoid CORS blocks."""
    import httpx
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(f"{hub_url.rstrip('/')}/api/v1/hub/matches/{match_id}")
            if resp.status_code != 200:
                raise HTTPException(resp.status_code, resp.text)
            return resp.json()
        except Exception as e:
            raise HTTPException(500, f"Error calling Hub: {e}")


# ── Cloudflare Tunnel Manager for TryCloudflare ──
import subprocess
import re
import threading
import time
import os
import atexit

class CloudflareTunnelManager:
    def __init__(self):
        self.process = None
        self.url = None
        self.log_thread = None
        self.lock = threading.Lock()

    def start_tunnel(self, port: int = 5295) -> Optional[str]:
        with self.lock:
            if self.process and self.process.poll() is None:
                if self.url:
                    return self.url
                # Wait a bit if it's currently starting
                for _ in range(30):
                    if self.url:
                        return self.url
                    time.sleep(0.5)
                if self.url:
                    return self.url

            self.stop_tunnel()

            cmd = ["cloudflared", "tunnel", "--url", f"http://127.0.0.1:{port}"]
            logger.info(f"Starting cloudflared tunnel: {' '.join(cmd)}")
            
            # Start process
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )

            self.url = None
            url_found_event = threading.Event()

            def read_stderr():
                # cloudflared prints tunnel info to stderr
                pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")
                for line in iter(self.process.stderr.readline, ''):
                    if self.process is None or self.process.poll() is not None:
                        break
                    logger.info(f"[cloudflared] {line.strip()}")
                    match = pattern.search(line)
                    if match:
                        self.url = match.group(0)
                        url_found_event.set()
                        logger.info(f"Cloudflare Tunnel URL found: {self.url}")
                
            self.log_thread = threading.Thread(target=read_stderr, daemon=True)
            self.log_thread.start()

            # Wait for URL to be parsed (up to 15 seconds)
            success = url_found_event.wait(timeout=15.0)
            if not success or not self.url:
                logger.error("Failed to retrieve Cloudflare Tunnel URL within timeout.")
                return None

            return self.url

    def stop_tunnel(self):
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=2.0)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None
            self.url = None
            self.log_thread = None

tunnel_manager = CloudflareTunnelManager()
atexit.register(tunnel_manager.stop_tunnel)

@router.post("/tunnel/start")
async def start_tunnel_api():
    """Start cloudflared tunnel to expose local server and return trycloudflare URL."""
    try:
        url = await asyncio.to_thread(tunnel_manager.start_tunnel, 5295)
        if not url:
            raise HTTPException(500, "Could not start cloudflared tunnel or retrieve URL.")
        return {"url": url}
    except Exception as e:
        raise HTTPException(500, f"Error starting tunnel: {str(e)}")


main_router.include_router(router)
main_router.include_router(compat_router)

