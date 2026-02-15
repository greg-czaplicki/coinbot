from __future__ import annotations

import unittest

from coinbot.decision_engine.kill_switch import AutoKillGuard, AutoKillThresholds, KillSwitch


class KillSwitchTests(unittest.TestCase):
    def test_auto_kill_activates_on_latency_breach(self) -> None:
        guard = AutoKillGuard(
            KillSwitch(),
            AutoKillThresholds(
                max_error_rate=0.2,
                max_p95_latency_ms=1200,
                recover_max_error_rate=0.1,
                recover_max_p95_latency_ms=800,
                recovery_consecutive_snapshots=2,
            ),
        )
        state = guard.evaluate(error_rate=0.0, p95_latency_ms=1500)
        self.assertTrue(state.active)
        self.assertEqual(state.reason, "auto_latency_threshold")

    def test_auto_kill_recovers_after_consecutive_healthy_snapshots(self) -> None:
        guard = AutoKillGuard(
            KillSwitch(),
            AutoKillThresholds(
                max_error_rate=0.2,
                max_p95_latency_ms=1200,
                recover_max_error_rate=0.1,
                recover_max_p95_latency_ms=800,
                recovery_consecutive_snapshots=2,
            ),
        )
        guard.evaluate(error_rate=0.0, p95_latency_ms=1500)
        state = guard.evaluate(error_rate=0.05, p95_latency_ms=700)
        self.assertTrue(state.active)
        state = guard.evaluate(error_rate=0.05, p95_latency_ms=700)
        self.assertFalse(state.active)
        self.assertEqual(state.reason, "")


if __name__ == "__main__":
    unittest.main()
