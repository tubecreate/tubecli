"""
TubeCLI REST API Server
FastAPI-based REST API for agents, skills, and workflows.
"""
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import os, sys
import mimetypes

# Fix Windows registry MIME type bug for CSS/JS/SVG files
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("image/png", ".png")
mimetypes.add_type("image/jpeg", ".jpg")
mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("application/json", ".json")


app = FastAPI(
    title="TubeCLI API",
    description="REST API for TubeCLI — AI Agent management, skills, and workflows.",
    version="0.1.0",
    docs_url="/api/v1/docs",
    redoc_url="/api/v1/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    import sys
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass
    from tubecli.core.telegram_listener import telegram_listener
    telegram_listener.start()

    # Start PageWatcher scheduler (if web_crawler extension has watches)
    try:
        import sys
        from tubecli.config import EXTENSIONS_EXTERNAL_DIR
        wc_dir = os.path.join(str(EXTENSIONS_EXTERNAL_DIR), "web_crawler")
        if os.path.isdir(wc_dir) and wc_dir not in sys.path:
            sys.path.insert(0, wc_dir)
        from watcher import page_watcher
        if page_watcher.list_watches():
            page_watcher.start_scheduler()
            print("[Startup] PageWatcher scheduler started")
    except Exception as e:
        print(f"[Startup] PageWatcher not available: {e}")

@app.on_event("shutdown")
async def shutdown_event():
    from tubecli.core.telegram_listener import telegram_listener
    await telegram_listener.stop()

@app.post("/api/v1/system/shutdown")
async def shutdown_server():
    """Trigger a graceful shutdown of the TubeCLI server."""
    import threading
    import time
    def _shutdown():
        time.sleep(1)
        cli_pid = os.environ.get("TUBECLI_CLI_PID")
        if cli_pid:
            try:
                import signal
                if os.name == 'nt':
                    os.system(f"taskkill /F /PID {cli_pid}")
                else:
                    os.kill(int(cli_pid), signal.SIGTERM)
            except Exception:
                pass
        os._exit(0)
    threading.Thread(target=_shutdown).start()
    return {"status": "success", "message": "Server is shutting down..."}

# ── Pydantic Models ──────────────────────────────────────────────

class AgentCreateRequest(BaseModel):
    name: str
    description: str = ""
    system_prompt: str = "You are a helpful AI assistant."
    model: Optional[str] = None
    
    # New Fields
    allowed_skills: Optional[List[str]] = None
    avatar_icon: Optional[str] = "SMART_TOY"
    avatar_type: Optional[str] = "bot"
    avatar_color: Optional[str] = "blue"
    browser_ai_model: Optional[str] = "qwen:latest"
    telegram_token: Optional[str] = ""
    telegram_chat_id: Optional[str] = ""
    messenger_token: Optional[str] = ""
    messenger_page_id: Optional[str] = ""
    messenger_php_url: Optional[str] = ""
    direct_trigger_skill_id: Optional[str] = ""
    persona: Optional[Dict] = {}
    routine: Optional[Dict] = {}
    thinking_map: Optional[Dict] = {}
    allowed_profiles: Optional[List[str]] = []
    proxy_config: Optional[str] = ""
    proxy_provider: Optional[Dict] = {"mode": "static"}
    timezone: Optional[str] = None
    auth: Optional[Dict] = {}
    cloud_api_keys: Optional[Dict] = {}
    enable_scraping: Optional[bool] = False
    scraper_text_limit: Optional[int] = 10000
    script_output_format: Optional[str] = "json"

class AgentGenerateRequest(BaseModel):
    name: str = ""
    description: str = ""
    provider: str = "ollama"
    model: str = "qwen:latest"
    api_key: Optional[str] = None
    output_target_prefix: str = "ai"

class ExtensionUpdateRequest(BaseModel):
    port: Optional[int] = None

class AgentUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    model: Optional[str] = None
    allowed_skills: Optional[List[str]] = None
    avatar_icon: Optional[str] = None
    avatar_type: Optional[str] = None
    avatar_color: Optional[str] = None
    browser_ai_model: Optional[str] = None
    telegram_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    messenger_token: Optional[str] = None
    messenger_page_id: Optional[str] = None
    messenger_php_url: Optional[str] = None
    direct_trigger_skill_id: Optional[str] = None
    persona: Optional[Dict] = None
    routine: Optional[Dict] = None
    thinking_map: Optional[Dict] = None
    allowed_profiles: Optional[List[str]] = None
    proxy_config: Optional[str] = None
    proxy_provider: Optional[Dict] = None
    timezone: Optional[str] = None
    auth: Optional[Dict] = None
    cloud_api_keys: Optional[Dict] = None
    enable_scraping: Optional[bool] = None
    scraper_text_limit: Optional[int] = None
    script_output_format: Optional[str] = None

class SkillCreateRequest(BaseModel):
    name: str
    description: str = ""
    workflow_data: Dict = {}
    skill_type: str = "Skill"

class WorkflowGenerateRequest(BaseModel):
    prompt: str
    provider: str = "ollama"
    model: str = ""
    api_key: str = ""

class WorkflowRunRequest(BaseModel):
    workflow_data: Dict
    input_text: str = ""

class WorkflowSaveRequest(BaseModel):
    name: str
    workflow_data: Dict


# ── Health ───────────────────────────────────────────────────────

@app.get("/api/v1/health")
async def health():
    from tubecli.config import get_api_port
    return {"status": "ok", "message": "TubeCLI API is running", "port": get_api_port()}


# ── Version & Update ──────────────────────────────────────────────

@app.get("/api/v1/version")
async def get_version_info():
    import subprocess
    from tubecli import __version__, __build__
    info = {"version": __version__, "build": __build__, "pip_version": __version__, "git_hash": None, "git_branch": None}
    try:
        repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        h = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=repo, timeout=3)
        b = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True, cwd=repo, timeout=3)
        if h.returncode == 0: info["git_hash"] = h.stdout.strip()
        if b.returncode == 0: info["git_branch"] = b.stdout.strip()
    except Exception:
        pass
    return info

