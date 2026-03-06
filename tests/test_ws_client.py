from __future__ import annotations

import asyncio
import unittest
from importlib.util import find_spec
from unittest.mock import patch

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

    def test_ttl_rollover_does_not_block_on_idle_recv(self) -> None:
        async def _run() -> None:
            client = ReconnectingWsClient(
                url="wss://example.invalid/ws",
                subscribe_messages=[],
                on_message=_noop,
                session_ttl_s=0.05,
            )

            class _IdleWs:
                async def recv(self) -> str:
                    await asyncio.sleep(60)
                    return ""

            started = 100.0
            monotonic_values = iter([100.0, 100.02, 100.04, 100.06])
            with patch("time.monotonic", side_effect=lambda: next(monotonic_values)):
                await asyncio.wait_for(client._connect_once_with_socket(_IdleWs(), started=started), timeout=0.2)

        async def _noop(_message: dict[str, object]) -> None:
            return None

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
