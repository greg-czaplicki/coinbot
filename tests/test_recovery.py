from __future__ import annotations

import tempfile
import unittest

from coinbot.state_store.checkpoints import SqliteCheckpointStore
from coinbot.state_store.dedupe import EventKey, SqliteDedupeStore, build_dedupe_key


class RecoveryTests(unittest.TestCase):
    def test_checkpoint_persists_across_restarts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = f"{tmp}/coinbot.db"
            store = SqliteCheckpointStore(db_path)
            store.set("source_activity", "evt-123")

            restarted = SqliteCheckpointStore(db_path)
            self.assertEqual(restarted.get("source_activity"), "evt-123")

    def test_dedupe_persists_across_restarts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = f"{tmp}/coinbot.db"
            key = EventKey(
                event_id="evt-1",
                market_id="m1",
                tx_hash="0xabc",
                sequence="42",
                seen_at_unix=1,
            )
            store = SqliteDedupeStore(db_path)
            self.assertTrue(store.mark_seen(key))
            self.assertFalse(store.mark_seen(key))

            restarted = SqliteDedupeStore(db_path)
            self.assertTrue(restarted.already_seen(build_dedupe_key(key)))


if __name__ == "__main__":
    unittest.main()
