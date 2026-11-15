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
import re
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("Codex")

# Codex tasks run in the background, so they get a far longer budget than the
# 90 s cap the Telegram chat path uses.
SKILL_TIMEOUT_SEC = 900


class TaskCancelled(Exception):
    """Raised when the user cancelled a task between steps."""


class AgentRefused(RuntimeError):
    """The agent answered without doing the work (refused / said it cannot). Worker ⇒ task FAILED with this text."""


async def execute_task(
    task: Dict[str, Any],
    report: Callable[..., None],
    is_cancelled: Callable[[], bool],
) -> str:
    """Run one task and return its final result text.

    `report(name, status, message="", label="")` mirrors the PipelineStep
    vocabulary: pending | running | success | error | skipped.

    MỘT task = MỘT lượt, có trần hành động như chat web và Telegram. Trần từng
    chỉ nằm trong extensions/chat/pipeline.run_turn — hàm mà đường này không
    bao giờ gọi — nên một task tự sinh task/skill lồng nhau chạy không giới hạn.
    """
    from tubecli.core.turn_budget import depth_refusal, turn_budget

    with turn_budget() as budget:
        refusal = depth_refusal(budget)
        if refusal:
            report("depth", "error", refusal, label="Chuỗi quá sâu")
            return refusal
        return await _execute_task_turn(task, report, is_cancelled)


async def _execute_task_turn(
    task: Dict[str, Any],
    report: Callable[..., None],
    is_cancelled: Callable[[], bool],
) -> str:
    assignee_type = (task.get("assignee_type") or "agent").lower()

    if is_cancelled():
        raise TaskCancelled()

    # Tasks queued by another extension carry a machine-readable kind in their
    # event log, so the worker runs the real pipeline instead of handing the
    # goal text to an LLM.
    special = await _run_registered_pipeline(task, report, is_cancelled)
    if special is not None:
        return special

    if assignee_type == "team":
        return await _execute_team(task, report, is_cancelled)
    if assignee_type == "skill" or (task.get("skill_ref") or {}).get("skill_id"):
        return await _execute_skill(task, report, is_cancelled)
    return await _execute_agent(task, report, is_cancelled)


# ── Extension-provided pipelines ─────────────────────────────────────

async def _run_registered_pipeline(
    task: Dict[str, Any],
    report: Callable[..., None],
    is_cancelled: Callable[[], bool],
) -> Optional[str]:
    """Run a task that another extension queued with a declared `kind`.

    Returns the result text, or None when this is an ordinary agent task.
    """
    kind, payload = _task_kind(task)
    if not kind:
        return None

    if kind == "video_studio.reup":
        from tubecli.extensions.video_studio.pipeline import run_reup

        url = payload.get("url", "")
        options = payload.get("options") or {}
        logger.info(f"[Codex] running video_studio reup for {url}")
        return await asyncio.to_thread(run_reup, url, options, report, is_cancelled)

    if kind == "video_studio.download":
        from tubecli.extensions.video_studio.jobs import run_download_task

        url = payload.get("url", "")
        logger.info(f"[Codex] running video_studio download for {url}")
        return await asyncio.to_thread(
            run_download_task, url, payload.get("options") or {}, report, is_cancelled
        )

    if kind.startswith("content_video."):
        # .plan (script for review) and .render (accepted script → mp4);
        # the pipeline module owns the mapping so codex never learns the stages.
        from tubecli.extensions.content_video.pipeline import run_kind

        logger.info(f"[Codex] running {kind} for agent {payload.get('agent_id', '')!r}")
        return await asyncio.to_thread(run_kind, kind, payload, report, is_cancelled)

    # Pipeline do extension KHÁC đăng ký lúc bật (codex/pipelines.py) — Pod Studio «Video từ ảnh tham chiếu»…
    # Lõi không cần biết tên từng extension nữa.
    try:
        from tubecli.extensions.codex.pipelines import run_registered

        result = await run_registered(kind, payload, report, is_cancelled)
        if result is not None:
            return result
    except TaskCancelled:
        raise
    except Exception as e:
        logger.error(f"[Codex] registered pipeline {kind!r} failed: {e}", exc_info=True)
        raise

    logger.warning(f"[Codex] unknown pipeline kind {kind!r}; falling back to the agent")
    return None


