from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Final


SCHEMA: Final[str] = """
CREATE TABLE IF NOT EXISTS processed_events (
  event_id TEXT PRIMARY KEY,
  tx_hash TEXT NOT NULL,
  market_id TEXT NOT NULL,
  seen_at_unix INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_processed_events_tx_hash
ON processed_events (tx_hash);
"""


@dataclass
class EventKey:
    event_id: str
    tx_hash: str
    market_id: str
    seen_at_unix: int


class SqliteDedupeStore:
    def __init__(self, db_path: str = "data/coinbot.db") -> None:
        self._db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            conn.commit()

    def already_seen(self, event_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM processed_events WHERE event_id = ? LIMIT 1",
                (event_id,),
            ).fetchone()
        return row is not None

    def mark_seen(self, key: EventKey) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO processed_events (
                  event_id, tx_hash, market_id, seen_at_unix
                ) VALUES (?, ?, ?, ?)
                """,
                (key.event_id, key.tx_hash, key.market_id, key.seen_at_unix),
            )
            conn.commit()
        return cursor.rowcount == 1

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn
