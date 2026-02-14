from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass
class Position:
    qty: Decimal = Decimal("0")
    avg_price: Decimal = Decimal("0")


@dataclass(frozen=True)
class PnLSnapshot:
    realized_usd: Decimal
    unrealized_usd: Decimal


class PnLTracker:
    def __init__(self) -> None:
        self._positions: dict[str, Position] = {}
        self._marks: dict[str, Decimal] = {}
        self._realized = Decimal("0")

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
            self._realized += (price - pos.avg_price) * close_qty
            pos.qty -= close_qty
            if pos.qty == 0:
                pos.avg_price = Decimal("0")
        else:
            pos.qty -= qty
            pos.avg_price = price

    def snapshot(self) -> PnLSnapshot:
        unrealized = Decimal("0")
        for key, pos in self._positions.items():
            if pos.qty == 0:
                continue
            mark = self._marks.get(key, pos.avg_price)
            unrealized += (mark - pos.avg_price) * pos.qty
        return PnLSnapshot(realized_usd=self._realized, unrealized_usd=unrealized)


def _key(market_id: str, outcome: str) -> str:
    return f"{market_id}:{outcome}"
