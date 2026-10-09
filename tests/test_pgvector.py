import pytest

from app.memory.pgvector import PgVectorStore


class FakeConnection:
    def __init__(self):
        self.executed = []
        self.rows = []

    async def execute(self, sql, *values):
        self.executed.append((sql, values))

    async def fetch(self, sql, *values):
        self.executed.append((sql, values))
        return self.rows


class Acquire:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, *_args):
        return None


class FakePool:
    def __init__(self, connection):
        self.connection = connection
        self.closed = False

    def acquire(self):
        return Acquire(self.connection)

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_pgvector_initializes_upserts_searches_and_deletes():
    connection = FakeConnection()
    pool = FakePool(connection)

    async def factory(_url, **_kwargs):
        return pool

    store = PgVectorStore("postgresql://db/liteclaw", pool_factory=factory)
    assert await store.initialize() is True
    assert store.status == "ready"
    assert "CREATE EXTENSION IF NOT EXISTS vector" in connection.executed[0][0]

    memory = {
        "id": "m1",
        "owner_id": "alice",
        "agent_id": "main",
        "session_id": "s1",
        "content": "Atlas is the project",
        "kind": "fact",
        "importance": 0.8,
    }
    await store.upsert(memory, "embed-v1", [0.1, 0.2])
    assert "INSERT INTO liteclaw_memory_vectors" in connection.executed[-1][0]
    assert connection.executed[-1][1][-1] == "[0.1,0.2]"

    connection.rows = [
        {
            **memory,
            "embedding_model": "embed-v1",
            "distance": 0.1,
        }
    ]
    hits = await store.search([0.1, 0.2], "embed-v1", 8, owner_id="alice")
    assert hits[0]["id"] == "m1"
    assert "<=>" in connection.executed[-1][0]
    assert "owner_id=$3" in connection.executed[-1][0]
    assert connection.executed[-1][1][2] == "alice"

    assert (
        await store.sync(
            [{**memory, "embedding_model": "embed-v1", "embedding": b"[0.3,0.4]"}]
        )
        == 1
    )

    await store.delete("m1")
    assert connection.executed[-1][1] == ("m1",)
    await store.close()
    assert pool.closed is True


@pytest.mark.asyncio
async def test_pgvector_is_optional_and_connection_failure_degrades():
    disabled = PgVectorStore("")
    assert await disabled.initialize() is False
    assert disabled.status == "disabled"

    async def failing_factory(_url, **_kwargs):
        raise OSError("database unavailable")

    unavailable = PgVectorStore(
        "postgresql://db/liteclaw", pool_factory=failing_factory
    )
    assert await unavailable.initialize() is False
    assert unavailable.status == "unavailable"


def test_pgvector_rejects_unsafe_table_name():
    with pytest.raises(ValueError, match="Invalid pgvector table name"):
        PgVectorStore("postgresql://db/liteclaw", table="vectors; DROP TABLE users")
