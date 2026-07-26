"""
Chat — FastAPI routes (session API + the /chat page).
"""
import logging
import mimetypes
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from tubecli.extensions.chat.store import conversation_store

logger = logging.getLogger("Chat")

_EXT_DIR = os.path.dirname(os.path.abspath(__file__))
_STATIC_DIR = os.path.join(_EXT_DIR, "static")

_MEDIA_TYPES = {
    ".css": "text/css", ".js": "application/javascript", ".html": "text/html",
    ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png",
    ".webp": "image/webp", ".ico": "image/x-icon",
}
_NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate"}


# ── UI router ────────────────────────────────────────────────────────

ui_router = APIRouter(tags=["chat-ui"])


@ui_router.get("/chat")
async def serve_chat_ui():
    return FileResponse(
        os.path.join(_STATIC_DIR, "chat.html"), media_type="text/html", headers=_NO_CACHE
    )


@ui_router.get("/chat/{filename:path}")
async def serve_chat_static(filename: str):
    filepath = os.path.normpath(os.path.join(_STATIC_DIR, filename))
    if not filepath.startswith(_STATIC_DIR) or not os.path.isfile(filepath):
        raise HTTPException(404, "File not found")
    ext = os.path.splitext(filename)[1].lower()
    media = _MEDIA_TYPES.get(ext) or mimetypes.guess_type(filepath)[0] or "application/octet-stream"
    return FileResponse(filepath, media_type=media, headers=_NO_CACHE)


# ── API router ───────────────────────────────────────────────────────

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


class CreateSessionRequest(BaseModel):
    title: str = ""
    agent_id: str = ""


class UpdateSessionRequest(BaseModel):
    title: Optional[str] = None
    agent_id: Optional[str] = None
    pinned: Optional[bool] = None
    model: Optional[str] = None


class SendMessageRequest(BaseModel):
    message: str
    agent_id: str = ""
    model: str = ""
    auto_route: bool = True


def _require(session_id: str) -> Dict[str, Any]:
    s = conversation_store.get_session(session_id)
    if not s:
        raise HTTPException(404, f"Session not found: {session_id}")
    return s


@router.get("/sessions")
async def list_sessions(limit: int = 100):
    sessions = conversation_store.list_sessions(limit=limit)
    return {"sessions": sessions, "count": len(sessions)}


@router.post("/sessions")
async def create_session(req: CreateSessionRequest):
    from tubecli.extensions.chat.pipeline import resolve_agent

    agent = resolve_agent(req.agent_id)
    session = conversation_store.create_session(
        title=req.title,
        agent_id=(agent or {}).get("id", ""),
        agent_name=(agent or {}).get("name", ""),
    )
    return {"status": "created", "session": session}


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, limit: int = 200):
    session = _require(session_id)
    return {"session": session, "messages": conversation_store.get_messages(session_id, limit)}


@router.put("/sessions/{session_id}")
async def update_session(session_id: str, req: UpdateSessionRequest):
    _require(session_id)
    updates = req.dict(exclude_none=True)
    if "agent_id" in updates:
        from tubecli.extensions.chat.pipeline import resolve_agent

        agent = resolve_agent(updates["agent_id"])
        updates["agent_name"] = (agent or {}).get("name", "")
    return {"status": "updated", "session": conversation_store.update_session(session_id, **updates)}


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    _require(session_id)
    return {"status": "deleted", "ok": conversation_store.delete_session(session_id)}


@router.post("/sessions/{session_id}/clear")
async def clear_session(session_id: str):
    _require(session_id)
    return {"status": "cleared", "ok": conversation_store.clear_messages(session_id)}


@router.get("/sessions/{session_id}/messages")
async def get_messages(session_id: str, limit: int = 200):
    _require(session_id)
    return {"messages": conversation_store.get_messages(session_id, limit)}


