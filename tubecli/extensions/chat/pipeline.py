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
import os
import re
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
    session_id: str = "",
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
            AgentBrain.quick_reply, message,
            _with_language_instruction(agent_dict), history,
        )
        return (reply or ""), meta

    # ── 0-token fast-paths (mirror of the Telegram listener) ─────
    # A download request must never depend on the LLM composing the right
    # action: "download <url>" once became a run_api call with an empty body.
    if intent is not None and intent.intent_type == "video_download":
        url = (intent.extracted_data or {}).get("url", "")
        if url:
            try:
                from tubecli.core.telegram_actions import execute_download

                out = await execute_download(url, agent_dict, {})
                if isinstance(out, dict):
                    # Douyin-family links resolve inline and come back as a
                    # file descriptor (the Telegram path sends the file).
                    # Web chat shows the caption + local path instead of
                    # falling through to the LLM after the work is done.
                    parts = [out.get("caption") or ""]
                    if out.get("file_path"):
                        parts.append(f"📁 `{out['file_path']}`")
                    meta["action"] = "download_video"
                    return "\n".join(p for p in parts if p).strip(), meta
                if isinstance(out, str) and out.strip():
                    text, task = _extract_task_marker(out)
                    if task:
                        meta["codex_task"] = task
                    meta["action"] = "download_video"
                    return text, meta
            except Exception as e:
                logger.error(f"[Chat] download fast-path failed: {e}", exc_info=True)
                # fall through to the LLM rather than answering with nothing

    # A video request with no link: ask for it instead of letting the model
    # guess a tool ("give me the transcript" once ran the capabilities skill).
    if intent is not None and intent.intent_type == "video_request_no_url":
        from tubecli.core.bot_i18n import t as _bt

        return _bt("vs.ask_url"), meta

    # "save that file to Downloads". Left to the model this went wrong twice in
    # one conversation: it invented a filename, and then simply ASSERTED it had
    # copied the file without emitting any action at all. The paths this
    # conversation produced are known, so do it here and report what really
    # happened.
    saved = _try_save_artifact(message, history, session_id)
    if saved is not None:
        meta["action"] = "save_file"
        return saved, meta

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

    # Applied LAST, after any specialist swap: routing replaces the whole agent
    # dict, so an instruction added earlier would be thrown away — which is
    # exactly why a Japanese question kept coming back in Vietnamese.
    agent_for_call = _with_language_instruction(agent_for_call)

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
                # A skill can queue codex work too (the video job wrappers do),
                # so the marker has to be consumed here as well — otherwise it
                # is printed verbatim and the user gets no approve button.
                text, task = _extract_task_marker(out or reply)
                if task:
                    meta["codex_task"] = task
                return text, meta
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
        text, task = _extract_task_marker(dispatched)
        if task:
            # The chat turns this into a live card: approve/reject buttons, a
            # progress bar while it runs, and the result when it finishes.
            meta["codex_task"] = task
        return text, meta

    text, task = _extract_task_marker(_clean(reply))
    if task:
        meta["codex_task"] = task
    return text, meta


# ── Helpers ──────────────────────────────────────────────────────────

# "save/copy it to <somewhere>", in every shipped language. Deliberately
# requires BOTH a save verb and a destination cue, so "lưu ý" or a sentence
# merely mentioning a folder does not trigger a copy.
_SAVE_VERBS = re.compile(
    r"(lưu|luu|sao\s*chép|sao\s*chep|copy|save|store|export|"
    r"保存|另存|复制|複製|保存して|コピー|저장|복사|"
    r"сохран|скопир|kaydet|kopyala|guardar|copiar)",
    re.IGNORECASE)

# Folder words → the real directory. A user says "Downloads", not a path.
_DEST_WORDS = [
    (re.compile(r"(download|tải\s*về|tai\s*ve|下载|下載|ダウンロード|다운로드|"
                r"загрузк|indirilen|descargas)", re.IGNORECASE), "~/Downloads"),
    (re.compile(r"(desktop|màn\s*hình|man\s*hinh|桌面|デスクトップ|바탕\s*화면|"
                r"рабочий\s*стол|masaüstü|escritorio)", re.IGNORECASE), "~/Desktop"),
    (re.compile(r"(document|tài\s*liệu|tai\s*lieu|文档|文件夾|ドキュメント|문서|"
                r"документ|belgeler|documentos)", re.IGNORECASE), "~/Documents"),
]

# An absolute path the assistant printed, usually inside backticks.
_PATH_RE = re.compile(r"(?:[A-Za-z]:\\[^`\n\"'|<>]+|/(?:home|Users|mnt|var)/[^`\n\"'|<>]+)")


def _paths_in(text: str, into: List[str]) -> None:
    for raw in _PATH_RE.findall(str(text or "")):
        path = raw.strip().rstrip(".,;:)`")
        if os.path.isfile(path) and path not in into:
            into.append(path)


