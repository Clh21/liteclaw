import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.tools.desktop.manager import DesktopManager


def _session(context: ToolContext | None) -> str:
    if context is None:
        raise ValueError("Desktop tool requires a session")
    return context.session_id


class DesktopInfoArgs(BaseModel):
    pass


class DesktopInfoTool(BaseTool):
    name = "desktop_info"
    description = "Return primary screen size and current pointer coordinates"
    args_model = DesktopInfoArgs

    def __init__(self, manager: DesktopManager):
        self.manager = manager

    async def run(self, arguments, context=None) -> ToolResult:
        info = await self.manager.info()
        return ToolResult(ok=True, content="Desktop information retrieved", data=info)


class DesktopScreenshotArgs(BaseModel):
    name: str = Field(default="desktop", min_length=1, max_length=100)


class DesktopScreenshotTool(BaseTool):
    name = "desktop_screenshot"
    description = "Save a screenshot of the primary desktop after approval"
    args_model = DesktopScreenshotArgs
    risk_level = "high"

    def __init__(self, manager: DesktopManager):
        self.manager = manager

    async def run(self, arguments: DesktopScreenshotArgs, context=None) -> ToolResult:
        session = _session(context)
        safe_name = re.sub(r"[^A-Za-z0-9_-]", "_", Path(arguments.name).stem)[:80]
        relative = (
            Path("data")
            / "desktop_screenshots"
            / session
            / f"{safe_name or 'desktop'}.png"
        )
        path = self.manager.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        await self.manager.screenshot(path)
        return ToolResult(
            ok=True, content=relative.as_posix(), data={"path": relative.as_posix()}
        )


class DesktopClickArgs(BaseModel):
    x: int = Field(ge=0, le=32767)
    y: int = Field(ge=0, le=32767)
    button: Literal["left", "middle", "right"] = "left"
    clicks: int = Field(default=1, ge=1, le=3)


class DesktopClickTool(BaseTool):
    name = "desktop_click"
    description = "Click primary-screen coordinates after approval"
    args_model = DesktopClickArgs
    risk_level = "high"

    def __init__(self, manager: DesktopManager):
        self.manager = manager

    async def run(self, arguments: DesktopClickArgs, context=None) -> ToolResult:
        await self.manager.click(
            arguments.x, arguments.y, arguments.button, arguments.clicks
        )
        return ToolResult(ok=True, content="Desktop click completed")


class DesktopTypeArgs(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    interval: float = Field(default=0.01, ge=0, le=1)


class DesktopTypeTool(BaseTool):
    name = "desktop_type"
    description = "Type text into the focused desktop application after approval"
    args_model = DesktopTypeArgs
    risk_level = "high"

    def __init__(self, manager: DesktopManager):
        self.manager = manager

    async def run(self, arguments: DesktopTypeArgs, context=None) -> ToolResult:
        await self.manager.write(arguments.text, arguments.interval)
        return ToolResult(ok=True, content="Desktop text input completed")


class DesktopHotkeyArgs(BaseModel):
    keys: list[str] = Field(min_length=1, max_length=5)


class DesktopHotkeyTool(BaseTool):
    name = "desktop_hotkey"
    description = "Press a desktop key combination after approval"
    args_model = DesktopHotkeyArgs
    risk_level = "high"

    def __init__(self, manager: DesktopManager):
        self.manager = manager

    async def run(self, arguments: DesktopHotkeyArgs, context=None) -> ToolResult:
        keys = [key.casefold() for key in arguments.keys]
        if any(not re.fullmatch(r"[a-z0-9_+\-]{1,20}", key) for key in keys):
            raise ValueError("Invalid desktop hotkey")
        await self.manager.hotkey(keys)
        return ToolResult(ok=True, content="Desktop hotkey completed")


class DesktopScrollArgs(BaseModel):
    amount: int = Field(ge=-100, le=100)


class DesktopScrollTool(BaseTool):
    name = "desktop_scroll"
    description = "Scroll the focused desktop application after approval"
    args_model = DesktopScrollArgs
    risk_level = "high"

    def __init__(self, manager: DesktopManager):
        self.manager = manager

    async def run(self, arguments: DesktopScrollArgs, context=None) -> ToolResult:
        await self.manager.scroll(arguments.amount)
        return ToolResult(ok=True, content="Desktop scroll completed")
