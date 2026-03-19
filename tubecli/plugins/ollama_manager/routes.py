"""
Ollama Manager Plugin — API routes.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/ollama", tags=["ollama"])


class PullModelRequest(BaseModel):
    model: str


class RemoveModelRequest(BaseModel):
    model: str


class AssignModelRequest(BaseModel):
    agent_id: str
    model: str


@router.get("/status")
async def api_ollama_status():
    """Get Ollama server status."""
    from tubecli.plugins.ollama_manager.plugin import ollama_model_manager
    return ollama_model_manager.server_status()


@router.get("/models")
async def api_list_models():
    """List locally installed models."""
    from tubecli.plugins.ollama_manager.plugin import ollama_model_manager
    result = ollama_model_manager.list_models()
    if "error" in result:
        raise HTTPException(503, result["error"])
    return result


@router.get("/running")
async def api_list_running():
    """List currently loaded models."""
    from tubecli.plugins.ollama_manager.plugin import ollama_model_manager
    result = ollama_model_manager.list_running()
    if "error" in result:
        raise HTTPException(503, result["error"])
    return result


@router.post("/pull")
async def api_pull_model(req: PullModelRequest):
    """Pull/download a model."""
    from tubecli.plugins.ollama_manager.plugin import ollama_model_manager
    result = ollama_model_manager.pull_model(req.model)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.delete("/models")
async def api_remove_model(req: RemoveModelRequest):
    """Remove a model."""
    from tubecli.plugins.ollama_manager.plugin import ollama_model_manager
    result = ollama_model_manager.remove_model(req.model)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.get("/models/{model_name}")
async def api_show_model(model_name: str):
    """Show model details."""
    from tubecli.plugins.ollama_manager.plugin import ollama_model_manager
    result = ollama_model_manager.show_model(model_name)
    if "error" in result:
        raise HTTPException(404, result["error"])
    return result


@router.post("/assign")
async def api_assign_model(req: AssignModelRequest):
    """Assign a model to an agent."""
    from tubecli.core.agent import agent_manager
    agent = agent_manager.get(req.agent_id)
    if not agent:
        raise HTTPException(404, f"Agent '{req.agent_id}' not found")
    agent_manager.update(req.agent_id, model=req.model, browser_ai_model=req.model)
    return {"status": "assigned", "agent_id": req.agent_id, "model": req.model}
