"""
TubeCLI REST API Server
FastAPI-based REST API for agents, skills, and workflows.
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

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


# ── Pydantic Models ──────────────────────────────────────────────

class AgentCreateRequest(BaseModel):
    name: str
    description: str = ""
    system_prompt: str = "You are a helpful AI assistant."
    model: Optional[str] = None

class AgentUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    model: Optional[str] = None

class SkillCreateRequest(BaseModel):
    name: str
    description: str = ""
    workflow_data: Dict = {}
    skill_type: str = "Skill"

class WorkflowRunRequest(BaseModel):
    workflow_data: Dict
    input_text: str = ""


# ── Health ───────────────────────────────────────────────────────

@app.get("/api/v1/health")
async def health():
    from tubecli.config import get_api_port
    return {"status": "ok", "message": "TubeCLI API is running", "port": get_api_port()}


# ── Agents ───────────────────────────────────────────────────────

@app.get("/api/v1/agents")
async def list_agents():
    from tubecli.core.agent import agent_manager
    agents = agent_manager.get_all()
    return {"agents": [a.to_dict() for a in agents], "count": len(agents)}

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


# ── Workflows ────────────────────────────────────────────────────

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


# ── Nodes ────────────────────────────────────────────────────────

@app.get("/api/v1/nodes")
async def list_nodes():
    from tubecli.nodes.registry import list_available_nodes
    return {"nodes": list_available_nodes()}
