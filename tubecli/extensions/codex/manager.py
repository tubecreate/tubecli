"""
Codex Manager — durable task store, state machine and event log.

This is the ONLY business-logic layer of the codex extension. Routes, Telegram
handlers, the CLI and the worker all go through the module singleton
`codex_manager`.

Storage (JSON, per SKILL_EXTENSION_BUILDER.md §4.5):
    data/extensions_data/codex/tasks.json          {task_id: task_dict}
    data/extensions_data/codex/events/<id>.jsonl   append-only event stream

All writes happen under a single re-entrant lock and use an atomic
tmp + os.replace, because three writers share this process: the FastAPI
threadpool, the Telegram asyncio loop and the codex worker.
"""
import datetime
import json
import logging
import os
import threading
from typing import Any, Dict, List, Optional

try:
    from uuid_extensions import uuid7 as _uuid7
except ImportError:  # pragma: no cover - fallback when uuid_extensions is absent
    import uuid

    _uuid7 = uuid.uuid4

from tubecli.config import DATA_DIR, EXTENSIONS_DATA_DIR
from tubecli.core.bot_i18n import t as _t

logger = logging.getLogger("Codex")

# ── Paths ────────────────────────────────────────────────────────────
CODEX_DATA_DIR = os.path.join(str(EXTENSIONS_DATA_DIR), "codex")
TASKS_FILE = os.path.join(CODEX_DATA_DIR, "tasks.json")
EVENTS_DIR = os.path.join(CODEX_DATA_DIR, "events")

# ── States ───────────────────────────────────────────────────────────
PENDING_APPROVAL = "pending_approval"
QUEUED = "queued"
RUNNING = "running"
REVIEW = "review"
DONE = "done"
FAILED = "failed"
REJECTED = "rejected"
CANCELLED = "cancelled"

ALL_STATES = [
    PENDING_APPROVAL, QUEUED, RUNNING, REVIEW, DONE, FAILED, REJECTED, CANCELLED,
]

# Allowed transitions. Anything not listed here is refused by _transition().
TRANSITIONS: Dict[str, set] = {
    PENDING_APPROVAL: {QUEUED, REJECTED, CANCELLED},
    QUEUED: {RUNNING, CANCELLED},
    RUNNING: {REVIEW, DONE, FAILED, CANCELLED},
    REVIEW: {DONE, QUEUED, CANCELLED},
    FAILED: {QUEUED, CANCELLED},
    REJECTED: {QUEUED},
    DONE: set(),
    CANCELLED: set(),
}

ACTIVE_STATES = {PENDING_APPROVAL, QUEUED, RUNNING, REVIEW}

# Step status vocabulary — identical to PipelineStep (core/pipeline_tracker.py)
STEP_PENDING = "pending"
STEP_RUNNING = "running"
STEP_SUCCESS = "success"
STEP_ERROR = "error"
STEP_SKIPPED = "skipped"

MAX_EVENT_LINES = 500


def _now() -> str:
    return datetime.datetime.now().isoformat()


def _new_id() -> str:
    return str(_uuid7())


class CodexTask:
    """A unit of delegated work. Plain class + to_dict/from_dict, **kwargs tail."""

    def __init__(
        self,
        goal: str,
        title: str = "",
        id: Optional[str] = None,
        seq: int = 0,
        status: str = PENDING_APPROVAL,
        created_by: str = "user",
        origin: Optional[Dict] = None,
        assignee_type: str = "agent",
        assignee_id: str = "",
        assignee_name: str = "",
        skill_ref: Optional[Dict] = None,
        plan: Optional[List[Dict]] = None,
        approval: Optional[Dict] = None,
        result: str = "",
        error: str = "",
        priority: int = 0,
        retry_count: int = 0,
        max_retries: int = 3,
        steps: Optional[List[Dict]] = None,
        created_at: Optional[str] = None,
        updated_at: Optional[str] = None,
        started_at: str = "",
        finished_at: str = "",
        **kwargs,
    ):
        self.id = id or _new_id()
        self.seq = seq
        self.goal = goal
        self.title = title or (goal[:60] + ("…" if len(goal) > 60 else ""))
        self.status = status
        self.created_by = created_by
        self.origin = origin or {}
        self.assignee_type = assignee_type
        self.assignee_id = assignee_id
        self.assignee_name = assignee_name
        # Store BOTH id and name: LLMs supply names far more reliably than UUIDs
        # (see AgentBrain._resolve_skill_ref, core/brain.py:160).
        self.skill_ref = skill_ref or {}
        self.plan = plan or []
        self.approval = approval or {
            "required": True, "decided_by": "", "decided_at": "", "note": "",
        }
        self.result = result
        self.error = error
        self.priority = priority
        self.retry_count = retry_count
        self.max_retries = max_retries
        self.steps = steps or []
        self.created_at = created_at or _now()
        self.updated_at = updated_at or self.created_at
        self.started_at = started_at
        self.finished_at = finished_at
        self.extra = kwargs

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "seq": self.seq,
            "goal": self.goal,
            "title": self.title,
            "status": self.status,
            "created_by": self.created_by,
            "origin": self.origin,
            "assignee_type": self.assignee_type,
            "assignee_id": self.assignee_id,
            "assignee_name": self.assignee_name,
            "skill_ref": self.skill_ref,
            "plan": self.plan,
            "approval": self.approval,
            "result": self.result,
            "error": self.error,
            "priority": self.priority,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "steps": self.steps,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CodexTask":
        return cls(**data)


