from types import SimpleNamespace

import pytest

from app.evals.repository import EvalRepository
from app.evals.service import EvalService
from app.memory.repository import Database


class FakeRuntime:
    async def run(self, session_id, prompt):
        if prompt == "explode":
            raise RuntimeError("model failed")
        answer = "The answer is 5." if "2+3" in prompt else f"reply: {prompt}"
        return SimpleNamespace(run_id=None, answer=answer)


@pytest.mark.asyncio
async def test_eval_repository_crud_and_run_scoring(tmp_path):
    database = Database(tmp_path / "evals.db")
    await database.initialize()
    repository = EvalRepository(database)
    await repository.create_case("math", "calculate 2+3", "5")
    failing = await repository.create_case("expectation", "hello", "missing")
    broken = await repository.create_case("error", "explode", None)

    assert [item["name"] for item in await repository.list_cases()] == [
        "math",
        "expectation",
        "error",
    ]
    updated = await repository.update_case(failing["id"], enabled=False)
    assert updated["enabled"] is False
    await repository.update_case(failing["id"], enabled=True)

    result = await EvalService(database, repository, FakeRuntime()).run()

    assert result["status"] == "completed"
    assert (result["total"], result["passed"], result["failed"], result["errors"]) == (
        3,
        1,
        1,
        1,
    )
    assert [item["status"] for item in result["results"]] == [
        "passed",
        "failed",
        "error",
    ]
    assert await repository.delete_case(broken["id"]) is True


@pytest.mark.asyncio
async def test_create_eval_case_from_agent_run(tmp_path):
    database = Database(tmp_path / "evals.db")
    await database.initialize()
    session = await database.create_session()
    await database.append_message(session["id"], "user", "original bad request")
    run_id = await database.create_run(session["id"])
    await database.finish_run(run_id, "completed", [])
    repository = EvalRepository(database)

    case = await repository.create_case_from_run(run_id, "regression", "expected")

    assert case["prompt"] == "original bad request"
    assert case["source_run_id"] == run_id
    assert await repository.create_case_from_run("missing", "x", None) is None
