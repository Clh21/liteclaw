from pathlib import Path

from pydantic import BaseModel, Field

from app.tools.base import BaseTool, ToolContext, ToolResult


def safe_path(root: Path, relative_path: str) -> Path:
    root = root.resolve()
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ValueError("Path escapes workspace root") from error
    return candidate


class FileReadArgs(BaseModel):
    relative_path: str = Field(min_length=1)
    offset: int = Field(default=0, ge=0)
    max_bytes: int = Field(default=100_000, ge=1, le=100_000)


class FileReadTool(BaseTool):
    name = "file_read"
    description = "Read a UTF-8 file from the configured workspace"
    args_model = FileReadArgs

    def __init__(self, root: Path):
        self.root = root.resolve()

    async def run(
        self, arguments: FileReadArgs, context: ToolContext | None = None
    ) -> ToolResult:
        path = safe_path(self.root, arguments.relative_path)
        with path.open("rb") as stream:
            stream.seek(arguments.offset)
            data = stream.read(arguments.max_bytes)
        return ToolResult(
            ok=True,
            content=data.decode("utf-8", errors="replace"),
            data={"bytes": len(data)},
        )


class FileWriteArgs(BaseModel):
    relative_path: str = Field(min_length=1)
    content: str
    overwrite: bool = False


class FileWriteTool(BaseTool):
    name = "file_write"
    description = "Write a UTF-8 file within the configured workspace"
    args_model = FileWriteArgs
    risk_level = "medium"

    def __init__(self, root: Path):
        self.root = root.resolve()

    def risk_level_for(self, arguments: dict) -> str:
        return "high" if arguments.get("overwrite") else "medium"

    async def run(
        self, arguments: FileWriteArgs, context: ToolContext | None = None
    ) -> ToolResult:
        path = safe_path(self.root, arguments.relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        mode = "w" if arguments.overwrite else "x"
        with path.open(mode, encoding="utf-8") as stream:
            stream.write(arguments.content)
        return ToolResult(ok=True, content=f"Wrote {path.relative_to(self.root)}")
