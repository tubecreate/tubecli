"""
AI Workflow Builder — Generate workflow graphs from natural language prompts.
Uses LLM to select appropriate nodes, configure them, and connect them.
Ported & enhanced from python-video-studio/core/ai_workflow_prompts.py

Design: n8n-friendly output (port names match, can be mapped via N8nBridge).
"""
import json
import re
import requests
from typing import Dict, Any, Optional
from tubecli.config import OLLAMA_BASE_URL, DEFAULT_AI_MODEL


def _render_node_catalog(available_nodes: list) -> str:
    """Render the full node catalog: ports with types/descriptions/required
    flags + every config key with type, options, default and description.
    This is what makes generated workflows actually runnable — the LLM no
    longer has to guess port names or config keys."""
    out = ""
    for node in available_nodes:
        ntype = node.get("type", "")
        name = node.get("name", ntype)
        desc = node.get("description", "")
        out += f"### {ntype} — {name}\n{desc}\n"

        in_ports = node.get("input_ports") or [
            {"name": n, "type": "any", "description": "", "required": True}
            for n in node.get("inputs", [])
        ]
        out_ports = node.get("output_ports") or [
            {"name": n, "type": "any", "description": ""}
            for n in node.get("outputs", [])
        ]

        if in_ports:
            parts = []
            for p in in_ports:
                tag = f"{p['name']} ({p.get('type', 'any')}"
                if not p.get("required", True):
                    tag += ", optional"
                tag += ")"
                if p.get("description"):
                    tag += f": {p['description']}"
                parts.append(tag)
            out += "  Input ports: " + "; ".join(parts) + "\n"
        else:
            out += "  Input ports: (none — this is a source node)\n"

        if out_ports:
            parts = []
            for p in out_ports:
                tag = f"{p['name']} ({p.get('type', 'any')})"
                if p.get("description"):
                    tag += f": {p['description']}"
                parts.append(tag)
            out += "  Output ports: " + "; ".join(parts) + "\n"

        cfg = node.get("config_schema") or {}
        if cfg:
            out += "  Config keys:\n"
            for key, cdef in cfg.items():
                line = f"    - {key} ({cdef.get('type', 'string')}"
                if cdef.get("required"):
                    line += ", REQUIRED"
                line += ")"
                if cdef.get("options"):
                    line += f" one of {cdef['options']}"
                if "default" in cdef:
                    line += f" [default: {json.dumps(cdef['default'], ensure_ascii=False)}]"
                if cdef.get("description"):
                    line += f" — {cdef['description']}"
                out += line + "\n"
        out += "\n"
    return out


def validate_workflow(nodes: list, connections: list, port_defs: dict, available_nodes: list = None) -> list:
    """Static validation of a generated workflow. Returns a list of
    human/LLM-readable issue strings (empty = valid)."""
    issues = []
    if not nodes:
        return ["Workflow has no nodes."]

    node_ids = [nd.get("id", "") for nd in nodes]
    id_set = set(node_ids)

    # Duplicate / missing ids
    seen_ids = set()
    for nid in node_ids:
        if not nid:
            issues.append("A node is missing its 'id' field.")
        elif nid in seen_ids:
            issues.append(f"Duplicate node id '{nid}' — every node needs a unique id.")
        seen_ids.add(nid)

    # Config keys against schema (unknown node types are handled upstream)
    schema_map = {}
    for n in (available_nodes or []):
        schema_map[n.get("type", "")] = n.get("config_schema") or {}

    node_type_map = {}
    for nd in nodes:
        ntype = nd.get("type", "")
        node_type_map[nd.get("id", "")] = ntype
        schema = schema_map.get(ntype)
        if schema:
            for req_key, cdef in schema.items():
                if cdef.get("required") and not (nd.get("config") or {}).get(req_key):
                    # Required config missing — may still arrive via an input port
                    inputs_for_type = set(port_defs.get(ntype, {}).get("inputs", []))
                    fed_by_conn = any(
                        c.get("to_node_id") == nd.get("id") for c in connections
                    ) and bool(inputs_for_type)
                    if not fed_by_conn:
                        issues.append(
                            f"Node '{nd.get('id')}' ({ntype}) is missing required config '{req_key}' and has no incoming connection to supply it."
                        )

    # Connection endpoints must exist
    connected = set()
    for c in connections:
        f, t = c.get("from_node_id", ""), c.get("to_node_id", "")
        if f not in id_set:
            issues.append(f"Connection references unknown from_node_id '{f}'.")
        if t not in id_set:
            issues.append(f"Connection references unknown to_node_id '{t}'.")
        if f == t:
            issues.append(f"Node '{f}' connects to itself.")
        connected.add(f)
        connected.add(t)

    # Orphan nodes (only matters when there are 2+ nodes)
    if len(nodes) > 1:
        for nid in node_ids:
            if nid and nid not in connected:
                issues.append(f"Node '{nid}' is not connected to anything (orphan).")

    # Cycle detection via Kahn's algorithm
    in_degree = {nid: 0 for nid in id_set}
    graph = {nid: [] for nid in id_set}
    for c in connections:
        f, t = c.get("from_node_id", ""), c.get("to_node_id", "")
        if f in graph and t in in_degree:
            graph[f].append(t)
            in_degree[t] += 1
    queue = [nid for nid, deg in in_degree.items() if deg == 0]
    visited = 0
    while queue:
        nid = queue.pop(0)
        visited += 1
        for nb in graph[nid]:
            in_degree[nb] -= 1
            if in_degree[nb] == 0:
                queue.append(nb)
    if visited < len(id_set):
        cyclic = [nid for nid, deg in in_degree.items() if deg > 0]
        issues.append(f"Workflow contains a cycle involving nodes: {cyclic}. Workflows must be a DAG (no loops in connections; use the 'loop' node for iteration).")

    return issues


