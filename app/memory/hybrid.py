import json
import math
import sqlite3

import httpx

from app.memory.embeddings import CachedEmbeddings
from app.memory.repository import Database
from app.memory.vector import SqliteVecStore


def rrf(keyword: list[dict], vector: list[dict], k: int = 60) -> list[dict]:
    merged: dict[str, dict] = {}
    for source, hits in (("keyword", keyword), ("vector", vector)):
        for rank, hit in enumerate(hits, 1):
            entry = merged.setdefault(
                hit["id"],
                {
                    **hit,
                    "source": [],
                    "keyword_rank": None,
                    "vector_rank": None,
                    "rrf_score": 0.0,
                },
            )
            entry["source"].append(source)
            entry[f"{source}_rank"] = rank
            entry["rrf_score"] += 1 / (k + rank)
    return sorted(merged.values(), key=lambda hit: (-hit["rrf_score"], hit["id"]))


def cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    denominator = math.sqrt(sum(value * value for value in left)) * math.sqrt(
        sum(value * value for value in right)
    )
    return sum(a * b for a, b in zip(left, right)) / denominator if denominator else 0.0


class HybridRetriever:
    def __init__(
        self,
        database: Database,
        embeddings: CachedEmbeddings | None = None,
        remote_vector_store=None,
    ):
        self.database = database
        self.embeddings = embeddings
        self.remote_vector_store = remote_vector_store
        self.vector_store = SqliteVecStore()

    async def search(
        self, query: str, top_k: int = 8, owner_id: str | None = None
    ) -> list[dict]:
        keyword = await self.database.search_fts(
            query, limit=top_k * 3, owner_id=owner_id
        )
        vector: list[dict] = []
        if self.embeddings is not None:
            try:
                query_vector = await self.embeddings.embed(query)
                if self.remote_vector_store and self.remote_vector_store.available:
                    try:
                        vector = await self.remote_vector_store.search(
                            query_vector,
                            self.embeddings.model,
                            top_k * 3,
                            owner_id=owner_id,
                        )
                        records = {
                            item["id"]: item
                            for item in await self.database.get_memories_by_ids(
                                [item["id"] for item in vector], owner_id=owner_id
                            )
                        }
                        vector = [
                            {**records[item["id"]], "distance": item.get("distance")}
                            for item in vector
                            if item["id"] in records
                        ]
                    except Exception:  # noqa: BLE001 - fall back to local vectors
                        vector = []
                if vector:
                    return rrf(keyword, vector)[:top_k]
                candidates = await self.database.all_memories(owner_id=owner_id)
                prepared = [
                    {**row, "embedding": json.loads(row["embedding"])}
                    for row in candidates
                    if row["embedding"] is not None
                    and row["embedding_model"] == self.embeddings.model
                ]
                if self.vector_store.available:
                    try:
                        vector = self.vector_store.search(
                            query_vector, prepared, top_k * 3
                        )
                    except sqlite3.Error:
                        vector = sorted(
                            prepared,
                            key=lambda row: -cosine(query_vector, row["embedding"]),
                        )[: top_k * 3]
                else:
                    vector = sorted(
                        prepared,
                        key=lambda row: -cosine(query_vector, row["embedding"]),
                    )[: top_k * 3]
            except (httpx.HTTPError, ValueError, KeyError):
                vector = []
        return rrf(keyword, vector)[:top_k]
