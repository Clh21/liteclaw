import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.core.messages import ModelResponse, ToolCall
from app.core.planner import Planner
from app.core.runtime import AgentRuntime, PendingRunResult
from app.main import create_app
from app.memory.repository import Database
from app.models.fake import FakeModel
from app.tools.builtin.file_tools import FileWriteTool
from app.tools.registry import ToolRegistry


@pytest.mark.asyncio
async def test_planner_runs_workers_in_independent_sessions():
    with tempfile.TemporaryDirectory() as directory:
        database = Database(Path(directory) / "planner.db")
        await database.initialize()
        parent = await database.create_session()
        model = FakeModel(
            [
                ModelResponse(
                    content='{"tasks":[{"id":"t1","goal":"Research topic A","depends_on":[]},{"id":"t2","goal":"Compare topic B","depends_on":["t1"]}]}'
                ),
                ModelResponse(content="A result"),
                ModelResponse(content="B result"),
                ModelResponse(content="Combined result"),
            ]
        )
        registry = ToolRegistry()
        planner = Planner(
            database,
            model,
            lambda: AgentRuntime(database, model, registry, max_steps=3),
        )
        result = await planner.execute(parent["id"], "Research A and compare B")
        assert result["answer"] == "Combined result"
        assert len(result["tasks"]) == 2
        assert result["tasks"][0]["session_id"] != result["tasks"][1]["session_id"]
        assert "A result" in model.seen_messages[2][-1]["content"]


def test_fake_mode_planner_api():
    with tempfile.TemporaryDirectory() as directory:
        settings = Settings(
            workspace_root=directory,
            db_path="planner.db",
            model_provider="fake",
            enable_planner=True,
        )
        with TestClient(create_app(settings)) as client:
            response = client.post(
                "/v1/chat", json={"message": "Research A and compare B", "plan": True}
            )
            assert response.status_code == 200
            assert response.json()["tasks"]


def test_planner_api_returns_202_then_completes_after_approval():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "note.txt"
        path.write_text("before", encoding="utf-8")
        settings = Settings(
            workspace_root=directory,
            db_path="planner.db",
            model_provider="fake",
            enable_planner=True,
            require_approval=True,
        )
        app = create_app(settings)
        app.state.planner.model.responses.extend(
            [
                ModelResponse(
                    content='{"tasks":[{"id":"t1","goal":"Update note","depends_on":[]}]}'
                ),
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
                ModelResponse(content="Done"),
            ]
        )
        with TestClient(app) as client:
            pending = client.post(
                "/v1/chat", json={"message": "Update note", "plan": True}
            )
            assert pending.status_code == 202
            approved = client.post(
                f"/v1/approvals/{pending.json()['approval_id']}/approve"
            )
            assert approved.status_code == 200
            assert approved.json()["answer"] == "Done"
            assert path.read_text(encoding="utf-8") == "after"


@pytest.mark.asyncio
async def test_planner_resumes_after_worker_approval_even_with_new_planner_instance():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "note.txt"
        path.write_text("before", encoding="utf-8")
        database = Database(Path(directory) / "planner.db")
        await database.initialize()
        parent = await database.create_session()
        model = FakeModel(
            [
                ModelResponse(
                    content='{"tasks":[{"id":"t1","goal":"Update note","depends_on":[]}]}'
                ),
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
                ModelResponse(content="Done"),
            ]
        )
        registry = ToolRegistry()
        registry.register(FileWriteTool(Path(directory)))
        runtime_factory = lambda: AgentRuntime(
            database,
            model,
            registry,
            max_steps=4,
            workspace_root=Path(directory),
            require_approval=True,
        )
        planner = Planner(database, model, runtime_factory)
        pending = await planner.execute(parent["id"], "Update note")
        assert isinstance(pending, PendingRunResult)
        assert path.read_text(encoding="utf-8") == "before"
        worker = await runtime_factory().resolve_approval(pending.approval_id, True)
        resumed = await Planner(database, model, runtime_factory).resume_worker(worker)
        assert resumed["answer"] == "Done"
        assert path.read_text(encoding="utf-8") == "after"
        assert (await database.get_run(pending.run_id))["status"] == "completed"
