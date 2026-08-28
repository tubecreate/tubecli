"""Durable record of what agent runs actually did.

The outcome of a run was already being computed and then thrown away. The
browser process manager's _monitor() thread waits on the process and works out
completed/error/timeout_killed with a return code and an end time — into an
in-memory dict that a restart wipes. The scheduler prints why it declined to run
an agent and keeps nothing. So the owner's questions — "did it run last night?",
"why didn't it run at 3am?", "is it broken or just idle?" — had no answer short
of reading a terminal that no longer exists.

This module is the missing disk. It is deliberately small and deliberately
best-effort: every public function swallows its own exceptions, because a
logging store that can break a scheduler tick is worse than no logging store.

Shape: one append-only JSONL file per local calendar day. Three line kinds share
a run_id and fold into one run at read time:

    start   the scheduler decided to run an agent (written BEFORE the launch, so
            a crash inside the launch still leaves evidence the run was tried)
    launch  the browser process was asked for, and what came back
    end     the process finished, and how

plus one standalone kind:

    skip    the scheduler declined — concurrency gate, tick cap, outside the
            time window, daily cap. No run_id; nothing follows it.

Why JSONL and not a mutable JSON document: a run needs a second write minutes
after the first, so a mutable index would mean read-parse-mutate-serialize-
replace the entire history on every event, with the whole file in flight each
time. An append costs one line and, if the process is killed mid-write, loses at
most that line.

Why not SQLite: no other core store here uses it, and the volume does not
warrant it — the workload is a handful of scheduled agents, tens of runs a day.
"""
import datetime
import json
import logging
import os
import re
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("RunLog")

# Keep whole day files this long. Fourteen days answers "did it run last week"
# without letting the directory grow without bound on a small VPS.
RETENTION_DAYS = 14
# Hard ceiling on the directory, enforced oldest-first. Today and yesterday are
# never deleted by this rule — a size sweep that eats the file currently being
# appended to would destroy the very run the owner is watching.
MAX_TOTAL_BYTES = 20 * 1024 * 1024
# Cap on any captured log excerpt.
LOG_TAIL_MAX = 2000
# A run with a start but no end for longer than this is presumed interrupted:
# long enough to cover the longest session plus model latency and grace.
RUN_MAX_WALL_SEC = 30 * 60

# One re-entrant lock for all writes. Three writers share this process — the
# FastAPI threadpool, the scheduler thread, and each browser monitor thread —
# and re-entrancy means a caller already holding it (a redactor that logs, say)
# cannot deadlock itself.
_LOCK = threading.RLock()

# ── Redaction ────────────────────────────────────────────────────────
#
# This is not optional hygiene. The launcher is invoked with --login-password on
# its argv when a profile has a saved login, open.js echoes its whole argv into
# the launcher log, and this module captures excerpts of that log. Without a
# redactor, adding run logging would convert a transient leak into a permanent
# one on disk, served over HTTP.
_SECRET_FLAGS = ("login-password", "login-email", "login-recovery", "login-2fa",
                 "password", "api-key", "apikey", "token", "secret")
_FLAG_RE = re.compile(
    r"(--(?:" + "|".join(re.escape(f) for f in _SECRET_FLAGS) + r"))"
    r"([=\s]+)(\"[^\"]*\"|'[^']*'|\S+)", re.IGNORECASE)
# open.js prints `RAW ARGV: [` then one quoted element per line, so the value of
# a secret flag sits on the line AFTER the flag and the single-line rule cannot
# see it. Detect that layout and drop the following value line too.
_ARGV_FLAG_LINE = re.compile(
    r"^\s*'?--(?:" + "|".join(re.escape(f) for f in _SECRET_FLAGS) + r")'?,?\s*$",
    re.IGNORECASE)


def redact(text: Optional[str]) -> Optional[str]:
    """Strip credentials from anything before it is stored or served."""
    if not text:
        return text
    try:
        out = []
        drop_next_value = False
        for line in str(text).splitlines():
            if drop_next_value:
                drop_next_value = False
                out.append("  '***',")
                continue
            if _ARGV_FLAG_LINE.match(line):
                drop_next_value = True
                out.append(line)
                continue
            out.append(_FLAG_RE.sub(r"\1\2***", line))
        return "\n".join(out)
    except Exception:
        # Never let the redactor's own failure result in raw text being stored.
        return "(redaction failed — content withheld)"


def _tail(text: Optional[str], limit: int = LOG_TAIL_MAX) -> Optional[str]:
    if not text:
        return None
    s = redact(str(text))
    return s[-limit:] if s and len(s) > limit else s


# ── Storage ──────────────────────────────────────────────────────────

def _dir() -> Path:
    from tubecli.config import ext_data_path
    return ext_data_path("agent_runs")


