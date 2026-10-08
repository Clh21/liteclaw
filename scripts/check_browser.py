import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.tools.base import ToolContext
from app.tools.browser.manager import BrowserManager
from app.tools.browser.tools import BrowserOpenTool


async def main():
    manager = BrowserManager(Path.cwd())
    try:
        result = await BrowserOpenTool(manager).execute(
            {"url": "https://example.com"}, ToolContext("demo", Path.cwd())
        )
        print(result.model_dump_json())
        if not result.ok:
            raise SystemExit(1)
    finally:
        await manager.close()


if __name__ == "__main__":
    asyncio.run(main())
