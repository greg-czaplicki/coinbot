from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from coinbot.config import ExecutionConfig, SizingConfig
from coinbot.schemas import ExecutionIntent, RiskSnapshot, TradeEvent


@dataclass
class DecisionResult:
    intent: ExecutionIntent | None
    blocked_reason: str = ""


class IntentPolicy:
    def __init__(self, sizing: SizingConfig, execution: ExecutionConfig) -> None:
        self._sizing = sizing
        self._execution = execution

    def apply(self, intent: ExecutionIntent, source_events: list[TradeEvent]) -> DecisionResult:
        if self._near_expiry(source_events):
            return DecisionResult(None, "near_expiry_cutoff")

        sized_notional = self._size_notional(intent.target_notional_usd)

        if sized_notional < Decimal(str(self._sizing.min_order_notional_usd)):
            return DecisionResult(None, "below_min_order_notional")

        return DecisionResult(
            ExecutionIntent(
                intent_id=intent.intent_id,
                market_id=intent.market_id,
                outcome=intent.outcome,
                side=intent.side,
                target_notional_usd=sized_notional,
                max_slippage_bps=self._execution.max_slippage_bps,
                coalesced_event_ids=intent.coalesced_event_ids,
                window_id=intent.window_id,
                created_ts=intent.created_ts,
            )
        )

    def _size_notional(self, source_notional: Decimal) -> Decimal:
        if self._sizing.mode == "fixed":
            sized = Decimal(str(self._sizing.fixed_order_notional_usd))
        elif self._sizing.mode == "proportional":
            sized = source_notional * Decimal(str(self._sizing.size_multiplier))
        else:
            sized = source_notional * Decimal(str(self._sizing.size_multiplier))
            sized = min(sized, Decimal(str(self._sizing.max_notional_per_order_usd)))
        return min(sized, Decimal(str(self._sizing.max_notional_per_order_usd)))

    def _near_expiry(self, source_events: list[TradeEvent]) -> bool:
        if not source_events:
            return False
        event = source_events[-1]
        if event.window is None:
            return False
        remaining = (event.window.end_ts - datetime.now(event.window.end_ts.tzinfo)).total_seconds()
        return remaining <= self._execution.near_expiry_cutoff_seconds


class WindowRiskTracker:
    def __init__(self, sizing: SizingConfig) -> None:
        self._sizing = sizing
        self._window_notional: dict[str, Decimal] = {}
        self._market_notional: dict[str, Decimal] = {}
        self._daily_notional: Decimal = Decimal("0")

    def check_and_apply(self, intent: ExecutionIntent) -> RiskSnapshot:
        window_id = intent.window_id or "na"
        current = self._window_notional.get(window_id, Decimal("0"))
        projected = current + intent.target_notional_usd
        cap = Decimal(str(self._sizing.max_total_notional_per_15m_window_usd))
        if projected > cap:
            return RiskSnapshot(
                total_notional_today_usd=Decimal("0"),
                total_notional_current_15m_window_usd=current,
                market_exposure_usd={},
                blocked=True,
                blocked_reason="window_cap_exceeded",
            )
        market_current = self._market_notional.get(intent.market_id, Decimal("0"))
        market_projected = market_current + intent.target_notional_usd
        market_cap = Decimal(str(self._sizing.max_notional_per_market_usd))
        if market_projected > market_cap:
            return RiskSnapshot(
                total_notional_today_usd=self._daily_notional,
                total_notional_current_15m_window_usd=current,
                market_exposure_usd={intent.market_id: market_current},
                blocked=True,
                blocked_reason="market_cap_exceeded",
            )
        daily_projected = self._daily_notional + intent.target_notional_usd
        daily_cap = Decimal(str(self._sizing.max_daily_traded_volume_usd))
        if daily_projected > daily_cap:
            return RiskSnapshot(
                total_notional_today_usd=self._daily_notional,
                total_notional_current_15m_window_usd=current,
                market_exposure_usd={intent.market_id: market_current},
                blocked=True,
                blocked_reason="daily_cap_exceeded",
            )
        self._window_notional[window_id] = projected
        self._market_notional[intent.market_id] = market_projected
        self._daily_notional = daily_projected
        return RiskSnapshot(
            total_notional_today_usd=self._daily_notional,
            total_notional_current_15m_window_usd=projected,
            market_exposure_usd={intent.market_id: market_projected},
        )
