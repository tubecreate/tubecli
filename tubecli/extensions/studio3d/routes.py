"""
3D Studio Extension — API routes for room/scene editing.
Adds /api/v1/studio3d/* endpoints for scene management.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict
import json
import os
from tubecli.config import DATA_DIR

router = APIRouter(prefix="/api/v1/studio3d", tags=["studio3d"])

SCENES_FILE = os.path.join(DATA_DIR, "studio3d_scenes.json")

# Built-in asset catalog
ASSET_CATALOG = [
    # ── Furniture ──
    {"id": "desk_modern", "name": "Bàn hiện đại", "category": "furniture", "emoji": "🖥️",
     "mesh": "box", "size": [1.6, 0.07, 0.9], "color": "#f0ebe4", "yOffset": 0.72},
    {"id": "desk_wood", "name": "Bàn gỗ cổ điển", "category": "furniture", "emoji": "📚",
     "mesh": "box", "size": [1.4, 0.06, 0.8], "color": "#5c3a1e", "yOffset": 0.45},
    {"id": "chair_office", "name": "Ghế xoay", "category": "furniture", "emoji": "🪑",
     "mesh": "box", "size": [0.5, 0.06, 0.5], "color": "#2d3250", "yOffset": 0.48},
    {"id": "sofa", "name": "Sofa", "category": "furniture", "emoji": "🛋️",
     "mesh": "box", "size": [1.8, 0.5, 0.8], "color": "#3d4a8a", "yOffset": 0.25},
    {"id": "bookshelf", "name": "Tủ sách", "category": "furniture", "emoji": "📕",
     "mesh": "box", "size": [1.2, 2.0, 0.4], "color": "#6b4226", "yOffset": 1.0},
    {"id": "table_round", "name": "Bàn tròn", "category": "furniture", "emoji": "🍽️",
     "mesh": "cylinder", "size": [0.6, 0.72, 0.6], "color": "#d4c8b0", "yOffset": 0.36},
    {"id": "cabinet", "name": "Tủ hồ sơ", "category": "furniture", "emoji": "🗄️",
     "mesh": "box", "size": [0.6, 1.2, 0.5], "color": "#8a8a8a", "yOffset": 0.6},
    # ── Decorations ──
    {"id": "plant_pot", "name": "Chậu cây", "category": "decoration", "emoji": "🌿",
     "mesh": "cylinder", "size": [0.25, 0.8, 0.25], "color": "#22c55e", "yOffset": 0.4},
    {"id": "plant_tall", "name": "Cây cao", "category": "decoration", "emoji": "🌳",
     "mesh": "cylinder", "size": [0.2, 1.8, 0.2], "color": "#228B22", "yOffset": 0.9},
    {"id": "plant_cactus", "name": "Xương rồng", "category": "decoration", "emoji": "🌵",
     "mesh": "cylinder", "size": [0.12, 0.6, 0.12], "color": "#2e8b57", "yOffset": 0.3},
    {"id": "aquarium_small", "name": "Bể cá nhỏ", "category": "decoration", "emoji": "🐠",
     "mesh": "sphere", "size": [0.18, 0.3, 0.18], "color": "#87ceeb", "yOffset": 0.15},
    {"id": "aquarium_large", "name": "Bể cá lớn", "category": "decoration", "emoji": "🐟",
     "mesh": "box", "size": [1.2, 0.55, 0.45], "color": "#1c7ed6", "yOffset": 0.6},
    {"id": "terrarium", "name": "Tiểu cảnh", "category": "decoration", "emoji": "🏞️",
     "mesh": "box", "size": [0.8, 0.1, 0.5], "color": "#2d5a27", "yOffset": 0.05},
    {"id": "rock_garden", "name": "Hòn non bộ", "category": "decoration", "emoji": "⛰️",
     "mesh": "box", "size": [1.4, 1.0, 0.9], "color": "#5a5a5a", "yOffset": 0.5},
    {"id": "lantern", "name": "Đèn lồng", "category": "decoration", "emoji": "🏮",
     "mesh": "sphere", "size": [0.2, 0.2, 0.2], "color": "#cc3333", "yOffset": 2.5, "emissive": True},
    {"id": "whiteboard", "name": "Bảng trắng", "category": "decoration", "emoji": "📋",
     "mesh": "box", "size": [1.5, 1.0, 0.05], "color": "#f0f0f0", "yOffset": 1.5},
    {"id": "monitor", "name": "Màn hình", "category": "decoration", "emoji": "🖥️",
     "mesh": "box", "size": [0.7, 0.5, 0.04], "color": "#1a1a2e", "yOffset": 1.05},
    {"id": "pillar_red", "name": "Cột đỏ", "category": "decoration", "emoji": "🔴",
     "mesh": "cylinder", "size": [0.18, 3.5, 0.18], "color": "#c9302c", "yOffset": 1.75},
    # ── Structures ──
    {"id": "wall_segment", "name": "Tường", "category": "structure", "emoji": "🧱",
     "mesh": "box", "size": [2.0, 3.5, 0.15], "color": "#c8bca8", "yOffset": 1.75},
    {"id": "wall_partition_solid", "name": "Vách ngăn 2m", "category": "structure", "emoji": "🚧",
     "mesh": "box", "size": [2.0, 1.2, 0.15], "color": "#a0a5b5", "yOffset": 0.6},
    {"id": "wall_partition_glass", "name": "Vách kính 2m", "category": "structure", "emoji": "🪟",
     "mesh": "box", "size": [2.0, 1.2, 0.15], "color": "#a0a5b5", "yOffset": 0.6},
    {"id": "wall_partition_1m", "name": "Vách ngăn 1m", "category": "structure", "emoji": "🚧",
     "mesh": "box", "size": [1.0, 1.2, 0.15], "color": "#a0a5b5", "yOffset": 0.6},
    {"id": "wall_partition_glass_1m", "name": "Vách kính 1m", "category": "structure", "emoji": "🪟",
     "mesh": "box", "size": [1.0, 1.2, 0.15], "color": "#a0a5b5", "yOffset": 0.6},
    {"id": "floor_tile", "name": "Ô sàn", "category": "structure", "emoji": "⬜",
     "mesh": "box", "size": [2.0, 0.1, 2.0], "color": "#d4c8b0", "yOffset": 0.05},
    {"id": "door_frame", "name": "Cửa ra vào", "category": "structure", "emoji": "🚪",
     "mesh": "box", "size": [1.0, 2.5, 0.15], "color": "#5c3a1e", "yOffset": 1.25},
    # ── New Furniture ──
    {"id": "chair_classic", "name": "Ghế cổ điển", "category": "furniture", "emoji": "🪑",
     "mesh": "box", "size": [0.44, 0.04, 0.44], "color": "#5c3a1e", "yOffset": 0.45},
    {"id": "chair_dining", "name": "Ghế bàn ăn", "category": "furniture", "emoji": "💺",
     "mesh": "box", "size": [0.44, 0.06, 0.42], "color": "#8B4513", "yOffset": 0.46},
    {"id": "fridge", "name": "Tủ lạnh", "category": "furniture", "emoji": "🧊",
     "mesh": "box", "size": [0.7, 1.8, 0.65], "color": "#e8e8e8", "yOffset": 0.9},
    {"id": "washing_machine", "name": "Máy giặt", "category": "furniture", "emoji": "🫧",
     "mesh": "box", "size": [0.6, 0.85, 0.6], "color": "#e0e0e0", "yOffset": 0.425},
    {"id": "bar_counter", "name": "Bar nước", "category": "furniture", "emoji": "🍸",
     "mesh": "box", "size": [2.4, 0.06, 0.6], "color": "#3a2518", "yOffset": 1.05},
    {"id": "coffee_machine", "name": "Máy pha cà phê", "category": "decoration", "emoji": "☕",
     "mesh": "box", "size": [0.35, 0.45, 0.3], "color": "#2c2c2c", "yOffset": 0.225},
    {"id": "pool_table", "name": "Bàn bida", "category": "furniture", "emoji": "🎱",
     "mesh": "box", "size": [2.4, 0.04, 1.3], "color": "#006400", "yOffset": 0.82},
    # ── Composite Workspace ──
    {"id": "workstation", "name": "Bàn làm việc (trọn bộ)", "category": "furniture", "emoji": "💼",
     "mesh": "box", "size": [1.6, 1.3, 1.8], "color": "#f0ebe4", "yOffset": 0},
]


def _load_scenes() -> dict:
    if os.path.exists(SCENES_FILE):
        with open(SCENES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_scenes(data: dict):
    os.makedirs(os.path.dirname(SCENES_FILE), exist_ok=True)
    with open(SCENES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


class PlacedAsset(BaseModel):
    asset_id: str
    x: float = 0
    z: float = 0
    rotation: float = 0  # Y-axis rotation in radians
    scale: float = 1.0
    custom_color: Optional[str] = None


class SaveSceneRequest(BaseModel):
    team_id: str
    assets: List[dict] = []
    room_width: float = 16
    room_depth: float = 12
    floor_color: Optional[str] = None
    wall_color: Optional[str] = None


@router.get("/assets")
async def get_asset_catalog():
    """Return the built-in asset catalog."""
    return {"assets": ASSET_CATALOG}


@router.get("/scenes/{team_id}")
async def get_scene(team_id: str):
    """Get the saved scene for a team."""
    scenes = _load_scenes()
    scene = scenes.get(team_id, {
        "team_id": team_id,
        "assets": [],
        "room_width": 16,
        "room_depth": 12,
    })
    return {"scene": scene}


@router.put("/scenes/{team_id}")
async def save_scene(team_id: str, req: SaveSceneRequest):
    """Save a scene layout for a team."""
    scenes = _load_scenes()
    scenes[team_id] = {
        "team_id": team_id,
        "assets": req.assets,
        "room_width": req.room_width,
        "room_depth": req.room_depth,
        "floor_color": req.floor_color,
        "wall_color": req.wall_color,
    }
    _save_scenes(scenes)
    return {"ok": True, "scene": scenes[team_id]}


@router.delete("/scenes/{team_id}")
async def delete_scene(team_id: str):
    """Delete a saved scene."""
    scenes = _load_scenes()
    if team_id in scenes:
        del scenes[team_id]
        _save_scenes(scenes)
    return {"ok": True}


class GenerateLayoutRequest(BaseModel):
    team_id: str
    prompt: str
    room_width: float
    room_depth: float
    provider: str
    model: str


@router.post("/generate")
async def generate_layout(req: GenerateLayoutRequest):
    """Generate a 3D studio layout using AI."""
    from tubecli.extensions.multi_agents.extension import orchestrator
    from tubecli.core.agent import agent_manager
    from tubecli.extensions.studio3d.ai_builder import generate_studio_json

    team_obj = orchestrator.get_team(req.team_id)
    if not team_obj:
        raise HTTPException(404, "Team not found")

    team = team_obj.to_dict()

    # Get team agents
    nodes = team.get("nodes", [])
    agent_ids = [n.get("agent_id") for n in nodes if n.get("agent_id")]
    
    all_agents = agent_manager.get_all()
    team_agents = [ag.to_dict() for ag in all_agents if ag.id in agent_ids]

    try:
        data = generate_studio_json(
            prompt=req.prompt,
            team_agents=team_agents,
            room_width=req.room_width,
            room_depth=req.room_depth,
            provider=req.provider,
            model=req.model
        )
        return {"ok": True, "result": data}
    except Exception as e:
        raise HTTPException(500, str(e))


class QuickTeamRequest(BaseModel):
    description: str
    provider: str
    model: str


@router.post("/quick-team")
async def quick_create_team(req: QuickTeamRequest):
    """AI-powered one-click team creation from natural language description."""
    from tubecli.core.agent import agent_manager
    from tubecli.extensions.multi_agents.extension import orchestrator
    from tubecli.extensions.studio3d.ai_builder import generate_quick_team

    try:
        # Step 1: AI parses description into team structure
        ai_result = generate_quick_team(req.description, req.provider, req.model)

        team_name = ai_result.get("team_name", "New Team")
        team_desc = ai_result.get("team_description", "")
        template = ai_result.get("template", "dev_team")
        agents_data = ai_result.get("agents", [])

        # Step 2: Create agents
        created_agents = []
        lead_agent_id = ""
        lead_role_id = None

        for i, ag in enumerate(agents_data):
            agent = agent_manager.create(
                name=ag.get("name", f"Agent {i+1}"),
                description=ag.get("description", ""),
                system_prompt=ag.get("system_prompt", "You are a helpful assistant."),
            )
            created_agents.append(agent)
            if ag.get("is_lead"):
                lead_agent_id = agent.id
                lead_role_id = f"role_{i}"

        # Build nodes with correct parent/children structure
        nodes = []
        member_role_ids = []

        for i, ag in enumerate(agents_data):
            role_id = f"role_{i}"
            is_lead = ag.get("is_lead", False)

            if not is_lead:
                member_role_ids.append(role_id)

            nodes.append({
                "role_id": role_id,
                "role": ag.get("role", f"Member {i+1}"),
                "emoji": ag.get("emoji", "🤖"),
                "description": ag.get("description", ""),
                "system_hint": ag.get("system_prompt", ""),
                "agent_id": created_agents[i].id,
                "parent": lead_role_id if not is_lead and lead_role_id else None,
                "children": member_role_ids if is_lead else [],
                "layer": 0 if is_lead else 1,
            })

        # Update lead node's children list (needs all member IDs)
        if lead_role_id:
            for nd in nodes:
                if nd["role_id"] == lead_role_id:
                    nd["children"] = [r for r in member_role_ids]

        # Step 3: Create team with nodes
        agent_ids = [a.id for a in created_agents]
        team = orchestrator.create_team(
            name=team_name,
            agent_ids=agent_ids,
            lead_agent_id=lead_agent_id,
            strategy="sequential",
            description=team_desc,
            template=template,
            nodes=nodes,
        )

        return {
            "ok": True,
            "team": team.to_dict(),
            "agents_created": len(created_agents),
        }
    except Exception as e:
        raise HTTPException(500, str(e))
