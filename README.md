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
