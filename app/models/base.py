from typing import Protocol

from app.core.messages import ModelResponse


class BaseChatModel(Protocol):
    async def complete(
        self, messages: list[dict], tools: list[dict]
    ) -> ModelResponse: ...
