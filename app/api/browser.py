from fastapi import APIRouter, Request

from app.api.access import require_session

router = APIRouter(prefix="/v1/browser/sessions", tags=["browser"])


@router.get("/{session_id}/state")
async def browser_state(session_id: str, request: Request):
    await require_session(request, session_id)
    return request.app.state.browser.state_store.metadata(session_id)


@router.delete("/{session_id}/state")
async def delete_browser_state(session_id: str, request: Request):
    await require_session(request, session_id)
    return {"deleted": await request.app.state.browser.reset(session_id)}
