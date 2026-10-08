import tempfile
from datetime import timedelta

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.tasks.models import utc_now


def task_body(**overrides):
    body = {
        "name": "daily report",
        "prompt": "calculate 2+3",
        "schedule_type": "once",
        "run_at": (utc_now() + timedelta(minutes=5)).isoformat(),
    }
    body.update(overrides)
    return body


def test_task_api_create_list_pause_resume_and_delete():
    with tempfile.TemporaryDirectory() as directory:
        settings = Settings(
            workspace_root=directory,
            db_path="tasks.db",
            model_provider="fake",
            tasks_enabled=False,
        )
        with TestClient(create_app(settings)) as client:
            created = client.post("/v1/tasks", json=task_body())
            assert created.status_code == 201
            task_id = created.json()["id"]
            assert client.get("/v1/tasks").json()["tasks"][0]["id"] == task_id
            assert client.get(f"/v1/tasks/{task_id}").json()["runs"] == []
            assert client.post(f"/v1/tasks/{task_id}/pause").status_code == 200
            assert client.post(f"/v1/tasks/{task_id}/pause").status_code == 409
            assert client.post(f"/v1/tasks/{task_id}/resume").status_code == 200
            assert client.delete(f"/v1/tasks/{task_id}").status_code == 200
            assert client.get(f"/v1/tasks/{task_id}").status_code == 404


def test_scheduler_tick_executes_due_task_once_and_reports_health():
    with tempfile.TemporaryDirectory() as directory:
        settings = Settings(
            workspace_root=directory,
            db_path="tasks.db",
            model_provider="fake",
            tasks_enabled=False,
        )
        app = create_app(settings)
        with TestClient(app) as client:
            created = client.post(
                "/v1/tasks",
                json=task_body(run_at=(utc_now() - timedelta(seconds=1)).isoformat()),
            ).json()
            client.portal.call(app.state.scheduler.tick)
            saved = client.get(f"/v1/tasks/{created['id']}").json()
            assert saved["status"] == "completed"
            assert len(saved["runs"]) == 1
            client.portal.call(app.state.scheduler.tick)
            assert len(client.get(f"/v1/tasks/{created['id']}").json()["runs"]) == 1
            health = client.get("/health").json()
            assert health["tasks"]["status"] == "disabled"
