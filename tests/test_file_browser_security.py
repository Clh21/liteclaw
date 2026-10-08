import asyncio
import tempfile
from pathlib import Path

import pytest

from app.tools.browser.manager import validate_url
from app.tools.builtin.file_tools import FileReadTool, FileWriteTool


def test_file_read_rejects_parent_escape():
    with tempfile.TemporaryDirectory() as directory:
        tool = FileReadTool(Path(directory))
        result = asyncio.run(tool.execute({"relative_path": "../outside.txt"}))
        assert result.ok is False


def test_file_write_does_not_overwrite_without_flag():
    with tempfile.TemporaryDirectory() as directory:
        tool = FileWriteTool(Path(directory))
        first = asyncio.run(
            tool.execute({"relative_path": "note.txt", "content": "first"})
        )
        second = asyncio.run(
            tool.execute({"relative_path": "note.txt", "content": "second"})
        )
        assert first.ok is True
        assert second.ok is False


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://127.0.0.1:8080",
        "http://localhost",
        "http://192.168.1.1",
    ],
)
def test_browser_rejects_unsafe_urls(url):
    with pytest.raises(ValueError):
        validate_url(url)


def test_browser_accepts_public_https_url():
    assert validate_url("https://example.com/path") == "https://example.com/path"
