import tempfile
from datetime import timedelta
from pathlib import Path

import pytest

from app.memory.repository import Database
from app.tasks.models import TaskCreate, utc_now
from app.tasks.repository import TaskRepository


@pytest.mark.asyncio
async def test_repository_creates_lists_and_claims_due_task_once():
    with tempfile.TemporaryDirectory() as directory:
        database = Database(Path(directory) / "tasks.db")
        await database.initialize()
        session = await database.create_session()
        repository = TaskRepository(database)
        task = await repository.create(
            TaskCreate(
                name="report",
                prompt="Write report",
                schedule_type="once",
                run_at=utc_now() - timedelta(seconds=1),
                session_id=session["id"],
            )
        )
        assert (await repository.list())[0]["id"] == task["id"]
        claimed = await repository.claim_due(utc_now())
        assert [item["id"] for item in claimed] == [task["id"]]
        assert await repository.claim_due(utc_now()) == []


@pytest.mark.asyncio
async def test_repository_pause_resume_and_delete_with_runs():
    with tempfile.TemporaryDirectory() as directory:
        database = Database(Path(directory) / "tasks.db")
        await database.initialize()
        session = await database.create_session()
        repository = TaskRepository(database)
        task = await repository.create(
            TaskCreate(
                name="poll",
                prompt="Check status",
                schedule_type="interval",
                interval_seconds=60,
                run_at=utc_now() + timedelta(minutes=1),
                session_id=session["id"],
            )
        )
        assert (await repository.pause(task["id"]))["status"] == "paused"
        assert await repository.pause(task["id"]) is None
        resumed = await repository.resume(task["id"], utc_now())
        assert resumed["status"] == "active"
        task_run = await repository.create_run(task["id"], attempt=1)
        assert (await repository.get(task["id"]))["runs"][0]["id"] == task_run["id"]
        assert await repository.delete(task["id"]) is True
        assert await repository.get(task["id"]) is None


@pytest.mark.asyncio
async def test_repository_recovers_expired_running_task():
    with tempfile.TemporaryDirectory() as directory:
        database = Database(Path(directory) / "tasks.db")
        await database.initialize()
        session = await database.create_session()
        repository = TaskRepository(database)
        task = await repository.create(
            TaskCreate(
                name="report",
                prompt="Write report",
                schedule_type="once",
                run_at=utc_now() - timedelta(minutes=10),
                session_id=session["id"],
            )
        )
        await repository.claim_due(utc_now() - timedelta(minutes=9))
        assert await repository.recover_expired(utc_now(), lease_seconds=300) == 1
        assert (await repository.get(task["id"]))["status"] == "active"


@pytest.mark.asyncio
async def test_pause_running_task_records_pause_request():
    with tempfile.TemporaryDirectory() as directory:
        database = Database(Path(directory) / "tasks.db")
        await database.initialize()
        session = await database.create_session()
        repository = TaskRepository(database)
        task = await repository.create(
            TaskCreate(
                name="running",
                prompt="work",
                schedule_type="once",
                run_at=utc_now() - timedelta(seconds=1),
                session_id=session["id"],
            )
        )
        await repository.claim_due(utc_now())
        paused = await repository.pause(task["id"])
        assert paused["status"] == "running"
        assert paused["pause_requested"] == 1