def build_system_prompt(available_nodes: list) -> str:
    """
    Build a comprehensive system prompt that teaches the LLM
    about every available node type, their ports, and config fields.
    """
    prompt = (
        "You are a Workflow Builder AI for TubeCLI. "
        "Convert user requests into a valid JSON workflow.\n\n"
    )

    # ── Node Catalog ────────────────────────────────────────────
    prompt += "## AVAILABLE NODES\n\n"
    prompt += _render_node_catalog(available_nodes)

    # ── Fallback Instruction ────────────────────────────────────
    prompt += "\n## PYTHON CODE FALLBACK\n"
    prompt += (
        "If NO existing node can handle a specific task (e.g., scraping a website, "
        "calling a custom API, data transformation), use a `python_code` node.\n"
        "Set config.code to valid Python. Available variables:\n"
        "  - `input_data`: auto-set to text_input or json_input (whichever has data)\n"
        "  - `text_input`: text from connected input port\n"
        "  - `json_input`: JSON data from connected input port\n"
        "  - Pre-imported: `json`, `re`, `os`\n"
        "  - You may also `import requests, subprocess, urllib` in your code.\n"
        "Assign the final value to `result`.\n"
        "Example config: {\"code\": \"import requests\\nresp = requests.get(input_data)\\nresult = resp.json()\"}\n\n"
    )

    # ── Output Schema ───────────────────────────────────────────
    prompt += "## OUTPUT FORMAT (STRICT JSON)\n\n"
    prompt += "Return ONLY a single JSON object with this exact structure:\n"
    prompt += "```json\n"
    prompt += json.dumps({
        "nodes": [
            {
                "id": "node_1",
                "type": "text_input",
                "label": "Input URL",
                "x": 100, "y": 150,
                "config": {"text": "https://example.com/user/123"}
            },
            {
                "id": "node_2",
                "type": "google_auth",
                "label": "Google Auth",
                "x": 100, "y": 350,
                "config": {"scopes": "https://www.googleapis.com/auth/spreadsheets,https://www.googleapis.com/auth/drive"}
            },
            {
                "id": "node_3",
                "type": "python_code",
                "label": "Scrape Data",
                "x": 450, "y": 150,
                "config": {"code": "import requests\nresp = requests.get(input_data)\nresult = resp.json()"}
            },
            {
                "id": "node_4",
                "type": "google_sheets",
                "label": "Save to Sheet",
                "x": 800, "y": 150,
                "config": {"action": "append", "spreadsheet_id": "auto", "title": "Scraped Data"}
            }
        ],
        "connections": [
            {"from_node_id": "node_1", "from_port_id": "content", "to_node_id": "node_3", "to_port_id": "text_input"},
            {"from_node_id": "node_2", "from_port_id": "credentials", "to_node_id": "node_4", "to_port_id": "credentials"},
            {"from_node_id": "node_3", "from_port_id": "result", "to_node_id": "node_4", "to_port_id": "data"}
        ]
    }, indent=2, ensure_ascii=False)
    prompt += "\n```\n\n"

    # ── Critical Rules ──────────────────────────────────────────
    prompt += "## CRITICAL RULES\n\n"
    prompt += "1. MANDATORY: Return BOTH `nodes` AND `connections` arrays.\n"
    prompt += "2. PORT NAMES: `from_port_id` and `to_port_id` MUST match the port names listed above (e.g. 'content', 'text_input', 'items', 'result').\n"
    prompt += "3. SPACING: Place nodes at x = 100, 450, 800, 1150 (350px horizontal steps). Multiple parallel nodes: vary y by 200px.\n"
    prompt += "4. LOGIC: Connect nodes sequentially. Input → Processing → Output.\n"
    prompt += "5. JSON ONLY: No markdown fences, no comments, no chat text. Pure JSON.\n"
    prompt += "6. LANGUAGE: Node labels should match the user's language.\n"
    prompt += "7. UNIQUE IDs: Each node must have a unique `id` string.\n"
    prompt += "8. PREFER NATIVE NODES: Use built-in nodes over python_code when possible.\n"
    prompt += "9. For loops/batches: connect a data source to `loop` node's `items` input, then use `current_item` output. The `items` port MUST receive a FLAT LIST (not a dict).\n"
    prompt += "10. GOOGLE SHEETS: ALWAYS use `google_auth` node + `google_sheets` node together (NOT python_code).\n"
    prompt += "    - Connect google_auth `credentials` port → google_sheets `credentials` port.\n"
    prompt += "    - Set google_sheets config: action='append'|'write'|'read', spreadsheet_id='auto' (creates new sheet), title='My Data'.\n"
    prompt += "    - Connect data to google_sheets `data` port. Data MUST be a 2D array: [[col1, col2], [val1, val2]].\n"
    prompt += "11. DATA FORMAT: python_code result for Google Sheets must be a 2D array (list of lists). First row = headers.\n"
    prompt += "    Example: result = [['Title', 'URL', 'Views'], ['Video 1', 'https://...', '1000']]\n"
    prompt += "12. google_auth node auto-uses saved OAuth credentials (no config needed). Just add it to the workflow.\n"
    # Only teach video_processing when this machine actually HAS it. It comes
    # from an optional extension (video_editor), which lives under data/ and is
    # therefore not part of the repository — a fresh install has no such node.
    # Teaching it unconditionally was self-defeating: the model obeyed "ALWAYS
    # use video_processing", the type was absent from the registry, and
    # generate_workflow rewrote it into an empty python_code box. The user asked
    # for a video task in plain language and got a blank "write it yourself" box
    # with no explanation. Every instruction in this prompt must name a node that
    # exists on THIS machine.
    _types = {n.get("type") for n in available_nodes}
    if "video_processing" in _types:
        prompt += "\n## VIDEO PROCESSING (MUST USE for video tasks)\n\n"
        prompt += "For ANY video processing task, ALWAYS use the `video_processing` node (NOT python_code + run_command).\n"
        prompt += "- Ports: input_file (FILE), input_files (TEXT), audio_file (TEXT), start_time (TEXT), end_time (TEXT), text (TEXT), output_dir (TEXT) → output_file (FILE), status (TEXT)\n"
        prompt += "- Config `operation`: choose one of: trim, grayscale, sepia, blur, sharpen, negative, vintage, vignette, speed_2x, speed_05x, rotate_90, rotate_180, flip_h, flip_v, resize_720p, resize_1080p, resize_480p, extract_audio, remove_audio, add_audio, merge_concat, overlay_text, convert_mp4, convert_webm, convert_gif, export_high, export_medium, export_fast, fade_in_out, stabilize, reverse, thumbnail, custom\n"
        prompt += "- Config `command`: auto-filled by operation. Can be customized for 'custom' operation.\n"
        prompt += "- Config `output_suffix`: suffix added to output filename (default: '_processed').\n"
        prompt += "- Config `output_dir`: output folder path. If empty, uses default exports dir. Can also be set via the `output_dir` input port.\n"
        prompt += "- For batch video: use python_code to list files (result = [path1, path2, ...] as FLAT list), connect to loop `items`, connect loop `current_item` → video_processing `input_file`.\n"
        prompt += "- To save to a custom folder: connect a text_input with the folder path to video_processing `output_dir` port, OR set config `output_dir`.\n"
        prompt += "- Example: To flip all videos and save to custom dir: text_input(folder) → python_code(list files) → loop → video_processing(operation='flip_h', output_dir='C:/output')\n"

    return prompt


