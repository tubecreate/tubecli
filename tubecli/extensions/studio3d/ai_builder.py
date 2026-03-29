import json
from typing import List, Dict, Any
from tubecli.core.ai_generator import (
    call_ollama, call_gemini, call_openai_compatible, call_claude, extract_json
)
from tubecli.extensions.cloud_api.extension import key_manager
from tubecli.extensions.studio3d.routes import ASSET_CATALOG

def build_studio_prompt(prompt: str, team_agents: List[Dict], room_width: float, room_depth: float) -> str:
    # Build list of available furniture
    available_assets = []
    for asset in ASSET_CATALOG:
        available_assets.append(f"- {asset['id']} ({asset['name']}) - Size: {asset['size'][0]}x{asset['size'][2]}m")
    
    # Build list of agents
    agents_list = []
    for ag in team_agents:
        agents_list.append(f"- ID: {ag['id']}, Name: {ag['name']}")

    system_prompt = f"""You are an expert 3D Interior Designer. Your task is to design an office layout based on user requirements.
You MUST return ONLY valid JSON data, no markdown formatting, no explanations.

# ROOM BOUNDARIES
- Width (X-axis): {-room_width/2} to {room_width/2}
- Depth (Z-axis): {-room_depth/2} to {room_depth/2}
- Center is (0, 0).

# TEAM MEMBERS ({len(team_agents)} members)
{chr(10).join(agents_list) if agents_list else "No team members."}

# AVAILABLE FURNITURE ASSETS
{chr(10).join(available_assets)}

# WORKSPACE PLACEMENT TEMPLATES (CRITICAL)
For every team member, you must build a "Workspace" consisting of a Desk, a Monitor (on the desk), and a Chair.
Because you cannot do complex math, you MUST pick ONE of these 4 pre-calculated directional setups for each workspace:

[SETUP 1 - Facing South (+Z)]
- Desk: x=D_X, z=D_Z, rotation=0
- Monitor: x=D_X, z=D_Z, rotation=0
- Chair: x=D_X, z=D_Z + 0.8, rotation=3.14

[SETUP 2 - Facing North (-Z)]
- Desk: x=D_X, z=D_Z, rotation=3.14
- Monitor: x=D_X, z=D_Z, rotation=3.14
- Chair: x=D_X, z=D_Z - 0.8, rotation=0

[SETUP 3 - Facing East (+X)]
- Desk: x=D_X, z=D_Z, rotation=1.57
- Monitor: x=D_X, z=D_Z, rotation=1.57
- Chair: x=D_X + 0.8, z=D_Z, rotation=-1.57

[SETUP 4 - Facing West (-X)]
- Desk: x=D_X, z=D_Z, rotation=-1.57
- Monitor: x=D_X, z=D_Z, rotation=-1.57
- Chair: x=D_X - 0.8, z=D_Z, rotation=1.57

Only replace D_X and D_Z with the actual coordinates of where you want the desk. Keep the offsets and rotations EXACTLY as shown in the template. Assign the `agent_id` ONLY to the desk.

# USER REQUIREMENT
"{prompt}"

# OUTPUT FORMAT
Return a JSON object with "assets" array and optional "room_resize". Example:
{{
  "room_resize": {{ "room_width": 16, "room_depth": 12 }},
  "assets": [
    {{ "asset_id": "desk_modern", "x": -2.5, "z": 1.0, "rotation": 0, "agent_id": "agent_123" }},
    {{ "asset_id": "monitor", "x": -2.5, "z": 1.0, "rotation": 0, "agent_id": "" }},
    {{ "asset_id": "chair_office", "x": -2.5, "z": 1.8, "rotation": 3.14, "agent_id": "" }},
    {{ "asset_id": "plant_tall", "x": 4.0, "z": -4.0, "rotation": 0, "agent_id": "" }}
  ]
}}

# OTHER RULES
1. Bookshelves and Cabinets: Place them touching the wall [-{room_width/2} or {room_width/2} for X, -{room_depth/2} or {room_depth/2} for Z].
2. Partitions: Use `wall_partition_solid` or `wall_partition_glass` (2m or 1m lengths) to build cubicles or divide the room.
3. `asset_id` MUST be exactly one of the IDs from the AVAILABLE FURNITURE ASSETS list above.
4. Output STRICT JSON only. Do not wrap in ```json blocks."""

    return system_prompt

def generate_studio_json(prompt: str, team_agents: List[Dict], room_width: float, room_depth: float, provider: str, model: str) -> dict:
    ai_prompt = build_studio_prompt(prompt, team_agents, room_width, room_depth)
    
    current_key = key_manager.get_active_key(provider) or ""
    
    if provider == "ollama":
        raw = call_ollama(model, ai_prompt)
    elif provider == "gemini":
        raw = call_gemini(model, current_key, ai_prompt)
    elif provider == "chatgpt":
        raw = call_openai_compatible(model, current_key, ai_prompt)
    elif provider == "claude":
        raw = call_claude(model, current_key, ai_prompt)
    else:
        raise ValueError(f"Unknown AI provider: {provider}")

    if raw.startswith("[ERROR]") or raw.startswith("[QUOTA_ERROR]"):
        raise RuntimeError(raw)

    json_str = extract_json(raw)
    try:
        data = json.loads(json_str)
        return data
    except Exception as e:
        raise ValueError(f"AI did not return valid JSON. Error: {e}\nRaw output: {raw[:300]}")
