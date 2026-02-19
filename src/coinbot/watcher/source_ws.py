from __future__ import annotations

import asyncio
import logging
import json
import urllib.parse
import urllib.request
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
        data_api_url: str,
        source_wallet: str,
        on_trade_event: Callable[[TradeEvent], None],
    ) -> None:
        self._ws_url = ws_url
        self._data_api_url = data_api_url
        self._source_wallet = source_wallet.lower()
        self._on_trade_event = on_trade_event
        self._log = logging.getLogger(self.__class__.__name__)
        self._seen_messages = 0
        self._seen_trade_rows = 0
        self._wallet_matched_rows = 0
        self._emitted_events = 0

    def run_forever(self) -> None:
        asyncio.run(self._run())

    async def _run(self) -> None:
        ws_url = self._market_ws_url(self._ws_url)
        asset_ids = self._discover_asset_ids()
        self._log.info(
            "ws_seed_assets count=%s sample=%s",
            len(asset_ids),
            asset_ids[:5],
        )
        # Polymarket market channel requires assets_ids.
        subscribe_messages = [
            {"type": "market", "assets_ids": asset_ids, "custom_feature_enabled": True},
        ]
        client = ReconnectingWsClient(
            url=ws_url,
            subscribe_messages=subscribe_messages,
            on_message=self._on_message,
        )
        await client.run_forever()

    async def _on_message(self, message: dict[str, Any]) -> None:
        self._seen_messages += 1
        if self._seen_messages <= 5:
            self._log.info(
                "ws_message_sample idx=%s top_keys=%s",
                self._seen_messages,
                sorted(message.keys())[:30],
            )
        rows = _extract_trade_rows(message)
        self._seen_trade_rows += len(rows)
        matched_in_message = 0
        for row in rows:
            if not _wallet_matches(row, self._source_wallet):
                continue
            self._wallet_matched_rows += 1
            matched_in_message += 1
            event = _normalize_trade(row, self._source_wallet)
            if event is None:
                continue
            self._on_trade_event(event)
            self._emitted_events += 1

        if self._seen_messages % 20 == 0:
            self._log.info(
                "ws_source_stats seen_messages=%s trade_rows=%s wallet_matches=%s emitted=%s",
                self._seen_messages,
                self._seen_trade_rows,
                self._wallet_matched_rows,
                self._emitted_events,
            )
        if rows and matched_in_message == 0 and self._seen_messages % 50 == 0:
            sample = rows[0]
            self._log.info(
                "ws_trade_no_wallet_match sample_keys=%s",
                sorted(sample.keys())[:25],
            )

    def _discover_asset_ids(self) -> list[str]:
        params = {
            "user": self._source_wallet,
            "type": "TRADE",
            "limit": "400",
        }
        query = urllib.parse.urlencode(params)
        urls = [
            f"{self._data_api_url}/activity?{query}",
            f"{self._data_api_url}/api/activity?{query}",
        ]
        headers = {
            "Accept": "application/json",
            "User-Agent": "coinbot/0.1 (+https://github.com/greg-czaplicki/coinbot)",
            "Connection": "keep-alive",
        }
        seen: set[str] = set()
        for url in urls:
            try:
                req = urllib.request.Request(url, headers=headers, method="GET")
                with urllib.request.urlopen(req, timeout=4) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                rows: list[dict[str, Any]]
                if isinstance(payload, list):
                    rows = [x for x in payload if isinstance(x, dict)]
                elif isinstance(payload, dict):
                    data = payload.get("data")
                    rows = [x for x in data if isinstance(x, dict)] if isinstance(data, list) else []
                else:
                    rows = []
                for row in rows:
                    raw = row.get("asset") or row.get("asset_id") or row.get("token_id")
                    if raw is None:
                        continue
                    token = str(raw).strip()
                    if token:
                        seen.add(token)
                if seen:
                    break
            except Exception as exc:
                self._log.warning("ws_seed_fetch_error url=%s error=%s", url, exc)
                continue
        if not seen:
            self._log.warning("ws_seed_assets_empty")
        return sorted(seen)

    @staticmethod
    def _market_ws_url(raw_url: str) -> str:
        # Normalize to .../ws/market.
        url = raw_url.rstrip("/")
        if url.endswith("/market"):
            return url
        if url.endswith("/ws"):
            return f"{url}/market"
        return f"{url}/market"


def _extract_trade_rows(message: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if _looks_like_trade(message):
        out.append(message)

    data = message.get("data")
    if isinstance(data, dict) and _looks_like_trade(data):
        out.append(data)
    elif isinstance(data, dict):
        nested_trade = data.get("trade")
        if isinstance(nested_trade, dict) and _looks_like_trade(nested_trade):
            out.append(nested_trade)
    elif isinstance(data, list):
        out.extend(item for item in data if isinstance(item, dict) and _looks_like_trade(item))

    events = message.get("events")
    if isinstance(events, list):
        for item in events:
            if not isinstance(item, dict):
                continue
            if _looks_like_trade(item):
                out.append(item)
            nested_trade = item.get("trade")
            if isinstance(nested_trade, dict) and _looks_like_trade(nested_trade):
                out.append(nested_trade)
            nested_event = item.get("event")
            if isinstance(nested_event, dict) and _looks_like_trade(nested_event):
                out.append(nested_event)

    trade = message.get("trade")
    if isinstance(trade, dict) and _looks_like_trade(trade):
        out.append(trade)
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
        "wallet",
        "wallet_address",
        "user_address",
        "owner_address",
        "proxy_wallet",
        "maker",
        "taker",
        "maker_address",
        "taker_address",
    ):
        value = payload.get(key)
        if isinstance(value, str) and value.lower() == wallet_lower:
            return True

    # Some payloads nest wallet addresses under maker/taker orders.
    for container_key in ("maker_orders", "taker_orders", "orders"):
        container = payload.get(container_key)
        if isinstance(container, list):
            for item in container:
                if not isinstance(item, dict):
                    continue
                for key in ("owner", "maker_address", "taker_address", "address", "user"):
                    value = item.get(key)
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
