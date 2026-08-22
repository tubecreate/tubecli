"""
Script Studio — API Routes.
"""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List, Any
import os
import json
import logging
import subprocess
import threading
import time

logger = logging.getLogger("ScriptStudio.Routes")
router = APIRouter(prefix="/api/v1/scripts", tags=["scripts"])

# ── Static UI Router ──
ui_router = APIRouter(tags=["script-studio-ui"])
_EXT_DIR = os.path.dirname(os.path.abspath(__file__))

@ui_router.get("/script-studio")
async def serve_ui():
    return FileResponse(
        os.path.join(_EXT_DIR, "static", "index.html"),
        media_type="text/html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
    )

@ui_router.get("/script-studio/{filename:path}")
async def serve_static(filename: str):
    filepath = os.path.join(_EXT_DIR, "static", filename)
    if os.path.isfile(filepath):
        media = "text/css" if filename.endswith(".css") else "application/javascript" if filename.endswith(".js") else "application/octet-stream"
        return FileResponse(filepath, media_type=media, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
    raise HTTPException(404, "File not found")

_store_mod = None
_db_mod = None

def _store():
    """Get JSON-based ScriptStore instance."""
    global _store_mod
    if _store_mod is None:
        import importlib.util
        ext_dir = os.path.dirname(os.path.abspath(__file__))
        store_file = os.path.join(ext_dir, "db", "script_store.py")
        spec = importlib.util.spec_from_file_location("script_store", store_file)
        _store_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_store_mod)

    store = _store_mod.ScriptStore.get_instance()
    if store is None:
        from tubecli.config import ext_data_dir
        scripts_dir = str(ext_data_dir("browser_scripts"))
        store = _store_mod.ScriptStore.get_instance(scripts_dir)
    return store

def _db():
    """Get SQLite DB for execution history only."""
    global _db_mod
    if _db_mod is None:
        import importlib.util
        ext_dir = os.path.dirname(os.path.abspath(__file__))
        db_file = os.path.join(ext_dir, "db", "database.py")
        spec = importlib.util.spec_from_file_location("script_studio_db", db_file)
        _db_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_db_mod)

    db = _db_mod.ScriptDatabase.get_instance()
    if db is None:
        from tubecli.config import ext_data_dir
        db_dir = str(ext_data_dir("browser_scripts"))
        os.makedirs(db_dir, exist_ok=True)
        db_path = os.path.join(db_dir, "scripts.db")
        db = _db_mod.ScriptDatabase.get_instance(db_path)
    return db


def _get_node_env():
    """Get environment with NODE_PATH pointing to browser extension's node_modules."""
    env = os.environ.copy()
    # Playwright is installed in the browser extension's node_modules
    browser_ext_nm = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "..", "..", "tubecli", "extensions", "browser", "node_modules"
    )
    browser_ext_nm = os.path.normpath(browser_ext_nm)
    if os.path.isdir(browser_ext_nm):
        existing = env.get("NODE_PATH", "")
        env["NODE_PATH"] = browser_ext_nm + (";" + existing if existing else "")
    return env


def _get_profiles_dir():
    """Get browser profiles directory from TubeCLI config.

    data/browser_profiles is a junction onto this path, so the old spelling
    still worked — but every caller that keeps using it keeps the compat shim
    alive, and the scanner has to treat it as an alias.
    """
    try:
        from tubecli.config import ext_data_path
        return str(ext_data_path("browser", "browser_profiles"))
    except Exception:
        return ""


# ── Models ──

class ScriptCreate(BaseModel):
    name: str
    slug: Optional[str] = None
    description: str = ""
    category: str = "general"
    target_url: str = ""
    tags: List[str] = []
    steps: List[dict] = []
    variables: List[dict] = []
    is_template: bool = False
    is_function: bool = False
    function_inputs: List[dict] = []
    function_outputs: List[dict] = []

class ScriptUpdate(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    target_url: Optional[str] = None
    tags: Optional[List[str]] = None
    steps: Optional[List[dict]] = None
    variables: Optional[List[dict]] = None
    is_template: Optional[bool] = None
    is_function: Optional[bool] = None
    function_inputs: Optional[List[dict]] = None
    function_outputs: Optional[List[dict]] = None

class RunRequest(BaseModel):
    profile: str = ""
    variables: dict = {}
    headless: bool = True
    engine: str = "playwright"  # "playwright" or "bablosoft" (Security Browser)
    attach: bool = False  # True: chạy trên browser live đang mở (khung Browser) qua CDP
    tab_index: int = -1  # index tab đang xem (context.pages()) — chạy đúng tab đó


# ── Script CRUD ──

def _resolve_providers(selected_provider: str = "auto") -> list:
    if selected_provider and selected_provider != "auto":
        return [selected_provider]
    
    global_default = "gemini"
    try:
        from tubecli.config import DATA_DIR
        settings_path = os.path.join(str(DATA_DIR), "global_settings.json")
        if os.path.exists(settings_path):
            with open(settings_path, "r", encoding="utf-8") as f:
                settings = json.load(f)
            default_model = settings.get("default_model", "").lower()
            if "gemini" in default_model:
                global_default = "gemini"
            elif "deepseek" in default_model:
                global_default = "deepseek"
            elif "grok" in default_model:
                global_default = "grok"
            elif "gpt" in default_model or "openai" in default_model:
                global_default = "chatgpt"
            elif "9router" in default_model:
                global_default = "9router"
            elif "qwen" in default_model or "ollama" in default_model or "llama" in default_model:
                global_default = "ollama"
    except Exception:
        pass
        
    base_providers = ["deepseek", "gemini", "grok", "chatgpt", "9router", "ollama"]
    if global_default in base_providers:
        base_providers.remove(global_default)
        return [global_default] + base_providers
    return base_providers


@router.get("/ai-providers")
async def list_ai_providers():
    from tubecli.extensions.cloud_api.extension import key_manager
    import requests
    
    # Gather models for each provider (fallbacks)
    models_dict = {
        "gemini": ["gemini-2.0-flash", "gemini-2.0-pro", "gemini-1.5-flash", "gemini-1.5-pro"],
        "chatgpt": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "o1", "o3-mini"],
        "deepseek": ["deepseek-v4-flash", "deepseek-v4-pro"],
        "grok": ["grok-2", "grok-2-mini"],
        "9router": ["deepseek-chat", "deepseek-reasoner", "deepseek/deepseek-r1", "google/gemini-2.5-flash-lite"],
        "ollama": []
    }
    
    # Query 9Router status and models directly
    nr_active = False
    try:
        key = key_manager.get_active_key("9router")
        headers = {}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        r = requests.get("http://localhost:20128/v1/models", headers=headers, timeout=1.0)
        if r.status_code == 200:
            nr_active = True
            data = r.json()
            if isinstance(data, dict) and "data" in data:
                models = [m.get("id", m.get("name", "")) for m in data["data"] if isinstance(m, dict)]
                if models:
                    models_dict["9router"] = models
    except Exception:
        pass

    # Query Ollama status and models directly
    ollama_active = False
    try:
        from tubecli.config import OLLAMA_BASE_URL
        r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=1.0)
        if r.status_code == 200:
            ollama_active = True
            models = r.json().get("models", [])
            if models:
                models_dict["ollama"] = [m.get("name") for m in models if m.get("name")]
    except Exception:
        pass
    if not models_dict["ollama"]:
        models_dict["ollama"] = ["qwen2.5:7b", "qwen:latest", "llama3"]

    providers_status = {}
    display_names = {
        "deepseek": "DeepSeek",
        "gemini": "Google Gemini",
        "grok": "xAI Grok",
        "chatgpt": "OpenAI ChatGPT",
        "9router": "9Router (Local Proxy)",
        "ollama": "Ollama (Local)"
    }
    
    for prov in ["deepseek", "gemini", "grok", "chatgpt", "9router", "ollama"]:
        if prov == "ollama":
            providers_status[prov] = {"active": ollama_active, "display_name": display_names[prov]}
        elif prov == "9router":
            providers_status[prov] = {"active": nr_active, "display_name": display_names[prov]}
        else:
            has_key = key_manager.get_active_key(prov) is not None
            providers_status[prov] = {"active": has_key, "display_name": display_names[prov]}
        
    # Determine global default provider
    global_default = "gemini"
    default_model = ""
    try:
        from tubecli.config import DATA_DIR
        settings_path = os.path.join(str(DATA_DIR), "global_settings.json")
        if os.path.exists(settings_path):
            with open(settings_path, "r", encoding="utf-8") as f:
                settings = json.load(f)
            default_model = settings.get("default_model", "")
            lower_model = default_model.lower()
            if "gemini" in lower_model:
                global_default = "gemini"
            elif "deepseek" in lower_model:
                global_default = "deepseek"
            elif "grok" in lower_model:
                global_default = "grok"
            elif "gpt" in lower_model or "openai" in lower_model:
                global_default = "chatgpt"
            elif "9router" in lower_model:
                global_default = "9router"
            elif "qwen" in lower_model or "ollama" in lower_model or "llama" in lower_model:
                global_default = "ollama"
    except Exception:
        pass
        
    return {
        "providers": providers_status,
        "models": models_dict,
        "default_provider": global_default,
        "default_model": default_model
    }

