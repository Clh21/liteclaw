import asyncio
import json

import httpx

from app.core.messages import ModelResponse, ToolCall, Usage


class ModelUnavailable(Exception):
    pass


class ModelAuthError(Exception):
    pass


class OpenAICompatibleModel:
    def __init__(
        self,
        model: str,
        base_url: str,
        api_key: str,
        timeout: float = 30.0,
        client_factory=None,
    ):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.client_factory = client_factory or httpx.AsyncClient

    async def complete(self, messages: list[dict], tools: list[dict]) -> ModelResponse:
        if not self.api_key:
            raise ModelAuthError("LITECLAW_API_KEY is empty")
        payload = {"model": self.model, "messages": messages}
        if tools:
            payload["tools"] = tools
        async with self.client_factory(timeout=self.timeout) as client:
            for attempt in range(3):
                try:
                    response = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        json=payload,
                    )
                    if response.status_code in (401, 403):
                        raise ModelAuthError("Model authentication failed")
                    if (
                        response.status_code == 429 or response.status_code >= 500
                    ) and attempt < 2:
                        await asyncio.sleep(0.5 * 2**attempt)
                        continue
                    response.raise_for_status()
                    body = response.json()
                    choice = body["choices"][0]
                    message = choice["message"]
                    content = message.get("content")
                    if isinstance(content, list):
                        content = "".join(
                            part.get("text", "")
                            for part in content
                            if isinstance(part, dict)
                        )
                    calls = []
                    for call in message.get("tool_calls") or []:
                        function = call["function"]
                        try:
                            arguments = json.loads(function.get("arguments") or "{}")
                        except json.JSONDecodeError:
                            arguments = {
                                "_malformed_arguments": function.get("arguments")
                            }
                        calls.append(
                            ToolCall(
                                id=call["id"],
                                name=function["name"],
                                arguments=arguments,
                            )
                        )
                    raw_usage = body.get("usage") or {}
                    return ModelResponse(
                        content=content,
                        tool_calls=calls,
                        usage=Usage(
                            input_tokens=raw_usage.get("prompt_tokens", 0),
                            output_tokens=raw_usage.get("completion_tokens", 0),
                        ),
                        finish_reason=choice.get("finish_reason"),
                    )
                except (httpx.TimeoutException, httpx.ConnectError) as error:
                    if attempt == 2:
                        raise ModelUnavailable(str(error)) from error
                    await asyncio.sleep(0.5 * 2**attempt)
                except httpx.HTTPStatusError as error:
                    raise ModelUnavailable(
                        f"Model HTTP {error.response.status_code}"
                    ) from error
        raise ModelUnavailable("Model request failed after retries")
