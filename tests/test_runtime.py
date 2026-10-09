import asyncio
import tempfile
from contextlib import contextmanager
from pathlib import Path

import pytest

from app.core.messages import ModelResponse, ToolCall
from app.core.runtime import AgentRuntime, MaxStepsExceeded
from app.memory.repository import Database
from app.models.fake import FakeModel
from app.tools.builtin.calculator import CalculatorTool
from app.tools.registry import ToolRegistry


@pytest.mark.asyncio
async def test_runtime_sends_tool_result_back_to_model():
    with tempfile.TemporaryDirectory() as directory:
        database = Database(Path(directory) / "agent.db")
        await database.initialize()
        session = await database.create_session()
        model = FakeModel(
            [
                ModelResponse(
                    tool_calls=[
                        ToolCall(
                            id="call-1",
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
        result = await AgentRuntime(database, model, registry, max_steps=3).run(
            session["id"], "Calculate 2+3"
        )
        assert result.answer == "The answer is 5."
        assert model.seen_messages[1][-1]["role"] == "tool"
        assert "5" in model.seen_messages[1][-1]["content"]
        assert [
            message["role"] for message in await database.get_messages(session["id"])
        ] == ["user", "assistant", "tool", "assistant"]


@pytest.mark.asyncio
async def test_runtime_stops_at_max_steps():
    with tempfile.TemporaryDirectory() as directory:
        database = Database(Path(directory) / "agent.db")
        await database.initialize()
        session = await database.create_session()
        response = ModelResponse(
            tool_calls=[
                ToolCall(
                    id="repeat", name="calculator", arguments={"expression": "1+1"}
                )
            ]
        )
        model = FakeModel([response, response])
        registry = ToolRegistry()
        registry.register(CalculatorTool())
        with pytest.raises(MaxStepsExceeded):
            await AgentRuntime(database, model, registry, max_steps=2).run(
                session["id"], "Keep calculating"
            )


def test_calculator_rejects_code_execution():
    tool = CalculatorTool()
    result = asyncio.run(
        tool.execute({"expression": "__import__('os').system('echo bad')"})
    )
    assert result.ok is False


@pytest.mark.asyncio
async def test_runtime_traces_agent_model_and_tool_without_payloads(tmp_path):
    class RecordingTracing:
        def __init__(self):
            self.spans = []

        @contextmanager
        def span(self, name, **attributes):
            self.spans.append((name, attributes))
            yield None

    database = Database(tmp_path / "trace.db")
    await database.initialize()
    session = await database.create_session()
    registry = ToolRegistry()
    registry.register(CalculatorTool())
    tracing = RecordingTracing()

    await AgentRuntime(
        database, FakeModel(), registry, max_steps=3, tracing=tracing
    ).run(session["id"], "calculate 2+3")

    assert [name for name, _ in tracing.spans] == [
        "agent.run",
        "model.complete",
        "tool.execute",
        "model.complete",
    ]
    assert all("arguments" not in attributes for _, attributes in tracing.spans)
