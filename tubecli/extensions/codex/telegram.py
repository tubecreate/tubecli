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
        return "📋 Không có task nào."
    lines = [header] if header else ["📋 *Codex tasks*"]
    lines += [_fmt_line(t) for t in tasks]
    lines.append("\nLệnh: `approve <n>` · `reject <n>` · `cancel <n>` · `retry <n>` · `codex <n>`")
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
        lines.append(f"\n👤 Giao cho: _{who}_ ({task.get('assignee_type')})")
    steps = task.get("steps") or []
    if steps:
        lines.append("\n*Tiến độ:*")
        for s in steps[-8:]:
            mark = {"success": "✅", "error": "❌", "running": "⏳", "skipped": "⏭"}.get(
                s.get("status"), "•"
            )
            lines.append(f"{mark} {s.get('label') or s.get('name')} — {s.get('message', '')}"[:200])
    if task.get("result"):
        lines.append(f"\n*Kết quả:*\n{task['result'][:1200]}")
    if task.get("error"):
        lines.append(f"\n❌ *Lỗi:* {task['error'][:600]}")

    status = task.get("status")
    seq = task.get("seq")
    if status == PENDING_APPROVAL:
        lines.append(f"\n➡️ `approve {seq}` hoặc `reject {seq}`")
    elif status == REVIEW:
        lines.append(f"\n➡️ `accept {seq}` để đóng, `retry {seq}` để chạy lại")
    elif status == "failed":
        lines.append(f"\n➡️ `retry {seq}` để chạy lại")
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
        return "❌ Thiếu `goal` — cần mô tả công việc cần làm."

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
        return f"❌ Không tạo được task: {e}"

    who = task.get("assignee_name") or "agent phù hợp nhất"
    return (
        f"📋 Đã tạo *Codex #{task['seq']}* — _{task['title']}_\n"
        f"👤 Giao cho: {who}\n\n"
        f"⏸ Đang chờ bạn duyệt. Trả lời `approve {task['seq']}` để chạy, "
        f"`reject {task['seq']}` để bỏ."
    )


async def action_list_tasks(action_data: dict, context: dict) -> str:
    status = (action_data.get("status") or "").strip().lower()
    if status and status not in ALL_STATES and status != "active":
        status = ""
    tasks = codex_manager.list_tasks(status=status or "active", limit=15)
    header = f"📋 *Codex tasks* ({status or 'active'})"
    return format_task_list(tasks, header)


async def action_task_status(action_data: dict, context: dict) -> str:
    ref = action_data.get("task") or action_data.get("id") or action_data.get("seq")
    task = codex_manager.resolve_ref(ref)
    if not task:
        return f"❌ Không tìm thấy task `{ref}`."
    return format_task_detail(task)


def _actor(context: dict) -> str:
    chat_id = context.get("chat_id", "")
    return f"user:telegram:{chat_id}" if chat_id else "user:telegram"


async def action_approve(action_data: dict, context: dict) -> str:
    ref = action_data.get("task") or action_data.get("id") or action_data.get("seq")
    task = codex_manager.resolve_ref(ref)
    if not task:
        return f"❌ Không tìm thấy task `{ref}`."
    try:
        updated = codex_manager.approve(
            task["id"], actor=_actor(context), note=(action_data.get("note") or "")
        )
    except Exception as e:
        return f"❌ Không duyệt được: {e}"
    return f"✅ Đã duyệt *Codex #{updated['seq']}* — đang xếp hàng chạy."


async def action_reject(action_data: dict, context: dict) -> str:
    ref = action_data.get("task") or action_data.get("id") or action_data.get("seq")
    task = codex_manager.resolve_ref(ref)
    if not task:
        return f"❌ Không tìm thấy task `{ref}`."
    try:
        updated = codex_manager.reject(
            task["id"], actor=_actor(context), note=(action_data.get("note") or "")
        )
    except Exception as e:
        return f"❌ Không từ chối được: {e}"
    return f"🚫 Đã từ chối *Codex #{updated['seq']}*."


async def action_cancel(action_data: dict, context: dict) -> str:
    ref = action_data.get("task") or action_data.get("id") or action_data.get("seq")
    task = codex_manager.resolve_ref(ref)
    if not task:
        return f"❌ Không tìm thấy task `{ref}`."
    try:
        updated = codex_manager.cancel(task["id"], actor=_actor(context))
    except Exception as e:
        return f"❌ Không huỷ được: {e}"
    return f"⛔ Đã huỷ *Codex #{updated['seq']}*."


