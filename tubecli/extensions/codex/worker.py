"""
Codex worker — a single asyncio loop that drains the queued tasks.

Started from the router's startup event (routes.py) rather than from
Extension.on_enable(), because on_enable() re-fires on every discovery pass and
would spawn duplicate workers. The core Scheduler is not used either: both of
its callback slots are already claimed (api/server.py:566-588).
"""
import asyncio
import logging
from typing import Dict, Optional

from tubecli.extensions.codex.executor import TaskCancelled, execute_task
from tubecli.extensions.codex.manager import codex_manager

logger = logging.getLogger("Codex")

DEFAULT_CONCURRENCY = 2
IDLE_POLL_SEC = 3

# Error prefixes the brain/skill layers use to signal failure in a plain string.
_ERROR_MARKERS = ("❌", "Error:", "error:")


class CodexWorker:
    """Claims queued tasks and runs them, at most `concurrency` at a time."""

    def __init__(self, concurrency: int = DEFAULT_CONCURRENCY):
        self.concurrency = concurrency
        self._running = False
        self._loop_task: Optional[asyncio.Task] = None
        self._sem: Optional[asyncio.Semaphore] = None
        self._inflight: Dict[str, asyncio.Task] = {}

    # ── Lifecycle ────────────────────────────────────────────────

    def start(self):
        if self._running:
            return
        self._running = True
        self._sem = asyncio.Semaphore(self.concurrency)
        self._loop_task = asyncio.create_task(self._loop())
        logger.info(f"[Codex] Worker started (concurrency={self.concurrency})")

    def stop(self):
        self._running = False
        for task in list(self._inflight.values()):
            task.cancel()
        self._inflight.clear()
        if self._loop_task:
            self._loop_task.cancel()
            self._loop_task = None
        logger.info("[Codex] Worker stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    def status(self) -> Dict:
        return {
            "running": self._running,
            "concurrency": self.concurrency,
            "inflight": list(self._inflight.keys()),
        }

    # ── Main loop ────────────────────────────────────────────────

    async def _loop(self):
        # Anything left in `running` came from a crash/restart and cannot be
        # resumed — surface it as failed so the user can retry.
        try:
            codex_manager.recover_orphans()
        except Exception as e:
            logger.error(f"[Codex] Orphan recovery failed: {e}")

        while self._running:
            try:
                # Acquire the slot BEFORE claiming, so a task never sits in
                # `running` while waiting for a free worker.
                await self._sem.acquire()
                if not self._running:
                    self._sem.release()
                    break

                task = None
                try:
                    task = codex_manager.claim_next()
                except Exception as e:
                    logger.error(f"[Codex] claim_next failed: {e}")

                if not task:
                    self._sem.release()
                    await asyncio.sleep(IDLE_POLL_SEC)
                    continue

                runner = asyncio.create_task(self._run_one(task))
                self._inflight[task["id"]] = runner
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[Codex] Worker loop error: {e}")
                await asyncio.sleep(IDLE_POLL_SEC)

    async def _run_one(self, task: Dict):
        task_id = task["id"]
        try:
            def report(name: str, status: str, message: str = "", label: str = "",
                       progress=None):
                try:
                    codex_manager.report_step(
                        task_id, name, status, message, label, progress
                    )
                except Exception as e:
                    logger.error(f"[Codex] report_step failed: {e}")

            def is_cancelled() -> bool:
                return codex_manager.is_cancel_requested(task_id)

            result = await execute_task(task, report, is_cancelled)

            if is_cancelled():
                logger.info(f"[Codex] Task {task_id} was cancelled during execution")
                return

            text = (result or "").strip()
            if not text:
                codex_manager.report_failure(task_id, "The agent returned an empty result.")
            elif text.startswith(_ERROR_MARKERS):
                codex_manager.report_failure(task_id, text)
            else:
                codex_manager.report_result(task_id, text)

        except TaskCancelled:
            logger.info(f"[Codex] Task {task_id} cancelled")
        except asyncio.CancelledError:
            try:
                codex_manager.report_failure(task_id, "Task was cancelled by shutdown.")
            except Exception:
                pass
            raise
        except Exception as e:
            logger.error(f"[Codex] Task {task_id} failed: {e}", exc_info=True)
            try:
                codex_manager.report_failure(task_id, f"{type(e).__name__}: {e}")
            except Exception as inner:
                logger.error(f"[Codex] Could not record failure: {inner}")
        finally:
            self._inflight.pop(task_id, None)
            if self._sem:
                self._sem.release()


codex_worker = CodexWorker()
