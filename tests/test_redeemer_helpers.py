from __future__ import annotations

import unittest

from coinbot.executor.redeemer import _build_safe_signature


class RedeemerHelperTests(unittest.TestCase):
    def test_build_safe_signature_normalizes_v(self) -> None:
        sig = _build_safe_signature(r=1, s=2, v=1)
        self.assertEqual(65, len(sig))
        self.assertEqual(28, sig[-1])

    def test_build_safe_signature_keeps_27_28(self) -> None:
        sig = _build_safe_signature(r=3, s=4, v=27)
        self.assertEqual(65, len(sig))
        self.assertEqual(27, sig[-1])


if __name__ == "__main__":
    unittest.main()
