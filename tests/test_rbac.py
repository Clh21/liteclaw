import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.memory.repository import Database


def rbac_app(tmp_path):
    return create_app(
        Settings(
            workspace_root=tmp_path,
            db_path="rbac.db",
            model_provider="fake",
            tasks_enabled=False,
            rbac_enabled=True,
            server_api_key="bootstrap-admin",
        )
    )


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_admin_creates_user_and_one_time_token_with_role_enforcement(tmp_path):
    with TestClient(rbac_app(tmp_path)) as client:
        user = client.post(
            "/v1/admin/users",
            headers=bearer("bootstrap-admin"),
            json={"username": "reader", "role": "viewer"},
        )
        assert user.status_code == 200
        token_response = client.post(
            f"/v1/admin/users/{user.json()['id']}/tokens",
            headers=bearer("bootstrap-admin"),
            json={"label": "test"},
        )
        token = token_response.json()["token"]
        assert token.startswith("lc_")
        assert "token_hash" not in token_response.json()

        assert (
            client.get("/v1/sessions/missing", headers=bearer(token)).status_code == 404
        )
        forbidden = client.post("/v1/sessions", headers=bearer(token), json={})
        assert forbidden.status_code == 403
        assert forbidden.json()["detail"]["code"] == "forbidden"


def test_user_can_write_and_revoked_token_is_rejected(tmp_path):
    with TestClient(rbac_app(tmp_path)) as client:
        admin = bearer("bootstrap-admin")
        user = client.post(
            "/v1/admin/users",
            headers=admin,
            json={"username": "operator", "role": "user"},
        ).json()
        issued = client.post(
            f"/v1/admin/users/{user['id']}/tokens",
            headers=admin,
            json={"label": "cli"},
        ).json()
        assert (
            client.post(
                "/v1/sessions", headers=bearer(issued["token"]), json={}
            ).status_code
            == 200
        )

        assert (
            client.delete(f"/v1/admin/tokens/{issued['id']}", headers=admin).status_code
            == 200
        )
        assert (
            client.get(
                "/v1/sessions/missing", headers=bearer(issued["token"])
            ).status_code
            == 401
        )


def test_rbac_requires_bootstrap_key(tmp_path):
    try:
        create_app(
            Settings(
                workspace_root=tmp_path,
                model_provider="fake",
                rbac_enabled=True,
                server_api_key="",
            )
        )
    except ValueError as error:
        assert "SERVER_API_KEY" in str(error)
    else:
        raise AssertionError("RBAC must require a bootstrap key")


@pytest.mark.asyncio
async def test_api_token_is_hashed_at_rest(tmp_path):
    database = Database(tmp_path / "tokens.db")
    await database.initialize()
    user = await database.create_user("hash-check", "user")
    issued = await database.create_api_token(user["id"], "test")

    async with database.connection() as connection:
        row = await (
            await connection.execute(
                "SELECT token_hash FROM api_tokens WHERE id=?", (issued["id"],)
            )
        ).fetchone()

    assert issued["token"] not in row["token_hash"]
    assert len(row["token_hash"]) == 64
