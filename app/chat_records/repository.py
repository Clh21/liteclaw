from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from app.chat_records.parser import ParsedMessage
from app.memory.repository import Database


class ChatRecordRepository:
    def __init__(self, database: Database):
        self.database = database

    async def import_messages(
        self,
        filename: str,
        data: bytes,
        rows: list[ParsedMessage],
        owner_id: str | None,
        self_sender: str,
        timezone_name: str,
        conversation: str | None,
    ) -> dict:
        scope_key = owner_id or "__local__"
        digest = sha256(
            data
            + (conversation or "").encode()
            + self_sender.encode()
            + timezone_name.encode()
        ).hexdigest()
        now = datetime.now(timezone.utc).isoformat()
        times = [row.sent_at for row in rows]
        source = {
            "id": uuid4().hex,
            "owner_id": owner_id,
            "scope_key": scope_key,
            "filename": Path(filename).name,
            "format": Path(filename).suffix.lower().lstrip("."),
            "conversation": conversation,
            "self_sender": self_sender,
            "timezone": timezone_name,
            "file_digest": digest,
            "message_count": 0,
            "first_at": min(times),
            "last_at": max(times),
            "created_at": now,
        }
        async with self.database.connection() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            existing = await (
                await connection.execute(
                    "SELECT * FROM chat_sources WHERE scope_key=? AND file_digest=?",
                    (scope_key, digest),
                )
            ).fetchone()
            if existing:
                return dict(existing)
            await connection.execute(
                """INSERT INTO chat_sources
                (id,owner_id,scope_key,filename,format,conversation,self_sender,timezone,
                file_digest,message_count,first_at,last_at,created_at)
                VALUES(:id,:owner_id,:scope_key,:filename,:format,:conversation,
                :self_sender,:timezone,:file_digest,:message_count,:first_at,:last_at,:created_at)""",
                source,
            )
            count = 0
            for row in rows:
                fingerprint = sha256(
                    f"{row.conversation}\0{row.sent_at}\0{row.sender}\0{row.content}".encode()
                ).hexdigest()
                result = await connection.execute(
                    """INSERT OR IGNORE INTO chat_messages
                    (id,source_id,owner_id,scope_key,conversation,sent_at,sender,content,source_row,fingerprint)
                    VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (
                        uuid4().hex,
                        source["id"],
                        owner_id,
                        scope_key,
                        row.conversation,
                        row.sent_at,
                        row.sender,
                        row.content,
                        row.source_row,
                        fingerprint,
                    ),
                )
                count += result.rowcount
            source["message_count"] = count
            await connection.execute(
                "UPDATE chat_sources SET message_count=? WHERE id=?",
                (count, source["id"]),
            )
            await connection.commit()
        return source

    async def get_source(
        self, source_id: str, owner_id: str | None = None
    ) -> dict | None:
        async with self.database.connection() as connection:
            if owner_id is None:
                cursor = await connection.execute(
                    "SELECT * FROM chat_sources WHERE id=?", (source_id,)
                )
            else:
                cursor = await connection.execute(
                    "SELECT * FROM chat_sources WHERE id=? AND owner_id=?",
                    (source_id, owner_id),
                )
            row = await cursor.fetchone()
        return dict(row) if row else None

    async def list_sources(self, owner_id: str | None = None) -> list[dict]:
        async with self.database.connection() as connection:
            if owner_id is None:
                cursor = await connection.execute(
                    "SELECT * FROM chat_sources ORDER BY created_at DESC,id DESC"
                )
            else:
                cursor = await connection.execute(
                    "SELECT * FROM chat_sources WHERE owner_id=? ORDER BY created_at DESC,id DESC",
                    (owner_id,),
                )
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def list_messages(
        self,
        owner_id: str | None = None,
        source_id: str | None = None,
        conversation: str | None = None,
        start_at: str | None = None,
        end_at: str | None = None,
        limit: int | None = 100,
        offset: int = 0,
    ) -> list[dict]:
        clauses = []
        parameters: list[object] = []
        if owner_id is not None:
            clauses.append("m.owner_id=?")
            parameters.append(owner_id)
        for field, value in (
            ("source_id", source_id),
            ("conversation", conversation),
        ):
            if value is not None:
                clauses.append(f"m.{field}=?")
                parameters.append(value)
        if start_at:
            clauses.append("m.sent_at>=?")
            parameters.append(start_at)
        if end_at:
            clauses.append("m.sent_at<?")
            parameters.append(end_at)
        if source_id is None:
            clauses.append(
                "m.id=(SELECT MIN(d.id) FROM chat_messages d "
                "WHERE d.scope_key=m.scope_key AND d.fingerprint=m.fingerprint)"
            )
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        async with self.database.connection() as connection:
            query = (
                "SELECT m.*,s.self_sender FROM chat_messages m "
                "JOIN chat_sources s ON s.id=m.source_id"
                + where
                + " ORDER BY m.sent_at,m.id"
            )
            if limit is None:
                cursor = await connection.execute(query, parameters)
            else:
                cursor = await connection.execute(
                    query + " LIMIT ? OFFSET ?", [*parameters, limit, offset]
                )
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def delete_source(self, source_id: str, owner_id: str | None = None) -> bool:
        async with self.database.connection() as connection:
            if owner_id is None:
                cursor = await connection.execute(
                    "DELETE FROM chat_sources WHERE id=?", (source_id,)
                )
            else:
                cursor = await connection.execute(
                    "DELETE FROM chat_sources WHERE id=? AND owner_id=?",
                    (source_id, owner_id),
                )
            await connection.commit()
        return cursor.rowcount == 1
