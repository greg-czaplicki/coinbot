#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean


@dataclass
class Row:
    ts: datetime
    copy_delay_p50_ms: float | None
    copy_delay_p95_ms: float | None
    copy_delay_p99_ms: float | None
    source_fills: int
    destination_orders: int
    coalescing_efficiency: float | None
    reject_rate: float
    realized_pnl_usd: float
    realized_settled_pnl_usd: float
    unrealized_pnl_usd: float
    fees_usd: float
    net_pnl_usd: float


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate daily telemetry rollup")
    parser.add_argument("--input", default="runs/telemetry/snapshots.csv")
    parser.add_argument("--date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    rows = load_rows(Path(args.input), args.date)
    if not rows:
        print(f"No rows found for {args.date}")
        return

    report = build_report(args.date, rows)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")
        print(f"Wrote {out_path}")
    else:
        print(report)


def load_rows(path: Path, day: str) -> list[Row]:
    rows: list[Row] = []
    with path.open("r", encoding="utf-8", newline="") as fp:
        reader = csv.DictReader(fp)
        for raw in reader:
            ts_raw = raw.get("ts", "")
            if not ts_raw.startswith(day):
                continue
            ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            rows.append(
                Row(
                    ts=ts,
                    copy_delay_p50_ms=_to_float(raw.get("copy_delay_p50_ms")),
                    copy_delay_p95_ms=_to_float(raw.get("copy_delay_p95_ms")),
                    copy_delay_p99_ms=_to_float(raw.get("copy_delay_p99_ms")),
                    source_fills=_to_int(raw.get("source_fills")),
                    destination_orders=_to_int(raw.get("destination_orders")),
                    coalescing_efficiency=_to_float(raw.get("coalescing_efficiency")),
                    reject_rate=_to_float(raw.get("reject_rate")) or 0.0,
                    realized_pnl_usd=_to_float(raw.get("realized_pnl_usd")) or 0.0,
                    realized_settled_pnl_usd=_to_float(raw.get("realized_settled_pnl_usd")) or 0.0,
                    unrealized_pnl_usd=_to_float(raw.get("unrealized_pnl_usd")) or 0.0,
                    fees_usd=_to_float(raw.get("fees_usd")) or 0.0,
                    net_pnl_usd=_to_float(raw.get("net_pnl_usd")) or 0.0,
                )
            )
    return rows


def build_report(day: str, rows: list[Row]) -> str:
    last = rows[-1]
    first = rows[0]

    p50s = [r.copy_delay_p50_ms for r in rows if r.copy_delay_p50_ms is not None]
    p95s = [r.copy_delay_p95_ms for r in rows if r.copy_delay_p95_ms is not None]
    p99s = [r.copy_delay_p99_ms for r in rows if r.copy_delay_p99_ms is not None]
    effs = [r.coalescing_efficiency for r in rows if r.coalescing_efficiency is not None]
    rejects = [r.reject_rate for r in rows]

    fills_delta = max(0, last.source_fills - first.source_fills)
    orders_delta = max(0, last.destination_orders - first.destination_orders)

    lines = [
        f"# Daily Rollup ({day})",
        "",
        "## Throughput",
        f"- Source fills delta: {fills_delta}",
        f"- Destination orders delta: {orders_delta}",
        f"- Coalescing efficiency (last): {fmt(last.coalescing_efficiency)}",
        f"- Coalescing efficiency (avg): {fmt(mean(effs) if effs else None)}",
        "",
        "## Latency",
        f"- copy_delay_p50_ms (avg): {fmt(mean(p50s) if p50s else None)}",
        f"- copy_delay_p95_ms (avg): {fmt(mean(p95s) if p95s else None)}",
        f"- copy_delay_p99_ms (avg): {fmt(mean(p99s) if p99s else None)}",
        f"- copy_delay_p95_ms (last): {fmt(last.copy_delay_p95_ms)}",
        "",
        "## Risk",
        f"- reject_rate (avg): {fmt(mean(rejects) if rejects else None)}",
        "",
        "## PnL",
        f"- realized_pnl_usd (last): {fmt(last.realized_pnl_usd)}",
        f"- realized_settled_pnl_usd (last): {fmt(last.realized_settled_pnl_usd)}",
        f"- unrealized_pnl_usd (last): {fmt(last.unrealized_pnl_usd)}",
        f"- fees_usd (last): {fmt(last.fees_usd)}",
        f"- net_pnl_usd (last): {fmt(last.net_pnl_usd)}",
    ]
    return "\n".join(lines)


def _to_float(v: str | None) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _to_int(v: str | None) -> int:
    if v is None or v == "":
        return 0
    try:
        return int(float(v))
    except ValueError:
        return 0


def fmt(v: float | None) -> str:
    if v is None:
        return "n/a"
    return f"{v:.6f}".rstrip("0").rstrip(".")


if __name__ == "__main__":
    main()
