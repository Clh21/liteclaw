import asyncio
from pathlib import Path

from pydantic import BaseModel, Field

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.tools.builtin.file_tools import safe_path


class ShellArgs(BaseModel):
    command: str = Field(min_length=1, max_length=2000)
    cwd: str = "."


class ShellRunTool(BaseTool):
    name = "shell_run"
    description = "Run a shell command inside the workspace after approval"
    args_model = ShellArgs
    risk_level = "high"

    def __init__(self, root: Path):
        self.root = root.resolve()

    async def run(
        self, arguments: ShellArgs, context: ToolContext | None = None
    ) -> ToolResult:
        cwd = safe_path(self.root, arguments.cwd)
        process = await asyncio.create_subprocess_shell(
            arguments.command,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), 25)
        except asyncio.TimeoutError:
            process.kill()
            await process.communicate()
            return ToolResult(ok=False, content="Command timed out", error="timeout")
        output = (stdout + b"\n" + stderr).decode("utf-8", errors="replace")[:20000]
        return ToolResult(
            ok=process.returncode == 0,
            content=output,
            data={"exit_code": process.returncode},
        )
