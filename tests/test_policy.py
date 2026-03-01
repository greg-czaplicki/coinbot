from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest

from coinbot.config import ExecutionConfig, SizingConfig
from coinbot.decision_engine.policy import IntentPolicy, WindowRiskTracker
from coinbot.schemas import ExecutionIntent, Side, TradeEvent


class IntentPolicyTests(unittest.TestCase):
    def _intent(self) -> ExecutionIntent:
        return ExecutionIntent(
            intent_id="intent-1",
            market_id="m1",
            outcome="YES",
            side=Side.BUY,
            target_notional_usd=Decimal("10"),
            max_slippage_bps=60,
            coalesced_event_ids=("e1",),
        )

    def _event(self, executed_ts: datetime) -> TradeEvent:
        return TradeEvent(
            event_id="e1",
            source_wallet="0x1d0034134e339a309700ff2d34e99fa2d48b0313",
            market_id="m1",
            market_slug="m1",
            outcome="YES",
            side=Side.BUY,
            price=Decimal("0.55"),
            shares=Decimal("10"),
            notional_usd=Decimal("5.5"),
            executed_ts=executed_ts,
        )

    def test_blocks_stale_source_event_when_cutoff_enabled(self) -> None:
        policy = IntentPolicy(
            SizingConfig(),
            ExecutionConfig(),
            max_source_staleness_ms=4000,
        )
        stale_event = self._event(datetime.now(timezone.utc) - timedelta(seconds=10))

        result = policy.apply(self._intent(), [stale_event])

        self.assertIsNone(result.intent)
        self.assertEqual(result.blocked_reason, "source_stale")

    def test_allows_recent_source_event_when_cutoff_enabled(self) -> None:
        policy = IntentPolicy(
            SizingConfig(),
            ExecutionConfig(),
            max_source_staleness_ms=4000,
        )
        fresh_event = self._event(datetime.now(timezone.utc) - timedelta(seconds=1))

        result = policy.apply(self._intent(), [fresh_event])

        self.assertIsNotNone(result.intent)
        self.assertEqual(result.blocked_reason, "")


class WindowRiskTrackerTests(unittest.TestCase):
    def _intent(self, *, side: Side, notional: str = "1.5") -> ExecutionIntent:
        return ExecutionIntent(
            intent_id=f"intent-{side.value.lower()}",
            market_id="m1",
            outcome="YES",
            side=side,
            target_notional_usd=Decimal(notional),
            max_slippage_bps=120,
            coalesced_event_ids=("e1",),
            window_id="w1",
        )

    def test_market_cap_blocks_when_net_exposure_exceeds_cap(self) -> None:
        tracker = WindowRiskTracker(
            SizingConfig(
                max_notional_per_market_usd=3.0,
                max_total_notional_per_15m_window_usd=100.0,
                max_daily_traded_volume_usd=100.0,
            )
        )
        self.assertFalse(tracker.check_and_apply(self._intent(side=Side.BUY)).blocked)
        self.assertFalse(tracker.check_and_apply(self._intent(side=Side.BUY)).blocked)

        blocked = tracker.check_and_apply(self._intent(side=Side.BUY))
        self.assertTrue(blocked.blocked)
        self.assertEqual(blocked.blocked_reason, "market_cap_exceeded")

    def test_opposite_side_reduces_market_exposure(self) -> None:
        tracker = WindowRiskTracker(
            SizingConfig(
                max_notional_per_market_usd=3.0,
                max_total_notional_per_15m_window_usd=100.0,
                max_daily_traded_volume_usd=100.0,
            )
        )
        self.assertFalse(tracker.check_and_apply(self._intent(side=Side.BUY)).blocked)
        self.assertFalse(tracker.check_and_apply(self._intent(side=Side.BUY)).blocked)

        # Opposite trade should reduce net exposure and be accepted.
        unwind = tracker.check_and_apply(self._intent(side=Side.SELL))
        self.assertFalse(unwind.blocked)
        self.assertEqual(unwind.market_exposure_usd["m1"], Decimal("1.5"))

        # After reducing exposure, a new BUY can be accepted again.
        resumed = tracker.check_and_apply(self._intent(side=Side.BUY))
        self.assertFalse(resumed.blocked)
        self.assertEqual(resumed.market_exposure_usd["m1"], Decimal("3.0"))


if __name__ == "__main__":
    unittest.main()
