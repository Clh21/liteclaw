import asyncio
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.memory.repository import Database


class FoundationTests(unittest.TestCase):
    def test_settings_resolve_database_path(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(db_path="data/liteclaw.db", workspace_root=directory)
            self.assertEqual(
                settings.database_path, Path(directory) / "data" / "liteclaw.db"
            )

    def test_migration_is_repeatable_and_creates_core_tables(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "nested" / "liteclaw.db"
            database = Database(db_path)
            asyncio.run(database.initialize())
            asyncio.run(database.initialize())
            with closing(sqlite3.connect(db_path)) as connection:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
                    )
                }
                self.assertTrue(
                    {
                        "sessions",
                        "messages",
                        "memories",
                        "memories_fts",
                        "embedding_cache",
                        "agent_runs",
                        "tool_events",
                        "approvals",
                    }.issubset(tables)
                )
                self.assertEqual(
                    connection.execute("PRAGMA journal_mode").fetchone()[0], "wal"
                )

    def test_health_reports_real_database_state(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(db_path="data/liteclaw.db", workspace_root=directory)
            with TestClient(create_app(settings)) as client:
                response = client.get("/health")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["database"], "ready")
                self.assertEqual(response.json()["status"], "ok")
                self.assertTrue(settings.database_path.exists())


if __name__ == "__main__":
    unittest.main()
