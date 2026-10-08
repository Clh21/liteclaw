import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.config import Settings
from app.core.messages import ModelResponse, ToolCall
from app.core.runtime import AgentRuntime, PendingRunResult
from app.main import create_app
from app.memory.repository import Database
from app.models.fake import FakeModel
from app.tools.base import BaseTool, ToolResult
from app.tools.registry import ToolRegistry


class EmptyArgs(BaseModel):
    pass


class DangerousTool(BaseTool):
    name = "dangerous"
    description = "A test side effect"
    args_model = EmptyArgs
    risk_level = "high"

    def __init__(self):
        self.calls = 0

    async def run(self, arguments, context=None):
        self.calls += 1
        return ToolResult(ok=True, content="done")


@pytest.mark.asyncio
async def test_high_risk_tool_waits_then_resumes_after_approval():
    with tempfile.TemporaryDirectory() as directory:
        database = Database(Path(directory) / "approval.db")
        await database.initialize()
        session = await database.create_session()
        model = FakeModel(
            [
                ModelResponse(
                    tool_calls=[ToolCall(id="call-1", name="dangerous", arguments={})]
                ),
                ModelResponse(content="completed"),
            ]
        )
        tool = DangerousTool()
        registry = ToolRegistry()
        registry.register(tool)
        runtime = AgentRuntime(
            database, model, registry, max_steps=3, require_approval=True
        )
        pending = await runtime.run(session["id"], "Do it")
        assert isinstance(pending, PendingRunResult)
        assert tool.calls == 0
        result = await runtime.resolve_approval(pending.approval_id, approve=True)
        assert result.answer == "completed"
        assert tool.calls == 1


@pytest.mark.asyncio
async def test_rejection_returns_observation_without_running_tool():
    with tempfile.TemporaryDirectory() as directory:
        database = Database(Path(directory) / "approval.db")
        await database.initialize()
        session = await database.create_session()
        model = FakeModel(
            [
                ModelResponse(
                    tool_calls=[ToolCall(id="call-1", name="dangerous", arguments={})]
                ),
                ModelResponse(content="rejected"),
            ]
        )
        tool = DangerousTool()
        registry = ToolRegistry()
        registry.register(tool)
        runtime = AgentRuntime(
            database, model, registry, max_steps=3, require_approval=True
        )
        pending = await runtime.run(session["id"], "Do it")
        result = await runtime.resolve_approval(pending.approval_id, approve=False)
        assert result.answer == "rejected"
        assert tool.calls == 0


def test_api_returns_202_and_resumes_file_overwrite_after_approval():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "note.txt"
        path.write_text("before", encoding="utf-8")
        settings = Settings(
            workspace_root=directory,
            db_path="approval.db",
            model_provider="fake",
            require_approval=True,
        )
        app = create_app(settings)
        app.state.runtime.model = FakeModel(
            [
                ModelResponse(
                    tool_calls=[
                        ToolCall(
                            id="write-1",
                            name="file_write",
                            arguments={
                                "relative_path": "note.txt",
                                "content": "after",
                                "overwrite": True,
                            },
                        )
                    ]
                ),
                ModelResponse(content="Updated"),
            ]
        )
        with TestClient(app) as client:
            pending = client.post("/v1/chat", json={"message": "Update note"})
            assert pending.status_code == 202
            assert path.read_text(encoding="utf-8") == "before"
            approved = client.post(
                f"/v1/approvals/{pending.json()['approval_id']}/approve"
            )
            assert approved.status_code == 200
            assert approved.json()["answer"] == "Updated"
            assert path.read_text(encoding="utf-8") == "after"