@router.get("")
async def list_scripts(category: Optional[str] = None):
    scripts = _store().list_scripts(category)
    return {"scripts": scripts}

@router.post("")
async def create_script(req: ScriptCreate):
    try:
        script = _store().create_script(
            name=req.name, slug=req.slug, description=req.description,
            category=req.category, target_url=req.target_url,
            tags=req.tags, steps=req.steps, variables=req.variables,
            is_template=req.is_template, is_function=req.is_function,
            function_inputs=req.function_inputs, function_outputs=req.function_outputs,
        )
        return {"status": "created", "script": script}
    except Exception as e:
        raise HTTPException(400, str(e))

@router.get("/functions")
async def list_functions():
    """List all scripts marked as functions."""
    functions = _store().list_functions()
    # Return lightweight list (no steps)
    return {"functions": [
        {
            "slug": f["slug"], "name": f["name"], "description": f.get("description", ""),
            "function_inputs": f.get("function_inputs", []),
            "function_outputs": f.get("function_outputs", []),
            "category": f.get("category", "general"),
            "tags": f.get("tags", []),
        }
        for f in functions
    ]}

@router.get("/functions/{slug}")
async def get_function(slug: str):
    """Get function detail by slug (includes steps for runner)."""
    script = _store().get_script(slug)
    if not script or not script.get("is_function"):
        raise HTTPException(404, "Function not found")
    return script

@router.get("/by-slug/{slug}")
async def get_script_by_slug(slug: str):
    """Get script by slug."""
    script = _store().get_script(slug)
    if not script:
        raise HTTPException(404, "Script not found")
    return script

@router.get("/{script_id}")
async def get_script(script_id: str):
    """Get script by slug (or legacy numeric ID)."""
    script = _store().get_script(script_id)
    if not script:
        # Backward compat: try as numeric ID
        script = _store().get_script_by_id(int(script_id)) if script_id.isdigit() else None
    if not script:
        raise HTTPException(404, "Script not found")
    return script

@router.put("/{script_id}")
async def update_script(script_id: str, req: ScriptUpdate):
    data = req.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(400, "No fields to update")
    script = _store().update_script(script_id, **data)
    if not script:
        raise HTTPException(404, "Script not found")
    return {"status": "updated", "script": script}

@router.delete("/{script_id}")
async def delete_script(script_id: str):
    _store().delete_script(script_id)
    return {"status": "deleted"}

@router.post("/{script_id}/duplicate")
async def duplicate_script(script_id: str):
    script = _store().duplicate_script(script_id)
    if not script:
        raise HTTPException(404, "Script not found")
    return {"status": "duplicated", "script": script}


# ── Steps ──

@router.put("/{script_id}/steps")
async def update_steps(script_id: str, request: Request):
    body = await request.json()
    steps = body.get("steps", [])
    script = _store().update_script(script_id, steps=steps)
    if not script:
        raise HTTPException(404, "Script not found")
    return {"status": "updated", "steps": script.get("steps", [])}


# ── Execution ──

_running_processes = {}
_running_logs = {}  # exec_id -> list of log lines (real-time)
_attach_running = {}  # profile -> exec_id: chỉ 1 phiên attach mỗi profile (tránh 2 runner cùng điều khiển 1 browser live)

