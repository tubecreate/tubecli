"""
Web chat pipeline — Telegram-grade routing for the browser.

`POST /api/v1/agents/{id}/chat` (api/server.py:1723) is a much thinner path than
the Telegram one: it pushes EVERY skill into the prompt, handles only
`run_skill`/`create_skill`, and never calls `handle_extension_action` — so an
extension verb (codex, tracker, calendar…) comes back to the browser as a raw
```json blob instead of doing anything.

This module runs the same sequence TelegramListener._process_message uses
(core/telegram_listener.py:206), so the web chat behaves like the bot:

    intent_router.classify   →  0-token classification
    quick_reply              →  cheap path for greetings/small talk
    skill_selector.select    →  narrow to ~3 skills before the LLM
    AgentBrain.chat_targeted →  one LLM call
    autonomous_run           →  when the model picks a skill
    handle_extension_action  →  when the model emits an extension verb

Every synchronous AgentBrain call is pushed off the event loop with
asyncio.to_thread (the pattern at telegram_listener.py:671/695/740).
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("Chat")

SKILL_TIMEOUT_SEC = 600
SKILL_LIMIT = 3


async def run_turn(
    message: str,
    agent_dict: Dict[str, Any],
    history: List[Dict[str, str]],
    auto_route: bool = True,
    model_override: str = "",
    provider_override: str = "",
) -> Tuple[str, Dict[str, Any]]:
    """Process one user turn. Returns (reply_text, meta).

    `model_override`/`provider_override` (the chat header's model picker)
    survive specialist routing: whichever agent ends up answering, the picked
    model wins. The provider travels with the model because a model id alone is
    ambiguous across OpenAI-compatible proxies.
    """
    from tubecli.core.brain import AgentBrain

    def _apply_override(a: Dict[str, Any]) -> Dict[str, Any]:
        if not model_override:
            return a
        a = {**a, "model": model_override}
        # An empty provider must CLEAR any inherited one, or the agent's own
        # provider would be applied to the newly picked model.
        a["provider"] = provider_override
        return a

    agent_dict = _apply_override(agent_dict)

    meta: Dict[str, Any] = {
        "agent_id": agent_dict.get("id", ""),
        "agent_name": agent_dict.get("name", ""),
        "model": agent_dict.get("model", ""),
        "intent": "",
        "skill_used": "",
        "action": "",
        "routed_to": "",
    }

    all_skills = _all_skills()
    allowed = agent_dict.get("allowed_skills") or []
    available = [s for s in all_skills if s.get("id") in allowed] if allowed else all_skills

    # ── Tier 1: zero-token classification ────────────────────────
    intent = None
    try:
        from tubecli.core.intent_router import intent_router

        intent = intent_router.classify(message, agent_dict, available)
        meta["intent"] = intent.intent_type
    except Exception as e:
        logger.warning(f"[Chat] Intent classification failed: {e}")

    # Cheap path for greetings / small talk — ~500 tokens instead of the full prompt.
    if intent is not None and intent.intent_type == "greeting":
        reply = await asyncio.to_thread(
            AgentBrain.quick_reply, message, agent_dict, history
        )
        return (reply or ""), meta

    # Optionally hand the turn to the specialist that owns this intent.
    if auto_route and intent is not None:
        specialist = _route_to_specialist(intent, agent_dict)
        if specialist is not None:
            agent_dict = _apply_override(specialist)
            meta["routed_to"] = specialist.get("name", "")
            meta["agent_id"] = specialist.get("id", "")
            meta["agent_name"] = specialist.get("name", "")
            meta["model"] = agent_dict.get("model", "")
            allowed = specialist.get("allowed_skills") or []
            available = (
                [s for s in all_skills if s.get("id") in allowed] if allowed else all_skills
            )

    # ── Narrow the skill set before spending prompt budget ───────
    skills = available
    try:
        from tubecli.core.skill_selector import skill_selector

        matched = list(getattr(intent, "matched_skills", None) or []) if intent else []
        skills = skill_selector.select(
            message,
            (intent.intent_type if intent else "complex_action"),
            available,
            matched_skill_ids=matched,
            limit=SKILL_LIMIT,
        ) or available[:SKILL_LIMIT]
    except Exception as e:
        logger.warning(f"[Chat] Skill selection failed: {e}")
        skills = available[:SKILL_LIMIT]

    # ── Let the model see what the extensions can do ─────────────
    agent_for_call = dict(agent_dict)
    if intent is None or intent.intent_type == "complex_action":
        caps = _extension_capabilities()
        if caps:
            agent_for_call["system_prompt"] = (
                agent_for_call.get("system_prompt", "") + "\n\n" + caps
            )

    # ── Tier 2: one LLM call ─────────────────────────────────────
    result = await asyncio.to_thread(
        AgentBrain.chat_targeted, message, agent_for_call, skills, history, ""
    )
    result = result or {}
    reply = result.get("reply", "") or ""
    action = result.get("action")
    meta["action"] = action or ""

    # ── Act on what the model decided ────────────────────────────
    if action == "run_skill":
        skill = _get_skill(result.get("skill_id") or "")
        if skill:
            meta["skill_used"] = skill.get("name", "")
            try:
                out = await asyncio.wait_for(
                    AgentBrain.autonomous_run(
                        result.get("skill_input") or message, agent_for_call, skill
                    ),
                    timeout=SKILL_TIMEOUT_SEC,
                )
                return (out or reply), meta
            except asyncio.TimeoutError:
                return (
                    f"⏱ Skill '{skill.get('name')}' chạy quá {SKILL_TIMEOUT_SEC}s và đã bị dừng.",
                    meta,
                )
            except Exception as e:
                logger.error(f"[Chat] Skill run failed: {e}", exc_info=True)
                return f"❌ Lỗi khi chạy skill '{skill.get('name')}': {e}", meta
        return reply, meta

    # Any other verb (codex_create_task, add_tracker, run_api, …) goes to the
    # shared dispatcher — this is the piece the stock web chat is missing.
    dispatched = await _dispatch_extension_action(reply, agent_for_call)
    if dispatched is not None and dispatched != reply:
        return dispatched, meta

    return _clean(reply), meta


# ── Helpers ──────────────────────────────────────────────────────────

def _all_skills() -> List[Dict[str, Any]]:
    try:
        from tubecli.core.skill import skill_manager

        return [s.to_dict() for s in skill_manager.get_all()]
    except Exception as e:
        logger.warning(f"[Chat] Could not load skills: {e}")
        return []


def _get_skill(skill_id: str) -> Optional[Dict[str, Any]]:
    if not skill_id:
        return None
    try:
        from tubecli.core.skill import skill_manager

        skill = skill_manager.get(skill_id) or skill_manager.find_by_name(skill_id)
        return skill.to_dict() if skill else None
    except Exception:
        return None


def _route_to_specialist(intent, current_agent: Dict) -> Optional[Dict[str, Any]]:
    """Send domain intents to their specialist, like the bot does."""
    try:
        from tubecli.core.agent import agent_manager

        target_id = getattr(intent, "target_agent_id", "") or ""
        if target_id and target_id != current_agent.get("id"):
            agent = agent_manager.get(target_id)
            if agent:
                return agent.to_dict()

        from tubecli.core.specialists import get_specialist_for_intent

        specialist = get_specialist_for_intent(intent.intent_type)
        if specialist and specialist.id != current_agent.get("id"):
            return specialist.to_dict()
    except Exception as e:
        logger.debug(f"[Chat] Specialist routing skipped: {e}")
    return None


def _extension_capabilities() -> str:
    """The same SKILL.md block the bot injects (telegram_listener.py:1847)."""
    try:
        from tubecli.core.telegram_listener import telegram_listener

        return telegram_listener._build_extension_capabilities() or ""
    except Exception as e:
        logger.debug(f"[Chat] Could not build extension capabilities: {e}")
        return ""


async def _dispatch_extension_action(reply: str, agent_dict: Dict) -> Optional[str]:
    try:
        from tubecli.core.telegram_actions import handle_extension_action

        # No token/chat_id: this turn came from the browser, so notifications
        # fall back to the globally configured Telegram target.
        result = await handle_extension_action(reply, agent_dict, {"source": "web_chat"})
        if isinstance(result, str):
            return result
        if isinstance(result, dict):
            return result.get("message") or result.get("reply") or str(result)
        return None if result is None else str(result)
    except Exception as e:
        logger.warning(f"[Chat] Extension action dispatch failed: {e}")
        return None


def _clean(reply: str) -> str:
    """Strip JSON wrappers the model sometimes emits around plain answers."""
    try:
        from tubecli.core.telegram_actions import clean_reply_text

        return clean_reply_text(reply) or reply
    except Exception:
        return reply


def resolve_agent(agent_id: str = "") -> Optional[Dict[str, Any]]:
    """Explicit agent, else the orchestrator, else the first agent."""
    from tubecli.core.agent import agent_manager

    if agent_id:
        agent = agent_manager.get(agent_id)
        if agent:
            return agent.to_dict()

    agents = agent_manager.get_all()
    if not agents:
        return None
    for a in agents:
        if (a.role or "") == "orchestrator":
            return a.to_dict()
    for a in agents:
        name = (a.name or "").lower()
        if "orchestr" in name or "tổng" in name:
            return a.to_dict()
    return agents[0].to_dict()
