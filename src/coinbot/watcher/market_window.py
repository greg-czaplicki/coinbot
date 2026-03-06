from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from coinbot.schemas import MarketWindow


MARKET_WINDOW_RE = re.compile(
    r"^(?P<asset>[A-Za-z0-9 ]+?) Up or Down - "
    r"(?P<month>[A-Za-z]+) (?P<day>\d{1,2}), "
    r"(?P<start>\d{1,2}:\d{2}[AP]M)-(?P<end>\d{1,2}:\d{2}[AP]M) ET$"
)

UPDOWN_SLUG_WINDOW_RE = re.compile(
    r"^(?P<asset>[a-z0-9]+)-updown-(?P<minutes>\d+)m-(?P<end_ts>\d{9,12})$"
)


def infer_market_window(*, title: str, slug: str, now: datetime) -> MarketWindow | None:
    return parse_market_window(title, now=now) or parse_market_window_from_slug(slug)


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


def parse_market_window_from_slug(slug: str) -> MarketWindow | None:
    match = UPDOWN_SLUG_WINDOW_RE.match(slug.strip().lower())
    if not match:
        return None
    asset = match.group("asset")
    duration_seconds = int(match.group("minutes")) * 60
    end_ts = datetime.fromtimestamp(int(match.group("end_ts")), tz=timezone.utc)
    start_ts = end_ts - timedelta(seconds=duration_seconds)
    return MarketWindow(
        asset=asset,
        start_ts=start_ts,
        end_ts=end_ts,
        duration_seconds=duration_seconds,
        window_id=f"{asset}:{start_ts.strftime('%Y%m%dT%H%M')}",
    )


def _parse_et_time(month: str, day: int, time_str: str, now: datetime) -> datetime:
    et = ZoneInfo("America/New_York")
    year = now.astimezone(et).year
    dt = datetime.strptime(f"{month} {day} {year} {time_str}", "%B %d %Y %I:%M%p")
    return dt.replace(tzinfo=et)
