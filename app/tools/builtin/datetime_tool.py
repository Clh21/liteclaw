from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from app.tools.base import BaseTool, ToolContext, ToolResult


class DateTimeArgs(BaseModel):
    timezone: str = "UTC"


class DateTimeTool(BaseTool):
    name = "datetime_now"
    description = "Return the current ISO 8601 time in a timezone"
    args_model = DateTimeArgs

    async def run(
        self, arguments: DateTimeArgs, context: ToolContext | None = None
    ) -> ToolResult:
        value = datetime.now(ZoneInfo(arguments.timezone)).isoformat()
        return ToolResult(ok=True, content=value)
