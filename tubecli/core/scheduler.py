"""
Scheduler — Background daemon for scheduled skill/workflow execution.
"""
import os
import threading
import time
import json
import random
import datetime
from typing import Dict, List, Callable, Optional
from pathlib import Path

from tubecli.config import DATA_DIR, ensure_data_dirs

# build: 91e9d895bce8017b6501422f

# ── Smart scheduling knobs ───────────────────────────────────────
# Max agent browser sessions the scheduler may have running at once.
MAX_CONCURRENT_AGENT_BROWSERS = int(os.environ.get("TUBECLI_MAX_SCHEDULED_BROWSERS", "2"))
# Max agents launched within a single scheduler tick (staggers launches).
MAX_LAUNCHES_PER_TICK = 1
# If a run is overdue by more than this, it was "missed" (app was closed /
# machine slept). Instead of firing immediately, spread it randomly.
MISSED_RUN_GRACE_SEC = 300
# Missed/startup runs get rescheduled randomly within this window (minutes).
MISSED_SPREAD_MIN, MISSED_SPREAD_MAX = 2, 20
# Short deferral when blocked by concurrency/tick limits (minutes).
DEFER_MIN, DEFER_MAX = 2, 6
# Wait this long after app startup before the first tick, so launching the
# app never immediately spawns browsers while the UI is still loading.
STARTUP_GRACE_SEC = int(os.environ.get("TUBECLI_SCHEDULER_STARTUP_GRACE", "60"))


