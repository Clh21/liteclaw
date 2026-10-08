import json
import re
from collections import deque
from uuid import uuid4

from app.core.messages import ModelResponse, ToolCall


class FakeModel:
    """Scripted responses for tests, with a small offline calculator demo mode."""

    def __init__(self, responses: list[ModelResponse] | None = None):
        self.responses = deque(responses or [])
        self.seen_messages: list[list[dict]] = []

    async def complete(self, messages: list[dict], tools: list[dict]) -> ModelResponse:
        self.seen_messages.append([message.copy() for message in messages])
        if self.responses:
            return self.responses.popleft()
        last = messages[-1]
        if any(
            "Break the request into" in (message.get("content") or "")
            for message in messages
            if message["role"] == "system"
        ):
            pieces = [
                piece.strip()
                for piece in re.split(
                    r"\s+and\s+|然后|并且",
                    last.get("content") or "",
                    flags=re.IGNORECASE,
                )
                if piece.strip()
            ]
            tasks = [
                {
                    "id": f"t{index}",
                    "goal": piece,
                    "depends_on": [f"t{index - 1}"] if index > 1 else [],
                }
                for index, piece in enumerate(pieces[:5], 1)
            ]
            return ModelResponse(content=json.dumps({"tasks": tasks}))
        if any(
            "Synthesize the worker results" in (message.get("content") or "")
            for message in messages
            if message["role"] == "system"
        ):
            payload = json.loads(last.get("content") or "{}")
            return ModelResponse(
                content="\n".join(item["answer"] for item in payload.get("results", []))
            )
        if last["role"] == "tool":
            try:
                observation = json.loads(last["content"] or "{}")
            except json.JSONDecodeError:
                return ModelResponse(content=last["content"])
            if observation.get("ok") and isinstance(observation.get("data"), dict):
                value = observation["data"].get("value")
                if value is not None:
                    return ModelResponse(content=f"The answer is {value}.")
            return ModelResponse(content=observation.get("content") or last["content"])
        text = last.get("content") or ""
        for message in messages:
            if message["role"] == "system" and "Relevant memories:" in (
                message.get("content") or ""
            ):
                return ModelResponse(
                    content=message["content"].split("Relevant memories:\n", 1)[-1]
                )
        expression = re.search(r"[-+*/().\d\s]+", text)
        if expression and any(char.isdigit() for char in expression.group()):
            candidate = expression.group().strip()
            if len(candidate) >= 3 and any(
                operator in candidate for operator in "+-*/"
            ):
                return ModelResponse(
                    tool_calls=[
                        ToolCall(
                            id=f"fake-{uuid4().hex}",
                            name="calculator",
                            arguments={"expression": candidate},
                        )
                    ]
                )
        return ModelResponse(content=f"FakeModel: {text}")
