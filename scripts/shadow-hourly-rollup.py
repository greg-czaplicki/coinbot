#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path


@dataclass
class HourDecisionStats:
    total: int = 0
    executed: int = 0
    reasons: Counter[str] = field(default_factory=Counter)


@dataclass
class HourPnlStats:
    first_ts: datetime | None = None
    first_net: Decimal | None = None
    last_ts: datetime | None = None
    last_net: Decimal | None = None


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate hourly shadow rollup")
    parser.add_argument("--decisions", default="runs/telemetry/shadow_decisions.jsonl")
    parser.add_argument("--snapshots", default="runs/telemetry/snapshots.jsonl")
    parser.add_argument("--date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    decision_stats = load_decisions(Path(args.decisions), args.date)
    pnl_stats = load_snapshots(Path(args.snapshots), args.date)
    hours = sorted(set(decision_stats.keys()) | set(pnl_stats.keys()))
    if not hours:
        print(f"No rows found for {args.date}")
        return

    report = build_report(args.date, hours, decision_stats, pnl_stats)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")
        print(f"Wrote {out_path}")
    else:
        print(report)


def load_decisions(path: Path, day: str) -> dict[str, HourDecisionStats]:
    stats: dict[str, HourDecisionStats] = defaultdict(HourDecisionStats)
    if not path.exists():
        return stats
    with path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            row = _parse_json(line)
            ts = _parse_ts(row.get("ts", ""))
            if ts is None or ts.strftime("%Y-%m-%d") != day:
                continue
            hour = _hour_key(ts)
            hour_stats = stats[hour]
            hour_stats.total += 1
            if bool(row.get("executed", False)):
                hour_stats.executed += 1
            reason = str(row.get("blocked_reason", "") or "executed")
            hour_stats.reasons[reason] += 1
    return stats


def load_snapshots(path: Path, day: str) -> dict[str, HourPnlStats]:
    stats: dict[str, HourPnlStats] = defaultdict(HourPnlStats)
    if not path.exists():
        return stats
    with path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            row = _parse_json(line)
            ts = _parse_ts(row.get("ts", ""))
            if ts is None or ts.strftime("%Y-%m-%d") != day:
                continue
            net = _parse_decimal(row.get("net_pnl_usd"))
            if net is None:
                continue
            hour = _hour_key(ts)
            hour_stats = stats[hour]
            if hour_stats.first_ts is None or ts < hour_stats.first_ts:
                hour_stats.first_ts = ts
                hour_stats.first_net = net
            if hour_stats.last_ts is None or ts > hour_stats.last_ts:
                hour_stats.last_ts = ts
                hour_stats.last_net = net
    return stats


def build_report(
    day: str,
    hours: list[str],
    decisions: dict[str, HourDecisionStats],
    pnl: dict[str, HourPnlStats],
) -> str:
    lines = [
        f"# Shadow Hourly Rollup ({day})",
        "",
        "| hour_utc | decisions | executed | execution_ratio | top_block_reasons | pnl_delta_usd |",
        "|---|---:|---:|---:|---|---:|",
    ]
    for hour in hours:
        d = decisions.get(hour, HourDecisionStats())
        p = pnl.get(hour, HourPnlStats())
        ratio = (d.executed / d.total) if d.total else 0.0
        pnl_delta = _pnl_delta(p)
        reasons = _top_reasons(d.reasons)
        lines.append(
            "| "
            + " | ".join(
                [
                    hour,
                    str(d.total),
                    str(d.executed),
                    _fmt_ratio(ratio),
                    reasons,
                    _fmt_decimal(pnl_delta),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def _top_reasons(reasons: Counter[str], top_n: int = 3) -> str:
    if not reasons:
        return "n/a"
    parts: list[str] = []
    for reason, count in reasons.most_common(top_n):
        parts.append(f"{reason}:{count}")
    return ", ".join(parts)


def _hour_key(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%d %H:00")


def _pnl_delta(stats: HourPnlStats) -> Decimal | None:
    if stats.first_net is None or stats.last_net is None:
        return None
    return stats.last_net - stats.first_net


def _fmt_ratio(v: float) -> str:
    return f"{v:.4f}".rstrip("0").rstrip(".")


def _fmt_decimal(v: Decimal | None) -> str:
    if v is None:
        return "n/a"
    return format(v, "f").rstrip("0").rstrip(".")


def _parse_json(line: str) -> dict:
    try:
        value = json.loads(line)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass
    return {}


def _parse_ts(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_decimal(raw: object) -> Decimal | None:
    if raw is None or raw == "":
        return None
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None


if __name__ == "__main__":
    main()
