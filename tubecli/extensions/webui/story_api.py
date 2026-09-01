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
    scene_id: Optional[str] = ""
    actors: list[dict] = []
    waypoints: list[dict] = []
    timeline: list[dict] = []

class AIGenerateRequest(BaseModel):
    prompt: str
    scene_id: Optional[str] = ""
    actors: Optional[list[dict]] = []
    waypoints: Optional[list[dict]] = []
    provider: Optional[str] = "ollama"
    model: Optional[str] = ""
    api_key: Optional[str] = ""


# ── AI Models listing ───────────────────────────────────────────────

CLOUD_KEYS_FILE = os.path.normpath(os.path.join(
    os.path.dirname(__file__),
    "..", "..", "..", "data", "cloud_api_keys.json"
))

def _load_cloud_keys() -> dict:
    """Load cloud API keys from data/cloud_api_keys.json (Cloud API Keys extension)."""
    try:
        with open(CLOUD_KEYS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


@story_router.get("/ai-models")
async def list_ai_models():
    """Return available AI models: local Ollama + cloud providers."""
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

    # 2. Cloud providers — dynamic models from KeyManager
    from tubecli.extensions.cloud_api.extension import key_manager, PROVIDERS as CLOUD_PROVIDERS
    PROVIDER_MAP = {"openai": "chatgpt"}  # openai key → chatgpt provider

    PROVIDER_LABELS = {
        "gemini": "Google Gemini", "chatgpt": "OpenAI", "claude": "Anthropic Claude",
        "grok": "xAI Grok", "deepseek": "DeepSeek", "openrouter": "OpenRouter",
        "9router": "9Router",
    }

    cloud_keys = _load_cloud_keys()
    for key_name, key_entries in cloud_keys.items():
        if key_name.startswith("_"):
            continue
        # Check if there's at least one active key
        has_active = any(
            v.get("active", False) and v.get("key", "").strip()
            for v in (key_entries.values() if isinstance(key_entries, dict) else [])
        )
        if not has_active:
            continue
        # Map stored key name to provider name
        provider = PROVIDER_MAP.get(key_name, key_name)
        # Get models dynamically from KeyManager settings (or defaults)
        model_names = key_manager.get_models(key_name)
        if key_name == "9router" and not model_names:
            try:
                import requests
                active_key = key_manager.get_active_key("9router")
                headers = {}
                if active_key:
                    headers["Authorization"] = f"Bearer {active_key}"
                resp = requests.get("http://localhost:20128/v1/models", headers=headers, timeout=2)
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, dict) and "data" in data:
                        model_names = [m.get("id", m.get("name", "")) for m in data["data"] if isinstance(m, dict)]
            except Exception:
                pass
            if not model_names:
                model_names = ["deepseek-chat"]
                
        if model_names:
            result["cloud"].append({
                "provider": provider,
                "label": PROVIDER_LABELS.get(provider, provider.title()),
                "models": [{"name": m, "label": m} for m in model_names],
            })

    return result


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

    system_prompt = f"""You are an AI director writing interactive 3D scenes for a virtual office.
Your task: study the user's intent, the number of characters and the objects (waypoints) on the map, and FORM a coherent story BEFORE emitting the timeline.

REQUIRED JSON FORMAT (return the keys in this order):
{{
  "title": "Short scene title",
  "intent_analysis": "TEXT: analysis of the {len(actor_keys)} characters, their roles, and how to make flexible use of the objects on the map instead of falling into the obvious pattern.",
  "plot_outline": [
    "Scene 1: ...",
    "Scene 2: ...",
    "Scene 3: ..."
  ],
  "waypoints": [{{"id":"wp_id","label":"Place name","x":number,"z":number}}],
  "timeline": [
    {{"time": 0, "actor": "actor_key", "action": "walk_to", "target": "wp_id_or_coordinates"}},
    {{"time": 3, "actor": "actor_key", "action": "chat", "dialog": "Line of dialogue", "duration": 3}},
    {{"time": 7, "actor": "actor_key", "action": "animate", "anim": "think"}},
    {{"time": 9, "actor": "actor_key", "action": "emote", "emoji": "💡"}},
    {{"time": 12, "actor": "actor_key", "action": "return_desk"}}
  ]
}}

ACTIONS:
- walk_to: move to a waypoint (target: string id) or to coordinates (target: {{"x":number,"z":number}})
- chat: speak (dialog: the line, duration: 2-5 seconds)
- animate: play an animation (anim: read/write_board/shake_hand/cheer/think)
- emote: show a reaction (emoji: exactly 1 emoji)
- sit: sit down
- stand: stand up
- return_desk: go back to one's own desk

CHARACTERS: {', '.join(f'{k} ({n})' for k, n in zip(actor_keys, actor_names))}

WAYPOINTS ON THE MAP (including each character's own desk):
{wp_text}

ABOUT INTERACTION AND DESKS:
- Waypoint "desk_<key>" is a character's own desk (e.g. desk_pa = the Personal Assistant's desk).
- For two people to talk, A must walk_to B's desk, or both must walk_to the same waypoint (e.g. sofa, board). They must NOT talk across the room or through walls.

DIRECTING RULES:
1. USE THE WHOLE SPACE: work the entire map (especially visiting each other's desks). Do not repeat the "walk to the board, talk, walk back" pattern.
2. CHAIN OF THOUGHT: "intent_analysis" and "plot_outline" are mandatory and must be substantive. The timeline actions must follow the "plot_outline" you just wrote.
3. Produce AT LEAST 15-30 events; every character must keep moving, changing position, playing animations or interacting.
4. Dialogue must be natural, informative and DIFFERENT every line. Use emoji reactions in emote.
5. End with return_desk for every character.
6. Write "title", "plot_outline" and every "dialog" line in the SAME language as the user's request below.

Return ONLY valid raw JSON — NO markdown, NO explanation."""

    user_prompt = f"""Scene request: {req.prompt}

Think it through properly (analyse the intent -> draft the outline -> turn it into a timeline). Make sure:
- The actions are logical and the whole thing runs about 60-120 seconds
- The scene is lively and interesting, and uses all {len(actor_keys)} characters: {', '.join(actor_keys)}
- You return raw JSON exactly as specified (mandatory)."""

    full_prompt = f"{system_prompt}\n\n{user_prompt}"

    # Determine provider and model
    provider = (req.provider or "ollama").lower()
    model = req.model or ""
    api_key_override = req.api_key or ""

    raw = ""
    error_msg = ""
    
    from tubecli.extensions.cloud_api.extension import key_manager
    KEY_MAP = {"chatgpt": "openai", "gemini": "gemini", "claude": "claude", "grok": "grok", "deepseek": "deepseek", "openrouter": "openrouter", "9router": "9router"}
    km_provider = KEY_MAP.get(provider, provider)

    max_retries = 3
    for attempt in range(max_retries):
        current_key = api_key_override or key_manager.get_active_key(km_provider) or ""
        error_msg = ""
        raw = ""
        
        try:
            if provider == "ollama":
                if not model: model = "qwen2.5:7b"
                raw = call_ollama(model, full_prompt)
            elif provider == "gemini":
                if not model: model = "gemini-2.0-flash"
                if not current_key:
                    error_msg = "Chưa cấu hình Gemini API key. Vào Dashboard → Agent → Cloud API Keys để thêm."
                    break
                raw = call_gemini(model, current_key, full_prompt)
            elif provider == "chatgpt":
                if not model: model = "gpt-4o-mini"
                if not current_key:
                    error_msg = "Chưa cấu hình OpenAI API key. Vào Dashboard → Agent → Cloud API Keys để thêm."
                    break
                raw = call_openai_compatible(model, current_key, full_prompt)
            elif provider == "grok":
                if not model: model = "grok-3-mini-fast"
                if not current_key:
                    error_msg = "Chưa cấu hình Grok API key."
                    break
                raw = call_openai_compatible(model, current_key, full_prompt, base_url="https://api.x.ai/v1")
            elif provider == "deepseek":
                if not model: model = "deepseek-v4-flash"
                if not current_key:
                    error_msg = "Chưa cấu hình DeepSeek API key."
                    break
                raw = call_openai_compatible(model, current_key, full_prompt, base_url="https://api.deepseek.com")
            elif provider == "claude":
                if not model: model = "claude-sonnet-4-20250514"
                if not current_key:
                    error_msg = "Chưa cấu hình Claude API key."
                    break
                raw = call_claude(model, current_key, full_prompt)
            elif provider == "openrouter":
                if not model: model = "openai/gpt-4o-mini"
                if not current_key:
                    error_msg = "Chưa cấu hình OpenRouter API key."
                    break
                raw = call_openai_compatible(model, current_key, full_prompt, base_url="https://openrouter.ai/api/v1")
            elif provider == "9router":
                if not model: model = "deepseek-chat"
                raw = call_openai_compatible(model, current_key or "9router", full_prompt, base_url="http://localhost:20128/v1")
            else:
                error_msg = f"Provider không hỗ trợ: {provider}"
                break
                
            if raw.startswith("[QUOTA_ERROR]"):
                if not api_key_override and current_key:
                    hard = any(k in raw.lower() for k in ("insufficient_quota", "billing", "payment"))
                    key_manager.report_key_error(km_provider, current_key, "Quota Exceeded", transient=not hard)
                    continue
                else:
                    error_msg = raw
                    break
            elif raw.startswith("[ERROR]"):
                error_msg = raw
                break
                
            break # Success
        except Exception as e:
            error_msg = str(e)
            break

    # Check for errors
    if raw.startswith("[QUOTA_ERROR]") or raw.startswith("[ERROR]") or error_msg:
        err = error_msg or raw
        # Fallback to demo
        demo = _generate_demo_script(req.prompt, req.actors or [
            {"key": actor_keys[0], "name": actor_names[0], "color": "#f43f5e"},
            {"key": actor_keys[1] if len(actor_keys) > 1 else "b",
             "name": actor_names[1] if len(actor_names) > 1 else "Agent B", "color": "#22d3ee"},
        ], req.waypoints or [])
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
        ], req.waypoints or [])
        return {"ok": True, "script": demo, "note": "demo_fallback", "raw_preview": raw[:300]}


