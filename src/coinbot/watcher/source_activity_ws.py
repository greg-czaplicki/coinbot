from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from coinbot.schemas import Side, TradeEvent


class SourceWalletActivityWsWatcher:
    def __init__(
        self,
        *,
        ws_url: str,
        source_wallet: str,
        on_trade_event: Callable[[TradeEvent], None],
        source_ws_reseed_sec: int = 60,
    ) -> None:
        self._ws_url = ws_url
        self._source_wallet = source_wallet.lower()
        self._on_trade_event = on_trade_event
        self._source_ws_reseed_sec = source_ws_reseed_sec
        self._log = logging.getLogger(self.__class__.__name__)
        self._seen_messages = 0
        self._emitted_events = 0

    def run_forever(self) -> None:
        asyncio.run(self._run())

    async def _run(self) -> None:
        from coinbot.watcher.ws_client import ReconnectingWsClient

        client = ReconnectingWsClient(
            url=self._ws_url,
            subscribe_messages=[
                {
                    "action": "subscribe",
                    "subscriptions": [{"topic": "activity", "type": "trades"}],
                }
            ],
            on_message=self._on_message,
            session_ttl_s=self._source_ws_reseed_sec,
        )
        await client.run_forever()

    async def _on_message(self, message: dict[str, Any]) -> None:
        self._seen_messages += 1
        rows = _extract_activity_rows(message)
        if not rows:
            return
        for row in rows:
            if not _wallet_matches(row, self._source_wallet):
                continue
            event = _normalize_trade(row, self._source_wallet)
            if event is None:
                continue
            self._on_trade_event(event)
            self._emitted_events += 1
        if self._seen_messages % 100 == 0:
            self._log.info(
                "activity_ws_stats seen_messages=%s emitted=%s",
                self._seen_messages,
                self._emitted_events,
            )


def _extract_activity_rows(message: dict[str, Any]) -> list[dict[str, Any]]:
    topic = str(message.get("topic") or "").lower()
    payload = message.get("payload")
    rows: list[dict[str, Any]] = []
    if topic == "activity":
        if isinstance(payload, dict):
            rows.append(payload)
        elif isinstance(payload, list):
            rows.extend([x for x in payload if isinstance(x, dict)])
        elif isinstance(message, dict):
            rows.append(message)
    elif _looks_like_activity_trade(message):
        rows.append(message)
    return rows


def _looks_like_activity_trade(payload: dict[str, Any]) -> bool:
    keys = {k.lower() for k in payload.keys()}
    return "side" in keys and ("asset" in keys or "conditionid" in keys)


def _wallet_matches(payload: dict[str, Any], wallet_lower: str) -> bool:
    proxy_wallet = str(payload.get("proxyWallet") or payload.get("proxy_wallet") or "").lower()
    return bool(proxy_wallet and proxy_wallet == wallet_lower)


def _normalize_trade(raw: dict[str, Any], source_wallet: str) -> TradeEvent | None:
    side_raw = str(raw.get("side") or "").upper()
    if side_raw not in {"BUY", "SELL"}:
        return None
    side = Side.BUY if side_raw == "BUY" else Side.SELL

    market_id = str(raw.get("conditionId") or raw.get("condition_id") or raw.get("asset") or "")
    if not market_id:
        return None

    event_id = str(raw.get("id") or raw.get("activityId") or "")
    if not event_id:
        tx_hash = str(raw.get("transactionHash") or raw.get("transaction_hash") or "")
        asset = str(raw.get("asset") or "")
        timestamp = str(raw.get("timestamp") or "")
        event_id = f"{tx_hash}:{asset}:{timestamp}:{side_raw}"
    if not event_id:
        return None

    price = _to_decimal(raw.get("price")) or Decimal("0")
    shares = _to_decimal(raw.get("size")) or Decimal("0")
    notional = _to_decimal(raw.get("usdcSize") or raw.get("amount"))
    if notional is None:
        notional = shares * price

    executed_ts = _parse_ts(raw.get("timestamp"))
    now_utc = datetime.now(timezone.utc)
    return TradeEvent(
        event_id=event_id,
        source_wallet=source_wallet,
        market_id=market_id,
        market_slug=str(raw.get("slug") or ""),
        outcome=str(raw.get("outcome") or ""),
        side=side,
        price=price,
        shares=shares,
        notional_usd=notional,
        executed_ts=executed_ts,
        received_ts=now_utc,
        source_path="activity_ws",
        source_exec_to_fetch_ms=max(0.0, (now_utc - executed_ts).total_seconds() * 1000),
        source_fetch_to_emit_ms=0.0,
        source_poll_cycle_ms=0.0,
    )


def _parse_ts(value: Any) -> datetime:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if isinstance(value, str) and value:
        try:
            if value.isdigit():
                return datetime.fromtimestamp(float(value), tz=timezone.utc)
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