def resolve_port_connections(nodes_data: list, connections_data: list, port_defs: dict) -> list:
    """
    Resolve port name-based connections from LLM output.
    The LLM returns port names (e.g., 'content', 'items'), but the frontend
    needs port IDs. This function validates port names exist for the given node types.
    
    Since TubeCLI frontend generates port IDs dynamically on fromJSON(),
    we just need to ensure the port NAMES are valid. The frontend's fromJSON()
    will assign UUIDs and the connection matching happens by port position/name.
    """
    resolved = []
    
    # Build a map: node_id -> node_type
    node_type_map = {}
    for nd in nodes_data:
        node_type_map[nd.get("id", "")] = nd.get("type", "")

    for conn in connections_data:
        from_node_id = conn.get("from_node_id", "")
        to_node_id = conn.get("to_node_id", "")
        from_port = conn.get("from_port_id", "")
        to_port = conn.get("to_port_id", "")

        from_type = node_type_map.get(from_node_id, "")
        to_type = node_type_map.get(to_node_id, "")

        # Validate from_port exists in the node's output ports
        from_ports = port_defs.get(from_type, {}).get("outputs", [])
        to_ports = port_defs.get(to_type, {}).get("inputs", [])

        # Fuzzy match: normalize port names
        def normalize(name):
            return re.sub(r'[^a-z0-9]', '', str(name).lower())

        # Try exact match first, then fuzzy, then fallback to first port
        matched_from = from_port
        if from_ports and not any(normalize(p) == normalize(from_port) for p in from_ports):
            # Try partial match
            for p in from_ports:
                if normalize(from_port) in normalize(p) or normalize(p) in normalize(from_port):
                    matched_from = p
                    break
            else:
                matched_from = from_ports[0] if from_ports else from_port

        matched_to = to_port
        if to_ports and not any(normalize(p) == normalize(to_port) for p in to_ports):
            for p in to_ports:
                if normalize(to_port) in normalize(p) or normalize(p) in normalize(to_port):
                    matched_to = p
                    break
            else:
                matched_to = to_ports[0] if to_ports else to_port

        resolved.append({
            "from_node_id": from_node_id,
            "from_port_id": matched_from,
            "to_node_id": to_node_id,
            "to_port_id": matched_to,
        })

    return resolved


