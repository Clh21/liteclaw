import re
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.tools.browser.manager import BrowserManager, validate_url


def session_id(context: ToolContext | None) -> str:
    if context is None:
        raise ValueError("Browser tool requires a session")
    return context.session_id


class BrowserOpenArgs(BaseModel):
    url: str


class BrowserOpenTool(BaseTool):
    name = "browser_open"
    description = "Open a public web page and return its title and a text excerpt"
    args_model = BrowserOpenArgs
    timeout_seconds = 60.0

    def __init__(self, manager: BrowserManager):
        self.manager = manager

    async def run(
        self, arguments: BrowserOpenArgs, context: ToolContext | None = None
    ) -> ToolResult:
        url = validate_url(arguments.url, self.manager.allow_private)
        page = await self.manager.page(session_id(context))
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        await self.manager.persist(session_id(context))
        title = await page.title()
        excerpt = (await page.locator("body").inner_text(timeout=10000))[:20000]
        return ToolResult(
            ok=True,
            content=f"Title: {title}\nURL: {page.url}\n{excerpt}",
            data={"title": title, "url": page.url},
        )


class BrowserExtractArgs(BaseModel):
    selector: str | None = None
    max_chars: int = Field(default=20000, ge=1, le=20000)


class BrowserExtractTool(BaseTool):
    name = "browser_extract"
    description = "Extract visible text from the current browser page"
    args_model = BrowserExtractArgs
    timeout_seconds = 60.0

    def __init__(self, manager: BrowserManager):
        self.manager = manager

    async def run(
        self, arguments: BrowserExtractArgs, context: ToolContext | None = None
    ) -> ToolResult:
        page = await self.manager.page(session_id(context))
        locator = page.locator(arguments.selector or "body")
        content = (await locator.inner_text(timeout=30000))[: arguments.max_chars]
        return ToolResult(ok=True, content=content, data={"url": page.url})


class BrowserLocatorArgs(BaseModel):
    selector: str | None = None
    text: str | None = None

    @model_validator(mode="after")
    def require_locator(self):
        if not self.selector and not self.text:
            raise ValueError("selector or text is required")
        return self


class BrowserClickTool(BaseTool):
    name = "browser_click"
    description = "Click an element on the current browser page"
    args_model = BrowserLocatorArgs
    risk_level = "high"
    timeout_seconds = 60.0

    def __init__(self, manager: BrowserManager):
        self.manager = manager

    async def run(
        self, arguments: BrowserLocatorArgs, context: ToolContext | None = None
    ) -> ToolResult:
        page = await self.manager.page(session_id(context))
        locator = (
            page.get_by_text(arguments.text, exact=True)
            if arguments.text
            else page.locator(arguments.selector)
        )
        await locator.click(timeout=30000)
        await self.manager.persist(session_id(context))
        return ToolResult(ok=True, content=f"Clicked element on {page.url}")


class BrowserTypeArgs(BrowserLocatorArgs):
    value: str


class BrowserTypeTool(BaseTool):
    name = "browser_type"
    description = "Type into an input on the current browser page"
    args_model = BrowserTypeArgs
    risk_level = "medium"
    timeout_seconds = 60.0

    def __init__(self, manager: BrowserManager):
        self.manager = manager

    async def run(
        self, arguments: BrowserTypeArgs, context: ToolContext | None = None
    ) -> ToolResult:
        page = await self.manager.page(session_id(context))
        locator = (
            page.get_by_label(arguments.text)
            if arguments.text
            else page.locator(arguments.selector)
        )
        await locator.fill(arguments.value, timeout=30000)
        await self.manager.persist(session_id(context))
        return ToolResult(ok=True, content="Input filled")


class BrowserScreenshotArgs(BaseModel):
    name: str = "screenshot"


class BrowserScreenshotTool(BaseTool):
    name = "browser_screenshot"
    description = "Save a screenshot of the current browser page"
    args_model = BrowserScreenshotArgs
    timeout_seconds = 60.0

    def __init__(self, manager: BrowserManager):
        self.manager = manager

    async def run(
        self, arguments: BrowserScreenshotArgs, context: ToolContext | None = None
    ) -> ToolResult:
        current_session = session_id(context)
        safe_name = (
            re.sub(r"[^A-Za-z0-9_-]", "_", Path(arguments.name).stem)[:80]
            or "screenshot"
        )
        relative = Path("data") / "screenshots" / current_session / f"{safe_name}.png"
        path = self.manager.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        page = await self.manager.page(current_session)
        await page.screenshot(path=str(path), full_page=True)
        return ToolResult(
            ok=True, content=relative.as_posix(), data={"path": relative.as_posix()}
        )
