"""
AI Script Parser — Convert existing Playwright .js files into Script Studio steps.
Uses cloud AI to analyze JavaScript automation code and extract structured steps.
"""
import json
import logging
import re

logger = logging.getLogger("ScriptStudio.Parser")

PARSER_SYSTEM_PROMPT = """You are a browser automation script analyst. Your task is to analyze a Playwright/Puppeteer JavaScript file and extract a structured list of automation steps.

## Output Format
Return ONLY a valid JSON object:
```json
{
  "name": "Script name (infer from filename/comments)",
  "description": "What the script does",
  "category": "video|image|audio|scraping|general",
  "target_url": "The main URL the script navigates to",
  "variables": [
    {"name": "var_name", "type": "string|number|boolean", "default": "default_value", "description": "What this variable is for"}
  ],
  "steps": [
    {
      "id": "step_001",
      "type": "navigate|click|type|wait|wait_hidden|sleep|evaluate|extract|screenshot|download|condition|loop|keyboard",
      "label": "Human-readable description of what this step does",
      "enabled": true,
      "selector": "CSS selector if applicable",
      "params": {},
      "on_error": "abort|skip|retry",
      "retry_count": 0,
      "retry_delay": 1000,
      "notes": "Any important context about this step"
    }
  ]
}
```

## Step Type Mapping Rules
- `page.goto(url)` → type: "navigate", params: {url: "..."}
- `page.click(selector)` / `.click()` → type: "click"
- `page.fill(selector, text)` / `.fill(text)` / `page.keyboard.type(text)` → type: "type", params: {text: "...", clear_first: true/false}
- `page.waitForSelector(selector)` / `.waitFor({state: 'visible'})` → type: "wait", params: {state: "visible", timeout: N}
- `page.waitForSelector(selector, {state: 'hidden'})` → type: "wait_hidden"
- `await new Promise(r => setTimeout(r, N))` / `sleep(N)` → type: "sleep", params: {ms: N}
- `page.evaluate(...)` → type: "evaluate", params: {code: "..."}
- `page.$eval(selector, el => el.textContent)` / getting attributes → type: "extract"
- `page.screenshot(...)` → type: "screenshot"
- `page.waitForEvent('download')` → type: "download"
- `page.keyboard.press(key)` → type: "keyboard", params: {key: "..."}
- `if (condition) { ... }` → type: "condition" with then_steps/else_steps
- `for/while loops` → type: "loop" with count/steps

## Variable Detection
- CLI arguments (args.profile, args.prompt, etc.) → variables with type "string"
- Environment variables → variables
- Hardcoded URLs that look configurable → extract as variables
- Use {{var_name}} syntax in step params

## Important Rules
1. Preserve the EXACT CSS selectors from the code
2. Keep error handling patterns (try/catch → on_error: "skip" or "retry")
3. Group related operations logically
4. Skip boilerplate (browser launch, profile loading) — focus on the AUTOMATION FLOW
5. For complex evaluate() blocks, include the full JavaScript code
6. If the script has a main loop processing multiple items, represent it as a "loop" step
7. Extract meaningful labels from comments or function names
8. Return ONLY valid JSON, no other text
"""


