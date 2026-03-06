from __future__ import annotations

import unittest
from datetime import datetime, timezone

from coinbot.executor.redeemer import _group_by_condition, _token_id_from_row
from coinbot.watcher.source_activity_ws import (
    _extract_activity_rows,
    _normalize_trade,
    _wallet_matches,
)


class SourceActivityWsTests(unittest.TestCase):
    def test_extract_activity_rows_from_topic_payload(self) -> None:
        message = {
            "topic": "activity",
            "payload": {"side": "BUY", "asset": "123", "proxyWallet": "0xabc"},
        }
        rows = _extract_activity_rows(message)
        self.assertEqual(1, len(rows))

    def test_wallet_matches_proxy_wallet(self) -> None:
        payload = {"proxyWallet": "0xabc"}
        self.assertTrue(_wallet_matches(payload, "0xabc"))
        self.assertFalse(_wallet_matches(payload, "0xdef"))

    def test_normalize_trade_builds_event(self) -> None:
        row = {
            "id": "evt-1",
            "conditionId": "0xcondition",
            "slug": "btc-updown-5m-1771812000",
            "outcome": "Up",
            "side": "BUY",
            "price": "0.44",
            "size": "10",
            "usdcSize": "4.4",
            "timestamp": "2026-02-23T01:00:00Z",
            "proxyWallet": "0xabc",
        }
        event = _normalize_trade(row, "0xabc")
        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual("evt-1", event.event_id)
        self.assertEqual("0xcondition", event.market_id)
        self.assertEqual("activity_ws", event.source_path)
        self.assertIsNotNone(event.window)
        assert event.window is not None
        self.assertEqual("btc:20260223T0100", event.window.window_id)
        self.assertEqual(datetime(2026, 2, 23, 1, 5, tzinfo=timezone.utc), event.window.end_ts)

    def test_normalize_trade_infers_window_from_market_title(self) -> None:
        row = {
            "id": "evt-2",
            "conditionId": "0xcondition",
            "slug": "btc-updown-5m-1771812000",
            "marketTitle": "Bitcoin Up or Down - February 22, 8:00PM-8:05PM ET",
            "outcome": "Up",
            "side": "BUY",
            "price": "0.44",
            "size": "10",
            "usdcSize": "4.4",
            "timestamp": "2026-02-23T01:00:00Z",
            "proxyWallet": "0xabc",
        }
        event = _normalize_trade(row, "0xabc")
        self.assertIsNotNone(event)
        assert event is not None
        self.assertIsNotNone(event.window)
        assert event.window is not None
        self.assertEqual("bitcoin:20260222T2000", event.window.window_id)
        self.assertEqual(datetime(2026, 2, 23, 1, 5, tzinfo=timezone.utc), event.window.end_ts)

    def test_group_by_condition_and_token_id(self) -> None:
        rows = [
            {"conditionId": "c1", "asset": "1"},
            {"conditionId": "c1", "asset": "2"},
            {"conditionId": "c2", "asset": "3"},
        ]
        grouped = _group_by_condition(rows)
        self.assertEqual(2, len(grouped))
        self.assertEqual(1, _token_id_from_row({"asset": "1"}))


if __name__ == "__main__":
    unittest.main()
