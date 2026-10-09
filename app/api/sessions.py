from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.api.access import require_session, resolve_creation_owner

router = APIRouter(prefix="/v1/sessions", tags=["sessions"])


class CreateSessionRequest(BaseModel):
    title: str | None = None
    owner_id: str | None = None


@router.post("")
async def create_session(request: Request, body: CreateSessionRequest | None = None):
    return await request.app.state.database.create_session(
        body.title if body else None,
        owner_id=await resolve_creation_owner(request, body.owner_id if body else None),
    )


@router.get("/{session_id}")
async def get_session(session_id: str, request: Request):
    database = request.app.state.database
    session = await require_session(request, session_id)
    return {**session, "messages": await database.get_messages(session_id)}