class Scheduler:
    """Background scheduler that checks agent routines and triggers skills."""

    def __init__(self):
        self.history_file = DATA_DIR / "schedule_history.json"
        self._last_sweep_date = None
        self._thread: Optional[threading.Thread] = None
        self._stop_flag = threading.Event()
        self._runner_callback: Optional[Callable] = None
        self._agent_runner_callback: Optional[Callable] = None
        ensure_data_dirs()

    def set_agent_runner(self, callback: Callable):
        """Set callback function for triggering agent behavior."""
        self._agent_runner_callback = callback

    def set_runner(self, callback: Callable):
        """Set callback function for triggering skill execution."""
        self._runner_callback = callback

    def start(self, interval_sec: int = 60):
        """Start the scheduler daemon."""
        if self._thread and self._thread.is_alive():
            print("[Scheduler] Already running")
            return

        self._stop_flag.clear()
        self._thread = threading.Thread(target=self._loop, args=(interval_sec,), daemon=True)
        self._thread.start()
        print("[Scheduler] Started")

    def stop(self):
        """Stop the scheduler daemon."""
        self._stop_flag.set()
        if self._thread:
            self._thread.join(timeout=3)
        print("[Scheduler] Stopped")

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _loop(self, interval_sec: int):
        # Startup grace: give the app time to finish loading before any
        # scheduled agent can spawn a browser.
        for _ in range(STARTUP_GRACE_SEC):
            if self._stop_flag.is_set():
                return
            time.sleep(1)

        while not self._stop_flag.is_set():
            try:
                self._tick()
            except Exception as e:
                print(f"[Scheduler] Error: {e}")

            # Sleep in small chunks to respond to stop flag quickly
            for _ in range(interval_sec):
                if self._stop_flag.is_set():
                    break
                time.sleep(1)

    def _tick(self):
        """Check all scheduled skills and trigger if needed."""
        from tubecli.core.skill import skill_manager

        now = datetime.datetime.now()

        # Prune old run-log day files once a day. Doing it here rather than only
        # at startup matters: this server is meant to run for weeks under systemd
        # and would otherwise never sweep.
        if self._last_sweep_date != now.date():
            self._last_sweep_date = now.date()
            try:
                from tubecli.core import run_log
                run_log.sweep()
            except Exception as e:
                print(f"[Scheduler] run_log sweep failed: {e}")

        for skill in skill_manager.get_all():
            if not skill.schedule_enabled:
                continue
            if not skill.next_run:
                continue

            try:
                next_run = datetime.datetime.fromisoformat(skill.next_run)
                if now >= next_run:
                    print(f"[Scheduler] Triggering: {skill.name}")
                    if self._runner_callback:
                        self._runner_callback(skill.id)

                    skill.last_run = now.isoformat()
                    skill.next_run = self._calc_next_run(skill)
                    skill_manager._save()
                    self._log_history(skill.name, skill.id)
            except ValueError:
                pass

        # Check Agents
        from tubecli.core.agent import agent_manager

        launches_this_tick = 0

        for agent in agent_manager.get_all():
            if not getattr(agent, "schedule_enabled", False):
                continue

            runs_today = getattr(agent, "schedule_runs_today", 0)
            last_run = getattr(agent, "schedule_last_run", None)

            if last_run:
                try:
                    last_run_date = datetime.datetime.fromisoformat(last_run).date()
                    if last_run_date < now.date():
                        runs_today = 0
                        agent.schedule_runs_today = 0
                except ValueError:
                    pass

            next_run_str = getattr(agent, "schedule_next_run", None)
            should_run_now = False
            overdue_sec = 0.0
            # Deliberately NOT named next_run: the skill loop earlier in this same
            # function binds that name, so on a ValueError below this would silently
            # carry some unrelated skill's schedule into the agent's run record.
            agent_next_run = None

            if not next_run_str:
                # Never scheduled before (fresh agent or scheduling just enabled).
                # Do NOT fire immediately — assign a randomized first slot so a
                # fleet of new/reset agents doesn't stampede at app startup.
                first_slot = now + datetime.timedelta(minutes=random.randint(MISSED_SPREAD_MIN, MISSED_SPREAD_MAX))
                valid_next = self._calculate_next_schedule_time(agent, first_slot)
                agent.schedule_next_run = valid_next.isoformat()
                agent_manager._save()
                print(f"[Scheduler] Initialized schedule for Agent {agent.name}: first run at {agent.schedule_next_run}")
                continue
            else:
                try:
                    agent_next_run = datetime.datetime.fromisoformat(next_run_str)
                    if now >= agent_next_run:
                        should_run_now = True
                        overdue_sec = (now - agent_next_run).total_seconds()
                except ValueError:
                    should_run_now = True

            if should_run_now:
                # Missed run detection: the run time passed long ago (app was
                # closed or machine slept). Firing all missed agents at once
                # would open many browsers simultaneously and freeze the
                # machine — instead spread them randomly over the next minutes.
                if overdue_sec > MISSED_RUN_GRACE_SEC:
                    delay_min = random.randint(MISSED_SPREAD_MIN, MISSED_SPREAD_MAX)
                    valid_next = self._calculate_next_schedule_time(agent, now + datetime.timedelta(minutes=delay_min))
                    agent.schedule_next_run = valid_next.isoformat()
                    agent_manager._save()
                    print(f"[Scheduler] Agent {agent.name} missed its run by {int(overdue_sec // 60)} min "
                          f"(app was closed?). Rescheduled to {agent.schedule_next_run} to avoid a launch storm.")
                    continue

                # Check if we are allowed to run now
                day_name = now.strftime("%a").lower()
                active_days = getattr(agent, "schedule_active_days", []) or ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
                active_days = [d.lower() for d in active_days]

                start_time = getattr(agent, "schedule_start_time", "00:00")
                end_time = getattr(agent, "schedule_end_time", "23:59")
                current_time_str = now.strftime("%H:%M")
                max_runs = getattr(agent, "schedule_max_runs", 10)

                is_active_day = day_name in active_days
                is_inside_window = start_time <= current_time_str <= end_time
                is_not_maxed = runs_today < max_runs

                if is_active_day and is_inside_window and is_not_maxed:
                    # Stagger: at most MAX_LAUNCHES_PER_TICK browser launches
                    # per tick. Other due agents get a short random deferral —
                    # they stay inside their time window, just a bit later.
                    if launches_this_tick >= MAX_LAUNCHES_PER_TICK:
                        self._defer_agent(agent, now, reason="another agent already launched this tick")
                        self._log_skip(agent, "tick_limit",
                                       "Another agent already launched a browser in this tick.")
                        agent_manager._save()
                        continue

                    # Concurrency gate: don't pile browsers on top of each other.
                    running_count = self._count_running_agent_browsers()
                    if running_count >= MAX_CONCURRENT_AGENT_BROWSERS:
                        self._defer_agent(agent, now, reason=f"{running_count} browser session(s) already running")
                        self._log_skip(agent, "busy",
                                       f"{running_count} browser session(s) already running "
                                       f"(limit {MAX_CONCURRENT_AGENT_BROWSERS}).")
                        agent_manager._save()
                        continue

                    print(f"[Scheduler] Triggering Agent: {agent.name}")
                    # Minted here and written BEFORE the callback, so a crash inside
                    # the launch still leaves evidence that the run was attempted.
                    run_id = None
                    try:
                        from tubecli.core import run_log
                        run_id = run_log.new_run_id()
                        run_log.start(run_id, agent.id, getattr(agent, "name", ""),
                                      trigger="schedule",
                                      scheduled_for=(agent_next_run.isoformat()
                                                     if agent_next_run else None),
                                      overdue_sec=overdue_sec)
                    except Exception as e:
                        print(f"[Scheduler] run_log unavailable: {e}")

                    if self._agent_runner_callback:
                        self._agent_runner_callback(agent.id, run_id=run_id)
                    launches_this_tick += 1

                    agent.schedule_last_run = now.isoformat()
                    agent.schedule_runs_today = runs_today + 1

                    # Next run depends on repeat strategy (e.g. interval)
                    repeat = getattr(agent, "schedule_repeat", "daily") or "daily"
                    repeat_lower = repeat.lower()
                    if repeat_lower == "interval":
                        interval_min = getattr(agent, "schedule_interval", 60)
                        try:
                            interval_min = int(interval_min)
                        except Exception:
                            interval_min = 60
                    else:
                        interval_min = 60

                    # Humanize: add random jitter so runs land "within the
                    # window" rather than at rigid exact times.
                    jitter_min = random.randint(0, max(1, min(15, interval_min // 3)))
                    raw_next = now + datetime.timedelta(minutes=interval_min + jitter_min)

                    valid_next = self._calculate_next_schedule_time(agent, raw_next)
                    agent.schedule_next_run = valid_next.isoformat()
                    agent_manager._save()
                    self._log_history(f"Agent: {agent.name}", agent.id)
                else:
                    # We are due to run but not allowed now. Push to next valid slot.
                    valid_next = self._calculate_next_schedule_time(agent, now)
                    agent.schedule_next_run = valid_next.isoformat()
                    agent_manager._save()
                    print(f"[Scheduler] Advanced Agent {agent.name} schedule to {agent.schedule_next_run} because it was due but could not run now (Day active: {is_active_day}, Window active: {is_inside_window}, Not maxed: {is_not_maxed}).")
                    # Say WHICH rule blocked it. "It was due but didn't run" is the
                    # owner's most common question and the three causes need
                    # completely different fixes.
                    # English on purpose: this text goes to the run log, which is
                    # read alongside journalctl. The dashboard does not print it
                    # raw — it renders the `reason` code below in the user's own
                    # language, so the log stays uniform without the UI turning
                    # English. Keep the code and the text in step.
                    if not is_active_day:
                        reason, detail = "inactive_day", f"{day_name} is not one of the selected active days."
                    elif not is_inside_window:
                        reason, detail = "outside_window", f"Outside the {start_time}-{end_time} window (it was {current_time_str})."
                    else:
                        reason, detail = "daily_cap", f"Already ran {max_runs} time(s) today."
                    self._log_skip(agent, reason, detail)

    def _defer_agent(self, agent, now: datetime.datetime, reason: str = ""):
        """Push a due agent's run a few random minutes into the future
        (respecting its window/day settings) without executing it."""
        delay_min = random.randint(DEFER_MIN, DEFER_MAX)
        valid_next = self._calculate_next_schedule_time(agent, now + datetime.timedelta(minutes=delay_min))
        agent.schedule_next_run = valid_next.isoformat()
        print(f"[Scheduler] Deferred Agent {agent.name} by ~{delay_min} min ({reason}). Next attempt: {agent.schedule_next_run}")

    def _count_running_agent_browsers(self) -> int:
        """Count currently running scheduled browser sessions. Returns 0 if the
        browser extension is unavailable so scheduling never hard-blocks."""
        try:
            from tubecli.extensions.browser.process_manager import browser_process_manager
            return len(browser_process_manager.list_running())
        except Exception:
            return 0

    def _log_skip(self, agent, reason: str, detail: str) -> None:
        """Record why an agent that was due did not run.

        Best effort by design — the run log must never be able to break a tick.
        """
        try:
            from tubecli.core import run_log
            run_log.skip(agent.id, getattr(agent, "name", ""), reason, detail,
                         next_attempt=getattr(agent, "schedule_next_run", None))
        except Exception as e:
            print(f"[Scheduler] Could not record skip: {e}")

    def _calculate_next_schedule_time(self, agent, start_from: datetime.datetime) -> datetime.datetime:
        active_days = getattr(agent, "schedule_active_days", []) or ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        active_days = [d.lower() for d in active_days]
        if not active_days:
            active_days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
            
        start_time_str = getattr(agent, "schedule_start_time", "08:00")
        end_time_str = getattr(agent, "schedule_end_time", "22:00")
        
        try:
            sh, sm = map(int, start_time_str.split(":"))
        except Exception:
            sh, sm = 8, 0
        try:
            eh, em = map(int, end_time_str.split(":"))
        except Exception:
            eh, em = 22, 0

        dt = start_from
        runs_today = getattr(agent, "schedule_runs_today", 0)
        max_runs = getattr(agent, "schedule_max_runs", 10)

        for _ in range(15):  # check up to 15 days in future
            day_name = dt.strftime("%a").lower()
            if day_name not in active_days:
                dt = (dt + datetime.timedelta(days=1)).replace(hour=sh, minute=sm, second=0, microsecond=0)
                continue
                
            today_start = dt.replace(hour=sh, minute=sm, second=0, microsecond=0)
            today_end = dt.replace(hour=eh, minute=em, second=0, microsecond=0)
            
            if dt < today_start:
                return today_start
            elif dt <= today_end:
                target_runs = runs_today if dt.date() == start_from.date() else 0
                if target_runs >= max_runs:
                    dt = (dt + datetime.timedelta(days=1)).replace(hour=sh, minute=sm, second=0, microsecond=0)
                    continue
                return dt
            else:
                dt = (dt + datetime.timedelta(days=1)).replace(hour=sh, minute=sm, second=0, microsecond=0)
                continue
                
        return start_from + datetime.timedelta(days=1)


    def _calc_next_run(self, skill) -> Optional[str]:
        """Calculate next run time."""
        now = datetime.datetime.now()
        if skill.schedule_type == "interval":
            return (now + datetime.timedelta(minutes=skill.schedule_interval_minutes)).isoformat()
        elif skill.schedule_type == "daily":
            try:
                h, m = map(int, skill.schedule_value.split(":"))
                target = now.replace(hour=h, minute=m, second=0, microsecond=0)
                if target <= now:
                    target += datetime.timedelta(days=1)
                return target.isoformat()
            except ValueError:
                return None
        return None

    def _log_history(self, name: str, skill_id: str):
        """Append to schedule history."""
        try:
            history = []
            if self.history_file.exists():
                history = json.loads(self.history_file.read_text(encoding="utf-8"))

            history.append({
                "timestamp": datetime.datetime.now().isoformat(),
                "skill_id": skill_id,
                "skill_name": name,
            })

            if len(history) > 500:
                history = history[-500:]

            self.history_file.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            print(f"[Scheduler] History error: {e}")


# Global singleton
scheduler = Scheduler()
