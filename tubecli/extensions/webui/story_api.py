"""
Story Script API — CRUD for 3D story scripts + AI generation.
Scripts stored as JSON files in data/story_scripts/.
"""
import os
import uuid
import json
from datetime import datetime
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Any, Optional

story_router = APIRouter(prefix="/api/v1/story", tags=["story"])

# ── Data directory ──────────────────────────────────────────────────
DATA_DIR = os.path.join(
    os.path.dirname(__file__),
    "..", "..", "..", "data", "story_scripts"
)

def _ensure_dir():
    os.makedirs(DATA_DIR, exist_ok=True)

def _script_path(script_id: str) -> str:
    return os.path.join(DATA_DIR, f"{script_id}.json")

# ── Models ──────────────────────────────────────────────────────────
class StoryScript(BaseModel):
    title: str
    scene_id: Optional[str] = "team_trieudionh"
    actors: list[dict] = []
    waypoints: list[dict] = []
    timeline: list[dict] = []

class AIGenerateRequest(BaseModel):
    prompt: str
    scene_id: Optional[str] = "team_trieudionh"
    actors: Optional[list[dict]] = []
    waypoints: Optional[list[dict]] = []
    provider: Optional[str] = "ollama"
    model: Optional[str] = ""
    api_key: Optional[str] = ""


# ── AI Models listing ───────────────────────────────────────────────

@story_router.get("/ai-models")
async def list_ai_models():
    """Return available AI models: local Ollama + cloud providers with keys from agents."""
    result = {"ollama": [], "cloud": []}

    # 1. Ollama local models
    try:
        import httpx
        resp = httpx.get("http://localhost:11434/api/tags", timeout=5.0)
        if resp.status_code == 200:
            models = resp.json().get("models", [])
            result["ollama"] = [
                {"name": m["name"], "size": m.get("size", 0)}
                for m in models
            ]
    except Exception:
        pass

    # 2. Cloud providers from agent cloud_api_keys
    # Mapping: agent stores 'openai' key, our provider name is 'chatgpt'
    PROVIDER_KEY_MAP = {"chatgpt": "openai", "gemini": "gemini", "claude": "claude", "grok": "grok"}
    KEY_PROVIDER_MAP = {v: k for k, v in PROVIDER_KEY_MAP.items()}  # reverse
    cloud_providers = set()
    try:
        from tubecli.core.agent import agent_manager
        for agent in agent_manager.get_all():
            d = agent.to_dict()
            keys = d.get("cloud_api_keys") or {}
            for key_name, key_val in keys.items():
                if key_val and str(key_val).strip():
                    # Map stored key name to our provider name
                    provider = KEY_PROVIDER_MAP.get(key_name, key_name)
                    cloud_providers.add(provider)
    except Exception:
        pass

    # Known cloud provider configs
    CLOUD_MODELS = {
        "gemini": [
            {"name": "gemini-2.0-flash", "label": "Gemini 2.0 Flash"},
            {"name": "gemini-2.5-flash-preview-05-20", "label": "Gemini 2.5 Flash"},
            {"name": "gemini-1.5-pro", "label": "Gemini 1.5 Pro"},
        ],
        "chatgpt": [
            {"name": "gpt-4o-mini", "label": "GPT-4o Mini"},
            {"name": "gpt-4o", "label": "GPT-4o"},
            {"name": "gpt-4.1-mini", "label": "GPT-4.1-mini"},
        ],
        "claude": [
            {"name": "claude-sonnet-4-20250514", "label": "Claude Sonnet 4"},
            {"name": "claude-3-5-haiku-20241022", "label": "Claude 3.5 Haiku"},
        ],
        "grok": [
            {"name": "grok-3-mini-fast", "label": "Grok 3 Mini Fast"},
            {"name": "grok-3-fast", "label": "Grok 3 Fast"},
        ],
    }
    for provider in cloud_providers:
        p = provider.lower()
        if p in CLOUD_MODELS:
            result["cloud"].append({
                "provider": p,
                "label": p.title(),
                "models": CLOUD_MODELS[p],
            })

    return result


