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
    {"id": "floor_tile", "name": "Ô sàn", "category": "structure", "emoji": "⬜",
     "mesh": "box", "size": [2.0, 0.1, 2.0], "color": "#d4c8b0", "yOffset": 0.05},
    {"id": "door_frame", "name": "Cửa ra vào", "category": "structure", "emoji": "🚪",
     "mesh": "box", "size": [1.0, 2.5, 0.15], "color": "#5c3a1e", "yOffset": 1.25},
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
