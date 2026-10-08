from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/v1/browser/sessions", tags=["browser"])


async def require_session(request: Request, session_id: str) -> None:
    if await request.app.state.database.get_session(session_id) is None:
        raise HTTPException(404, detail={"code": "session_not_found"})


@router.get("/{session_id}/state")
async def browser_state(session_id: str, request: Request):
    await require_session(request, session_id)
    return request.app.state.browser.state_store.metadata(session_id)


@router.delete("/{session_id}/state")
async def delete_browser_state(session_id: str, request: Request):
    await require_session(request, session_id)
    return {"deleted": await request.app.state.browser.reset(session_id)}
