import tempfile
from pathlib import Path

import pytest

from app.core.events import RunEventEmitter
from app.core.messages import ModelResponse, ToolCall
from app.core.runtime import AgentRuntime
from app.memory.repository import Database
from app.models.fake import FakeModel
from app.tools.builtin.calculator import CalculatorTool
from app.tools.registry import ToolRegistry


@pytest.mark.asyncio
async def test_runtime_emits_ordered_model_tool_and_final_events():
    with tempfile.TemporaryDirectory() as directory:
        database = Database(Path(directory) / "events.db")
        await database.initialize()
        session = await database.create_session()
        model = FakeModel(
            [
                ModelResponse(
                    tool_calls=[
                        ToolCall(
                            id="calc-1",
                            name="calculator",
                            arguments={"expression": "2+3"},
                        )
                    ]
                ),
                ModelResponse(content="The answer is 5."),
            ]
        )
        registry = ToolRegistry()
        registry.register(CalculatorTool())
        events = []
        result = await AgentRuntime(database, model, registry).run(
            session["id"], "calculate 2+3", RunEventEmitter(events.append)
        )
        assert result.answer == "The answer is 5."
        assert [event["type"] for event in events] == [
            "run_started",
            "model_started",
            "model_completed",
            "tool_started",
            "tool_completed",
            "model_started",
            "model_completed",
            "final",
        ]
        assert [event["seq"] for event in events] == list(range(1, 9))
        assert events[4]["tool_name"] == "calculator"
        assert "arguments" not in events[3]
        assert events[-1]["answer"] == "The answer is 5."


@pytest.mark.asyncio
async def test_runtime_without_emitter_keeps_existing_api():
    with tempfile.TemporaryDirectory() as directory:
        database = Database(Path(directory) / "events.db")
        await database.initialize()
        session = await database.create_session()
        result = await AgentRuntime(database, FakeModel(), ToolRegistry()).run(
            session["id"], "hello"
        )
        assert result.answer == "FakeModel: hello"