def _get_cloud_api_key(provider: str) -> str:
    """Get API key for a cloud provider from any agent that has it configured."""
    # Map our provider name to the key name stored in agent
    KEY_MAP = {"chatgpt": "openai", "gemini": "gemini", "claude": "claude", "grok": "grok"}
    key_name = KEY_MAP.get(provider, provider)
    try:
        from tubecli.core.agent import agent_manager
        for agent in agent_manager.get_all():
            d = agent.to_dict()
            keys = d.get("cloud_api_keys") or {}
            key = keys.get(key_name, "")
            if key and str(key).strip():
                return str(key).strip()
    except Exception:
        pass
    return ""


# ── Routes ──────────────────────────────────────────────────────────

@story_router.post("/ai-generate")
async def ai_generate_script(req: AIGenerateRequest):
    """Generate a story script from a natural language prompt using AI."""
    from tubecli.core.ai_generator import call_ollama, call_gemini, call_openai_compatible, call_claude, extract_json

    # Build actor context
    actor_names = []
    actor_keys = []
    for a in (req.actors or [])[:6]:
        actor_names.append(a.get("name", a.get("key", "?")))
        actor_keys.append(a.get("key", "actor"))
    if not actor_names:
        actor_names = ["Agent A", "Agent B"]
        actor_keys = ["a", "b"]

    # Build waypoint context
    wp_list = []
    for wp in (req.waypoints or []):
        wp_list.append(f"  - {wp.get('id','?')} ({wp.get('label','')}) tại ({wp.get('x',0)}, {wp.get('z',0)})")
    wp_text = "\n".join(wp_list) if wp_list else "  - board (Whiteboard), sofa (Sofa), door (Cửa)"

    system_prompt = f"""Bạn là một AI viết kịch bản tương tác 3D cho văn phòng ảo.
Hãy sinh ra một story script JSON theo đúng format sau:

{{
  "title": "Tên kịch bản",
  "waypoints": [{{"id":"wp_id","label":"Tên","x":0,"z":0}}],
  "timeline": [
    {{"time": 0, "actor": "actor_key", "action": "walk_to", "target": "wp_id"}},
    {{"time": 3, "actor": "actor_key", "action": "chat", "dialog": "Xin chào!", "duration": 3}},
    {{"time": 7, "actor": "actor_key", "action": "animate", "anim": "think"}},
    {{"time": 10, "actor": "actor_key", "action": "emote", "emoji": "💡"}},
    {{"time": 12, "actor": "actor_key", "action": "return_desk"}}
  ]
}}

Các action hỗ trợ: walk_to, chat, animate, return_desk, sit, stand, emote
Các anim hỗ trợ: read, write_board, shake_hand, cheer, think
target có thể là waypoint id (string) hoặc {{"x": số, "z": số}}

Nhân vật (actor keys): {', '.join(f'{k} ({n})' for k, n in zip(actor_keys, actor_names))}
Waypoints có sẵn trên map:
{wp_text}

CHỈ trả về JSON thuần, không markdown, không giải thích."""

    user_prompt = f"""Kịch bản: {req.prompt}
Tạo kịch bản khoảng 45-90 giây với nhiều tương tác thú vị giữa các nhân vật.
Dùng đúng actor keys: {', '.join(actor_keys)}"""

    full_prompt = f"{system_prompt}\n\n{user_prompt}"

    # Determine provider and model
    provider = (req.provider or "ollama").lower()
    model = req.model or ""
    api_key = req.api_key or ""

    # Get cloud API key if not provided
    if provider != "ollama" and not api_key:
        api_key = _get_cloud_api_key(provider)

    raw = ""
    error_msg = ""

    try:
        if provider == "ollama":
            if not model:
                model = "qwen2.5:7b"
            raw = call_ollama(model, full_prompt)
        elif provider == "gemini":
            if not model:
                model = "gemini-2.0-flash"
            if not api_key:
                return {"ok": False, "error": "Chưa cấu hình Gemini API key. Vào Dashboard → Agent → Cloud API Keys để thêm."}
            raw = call_gemini(model, api_key, full_prompt)
        elif provider == "chatgpt":
            if not model:
                model = "gpt-4o-mini"
            if not api_key:
                return {"ok": False, "error": "Chưa cấu hình OpenAI API key. Vào Dashboard → Agent → Cloud API Keys để thêm."}
            raw = call_openai_compatible(model, api_key, full_prompt)
        elif provider == "grok":
            if not model:
                model = "grok-3-mini-fast"
            if not api_key:
                return {"ok": False, "error": "Chưa cấu hình Grok API key."}
            raw = call_openai_compatible(model, api_key, full_prompt, base_url="https://api.x.ai/v1")
        elif provider == "claude":
            if not model:
                model = "claude-sonnet-4-20250514"
            if not api_key:
                return {"ok": False, "error": "Chưa cấu hình Claude API key."}
            raw = call_claude(model, api_key, full_prompt)
        else:
            return {"ok": False, "error": f"Provider không hỗ trợ: {provider}"}
    except Exception as e:
        error_msg = str(e)

    # Check for errors
    if raw.startswith("[ERROR]") or error_msg:
        err = error_msg or raw
        # Fallback to demo
        demo = _generate_demo_script(req.prompt, req.actors or [
            {"key": actor_keys[0], "name": actor_names[0], "color": "#f43f5e"},
            {"key": actor_keys[1] if len(actor_keys) > 1 else "b",
             "name": actor_names[1] if len(actor_names) > 1 else "Agent B", "color": "#22d3ee"},
        ])
        return {"ok": True, "script": demo, "note": "demo_fallback", "error_detail": err}

    # Extract JSON from response
    json_str = extract_json(raw)
    try:
        script_data = json.loads(json_str)
        return {"ok": True, "script": script_data, "provider": provider, "model": model}
    except Exception:
        # Fallback to demo
        demo = _generate_demo_script(req.prompt, req.actors or [
            {"key": actor_keys[0], "name": actor_names[0], "color": "#f43f5e"},
            {"key": actor_keys[1] if len(actor_keys) > 1 else "b",
             "name": actor_names[1] if len(actor_names) > 1 else "Agent B", "color": "#22d3ee"},
        ])
        return {"ok": True, "script": demo, "note": "demo_fallback", "raw_preview": raw[:300]}


