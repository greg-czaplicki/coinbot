from __future__ import annotations

import unittest
from datetime import datetime, timezone
from decimal import Decimal

from coinbot.main import _cross_source_event_key
from coinbot.schemas import Side, TradeEvent


class MainDedupeTests(unittest.TestCase):
    def test_cross_source_key_matches_for_equivalent_events(self) -> None:
        ts = datetime(2026, 2, 22, 17, 53, 42, tzinfo=timezone.utc)
        ws_event = TradeEvent(
            event_id="ws-1",
            source_wallet="0xabc",
            market_id="m1",
            market_slug="slug",
            outcome="YES",
            side=Side.BUY,
            price=Decimal("0.5"),
            shares=Decimal("10"),
            notional_usd=Decimal("5"),
            executed_ts=ts,
            source_path="clob_ws",
        )
        api_event = TradeEvent(
            event_id="api-1",
            source_wallet="0xabc",
            market_id="m1",
            market_slug="slug",
            outcome="yes",
            side=Side.BUY,
            price=Decimal("0.5000"),
            shares=Decimal("10.000"),
            notional_usd=Decimal("5.0"),
            executed_ts=ts,
            source_path="activity_api",
        )
        self.assertEqual(_cross_source_event_key(ws_event), _cross_source_event_key(api_event))

    def test_cross_source_key_differs_when_trade_differs(self) -> None:
        ts = datetime(2026, 2, 22, 17, 53, 42, tzinfo=timezone.utc)
        event_a = TradeEvent(
            event_id="a",
            source_wallet="0xabc",
            market_id="m1",
            market_slug="slug",
            outcome="YES",
            side=Side.BUY,
            price=Decimal("0.5"),
            shares=Decimal("10"),
            notional_usd=Decimal("5"),
            executed_ts=ts,
        )
        event_b = TradeEvent(
            event_id="b",
            source_wallet="0xabc",
            market_id="m1",
            market_slug="slug",
            outcome="YES",
            side=Side.BUY,
            price=Decimal("0.5"),
            shares=Decimal("12"),
            notional_usd=Decimal("6"),
            executed_ts=ts,
        )
        self.assertNotEqual(_cross_source_event_key(event_a), _cross_source_event_key(event_b))


if __name__ == "__main__":
    unittest.main()