def _task_kind(task: Dict[str, Any]):
    """Read the `kind` an extension stamped on the task's event log."""
    try:
        from tubecli.extensions.codex.manager import codex_manager

        # Read the whole log, not the last 50 lines: a multi-step pipeline writes
        # a couple of events per step, so after a few retries the `kind` event
        # fell out of a 50-line window and the task silently became a chat turn.
        # The file itself is pruned to 500 lines, so 1000 means "everything".
        for ev in reversed(codex_manager.get_events(task["id"], limit=1000)):
            data = ev.get("data") or {}
            if data.get("kind"):
                return data["kind"], data
    except Exception as e:
        logger.debug(f"[Codex] could not read the task kind: {e}")
    return None, {}


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
            # Trước đây trả `reply` về như kết quả ⇒ task sang REVIEW dù bước «run_skill» đã báo lỗi (10/11/2026).
            report("run_skill", "error", f"Skill not found: {skill_id}")
            raise AgentRefused(f"The agent picked a skill that does not exist on this server ({skill_id or '?'})"
                               + (f" — it said: {_brief(reply)}" if reply.strip() else ""))
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
        failure = skill_failure(out)
        if failure:
            # Trước đây «[Codex Error] wrong_thread: …» về như kết quả: bước báo success, task sang review.
            report("run_skill", "error", failure[:300])
            raise RuntimeError(f"Skill '{skill.get('name')}' failed: {failure[:500]}")
        if wants_video(task, skill):
            video = find_video(out)
            if not video:
                report("run_skill", "error", "The skill ended without a video file")
                raise RuntimeError(
                    f"Skill '{skill.get('name')}' finished but produced no video file — a video task only goes to "
                    "review with a real, playable video. Skill output: " + str(out or reply or "")[:400])
            report("run_skill", "success", f"Video: {video}")
            return out or reply
        report("run_skill", "success", "Skill finished")
        return out or reply

    if action and action not in ("run_skill", None):
        # download_video / create_team / run_api / schedule_event / extension
        # actions all flow through the shared dispatcher.
        report("action", "running", f"Dispatching action: {action}", label="Thực thi action")
        dispatched = await _dispatch_action(reply, agent_dict, task)
        report("action", "success", f"Action {action} handled")
        return dispatched or reply

    # Trả lời thẳng (không chạy skill / action nào) mà câu trả lời là TỪ CHỐI / «không làm được» ⇒ task HỎNG với lý do
    # của agent, không vào REVIEW (task #190 contabo, 7/11/2026: Orchestrator viết «Tôi không dựng được video Bài 14…
    # không có thư mục, API không gọi được» — bảng ghi «awaiting review» như một kết quả xong).
    why = refusal_reason(reply, goal)
    if why:
        report("reason", "error", f"The agent did not do the task: {why[:240]}")
        raise AgentRefused(f"The agent did not do the task — {why}")
    return reply


# ── Kết quả skill: lỗi hay thật (Task Board #4, 7/11/2026) ──────────────────────────────────────────────────
_SKILL_ERROR_RE = re.compile(r"^\s*(?:⚠️\s*\*\[Auto-Failover[^\]]*\]\*\s*)?(?:\[[\w .-]*Error\]|\[AI SERVER\]|❌)", re.I)
_VIDEO_EXT = (".mp4", ".mov", ".mkv", ".webm", ".m4v")
_VIDEO_PATH_RE = re.compile(r"(?:[A-Za-z]:[\\/]|/)[^\n\r\"'<>|*?`]*?\.(?:mp4|mov|mkv|webm|m4v)\b", re.I)
_MAKE_VIDEO_RE = re.compile(
    r"\b(?:make|create|render|build|produce|generate)\b[^.\n]{0,40}\bvideos?\b|\b(?:tạo|dựng|làm|xuất|render)\s+(?:lại\s+)?video",
    re.I)


