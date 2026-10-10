from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def sample():
    return (
        "2026-10-01 09:30 我: 我来写方案\n"
        "2026-10-02 10:00 我: 方案已完成\n"
        "2026-10-03 11:00 小王: 下周再检查报告"
    ).encode()


def app_for(tmp_path, rbac=False):
    return create_app(
        Settings(
            workspace_root=tmp_path,
            db_path="records.db",
            model_provider="fake",
            tasks_enabled=False,
            rbac_enabled=rbac,
            server_api_key="admin-key" if rbac else "",
        )
    )


def upload(client, headers=None, data=None):
    return client.post(
        "/v1/chat-records/import",
        params={"filename": "group.txt", "conversation": "项目群", "self_sender": "我"},
        headers=headers,
        content=data if data is not None else sample(),
    )


def test_import_list_duplicate_delete_and_atomic_invalid(tmp_path):
    with TestClient(app_for(tmp_path)) as client:
        imported = upload(client)
        assert imported.status_code == 201
        source = imported.json()
        assert source["message_count"] == 3
        assert upload(client).json()["id"] == source["id"]
        assert len(client.get("/v1/chat-records/sources").json()["sources"]) == 1
        messages = client.get(
            "/v1/chat-records/messages", params={"source_id": source["id"], "limit": 2}
        ).json()["messages"]
        assert len(messages) == 2
        assert messages[0]["content"] == "我来写方案"
        assert upload(client, data=b"bad export").status_code == 422
        assert len(client.get("/v1/chat-records/sources").json()["sources"]) == 1
        assert (
            client.delete(f"/v1/chat-records/sources/{source['id']}").status_code == 200
        )
        assert client.get("/v1/chat-records/messages").json()["messages"] == []


def _user_token(client, admin, name):
    user = client.post(
        "/v1/admin/users", headers=admin, json={"username": name, "role": "user"}
    ).json()
    token = client.post(
        f"/v1/admin/users/{user['id']}/tokens",
        headers=admin,
        json={"label": "records"},
    ).json()["token"]
    return user, {"Authorization": f"Bearer {token}"}


def test_chat_records_respect_owner(tmp_path):
    with TestClient(app_for(tmp_path, rbac=True)) as client:
        admin = {"Authorization": "Bearer admin-key"}
        alice_user, alice = _user_token(client, admin, "records-alice")
        _, bob = _user_token(client, admin, "records-bob")
        source = upload(client, alice).json()
        assert source["owner_id"] == alice_user["id"]
        assert (
            client.get("/v1/chat-records/sources", headers=bob).json()["sources"] == []
        )
        assert (
            client.get("/v1/chat-records/messages", headers=bob).json()["messages"]
            == []
        )
        assert (
            client.get(
                "/v1/chat-records/messages",
                headers=bob,
                params={"source_id": source["id"]},
            ).status_code
            == 404
        )
        assert (
            client.delete(
                f"/v1/chat-records/sources/{source['id']}", headers=bob
            ).status_code
            == 404
        )
        assert (
            len(client.get("/v1/chat-records/sources", headers=admin).json()["sources"])
            == 1
        )
