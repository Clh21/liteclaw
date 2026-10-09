import json
from collections.abc import Callable

from pydantic import BaseModel, Field, model_validator

from app.core.runtime import AgentRunResult, AgentRuntime, PendingRunResult
from app.memory.repository import Database
from app.models.base import BaseChatModel
from app.models.structured import parse_json_object


class PlanTask(BaseModel):
    id: str
    goal: str = Field(min_length=1)
    depends_on: list[str] = Field(default_factory=list)


class Plan(BaseModel):
    tasks: list[PlanTask] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def validate_dependencies(self):
        seen = set()
        for task in self.tasks:
            if task.id in seen or not set(task.depends_on).issubset(seen):
                raise ValueError(
                    "Task IDs must be unique and dependencies must precede tasks"
                )
            seen.add(task.id)
        return self


class Planner:
    def __init__(
        self,
        database: Database,
        model: BaseChatModel,
        runtime_factory: Callable[[], AgentRuntime],
    ):
        self.database = database
        self.model = model
        self.runtime_factory = runtime_factory

    async def execute(self, session_id: str, request: str) -> dict:
        plan_response = await self.model.complete(
            [
                {
                    "role": "system",
                    "content": 'Break the request into at most five sequential tasks. Return only JSON: {"tasks":[{"id":"t1","goal":"...","depends_on":[]}]}.',
                },
                {"role": "user", "content": request},
            ],
            [],
        )
        plan = Plan.model_validate(
            parse_json_object(plan_response.content or "", wrapper_keys=("plan",))
        )
        run_id = await self.database.create_run(session_id)
        await self.database.append_message(session_id, "user", request)
        await self.database.save_planner_state(run_id, plan.model_dump(), [], 0)
        return await self._advance(run_id)

    async def resume_worker(
        self, result: AgentRunResult | PendingRunResult
    ) -> dict | PendingRunResult | None:
        state = await self.database.get_planner_by_worker(result.run_id)
        if state is None:
            return None
        if isinstance(result, PendingRunResult):
            return PendingRunResult(
                state["parent_run_id"],
                result.approval_id,
                result.tool_name,
                result.arguments,
                result.trace,
            )
        return await self._advance(state["parent_run_id"], result)

    async def _advance(
        self, run_id: str, completed_worker: AgentRunResult | None = None
    ) -> dict | PendingRunResult:
        state = await self.database.get_planner_state(run_id)
        if state is None:
            raise KeyError("planner_run_not_found")
        plan = Plan.model_validate(state["plan"])
        results = state["results"]
        index = state["next_index"]
        parent = await self.database.get_run(run_id)
        session_id = parent["session_id"]
        parent_session = await self.database.get_session(session_id)
        owner_id = parent_session["owner_id"] if parent_session else None
        try:
            if completed_worker is not None:
                task = plan.tasks[index]
                results.append(
                    {
                        "id": task.id,
                        "goal": task.goal,
                        "answer": completed_worker.answer,
                        "session_id": state["worker_session_id"],
                        "run_id": completed_worker.run_id,
                    }
                )
                index += 1
                await self.database.save_planner_state(
                    run_id, plan.model_dump(), results, index
                )
            for task in plan.tasks[index:]:
                worker_session = await self.database.create_session(
                    title=f"Worker {task.id}: {task.goal[:80]}", owner_id=owner_id
                )
                dependencies = "\n".join(
                    f"{name}: {next(item['answer'] for item in results if item['id'] == name)}"
                    for name in task.depends_on
                )
                prompt = task.goal + (
                    f"\nPrevious results:\n{dependencies}" if dependencies else ""
                )
                worker = await self.runtime_factory().run(worker_session["id"], prompt)
                if isinstance(worker, PendingRunResult):
                    await self.database.save_planner_state(
                        run_id,
                        plan.model_dump(),
                        results,
                        index,
                        worker.run_id,
                        worker_session["id"],
                    )
                    await self.database.finish_run(
                        run_id,
                        "waiting_approval",
                        [{"type": "planner", "tasks_completed": index}],
                    )
                    return PendingRunResult(
                        run_id,
                        worker.approval_id,
                        worker.tool_name,
                        worker.arguments,
                        worker.trace,
                    )
                results.append(
                    {
                        "id": task.id,
                        "goal": task.goal,
                        "answer": worker.answer,
                        "session_id": worker_session["id"],
                        "run_id": worker.run_id,
                    }
                )
                index += 1
                await self.database.save_planner_state(
                    run_id, plan.model_dump(), results, index
                )
            history = await self.database.get_messages(session_id)
            request = next(
                (
                    item["content"]
                    for item in reversed(history)
                    if item["role"] == "user"
                ),
                "",
            )
            synthesis = await self.model.complete(
                [
                    {
                        "role": "system",
                        "content": "Synthesize the worker results into one concise answer to the original request.",
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {"request": request, "results": results}, ensure_ascii=False
                        ),
                    },
                ],
                [],
            )
            answer = synthesis.content or ""
            await self.database.append_message(session_id, "assistant", answer)
            await self.database.finish_run(
                run_id, "completed", [{"type": "planner", "tasks": len(results)}]
            )
            return {
                "session_id": session_id,
                "run_id": run_id,
                "answer": answer,
                "tasks": results,
            }
        except Exception as error:
            await self.database.finish_run(run_id, "failed", [], str(error))
            raise
