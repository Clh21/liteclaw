from typing import Literal

import aiosqlite
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/admin", tags=["admin"])


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    role: Literal["admin", "user", "viewer"] = "user"


class CreateTokenRequest(BaseModel):
    label: str | None = Field(default=None, max_length=100)


@router.post("/users")
async def create_user(body: CreateUserRequest, request: Request):
    try:
        return await request.app.state.database.create_user(body.username, body.role)
    except aiosqlite.IntegrityError as error:
        raise HTTPException(409, detail={"code": "username_exists"}) from error


@router.post("/users/{user_id}/tokens")
async def create_token(user_id: str, body: CreateTokenRequest, request: Request):
    try:
        return await request.app.state.database.create_api_token(user_id, body.label)
    except KeyError as error:
        raise HTTPException(404, detail={"code": "user_not_found"}) from error


@router.delete("/tokens/{token_id}")
async def revoke_token(token_id: str, request: Request):
    if not await request.app.state.database.revoke_api_token(token_id):
        raise HTTPException(404, detail={"code": "token_not_found"})
    return {"revoked": True}