@router.post("/{script_id}/run")
async def run_script(script_id: str, req: RunRequest):
    script = _store().get_script(script_id)
    if not script:
        raise HTTPException(404, "Script not found")

    # Chỉ 1 lượt chạy trên mỗi profile — kể cả attach=false: attach thì 2 runner
    # đan xen chuột/phím làm hỏng flow, không attach thì runner tự mở Chromium
    # trên chính user-data-dir ấy nên cái thứ hai chết vì khoá profile. Nút
    # "Chạy thử" của node Script và lượt chạy của agent (group script_run) dùng chung
    # khoá này nên thấy nhau. Dọn khoá cũ nếu tiến trình đã chết.
    if req.profile:
        prev = _attach_running.get(req.profile)
        if prev and prev in _running_processes and _running_processes[prev].poll() is None:
            raise HTTPException(409, f"Đang có script chạy trên browser '{req.profile}'. Chờ nó xong rồi thử lại.")
        _attach_running.pop(req.profile, None)

    # Auto-inject profile account credentials if a profile is specified
    if req.profile:
        import asyncio
        from tubecli.extensions.browser.profile_manager import get_profile
        profile_data = await asyncio.to_thread(get_profile, req.profile)
        if profile_data:
            services = ['google', 'facebook', 'tiktok', 'x', 'discord', 'telegram']
            for service in services:
                acc = profile_data.get(f"{service}_account")
                if acc and isinstance(acc, dict):
                    email_var = f"{service}_email"
                    pass_var = f"{service}_password"
                    rec_var = f"{service}_recovery"
                    twofa_var = f"{service}_2fa"
                    
                    if email_var not in req.variables and acc.get("email"):
                        req.variables[email_var] = acc["email"]
                    if pass_var not in req.variables and acc.get("password"):
                        req.variables[pass_var] = acc["password"]
                    if rec_var not in req.variables and acc.get("recoveryEmail"):
                        req.variables[rec_var] = acc["recoveryEmail"]
                    if twofa_var not in req.variables and acc.get("twoFactorCodes"):
                        req.variables[twofa_var] = acc["twoFactorCodes"]

    exec_id = _db().create_execution(script_id, req.profile, req.variables)

    ext_dir = os.path.dirname(os.path.abspath(__file__))
    runner_path = os.path.join(ext_dir, "runner", "script_runner.js")

    # Write temp script file for runner
    tmp_dir = os.path.join(ext_dir, "runner", "tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    tmp_file = os.path.join(tmp_dir, f"exec_{exec_id}.json")
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump({
            "script": script,
            "variables": req.variables,
            "profile": req.profile,
            "headless": req.headless,
            "engine": req.engine,
            "attach": req.attach,
            "tab_index": req.tab_index,
            "exec_id": exec_id,
            "profiles_dir": _get_profiles_dir(),
            "scripts_dir": os.path.join(ext_dir, "scripts"),
        }, f, ensure_ascii=False, indent=2)

    _running_logs[exec_id] = []
    if req.profile:
        # Giữ khoá cho MỌI lượt chạy có profile (xem chỗ 409 ở trên);
        # khối finally của run_bg trả lại khoá này.
        _attach_running[req.profile] = exec_id

    def run_bg():
        try:
            env = _get_node_env()
            proc = subprocess.Popen(
                ["node", runner_path, "--exec-file", tmp_file],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                cwd=ext_dir, encoding="utf-8", errors="replace",
                env=env,
            )
            _running_processes[exec_id] = proc
            for line in proc.stdout:
                stripped = line.rstrip()
                if exec_id in _running_logs:
                    _running_logs[exec_id].append(stripped)
            proc.wait()
            final_log = "\n".join(_running_logs.get(exec_id, [])[-500:])
            _db().update_execution(exec_id,
                status="success" if proc.returncode == 0 else "error",
                log=final_log,
                finished_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            )
        except Exception as e:
            if exec_id in _running_logs:
                _running_logs[exec_id].append(f"ERROR: {e}")
            _db().update_execution(exec_id, status="error", log=str(e),
                finished_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        finally:
            _running_processes.pop(exec_id, None)
            if _attach_running.get(req.profile) == exec_id:
                _attach_running.pop(req.profile, None)
            # Keep logs for 60s after finish, then cleanup
            def cleanup():
                time.sleep(60)
                _running_logs.pop(exec_id, None)
            threading.Thread(target=cleanup, daemon=True).start()
            try:
                os.remove(tmp_file)
            except OSError:
                pass

    threading.Thread(target=run_bg, daemon=True).start()
    return {"status": "started", "exec_id": exec_id}

class RunResult(dict):
    """The runner's output variables — plus how the run ENDED.

    WHY a dict subclass: a failed run writes a result file too (the runner sets
    success=false and still saves the variables it had), so a caller that only
    saw the returned dict read "did not raise" as "the script did its job" and
    told the user a half-finished upload was done. Every existing caller uses
    the return value as a plain mapping (brain.py json-dumps it, the web
    crawler reads keys off it), so the outcome rides alongside as attributes
    instead of changing the shape: result.success, result.log, result.exec_id.
    """

    def __init__(self, variables=None, success: bool = True, log: str = "", exec_id=None):
        super().__init__(variables if isinstance(variables, dict) else {})
        self.success = bool(success)
        self.log = log or ""
        self.exec_id = exec_id


def _kill_run_tree(proc) -> None:
    """Kill the runner AND the browser it started.

    Playwright's Chromium is a child of the node process and it is what holds
    the profile's user-data-dir; killing node alone leaves it running, so the
    next run on that profile would die on the profile lock instead.
    """
    try:
        import platform
        if platform.system() == "Windows":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           capture_output=True, timeout=10)
        else:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
    except Exception as e:
        logger.warning(f"Could not kill run tree {getattr(proc, 'pid', '?')}: {e}")
    try:
        proc.kill()
    except Exception:
        pass


def run_script_sync(script_id: str, variables: dict = None, profile: str = "",
                    headless: bool = True, timeout: float = None) -> dict:
    """Run a browser script synchronously and return its output variables.

    `timeout` (seconds) is the deadline for the whole run. Without one the
    calling THREAD stays blocked for as long as the browser lives — and the
    callers are `asyncio.to_thread`, whose default executor is shared by the
    whole API process, so a run hung on a captcha starves everything else.
    """
    script = _store().get_script(script_id)
    if not script:
        raise ValueError(f"Script {script_id} not found")

    variables = variables or {}
    exec_id = _db().create_execution(script_id, profile, variables)

    ext_dir = os.path.dirname(os.path.abspath(__file__))
    runner_path = os.path.join(ext_dir, "runner", "script_runner.js")

    tmp_dir = os.path.join(ext_dir, "runner", "tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    tmp_file = os.path.join(tmp_dir, f"exec_{exec_id}.json")
    result_file = os.path.join(tmp_dir, f"result_{exec_id}.json")

    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump({
            "script": script,
            "variables": variables,
            "profile": profile,
            "headless": headless,
            "engine": "playwright",
            "exec_id": exec_id,
            "profiles_dir": _get_profiles_dir(),
            "scripts_dir": os.path.join(ext_dir, "scripts"),
        }, f, ensure_ascii=False, indent=2)

    try:
        env = _get_node_env()
        proc = subprocess.Popen(
            ["node", runner_path, "--exec-file", tmp_file],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
            cwd=ext_dir, env=env,
        )
        try:
            out, _err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            # Popen, not subprocess.run(timeout=…): run() kills the node process
            # only, and the browser it started would keep the profile locked.
            _kill_run_tree(proc)
            out, _err = proc.communicate()
            _db().update_execution(
                exec_id, status="error",
                log=((out or "")[-4900:] + f"\nTIMEOUT after {timeout}s"),
                finished_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            )
            raise TimeoutError(f"Script execution timed out after {timeout}s and was stopped.")
        out = out or ""

        # Read result file
        if os.path.exists(result_file):
            with open(result_file, "r", encoding="utf-8") as rf:
                result_data = json.load(rf)

            ok = bool(result_data.get("success"))
            _db().update_execution(
                exec_id,
                status="success" if ok else "error",
                log=out[-5000:],
                finished_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            )
            # The runner writes this file on failure too, with whatever
            # variables it had — hence RunResult: "variables came back" has
            # never meant "the script finished its job".
            return RunResult(result_data.get("variables", {}), success=ok,
                             log=out[-5000:], exec_id=exec_id)
        else:
            _db().update_execution(
                exec_id, status="error", log=out[-5000:],
                finished_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            )
            raise RuntimeError(f"Script execution failed. No result file found. Log: {out[-500:]}")

    finally:
        try: os.remove(tmp_file)
        except OSError: pass
        try: os.remove(result_file)
        except OSError: pass


@router.get("/execution/{exec_id}/logs")
async def get_execution_logs(exec_id: int, offset: int = 0):
    """Get real-time logs for a running execution."""
    logs = _running_logs.get(exec_id, [])
    new_lines = logs[offset:]
    is_running = exec_id in _running_processes
    return {
        "lines": new_lines,
        "offset": len(logs),
        "running": is_running,
    }

@router.get("/{script_id}/status")
async def get_execution_status(script_id: int):
    execs = _db().list_executions(script_id, limit=1)
    if not execs:
        return {"status": "no_executions"}
    return execs[0]

@router.post("/execution/{exec_id}/stop")
async def stop_execution(exec_id: int):
    proc = _running_processes.get(exec_id)
    if proc:
        try:
            # Kill process tree (node + chrome) on Windows
            import platform
            if platform.system() == "Windows":
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    capture_output=True, timeout=5
                )
            else:
                proc.terminate()
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        _running_processes.pop(exec_id, None)
        _db().update_execution(exec_id, status="cancelled",
            finished_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        return {"status": "stopped"}
    return {"status": "not_running"}

@router.get("/executions/history")
async def execution_history(limit: int = 50):
    return {"executions": _db().list_executions(limit=limit)}


# ── Browser Preview ──

_preview_processes = {}

@router.post("/preview/launch")
async def launch_preview(request: Request):
    """Launch a browser for preview/element picking."""
    body = await request.json()
    profile = body.get("profile", "")
    url = body.get("url", "about:blank")

    ext_dir = os.path.dirname(os.path.abspath(__file__))
    preview_path = os.path.join(ext_dir, "runner", "preview_server.js")

    # Find available port
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("", 0))
    port = sock.getsockname()[1]
    sock.close()

    env = _get_node_env()
    profiles_dir = _get_profiles_dir()
    proc = subprocess.Popen(
        ["node", preview_path, "--profile", profile or "default",
         "--url", url, "--port", str(port),
         "--profiles-dir", profiles_dir],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        cwd=ext_dir, encoding="utf-8", errors="replace",
        env=env,
    )
    session_id = f"preview_{int(time.time())}"
    _preview_processes[session_id] = {"proc": proc, "port": port, "profile": profile}
    return {"status": "launched", "session_id": session_id, "port": port}

@router.post("/preview/stop")
async def stop_preview(request: Request):
    body = await request.json()
    session_id = body.get("session_id", "")
    info = _preview_processes.pop(session_id, None)
    if info:
        try:
            info["proc"].terminate()
        except Exception:
            pass
        return {"status": "stopped"}
    return {"status": "not_found"}


# ── WebSocket Proxy for Remote Access ──
# When accessing via tunnel domain, ws://localhost:{port} is unreachable.
# This endpoint proxies WebSocket traffic through the main server.

from fastapi import WebSocket, WebSocketDisconnect
import asyncio

@router.websocket("/preview/ws/{port}")
async def ws_preview_proxy(websocket: WebSocket, port: int):
    """Proxy WebSocket connection to the local preview server.

    Checked here because HTTP middleware never runs for a WebSocket: Starlette
    dispatches the "websocket" scope past every @app.middleware("http"),
    including the login gate. Without this, the route proxies raw traffic to any
    localhost port a caller names, with no credential at all.
    """
    from tubecli.core.ws_auth import reject_unless_allowed

    if not await reject_unless_allowed(websocket):
        return

    try:
        import aiohttp
    except ImportError:
        logger.error("[WS Proxy] aiohttp not installed. Run: pip install aiohttp")
        try:
            await websocket.close(code=1011, reason="aiohttp not installed on server")
        except Exception:
            pass
        return

    session = aiohttp.ClientSession()
    local_ws = None
    try:
        # Connect to the upstream preview server BEFORE accepting the client. If
        # the run has finished, that server is gone; accepting first would make
        # the client log a phantom "connected" and then immediately reconnect —
        # open → dead upstream → close → open … forever. Rejecting the handshake
        # instead means the client's WS never opens, so its own reconnect limit
        # engages and it falls back to screenshots.
        try:
            local_ws = await session.ws_connect(f"http://localhost:{port}", timeout=10)
        except Exception as e:
            logger.info(f"[WS Proxy] upstream :{port} unreachable ({e}); rejecting handshake")
            try:
                await websocket.close(code=1013, reason="preview server not available")
            except Exception:
                pass
            return

        await websocket.accept()
        logger.info(f"[WS Proxy] Connected to local preview server on port {port}")

        async def forward_to_local():
            """Client → Local preview server"""
            try:
                while True:
                    data = await websocket.receive_text()
                    await local_ws.send_str(data)
            except (WebSocketDisconnect, Exception):
                pass
        
        async def forward_to_client():
            """Local preview server → Client"""
            try:
                async for msg in local_ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        await websocket.send_text(msg.data)
                    elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                        break
            except Exception:
                pass
        
        async def heartbeat():
            """Keep connection alive through reverse proxies (Cloudflare, nginx)"""
            try:
                while True:
                    await asyncio.sleep(15)
                    try:
                        await local_ws.ping()
                    except Exception:
                        break
            except asyncio.CancelledError:
                pass
        
        # Run all three tasks concurrently
        done, pending = await asyncio.wait(
            [asyncio.create_task(forward_to_local()),
             asyncio.create_task(forward_to_client()),
             asyncio.create_task(heartbeat())],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
    except Exception as e:
        logger.error(f"[WS Proxy] Error: {e}")
        try:
            await websocket.close(code=1011, reason=str(e)[:120])
        except Exception:
            pass
    finally:
        # Always close the session, even when ws_connect failed — the old guard
        # (`if local_ws:`) skipped it on a failed connect, leaking one aiohttp
        # ClientSession per reconnect attempt (dozens, in a reconnect loop).
        if local_ws:
            try:
                await local_ws.close()
            except Exception:
                pass
        await session.close()


# ── Screenshot proxy for remote access ──
@router.get("/preview/screenshot/{port}")
async def proxy_screenshot(port: int):
    """Proxy screenshot from local preview server for remote access."""
    import asyncio
    try:
        import requests as _requests
        resp = await asyncio.to_thread(
            _requests.get, f"http://localhost:{port}/screenshot", timeout=10
        )
        if resp.status_code == 200:
            from fastapi.responses import Response
            return Response(content=resp.content, media_type="image/jpeg")
    except Exception as e:
        logger.error(f"[Screenshot Proxy] Error: {e}")
    raise HTTPException(502, "Preview server unavailable")


# ── AI Generate Script ──

@router.post("/generate")
async def ai_generate_script(request: Request):
    """Generate automation steps from a natural language description using AI."""
    body = await request.json()
    prompt_text = body.get("prompt", "")
    script_name = body.get("name", "AI Generated Script")
    target_url = body.get("target_url", "")
    selected_provider = body.get("provider", "auto")

    if not prompt_text:
        raise HTTPException(400, "Missing 'prompt' field")

    system_prompt = f"""You are an expert browser automation script generator for Script Studio.
Generate a JSON object with automation steps based on the user's description.
The script MUST behave like a real human user — not a robot.

Available step types:
- navigate: Go to URL. params: {{ url: string }}
- click: Click element. selector: CSS selector
- type: Type text. selector: CSS selector, params: {{ text: string, clear_first: bool }}
- wait: Wait for element. selector: CSS selector, params: {{ state: "visible"|"hidden", timeout: number }}
- sleep: Random delay. params: {{ ms: number }} (use 1000-3000 for natural pauses)
- scroll: Scroll page. params: {{ direction: "down"|"up", amount: 200-600 }}
- mouse_move: Move mouse to random area. params: {{ x: number, y: number }} (omit for random position)
- hover: Hover over element. selector: CSS selector
- evaluate: Run JS code. params: {{ code: string, save_as: string }}
- extract: Extract data. selector: CSS selector, params: {{ attribute: "innerText"|"innerHTML"|"href"|"src"|"value", save_as: string }}
- screenshot: Take screenshot. params: {{ save_as: string, full_page: bool }}
- keyboard: Press key. params: {{ key: "Enter"|"Tab"|"Escape"|etc }}
- condition: If/else. params: {{ check: "JS expression", then_steps: [...], else_steps: [...] }}
- loop: Repeat steps. params: {{ count: number, delay: number, steps: [...], break_on: "JS expression" }}
- download: Download file. selector: trigger element, params: {{ output_dir: string, filename: string }}
- fetch_otp: Fetch TOTP/2FA code from system API. params: {{ secret: "{{{{totp_secret}}}}", save_as: "otp_code" }}
- wait_network_response: Wait for an HTTP network request/response. params: {{ url_pattern: string, status: number, save_as: string }} (use when you need to wait for and save API/JSON data from background traffic instead of scraping fragile DOM elements)

SYSTEM 2FA/OTP API:
The system has a built-in TOTP API for automatic 2FA code generation.
Use the "fetch_otp" step type to get OTP codes during login flows.

To handle 2FA in scripts:
  {{ "type": "fetch_otp", "label": "Get 2FA code", "params": {{ "secret": "{{{{totp_secret}}}}", "save_as": "otp_code" }} }}
  {{ "type": "type", "label": "Enter 2FA code", "selector": "input#totpPin, input[name='totpPin'], input[type='tel'], input[autocomplete='one-time-code']", "params": {{ "text": "{{{{otp_code}}}}", "clear_first": true }} }}

When generating LOGIN scripts that involve 2FA:
- Add a variable: {{ "name": "totp_secret", "default": "", "description": "TOTP/2FA secret key (base32)" }}
- After the password step, add a condition to check if 2FA page appeared
- Use fetch_otp to get the code, then type it

Google 2FA selectors (language-agnostic):
- 2FA input: input#totpPin, input[name="totpPin"], input[type="tel"], input[autocomplete="one-time-code"]
- Next button after 2FA: #totpNext button, button[jsname="LgbsSe"]

CRITICAL RULES FOR HUMAN-LIKE BEHAVIOR:
1. Add a "sleep" step (1000-3000ms) between major actions (after navigate, after click, before type)
2. Add "scroll" steps before interacting with elements below the fold (comment sections, footers)
3. MANDATORY: Before EVERY "click" step, add a "hover" step on the SAME selector. The mouse cursor must visually move to the button/element before clicking. This simulates a real human who moves their hand to the button before pressing.
   Pattern: hover(selector) → sleep(300-800ms) → click(selector)
4. Add "mouse_move" steps with random positions between unrelated actions to simulate idle mouse drift
5. After loading a page, add a "sleep" (2000-4000ms) to simulate reading
6. Use "scroll" with direction "down" and amount 300-500 to reveal lower content naturally
7. Between typing and pressing Enter, add a short "sleep" (500-1500ms)
8. Before typing in an input, add "hover" on the input selector first, then "sleep" 200-500ms, then "click" on it, then "type"
9. Use "mouse_move" without specific x/y (random) when transitioning between different page sections

CRITICAL RULES FOR PAGE STATE TRACKING:
10. MANDATORY: After EVERY click that causes page navigation (clicking a link, search result, submit button, "Next" button, login button), you MUST add a "wait" step for a KEY ELEMENT on the NEW page BEFORE any further interaction.
    Pattern: click(link) → wait(element_on_new_page, timeout: 15000) → sleep(2000) → next action
11. MANDATORY: After a form submit or login click, add a "wait" for an element that ONLY exists on the success/next page (e.g. wait for dashboard, wait for profile icon, wait for the next form field).
12. After clicking a search button or pressing Enter to search, ALWAYS add a "wait" step for the search results container before interacting with results.
13. NEVER put two consecutive "click" steps that target different pages without a "wait" between them.
14. If a click might trigger a CAPTCHA, popup, or modal, add a "sleep" (3000-5000ms) after the click AND a "wait" with retry_count: 2 for the expected next element.

WRONG (no page state tracking — will fail):
  click(a.search-result) → click(#like-button)  ← #like-button doesn't exist yet!

RIGHT (waits for new page before interacting):
  click(a.search-result) → wait(#video-player, timeout: 15000) → sleep(2000) → hover(#like-button) → click(#like-button)

COMPLETE FLOW EXAMPLE for clicking a link that navigates:
  {{ "type": "hover", "label": "Hover over first result", "selector": "a.result-link" }}
  {{ "type": "sleep", "label": "Pause before click", "params": {{ "ms": 500 }} }}
  {{ "type": "click", "label": "Click first result", "selector": "a.result-link" }}
  {{ "type": "wait", "label": "Wait for new page to load", "selector": "body main, #content, article", "params": {{ "state": "visible", "timeout": 15000 }} }}
  {{ "type": "sleep", "label": "Read new page", "params": {{ "ms": 3000 }} }}

Variables can be referenced with {{{{var_name}}}} in any string field.

Output format (JSON only, no markdown):
{{
  "name": "{script_name}",
  "description": "...",
  "category": "video|image|audio|scraping|general",
  "target_url": "{target_url}",
  "steps": [
    {{ "type": "navigate", "label": "Go to site", "selector": "", "params": {{ "url": "https://..." }}, "enabled": true, "on_error": "abort", "retry_count": 0 }},
    ...
  ],
  "variables": [
    {{ "name": "var_name", "default": "value", "description": "..." }},
    ...
  ]
}}

User request: {prompt_text}
{f'Target URL: {target_url}' if target_url else ''}

Generate realistic, working CSS selectors. Use language-agnostic selectors (IDs, data-attributes, roles) over text-based selectors. Output ONLY the JSON object."""

    try:
        from tubecli.extensions.cloud_api.extension import key_manager
        from tubecli.core.ai_generator import (
            call_gemini, call_openai_compatible, call_claude, call_ollama, extract_json
        )

        # Resolve providers to try
        selected_model = body.get("model", "")
        providers = _resolve_providers(selected_provider)
        raw = None
        used_provider = None

        for provider in providers:
            api_key = key_manager.get_active_key(provider) if provider not in ["ollama", "9router"] else (key_manager.get_active_key("9router") or "9router")
            if not api_key and provider not in ["ollama", "9router"]:
                continue

            try:
                if provider == "gemini":
                    model_to_use = selected_model or "gemini-2.0-flash"
                    raw = call_gemini(model_to_use, api_key, system_prompt)
                elif provider == "deepseek":
                    model_to_use = selected_model or "deepseek-v4-flash"
                    raw = call_openai_compatible(model_to_use, api_key, system_prompt, base_url="https://api.deepseek.com/v1")
                elif provider == "grok":
                    model_to_use = selected_model or "grok-3-mini-fast"
                    raw = call_openai_compatible(model_to_use, api_key, system_prompt, base_url="https://api.x.ai/v1")
                elif provider == "chatgpt":
                    model_to_use = selected_model or "gpt-4o-mini"
                    raw = call_openai_compatible(model_to_use, api_key, system_prompt)
                elif provider == "9router":
                    model_to_use = selected_model or "deepseek-chat"
                    raw = call_openai_compatible(model_to_use, api_key, system_prompt, base_url="http://localhost:20128/v1")
                elif provider == "ollama":
                    model_to_use = selected_model or "qwen2.5:7b"
                    raw = call_ollama(model_to_use, system_prompt)

                if raw and not raw.startswith("[ERROR]") and not raw.startswith("[QUOTA_ERROR]"):
                    used_provider = provider
                    break
            except Exception:
                continue

        if not raw or raw.startswith("[ERROR]") or raw.startswith("[QUOTA_ERROR]"):
            raise HTTPException(500, f"AI generation failed: {raw or 'No API keys available'}")

        json_str = extract_json(raw)
        parsed = json.loads(json_str)

        # Save to JSON
        script = _store().create_script(
            name=parsed.get("name", script_name),
            description=parsed.get("description", prompt_text),
            category=parsed.get("category", "general"),
            target_url=parsed.get("target_url", target_url),
            steps=parsed.get("steps", []),
            variables=parsed.get("variables", []),
        )

        return {
            "status": "generated",
            "script": script,
            "provider": used_provider,
            "steps_count": len(parsed.get("steps", [])),
        }

    except json.JSONDecodeError:
        raise HTTPException(500, f"AI returned invalid JSON")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"AI generate error: {e}")
        raise HTTPException(500, str(e))


# ── Chat Bot (Script Assistant) ──

@router.post("/chat")
async def chat_with_script(request: Request):
    """AI chat assistant for modifying/explaining scripts."""
    body = await request.json()
    message = body.get("message", "")
    history = body.get("history", [])
    script = body.get("script")
    selected_provider = body.get("provider", "auto")

    if not message:
        raise HTTPException(400, "Missing 'message'")

    script_context = ""
    if script:
        steps_summary = ""
        for i, step in enumerate(script.get("steps", [])):
            label = step.get("label", step.get("type", "?"))
            sel = step.get("selector", "")
            params = step.get("params", {})
            steps_summary += f"  {i}: [{step.get('type')}] {label}"
            if sel: steps_summary += f" (selector: {sel})"
            if params.get("text"): steps_summary += f" text=\"{params['text']}\""
            if params.get("url"): steps_summary += f" url={params['url']}"
            if params.get("prompt"): steps_summary += f" prompt=\"{params['prompt']}\""
            steps_summary += "\n"

        script_context = f"Current script: \"{script.get('name', '')}\"\nSteps:\n{steps_summary}"

    system_prompt = f"""You are Script Assistant for Script Studio (browser automation).
Help users modify, explain, and improve their scripts.

{script_context}

Available step types: navigate, click, type, wait, sleep, scroll, mouse_move, hover, keyboard, evaluate, extract, screenshot, download, condition, loop, ai_generate, fetch_otp, wait_network_response.

The "wait_network_response" step:
- params.url_pattern: keyword or path to match request URL (e.g. "/api/v1/data")
- params.status: expected HTTP status code (default 200)
- params.save_as: variable name to save JSON or text response
- Best practice: use this to get structured data from API traffic instead of scraping DOM.

The "ai_generate" step generates dynamic text at runtime:
- params.prompt: AI instruction (e.g. "Write a comment about this video")
- params.extract_selector: CSS selector to get page context (e.g. "h1" for title)
- params.save_as: variable name to store result
- Use {{{{variable_name}}}} in subsequent type steps

SYSTEM 2FA/OTP API:
- API: GET /api/v1/browser/2fa?secret=<BASE32_SECRET> → returns {{"code": "123456", "remaining": 25}}
- To auto-fill 2FA: use "evaluate" step to fetch code, save to variable, then "type" the variable
- Example: evaluate(code: "const r = await fetch('/api/v1/browser/2fa?secret='+encodeURIComponent('{{{{totp_secret}}}}'));const d=await r.json();return d.code;", save_as: "otp_code") → type(selector: "input#totpPin", text: "{{{{otp_code}}}}")
- Google 2FA selectors: input#totpPin, input[name="totpPin"], input[type="tel"], input[autocomplete="one-time-code"]

RULES:
1. Reply in user's language.
2. To MODIFY script, include JSON: {{"updated_steps": [full steps array]}}
3. For explanations, use plain text only.
4. Keep responses concise.
5. MANDATORY: Before EVERY "click" step, always add a "hover" step with the SAME selector, then a "sleep" (300-800ms). The cursor must move to the element before clicking. Pattern: hover → sleep → click.
6. Before typing in an input, add hover → sleep → click → type.
7. Use language-agnostic selectors (IDs, data-attributes, roles) over text-based selectors.
8. MANDATORY: After EVERY click that causes page navigation (link, submit, search), add a "wait" step for a KEY element on the NEW page before any further interaction. Pattern: click → wait(new_page_element, timeout:15000) → sleep(2000).
9. NEVER put two consecutive clicks targeting different pages without a "wait" between them.

User: {message}"""

    try:
        from tubecli.extensions.cloud_api.extension import key_manager
        from tubecli.core.ai_generator import (
            call_gemini, call_openai_compatible, call_ollama, extract_json
        )

        # Resolve providers to try
        selected_model = body.get("model", "")
        providers = _resolve_providers(selected_provider)
        raw = None

        for provider in providers:
            api_key = key_manager.get_active_key(provider) if provider not in ["ollama", "9router"] else (key_manager.get_active_key("9router") or "9router")
            if not api_key and provider not in ["ollama", "9router"]: continue
            try:
                if provider == "gemini":
                    model_to_use = selected_model or "gemini-2.0-flash"
                    raw = call_gemini(model_to_use, api_key, system_prompt)
                elif provider == "deepseek":
                    model_to_use = selected_model or "deepseek-v4-flash"
                    raw = call_openai_compatible(model_to_use, api_key, system_prompt, base_url="https://api.deepseek.com/v1")
                elif provider == "grok":
                    model_to_use = selected_model or "grok-3-mini-fast"
                    raw = call_openai_compatible(model_to_use, api_key, system_prompt, base_url="https://api.x.ai/v1")
                elif provider == "chatgpt":
                    model_to_use = selected_model or "gpt-4o-mini"
                    raw = call_openai_compatible(model_to_use, api_key, system_prompt)
                elif provider == "9router":
                    model_to_use = selected_model or "deepseek-chat"
                    raw = call_openai_compatible(model_to_use, api_key, system_prompt, base_url="http://localhost:20128/v1")
                elif provider == "ollama":
                    model_to_use = selected_model or "qwen2.5:7b"
                    raw = call_ollama(model_to_use, system_prompt)
                if raw and not raw.startswith("[ERROR]") and not raw.startswith("[QUOTA_ERROR]"):
                    break
            except Exception: continue

        if not raw:
            return {"reply": "Không thể kết nối AI. Kiểm tra API keys.", "updated_steps": None}

        updated_steps = None
        reply = raw.replace("```json", "").replace("```", "").strip()

        if '"updated_steps"' in raw:
            try:
                json_str = extract_json(raw)
                parsed = json.loads(json_str)
                if "updated_steps" in parsed:
                    updated_steps = parsed["updated_steps"]
                    reply = "Đã chỉnh sửa script theo yêu cầu."
            except Exception: pass

        if reply.startswith("{") and '"updated_steps"' in reply:
            reply = "Đã chỉnh sửa script theo yêu cầu."

        return {"reply": reply, "updated_steps": updated_steps}

    except Exception as e:
        logger.error(f"Chat error: {e}")
        return {"reply": f"Lỗi: {str(e)}", "updated_steps": None}


# ── AI Auto-Fix Selector ──

@router.post("/ai-fix")
async def ai_fix_selector(request: Request):
    """AI analyzes page HTML and suggests correct CSS selector or recovery action."""
    body = await request.json()
    failed_selector = body.get("selector", "")
    step_type = body.get("step_type", "click")
    step_label = body.get("label", "")
    error_msg = body.get("error", "")
    page_html = body.get("page_html", "")[:15000]
    page_url = body.get("page_url", "")
    visible_text = body.get("visible_text", "")[:3000]

    prompt = f"""You are a browser automation expert debugging a Playwright script.
A step FAILED — the element was not visible/found within the timeout.

IMPORTANT: The selector may actually be correct in the HTML, but something is BLOCKING it:
- Cookie consent dialogs/banners
- GDPR accept buttons
- Login/signup modals
- Age verification popups  
- "Accept cookies" overlays
- Any modal/dialog covering the page

Page URL: {page_url}
Step type: {step_type}
Step label: {step_label}
Failed selector: {failed_selector}
Error: {error_msg}

Visible text on page (what user sees):
{visible_text}

Page HTML (truncated):
{page_html[:12000]}

ANALYZE:
1. Check: is there a consent dialog, cookie banner, overlay, or modal blocking the page?
2. Look for buttons with text like "Accept all", "Accept", "I agree", "OK", "Continue", "Consent", "Reject all"
3. If yes: provide CSS selectors to CLICK those buttons via Playwright (not JS evaluate)
4. Check: is the original selector correct or suggest a better one?

Output ONLY this JSON (no markdown):
{{
  "selector": "correct-css-selector-or-same-if-correct",
  "pre_action_clicks": ["button[aria-label='Accept all']", "button.consent-accept"],
  "pre_action_js": "optional JS to run after clicking, or empty string",
  "reason": "brief explanation"
}}

RULES for pre_action_clicks:
- Use real CSS selectors from the HTML above
- These will be clicked using Playwright page.click() which handles web components
- Include ALL possible selectors for the dismiss button (ordered by most likely)
- If no overlay, use empty array []

If selector is correct, keep it and focus on dismissing overlays."""

    try:
        from tubecli.extensions.cloud_api.extension import key_manager
        from tubecli.core.ai_generator import (
            call_gemini, call_openai_compatible, extract_json
        )

        providers = ["deepseek", "gemini", "grok"]
        raw = None
        for provider in providers:
            api_key = key_manager.get_active_key(provider)
            if not api_key:
                continue
            try:
                if provider == "gemini":
                    raw = call_gemini("gemini-2.0-flash", api_key, prompt)
                elif provider == "deepseek":
                    raw = call_openai_compatible("deepseek-v4-flash", api_key, prompt, base_url="https://api.deepseek.com/v1")
                elif provider == "grok":
                    raw = call_openai_compatible("grok-3-mini-fast", api_key, prompt, base_url="https://api.x.ai/v1")
                if raw and not raw.startswith("[ERROR]"):
                    break
            except Exception:
                continue

        if not raw or raw.startswith("[ERROR]"):
            return {"status": "no_fix", "reason": "AI unavailable"}

        json_str = extract_json(raw)
        parsed = json.loads(json_str)
        return {
            "status": "fixed",
            "selector": parsed.get("selector", ""),
            "pre_action_clicks": parsed.get("pre_action_clicks", []),
            "pre_action_js": parsed.get("pre_action_js", ""),
            "reason": parsed.get("reason", ""),
        }
    except Exception as e:
        return {"status": "no_fix", "reason": str(e)}


# ── AI Generate Steps at Position ──

@router.post("/{script_id}/ai-generate-steps")
async def ai_generate_steps_at(script_id: str, request: Request):
    """AI generates steps to insert at a specific position in the script."""
    body = await request.json()
    prompt_text = body.get("prompt", "")
    insert_after = body.get("insert_after", 0)
    context_before = body.get("context_before", [])
    context_after = body.get("context_after", [])
    variables = body.get("variables", [])

    if not prompt_text:
        raise HTTPException(400, "Missing 'prompt' field")

    # Format context for AI
    ctx_before_str = ""
    for i, step in enumerate(context_before):
        lbl = step.get("label", step.get("type", "?"))
        ctx_before_str += f"  [{step.get('type')}] {lbl}"
        if step.get("selector"): ctx_before_str += f" selector={step['selector']}"
        p = step.get("params", {})
        if p.get("url"): ctx_before_str += f" url={p['url']}"
        if p.get("text"): ctx_before_str += f" text=\"{p['text']}\""
        if p.get("ms"): ctx_before_str += f" ms={p['ms']}"
        ctx_before_str += "\n"

    ctx_after_str = ""
    for i, step in enumerate(context_after):
        lbl = step.get("label", step.get("type", "?"))
        ctx_after_str += f"  [{step.get('type')}] {lbl}"
        if step.get("selector"): ctx_after_str += f" selector={step['selector']}"
        p = step.get("params", {})
        if p.get("url"): ctx_after_str += f" url={p['url']}"
        if p.get("text"): ctx_after_str += f" text=\"{p['text']}\""
        if p.get("ms"): ctx_after_str += f" ms={p['ms']}"
        ctx_after_str += "\n"

    vars_str = ", ".join([f"{{{{{v.get('name', '')}}}}}" for v in variables if v.get("name")])

    system_prompt = f"""You are an expert browser automation step generator for Script Studio.
Generate ONLY the NEW steps to INSERT between existing steps in a script.

Available step types:
- navigate: Go to URL. params: {{ url: string }}
- click: Click element. selector: CSS selector
- type: Type text. selector: CSS selector, params: {{ text: string, clear_first: bool }}
- wait: Wait for element. selector: CSS selector, params: {{ state: "visible"|"hidden", timeout: number }}
- sleep: Random delay. params: {{ ms: number }}
- scroll: Scroll page. params: {{ direction: "down"|"up", amount: number }}
- mouse_move: Move mouse. params: {{ x: number, y: number }}
- hover: Hover element. selector: CSS selector
- evaluate: Run JS. params: {{ code: string, save_as: string }}
- extract: Extract data. selector: CSS selector, params: {{ attribute: string, save_as: string }}
- keyboard: Press key. params: {{ key: string }}
- condition: If/else. params: {{ check: "JS expression", then_steps: [...], else_steps: [...] }}
- loop: Repeat. params: {{ count: number, delay: number, steps: [...] }}
- ai_generate: AI text. params: {{ prompt: string, save_as: string }}
- call_function: Call function. params: {{ function_slug: string, inputs: {{}}, outputs: {{}} }}
- wait_network_response: Wait for an HTTP network response. params: {{ url_pattern: string, status: number, save_as: string }} (use when you want to intercept and capture API JSON data from background traffic instead of cào DOM)

EXISTING CONTEXT:
Steps BEFORE insertion point:
{ctx_before_str or '  (beginning of script)'}

Steps AFTER insertion point:
{ctx_after_str or '  (end of script)'}

Existing variables: {vars_str or 'none'}

RULES:
1. Generate ONLY new steps — do NOT repeat existing steps.
2. Add sleep steps (1000-3000ms) between major actions.
3. Before every click, add hover → sleep(300-800ms) → click.
4. After navigation clicks, add wait for new page element.
5. Variables: use {{{{var_name}}}} syntax. If you need new variables, include them.
6. Output ONLY this JSON (no markdown):
{{
  "steps": [
    {{ "type": "...", "label": "...", "selector": "...", "params": {{...}}, "enabled": true, "on_error": "abort", "retry_count": 0 }},
    ...
  ],
  "variables": [
    {{ "name": "var_name", "type": "string", "default": "" }}
  ]
}}

User request: {prompt_text}
Generate realistic, working CSS selectors. Output ONLY the JSON."""

    try:
        from tubecli.extensions.cloud_api.extension import key_manager
        from tubecli.core.ai_generator import (
            call_gemini, call_openai_compatible, call_ollama, extract_json
        )

        selected_provider = body.get("provider", "auto")
        selected_model = body.get("model", "")
        providers = _resolve_providers(selected_provider)
        raw = None
        used_provider = None

        for provider in providers:
            api_key = key_manager.get_active_key(provider) if provider not in ["ollama", "9router"] else (key_manager.get_active_key("9router") or "9router")
            if not api_key and provider not in ["ollama", "9router"]:
                continue
            try:
                if provider == "gemini":
                    model_to_use = selected_model or "gemini-2.0-flash"
                    raw = call_gemini(model_to_use, api_key, system_prompt)
                elif provider == "deepseek":
                    model_to_use = selected_model or "deepseek-v4-flash"
                    raw = call_openai_compatible(model_to_use, api_key, system_prompt, base_url="https://api.deepseek.com/v1")
                elif provider == "grok":
                    model_to_use = selected_model or "grok-3-mini-fast"
                    raw = call_openai_compatible(model_to_use, api_key, system_prompt, base_url="https://api.x.ai/v1")
                elif provider == "chatgpt":
                    model_to_use = selected_model or "gpt-4o-mini"
                    raw = call_openai_compatible(model_to_use, api_key, system_prompt)
                elif provider == "9router":
                    model_to_use = selected_model or "deepseek-chat"
                    raw = call_openai_compatible(model_to_use, api_key, system_prompt, base_url="http://localhost:20128/v1")
                elif provider == "ollama":
                    model_to_use = selected_model or "qwen2.5:7b"
                    raw = call_ollama(model_to_use, system_prompt)

                if raw and not raw.startswith("[ERROR]") and not raw.startswith("[QUOTA_ERROR]"):
                    used_provider = provider
                    break
            except Exception:
                continue

        if not raw or raw.startswith("[ERROR]") or raw.startswith("[QUOTA_ERROR]"):
            raise HTTPException(500, f"AI generation failed: {raw or 'No API keys available'}")

        json_str = extract_json(raw)
        parsed = json.loads(json_str)

        steps = parsed.get("steps", [])
        # Ensure each step has required fields
        for step in steps:
            step.setdefault("id", f"step_{int(time.time() * 1000)}")
            step.setdefault("enabled", True)
            step.setdefault("selector", "")
            step.setdefault("params", {})
            step.setdefault("on_error", "abort")
            step.setdefault("retry_count", 0)

        return {
            "status": "generated",
            "steps": steps,
            "variables": parsed.get("variables", []),
            "provider": used_provider,
        }

    except json.JSONDecodeError:
        raise HTTPException(500, "AI returned invalid JSON")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"AI generate steps error: {e}")
        raise HTTPException(500, str(e))


