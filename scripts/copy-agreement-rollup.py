#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from statistics import median


@dataclass
class HourStats:
    decisions: int = 0
    submitted: int = 0
    executed: int = 0
    blocked: Counter[str] = field(default_factory=Counter)
    size_ratios: list[float] = field(default_factory=list)
    exec_to_submit_ms: list[int] = field(default_factory=list)
    recv_to_submit_ms: list[int] = field(default_factory=list)


def main() -> None:
    parser = argparse.ArgumentParser(description="Roll up copy agreement metrics")
    parser.add_argument("--input", default="runs/telemetry/copy_audit.jsonl")
    parser.add_argument("--date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"No audit file found at {args.input}")
        return

    by_hour: dict[str, HourStats] = defaultdict(HourStats)
    with input_path.open("r", encoding="utf-8") as fp:
        for line in fp:
            row = _parse(line)
            ts = row.get("ts", "")
            if not ts.startswith(args.date):
                continue
            hour = ts[:13] + ":00"
            stats = by_hour[hour]
            stats.decisions += 1
            if bool(row.get("submitted", False)):
                stats.submitted += 1
            if bool(row.get("executed", False)):
                stats.executed += 1

            reason = str(row.get("blocked_reason", "") or "")
            if reason:
                stats.blocked[reason] += 1

            ratio = _to_float(row.get("size_ratio_vs_source_net"))
            if ratio is not None:
                stats.size_ratios.append(ratio)

            exec_to_submit = _to_int(row.get("source_exec_to_submit_ms"))
            if exec_to_submit is not None:
                stats.exec_to_submit_ms.append(exec_to_submit)
            recv_to_submit = _to_int(row.get("source_receive_to_submit_ms"))
            if recv_to_submit is not None:
                stats.recv_to_submit_ms.append(recv_to_submit)

    print(f"# Copy Agreement Rollup ({args.date})")
    print("")
    print("| hour_utc | decisions | submitted | executed | submit_ratio | exec_ratio | size_ratio_med | source_exec_to_submit_p50_ms | source_exec_to_submit_p95_ms | top_block_reasons |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for hour in sorted(by_hour.keys()):
        s = by_hour[hour]
        submit_ratio = _ratio(s.submitted, s.decisions)
        exec_ratio = _ratio(s.executed, s.decisions)
        size_med = _fmt(_median(s.size_ratios))
        exec_p50 = _fmt(_percentile(s.exec_to_submit_ms, 50))
        exec_p95 = _fmt(_percentile(s.exec_to_submit_ms, 95))
        reasons = ", ".join(f"{k}:{v}" for k, v in s.blocked.most_common(3)) if s.blocked else "n/a"
        print(
            f"| {hour} | {s.decisions} | {s.submitted} | {s.executed} | "
            f"{_fmt(submit_ratio)} | {_fmt(exec_ratio)} | {size_med} | {exec_p50} | {exec_p95} | {reasons} |"
        )


def _parse(line: str) -> dict:
    try:
        value = json.loads(line)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}


def _to_float(value: object) -> float | None:
    if value in ("", None):
        return None
    try:
        return float(str(value))
    except ValueError:
        return None


def _to_int(value: object) -> int | None:
    if value in ("", None):
        return None
    try:
        return int(float(str(value)))
    except ValueError:
        return None


def _ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    return median(values)


def _percentile(values: list[int], p: int) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = int(round((p / 100) * (len(ordered) - 1)))
    return float(ordered[max(0, min(idx, len(ordered) - 1))])


def _fmt(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.4f}".rstrip("0").rstrip(".")


if __name__ == "__main__":
    main()
