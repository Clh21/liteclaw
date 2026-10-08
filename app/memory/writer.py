import json
import re

import httpx
from pydantic import BaseModel, Field

from app.logging import log_event
from app.memory.embeddings import CachedEmbeddings
from app.memory.repository import Database
from app.memory.summarizer import SessionSummarizer
from app.models.base import BaseChatModel


class MemoryCandidate(BaseModel):
    content: str = Field(min_length=1, max_length=1000)
    kind: str = "fact"
    importance: float = Field(default=0.5, ge=0, le=1)


class MemoryWriter:
    def __init__(
        self,
        database: Database,
        embeddings: CachedEmbeddings | None = None,
        extractor_model: BaseChatModel | None = None,
    ):
        self.database = database
        self.embeddings = embeddings
        self.extractor_model = extractor_model
        self.summarizer = SessionSummarizer(database, model=extractor_model)

    async def after_turn(self, session_id: str, user_text: str) -> None:
        forget = re.search(r"(?:forget|忘记)\s*[:：]?\s*(.+)", user_text, re.IGNORECASE)
        if forget:
            target = forget.group(1).strip()
            if target:
                for memory in await self.database.search_fts(target):
                    if target.casefold() in memory["content"].casefold():
                        await self.database.delete_memory(memory["id"])
            return
        if re.search(r"不要记住|别记住|do not remember", user_text, re.IGNORECASE):
            return
        candidates = []
        match = re.search(
            r"(?:remember(?: that)?|记住)\s*[:：]?\s*(.+)",
            user_text,
            re.IGNORECASE | re.DOTALL,
        )
        if match:
            candidates.append(MemoryCandidate(content=match.group(1).strip()[:1000]))
        elif self.extractor_model is not None:
            try:
                response = await self.extractor_model.complete(
                    [
                        {
                            "role": "system",
                            "content": (
                                "Extract only durable personal preferences, project facts, or "
                                "ongoing goals explicitly stated by the user. Return a JSON "
                                "array of up to 5 objects with content, kind, importance. "
                                "Use [] if nothing is stable. No markdown or commentary."
                            ),
                        },
                        {"role": "user", "content": user_text[:4000]},
                    ],
                    [],
                )
                raw = json.loads(response.content or "[]")
                if not isinstance(raw, list):
                    raise TypeError("Memory extraction must return an array")
                candidates = [MemoryCandidate.model_validate(item) for item in raw[:5]]
            except Exception as error:  # noqa: BLE001 - extraction is best effort
                log_event("memory.extract_unavailable", error=type(error).__name__)
        for candidate in candidates:
            memory = await self.database.add_memory(
                candidate.content,
                kind=candidate.kind,
                importance=candidate.importance,
                session_id=session_id,
            )
            if self.embeddings is not None and memory["embedding"] is None:
                try:
                    vector = await self.embeddings.embed(candidate.content)
                    await self.database.set_memory_embedding(
                        memory["id"], self.embeddings.model, vector
                    )
                except (httpx.HTTPError, OSError, ValueError) as error:
                    log_event("embedding.unavailable", error=type(error).__name__)
        await self.summarizer.maybe_summarize(session_id)
