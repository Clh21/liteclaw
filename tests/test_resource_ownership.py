import asyncio
import sqlite3

from fastapi.testclient import TestClient

from app.config import Settings
from app.core.messages import ModelResponse, ToolCall
from app.main import create_app
from app.memory.repository import Database
from app.models.fake import FakeModel


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def issue_user(client, admin_headers, username):
    user = client.post(
        "/v1/admin/users",
        headers=admin_headers,
        json={"username": username, "role": "user"},
    ).json()
    return client.post(
        f"/v1/admin/users/{user['id']}/tokens",
        headers=admin_headers,
        json={"label": "ownership-test"},
    ).json()["token"]


def ownership_app(tmp_path):
    return create_app(
        Settings(
            workspace_root=tmp_path,
            db_path="ownership.db",
            model_provider="fake",
            tasks_enabled=False,
            rbac_enabled=True,
            server_api_key="bootstrap-admin",
        )
    )


def test_users_cannot_access_each_others_sessions_runs_or_browser_state(tmp_path):
    with TestClient(ownership_app(tmp_path)) as client:
        admin = bearer("bootstrap-admin")
        alice = bearer(issue_user(client, admin, "alice"))
        bob = bearer(issue_user(client, admin, "bob"))
        session_id = client.post("/v1/sessions", headers=alice, json={}).json()["id"]
        run = client.post(
            "/v1/chat",
            headers=alice,
            json={"session_id": session_id, "message": "calculate 2+3"},
        ).json()

        assert client.get(f"/v1/sessions/{session_id}", headers=bob).status_code == 404
        assert client.get(f"/v1/runs/{run['run_id']}", headers=bob).status_code == 404
        assert (
            client.post(
                "/v1/chat",
                headers=bob,
                json={"session_id": session_id, "message": "intrude"},
            ).status_code
            == 404
        )
        assert (
            client.post(
                "/v1/chat/stream",
                headers=bob,
                json={"session_id": session_id, "message": "intrude"},
            ).status_code
            == 404
        )
        assert (
            client.get(
                f"/v1/browser/sessions/{session_id}/state", headers=bob
            ).status_code
            == 404
        )
        assert (
            client.get(f"/v1/sessions/{session_id}", headers=admin).status_code == 200
        )


def test_users_have_isolated_memories_and_tasks(tmp_path):
    with TestClient(ownership_app(tmp_path)) as client:
        admin = bearer("bootstrap-admin")
        alice = bearer(issue_user(client, admin, "alice-memory"))
        bob = bearer(issue_user(client, admin, "bob-memory"))
        session_id = client.post("/v1/sessions", headers=alice, json={}).json()["id"]
        memory = client.post(
            "/v1/memory",
            headers=alice,
            json={"content": "Atlas belongs to Alice"},
        ).json()
        task = client.post(
            "/v1/tasks",
            headers=alice,
            json={
                "name": "Alice task",
                "prompt": "calculate 2+3",
                "schedule_type": "interval",
                "interval_seconds": 3600,
                "session_id": session_id,
            },
        ).json()

        assert (
            client.get("/v1/memory/search?q=Atlas", headers=bob).json()["results"] == []
        )
        assert (
            client.delete(f"/v1/memory/{memory['id']}", headers=bob).status_code == 404
        )
        assert client.get("/v1/tasks", headers=bob).json()["tasks"] == []
        assert client.get(f"/v1/tasks/{task['id']}", headers=bob).status_code == 404
        assert (
            client.post(
                "/v1/tasks",
                headers=bob,
                json={
                    "name": "Intruding task",
                    "prompt": "noop",
                    "schedule_type": "interval",
                    "interval_seconds": 3600,
                    "session_id": session_id,
                },
            ).status_code
            == 404
        )
        assert (
            client.post(f"/v1/tasks/{task['id']}/pause", headers=bob).status_code == 404
        )
        assert (
            client.post(f"/v1/tasks/{task['id']}/resume", headers=bob).status_code
            == 404
        )
        assert client.delete(f"/v1/tasks/{task['id']}", headers=bob).status_code == 404
        assert client.get(f"/v1/tasks/{task['id']}", headers=admin).status_code == 200


