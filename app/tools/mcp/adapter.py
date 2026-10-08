import json
from time import perf_counter
from typing import Any

import jsonschema

from app.tools.base import BaseTool, ToolContext, ToolDefinition, ToolResult


class MCPToolAdapter(BaseTool):
    source = "mcp"
    risk_level = "high"

    def __init__(self, server_name: str, client: Any, tool: Any):
        self.name = f"mcp.{server_name}.{tool.name}"
        self.remote_name = tool.name
        self.description = tool.description or f"MCP tool from {server_name}"
        self.schema = getattr(tool, "input_schema", None) or tool.inputSchema
        self.client = client

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            input_schema=self.schema,
            risk_level=self.risk_level,
            source=self.source,
        )

    async def execute(
        self, arguments: dict[str, Any], context: ToolContext | None = None
    ) -> ToolResult:
        started = perf_counter()
        try:
            jsonschema.validate(arguments, self.schema)
        except jsonschema.ValidationError as error:
            return ToolResult(ok=False, content=error.message, error="validation_error")
        try:
            result = await self.client.call_tool(self.remote_name, arguments)
            content = "\n".join(
                getattr(
                    block,
                    "text",
                    json.dumps(block.model_dump(), ensure_ascii=False)
                    if hasattr(block, "model_dump")
                    else str(block),
                )
                for block in result.content
            )
            return ToolResult(
                ok=not getattr(result, "is_error", getattr(result, "isError", False)),
                content=content[:20000],
                data=getattr(result, "structured_content", None)
                or getattr(result, "structuredContent", None),
                error="mcp_tool_error"
                if getattr(result, "is_error", getattr(result, "isError", False))
                else None,
                elapsed_ms=round((perf_counter() - started) * 1000),
            )
        except Exception as error:  # noqa: BLE001 - A remote MCP tool can fail in arbitrary ways.
            return ToolResult(
                ok=False,
                content=str(error),
                error="mcp_unavailable",
                elapsed_ms=round((perf_counter() - started) * 1000),
            )