@router.post("/sessions/{session_id}/messages")
async def send_message(session_id: str, req: SendMessageRequest):
    """Run one full turn through the Telegram-grade pipeline."""
    from tubecli.extensions.chat.pipeline import resolve_agent, run_turn

    session = _require(session_id)
    text = (req.message or "").strip()
    if not text:
        raise HTTPException(400, "message is required")

    agent = resolve_agent(req.agent_id or session.get("agent_id", ""))
    if not agent:
        raise HTTPException(400, "Chưa có agent nào. Hãy tạo một agent trước.")

    # Per-conversation model override (the chat header's model picker).
    model_override = (req.model or session.get("model") or "").strip()

    user_msg = conversation_store.append_message(session_id, "user", text)
    history = conversation_store.get_history_for_llm(session_id, turns=10)
    # Drop the turn we just stored — it is passed as the prompt, not as history.
    if history and history[-1].get("content") == text:
        history = history[:-1]

    try:
        reply, meta = await run_turn(
            text, agent, history,
            auto_route=req.auto_route, model_override=model_override,
        )
    except Exception as e:
        logger.error(f"[Chat] Turn failed: {e}", exc_info=True)
        reply, meta = f"❌ Lỗi: {e}", {"error": str(e)}

    # Safety net: raw Ollama connection errors can still leak through paths
    # that bypass _call_llm's fallback (workflow nodes, browser scripts).
    # Never show a stacktrace to the user — show what to do instead.
    if "[Ollama Error]" in (reply or ""):
        from tubecli.i18n import t

        friendly = t("brain.no_model_available")
        if friendly != "brain.no_model_available":  # key resolved
            reply = friendly
        meta["error_type"] = "no_model"

    assistant_msg = conversation_store.append_message(session_id, "assistant", reply, meta=meta)
    conversation_store.prune(session_id)

    if (agent or {}).get("id") and session.get("agent_id") != agent["id"]:
        conversation_store.update_session(
            session_id, agent_id=agent["id"], agent_name=agent.get("name", "")
        )

    return {
        "status": "ok",
        "user_message": user_msg,
        "message": assistant_msg,
        "session": conversation_store.get_session(session_id),
    }


@router.get("/models")
async def list_models():
    """Providers the user has actually integrated, with their models.

    Feeds the chat header's model picker. Only three sources count as
    "integrated": a cloud provider with an ACTIVE key in cloud_api, a running
    local Ollama, and a running 9router proxy. Everything else is omitted so
    the picker never offers a model that cannot answer.
    """
    providers = []

    # Cloud providers with an active key.
    try:
        from tubecli.extensions.cloud_api.extension import PROVIDERS, key_manager

        for pid, info in PROVIDERS.items():
            if pid == "9router":
                continue  # handled below via a live probe — key alone is not enough
            try:
                if key_manager.get_active_key(pid):
                    models = list(info.get("models") or [])
                    if models:
                        providers.append({
                            "id": pid,
                            "label": info.get("name") or pid.title(),
                            "source": "cloud",
                            "models": models,
                        })
            except Exception:
                continue
    except Exception as e:
        logger.warning(f"[Chat] Could not read cloud providers: {e}")

    # Local Ollama — probe quickly; list installed models only.
    try:
        import requests

        resp = requests.get("http://localhost:11434/api/tags", timeout=1.5)
        if resp.status_code == 200:
            names = [
                m.get("name") for m in resp.json().get("models", []) if m.get("name")
            ]
            if names:
                providers.append({
                    "id": "ollama",
                    "label": "Ollama (local)",
                    "source": "local",
                    "models": sorted(names),
                })
    except Exception:
        pass  # not installed/running — simply absent from the picker

    # 9router proxy — probe quickly.
    try:
        import requests

        resp = requests.get("http://localhost:20128/v1/models", timeout=1.5)
        if resp.status_code == 200:
            names = [
                m.get("id") for m in resp.json().get("data", []) if m.get("id")
            ]
            if names:
                providers.append({
                    "id": "9router",
                    "label": "9Router (local proxy)",
                    "source": "local",
                    "models": sorted(names)[:40],
                })
    except Exception:
        pass

    return {"providers": providers, "count": len(providers)}


@router.get("/agents")
async def list_agents():
    """Agents available in the picker, orchestrator first."""
    try:
        from tubecli.core.agent import agent_manager

        agents = [
            {
                "id": a.id,
                "name": a.name,
                "role": a.role or "general",
                "model": a.model or "",
                "description": (a.description or "")[:160],
                "specialties": a.specialties or [],
            }
            for a in agent_manager.get_all()
        ]
    except Exception as e:
        logger.warning(f"[Chat] Could not list agents: {e}")
        agents = []
    agents.sort(key=lambda a: (a["role"] != "orchestrator", a["name"].lower()))
    return {"agents": agents, "count": len(agents)}
