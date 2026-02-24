from __future__ import annotations

import logging
import unittest

from coinbot.telemetry.logging import ConciseFilter


class LoggingProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.filter = ConciseFilter()

    def _record(self, *, msg: str, level: int = logging.INFO) -> logging.LogRecord:
        return logging.LogRecord(
            name="test",
            level=level,
            pathname=__file__,
            lineno=1,
            msg=msg,
            args=(),
            exc_info=None,
        )

    def test_allows_core_messages(self) -> None:
        self.assertTrue(self.filter.filter(self._record(msg="order_submitted")))
        self.assertTrue(self.filter.filter(self._record(msg="telemetry_snapshot")))

    def test_blocks_noisy_messages(self) -> None:
        self.assertFalse(self.filter.filter(self._record(msg="ws_recv_progress count=50")))
        self.assertFalse(self.filter.filter(self._record(msg="dry_run_blocked")))
        self.assertFalse(self.filter.filter(self._record(msg="dry_run_intent")))

    def test_allows_warnings_and_errors(self) -> None:
        self.assertTrue(self.filter.filter(self._record(msg="anything", level=logging.WARNING)))
        self.assertTrue(self.filter.filter(self._record(msg="anything", level=logging.ERROR)))


if __name__ == "__main__":
    unittest.main()
