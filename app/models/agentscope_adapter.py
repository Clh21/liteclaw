from app.core.messages import ModelResponse, ToolCall, Usage
from app.models.openai_compatible import ModelAuthError


class AgentScopeModelAdapter:
    """Isolates AgentScope 1.x model API from LiteClaw's runtime interface."""

    def __init__(self, model: str, base_url: str, api_key: str, model_client=None):
        if model_client is None:
            if not api_key:
                raise ModelAuthError("LITECLAW_API_KEY is empty")
            from agentscope.model import OpenAIChatModel

            model_client = OpenAIChatModel(
                model_name=model,
                api_key=api_key,
                stream=False,
                client_kwargs={"base_url": base_url},
            )
        self.client = model_client

    async def complete(self, messages: list[dict], tools: list[dict]) -> ModelResponse:
        response = await self.client(messages=messages, tools=tools)
        text = []
        calls = []
        for block in response.content or []:
            if block.get("type") == "text":
                text.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                calls.append(
                    ToolCall(
                        id=block["id"],
                        name=block["name"],
                        arguments=block.get("input") or {},
                    )
                )
        raw_usage = response.usage
        usage = Usage(
            input_tokens=getattr(raw_usage, "input_tokens", 0) or 0,
            output_tokens=getattr(raw_usage, "output_tokens", 0) or 0,
        )
        return ModelResponse(
            content="".join(text) or None, tool_calls=calls, usage=usage
        )
