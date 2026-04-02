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
    """Call Gemini via REST API (no SDK required)."""
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 4096},
        }
        r = requests.post(url, json=payload, timeout=120)
        if r.status_code == 429:
            return f"[QUOTA_ERROR] Gemini: Rate limit exceeded (429)"
        if r.status_code != 200:
            return f"[ERROR] Gemini HTTP {r.status_code}: {r.text[:200]}"
        data = r.json()
        candidates = data.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            return "".join(p.get("text", "") for p in parts)
        # Check for block reason
        block = data.get("promptFeedback", {}).get("blockReason")
        if block:
            return f"[ERROR] Gemini blocked: {block}"
        return "[ERROR] Gemini: No candidates in response"
    except Exception as ex:
        err_str = str(ex)
        if "429" in err_str or "quota" in err_str.lower():
            return f"[QUOTA_ERROR] Gemini: {err_str}"
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
        err_str = str(ex)
        if "429" in err_str or "RateLimitError" in err_str or "quota" in err_str.lower():
            return f"[QUOTA_ERROR] OpenAI-compatible: {err_str}"
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
        err_str = str(ex)
        if hasattr(ex, 'response') and ex.response is not None and ex.response.status_code == 429:
            return f"[QUOTA_ERROR] Claude: {err_str}"
        if "429" in err_str or "quota" in err_str.lower():
            return f"[QUOTA_ERROR] Claude: {err_str}"
        return f"[ERROR] Claude: {ex}"

def generate_agent_json(name: str, description: str, provider: str, model: str, api_key: str = "") -> dict:
    from tubecli.extensions.cloud_api.extension import key_manager
    prompt = build_ai_prompt(name, description)
    
    max_retries = 3
    for attempt in range(max_retries):
        current_key = api_key or key_manager.get_active_key(provider) or ""
        
        if provider == "ollama":
            raw = call_ollama(model, prompt)
        elif provider == "gemini":
            raw = call_gemini(model, current_key, prompt)
        elif provider == "chatgpt":
            raw = call_openai_compatible(model, current_key, prompt)
        elif provider == "grok":
            raw = call_openai_compatible(model, current_key, prompt, base_url="https://api.x.ai/v1")
        elif provider == "claude":
            raw = call_claude(model, current_key, prompt)
        else:
            raise ValueError(f"Unknown provider: {provider}")

        if raw.startswith("[QUOTA_ERROR]"):
            if not api_key and current_key:
                key_manager.report_key_error(provider, current_key, "Quota Exceeded")
                continue
            else:
                raise RuntimeError(raw)
        elif raw.startswith("[ERROR]"):
            raise RuntimeError(raw)

        json_str = extract_json(raw)
        try:
            import json
            data = json.loads(json_str)
            return data
        except Exception as e:
            raise ValueError(f"AI did not return valid JSON. Raw output: {raw[:200]}...")
            
    raise RuntimeError(f"All keys for {provider} are exhausted or invalid.")