def auto_connect_sequential(nodes_data: list, port_defs: dict) -> list:
    """
    Fallback: If LLM returns no connections, auto-connect nodes sequentially.
    Maps first output port of node N to first input port of node N+1.
    """
    connections = []
    for i in range(len(nodes_data) - 1):
        from_nd = nodes_data[i]
        to_nd = nodes_data[i + 1]

        from_type = from_nd.get("type", "")
        to_type = to_nd.get("type", "")

        from_outputs = port_defs.get(from_type, {}).get("outputs", ["output"])
        to_inputs = port_defs.get(to_type, {}).get("inputs", ["input"])

        if from_outputs and to_inputs:
            connections.append({
                "from_node_id": from_nd["id"],
                "from_port_id": from_outputs[0],
                "to_node_id": to_nd["id"],
                "to_port_id": to_inputs[0],
            })

    return connections


def resolve_global_ai(model: str = "") -> tuple:
    """Resolve the system default AI into (provider, model, api_key).

    The Workflow Builder's provider dropdown offers "Global AI (mặc định)" —
    the option a first-time user is meant to land on, because it asks them for
    nothing. Nothing implemented it: the value reached call_llm and fell through
    to "Unknown provider: global". This is that implementation.

    The rule is copied from ModelAgentNode (model_agent_node.py:47-92), which
    already did it correctly: take default_model from global_settings.json,
    infer the provider from the model NAME, then look up an active key. Provider
    is inferred rather than stored because global_settings only records a model.
    """
    import os
    from tubecli.config import DATA_DIR

    if not model:
        gs_file = os.path.join(str(DATA_DIR), "global_settings.json")
        if os.path.exists(gs_file):
            try:
                with open(gs_file, "r", encoding="utf-8") as f:
                    model = (json.load(f) or {}).get("default_model", "") or ""
            except Exception:
                pass
    if not model:
        model = DEFAULT_AI_MODEL

    low = model.lower()
    if "deepseek" in low:
        provider = "deepseek"
    elif "gemini" in low:
        provider = "gemini"
    elif "gpt" in low or low.startswith("o1") or low.startswith("o3"):
        provider = "chatgpt"
    elif "claude" in low:
        provider = "claude"
    elif "grok" in low:
        provider = "grok"
    else:
        provider = "ollama"

    api_key = "" if provider == "ollama" else _resolve_cloud_api_key(provider)
    print(f"  [AIWorkflow] global -> provider={provider} model={model} has_key={bool(api_key)}")
    return provider, model, api_key


