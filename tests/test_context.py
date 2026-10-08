import json
import tempfile
from pathlib import Path

import pytest

from app.core.context import ContextBuilder
from app.memory.repository import Database
from app.memory.summarizer import SessionSummarizer


@pytest.mark.asyncio
async def test_context_keeps_recent_messages_and_summary_within_budget():
    with tempfile.TemporaryDirectory() as directory:
        database = Database(Path(directory) / "context.db")
        await database.initialize()
        session = await database.create_session()
        for index in range(12):
            await database.append_message(
                session["id"], "user", f"old message {index} " + "word " * 30
            )
        await database.update_summary(session["id"], "Earlier goal: build Atlas")
        await database.append_message(session["id"], "user", "What is the status?")
        context = await ContextBuilder(database, budget=250, recent_budget=120).build(
            session["id"]
        )
        assert context.stats.estimated_tokens <= 250
        assert any("Earlier goal" in message["content"] for message in context.messages)
        assert context.messages[-1]["content"] == "What is the status?"
        assert context.stats.messages_kept < 13


@pytest.mark.asyncio
async def test_rolling_summary_keeps_structured_facts_without_nesting():
    with tempfile.TemporaryDirectory() as directory:
        database = Database(Path(directory) / "summary.db")
        await database.initialize()
        session = await database.create_session()
        await database.update_summary(
            session["id"],
            json.dumps(
                {
                    "user_goals": ["Build Atlas"],
                    "decisions": ["Use SQLite"],
                    "important_facts": ["Project is Atlas"],
                    "artifacts": [],
                    "open_items": [],
                }
            ),
        )
        for index in range(12):
            await database.append_message(session["id"], "user", f"Update {index}")
        await SessionSummarizer(database).maybe_summarize(session["id"])
        summary = json.loads((await database.get_session(session["id"]))["summary"])
        assert "Use SQLite" in summary["decisions"]
        assert "Project is Atlas" in summary["important_facts"]
        assert all(isinstance(item, str) for item in summary["important_facts"])


@pytest.mark.asyncio
async def test_summary_runs_only_after_new_message_threshold():
    with tempfile.TemporaryDirectory() as directory:
        database = Database(Path(directory) / "summary.db")
        await database.initialize()
        session = await database.create_session()
        summarizer = SessionSummarizer(database, threshold=3)
        for index in range(3):
            await database.append_message(session["id"], "user", f"Goal {index}")
        assert await summarizer.maybe_summarize(session["id"])
        assert await summarizer.maybe_summarize(session["id"]) is None
        for index in range(3, 6):
            await database.append_message(session["id"], "user", f"Goal {index}")
        assert await summarizer.maybe_summarize(session["id"])
        assert (await database.get_session(session["id"]))[
            "summarized_message_count"
        ] == 6
