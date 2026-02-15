from __future__ import annotations

import unittest

from coinbot.telemetry.metrics import MetricsCollector


class MetricsCollectorTests(unittest.TestCase):
    def test_window_snapshot_resets_interval_metrics(self) -> None:
        metrics = MetricsCollector()
        correlation_id = "cid-1"

        metrics.record_event_receive(correlation_id, 1000)
        metrics.record_order_submit(correlation_id, 2500)
        metrics.record_ack(correlation_id, 2600, accepted=False)

        first = metrics.snapshot_window()
        self.assertAlmostEqual(first.reject_rate, 1.0)
        self.assertIsNotNone(first.copy_delay_ms)
        assert first.copy_delay_ms is not None
        self.assertEqual(first.copy_delay_ms.p95, 1500)

        second = metrics.snapshot_window()
        self.assertEqual(second.reject_rate, 0.0)
        self.assertIsNone(second.copy_delay_ms)


if __name__ == "__main__":
    unittest.main()
