from __future__ import annotations

import json
import unittest

from coinbot.watcher.source_ws import (
    _extract_market_token_ids,
    _extract_trade_rows,
    _extract_updown_families,
    _normalize_trade,
    _wallet_matches,
)


class SourceWsParserTests(unittest.TestCase):
    def test_extract_trade_rows_from_event_message_json_string(self) -> None:
        msg = {
            "event_type": "market",
            "event_message": json.dumps(
                {
                    "event_type": "trade",
                    "trade": {
                        "trade_id": "t1",
                        "market_id": "m1",
                        "token_id": "tok1",
                        "price": "0.51",
                        "size": "10",
                        "usdcSize": "5.1",
                        "side": "BUY",
                        "outcome": "Up",
                        "timestamp": "2026-02-23T01:00:00Z",
                        "maker_orders": [{"owner": "0xabc"}],
                    },
                }
            ),
        }
        rows = _extract_trade_rows(msg)
        self.assertTrue(rows)
        self.assertIn("t1", {str(r.get("trade_id") or "") for r in rows})

    def test_wallet_match_finds_nested_owner(self) -> None:
        row = {
            "event_message": json.dumps(
                {
                    "trade": {
                        "price": "0.5",
                        "size": "10",
                        "maker_orders": [{"owner": "0xabc"}],
                    }
                }
            )
        }
        self.assertTrue(_wallet_matches(row, "0xabc"))
        self.assertFalse(_wallet_matches(row, "0xdef"))

    def test_normalize_trade_reads_nested_fields(self) -> None:
        row = {
            "event_message": json.dumps(
                {
                    "trade": {
                        "trade_id": "t2",
                        "market_id": "m2",
                        "price": "0.49",
                        "size": "12.5",
                        "usdcSize": "6.125",
                        "side": "SELL",
                        "outcome": "Down",
                        "timestamp": "2026-02-23T01:00:01Z",
                        "slug": "btc-up-down",
                    }
                }
            )
        }
        event = _normalize_trade(row, "0xabc")
        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual("t2", event.event_id)
        self.assertEqual("m2", event.market_id)
        self.assertEqual("btc-up-down", event.market_slug)
        self.assertEqual("Down", event.outcome)

    def test_extract_updown_families(self) -> None:
        slugs = [
            "btc-updown-5m-1771808400",
            "eth-updown-15m-1771808400",
            "not-a-match",
        ]
        families = _extract_updown_families(slugs)
        self.assertEqual({"btc-updown-5m", "eth-updown-15m"}, families)

    def test_extract_market_token_ids_from_gamma_shape(self) -> None:
        market = {
            "clobTokenIds": "[\"111\",\"222\"]",
        }
        self.assertEqual({"111", "222"}, _extract_market_token_ids(market))


if __name__ == "__main__":
    unittest.main()
