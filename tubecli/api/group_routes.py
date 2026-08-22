"""Group context API — the canvas syncs what each Flow Builder group shares.

The cloud computes one manifest per group (agents, spreadsheet files, folders,
Google Sheets) and PUTs it here after every flow save; the chat and Telegram
pipelines read it back through tubecli.core.group_context.

Owner-only by construction: none of these paths is in the guest allowlist
(_guest_allowed in server.py denies by default), so a sharee can neither read
a manifest — it carries credential ids — nor widen one.
"""
from fastapi import APIRouter, HTTPException, Request

from tubecli.core import group_context

router = APIRouter(tags=["Groups"])


def _check_id(group_id: str) -> None:
    # The id becomes a file name under data/groups/, so it is refused before
    # it reaches the filesystem rather than sanitised into something else.
    if not group_context.valid_group_id(group_id):
        raise HTTPException(400, "invalid group_id (allowed: A-Z a-z 0-9 _ -, max 64)")


@router.get("/api/v1/groups")
async def list_groups(agent_id: str = ""):
    """Every group, or only those the agent belongs to."""
    groups = group_context.groups_for_agent(agent_id) if agent_id else group_context.list_all()
    return {"groups": groups, "count": len(groups)}


@router.get("/api/v1/groups/{group_id}/context")
async def get_group_context(group_id: str):
    _check_id(group_id)
    ctx = group_context.load(group_id)
    if ctx is None:
        raise HTTPException(404, f"Group not found: {group_id}")
    return ctx


@router.put("/api/v1/groups/{group_id}/context")
async def put_group_context(group_id: str, request: Request):
    """Replace the manifest. The path names the group; a group_id in the body
    is ignored so two ids can never disagree about which file is written."""
    _check_id(group_id)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "body must be a JSON object")
    if not isinstance(body, dict):
        raise HTTPException(400, "body must be a JSON object")
    try:
        stored = group_context.save(group_id, body)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "group_id": group_id, "updated_at": stored.get("updated_at", "")}


@router.delete("/api/v1/groups/{group_id}/context")
async def delete_group_context(group_id: str):
    """Idempotent: deleting a group that is already gone is still ok."""
    _check_id(group_id)
    group_context.delete(group_id)
    return {"ok": True}
