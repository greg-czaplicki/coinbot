from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from coinbot.schemas import Side, TradeEvent
from coinbot.watcher.ws_client import ReconnectingWsClient


class SourceWalletWsWatcher:
    def __init__(
        self,
        *,
        ws_url: str,
        source_wallet: str,
        on_trade_event: Callable[[TradeEvent], None],
    ) -> None:
        self._ws_url = ws_url
        self._source_wallet = source_wallet.lower()
        self._on_trade_event = on_trade_event
        self._log = logging.getLogger(self.__class__.__name__)

    def run_forever(self) -> None:
        asyncio.run(self._run())

    async def _run(self) -> None:
        # Keep subscriptions broad and rely on wallet filtering in parser.
        subscribe_messages = [
            {"type": "subscribe", "channel": "market"},
            {"type": "subscribe", "channel": "user", "address": self._source_wallet},
        ]
        client = ReconnectingWsClient(
            url=self._ws_url,
            subscribe_messages=subscribe_messages,
            on_message=self._on_message,
        )
        await client.run_forever()

    async def _on_message(self, message: dict[str, Any]) -> None:
        for row in _extract_trade_rows(message):
            if not _wallet_matches(row, self._source_wallet):
                continue
            event = _normalize_trade(row, self._source_wallet)
            if event is None:
                continue
            self._on_trade_event(event)


def _extract_trade_rows(message: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if _looks_like_trade(message):
        out.append(message)

    data = message.get("data")
    if isinstance(data, dict) and _looks_like_trade(data):
        out.append(data)
    elif isinstance(data, list):
        out.extend(item for item in data if isinstance(item, dict) and _looks_like_trade(item))

    events = message.get("events")
    if isinstance(events, list):
        out.extend(item for item in events if isinstance(item, dict) and _looks_like_trade(item))
    return out


def _looks_like_trade(payload: dict[str, Any]) -> bool:
    keys = {k.lower() for k in payload.keys()}
    return bool(
        {"price", "size"} & keys
        or {"usdcsize", "notional"} & keys
        or "trade_id" in keys
        or payload.get("event_type") in {"trade", "fill"}
    )


def _wallet_matches(payload: dict[str, Any], wallet_lower: str) -> bool:
    for key in (
        "owner",
        "user",
        "trader",
        "address",
        "maker",
        "taker",
        "maker_address",
        "taker_address",
    ):
        value = payload.get(key)
        if isinstance(value, str) and value.lower() == wallet_lower:
            return True
    return False


def _normalize_trade(raw: dict[str, Any], source_wallet: str) -> TradeEvent | None:
    market_id = str(
        raw.get("market")
        or raw.get("market_id")
        or raw.get("condition_id")
        or raw.get("asset_id")
        or raw.get("token_id")
        or ""
    )
    if not market_id:
        return None

    event_id = str(raw.get("id") or raw.get("trade_id") or "")
    if not event_id:
        tx_hash = str(raw.get("transaction_hash") or raw.get("transactionHash") or "")
        ts = str(raw.get("timestamp") or "")
        size = str(raw.get("size") or raw.get("shares") or raw.get("usdcSize") or "")
        event_id = f"{tx_hash}:{market_id}:{ts}:{size}"
    if not event_id:
        return None

    price = _to_decimal(raw.get("price")) or Decimal("0")
    shares = _to_decimal(raw.get("size") or raw.get("shares")) or Decimal("0")
    notional = _to_decimal(raw.get("usdcSize") or raw.get("notional") or raw.get("amount"))
    if notional is None:
        notional = shares * price

    side_raw = str(raw.get("side") or raw.get("direction") or "BUY").upper()
    side = Side.BUY if side_raw in {"BUY", "BID"} else Side.SELL

    executed_ts = _parse_ts(raw.get("timestamp"))
    now_utc = datetime.now(timezone.utc)
    return TradeEvent(
        event_id=event_id,
        source_wallet=source_wallet,
        market_id=market_id,
        market_slug=str(raw.get("market_slug") or raw.get("slug") or ""),
        outcome=str(raw.get("outcome") or ""),
        side=side,
        price=price,
        shares=shares,
        notional_usd=notional,
        executed_ts=executed_ts,
        received_ts=now_utc,
        source_path="clob_ws",
        source_exec_to_fetch_ms=max(0.0, (now_utc - executed_ts).total_seconds() * 1000),
        source_fetch_to_emit_ms=0.0,
        source_poll_cycle_ms=0.0,
    )


def _parse_ts(value: Any) -> datetime:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _to_decimal(value: Any) -> Decimal | None:
    try:
        if value is None or value == "":
            return None
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
