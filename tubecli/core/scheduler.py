"""
Scheduler — Background daemon for scheduled skill/workflow execution.
"""
import threading
import time
import json
import datetime
from typing import Dict, List, Callable, Optional
from pathlib import Path

from tubecli.config import DATA_DIR, ensure_data_dirs


class Scheduler:
    """Background scheduler that checks agent routines and triggers skills."""

    def __init__(self):
        self.history_file = DATA_DIR / "schedule_history.json"
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
            
            if not next_run_str:
                should_run_now = True
            else:
                try:
                    next_run = datetime.datetime.fromisoformat(next_run_str)
                    if now >= next_run:
                        should_run_now = True
                except ValueError:
                    should_run_now = True

            if should_run_now:
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
                    print(f"[Scheduler] Triggering Agent: {agent.name}")
                    if self._agent_runner_callback:
                        self._agent_runner_callback(agent.id)

                    agent.schedule_last_run = now.isoformat()
                    agent.schedule_runs_today = runs_today + 1
                    
                    # Next run depends on repeat strategy (e.g. interval)
                    repeat = getattr(agent, "schedule_repeat", "daily") or "daily"
                    repeat_lower = repeat.lower()
                    if repeat_lower == "daily":
                        raw_next = now + datetime.timedelta(minutes=60)
                    elif repeat_lower == "interval":
                        interval_min = getattr(agent, "schedule_interval", 60)
                        try:
                            interval_min = int(interval_min)
                        except Exception:
                            interval_min = 60
                        raw_next = now + datetime.timedelta(minutes=interval_min)
                    else:
                        raw_next = now + datetime.timedelta(minutes=60)

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
