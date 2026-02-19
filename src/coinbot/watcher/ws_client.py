from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable

import websockets
from websockets.client import WebSocketClientProtocol

MessageHandler = Callable[[dict], Awaitable[None]]


class ReconnectingWsClient:
    def __init__(
        self,
        url: str,
        subscribe_messages: list[dict],
        on_message: MessageHandler,
        *,
        ping_interval_s: int = 20,
        ping_timeout_s: int = 20,
        max_backoff_s: int = 30,
    ) -> None:
        self._url = url
        self._subscribe_messages = subscribe_messages
        self._on_message = on_message
        self._ping_interval_s = ping_interval_s
        self._ping_timeout_s = ping_timeout_s
        self._max_backoff_s = max_backoff_s
        self._log = logging.getLogger(self.__class__.__name__)
        self._stop_event = asyncio.Event()
        self._recv_count = 0

    async def run_forever(self) -> None:
        backoff_s = 1
        while not self._stop_event.is_set():
            try:
                await self._connect_once()
                backoff_s = 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._log.warning("ws_loop_error url=%s error=%s", self._url, exc)
                await asyncio.sleep(backoff_s)
                backoff_s = min(backoff_s * 2, self._max_backoff_s)

    async def stop(self) -> None:
        self._stop_event.set()

    async def _connect_once(self) -> None:
        async with websockets.connect(
            self._url,
            ping_interval=self._ping_interval_s,
            ping_timeout=self._ping_timeout_s,
            max_queue=1000,
        ) as ws:
            await self._subscribe(ws)
            self._log.info("ws_connected url=%s", self._url)
            while not self._stop_event.is_set():
                raw = await ws.recv()
                self._recv_count += 1
                if self._recv_count <= 5:
                    self._log.info(
                        "ws_recv_sample idx=%s raw_type=%s raw_len=%s",
                        self._recv_count,
                        type(raw).__name__,
                        len(raw) if hasattr(raw, "__len__") else "n/a",
                    )
                elif self._recv_count % 50 == 0:
                    self._log.info("ws_recv_progress count=%s", self._recv_count)
                message = self._parse(raw)
                await self._on_message(message)

    async def _subscribe(self, ws: WebSocketClientProtocol) -> None:
        for payload in self._subscribe_messages:
            await ws.send(json.dumps(payload))
            self._log.info("ws_subscribe payload=%s", payload)

    @staticmethod
    def _parse(raw: str | bytes) -> dict:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("Expected dict websocket message")
        return parsed
