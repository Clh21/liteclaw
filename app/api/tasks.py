from fastapi import APIRouter, HTTPException, Query, Request, Response

from app.api.access import creation_owner, owner_scope
from app.logging import log_event
from app.tasks.models import TaskCreate, TaskStatus, utc_now

router = APIRouter(prefix="/v1/tasks", tags=["tasks"])


@router.post("", status_code=201)
async def create_task(body: TaskCreate, request: Request):
    try:
        task = await request.app.state.task_repository.create(
            body,
            owner_id=creation_owner(request),
            access_owner_id=owner_scope(request),
        )
    except KeyError as error:
        raise HTTPException(404, detail={"code": "session_not_found"}) from error
    log_event("task.created", task_id=task["id"])
    return task


@router.get("")
async def list_tasks(
    request: Request,
    status: TaskStatus | None = None,
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return {
        "tasks": await request.app.state.task_repository.list(
            status.value if status else None,
            limit,
            offset,
            owner_id=owner_scope(request),
        )
    }


@router.get("/{task_id}")
async def get_task(task_id: str, request: Request):
    task = await request.app.state.task_repository.get(
        task_id, owner_id=owner_scope(request)
    )
    if task is None:
        raise HTTPException(404, detail={"code": "task_not_found"})
    return task


@router.post("/{task_id}/pause")
async def pause_task(task_id: str, request: Request):
    repository = request.app.state.task_repository
    if await repository.get(task_id, owner_id=owner_scope(request)) is None:
        raise HTTPException(404, detail={"code": "task_not_found"})
    task = await repository.pause(task_id)
    if task is None:
        raise HTTPException(409, detail={"code": "invalid_task_state"})
    log_event("task.paused", task_id=task_id)
    return task


@router.post("/{task_id}/resume")
async def resume_task(task_id: str, request: Request):
    repository = request.app.state.task_repository
    if await repository.get(task_id, owner_id=owner_scope(request)) is None:
        raise HTTPException(404, detail={"code": "task_not_found"})
    task = await repository.resume(task_id, utc_now())
    if task is None:
        raise HTTPException(409, detail={"code": "invalid_task_state"})
    log_event("task.resumed", task_id=task_id)
    return task


@router.delete("/{task_id}")
async def delete_task(task_id: str, request: Request, response: Response):
    if (
        await request.app.state.task_repository.get(
            task_id, owner_id=owner_scope(request)
        )
        is None
    ):
        raise HTTPException(404, detail={"code": "task_not_found"})
    if not await request.app.state.task_repository.delete(task_id):
        raise HTTPException(404, detail={"code": "task_not_found"})
    return {"deleted": True}
