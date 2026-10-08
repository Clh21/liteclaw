import httpx
import pytest

from app.models.openai_compatible import OpenAICompatibleModel


@pytest.mark.asyncio
async def test_openai_compatible_parses_tool_call_and_usage():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "function": {
                                        "name": "calculator",
                                        "arguments": '{"expression":"2+3"}',
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 4},
            },
        )

    factory = lambda timeout: httpx.AsyncClient(
        transport=httpx.MockTransport(handler), timeout=timeout
    )
    model = OpenAICompatibleModel(
        "test", "https://provider.example/v1", "secret", client_factory=factory
    )
    response = await model.complete([{"role": "user", "content": "2+3"}], [])
    assert response.tool_calls[0].arguments == {"expression": "2+3"}
    assert response.usage.input_tokens == 12
    assert requests[0].url.path == "/v1/chat/completions"
