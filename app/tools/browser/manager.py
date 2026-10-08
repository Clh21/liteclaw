import ipaddress
import socket
from pathlib import Path
from urllib.parse import urlsplit


def validate_url(url: str, allow_private: bool = False) -> str:
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError("Only public http/https URLs are allowed")
    hostname = parsed.hostname.casefold().strip(".")
    if not allow_private:
        if hostname == "localhost" or hostname.endswith(".localhost"):
            raise ValueError("Local URLs are blocked")
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            raise ValueError("Private addresses are blocked")
    return url


class BrowserManager:
    def __init__(self, root: Path, headless: bool = True, allow_private: bool = False):
        self.root = root
        self.headless = headless
        self.allow_private = allow_private
        self._playwright = None
        self._browser = None
        self._contexts: dict[str, object] = {}
        self._pages: dict[str, object] = {}

    async def _ensure_browser(self):
        if self._browser is None or not self._browser.is_connected():
            from playwright.async_api import async_playwright

            self._contexts.clear()
            self._pages.clear()
            if self._playwright is None:
                self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=self.headless
            )

    async def page(self, session_id: str):
        await self._ensure_browser()
        page = self._pages.get(session_id)
        if page is None or page.is_closed():
            context = await self._browser.new_context()
            await context.route("**/*", self._guard_request)
            page = await context.new_page()
            self._contexts[session_id] = context
            self._pages[session_id] = page
        return page

    async def _guard_request(self, route):
        try:
            url = validate_url(route.request.url, self.allow_private)
            if not self.allow_private:
                host = urlsplit(url).hostname
                for address in await __import__("asyncio").to_thread(
                    socket.getaddrinfo, host, None
                ):
                    if not ipaddress.ip_address(address[4][0]).is_global:
                        raise ValueError("Private resolved address is blocked")
        except (ValueError, OSError):
            await route.abort()
        else:
            await route.continue_()

    async def close(self):
        for context in self._contexts.values():
            await context.close()
        if self._browser is not None:
            await self._browser.close()
        if self._playwright is not None:
            await self._playwright.stop()
