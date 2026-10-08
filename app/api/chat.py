from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.core.runtime import MaxStepsExceeded, PendingRunResult
from app.models.openai_compatible import ModelAuthError, ModelUnavailable

router = APIRouter(prefix="/v1", tags=["chat"])


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str = Field(min_length=1)
    debug: bool = False
    plan: bool = False


@router.post("/chat")
async def chat(body: ChatRequest, request: Request, response: Response):
    database = request.app.state.database
    session_id = body.session_id
    if session_id is None:
        session_id = (await database.create_session())["id"]
    planned = body.plan and request.app.state.settings.enable_planner
    try:
        result = (
            await request.app.state.planner.execute(session_id, body.message)
            if planned
            else await request.app.state.runtime.run(session_id, body.message)
        )
    except KeyError as error:
        raise HTTPException(404, detail={"code": "session_not_found"}) from error
    except ModelAuthError as error:
        raise HTTPException(
            502, detail={"code": "model_auth_error", "message": str(error)}
        ) from error
    except ModelUnavailable as error:
        raise HTTPException(
            503, detail={"code": "model_unavailable", "message": str(error)}
        ) from error
    except MaxStepsExceeded as error:
        raise HTTPException(
            500, detail={"code": "max_steps_exceeded", "message": str(error)}
        ) from error
    if isinstance(result, dict):
        return result
    if isinstance(result, PendingRunResult):
        response.status_code = 202
        return {
            "code": "approval_required",
            "session_id": session_id,
            "run_id": result.run_id,
            "approval_id": result.approval_id,
            "tool_name": result.tool_name,
            "arguments": result.arguments,
            "trace": result.trace,
        }
    return {
        "session_id": session_id,
        "run_id": result.run_id,
        "answer": result.answer,
        "usage": result.usage,
        "trace": result.trace,
    }


@router.get("/runs/{run_id}")
async def get_run(run_id: str, request: Request):
    run = await request.app.state.database.get_run(run_id)
    if run is None:
        raise HTTPException(404, detail={"code": "run_not_found"})
    return {
        **run,
        "tool_events": await request.app.state.database.get_tool_events(run_id),
    }