def parse_js_to_steps(js_content: str, filename: str = "") -> dict:
    """
    Parse a JavaScript automation file into Script Studio steps using regex-based analysis.
    This is the local fallback parser (no AI needed).
    """
    steps = []
    variables = []
    target_url = ""
    name = filename.replace('.js', '').replace('_', ' ').title() if filename else "Imported Script"
    description = ""
    category = "general"

    # Extract description from top comments
    comment_match = re.search(r'/\*\*(.*?)\*/', js_content, re.DOTALL)
    if comment_match:
        description = comment_match.group(1).strip().replace(' * ', ' ').replace('\n', ' ')[:200]

    # Detect category from filename/content
    if any(k in js_content.lower() for k in ['video', 'veo3', 'flow']):
        category = 'video'
    elif any(k in js_content.lower() for k in ['image', 'grok_image', 'batch_image']):
        category = 'image'
    elif any(k in js_content.lower() for k in ['tts', 'audio', 'gemini_tts']):
        category = 'audio'

    # Extract target URL
    url_match = re.search(r"(?:const|let|var)\s+\w*URL\w*\s*=\s*['\"](.+?)['\"]", js_content)
    if url_match:
        target_url = url_match.group(1)

    # Extract CLI variables
    for m in re.finditer(r"args\[?['\"]?([\w-]+)['\"]?\]?|args\.([\w]+)", js_content):
        var_name = m.group(1) or m.group(2)
        if var_name not in ('_', '$0') and var_name not in [v['name'] for v in variables]:
            variables.append({
                "name": var_name,
                "type": "string",
                "default": "",
                "description": f"CLI argument: --{var_name}"
            })

    # Parse automation steps
    step_idx = 0
    lines = js_content.split('\n')

    for i, line in enumerate(lines):
        stripped = line.strip()

        # page.goto
        goto_match = re.search(r"(?:page|frame)\.goto\s*\(\s*(.+?)\s*[,)]", stripped)
        if goto_match:
            url_val = goto_match.group(1).strip().strip("'\"")
            step_idx += 1
            steps.append({
                "id": f"step_{step_idx:03d}",
                "type": "navigate",
                "label": f"Navigate to {url_val[:50]}",
                "enabled": True,
                "selector": "",
                "params": {"url": url_val},
                "on_error": "abort",
                "retry_count": 0,
            })
            continue

        # page.click / .click()
        click_match = re.search(r"(?:page|frame|el|element|btn|button)\s*\.\s*click\s*\(([^)]*)\)", stripped)
        if click_match and 'locator' not in stripped:
            sel = click_match.group(1).strip().strip("'\"") or ""
            step_idx += 1
            # Get comment from previous or same line
            label = _extract_comment(lines, i) or f"Click: {sel[:60]}"
            steps.append({
                "id": f"step_{step_idx:03d}",
                "type": "click",
                "label": label,
                "enabled": True,
                "selector": sel,
                "params": {"timeout": 10000},
                "on_error": "abort",
                "retry_count": 0,
            })
            continue

        # locator().click()
        loc_click = re.search(r"(?:page|frame)\.locator\s*\(\s*['\"](.+?)['\"]\s*\).*\.click\s*\(", stripped)
        if loc_click:
            sel = loc_click.group(1)
            step_idx += 1
            label = _extract_comment(lines, i) or f"Click: {sel[:60]}"
            steps.append({
                "id": f"step_{step_idx:03d}",
                "type": "click",
                "label": label,
                "enabled": True,
                "selector": sel,
                "params": {"timeout": 10000},
                "on_error": "abort",
                "retry_count": 0,
            })
            continue

        # page.fill / page.type / keyboard.type
        fill_match = re.search(r"(?:page|frame)\.(?:fill|type)\s*\(\s*['\"](.+?)['\"]\s*,\s*(.+?)\s*[,)]", stripped)
        if fill_match:
            sel = fill_match.group(1)
            text_val = fill_match.group(2).strip().strip("'\"")
            step_idx += 1
            steps.append({
                "id": f"step_{step_idx:03d}",
                "type": "type",
                "label": _extract_comment(lines, i) or f"Type into: {sel[:40]}",
                "enabled": True,
                "selector": sel,
                "params": {"text": text_val, "clear_first": False},
                "on_error": "abort",
                "retry_count": 0,
            })
            continue

        # locator().fill()
        loc_fill = re.search(r"(?:page|frame)\.locator\s*\(\s*['\"](.+?)['\"]\s*\).*\.fill\s*\(\s*(.+?)\s*\)", stripped)
        if loc_fill:
            sel = loc_fill.group(1)
            text_val = loc_fill.group(2).strip().strip("'\"")
            step_idx += 1
            steps.append({
                "id": f"step_{step_idx:03d}",
                "type": "type",
                "label": _extract_comment(lines, i) or f"Fill: {sel[:40]}",
                "enabled": True,
                "selector": sel,
                "params": {"text": text_val, "clear_first": True},
                "on_error": "abort",
                "retry_count": 0,
            })
            continue

        # waitForSelector / waitFor
        wait_match = re.search(r"(?:page|frame)\.waitForSelector\s*\(\s*['\"](.+?)['\"]\s*(?:,\s*\{[^}]*state:\s*['\"](\w+)['\"])?", stripped)
        if wait_match:
            sel = wait_match.group(1)
            state = wait_match.group(2) or "visible"
            step_idx += 1
            stype = "wait_hidden" if state == "hidden" else "wait"
            steps.append({
                "id": f"step_{step_idx:03d}",
                "type": stype,
                "label": _extract_comment(lines, i) or f"Wait {state}: {sel[:50]}",
                "enabled": True,
                "selector": sel,
                "params": {"state": state, "timeout": 10000},
                "on_error": "abort",
                "retry_count": 0,
            })
            continue

        # sleep / setTimeout
        sleep_match = re.search(r"(?:await\s+)?(?:sleep|new Promise.*setTimeout)\s*\(\s*(\d+)", stripped)
        if sleep_match:
            ms = int(sleep_match.group(1))
            step_idx += 1
            steps.append({
                "id": f"step_{step_idx:03d}",
                "type": "sleep",
                "label": f"Wait {ms}ms",
                "enabled": True,
                "selector": "",
                "params": {"ms": ms},
                "on_error": "skip",
                "retry_count": 0,
            })
            continue

        # page.evaluate
        eval_match = re.search(r"(?:page|frame)\.evaluate\s*\(\s*(.+)", stripped)
        if eval_match and 'waitFor' not in stripped:
            code_preview = eval_match.group(1)[:100]
            step_idx += 1
            steps.append({
                "id": f"step_{step_idx:03d}",
                "type": "evaluate",
                "label": _extract_comment(lines, i) or f"Evaluate JS",
                "enabled": True,
                "selector": "",
                "params": {"code": code_preview},
                "on_error": "skip",
                "retry_count": 0,
                "notes": "Code extracted from original script — review and adjust"
            })
            continue

        # page.screenshot
        if 'screenshot' in stripped and 'page.' in stripped:
            step_idx += 1
            steps.append({
                "id": f"step_{step_idx:03d}",
                "type": "screenshot",
                "label": "Take screenshot",
                "enabled": True,
                "selector": "",
                "params": {"save_as": "screenshot.png"},
                "on_error": "skip",
                "retry_count": 0,
            })
            continue

        # keyboard.press
        key_match = re.search(r"keyboard\.press\s*\(\s*['\"](.+?)['\"]\s*\)", stripped)
        if key_match:
            key = key_match.group(1)
            step_idx += 1
            steps.append({
                "id": f"step_{step_idx:03d}",
                "type": "keyboard",
                "label": f"Press {key}",
                "enabled": True,
                "selector": "",
                "params": {"key": key},
                "on_error": "skip",
                "retry_count": 0,
            })
            continue

    return {
        "name": name,
        "description": description[:200],
        "category": category,
        "target_url": target_url,
        "variables": variables,
        "steps": steps,
    }