@app.post("/api/v1/version/update")
async def perform_git_update():
    """Safe update: git pull + install only missing deps + restart.
    Mirrors the init_cmd.py option-9 logic. Never runs 'pip install -e .'
    which would break the running installation.
    """
    import subprocess, re, threading, time
    from tubecli import __build__
    from tubecli.config import BASE_DIR
    try:
        repo = str(BASE_DIR)

        # Step 1: git pull
        r = subprocess.run(["git", "pull"], capture_output=True, text=True, cwd=repo, timeout=60)
        pull_output = r.stdout.strip() or r.stderr.strip()
        if r.returncode != 0:
            return {"status": "error", "output": f"git pull failed: {pull_output}"}

        # Step 2: Check which files changed to determine if deps need updating
        changed_files = []
        try:
            r_diff = subprocess.run(
                ["git", "diff", "--name-only", "HEAD~1..HEAD"],
                capture_output=True, text=True, cwd=repo, timeout=10,
            )
            if r_diff.returncode == 0:
                changed_files = [f.strip() for f in r_diff.stdout.strip().split("\n") if f.strip()]
        except Exception:
            pass

        deps_changed = any(f in ("pyproject.toml", "requirements.txt", "setup.py", "setup.cfg") for f in changed_files)
        pip_output = ""

        # Step 3: Smart dependency check — only if pyproject.toml or requirements.txt changed
        if deps_changed:
            required_packages = set()
            # From pyproject.toml
            pyproject_path = os.path.join(repo, "pyproject.toml")
            if os.path.exists(pyproject_path):
                try:
                    with open(pyproject_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    in_deps = False
                    for line in content.splitlines():
                        stripped = line.strip()
                        if stripped.startswith("dependencies"):
                            in_deps = True
                            continue
                        if in_deps:
                            if stripped == "]":
                                break
                            match = re.match(r'^\s*"([a-zA-Z0-9_-]+)', stripped)
                            if match:
                                required_packages.add(match.group(1).lower().replace("-", "_"))
                except Exception:
                    pass

            # From requirements.txt
            req_path = os.path.join(repo, "requirements.txt")
            if os.path.exists(req_path):
                try:
                    with open(req_path, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if line and not line.startswith("#"):
                                pkg = re.split(r"[>=<!\[\];]", line)[0].strip().lower().replace("-", "_")
                                if pkg:
                                    required_packages.add(pkg)
                except Exception:
                    pass

            if required_packages:
                # Get installed packages
                installed = set()
                try:
                    r_pip = subprocess.run(
                        [sys.executable, "-m", "pip", "list", "--format=columns"],
                        capture_output=True, text=True, timeout=30,
                    )
                    if r_pip.returncode == 0:
                        for line in r_pip.stdout.splitlines()[2:]:
                            parts = line.split()
                            if parts:
                                installed.add(parts[0].lower().replace("-", "_"))
                except Exception:
                    pass

                missing = required_packages - installed
                if missing:
                    pip_r = subprocess.run(
                        [sys.executable, "-m", "pip", "install", *sorted(missing), "--quiet"],
                        capture_output=True, text=True, timeout=120,
                    )
                    pip_output = f"Installed {len(missing)} new package(s): {', '.join(sorted(missing))}"
                else:
                    pip_output = "All dependencies already satisfied."
            else:
                pip_output = "No dependencies to check."
        else:
            pip_output = "No dependency files changed, skipping pip."

        # Step 4: Read updated version from file
        new_version = __build__
        try:
            init_file = os.path.join(repo, "tubecli", "__init__.py")
            with open(init_file, "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("__version__"):
                        new_version = line.split("=")[1].strip().strip('"').strip("'")
                        break
        except Exception:
            pass

        # Step 5: Schedule restart — kill CLI parent process after response is sent
        # The CLI init_cmd.py menu loop will detect termination and the user
        # double-clicks the shortcut or runs 'tubecli init' again.
        restart_flag = os.path.join(repo, ".restarted")
        try:
            with open(restart_flag, "w") as f:
                f.write("1")
        except Exception:
            pass

        def _delayed_restart():
            time.sleep(2)
            cli_pid = os.environ.get("TUBECLI_CLI_PID")
            if cli_pid:
                try:
                    if os.name == 'nt':
                        os.system(f"taskkill /F /PID {cli_pid}")
                    else:
                        import signal
                        os.kill(int(cli_pid), signal.SIGTERM)
                except Exception:
                    pass
            # Restart CLI in a new process
            try:
                if os.name == 'nt':
                    CREATE_NO_WINDOW = 0x08000000
                    subprocess.Popen(
                        f'start "TubeCLI" cmd /k "cd /d {repo} && python -m tubecli.main init"',
                        shell=True, cwd=repo,
                    )
                else:
                    subprocess.Popen(
                        [sys.executable, "-m", "tubecli.main", "init"],
                        cwd=repo, start_new_session=True,
                    )
            except Exception:
                pass
            time.sleep(1)
            os._exit(0)

        threading.Thread(target=_delayed_restart, daemon=True).start()

        return {
            "status": "success",
            "output": pull_output,
            "pip_output": pip_output,
            "version": new_version,
            "restarting": True,
        }
    except Exception as e:
        return {"status": "error", "output": str(e)}

VERSION_CHECK_CACHE = {"data": None}

@app.get("/api/v1/version/check")
async def check_for_updates():
    """Check GitHub for newer version by reading pyproject.toml from main branch (checked once per server startup)."""
    global VERSION_CHECK_CACHE
    if VERSION_CHECK_CACHE["data"] is not None:
        return VERSION_CHECK_CACHE["data"]

    import httpx, re
    from tubecli import __version__
    print(f"[VersionCheck] Local version: {__version__}")
    try:
        raw_url = "https://raw.githubusercontent.com/tubecreate/tubecli/main/pyproject.toml"
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(raw_url)
            if resp.status_code != 200:
                print(f"[VersionCheck] GitHub returned {resp.status_code}")
                res = {"has_update": False, "error": f"GitHub returned {resp.status_code}"}
                VERSION_CHECK_CACHE["data"] = res
                VERSION_CHECK_CACHE["last_check"] = now
                return res
            text = resp.text
            # Match version specifically under [project] section to avoid false matches
            m = re.search(r'^\[project\].*?^version\s*=\s*"([^"]+)"', text, re.MULTILINE | re.DOTALL)
            if not m:
                # Fallback: match first version = "..." in file
                m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
            if not m:
                print("[VersionCheck] Could not parse version from GitHub pyproject.toml")
                res = {"has_update": False, "error": "Could not parse version"}
                VERSION_CHECK_CACHE["data"] = res
                VERSION_CHECK_CACHE["last_check"] = now
                return res
            remote_version = m.group(1)
            print(f"[VersionCheck] Remote version: {remote_version}")
            # Version comparison (supports N-part dotted versions like 2026.05.18.151200)
            try:
                local_parts = [int(x) for x in __version__.split(".")]
                remote_parts = [int(x) for x in remote_version.split(".")]
                has_update = remote_parts > local_parts
            except ValueError:
                # Fallback string comparison if parts are non-numeric
                has_update = remote_version != __version__
            print(f"[VersionCheck] has_update={has_update}")
            res = {
                "has_update": has_update,
                "current_version": __version__,
                "remote_version": remote_version,
            }
            VERSION_CHECK_CACHE["data"] = res
            VERSION_CHECK_CACHE["last_check"] = now
            return res
    except Exception as e:
        print(f"[VersionCheck] Error: {e}")
        res = {"has_update": False, "error": str(e)}
        VERSION_CHECK_CACHE["data"] = res
        VERSION_CHECK_CACHE["last_check"] = now
        return res


# ── Agents ───────────────────────────────────────────────────────

@app.get("/api/v1/agents")
async def list_agents():
    from tubecli.core.agent import agent_manager
    agents = agent_manager.get_all()
    return {"agents": [a.to_dict() for a in agents], "count": len(agents)}

@app.post("/api/v1/agents/generate")
async def generate_agent_with_ai(req: AgentGenerateRequest):
    from tubecli.core.ai_generator import generate_agent_json
    try:
        data = generate_agent_json(
            name=req.name,
            description=req.description,
            provider=req.provider,
            model=req.model,
            api_key=req.api_key or ""
        )
        return {"status": "success", "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/agents/{agent_id}")
async def get_agent(agent_id: str):
    from tubecli.core.agent import agent_manager
    agent = agent_manager.get(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent {agent_id} not found")
    return agent.to_dict()

@app.post("/api/v1/agents")
async def create_agent(req: AgentCreateRequest):
    from tubecli.core.agent import agent_manager
    agent = agent_manager.create(**req.model_dump(exclude_none=True))
    return {"status": "created", "agent": agent.to_dict()}

@app.put("/api/v1/agents/{agent_id}")
async def update_agent(agent_id: str, req: AgentUpdateRequest):
    from tubecli.core.agent import agent_manager
    agent = agent_manager.update(agent_id, **req.model_dump(exclude_none=True))
    if not agent:
        raise HTTPException(404, f"Agent {agent_id} not found")
    return {"status": "updated", "agent": agent.to_dict()}

@app.delete("/api/v1/agents/{agent_id}")
async def delete_agent(agent_id: str):
    from tubecli.core.agent import agent_manager
    if not agent_manager.delete(agent_id):
        raise HTTPException(404, f"Agent {agent_id} not found")
    return {"status": "deleted", "agent_id": agent_id}


# ── Agent Chat ───────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str


# ── AI Proxy Endpoint for Browser Extension ──
@app.post("/api/v1/localai/chat/completions")
async def localai_chat_completions(req: Request):
    """
    Proxy endpoint used by browser extension (ai_engine.js).
    Routes to the correct AI provider based on Global Settings default_model.
    """
    import requests as _requests
    from tubecli.config import get_setting

    data = await req.json()
    messages = data.get("messages", [])

    # Read default model: try global_settings.json first, then settings.json
    import os as _os, json as _json
    from tubecli.config import DATA_DIR
    model = ""
    global_settings_file = _os.path.join(str(DATA_DIR), "global_settings.json")
    if _os.path.exists(global_settings_file):
        try:
            with open(global_settings_file, "r", encoding="utf-8") as f:
                gs = _json.load(f)
                model = gs.get("default_model", "")
        except Exception:
            pass
    if not model:
        model = get_setting("default_model", "qwen:latest")
    lower_model = model.lower()

    # Determine provider from model name
    provider = "ollama"
    if "gemini" in lower_model:
        provider = "gemini"
    elif "gpt" in lower_model or "o1" in lower_model or "o3" in lower_model:
        provider = "chatgpt"
    elif "claude" in lower_model:
        provider = "claude"
    elif "deepseek" in lower_model:
        provider = "deepseek"
    elif "grok" in lower_model:
        provider = "grok"

    # Get first active API key for provider from cloud_api_keys.json
    api_key = ""
    cloud_keys_file = _os.path.join(str(DATA_DIR), "cloud_api_keys.json")
    cloud_keys = {}
    if _os.path.exists(cloud_keys_file):
        try:
            with open(cloud_keys_file, "r", encoding="utf-8") as f:
                cloud_keys = _json.load(f)
        except Exception:
            pass
    if provider in cloud_keys:
        val = cloud_keys[provider]
        if isinstance(val, str) and val:
            # Legacy plain-string key format
            api_key = val
        elif isinstance(val, dict):
            for label, info in val.items():
                if isinstance(info, dict) and info.get("active", True):
                    api_key = info.get("key", "") or info.get("api_key", "")
                    if api_key:
                        break

    print(f"[AI Proxy] provider={provider} model={model} has_key={bool(api_key)}")

    response_content = ""
    try:
        if provider == "deepseek":
            if not api_key:
                raise Exception("No API key for Deepseek")
            resp = _requests.post(
                "https://api.deepseek.com/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": model, "messages": messages, "stream": False},
                timeout=180,
            )
            if resp.status_code == 200:
                response_content = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
            else:
                raise Exception(f"Deepseek {resp.status_code}: {resp.text[:300]}")

        elif provider == "gemini":
            if not api_key:
                raise Exception("No API key for Gemini")
            model_name = model if "gemini" in model else "gemini-2.0-flash"
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
            contents = []
            for msg in messages:
                role = "user" if msg["role"] in ("user", "system") else "model"
                contents.append({"role": role, "parts": [{"text": msg["content"]}]})
            resp = _requests.post(url, json={"contents": contents}, timeout=120)
            if resp.status_code == 200:
                response_content = resp.json().get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            else:
                raise Exception(f"Gemini {resp.status_code}: {resp.text[:300]}")

        elif provider == "chatgpt":
            if not api_key:
                raise Exception("No API key for OpenAI")
            resp = _requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": model or "gpt-4o-mini", "messages": messages, "temperature": 0.5},
                timeout=120,
            )
            if resp.status_code == 200:
                response_content = resp.json()["choices"][0]["message"]["content"]
            else:
                raise Exception(f"OpenAI {resp.status_code}: {resp.text[:300]}")

        elif provider == "claude":
            if not api_key:
                raise Exception("No API key for Claude")
            system_text = ""
            chat_msgs = []
            for msg in messages:
                if msg["role"] == "system":
                    system_text = msg["content"]
                else:
                    chat_msgs.append(msg)
            payload = {"model": model or "claude-sonnet-4-20250514", "max_tokens": 4096, "messages": chat_msgs}
            if system_text:
                payload["system"] = system_text
            resp = _requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": api_key, "Content-Type": "application/json", "anthropic-version": "2023-06-01"},
                json=payload, timeout=120,
            )
            if resp.status_code == 200:
                response_content = resp.json().get("content", [{}])[0].get("text", "")
            else:
                raise Exception(f"Claude {resp.status_code}: {resp.text[:300]}")

        elif provider == "grok":
            if not api_key:
                raise Exception("No API key for Grok")
            resp = _requests.post(
                "https://api.x.ai/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": model or "grok-3", "messages": messages, "temperature": 0.5},
                timeout=120,
            )
            if resp.status_code == 200:
                response_content = resp.json()["choices"][0]["message"]["content"]
            else:
                raise Exception(f"Grok {resp.status_code}: {resp.text[:300]}")

        else:
            # Ollama (local)
            from tubecli.config import OLLAMA_BASE_URL
            resp = _requests.post(
                f"{OLLAMA_BASE_URL}/api/chat",
                json={"model": model, "messages": messages, "stream": False},
                timeout=120,
            )
            if resp.status_code == 200:
                response_content = resp.json().get("message", {}).get("content", "")
            else:
                raise Exception(f"Ollama {resp.status_code}: {resp.text[:300]}")

    except Exception as e:
        print(f"[AI Proxy] Error: {e}")
        response_content = f"Error: {e}"

    # Return OpenAI-compatible JSON for ai_engine.js
    return {
        "id": "chatcmpl-proxy",
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": response_content},
                "finish_reason": "stop"
            }
        ]
    }


