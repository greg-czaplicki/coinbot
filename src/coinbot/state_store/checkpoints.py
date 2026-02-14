from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Final


SCHEMA: Final[str] = """
CREATE TABLE IF NOT EXISTS checkpoints (
  stream_name TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""


class SqliteCheckpointStore:
    def __init__(self, db_path: str = "data/coinbot.db") -> None:
        self._db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            conn.commit()

    def get(self, stream_name: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM checkpoints WHERE stream_name = ?",
                (stream_name,),
            ).fetchone()
        return row[0] if row else None

    def set(self, stream_name: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO checkpoints (stream_name, value)
                VALUES (?, ?)
                ON CONFLICT(stream_name)
                DO UPDATE SET value = excluded.value
                """,
                (stream_name, value),
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn
