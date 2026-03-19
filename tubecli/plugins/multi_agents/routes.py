"""
Multi-Agents Plugin — API routes.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional

router = APIRouter(prefix="/api/v1/multi-agents", tags=["multi-agents"])


class CreateTeamRequest(BaseModel):
    name: str
    agent_ids: List[str]
    lead_agent_id: str = ""
    strategy: str = "sequential"
    description: str = ""


class DelegateRequest(BaseModel):
    task: str


@router.get("/teams")
async def api_list_teams():
    """List all agent teams."""
    from tubecli.plugins.multi_agents.plugin import orchestrator
    teams = orchestrator.get_all_teams()
    return {"teams": [t.to_dict() for t in teams], "count": len(teams)}


@router.post("/teams")
async def api_create_team(req: CreateTeamRequest):
    """Create a new agent team."""
    from tubecli.plugins.multi_agents.plugin import orchestrator
    if not req.agent_ids:
        raise HTTPException(400, "At least one agent ID is required.")
    team = orchestrator.create_team(
        name=req.name, agent_ids=req.agent_ids, lead_agent_id=req.lead_agent_id,
        strategy=req.strategy, description=req.description,
    )
    return {"status": "created", "team": team.to_dict()}


@router.get("/teams/{team_id}")
async def api_get_team(team_id: str):
    """Get team details."""
    from tubecli.plugins.multi_agents.plugin import orchestrator
    team = orchestrator.get_team(team_id)
    if not team:
        raise HTTPException(404, f"Team '{team_id}' not found")
    return team.to_dict()


@router.delete("/teams/{team_id}")
async def api_delete_team(team_id: str):
    """Delete a team."""
    from tubecli.plugins.multi_agents.plugin import orchestrator
    if not orchestrator.delete_team(team_id):
        raise HTTPException(404, f"Team '{team_id}' not found")
    return {"status": "deleted", "team_id": team_id}


@router.post("/teams/{team_id}/delegate")
async def api_delegate_task(team_id: str, req: DelegateRequest):
    """Delegate a task to a team."""
    from tubecli.plugins.multi_agents.plugin import orchestrator
    result = await orchestrator.delegate(team_id, req.task)
    if result.get("status") == "error":
        raise HTTPException(400, result["message"])
    return result


@router.get("/log")
async def api_task_log():
    """Get delegation task log."""
    from tubecli.plugins.multi_agents.plugin import orchestrator
    return {"log": orchestrator.get_task_log()}