def _extract_comment(lines, idx):
    """Extract inline or preceding comment as step label."""
    line = lines[idx]
    # Inline comment
    inline = re.search(r'//\s*(.+)$', line)
    if inline:
        return inline.group(1).strip()[:80]
    # Previous line comment
    if idx > 0:
        prev = lines[idx - 1].strip()
        if prev.startswith('//'):
            return prev.lstrip('/ ').strip()[:80]
    return ""


async def ai_parse_js_to_steps(js_content: str, filename: str = "") -> dict:
    """
    Use cloud AI to parse JavaScript into steps (higher quality than regex).
    Falls back to regex parser if AI is unavailable.
    """
    try:
        import httpx
        from tubecli.config import DATA_DIR
        import os

        # Try to get cloud API key
        keys_path = os.path.join(str(DATA_DIR), "cloud_api_keys.json")
        if not os.path.exists(keys_path):
            logger.info("No cloud API keys, falling back to regex parser")
            return parse_js_to_steps(js_content, filename)

        with open(keys_path, "r", encoding="utf-8") as f:
            keys_data = json.load(f)

        # Find a working API key (Gemini or OpenAI compatible)
        api_key = None
        api_base = None
        model = None

        for provider_id, provider_data in keys_data.items():
            if isinstance(provider_data, dict):
                key_list = provider_data.get("keys", [])
                if key_list:
                    api_key = key_list[0].get("key") if isinstance(key_list[0], dict) else key_list[0]
                    api_base = provider_data.get("base_url", "")
                    model = provider_data.get("default_model", "")
                    if api_key:
                        break

        if not api_key:
            logger.info("No valid API key found, using regex parser")
            return parse_js_to_steps(js_content, filename)

        # Truncate if too long
        max_chars = 30000
        if len(js_content) > max_chars:
            js_content = js_content[:max_chars] + "\n\n// ... [TRUNCATED] ..."

        prompt = f"Analyze this browser automation script and extract structured steps.\n\nFilename: {filename}\n\n```javascript\n{js_content}\n```"

        # Call API
        if not api_base:
            api_base = "https://generativelanguage.googleapis.com/v1beta"

        async with httpx.AsyncClient(timeout=60) as client:
            if "googleapis.com" in api_base:
                # Gemini API
                resp = await client.post(
                    f"{api_base}/models/{model or 'gemini-2.0-flash'}:generateContent?key={api_key}",
                    json={
                        "systemInstruction": {"parts": [{"text": PARSER_SYSTEM_PROMPT}]},
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 8000},
                    }
                )
            else:
                # OpenAI-compatible API
                headers = {"Authorization": f"Bearer {api_key}"}
                resp = await client.post(
                    f"{api_base}/chat/completions",
                    headers=headers,
                    json={
                        "model": model or "gpt-4o-mini",
                        "messages": [
                            {"role": "system", "content": PARSER_SYSTEM_PROMPT},
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": 0.1,
                        "max_tokens": 8000,
                    }
                )

            if resp.status_code != 200:
                logger.warning(f"AI API returned {resp.status_code}, using regex parser")
                return parse_js_to_steps(js_content, filename)

            data = resp.json()

            # Extract text from response
            if "candidates" in data:  # Gemini
                text = data["candidates"][0]["content"]["parts"][0]["text"]
            else:  # OpenAI
                text = data["choices"][0]["message"]["content"]

            # Parse JSON from response
            json_match = re.search(r'\{[\s\S]*\}', text)
            if json_match:
                result = json.loads(json_match.group())
                logger.info(f"AI parsed {len(result.get('steps', []))} steps from {filename}")
                return result

    except Exception as e:
        logger.warning(f"AI parser failed: {e}, falling back to regex")

    return parse_js_to_steps(js_content, filename)
