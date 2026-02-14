from __future__ import annotations

import json
import logging
import re
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
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
        while True:
            try:
                events = self._fetch_activity()
                for raw in events:
                    event = self._normalize(raw)
                    if event is None:
                        continue
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
                        continue
                    self._on_trade_event(event)
                    self._checkpoints.set(self._cfg.stream_name, event.event_id)
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
        url = f"{self._cfg.data_api_url}/activity?{query}"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=4) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            items = payload.get("data")
            if isinstance(items, list):
                return items
        return []

    def _normalize(self, raw: dict[str, Any]) -> TradeEvent | None:
        market_id = str(raw.get("market") or raw.get("marketId") or "")
        if not market_id:
            return None
        event_id = str(raw.get("id") or raw.get("activityId") or "")
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
            window=parse_market_window(market_title, now=executed_ts),
        )


def _parse_ts(value: Any) -> datetime:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=UTC)
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(UTC)


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
        start_ts=start_local.astimezone(UTC),
        end_ts=end_local.astimezone(UTC),
        duration_seconds=duration,
        window_id=window_id,
    )


def _parse_et_time(month: str, day: int, time_str: str, now: datetime) -> datetime:
    et = ZoneInfo("America/New_York")
    year = now.astimezone(et).year
    dt = datetime.strptime(f"{month} {day} {year} {time_str}", "%B %d %Y %I:%M%p")
    return dt.replace(tzinfo=et)