@app.post("/api/v1/localai/generate")
async def localai_generate(req: Request):
    """
    Proxy endpoint for Ollama-style text generation (/api/generate).
    Used by browser extension (ai_engine.js) as fallback.
    Converts to chat/completions format internally.
    """
    data = await req.json()
    prompt = data.get("prompt", "")
    model = data.get("model", "")

    if not model:
        import os as _os, json as _json
        from tubecli.config import DATA_DIR, get_setting
        global_settings_file = _os.path.join(str(DATA_DIR), "global_settings.json")
        if _os.path.exists(global_settings_file):
            try:
                with open(global_settings_file, "r", encoding="utf-8") as f:
                    gs = _json.load(f)
                    model = gs.get("default_model", "")
            except Exception:
                pass
        if not model:
            model = get_setting("default_model", "qwen:latest")

    # Reuse the chat/completions logic by constructing a chat request
    from starlette.requests import Request as _Request
    from starlette.datastructures import Headers as _Headers
    import json as _json

    chat_body = _json.dumps({
        "messages": [{"role": "user", "content": prompt}],
        "model": model,
    }).encode()

    # Create a sub-request to reuse localai_chat_completions
    scope = req.scope.copy()
    scope["body"] = chat_body

    class FakeRequest:
        async def json(self_inner):
            return {"messages": [{"role": "user", "content": prompt}], "model": model}

    result = await localai_chat_completions(FakeRequest())

    # Convert chat format to generate format
    response_text = ""
    if isinstance(result, dict):
        choices = result.get("choices", [])
        if choices:
            response_text = choices[0].get("message", {}).get("content", "")

    return {
        "model": model,
        "response": response_text,
        "done": True,
    }


