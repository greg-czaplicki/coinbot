from __future__ import annotations

from decimal import Decimal
import unittest

from coinbot.telemetry.pnl import PnLTracker


class PnLTests(unittest.TestCase):
    def test_fee_and_net_tracking(self) -> None:
        pnl = PnLTracker(fee_bps=Decimal("10"))  # 0.1%
        pnl.apply_fill(
            market_id="m1",
            outcome="Up",
            side="BUY",
            qty=Decimal("10"),
            price=Decimal("0.5"),
        )
        pnl.set_mark("m1", "Up", Decimal("0.6"))
        snap = pnl.snapshot()
        self.assertEqual(snap.realized_trading_usd, Decimal("0"))
        self.assertEqual(snap.unrealized_usd, Decimal("1.0"))
        self.assertEqual(snap.fees_usd, Decimal("0.005"))
        self.assertEqual(snap.net_usd, Decimal("0.995"))

    def test_market_settlement_realizes_pnl(self) -> None:
        pnl = PnLTracker()
        pnl.apply_fill(
            market_id="m2",
            outcome="Down",
            side="BUY",
            qty=Decimal("4"),
            price=Decimal("0.4"),
        )
        settled = pnl.settle_market(
            market_id="m2",
            winning_outcome="Down",
        )
        self.assertEqual(settled, 1)
        snap = pnl.snapshot()
        self.assertEqual(snap.realized_settled_usd, Decimal("2.4"))
        self.assertEqual(snap.unrealized_usd, Decimal("0"))


if __name__ == "__main__":
    unittest.main()
