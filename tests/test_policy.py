from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest

from coinbot.config import ExecutionConfig, SizingConfig
from coinbot.decision_engine.policy import IntentPolicy
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


if __name__ == "__main__":
    unittest.main()
