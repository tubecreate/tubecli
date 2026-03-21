"""
Multi-Agents Extension — API routes for team management.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict

router = APIRouter(prefix="/api/v1/multi-agents", tags=["multi-agents"])


class CreateTeamRequest(BaseModel):
    name: str
    agent_ids: List[str] = []
    lead_agent_id: str = ""
    strategy: str = "sequential"
    description: str = ""
    template: str = "custom"
    nodes: List[dict] = []


class CreateFromTemplateRequest(BaseModel):
    template_id: str
    name: str = ""
    agent_assignments: Dict[str, str] = {}  # role_id -> agent_id


class UpdateTeamRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    strategy: Optional[str] = None
    nodes: Optional[List[dict]] = None


class DelegateRequest(BaseModel):
    task: str


# ── Templates ────────────────────────────────────────────────

@router.get("/templates")
async def api_list_templates():
    """List all available team templates."""
    from tubecli.extensions.multi_agents.templates import get_all_templates
    return {"templates": get_all_templates()}


@router.get("/templates/{template_id}")
async def api_get_template(template_id: str):
    """Get a specific template with full node definitions."""
    from tubecli.extensions.multi_agents.templates import get_template
    tmpl = get_template(template_id)
    if not tmpl:
        raise HTTPException(404, f"Template '{template_id}' not found")
    return {"id": template_id, **tmpl}


# ── Team CRUD ────────────────────────────────────────────────

@router.get("/teams")
async def api_list_teams():
    """List all agent teams."""
    from tubecli.extensions.multi_agents.extension import orchestrator
    teams = orchestrator.get_all_teams()
    return {"teams": [t.to_dict() for t in teams], "count": len(teams)}


@router.post("/teams")
async def api_create_team(req: CreateTeamRequest):
    """Create a new agent team."""
    from tubecli.extensions.multi_agents.extension import orchestrator
    team = orchestrator.create_team(
        name=req.name, agent_ids=req.agent_ids, lead_agent_id=req.lead_agent_id,
        strategy=req.strategy, description=req.description,
        template=req.template, nodes=req.nodes,
    )
    return {"status": "created", "team": team.to_dict()}


@router.post("/teams/from-template")
async def api_create_from_template(req: CreateFromTemplateRequest):
    """Create a team from a preset template with agent assignments."""
    from tubecli.extensions.multi_agents.extension import orchestrator
    try:
        team = orchestrator.create_from_template(
            template_id=req.template_id,
            name=req.name,
            agent_assignments=req.agent_assignments,
        )
        return {"status": "created", "team": team.to_dict()}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/teams/{team_id}")
async def api_get_team(team_id: str):
    """Get team details."""
    from tubecli.extensions.multi_agents.extension import orchestrator
    team = orchestrator.get_team(team_id)
    if not team:
        raise HTTPException(404, f"Team '{team_id}' not found")
    return team.to_dict()


@router.put("/teams/{team_id}")
async def api_update_team(team_id: str, req: UpdateTeamRequest):
    """Update a team's configuration."""
    from tubecli.extensions.multi_agents.extension import orchestrator
    updates = {k: v for k, v in req.dict().items() if v is not None}
    team = orchestrator.update_team(team_id, **updates)
    if not team:
        raise HTTPException(404, f"Team '{team_id}' not found")
    return {"status": "updated", "team": team.to_dict()}


@router.delete("/teams/{team_id}")
async def api_delete_team(team_id: str):
    """Delete a team."""
    from tubecli.extensions.multi_agents.extension import orchestrator
    if not orchestrator.delete_team(team_id):
        raise HTTPException(404, f"Team '{team_id}' not found")
    return {"status": "deleted", "team_id": team_id}


# ── Org Chart ────────────────────────────────────────────────

@router.get("/teams/{team_id}/org-chart")
async def api_org_chart(team_id: str):
    """Get the hierarchical org chart for a team."""
    from tubecli.extensions.multi_agents.extension import orchestrator
    team = orchestrator.get_team(team_id)
    if not team:
        raise HTTPException(404, f"Team '{team_id}' not found")
    return {"team_id": team_id, "team_name": team.name, "org_chart": team.get_org_chart()}


# ── Delegation ───────────────────────────────────────────────

@router.post("/teams/{team_id}/delegate")
async def api_delegate_task(team_id: str, req: DelegateRequest):
    """Delegate a task to a team."""
    from tubecli.extensions.multi_agents.extension import orchestrator
    result = await orchestrator.delegate(team_id, req.task)
    if result.get("status") == "error":
        raise HTTPException(400, result["message"])
    return result


# ── Task Log ─────────────────────────────────────────────────

@router.get("/log")
async def api_task_log():
    """Get delegation task log."""
    from tubecli.extensions.multi_agents.extension import orchestrator
    return {"log": orchestrator.get_task_log()}
