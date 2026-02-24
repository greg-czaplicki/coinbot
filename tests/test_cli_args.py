from __future__ import annotations

import unittest

from coinbot.main import _parse_args


class CliArgsTests(unittest.TestCase):
    def test_concise_flag(self) -> None:
        args = _parse_args(["--concise"])
        self.assertTrue(args.concise)
        self.assertFalse(args.debug)

    def test_debug_flag(self) -> None:
        args = _parse_args(["--debug"])
        self.assertFalse(args.concise)
        self.assertTrue(args.debug)

    def test_both_flags(self) -> None:
        args = _parse_args(["--concise", "--debug"])
        self.assertTrue(args.concise)
        self.assertTrue(args.debug)


if __name__ == "__main__":
    unittest.main()
