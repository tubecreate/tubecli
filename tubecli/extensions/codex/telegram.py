"""
Codex ↔ Telegram bridge.

Two entry points:

1. LLM-driven actions (`codex_*`) registered through
   Extension.get_telegram_actions() and dispatched by
   core/telegram_actions.py:handle_extension_action.
   Payloads MUST stay FLAT — AgentBrain._extract_action (core/brain.py:1153)
   truncates nested JSON.

2. A deterministic, zero-token command parser (`handle_command`) reached by the
   registered "Codex" skill, so "approve 3" works without an LLM round-trip.
"""
import asyncio
import logging
import threading
from typing import Any, Dict, List

from tubecli.core.bot_i18n import t
from tubecli.extensions.codex.manager import (
    ALL_STATES,
    PENDING_APPROVAL,
    REVIEW,
    codex_manager,
)

logger = logging.getLogger("Codex")

STATUS_ICON = {
    "pending_approval": "🟡",
    "queued": "⏳",
    "running": "⚙️",
    "review": "🔍",
    "done": "✅",
    "failed": "❌",
    "rejected": "🚫",
    "cancelled": "⛔",
}


# ── Outbound notifications ───────────────────────────────────────────

async def notify(token: str, chat_id: str, text: str):
    """Send one Telegram message, retrying without Markdown on failure."""
    if not token or not chat_id:
        return
    try:
        import httpx

        async with httpx.AsyncClient(timeout=15) as client:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            resp = await client.post(url, json={
                "chat_id": chat_id,
                "text": text[:4000],
                "parse_mode": "Markdown",
            })
            if resp.status_code != 200 or not resp.json().get("ok"):
                await client.post(url, json={"chat_id": chat_id, "text": text[:4000]})
    except Exception as e:
        logger.warning(f"[Codex] Telegram notify failed: {e}")


