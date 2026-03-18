import json
import re
import requests

OLLAMA_BASE = "http://localhost:11434"

def build_ai_prompt(name: str, description: str) -> str:
    return f"""You are a JSON generator. Output ONLY valid JSON, no markdown, no explanation.

Generate an agent behavior JSON for: {name}
Description: {description}

The JSON must follow this EXACT structure (fill in realistic values based on the description):
{{
  "name": "{name}",
  "description": "{description}",
  "persona": {{
    "traits": ["trait1", "trait2", "trait3", "trait4", "trait5"],
    "interests": ["interest1", "interest2", "interest3", "interest4", "interest5", "interest6"]
  }},
  "routine": {{
    "dailyRoutine": ["action1", "action2", "action3", "action4"],
    "workHabits": {{
      "preferredSites": ["site1.com", "site2.com", "site3.com", "site4.com", "site5.com"],
      "focusAreas": ["Area 1", "Area 2", "Area 3", "Area 4"],
      "typicalActions": ["Action 1", "Action 2", "Action 3", "Action 4"]
    }}
  }},
  "browserBehavior": {{
    "sessionDuration": "20-30 minutes",
    "actionsPerSession": "8-15",
    "typicalFlow": "Step 1 -> Step 2 -> Step 3 -> Step 4"
  }}
}}

Note: the "auth" and "allowed_profiles" sections will be handled separately. Do NOT include them in your output.

Output ONLY the JSON object. No extra text."""

def extract_json(text: str) -> str:
    """Try to extract the first JSON object from AI response."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        candidate = match.group(0)
        try:
            json.loads(candidate)
            return candidate
        except Exception:
            pass
    return text.strip()

def call_ollama(model: str, prompt: str) -> str:
    try:
        r = requests.post(
            f"{OLLAMA_BASE}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=120,
        )
        if r.status_code == 200:
            return r.json().get("response", "")
        return f"[ERROR] Ollama returned status {r.status_code}: {r.text}"
    except Exception as ex:
        return f"[ERROR] Ollama connection: {ex}"

def call_gemini(model: str, api_key: str, prompt: str) -> str:
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        gen_model = genai.GenerativeModel(model)
        response = gen_model.generate_content(prompt)
        return response.text
    except Exception as ex:
        return f"[ERROR] Gemini: {ex}"

def call_openai_compatible(model: str, api_key: str, prompt: str, base_url: str = None) -> str:
    try:
        from openai import OpenAI
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        client = OpenAI(**kwargs)
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
        )
        return response.choices[0].message.content
    except Exception as ex:
        return f"[ERROR] OpenAI-compatible: {ex}"

def call_claude(model: str, api_key: str, prompt: str) -> str:
    try:
        import httpx
        resp = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 4096,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        blocks = data.get("content", [])
        return "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text")
    except Exception as ex:
        return f"[ERROR] Claude: {ex}"

def generate_agent_json(name: str, description: str, provider: str, model: str, api_key: str = "") -> dict:
    prompt = build_ai_prompt(name, description)
    
    if provider == "ollama":
        raw = call_ollama(model, prompt)
    elif provider == "gemini":
        raw = call_gemini(model, api_key, prompt)
    elif provider == "chatgpt":
        raw = call_openai_compatible(model, api_key, prompt)
    elif provider == "grok":
        raw = call_openai_compatible(model, api_key, prompt, base_url="https://api.x.ai/v1")
    elif provider == "claude":
        raw = call_claude(model, api_key, prompt)
    else:
        raise ValueError(f"Unknown provider: {provider}")

    if raw.startswith("[ERROR]"):
        raise RuntimeError(raw)

    json_str = extract_json(raw)
    try:
        data = json.loads(json_str)
        return data
    except Exception as e:
        raise ValueError(f"AI did not return valid JSON. Raw output: {raw[:200]}...")
