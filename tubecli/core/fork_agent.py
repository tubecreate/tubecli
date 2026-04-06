"""
Fork Sub-Agent — Parallel task execution for complex multi-step pipelines.
Inspired by claw-code-main's forkSubagent pattern.

Key concept: When a task has independent sub-steps, run them concurrently
instead of sequentially. Each sub-task runs in its own "forked" context.

Example:
    "Tải video douyin này, optimize tiêu đề, upload lên YouTube"
    
    Sequential (old): Download → AI Title → Upload = 30s total
    Parallel (new):   Download + AI Title → Upload = 20s total
"""
import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Dict, List, Optional
from enum import Enum


class SubTaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class SubTaskResult:
    """Result of a single sub-task execution."""
    task_name: str
    status: SubTaskStatus
    result: Any = None
    error: str = ""
    duration_ms: int = 0


@dataclass
class ForkResult:
    """Aggregated result from all forked sub-tasks."""
    subtasks: List[SubTaskResult] = field(default_factory=list)
    total_duration_ms: int = 0

    @property
    def all_success(self) -> bool:
        return all(t.status == SubTaskStatus.COMPLETED for t in self.subtasks)

    @property
    def any_failed(self) -> bool:
        return any(t.status == SubTaskStatus.FAILED for t in self.subtasks)

    def get(self, task_name: str) -> Optional[SubTaskResult]:
        """Get result by task name."""
        for t in self.subtasks:
            if t.task_name == task_name:
                return t
        return None

    def summary(self) -> str:
        lines = [f"Fork Result ({len(self.subtasks)} tasks, {self.total_duration_ms}ms):"]
        for t in self.subtasks:
            icon = "✅" if t.status == SubTaskStatus.COMPLETED else "❌"
            lines.append(f"  {icon} {t.task_name}: {t.status.value} ({t.duration_ms}ms)")
            if t.error:
                lines.append(f"     Error: {t.error[:100]}")
        return "\n".join(lines)


class SubAgentFork:
    """
    Fork manager for parallel sub-task execution.
    
    Usage:
        fork = SubAgentFork()
        fork.add("download", download_video(url))
        fork.add("ai_title", generate_title(text))
        result = await fork.run()
        
        video = result.get("download").result
        title = result.get("ai_title").result
    """

    def __init__(self, timeout: int = 120):
        self.tasks: List[tuple] = []  # (name, coroutine)
        self.timeout = timeout

    def add(self, name: str, coro: Coroutine):
        """Add a sub-task to the fork."""
        self.tasks.append((name, coro))

    async def run(self) -> ForkResult:
        """Execute all sub-tasks concurrently and collect results."""
        start = time.monotonic()
        fork_result = ForkResult()

        if not self.tasks:
            return fork_result

        # Wrap each task with timing and error handling
        async def _run_subtask(name: str, coro: Coroutine) -> SubTaskResult:
            t0 = time.monotonic()
            try:
                result = await asyncio.wait_for(coro, timeout=self.timeout)
                return SubTaskResult(
                    task_name=name,
                    status=SubTaskStatus.COMPLETED,
                    result=result,
                    duration_ms=int((time.monotonic() - t0) * 1000),
                )
            except asyncio.TimeoutError:
                return SubTaskResult(
                    task_name=name,
                    status=SubTaskStatus.FAILED,
                    error=f"Timeout after {self.timeout}s",
                    duration_ms=int((time.monotonic() - t0) * 1000),
                )
            except asyncio.CancelledError:
                return SubTaskResult(
                    task_name=name,
                    status=SubTaskStatus.CANCELLED,
                    duration_ms=int((time.monotonic() - t0) * 1000),
                )
            except Exception as e:
                return SubTaskResult(
                    task_name=name,
                    status=SubTaskStatus.FAILED,
                    error=str(e),
                    duration_ms=int((time.monotonic() - t0) * 1000),
                )

        # Run all in parallel
        coros = [_run_subtask(name, coro) for name, coro in self.tasks]
        subtask_results = await asyncio.gather(*coros, return_exceptions=False)

        fork_result.subtasks = list(subtask_results)
        fork_result.total_duration_ms = int((time.monotonic() - start) * 1000)

        print(f"[Fork] {fork_result.summary()}")
        return fork_result


# ═══════════════════════════════════════════════════════════════
#  PRE-BUILT FORK PATTERNS
# ═══════════════════════════════════════════════════════════════

async def fork_download_and_title(
    video_url: str,
    user_text: str,
    agent_dict: Dict,
) -> ForkResult:
    """
    Fork Pattern: Download video + Generate AI title in parallel.
    
    Before (sequential): 15s download + 5s title = 20s
    After (parallel):    max(15s, 5s) = 15s (25% faster)
    """
    from tubecli.core.telegram_actions import execute_download

    async def _generate_title():
        from tubecli.core.brain import AgentBrain
        
        prompt = f"""Bạn là chuyên gia viết tiêu đề YouTube Shorts viral.
Yêu cầu người dùng: "{user_text}"

Nhiệm vụ:
1. Nếu trong yêu cầu CÓ chỉ định tiêu đề → dùng nội dung đó.
2. Nếu không, sáng tạo tiêu đề thu hút + Emoji + 3-5 Hashtag.
3. TRẢ VỀ DUY NHẤT dòng tiêu đề. Không giải thích."""

        try:
            title = AgentBrain._call_llm(
                agent_dict,
                [{"role": "user", "content": prompt}],
                temperature=0.7,
            )
            if title and "[Error]" not in title:
                return title.strip().strip('"').strip("'")
        except Exception as e:
            print(f"[Fork] AI title error: {e}")
        return None

    fork = SubAgentFork(timeout=120)
    fork.add("download", execute_download(video_url, agent_dict))
    fork.add("ai_title", _generate_title())
    return await fork.run()


async def fork_multi_download(
    urls: List[str],
    agent_dict: Dict,
) -> ForkResult:
    """
    Fork Pattern: Download multiple videos in parallel.
    
    Before: 3 videos × 15s = 45s sequential
    After:  max(15s, 15s, 15s) = 15s parallel (3x faster)
    """
    from tubecli.core.telegram_actions import execute_download

    fork = SubAgentFork(timeout=180)
    for i, url in enumerate(urls):
        fork.add(f"download_{i}", execute_download(url, agent_dict))
    return await fork.run()


async def fork_specialist_tasks(
    tasks: List[Dict],
    agent_dict: Dict,
) -> ForkResult:
    """
    Fork Pattern: Run multiple specialist tasks in parallel.
    
    Each task: {"name": "...", "agent_id": "...", "message": "...", "skills": [...]}
    """
    from tubecli.core.brain import AgentBrain
    from tubecli.core.agent import agent_manager

    async def _run_specialist(task: Dict):
        target_id = task.get("agent_id")
        message = task.get("message", "")
        skills = task.get("skills", [])

        target = agent_manager.get(target_id)
        if not target:
            return f"Agent {target_id} not found"

        target_dict = target.to_dict()
        result = AgentBrain.chat_targeted(
            message=message,
            agent=target_dict,
            skills=skills,
            intent_hint="team_delegate",
        )
        return result.get("reply", "No response")

    fork = SubAgentFork(timeout=90)
    for task in tasks:
        fork.add(task.get("name", "task"), _run_specialist(task))
    return await fork.run()
