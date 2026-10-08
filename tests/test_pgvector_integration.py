from pathlib import Path

import pytest

from app.memory.embeddings import CachedEmbeddings
from app.memory.hybrid import HybridRetriever
from app.memory.repository import Database
from app.memory.writer import MemoryWriter


class Provider:
    model = "embed-v1"

    async def embed(self, _text):
        return [1.0, 0.0]


class RemoteStore:
    available = True

    def __init__(self, fail_search=False, memory_id="remote"):
        self.fail_search = fail_search
        self.memory_id = memory_id
        self.upserts = []
        self.deleted = []

    async def search(self, query, model, limit):
        if self.fail_search:
            raise OSError("postgres disconnected")
        return [
            {
                "id": self.memory_id,
                "content": "remote vector result",
                "kind": "fact",
                "importance": 0.8,
                "agent_id": "main",
                "session_id": None,
                "embedding_model": model,
            }
        ][:limit]

    async def upsert(self, memory, model, embedding):
        self.upserts.append((memory, model, embedding))
        return True

    async def delete(self, memory_id):
        self.deleted.append(memory_id)
        return True


@pytest.mark.asyncio
async def test_hybrid_uses_pgvector_when_ready(tmp_path):
    database = Database(Path(tmp_path) / "memory.db")
    await database.initialize()
    memory = await database.add_memory("remote vector result")
    retriever = HybridRetriever(
        database,
        CachedEmbeddings(database, Provider()),
        RemoteStore(memory_id=memory["id"]),
    )

    hits = await retriever.search("nothing in fts", top_k=3)

    assert hits[0]["id"] == memory["id"]
    assert hits[0]["vector_rank"] == 1


@pytest.mark.asyncio
async def test_pgvector_failure_falls_back_to_local_cosine(tmp_path):
    database = Database(Path(tmp_path) / "memory.db")
    await database.initialize()
    memory = await database.add_memory("local fallback")
    await database.set_memory_embedding(memory["id"], "embed-v1", [1.0, 0.0])
    retriever = HybridRetriever(
        database,
        CachedEmbeddings(database, Provider()),
        RemoteStore(fail_search=True),
    )

    hits = await retriever.search("unmatched query", top_k=3)

    assert hits[0]["id"] == memory["id"]


@pytest.mark.asyncio
async def test_memory_writer_upserts_and_deletes_pgvector_copy(tmp_path):
    database = Database(Path(tmp_path) / "memory.db")
    await database.initialize()
    session = await database.create_session()
    remote = RemoteStore()
    writer = MemoryWriter(
        database, CachedEmbeddings(database, Provider()), vector_store=remote
    )

    await writer.after_turn(session["id"], "Remember Atlas is my project")
    memory_id = remote.upserts[0][0]["id"]
    assert remote.upserts[0][1:] == ("embed-v1", [1.0, 0.0])

    await writer.after_turn(session["id"], "Forget Atlas")
    assert remote.deleted == [memory_id]
