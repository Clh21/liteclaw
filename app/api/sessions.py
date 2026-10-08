from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/v1/sessions", tags=["sessions"])


class CreateSessionRequest(BaseModel):
    title: str | None = None


@router.post("")
async def create_session(request: Request, body: CreateSessionRequest | None = None):
    return await request.app.state.database.create_session(body.title if body else None)


@router.get("/{session_id}")
async def get_session(session_id: str, request: Request):
    database = request.app.state.database
    session = await database.get_session(session_id)
    if session is None:
        raise HTTPException(404, detail={"code": "session_not_found"})
    return {**session, "messages": await database.get_messages(session_id)}
