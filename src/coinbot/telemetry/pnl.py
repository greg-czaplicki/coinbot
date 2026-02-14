from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass
class Position:
    qty: Decimal = Decimal("0")
    avg_price: Decimal = Decimal("0")


@dataclass(frozen=True)
class PnLSnapshot:
    realized_trading_usd: Decimal
    realized_settled_usd: Decimal
    unrealized_usd: Decimal
    fees_usd: Decimal
    net_usd: Decimal


class PnLTracker:
    def __init__(self, *, fee_bps: Decimal = Decimal("0")) -> None:
        self._positions: dict[str, Position] = {}
        self._marks: dict[str, Decimal] = {}
        self._realized_trading = Decimal("0")
        self._realized_settled = Decimal("0")
        self._fees = Decimal("0")
        self._fee_bps = fee_bps

    def set_mark(self, market_id: str, outcome: str, price: Decimal) -> None:
        self._marks[_key(market_id, outcome)] = price

    def apply_fill(
        self,
        *,
        market_id: str,
        outcome: str,
        side: str,
        qty: Decimal,
        price: Decimal,
    ) -> None:
        key = _key(market_id, outcome)
        pos = self._positions.setdefault(key, Position())
        self._fees += abs(qty * price) * self._fee_bps / Decimal("10000")

        if side == "BUY":
            if pos.qty <= 0:
                pos.qty = qty
                pos.avg_price = price
                return
            new_qty = pos.qty + qty
            pos.avg_price = ((pos.qty * pos.avg_price) + (qty * price)) / new_qty
            pos.qty = new_qty
            return

        if pos.qty > 0:
            close_qty = min(qty, pos.qty)
            self._realized_trading += (price - pos.avg_price) * close_qty
            pos.qty -= close_qty
            if pos.qty == 0:
                pos.avg_price = Decimal("0")
        else:
            pos.qty -= qty
            pos.avg_price = price

    def settle_market(
        self,
        *,
        market_id: str,
        winning_outcome: str | None = None,
        outcome_settle_prices: dict[str, Decimal] | None = None,
    ) -> int:
        settled = 0
        for key, pos in self._positions.items():
            if not key.startswith(f"{market_id}:"):
                continue
            if pos.qty == 0:
                continue
            outcome = key.split(":", 1)[1]
            settle_px = None
            if outcome_settle_prices and outcome in outcome_settle_prices:
                settle_px = outcome_settle_prices[outcome]
            elif winning_outcome is not None:
                settle_px = Decimal("1") if outcome == winning_outcome else Decimal("0")
            if settle_px is None:
                continue
            self._realized_settled += (settle_px - pos.avg_price) * pos.qty
            pos.qty = Decimal("0")
            pos.avg_price = Decimal("0")
            self._marks[key] = settle_px
            settled += 1
        return settled

    def open_markets(self) -> set[str]:
        markets: set[str] = set()
        for key, pos in self._positions.items():
            if pos.qty != 0:
                markets.add(key.split(":", 1)[0])
        return markets

    def snapshot(self) -> PnLSnapshot:
        unrealized = Decimal("0")
        for key, pos in self._positions.items():
            if pos.qty == 0:
                continue
            mark = self._marks.get(key, pos.avg_price)
            unrealized += (mark - pos.avg_price) * pos.qty
        net = self._realized_trading + self._realized_settled + unrealized - self._fees
        return PnLSnapshot(
            realized_trading_usd=self._realized_trading,
            realized_settled_usd=self._realized_settled,
            unrealized_usd=unrealized,
            fees_usd=self._fees,
            net_usd=net,
        )


def _key(market_id: str, outcome: str) -> str:
    return f"{market_id}:{outcome}"
