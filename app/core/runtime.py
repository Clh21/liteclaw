import json
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path

from app.core.context import ContextBuilder
from app.core.events import RunEventEmitter
from app.logging import log_event
from app.memory.repository import Database
from app.memory.writer import MemoryWriter
from app.models.base import BaseChatModel
from app.tools.base import ToolContext, ToolResult
from app.tools.registry import ToolRegistry


class MaxStepsExceeded(Exception):
    pass


@dataclass
class AgentRunResult:
    run_id: str
    answer: str
    trace: list[dict]
    usage: dict[str, int]


@dataclass
class PendingRunResult:
    run_id: str
    approval_id: str
    tool_name: str
    arguments: dict
    trace: list[dict]


class AgentRuntime:
    def __init__(
        self,
        database: Database,
        model: BaseChatModel,
        registry: ToolRegistry,
        max_steps: int = 8,
        context_builder: ContextBuilder | None = None,
        memory_writer: MemoryWriter | None = None,
        workspace_root: Path | None = None,
        require_approval: bool = False,
        tracing=None,
    ):
        self.database = database
        self.model = model
        self.registry = registry
        self.max_steps = max_steps
        self.context_builder = context_builder or ContextBuilder(database)
        self.memory_writer = memory_writer or MemoryWriter(database)
        self.workspace_root = workspace_root or Path.cwd()
        self.require_approval = require_approval
        self.tracing = tracing

    def _span(self, name: str, **attributes):
        return (
            self.tracing.span(name, **attributes)
            if self.tracing is not None
            else nullcontext()
        )

    async def run(
        self,
        session_id: str,
        user_text: str,
        emitter: RunEventEmitter | None = None,
    ) -> AgentRunResult | PendingRunResult:
        if await self.database.get_session(session_id) is None:
            raise KeyError("session_not_found")
        await self.database.append_message(session_id, "user", user_text)
        run_id = await self.database.create_run(session_id)
        if emitter:
            emitter.emit("run_started", run_id=run_id, session_id=session_id)
        log_event("run.start", run_id=run_id, session_id=session_id)
        with self._span("agent.run", run_id=run_id, session_id=session_id):
            return await self._loop(session_id, user_text, run_id, [], 1, emitter)

    async def resolve_approval(
        self,
        approval_id: str,
        approve: bool,
        emitter: RunEventEmitter | None = None,
    ) -> AgentRunResult | PendingRunResult:
        approval = await self.database.decide_approval(approval_id, approve)
        if approval is None:
            raise KeyError("approval_not_found_or_already_decided")
        run = await self.database.get_run(approval["run_id"])
        if run is None or run["status"] != "waiting_approval":
            raise KeyError("run_not_waiting")
        session_id = run["session_id"]
        trace = run["trace"]
        step = max((item.get("step", 0) for item in trace), default=1)
        pending = await self._drain_calls(
            session_id,
            run["id"],
            trace,
            step,
            (approval["tool_call_id"], approve),
            emitter,
        )
        if pending:
            return pending
        history = await self.database.get_messages(session_id)
        user_text = next(
            (item["content"] for item in reversed(history) if item["role"] == "user"),
            "",
        )
        with self._span(
            "agent.run", run_id=run["id"], session_id=session_id, resumed=True
        ):
            return await self._loop(
                session_id, user_text, run["id"], trace, step + 1, emitter
            )

    async def _loop(
        self,
        session_id: str,
        user_text: str,
        run_id: str,
        trace: list[dict],
        start_step: int,
        emitter: RunEventEmitter | None = None,
    ) -> AgentRunResult | PendingRunResult:
        usage = {"input_tokens": 0, "output_tokens": 0}
        try:
            for step in range(start_step, self.max_steps + 1):
                context = await self.context_builder.build(session_id)
                log_event(
                    "context.build",
                    run_id=run_id,
                    session_id=session_id,
                    estimated_tokens=context.stats.estimated_tokens,
                    memories_used=context.stats.memories_used,
                )
                log_event(
                    "model.start", run_id=run_id, session_id=session_id, step=step
                )
                if emitter:
                    emitter.emit("model_started", run_id=run_id, step=step)
                with self._span(
                    "model.complete",
                    run_id=run_id,
                    session_id=session_id,
                    step=step,
                ):
                    response = await self.model.complete(
                        context.messages, self.registry.schemas_for_model()
                    )
                log_event(
                    "model.end",
                    run_id=run_id,
                    session_id=session_id,
                    step=step,
                    tool_calls=len(response.tool_calls),
                )
                if emitter:
                    emitter.emit(
                        "model_completed",
                        run_id=run_id,
                        step=step,
                        tool_call_count=len(response.tool_calls),
                    )
                if response.usage:
                    usage["input_tokens"] += response.usage.input_tokens
                    usage["output_tokens"] += response.usage.output_tokens
                if not response.tool_calls:
                    answer = response.content or ""
                    await self.database.append_message(session_id, "assistant", answer)
                    trace.append({"step": step, "type": "final"})
                    await self.database.finish_run(run_id, "completed", trace)
                    log_event("run.completed", run_id=run_id, session_id=session_id)
                    if emitter:
                        emitter.emit(
                            "final",
                            run_id=run_id,
                            session_id=session_id,
                            answer=answer,
                            usage=usage,
                        )
                    try:
                        await self.memory_writer.after_turn(session_id, user_text)
                    except Exception as error:  # noqa: BLE001 - answer is already stored
                        log_event(
                            "memory.postprocess_failed",
                            run_id=run_id,
                            error=type(error).__name__,
                        )
                    return AgentRunResult(run_id, answer, trace, usage)
                await self.database.append_message(
                    session_id,
                    "assistant",
                    response.content,
                    [call.model_dump() for call in response.tool_calls],
                )
                pending = await self._drain_calls(
                    session_id, run_id, trace, step, emitter=emitter
                )
                if pending:
                    return pending
            raise MaxStepsExceeded(f"Agent stopped after {self.max_steps} steps")
        except Exception as error:
            await self.database.finish_run(run_id, "failed", trace, str(error))
            log_event(
                "run.error",
                run_id=run_id,
                session_id=session_id,
                error=type(error).__name__,
            )
            raise

    async def _drain_calls(
        self,
        session_id: str,
        run_id: str,
        trace: list[dict],
        step: int,
        decision: tuple[str, bool] | None = None,
        emitter: RunEventEmitter | None = None,
    ) -> PendingRunResult | None:
        history = await self.database.get_messages(session_id)
        assistant_index = max(
            index
            for index, item in enumerate(history)
            if item["role"] == "assistant" and item["tool_calls"]
        )
        assistant = history[assistant_index]
        answered = {
            item["tool_call_id"]
            for item in history[assistant_index + 1 :]
            if item["role"] == "tool"
        }
        for call in assistant["tool_calls"]:
            if call["id"] in answered:
                continue
            tool = self.registry.get(call["name"])
            matching_decision = decision is not None and decision[0] == call["id"]
            if (
                tool
                and tool.risk_level_for(call["arguments"]) == "high"
                and self.require_approval
                and not matching_decision
            ):
                approval_id = await self.database.create_approval(
                    run_id, call["id"], call["name"], call["arguments"]
                )
                trace.append(
                    {"step": step, "type": "approval_wait", "name": call["name"]}
                )
                await self.database.finish_run(run_id, "waiting_approval", trace)
                log_event(
                    "approval.wait",
                    run_id=run_id,
                    session_id=session_id,
                    tool_name=call["name"],
                )
                if emitter:
                    emitter.emit(
                        "approval_required",
                        run_id=run_id,
                        approval_id=approval_id,
                        tool_name=call["name"],
                    )
                return PendingRunResult(
                    run_id, approval_id, call["name"], call["arguments"], trace
                )
            if matching_decision and not decision[1]:
                result = ToolResult(
                    ok=False,
                    content="Tool action rejected by user",
                    error="approval_rejected",
                )
            else:
                if emitter:
                    emitter.emit(
                        "tool_started",
                        run_id=run_id,
                        step=step,
                        tool_name=call["name"],
                    )
                with self._span(
                    "tool.execute",
                    run_id=run_id,
                    session_id=session_id,
                    step=step,
                    tool_name=call["name"],
                ):
                    result = await self.registry.execute(
                        call["name"],
                        call["arguments"],
                        ToolContext(session_id, self.workspace_root),
                    )
            observation = json.dumps(result.model_dump(), ensure_ascii=False)
            await self.database.append_message(
                session_id, "tool", observation, tool_call_id=call["id"]
            )
            await self.database.record_tool_event(
                run_id, call["name"], call["arguments"], result.model_dump()
            )
            log_event(
                "tool.end",
                run_id=run_id,
                session_id=session_id,
                tool_name=call["name"],
                ok=result.ok,
                elapsed_ms=result.elapsed_ms,
            )
            if emitter:
                emitter.emit(
                    "tool_completed",
                    run_id=run_id,
                    step=step,
                    tool_name=call["name"],
                    ok=result.ok,
                    elapsed_ms=result.elapsed_ms,
                )
            trace.append(
                {
                    "step": step,
                    "type": "tool_call",
                    "name": call["name"],
                    "ok": result.ok,
                    "elapsed_ms": result.elapsed_ms,
                }
            )
            answered.add(call["id"])
        return None
