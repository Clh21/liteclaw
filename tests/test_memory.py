import tempfile
from pathlib import Path

import pytest

from app.memory.embeddings import CachedEmbeddings
from app.memory.hybrid import HybridRetriever, rrf
from app.memory.repository import Database
from app.memory.vector import SqliteVecStore


@pytest.mark.asyncio
async def test_all_memories_supports_unbounded_pgvector_backfill(tmp_path):
    database = Database(tmp_path / "memory.db")
    await database.initialize()
    rows = [
        (
            f"memory-{index}",
            "alice",
            "main",
            f"content {index}",
            "fact",
            0.5,
            f"2026-01-01T00:00:{index % 60:02d}+00:00",
        )
        for index in range(1001)
    ]
    async with database.connection() as connection:
        await connection.executemany(
            """INSERT INTO memories(
            id,owner_id,agent_id,content,kind,importance,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?)""",
            [(*row, row[-1]) for row in rows],
        )
        await connection.commit()

    assert len(await database.all_memories()) == 1000
    assert len(await database.all_memories(limit=None)) == 1001


@pytest.mark.asyncio
async def test_memory_fts_and_hybrid_search():
    with tempfile.TemporaryDirectory() as directory:
        database = Database(Path(directory) / "memory.db")
        await database.initialize()
        memory = await database.add_memory("My project is Atlas", kind="fact")
        matches = await database.search_fts("Atlas")
        assert matches[0]["id"] == memory["id"]
        hits = await HybridRetriever(database).search("Atlas", top_k=3)
        assert hits[0]["id"] == memory["id"]
        assert hits[0]["keyword_rank"] == 1


@pytest.mark.asyncio
async def test_embedding_cache_avoids_second_provider_call():
    class Provider:
        model = "test-embedding"
        calls = 0

        async def embed(self, text):
            self.calls += 1
            return [1.0, 0.0]

    with tempfile.TemporaryDirectory() as directory:
        database = Database(Path(directory) / "memory.db")
        await database.initialize()
        provider = Provider()
        cached = CachedEmbeddings(database, provider)
        assert await cached.embed(" Atlas  project ") == [1.0, 0.0]
        assert await cached.embed("Atlas project") == [1.0, 0.0]
        assert provider.calls == 1
        assert cached.stats["cache_hits"] == 1


def test_rrf_deduplicates_and_orders_results():
    keyword = [{"id": "a"}, {"id": "b"}]
    vector = [{"id": "b"}, {"id": "c"}]
    ranked = rrf(keyword, vector)
    assert [hit["id"] for hit in ranked] == ["b", "a", "c"]
    assert ranked[0]["keyword_rank"] == 2
    assert ranked[0]["vector_rank"] == 1


def test_sqlite_vec_knn_when_extension_is_available():
    store = SqliteVecStore()
    if not store.available:
        pytest.skip("sqlite-vec extension unavailable")
    candidates = [
        {"id": "a", "embedding": [1.0, 0.0]},
        {"id": "b", "embedding": [0.0, 1.0]},
    ]
    assert [item["id"] for item in store.search([0.9, 0.1], candidates, 2)] == [
        "a",
        "b",
    ]