# ── Skill API ──

@router.get("/skill/{slug}")
async def get_skill_script(slug: str):
    """Get a script by slug — used by other extensions."""
    script = _store().get_script(slug)
    if not script:
        raise HTTPException(404, f"Script '{slug}' not found")
    return script

@router.post("/skill/{slug}/run")
async def run_skill_script(slug: str, request: Request):
    """Run a script by slug — used by other extensions."""
    script = _store().get_script(slug)
    if not script:
        raise HTTPException(404, f"Script '{slug}' not found")
    body = await request.json()
    req = RunRequest(
        profile=body.get("profile", ""),
        variables=body.get("variables", {}),
        headless=body.get("headless", True),
    )
    return await run_script(slug, req)


# ── Import/Export ──

@router.post("/import/json")
async def import_json(request: Request):
    """Import a script from JSON."""
    body = await request.json()
    script_data = body.get("script", {})
    if not script_data.get("name"):
        raise HTTPException(400, "Missing script name")
    script = _store().create_script(
        name=script_data["name"],
        slug=script_data.get("slug"),
        description=script_data.get("description", ""),
        category=script_data.get("category", "general"),
        target_url=script_data.get("target_url", ""),
        tags=script_data.get("tags", []),
        steps=script_data.get("steps", []),
        variables=script_data.get("variables", []),
    )
    return {"status": "imported", "script": script}

