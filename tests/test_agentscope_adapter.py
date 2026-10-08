import pytest

from app.models.agentscope_adapter import AgentScopeModelAdapter


class FakeAgentScopeModel:
    async def __call__(self, messages, tools):
        return type(
            "Response",
            (),
            {
                "content": [
                    {"type": "text", "text": "Checking"},
                    {
                        "type": "tool_use",
                        "id": "1",
                        "name": "calculator",
                        "input": {"expression": "2+3"},
                    },
                ],
                "usage": type("Usage", (), {"input_tokens": 10, "output_tokens": 4})(),
            },
        )()


@pytest.mark.asyncio
async def test_agentscope_blocks_convert_to_internal_response():
    adapter = AgentScopeModelAdapter(
        "model", "https://example.com/v1", "key", model_client=FakeAgentScopeModel()
    )
    response = await adapter.complete([{"role": "user", "content": "2+3"}], [])
    assert response.content == "Checking"
    assert response.tool_calls[0].name == "calculator"
    assert response.usage.input_tokens == 10