def _day_file(day: Optional[datetime.date] = None) -> Path:
    day = day or datetime.date.today()
    return _dir() / f"runs-{day.isoformat()}.jsonl"


def _now() -> str:
    # Local naive ISO, matching every other timestamp in this codebase
    # (process_manager instance records, scheduler history, schedule_next_run).
    # The dashboard compares these against the browser's own local clock.
    return datetime.datetime.now().isoformat()


def new_run_id() -> str:
    return "run-" + uuid.uuid4().hex[:12]


def _append(event: Dict[str, Any]) -> None:
    """Append one event. Best effort — never raises into a caller."""
    try:
        path = _day_file()
        with _LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Repair a torn tail before writing. If the process died mid-append
            # the file can end without a newline, and appending after that would
            # fuse the survivor of the old line onto the new one — corrupting
            # two records instead of one, the second being whatever we are
            # writing now (often the very row explaining the crash).
            with open(path, "a+", encoding="utf-8", newline="\n") as f:
                f.seek(0, os.SEEK_END)
                if f.tell() > 0:
                    f.seek(f.tell() - 1, os.SEEK_SET)
                    if f.read(1) != "\n":
                        f.write("\n")
                    f.seek(0, os.SEEK_END)
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning("run_log: could not append (%s)", e)


# ── Writers ──────────────────────────────────────────────────────────

def start(run_id: str, agent_id: str, agent_name: str, trigger: str = "schedule",
          scheduled_for: Optional[str] = None, overdue_sec: float = 0.0) -> None:
    """The scheduler decided to run this agent. Written before the launch."""
    _append({"kind": "start", "run_id": run_id, "ts": _now(),
             "agent_id": agent_id, "agent_name": agent_name,
             "trigger": trigger, "scheduled_for": scheduled_for,
             "overdue_sec": round(float(overdue_sec or 0), 1)})


def launch(run_id: str, agent_id: str, **fields: Any) -> None:
    """The browser was asked for, and this is what came back."""
    event = {"kind": "launch", "run_id": run_id, "ts": _now(), "agent_id": agent_id}
    for key in ("profile", "time_period", "behavior", "query", "session_minutes",
                "max_duration_sec", "spawn_status", "instance_id", "pid",
                "log_file", "ai_model"):
        if key in fields:
            event[key] = fields[key]
    if fields.get("prompt"):
        event["prompt"] = redact(str(fields["prompt"]))[:500]
    if fields.get("error"):
        event["error"] = redact(str(fields["error"]))[:500]
    if fields.get("log_tail"):
        event["log_tail"] = _tail(fields["log_tail"])
    _append(event)


def end(run_id: str, agent_id: str, outcome: str, return_code: Optional[int] = None,
        instance_id: Optional[str] = None, duration_sec: Optional[float] = None,
        log_tail: Optional[str] = None,
        warnings: Optional[List[str]] = None) -> None:
    """The process finished. outcome: completed | error | timeout_killed | failed.

    `warnings` is for a run that FINISHED yet should not read as clean — today
    that means ANTIDETECT_OFF, a session the browser opened with no fingerprint
    applied. Exit code 0 and a full History make it indistinguishable from a good
    run, which is exactly how the anti-detect could stay silently off for weeks.
    A warned run keeps its log_tail even when it completed, because the tail is
    the evidence.
    """
    event = {"kind": "end", "run_id": run_id, "ts": _now(), "agent_id": agent_id,
             "outcome": outcome, "return_code": return_code,
             "instance_id": instance_id}
    if duration_sec is not None:
        event["duration_sec"] = round(float(duration_sec), 1)
    warns = [str(w) for w in (warnings or []) if w]
    if warns:
        event["warnings"] = warns[:10]
    if (outcome != "completed" or warns) and log_tail:
        event["log_tail"] = _tail(log_tail)
    _append(event)


def skip(agent_id: str, agent_name: str, reason: str, detail: str = "",
         next_attempt: Optional[str] = None) -> None:
    """The scheduler declined to run. This is the answer to 'why didn't it run'."""
    _append({"kind": "skip", "run_id": None, "ts": _now(),
             "agent_id": agent_id, "agent_name": agent_name,
             "reason": reason, "detail": detail, "next_attempt": next_attempt})


# ── Reading ──────────────────────────────────────────────────────────

def _read_days(days: int) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    today = datetime.date.today()
    for back in range(max(1, days)):
        path = _day_file(today - datetime.timedelta(days=back))
        if not path.exists():
            continue
        try:
            # errors="replace" so one torn line cannot make the whole day
            # unreadable; the per-line json guard drops it on its own.
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except Exception:
                    continue
        except Exception as e:
            logger.warning("run_log: could not read %s (%s)", path.name, e)
    return events


