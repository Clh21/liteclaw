import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.logging import log_event

router = APIRouter(prefix="/v1/memory", tags=["memory"])


class CreateMemoryRequest(BaseModel):
    content: str = Field(min_length=1)
    kind: str = "note"
    importance: float = Field(default=0.5, ge=0, le=1)


@router.get("/search")
async def search_memory(
    request: Request,
    q: str = Query(min_length=1),
    top_k: int = Query(default=8, ge=1, le=100),
):
    results = await request.app.state.retriever.search(q, top_k)
    return {
        "results": [
            {key: value for key, value in result.items() if key != "embedding"}
            for result in results
        ]
    }


@router.post("")
async def create_memory(body: CreateMemoryRequest, request: Request):
    memory = await request.app.state.database.add_memory(
        body.content, body.kind, body.importance
    )
    embeddings = request.app.state.embeddings
    if embeddings is not None and memory["embedding"] is None:
        try:
            vector = await embeddings.embed(body.content)
            await request.app.state.database.set_memory_embedding(
                memory["id"], embeddings.model, vector
            )
        except (httpx.HTTPError, OSError, ValueError) as error:
            log_event("embedding.unavailable", error=type(error).__name__)
    return {key: value for key, value in memory.items() if key != "embedding"}


@router.delete("/{memory_id}")
async def delete_memory(memory_id: str, request: Request):
    if not await request.app.state.database.delete_memory(memory_id):
        raise HTTPException(404, detail={"code": "memory_not_found"})
    return {"deleted": True}
