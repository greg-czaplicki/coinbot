from __future__ import annotations

import unittest
from decimal import Decimal

from coinbot.executor.market_cache import _extract_outcome_prices, _extract_token_ids


class MarketCacheTests(unittest.TestCase):
    def test_extract_outcome_prices_from_string_encoded_outcomes(self) -> None:
        item = {
            "outcomes": "[\"Up\", \"Down\"]",
            "outcomePrices": "[\"0\", \"1\"]",
        }
        prices = _extract_outcome_prices(item)
        self.assertEqual(prices.get("Up"), Decimal("0"))
        self.assertEqual(prices.get("Down"), Decimal("1"))

    def test_extract_token_ids_from_string_encoded_list(self) -> None:
        item = {"clobTokenIds": "[\"123\", \"456\"]"}
        token_ids = _extract_token_ids(item)
        self.assertEqual(token_ids, ["123", "456"])


if __name__ == "__main__":
    unittest.main()