def _age_sec(ts: Optional[str]) -> float:
    try:
        return (datetime.datetime.now() - datetime.datetime.fromisoformat(ts)).total_seconds()
    except Exception:
        return 0.0


def list_for_agent(agent_id: str, days: int = 14, limit: int = 100) -> List[Dict[str, Any]]:
    """Fold the event stream into run records for one agent, newest first.

    Read-time folding, rather than a repair pass that mutates the log: a run
    whose process is gone leaves no writer behind to close it, so an unterminated
    run is resolved by looking at how old it is. That keeps the store append-only
    and means a crash needs no recovery step at all.
    """
    try:
        runs: Dict[str, Dict[str, Any]] = {}
        skips: List[Dict[str, Any]] = []

        for e in _read_days(days):
            if e.get("agent_id") != agent_id:
                continue
            kind = e.get("kind")
            if kind == "skip":
                skips.append({"type": "skip", "ts": e.get("ts"),
                              "reason": e.get("reason"), "detail": e.get("detail"),
                              "next_attempt": e.get("next_attempt")})
                continue
            rid = e.get("run_id")
            if not rid:
                continue
            run = runs.setdefault(rid, {"type": "run", "run_id": rid})
            if kind == "start":
                run.update({"ts": e.get("ts"), "trigger": e.get("trigger"),
                            "scheduled_for": e.get("scheduled_for"),
                            "overdue_sec": e.get("overdue_sec"),
                            "agent_name": e.get("agent_name")})
            elif kind == "launch":
                run["launch"] = e
            elif kind == "end":
                run["end"] = e

        out: List[Dict[str, Any]] = []
        for run in runs.values():
            launched = run.get("launch") or {}
            ended = run.get("end") or {}
            if ended:
                run["outcome"] = ended.get("outcome")
                run["return_code"] = ended.get("return_code")
                run["duration_sec"] = ended.get("duration_sec")
                run["log_tail"] = ended.get("log_tail")
                # Lượt chạy xong mà vẫn có cảnh báo (ANTIDETECT_OFF) phải nhìn thấy
                # được ở tầng đọc, không thì nó lẫn hẳn vào các lượt sạch.
                if ended.get("warnings"):
                    run["warnings"] = ended.get("warnings")
            elif launched.get("spawn_status") == "error":
                run["outcome"] = "launch_failed"
                run["error"] = launched.get("error")
                run["log_tail"] = launched.get("log_tail")
            elif not launched:
                # Never got as far as asking for a browser.
                run["outcome"] = ("never_started"
                                  if _age_sec(run.get("ts")) > RUN_MAX_WALL_SEC
                                  else "starting")
            else:
                budget = (launched.get("max_duration_sec") or 0) + 120
                age = _age_sec(launched.get("ts"))
                run["outcome"] = "interrupted" if age > max(budget, RUN_MAX_WALL_SEC) else "running"
            run["profile"] = launched.get("profile")
            run["query"] = launched.get("query")
            run["instance_id"] = launched.get("instance_id")
            out.append(run)

        out.extend(skips)
        out.sort(key=lambda r: r.get("ts") or "", reverse=True)
        return out[:limit]
    except Exception as e:
        logger.warning("run_log: could not build run list (%s)", e)
        return []


# ── Retention ────────────────────────────────────────────────────────

def sweep() -> None:
    """Drop day files past the retention window, then past the size ceiling."""
    try:
        d = _dir()
        if not d.exists():
            return
        today = datetime.date.today()
        keep_names = {_day_file(today).name,
                      _day_file(today - datetime.timedelta(days=1)).name}
        files = sorted(d.glob("runs-*.jsonl"))

        cutoff = today - datetime.timedelta(days=RETENTION_DAYS)
        survivors = []
        for f in files:
            try:
                day = datetime.date.fromisoformat(f.stem.replace("runs-", ""))
            except Exception:
                continue
            if day < cutoff and f.name not in keep_names:
                # Unlink outside the append lock is fine: these are old files no
                # writer touches. On Windows an open reader would block the
                # unlink, so a failure here is ignored and retried next sweep.
                try:
                    f.unlink()
                except OSError:
                    pass
            else:
                survivors.append(f)

        total = sum(f.stat().st_size for f in survivors if f.exists())
        for f in survivors:
            if total <= MAX_TOTAL_BYTES:
                break
            if f.name in keep_names:
                # Refuse to delete the file being written to. If the ceiling is
                # still exceeded after everything else is gone, say so rather
                # than destroying the current day.
                logger.warning("run_log: over %d bytes but only current files remain",
                               MAX_TOTAL_BYTES)
                break
            try:
                size = f.stat().st_size
                f.unlink()
                total -= size
            except OSError:
                pass
    except Exception as e:
        logger.warning("run_log: sweep failed (%s)", e)
