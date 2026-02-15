from __future__ import annotations

import unittest

from coinbot.executor.order_client import _classify_error_code


class OrderClientTests(unittest.TestCase):
    def test_classify_min_size_reject(self) -> None:
        error = "order ... is invalid. Size (3.98) lower than the minimum: 5"
        self.assertEqual(_classify_error_code(error), "min_size")

    def test_classify_unknown_reject(self) -> None:
        self.assertEqual(_classify_error_code("HTTP Error 400: Bad Request"), "")


if __name__ == "__main__":
    unittest.main()