def skill_failure(out: Any) -> str:
    """Câu lỗi (provider / skill) mà skill trả về dưới dạng CHUỖI — rỗng nếu là kết quả thật."""
    text = str(out or "")
    return text.strip() if _SKILL_ERROR_RE.match(text) else ""


# ── Trả lời thẳng mà KHÔNG làm việc: từ chối / «không làm được» (10/11/2026) ─────────────────────────────────────
# Chỉ xét PHẦN MỞ ĐẦU câu trả lời (REFUSAL_WINDOW ký tự): agent từ chối thì nói ngay câu đầu («Tôi không dựng được video
# Bài 14…», «I can't do that here…»); một kết quả thật có thể nhắc «không thể» ở đoạn giữa (giải thích một hạn chế
# nhỏ) mà vẫn là kết quả — không được đánh hỏng nó. Mọi mẫu ở MỘT bảng này.
REFUSAL_WINDOW = 320
_REFUSAL_PATTERNS = (
    # English
    r"\bI\s*(?:'m|am)\s+(?:sorry|afraid)\b[^.!?\n]{0,60}\b(?:can(?:no|')t|cannot|unable|not\s+able)\b",
    r"\bI\s+(?:can(?:no|')t|cannot|could\s?n[o']t|could\s+not|won'?t\s+be\s+able\s+to|was\s+(?:not\s+able|unable)\s+to"
    r"|(?:am|'m)\s+(?:not\s+able|unable)\s+to|do\s+not\s+have\s+(?:access|the\s+(?:ability|tools?|permissions?))"
    r"|don'?t\s+have\s+(?:access|the\s+(?:ability|tools?|permissions?)))\b",
    r"^\s*(?:unfortunately|sorry)[,!]?\s+(?:I|this|that|it)\b[^.!?\n]{0,40}\b(?:can(?:no|')t|cannot|isn'?t\s+possible"
    r"|not\s+possible|unable)\b",
    r"\b(?:this|that|it)\s+(?:is\s+not|isn'?t)\s+(?:possible|something\s+I\s+can\s+do)\b",
    # Tiếng Việt — «không thể», «không <động từ…> được», «chưa thể», «không có quyền/cách/khả năng»
    r"\b(?:tôi|mình|em|tớ)\s+(?:hiện\s+|đã\s+|vẫn\s+|rất\s+tiếc\s+)?(?:không\s+thể|chưa\s+thể"
    r"|không\s+(?!chỉ\b|những\b|cần\b|quên\b|ngại\b)(?:[^\s.,!?;:]+\s+){1,6}?được\b|không\s+có\s+(?:quyền|cách|khả\s+năng|công\s+cụ))",
    r"^\s*(?:xin\s+lỗi|rất\s+tiếc)[,!]?\s+[^.!?\n]{0,60}\b(?:không\s+thể|không\s+(?!chỉ\b|những\b|cần\b)(?:[^\s.,!?;:]+\s+){1,6}?được\b)",
    r"^\s*(?:hiện\s+)?không\s+thể\s+(?:thực\s+hiện|làm|tạo|dựng|chạy|truy\s+cập|hoàn\s+thành)\b",
    # Español
    r"\bno\s+(?:puedo|pude|podré|he\s+podido|logré|es\s+posible|me\s+es\s+posible|soy\s+capaz|tengo\s+(?:acceso|forma|"
    r"manera|permiso))\b",
    r"^\s*(?:lo\s+siento|lamentablemente|desafortunadamente)\b[^.!?\n]{0,60}\bno\b",
    # Français / Português / Deutsch — rẻ, cùng một kiểu câu mở đầu
    r"\bje\s+ne\s+(?:peux|pourrai|suis\s+pas\s+en\s+mesure)\b",
    r"\b(?:não\s+(?:consigo|posso|consegui|foi\s+possível))\b",
    r"\bich\s+(?:kann|konnte)\s+(?:das\s+|dies\s+|es\s+)?(?:leider\s+)?nicht\b",
)
_REFUSAL_RE = re.compile("|".join(f"(?:{p})" for p in _REFUSAL_PATTERNS), re.I | re.M)
# Việc mà bản thân nó là CÂU HỎI («làm được X không?», «có thể … không?») thì «không thể» chính là câu trả lời đúng.
_QUESTION_GOAL_RE = re.compile(r"\?\s*$|\b(?:có\s+thể|được\s+không|is\s+it\s+possible|can\s+(?:you|we|I)\b"
                               r"|¿)", re.I)