def call_llm(prompt: str, user_message: str, provider: str, model: str, api_key: str = "") -> str:
    """
    Call an LLM provider to generate workflow JSON.
    Reuses the same multi-provider pattern as ModelAgentNode.
    """
    if provider == "global":
        provider, model, api_key = resolve_global_ai(model)
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": user_message},
    ]

    if provider == "ollama":
        resp = requests.post(
            f"{OLLAMA_BASE_URL}/api/chat",
            json={"model": model or DEFAULT_AI_MODEL, "messages": messages, "stream": False, "format": "json"},
            timeout=120,
        )
        if resp.status_code == 200:
            return resp.json().get("message", {}).get("content", "")
        raise Exception(f"Ollama error ({resp.status_code}): {resp.text[:300]}")

    elif provider == "gemini":
        if not api_key:
            raise Exception("Gemini API key required")
        model_name = model or "gemini-2.0-flash"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        contents = [{"role": "user", "parts": [{"text": prompt + "\n\nUSER REQUEST:\n" + user_message}]}]
        resp = requests.post(url, json={
            "contents": contents,
            "generationConfig": {"responseMimeType": "application/json"}
        }, timeout=120)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
        raise Exception(f"Gemini error ({resp.status_code}): {resp.text[:300]}")

    elif provider == "chatgpt":
        if not api_key:
            raise Exception("OpenAI API key required")
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model or "gpt-4o-mini",
                "messages": messages,
                "temperature": 0.3,
                "response_format": {"type": "json_object"},
            },
            timeout=120,
        )
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]
        raise Exception(f"OpenAI error ({resp.status_code}): {resp.text[:300]}")

    elif provider == "claude":
        if not api_key:
            raise Exception("Claude API key required")
        payload = {
            "model": model or "claude-sonnet-4-20250514",
            "max_tokens": 4096,
            "system": prompt,
            "messages": [{"role": "user", "content": user_message}],
        }
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "Content-Type": "application/json", "anthropic-version": "2023-06-01"},
            json=payload,
            timeout=120,
        )
        if resp.status_code == 200:
            return resp.json().get("content", [{}])[0].get("text", "")
        raise Exception(f"Claude error ({resp.status_code}): {resp.text[:300]}")

    elif provider == "grok":
        if not api_key:
            raise Exception("Grok API key required")
        resp = requests.post(
            "https://api.x.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model or "grok-3", "messages": messages, "temperature": 0.3},
            timeout=120,
        )
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]
        raise Exception(f"Grok error ({resp.status_code}): {resp.text[:300]}")

    elif provider == "deepseek":
        if not api_key:
            raise Exception("DeepSeek API key required")
        resp = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model or "deepseek-v4-flash", "messages": messages, "temperature": 0.3},
            timeout=120,
        )
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]
        raise Exception(f"DeepSeek error ({resp.status_code}): {resp.text[:300]}")

    elif provider == "openai":
        # Alias for chatgpt
        return call_llm(prompt, user_message, "chatgpt", model, api_key)

    elif provider == "9router":
        headers = {"Content-Type": "application/json"}
        current_key = api_key
        if not current_key or current_key == "9router":
            from tubecli.extensions.cloud_api.extension import key_manager
            current_key = key_manager.get_active_key("9router")
        if current_key:
            headers["Authorization"] = f"Bearer {current_key}"
        resp = requests.post(
            "http://localhost:20128/v1/chat/completions",
            headers=headers,
            json={
                "model": model or "deepseek-v4-flash",
                "messages": messages,
                "temperature": 0.3,
            },
            timeout=120,
        )
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]
        raise Exception(f"9Router error ({resp.status_code}): {resp.text[:300]}")

    else:
        # Check central PROVIDERS map for generic OpenAI compatible fallback
        try:
            from tubecli.extensions.cloud_api.extension import PROVIDERS
            if provider in PROVIDERS:
                p_info = PROVIDERS[provider]
                p_url = p_info.get("base_url")
                if p_url:
                    headers = {"Content-Type": "application/json"}
                    if api_key and api_key != "9router":
                        headers["Authorization"] = f"Bearer {api_key}"
                    resp = requests.post(
                        f"{p_url.rstrip('/')}/chat/completions",
                        headers=headers,
                        json={
                            "model": model or (p_info.get("models")[0] if p_info.get("models") else "gpt-4o-mini"),
                            "messages": messages,
                            "temperature": 0.3,
                        },
                        timeout=120,
                    )
                    if resp.status_code == 200:
                        return resp.json()["choices"][0]["message"]["content"]
                    raise Exception(f"{p_info.get('name', provider)} error ({resp.status_code}): {resp.text[:300]}")
        except Exception as ex:
            raise Exception(f"Provider {provider} failed: {ex}")

        raise Exception(f"Unknown provider: {provider}")


