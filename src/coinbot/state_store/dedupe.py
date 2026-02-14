from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Final


SCHEMA: Final[str] = """
CREATE TABLE IF NOT EXISTS processed_events (
  dedupe_key TEXT PRIMARY KEY,
  event_id TEXT NOT NULL,
  tx_hash TEXT,
  sequence TEXT,
  market_id TEXT NOT NULL,
  seen_at_unix INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_processed_events_tx_hash
ON processed_events (tx_hash);
"""


@dataclass
class EventKey:
    event_id: str
    market_id: str
    seen_at_unix: int
    tx_hash: str = ""
    sequence: str = ""


class SqliteDedupeStore:
    def __init__(self, db_path: str = "data/coinbot.db") -> None:
        self._db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            conn.commit()

    def already_seen(self, dedupe_key: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM processed_events WHERE dedupe_key = ? LIMIT 1",
                (dedupe_key,),
            ).fetchone()
        return row is not None

    def mark_seen(self, key: EventKey) -> bool:
        dedupe_key = build_dedupe_key(key)
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO processed_events (
                  dedupe_key, event_id, tx_hash, sequence, market_id, seen_at_unix
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    dedupe_key,
                    key.event_id,
                    key.tx_hash,
                    key.sequence,
                    key.market_id,
                    key.seen_at_unix,
                ),
            )
            conn.commit()
        return cursor.rowcount == 1

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn


def build_dedupe_key(key: EventKey) -> str:
    if key.event_id:
        return f"id:{key.event_id}"
    if key.tx_hash and key.sequence:
        return f"txseq:{key.tx_hash}:{key.sequence}"
    if key.tx_hash:
        return f"tx:{key.tx_hash}:{key.market_id}"
    return f"fallback:{key.market_id}:{key.seen_at_unix}"