def _generate_demo_script(prompt: str, actors: list) -> dict:
    """Generate a basic demo script when LLM is unavailable."""
    k0 = actors[0]["key"] if actors else "a"
    k1 = actors[1]["key"] if len(actors) > 1 else k0
    n0 = actors[0].get("name", "Agent A") if actors else "Agent A"
    n1 = actors[1].get("name", "Agent B") if len(actors) > 1 else "Agent B"

    return {
        "title": prompt[:60] if prompt else "Câu chuyện văn phòng",
        "scene_id": "team_trieudionh",
        "actors": actors[:4],
        "waypoints": [
            {"id": "board", "label": "Whiteboard", "x": 0.5, "z": -4},
            {"id": "sofa",  "label": "Sofa",       "x": 5.0, "z": -3.5},
            {"id": "door",  "label": "Cửa",         "x": 0.5, "z": 6.0},
        ],
        "timeline": [
            {"time": 0,  "actor": k0, "action": "walk_to",  "target": "board"},
            {"time": 3,  "actor": k1, "action": "walk_to",  "target": {"x": 2, "z": 1}},
            {"time": 6,  "actor": k0, "action": "animate",  "anim": "write_board"},
            {"time": 8,  "actor": k1, "action": "chat",     "dialog": f"Chào {n0}! Hôm nay làm task gì vậy?", "duration": 3},
            {"time": 11, "actor": k0, "action": "chat",     "dialog": "Mình đang cập nhật tính năng mới 🚀", "duration": 3},
            {"time": 15, "actor": k0, "action": "emote",    "emoji": "💡"},
            {"time": 16, "actor": k1, "action": "animate",  "anim": "think"},
            {"time": 20, "actor": k1, "action": "walk_to",  "target": "sofa"},
            {"time": 24, "actor": k1, "action": "sit"},
            {"time": 25, "actor": k0, "action": "walk_to",  "target": "sofa"},
            {"time": 28, "actor": k0, "action": "chat",     "dialog": "Nghỉ giải lao tí nhé 😄", "duration": 3},
            {"time": 31, "actor": k1, "action": "animate",  "anim": "cheer"},
            {"time": 35, "actor": k0, "action": "animate",  "anim": "shake_hand"},
            {"time": 38, "actor": k1, "action": "stand"},
            {"time": 40, "actor": k0, "action": "return_desk"},
            {"time": 40, "actor": k1, "action": "return_desk"},
        ]
    }



TEAMS_FILE = os.path.normpath(os.path.join(
    os.path.dirname(__file__),
    "..", "..", "..", "data", "agent_teams.json"
))

def _load_teams() -> list:
    try:
        with open(TEAMS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("teams", [])
    except Exception:
        return []

# ── Routes ──────────────────────────────────────────────────────────

@story_router.get("/teams")
async def list_teams():
    """Return all agent teams (reads from agent_teams.json)."""
    teams = _load_teams()
    return {"teams": [
        {"id": t["id"], "name": t["name"], "template": t.get("template", "dev_team"),
         "nodes": t.get("nodes", []), "agent_ids": t.get("agent_ids", [])}
        for t in teams
    ]}

@story_router.get("/teams/{team_id}")
async def get_team(team_id: str):
    """Return a single team by ID."""
    for t in _load_teams():
        if t["id"] == team_id:
            return t
    raise HTTPException(status_code=404, detail="Team not found")

@story_router.get("/scripts")
async def list_scripts():
    """List all story scripts."""
    _ensure_dir()
    scripts = []
    for fname in os.listdir(DATA_DIR):
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(DATA_DIR, fname), "r", encoding="utf-8") as f:
                data = json.load(f)
            scripts.append({
                "id": data.get("id"),
                "title": data.get("title", "Untitled"),
                "scene_id": data.get("scene_id"),
                "actor_count": len(data.get("actors", [])),
                "event_count": len(data.get("timeline", [])),
                "updated_at": data.get("updated_at"),
            })
        except Exception:
            continue
    scripts.sort(key=lambda x: x.get("updated_at") or "", reverse=True)
    return {"scripts": scripts}


@story_router.post("/scripts")
async def create_script(script: StoryScript):
    """Create a new story script."""
    _ensure_dir()
    script_id = str(uuid.uuid4())[:8]
    now = datetime.now().isoformat()
    data = {
        "id": script_id,
        "title": script.title,
        "scene_id": script.scene_id,
        "actors": script.actors,
        "waypoints": script.waypoints,
        "timeline": script.timeline,
        "created_at": now,
        "updated_at": now,
    }
    with open(_script_path(script_id), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return {"ok": True, "id": script_id, "script": data}


@story_router.get("/scripts/{script_id}")
async def get_script(script_id: str):
    """Load a story script by ID."""
    path = _script_path(script_id)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Script not found")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {"script": data}


@story_router.put("/scripts/{script_id}")
async def update_script(script_id: str, script: StoryScript):
    """Update an existing story script."""
    path = _script_path(script_id)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Script not found")
    with open(path, "r", encoding="utf-8") as f:
        existing = json.load(f)
    existing.update({
        "title": script.title,
        "scene_id": script.scene_id,
        "actors": script.actors,
        "waypoints": script.waypoints,
        "timeline": script.timeline,
        "updated_at": datetime.now().isoformat(),
    })
    with open(path, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
    return {"ok": True, "script": existing}


@story_router.delete("/scripts/{script_id}")
async def delete_script(script_id: str):
    """Delete a story script."""
    path = _script_path(script_id)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Script not found")
    os.remove(path)
    return {"ok": True}