def test_users_cannot_resolve_each_others_approvals(tmp_path):
    note = tmp_path / "owned.txt"
    note.write_text("before", encoding="utf-8")
    app = create_app(
        Settings(
            workspace_root=tmp_path,
            db_path="approval-ownership.db",
            model_provider="fake",
            tasks_enabled=False,
            require_approval=True,
            rbac_enabled=True,
            server_api_key="bootstrap-admin",
        )
    )
    app.state.runtime.model = FakeModel(
        [
            ModelResponse(
                tool_calls=[
                    ToolCall(
                        id="write-owned",
                        name="file_write",
                        arguments={
                            "relative_path": "owned.txt",
                            "content": "after",
                            "overwrite": True,
                        },
                    )
                ]
            ),
            ModelResponse(content="updated"),
        ]
    )
    with TestClient(app) as client:
        admin = bearer("bootstrap-admin")
        alice = bearer(issue_user(client, admin, "alice-approval"))
        bob = bearer(issue_user(client, admin, "bob-approval"))
        pending = client.post(
            "/v1/chat", headers=alice, json={"message": "update owned.txt"}
        )
        assert pending.status_code == 202
        approval_id = pending.json()["approval_id"]

        assert (
            client.post(f"/v1/approvals/{approval_id}/approve", headers=bob).status_code
            == 404
        )
        assert note.read_text(encoding="utf-8") == "before"
        assert (
            client.post(
                f"/v1/approvals/{approval_id}/approve", headers=alice
            ).status_code
            == 200
        )
        assert note.read_text(encoding="utf-8") == "after"


def test_evals_are_admin_only_and_legacy_sessions_are_hidden(tmp_path):
    app = ownership_app(tmp_path)
    with TestClient(app) as client:
        admin = bearer("bootstrap-admin")
        user = bearer(issue_user(client, admin, "legacy-reader"))
        legacy = asyncio.run(app.state.database.create_session(title="legacy"))
        asyncio.run(app.state.database.add_memory("Legacy secret"))

        assert client.get("/evals").status_code == 401
        assert client.get("/evals", headers=user).status_code == 403
        assert client.get("/evals", headers=admin).status_code == 200
        assert client.get("/v1/evals/cases", headers=user).status_code == 403
        assert client.get("/v1/evals/cases", headers=admin).status_code == 200
        assert (
            client.get("/v1/memory/search?q=Legacy", headers=user).json()["results"]
            == []
        )
        assert (
            len(
                client.get("/v1/memory/search?q=Legacy", headers=admin).json()[
                    "results"
                ]
            )
            == 1
        )
        assert (
            client.get(f"/v1/sessions/{legacy['id']}", headers=user).status_code == 404
        )
        assert (
            client.get(f"/v1/sessions/{legacy['id']}", headers=admin).status_code == 200
        )


def test_database_migrates_legacy_owner_columns(tmp_path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TABLE sessions (
            id TEXT PRIMARY KEY,title TEXT,agent_id TEXT NOT NULL DEFAULT 'main',
            summary TEXT,summarized_message_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,updated_at TEXT NOT NULL)"""
        )
        connection.execute(
            """CREATE TABLE memories (
            id TEXT PRIMARY KEY,agent_id TEXT NOT NULL,session_id TEXT,content TEXT NOT NULL,
            kind TEXT NOT NULL,importance REAL NOT NULL DEFAULT 0.5,embedding_model TEXT,
            embedding BLOB,content_hash TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)"""
        )

    database = Database(path)
    asyncio.run(database.initialize())

    with sqlite3.connect(path) as connection:
        session_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(sessions)")
        }
        memory_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(memories)")
        }
        indexes = {
            row[1] for row in connection.execute("PRAGMA index_list(sessions)")
        } | {row[1] for row in connection.execute("PRAGMA index_list(memories)")}

    assert "owner_id" in session_columns
    assert "owner_id" in memory_columns
    assert {"idx_sessions_owner", "idx_memories_owner"}.issubset(indexes)


def test_admin_can_assign_owner_and_users_cannot_spoof_it(tmp_path):
    with TestClient(ownership_app(tmp_path)) as client:
        admin = bearer("bootstrap-admin")
        user_record = client.post(
            "/v1/admin/users",
            headers=admin,
            json={"username": "import-owner", "role": "user"},
        ).json()
        token = client.post(
            f"/v1/admin/users/{user_record['id']}/tokens",
            headers=admin,
            json={"label": "owner-test"},
        ).json()["token"]
        user = bearer(token)

        assigned_session = client.post(
            "/v1/sessions",
            headers=admin,
            json={"title": "imported", "owner_id": user_record["id"]},
        )
        assert assigned_session.status_code == 200
        assert assigned_session.json()["owner_id"] == user_record["id"]
        assert (
            client.get(
                f"/v1/sessions/{assigned_session.json()['id']}", headers=user
            ).status_code
            == 200
        )

        assigned_memory = client.post(
            "/v1/memory",
            headers=admin,
            json={"content": "Imported for owner", "owner_id": user_record["id"]},
        )
        assert assigned_memory.status_code == 200
        assert assigned_memory.json()["owner_id"] == user_record["id"]
        assert (
            len(
                client.get("/v1/memory/search?q=Imported", headers=user).json()[
                    "results"
                ]
            )
            == 1
        )

        spoofed = client.post(
            "/v1/sessions", headers=user, json={"owner_id": "bootstrap"}
        )
        assert spoofed.status_code == 200
        assert spoofed.json()["owner_id"] == user_record["id"]
        assert (
            client.post(
                "/v1/sessions", headers=admin, json={"owner_id": "missing"}
            ).status_code
            == 404
        )
