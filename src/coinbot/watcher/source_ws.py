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


class SourceWalletWsWatcher:
    def __init__(
        self,
        *,
        ws_url: str,
        data_api_url: str,
        source_wallet: str,
        on_trade_event: Callable[[TradeEvent], None],
        source_ws_reseed_sec: int = 60,
    ) -> None:
        self._ws_url = ws_url
        self._data_api_url = data_api_url
        self._source_wallet = source_wallet.lower()
        self._on_trade_event = on_trade_event
        self._source_ws_reseed_sec = source_ws_reseed_sec
        self._log = logging.getLogger(self.__class__.__name__)
        self._seen_messages = 0
        self._seen_trade_rows = 0
        self._wallet_matched_rows = 0
        self._emitted_events = 0

    def run_forever(self) -> None:
        asyncio.run(self._run())

    async def _run(self) -> None:
        from coinbot.watcher.ws_client import ReconnectingWsClient

        ws_url = self._market_ws_url(self._ws_url)
        client = ReconnectingWsClient(
            url=ws_url,
            subscribe_messages=[],
            subscribe_messages_factory=self._build_subscribe_messages,
            on_message=self._on_message,
            session_ttl_s=self._source_ws_reseed_sec,
        )
        await client.run_forever()

    def _build_subscribe_messages(self) -> list[dict]:
        asset_ids = self._discover_asset_ids()
        self._log.info(
            "ws_seed_assets count=%s sample=%s",
            len(asset_ids),
            asset_ids[:5],
        )
        if not asset_ids:
            return []
        # Polymarket market channel requires assets_ids.
        return [{"type": "market", "assets_ids": asset_ids, "custom_feature_enabled": True}]

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
    seen: set[str] = set()
    for node in _iter_nodes(message):
        if not isinstance(node, dict):
            continue
        if not _looks_like_trade(node):
            continue
        sig = _row_signature(node)
        if sig in seen:
            continue
        seen.add(sig)
        out.append(node)
    return out


def _looks_like_trade(payload: dict[str, Any]) -> bool:
    event_type = str(payload.get("event_type") or payload.get("type") or "").lower()
    keys = {k.lower() for k in payload.keys()}
    if event_type in {"trade", "fill", "last_trade_price"} and (
        {"price", "size"} & keys
        or {"usdcsize", "notional"} & keys
        or {"trade", "trade_id", "transaction_hash", "tx_hash"} & keys
    ):
        return True
    return bool(
        {"price", "size"} & keys
        or {"usdcsize", "notional"} & keys
        or {"trade_id", "transaction_hash", "tx_hash"} & keys
        or (
            "price" in keys
            and (
                {"maker", "taker", "owner", "user", "wallet"} & keys
                or {"maker_orders", "taker_orders", "orders"} & keys
            )
        )
    )


def _wallet_matches(payload: dict[str, Any], wallet_lower: str) -> bool:
    for node in _iter_nodes(payload):
        if not isinstance(node, dict):
            continue
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
            "maker_proxy_wallet",
            "taker_proxy_wallet",
        ):
            value = node.get(key)
            if isinstance(value, str) and value.lower() == wallet_lower:
                return True
    return False


def _normalize_trade(raw: dict[str, Any], source_wallet: str) -> TradeEvent | None:
    market_id = str(_pick(raw, "market", "market_id", "condition_id", "asset_id", "token_id") or "")
    if not market_id:
        return None

    event_id = str(_pick(raw, "id", "trade_id", "event_id", "match_id", "order_id") or "")
    if not event_id:
        tx_hash = str(_pick(raw, "transaction_hash", "transactionHash", "tx_hash", "txHash") or "")
        ts = str(_pick(raw, "timestamp", "time", "created_at", "createdAt") or "")
        size = str(_pick(raw, "size", "shares", "usdcSize", "amount", "matched_size") or "")
        event_id = f"{tx_hash}:{market_id}:{ts}:{size}"
    if not event_id:
        return None

    price = _to_decimal(_pick(raw, "price", "trade_price", "last_price")) or Decimal("0")
    shares = _to_decimal(
        _pick(
            raw,
            "size",
            "shares",
            "matched_size",
            "base_amount",
            "maker_base_asset_amount",
            "taker_base_asset_amount",
        )
    ) or Decimal("0")
    notional = _to_decimal(
        _pick(
            raw,
            "usdcSize",
            "notional",
            "amount",
            "quote_amount",
            "maker_quote_asset_amount",
            "taker_quote_asset_amount",
        )
    )
    if notional is None:
        notional = shares * price

    side_raw = str(_pick(raw, "side", "direction", "taker_side", "maker_side") or "BUY").upper()
    side = Side.BUY if side_raw in {"BUY", "BID"} else Side.SELL

    executed_ts = _parse_ts(_pick(raw, "timestamp", "time", "created_at", "createdAt"))
    now_utc = datetime.now(timezone.utc)
    return TradeEvent(
        event_id=event_id,
        source_wallet=source_wallet,
        market_id=market_id,
        market_slug=str(_pick(raw, "market_slug", "slug") or ""),
        outcome=str(_pick(raw, "outcome", "token_outcome", "side_outcome") or ""),
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


def _try_parse_json(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text or text[0] not in "{[":
        return value
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return value


def _iter_nodes(root: Any) -> list[Any]:
    out: list[Any] = []
    stack: list[Any] = [_try_parse_json(root)]
    while stack:
        current = stack.pop()
        out.append(current)
        if isinstance(current, dict):
            for key, value in current.items():
                if key in {"event_message", "message", "payload", "data", "event", "trade", "events", "changes"}:
                    stack.append(_try_parse_json(value))
                elif isinstance(value, (dict, list)):
                    stack.append(value)
        elif isinstance(current, list):
            for item in current:
                stack.append(_try_parse_json(item))
    return out


def _pick(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload and payload.get(key) not in (None, ""):
            return payload.get(key)
    for node in _iter_nodes(payload):
        if not isinstance(node, dict):
            continue
        for key in keys:
            if key in node and node.get(key) not in (None, ""):
                return node.get(key)
    return None


def _row_signature(payload: dict[str, Any]) -> str:
    event_id = str(
        payload.get("id")
        or payload.get("trade_id")
        or payload.get("event_id")
        or payload.get("match_id")
        or ""
    )
    if event_id:
        return f"id:{event_id}"
    market = str(
        payload.get("market")
        or payload.get("market_id")
        or payload.get("condition_id")
        or payload.get("asset_id")
        or payload.get("token_id")
        or ""
    )
    timestamp = str(
        payload.get("timestamp")
        or payload.get("time")
        or payload.get("created_at")
        or payload.get("createdAt")
        or ""
    )
    size = str(
        payload.get("size")
        or payload.get("shares")
        or payload.get("usdcSize")
        or payload.get("amount")
        or payload.get("matched_size")
        or ""
    )
    price = str(payload.get("price") or payload.get("trade_price") or payload.get("last_price") or "")
    return f"row:{market}:{timestamp}:{size}:{price}"
