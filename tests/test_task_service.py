import tempfile
from datetime import timedelta
from pathlib import Path

import pytest

from app.core.runtime import AgentRunResult, PendingRunResult
from app.memory.repository import Database
from app.models.openai_compatible import ModelAuthError, ModelUnavailable
from app.tasks.models import TaskCreate, utc_now
from app.tasks.repository import TaskRepository
from app.tasks.service import TaskService


class StubRuntime:
    def __init__(self, outcome):
        self.outcome = outcome

    async def run(self, session_id, prompt):
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


async def due_task(repository, session_id, **overrides):
    values = {
        "name": "task",
        "prompt": "Do work",
        "schedule_type": "once",
        "run_at": utc_now() - timedelta(seconds=1),
        "session_id": session_id,
        "max_retries": 2,
    }
    values.update(overrides)
    created = await repository.create(TaskCreate(**values))
    return (await repository.claim_due(utc_now()))[0] | {"id": created["id"]}


@pytest.mark.asyncio
async def test_service_completes_successful_once_task():
    with tempfile.TemporaryDirectory() as directory:
        database = Database(Path(directory) / "tasks.db")
        await database.initialize()
        session = await database.create_session()
        repository = TaskRepository(database)
        task = await due_task(repository, session["id"])
        agent_run_id = await database.create_run(session["id"])
        runtime = StubRuntime(AgentRunResult(agent_run_id, "done", [], {}))
        await TaskService(repository, runtime).execute(task)
        saved = await repository.get(task["id"])
        assert saved["status"] == "completed"
        assert saved["runs"][0]["answer"] == "done"


@pytest.mark.asyncio
async def test_service_retries_temporary_failure_but_not_auth_failure():
    with tempfile.TemporaryDirectory() as directory:
        database = Database(Path(directory) / "tasks.db")
        await database.initialize()
        session = await database.create_session()
        repository = TaskRepository(database)
        retry = await due_task(repository, session["id"])
        await TaskService(repository, StubRuntime(ModelUnavailable("offline"))).execute(
            retry
        )
        saved = await repository.get(retry["id"])
        assert saved["status"] == "active"
        assert saved["retry_count"] == 1

        auth = await due_task(repository, session["id"], name="auth")
        await TaskService(repository, StubRuntime(ModelAuthError("bad key"))).execute(
            auth
        )
        saved = await repository.get(auth["id"])
        assert saved["status"] == "failed"
        assert saved["retry_count"] == 0


@pytest.mark.asyncio
async def test_service_waits_for_approval_then_completes():
    with tempfile.TemporaryDirectory() as directory:
        database = Database(Path(directory) / "tasks.db")
        await database.initialize()
        session = await database.create_session()
        repository = TaskRepository(database)
        task = await due_task(repository, session["id"])
        agent_run_id = await database.create_run(session["id"])
        pending = PendingRunResult(agent_run_id, "approval-1", "shell_run", {}, [])
        service = TaskService(repository, StubRuntime(pending))
        await service.execute(task)
        assert (await repository.get(task["id"]))["status"] == "waiting_approval"
        assert await service.complete_after_approval(
            AgentRunResult(agent_run_id, "approved", [], {})
        )
        saved = await repository.get(task["id"])
        assert saved["status"] == "completed"
        assert saved["runs"][0]["answer"] == "approved"
