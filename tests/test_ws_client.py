from __future__ import annotations

import unittest
from importlib.util import find_spec

if find_spec("websockets") is not None:
    from coinbot.watcher.ws_client import ReconnectingWsClient
else:
    ReconnectingWsClient = None  # type: ignore[assignment]


@unittest.skipIf(ReconnectingWsClient is None, "websockets not installed")
class WsClientParseTests(unittest.TestCase):
    def test_parse_ignores_empty_and_heartbeat(self) -> None:
        self.assertIsNone(ReconnectingWsClient._parse(""))
        self.assertIsNone(ReconnectingWsClient._parse("   "))
        self.assertIsNone(ReconnectingWsClient._parse("ping"))
        self.assertIsNone(ReconnectingWsClient._parse("pong"))

    def test_parse_json_variants(self) -> None:
        self.assertEqual({"ok": True}, ReconnectingWsClient._parse('{"ok": true}'))
        self.assertEqual({"data": [{"a": 1}]}, ReconnectingWsClient._parse('[{"a": 1}]'))


if __name__ == "__main__":
    unittest.main()