async def action_retry(action_data: dict, context: dict) -> str:
    ref = action_data.get("task") or action_data.get("id") or action_data.get("seq")
    task = codex_manager.resolve_ref(ref)
    if not task:
        return f"❌ Không tìm thấy task `{ref}`."
    try:
        updated = codex_manager.retry(task["id"], actor=_actor(context))
    except Exception as e:
        return f"❌ Không chạy lại được: {e}"
    return f"🔁 Đã xếp lại *Codex #{updated['seq']}* vào hàng chờ."


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
    "approve": "approve", "duyet": "approve", "duyệt": "approve", "ok": "approve",
    "reject": "reject", "tuchoi": "reject", "từchối": "reject", "no": "reject",
    "cancel": "cancel", "huy": "cancel", "hủy": "cancel", "stop": "cancel",
    "retry": "retry", "chaylai": "retry", "chạylại": "retry", "again": "retry",
    "accept": "accept", "done": "accept", "xong": "accept",
    "status": "status", "show": "status", "xem": "status",
    "list": "list", "tasks": "list", "ls": "list",
}


def handle_command(text: str, actor: str = "user") -> str:
    """Parse a free-text codex command. Never calls an LLM.

    Recognised: "codex", "codex 3", "approve 3", "reject 3 lý do", "cancel 3",
    "retry 3", "accept 3", "status 3", "codex list running".
    """
    raw = (text or "").strip()
    if not raw:
        return format_task_list(codex_manager.list_tasks(status="active", limit=15))

    words = raw.split()
    # Drop a leading "codex" / "task" / "nhiệm vụ" trigger word.
    lead = words[0].lower().lstrip("/")
    if lead in ("codex", "task", "tasks", "nhiệm", "nhiem"):
        words = words[1:]
        if words and words[0].lower() in ("vụ", "vu"):
            words = words[1:]

    if not words:
        return format_task_list(codex_manager.list_tasks(status="active", limit=15))

    head = words[0].lower().strip(":#")
    has_task_arg = len(words) > 1 and words[1].strip("#:").isdigit()

    # A bare state name is a filter ("codex done"), not a verb — this matters
    # because "done" is also an alias for accept, which needs a task number.
    if head in ALL_STATES and not has_task_arg:
        return format_task_list(
            codex_manager.list_tasks(status=head, limit=20), f"📋 *Codex tasks* ({head})"
        )

    verb = _VERBS.get(head)

    # "codex 3" → show detail
    if verb is None and head.isdigit():
        task = codex_manager.resolve_ref(head)
        return format_task_detail(task) if task else f"❌ Không tìm thấy task #{head}."

    if verb is None:
        return (
            "📋 *Codex* — lệnh khả dụng:\n"
            "`codex` — danh sách task đang hoạt động\n"
            "`codex <n>` — chi tiết task\n"
            "`approve <n>` · `reject <n>` · `cancel <n>` · `retry <n>` · `accept <n>`\n"
            "`codex done|failed|running|pending_approval` — lọc theo trạng thái"
        )

    if verb == "list":
        rest = words[1].lower() if len(words) > 1 else "active"
        status = rest if (rest in ALL_STATES or rest == "active") else "active"
        return format_task_list(
            codex_manager.list_tasks(status=status, limit=20), f"📋 *Codex tasks* ({status})"
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
            return format_task_list(candidates, f"❓ Có {len(candidates)} task — cần rõ số:")
        else:
            return f"❌ Cần số task, ví dụ `{verb} 3`."

    task = codex_manager.resolve_ref(ref)
    if not task:
        return f"❌ Không tìm thấy task `{ref}`."

    try:
        if verb == "approve":
            t = codex_manager.approve(task["id"], actor=actor, note=note)
            return f"✅ Đã duyệt *Codex #{t['seq']}* — đang xếp hàng chạy."
        if verb == "reject":
            t = codex_manager.reject(task["id"], actor=actor, note=note)
            return f"🚫 Đã từ chối *Codex #{t['seq']}*."
        if verb == "cancel":
            t = codex_manager.cancel(task["id"], actor=actor)
            return f"⛔ Đã huỷ *Codex #{t['seq']}*."
        if verb == "retry":
            t = codex_manager.retry(task["id"], actor=actor)
            return f"🔁 Đã xếp lại *Codex #{t['seq']}* vào hàng chờ."
        if verb == "accept":
            t = codex_manager.complete_review(task["id"], True, actor=actor)
            return f"✅ *Codex #{t['seq']}* đã hoàn tất."
        if verb == "status":
            return format_task_detail(task)
    except Exception as e:
        return f"❌ {e}"

    return format_task_detail(task)
