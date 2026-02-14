from __future__ import annotations

import asyncio
import tempfile
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

from coinbot.config import ExecutionConfig, PolymarketConfig
from coinbot.decision_engine.coalescer import CoalescerConfig, IntentNetCoalescer
from coinbot.executor.order_client import ClobOrderClient
from coinbot.schemas import MarketWindow, Side, TradeEvent
from coinbot.state_store.dedupe import EventKey, SqliteDedupeStore


class IntegrationFlowTests(unittest.TestCase):
    def test_duplicate_events_are_deduped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = f"{tmp}/coinbot.db"
            store = SqliteDedupeStore(db_path)
            key = EventKey(event_id="evt-dup", market_id="m1", seen_at_unix=1)
            self.assertTrue(store.mark_seen(key))
            self.assertFalse(store.mark_seen(key))

    def test_out_of_order_events_are_coalesced_deterministically(self) -> None:
        async def _run() -> Decimal:
            coalescer = IntentNetCoalescer(CoalescerConfig(coalesce_ms=10))
            now = datetime.now(timezone.utc)
            window = MarketWindow(
                asset="Bitcoin",
                start_ts=now,
                end_ts=now + timedelta(minutes=15),
                duration_seconds=900,
                window_id="bitcoin:20260214T0745",
            )
            newer = TradeEvent(
                event_id="evt-2",
                source_wallet="0xabc",
                market_id="m1",
                market_slug="btc-up-down",
                outcome="Up",
                side=Side.BUY,
                price=Decimal("0.55"),
                shares=Decimal("10"),
                notional_usd=Decimal("5.5"),
                executed_ts=now + timedelta(milliseconds=10),
                window=window,
            )
            older = TradeEvent(
                event_id="evt-1",
                source_wallet="0xabc",
                market_id="m1",
                market_slug="btc-up-down",
                outcome="Up",
                side=Side.BUY,
                price=Decimal("0.54"),
                shares=Decimal("20"),
                notional_usd=Decimal("10.8"),
                executed_ts=now,
                window=window,
            )
            await coalescer.push(newer)
            await coalescer.push(older)
            intent = await coalescer.next_intent()
            return intent.target_notional_usd

        result = asyncio.run(_run())
        self.assertEqual(result, Decimal("16.3"))

    def test_partial_outage_returns_rejected_after_retries(self) -> None:
        client = ClobOrderClient(
            PolymarketConfig(api_key="k", api_secret="s", api_passphrase="p"),
            ExecutionConfig(dry_run=False),
            max_retries=2,
        )
        intent = _sample_intent()
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("down")):
            result = client.submit_marketable_limit(
                intent=intent,
                price=Decimal("0.5"),
                size=Decimal("10"),
            )
        self.assertFalse(result.accepted)
        self.assertEqual(result.status, "rejected")


def _sample_intent():
    from coinbot.schemas import ExecutionIntent

    return ExecutionIntent(
        intent_id="i1",
        market_id="m1",
        outcome="Up",
        side=Side.BUY,
        target_notional_usd=Decimal("5"),
        max_slippage_bps=120,
        coalesced_event_ids=("e1",),
        window_id="w1",
    )


if __name__ == "__main__":
    unittest.main()
