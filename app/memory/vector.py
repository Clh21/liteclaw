import json
import sqlite3
from contextlib import closing


class SqliteVecStore:
    """Optional sqlite-vec KNN with a Python cosine fallback in the retriever."""

    def __init__(self):
        try:
            import sqlite_vec

            self.sqlite_vec = sqlite_vec
            connection = self._connect()
            connection.close()
            self.available = True
        except (ImportError, sqlite3.Error, OSError):
            self.sqlite_vec = None
            self.available = False

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(":memory:")
        connection.enable_load_extension(True)
        self.sqlite_vec.load(connection)
        connection.enable_load_extension(False)
        return connection

    def search(
        self, query: list[float], candidates: list[dict], limit: int
    ) -> list[dict]:
        if not self.available or not query:
            return []
        matching = [item for item in candidates if len(item["embedding"]) == len(query)]
        if not matching:
            return []
        with closing(self._connect()) as connection:
            connection.execute(
                f"CREATE VIRTUAL TABLE vectors USING vec0(embedding float[{len(query)}])"
            )
            connection.executemany(
                "INSERT INTO vectors(rowid,embedding) VALUES(?,?)",
                [
                    (index, json.dumps(item["embedding"]))
                    for index, item in enumerate(matching, 1)
                ],
            )
            rows = connection.execute(
                "SELECT rowid FROM vectors WHERE embedding MATCH ? AND k = ? ORDER BY distance",
                (json.dumps(query), limit),
            ).fetchall()
        return [matching[rowid - 1] for (rowid,) in rows]