def _task_artifacts(session_id: str, limit: int = 20) -> List[str]:
    """Files produced by the codex tasks this conversation started.

    A task's output lives on the TASK, not in the transcript: the stored
    assistant message only says "queued as Codex #22", and the result arrives
    later through the card. get_history_for_llm also drops meta, so without
    this the .srt the user just watched appear is invisible to the save path.
    """
    found: List[str] = []
    try:
        from tubecli.extensions.chat.store import conversation_store
        from tubecli.extensions.codex.manager import codex_manager
    except Exception:
        return found
    try:
        messages = conversation_store.get_messages(session_id, limit=limit * 2)
    except Exception:
        return found
    for msg in reversed(messages):
        ref = ((msg or {}).get("meta") or {}).get("codex_task") or {}
        task_id = ref.get("id")
        if not task_id:
            continue
        try:
            task = codex_manager.get_task(task_id) or {}
        except Exception:
            continue
        _paths_in(task.get("result", ""), found)
    return found


def _recent_artifacts(history: List[Dict[str, str]], session_id: str = "",
                      limit: int = 8) -> List[str]:
    """Files this conversation actually produced, newest first.

    Reading the real paths back beats asking the model to remember a filename,
    which is exactly how it came to invent one.
    """
    found: List[str] = []
    for msg in reversed(history[-limit:] if limit else history):
        if (msg or {}).get("role") == "user":
            continue
        _paths_in((msg or {}).get("content", ""), found)
    if session_id:
        for path in _task_artifacts(session_id):
            if path not in found:
                found.append(path)
    return found


def _save_destination(message: str) -> Optional[str]:
    """The folder the user asked for, or None when they named none."""
    explicit = _PATH_RE.search(message)
    if explicit:
        return explicit.group(0).strip().rstrip(".,;:)`")
    for pattern, folder in _DEST_WORDS:
        if pattern.search(message):
            return os.path.expanduser(folder)
    return None


def _try_save_artifact(message: str, history: List[Dict[str, str]],
                       session_id: str = "") -> Optional[str]:
    """Copy the newest produced file where the user asked. None = not this."""
    from tubecli.core.bot_i18n import t as _bt

    if not _SAVE_VERBS.search(message or ""):
        return None
    dest = _save_destination(message or "")
    if not dest:
        return None
    artifacts = _recent_artifacts(history or [], session_id)
    if not artifacts:
        return None                      # nothing produced yet — let the model talk

    src = artifacts[0]
    target = os.path.join(dest, os.path.basename(src)) if (
        os.path.isdir(dest) or not os.path.splitext(dest)[1]) else dest
    try:
        from tubecli.extensions.file_manager.file_service import file_service

        result = file_service.copy(src, target)
    except Exception as e:
        logger.warning(f"[Chat] save-artifact failed: {e}")
        return _bt("chat.save_failed", error=str(e)[:200])
    return _bt("chat.save_ok", src=result.get("from", src), dst=result.get("to", target))


LANGUAGE_NAMES = {
    "en": "English", "vi": "Vietnamese (Tiếng Việt)", "zh": "Simplified Chinese (简体中文)",
    "zh-TW": "Traditional Chinese (繁體中文)", "ja": "Japanese (日本語)",
    "ko": "Korean (한국어)", "ru": "Russian (Русский)", "tr": "Turkish (Türkçe)",
    "es": "Spanish (Español)",
}


def _with_language_instruction(agent_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Answer in the language configured in Settings.

    The interface language is the user's explicit choice, so it wins — an
    earlier version mirrored whatever language the message happened to be
    written in, which meant the setting was quietly ignored. The user can still
    override per message ("reply in Japanese"); only the default is fixed.

    The Telegram path hard-codes vi/zh and sends everyone else English
    (telegram_listener.py:728-738); this covers all nine shipped locales.
    """
    try:
        from tubecli.config import get_language

        ui_lang = (get_language() or "en").strip()
    except Exception:
        ui_lang = "en"

    label = LANGUAGE_NAMES.get(ui_lang, ui_lang)
    instruction = (
        f"IMPORTANT — LANGUAGE: Always write your reply in {label}. That is the "
        "interface language the user chose in Settings, so use it even when their "
        "message is in another language. The only exception is an explicit request "
        "to answer in a different language. Never translate code, commands, file "
        "paths, URLs or model names."
    )
    prompt = agent_dict.get("system_prompt", "You are a helpful assistant.")
    return {**agent_dict, "system_prompt": f"{prompt}\n\n{instruction}"}


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


# Handlers that queue a codex task append this marker so the chat can render
# Approve/Reject buttons. It travels inside the reply string because
# handle_extension_action can only return text.
TASK_MARKER = re.compile(r"<!--\s*codex:([0-9a-fA-F-]+):(\d+):(\w+)\s*-->")


def _extract_task_marker(reply: str):
    """Pull the codex task out of a reply. Returns (clean_reply, task|None)."""
    if not reply:
        return reply, None
    m = TASK_MARKER.search(reply)
    if not m:
        return reply, None
    task = {"id": m.group(1), "seq": int(m.group(2)), "status": m.group(3)}
    return TASK_MARKER.sub("", reply).strip(), task


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
