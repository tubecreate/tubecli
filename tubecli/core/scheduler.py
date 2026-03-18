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
        ensure_data_dirs()

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
