#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import median


@dataclass
class BucketDecisionStats:
    decisions: int = 0
    submitted: int = 0
    executed: int = 0
    source_net_notional_usd: Decimal = Decimal("0")
    bot_target_notional_usd: Decimal = Decimal("0")
    size_ratios: list[float] = field(default_factory=list)
    exec_to_receive_ms: list[float] = field(default_factory=list)
    exec_to_submit_ms: list[int] = field(default_factory=list)
    stage_coalesce_wait_ms: list[int] = field(default_factory=list)
    stage_policy_ms: list[float] = field(default_factory=list)
    stage_risk_ms: list[float] = field(default_factory=list)
    stage_submit_ms: list[float] = field(default_factory=list)
    stage_total_pipeline_ms: list[float] = field(default_factory=list)
    stage_submit_ms_submitted: list[float] = field(default_factory=list)
    stage_total_pipeline_ms_submitted: list[float] = field(default_factory=list)
    blocked: Counter[str] = field(default_factory=Counter)


@dataclass
class BucketPnlStats:
    first_ts: datetime | None = None
    first_net: Decimal | None = None
    last_ts: datetime | None = None
    last_net: Decimal | None = None


def main() -> None:
    parser = argparse.ArgumentParser(description="5m/15m tale-of-the-tape rollup")
    parser.add_argument("--audit", default="runs/telemetry/copy_audit.jsonl")
    parser.add_argument("--snapshots", default="runs/telemetry/snapshots.jsonl")
    parser.add_argument("--date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    parser.add_argument("--intervals", default="5,15", help="Comma-separated minute buckets")
    args = parser.parse_args()

    audit_path = Path(args.audit)
    snapshots_path = Path(args.snapshots)
    if not audit_path.exists():
        print(f"No audit file found at {args.audit}")
        return
    if not snapshots_path.exists():
        print(f"No snapshot file found at {args.snapshots}")
        return

    intervals = _parse_intervals(args.intervals)
    print(f"# Tale Of The Tape ({args.date})")
    print("")
    for minutes in intervals:
        decisions = load_decisions(audit_path, args.date, minutes)
        pnl = load_pnl(snapshots_path, args.date, minutes)
        buckets = sorted(set(decisions.keys()) | set(pnl.keys()))
        print(f"## {minutes}m")
        print("")
        print("| bucket_utc | decisions | submitted | executed | submit_ratio | exec_ratio | source_notional | bot_notional | capture_ratio | size_ratio_med | src_exec_to_recv_p50_ms | src_exec_to_recv_p95_ms | src_exec_to_submit_p50_ms | src_exec_to_submit_p95_ms | stage_coalesce_p50_ms | stage_policy_p50_ms | stage_risk_p50_ms | stage_submit_p50_ms | stage_submit_p50_ms_submitted | stage_total_p50_ms | stage_total_p50_ms_submitted | pnl_delta_usd | top_block_reasons |")
        print("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|")
        for bucket in buckets:
            d = decisions.get(bucket, BucketDecisionStats())
            p = pnl.get(bucket, BucketPnlStats())
            submit_ratio = _ratio(d.submitted, d.decisions)
            exec_ratio = _ratio(d.executed, d.decisions)
            capture_ratio = (
                float(d.bot_target_notional_usd / d.source_net_notional_usd)
                if d.source_net_notional_usd > 0
                else 0.0
            )
            pnl_delta = _pnl_delta(p)
            reasons = _top_reasons(d.blocked)
            print(
                "| "
                + " | ".join(
                    [
                        bucket,
                        str(d.decisions),
                        str(d.submitted),
                        str(d.executed),
                        _fmt_float(submit_ratio),
                        _fmt_float(exec_ratio),
                        _fmt_decimal(d.source_net_notional_usd),
                        _fmt_decimal(d.bot_target_notional_usd),
                        _fmt_float(capture_ratio),
                        _fmt_float(_median(d.size_ratios)),
                        _fmt_float(_percentile(d.exec_to_receive_ms, 50)),
                        _fmt_float(_percentile(d.exec_to_receive_ms, 95)),
                        _fmt_float(_percentile(d.exec_to_submit_ms, 50)),
                        _fmt_float(_percentile(d.exec_to_submit_ms, 95)),
                        _fmt_float(_percentile(d.stage_coalesce_wait_ms, 50)),
                        _fmt_float(_percentile(d.stage_policy_ms, 50)),
                        _fmt_float(_percentile(d.stage_risk_ms, 50)),
                        _fmt_float(_percentile(d.stage_submit_ms, 50)),
                        _fmt_float(_percentile(d.stage_submit_ms_submitted, 50)),
                        _fmt_float(_percentile(d.stage_total_pipeline_ms, 50)),
                        _fmt_float(_percentile(d.stage_total_pipeline_ms_submitted, 50)),
                        _fmt_decimal(pnl_delta),
                        reasons,
                    ]
                )
                + " |"
            )
        if not buckets:
            print("| n/a | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |")
        print("")


def load_decisions(path: Path, day: str, interval_minutes: int) -> dict[str, BucketDecisionStats]:
    stats: dict[str, BucketDecisionStats] = defaultdict(BucketDecisionStats)
    with path.open("r", encoding="utf-8") as fp:
        for line in fp:
            row = _parse_json(line)
            ts = _parse_ts(row.get("ts", ""))
            if ts is None or ts.strftime("%Y-%m-%d") != day:
                continue
            bucket = _bucket_key(ts, interval_minutes)
            b = stats[bucket]
            b.decisions += 1
            submitted = bool(row.get("submitted", False))
            executed = bool(row.get("executed", False))
            if submitted:
                b.submitted += 1
            if executed:
                b.executed += 1

            source_net = _parse_decimal(row.get("source_net_notional_usd")) or Decimal("0")
            b.source_net_notional_usd += source_net
            bot_notional = _parse_decimal(row.get("bot_target_notional_usd")) or Decimal("0")
            b.bot_target_notional_usd += bot_notional

            size_ratio = _to_float(row.get("size_ratio_vs_source_net"))
            if size_ratio is not None:
                b.size_ratios.append(size_ratio)
            exec_to_receive = _to_float(row.get("source_exec_to_receive_ms"))
            if exec_to_receive is not None:
                b.exec_to_receive_ms.append(exec_to_receive)
            exec_to_submit = _to_int(row.get("source_exec_to_submit_ms"))
            if exec_to_submit is not None:
                b.exec_to_submit_ms.append(exec_to_submit)
            stage_coalesce_wait = _to_int(row.get("stage_coalesce_wait_ms"))
            if stage_coalesce_wait is not None:
                b.stage_coalesce_wait_ms.append(stage_coalesce_wait)
            stage_policy = _to_float(row.get("stage_policy_ms"))
            if stage_policy is not None:
                b.stage_policy_ms.append(stage_policy)
            stage_risk = _to_float(row.get("stage_risk_ms"))
            if stage_risk is not None:
                b.stage_risk_ms.append(stage_risk)
            stage_submit = _to_float(row.get("stage_submit_ms"))
            if stage_submit is not None:
                b.stage_submit_ms.append(stage_submit)
                if submitted:
                    b.stage_submit_ms_submitted.append(stage_submit)
            stage_total_pipeline = _to_float(row.get("stage_total_pipeline_ms"))
            if stage_total_pipeline is not None:
                b.stage_total_pipeline_ms.append(stage_total_pipeline)
                if submitted:
                    b.stage_total_pipeline_ms_submitted.append(stage_total_pipeline)

            reason = str(row.get("blocked_reason", "") or "")
            if reason:
                b.blocked[reason] += 1
    return stats


def load_pnl(path: Path, day: str, interval_minutes: int) -> dict[str, BucketPnlStats]:
    stats: dict[str, BucketPnlStats] = defaultdict(BucketPnlStats)
    with path.open("r", encoding="utf-8") as fp:
        for line in fp:
            row = _parse_json(line)
            ts = _parse_ts(row.get("ts", ""))
            if ts is None or ts.strftime("%Y-%m-%d") != day:
                continue
            net = _parse_decimal(row.get("net_pnl_usd"))
            if net is None:
                continue
            bucket = _bucket_key(ts, interval_minutes)
            b = stats[bucket]
            if b.first_ts is None or ts < b.first_ts:
                b.first_ts = ts
                b.first_net = net
            if b.last_ts is None or ts > b.last_ts:
                b.last_ts = ts
                b.last_net = net
    return stats


def _parse_intervals(raw: str) -> list[int]:
    out: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            value = int(part)
        except ValueError:
            continue
        if value > 0:
            out.append(value)
    return sorted(set(out)) or [5, 15]


def _bucket_key(ts: datetime, interval_minutes: int) -> str:
    utc = ts.astimezone(timezone.utc)
    floored_minute = (utc.minute // interval_minutes) * interval_minutes
    bucket = utc.replace(minute=floored_minute, second=0, microsecond=0)
    return bucket.strftime("%Y-%m-%d %H:%M")


def _top_reasons(reasons: Counter[str], top_n: int = 3) -> str:
    if not reasons:
        return "n/a"
    return ", ".join(f"{k}:{v}" for k, v in reasons.most_common(top_n))


def _pnl_delta(stats: BucketPnlStats) -> Decimal | None:
    if stats.first_net is None or stats.last_net is None:
        return None
    return stats.last_net - stats.first_net


def _ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    return float(median(values))


def _percentile(values: list[float], p: int) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = int(round((p / 100) * (len(ordered) - 1)))
    return float(ordered[max(0, min(idx, len(ordered) - 1))])


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


def _to_int(raw: object) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        return int(float(str(raw)))
    except ValueError:
        return None


def _to_float(raw: object) -> float | None:
    if raw is None or raw == "":
        return None
    try:
        return float(str(raw))
    except ValueError:
        return None


def _parse_decimal(raw: object) -> Decimal | None:
    if raw is None or raw == "":
        return None
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None


def _fmt_float(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.4f}".rstrip("0").rstrip(".")


def _fmt_decimal(value: Decimal | None) -> str:
    if value is None:
        return "n/a"
    return format(value, "f").rstrip("0").rstrip(".")


if __name__ == "__main__":
    main()
