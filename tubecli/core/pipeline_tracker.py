"""
Pipeline Tracker — In-memory tracking for Telegram pipeline tasks.
Provides real-time visibility into Download → Subtitle → TTS → Burn → Upload flows.
"""
import time
import uuid
import threading
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class PipelineStep:
    """One step in a pipeline (e.g., 'download', 'extract', 'tts', 'burn', 'upload')."""
    name: str
    label: str          # Human-readable label (e.g., "📥 Tải video")
    status: str = "pending"   # pending, running, success, error, skipped
    message: str = ""         # Progress or error message
    started_at: float = 0
    finished_at: float = 0

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "label": self.label,
            "status": self.status,
            "message": self.message,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration": round(self.finished_at - self.started_at, 1) if self.finished_at and self.started_at else 0,
        }


@dataclass
class PipelineTask:
    """A full pipeline execution (tracks all steps)."""
    task_id: str
    pipeline_type: str       # "subtitle_pipeline", "reup_pipeline", etc.
    chat_id: int
    url: str
    original_message: str
    status: str = "running"   # running, success, error
    steps: List[PipelineStep] = field(default_factory=list)
    created_at: float = 0
    finished_at: float = 0
    result_summary: str = ""
    error_message: str = ""
    video_filename: str = ""

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "pipeline_type": self.pipeline_type,
            "chat_id": self.chat_id,
            "url": self.url[:100],
            "original_message": self.original_message[:200],
            "status": self.status,
            "steps": [s.to_dict() for s in self.steps],
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "duration": round(self.finished_at - self.created_at, 1) if self.finished_at and self.created_at else round(time.time() - self.created_at, 1) if self.created_at else 0,
            "result_summary": self.result_summary,
            "error_message": self.error_message,
            "video_filename": self.video_filename,
            "created_at_iso": datetime.fromtimestamp(self.created_at).isoformat() if self.created_at else "",
        }


class PipelineTracker:
    """Thread-safe pipeline task tracker with history."""

    MAX_HISTORY = 50  # Keep last N tasks

    def __init__(self):
        self._tasks: Dict[str, PipelineTask] = {}
        self._lock = threading.Lock()

    def create_task(
        self,
        pipeline_type: str,
        chat_id: int,
        url: str,
        original_message: str,
        step_names: List[tuple],  # [(name, label), ...]
    ) -> PipelineTask:
        """Create a new pipeline task with defined steps."""
        task_id = uuid.uuid4().hex[:12]
        steps = [PipelineStep(name=name, label=label) for name, label in step_names]

        task = PipelineTask(
            task_id=task_id,
            pipeline_type=pipeline_type,
            chat_id=chat_id,
            url=url,
            original_message=original_message,
            steps=steps,
            created_at=time.time(),
        )

        with self._lock:
            self._tasks[task_id] = task
            # Prune old tasks
            if len(self._tasks) > self.MAX_HISTORY:
                sorted_ids = sorted(
                    self._tasks.keys(),
                    key=lambda k: self._tasks[k].created_at
                )
                for old_id in sorted_ids[:len(self._tasks) - self.MAX_HISTORY]:
                    del self._tasks[old_id]

        return task

    def start_step(self, task_id: str, step_name: str, message: str = ""):
        """Mark a step as running."""
        task = self._tasks.get(task_id)
        if not task:
            return
        for step in task.steps:
            if step.name == step_name:
                step.status = "running"
                step.started_at = time.time()
                step.message = message
                break

    def complete_step(self, task_id: str, step_name: str, message: str = ""):
        """Mark a step as completed successfully."""
        task = self._tasks.get(task_id)
        if not task:
            return
        for step in task.steps:
            if step.name == step_name:
                step.status = "success"
                step.finished_at = time.time()
                step.message = message
                break

    def fail_step(self, task_id: str, step_name: str, error: str = ""):
        """Mark a step as failed."""
        task = self._tasks.get(task_id)
        if not task:
            return
        for step in task.steps:
            if step.name == step_name:
                step.status = "error"
                step.finished_at = time.time()
                step.message = error
                break

    def skip_step(self, task_id: str, step_name: str):
        """Mark a step as skipped."""
        task = self._tasks.get(task_id)
        if not task:
            return
        for step in task.steps:
            if step.name == step_name:
                step.status = "skipped"
                break

    def update_step_message(self, task_id: str, step_name: str, message: str):
        """Update progress message for a step."""
        task = self._tasks.get(task_id)
        if not task:
            return
        for step in task.steps:
            if step.name == step_name:
                step.message = message
                break

    def complete_task(self, task_id: str, summary: str = "", video_filename: str = ""):
        """Mark entire pipeline as completed."""
        task = self._tasks.get(task_id)
        if not task:
            return
        task.status = "success"
        task.finished_at = time.time()
        task.result_summary = summary
        if video_filename:
            task.video_filename = video_filename

    def fail_task(self, task_id: str, error: str = ""):
        """Mark entire pipeline as failed."""
        task = self._tasks.get(task_id)
        if not task:
            return
        task.status = "error"
        task.finished_at = time.time()
        task.error_message = error

    def get_task(self, task_id: str) -> Optional[dict]:
        """Get a single task by ID."""
        task = self._tasks.get(task_id)
        return task.to_dict() if task else None

    def list_tasks(self, limit: int = 20, status: str = None) -> List[dict]:
        """List recent tasks, optionally filtered by status."""
        with self._lock:
            tasks = list(self._tasks.values())

        if status:
            tasks = [t for t in tasks if t.status == status]

        tasks.sort(key=lambda t: t.created_at, reverse=True)
        return [t.to_dict() for t in tasks[:limit]]

    def get_stats(self) -> dict:
        """Get summary statistics."""
        with self._lock:
            tasks = list(self._tasks.values())

        running = sum(1 for t in tasks if t.status == "running")
        success = sum(1 for t in tasks if t.status == "success")
        error = sum(1 for t in tasks if t.status == "error")

        return {
            "total": len(tasks),
            "running": running,
            "success": success,
            "error": error,
        }


# Global singleton
pipeline_tracker = PipelineTracker()