def notify_fire_and_forget(token: str, chat_id: str, text: str):
    """Schedule a notification from ANY context (event loop or plain thread)."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        loop.create_task(notify(token, chat_id, text))
    else:
        threading.Thread(
            target=lambda: asyncio.run(notify(token, chat_id, text)),
            daemon=True,
        ).start()


# ── Formatting ───────────────────────────────────────────────────────

def _fmt_line(task: Dict[str, Any]) -> str:
    icon = STATUS_ICON.get(task.get("status", ""), "•")
    who = task.get("assignee_name") or task.get("assignee_type") or ""
    suffix = f" — _{who}_" if who else ""
    return f"{icon} *#{task.get('seq')}* {task.get('title', '')}{suffix}"


def format_task_list(tasks: List[Dict[str, Any]], header: str = "") -> str:
    if not tasks:
        return t("codex.no_tasks")
    lines = [header] if header else [t("codex.list_header")]
    lines += [_fmt_line(task) for task in tasks]
    lines.append(t("codex.list_commands"))
    return "\n".join(lines)


def format_task_detail(task: Dict[str, Any]) -> str:
    icon = STATUS_ICON.get(task.get("status", ""), "•")
    lines = [
        f"{icon} *Codex #{task.get('seq')}* — {task.get('status')}",
        f"*{task.get('title', '')}*",
        "",
        task.get("goal", "")[:800],
    ]
    who = task.get("assignee_name") or ""
    if who:
        lines.append(t("codex.detail_assignee", who=who, kind=task.get("assignee_type")))
    steps = task.get("steps") or []
    if steps:
        lines.append(t("codex.detail_progress"))
        for s in steps[-8:]:
            mark = {"success": "✅", "error": "❌", "running": "⏳", "skipped": "⏭"}.get(
                s.get("status"), "•"
            )
            lines.append(f"{mark} {s.get('label') or s.get('name')} — {s.get('message', '')}"[:200])
    if task.get("result"):
        lines.append(t("codex.detail_result") + f"\n{task['result'][:1200]}")
    if task.get("error"):
        lines.append(t("codex.detail_error") + f" {task['error'][:600]}")

    status = task.get("status")
    seq = task.get("seq")
    if status == PENDING_APPROVAL:
        lines.append(t("codex.hint_approve", seq=seq))
    elif status == REVIEW:
        lines.append(t("codex.hint_review", seq=seq))
    elif status == "failed":
        lines.append(t("codex.hint_retry", seq=seq))
    return "\n".join(lines)


# ── LLM-driven actions ───────────────────────────────────────────────

async def action_create_task(action_data: dict, context: dict) -> str:
    goal = (
        action_data.get("goal")
        or action_data.get("task")
        or action_data.get("input")
        or ""
    ).strip()
    if not goal:
        return t("codex.err_no_goal")

    assignee = (action_data.get("assignee") or action_data.get("agent") or "").strip()
    assignee_type = (action_data.get("assignee_type") or "").strip().lower()
    if not assignee_type:
        assignee_type = "team" if action_data.get("team") else "agent"
    if not assignee and action_data.get("team"):
        assignee = str(action_data.get("team")).strip()

    origin = {
        "chat_id": context.get("chat_id", ""),
        "token": context.get("token", ""),
        "agent_id": (context.get("agent") or {}).get("id", ""),
    }

    try:
        task = codex_manager.create_task(
            goal=goal,
            title=(action_data.get("title") or "").strip(),
            created_by="brain",
            origin=origin,
            assignee_type=assignee_type,
            assignee_name=assignee,
            skill_name=(action_data.get("skill") or "").strip(),
            priority=int(action_data.get("priority") or 0),
        )
    except Exception as e:
        return t("codex.err_create", error=e)

    who = task.get("assignee_name") or t("codex.best_agent")
    return t("codex.created", seq=task["seq"], title=task["title"], who=who)


async def action_list_tasks(action_data: dict, context: dict) -> str:
    status = (action_data.get("status") or "").strip().lower()
    if status and status not in ALL_STATES and status != "active":
        status = ""
    tasks = codex_manager.list_tasks(status=status or "active", limit=15)
    header = f"{t('codex.list_header')} ({status or 'active'})"
    return format_task_list(tasks, header)


async def action_task_status(action_data: dict, context: dict) -> str:
    ref = action_data.get("task") or action_data.get("id") or action_data.get("seq")
    task = codex_manager.resolve_ref(ref)
    if not task:
        return t("codex.err_not_found", ref=ref)
    return format_task_detail(task)


def _actor(context: dict) -> str:
    chat_id = context.get("chat_id", "")
    return f"user:telegram:{chat_id}" if chat_id else "user:telegram"


async def action_approve(action_data: dict, context: dict) -> str:
    ref = action_data.get("task") or action_data.get("id") or action_data.get("seq")
    task = codex_manager.resolve_ref(ref)
    if not task:
        return t("codex.err_not_found", ref=ref)
    try:
        updated = codex_manager.approve(
            task["id"], actor=_actor(context), note=(action_data.get("note") or "")
        )
    except Exception as e:
        return t("codex.err_approve", error=e)
    return t("codex.approved", seq=updated["seq"])


async def action_reject(action_data: dict, context: dict) -> str:
    ref = action_data.get("task") or action_data.get("id") or action_data.get("seq")
    task = codex_manager.resolve_ref(ref)
    if not task:
        return t("codex.err_not_found", ref=ref)
    try:
        updated = codex_manager.reject(
            task["id"], actor=_actor(context), note=(action_data.get("note") or "")
        )
    except Exception as e:
        return t("codex.err_reject", error=e)
    return t("codex.rejected", seq=updated["seq"])


async def action_cancel(action_data: dict, context: dict) -> str:
    ref = action_data.get("task") or action_data.get("id") or action_data.get("seq")
    task = codex_manager.resolve_ref(ref)
    if not task:
        return t("codex.err_not_found", ref=ref)
    try:
        updated = codex_manager.cancel(task["id"], actor=_actor(context))
    except Exception as e:
        return t("codex.err_cancel", error=e)
    return t("codex.cancelled", seq=updated["seq"])


async def action_retry(action_data: dict, context: dict) -> str:
    ref = action_data.get("task") or action_data.get("id") or action_data.get("seq")
    task = codex_manager.resolve_ref(ref)
    if not task:
        return t("codex.err_not_found", ref=ref)
    try:
        updated = codex_manager.retry(task["id"], actor=_actor(context))
    except Exception as e:
        return t("codex.err_retry", error=e)
    return t("codex.retried", seq=updated["seq"])


def get_telegram_actions() -> Dict[str, Any]:
    return {
        "codex_create_task": action_create_task,
        "codex_list_tasks": action_list_tasks,
        "codex_task_status": action_task_status,
        "codex_approve": action_approve,
        "codex_reject": action_reject,
        "codex_cancel": action_cancel,
        "codex_retry": action_retry,
    }


# ── Deterministic command parser (zero LLM tokens) ───────────────────

_VERBS = {
    # English + ASCII shorthands
    "approve": "approve", "ok": "approve", "yes": "approve",
    "reject": "reject", "no": "reject",
    "cancel": "cancel", "stop": "cancel",
    "retry": "retry", "again": "retry",
    "accept": "accept", "done": "accept",
    "status": "status", "show": "status",
    "list": "list", "tasks": "list", "ls": "list",
    # Every shipped UI language, so users type in their own words. Accents are
    # optional (users often type without them) — both spellings map to the verb.
    "duyet": "approve", "duyệt": "approve",          # vi
    "批准": "approve", "同意": "approve", "核准": "approve",  # zh / zh-TW
    "承認": "approve", "승인": "approve",              # ja / ko
    "одобрить": "approve", "onayla": "approve", "aprobar": "approve",  # ru / tr / es
    "tuchoi": "reject", "từchối": "reject",           # vi
    "拒绝": "reject", "拒絕": "reject", "却下": "reject", "거절": "reject",
    "отклонить": "reject", "reddet": "reject", "rechazar": "reject",
    "huy": "cancel", "hủy": "cancel",                 # vi
    "取消": "cancel", "キャンセル": "cancel", "취소": "cancel",
    "отменить": "cancel", "iptal": "cancel", "cancelar": "cancel",
    "chaylai": "retry", "chạylại": "retry",           # vi
    "重试": "retry", "重試": "retry", "再実行": "retry", "재시도": "retry",
    "повторить": "retry", "tekrar": "retry", "reintentar": "retry",
    "xong": "accept",                                 # vi
    "完成": "accept", "完了": "accept", "완료": "accept",
    "готово": "accept", "tamam": "accept", "completar": "accept",
    "xem": "status",                                  # vi
    "详情": "status", "詳情": "status", "詳細": "status", "상세": "status",
    "статус": "status", "durum": "status", "estado": "status",
    "danhsach": "list", "列表": "list", "一覧": "list", "목록": "list",
    "список": "list", "liste": "list", "lista": "list",
}

# Leading words that only announce "this is a codex command" and carry no meaning.
_TRIGGERS = {
    "codex", "task", "tasks", "nhiệm", "nhiem",
    "任务", "任務", "タスク", "작업", "задача", "задачи", "görev", "tarea", "tareas",
}
# Second half of a two-word trigger ("nhiệm vụ") — only dropped after a trigger.
_TRIGGER_TAILS = {"vụ", "vu"}


def handle_command(text: str, actor: str = "user") -> str:
    """Parse a free-text codex command. Never calls an LLM.

    Recognised: "codex", "codex 3", "approve 3", "reject 3 lý do", "cancel 3",
    "retry 3", "accept 3", "status 3", "codex list running".
    """
    raw = (text or "").strip()
    if not raw:
        return format_task_list(codex_manager.list_tasks(status="active", limit=15))

    words = raw.split()
    # Drop a leading trigger word ("codex", "task", "nhiệm vụ", "任务", …).
    lead = words[0].lower().lstrip("/")
    if lead in _TRIGGERS:
        words = words[1:]
        if words and words[0].lower() in _TRIGGER_TAILS:
            words = words[1:]

    if not words:
        return format_task_list(codex_manager.list_tasks(status="active", limit=15))

    head = words[0].lower().strip(":#")
    has_task_arg = len(words) > 1 and words[1].strip("#:").isdigit()

    # A bare state name is a filter ("codex done"), not a verb — this matters
    # because "done" is also an alias for accept, which needs a task number.
    if head in ALL_STATES and not has_task_arg:
        return format_task_list(
            codex_manager.list_tasks(status=head, limit=20),
            f"{t('codex.list_header')} ({head})",
        )

    verb = _VERBS.get(head)

    # "codex 3" → show detail
    if verb is None and head.isdigit():
        task = codex_manager.resolve_ref(head)
        return (format_task_detail(task) if task
                else t("codex.err_not_found_seq", ref=head))

    if verb is None:
        return t("codex.help")

    if verb == "list":
        rest = words[1].lower() if len(words) > 1 else "active"
        status = rest if (rest in ALL_STATES or rest == "active") else "active"
        return format_task_list(
            codex_manager.list_tasks(status=status, limit=20),
            f"{t('codex.list_header')} ({status})",
        )

    ref = words[1].strip("#:") if len(words) > 1 else ""
    note = " ".join(words[2:]) if len(words) > 2 else ""
    if not ref:
        # "approve" with no number: act on the single obvious candidate.
        wanted = PENDING_APPROVAL if verb in ("approve", "reject") else (
            REVIEW if verb == "accept" else ""
        )
        candidates = codex_manager.list_tasks(status=wanted, limit=5) if wanted else []
        if len(candidates) == 1:
            ref = candidates[0]["id"]
        elif len(candidates) > 1:
            return format_task_list(
                candidates, t("codex.ambiguous", count=len(candidates)))
        else:
            return t("codex.err_need_number", verb=verb)

    task = codex_manager.resolve_ref(ref)
    if not task:
        return t("codex.err_not_found", ref=ref)

    try:
        if verb == "approve":
            done = codex_manager.approve(task["id"], actor=actor, note=note)
            return t("codex.approved", seq=done["seq"])
        if verb == "reject":
            done = codex_manager.reject(task["id"], actor=actor, note=note)
            return t("codex.rejected", seq=done["seq"])
        if verb == "cancel":
            done = codex_manager.cancel(task["id"], actor=actor)
            return t("codex.cancelled", seq=done["seq"])
        if verb == "retry":
            done = codex_manager.retry(task["id"], actor=actor)
            return t("codex.retried", seq=done["seq"])
        if verb == "accept":
            done = codex_manager.complete_review(task["id"], True, actor=actor)
            return t("codex.accepted", seq=done["seq"])
        if verb == "status":
            return format_task_detail(task)
    except Exception as e:
        return f"❌ {e}"

    return format_task_detail(task)
