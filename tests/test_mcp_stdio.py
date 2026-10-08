import sys
import tempfile
from pathlib import Path

import pytest

from app.tools.mcp.client import MCPClientManager
from app.tools.registry import ToolRegistry


@pytest.mark.asyncio
async def test_stdio_mcp_discovery_and_call():
    script = Path(__file__).resolve().parents[1] / "scripts" / "demo_mcp_server.py"
    with tempfile.TemporaryDirectory() as directory:
        config = Path(directory) / "mcp_servers.yaml"
        config.write_text(
            "mcp_servers:\n  demo:\n    transport: stdio\n    command: '"
            + sys.executable.replace("\\", "/")
            + "'\n    args: ['"
            + script.as_posix()
            + "']\n",
            encoding="utf-8",
        )
        manager = MCPClientManager(config)
        registry = ToolRegistry()
        try:
            await manager.start(registry)
            assert manager.status["demo"] == "ready"
            result = await registry.execute("mcp.demo.echo", {"message": "hello"})
            assert result.ok is True
            assert "hello" in result.content
        finally:
            await manager.close()


@pytest.mark.asyncio
async def test_documented_mcp_example_config_starts():
    project = Path(__file__).resolve().parents[1]
    config = project / "mcp_servers.example.yaml"
    manager = MCPClientManager(config)
    registry = ToolRegistry()
    try:
        await manager.start(registry)
        assert manager.status["demo"] == "ready"
    finally:
        await manager.close()
