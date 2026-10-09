import json
import re
from collections.abc import Callable


class PgVectorStore:
    def __init__(
        self,
        url: str,
        table: str = "liteclaw_memory_vectors",
        pool_factory: Callable | None = None,
    ):
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", table):
            raise ValueError("Invalid pgvector table name")
        self.url = url
        self.table = table
        self.pool_factory = pool_factory
        self.pool = None
        self.status = "disabled" if not url else "pending"

    @property
    def available(self) -> bool:
        return self.status == "ready" and self.pool is not None

    async def initialize(self) -> bool:
        if not self.url:
            return False
        try:
            factory = self.pool_factory
            if factory is None:
                import asyncpg

                factory = asyncpg.create_pool
            self.pool = await factory(
                self.url, min_size=1, max_size=4, command_timeout=30
            )
            async with self.pool.acquire() as connection:
                await connection.execute("CREATE EXTENSION IF NOT EXISTS vector")
                await connection.execute(
                    f"""CREATE TABLE IF NOT EXISTS {self.table} (
                        memory_id TEXT PRIMARY KEY,
                        owner_id TEXT,
                        agent_id TEXT NOT NULL,
                        session_id TEXT,
                        content TEXT NOT NULL,
                        kind TEXT NOT NULL,
                        importance DOUBLE PRECISION NOT NULL,
                        embedding_model TEXT NOT NULL,
                        embedding vector NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )"""
                )
                await connection.execute(
                    f"ALTER TABLE {self.table} ADD COLUMN IF NOT EXISTS owner_id TEXT"
                )
                await connection.execute(
                    f"CREATE INDEX IF NOT EXISTS {self.table}_owner_idx ON {self.table}(owner_id)"
                )
            self.status = "ready"
            return True
        except Exception:  # noqa: BLE001 - optional backend must degrade cleanly
            if self.pool is not None:
                try:
                    await self.pool.close()
                except Exception:  # noqa: BLE001 - failed pool cleanup is best effort
                    self.pool = None
            self.pool = None
            self.status = "unavailable"
            return False

    async def upsert(
        self, memory: dict, embedding_model: str, embedding: list[float]
    ) -> bool:
        if not self.available:
            return False
        vector = json.dumps(embedding, separators=(",", ":"))
        try:
            async with self.pool.acquire() as connection:
                await connection.execute(
                    f"""INSERT INTO {self.table}
                    (memory_id,owner_id,agent_id,session_id,content,kind,importance,embedding_model,embedding,updated_at)
                    VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9::vector,NOW())
                    ON CONFLICT(memory_id) DO UPDATE SET
                    owner_id=EXCLUDED.owner_id,agent_id=EXCLUDED.agent_id,
                    session_id=EXCLUDED.session_id,
                    content=EXCLUDED.content,kind=EXCLUDED.kind,
                    importance=EXCLUDED.importance,
                    embedding_model=EXCLUDED.embedding_model,
                    embedding=EXCLUDED.embedding,updated_at=NOW()""",
                    memory["id"],
                    memory.get("owner_id"),
                    memory.get("agent_id", "main"),
                    memory.get("session_id"),
                    memory["content"],
                    memory.get("kind", "note"),
                    float(memory.get("importance", 0.5)),
                    embedding_model,
                    vector,
                )
        except Exception:
            self.status = "unavailable"
            raise
        return True

    async def search(
        self,
        query: list[float],
        embedding_model: str,
        limit: int,
        owner_id: str | None = None,
    ) -> list[dict]:
        if not self.available or not query:
            return []
        vector = json.dumps(query, separators=(",", ":"))
        try:
            async with self.pool.acquire() as connection:
                if owner_id is None:
                    rows = await connection.fetch(
                        f"""SELECT memory_id AS id,owner_id,agent_id,session_id,content,kind,
                        importance,embedding_model,embedding <=> $1::vector AS distance
                        FROM {self.table} WHERE embedding_model=$2
                        ORDER BY embedding <=> $1::vector LIMIT $3""",
                        vector,
                        embedding_model,
                        limit,
                    )
                else:
                    rows = await connection.fetch(
                        f"""SELECT memory_id AS id,owner_id,agent_id,session_id,content,kind,
                        importance,embedding_model,embedding <=> $1::vector AS distance
                        FROM {self.table} WHERE embedding_model=$2 AND owner_id=$3
                        ORDER BY embedding <=> $1::vector LIMIT $4""",
                        vector,
                        embedding_model,
                        owner_id,
                        limit,
                    )
        except Exception:
            self.status = "unavailable"
            raise
        return [dict(row) for row in rows]

    async def delete(self, memory_id: str) -> bool:
        if not self.available:
            return False
        try:
            async with self.pool.acquire() as connection:
                await connection.execute(
                    f"DELETE FROM {self.table} WHERE memory_id=$1", memory_id
                )
        except Exception:
            self.status = "unavailable"
            raise
        return True

    async def sync(self, memories: list[dict]) -> int:
        if not self.available:
            return 0
        synced = 0
        for memory in memories:
            raw = memory.get("embedding")
            model = memory.get("embedding_model")
            if raw is None or not model:
                continue
            try:
                embedding = json.loads(raw)
                await self.upsert(memory, model, embedding)
                synced += 1
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            except Exception:  # noqa: BLE001 - keep the main service available
                self.status = "unavailable"
                return synced
        return synced

    async def close(self) -> None:
        if self.pool is not None:
            await self.pool.close()
            self.pool = None
        if self.status == "ready":
            self.status = "closed"
