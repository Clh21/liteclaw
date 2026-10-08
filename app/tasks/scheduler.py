import asyncio
from datetime import datetime, timezone

from app.logging import log_event
from app.tasks.repository import TaskRepository
from app.tasks.service import TaskService


class TaskScheduler:
    def __init__(
        self,
        repository: TaskRepository,
        service: TaskService,
        enabled: bool = True,
        poll_seconds: float = 1.0,
        max_concurrency: int = 2,
        shutdown_timeout: float = 15.0,
    ):
        self.repository = repository
        self.service = service
        self.enabled = enabled
        self.poll_seconds = poll_seconds
        self.shutdown_timeout = shutdown_timeout
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._claim_limit = max_concurrency
        self._stop = asyncio.Event()
        self._loop_task: asyncio.Task | None = None
        self._tick_lock = asyncio.Lock()
        self.active_count = 0
        self.last_tick_at: str | None = None

    @property
    def status(self) -> str:
        if not self.enabled:
            return "disabled"
        return "running" if self._loop_task and not self._loop_task.done() else "stopped"

    async def start(self) -> None:
        if not self.enabled or (self._loop_task and not self._loop_task.done()):
            return
        self._stop.clear()
        self._loop_task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._stop.set()
        if self._loop_task is None:
            return
        try:
            await asyncio.wait_for(self._loop_task, self.shutdown_timeout)
        except asyncio.TimeoutError:
            self._loop_task.cancel()
            await asyncio.gather(self._loop_task, return_exceptions=True)
        self._loop_task = None

    async def tick(self) -> None:
        async with self._tick_lock:
            self.last_tick_at = datetime.now(timezone.utc).isoformat()
            tasks = await self.repository.claim_due(
                datetime.now(timezone.utc), self._claim_limit
            )
            if tasks:
                await asyncio.gather(*(self._execute(task) for task in tasks))

    async def _execute(self, task: dict) -> None:
        async with self._semaphore:
            self.active_count += 1
            log_event("task.claimed", task_id=task["id"])
            try:
                await self.service.execute(task)
            finally:
                self.active_count -= 1

    async def _run_loop(self) -> None:
        while not self._stop.is_set():
            await self.tick()
            try:
                await asyncio.wait_for(self._stop.wait(), self.poll_seconds)
            except asyncio.TimeoutError:
                pass

    def health(self) -> dict:
        return {
            "status": self.status,
            "active_count": self.active_count,
            "last_tick_at": self.last_tick_at,
        }
