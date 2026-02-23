from __future__ import annotations

import unittest

from decimal import Decimal

from coinbot.executor.order_client import (
    _classify_error_code,
    _resolve_marketable_limit_order_type,
    _sanitize_buy_amounts,
)


class OrderClientTests(unittest.TestCase):
    def test_classify_min_size_reject(self) -> None:
        error = "order ... is invalid. Size (3.98) lower than the minimum: 5"
        self.assertEqual(_classify_error_code(error), "min_size")

    def test_classify_unknown_reject(self) -> None:
        self.assertEqual(_classify_error_code("HTTP Error 400: Bad Request"), "")

    def test_marketable_limit_prefers_fok(self) -> None:
        class _OrderType:
            FOK = "fok"
            GTC = "gtc"

        self.assertEqual(_resolve_marketable_limit_order_type(_OrderType), "fok")

    def test_marketable_limit_falls_back_to_ioc_then_gtc(self) -> None:
        class _IOCOnly:
            IOC = "ioc"

        class _GTCOnly:
            GTC = "gtc"

        self.assertEqual(_resolve_marketable_limit_order_type(_IOCOnly), "ioc")
        self.assertEqual(_resolve_marketable_limit_order_type(_GTCOnly), "gtc")

    def test_sanitize_buy_amounts_enforces_notional_and_size_precision(self) -> None:
        px, sz = _sanitize_buy_amounts(price=Decimal("0.537891"), size=Decimal("9.2958222"))
        self.assertLessEqual(-px.as_tuple().exponent, 6)
        self.assertLessEqual(-sz.as_tuple().exponent, 4)
        notional = (px * sz).quantize(Decimal("0.01"))
        self.assertLessEqual(-notional.as_tuple().exponent, 2)


if __name__ == "__main__":
    unittest.main()
