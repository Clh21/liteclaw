import asyncio
import platform
from pathlib import Path


class DesktopUnavailable(RuntimeError):
    pass


class DesktopManager:
    def __init__(self, root: Path, enabled: bool = False, backend=None, clipboard=None):
        self.root = Path(root).resolve()
        self.enabled = enabled
        self._backend_instance = backend
        self._clipboard_instance = clipboard
        self.status = (
            "ready" if backend is not None else ("enabled" if enabled else "disabled")
        )

    def _backend(self):
        if not self.enabled:
            raise DesktopUnavailable("Desktop tools are disabled")
        if self._backend_instance is None:
            try:
                import pyautogui
            except Exception as error:
                self.status = "unavailable"
                raise DesktopUnavailable(
                    "Desktop backend unavailable; install the desktop extra"
                ) from error
            pyautogui.FAILSAFE = True
            self._backend_instance = pyautogui
            self.status = "ready"
        return self._backend_instance

    @staticmethod
    def _pair(value) -> tuple[int, int]:
        if hasattr(value, "x") and hasattr(value, "y"):
            return int(value.x), int(value.y)
        return int(value[0]), int(value[1])

    async def info(self) -> dict:
        backend = self._backend()
        size, pointer = await asyncio.gather(
            asyncio.to_thread(backend.size),
            asyncio.to_thread(backend.position),
        )
        width, height = self._pair(size)
        pointer_x, pointer_y = self._pair(pointer)
        return {
            "width": width,
            "height": height,
            "pointer_x": pointer_x,
            "pointer_y": pointer_y,
        }

    async def screenshot(self, path: Path) -> None:
        backend = self._backend()
        image = await asyncio.to_thread(backend.screenshot)
        await asyncio.to_thread(image.save, path)

    async def click(self, x: int, y: int, button: str, clicks: int) -> None:
        backend = self._backend()
        width, height = self._pair(await asyncio.to_thread(backend.size))
        if x >= width or y >= height:
            raise ValueError("Desktop coordinates are outside the primary screen")
        await asyncio.to_thread(backend.click, x=x, y=y, button=button, clicks=clicks)

    async def write(self, text: str, interval: float) -> None:
        backend = self._backend()
        if text.isascii():
            await asyncio.to_thread(backend.write, text, interval=interval)
            return
        clipboard = self._clipboard_instance
        if clipboard is None:
            import pyperclip

            clipboard = pyperclip
        previous = await asyncio.to_thread(clipboard.paste)
        try:
            await asyncio.to_thread(clipboard.copy, text)
            modifier = "command" if platform.system() == "Darwin" else "ctrl"
            await asyncio.to_thread(backend.hotkey, modifier, "v")
            await asyncio.sleep(0.1)
        finally:
            await asyncio.to_thread(clipboard.copy, previous)

    async def hotkey(self, keys: list[str]) -> None:
        await asyncio.to_thread(self._backend().hotkey, *keys)

    async def scroll(self, amount: int) -> None:
        await asyncio.to_thread(self._backend().scroll, amount)
