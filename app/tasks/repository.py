from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.memory.repository import Database
from app.tasks.models import ScheduleType, TaskCreate, next_interval_time, utc_now


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


class TaskRepository:
    def __init__(self, database: Database):
        self.database = database

    async def create(self, request: TaskCreate) -> dict:
        now = utc_now()
        session_id = request.session_id
        if session_id is None:
            session_id = (await self.database.create_session(title=request.name))["id"]
        elif await self.database.get_session(session_id) is None:
            raise KeyError("session_not_found")
        first_run = request.run_at or now + timedelta(seconds=request.interval_seconds or 0)
        task = {
            "id": uuid4().hex,
            "name": request.name,
            "session_id": session_id,
            "prompt": request.prompt,
            "schedule_type": request.schedule_type.value,
            "run_at": _iso(request.run_at) if request.run_at else None,
            "interval_seconds": request.interval_seconds,
            "next_run_at": _iso(first_run),
            "status": "active",
            "max_retries": request.max_retries,
            "retry_count": 0,
            "claimed_at": None,
            "pause_requested": 0,
            "last_error": None,
            "created_at": _iso(now),
            "updated_at": _iso(now),
        }
        async with self.database.connection() as connection:
            await connection.execute(
                """INSERT INTO scheduled_tasks(
                id,name,session_id,prompt,schedule_type,run_at,interval_seconds,
                next_run_at,status,max_retries,retry_count,claimed_at,pause_requested,
                last_error,created_at,updated_at
                ) VALUES(:id,:name,:session_id,:prompt,:schedule_type,:run_at,
                :interval_seconds,:next_run_at,:status,:max_retries,:retry_count,
                :claimed_at,:pause_requested,:last_error,:created_at,:updated_at)""",
                task,
            )
            await connection.commit()
        return task

    async def list(
        self, status: str | None = None, limit: int = 100, offset: int = 0
    ) -> list[dict]:
        query = "SELECT * FROM scheduled_tasks"
        parameters: list[object] = []
        if status:
            query += " WHERE status=?"
            parameters.append(status)
        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        parameters.extend([limit, offset])
        async with self.database.connection() as connection:
            cursor = await connection.execute(query, parameters)
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get(self, task_id: str) -> dict | None:
        async with self.database.connection() as connection:
            cursor = await connection.execute(
                "SELECT * FROM scheduled_tasks WHERE id=?", (task_id,)
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            cursor = await connection.execute(
                "SELECT * FROM scheduled_task_runs WHERE task_id=? ORDER BY started_at DESC LIMIT 20",
                (task_id,),
            )
            runs = await cursor.fetchall()
        return {**dict(row), "runs": [dict(item) for item in runs]}

    async def claim_due(self, now: datetime, limit: int = 20) -> list[dict]:
        claimed = []
        timestamp = _iso(now)
        async with self.database.connection() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            cursor = await connection.execute(
                "SELECT * FROM scheduled_tasks WHERE status='active' AND next_run_at<=? ORDER BY next_run_at LIMIT ?",
                (timestamp, limit),
            )
            for row in await cursor.fetchall():
                result = await connection.execute(
                    "UPDATE scheduled_tasks SET status='running',claimed_at=?,updated_at=? WHERE id=? AND status='active'",
                    (timestamp, timestamp, row["id"]),
                )
                if result.rowcount == 1:
                    claimed.append({**dict(row), "status": "running", "claimed_at": timestamp})
            await connection.commit()
        return claimed

    async def pause(self, task_id: str) -> dict | None:
        now = _iso(utc_now())
        async with self.database.connection() as connection:
            cursor = await connection.execute(
                "UPDATE scheduled_tasks SET status='paused',updated_at=? WHERE id=? AND status='active' RETURNING *",
                (now, task_id),
            )
            row = await cursor.fetchone()
            if row is None:
                cursor = await connection.execute(
                    "UPDATE scheduled_tasks SET pause_requested=1,updated_at=? WHERE id=? AND status IN ('running','waiting_approval') RETURNING *",
                    (now, task_id),
                )
                row = await cursor.fetchone()
            await connection.commit()
        return dict(row) if row else None

    async def resume(self, task_id: str, now: datetime) -> dict | None:
        task = await self.get(task_id)
        if task is None or task["status"] != "paused":
            return None
        scheduled = datetime.fromisoformat(task["next_run_at"])
        if scheduled <= now and task["schedule_type"] == ScheduleType.interval.value:
            scheduled = next_interval_time(scheduled, task["interval_seconds"], now)
        elif scheduled <= now:
            scheduled = now
        async with self.database.connection() as connection:
            cursor = await connection.execute(
                "UPDATE scheduled_tasks SET status='active',pause_requested=0,next_run_at=?,updated_at=? WHERE id=? AND status='paused' RETURNING *",
                (_iso(scheduled), _iso(now), task_id),
            )
            row = await cursor.fetchone()
            await connection.commit()
        return dict(row) if row else None

    async def delete(self, task_id: str) -> bool:
        async with self.database.connection() as connection:
            cursor = await connection.execute(
                "DELETE FROM scheduled_tasks WHERE id=?", (task_id,)
            )
            await connection.commit()
        return cursor.rowcount == 1

    async def create_run(self, task_id: str, attempt: int) -> dict:
        task_run = {
            "id": uuid4().hex,
            "task_id": task_id,
            "agent_run_id": None,
            "status": "running",
            "attempt": attempt,
            "answer": None,
            "error": None,
            "started_at": _iso(utc_now()),
            "finished_at": None,
        }
        async with self.database.connection() as connection:
            await connection.execute(
                "INSERT INTO scheduled_task_runs(id,task_id,agent_run_id,status,attempt,answer,error,started_at,finished_at) VALUES(:id,:task_id,:agent_run_id,:status,:attempt,:answer,:error,:started_at,:finished_at)",
                task_run,
            )
            await connection.commit()
        return task_run

    async def recover_expired(self, now: datetime, lease_seconds: int) -> int:
        cutoff = _iso(now - timedelta(seconds=lease_seconds))
        async with self.database.connection() as connection:
            cursor = await connection.execute(
                "UPDATE scheduled_tasks SET status='active',claimed_at=NULL,updated_at=? WHERE status='running' AND claimed_at<=?",
                (_iso(now), cutoff),
            )
            await connection.commit()
        return cursor.rowcount

    async def update_run(
        self,
        task_run_id: str,
        status: str,
        agent_run_id: str | None = None,
        answer: str | None = None,
        error: str | None = None,
        finished: bool = False,
    ) -> None:
        async with self.database.connection() as connection:
            await connection.execute(
                "UPDATE scheduled_task_runs SET status=?,agent_run_id=COALESCE(?,agent_run_id),answer=?,error=?,finished_at=? WHERE id=?",
                (
                    status,
                    agent_run_id,
                    answer,
                    error,
                    _iso(utc_now()) if finished else None,
                    task_run_id,
                ),
            )
            await connection.commit()

    async def set_task_state(
        self,
        task_id: str,
        status: str,
        next_run_at: datetime | None = None,
        retry_count: int = 0,
        last_error: str | None = None,
    ) -> None:
        async with self.database.connection() as connection:
            await connection.execute(
                "UPDATE scheduled_tasks SET status=?,next_run_at=COALESCE(?,next_run_at),retry_count=?,claimed_at=NULL,last_error=?,updated_at=? WHERE id=?",
                (
                    status,
                    _iso(next_run_at) if next_run_at else None,
                    retry_count,
                    last_error,
                    _iso(utc_now()),
                    task_id,
                ),
            )
            await connection.commit()

    async def find_waiting_by_agent_run(self, agent_run_id: str) -> dict | None:
        async with self.database.connection() as connection:
            cursor = await connection.execute(
                """SELECT r.*,t.schedule_type,t.interval_seconds,t.next_run_at,
                t.status AS task_status FROM scheduled_task_runs r
                JOIN scheduled_tasks t ON t.id=r.task_id
                WHERE r.agent_run_id=? AND r.status='waiting_approval'""",
                (agent_run_id,),
            )
            row = await cursor.fetchone()
        return dict(row) if row else None
