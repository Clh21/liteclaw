import asyncio
import sys
from contextlib import AsyncExitStack
from pathlib import Path

import yaml
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.logging import get_logger
from app.tools.mcp.adapter import MCPToolAdapter
from app.tools.registry import ToolRegistry


class MCPClientManager:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.stack = AsyncExitStack()
        self.clients: dict[str, ClientSession] = {}
        self.status: dict[str, str] = {}

    async def start(self, registry: ToolRegistry) -> None:
        if not self.config_path.exists():
            return
        config = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        for name, definition in (config.get("mcp_servers") or {}).items():
            if not definition.get("enabled", True):
                continue
            if definition.get("transport", "stdio") != "stdio":
                self.status[name] = "unsupported_transport"
                continue
            try:
                workspace = self.config_path.resolve().parent.as_posix()
                replacements = {"python": sys.executable, "workspace": workspace}
                command = str(definition["command"]).format_map(replacements)
                args = [
                    str(value).format_map(replacements)
                    for value in definition.get("args", [])
                ]
                parameters = StdioServerParameters(
                    command=command,
                    args=args,
                    cwd=definition.get("cwd"),
                    env=definition.get("env"),
                )
                read, write = await self.stack.enter_async_context(
                    stdio_client(parameters)
                )
                client = await self.stack.enter_async_context(
                    ClientSession(read, write)
                )
                await asyncio.wait_for(client.initialize(), 15)
                discovered = await asyncio.wait_for(client.list_tools(), 15)
                for tool in discovered.tools:
                    registry.register(MCPToolAdapter(name, client, tool))
                self.clients[name] = client
                self.status[name] = "ready"
            except Exception as error:  # noqa: BLE001 - One MCP server cannot block application startup.
                self.status[name] = "unavailable"
                get_logger(__name__).warning(
                    "mcp.unavailable", server=name, error=str(error)
                )

    async def close(self) -> None:
        await self.stack.aclose()
