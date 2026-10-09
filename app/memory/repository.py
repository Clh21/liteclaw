import json
import re
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from hashlib import sha256
from importlib.resources import files
from pathlib import Path
from uuid import uuid4

import aiosqlite


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)

    async def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        schema = files("app.memory").joinpath("schema.sql").read_text(encoding="utf-8")
        async with aiosqlite.connect(self.path) as connection:
            await connection.executescript(schema)
            cursor = await connection.execute("PRAGMA table_info(approvals)")
            columns = {row[1] for row in await cursor.fetchall()}
            if "tool_call_id" not in columns:
                await connection.execute(
                    "ALTER TABLE approvals ADD COLUMN tool_call_id TEXT"
                )
            cursor = await connection.execute("PRAGMA table_info(sessions)")
            session_columns = {row[1] for row in await cursor.fetchall()}
            if "summarized_message_count" not in session_columns:
                await connection.execute(
                    "ALTER TABLE sessions ADD COLUMN summarized_message_count INTEGER NOT NULL DEFAULT 0"
                )
            await connection.commit()

    async def ready(self) -> bool:
        try:
            async with aiosqlite.connect(self.path) as connection:
                cursor = await connection.execute("SELECT 1 FROM sessions LIMIT 1")
                await cursor.fetchone()
            return True
        except (OSError, aiosqlite.Error):
            return False

    async def create_user(self, username: str, role: str) -> dict:
        user = {
            "id": uuid4().hex,
            "username": username,
            "role": role,
            "active": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        async with self.connection() as connection:
            await connection.execute(
                "INSERT INTO users(id,username,role,active,created_at) VALUES(:id,:username,:role,:active,:created_at)",
                user,
            )
            await connection.commit()
        return user

    async def create_api_token(self, user_id: str, label: str | None = None) -> dict:
        token = "lc_" + secrets.token_urlsafe(32)
        record = {
            "id": uuid4().hex,
            "user_id": user_id,
            "token_hash": sha256(token.encode()).hexdigest(),
            "label": label,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        async with self.connection() as connection:
            cursor = await connection.execute(
                "SELECT id FROM users WHERE id=? AND active=1", (user_id,)
            )
            if await cursor.fetchone() is None:
                raise KeyError("user_not_found")
            await connection.execute(
                "INSERT INTO api_tokens(id,user_id,token_hash,label,created_at) VALUES(:id,:user_id,:token_hash,:label,:created_at)",
                record,
            )
            await connection.commit()
        return {key: value for key, value in record.items() if key != "token_hash"} | {
            "token": token
        }

    async def authenticate_api_token(self, token: str) -> dict | None:
        digest = sha256(token.encode()).hexdigest()
        async with self.connection() as connection:
            cursor = await connection.execute(
                """SELECT users.id,users.username,users.role
                FROM api_tokens JOIN users ON users.id=api_tokens.user_id
                WHERE api_tokens.token_hash=? AND api_tokens.revoked_at IS NULL
                  AND users.active=1""",
                (digest,),
            )
            row = await cursor.fetchone()
        return dict(row) if row else None

    async def revoke_api_token(self, token_id: str) -> bool:
        async with self.connection() as connection:
            cursor = await connection.execute(
                "UPDATE api_tokens SET revoked_at=? WHERE id=? AND revoked_at IS NULL",
                (datetime.now(timezone.utc).isoformat(), token_id),
            )
            await connection.commit()
        return cursor.rowcount == 1

    @asynccontextmanager
    async def connection(self):
        async with aiosqlite.connect(self.path) as connection:
            connection.row_factory = aiosqlite.Row
            await connection.execute("PRAGMA foreign_keys=ON")
            yield connection

    async def create_session(self, title: str | None = None) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        session = {
            "id": uuid4().hex,
            "title": title,
            "agent_id": "main",
            "summary": None,
            "created_at": now,
            "updated_at": now,
        }
        async with self.connection() as connection:
            await connection.execute(
                "INSERT INTO sessions(id,title,agent_id,summary,created_at,updated_at) VALUES(:id,:title,:agent_id,:summary,:created_at,:updated_at)",
                session,
            )
            await connection.commit()
        return session

    async def get_session(self, session_id: str) -> dict | None:
        async with self.connection() as connection:
            cursor = await connection.execute(
                "SELECT * FROM sessions WHERE id=?", (session_id,)
            )
            row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_messages(self, session_id: str) -> list[dict]:
        async with self.connection() as connection:
            cursor = await connection.execute(
                "SELECT * FROM messages WHERE session_id=? ORDER BY created_at, rowid",
                (session_id,),
            )
            rows = await cursor.fetchall()
        return [
            {**dict(row), "tool_calls": json.loads(row["tool_calls_json"] or "[]")}
            for row in rows
        ]

    async def append_message(
        self,
        session_id: str,
        role: str,
        content: str | None = None,
        tool_calls: list[dict] | None = None,
        tool_call_id: str | None = None,
    ) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        message = {
            "id": uuid4().hex,
            "session_id": session_id,
            "role": role,
            "content": content,
            "tool_calls_json": json.dumps(tool_calls or [], ensure_ascii=False),
            "tool_call_id": tool_call_id,
            "token_count": max(0, len(content or "") // 4),
            "created_at": now,
        }
        async with self.connection() as connection:
            await connection.execute(
                "INSERT INTO messages(id,session_id,role,content,tool_calls_json,tool_call_id,token_count,created_at) VALUES(:id,:session_id,:role,:content,:tool_calls_json,:tool_call_id,:token_count,:created_at)",
                message,
            )
            await connection.execute(
                "UPDATE sessions SET updated_at=? WHERE id=?", (now, session_id)
            )
            await connection.commit()
        return {**message, "tool_calls": tool_calls or []}

    async def create_run(self, session_id: str) -> str:
        run_id = uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        async with self.connection() as connection:
            await connection.execute(
                "INSERT INTO agent_runs(id,session_id,status,trace_json,started_at) VALUES(?,?,?,?,?)",
                (run_id, session_id, "running", "[]", now),
            )
            await connection.commit()
        return run_id

    async def finish_run(
        self, run_id: str, status: str, trace: list[dict], error: str | None = None
    ) -> None:
        now = (
            datetime.now(timezone.utc).isoformat()
            if status in {"completed", "failed"}
            else None
        )
        async with self.connection() as connection:
            await connection.execute(
                "UPDATE agent_runs SET status=?,trace_json=?,error=?,finished_at=? WHERE id=?",
                (status, json.dumps(trace, ensure_ascii=False), error, now, run_id),
            )
            await connection.commit()

    async def get_run(self, run_id: str) -> dict | None:
        async with self.connection() as connection:
            cursor = await connection.execute(
                "SELECT * FROM agent_runs WHERE id=?", (run_id,)
            )
            row = await cursor.fetchone()
        return (
            {**dict(row), "trace": json.loads(row["trace_json"] or "[]")}
            if row
            else None
        )

    async def save_planner_state(
        self,
        parent_run_id: str,
        plan: dict,
        results: list[dict],
        next_index: int,
        worker_run_id: str | None = None,
        worker_session_id: str | None = None,
    ) -> None:
        async with self.connection() as connection:
            await connection.execute(
                "INSERT OR REPLACE INTO planner_runs(parent_run_id,plan_json,results_json,next_index,worker_run_id,worker_session_id) VALUES(?,?,?,?,?,?)",
                (
                    parent_run_id,
                    json.dumps(plan, ensure_ascii=False),
                    json.dumps(results, ensure_ascii=False),
                    next_index,
                    worker_run_id,
                    worker_session_id,
                ),
            )
            await connection.commit()

    async def get_planner_state(self, parent_run_id: str) -> dict | None:
        async with self.connection() as connection:
            cursor = await connection.execute(
                "SELECT * FROM planner_runs WHERE parent_run_id=?", (parent_run_id,)
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return {
            **dict(row),
            "plan": json.loads(row["plan_json"]),
            "results": json.loads(row["results_json"]),
        }

    async def get_planner_by_worker(self, worker_run_id: str) -> dict | None:
        async with self.connection() as connection:
            cursor = await connection.execute(
                "SELECT parent_run_id FROM planner_runs WHERE worker_run_id=?",
                (worker_run_id,),
            )
            row = await cursor.fetchone()
        return await self.get_planner_state(row[0]) if row else None

    async def create_approval(
        self, run_id: str, tool_call_id: str, tool_name: str, arguments: dict
    ) -> str:
        approval_id = uuid4().hex
        async with self.connection() as connection:
            await connection.execute(
                "INSERT INTO approvals(id,run_id,tool_call_id,tool_name,arguments_json,status,created_at) VALUES(?,?,?,?,?,?,?)",
                (
                    approval_id,
                    run_id,
                    tool_call_id,
                    tool_name,
                    json.dumps(arguments),
                    "pending",
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            await connection.commit()
        return approval_id

    async def decide_approval(self, approval_id: str, approve: bool) -> dict | None:
        async with self.connection() as connection:
            cursor = await connection.execute(
                "UPDATE approvals SET status=?,decided_at=? WHERE id=? AND status='pending'",
                (
                    "approved" if approve else "rejected",
                    datetime.now(timezone.utc).isoformat(),
                    approval_id,
                ),
            )
            if cursor.rowcount != 1:
                return None
            cursor = await connection.execute(
                "SELECT * FROM approvals WHERE id=?", (approval_id,)
            )
            row = await cursor.fetchone()
            await connection.commit()
        return dict(row)

    async def record_tool_event(
        self, run_id: str, tool_name: str, arguments: dict, result: dict
    ) -> None:
        from app.logging import redact

        async with self.connection() as connection:
            await connection.execute(
                "INSERT INTO tool_events(id,run_id,tool_name,arguments_json,result_json,elapsed_ms,created_at) VALUES(?,?,?,?,?,?,?)",
                (
                    uuid4().hex,
                    run_id,
                    tool_name,
                    json.dumps(redact(arguments), ensure_ascii=False),
                    json.dumps(result, ensure_ascii=False),
                    result.get("elapsed_ms", 0),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            await connection.commit()

    async def get_tool_events(self, run_id: str) -> list[dict]:
        async with self.connection() as connection:
            cursor = await connection.execute(
                "SELECT * FROM tool_events WHERE run_id=? ORDER BY created_at,rowid",
                (run_id,),
            )
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def update_summary(self, session_id: str, summary: str) -> None:
        async with self.connection() as connection:
            await connection.execute(
                "UPDATE sessions SET summary=?,summarized_message_count=(SELECT COUNT(*) FROM messages WHERE session_id=?),updated_at=? WHERE id=?",
                (
                    summary,
                    session_id,
                    datetime.now(timezone.utc).isoformat(),
                    session_id,
                ),
            )
            await connection.commit()

    async def add_memory(
        self,
        content: str,
        kind: str = "note",
        importance: float = 0.5,
        agent_id: str = "main",
        session_id: str | None = None,
        embedding: list[float] | None = None,
        embedding_model: str | None = None,
    ) -> dict:
        import hashlib

        normalized = " ".join(content.split())
        if not normalized:
            raise ValueError("Memory content is empty")
        content_hash = hashlib.sha256(normalized.casefold().encode()).hexdigest()
        now = datetime.now(timezone.utc).isoformat()
        async with self.connection() as connection:
            cursor = await connection.execute(
                "SELECT * FROM memories WHERE agent_id=? AND content_hash=?",
                (agent_id, content_hash),
            )
            existing = await cursor.fetchone()
            if existing:
                return dict(existing)
            memory = {
                "id": uuid4().hex,
                "agent_id": agent_id,
                "session_id": session_id,
                "content": normalized,
                "kind": kind,
                "importance": importance,
                "embedding_model": embedding_model,
                "embedding": json.dumps(embedding).encode()
                if embedding is not None
                else None,
                "content_hash": content_hash,
                "created_at": now,
                "updated_at": now,
            }
            await connection.execute(
                "INSERT INTO memories(id,agent_id,session_id,content,kind,importance,embedding_model,embedding,content_hash,created_at,updated_at) VALUES(:id,:agent_id,:session_id,:content,:kind,:importance,:embedding_model,:embedding,:content_hash,:created_at,:updated_at)",
                memory,
            )
            await connection.execute(
                "INSERT INTO memories_fts(memory_id,content) VALUES(?,?)",
                (memory["id"], normalized),
            )
            await connection.commit()
        return memory

    async def delete_memory(self, memory_id: str) -> bool:
        async with self.connection() as connection:
            await connection.execute(
                "DELETE FROM memories_fts WHERE memory_id=?", (memory_id,)
            )
            cursor = await connection.execute(
                "DELETE FROM memories WHERE id=?", (memory_id,)
            )
            await connection.commit()
            return cursor.rowcount > 0

    async def search_fts(self, query: str, limit: int = 24) -> list[dict]:
        tokens = re.findall(r"\w+", query, flags=re.UNICODE)
        if not tokens:
            return []
        match = " OR ".join(
            '"' + token.replace('"', '""') + '"' for token in tokens[:12]
        )
        async with self.connection() as connection:
            cursor = await connection.execute(
                "SELECT m.*,bm25(memories_fts) AS bm25_score FROM memories_fts JOIN memories m ON m.id=memories_fts.memory_id WHERE memories_fts MATCH ? ORDER BY bm25_score LIMIT ?",
                (match, limit),
            )
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def all_memories(self, limit: int = 1000) -> list[dict]:
        async with self.connection() as connection:
            cursor = await connection.execute(
                "SELECT * FROM memories ORDER BY created_at DESC LIMIT ?", (limit,)
            )
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_memories_by_ids(self, memory_ids: list[str]) -> list[dict]:
        if not memory_ids:
            return []
        placeholders = ",".join("?" for _ in memory_ids)
        async with self.connection() as connection:
            cursor = await connection.execute(
                f"SELECT * FROM memories WHERE id IN ({placeholders})",
                memory_ids,
            )
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def set_memory_embedding(
        self, memory_id: str, model: str, embedding: list[float]
    ) -> None:
        async with self.connection() as connection:
            await connection.execute(
                "UPDATE memories SET embedding_model=?,embedding=?,updated_at=? WHERE id=?",
                (
                    model,
                    json.dumps(embedding).encode(),
                    datetime.now(timezone.utc).isoformat(),
                    memory_id,
                ),
            )
            await connection.commit()

    async def get_cached_embedding(
        self, content_hash: str, model: str
    ) -> list[float] | None:
        async with self.connection() as connection:
            cursor = await connection.execute(
                "SELECT embedding FROM embedding_cache WHERE content_hash=? AND model=?",
                (content_hash, model),
            )
            row = await cursor.fetchone()
        return json.loads(row[0]) if row else None

    async def put_cached_embedding(
        self, content_hash: str, model: str, embedding: list[float]
    ) -> None:
        async with self.connection() as connection:
            await connection.execute(
                "INSERT OR REPLACE INTO embedding_cache(content_hash,model,embedding,created_at) VALUES(?,?,?,?)",
                (
                    content_hash,
                    model,
                    json.dumps(embedding).encode(),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            await connection.commit()
