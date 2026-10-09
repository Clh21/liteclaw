from fastapi import HTTPException, Request


def owner_scope(request: Request) -> str | None:
    if not request.app.state.settings.rbac_enabled:
        return None
    principal = request.state.principal
    return None if principal.role == "admin" else principal.id


def creation_owner(request: Request) -> str | None:
    if not request.app.state.settings.rbac_enabled:
        return None
    return request.state.principal.id


async def resolve_creation_owner(
    request: Request, requested_owner_id: str | None = None
) -> str | None:
    if not request.app.state.settings.rbac_enabled:
        return None
    principal = request.state.principal
    if principal.role != "admin" or requested_owner_id is None:
        return principal.id
    if requested_owner_id == principal.id:
        return requested_owner_id
    if await request.app.state.database.get_active_user(requested_owner_id) is None:
        raise HTTPException(404, detail={"code": "owner_not_found"})
    return requested_owner_id


async def require_session(request: Request, session_id: str) -> dict:
    session = await request.app.state.database.get_session_for_owner(
        session_id, owner_scope(request)
    )
    if session is None:
        raise HTTPException(404, detail={"code": "session_not_found"})
    return session
