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


def test_overlapping_exports_survive_source_deletion(tmp_path):
    with TestClient(app_for(tmp_path)) as client:
        first = upload(client).json()
        second_data = sample() + "\n2026-10-04 12:00 我: 新增记录".encode()
        second = upload(client, data=second_data).json()
        assert second["message_count"] == 4
        assert len(client.get("/v1/chat-records/messages").json()["messages"]) == 4
        assert (
            len(
                client.get(
                    "/v1/chat-records/messages", params={"source_id": second["id"]}
                ).json()["messages"]
            )
            == 4
        )
        client.delete(f"/v1/chat-records/sources/{first['id']}")
        assert len(client.get("/v1/chat-records/messages").json()["messages"]) == 4
        assert (
            client.post("/v1/chat-records/analyze", json={}).json()["message_count"]
            == 4
        )


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


def test_analysis_and_period_report_are_evidence_based(tmp_path):
    with TestClient(app_for(tmp_path)) as client:
        source = upload(client).json()
        analysis = client.post(
            "/v1/chat-records/analyze", json={"source_id": source["id"]}
        )
        assert analysis.status_code == 200
        body = analysis.json()
        assert body["message_count"] == 3
        assert body["completed_items"][0]["is_self"] is True
        assert body["open_items"][0]["status"] == "needs_confirmation"
        evidence_id = body["completed_items"][0]["evidence_ids"][0]
        assert body["evidence"][evidence_id]["content"] == "我来写方案"
        report = client.post(
            "/v1/chat-records/reports",
            json={
                "period": "month",
                "anchor_date": "2026-10-09",
                "source_id": source["id"],
            },
        )
        assert report.status_code == 200
        assert report.json()["period_start"] == "2026-09-30T16:00:00+00:00"
        assert report.json()["message_count"] == 3
        assert report.json()["completed_items"][0]["evidence_ids"]


def test_analysis_cannot_access_other_users_source(tmp_path):
    with TestClient(app_for(tmp_path, rbac=True)) as client:
        admin = {"Authorization": "Bearer admin-key"}
        _, alice = _user_token(client, admin, "insights-alice")
        _, bob = _user_token(client, admin, "insights-bob")
        source = upload(client, alice).json()
        assert (
            client.post(
                "/v1/chat-records/analyze",
                headers=bob,
                json={"source_id": source["id"]},
            ).status_code
            == 404
        )
        assert (
            client.post(
                "/v1/chat-records/reports",
                headers=bob,
                json={
                    "period": "month",
                    "anchor_date": "2026-10-09",
                    "source_id": source["id"],
                },
            ).status_code
            == 404
        )


def test_chat_records_page_has_import_and_report_controls(tmp_path):
    with TestClient(app_for(tmp_path, rbac=True)) as client:
        response = client.get("/chat-records")
        assert response.status_code == 200
        for marker in (
            'id="upload"',
            'id="sources"',
            'id="analyze"',
            'id="report"',
            'id="token"',
        ):
            assert marker in response.text
