from datetime import datetime, timezone
from uuid import uuid4

from app.memory.repository import Database


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def case_dict(row) -> dict:
    item = dict(row)
    item["enabled"] = bool(item["enabled"])
    return item


class EvalRepository:
    def __init__(self, database: Database):
        self.database = database

    async def create_case(
        self,
        name: str,
        prompt: str,
        expected_contains: str | None,
        enabled: bool = True,
        source_run_id: str | None = None,
    ) -> dict:
        now = utc_now()
        item = {
            "id": uuid4().hex,
            "name": name,
            "prompt": prompt,
            "expected_contains": expected_contains,
            "enabled": int(enabled),
            "source_run_id": source_run_id,
            "created_at": now,
            "updated_at": now,
        }
        async with self.database.connection() as connection:
            await connection.execute(
                "INSERT INTO eval_cases(id,name,prompt,expected_contains,enabled,source_run_id,created_at,updated_at) VALUES(:id,:name,:prompt,:expected_contains,:enabled,:source_run_id,:created_at,:updated_at)",
                item,
            )
            await connection.commit()
        return {**item, "enabled": bool(item["enabled"])}

    async def get_case(self, case_id: str) -> dict | None:
        async with self.database.connection() as connection:
            cursor = await connection.execute(
                "SELECT * FROM eval_cases WHERE id=?", (case_id,)
            )
            row = await cursor.fetchone()
        return case_dict(row) if row else None

    async def list_cases(
        self, enabled_only: bool = False, case_ids: list[str] | None = None
    ) -> list[dict]:
        clauses = []
        parameters: list[object] = []
        if enabled_only:
            clauses.append("enabled=1")
        if case_ids is not None:
            if not case_ids:
                return []
            clauses.append(f"id IN ({','.join('?' for _ in case_ids)})")
            parameters.extend(case_ids)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        async with self.database.connection() as connection:
            cursor = await connection.execute(
                f"SELECT * FROM eval_cases{where} ORDER BY created_at,rowid",
                parameters,
            )
            rows = await cursor.fetchall()
        return [case_dict(row) for row in rows]

    async def update_case(self, case_id: str, **changes) -> dict | None:
        allowed = {"name", "prompt", "expected_contains", "enabled"}
        values = {key: value for key, value in changes.items() if key in allowed}
        if not values:
            return await self.get_case(case_id)
        if "enabled" in values:
            values["enabled"] = int(values["enabled"])
        values["updated_at"] = utc_now()
        assignments = ",".join(f"{key}=?" for key in values)
        async with self.database.connection() as connection:
            cursor = await connection.execute(
                f"UPDATE eval_cases SET {assignments} WHERE id=?",
                [*values.values(), case_id],
            )
            await connection.commit()
        return await self.get_case(case_id) if cursor.rowcount else None

    async def delete_case(self, case_id: str) -> bool:
        async with self.database.connection() as connection:
            cursor = await connection.execute(
                "DELETE FROM eval_cases WHERE id=?", (case_id,)
            )
            await connection.commit()
        return bool(cursor.rowcount)

    async def create_case_from_run(
        self, run_id: str, name: str, expected_contains: str | None
    ) -> dict | None:
        run = await self.database.get_run(run_id)
        if run is None or run["session_id"] is None:
            return None
        messages = await self.database.get_messages(run["session_id"])
        prompt = next(
            (
                message["content"]
                for message in reversed(messages)
                if message["role"] == "user" and message["content"]
            ),
            None,
        )
        if prompt is None:
            return None
        return await self.create_case(
            name, prompt, expected_contains, source_run_id=run_id
        )

    async def start_run(self, total: int) -> str:
        run_id = uuid4().hex
        async with self.database.connection() as connection:
            await connection.execute(
                "INSERT INTO eval_runs(id,status,total,started_at) VALUES(?,?,?,?)",
                (run_id, "running", total, utc_now()),
            )
            await connection.commit()
        return run_id

    async def add_result(
        self,
        eval_run_id: str,
        case: dict,
        status: str,
        answer: str | None,
        error: str | None,
        elapsed_ms: int,
        agent_run_id: str | None = None,
    ) -> None:
        async with self.database.connection() as connection:
            await connection.execute(
                "INSERT INTO eval_results(id,eval_run_id,case_id,case_name,prompt,expected_contains,agent_run_id,status,answer,error,elapsed_ms,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    uuid4().hex,
                    eval_run_id,
                    case["id"],
                    case["name"],
                    case["prompt"],
                    case["expected_contains"],
                    agent_run_id,
                    status,
                    answer,
                    error,
                    elapsed_ms,
                    utc_now(),
                ),
            )
            await connection.commit()

    async def finish_run(self, run_id: str) -> None:
        async with self.database.connection() as connection:
            cursor = await connection.execute(
                "SELECT status,COUNT(*) count FROM eval_results WHERE eval_run_id=? GROUP BY status",
                (run_id,),
            )
            counts = {row["status"]: row["count"] for row in await cursor.fetchall()}
            await connection.execute(
                "UPDATE eval_runs SET status='completed',passed=?,failed=?,errors=?,finished_at=? WHERE id=?",
                (
                    counts.get("passed", 0),
                    counts.get("failed", 0),
                    counts.get("error", 0),
                    utc_now(),
                    run_id,
                ),
            )
            await connection.commit()

    async def get_run(self, run_id: str) -> dict | None:
        async with self.database.connection() as connection:
            cursor = await connection.execute(
                "SELECT * FROM eval_runs WHERE id=?", (run_id,)
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            cursor = await connection.execute(
                "SELECT * FROM eval_results WHERE eval_run_id=? ORDER BY created_at,rowid",
                (run_id,),
            )
            results = [dict(item) for item in await cursor.fetchall()]
        return {**dict(row), "results": results}

    async def list_runs(self, limit: int = 20) -> list[dict]:
        async with self.database.connection() as connection:
            cursor = await connection.execute(
                "SELECT * FROM eval_runs ORDER BY started_at DESC,rowid DESC LIMIT ?",
                (limit,),
            )
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]
