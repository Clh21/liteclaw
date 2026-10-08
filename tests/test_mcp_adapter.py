import pytest

from app.tools.mcp.adapter import MCPToolAdapter
from app.tools.registry import ToolRegistry


class FakeMCPClient:
    def __init__(self):
        self.calls = []

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return type(
            "Result",
            (),
            {
                "content": [type("Text", (), {"text": "hello"})()],
                "is_error": False,
                "structured_content": None,
            },
        )()


@pytest.mark.asyncio
async def test_mcp_tool_is_namespaced_and_preserves_schema():
    client = FakeMCPClient()
    tool = type(
        "Tool",
        (),
        {
            "name": "echo",
            "description": "Echo input",
            "input_schema": {
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
            },
        },
    )()
    registry = ToolRegistry()
    registry.register(MCPToolAdapter("local", client, tool))
    assert registry.schemas_for_model()[0]["function"]["name"] == "mcp_local_echo"
    assert registry.get("mcp.local.echo") is not None
    result = await registry.execute("mcp_local_echo", {"value": "hello"})
    assert result.ok is True
    assert result.content == "hello"
    assert client.calls == [("echo", {"value": "hello"})]


@pytest.mark.asyncio
async def test_mcp_arguments_follow_server_schema():
    client = FakeMCPClient()
    tool = type(
        "Tool",
        (),
        {
            "name": "echo",
            "description": "",
            "input_schema": {
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
            },
        },
    )()
    result = await MCPToolAdapter("local", client, tool).execute({"value": 5})
    assert result.error == "validation_error"
    assert client.calls == []
