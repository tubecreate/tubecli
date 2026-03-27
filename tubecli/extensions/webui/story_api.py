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

    # 2. Cloud providers from data/cloud_api_keys.json
    cloud_keys = _load_cloud_keys()

    # Known cloud provider configs
    # Key in JSON → provider name mapping
    PROVIDER_MAP = {"openai": "chatgpt"}  # openai key → chatgpt provider
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
        "deepseek": [
            {"name": "deepseek-chat", "label": "DeepSeek Chat"},
            {"name": "deepseek-reasoner", "label": "DeepSeek Reasoner"},
        ],
    }
    PROVIDER_LABELS = {
        "gemini": "Google Gemini", "chatgpt": "OpenAI", "claude": "Anthropic Claude",
        "grok": "xAI Grok", "deepseek": "DeepSeek",
    }

    for key_name, key_entries in cloud_keys.items():
        # Check if there's at least one active key
        has_active = any(
            v.get("active", False) and v.get("key", "").strip()
            for v in (key_entries.values() if isinstance(key_entries, dict) else [])
        )
        if not has_active:
            continue
        # Map stored key name to provider name
        provider = PROVIDER_MAP.get(key_name, key_name)
        if provider in CLOUD_MODELS:
            result["cloud"].append({
                "provider": provider,
                "label": PROVIDER_LABELS.get(provider, provider.title()),
                "models": CLOUD_MODELS[provider],
            })

    return result


