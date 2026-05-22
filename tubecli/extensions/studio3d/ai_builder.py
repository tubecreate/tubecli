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

# WORKSPACE RULE (MOST IMPORTANT)
For every team member, place ONE "workstation" item. This is a composite item that already includes a desk, chair, monitor, keyboard, mouse, and desk accessories — all correctly positioned.
- Set `agent_id` to the team member's ID.
- Set `rotation` to one of: 0, 1.57, 3.14, or -1.57 (to face different directions).
- The person sits at the +Z side of the workstation. rotation=0 means person faces +Z. rotation=3.14 means person faces -Z. etc.
- Space workstations at least 2.5m apart.

Do NOT use separate desk_modern + chair_office + monitor items. Use "workstation" instead.

# USER REQUIREMENT
"{prompt}"

# OUTPUT FORMAT
Return a JSON object with "assets" array and optional "room_resize". Example:
{{
  "room_resize": {{ "room_width": 16, "room_depth": 12 }},
  "assets": [
    {{ "asset_id": "workstation", "x": -3.0, "z": 2.0, "rotation": 3.14, "agent_id": "agent_123" }},
    {{ "asset_id": "workstation", "x": 3.0, "z": 2.0, "rotation": 3.14, "agent_id": "agent_456" }},
    {{ "asset_id": "bookshelf", "x": 7.5, "z": 0, "rotation": -1.57, "agent_id": "" }},
    {{ "asset_id": "plant_tall", "x": -7.5, "z": -5.5, "rotation": 0, "agent_id": "" }}
  ]
}}

# OTHER RULES
1. Bookshelves and Cabinets: Place them touching the wall.
2. Partitions: Use `wall_partition_solid` or `wall_partition_glass` to build cubicles or zones.
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
    elif provider == "chatgpt" or provider == "openai":
        raw = call_openai_compatible(model, current_key, ai_prompt)
    elif provider == "claude":
        raw = call_claude(model, current_key, ai_prompt)
    elif provider == "9router":
        raw = call_openai_compatible(model, current_key or "9router", ai_prompt, base_url="http://localhost:20128/v1")
    else:
        from tubecli.extensions.cloud_api.extension import PROVIDERS
        if provider in PROVIDERS:
            p_info = PROVIDERS[provider]
            p_url = p_info.get("base_url")
            raw = call_openai_compatible(model, current_key or provider, ai_prompt, base_url=p_url)
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


def generate_quick_team(description: str, provider: str, model: str) -> dict:
    """Parse a natural-language team description into structured team + agents JSON."""
    system_prompt = """You are an AI Team Architect. Given a user's description of a team they want to create, you must generate a JSON object describing the team structure.

# OUTPUT FORMAT (strict JSON, no markdown)
{
  "team_name": "Dev Team",
  "team_description": "A software development team",
  "template": "dev_team",
  "agents": [
    {
      "name": "Alex - Lead Developer",
      "role": "Team Lead",
      "emoji": "👨‍💼",
      "description": "Senior developer who leads the team",
      "system_prompt": "You are a senior tech lead. You review code, make architecture decisions, and mentor junior developers.",
      "is_lead": true
    },
    {
      "name": "Sam - Backend Dev",
      "role": "Backend Developer",
      "emoji": "⚙️",
      "description": "Backend developer specializing in APIs",
      "system_prompt": "You are a backend developer. You build REST APIs, manage databases, and write server-side code.",
      "is_lead": false
    }
  ]
}

# RULES
1. Give each agent a realistic first name + role title (e.g. "Minh - Frontend Dev")
2. Use Vietnamese names if the description is in Vietnamese
3. `template` should be one of: dev_team, company, imperial_court, military, hierarchy, custom
4. Each agent needs a unique, relevant system_prompt
5. `emoji` should match the role
6. Only ONE agent should have is_lead = true
7. Output STRICT JSON only. No markdown."""

    full_prompt = f"""{system_prompt}

# USER DESCRIPTION
"{description}"
"""
    current_key = key_manager.get_active_key(provider) or ""

    if provider == "ollama":
        raw = call_ollama(model, full_prompt)
    elif provider == "gemini":
        raw = call_gemini(model, current_key, full_prompt)
    elif provider == "chatgpt" or provider == "openai":
        raw = call_openai_compatible(model, current_key, full_prompt)
    elif provider == "claude":
        raw = call_claude(model, current_key, full_prompt)
    elif provider == "9router":
        raw = call_openai_compatible(model, current_key or "9router", full_prompt, base_url="http://localhost:20128/v1")
    else:
        from tubecli.extensions.cloud_api.extension import PROVIDERS
        if provider in PROVIDERS:
            p_info = PROVIDERS[provider]
            p_url = p_info.get("base_url")
            raw = call_openai_compatible(model, current_key or provider, full_prompt, base_url=p_url)
        else:
            raise ValueError(f"Unknown AI provider: {provider}")

    if raw.startswith("[ERROR]") or raw.startswith("[QUOTA_ERROR]"):
        raise RuntimeError(raw)

    json_str = extract_json(raw)
    try:
        data = json.loads(json_str)
        return data
    except Exception as e:
        raise ValueError(f"AI did not return valid JSON. Error: {e}\nRaw: {raw[:300]}")
