import asyncio
import hashlib
import re
from time import perf_counter
from typing import Any

from app.tools.base import BaseTool, ToolContext, ToolResult


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, BaseTool] = {}
        self._model_names: dict[str, str] = {}

    def register(self, tool: BaseTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        model_name = self.model_name(tool.name)
        if model_name in self._model_names:
            raise ValueError(f"Model tool name collision: {model_name}")
        self._tools[tool.name] = tool
        self._model_names[model_name] = tool.name

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name) or self._tools.get(self._model_names.get(name, ""))

    @staticmethod
    def model_name(name: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9_-]", "_", name)
        if len(safe) > 64:
            safe = safe[:55] + "_" + hashlib.sha256(name.encode()).hexdigest()[:8]
        return safe

    def schemas_for_model(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": self.model_name(tool.name),
                    "description": tool.description,
                    "parameters": tool.definition.input_schema,
                },
            }
            for tool in self._tools.values()
        ]

    async def execute(
        self, name: str, arguments: dict[str, Any], context: ToolContext | None = None
    ) -> ToolResult:
        tool = self.get(name)
        if tool is None:
            return ToolResult(
                ok=False, content=f"Unknown tool: {name}", error="tool_not_found"
            )
        started = perf_counter()
        try:
            result = await asyncio.wait_for(
                tool.execute(arguments, context), tool.timeout_seconds
            )
        except asyncio.TimeoutError:
            result = ToolResult(ok=False, content="Tool timed out", error="timeout")
        result.elapsed_ms = round((perf_counter() - started) * 1000)
        return result
