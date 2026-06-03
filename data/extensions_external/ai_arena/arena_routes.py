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

router = APIRouter(prefix="/api/v1/ai_arena", tags=["AI Arena"])

# Will be set by extension.py
_game_manager: Optional[GameManager] = None


def set_game_manager(gm: GameManager):
    global _game_manager
    _game_manager = gm


def _gm() -> GameManager:
    if _game_manager is None:
        raise HTTPException(500, "GameManager not initialized")
    return _game_manager


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
        model = a.model or getattr(a, "browser_ai_model", "") or ""
        provider = _infer_provider(model)
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
    api_key = ""  # Will be resolved dynamically by AIPlayer

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