def generate_workflow(prompt: str, provider: str = "ollama", model: str = "", api_key: str = "") -> dict:
    """
    Main entry point: Generate a workflow from a natural language prompt.
    
    Returns:
        dict with 'nodes' and 'connections' ready for WF.fromJSON() on the frontend.
    """
    # 0. Resolve cloud API key if signaled by frontend
    if api_key == "__CLOUD_API__" and provider != "ollama":
        api_key = _resolve_cloud_api_key(provider)

    # 1. Get available node types from registry
    from tubecli.nodes.registry import list_available_nodes
    available_nodes = list_available_nodes()

    # 2. Build port definition map for resolution
    port_defs = _build_port_defs()

    # 3. Build system prompt
    system_prompt = build_system_prompt(available_nodes)

    valid_types = {n["type"] for n in available_nodes}

    def _postprocess(workflow: dict):
        nodes = workflow.get("nodes", [])
        connections = workflow.get("connections", [])
        for nd in nodes:
            if nd.get("type") not in valid_types:
                nd["type"] = "python_code"  # Fallback unknown types to python_code
        _assign_coordinates(nodes)
        if connections:
            connections = resolve_port_connections(nodes, connections, port_defs)
        else:
            connections = auto_connect_sequential(nodes, port_defs)
        return nodes, connections

    # 4. Call LLM → parse → validate; on validation errors give the LLM ONE
    #    chance to self-repair with the concrete issue list as feedback.
    raw_response = call_llm(system_prompt, prompt, provider, model, api_key)
    workflow = _parse_json_response(raw_response)
    nodes, connections = _postprocess(workflow)
    issues = validate_workflow(nodes, connections, port_defs, available_nodes)

    if issues:
        print(f"[AI Workflow] Validation found {len(issues)} issue(s), asking LLM to self-repair...")
        repair_message = (
            f"Your previous workflow JSON had these problems:\n"
            + "\n".join(f"- {i}" for i in issues)
            + "\n\nHere is the JSON you produced:\n"
            + json.dumps({"nodes": nodes, "connections": connections}, ensure_ascii=False)
            + f"\n\nOriginal request: {prompt}\n"
            "Fix ALL the problems and return the corrected full workflow JSON (nodes + connections). JSON only."
        )
        try:
            raw_retry = call_llm(system_prompt, repair_message, provider, model, api_key)
            workflow_retry = _parse_json_response(raw_retry)
            nodes_retry, connections_retry = _postprocess(workflow_retry)
            issues_retry = validate_workflow(nodes_retry, connections_retry, port_defs, available_nodes)
            # Keep the repaired version if it is at least as good
            if len(issues_retry) <= len(issues):
                nodes, connections, issues = nodes_retry, connections_retry, issues_retry
        except Exception as e:
            print(f"[AI Workflow] Self-repair attempt failed, keeping first result: {e}")

    result = {"nodes": nodes, "connections": connections}
    if issues:
        # Surface remaining problems to the UI/caller instead of failing silently
        result["warnings"] = issues
        print(f"[AI Workflow] Remaining warnings: {issues}")
    return result


def _resolve_cloud_api_key(provider: str) -> str:
    """Fetch the real API key from the Cloud API Keys extension."""
    if provider == "9router":
        return "9router"
    try:
        from tubecli.extensions.cloud_api.extension import key_manager
        # Map frontend provider names to cloud_api provider names
        prov_map = {"chatgpt": "openai", "openai": "openai"}
        resolved_prov = prov_map.get(provider, provider)
        key = key_manager.get_active_key(resolved_prov)
        if key:
            return key
    except Exception:
        pass
    raise Exception(f"No API key configured for '{provider}'. Please add one in Cloud API Keys extension.")


