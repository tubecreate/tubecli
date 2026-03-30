"""
ZhiYing REST API Server
FastAPI-based REST API for agents, skills, and workflows.
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import os

app = FastAPI(
    title="ZhiYing API",
    description="REST API for ZhiYing — AI Agent management, skills, and workflows.",
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
    from zhiying.config import get_api_port
    return {"status": "ok", "message": "ZhiYing API is running", "port": get_api_port()}


# ── Version & Update ──────────────────────────────────────────────

@app.get("/api/v1/version")
async def get_version_info():
    import subprocess
    from zhiying import __version__, __build__
    info = {"version": __build__, "pip_version": __version__, "git_hash": None, "git_branch": None}
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
    import subprocess
    from zhiying import __build__
    try:
        repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        r = subprocess.run(["git", "pull"], capture_output=True, text=True, cwd=repo, timeout=30)
        return {"status": "success", "output": r.stdout.strip() or r.stderr.strip(), "version": __build__}
    except Exception as e:
        return {"status": "error", "output": str(e)}


# ── Agents ───────────────────────────────────────────────────────

@app.get("/api/v1/agents")
async def list_agents():
    from zhiying.core.agent import agent_manager
    agents = agent_manager.get_all()
    return {"agents": [a.to_dict() for a in agents], "count": len(agents)}

@app.post("/api/v1/agents/generate")
async def generate_agent_with_ai(req: AgentGenerateRequest):
    from zhiying.core.ai_generator import generate_agent_json
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
    from zhiying.core.agent import agent_manager
    agent = agent_manager.get(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent {agent_id} not found")
    return agent.to_dict()

@app.post("/api/v1/agents")
async def create_agent(req: AgentCreateRequest):
    from zhiying.core.agent import agent_manager
    agent = agent_manager.create(**req.model_dump(exclude_none=True))
    return {"status": "created", "agent": agent.to_dict()}

@app.put("/api/v1/agents/{agent_id}")
async def update_agent(agent_id: str, req: AgentUpdateRequest):
    from zhiying.core.agent import agent_manager
    agent = agent_manager.update(agent_id, **req.model_dump(exclude_none=True))
    if not agent:
        raise HTTPException(404, f"Agent {agent_id} not found")
    return {"status": "updated", "agent": agent.to_dict()}

@app.delete("/api/v1/agents/{agent_id}")
async def delete_agent(agent_id: str):
    from zhiying.core.agent import agent_manager
    if not agent_manager.delete(agent_id):
        raise HTTPException(404, f"Agent {agent_id} not found")
    return {"status": "deleted", "agent_id": agent_id}


# ── Agent Chat ───────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str


@app.post("/api/v1/agents/{agent_id}/chat")
async def agent_chat(agent_id: str, req: ChatRequest):
    """Chat with an agent. The brain dispatches skills automatically."""
    import datetime as _dt
    from zhiying.core.agent import agent_manager
    from zhiying.core.skill import skill_manager
    from zhiying.core.brain import AgentBrain

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
                from zhiying.core.config import config_manager
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
                from zhiying.i18n import t
                reply = t("brain.skill_run_error", name=skill.name, error=str(e))
        else:
            from zhiying.i18n import t
            reply = t("brain.skill_not_found", id=skill_id)

    elif action == "create_skill":
        # Feature: AI Self-Creation of Skill
        name = brain_result.get("skill_name", "New Skill")
        desc = brain_result.get("skill_desc", "")
        instructions = brain_result.get("skill_instructions", [])
        
        # Convert instructions into a text-based workflow SOP
        sop_text = "\n".join([f"{i+1}. {instr}" for i, instr in enumerate(instructions)])
        
        try:
            new_skill = skill_manager.create(
                name=name,
                description=desc or f"AI-generated skill: {name}",
                skill_type="AI Self-Created",
                workflow_data={"sop": sop_text, "nodes": [{"type": "text", "data": {"text": sop_text}}]},
                commands=[name.lower()]
            )
            from zhiying.i18n import t
            reply = t("brain.skill_created", name=name, desc=desc)
            skill_used = f"Created Skill: {name}"
        except Exception as e:
            from zhiying.i18n import t
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

    return {
        "reply": reply,
        "skill_used": skill_used,
        "history": history[-20:],  # return last 20 for UI
    }


@app.delete("/api/v1/agents/{agent_id}/chat")
async def clear_chat_history(agent_id: str):
    """Clear an agent's chat history."""
    from zhiying.core.agent import agent_manager
    agent = agent_manager.get(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent {agent_id} not found")
    agent_manager.update(agent_id, history_log=[])
    return {"status": "cleared", "agent_id": agent_id}

# ── Skills ───────────────────────────────────────────────────────

@app.get("/api/v1/skills")
async def list_skills():
    from zhiying.core.skill import skill_manager
    skills = skill_manager.get_all()
    return {"skills": [s.to_dict() for s in skills], "count": len(skills)}

@app.get("/api/v1/skills/{skill_id}")
async def get_skill(skill_id: str):
    from zhiying.core.skill import skill_manager
    skill = skill_manager.get(skill_id)
    if not skill:
        raise HTTPException(404, f"Skill {skill_id} not found")
    return skill.to_dict()

@app.post("/api/v1/skills")
async def create_skill(req: SkillCreateRequest):
    from zhiying.core.skill import skill_manager
    skill = skill_manager.create(**req.model_dump())
    return {"status": "created", "skill": skill.to_dict()}

@app.delete("/api/v1/skills/{skill_id}")
async def delete_skill(skill_id: str):
    from zhiying.core.skill import skill_manager
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
    from zhiying.core.skill import skill_manager

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
    from zhiying.core.skill import skill_manager
    from zhiying.nodes.registry import create_node_from_dict
    from zhiying.core.workflow_engine import WorkflowEngine

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
        from zhiying.i18n import t
        result["_skill_errors"] = errors
        result["_skill_guidance"] = guidance or [
            t("brain.workflow_error_guidance")
        ]

    return result


# ── Workflows ────────────────────────────────────────────────────

@app.post("/api/v1/workflows/generate")
async def generate_workflow_with_ai(req: WorkflowGenerateRequest):
    """Generate a workflow from a natural language prompt using AI."""
    from zhiying.core.ai_workflow_builder import generate_workflow
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
    from zhiying.nodes.registry import create_node_from_dict
    from zhiying.core.workflow_engine import WorkflowEngine

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
    from zhiying.config import DATA_DIR

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
    from zhiying.config import DATA_DIR

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
    from zhiying.config import DATA_DIR

    fpath = os.path.join(DATA_DIR, "workflows", name + ".json")
    if not os.path.exists(fpath):
        raise HTTPException(404, f"Workflow '{name}' not found")

    with open(fpath, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {"name": name, "workflow_data": data}


@app.delete("/api/v1/workflows/{name}")
async def delete_workflow(name: str):
    """Delete a saved workflow."""
    from zhiying.config import DATA_DIR

    fpath = os.path.join(DATA_DIR, "workflows", name + ".json")
    if not os.path.exists(fpath):
        raise HTTPException(404, f"Workflow '{name}' not found")

    os.remove(fpath)
    return {"status": "deleted", "name": name}


# ── Nodes ────────────────────────────────────────────────────────

@app.get("/api/v1/nodes")
async def list_nodes():
    from zhiying.nodes.registry import list_available_nodes
    return {"nodes": list_available_nodes()}


# ── Extensions Management ───────────────────────────────────────────

@app.get("/api/v1/extensions")
async def list_extensions():
    from zhiying.core.extension_manager import extension_manager
    extensions = extension_manager.get_all()
    return {"extensions": [p.to_dict() for p in extensions], "count": len(extensions)}

@app.post("/api/v1/extensions/{name}/enable")
async def enable_extension(name: str):
    from zhiying.core.extension_manager import extension_manager
    if extension_manager.enable(name):
        return {"status": "enabled", "extension": name}
    raise HTTPException(404, f"Extension '{name}' not found")

@app.post("/api/v1/extensions/{name}/disable")
async def disable_extension(name: str):
    from zhiying.core.extension_manager import extension_manager
    if extension_manager.disable(name):
        return {"status": "disabled", "extension": name}
    raise HTTPException(404, f"Extension '{name}' not found")

@app.put("/api/v1/extensions/{name}")
async def update_extension(name: str, req: ExtensionUpdateRequest):
    from zhiying.core.extension_manager import extension_manager
    extension = extension_manager.get(name)
    if not extension:
         raise HTTPException(404, f"Extension '{name}' not found")
    
    if req.port is not None:
        extension_manager.set_port(name, req.port)
        
    return {"status": "updated", "extension": extension.to_dict()}


@app.get("/api/v1/extensions/{name}/info")
async def extension_info(name: str):
    """Get detailed info about a extension including manifest and SKILL.md."""
    from zhiying.core.extension_manager import extension_manager
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
    from zhiying.core.extension_manager import extension_manager
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
    from zhiying.core.extension_manager import extension_manager
    result = extension_manager.install_from_git(req.git_url)
    if result["status"] == "error":
        raise HTTPException(400, result["message"])
    return result


@app.delete("/api/v1/extensions/{name}/uninstall")
async def uninstall_extension(name: str):
    """Uninstall an external extension."""
    from zhiying.core.extension_manager import extension_manager
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
    from zhiying.core.extension_manager import extension_manager

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
    SKIP_DIRS = {"__pycache__", ".git", "node_modules", ".venv", "venv"}
    SKIP_EXTS = {".pyc", ".pyo", ".egg-info"}
    MAX_FILE_SIZE = 500_000  # 500KB per file

    files = []
    all_imports: set = set()

    for root, dirs, filenames in os.walk(ext_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]

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
    req_deps_normalized = {r.replace("-", "_").lower() for r in req_deps}
    for module in sorted(all_imports):
        if module in _STDLIB:
            continue
        # Check if already covered by requirements.txt
        mod_normalized = module.replace("-", "_").lower()
        pip_name = IMPORT_TO_PIP.get(module)
        if not pip_name:
            continue  # Unknown mapping, skip
        pip_normalized = pip_name.replace("-", "_").lower()
        if pip_normalized in req_deps_normalized or mod_normalized in req_deps_normalized:
            continue  # Already in requirements.txt
        detected_deps.append(pip_name)

    # 3. Merge with existing manifest.dependencies (don't lose manually declared ones)
    read_manifest_path = os.path.join(ext_dir, "zhiying-extension.json")
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
    from zhiying.core.extension_manager import extension_manager
    return {"skill_mds": extension_manager.get_all_skill_mds()}


# ── System Version & Update ─────────────────────────────────────────

@app.get("/api/v1/system/version")
async def system_version():
    """Get current system version and git info."""
    import subprocess
    from zhiying import __version__
    from zhiying.config import BASE_DIR

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
    from zhiying import __version__
    from zhiying.config import BASE_DIR

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
    from zhiying import __version__
    from zhiying.config import BASE_DIR

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
        init_file = os.path.join(project_root, "zhiying", "__init__.py")
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
    from zhiying.core.extension_manager import extension_manager

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
    if not ext_dir or not os.path.isdir(os.path.join(ext_dir, ".git")):
        return {
            "name": name,
            "has_update": False,
            "message": "Extension is not a git repository.",
            "current_version": ext.version,
        }

    try:
        subprocess.run(
            ["git", "fetch", "origin"],
            cwd=ext_dir, capture_output=True, text=True, timeout=30,
        )

        r_count = subprocess.run(
            ["git", "rev-list", "--count", "HEAD..origin/main"],
            cwd=ext_dir, capture_output=True, text=True, timeout=10,
        )
        commits_behind = int(r_count.stdout.strip()) if r_count.returncode == 0 else 0

        changelog = []
        if commits_behind > 0:
            r_log = subprocess.run(
                ["git", "log", "--oneline", "HEAD..origin/main", "--format=%s"],
                cwd=ext_dir, capture_output=True, text=True, timeout=10,
            )
            if r_log.returncode == 0:
                changelog = [l.strip() for l in r_log.stdout.strip().split("\n") if l.strip()]

        return {
            "name": name,
            "has_update": commits_behind > 0,
            "current_version": ext.version,
            "commits_behind": commits_behind,
            "changelog": changelog[:10],
        }
    except Exception as e:
        raise HTTPException(500, f"Failed to check extension update: {e}")


@app.post("/api/v1/extensions/{name}/update")
async def update_extension(name: str):
    """Pull latest code for an external extension."""
    import subprocess
    from zhiying.core.extension_manager import extension_manager

    ext = extension_manager.get(name)
    if not ext:
        raise HTTPException(404, f"Extension '{name}' not found")

    if ext.extension_type != "external":
        raise HTTPException(400, "System extensions cannot be updated individually. Use System Update.")

    ext_dir = ext.extension_dir
    if not ext_dir or not os.path.isdir(os.path.join(ext_dir, ".git")):
        raise HTTPException(400, "Extension directory is not a git repository.")

    try:
        r_pull = subprocess.run(
            ["git", "pull", "origin", "main"],
            cwd=ext_dir, capture_output=True, text=True, timeout=60,
        )
        if r_pull.returncode != 0:
            return {"status": "error", "error": f"git pull failed: {r_pull.stderr}"}

        # Re-read manifest to get new version
        import json
        new_version = ext.version
        manifest_path = os.path.join(ext_dir, "zhiying-extension.json")
        if os.path.exists(manifest_path):
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                    new_version = manifest.get("version", ext.version)
            except Exception:
                pass

        return {
            "status": "success",
            "name": name,
            "new_version": new_version,
            "git_output": r_pull.stdout.strip()[:300],
            "message": f"Extension '{name}' updated. Restart API to apply.",
        }
    except Exception as e:
        raise HTTPException(500, f"Extension update failed: {e}")


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

    # 1. Built-in extensions: zhiying/extensions/*/locales/
    builtin_ext_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "extensions")
    _load_locales_from_dir(builtin_ext_dir)

    # 2. External extensions: data/extensions_external/*/locales/
    from zhiying.config import EXTENSIONS_EXTERNAL_DIR
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
    from zhiying.config import get_language, SUPPORTED_LANGUAGES
    return {
        "language": get_language(),
        "supported": SUPPORTED_LANGUAGES,
    }


@app.put("/api/v1/settings/language")
async def set_language_setting(req: LanguageUpdateRequest):
    """Update language setting."""
    from zhiying.config import set_language, SUPPORTED_LANGUAGES
    from zhiying.i18n import load_language
    if req.language not in SUPPORTED_LANGUAGES:
        raise HTTPException(400, f"Unsupported language: {req.language}. Supported: {SUPPORTED_LANGUAGES}")
    set_language(req.language)
    load_language(req.language)
    return {"status": "updated", "language": req.language}


# ── Register Extension Routes ───────────────────────────────────────
from zhiying.core.extension_manager import extension_manager
extension_manager.discover_extensions()
extension_manager.register_api_routes(app)
