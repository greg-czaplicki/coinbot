# coinbot

Polymarket copy-trading bot focused on low-latency intent-level replication.

## Quick Commands
- Boot dry-run: `PYTHONPATH=src python3 -m coinbot.main`
- Run recovery/integration tests: `PYTHONPATH=src python3 -m unittest tests.test_recovery tests.test_integration_flows`
- Benchmark endpoint latency on VPS: `./scripts/benchmark-latency.sh 30 docs/LATENCY_BASELINE.md`
- Run a timed paper session: `./scripts/live-paper.sh 60`
- Generate daily rollup: `python3 scripts/daily-rollup.py --date 2026-02-14 --out runs/reports/2026-02-14.md`

## Telemetry Files
- CSV snapshots: `runs/telemetry/snapshots.csv`
- JSONL snapshots: `runs/telemetry/snapshots.jsonl`
- Includes PnL fields: `realized_pnl_usd`, `realized_settled_pnl_usd`, `unrealized_pnl_usd`, `fees_usd`, `net_pnl_usd`

## Live Safety Profile
- `EXECUTION_SAFETY_PROFILE=standard`: no automatic cap tightening.
- `EXECUTION_SAFETY_PROFILE=conservative` (live mode only): clamps caps and slippage for safer initial rollout.

## Live Execution Note
- Live order submission uses `py-clob-client` for signed CLOB orders.
- After pulling updates, run `pip install -e .` to ensure dependencies are present.

## Optional Websocket Modes
- `COPY_SOURCE_WS_ENABLED=true` enables websocket ingestion.
- `COPY_SOURCE_WS_MODE=market` uses the existing CLOB market stream.
- `COPY_SOURCE_WS_MODE=activity` uses the simpler activity-trades websocket stream (`COPY_SOURCE_ACTIVITY_WS_URL`), matching the terminal-style watcher pattern.

## Optional Auto Redeem
- `REDEEM_ENABLED=true` starts a periodic on-chain redeem worker.
- Worker polls Data API wallet positions and redeems resolved conditions every `REDEEM_INTERVAL_SECONDS`.
- Redeem transactions only run when signer key matches `REDEEM_WALLET_ADDRESS` (or `POLYMARKET_FUNDER` fallback).
- If your trading wallet is a proxy/safe address different from your signer EOA, this worker will intentionally skip to avoid failing transactions.
- Safe/proxy mode is supported for single-owner threshold-1 Safes when signer is an owner; higher thresholds are intentionally rejected.
