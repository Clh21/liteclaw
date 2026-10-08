import hashlib
from typing import Protocol

import httpx

from app.memory.repository import Database


class EmbeddingProvider(Protocol):
    model: str

    async def embed(self, text: str) -> list[float]: ...


class OpenAIEmbeddingProvider:
    def __init__(self, model: str, base_url: str, api_key: str):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    async def embed(self, text: str) -> list[float]:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self.base_url}/embeddings",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.model, "input": text},
            )
            response.raise_for_status()
            return response.json()["data"][0]["embedding"]


class CachedEmbeddings:
    def __init__(self, database: Database, provider: EmbeddingProvider):
        self.database = database
        self.provider = provider
        self.stats = {"embedding_requests": 0, "cache_hits": 0, "cache_misses": 0}

    @property
    def model(self) -> str:
        return self.provider.model

    async def embed(self, text: str) -> list[float]:
        normalized = " ".join(text.split())
        content_hash = hashlib.sha256(
            f"{self.model}\0{normalized}".encode()
        ).hexdigest()
        cached = await self.database.get_cached_embedding(content_hash, self.model)
        if cached is not None:
            self.stats["cache_hits"] += 1
            return cached
        self.stats["cache_misses"] += 1
        self.stats["embedding_requests"] += 1
        vector = await self.provider.embed(normalized)
        await self.database.put_cached_embedding(content_hash, self.model, vector)
        return vector