def _get_cloud_api_key(provider: str) -> str:
    """Get first active API key for a provider from data/cloud_api_keys.json."""
    # Map our provider name to the key name stored in JSON
    KEY_MAP = {"chatgpt": "openai", "gemini": "gemini", "claude": "claude",
               "grok": "grok", "deepseek": "deepseek"}
    key_name = KEY_MAP.get(provider, provider)
    cloud_keys = _load_cloud_keys()
    entries = cloud_keys.get(key_name, {})
    if isinstance(entries, dict):
        for label, entry in entries.items():
            if isinstance(entry, dict) and entry.get("active", False):
                key = entry.get("key", "").strip()
                if key:
                    return key
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

    system_prompt = f"""Bạn là một AI chuyên viết kịch bản tương tác 3D cho văn phòng ảo. Nhiệm vụ: tạo story script JSON phong phú, dài, có câu chuyện hấp dẫn.

FORMAT JSON bắt buộc:
{{
  "title": "Tên kịch bản ngắn gọn",
  "waypoints": [{{"id":"wp_id","label":"Tên vị trí","x":số,"z":số}}],
  "timeline": [
    {{"time": 0, "actor": "actor_key", "action": "walk_to", "target": "wp_id_hoặc_tọa_độ"}},
    {{"time": 3, "actor": "actor_key", "action": "chat", "dialog": "Nội dung hội thoại", "duration": 3}},
    {{"time": 7, "actor": "actor_key", "action": "animate", "anim": "think"}},
    {{"time": 9, "actor": "actor_key", "action": "emote", "emoji": "💡"}},
    {{"time": 12, "actor": "actor_key", "action": "return_desk"}}
  ]
}}

CÁC ACTION:
- walk_to: di chuyển đến waypoint (target: string id) hoặc tọa độ (target: {{"x":số,"z":số}})
- chat: nói chuyện (dialog: nội dung, duration: 2-5 giây)
- animate: thực hiện hoạt cảnh (anim: read/write_board/shake_hand/cheer/think)
- emote: biểu cảm (emoji: 1 emoji)
- sit: ngồi xuống
- stand: đứng dậy
- return_desk: quay về bàn làm việc của chính mình

NHÂN VẬT: {', '.join(f'{k} ({n})' for k, n in zip(actor_keys, actor_names))}

WAYPOINTS TRÊN MAP (bao gồm bàn làm việc của từng nhân vật):
{wp_text}

LƯU Ý QUAN TRỌNG VỀ BÀN LÀM VIỆC:
- Waypoint "desk_<key>" là bàn làm việc riêng của nhân vật đó (VD: desk_pa = bàn của Personal Assistant)
- Nhân vật có thể walk_to bàn của nhân vật KHÁC để trao đổi công việc (VD: pa walk_to desk_tb để bàn dự án với Test Bot)
- Đây là cách tự nhiên nhất để nhân vật tương tác: đến bàn đồng nghiệp → trò chuyện → thảo luận

QUY TẮC QUAN TRỌNG:
1. Tạo ÍT NHẤT 15-25 events trong timeline, kéo dài 60-120 giây
2. Mỗi nhân vật phải có ít nhất 6-8 events riêng
3. Xen kẽ các action đa dạng: walk → chat → animate → emote → walk → chat...
4. Dialog phải tự nhiên, sinh động, có cảm xúc, KHÁC NHAU mỗi câu (không lặp lại khuôn mẫu)
5. Sử dụng nhiều emoji đa dạng trong emote: 💡🎉😄🤔💪🔥✨🎯👋❤️
6. Nhân vật di chuyển đến nhiều vị trí khác nhau: BÀN ĐỒNG NGHIỆP, board, sofa, door, vị trí bất kỳ
7. Có ít nhất 2-3 tương tác giữa các nhân vật (chat qua lại, shake_hand, walk cùng nhau, đến bàn nhau)
8. Kết thúc bằng return_desk cho tất cả nhân vật
9. Hãy SÁNG TẠO — mỗi kịch bản phải KHÁC BIỆT, đừng dùng mẫu cố định

CHỈ trả về JSON thuần, không markdown, không giải thích."""

    user_prompt = f"""Kịch bản: {req.prompt}

Hãy tạo một kịch bản thật PHONG PHÚ, DÀI, và SÁNG TẠO với:
- Ít nhất 18-25 events trong timeline
- Thời lượng 60-120 giây  
- Hội thoại tự nhiên, có nội dung ý nghĩa liên quan đến chủ đề "{req.prompt}"
- Nhiều loại action khác nhau, không chỉ walk+chat
- Dùng đúng actor keys: {', '.join(actor_keys)}
- Mỗi nhân vật active xuyên suốt kịch bản"""

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
        timeline = [
            {"time": 0,  "actor": k0, "action": "walk_to",  "target": "board"},
            {"time": 1,  "actor": k1, "action": "walk_to",  "target": "board"},
            {"time": 4,  "actor": k0, "action": "animate",  "anim": "write_board"},
            {"time": 7,  "actor": k0, "action": "chat",     "dialog": f"Chào mọi người! Bắt đầu meeting nhé!", "duration": 3},
            {"time": 10, "actor": k1, "action": "chat",     "dialog": "Ready! Mình nghe đây!", "duration": 2},
            {"time": 13, "actor": k0, "action": "chat",     "dialog": "Tuần này mình hoàn thành 3 task chính", "duration": 4},
            {"time": 17, "actor": k0, "action": "animate",  "anim": "write_board"},
            {"time": 20, "actor": k1, "action": "animate",  "anim": "think"},
            {"time": 23, "actor": k1, "action": "chat",     "dialog": "Phần mình cũng xong, kết quả rất khả quan!", "duration": 4},
            {"time": 27, "actor": k0, "action": "emote",    "emoji": "🎯"},
            {"time": 28, "actor": k0, "action": "chat",     "dialog": "Tuyệt! Vậy kế hoạch tuần tới?", "duration": 3},
            {"time": 31, "actor": k1, "action": "walk_to",  "target": {"x": 1, "z": -3}},
            {"time": 34, "actor": k1, "action": "animate",  "anim": "write_board"},
            {"time": 37, "actor": k1, "action": "chat",     "dialog": "Mình đề xuất ưu tiên những task này...", "duration": 4},
            {"time": 41, "actor": k0, "action": "chat",     "dialog": "Đồng ý! Plan rất rõ ràng!", "duration": 3},
            {"time": 44, "actor": k0, "action": "animate",  "anim": "shake_hand"},
            {"time": 47, "actor": k1, "action": "animate",  "anim": "cheer"},
            {"time": 50, "actor": k0, "action": "emote",    "emoji": "🚀"},
            {"time": 52, "actor": k0, "action": "chat",     "dialog": "Meeting kết thúc! Team mình quá giỏi!", "duration": 3},
            {"time": 56, "actor": k0, "action": "return_desk"},
            {"time": 56, "actor": k1, "action": "return_desk"},
        ]

    elif any(kw in topic for kw in ["nghỉ", "break", "giải lao", "ăn", "coffee", "cà phê", "lunch", "trưa"]):
        # BREAK TIME: leave desk → sofa → chill → chat casual
        timeline = [
            {"time": 0,  "actor": k0, "action": "walk_to",  "target": "door"},
            {"time": 2,  "actor": k0, "action": "chat",     "dialog": f"Ê {n1}! Nghỉ ngơi tí đi!", "duration": 3},
            {"time": 4,  "actor": k1, "action": "walk_to",  "target": "door"},
            {"time": 7,  "actor": k1, "action": "chat",     "dialog": "Ok! Mệt quá rồi 😫", "duration": 2},
            {"time": 10, "actor": k0, "action": "walk_to",  "target": "sofa"},
            {"time": 12, "actor": k1, "action": "walk_to",  "target": "sofa"},
            {"time": 15, "actor": k0, "action": "sit"},
            {"time": 16, "actor": k1, "action": "sit"},
            {"time": 18, "actor": k0, "action": "chat",     "dialog": "Ngồi đây relax chút!", "duration": 3},
            {"time": 21, "actor": k1, "action": "emote",    "emoji": "😄"},
            {"time": 22, "actor": k1, "action": "chat",     "dialog": "Cuối tuần này có plan gì không?", "duration": 3},
            {"time": 26, "actor": k0, "action": "chat",     "dialog": "Chưa, có gợi ý gì thú vị không?", "duration": 3},
            {"time": 30, "actor": k1, "action": "animate",  "anim": "think"},
            {"time": 33, "actor": k1, "action": "chat",     "dialog": "Đi cafe hoặc xem phim đi!", "duration": 3},
            {"time": 36, "actor": k0, "action": "animate",  "anim": "cheer"},
            {"time": 38, "actor": k0, "action": "emote",    "emoji": "🎉"},
            {"time": 40, "actor": k0, "action": "chat",     "dialog": "Deal! Quay lại làm việc nào!", "duration": 3},
            {"time": 43, "actor": k0, "action": "stand"},
            {"time": 44, "actor": k1, "action": "stand"},
            {"time": 46, "actor": k0, "action": "return_desk"},
            {"time": 46, "actor": k1, "action": "return_desk"},
        ]

    elif any(kw in topic for kw in ["code", "lập trình", "develop", "debug", "fix", "build", "feature"]):
        # CODING SESSION: code at own desk → colleague comes to help → whiteboard → back to desk
        code_desk = desk0 if has_desk0 else {"x": -2, "z": 1}
        timeline = [
            {"time": 0,  "actor": k0, "action": "walk_to",  "target": code_desk},
            {"time": 2,  "actor": k0, "action": "animate",  "anim": "think"},
            {"time": 5,  "actor": k0, "action": "chat",     "dialog": "Hmm, mình cần solve cái bug này...", "duration": 3},
            {"time": 7,  "actor": k1, "action": "walk_to",  "target": code_desk},
            {"time": 10, "actor": k1, "action": "chat",     "dialog": f"Cần giúp không {n0}? Mình qua bàn xem!", "duration": 3},
            {"time": 13, "actor": k0, "action": "walk_to",  "target": "board"},
            {"time": 16, "actor": k0, "action": "animate",  "anim": "write_board"},
            {"time": 19, "actor": k0, "action": "chat",     "dialog": "Để mình vẽ flow ra board!", "duration": 3},
            {"time": 21, "actor": k1, "action": "walk_to",  "target": "board"},
            {"time": 24, "actor": k1, "action": "animate",  "anim": "think"},
            {"time": 27, "actor": k1, "action": "chat",     "dialog": "Ah! Mình thấy vấn đề ở đây nè!", "duration": 3},
            {"time": 30, "actor": k0, "action": "emote",    "emoji": "💡"},
            {"time": 31, "actor": k1, "action": "animate",  "anim": "write_board"},
            {"time": 34, "actor": k1, "action": "chat",     "dialog": "Sửa logic ở chỗ này sẽ fix được!", "duration": 4},
            {"time": 38, "actor": k0, "action": "chat",     "dialog": "Genius! Mình implement thử!", "duration": 3},
            {"time": 41, "actor": k0, "action": "walk_to",  "target": code_desk},
            {"time": 44, "actor": k0, "action": "animate",  "anim": "read"},
            {"time": 47, "actor": k0, "action": "chat",     "dialog": "Chạy rồi! Bug fixed! 🎉", "duration": 3},
            {"time": 50, "actor": k1, "action": "walk_to",  "target": code_desk},
            {"time": 52, "actor": k1, "action": "animate",  "anim": "cheer"},
            {"time": 54, "actor": k0, "action": "animate",  "anim": "shake_hand"},
            {"time": 57, "actor": k1, "action": "emote",    "emoji": "🚀"},
            {"time": 60, "actor": k0, "action": "return_desk"},
            {"time": 60, "actor": k1, "action": "return_desk"},
        ]

    elif any(kw in topic for kw in ["demo", "trình bày", "present", "show", "chia sẻ", "giới thiệu"]):
        # PRESENTATION: setup board → present → Q&A → celebrate
        timeline = [
            {"time": 0,  "actor": k0, "action": "walk_to",  "target": "board"},
            {"time": 3,  "actor": k0, "action": "animate",  "anim": "write_board"},
            {"time": 6,  "actor": k0, "action": "chat",     "dialog": "Chuẩn bị xong! Bắt đầu demo nhé!", "duration": 3},
            {"time": 8,  "actor": k1, "action": "walk_to",  "target": {"x": 1, "z": 0}},
            {"time": 11, "actor": k1, "action": "chat",     "dialog": "Ready! Mình nghe đây!", "duration": 2},
            {"time": 14, "actor": k0, "action": "chat",     "dialog": "Feature đầu tiên: giao diện mới!", "duration": 4},
            {"time": 18, "actor": k0, "action": "animate",  "anim": "write_board"},
            {"time": 21, "actor": k1, "action": "emote",    "emoji": "✨"},
            {"time": 22, "actor": k0, "action": "chat",     "dialog": "Tiếp theo là phần performance!", "duration": 4},
            {"time": 26, "actor": k1, "action": "animate",  "anim": "think"},
            {"time": 29, "actor": k1, "action": "chat",     "dialog": "Ấn tượng! Metrics cải thiện bao nhiêu?", "duration": 3},
            {"time": 33, "actor": k0, "action": "chat",     "dialog": "Tăng 40%! Mình có data chứng minh!", "duration": 4},
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
        topic_display = prompt[:40] if prompt else "công việc hôm nay"
        
        # Extract generic waypoints (not desks) from the scene
        available_wps = [wp["id"] for wp in (waypoints or []) if not wp["id"].startswith("desk_")]
        if len(available_wps) >= 3:
            wp_order = random.sample(available_wps, 3)
        elif len(available_wps) > 0:
            wp_order = [random.choice(available_wps) for _ in range(3)]
        else:
            wp_order = ["board", "sofa", "door"]
            
        greetings = [
            f"Chào {n0}! Mình bàn về {topic_display} nhé!",
            f"Hey {n0}! Xem qua phần {topic_display} xíu nha.",
            f"{n0} ơi, có vài idea về {topic_display} nè."
        ]
        responses = [
            f"Ok {n1}! Mình lắng nghe đây!",
            f"Được đấy, bắt đầu thôi {n1}!",
            f"Tuyệt! Mình cũng đang nghĩ về {topic_display}."
        ]
        ideas = [
            f"Điểm mấu chốt của {topic_display} là phần này nè...",
            f"Theo mình, triển khai {topic_display} nên làm thế này.",
            f"Mình thấy có vài rủi ro với {topic_display}, cần lưu ý."
        ]
        reactions = [
            "Hay quá! Share chi tiết thêm đi!",
            "Hợp lý đó! Mình đồng ý hướng này.",
            "Wow góc nhìn mới lạ! Rất thú vị."
        ]
            
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
        "scene_id": "team_trieudionh",
        "actors": actors[:4],
        "waypoints": all_waypoints,
        "timeline": timeline
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


