import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.api.chat import ChatRequest
from app.core.events import RunEventEmitter
from app.core.runtime import PendingRunResult
from app.models.openai_compatible import ModelAuthError, ModelUnavailable

router = APIRouter(prefix="/v1", tags=["chat"])


def encode_sse(event: dict) -> str:
    payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event['type']}\nid: {event['seq']}\ndata: {payload}\n\n"


def error_code(error: Exception) -> str:
    if isinstance(error, ModelAuthError):
        return "model_auth_error"
    if isinstance(error, ModelUnavailable):
        return "model_unavailable"
    return "agent_error"


@router.post("/chat/stream")
async def stream_chat(body: ChatRequest, request: Request):
    database = request.app.state.database
    session_id = body.session_id
    if session_id is None:
        session_id = (await database.create_session())["id"]
    elif await database.get_session(session_id) is None:
        raise HTTPException(404, detail={"code": "session_not_found"})

    queue: asyncio.Queue[dict] = asyncio.Queue()
    emitter = RunEventEmitter(queue.put_nowait)
    emitter.emit("session", session_id=session_id)

    async def run_agent() -> None:
        status = "completed"
        try:
            if body.plan and request.app.state.settings.enable_planner:
                result = await request.app.state.planner.execute(
                    session_id, body.message
                )
                if isinstance(result, PendingRunResult):
                    status = "waiting_approval"
                    emitter.emit(
                        "approval_required",
                        run_id=result.run_id,
                        approval_id=result.approval_id,
                        tool_name=result.tool_name,
                    )
                else:
                    emitter.emit(
                        "final",
                        run_id=result["run_id"],
                        session_id=session_id,
                        answer=result["answer"],
                        usage={},
                    )
            else:
                result = await request.app.state.runtime.run(
                    session_id, body.message, emitter
                )
                if isinstance(result, PendingRunResult):
                    status = "waiting_approval"
        except Exception as error:  # noqa: BLE001 - errors must stay inside the SSE protocol
            status = "failed"
            emitter.emit("error", code=error_code(error), message=str(error)[:500])
        finally:
            emitter.emit("done", session_id=session_id, status=status)

    runner = asyncio.create_task(run_agent())
    request.app.state.streaming_tasks.add(runner)
    runner.add_done_callback(request.app.state.streaming_tasks.discard)

    async def event_stream() -> AsyncIterator[str]:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=15)
            except asyncio.TimeoutError:
                if await request.is_disconnected():
                    return
                yield ": heartbeat\n\n"
                continue
            yield encode_sse(event)
            if event["type"] == "done":
                return

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
