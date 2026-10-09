import tempfile
from pathlib import Path

import pytest

from app.core.messages import ModelResponse
from app.memory.repository import Database
from app.memory.writer import MemoryWriter


class Extractor:
    async def complete(self, messages, tools):
        return ModelResponse(
            content=(
                '```json\n{"memories":[{"content":"User prefers Vim",'
                '"kind":"preference","importance":0.9}]}\n```'
            )
        )


@pytest.mark.asyncio
async def test_memory_writer_extracts_stable_fact_from_model_json():
    with tempfile.TemporaryDirectory() as directory:
        database = Database(Path(directory) / "memory.db")
        await database.initialize()
        session = await database.create_session()
        await MemoryWriter(database, extractor_model=Extractor()).after_turn(
            session["id"], "I prefer Vim"
        )
        assert (await database.search_fts("Vim"))[0]["kind"] == "preference"


@pytest.mark.asyncio
async def test_explicit_forget_removes_matching_memory():
    with tempfile.TemporaryDirectory() as directory:
        database = Database(Path(directory) / "memory.db")
        await database.initialize()
        session = await database.create_session()
        writer = MemoryWriter(database)
        await writer.after_turn(session["id"], "Remember Atlas is my project")
        await writer.after_turn(session["id"], "Forget Atlas")
        assert await database.search_fts("Atlas") == []
