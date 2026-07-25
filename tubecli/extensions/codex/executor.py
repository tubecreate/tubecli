"""
Codex executors — turn a task into actual agent work.

Pure functions: no state, no persistence. Progress is reported through the
`report` callback supplied by the worker so the manager stays the only writer.

Every synchronous AgentBrain / Orchestrator call is pushed onto a thread with
asyncio.to_thread — calling them inline would freeze the FastAPI event loop and
the Telegram listener (see core/telegram_listener.py:671,695,740).
"""
import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("Codex")

# Codex tasks run in the background, so they get a far longer budget than the
# 90 s cap the Telegram chat path uses.
SKILL_TIMEOUT_SEC = 900


class TaskCancelled(Exception):
    """Raised when the user cancelled a task between steps."""


async def execute_task(
    task: Dict[str, Any],
    report: Callable[..., None],
    is_cancelled: Callable[[], bool],
) -> str:
    """Run one task and return its final result text.

    `report(name, status, message="", label="")` mirrors the PipelineStep
    vocabulary: pending | running | success | error | skipped.
    """
    assignee_type = (task.get("assignee_type") or "agent").lower()

    if is_cancelled():
        raise TaskCancelled()

    if assignee_type == "team":
        return await _execute_team(task, report, is_cancelled)
    if assignee_type == "skill" or (task.get("skill_ref") or {}).get("skill_id"):
        return await _execute_skill(task, report, is_cancelled)
    return await _execute_agent(task, report, is_cancelled)


# ── Agent ────────────────────────────────────────────────────────────

async def _execute_agent(
    task: Dict[str, Any],
    report: Callable[..., None],
    is_cancelled: Callable[[], bool],
) -> str:
    from tubecli.core.brain import AgentBrain

    goal = task.get("goal", "")

    report("resolve", "running", "Resolving the assigned agent", label="Chọn agent")
    agent = _resolve_agent(task)
    if not agent:
        report("resolve", "error", "No agent available")
        raise RuntimeError("No agent is available to run this task. Create one first.")
    agent_dict = agent.to_dict()
    report("resolve", "success", f"Agent: {agent.name}")

    if is_cancelled():
        raise TaskCancelled()

    report("select_skills", "running", "Selecting relevant skills", label="Chọn skill")
    skills = await asyncio.to_thread(_select_skills, goal, agent_dict)
    report(
        "select_skills", "success",
        f"{len(skills)} skill(s): " + (", ".join(s.get("name", "?") for s in skills) or "none"),
    )

    if is_cancelled():
        raise TaskCancelled()

    report("reason", "running", "Agent is thinking", label="Agent suy nghĩ")
    brain_result = await asyncio.to_thread(
        AgentBrain.chat_targeted, goal, agent_dict, skills, None, "team_delegate"
    )
    reply = (brain_result or {}).get("reply", "") or ""
    action = (brain_result or {}).get("action")
    report("reason", "success", f"Action: {action or 'direct reply'}")

    if is_cancelled():
        raise TaskCancelled()

    if action == "run_skill":
        skill_id = brain_result.get("skill_id") or ""
        skill = _get_skill(skill_id)
        if not skill:
            report("run_skill", "error", f"Skill not found: {skill_id}")
            return reply
        report("run_skill", "running", f"Running skill: {skill.get('name')}", label="Chạy skill")
        try:
            out = await asyncio.wait_for(
                AgentBrain.autonomous_run(
                    brain_result.get("skill_input") or goal, agent_dict, skill
                ),
                timeout=SKILL_TIMEOUT_SEC,
            )
        except asyncio.TimeoutError:
            report("run_skill", "error", f"Timed out after {SKILL_TIMEOUT_SEC}s")
            raise RuntimeError(
                f"Skill '{skill.get('name')}' timed out after {SKILL_TIMEOUT_SEC}s"
            )
        report("run_skill", "success", "Skill finished")
        return out or reply

    if action and action not in ("run_skill", None):
        # download_video / create_team / run_api / schedule_event / extension
        # actions all flow through the shared dispatcher.
        report("action", "running", f"Dispatching action: {action}", label="Thực thi action")
        dispatched = await _dispatch_action(reply, agent_dict, task)
        report("action", "success", f"Action {action} handled")
        return dispatched or reply

    return reply


def _resolve_agent(task: Dict[str, Any]):
    """Explicit assignee → named assignee → intent specialist → first agent."""
    from tubecli.core.agent import agent_manager

    assignee_id = task.get("assignee_id") or ""
    if assignee_id:
        agent = agent_manager.get(assignee_id)
        if agent:
            return agent
    assignee_name = task.get("assignee_name") or ""
    if assignee_name:
        agent = agent_manager.find_by_name(assignee_name)
        if agent:
            return agent

    try:
        from tubecli.core.intent_router import intent_router
        from tubecli.core.specialists import get_specialist_for_intent

        intent = intent_router.classify(task.get("goal", ""))
        specialist = get_specialist_for_intent(intent.intent_type)
        if specialist:
            return specialist
    except Exception as e:
        logger.debug(f"[Codex] Specialist routing skipped: {e}")

    agents = agent_manager.get_all()
    return agents[0] if agents else None