@app.post("/api/v1/agents/{agent_id}/chat")
async def agent_chat(agent_id: str, req: ChatRequest):
    """Chat with an agent. The brain dispatches skills automatically."""
    import datetime as _dt
    from tubecli.core.agent import agent_manager
    from tubecli.core.skill import skill_manager
    from tubecli.core.brain import AgentBrain

    agent = agent_manager.get(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent {agent_id} not found")

    agent_dict = agent.to_dict()

    # Get agent's allowed skills
    all_skills = skill_manager.get_all()
    if agent.allowed_skills:
        skills = [s.to_dict() for s in all_skills if s.id in agent.allowed_skills]
    else:
        skills = [s.to_dict() for s in all_skills]  # allow all if not restricted

    # Call brain
    brain_result = AgentBrain.chat(
        message=req.message,
        agent=agent_dict,
        skills=skills,
        history=agent.history_log or [],
    )

    reply = brain_result["reply"]
    skill_used = None

    # ── Handle Brain Result ──
    action = brain_result.get("action")
    
    if action == "run_skill" and brain_result.get("skill_id"):
        skill_id = brain_result["skill_id"]
        skill = skill_manager.get(skill_id)
        if skill:
            skill_used = skill.name
            skill_input = brain_result.get("skill_input", req.message)
            
            # Feature: Random Browser Profile Selection
            # If input mentions "random profile" or "ngẫu nhiên", and it's a browser skill
            if any(x in skill_input.lower() for x in ["ngẫu nhiên", "random profile", "mở profile"]):
                from tubecli.core.config import config_manager
                profiles = config_manager.get_browser_profiles()
                if profiles:
                    import random
                    chosen = random.choice(profiles)
                    skill_input += f"\n(AI Note: Randomly selected browser profile: {chosen})"
            
            try:
                # Call the Autonomous ReAct Loop
                skill_dict = skill.to_dict()
                final_answer = await AgentBrain.autonomous_run(
                    message=skill_input,
                    agent=agent_dict,
                    skill=skill_dict
                )
                reply = final_answer
                skill_manager.update(skill_id, last_run=_dt.datetime.now().isoformat())
            except Exception as e:
                from tubecli.i18n import t
                reply = t("brain.skill_run_error", name=skill.name, error=str(e))
        else:
            from tubecli.i18n import t
            reply = t("brain.skill_not_found", id=skill_id)

    elif action == "create_skill":
        # Feature: AI Self-Creation via Workflow Builder
        # 1. Generate real executable workflow from the user's request
        # 2. Run it immediately to handle the current request
        # 3. Save as a reusable skill for future similar requests
        from tubecli.core.ai_workflow_builder import generate_workflow
        from tubecli.core.workflow_engine import WorkflowEngine
        from tubecli.nodes.registry import create_node_from_dict

        action_data_raw = brain_result.get("_raw_action", {})
        skill_name = action_data_raw.get("name") or brain_result.get("skill_name", "New Skill")
        skill_desc = action_data_raw.get("description") or brain_result.get("skill_desc", "")
        skill_instructions = action_data_raw.get("instructions") or brain_result.get("skill_instructions", [])

        # Determine provider/model from agent config
        wf_provider = agent_dict.get("provider", "ollama")
        wf_model = agent_dict.get("model", "") or agent_dict.get("chatbot_model", "")
        wf_api_key = agent_dict.get("api_key", "")
        if not wf_provider or wf_provider == "local":
            wf_provider = "ollama"

        wf_data = None
        wf_result = None
        try:
            # Build enriched prompt: original request + instructions hint
            gen_prompt = req.message
            if skill_instructions:
                gen_prompt += "\n\nHints: " + "; ".join(skill_instructions)

            # Generate the workflow
            wf_data = generate_workflow(
                prompt=gen_prompt,
                provider=wf_provider,
                model=wf_model,
                api_key=wf_api_key or "__CLOUD_API__",
            )

            # Run the workflow immediately for the user's current request
            nodes_data = wf_data.get("nodes", [])
            connections = wf_data.get("connections", [])
            if nodes_data:
                # Inject user message into first text_input node
                for nd in nodes_data:
                    if nd.get("type") in ("text_input", "manual_input"):
                        nd.setdefault("config", {})["text"] = req.message
                        break

                wf_nodes = [create_node_from_dict(nd) for nd in nodes_data]
                engine = WorkflowEngine(nodes=wf_nodes, connections=connections)
                wf_result = await engine.run()

        except Exception as wf_err:
            print(f"[AutoSkill] Workflow generate/run failed: {wf_err}")

        # Derive trigger commands from skill name + instructions
        trigger_cmds = [skill_name.lower()]
        for instr in (skill_instructions or []):
            words = [w.lower() for w in instr.split() if len(w) > 3]
            if words:
                trigger_cmds.append(" ".join(words[:3]))
        trigger_cmds = list(set(trigger_cmds))[:5]

        # Save as skill (create or update)
        try:
            existing_skill = skill_manager.find_by_name(skill_name)
            if existing_skill and wf_data:
                skill_manager.update(
                    existing_skill.id,
                    workflow_data=wf_data,
                    description=skill_desc or f"AI-generated: {skill_name}",
                    commands=trigger_cmds,
                )
                new_skill = existing_skill
            else:
                new_skill = skill_manager.create(
                    name=skill_name,
                    description=skill_desc or f"AI-generated workflow skill: {skill_name}",
                    skill_type="AI Workflow",
                    workflow_data=wf_data or {
                        "sop": "\n".join(skill_instructions or []),
                        "nodes": []
                    },
                    commands=trigger_cmds,
                )
            skill_used = f"Created Skill: {skill_name}"

            # Build reply from workflow result or confirmation message
            if wf_result and wf_result.get("status") == "completed":
                # Extract output from last node
                node_results = wf_result.get("node_results", {})
                output_texts = []
                for nid, nr in node_results.items():
                    if isinstance(nr, dict):
                        for key in ("result", "response", "stdout", "rows", "output"):
                            if nr.get(key):
                                output_texts.append(str(nr[key])[:500])
                                break
                    elif nr:
                        output_texts.append(str(nr)[:500])
                if output_texts:
                    reply = "\n".join(output_texts)
                    reply += f"\n\n✅ *Đã lưu thành skill '{skill_name}'* — lần sau hỏi tương tự sẽ dùng ngay."
                else:
                    reply = f"✅ Đã tạo và chạy workflow cho '{skill_name}'.\nĐã lưu thành skill để dùng lại."
            else:
                reply = (
                    f"✅ Đã tạo skill **{skill_name}**\n"
                    f"📝 {skill_desc}\n"
                    f"🔑 Triggers: `{'`, `'.join(trigger_cmds)}`\n\n"
                    f"Lần sau hỏi tương tự AI sẽ chạy skill này ngay lập tức."
                )

        except Exception as e:
            from tubecli.i18n import t
            reply = t("brain.skill_create_error", error=str(e))

    # Save to history
    history = agent.history_log or []
    history.append({"role": "user", "content": req.message, "timestamp": _dt.datetime.now().isoformat()})
    history.append({"role": "assistant", "content": reply, "timestamp": _dt.datetime.now().isoformat(),
                     "skill_used": skill_used})

    # Keep history manageable (last 50 messages)
    if len(history) > 50:
        history = history[-50:]

    agent_manager.update(agent_id, history_log=history)

    # ── Background Memory Update (non-blocking) ──
    import asyncio
    async def _bg_memory_update():
        try:
            from tubecli.core.brain import AgentBrain
            AgentBrain.post_chat_memory_update(agent_id, agent_dict, history)
            # If history was marked summarized, save it back
            agent_manager.update(agent_id, history_log=history)
        except Exception as e:
            print(f"[Memory] Background update error: {e}")
    asyncio.create_task(_bg_memory_update())

    return {
        "reply": reply,
        "skill_used": skill_used,
        "history": history[-20:],  # return last 20 for UI
    }


@app.delete("/api/v1/agents/{agent_id}/chat")
async def clear_chat_history(agent_id: str):
    """Clear an agent's chat history."""
    from tubecli.core.agent import agent_manager
    agent = agent_manager.get(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent {agent_id} not found")
    agent_manager.update(agent_id, history_log=[])
    return {"status": "cleared", "agent_id": agent_id}


# ── Agent Memory API ─────────────────────────────────────────────

@app.get("/api/v1/agents/{agent_id}/memory")
async def get_agent_memory(agent_id: str):
    """Get full memory overview for an agent (sessions + knowledge)."""
    from tubecli.core.agent import agent_manager
    from tubecli.core.memory import AgentMemory
    agent = agent_manager.get(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent {agent_id} not found")
    return AgentMemory.get_full_memory(agent_id)


@app.delete("/api/v1/agents/{agent_id}/memory")
async def clear_agent_memory(agent_id: str):
    """Clear all memory for an agent (sessions + knowledge)."""
    from tubecli.core.agent import agent_manager
    from tubecli.core.memory import AgentMemory
    agent = agent_manager.get(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent {agent_id} not found")
    AgentMemory.clear_all(agent_id)
    return {"status": "cleared", "agent_id": agent_id}


@app.get("/api/v1/agents/{agent_id}/memory/sessions")
async def get_agent_sessions(agent_id: str):
    """Get session summaries for an agent."""
    from tubecli.core.memory import SessionMemory
    sessions = SessionMemory.get_recent_sessions(agent_id, limit=20)
    return {"agent_id": agent_id, "sessions": sessions, "count": len(sessions)}


@app.get("/api/v1/agents/{agent_id}/memory/knowledge")
async def get_agent_knowledge(agent_id: str):
    """Get knowledge facts for an agent."""
    from tubecli.core.memory import KnowledgeMemory
    facts = KnowledgeMemory.get_knowledge(agent_id)
    return {"agent_id": agent_id, "knowledge": facts, "count": len(facts)}


class AddFactRequest(BaseModel):
    fact: str
    category: str = "technical"
    importance: str = "medium"


@app.post("/api/v1/agents/{agent_id}/memory/knowledge")
async def add_agent_fact(agent_id: str, req: AddFactRequest):
    """Manually add a knowledge fact for an agent."""
    from tubecli.core.agent import agent_manager
    from tubecli.core.memory import KnowledgeMemory
    agent = agent_manager.get(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent {agent_id} not found")
    KnowledgeMemory.add_fact(agent_id, req.fact, req.category, req.importance)
    return {"status": "added", "agent_id": agent_id, "fact": req.fact}


# ── Team Memory API ──────────────────────────────────────────────

@app.get("/api/v1/teams/{team_id}/memory")
async def get_team_memory(team_id: str):
    """Get team shared memory (briefings + knowledge)."""
    from tubecli.core.memory import TeamMemory
    return {
        "team_id": team_id,
        "briefings": TeamMemory.get_briefings(team_id, limit=10),
        "knowledge": TeamMemory.get_team_knowledge(team_id),
    }


class TeamBriefingRequest(BaseModel):
    briefing: str
    context: Dict = {}


@app.post("/api/v1/teams/{team_id}/memory/briefing")
async def add_team_briefing(team_id: str, req: TeamBriefingRequest):
    """Add a task briefing for a team."""
    from tubecli.core.memory import TeamMemory
    TeamMemory.save_briefing(team_id, req.briefing, req.context)
    return {"status": "added", "team_id": team_id}


@app.delete("/api/v1/teams/{team_id}/memory")
async def clear_team_memory(team_id: str):
    """Clear all team memory."""
    from tubecli.core.memory import TeamMemory
    TeamMemory.clear(team_id)
    return {"status": "cleared", "team_id": team_id}


# ── Skills ───────────────────────────────────────────────────────

@app.get("/api/v1/skills")
async def list_skills():
    from tubecli.core.skill import skill_manager
    skills = skill_manager.get_all()
    return {"skills": [s.to_dict() for s in skills], "count": len(skills)}

@app.get("/api/v1/skills/{skill_id}")
async def get_skill(skill_id: str):
    from tubecli.core.skill import skill_manager
    skill = skill_manager.get(skill_id)
    if not skill:
        raise HTTPException(404, f"Skill {skill_id} not found")
    return skill.to_dict()

@app.post("/api/v1/skills")
async def create_skill(req: SkillCreateRequest):
    from tubecli.core.skill import skill_manager
    skill = skill_manager.create(**req.model_dump())
    return {"status": "created", "skill": skill.to_dict()}

@app.delete("/api/v1/skills/{skill_id}")
async def delete_skill(skill_id: str):
    from tubecli.core.skill import skill_manager
    if not skill_manager.delete(skill_id):
        raise HTTPException(404, f"Skill {skill_id} not found")
    return {"status": "deleted", "skill_id": skill_id}


class SaveAsSkillRequest(BaseModel):
    id: Optional[str] = None
    name: str
    description: str = ""
    trigger: str = ""
    workflow_data: Dict = {}
    skill_type: str = "Workflow Skill"


@app.post("/api/v1/workflows/save-as-skill")
async def save_workflow_as_skill(req: SaveAsSkillRequest):
    """Convert a workflow into a reusable Skill that Agents can execute."""
    from tubecli.core.skill import skill_manager

    if not req.name:
        raise HTTPException(400, "Skill name is required")

    commands = [req.trigger.strip()] if req.trigger and req.trigger.strip() else []

    if req.id:
        existing = skill_manager.get(req.id)
        if existing:
            skill_manager.update(
                existing.id,
                name=req.name,
                workflow_data=req.workflow_data,
                description=req.description,
                commands=commands,
            )
            return {"status": "updated", "skill": existing.to_dict(), "message": f"Skill '{req.name}' updated"}

    # Check if name already exists as fallback
    existing_by_name = skill_manager.find_by_name(req.name)
    if existing_by_name:
        skill_manager.update(
            existing_by_name.id,
            workflow_data=req.workflow_data,
            description=req.description,
            commands=commands,
        )
        return {"status": "updated", "skill": existing_by_name.to_dict(), "message": f"Skill '{req.name}' updated (by name)"}

    skill = skill_manager.create(
        name=req.name,
        description=req.description or f"Workflow skill: {req.name}",
        skill_type=req.skill_type,
        workflow_data=req.workflow_data,
        commands=commands
    )
    return {"status": "created", "skill": skill.to_dict(), "message": f"Skill '{req.name}' created successfully"}


@app.post("/api/v1/skills/{skill_id}/run")
async def run_skill(skill_id: str, input_text: str = ""):
    """Run a skill by executing its stored workflow. Returns error guidance for AI agents."""
    from tubecli.core.skill import skill_manager
    from tubecli.nodes.registry import create_node_from_dict
    from tubecli.core.workflow_engine import WorkflowEngine

    skill = skill_manager.get(skill_id)
    if not skill:
        raise HTTPException(404, f"Skill {skill_id} not found")

    wf = skill.workflow_data
    nodes_data = wf.get("nodes", [])
    connections = wf.get("connections", [])

    if not nodes_data:
        raise HTTPException(400, "Skill has no workflow nodes")

    if input_text:
        for nd in nodes_data:
            if nd.get("type") in ("text_input", "manual_input"):
                nd.setdefault("config", {})["text"] = input_text

    try:
        nodes = [create_node_from_dict(nd) for nd in nodes_data]
    except Exception as e:
        raise HTTPException(400, f"Node creation error: {e}")

    engine = WorkflowEngine(nodes=nodes, connections=connections)
    result = await engine.run()

    # Update last_run
    import datetime
    skill_manager.update(skill_id, last_run=datetime.datetime.now().isoformat())

    # Collect error guidance from node results for AI agents
    errors = []
    guidance = []
    if result.get("logs"):
        for log in result["logs"]:
            if log.get("status") == "error" or "Error" in str(log.get("message", "")):
                errors.append({"node": log.get("node_name", ""), "error": log.get("message", "")})
    if result.get("node_results"):
        for node_id, node_result in result["node_results"].items():
            if isinstance(node_result, dict):
                if node_result.get("_error_guidance"):
                    guidance.append(node_result["_error_guidance"])
                if "Error" in str(node_result.get("status", "")):
                    errors.append({"node": node_id, "error": node_result.get("status", "")})

    if errors or guidance:
        from tubecli.i18n import t
        result["_skill_errors"] = errors
        result["_skill_guidance"] = guidance or [
            t("brain.workflow_error_guidance")
        ]

    return result


# ── Workflows ────────────────────────────────────────────────────

@app.post("/api/v1/workflows/generate")
async def generate_workflow_with_ai(req: WorkflowGenerateRequest):
    """Generate a workflow from a natural language prompt using AI."""
    from tubecli.core.ai_workflow_builder import generate_workflow
    try:
        result = generate_workflow(
            prompt=req.prompt,
            provider=req.provider,
            model=req.model,
            api_key=req.api_key,
        )
        return {"status": "success", "workflow_data": result}
    except Exception as e:
        raise HTTPException(500, f"Workflow generation failed: {str(e)}")


@app.post("/api/v1/workflows/run")
async def run_workflow(req: WorkflowRunRequest):
    import asyncio
    from tubecli.nodes.registry import create_node_from_dict
    from tubecli.core.workflow_engine import WorkflowEngine

    nodes_data = req.workflow_data.get("nodes", [])
    connections = req.workflow_data.get("connections", [])

    if req.input_text:
        for nd in nodes_data:
            if nd.get("type") in ("text_input", "manual_input"):
                nd.setdefault("config", {})["text"] = req.input_text

    try:
        nodes = [create_node_from_dict(nd) for nd in nodes_data]
    except Exception as e:
        raise HTTPException(400, f"Node creation error: {e}")

    engine = WorkflowEngine(nodes=nodes, connections=connections)
    result = await engine.run()
    return result


@app.get("/api/v1/workflows")
async def list_workflows():
    """List all saved workflows."""
    import json
    from tubecli.config import DATA_DIR

    wf_dir = os.path.join(DATA_DIR, "workflows")
    os.makedirs(wf_dir, exist_ok=True)

    workflows = []
    for fname in os.listdir(wf_dir):
        if fname.endswith(".json"):
            fpath = os.path.join(wf_dir, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                workflows.append({
                    "name": fname.replace(".json", ""),
                    "node_count": len(data.get("nodes", [])),
                    "modified": os.path.getmtime(fpath),
                })
            except Exception:
                pass
    return {"workflows": workflows, "count": len(workflows)}


@app.post("/api/v1/workflows")
async def save_workflow(req: WorkflowSaveRequest):
    """Save a workflow to disk."""
    import json
    from tubecli.config import DATA_DIR

    wf_dir = os.path.join(DATA_DIR, "workflows")
    os.makedirs(wf_dir, exist_ok=True)

    safe_name = "".join(c for c in req.name if c.isalnum() or c in "_- ").strip()
    if not safe_name:
        raise HTTPException(400, "Invalid workflow name")

    fpath = os.path.join(wf_dir, safe_name + ".json")
    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(req.workflow_data, f, indent=2, ensure_ascii=False)

    return {"status": "saved", "name": safe_name}


@app.get("/api/v1/workflows/{name}")
async def get_workflow(name: str):
    """Get a saved workflow by name."""
    import json
    from tubecli.config import DATA_DIR

    fpath = os.path.join(DATA_DIR, "workflows", name + ".json")
    if not os.path.exists(fpath):
        raise HTTPException(404, f"Workflow '{name}' not found")

    with open(fpath, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {"name": name, "workflow_data": data}


@app.delete("/api/v1/workflows/{name}")
async def delete_workflow(name: str):
    """Delete a saved workflow."""
    from tubecli.config import DATA_DIR

    fpath = os.path.join(DATA_DIR, "workflows", name + ".json")
    if not os.path.exists(fpath):
        raise HTTPException(404, f"Workflow '{name}' not found")

    os.remove(fpath)
    return {"status": "deleted", "name": name}


# ── Nodes ────────────────────────────────────────────────────────

@app.get("/api/v1/nodes")
async def list_nodes():
    from tubecli.nodes.registry import list_available_nodes
    return {"nodes": list_available_nodes()}


# ── Extensions Management ───────────────────────────────────────────

@app.get("/api/v1/extensions")
async def list_extensions():
    from tubecli.core.extension_manager import extension_manager
    extensions = extension_manager.get_all()
    return {"extensions": [p.to_dict() for p in extensions], "count": len(extensions)}

@app.post("/api/v1/extensions/{name}/enable")
async def enable_extension(name: str):
    from tubecli.core.extension_manager import extension_manager
    if extension_manager.enable(name):
        return {"status": "enabled", "extension": name}
    raise HTTPException(404, f"Extension '{name}' not found")

@app.post("/api/v1/extensions/{name}/disable")
async def disable_extension(name: str):
    from tubecli.core.extension_manager import extension_manager
    if extension_manager.disable(name):
        return {"status": "disabled", "extension": name}
    raise HTTPException(404, f"Extension '{name}' not found")

@app.put("/api/v1/extensions/{name}")
async def update_extension(name: str, req: ExtensionUpdateRequest):
    from tubecli.core.extension_manager import extension_manager
    extension = extension_manager.get(name)
    if not extension:
         raise HTTPException(404, f"Extension '{name}' not found")
    
    if req.port is not None:
        extension_manager.set_port(name, req.port)
        
    return {"status": "updated", "extension": extension.to_dict()}


@app.get("/api/v1/extensions/{name}/info")
async def extension_info(name: str):
    """Get detailed info about a extension including manifest and SKILL.md."""
    from tubecli.core.extension_manager import extension_manager
    extension = extension_manager.get(name)
    if not extension:
        raise HTTPException(404, f"Extension '{name}' not found")
    info = extension.to_dict()
    info["manifest"] = extension.get_manifest()
    info["nodes"] = list(extension.get_nodes().keys()) if extension.get_nodes() else []
    skill_md = extension.get_skill_md()
    info["skill_md_content"] = skill_md[:2000] if skill_md else None
    return info


@app.get("/api/v1/extensions/{name}/locale/{lang}")
async def extension_locale(name: str, lang: str):
    """Return locale strings for an extension.
    Looks for locales/{lang}.json, falls back to en.json, returns {} if none found.
    """
    from tubecli.core.extension_manager import extension_manager
    import re
    # Sanitize lang to prevent path traversal
    if not re.match(r'^[a-z]{2}(-[A-Z]{2})?$', lang):
        lang = "en"
    extension = extension_manager.get(name)
    if not extension or not extension.extension_dir:
        return {}
    locales_dir = os.path.join(extension.extension_dir, "locales")
    # Try requested lang first, then "en" fallback
    for try_lang in [lang, "en"]:
        locale_path = os.path.join(locales_dir, f"{try_lang}.json")
        if os.path.isfile(locale_path):
            try:
                with open(locale_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    return {}


class ExtensionInstallRequest(BaseModel):
    git_url: str


@app.post("/api/v1/extensions/install")
async def install_extension(req: ExtensionInstallRequest):
    """Install a extension from a git repository URL."""
    from tubecli.core.extension_manager import extension_manager
    result = extension_manager.install_from_git(req.git_url)
    if result["status"] == "error":
        raise HTTPException(400, result["message"])
    return result


@app.delete("/api/v1/extensions/{name}/uninstall")
async def uninstall_extension(name: str):
    """Uninstall an external extension."""
    from tubecli.core.extension_manager import extension_manager
    result = extension_manager.uninstall(name)
    if result["status"] == "error":
        raise HTTPException(400, result["message"])
    return result


@app.get("/api/v1/extensions/{name}/package")
async def package_extension(name: str):
    """Package all files of an extension into a JSON structure for Market upload.
    Returns manifest + all source files so buyers can fully install the extension.
    Auto-detects pip dependencies from Python imports.
    """
    import re
    import ast
    import json as json_lib
    from tubecli.core.extension_manager import extension_manager

    ext = extension_manager.get(name)
    if not ext:
        raise HTTPException(404, f"Extension '{name}' not found")

    ext_dir = ext.extension_dir
    if not ext_dir or not os.path.isdir(ext_dir):
        raise HTTPException(400, "Extension directory not found")

    # ── Mapping: Python module name → pip package name ──────────────
    # Standard library modules are excluded automatically via sys.stdlib_module_names (Python 3.10+)
    # or a manual list. Any module not in stdlib that is imported is considered a dep.
    IMPORT_TO_PIP = {
        # Media / video
        "yt_dlp": "yt-dlp",
        "imageio_ffmpeg": "imageio-ffmpeg",
        "imageio": "imageio",
        "cv2": "opencv-python",
        "PIL": "Pillow",
        "moviepy": "moviepy",
        "ffmpeg": "ffmpeg-python",
        # HTTP / network
        "requests": "requests",
        "httpx": "httpx",
        "aiohttp": "aiohttp",
        "bs4": "beautifulsoup4",
        "lxml": "lxml",
        "selenium": "selenium",
        "playwright": "playwright",
        "pyppeteer": "pyppeteer",
        # Data / AI
        "numpy": "numpy",
        "pandas": "pandas",
        "sklearn": "scikit-learn",
        "scipy": "scipy",
        "torch": "torch",
        "tensorflow": "tensorflow",
        "openai": "openai",
        "anthropic": "anthropic",
        "google.generativeai": "google-generativeai",
        # Web / API
        "fastapi": "fastapi",
        "pydantic": "pydantic",
        "uvicorn": "uvicorn",
        "flask": "Flask",
        "django": "Django",
        "starlette": "starlette",
        # Utils
        "dotenv": "python-dotenv",
        "yaml": "PyYAML",
        "toml": "tomli",
        "rich": "rich",
        "click": "click",
        "tqdm": "tqdm",
        "loguru": "loguru",
        "cryptography": "cryptography",
        "jwt": "PyJWT",
        "paramiko": "paramiko",
        "pyautogui": "pyautogui",
        "pynput": "pynput",
        "pyperclip": "pyperclip",
        "psutil": "psutil",
        "pytesseract": "pytesseract",
        "docx": "python-docx",
        "openpyxl": "openpyxl",
        "xlrd": "xlrd",
        "reportlab": "reportlab",
        "telegram": "python-telegram-bot",
        "discord": "discord.py",
        "tweepy": "tweepy",
        "boto3": "boto3",
        "google.cloud": "google-cloud",
        "google.auth": "google-auth",
        "pymongo": "pymongo",
        "redis": "redis",
        "sqlalchemy": "SQLAlchemy",
        "alembic": "alembic",
        "celery": "celery",
    }

    # Known stdlib top-level module names (supplemented if sys.stdlib_module_names unavailable)
    import sys
    try:
        _STDLIB = sys.stdlib_module_names  # Python 3.10+
    except AttributeError:
        _STDLIB = {
            "os", "sys", "re", "io", "ast", "abc", "math", "time", "json",
            "uuid", "enum", "copy", "glob", "shutil", "logging", "pathlib",
            "typing", "hashlib", "base64", "struct", "socket", "threading",
            "asyncio", "subprocess", "functools", "itertools", "collections",
            "contextlib", "dataclasses", "importlib", "inspect", "traceback",
            "random", "string", "token", "tokenize", "weakref", "signal",
            "platform", "tempfile", "datetime", "calendar", "urllib",
            "http", "html", "email", "csv", "sqlite3", "xml", "zipfile",
            "tarfile", "gzip", "bz2", "lzma", "codecs", "multiprocessing",
        }

    def _scan_imports(py_source: str) -> set:
        """Extract top-level module names from Python source."""
        found = set()
        try:
            tree = ast.parse(py_source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        found.add(alias.name.split(".")[0])
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        found.add(node.module.split(".")[0])
        except SyntaxError:
            # Fallback: regex
            for m in re.finditer(r"^(?:import|from)\s+([\w]+)", py_source, re.MULTILINE):
                found.add(m.group(1))
        return found

    # ── Collect all files ──────────────────────────────────────────
    SKIP_DIRS = {
        "__pycache__", ".git", "node_modules", ".venv", "venv",
        "data", "db", "logs", "tmp", "dist", "build",
        ".env", ".vscode", ".idea", "coverage",
    }
    SKIP_EXTS = {".pyc", ".pyo", ".egg-info", ".sqlite3", ".db", ".log", ".exe", ".dll", ".so", ".zip", ".tar", ".gz"}
    MAX_FILE_SIZE = 500_000  # 500KB per file

    # ── Parse .gitignore for extra exclusions ──
    gitignore_patterns = set()
    gitignore_path = os.path.join(ext_dir, ".gitignore")
    if os.path.isfile(gitignore_path):
        try:
            with open(gitignore_path, "r") as f:
                for line in f:
                    line = line.strip().rstrip("/")
                    if line and not line.startswith("#"):
                        gitignore_patterns.add(line)
        except Exception:
            pass

    files = []
    all_imports: set = set()

    for root, dirs, filenames in os.walk(ext_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and d not in gitignore_patterns]

        for fname in filenames:
            if any(fname.endswith(e) for e in SKIP_EXTS):
                continue

            fpath = os.path.join(root, fname)
            rel_path = os.path.relpath(fpath, ext_dir).replace("\\", "/")

            if os.path.getsize(fpath) > MAX_FILE_SIZE:
                continue

            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    content = f.read()
                files.append({"path": rel_path, "content": content})

                # Scan Python files for imports
                if fname.endswith(".py"):
                    all_imports |= _scan_imports(content)
            except (UnicodeDecodeError, PermissionError):
                continue

    # ── Auto-detect pip packages ───────────────────────────────────
    detected_deps: list = []

    # 1. From requirements.txt (highest priority, preserves version pins)
    req_deps: set = set()
    req_file = os.path.join(ext_dir, "requirements.txt")
    if os.path.exists(req_file):
        try:
            with open(req_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        detected_deps.append(line)
                        pkg = re.split(r"[=<>!;]", line)[0].strip().lower().replace("-", "_")
                        req_deps.add(pkg)
        except Exception:
            pass

    # 2. From scanned imports → map to pip packages
    # Respect exclude_auto_deps from manifest (for lazy-loaded heavy deps)
    exclude_auto = set()
    if os.path.exists(os.path.join(ext_dir, "tubecli-extension.json")):
        try:
            with open(os.path.join(ext_dir, "tubecli-extension.json"), "r", encoding="utf-8") as f:
                _m = json_lib.load(f)
            for exc in _m.get("exclude_auto_deps", []):
                exclude_auto.add(exc.lower().replace("-", "_"))
        except Exception:
            pass

    req_deps_normalized = {r.replace("-", "_").lower() for r in req_deps}
    for module in sorted(all_imports):
        if module in _STDLIB:
            continue
        # Skip modules in exclude_auto_deps (heavy deps installed on-demand)
        if module.lower().replace("-", "_") in exclude_auto:
            continue
        # Check if already covered by requirements.txt
        mod_normalized = module.replace("-", "_").lower()
        pip_name = IMPORT_TO_PIP.get(module)
        if not pip_name:
            continue  # Unknown mapping, skip
        pip_normalized = pip_name.replace("-", "_").lower()
        if pip_normalized in exclude_auto:
            continue
        if pip_normalized in req_deps_normalized or mod_normalized in req_deps_normalized:
            continue  # Already in requirements.txt
        detected_deps.append(pip_name)

    # 3. Merge with existing manifest.dependencies (don't lose manually declared ones)
    read_manifest_path = os.path.join(ext_dir, "tubecli-extension.json")
    manifest = {}
    if os.path.exists(read_manifest_path):
        with open(read_manifest_path, "r", encoding="utf-8") as f:
            manifest = json_lib.load(f)

    existing_deps = manifest.get("dependencies", [])
    existing_normalized = {d.replace("-", "_").lower() for d in existing_deps}
    for dep in existing_deps:
        dep_norm = dep.replace("-", "_").lower()
        if dep_norm not in {d.replace("-", "_").lower() for d in detected_deps}:
            detected_deps.append(dep)

    # Deduplicate while preserving order
    seen = set()
    final_deps = []
    for dep in detected_deps:
        key = re.split(r"[=<>!;]", dep)[0].strip().lower().replace("-", "_")
        if key not in seen:
            seen.add(key)
            final_deps.append(dep)

    # Update manifest with auto-detected deps
    manifest["dependencies"] = final_deps

    return {
        "status": "success",
        "manifest": manifest,
        "files": files,
        "file_count": len(files),
        "detected_deps": final_deps,
    }


@app.get("/api/v1/extensions/skill-mds")
async def get_extension_skill_mds():
    """Return all SKILL.md contents from enabled extensions for AI agents."""
    from tubecli.core.extension_manager import extension_manager
    return {"skill_mds": extension_manager.get_all_skill_mds()}


# ── System Version & Update ─────────────────────────────────────────

@app.get("/api/v1/system/version")
async def system_version():
    """Get current system version and git info."""
    import subprocess
    from tubecli import __version__
    from tubecli.config import BASE_DIR

    git_hash = ""
    git_branch = ""
    project_root = str(BASE_DIR)

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=project_root, capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            git_hash = result.stdout.strip()
    except Exception:
        pass

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=project_root, capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            git_branch = result.stdout.strip()
    except Exception:
        pass

    return {
        "version": __version__,
        "git_hash": git_hash,
        "git_branch": git_branch,
    }


@app.post("/api/v1/system/check-update")
async def system_check_update():
    """Check if a system update is available by comparing local vs remote git."""
    import subprocess
    from tubecli import __version__
    from tubecli.config import BASE_DIR

    project_root = str(BASE_DIR)

    try:
        # Fetch latest from remote
        subprocess.run(
            ["git", "fetch", "origin"],
            cwd=project_root, capture_output=True, text=True, timeout=30,
        )

        # Get current hash
        r_local = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=project_root, capture_output=True, text=True, timeout=10,
        )
        current_hash = r_local.stdout.strip() if r_local.returncode == 0 else ""

        # Get remote hash
        r_remote = subprocess.run(
            ["git", "rev-parse", "--short", "origin/main"],
            cwd=project_root, capture_output=True, text=True, timeout=10,
        )
        latest_hash = r_remote.stdout.strip() if r_remote.returncode == 0 else ""

        # Count commits behind
        r_count = subprocess.run(
            ["git", "rev-list", "--count", "HEAD..origin/main"],
            cwd=project_root, capture_output=True, text=True, timeout=10,
        )
        commits_behind = int(r_count.stdout.strip()) if r_count.returncode == 0 else 0

        # Get changelog (commit messages)
        changelog = []
        if commits_behind > 0:
            r_log = subprocess.run(
                ["git", "log", "--oneline", f"HEAD..origin/main", "--format=%s"],
                cwd=project_root, capture_output=True, text=True, timeout=10,
            )
            if r_log.returncode == 0:
                changelog = [line.strip() for line in r_log.stdout.strip().split("\n") if line.strip()]

        return {
            "has_update": commits_behind > 0,
            "current_version": __version__,
            "current_hash": current_hash,
            "latest_hash": latest_hash,
            "commits_behind": commits_behind,
            "changelog": changelog[:20],
        }
    except Exception as e:
        raise HTTPException(500, f"Failed to check for updates: {e}")


@app.post("/api/v1/system/update")
async def system_update():
    """Pull latest code from git and reinstall dependencies."""
    import subprocess, sys
    from tubecli import __version__
    from tubecli.config import BASE_DIR

    project_root = str(BASE_DIR)
    old_version = __version__

    try:
        # Git pull
        r_pull = subprocess.run(
            ["git", "pull", "origin", "main"],
            cwd=project_root, capture_output=True, text=True, timeout=60,
        )
        if r_pull.returncode != 0:
            return {"status": "error", "error": f"git pull failed: {r_pull.stderr}"}

        # Reinstall (update dependencies)
        r_install = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-e", ".", "--quiet"],
            cwd=project_root, capture_output=True, text=True, timeout=120,
        )

        # Read new version from file (since module cache still has old value)
        new_version = old_version
        init_file = os.path.join(project_root, "tubecli", "__init__.py")
        try:
            with open(init_file, "r") as f:
                for line in f:
                    if line.startswith("__version__"):
                        new_version = line.split("=")[1].strip().strip('"').strip("'")
                        break
        except Exception:
            pass

        return {
            "status": "success",
            "old_version": old_version,
            "new_version": new_version,
            "git_output": r_pull.stdout.strip()[:500],
            "message": "Updated successfully! Please restart the API server to apply changes.",
        }
    except Exception as e:
        raise HTTPException(500, f"Update failed: {e}")


# ── Extension Update ─────────────────────────────────────────────────

@app.post("/api/v1/extensions/{name}/check-update")
async def check_extension_update(name: str):
    """Check if an external extension has updates available."""
    import subprocess
    import json
    from tubecli.core.extension_manager import (
        extension_manager,
        compare_versions,
        get_git_tracking_branch,
        get_git_commit_version,
    )
    from tubecli.extensions.market.market_service import market_service

    ext = extension_manager.get(name)
    if not ext:
        raise HTTPException(404, f"Extension '{name}' not found")

    # System extensions update with the core system
    if ext.extension_type != "external":
        return {
            "name": name,
            "has_update": False,
            "message": "System extensions update with 'System Update'. Use Settings → Update.",
            "current_version": ext.version,
        }

    ext_dir = ext.extension_dir
    git_dir = os.path.join(ext_dir, ".git") if ext_dir else None

    if ext_dir and git_dir and os.path.isdir(git_dir):
        # Git-based checking
        try:
            subprocess.run(
                ["git", "fetch", "origin"],
                cwd=ext_dir, capture_output=True, text=True, timeout=15,
            )
            branch = get_git_tracking_branch(ext_dir)

            r_count = subprocess.run(
                ["git", "rev-list", "--count", f"HEAD..origin/{branch}"],
                cwd=ext_dir, capture_output=True, text=True, timeout=10,
            )
            commits_behind = int(r_count.stdout.strip()) if r_count.returncode == 0 else 0

            changelog = []
            if commits_behind > 0:
                r_log = subprocess.run(
                    ["git", "log", "--oneline", f"HEAD..origin/{branch}", "--format=%s"],
                    cwd=ext_dir, capture_output=True, text=True, timeout=10,
                )
                if r_log.returncode == 0:
                    changelog = [l.strip() for l in r_log.stdout.strip().split("\n") if l.strip()]

            # Fetch remote version from git manifest, fallback to remote commit date
            remote_version = None
            try:
                res_show = subprocess.run(
                    ["git", "show", f"origin/{branch}:tubecli-extension.json"],
                    cwd=ext_dir, capture_output=True, text=True, timeout=10
                )
                if res_show.returncode == 0:
                    r_manifest = json.loads(res_show.stdout)
                    remote_version = r_manifest.get("version")
            except Exception:
                pass
            
            if not remote_version or compare_versions(remote_version, "2000.01.01.000000") < 0:
                remote_version = get_git_commit_version(ext_dir, remote=True, branch=branch) or "2026.05.21.000000"

            return {
                "name": name,
                "has_update": commits_behind > 0,
                "current_version": ext.version,
                "remote_version": remote_version,
                "commits_behind": commits_behind,
                "changelog": changelog[:10],
                "is_git": True,
            }
        except Exception as e:
            raise HTTPException(500, f"Failed to check extension git update: {e}")
    else:
        # Marketplace-based checking
        try:
            check_res = await market_service.check_name_exists(ext.name)
            if check_res.get("exists") and check_res.get("item"):
                item = check_res["item"]
                market_version = item.get("version", "0.0.0")
                if compare_versions(market_version, ext.version) > 0:
                    return {
                        "name": name,
                        "has_update": True,
                        "current_version": ext.version,
                        "remote_version": market_version,
                        "public_id": check_res.get("public_id", ""),
                        "is_git": False,
                    }
            return {
                "name": name,
                "has_update": False,
                "message": "Extension is up to date on marketplace.",
                "current_version": ext.version,
                "is_git": False,
            }
        except Exception as e:
            raise HTTPException(500, f"Failed to check extension marketplace update: {e}")


@app.post("/api/v1/extensions/{name}/update")
async def update_extension(name: str):
    """Pull latest code/updates for an external extension."""
    from tubecli.core.extension_manager import extension_manager

    result = extension_manager.update_extension(name)
    if result.get("status") == "error":
        raise HTTPException(400, result.get("message", "Update failed"))
    return result


# ── Aggregated i18n (per-extension locales) ─────────────────────────

@app.get("/api/v1/i18n/{lang}")
async def get_aggregated_i18n(lang: str):
    """Aggregate locale files from ALL extensions into a single flat dict.
    Scans both built-in extensions and external extensions directories.
    """
    import re
    import json
    import os

    # Sanitize lang
    if not re.match(r'^[a-z]{2}(-[A-Z]{2})?$', lang):
        lang = "zh"

    merged = {}

    def _load_locales_from_dir(base_dir):
        """Scan a directory for subdirectories containing locales/."""
        if not os.path.isdir(base_dir):
            return
        for entry in os.listdir(base_dir):
            ext_dir = os.path.join(base_dir, entry)
            if not os.path.isdir(ext_dir):
                continue
            locales_dir = os.path.join(ext_dir, "locales")
            if not os.path.isdir(locales_dir):
                continue
            for try_lang in [lang, "en"]:
                locale_path = os.path.join(locales_dir, f"{try_lang}.json")
                if os.path.isfile(locale_path):
                    try:
                        with open(locale_path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        merged.update(data)
                    except Exception:
                        pass
                    break

    # 1. Built-in extensions: tubecli/extensions/*/locales/
    builtin_ext_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "extensions")
    _load_locales_from_dir(builtin_ext_dir)

    # 2. External extensions: data/extensions_external/*/locales/
    from tubecli.config import EXTENSIONS_EXTERNAL_DIR
    _load_locales_from_dir(str(EXTENSIONS_EXTERNAL_DIR))

    merged["_DEBUG"] = {
        "__file__": __file__,
        "builtin_ext_dir": builtin_ext_dir,
        "external_ext_dir": str(EXTENSIONS_EXTERNAL_DIR)
    }

    return merged


# ── Language Settings ────────────────────────────────────────────────

class LanguageUpdateRequest(BaseModel):
    language: str


@app.get("/api/v1/settings/language")
async def get_language_setting():
    """Get current language setting."""
    from tubecli.config import get_language, SUPPORTED_LANGUAGES
    return {
        "language": get_language(),
        "supported": SUPPORTED_LANGUAGES,
    }


@app.put("/api/v1/settings/language")
async def set_language_setting(req: LanguageUpdateRequest):
    """Update language setting."""
    from tubecli.config import set_language, SUPPORTED_LANGUAGES
    from tubecli.i18n import load_language
    if req.language not in SUPPORTED_LANGUAGES:
        raise HTTPException(400, f"Unsupported language: {req.language}. Supported: {SUPPORTED_LANGUAGES}")
    set_language(req.language)
    load_language(req.language)
    return {"status": "updated", "language": req.language}


# ── Profile Settings ───────────────────────────────────────────────────

class ProfileUpdateRequest(BaseModel):
    profile: str


@app.get("/api/v1/settings/default-profile")
async def get_default_profile_setting():
    """Get current default browser profile."""
    from tubecli.config import get_setting
    return {"profile": get_setting("default_browser_profile", "default")}


@app.put("/api/v1/settings/default-profile")
async def set_default_profile_setting(req: ProfileUpdateRequest):
    """Update default browser profile."""
    from tubecli.config import set_setting
    set_setting("default_browser_profile", req.profile)
    return {"status": "updated", "profile": req.profile}


# ── Register Extension Routes ───────────────────────────────────────
from tubecli.core.extension_manager import extension_manager
extension_manager.discover_extensions()
extension_manager.register_api_routes(app)