def _build_port_defs() -> dict:
    """Build a map of node_type -> {inputs: [names], outputs: [names]}.
    Derived from the live node registry (covers extension nodes too),
    with hand-coded fallbacks for known extension nodes that may not be
    installed at build time."""
    fallbacks = {
        "video_processing": {"inputs": ["input_file", "input_files", "audio_file", "start_time", "end_time", "text", "output_dir"], "outputs": ["output_file", "status"]},
    }
    try:
        from tubecli.nodes.registry import build_port_defs
        defs = build_port_defs()
    except Exception:
        defs = {}
    for k, v in fallbacks.items():
        defs.setdefault(k, v)
    return defs


def _parse_json_response(raw: str) -> dict:
    """Extract and parse JSON from LLM response, handling markdown fences etc."""
    # Try direct parse first
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Try to extract from markdown code fence
    fence_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?\s*```', raw, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError:
            pass

    # Try to find first { ... } block
    brace_match = re.search(r'\{.*\}', raw, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass

    raise Exception(f"Could not parse JSON from AI response: {raw[:200]}...")


def _assign_coordinates(nodes: list):
    """Assign x, y coordinates to nodes if not already set."""
    OFFSET = 25000  # Match canvas OFFSET in workflow.js
    x_step = 350
    y_base = OFFSET + 150

    for i, nd in enumerate(nodes):
        if not nd.get("x") or nd["x"] < 100:
            nd["x"] = OFFSET + 100 + i * x_step
        elif nd["x"] < OFFSET:
            nd["x"] += OFFSET
        if not nd.get("y") or nd["y"] < 100:
            nd["y"] = y_base
        elif nd["y"] < OFFSET:
            nd["y"] += OFFSET


def build_skill_system_prompt(available_nodes: list, skill_mds: list) -> str:
    """
    Build system prompt to generate a new Skill (either Workflow-based or Markdown-based).
    """
    prompt = (
        "You are an AI Skill Architect for TubeCLI.\n"
        "Your task is to convert a user request into a structured Skill definition JSON.\n\n"
        "A Skill can be one of two types:\n"
        "1. **Workflow Skill** (skill_type='Workflow Skill'): Requires executing a graph of nodes. Set this type if the task requires sequential operations (e.g. scrape a URL, save to Sheets, run a local command, loop, etc.).\n"
        "2. **Markdown Skill** (skill_type='Markdown'): A prompt-based/static SOP instruction set. Set this type if the task is a prompt, translation template, writing guide, or reasoning task where no active node execution is required.\n\n"
    )

    # Available nodes
    prompt += "## AVAILABLE WORKFLOW NODES (Use these ONLY for Workflow Skills):\n\n"
    prompt += _render_node_catalog(available_nodes)

    # Python fallback instruction
    prompt += "\n## PYTHON CODE FALLBACK\n"
    prompt += (
        "If no existing node can handle a task, use a `python_code` node in Workflow Skills.\n"
        "Set config.code to valid Python. Assign final value to `result`.\n\n"
    )

    # Extension context
    if skill_mds:
        prompt += "## AVAILABLE SYSTEM EXTENSION CONTEXTS (How to interact with installed extensions):\n\n"
        for ext in skill_mds:
            prompt += f"### Extension: {ext.get('extension')} (v{ext.get('version')})\n"
            prompt += f"{ext.get('skill_md')}\n\n"

    # Format instruction
    prompt += "## OUTPUT FORMAT (STRICT JSON ONLY)\n"
    prompt += "Return a single JSON object with this exact structure:\n"
    prompt += "```json\n"
    prompt += json.dumps({
        "name": "Creative name with emoji",
        "description": "Short description of what the skill does",
        "skill_type": "Workflow Skill",
        "commands": ["command trigger 1", "command trigger 2"],
        "workflow_data": {
            "markdown": "(Only for 'Markdown' type) The detailed markdown prompt/SOP instructions.",
            "nodes": [
                {
                    "id": "node_1",
                    "type": "text_input",
                    "label": "Input URL",
                    "x": 100, "y": 150,
                    "config": {"text": ""}
                }
            ],
            "connections": [
                {"from_node_id": "node_1", "from_port_id": "content", "to_node_id": "node_2", "to_port_id": "text_input"}
            ]
        }
    }, indent=2, ensure_ascii=False)
    prompt += "\n```\n\n"

    # Rules
    prompt += "## CRITICAL RULES\n"
    prompt += "1. For Workflow Skills: nodes and connections must be fully configured. Set skill_type='Workflow Skill'. Set workflow_data.markdown=''.\n"
    prompt += "2. For Markdown Skills: workflow_data.nodes=[] and workflow_data.connections=[]. Set skill_type='Markdown'. Write the full logic in workflow_data.markdown.\n"
    prompt += "3. Trigger keywords in `commands` array must be relevant and in lowercase.\n"
    prompt += "4. JSON ONLY: No markdown fences (except the json block itself), no comments, no intro. Pure JSON.\n"
    return prompt