def _select_skills(goal: str, agent_dict: Dict[str, Any]) -> List[Dict[str, Any]]:
    try:
        from tubecli.core.skill import skill_manager
        from tubecli.core.skill_selector import skill_selector

        all_skills = [s.to_dict() for s in skill_manager.get_all()]
        return skill_selector.select_for_team(
            goal, agent_dict.get("allowed_skills") or [], all_skills, limit=3
        )
    except Exception as e:
        logger.warning(f"[Codex] Skill selection failed: {e}")
        return []


def _get_skill(skill_id: str) -> Optional[Dict[str, Any]]:
    try:
        from tubecli.core.skill import skill_manager

        skill = skill_manager.get(skill_id) or skill_manager.find_by_name(skill_id)
        return skill.to_dict() if skill else None
    except Exception:
        return None


async def _dispatch_action(reply: str, agent_dict: Dict, task: Dict) -> str:
    """Hand a non-skill brain action to the shared extension-action dispatcher."""
    try:
        from tubecli.core.telegram_actions import handle_extension_action

        origin = task.get("origin") or {}
        context = {
            "token": origin.get("token", ""),
            "chat_id": origin.get("chat_id", ""),
        }
        result = await handle_extension_action(reply, agent_dict, context)
        if isinstance(result, str):
            return result
        return str(result) if result is not None else ""
    except Exception as e:
        logger.warning(f"[Codex] Action dispatch failed: {e}")
        return ""


# ── Team ─────────────────────────────────────────────────────────────

async def _execute_team(
    task: Dict[str, Any],
    report: Callable[..., None],
    is_cancelled: Callable[[], bool],
) -> str:
    from tubecli.extensions.multi_agents.extension import orchestrator

    team_id = task.get("assignee_id") or ""
    team = orchestrator.get_team(team_id) if team_id else None
    if not team and task.get("assignee_name"):
        team = orchestrator.find_team_by_name(task["assignee_name"])
    if not team:
        raise RuntimeError(f"Team not found: {task.get('assignee_name') or team_id}")

    report("delegate", "running", f"Delegating to team: {team.name}", label="Giao cho team")

    goal = task.get("goal", "")

    # Orchestrator.delegate is async in signature only — it blocks on the
    # synchronous AgentBrain.chat. Run the whole thing on its own thread/loop
    # so the server's event loop stays responsive.
    def _run() -> Dict[str, Any]:
        return asyncio.run(orchestrator.delegate(team.id, goal))

    result = await asyncio.to_thread(_run)

    if (result or {}).get("status") == "error":
        report("delegate", "error", result.get("message", "Delegation failed"))
        raise RuntimeError(result.get("message", "Team delegation failed"))

    results = (result or {}).get("results", []) or []
    report("delegate", "success", f"{len(results)} agent reply/replies")

    _save_team_briefing(team.id, task, results)

    lines = []
    for r in results:
        name = r.get("agent_name") or r.get("role") or "Agent"
        lines.append(f"### {name}\n{r.get('reply', '')}")
    return "\n\n".join(lines) if lines else "Team returned no output."


def _save_team_briefing(team_id: str, task: Dict[str, Any], results: List[Dict]):
    try:
        from tubecli.core.memory import TeamMemory

        TeamMemory.save_briefing(
            team_id,
            f"Codex task #{task.get('seq')}: {task.get('title')}",
            {
                "codex_task_id": task.get("id"),
                "goal": task.get("goal"),
                "agent_count": len(results),
            },
        )
    except Exception as e:
        logger.debug(f"[Codex] Could not save team briefing: {e}")


# ── Skill ────────────────────────────────────────────────────────────

async def _execute_skill(
    task: Dict[str, Any],
    report: Callable[..., None],
    is_cancelled: Callable[[], bool],
) -> str:
    from tubecli.core.brain import AgentBrain

    skill_ref = task.get("skill_ref") or {}
    skill = _get_skill(skill_ref.get("skill_id") or skill_ref.get("skill_name") or "")
    if not skill:
        raise RuntimeError(
            f"Skill not found: {skill_ref.get('skill_name') or skill_ref.get('skill_id')}"
        )

    agent = _resolve_agent(task)
    if not agent:
        raise RuntimeError("No agent is available to run this skill.")

    report("run_skill", "running", f"Running skill: {skill.get('name')}", label="Chạy skill")
    try:
        out = await asyncio.wait_for(
            AgentBrain.autonomous_run(task.get("goal", ""), agent.to_dict(), skill),
            timeout=SKILL_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError:
        report("run_skill", "error", f"Timed out after {SKILL_TIMEOUT_SEC}s")
        raise RuntimeError(f"Skill '{skill.get('name')}' timed out after {SKILL_TIMEOUT_SEC}s")
    report("run_skill", "success", "Skill finished")
    return out or ""
