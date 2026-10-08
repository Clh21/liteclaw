import tempfile

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def auth_app(directory, key=""):
    return create_app(
        Settings(
            workspace_root=directory,
            db_path="auth.db",
            model_provider="fake",
            tasks_enabled=False,
            server_api_key=key,
        )
    )


def test_auth_disabled_preserves_local_api_access():
    with (
        tempfile.TemporaryDirectory() as directory,
        TestClient(auth_app(directory)) as client,
    ):
        assert client.post("/v1/sessions", json={}).status_code == 200


def test_auth_rejects_missing_wrong_and_conflicting_credentials():
    with (
        tempfile.TemporaryDirectory() as directory,
        TestClient(auth_app(directory, "correct-secret")) as client,
    ):
        missing = client.post("/v1/sessions", json={})
        assert missing.status_code == 401
        assert missing.json()["detail"]["code"] == "unauthorized"
        assert missing.headers["www-authenticate"] == "Bearer"
        assert (
            client.post(
                "/v1/sessions", json={}, headers={"Authorization": "Bearer wrong"}
            ).status_code
            == 401
        )
        assert (
            client.post(
                "/v1/sessions",
                json={},
                headers={
                    "Authorization": "Bearer correct-secret",
                    "X-API-Key": "different",
                },
            ).status_code
            == 401
        )


def test_auth_accepts_bearer_and_api_key_while_health_stays_public():
    with (
        tempfile.TemporaryDirectory() as directory,
        TestClient(auth_app(directory, "correct-secret")) as client,
    ):
        assert client.get("/health").status_code == 200
        assert (
            client.post(
                "/v1/sessions",
                json={},
                headers={"Authorization": "bearer correct-secret"},
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/v1/sessions", json={}, headers={"X-API-Key": "correct-secret"}
            ).status_code
            == 200
        )
