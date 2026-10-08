from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel


class ToolResult(BaseModel):
    ok: bool
    content: str
    data: dict[str, Any] | None = None
    error: str | None = None
    elapsed_ms: int = 0


class ToolDefinition(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]
    risk_level: Literal["low", "medium", "high"] = "low"
    source: str = "builtin"


@dataclass
class ToolContext:
    session_id: str
    workspace_root: Path


class BaseTool:
    name: str
    description: str
    args_model: type[BaseModel]
    risk_level: Literal["low", "medium", "high"] = "low"
    source: str = "builtin"
    timeout_seconds: float = 30.0

    def risk_level_for(
        self, arguments: dict[str, Any]
    ) -> Literal["low", "medium", "high"]:
        return self.risk_level

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            input_schema=self.args_model.model_json_schema(),
            risk_level=self.risk_level,
            source=self.source,
        )

    async def run(
        self, arguments: BaseModel, context: ToolContext | None = None
    ) -> ToolResult:
        raise NotImplementedError

    async def execute(
        self, arguments: dict[str, Any], context: ToolContext | None = None
    ) -> ToolResult:
        from pydantic import ValidationError

        try:
            validated = self.args_model.model_validate(arguments)
            return await self.run(validated, context)
        except ValidationError as error:
            return ToolResult(
                ok=False,
                content="Invalid tool arguments",
                error="validation_error",
                data={"details": error.errors(include_url=False)},
            )
        except Exception as error:  # noqa: BLE001 - Tool faults become observations, never process crashes.
            return ToolResult(ok=False, content=str(error), error=type(error).__name__)
