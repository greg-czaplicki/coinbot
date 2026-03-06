from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from coinbot.schemas import Side, TradeEvent
from coinbot.state_store.checkpoints import SqliteCheckpointStore
from coinbot.state_store.dedupe import EventKey, SqliteDedupeStore
from coinbot.watcher.market_window import parse_market_window


@dataclass(frozen=True)
class ActivityPollerConfig:
    data_api_url: str
    source_wallet: str
    poll_interval_s: float = 0.7
    limit: int = 200
    stream_name: str = "source_activity"
    request_timeout_s: float = 4.0


class SourceWalletActivityPoller:
    def __init__(
        self,
        cfg: ActivityPollerConfig,
        *,
        dedupe: SqliteDedupeStore,
        checkpoints: SqliteCheckpointStore,
        on_trade_event: Callable[[TradeEvent], None],
    ) -> None:
        self._cfg = cfg
        self._dedupe = dedupe
        self._checkpoints = checkpoints
        self._on_trade_event = on_trade_event
        self._log = logging.getLogger(self.__class__.__name__)
        self._activity_urls = self._build_activity_urls()
        self._preferred_activity_url_idx = 0

    def run_forever(self) -> None:
        last_checkpoint = self._checkpoints.get(self._cfg.stream_name)
        initialized = last_checkpoint is not None
        while True:
            try:
                poll_cycle_start_ns = time.perf_counter_ns()
                fetch_start_ns = time.perf_counter_ns()
                events = self._fetch_activity()
                fetch_end_ns = time.perf_counter_ns()
                fetch_ms = (fetch_end_ns - fetch_start_ns) / 1_000_000
                if not initialized and events:
                    # On first boot, anchor at latest event and avoid replaying stale history.
                    anchor = _raw_event_id(events[0])
                    if anchor:
                        self._checkpoints.set(self._cfg.stream_name, anchor)
                        last_checkpoint = anchor
                        initialized = True
                        self._log.info("source_anchor_set event_id=%s", anchor)
                    time.sleep(self._cfg.poll_interval_s)
                    continue

                candidates: list[dict[str, Any]] = []
                for raw in events:
                    raw_id = _raw_event_id(raw)
                    if last_checkpoint and raw_id == last_checkpoint:
                        break
                    candidates.append(raw)

                for raw in reversed(candidates):
                    event = self._normalize(raw)
                    normalize_end_ns = time.perf_counter_ns()
                    if event is None:
                        continue
                    now_utc = datetime.now(timezone.utc)
                    source_exec_to_fetch_ms = max(
                        0.0,
                        (now_utc - event.executed_ts).total_seconds() * 1000 - fetch_ms,
                    )
                    event = replace(
                        event,
                        received_ts=now_utc,
                        source_exec_to_fetch_ms=round(source_exec_to_fetch_ms, 3),
                        source_fetch_to_emit_ms=round(
                            max(0.0, (normalize_end_ns - fetch_end_ns) / 1_000_000),
                            3,
                        ),
                        source_poll_cycle_ms=round(
                            (time.perf_counter_ns() - poll_cycle_start_ns) / 1_000_000,
                            3,
                        ),
                    )
                    inserted = self._dedupe.mark_seen(
                        EventKey(
                            event_id=event.event_id,
                            market_id=event.market_id,
                            seen_at_unix=int(time.time()),
                            tx_hash=str(raw.get("transactionHash", "")),
                            sequence=str(raw.get("sequence", "")),
                        )
                    )
                    if not inserted:
                        last_checkpoint = event.event_id
                        self._checkpoints.set(self._cfg.stream_name, last_checkpoint)
                        continue
                    self._on_trade_event(event)
                    last_checkpoint = event.event_id
                    self._checkpoints.set(self._cfg.stream_name, last_checkpoint)
                time.sleep(self._cfg.poll_interval_s)
            except Exception as exc:
                self._log.warning("source_poller_error error=%s", exc)
                time.sleep(min(2 * self._cfg.poll_interval_s, 5))

    def _fetch_activity(self) -> list[dict[str, Any]]:
        params = {
            "user": self._cfg.source_wallet,
            "type": "TRADE",
            "limit": str(self._cfg.limit),
        }
        query = urllib.parse.urlencode(params)
        urls = [f"{base}?{query}" for base in self._ordered_activity_urls()]
        headers = {
            "Accept": "application/json",
            "User-Agent": "coinbot/0.1 (+https://github.com/greg-czaplicki/coinbot)",
            "Connection": "keep-alive",
        }
        for url in urls:
            try:
                req = urllib.request.Request(url, headers=headers, method="GET")
                with urllib.request.urlopen(req, timeout=self._cfg.request_timeout_s) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                items = _activity_items(payload)
                if items is not None:
                    self._promote_activity_url(url)
                    return items
            except Exception as exc:
                self._log.warning("source_fetch_error url=%s error=%s", url, exc)
                continue
        return []

    def _build_activity_urls(self) -> list[str]:
        root = self._cfg.data_api_url.rstrip("/")
        return [f"{root}/activity", f"{root}/api/activity"]

    def _ordered_activity_urls(self) -> list[str]:
        if not self._activity_urls:
            return []
        preferred = self._activity_urls[self._preferred_activity_url_idx]
        return [preferred] + [u for u in self._activity_urls if u != preferred]

    def _promote_activity_url(self, url_with_query: str) -> None:
        base = url_with_query.split("?", 1)[0]
        for i, candidate in enumerate(self._activity_urls):
            if candidate == base:
                self._preferred_activity_url_idx = i
                break

    def _normalize(self, raw: dict[str, Any]) -> TradeEvent | None:
        market_id = str(
            raw.get("market")
            or raw.get("marketId")
            or raw.get("conditionId")
            or raw.get("asset")
            or ""
        )
        if not market_id:
            return None
        event_id = str(raw.get("id") or raw.get("activityId") or "")
        if not event_id:
            tx_hash = str(raw.get("transactionHash") or "")
            ts = str(raw.get("timestamp") or "")
            asset = str(raw.get("asset") or "")
            usdc = str(raw.get("usdcSize") or raw.get("amount") or "")
            event_id = f"{tx_hash}:{asset}:{ts}:{usdc}"
        if not event_id:
            return None

        side_raw = str(raw.get("side", "BUY")).upper()
        side = Side.BUY if side_raw == "BUY" else Side.SELL
        price = Decimal(str(raw.get("price", "0")))
        shares = Decimal(str(raw.get("size") or raw.get("shares") or "0"))
        notional = Decimal(str(raw.get("amount") or raw.get("usdcSize") or "0"))
        market_title = str(raw.get("marketTitle") or raw.get("title") or "")
        executed_ts = _parse_ts(raw.get("timestamp"))
        return TradeEvent(
            event_id=event_id,
            source_wallet=self._cfg.source_wallet,
            market_id=market_id,
            market_slug=str(raw.get("slug") or ""),
            outcome=str(raw.get("outcome") or ""),
            side=side,
            price=price,
            shares=shares,
            notional_usd=notional,
            executed_ts=executed_ts,
            source_path="activity_api",
            window=parse_market_window(market_title, now=executed_ts),
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


def _raw_event_id(raw: dict[str, Any]) -> str:
    event_id = str(raw.get("id") or raw.get("activityId") or "")
    if event_id:
        return event_id
    tx_hash = str(raw.get("transactionHash") or "")
    ts = str(raw.get("timestamp") or "")
    asset = str(raw.get("asset") or "")
    usdc = str(raw.get("usdcSize") or raw.get("amount") or "")
    return f"{tx_hash}:{asset}:{ts}:{usdc}"


def _activity_items(payload: Any) -> list[dict[str, Any]] | None:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        items = payload.get("data")
        if isinstance(items, list):
            return items
    return None