def generate_skill_with_ai(prompt: str, provider: str = "ollama", model: str = "", api_key: str = "") -> dict:
    """
    Generate a complete Skill (metadata + workflow/markdown) using AI.
    """
    if api_key == "__CLOUD_API__" and provider != "ollama":
        api_key = _resolve_cloud_api_key(provider)

    from tubecli.nodes.registry import list_available_nodes
    from tubecli.core.extension_manager import extension_manager

    available_nodes = list_available_nodes()
    skill_mds = extension_manager.get_all_skill_mds()

    system_prompt = build_skill_system_prompt(available_nodes, skill_mds)
    raw_response = call_llm(system_prompt, f"Generate a skill for the following request:\n{prompt}", provider, model, api_key)
    
    skill_data = _parse_json_response(raw_response)
    
    # Validation/fallback defaults
    skill_data.setdefault("name", "New AI Skill")
    skill_data.setdefault("description", "")
    skill_data.setdefault("skill_type", "Markdown")
    skill_data.setdefault("commands", [])
    
    wf = skill_data.setdefault("workflow_data", {})
    nodes = wf.setdefault("nodes", [])
    connections = wf.setdefault("connections", [])
    wf.setdefault("markdown", "")

    if skill_data["skill_type"] == "Workflow Skill" and nodes:
        valid_types = {n["type"] for n in available_nodes}
        port_defs = _build_port_defs()

        def _postprocess_skill_wf(wf_dict):
            nds = wf_dict.get("nodes", [])
            conns = wf_dict.get("connections", [])
            for nd in nds:
                if nd.get("type") not in valid_types:
                    nd["type"] = "python_code"
            _assign_coordinates(nds)
            if conns:
                conns = resolve_port_connections(nds, conns, port_defs)
            else:
                conns = auto_connect_sequential(nds, port_defs)
            wf_dict["nodes"] = nds
            wf_dict["connections"] = conns
            return nds, conns

        nodes, connections = _postprocess_skill_wf(wf)
        issues = validate_workflow(nodes, connections, port_defs, available_nodes)

        if issues:
            print(f"[AI Skill] Workflow validation found {len(issues)} issue(s), asking LLM to self-repair...")
            repair_message = (
                "Your previous Skill JSON had these workflow problems:\n"
                + "\n".join(f"- {i}" for i in issues)
                + "\n\nHere is the JSON you produced:\n"
                + json.dumps(skill_data, ensure_ascii=False)
                + f"\n\nOriginal request: {prompt}\n"
                "Fix ALL the problems and return the corrected FULL skill JSON (same structure). JSON only."
            )
            try:
                raw_retry = call_llm(system_prompt, repair_message, provider, model, api_key)
                retry_data = _parse_json_response(raw_retry)
                retry_wf = retry_data.get("workflow_data") or {}
                retry_nodes, retry_conns = _postprocess_skill_wf(retry_wf)
                retry_issues = validate_workflow(retry_nodes, retry_conns, port_defs, available_nodes)
                if retry_nodes and len(retry_issues) <= len(issues):
                    retry_data.setdefault("name", skill_data["name"])
                    retry_data.setdefault("description", skill_data["description"])
                    retry_data.setdefault("skill_type", skill_data["skill_type"])
                    retry_data.setdefault("commands", skill_data["commands"])
                    retry_wf.setdefault("markdown", "")
                    skill_data = retry_data
                    wf = retry_wf
                    issues = retry_issues
            except Exception as e:
                print(f"[AI Skill] Self-repair attempt failed, keeping first result: {e}")

        if issues:
            skill_data["workflow_warnings"] = issues
            print(f"[AI Skill] Remaining workflow warnings: {issues}")

    return skill_data
