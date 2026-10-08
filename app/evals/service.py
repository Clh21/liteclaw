from time import perf_counter

from app.evals.repository import EvalRepository
from app.memory.repository import Database


class EvalService:
    def __init__(self, database: Database, repository: EvalRepository, runtime):
        self.database = database
        self.repository = repository
        self.runtime = runtime

    async def run(self, case_ids: list[str] | None = None) -> dict:
        cases = await self.repository.list_cases(
            enabled_only=case_ids is None, case_ids=case_ids
        )
        run_id = await self.repository.start_run(len(cases))
        for case in cases:
            started = perf_counter()
            answer = None
            error = None
            agent_run_id = None
            try:
                session = await self.database.create_session(
                    title=f"Eval: {case['name']}"
                )
                result = await self.runtime.run(session["id"], case["prompt"])
                answer = getattr(result, "answer", None)
                agent_run_id = getattr(result, "run_id", None)
                if answer is None:
                    raise RuntimeError("evaluation requires approval")
                expected = case["expected_contains"]
                status = (
                    "passed"
                    if expected is None or expected.casefold() in answer.casefold()
                    else "failed"
                )
            except Exception as exception:  # noqa: BLE001 - isolate each eval case
                status = "error"
                error = str(exception)
            await self.repository.add_result(
                run_id,
                case,
                status,
                answer,
                error,
                round((perf_counter() - started) * 1000),
                agent_run_id,
            )
        await self.repository.finish_run(run_id)
        return await self.repository.get_run(run_id)
