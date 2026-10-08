from datetime import datetime, timedelta

from app.core.runtime import AgentRunResult, PendingRunResult
from app.logging import log_event
from app.models.openai_compatible import ModelAuthError, ModelUnavailable
from app.tasks.models import next_interval_time, utc_now
from app.tasks.repository import TaskRepository

RETRY_DELAYS = (5, 15, 30, 60, 120)


class TaskService:
    def __init__(self, repository: TaskRepository, runtime):
        self.repository = repository
        self.runtime = runtime

    async def execute(self, task: dict) -> None:
        attempt = task["retry_count"] + 1
        task_run = await self.repository.create_run(task["id"], attempt)
        try:
            result = await self.runtime.run(task["session_id"], task["prompt"])
        except (ModelAuthError, KeyError) as error:
            await self._fail(task, task_run, error, retryable=False)
            return
        except ModelUnavailable as error:
            await self._fail(task, task_run, error, retryable=True)
            return
        except Exception as error:  # noqa: BLE001 - scheduler records isolated task failures
            await self._fail(task, task_run, error, retryable=True)
            return
        if isinstance(result, PendingRunResult):
            await self.repository.update_run(
                task_run["id"], "waiting_approval", agent_run_id=result.run_id
            )
            await self.repository.set_task_state(
                task["id"], "waiting_approval", retry_count=task["retry_count"]
            )
            log_event(
                "task.waiting_approval",
                task_id=task["id"],
                task_run_id=task_run["id"],
                agent_run_id=result.run_id,
            )
            return
        await self._complete(task, task_run["id"], result)

    async def complete_after_approval(
        self, result: AgentRunResult | PendingRunResult
    ) -> bool:
        waiting = await self.repository.find_waiting_by_agent_run(result.run_id)
        if waiting is None:
            return False
        if isinstance(result, PendingRunResult):
            await self.repository.update_run(
                waiting["id"], "waiting_approval", agent_run_id=result.run_id
            )
            return True
        task = await self.repository.get(waiting["task_id"])
        await self._complete(task, waiting["id"], result)
        return True

    async def _complete(
        self, task: dict, task_run_id: str, result: AgentRunResult
    ) -> None:
        await self.repository.update_run(
            task_run_id,
            "completed",
            agent_run_id=result.run_id,
            answer=result.answer,
            finished=True,
        )
        current = await self.repository.get(task["id"])
        if current["pause_requested"]:
            await self.repository.set_task_state(task["id"], "paused")
        elif task["schedule_type"] == "interval":
            planned = datetime.fromisoformat(task["next_run_at"])
            next_run = next_interval_time(planned, task["interval_seconds"], utc_now())
            await self.repository.set_task_state(task["id"], "active", next_run)
        else:
            await self.repository.set_task_state(task["id"], "completed")
        log_event(
            "task.run_completed",
            task_id=task["id"],
            task_run_id=task_run_id,
            agent_run_id=result.run_id,
        )

    async def _fail(
        self, task: dict, task_run: dict, error: Exception, retryable: bool
    ) -> None:
        message = str(error)[:1000]
        await self.repository.update_run(
            task_run["id"], "failed", error=message, finished=True
        )
        current = await self.repository.get(task["id"])
        retries = task["retry_count"] + 1
        if current["pause_requested"]:
            await self.repository.set_task_state(
                task["id"],
                "paused",
                retry_count=task["retry_count"],
                last_error=message,
            )
        elif retryable and retries <= task["max_retries"]:
            delay = RETRY_DELAYS[min(retries - 1, len(RETRY_DELAYS) - 1)]
            await self.repository.set_task_state(
                task["id"],
                "active",
                utc_now() + timedelta(seconds=delay),
                retries,
                message,
            )
        elif task["schedule_type"] == "interval" and retryable:
            planned = datetime.fromisoformat(task["next_run_at"])
            next_run = next_interval_time(planned, task["interval_seconds"], utc_now())
            await self.repository.set_task_state(
                task["id"], "active", next_run, 0, message
            )
        else:
            await self.repository.set_task_state(
                task["id"],
                "failed",
                retry_count=task["retry_count"],
                last_error=message,
            )
        log_event(
            "task.run_failed",
            task_id=task["id"],
            task_run_id=task_run["id"],
            error=type(error).__name__,
        )
