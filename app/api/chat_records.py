from fastapi import APIRouter, HTTPException, Query, Request

from app.api.access import owner_scope, resolve_creation_owner
from app.chat_records.parser import MAX_BYTES, ImportFormatError, parse_chat_export

router = APIRouter(prefix="/v1/chat-records", tags=["chat-records"])


@router.post("/import", status_code=201)
async def import_chat_records(
    request: Request,
    filename: str = Query(min_length=1),
    self_sender: str = Query(min_length=1),
    conversation: str | None = None,
    timezone: str = "Asia/Shanghai",
    owner_id: str | None = None,
):
    if (
        request.headers.get("content-length")
        and int(request.headers["content-length"]) > MAX_BYTES
    ):
        raise HTTPException(413, detail={"code": "file_too_large"})
    data = await request.body()
    try:
        rows = parse_chat_export(filename, data, timezone, conversation)
    except ImportFormatError as error:
        raise HTTPException(422, detail={"code": str(error)}) from error
    assigned_owner = await resolve_creation_owner(request, owner_id)
    return await request.app.state.chat_record_repository.import_messages(
        filename,
        data,
        rows,
        assigned_owner,
        self_sender.strip(),
        timezone,
        conversation,
    )


@router.get("/sources")
async def list_chat_sources(request: Request):
    return {
        "sources": await request.app.state.chat_record_repository.list_sources(
            owner_scope(request)
        )
    }


@router.get("/messages")
async def list_chat_messages(
    request: Request,
    source_id: str | None = None,
    conversation: str | None = None,
    start_at: str | None = None,
    end_at: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    repository = request.app.state.chat_record_repository
    if (
        source_id
        and await repository.get_source(source_id, owner_scope(request)) is None
    ):
        raise HTTPException(404, detail={"code": "source_not_found"})
    return {
        "messages": await repository.list_messages(
            owner_scope(request),
            source_id,
            conversation,
            start_at,
            end_at,
            limit,
            offset,
        )
    }


@router.delete("/sources/{source_id}")
async def delete_chat_source(source_id: str, request: Request):
    if not await request.app.state.chat_record_repository.delete_source(
        source_id, owner_scope(request)
    ):
        raise HTTPException(404, detail={"code": "source_not_found"})
    return {"deleted": True}
