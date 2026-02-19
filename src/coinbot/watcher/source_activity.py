from __future__ import annotations

import json
import logging
import re
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from datetime import timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from coinbot.schemas import MarketWindow, Side, TradeEvent
from coinbot.state_store.checkpoints import SqliteCheckpointStore
from coinbot.state_store.dedupe import EventKey, SqliteDedupeStore


MARKET_WINDOW_RE = re.compile(
    r"^(?P<asset>[A-Za-z0-9 ]+?) Up or Down - "
    r"(?P<month>[A-Za-z]+) (?P<day>\d{1,2}), "
    r"(?P<start>\d{1,2}:\d{2}[AP]M)-(?P<end>\d{1,2}:\d{2}[AP]M) ET$"
)


@dataclass(frozen=True)
class ActivityPollerConfig:
    data_api_url: str
    source_wallet: str
    poll_interval_s: float = 0.7
    limit: int = 200
    stream_name: str = "source_activity"


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
        urls = [
            f"{self._cfg.data_api_url}/activity?{query}",
            f"{self._cfg.data_api_url}/api/activity?{query}",
        ]
        headers = {
            "Accept": "application/json",
            "User-Agent": "coinbot/0.1 (+https://github.com/greg-czaplicki/coinbot)",
            "Connection": "keep-alive",
        }
        for url in urls:
            try:
                req = urllib.request.Request(url, headers=headers, method="GET")
                with urllib.request.urlopen(req, timeout=4) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                items = _activity_items(payload)
                if items is not None:
                    return items
            except Exception as exc:
                self._log.warning("source_fetch_error url=%s error=%s", url, exc)
                continue
        return []

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


def parse_market_window(title: str, *, now: datetime) -> MarketWindow | None:
    match = MARKET_WINDOW_RE.match(title.strip())
    if not match:
        return None
    asset = match.group("asset").strip()
    month = match.group("month")
    day = int(match.group("day"))
    start_local = _parse_et_time(month, day, match.group("start"), now)
    end_local = _parse_et_time(month, day, match.group("end"), now)
    if end_local <= start_local:
        end_local = end_local + timedelta(days=1)
    duration = int((end_local - start_local).total_seconds())
    window_id = f"{asset.lower()}:{start_local.strftime('%Y%m%dT%H%M')}"
    return MarketWindow(
        asset=asset,
        start_ts=start_local.astimezone(timezone.utc),
        end_ts=end_local.astimezone(timezone.utc),
        duration_seconds=duration,
        window_id=window_id,
    )


def _parse_et_time(month: str, day: int, time_str: str, now: datetime) -> datetime:
    et = ZoneInfo("America/New_York")
    year = now.astimezone(et).year
    dt = datetime.strptime(f"{month} {day} {year} {time_str}", "%B %d %Y %I:%M%p")
    return dt.replace(tzinfo=et)