@router.get("/{script_id}/export/json")
async def export_json(script_id: str):
    script = _store().get_script(script_id)
    if not script:
        raise HTTPException(404, "Script not found")
    export = {k: v for k, v in script.items() if k not in ("created_at", "updated_at")}
    return {"script": export}


# ── Import JS (AI Parser) ──

@router.post("/import/js")
async def import_js_file(request: Request):
    """Import a .js automation file — parse into Script Studio steps using AI."""
    body = await request.json()
    js_content = body.get("content", "")
    filename = body.get("filename", "imported.js")
    use_ai = body.get("use_ai", True)

    if not js_content:
        raise HTTPException(400, "Missing 'content' field")

    import sys
    ext_dir = os.path.dirname(os.path.abspath(__file__))
    if ext_dir not in sys.path:
        sys.path.insert(0, ext_dir)

    from parser.ai_parser import parse_js_to_steps, ai_parse_js_to_steps

    if use_ai:
        parsed = await ai_parse_js_to_steps(js_content, filename)
    else:
        parsed = parse_js_to_steps(js_content, filename)

    # Save to JSON
    script = _store().create_script(
        name=parsed.get("name", filename),
        description=parsed.get("description", ""),
        category=parsed.get("category", "general"),
        target_url=parsed.get("target_url", ""),
        steps=parsed.get("steps", []),
        variables=parsed.get("variables", []),
    )
    return {
        "status": "imported",
        "script": script,
        "parsed_steps": len(parsed.get("steps", [])),
        "parsed_variables": len(parsed.get("variables", [])),
    }

