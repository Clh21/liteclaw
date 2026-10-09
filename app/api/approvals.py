from fastapi import APIRouter, HTTPException, Request, Response

from app.api.access import owner_scope
from app.core.runtime import PendingRunResult
from app.models.openai_compatible import ModelAuthError, ModelUnavailable

router = APIRouter(prefix="/v1/approvals", tags=["approvals"])


async def decide(approval_id: str, approve: bool, request: Request, response: Response):
    approval = await request.app.state.database.get_approval_for_owner(
        approval_id, owner_scope(request)
    )
    if approval is None:
        raise HTTPException(404, detail={"code": "approval_not_found"})
    try:
        result = await request.app.state.runtime.resolve_approval(approval_id, approve)
        await request.app.state.task_service.complete_after_approval(result)
        planner_result = await request.app.state.planner.resume_worker(result)
    except KeyError as error:
        raise HTTPException(404, detail={"code": str(error)}) from error
    except ModelAuthError as error:
        raise HTTPException(
            502, detail={"code": "model_auth_error", "message": str(error)}
        ) from error
    except ModelUnavailable as error:
        raise HTTPException(
            503, detail={"code": "model_unavailable", "message": str(error)}
        ) from error
    if planner_result is not None:
        result = planner_result
    if isinstance(result, dict):
        return result
    if isinstance(result, PendingRunResult):
        response.status_code = 202
        return {
            "code": "approval_required",
            "run_id": result.run_id,
            "approval_id": result.approval_id,
            "tool_name": result.tool_name,
            "arguments": result.arguments,
            "trace": result.trace,
        }
    return {
        "run_id": result.run_id,
        "answer": result.answer,
        "usage": result.usage,
        "trace": result.trace,
    }


@router.post("/{approval_id}/approve")
async def approve(approval_id: str, request: Request, response: Response):
    return await decide(approval_id, True, request, response)


@router.post("/{approval_id}/reject")
async def reject(approval_id: str, request: Request, response: Response):
    return await decide(approval_id, False, request, response)
