import tempfile

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_chat_persists_across_app_restart():
    with tempfile.TemporaryDirectory() as directory:
        settings = Settings(
            workspace_root=directory, db_path="test.db", model_provider="fake"
        )
        with TestClient(create_app(settings)) as client:
            session_id = client.post("/v1/sessions").json()["id"]
            response = client.post(
                "/v1/chat", json={"session_id": session_id, "message": "calculate 2+3"}
            )
            assert response.status_code == 200
            assert "5" in response.json()["answer"]
        with TestClient(create_app(settings)) as client:
            saved = client.get(f"/v1/sessions/{session_id}")
            assert saved.status_code == 200
            assert len(saved.json()["messages"]) >= 4


def test_memory_is_recalled_in_new_session():
    with tempfile.TemporaryDirectory() as directory:
        settings = Settings(
            workspace_root=directory, db_path="test.db", model_provider="fake"
        )
        with TestClient(create_app(settings)) as client:
            first = client.post(
                "/v1/chat", json={"message": "Remember my test project is Atlas"}
            )
            assert first.status_code == 200
            second = client.post(
                "/v1/chat", json={"message": "What is my test project?"}
            )
            assert second.status_code == 200
            assert "Atlas" in second.json()["answer"]
            results = client.get("/v1/memory/search", params={"q": "Atlas"})
            assert results.status_code == 200
            assert results.json()["results"]


def test_memory_api_create_and_delete():
    with tempfile.TemporaryDirectory() as directory:
        settings = Settings(
            workspace_root=directory, db_path="test.db", model_provider="fake"
        )
        with TestClient(create_app(settings)) as client:
            created = client.post(
                "/v1/memory",
                json={"content": "Favorite editor is Vim", "kind": "preference"},
            )
            assert created.status_code == 200
            memory_id = created.json()["id"]
            assert client.delete(f"/v1/memory/{memory_id}").status_code == 200
            assert (
                client.get("/v1/memory/search", params={"q": "Vim"}).json()["results"]
                == []
            )