@router.post("/import/js/parse")
async def parse_js_preview(request: Request):
    """Preview parsing without saving — returns parsed steps for review."""
    body = await request.json()
    js_content = body.get("content", "")
    filename = body.get("filename", "preview.js")
    use_ai = body.get("use_ai", True)

    if not js_content:
        raise HTTPException(400, "Missing 'content' field")

    import sys
    ext_dir = os.path.dirname(os.path.abspath(__file__))
    if ext_dir not in sys.path:
        sys.path.insert(0, ext_dir)

    from parser.ai_parser import parse_js_to_steps, ai_parse_js_to_steps

    if use_ai:
        parsed = await ai_parse_js_to_steps(js_content, filename)
    else:
        parsed = parse_js_to_steps(js_content, filename)

    return {"status": "parsed", "result": parsed}


# ── Elements ──

@router.get("/{script_id}/elements")
async def list_elements(script_id: int):
    return {"elements": _db().list_elements(script_id)}

@router.post("/{script_id}/elements")
async def save_element(script_id: int, request: Request):
    body = await request.json()
    elem_id = _db().save_element(
        script_id=script_id,
        step_index=body.get("step_index", 0),
        name=body.get("name", ""),
        selector=body.get("selector", ""),
        xpath=body.get("xpath", ""),
        screenshot=body.get("screenshot", ""),
        attributes=body.get("attributes", {}),
        page_url=body.get("page_url", ""),
    )
    return {"status": "saved", "element_id": elem_id}
