from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True)
class MarketWindow:
    asset: str
    start_ts: datetime
    end_ts: datetime
    duration_seconds: int
    window_id: str


@dataclass(frozen=True)
class TradeEvent:
    event_id: str
    source_wallet: str
    market_id: str
    market_slug: str
    outcome: str
    side: Side
    price: Decimal
    shares: Decimal
    notional_usd: Decimal
    executed_ts: datetime
    received_ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    window: MarketWindow | None = None


@dataclass(frozen=True)
class ExecutionIntent:
    intent_id: str
    market_id: str
    outcome: str
    side: Side
    target_notional_usd: Decimal
    max_slippage_bps: int
    coalesced_event_ids: tuple[str, ...]
    window_id: str | None = None
    created_ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class RiskSnapshot:
    total_notional_today_usd: Decimal
    total_notional_current_15m_window_usd: Decimal
    market_exposure_usd: dict[str, Decimal]
    blocked: bool = False
    blocked_reason: str = ""
