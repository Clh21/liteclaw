import json
import tempfile

from fastapi.testclient import TestClient

from app.config import Settings
from app.core.messages import ModelResponse, ToolCall
from app.main import create_app
from app.models.fake import FakeModel
from app.models.openai_compatible import ModelUnavailable


def parse_events(text):
    events = []
    for block in text.strip().split("\n\n"):
        lines = block.splitlines()
        if not lines or lines[0].startswith(":"):
            continue
        event_type = next(line[7:] for line in lines if line.startswith("event: "))
        data = json.loads(next(line[6:] for line in lines if line.startswith("data: ")))
        assert data["type"] == event_type
        events.append(data)
    return events


def stream_app(directory):
    return create_app(
        Settings(
            workspace_root=directory,
            db_path="stream.db",
            model_provider="fake",
            tasks_enabled=False,
        )
    )


def test_chat_stream_emits_calculator_lifecycle_and_sse_headers():
    with (
        tempfile.TemporaryDirectory() as directory,
        TestClient(stream_app(directory)) as client,
    ):
        response = client.post("/v1/chat/stream", json={"message": "calculate 2+3"})
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["cache-control"] == "no-cache"
        assert response.headers["x-accel-buffering"] == "no"
        events = parse_events(response.text)
        types = [event["type"] for event in events]
        assert types == [
            "session",
            "run_started",
            "model_started",
            "model_completed",
            "tool_started",
            "tool_completed",
            "model_started",
            "model_completed",
            "final",
            "done",
        ]
        assert events[-2]["answer"] == "The answer is 5."


def test_chat_stream_converts_execution_error_to_event():
    class BrokenModel:
        async def complete(self, messages, tools):
            raise ModelUnavailable("offline")

    with tempfile.TemporaryDirectory() as directory:
        app = stream_app(directory)
        app.state.runtime.model = BrokenModel()
        with TestClient(app) as client:
            response = client.post("/v1/chat/stream", json={"message": "hello"})
            events = parse_events(response.text)
            assert events[-2]["type"] == "error"
            assert events[-2]["code"] == "model_unavailable"
            assert events[-1]["type"] == "done"


def test_chat_stream_stops_at_approval_without_exposing_arguments():
    with tempfile.TemporaryDirectory() as directory:
        app = stream_app(directory)
        app.state.runtime.model = FakeModel(
            [
                ModelResponse(
                    tool_calls=[
                        ToolCall(
                            id="shell-1",
                            name="shell_run",
                            arguments={"command": "echo secret"},
                        )
                    ]
                )
            ]
        )
        with TestClient(app) as client:
            response = client.post("/v1/chat/stream", json={"message": "run it"})
            events = parse_events(response.text)
            approval = next(
                event for event in events if event["type"] == "approval_required"
            )
            assert approval["tool_name"] == "shell_run"
            assert "arguments" not in approval
            assert events[-1]["type"] == "done"
            assert all(event["type"] != "tool_started" for event in events)
