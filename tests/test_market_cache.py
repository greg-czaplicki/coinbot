from __future__ import annotations

import unittest
from decimal import Decimal

from coinbot.executor.market_cache import _extract_outcome_prices


class MarketCacheTests(unittest.TestCase):
    def test_extract_outcome_prices_from_string_encoded_outcomes(self) -> None:
        item = {
            "outcomes": "[\"Up\", \"Down\"]",
            "outcomePrices": "[\"0\", \"1\"]",
        }
        prices = _extract_outcome_prices(item)
        self.assertEqual(prices.get("Up"), Decimal("0"))
        self.assertEqual(prices.get("Down"), Decimal("1"))


if __name__ == "__main__":
    unittest.main()
