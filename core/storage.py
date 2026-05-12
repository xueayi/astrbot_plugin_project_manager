"""Async SQLite storage for raw messages and LLM summaries."""

from __future__ import annotations

import logging
import time
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    group_id TEXT NOT NULL,
    sender_id TEXT NOT NULL,
    sender_name TEXT,
    content TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    processed INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_msg_project_time
    ON raw_messages(project_id, timestamp);

CREATE TABLE IF NOT EXISTS summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    summary_json TEXT NOT NULL,
    raw_text TEXT,
    created_at INTEGER NOT NULL,
    message_count INTEGER,
    time_range_start INTEGER,
    time_range_end INTEGER
);

CREATE TABLE IF NOT EXISTS operation_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    detail TEXT,
    success INTEGER DEFAULT 1,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_log_project_time
    ON operation_logs(project_id, created_at);
"""


class MessageStore:
    """Async wrapper around an SQLite database for plugin data."""

    def __init__(self, data_dir: Path) -> None:
        self._db_path = data_dir / "messages.db"
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self._db_path))
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(_SCHEMA)
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    # ---- raw messages ----

    async def insert_message(
        self,
        *,
        project_id: str,
        group_id: str,
        sender_id: str,
        sender_name: str | None,
        content: str,
        timestamp: int | None = None,
    ) -> None:
        ts = timestamp or int(time.time())
        await self._db.execute(
            "INSERT INTO raw_messages "
            "(project_id, group_id, sender_id, sender_name, content, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (project_id, group_id, sender_id, sender_name, content, ts),
        )
        await self._db.commit()

    async def get_unprocessed_messages(
        self, project_id: str, limit: int = 2000
    ) -> list[dict]:
        cursor = await self._db.execute(
            "SELECT * FROM raw_messages "
            "WHERE project_id = ? AND processed = 0 "
            "ORDER BY timestamp ASC LIMIT ?",
            (project_id, limit),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def mark_messages_processed(self, message_ids: list[int]) -> None:
        if not message_ids:
            return
        placeholders = ",".join("?" * len(message_ids))
        await self._db.execute(
            f"UPDATE raw_messages SET processed = 1 WHERE id IN ({placeholders})",
            message_ids,
        )
        await self._db.commit()

    async def get_message_count(self, project_id: str, since: int = 0) -> int:
        cursor = await self._db.execute(
            "SELECT COUNT(*) FROM raw_messages WHERE project_id = ? AND timestamp >= ?",
            (project_id, since),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def cleanup_old_messages(self, retention_days: int) -> int:
        cutoff = int(time.time()) - retention_days * 86400
        cursor = await self._db.execute(
            "DELETE FROM raw_messages WHERE processed = 1 AND timestamp < ?",
            (cutoff,),
        )
        await self._db.commit()
        return cursor.rowcount

    # ---- summaries ----

    async def insert_summary(
        self,
        *,
        project_id: str,
        summary_json: str,
        raw_text: str | None = None,
        message_count: int = 0,
        time_range_start: int = 0,
        time_range_end: int = 0,
    ) -> int:
        cursor = await self._db.execute(
            "INSERT INTO summaries "
            "(project_id, summary_json, raw_text, created_at, "
            "message_count, time_range_start, time_range_end) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                project_id,
                summary_json,
                raw_text,
                int(time.time()),
                message_count,
                time_range_start,
                time_range_end,
            ),
        )
        await self._db.commit()
        return cursor.lastrowid

    async def get_recent_summaries(self, project_id: str, limit: int = 5) -> list[dict]:
        cursor = await self._db.execute(
            "SELECT * FROM summaries "
            "WHERE project_id = ? ORDER BY created_at DESC LIMIT ?",
            (project_id, limit),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # ---- operation logs ----

    async def log_operation(
        self,
        *,
        project_id: str,
        operation: str,
        detail: str | None = None,
        success: bool = True,
    ) -> None:
        await self._db.execute(
            "INSERT INTO operation_logs "
            "(project_id, operation, detail, success, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (project_id, operation, detail, 1 if success else 0, int(time.time())),
        )
        await self._db.commit()

    async def get_recent_logs(self, project_id: str, limit: int = 20) -> list[dict]:
        cursor = await self._db.execute(
            "SELECT * FROM operation_logs "
            "WHERE project_id = ? ORDER BY created_at DESC LIMIT ?",
            (project_id, limit),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
