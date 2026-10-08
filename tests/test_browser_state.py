import json

from cryptography.fernet import Fernet

from app.tools.browser.state import BrowserStateStore


def test_browser_state_is_encrypted_and_round_trips(tmp_path):
    store = BrowserStateStore(tmp_path, Fernet.generate_key().decode())
    state = {"cookies": [{"name": "session", "value": "top-secret"}], "origins": []}

    store.save("session-1", state)

    raw = (tmp_path / "session-1.state").read_bytes()
    assert b"top-secret" not in raw
    assert store.load("session-1") == state
    metadata = store.metadata("session-1")
    assert metadata["exists"] is True
    assert metadata["updated_at"] is not None


def test_browser_state_corruption_falls_back_and_is_removed(tmp_path):
    store = BrowserStateStore(tmp_path, Fernet.generate_key().decode())
    path = tmp_path / "session-2.state"
    tmp_path.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not-encrypted-state")

    assert store.load("session-2") is None
    assert not path.exists()


def test_browser_state_delete_and_disabled_mode(tmp_path):
    disabled = BrowserStateStore(tmp_path, "")
    disabled.save("session-3", {"cookies": []})
    assert disabled.load("session-3") is None
    assert disabled.metadata("session-3") == {
        "enabled": False,
        "exists": False,
        "updated_at": None,
    }

    store = BrowserStateStore(tmp_path, Fernet.generate_key().decode())
    store.save("session-3", json.loads('{"cookies": [], "origins": []}'))
    assert store.delete("session-3") is True
    assert store.delete("session-3") is False


def test_browser_state_rejects_unsafe_session_ids(tmp_path):
    store = BrowserStateStore(tmp_path, Fernet.generate_key().decode())

    try:
        store.save("../escape", {"cookies": []})
    except ValueError as error:
        assert str(error) == "Invalid browser session id"
    else:
        raise AssertionError("unsafe session id was accepted")
