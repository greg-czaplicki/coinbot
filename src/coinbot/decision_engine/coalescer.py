from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from coinbot.schemas import ExecutionIntent, Side, TradeEvent


@dataclass(frozen=True)
class CoalescerConfig:
    coalesce_ms: int = 300
    max_slippage_bps: int = 120
    net_opposite_trades: bool = True


class IntentNetCoalescer:
    def __init__(self, cfg: CoalescerConfig) -> None:
        self._cfg = cfg
        self._events_by_key: dict[str, list[TradeEvent]] = {}
        self._timers: dict[str, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()
        self._out: asyncio.Queue[ExecutionIntent] = asyncio.Queue()

    async def push(self, event: TradeEvent) -> None:
        key = self._coalesce_key(event)
        async with self._lock:
            self._events_by_key.setdefault(key, []).append(event)
            if key not in self._timers:
                self._timers[key] = asyncio.create_task(self._flush_after(key))

    async def next_intent(self) -> ExecutionIntent:
        return await self._out.get()

    async def _flush_after(self, key: str) -> None:
        try:
            await asyncio.sleep(self._cfg.coalesce_ms / 1000)
            async with self._lock:
                events = self._events_by_key.pop(key, [])
                self._timers.pop(key, None)
            if not events:
                return
            intent = self._to_intent(events)
            if intent is not None:
                await self._out.put(intent)
        finally:
            async with self._lock:
                self._timers.pop(key, None)

    def _to_intent(self, events: list[TradeEvent]) -> ExecutionIntent | None:
        events = sorted(events, key=lambda e: e.executed_ts)
        market_id = events[0].market_id
        outcome = events[0].outcome
        window_id = events[0].window.window_id if events[0].window else None
        event_ids = tuple(e.event_id for e in events)

        if self._cfg.net_opposite_trades:
            net_usd = Decimal("0")
            for event in events:
                direction = Decimal("1") if event.side == Side.BUY else Decimal("-1")
                net_usd += direction * event.notional_usd
            if net_usd == 0:
                return None
            side = Side.BUY if net_usd > 0 else Side.SELL
            target_notional = abs(net_usd)
        else:
            first_side = events[0].side
            target_notional = sum(e.notional_usd for e in events)
            side = first_side

        return ExecutionIntent(
            intent_id=f"{market_id}:{outcome}:{int(datetime.now(timezone.utc).timestamp() * 1000)}",
            market_id=market_id,
            outcome=outcome,
            side=side,
            target_notional_usd=target_notional,
            max_slippage_bps=self._cfg.max_slippage_bps,
            coalesced_event_ids=event_ids,
            window_id=window_id,
        )

    def _coalesce_key(self, event: TradeEvent) -> str:
        window_id = event.window.window_id if event.window else "na"
        if self._cfg.net_opposite_trades:
            return f"{event.market_id}:{window_id}"
        return f"{event.market_id}:{event.outcome}:{event.side.value}:{window_id}"
