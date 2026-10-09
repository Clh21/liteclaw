import json

import pytest

from app.config import Settings
from app.core.messages import ModelResponse, ToolCall
from app.model_doctor import diagnose_model
from app.models.fake import FakeModel


@pytest.mark.asyncio
async def test_model_doctor_reports_missing_key_without_calling_model(tmp_path):
    model = FakeModel([ModelResponse(content="must remain unused")])
    report = await diagnose_model(
        Settings(
            workspace_root=tmp_path,
            model_provider="openai_compatible",
            api_key="",
            tasks_enabled=False,
        ),
        model,
    )

    assert report["ok"] is False
    assert report["checks"]["configuration"] == {
        "ok": False,
        "reason": "api_key_missing",
    }
    assert model.seen_messages == []


@pytest.mark.asyncio
async def test_model_doctor_checks_chat_tools_and_structured_output_without_secrets(
    tmp_path,
):
    secret = "doctor-secret-value"
    model = FakeModel(
        [
            ModelResponse(content="OK"),
            ModelResponse(
                tool_calls=[
                    ToolCall(
                        id="doctor-tool",
                        name="calculator",
                        arguments={"expression": "2+3"},
                    )
                ]
            ),
            ModelResponse(
                content=(
                    '```json\n{"memories":[{"content":"Prefers dark mode",'
                    '"kind":"preference","importance":0.8}]}\n```'
                )
            ),
        ]
    )
    report = await diagnose_model(
        Settings(
            workspace_root=tmp_path,
            model_provider="openai_compatible",
            model="qwen-plus",
            base_url="https://provider.example/v1",
            api_key=secret,
            tasks_enabled=False,
        ),
        model,
    )

    assert report["ok"] is True
    assert all(check["ok"] for check in report["checks"].values())
    assert report["api_key_configured"] is True
    assert secret not in json.dumps(report)
