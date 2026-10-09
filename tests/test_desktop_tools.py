from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.tools.base import ToolContext
from app.tools.desktop.manager import DesktopManager
from app.tools.desktop.tools import (
    DesktopClickTool,
    DesktopHotkeyTool,
    DesktopInfoTool,
    DesktopScreenshotTool,
    DesktopScrollTool,
    DesktopTypeTool,
)


class FakeImage:
    def save(self, path):
        Path(path).write_bytes(b"fake-png")


class FakeBackend:
    def __init__(self):
        self.calls = []

    def size(self):
        return (1920, 1080)

    def position(self):
        return (120, 240)

    def screenshot(self):
        self.calls.append(("screenshot",))
        return FakeImage()

    def click(self, **kwargs):
        self.calls.append(("click", kwargs))

    def write(self, text, interval=0):
        self.calls.append(("write", text, interval))

    def hotkey(self, *keys):
        self.calls.append(("hotkey", keys))

    def scroll(self, amount):
        self.calls.append(("scroll", amount))


class FakeClipboard:
    def __init__(self):
        self.value = "original clipboard"
        self.copies = []

    def paste(self):
        return self.value

    def copy(self, value):
        self.value = value
        self.copies.append(value)


@pytest.mark.asyncio
async def test_desktop_tools_use_backend_and_keep_sensitive_output_minimal(tmp_path):
    backend = FakeBackend()
    manager = DesktopManager(tmp_path, enabled=True, backend=backend)
    context = ToolContext("session-1", tmp_path)

    info = await DesktopInfoTool(manager).execute({}, context)
    screenshot = await DesktopScreenshotTool(manager).execute(
        {"name": "../../desk view"}, context
    )
    clicked = await DesktopClickTool(manager).execute({"x": 20, "y": 30}, context)
    typed = await DesktopTypeTool(manager).execute(
        {"text": "private text", "interval": 0.01}, context
    )
    hotkey = await DesktopHotkeyTool(manager).execute({"keys": ["ctrl", "s"]}, context)
    scrolled = await DesktopScrollTool(manager).execute({"amount": -3}, context)

    assert info.data == {
        "width": 1920,
        "height": 1080,
        "pointer_x": 120,
        "pointer_y": 240,
    }
    assert screenshot.data["path"].startswith("data/desktop_screenshots/session-1/")
    assert (tmp_path / screenshot.data["path"]).read_bytes() == b"fake-png"
    assert all(result.ok for result in (clicked, typed, hotkey, scrolled))
    assert "private text" not in typed.content
    assert backend.calls[-4:] == [
        ("click", {"x": 20, "y": 30, "button": "left", "clicks": 1}),
        ("write", "private text", 0.01),
        ("hotkey", ("ctrl", "s")),
        ("scroll", -3),
    ]


def test_desktop_sensitive_tools_are_high_risk(tmp_path):
    manager = DesktopManager(tmp_path, enabled=True, backend=FakeBackend())
    assert DesktopInfoTool(manager).risk_level == "low"
    assert all(
        tool(manager).risk_level == "high"
        for tool in (
            DesktopScreenshotTool,
            DesktopClickTool,
            DesktopTypeTool,
            DesktopHotkeyTool,
            DesktopScrollTool,
        )
    )


@pytest.mark.asyncio
async def test_desktop_type_uses_and_restores_clipboard_for_unicode(tmp_path):
    backend = FakeBackend()
    clipboard = FakeClipboard()
    manager = DesktopManager(
        tmp_path, enabled=True, backend=backend, clipboard=clipboard
    )

    result = await DesktopTypeTool(manager).execute(
        {"text": "你好"}, ToolContext("session-1", tmp_path)
    )

    assert result.ok is True
    assert ("hotkey", ("ctrl", "v")) in backend.calls
    assert clipboard.copies == ["你好", "original clipboard"]
    assert clipboard.value == "original clipboard"


def test_desktop_tools_register_only_when_explicitly_enabled(tmp_path):
    disabled = create_app(
        Settings(
            workspace_root=tmp_path,
            db_path="disabled.db",
            model_provider="fake",
            tasks_enabled=False,
            desktop_enabled=False,
        )
    )
    enabled = create_app(
        Settings(
            workspace_root=tmp_path,
            db_path="enabled.db",
            model_provider="fake",
            tasks_enabled=False,
            desktop_enabled=True,
        )
    )

    assert disabled.state.registry.get("desktop_click") is None
    assert enabled.state.registry.get("desktop_click") is not None
    with TestClient(enabled) as client:
        assert client.get("/health").json()["desktop"] == "enabled"
