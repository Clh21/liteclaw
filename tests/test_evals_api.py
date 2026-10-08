import tempfile

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_eval_api_dashboard_run_and_bad_case_flow():
    with tempfile.TemporaryDirectory() as directory:
        app = create_app(
            Settings(
                workspace_root=directory,
                db_path="eval-api.db",
                model_provider="fake",
                tasks_enabled=False,
            )
        )
        with TestClient(app) as client:
            dashboard = client.get("/evals")
            assert dashboard.status_code == 200
            assert "LiteClaw Eval" in dashboard.text
            assert "sessionStorage" in dashboard.text

            created = client.post(
                "/v1/evals/cases",
                json={
                    "name": "calculator",
                    "prompt": "calculate 2+3",
                    "expected_contains": "5",
                },
            ).json()
            assert created["enabled"] is True
            assert client.get("/v1/evals/cases").json()[0]["id"] == created["id"]

            updated = client.patch(
                f"/v1/evals/cases/{created['id']}", json={"name": "math"}
            ).json()
            assert updated["name"] == "math"

            evaluation = client.post("/v1/evals/run", json={}).json()
            assert evaluation["passed"] == 1
            assert evaluation["results"][0]["status"] == "passed"
            assert client.get("/v1/evals/runs").json()[0]["id"] == evaluation["id"]
            assert client.get(f"/v1/evals/runs/{evaluation['id']}").json()["total"] == 1

            chat = client.post(
                "/v1/chat", json={"message": "an answer that needs regression"}
            ).json()
            regression = client.post(
                f"/v1/evals/cases/from-run/{chat['run_id']}",
                json={"name": "regression", "expected_contains": "FakeModel"},
            ).json()
            assert regression["prompt"] == "an answer that needs regression"
            assert regression["source_run_id"] == chat["run_id"]

            assert client.delete(f"/v1/evals/cases/{created['id']}").status_code == 204
            assert (
                client.get(f"/v1/evals/runs/{evaluation['id']}").json()["results"][0][
                    "case_name"
                ]
                == "math"
            )
            assert client.get("/v1/evals/runs/missing").status_code == 404
