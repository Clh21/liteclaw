import tempfile
from unittest.mock import AsyncMock

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.tools.browser.manager import BrowserManager
from app.tools.browser.state import BrowserStateStore


class FakePage:
    def is_closed(self):
        return False


class FakeContext:
    def __init__(self, state):
        self.state = state
        self.closed = False

    async def route(self, *_args):
        return None

    async def new_page(self):
        return FakePage()

    async def storage_state(self):
        return self.state

    async def close(self):
        self.closed = True


class FakeBrowser:
    def __init__(self, context):
        self.context = context
        self.kwargs = None

    def is_connected(self):
        return True

    async def new_context(self, **kwargs):
        self.kwargs = kwargs
        return self.context

    async def close(self):
        return None


@pytest.mark.asyncio
async def test_manager_loads_persists_and_resets_state(tmp_path):
    store = BrowserStateStore(tmp_path / "states", Fernet.generate_key().decode())
    original = {"cookies": [{"name": "login", "value": "old"}], "origins": []}
    store.save("session-1", original)
    context = FakeContext(
        {"cookies": [{"name": "login", "value": "new"}], "origins": []}
    )
    browser = FakeBrowser(context)
    manager = BrowserManager(tmp_path, state_store=store)
    manager._browser = browser
    manager._ensure_browser = AsyncMock()

    await manager.page("session-1")
    assert browser.kwargs == {"storage_state": original}

    await manager.persist("session-1")
    assert store.load("session-1")["cookies"][0]["value"] == "new"

    assert await manager.reset("session-1") is True
    assert context.closed is True
    assert store.metadata("session-1")["exists"] is False


def test_browser_state_api_returns_metadata_and_deletes_state():
    key = Fernet.generate_key().decode()
    with tempfile.TemporaryDirectory() as directory:
        app = create_app(
            Settings(
                workspace_root=directory,
                db_path="browser-api.db",
                model_provider="fake",
                tasks_enabled=False,
                browser_state_key=key,
            )
        )
        with TestClient(app) as client:
            session = client.post("/v1/sessions", json={}).json()
            app.state.browser.state_store.save(
                session["id"], {"cookies": [], "origins": []}
            )

            metadata = client.get(f"/v1/browser/sessions/{session['id']}/state").json()
            assert metadata["enabled"] is True
            assert metadata["exists"] is True
            assert "cookies" not in metadata

            deleted = client.delete(
                f"/v1/browser/sessions/{session['id']}/state"
            ).json()
            assert deleted == {"deleted": True}
            assert client.get("/v1/browser/sessions/missing/state").status_code == 404