class CodexManager:
    """Durable task board with an approval-gated state machine."""

    def __init__(self):
        self._lock = threading.RLock()
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._loaded = False
        self._cancel_requested: set = set()
        # Off in tests, so a harness cannot push into the user's real chat.
        self.notifications_enabled = True

    # ── Persistence ──────────────────────────────────────────────

    def _ensure_dirs(self):
        os.makedirs(CODEX_DATA_DIR, exist_ok=True)
        os.makedirs(EVENTS_DIR, exist_ok=True)

    def _ensure_loaded(self):
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            self._ensure_dirs()
            try:
                if os.path.exists(TASKS_FILE):
                    with open(TASKS_FILE, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, dict):
                        self._tasks = data
            except Exception as e:
                logger.error(f"[Codex] Failed to load tasks.json: {e}")
                self._tasks = {}
            self._loaded = True

    def _save(self):
        """Atomic whole-file write. MUST be called while holding self._lock."""
        self._ensure_dirs()
        tmp = TASKS_FILE + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._tasks, f, indent=2, ensure_ascii=False)
            os.replace(tmp, TASKS_FILE)
        except Exception as e:
            logger.error(f"[Codex] Failed to save tasks.json: {e}")
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass

    # ── Events ───────────────────────────────────────────────────

    def _events_path(self, task_id: str) -> str:
        return os.path.join(EVENTS_DIR, f"{task_id}.jsonl")

    def append_event(
        self,
        task_id: str,
        kind: str,
        message: str,
        actor: str = "system",
        data: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """Append one line to the task's event stream.

        kind: created | state | step | log | approval | result | error | plan
        """
        event = {
            "ts": _now(),
            "task_id": task_id,
            "kind": kind,
            "actor": actor,
            "message": message,
        }
        if data:
            event["data"] = data
        try:
            self._ensure_dirs()
            with self._lock:
                with open(self._events_path(task_id), "a", encoding="utf-8") as f:
                    f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"[Codex] Failed to append event for {task_id}: {e}")
        return event

    def get_events(
        self, task_id: str, after: str = "", limit: int = 200
    ) -> List[Dict[str, Any]]:
        """Read events, optionally only those strictly newer than `after` (ISO ts)."""
        path = self._events_path(task_id)
        if not os.path.exists(path):
            return []
        out: List[Dict[str, Any]] = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except Exception:
                        continue
                    if after and ev.get("ts", "") <= after:
                        continue
                    out.append(ev)
        except Exception as e:
            logger.error(f"[Codex] Failed to read events for {task_id}: {e}")
            return []
        return out[-limit:] if limit else out

    def _prune_events(self, task_id: str):
        """Keep only the last MAX_EVENT_LINES lines once a task settles."""
        path = self._events_path(task_id)
        if not os.path.exists(path):
            return
        try:
            with self._lock:
                with open(path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                if len(lines) <= MAX_EVENT_LINES:
                    return
                tmp = path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    f.writelines(lines[-MAX_EVENT_LINES:])
                os.replace(tmp, path)
        except Exception as e:
            logger.error(f"[Codex] Failed to prune events for {task_id}: {e}")

    # ── Notifications ────────────────────────────────────────────

    def _resolve_notify_target(self, task: Dict[str, Any]):
        origin = task.get("origin") or {}
        token = origin.get("token") or ""
        chat_id = origin.get("chat_id") or ""
        if token and chat_id:
            return token, str(chat_id)
        try:
            settings_file = os.path.join(str(DATA_DIR), "global_settings.json")
            if os.path.exists(settings_file):
                with open(settings_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                token = token or data.get("telegram_bot_token", "")
                chat_id = chat_id or data.get("telegram_chat_id", "")
        except Exception:
            pass
        return token, str(chat_id) if chat_id else ""

    def notify(self, task: Dict[str, Any], text: str):
        """Fire-and-forget Telegram push. Never raises, never blocks.

        `notifications_enabled` is the seam a test harness switches off. A
        manager pointed at a temp directory still resolves the REAL bot token
        from global settings, so an isolated store is not isolation: a test
        creating six tasks pushed six messages into the user's chat.
        """
        if not self.notifications_enabled:
            return
        token, chat_id = self._resolve_notify_target(task)
        if not token or not chat_id:
            return
        try:
            from tubecli.extensions.codex.telegram import notify_fire_and_forget

            notify_fire_and_forget(token, chat_id, text)
        except Exception as e:
            logger.warning(f"[Codex] notify failed: {e}")

    # ── Task helpers ─────────────────────────────────────────────

    def _next_seq(self) -> int:
        """Short human-facing number, so a user can type 'approve 3'."""
        if not self._tasks:
            return 1
        try:
            return max(int(t.get("seq") or 0) for t in self._tasks.values()) + 1
        except Exception:
            return len(self._tasks) + 1

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        self._ensure_loaded()
        with self._lock:
            task = self._tasks.get(task_id)
            return dict(task) if task else None

    def resolve_ref(self, ref: Any) -> Optional[Dict[str, Any]]:
        """Resolve a task by full id, seq number ('3', '#3'), id prefix or title."""
        self._ensure_loaded()
        if ref is None:
            return None
        ref_s = str(ref).strip().lstrip("#")
        if not ref_s:
            return None
        with self._lock:
            if ref_s in self._tasks:
                return dict(self._tasks[ref_s])
            if ref_s.isdigit():
                seq = int(ref_s)
                for t in self._tasks.values():
                    if int(t.get("seq") or 0) == seq:
                        return dict(t)
            low = ref_s.lower()
            for t in self._tasks.values():
                if t["id"].lower().startswith(low):
                    return dict(t)
            for t in self._tasks.values():
                if low in (t.get("title") or "").lower():
                    return dict(t)
        return None

    def list_tasks(
        self, status: str = "", limit: int = 50, created_by: str = ""
    ) -> List[Dict[str, Any]]:
        self._ensure_loaded()
        with self._lock:
            items = list(self._tasks.values())
        if status:
            if status == "active":
                items = [t for t in items if t.get("status") in ACTIVE_STATES]
            else:
                items = [t for t in items if t.get("status") == status]
        if created_by:
            items = [t for t in items if t.get("created_by") == created_by]
        items.sort(key=lambda t: t.get("created_at", ""), reverse=True)
        return [dict(t) for t in items[:limit]] if limit else [dict(t) for t in items]

    def get_stats(self) -> Dict[str, int]:
        self._ensure_loaded()
        with self._lock:
            items = list(self._tasks.values())
        stats = {s: 0 for s in ALL_STATES}
        for t in items:
            st = t.get("status")
            if st in stats:
                stats[st] += 1
        stats["total"] = len(items)
        stats["active"] = sum(1 for t in items if t.get("status") in ACTIVE_STATES)
        return stats

    # ── Create ───────────────────────────────────────────────────

    def create_task(
        self,
        goal: str,
        title: str = "",
        created_by: str = "user",
        origin: Optional[Dict] = None,
        assignee_type: str = "agent",
        assignee_id: str = "",
        assignee_name: str = "",
        skill_name: str = "",
        approval_required: Optional[bool] = None,
        priority: int = 0,
    ) -> Dict[str, Any]:
        """Create a task. Tasks created by the AI always require human approval
        unless the `codex_brain_auto_approve` setting says otherwise."""
        self._ensure_loaded()
        goal = (goal or "").strip()
        if not goal:
            raise ValueError("goal is required")

        is_brain = created_by in ("brain", "telegram_brain")
        if approval_required is None:
            # Auto-approve is an explicit, user-set policy: when it is on, work
            # queued from chat starts without a second confirmation click.
            approval_required = not _brain_auto_approve()
        if is_brain and not _brain_auto_approve():
            # The AI can propose, never self-approve.
            approval_required = True

        skill_ref = {}
        if skill_name:
            skill_ref = _resolve_skill_ref(skill_name)

        if assignee_id and not assignee_name:
            assignee_name = _lookup_assignee_name(assignee_type, assignee_id)
        elif assignee_name and not assignee_id:
            assignee_id, assignee_name = _lookup_assignee_id(assignee_type, assignee_name)

        with self._lock:
            task = CodexTask(
                goal=goal,
                title=title,
                seq=self._next_seq(),
                created_by=created_by,
                origin=origin or {},
                assignee_type=assignee_type or "agent",
                assignee_id=assignee_id,
                assignee_name=assignee_name,
                skill_ref=skill_ref,
                priority=priority,
                status=PENDING_APPROVAL if approval_required else QUEUED,
            )
            task.approval["required"] = bool(approval_required)
            if not approval_required:
                task.approval.update({"decided_by": created_by, "decided_at": _now()})
            data = task.to_dict()
            self._tasks[task.id] = data
            self._save()

        self.append_event(
            task.id, "created",
            f"Task created by {created_by}: {task.title}",
            actor=created_by,
            data={"goal": goal, "assignee_type": assignee_type, "assignee_id": assignee_id},
        )
        if approval_required:
            self.append_event(task.id, "state", f"→ {PENDING_APPROVAL}", actor=created_by)
            self.notify(
                data,
                _t("codex.notify_pending", seq=task.seq,
                   title=_md(task.title), goal=_md(goal[:400])),
            )
        else:
            self.append_event(task.id, "state", f"→ {QUEUED}", actor=created_by)
        return data

    # ── State machine ────────────────────────────────────────────

    def _transition(
        self,
        task_id: str,
        new_status: str,
        actor: str,
        message: str = "",
        updates: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """Validate + apply a state change. Returns the updated task dict.

        Raises ValueError when the transition is not allowed.
        """
        self._ensure_loaded()
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                raise ValueError(f"Task not found: {task_id}")
            old = task.get("status")
            if new_status != old and new_status not in TRANSITIONS.get(old, set()):
                raise ValueError(
                    f"Illegal transition {old} → {new_status} (task #{task.get('seq')})"
                )
            task["status"] = new_status
            task["updated_at"] = _now()
            if updates:
                task.update(updates)
            self._save()
            snapshot = dict(task)

        self.append_event(
            task_id, "state", message or f"{old} → {new_status}", actor=actor,
            data={"from": old, "to": new_status},
        )
        if new_status in (DONE, REJECTED, CANCELLED, FAILED):
            self._prune_events(task_id)
        return snapshot

    def approve(self, task_id: str, actor: str = "user", note: str = "") -> Dict[str, Any]:
        task = self.get_task(task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")
        if actor.startswith("brain") and not _brain_auto_approve():
            raise ValueError("The AI is not allowed to approve its own tasks")
        approval = dict(task.get("approval") or {})
        approval.update({"decided_by": actor, "decided_at": _now(), "note": note})
        updated = self._transition(
            task_id, QUEUED, actor,
            message=f"Approved by {actor}" + (f": {note}" if note else ""),
            updates={"approval": approval, "error": ""},
        )
        self.append_event(task_id, "approval", f"✅ Approved by {actor}", actor=actor)
        return updated

    def reject(self, task_id: str, actor: str = "user", note: str = "") -> Dict[str, Any]:
        task = self.get_task(task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")
        approval = dict(task.get("approval") or {})
        approval.update({"decided_by": actor, "decided_at": _now(), "note": note})
        updated = self._transition(
            task_id, REJECTED, actor,
            message=f"Rejected by {actor}" + (f": {note}" if note else ""),
            updates={"approval": approval, "finished_at": _now()},
        )
        self.append_event(task_id, "approval", f"🚫 Rejected by {actor}", actor=actor)
        return updated

    def cancel(self, task_id: str, actor: str = "user") -> Dict[str, Any]:
        task = self.get_task(task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")
        if task.get("status") == RUNNING:
            # The worker checks this flag between steps.
            self._cancel_requested.add(task_id)
        return self._transition(
            task_id, CANCELLED, actor,
            message=f"Cancelled by {actor}",
            updates={"finished_at": _now()},
        )

    def retry(self, task_id: str, actor: str = "user") -> Dict[str, Any]:
        task = self.get_task(task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")
        self._cancel_requested.discard(task_id)
        return self._transition(
            task_id, QUEUED, actor,
            message=f"Retry requested by {actor}",
            updates={
                "error": "",
                "steps": [],
                "started_at": "",
                "finished_at": "",
                "retry_count": int(task.get("retry_count") or 0) + 1,
            },
        )

    def complete_review(
        self, task_id: str, accepted: bool, actor: str = "user", feedback: str = ""
    ) -> Dict[str, Any]:
        task = self.get_task(task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")
        if accepted:
            return self._transition(
                task_id, DONE, actor,
                message=f"Result accepted by {actor}",
                updates={"finished_at": _now()},
            )
        # Rework: append the feedback to the goal and re-queue. This text is an
        # instruction to the agent, so it stays English like the event messages
        # around it — the reviewer's own words are carried through verbatim.
        goal = task.get("goal", "")
        if feedback:
            goal = f"{goal}\n\n[Feedback from {actor}]: {feedback}"
        self.append_event(
            task_id, "log", f"🔁 Changes requested by {actor}: {feedback}", actor=actor
        )
        return self._transition(
            task_id, QUEUED, actor,
            message=f"Changes requested by {actor}",
            updates={"goal": goal, "steps": [], "error": "", "started_at": "", "finished_at": ""},
        )

    def update_task(self, task_id: str, **updates) -> Optional[Dict[str, Any]]:
        """Edit metadata of a task that has not started yet."""
        self._ensure_loaded()
        editable = {
            "title", "goal", "priority", "assignee_type", "assignee_id",
            "assignee_name", "max_retries",
        }
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            if task.get("status") not in (PENDING_APPROVAL, QUEUED, REJECTED):
                raise ValueError("Only tasks that have not started can be edited")
            for k, v in updates.items():
                if k in editable and v is not None:
                    task[k] = v
            task["updated_at"] = _now()
            self._save()
            return dict(task)

    # ── Worker-facing ────────────────────────────────────────────

    def claim_next(self) -> Optional[Dict[str, Any]]:
        """Atomically move the highest-priority queued task to running."""
        self._ensure_loaded()
        with self._lock:
            candidates = [t for t in self._tasks.values() if t.get("status") == QUEUED]
            if not candidates:
                return None
            candidates.sort(
                key=lambda t: (-int(t.get("priority") or 0), t.get("created_at", ""))
            )
            chosen = candidates[0]
            chosen["status"] = RUNNING
            chosen["started_at"] = _now()
            chosen["updated_at"] = chosen["started_at"]
            self._save()
            snapshot = dict(chosen)
        self._cancel_requested.discard(snapshot["id"])
        self.append_event(
            snapshot["id"], "state", f"{QUEUED} → {RUNNING}", actor="worker",
            data={"from": QUEUED, "to": RUNNING},
        )
        self.notify(snapshot, _t("codex.notify_started", seq=snapshot["seq"],
                                 title=_md(snapshot["title"])))
        return snapshot

    def report_step(
        self, task_id: str, name: str, status: str, message: str = "",
        label: str = "", progress: Optional[float] = None,
    ):
        """Upsert a step on the task and mirror it into the event log.

        `progress` is 0-100 for long-running work (a download, an encode) so the
        board can draw a bar instead of an indeterminate spinner. Progress-only
        updates are frequent, so they do NOT write an event — that would flood
        the log with hundreds of lines per download.
        """
        self._ensure_loaded()
        pct = None
        if progress is not None:
            try:
                pct = max(0.0, min(100.0, round(float(progress), 1)))
            except (TypeError, ValueError):
                pct = None

        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            steps = task.setdefault("steps", [])
            existing = next((s for s in steps if s.get("name") == name), None)
            if existing is None:
                existing = {
                    "name": name,
                    "label": label or name,
                    "status": status,
                    "message": message,
                    "progress": pct,
                    "started_at": _now(),
                    "ended_at": "",
                }
                steps.append(existing)
                is_new = True
            else:
                is_new = existing.get("status") != status
                existing["status"] = status
                if message:
                    existing["message"] = message
                if label:
                    existing["label"] = label
                if pct is not None:
                    existing["progress"] = pct
            if status in (STEP_SUCCESS, STEP_ERROR, STEP_SKIPPED):
                existing["ended_at"] = _now()
                existing["progress"] = 100.0 if status == STEP_SUCCESS else existing.get("progress")
            task["updated_at"] = _now()
            self._save()

        # Only log real transitions, not every percent tick.
        if is_new:
            self.append_event(
                task_id, "step", message or f"{name}: {status}", actor="worker",
                data={"step": name, "status": status, "progress": pct},
            )

    def report_result(self, task_id: str, result: str) -> Dict[str, Any]:
        task = self.get_task(task_id)
        seq = task.get("seq") if task else "?"
        updated = self._transition(
            task_id, REVIEW, "worker",
            message="Execution finished — awaiting review",
            updates={"result": result, "finished_at": _now(), "error": ""},
        )
        self.append_event(task_id, "result", (result or "")[:2000], actor="worker")
        preview = (result or "").strip()
        if len(preview) > 600:
            preview = preview[:600] + "…"
        self.notify(
            updated,
            _t("codex.notify_done", seq=seq,
               title=_md(updated.get("title", "")), preview=_md(preview)),
        )
        return updated

    def report_failure(self, task_id: str, error: str) -> Dict[str, Any]:
        task = self.get_task(task_id)
        seq = task.get("seq") if task else "?"
        updated = self._transition(
            task_id, FAILED, "worker",
            message=f"Execution failed: {error[:200]}",
            updates={"error": error, "finished_at": _now()},
        )
        self.append_event(task_id, "error", error[:2000], actor="worker")
        self.notify(
            updated,
            _t("codex.notify_failed", seq=seq,
               title=_md(updated.get("title", "")), error=_md(error[:600])),
        )
        return updated

    def is_cancel_requested(self, task_id: str) -> bool:
        if task_id in self._cancel_requested:
            return True
        task = self.get_task(task_id)
        return bool(task and task.get("status") == CANCELLED)

    def recover_orphans(self) -> int:
        """Tasks left in `running` by a crash/restart cannot be resumed — fail
        them so they become visible and retryable. Returns how many were fixed."""
        self._ensure_loaded()
        with self._lock:
            orphans = [t["id"] for t in self._tasks.values() if t.get("status") == RUNNING]
        for task_id in orphans:
            try:
                self._transition(
                    task_id, FAILED, "system",
                    message="Orphaned by server restart",
                    updates={
                        "error": "Task was interrupted by a server restart.",
                        "finished_at": _now(),
                    },
                )
            except Exception as e:
                logger.error(f"[Codex] Failed to recover orphan {task_id}: {e}")
        if orphans:
            logger.info(f"[Codex] Recovered {len(orphans)} orphaned task(s) after restart")
        return len(orphans)

    # ── Planning (AI decomposition) ──────────────────────────────

    def plan_task(self, task_id: str) -> Dict[str, Any]:
        """Ask the brain to split the goal into steps. Synchronous — callers on
        the event loop must wrap this in asyncio.to_thread."""
        task = self.get_task(task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")

        from tubecli.core.agent import agent_manager
        from tubecli.core.brain import AgentBrain

        agents = agent_manager.get_all()
        if not agents:
            raise ValueError("No agents available to plan with")

        planner = agents[0]
        for a in agents:
            if (a.role or "") == "orchestrator":
                planner = a
                break

        roster = "\n".join(
            f"- {a.name} (id={a.id}, role={a.role or 'general'}, "
            f"specialties={', '.join(a.specialties or []) or 'general'})"
            for a in agents[:20]
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a task planner. Split the user's goal into 2-6 concrete, "
                    "ordered steps and assign each step to ONE agent from the roster.\n\n"
                    f"AGENT ROSTER:\n{roster}\n\n"
                    'Reply with ONLY a JSON array, no prose:\n'
                    '[{"step": 1, "description": "...", "agent_id": "...", "agent_name": "..."}]'
                ),
            },
            {"role": "user", "content": task["goal"]},
        ]
        raw = AgentBrain._call_llm(planner.to_dict(), messages, temperature=0.2)
        plan = _parse_plan(raw)
        if not plan:
            raise ValueError("The planner did not return a usable plan")

        with self._lock:
            stored = self._tasks.get(task_id)
            if stored is not None:
                stored["plan"] = plan
                stored["updated_at"] = _now()
                self._save()
                snapshot = dict(stored)
            else:
                snapshot = task
        self.append_event(
            task_id, "plan", f"AI produced a {len(plan)}-step plan",
            actor="brain", data={"plan": plan},
        )
        return snapshot


# ── Module helpers ───────────────────────────────────────────────────

def _md(text: str) -> str:
    """Neutralise Telegram Markdown control characters in interpolated text."""
    if not text:
        return ""
    for ch in ("*", "_", "`", "["):
        text = text.replace(ch, "")
    return text


AUTO_APPROVE_DEFAULT = True


def _brain_auto_approve() -> bool:
    """Whether work may skip the human approval gate.

    `codex_auto_approve` is the general switch, shown both in the board header
    and next to the chat composer; `codex_brain_auto_approve` is the older,
    brain-only key and still honoured.

    Defaults to ON: having to approve every routine download turned the gate
    into noise. Turn it off from either switch to get the review step back for
    everything, including work the AI queues on its own.
    """
    try:
        from tubecli.config import get_setting

        return bool(get_setting("codex_auto_approve", AUTO_APPROVE_DEFAULT)) or bool(
            get_setting("codex_brain_auto_approve", False)
        )
    except Exception:
        return AUTO_APPROVE_DEFAULT


def auto_approve_enabled() -> bool:
    """Public read of the auto-approve switch (used by the API and the board)."""
    return _brain_auto_approve()


def _parse_plan(raw: str) -> List[Dict[str, Any]]:
    """Extract a JSON array of steps from an LLM reply."""
    import re

    if not raw:
        return []
    # Strip the auto-failover banner the brain prepends (core/brain.py:989).
    raw = re.sub(r"^⚠️\s*\*?\[Auto-Failover[^\]]*\]\*?\s*", "", raw.strip())
    candidates = re.findall(r"```(?:json)?\s*(\[.*?\])\s*```", raw, re.DOTALL)
    candidates.append(raw)
    match = re.search(r"\[\s*\{.*\}\s*\]", raw, re.DOTALL)
    if match:
        candidates.insert(0, match.group(0))
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except Exception:
            continue
        if isinstance(data, list):
            steps = []
            for i, item in enumerate(data, start=1):
                if not isinstance(item, dict):
                    continue
                steps.append({
                    "step": int(item.get("step") or i),
                    "description": str(item.get("description") or item.get("task") or ""),
                    "agent_id": str(item.get("agent_id") or ""),
                    "agent_name": str(item.get("agent_name") or ""),
                })
            if steps:
                return steps
    return []


def _resolve_skill_ref(skill_name: str) -> Dict[str, str]:
    try:
        from tubecli.core.skill import skill_manager

        skill = skill_manager.get(skill_name) or skill_manager.find_by_name(skill_name)
        if skill:
            return {"skill_id": skill.id, "skill_name": skill.name}
    except Exception as e:
        logger.warning(f"[Codex] Could not resolve skill '{skill_name}': {e}")
    return {"skill_id": "", "skill_name": skill_name}


def _lookup_assignee_name(assignee_type: str, assignee_id: str) -> str:
    try:
        if assignee_type == "team":
            from tubecli.extensions.multi_agents.extension import orchestrator

            team = orchestrator.get_team(assignee_id)
            return team.name if team else ""
        from tubecli.core.agent import agent_manager

        agent = agent_manager.get(assignee_id)
        return agent.name if agent else ""
    except Exception:
        return ""


def _lookup_assignee_id(assignee_type: str, assignee_name: str):
    """Resolve a human-supplied assignee name to (id, canonical_name)."""
    try:
        if assignee_type == "team":
            from tubecli.extensions.multi_agents.extension import orchestrator

            team = orchestrator.find_team_by_name(assignee_name)
            if team:
                return team.id, team.name
            return "", assignee_name
        from tubecli.core.agent import agent_manager

        agent = agent_manager.find_by_name(assignee_name)
        if agent:
            return agent.id, agent.name
    except Exception:
        pass
    return "", assignee_name


# Module-level singleton — the DI convention of this codebase.
codex_manager = CodexManager()
