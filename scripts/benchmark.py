import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.context import ContextBuilder, estimate_tokens
from app.memory.embeddings import CachedEmbeddings
from app.memory.repository import Database


class DemoEmbeddingProvider:
    model = "demo-embedding"

    async def embed(self, text: str) -> list[float]:
        return [float(len(text)), 1.0]


async def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database = Database(Path(directory) / "benchmark.db")
        await database.initialize()
        embeddings = CachedEmbeddings(database, DemoEmbeddingProvider())
        for index in range(100):
            await embeddings.embed(f"repeatable note {index % 10}")
        session = await database.create_session()
        for index in range(24):
            await database.append_message(
                session["id"], "user", f"Conversation item {index}: " + "history " * 100
            )
        await database.update_summary(
            session["id"], "Goal: retain the important history while using fewer tokens"
        )
        history = await database.get_messages(session["id"])
        full_tokens = sum(estimate_tokens(message["content"]) for message in history)
        context = await ContextBuilder(database, budget=1000, recent_budget=600).build(
            session["id"]
        )
        print(
            json.dumps(
                {
                    "embedding": embeddings.stats,
                    "context": {
                        "full_history_estimated_tokens": full_tokens,
                        "built_context_estimated_tokens": context.stats.estimated_tokens,
                        "messages_kept": context.stats.messages_kept,
                    },
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