def _brief(text: Any, limit: int = 400) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= limit else s[:limit].rstrip() + "…"


_SENTENCE_END_RE = re.compile(r"[.!?…。！？](?=\s|$)|\n")


def _opening(text: str) -> str:
    """Câu MỞ ĐẦU (tối đa REFUSAL_WINDOW ký tự); câu đầu quá ngắn («Xin lỗi.», «Sorry!») thì lấy thêm câu kế.
    «Done. … Note: I cannot verify the GPU path» không phải từ chối — chữ «cannot» nằm ở câu thứ hai."""
    head = text[:REFUSAL_WINDOW]
    m = _SENTENCE_END_RE.search(head)
    if not m:
        return head
    first = head[:m.end()]
    if len(first.strip()) >= 25:
        return first
    m2 = _SENTENCE_END_RE.search(head, m.end())
    return head[:m2.end()] if m2 else head


def refusal_reason(reply: Any, goal: Any = "") -> str:
    """Câu trả lời THẲNG của agent là lời từ chối / «không làm được» ⇒ lý do (mở đầu câu trả lời, gọn); không thì "".

    Bảo thủ có chủ ý: chỉ xét CÂU MỞ ĐẦU; việc là một câu hỏi ngắn thì không bao giờ coi là từ chối."""
    text = str(reply or "").strip()
    if not text:
        return ""
    g = " ".join(str(goal or "").split())
    if g and len(g) <= 240 and _QUESTION_GOAL_RE.search(g):
        return ""
    if not _REFUSAL_RE.search(_opening(text)):
        return ""
    return _brief(text)


def wants_video(task: Dict[str, Any], skill: Optional[Dict[str, Any]] = None) -> bool:
    """Việc này là TẠO video (làn video, hoặc mục tiêu / tên skill nói tạo / dựng video)."""
    if str(task.get("lane") or "").strip().lower() == "video":
        return True
    text = " ".join(str(x or "") for x in (task.get("title"), task.get("goal"), (skill or {}).get("name")))
    return bool(_MAKE_VIDEO_RE.search(text))


def _video_ok(path: str) -> bool:
    """File video có thật, không rỗng, và (nếu có ffprobe) đọc được thời lượng > 0."""
    import os
    import shutil
    import subprocess
    try:
        if not os.path.isfile(path) or os.path.getsize(path) < 10_000:
            return False
    except OSError:
        return False
    probe = shutil.which("ffprobe")
    if not probe:
        return True
    try:
        r = subprocess.run([probe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                           capture_output=True, text=True, timeout=30)
        return float((r.stdout or "0").strip() or 0) > 0
    except Exception:  # noqa: BLE001 — ffprobe lỗi thì không đánh hỏng việc vì nó
        return True


def find_video(out: Any) -> str:
    """Đường dẫn video HỢP LỆ đầu tiên nhắc trong kết quả skill — rỗng nếu không có."""
    text = str(out or "")
    for m in _VIDEO_PATH_RE.finditer(text):
        path = m.group(0).strip().rstrip(".,;)")
        # Khớp có thể bắt đầu sớm («and/or C:/x.mp4»): thử cả từng đoạn đuôi bắt đầu bằng ổ đĩa.
        tails = [path] + [path[i:] for i in range(1, len(path) - 2) if path[i + 1] == ":" and path[i].isalpha()
                          and path[i + 2] in "\\/"]
        for cand in tails:
            if _video_ok(cand):
                return cand
    return ""


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