def _generate_demo_script(prompt: str, actors: list, waypoints: list = None) -> dict:
    """Generate a topic-aware demo script with different timeline structures per topic."""
    import random
    k0 = actors[0]["key"] if actors else "a"
    k1 = actors[1]["key"] if len(actors) > 1 else k0
    n0 = actors[0].get("name", "Agent A") if actors else "Agent A"
    n1 = actors[1].get("name", "Agent B") if len(actors) > 1 else "Agent B"
    topic = (prompt or "").lower()

    # Build desk references from waypoints
    desk0 = f"desk_{k0}"
    desk1 = f"desk_{k1}"
    has_desk0 = any(wp.get("id") == desk0 for wp in (waypoints or []))
    has_desk1 = any(wp.get("id") == desk1 for wp in (waypoints or []))

    emojis_pool = ["💡", "🎉", "😄", "🤔", "💪", "🔥", "✨", "🎯", "👋", "❤️", "🚀", "⭐", "📰", "📝", "🎊"]
    def e(): return random.choice(emojis_pool)

    # ── Detect topic and build appropriate timeline ──
    if any(kw in topic for kw in ["tin tức", "news", "đọc", "read", "bài báo", "tin"]):
        # NEWS & DISCUSSION: read at own desk → colleague comes over → discuss at board → sofa
        start0 = desk0 if has_desk0 else {"x": -1, "z": -2}
        timeline = [
            {"time": 0,  "actor": k0, "action": "walk_to",  "target": start0},
            {"time": 2,  "actor": k0, "action": "animate",  "anim": "read"},
            {"time": 5,  "actor": k0, "action": "chat",     "dialog": f"Có bài tin thú vị quá, {n1} lại bàn mình xem!", "duration": 3},
            {"time": 6,  "actor": k1, "action": "walk_to",  "target": start0},
            {"time": 9,  "actor": k1, "action": "chat",     "dialog": "Gì vậy? Show mình xem nào!", "duration": 3},
            {"time": 12, "actor": k0, "action": "emote",    "emoji": "📰"},
            {"time": 13, "actor": k0, "action": "walk_to",  "target": "board"},
            {"time": 16, "actor": k0, "action": "animate",  "anim": "write_board"},
            {"time": 19, "actor": k0, "action": "chat",     "dialog": "Đây nè, mình tóm tắt lên board cho rõ", "duration": 4},
            {"time": 21, "actor": k1, "action": "walk_to",  "target": "board"},
            {"time": 24, "actor": k1, "action": "animate",  "anim": "think"},
            {"time": 27, "actor": k1, "action": "chat",     "dialog": "Hmm, mình thấy góc nhìn này hay đó!", "duration": 3},
            {"time": 30, "actor": k0, "action": "chat",     "dialog": "Đúng! Theo mình phân tích thì...", "duration": 4},
            {"time": 34, "actor": k1, "action": "emote",    "emoji": "💡"},
            {"time": 35, "actor": k1, "action": "chat",     "dialog": "À mình hiểu rồi! Quan điểm thú vị!", "duration": 3},
            {"time": 38, "actor": k0, "action": "walk_to",  "target": "sofa"},
            {"time": 41, "actor": k1, "action": "walk_to",  "target": "sofa"},
            {"time": 44, "actor": k0, "action": "chat",     "dialog": "Ngồi đây trao đổi thêm nhé!", "duration": 3},
            {"time": 47, "actor": k1, "action": "animate",  "anim": "read"},
            {"time": 50, "actor": k1, "action": "chat",     "dialog": "Có thêm bài nữa nè, đọc tiếp!", "duration": 3},
            {"time": 53, "actor": k0, "action": "emote",    "emoji": e()},
            {"time": 55, "actor": k0, "action": "chat",     "dialog": "Ok tổng kết lại, hôm nay nhiều tin hay!", "duration": 4},
            {"time": 60, "actor": k0, "action": "return_desk"},
            {"time": 60, "actor": k1, "action": "return_desk"},
        ]

    elif any(kw in topic for kw in ["họp", "meeting", "báo cáo", "report", "thảo luận", "discuss"]):
        # MEETING: gather at board → present → discuss → shake hands
        meet_greetings = [
            "Chào mọi người! Bắt đầu meeting nhé!",
            "Mọi người tập trung nhé, mình bắt đầu cuộc họp.",
            "Ok, đủ người rồi. Cùng tổng kết tiến độ nào."
        ]
        meet_responses = [
            "Ready! Mình nghe đây!",
            "Ok, mình đã chuẩn bị xong báo cáo.",
            "Bắt đầu đi bạn, mình sẵn sàng rồi."
        ]
        meet_reports = [
            "Tuần này mình hoàn thành 3 task chính như đã định.",
            "Tiến độ hiện tại đang đi đúng hướng, các chỉ số đều tốt.",
            "Điểm nhấn tuần qua là mình đã release bản update ổn định."
        ]
        meet_feedback = [
            "Phần mình cũng xong, kết quả rất khả quan!",
            "Tuyệt vời, phía bên mình cũng không vướng mắc gì.",
            "Good! Nhìn chung tiến độ team rất đồng đều."
        ]
        meet_plans = [
            "Tuyệt! Vậy kế hoạch tuần tới mình làm gì tiếp?",
            "Thế tuần sau mục tiêu chính của chúng ta là gì?",
            "Ok, vậy next step cho dự án này là gì nhỉ?"
        ]
        meet_proposals = [
            "Mình đề xuất ưu tiên dứt điểm những phần này...",
            "Theo mình, tuần tới nên focus vào tối ưu hiệu năng.",
            "Mình nghĩ nên đẩy nhanh tiến độ khâu kiểm thử."
        ]
        meet_agrees = [
            "Đồng ý! Plan rất rõ ràng!",
            "Hợp lý đấy, chốt phương án này nhé.",
            "Ok, mình sẽ follow theo kế hoạch này."
        ]
        meet_closings = [
            "Meeting kết thúc! Team mình quá giỏi!",
            "Xong! Mọi người quay lại làm việc nhé.",
            "Cảm ơn mọi người, cuộc họp rất hiệu quả!"
        ]
        
        timeline = [
            {"time": 0,  "actor": k0, "action": "walk_to",  "target": "board"},
            {"time": 1,  "actor": k1, "action": "walk_to",  "target": "board"},
            {"time": 4,  "actor": k0, "action": "animate",  "anim": "write_board"},
            {"time": 7,  "actor": k0, "action": "chat",     "dialog": random.choice(meet_greetings), "duration": 3},
            {"time": 10, "actor": k1, "action": "chat",     "dialog": random.choice(meet_responses), "duration": 2},
            {"time": 13, "actor": k0, "action": "chat",     "dialog": random.choice(meet_reports), "duration": 4},
            {"time": 17, "actor": k0, "action": "animate",  "anim": "write_board"},
            {"time": 20, "actor": k1, "action": "animate",  "anim": "think"},
            {"time": 23, "actor": k1, "action": "chat",     "dialog": random.choice(meet_feedback), "duration": 4},
            {"time": 27, "actor": k0, "action": "emote",    "emoji": "🎯"},
            {"time": 28, "actor": k0, "action": "chat",     "dialog": random.choice(meet_plans), "duration": 3},
            {"time": 31, "actor": k1, "action": "walk_to",  "target": {"x": 1, "z": -3}},
            {"time": 34, "actor": k1, "action": "animate",  "anim": "write_board"},
            {"time": 37, "actor": k1, "action": "chat",     "dialog": random.choice(meet_proposals), "duration": 4},
            {"time": 41, "actor": k0, "action": "chat",     "dialog": random.choice(meet_agrees), "duration": 3},
            {"time": 44, "actor": k0, "action": "animate",  "anim": "shake_hand"},
            {"time": 47, "actor": k1, "action": "animate",  "anim": "cheer"},
            {"time": 50, "actor": k0, "action": "emote",    "emoji": "🚀"},
            {"time": 52, "actor": k0, "action": "chat",     "dialog": random.choice(meet_closings), "duration": 3},
            {"time": 56, "actor": k0, "action": "return_desk"},
            {"time": 56, "actor": k1, "action": "return_desk"},
        ]

    elif any(kw in topic for kw in ["nghỉ", "break", "giải lao", "ăn", "coffee", "cà phê", "lunch", "trưa"]):
        # BREAK TIME: leave desk → sofa → chill → chat casual
        br_invites = [
            f"Ê {n1}! Nghỉ ngơi tí đi!",
            f"{n1} ơi uống cà phê không? Mỏi mắt quá.",
            "Relax xíu nha, nãy giờ tập trung quá rồi."
        ]
        br_agrees = [
            "Ok! Mệt quá rồi 😫",
            "Đồng ý, đi pha cốc nước đã.",
            "Ý hay đấy, xả stress tí."
        ]
        br_chats = [
            "Cuối tuần này có plan gì không?",
            "Dạo này công việc nhiều, căng phết nhỉ?",
            "Bộ phim mới ra rạp xem hay lắm, đi xem chưa?"
        ]
        br_replies = [
            "Chưa, có gợi ý gì thú vị không?",
            "Cũng bình thường, cố gắng qua giai đoạn này thôi.",
            "Chưa xem nữa, chắc cuối tuần rảnh đi xem."
        ]
        br_ideas = [
            "Đi cafe hoặc xem phim đi!",
            "Cứ nghỉ ngơi ngủ một giấc cho khoẻ.",
            "Theo mình đi ăn món gì ngon ngon là tốt nhất."
        ]
        br_ends = [
            "Deal! Quay lại làm việc nào!",
            "Ok nha. Thôi hết giờ giải lao rồi.",
            "Quyết định vậy đi. Mình về bàn đây."
        ]
        
        timeline = [
            {"time": 0,  "actor": k0, "action": "walk_to",  "target": "door"},
            {"time": 2,  "actor": k0, "action": "chat",     "dialog": random.choice(br_invites), "duration": 3},
            {"time": 4,  "actor": k1, "action": "walk_to",  "target": "door"},
            {"time": 7,  "actor": k1, "action": "chat",     "dialog": random.choice(br_agrees), "duration": 2},
            {"time": 10, "actor": k0, "action": "walk_to",  "target": "sofa"},
            {"time": 12, "actor": k1, "action": "walk_to",  "target": "sofa"},
            {"time": 15, "actor": k0, "action": "sit"},
            {"time": 16, "actor": k1, "action": "sit"},
            {"time": 18, "actor": k0, "action": "chat",     "dialog": "Ngồi đây relax chút!", "duration": 3},
            {"time": 21, "actor": k1, "action": "emote",    "emoji": "😄"},
            {"time": 22, "actor": k1, "action": "chat",     "dialog": random.choice(br_chats), "duration": 3},
            {"time": 26, "actor": k0, "action": "chat",     "dialog": random.choice(br_replies), "duration": 3},
            {"time": 30, "actor": k1, "action": "animate",  "anim": "think"},
            {"time": 33, "actor": k1, "action": "chat",     "dialog": random.choice(br_ideas), "duration": 3},
            {"time": 36, "actor": k0, "action": "animate",  "anim": "cheer"},
            {"time": 38, "actor": k0, "action": "emote",    "emoji": "🎉"},
            {"time": 40, "actor": k0, "action": "chat",     "dialog": random.choice(br_ends), "duration": 3},
            {"time": 43, "actor": k0, "action": "stand"},
            {"time": 44, "actor": k1, "action": "stand"},
            {"time": 46, "actor": k0, "action": "return_desk"},
            {"time": 46, "actor": k1, "action": "return_desk"},
        ]

    elif any(kw in topic for kw in ["code", "lập trình", "develop", "debug", "fix", "build", "feature"]):
        # CODING SESSION: code at own desk → colleague comes to help → whiteboard → back to desk
        code_desk = desk0 if has_desk0 else {"x": -2, "z": 1}
        cod_probs = [
            "Hmm, mình cần giải quyết cái phần logic này...",
            "Đang tối ưu đoạn code này mà cấn cấn...",
            "Lỗi lạ quá, check log mãi chưa ra nguyên nhân."
        ]
        cod_offers = [
            f"Cần giúp không {n0}? Mình qua xem!",
            "Để mình ngó qua phụ một tay nhé?",
            "Có vẻ khoai đấy, mình qua cùng debug xem."
        ]
        cod_finds = [
            "Ah! Mình thấy vấn đề ở chỗ này nè!",
            "Hình như đoạn này bắt case chưa đủ?",
            "Thử đổi thuật toán chỗ này xem sao."
        ]
        cod_solves = [
            "Sửa logic ở chỗ này sẽ xử lý được!",
            "Chỉ cần thêm điều kiện chặn là ngon lành.",
            "Refactor lại một chút là hết bị conflict ngay."
        ]
        cod_succs = [
            "Chạy rồi! Tuyệt vời quá! 🎉",
            "Bug đã được fixed hoàn toàn!",
            "Test build pass rồi, cảm ơn nhé!"
        ]
        
        timeline = [
            {"time": 0,  "actor": k0, "action": "walk_to",  "target": code_desk},
            {"time": 2,  "actor": k0, "action": "animate",  "anim": "think"},
            {"time": 5,  "actor": k0, "action": "chat",     "dialog": random.choice(cod_probs), "duration": 3},
            {"time": 7,  "actor": k1, "action": "walk_to",  "target": code_desk},
            {"time": 10, "actor": k1, "action": "chat",     "dialog": random.choice(cod_offers), "duration": 3},
            {"time": 13, "actor": k0, "action": "walk_to",  "target": "board"},
            {"time": 16, "actor": k0, "action": "animate",  "anim": "write_board"},
            {"time": 19, "actor": k0, "action": "chat",     "dialog": "Để mình vẽ flow ra board cho dễ nhìn!", "duration": 3},
            {"time": 21, "actor": k1, "action": "walk_to",  "target": "board"},
            {"time": 24, "actor": k1, "action": "animate",  "anim": "think"},
            {"time": 27, "actor": k1, "action": "chat",     "dialog": random.choice(cod_finds), "duration": 3},
            {"time": 30, "actor": k0, "action": "emote",    "emoji": "💡"},
            {"time": 31, "actor": k1, "action": "animate",  "anim": "write_board"},
            {"time": 34, "actor": k1, "action": "chat",     "dialog": random.choice(cod_solves), "duration": 4},
            {"time": 38, "actor": k0, "action": "chat",     "dialog": "Genius! Mình implement thử ngay!", "duration": 3},
            {"time": 41, "actor": k0, "action": "walk_to",  "target": code_desk},
            {"time": 44, "actor": k0, "action": "animate",  "anim": "read"},
            {"time": 47, "actor": k0, "action": "chat",     "dialog": random.choice(cod_succs), "duration": 3},
            {"time": 50, "actor": k1, "action": "walk_to",  "target": code_desk},
            {"time": 52, "actor": k1, "action": "animate",  "anim": "cheer"},
            {"time": 54, "actor": k0, "action": "animate",  "anim": "shake_hand"},
            {"time": 57, "actor": k1, "action": "emote",    "emoji": "🚀"},
            {"time": 60, "actor": k0, "action": "return_desk"},
            {"time": 60, "actor": k1, "action": "return_desk"},
        ]

    elif any(kw in topic for kw in ["demo", "trình bày", "present", "show", "chia sẻ", "giới thiệu"]):
        # PRESENTATION: setup board → present → Q&A → celebrate
        pre_starts = [
            "Chuẩn bị xong! Mình bắt đầu demo luôn nhé!",
            "Tài liệu đã sẵn sàng trên bảng, mọi người chú ý.",
            "Buổi trình bày hôm nay sẽ xoay quanh kết quả đạt được."
        ]
        pre_points = [
            "Feature đầu tiên: UI mới mượt mà hơn rất nhiều!",
            "Phần core logic đã được đập đi xây lại hoàn thiện.",
            "Điểm nhấn là tính năng tự động hoá hoàn toàn mới."
        ]
        pre_metrics = [
            "Tiếp theo, hãy nhìn vào biểu đồ performance này!",
            "Kết quả đo lường cho thấy độ trễ giảm đi rõ rệt.",
            "Tỷ lệ chuyển đổi đã tăng lên đáng kể tuần qua."
        ]
        pre_asks = [
            "Ấn tượng thật! Metrics cải thiện bao nhiêu %?",
            "Tuyệt! Chi phí vận hành có giảm theo không?",
            "Rất tốt. Phản hồi từ user thế nào?"
        ]
        pre_answers = [
            "Tăng 40% hiệu suất! Mình có lưu cả data report.",
            "Giảm một nửa chi phí server trong khi traffic tăng gấp đôi.",
            "Đa số user đều thích giao diện mới và đánh giá 5 sao."
        ]
        
        timeline = [
            {"time": 0,  "actor": k0, "action": "walk_to",  "target": "board"},
            {"time": 3,  "actor": k0, "action": "animate",  "anim": "write_board"},
            {"time": 6,  "actor": k0, "action": "chat",     "dialog": random.choice(pre_starts), "duration": 3},
            {"time": 8,  "actor": k1, "action": "walk_to",  "target": {"x": 1, "z": 0}},
            {"time": 11, "actor": k1, "action": "chat",     "dialog": "Ready! Mình nghe đây!", "duration": 2},
            {"time": 14, "actor": k0, "action": "chat",     "dialog": random.choice(pre_points), "duration": 4},
            {"time": 18, "actor": k0, "action": "animate",  "anim": "write_board"},
            {"time": 21, "actor": k1, "action": "emote",    "emoji": "✨"},
            {"time": 22, "actor": k0, "action": "chat",     "dialog": random.choice(pre_metrics), "duration": 4},
            {"time": 26, "actor": k1, "action": "animate",  "anim": "think"},
            {"time": 29, "actor": k1, "action": "chat",     "dialog": random.choice(pre_asks), "duration": 3},
            {"time": 33, "actor": k0, "action": "chat",     "dialog": random.choice(pre_answers), "duration": 4},
            {"time": 37, "actor": k1, "action": "emote",    "emoji": "🔥"},
            {"time": 38, "actor": k1, "action": "chat",     "dialog": "Incredible! Team mình làm tốt lắm!", "duration": 3},
            {"time": 42, "actor": k0, "action": "animate",  "anim": "cheer"},
            {"time": 44, "actor": k1, "action": "animate",  "anim": "cheer"},
            {"time": 47, "actor": k0, "action": "animate",  "anim": "shake_hand"},
            {"time": 50, "actor": k0, "action": "emote",    "emoji": "🎉"},
            {"time": 52, "actor": k0, "action": "return_desk"},
            {"time": 52, "actor": k1, "action": "return_desk"},
        ]

    else:
        # GENERIC: varied random sequence using available waypoints
        anims = ["think", "read", "write_board", "cheer"]
        
        # Extract generic waypoints (not desks) from the scene
        available_wps = [wp["id"] for wp in (waypoints or []) if not wp["id"].startswith("desk_")]
        if len(available_wps) >= 3:
            wp_order = random.sample(available_wps, 3)
        elif len(available_wps) > 0:
            wp_order = [random.choice(available_wps) for _ in range(3)]
        else:
            wp_order = ["board", "sofa", "door"]
            
        greetings = [
            f"Chào {n0}! Bắt đầu công việc hôm nay nhé.",
            f"Hey {n0}! Mình cùng trao đổi vài việc xíu nha.",
            f"{n0} ơi, gặp nhau một lát thảo luận nhé."
        ]
        responses = [
            f"Ok {n1}! Mình lắng nghe đây!",
            f"Được đấy, mình đang rảnh luôn.",
            f"Tuyệt! Ra đây nói chuyện cho thoải mái."
        ]
        ideas = [
            "Về phần công việc chung, mình thấy cần cải thiện.",
            "Mình mới nảy ra một hướng đi khá hay cho team.",
            "Có vài điểm mình đã note lại, bạn xem thử."
        ]
        reactions = [
            "Hay quá! Share chi tiết cho mình xem với!",
            "Hợp lý đó! Mình hoàn toàn đồng ý.",
            "Góc nhìn rất sáng tạo! Triển khai luôn thôi."
        ]
            
        # Available patterns for generic fallback
        patterns = ["walk_around"]
        if has_desk0:
            patterns.append("desk_discussion")
        
        chosen_pattern = random.choice(patterns)
        
        if chosen_pattern == "desk_discussion":
            # STAY AT DESK AND ASK FOR HELP
            desk_probs = [
                "Hmm, phần này mãi chưa xử lý được...",
                "Có một vấn đề nhỏ ở đây cần ý kiến.",
                "Đang vướng một chút chỗ cấu hình này."
            ]
            desk_helps = [
                f"Sao thế {n0}? Mình qua xem thử.",
                "Cần mình hỗ trợ gì không?",
                "Có vẻ căng thẳng vậy, để mình qua góp ý."
            ]
            desk_shows = [
                "Đây nè, bạn nhìn chi tiết phần này đi.",
                "Mình đang nghĩ đến giải pháp này, ổn không?",
                "Theo bạn thì chỗ này nên đi theo hướng nào?"
            ]
            desk_advices = [
                "À, có thể thử hướng tiếp cận kia xem.",
                "Chỗ này mình từng gặp rồi, sửa nhẹ là xong.",
                "Góc nhìn của bạn khá hay, mình đồng ý chỉnh lại."
            ]
            desk_ends = [
                "Cảm ơn nhé! Mình sẽ thử ngay.",
                "Tuyệt, hướng đi này khả thi đấy.",
                "Ok, được rồi. Chốt phương án này nha."
            ]
            
            timeline = [
                {"time": 0,  "actor": k0, "action": "walk_to",  "target": desk0},
                {"time": 2,  "actor": k0, "action": "animate",  "anim": "think"},
                {"time": 5,  "actor": k0, "action": "chat",     "dialog": random.choice(desk_probs), "duration": 4},
                {"time": 8,  "actor": k1, "action": "walk_to",  "target": desk0},
                {"time": 11, "actor": k1, "action": "chat",     "dialog": random.choice(desk_helps), "duration": 3},
                {"time": 15, "actor": k0, "action": "chat",     "dialog": random.choice(desk_shows), "duration": 4},
                {"time": 19, "actor": k0, "action": "animate",  "anim": "write_board"}, # point to screen
                {"time": 22, "actor": k1, "action": "animate",  "anim": "think"},
                {"time": 25, "actor": k1, "action": "chat",     "dialog": random.choice(desk_advices), "duration": 4},
                {"time": 29, "actor": k0, "action": "emote",    "emoji": "💡"},
                {"time": 30, "actor": k0, "action": "chat",     "dialog": random.choice(desk_ends), "duration": 3},
                {"time": 34, "actor": k1, "action": "animate",  "anim": "cheer"},
                {"time": 36, "actor": k1, "action": "emote",    "emoji": "👌"},
                {"time": 39, "actor": k1, "action": "return_desk"},
                {"time": 39, "actor": k0, "action": "return_desk"}
            ]
        else:
            # ORIGINAL GENERIC (Walk around)
            timeline = [
                {"time": 0,  "actor": k0, "action": "walk_to",  "target": wp_order[0]},
                {"time": 3,  "actor": k1, "action": "walk_to",  "target": {"x": random.uniform(-2, 3), "z": random.uniform(-2, 2)}},
                {"time": 6,  "actor": k0, "action": "animate",  "anim": random.choice(anims)},
                {"time": 9,  "actor": k1, "action": "walk_to",  "target": wp_order[0]},
                {"time": 12, "actor": k1, "action": "chat",     "dialog": random.choice(greetings), "duration": 3},
                {"time": 15, "actor": k0, "action": "chat",     "dialog": random.choice(responses), "duration": 3},
                {"time": 18, "actor": k0, "action": "emote",    "emoji": e()},
                {"time": 20, "actor": k1, "action": "animate",  "anim": random.choice(anims)},
                {"time": 24, "actor": k0, "action": "walk_to",  "target": wp_order[1]},
                {"time": 27, "actor": k1, "action": "walk_to",  "target": wp_order[1]},
                {"time": 30, "actor": k0, "action": "chat",     "dialog": random.choice(ideas), "duration": 4},
                {"time": 34, "actor": k1, "action": "chat",     "dialog": random.choice(reactions), "duration": 3},
                {"time": 37, "actor": k0, "action": "animate",  "anim": random.choice(anims)},
                {"time": 40, "actor": k1, "action": "emote",    "emoji": e()},
                {"time": 42, "actor": k0, "action": "walk_to",  "target": wp_order[2]},
                {"time": 45, "actor": k1, "action": "walk_to",  "target": wp_order[2]},
                {"time": 48, "actor": k0, "action": "animate",  "anim": "shake_hand"},
                {"time": 50, "actor": k1, "action": "animate",  "anim": "cheer"},
                {"time": 53, "actor": k0, "action": "return_desk"},
                {"time": 53, "actor": k1, "action": "return_desk"},
            ]

    # Merge standard waypoints with desk waypoints from request
    all_waypoints = [
        {"id": "board", "label": "Whiteboard", "x": 0.5, "z": -4},
        {"id": "sofa",  "label": "Sofa",       "x": 5.0, "z": -3.5},
        {"id": "door",  "label": "Cửa",        "x": 0.5, "z": 6.0},
    ]
    # Add desk waypoints from request if present
    for wp in (waypoints or []):
        wp_id = wp.get("id", "")
        if wp_id.startswith("desk_") and not any(w.get("id") == wp_id for w in all_waypoints):
            all_waypoints.append(wp)

    return {
        "title": prompt[:60] if prompt else "Câu chuyện văn phòng",
        "scene_id": "",
        "actors": actors[:4],
        "waypoints": all_waypoints,
        "timeline": timeline
    }




@story_router.get("/teams")
async def list_teams():
    """Return all agent teams."""
    from tubecli.extensions.multi_agents.extension import orchestrator
    teams = orchestrator.get_all_teams()
    return {"teams": [t.to_dict() for t in teams]}

@story_router.get("/teams/{team_id}")
async def get_team(team_id: str):
    """Return a single team by ID."""
    from tubecli.extensions.multi_agents.extension import orchestrator
    team = orchestrator.get_team(team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    return team.to_dict()

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


