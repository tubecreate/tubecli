"""Group context API — the canvas syncs what each Flow Builder group shares.

The cloud computes one manifest per group (agents, files, folders, Google
Sheets, playbook notes — whatever kinds are registered) and PUTs it here after
every flow save; the chat and Telegram pipelines read it back through
tubecli.core.group_context. A PUT replaces only the canvas half of the stored
file: entries this machine added on its own (POST …/server/{kind}) survive it.

Owner-only by construction: none of these paths is in the guest allowlist
(_guest_allowed in server.py denies by default), so a sharee can neither read
a manifest — it carries credential ids — nor widen one. The activity log below
is on the same footing and for a sharper reason: one agent works in several of
the owner's groups, so a log the sharee could poll would narrate work in groups
that were never shared with them.
"""
import asyncio
import os

from fastapi import APIRouter, HTTPException, Request

from tubecli.core import group_context, group_log

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


@router.post("/api/v1/groups/{group_id}/server/{kind}")
async def post_server_entry(group_id: str, kind: str, request: Request):
    """Add one entry to the group's server half — what this machine adds on
    its own (an agent's schedule, a skill it wrote) and the next canvas sync
    must not erase. The body is the entry; the kind decides its shape and
    which field makes two entries the same (path, sheet_id, alias)."""
    _check_id(group_id)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "body must be a JSON object")
    if not isinstance(body, dict):
        raise HTTPException(400, "body must be a JSON object")
    try:
        entry = group_context.add_server_entry(group_id, kind, body)
    except LookupError:
        raise HTTPException(404, f"Group not found: {group_id}")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "group_id": group_id, "kind": kind, "entry": entry}


def _selector_matches(key: str, have, want: str) -> bool:
    have = str(have or "").strip()
    if key == "path":
        # Canonical compare, like resolve_xlsx: ~, .., symlinks and Windows
        # case must not make the owner's path miss its own entry.
        c1, c2 = group_context.canon_path(have), group_context.canon_path(want)
        return bool(c1) and os.path.normcase(c1) == os.path.normcase(c2)
    if key == "alias":
        return have.casefold() == want.casefold()
    return have == want            # sheet_id is case-sensitive at Google


@router.delete("/api/v1/groups/{group_id}/server/{kind}")
async def delete_server_entry(group_id: str, kind: str, alias: str = "", path: str = "", sheet_id: str = ""):
    """Remove the server entries matching EVERY selector given. Idempotent:
    removing what is not there is still ok, with removed=0."""
    _check_id(group_id)
    wanted = {k: v.strip() for k, v in (("alias", alias), ("path", path), ("sheet_id", sheet_id))
              if v and v.strip()}
    if not wanted:
        raise HTTPException(400, "give at least one of alias=, path=, sheet_id=")
    try:
        removed = group_context.remove_server_entry(
            group_id, kind,
            lambda e: all(_selector_matches(k, e.get(k), v) for k, v in wanted.items()))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "group_id": group_id, "kind": kind, "removed": removed}


def _int(value: str, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


@router.get("/api/v1/groups/{group_id}/log")
async def get_group_log(group_id: str, since: str = "0", limit: str = "200"):
    """What the agents in this group have been doing, for the canvas panel.

    `since` is the last seq the panel already holds, so a poll every couple of
    seconds costs one line, not the whole file. A group with no log yet is not
    an error — it is a group nobody has worked in — so it answers with an empty
    list and next_seq=0 rather than 404.

    Both numbers arrive as strings on purpose. Declared as int, FastAPI answers
    422 for `?since=` or `?since=undefined` — which is what a polling panel
    sends on its very first tick, and a log that 422s until you reload is worse
    than one that starts from the beginning. group_log.read() clamps them.
    """
    _check_id(group_id)
    # read() parses the whole file, and every open panel asks every two seconds.
    # On a thread, so a room full of panels cannot stall the loop that serves
    # the canvas itself.
    return await asyncio.to_thread(group_log.read, group_id,
                                   _int(since, 0), _int(limit, 200))


@router.delete("/api/v1/groups/{group_id}/log")
async def delete_group_log(group_id: str):
    """Idempotent, like the context DELETE: clearing an empty log is still ok."""
    _check_id(group_id)
    return {"ok": True, "cleared": await asyncio.to_thread(group_log.clear, group_id)}
