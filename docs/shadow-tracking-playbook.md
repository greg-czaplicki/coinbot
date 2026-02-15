# Shadow Tracking Playbook

Goal: reverse engineer the source wallet's edge without increasing execution risk.

## Operating Mode

Run in normal live mode (`EXECUTION_DRY_RUN=false`) with conservative bankroll caps, and use logs/telemetry to infer what the source wallet does that we are not copying.

## Data You Already Have

1. `telemetry_snapshot` every ~30s in app logs.
2. `dry_run_blocked` reason tags for each blocked decision.
3. Snapshot exports in `runs/telemetry/snapshots.csv` and `runs/telemetry/snapshots.jsonl`.

## Core Hypothesis Tests

1. Throughput bottleneck test:
- Is missed edge mostly from `window_cap_exceeded` and `market_cap_exceeded`?

2. Min-notional filter test:
- Are `below_min_order_notional` blocks high-frequency and net-positive if hypothetically included?

3. Timing test:
- Are late entries (`near_expiry_cutoff`) disproportionately profitable for the source wallet?

## Metrics To Track Per 30m Block

1. Count blocked events by reason.
2. Source fills vs destination orders.
3. Coalescing efficiency.
4. Reject rate.
5. Net PnL delta.
6. Kill-switch transitions (on/off counts, reason).

## Quick Parsers

Count blocked reasons from logs:

```bash
rg -n '"msg":"dry_run_blocked"' /var/log/coinbot/coinbot.log \
  | rg -o '"reason":"[^"]+"' \
  | sort | uniq -c | sort -nr
```

Snapshot tail (latest telemetry):

```bash
tail -n 20 runs/telemetry/snapshots.jsonl
```

Hourly shadow rollup:

```bash
./scripts/shadow-hourly-rollup.py --date "$(date -u +%F)"
```

30-minute CSV slices (manual):

```bash
# copy snapshots.csv and analyze in a sheet with 30m buckets by ts
```

## 24h Shadow Experiment Plan

Phase A (8h): Baseline
- Keep current env as-is.
- Collect block-reason distribution and PnL trend.

Phase B (8h): Slight throughput unlock
- `SIZING_MAX_TOTAL_NOTIONAL_PER_15M_WINDOW_USD`: `25 -> 35`
- `SIZING_MAX_NOTIONAL_PER_MARKET_USD`: `12 -> 15`
- Keep all other keys unchanged.

Phase C (8h): Min-notional sensitivity
- Keep Phase B caps.
- `SIZING_MIN_ORDER_NOTIONAL_USD`: `2 -> 1.5`

## Decision Rules After 24h

1. Keep change if:
- Net PnL improves, and
- Reject rate does not materially worsen, and
- Kill-switch does not trigger more frequently.

2. Revert change if:
- PnL flat/down with higher variance, or
- Reject spikes or kill-switch frequency increases.

## Implemented Tracking

1. `runs/telemetry/shadow_decisions.jsonl` now records one row per intent with:
- `ts`, `correlation_id`, `market_id`, `window_id`, `target_notional_usd`, `blocked_reason`, `executed`.

2. `scripts/shadow-hourly-rollup.py` now produces hourly tables with:
- block reason counts,
- execution ratio,
- pnl delta by hour.

This gives enough observability to identify whether the source edge is mostly timing, throughput, or micro-size selection.
